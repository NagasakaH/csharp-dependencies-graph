#!/usr/bin/env node
// Terraform (.tf) から AWS リソースノードと参照エッジを作る（静的解析・provenance=terraform）。
import { readFileSync, writeFileSync, readdirSync, statSync, mkdirSync } from 'node:fs';
import { join, relative, dirname, basename, resolve } from 'node:path';

const EXCLUDES = new Set(['.git', '.terraform', 'node_modules', 'bin', 'obj', 'dist', 'build']);
const CATEGORY = [
  [/^aws_lambda_(function|permission|version)$/, 'lambda'],
  [/^aws_sfn_state_machine$/, 'stepfunctions'],
  [/^aws_api_gateway_/, 'apigateway'],
  [/^aws_apigatewayv2_/, 'apigateway'],
  [/^aws_dynamodb_table$/, 'dynamodb'],
  [/^(aws_db_instance|aws_rds_cluster|aws_db_subnet_group|aws_db_parameter_group)$/, 'rds'],
  [/^aws_s3_bucket$/, 's3'],
  [/^aws_sqs_/, 'sqs'],
  [/^aws_sns_/, 'sns'],
  [/^aws_secretsmanager_/, 'secretsmanager'],
  [/^aws_iam_/, 'iam'],
  [/^aws_cloudwatch_log_group$/, 'cloudwatch'],
  [/^aws_cloudwatch_event/, 'eventbridge'],
  [/^aws_ecs_|^aws_ecr_/, 'ecs'],
];

function parseArgs(argv) {
  const opts = { root: process.cwd(), out: 'graph.terraform.json', files: [] };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--root': opts.root = resolve(argv[++i]); break;
      case '--out': opts.out = argv[++i]; break;
      case '--file': opts.files.push(resolve(argv[++i])); break;
      case '--help': console.log('使い方: scan-terraform.mjs --root <repo> --out <graph.terraform.json> [--file main.tf]'); process.exit(0);
    }
  }
  return opts;
}

function categoryOf(type) {
  for (const [pattern, category] of CATEGORY) if (pattern.test(type)) return category;
  return type.replace(/^aws_/, '').split('_')[0] || 'resource';
}

// `resource "aws_lambda_function" "api" { ... }` を括弧対応で切り出す
function parseBlocks(text) {
  const blocks = [];
  const re = /(resource|data|module|variable|output)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{/g;
  let match;
  while ((match = re.exec(text))) {
    let i = re.lastIndex - 1, depth = 0, start = i;
    for (; i < text.length; i++) {
      const ch = text[i];
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) break; }
    }
    blocks.push({ kind: match[1], type: match[2], name: match[3] || match[2], body: text.slice(start + 1, i), start: match.index });
    re.lastIndex = i;
  }
  return blocks;
}

// 右辺を**構文の形**で判別するための生値（引用符を含めたまま）を、パス組み立てに使うキーだけ保持する。
// `attributes()` は表示用に引用符を落とした値を持つので、「引用されたリテラル」と「点を含む参照」を
// 区別できない（実測で `path_part = "local.segment"` の endpoint が消え、
// `path_part = aws_ssm_parameter.p.value` が通った）
// `api_id`（HTTP API の所属）と `target`（route の委譲先）も「決まらないときに残す」対象
// `rest_api_id` も raw で持つ（v1 REST API の `method` ↔ `integration` 対応は
// `rest_api_id` / `resource_id` / `http_method` の 3 点セットで決める。`attributes()` の
// 表示用値だと `var.x` と単一参照を区別できず、決まらない値から縁を張ってしまう）
const RAW_KEYS = ['path_part', 'parent_id', 'resource_id', 'rest_api_id', 'http_method',
  'route_key', 'api_id', 'target'];
function rawAttributes(body) {
  const raws = {};
  for (const raw of body.split('\n')) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith('//')) continue;
    const m = line.match(/^([a-z_][\w-]*)\s*=\s*(.+?)(?:\s*#.*)?$/);
    if (!m || !RAW_KEYS.includes(m[1]) || raws[m[1]] !== undefined) continue;
    raws[m[1]] = m[2].trim().replace(/,$/, '');
  }
  return raws;
}

function attributes(body) {
  const attrs = {};
  const lines = body.split('\n');
  let depth = 0;
  for (const raw of lines) {
    const line = raw.trim();
    if (!line || line.startsWith('#') || line.startsWith('//')) continue;
    depth += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    if (depth < 0) depth = 0;
    if (depth > 1) continue;
    const m = line.match(/^([a-z_][\w-]*)\s*=\s*(.+?)(?:\s*#.*)?$/);
    if (!m) continue;
    const key = m[1];
    let value = m[2].trim().replace(/,$/, '');
    // HCL の文字列リテラルは引用符ごと取れる。表示と照合のしやすさからouterの引用符を落とす
    if (value.length > 1 && ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'")))) {
      value = value.slice(1, -1);
    }
    if (attrs[key] === undefined) attrs[key] = value.length > 200 ? value.slice(0, 197) + '…' : value;
  }
  return attrs;
}

function references(body, selfType, selfName) {
  const refs = new Set();
  const re = /\b(resource\.)?([a-z_][a-z0-9_]*)\.([a-zA-Z0-9_-]+)\b/g;
  let match;
  while ((match = re.exec(body))) {
    const type = match[2], name = match[3];
    if (type === selfType && name === selfName) continue;
    // local / var はリソースではなく設定値なので、ノード化しない（ルート表示がノイズで埋まる）
    if (!type.startsWith('aws_') && !['module', 'data'].includes(type)) continue;
    refs.add(`${type}.${name}`);
  }
  return [...refs];
}

const opts = parseArgs(process.argv);
let tfFiles = opts.files;
if (!tfFiles.length) {
  const walk = (dir) => {
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const abs = join(dir, e.name);
      if (e.isDirectory()) { if (!EXCLUDES.has(e.name) && !e.name.startsWith('.')) walk(abs); }
      else if (/\.(tf|tfvars)$/i.test(e.name)) tfFiles.push(abs);
    }
  };
  walk(opts.root);
}

const nodes = [], edges = [], resources = new Map();
const nodeRaws = new Map();   // ノード -> パス組み立てに使う右辺の生値（引用符込み）
// `target` が読めた route（ノード -> { addr, file }）。宣言順に依存せず張るために覚えておく
const routeTarget = new Map();
// `target` の形は読めたが参照先の resource が無い、または同名アドレス衝突で選べないノード。
// 推測で縁を張らず、`metadata.unresolved` に `target` を残す
const missingRouteTarget = new Set();
// `target` が書かれているのに既知の形で読めなかった route。縁を張らず `metadata.unresolved` に出す
const unparsableRouteTarget = new Set();
// `target = "integrations/\${aws_apigatewayv2_integration.<name>.id}"` **そのもの**だけを通す。
// 部分一致ではなく値全体を見るので、混合補間・三項式・関数呼び出しは通さない
function routeTargetIntegration(raw) {
  const v = String(raw === undefined || raw === null ? '' : raw).trim();
  const quoted = /^"([\s\S]*)"$/.exec(v);
  const inner = quoted ? quoted[1].trim() : v;
  const m = /^integrations\/\$\{\s*(?:resource\.)?aws_apigatewayv2_integration\.([a-zA-Z0-9_-]+)\.id\s*\}$/.exec(inner);
  return m ? `aws_apigatewayv2_integration.${m[1]}` : null;
}
for (const file of tfFiles) {
  const rel = relative(opts.root, file).split(/[\\/]/).join('/');
  const text = readFileSync(file, 'utf8');
  const dir = rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '';
  const parent = `folder:${dir || '.'}`;
  nodes.push({ id: `file:${rel}`, kind: 'file', name: basename(rel), parent, path: rel, metadata: { language: 'terraform' } });
  for (const block of parseBlocks(text)) {
    if (block.kind === 'variable' || block.kind === 'output') continue;
    const address = block.kind === 'resource' ? `${block.type}.${block.name}` : `${block.kind === 'module' ? 'module' : 'data'}.${block.name}`;
    const id = `tf:${address}`;
    const attrs = attributes(block.body);
    const rawsForPath = rawAttributes(block.body);
    const meta = { resourceType: block.type, terraformAddress: address, file: rel, provider: block.kind === 'resource' ? 'terraform' : block.kind };
    for (const key of ['function_name', 'name', 'handler', 'runtime', 'memory_size', 'timeout', 'filename', 's3_key', 'role', 'state_machine_type', 'execution_role_arn', 'rest_api_id', 'resource_id', 'http_method', 'integration_uri', 'uri', 'table_name', 'bucket', 'engine', 'topic_arn', 'queue_url', 'path_part', 'parent_id', 'stage_name', 'route_key', 'api_id', 'target']) {
      if (attrs[key] !== undefined) meta[key] = attrs[key];
    }
    const node = block.kind === 'resource'
      ? { id, kind: 'resource', name: block.name, parent, path: rel, metadata: { ...meta, category: categoryOf(block.type) } }
      : { id, kind: 'resource', name: block.name, parent, path: rel, metadata: { ...meta, dataSource: true, category: categoryOf(block.type) } };
    nodes.push(node);
    nodeRaws.set(node, rawsForPath);
    if (block.kind === 'resource') resources.set(address, { id, type: block.type, file: rel });
    for (const ref of references(block.body, block.type, block.name)) {
      const target = resources.get(ref) || null;
      const targetId = target ? target.id : `tf:${ref}`;
      const kind = /api_gateway|apigatewayv2/.test(block.type) && categoryOf(ref.split('.')[0]) === 'lambda'
        ? 'triggers'
        : categoryOf(block.type) === 'stepfunctions' && categoryOf(ref.split('.')[0]) === 'lambda'
          ? 'invokes'
          : 'references';
      edges.push({
        id: `${kind}:${id}->${targetId}`, source: id, target: targetId, kind, provenance: 'terraform',
        detail: `${rel} 内の参照`, count: 1, _file: rel,   // _file: 同名アドレスの解決にだけ使う（出力前に落とす）
      });
      if (!target) edges[edges.length - 1].metadata = { unresolvedTarget: true };
    }
    // `aws_apigatewayv2_route` の `target` は `integrations/\${aws_apigatewayv2_integration.x.id}` と
    // いう**形が決まっている**書き方をする。`references` だけを張ると、伝播の資格は
    // 「参照されている側 → 参照している側」にしか通らない設計（`report.mjs` の `refersInto`）で、
    // `route` から `integration` へ進む一歩が 定義上の関連 に落ちる。その結果 `--api` で v2 の
    // route を起点にしたときに `integration → triggers → Lambda → handler → C#` が本命へ届かない
    // （双人レビュー第 25 ラウンドで agy が実測で特定、codex も再現）。**この既知の形に限定して**
    // 動きの縁 `invokes`（route が integration に委ねる）として張る。他の書き方は推測しない
    if (block.type === 'aws_apigatewayv2_route') {
      // ここで縁を張らない。`integration` がこの route より**後ろ**に宣言されていると
      // `resources` に入っていなくて、宣言順で結果が変わってしまう。宣言順に依存しないよう、
      // ここでは読み取れた所属先を覚えておくだけにする（縁は後のまとめて張りで張る）
      const rawTarget = (rawsForPath || {}).target;
      const integ = routeTargetIntegration(rawTarget);
      if (integ) routeTarget.set(node, { addr: integ, file: rel });
      // `target` に値が書かれているのに既知の形で読めない（末尾に文字が足された混合補間など）は
      // 推測しない。未解決として出す
      else if (rawTarget !== undefined) unparsableRouteTarget.add(node);
    }
  }
}

// ---- 同じ Terraform アドレスが複数ある場合（module 内の同名リソース）----
// module の展開はしない（`source = "./modules/one"` の中を別ディレクトリとして走査するだけ）なので、
// `modules/one` と `modules/two` に同じ `aws_api_gateway_resource.path` を置くと id が衝突して
// 片方の endpoint が黙って消える（実測: `GET /two` のみが残り `GET /one` が失せた）。
// 衝突したら id に宣言ファイルを含めて両方残す（どちらがどちらかを実データで区別できるようにする）
const byIdCount = new Map();
for (const n of nodes) if (n.kind === 'resource') byIdCount.set(n.id, (byIdCount.get(n.id) || 0) + 1);
const conflicts = [...byIdCount.entries()].filter(([, c]) => c > 1).map(([id]) => id);
const conflictSet = new Set(conflicts);
if (conflicts.length) {
  const rename = new Map();   // `${oldId}\u0000${file}` -> 新しい id
  for (const n of nodes) {
    if (n.kind !== 'resource' || !conflictSet.has(n.id)) continue;
    const nid = `tf:${n.metadata.file}#${n.metadata.terraformAddress}`;
    rename.set(`${n.id}\u0000${n.metadata.file}`, nid);
    n.id = nid;
    n.metadata.addressConflict = true;
  }
  for (const e of edges) {
    const file = e._file;
    if (conflictSet.has(e.source) && rename.has(`${e.source}\u0000${file}`)) e.source = rename.get(`${e.source}\u0000${file}`);
    if (conflictSet.has(e.target) && rename.has(`${e.target}\u0000${file}`)) e.target = rename.get(`${e.target}\u0000${file}`);
    e.id = `${e.kind}:${e.source}->${e.target}`;
    if (conflictSet.has(e.target) || conflictSet.has(e.source)) e.metadata = { ...e.metadata, ambiguousAddress: true };
  }
  for (const e of edges) delete e._file;
  console.log(`[terraform] 同名アドレス ${conflicts.length} 件をファイル付きの id に分けた（module 展開はしない）: ${conflicts.join(', ')}`);
} else {
  for (const e of edges) delete e._file;
}

// ---- API Gateway の HTTP パスを組み立てる ----
// `path_part` はリソース単体の値で、実際の HTTP パスは `parent_id` を辿って作る。
// `parent_id` が `aws_api_gateway_rest_api.<x>.root_resource_id` を指すなら直下、
// 別の `aws_api_gateway_resource` を指すなら親のパスへ連結する。
// レポートが「`POST /orders`」のように HTTP のメソッドとパスで起点を引くための値で、
// 決まらないのに推測して `endpoint` を張ることはしない
// HCL の右辺を構文の形で返す。**部分一致で参照を拾うのをやめ**、値全体が
// 「リテラル」「単一の参照」「単一の参照だけの補間」のどれであるかを見る。
// 三項式・関数呼び出し・文字列と補間の混合は `unknown`（= 未解決）になり、
// `var.use_root ? aws_api_gateway_rest_api.api.root_resource_id : ...` から
// root 直下だと断定しなくなる（実測で `GET /orders` が実在しないまま生まれていた）
function valueForm(raw) {
  const v = String(raw === undefined || raw === null ? '' : raw).trim();
  if (!v) return { kind: 'empty' };
  const quoted = /^"([\s\S]*)"$/.exec(v) || /^'([\s\S]*)'$/.exec(v);
  if (quoted) {
    const inner = quoted[1];
    if (inner.includes('${') || inner.includes('%{')) {
      // `%{ if ... }` / `%{ for ... }` のテンプレート指令は「リテラルだった部分」が条件で
      // 消える。値が一つに決まらないのでリテラル扱いしない（実測: `%{ if true }dyn%{ endif }`
      // から `/dyn` という実在しないパスを作っていた）
      const one = /^\$\{\s*([^{}]+?)\s*\}$/.exec(inner.trim());
      return one ? { kind: 'ref', expr: one[1] } : { kind: 'unknown' };   // 混合補間・指令は未解決
    }
    return { kind: 'literal', text: inner };                              // 引用されたリテラル
  }
  if (/^\$[a-zA-Z_][\w-]*$/.test(v)) return { kind: 'literal', text: v };  // `$default` などのbareな語
  if (/^[a-zA-Z_][a-zA-Z0-9_-]*$/.test(v)) return { kind: 'literal', text: v };  // 点の無い裸の語
  if (/^(?:resource\.)?[a-z_][a-z0-9_]*\.[a-zA-Z0-9_-]+(?:\[[^\]]*\])?(?:\.[a-zA-Z0-9_-]+)*$/.test(v)) {
    return { kind: 'ref', expr: v };                                      // 単一の参照式
  }
  return { kind: 'unknown' };   // 関数呼び出し、三項式、演算、リスト、`count.index` 混在など
}
// `aws_api_gateway_rest_api.<name>.root_resource_id` **そのもの**かどうか（部分一致ではない）
function rootResourceRef(form) {
  if (!form || form.kind !== 'ref') return null;
  const m = /^(?:resource\.)?aws_api_gateway_rest_api\.([a-zA-Z0-9_-]+)\.root_resource_id$/.exec(form.expr);
  return m ? m[1] : null;
}
// `<type>.<name>` または `<type>.<name>.<attr>` だけを通す。`var.x` / `module.x.y` /
// `each.value` / `aws_ssm_parameter.p.value`（値が分からない属性参照）は形が似ていても弾く
function refOf(form, type, attrs) {
  if (!form || form.kind !== 'ref') return null;
  const m = /^(?:resource\.)?([a-z_][a-z0-9_]*)\.([a-zA-Z0-9_-]+)(?:\[[^\]]*\])?(?:\.([a-zA-Z0-9_-]+))?$/.exec(form.expr);
  if (!m || m[1] !== type) return null;
  if (m[3] && attrs && !attrs.includes(m[3])) return null;
  return { name: m[2], attr: m[3] || null };
}
// リテラルとして確定している値。`null` は「決まらない」なので、そこから endpoint を張らない
function literalText(form) {
  return form && form.kind === 'literal' ? form.text : null;
}
const HTTP_VERB = /^[A-Z*]+$/;
// 同じアドレスを module 間で使い得るので、アドレスからは**候補の配列**で引く
const byAddress = new Map();
for (const n of nodes) {
  const a = n.metadata && n.metadata.terraformAddress;
  if (!a) continue;
  if (!byAddress.has(a)) byAddress.set(a, []);
  byAddress.get(a).push(n);
}
// `同一ファイル > 候補が 1 件だけ > どちらかを選べない` の順で決める。選べないときに
// 一方へ勝手に決めるのは「もう一方の定義を無視した」パスになるのでやめる
function sameFileNode(address, file) {
  const cands = byAddress.get(address) || [];
  if (!cands.length) return null;
  const same = cands.filter((n) => n.metadata.file === file);
  if (same.length === 1) return same[0];
  return cands.length === 1 ? cands[0] : null;
}
// リソースの生値（address -> {path_part: …}）。パスの成否はここで決める
const rawValues = new Map();
for (const n of nodes) if (nodeRaws.has(n)) rawValues.set(n.id, nodeRaws.get(n));
const pathCache = new Map();
function gatewayResourcePath(node, guard = new Set()) {
  if (!node) return null;
  const address = node.metadata.terraformAddress;
  if (pathCache.has(node.id)) return pathCache.get(node.id);
  if (guard.has(node.id)) return null;      // 循環参照で無限再帰しない
  guard.add(node.id);
  const raws = rawValues.get(node.id);
  const meta = node.metadata;
  if (!raws || !meta) return null;
  // `path_part` は**リテラルと決まっている**ときだけパスにする。`each.value` や
  // `aws_ssm_parameter.p.value` から `/${part}` を作ると「そのパスが実在する」表示になる
  const part = literalText(valueForm(raws.path_part));
  if (!part) return null;
  let path = `/${part}`;
  const parentRaw = valueForm(raws.parent_id);
  if (rootResourceRef(parentRaw)) {
    // REST API の直下（`root_resource_id` そのものを指しているときだけ）
  } else {
    const parent = refOf(parentRaw, 'aws_api_gateway_resource', ['id']);
    // 親が解決できない（`var.parent_id`、三項式、`module.x.parent_id`）なら直下扱いにしない
    if (!parent) return null;
    const up = gatewayResourcePath(sameFileNode(`aws_api_gateway_resource.${parent.name}`, meta.file), guard);
    if (!up) return null;
    path = `${up}${path}`;
  }
  pathCache.set(node.id, path);
  return path;
}
// パス組み立てに使う属性のうち、**値が決まらないもの**をノードに書く。決まらない属性から
// 推測した値は作らない設計なので、「どこを見れば復元できるか」をノード側に残す
// `api_id` は HTTP API（v2）の所属、`target` は route の委譲先。決まらないときに
// 「どこを見れば復元できるか」を残す属性として同じ扱いにする
const PATH_ATTRS = ['path', 'path_part', 'parent_id', 'rest_api_id', 'http_method', 'api_id'];
const unresolvableForm = (form) => {
  if (!form) return false;
  if (form.kind === 'unknown') return true;
  if (form.kind !== 'ref') return false;
  return /^(var|local|each|count|module|data)\b/.test(form.expr) || form.expr.includes('(');
};
for (const node of nodes) {
  const raws = rawValues.get(node.id);
  if (!raws || !node.metadata) continue;
  const bad = PATH_ATTRS.filter((a) => raws[a] !== undefined && unresolvableForm(valueForm(raws[a])));
  // `target` は専用の構文で読む（`integrations/\${...}` は混合補間なので `unresolvableForm` が
  // 正しく判定できない。ここで見ない）。**縁を張れた route は未解決に数えない**。
  // ここで並べるのは形が読めないもの。形は読めたが参照先が無いものは、縁を張る場所が
  // 決まる後続（`missingRouteTarget`）で `target` を足す
  if (unparsableRouteTarget.has(node) && !bad.includes('target')) bad.push('target');
  if (bad.length) node.metadata.unresolved = bad;
}

for (const node of nodes) {
  const meta = node.metadata;
  if (!meta) continue;
  if (meta.resourceType === 'aws_api_gateway_resource') {
    const path = gatewayResourcePath(node);
    if (path) meta.apiPath = path;
  } else if (meta.resourceType === 'aws_api_gateway_method') {
    const raws = rawValues.get(node.id) || {};
    // `resource_id` が **単一の `aws_api_gateway_resource.<name>.id`** のときだけパスを結ぶ。
    // 三項式や `var.x` から resource を推測しない
    const res = refOf(valueForm(raws.resource_id), 'aws_api_gateway_resource', ['id']);
    const path = res
      ? gatewayResourcePath(sameFileNode(`aws_api_gateway_resource.${res.name}`, meta.file))
      : null;
    // HTTP method もリテラルと決まっているときだけ endpoint にする。`http_method = var.verb` から
    // `VAR.VERB /base` のような表示を作らない
    const verb = literalText(valueForm(raws.http_method));
    if (path && verb && HTTP_VERB.test(verb.toUpperCase())) {
      meta.apiPath = path;
      meta.endpoint = `${verb.toUpperCase()} ${path}`;
    } else if (path) {
      meta.apiPath = path;      // パスは決まるが method が未確定。endpoint は張らない
    }
  } else if (meta.resourceType === 'aws_apigatewayv2_route') {
    // HTTP API の `route_key` は `POST /orders/{id}` の形でメソッドとパスを両方含む
    const key = literalText(valueForm((rawValues.get(node.id) || {}).route_key));
    if (key) {
      const parts = key.split(/\s+/).filter(Boolean);
      const verb = parts.length > 1 ? parts[0].toUpperCase() : '*';
      const raw = parts.length > 1 ? parts[1] : parts[0];
      if (raw === '$default') {
        // catch-all のリテラル。実在する HTTP パスではないので `endpoint` / `apiPath` を張らず、
        // 既定ルートだと分かる旗だけ持たせる（`--api` の候補にも起点一覧にも出さない）
        meta.defaultRoute = true;
      } else if (raw.startsWith('$')) {
        // `$connect` / `$disconnect` など（WebSocket の eventId だけの route）。これも HTTP の
        // メソッドとパスではないので `endpoint` を捏造しない。今回のゴールは HTTP API が対象なので、
        // 「HTTP のパスとして存在しない」と分かる旗だけを立てる
        meta.nonHttpRouteKey = raw;
      } else if (HTTP_VERB.test(verb)) {
        meta.apiPath = raw.startsWith('/') ? raw : `/${raw}`;
        meta.endpoint = `${verb} ${meta.apiPath}`;
      }
    }
  }
}

// ---- `aws_apigatewayv2_route` の `target` を動きの縁として張る ----
// 同名アドレスの衝突解決（上の貼り替え）と宣言順の両方に影響しない場所で行う。
// 解決できないとき（参照先が無い、同名で選べない）は縁を張らず `metadata.unresolved` に出す
for (const [node, t] of routeTarget) {
  const found = sameFileNode(t.addr, t.file);
  // `referencedOnly`（参照されただけで宣言されていないノード）を宣言済みと取り違えると、
  // 実在しない integration へ動きの縁を張ってしまう
  if (!found || found.metadata.referencedOnly === true) { missingRouteTarget.add(node); continue; }
  edges.push({
    id: `invokes:${node.id}->${found.id}`, source: node.id, target: found.id, kind: 'invokes',
    provenance: 'terraform', detail: '`aws_apigatewayv2_route` の `target` が integration に委譲する先',
    count: 1,
  });
}
// ---- v1 REST API の `method` → `integration` を動きの縁として張る ----
// `aws_api_gateway_integration` は `rest_api_id` / `resource_id` / `http_method` の 3 点セットで
// method を指す（API Gateway ではこの 3 つが integration の所在そのもの）。3 つとも**値が
// 決まって**いて、同じファイルに同じ 3 点セットの `aws_api_gateway_method` が **1 件だけ**ある
// ときだけ `invokes`（method が integration に委ねる）を張る。0 件でも 2 件以上でも張らない。
// 「同じ resource の下に method が 1 件しかない」での橋渡しはしない（第 29 ラウンドの裁定:
// 候補が 1 件なのは対応が確定した証拠にならない。兄弟 method が 1 本増えただけで結果が変わる）。
// HTTP API（v2）の `target` と同じ縁に揃えるので、v1 でも v2 でも `--api` 起点の連鎖が
// `integration → triggers → Lambda → handler → C#` まで届く。逆に 3 点セットが無い（たとえば
// `http_method` を書かない）integration は定義上の関連のままで、レポート側が
// 「対応未確定」として出す
const methodTriple = (raws, file) => {
  const api = refOf(valueForm(raws.rest_api_id), 'aws_api_gateway_rest_api', ['id']);
  const res = refOf(valueForm(raws.resource_id), 'aws_api_gateway_resource', ['id']);
  const verb = literalText(valueForm(raws.http_method));
  if (!api || !res || !verb) return null;
  const up = verb.toUpperCase();
  if (up === '*' || !HTTP_VERB.test(up)) return null;
  // 参照先の rest API / resource を**実体のノード**として解決する（パス組み立ての `gatewayResourcePath`
  // と同じ `sameFileNode`）。名前だけで決めると、別ディレクトリの独立 API が同じローカル名
  // （`rest_api.a` / `resource.r` / `POST`）を使っただけで「三点組の重複宣言」になり、
  // 正常な対応まで落ちた（双人レビュー第 30 ラウンド A、両名実測: `POST /one` の invokes が消えた）。
  // `sameFileNode` は「同じファイルに 1 件 > 候補が全体で 1 件 > 選べない」の順で決めるので、
  //  ・`api.tf` に rest API / resource、`orders.tf` に method / integration の分割 → 解決する
  //  （従来は「同じファイルに宣言が無い」で縁を張っていなかった。第 30 ラウンド agy 指摘 1）
  //  ・module をまたいだ同名アドレス（候補 2 件で同じファイルにも無い）→ 解決しない
  // キーは解決後のノード id。実体が違えば別扱いになり、本当に同じ実体へ同じ三点組が 2 本
  // 届いたときだけ重複になる
  const apiNode = sameFileNode(`aws_api_gateway_rest_api.${api.name}`, file);
  const resNode = sameFileNode(`aws_api_gateway_resource.${res.name}`, file);
  if (!apiNode || !resNode) return null;
  return `${apiNode.id}\u0000${resNode.id}\u0000${up}`;
};
const v1Methods = new Map();     // 3 点セット -> method ノード（同じ値の method が複数なら縁を張らない）
for (const node of nodes) {
  const meta = node.metadata;
  if (!meta || meta.resourceType !== 'aws_api_gateway_method' || meta.referencedOnly === true) continue;
  const key = methodTriple(rawValues.get(node.id) || {}, meta.file);
  if (!key) continue;
  const list = v1Methods.get(key);
  if (list) list.push(node); else v1Methods.set(key, [node]);
}
for (const node of nodes) {
  const meta = node.metadata;
  if (!meta || meta.resourceType !== 'aws_api_gateway_integration' || meta.referencedOnly === true) continue;
  const key = methodTriple(rawValues.get(node.id) || {}, meta.file);
  if (!key) continue;
  const list = v1Methods.get(key) || [];
  if (list.length !== 1) continue;      // 宣言が重複している（= どれが実装か決まらない）ので張らない
  const method = list[0];
  edges.push({
    id: `invokes:${method.id}->${node.id}`, source: method.id, target: node.id, kind: 'invokes',
    provenance: 'terraform',
    detail: '`aws_api_gateway_integration` の `rest_api_id` / `resource_id` / `http_method` が指す method',
    count: 1,
  });
}

// 参照先が無かったことはここでのみ分かる（上の未解決チェックより後でしか決まらない）
for (const node of missingRouteTarget) {
  if (!node.metadata) continue;
  const bad = node.metadata.unresolved || [];
  if (!bad.includes('target')) node.metadata.unresolved = [...bad, 'target'];
}

// data source 参照のみで存在したノードを resource として補完
const known = new Set(nodes.map((n) => n.id));
for (const edge of edges) {
  if (!known.has(edge.target)) {
    const address = edge.target.slice(3);
    const type = address.split('.')[0];
    nodes.push({ id: edge.target, kind: 'resource', name: address.split('.').slice(1).join('.'), parent: 'folder:.', metadata: { resourceType: type, category: categoryOf(type), referencedOnly: true } });
    known.add(edge.target);
  }
}

const fragment = {
  schemaVersion: 1, producer: 'terraform-scanner', generatedAt: new Date().toISOString(), root: opts.root, nodes, edges,
  stats: { tfFiles: tfFiles.length, tfResources: nodes.filter((n) => n.kind === 'resource').length, tfEdges: edges.length },
};
mkdirSync(dirname(resolve(opts.out)) || '.', { recursive: true });
writeFileSync(opts.out, JSON.stringify(fragment));
console.log(`[terraform] ファイル ${tfFiles.length} / リソース ${fragment.stats.tfResources} / エッジ ${edges.length} → ${opts.out}`);
