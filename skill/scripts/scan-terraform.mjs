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
const RAW_KEYS = ['path_part', 'parent_id', 'resource_id', 'http_method', 'route_key'];
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
    for (const key of ['function_name', 'name', 'handler', 'runtime', 'memory_size', 'timeout', 'filename', 's3_key', 'role', 'state_machine_type', 'execution_role_arn', 'rest_api_id', 'resource_id', 'http_method', 'integration_uri', 'uri', 'table_name', 'bucket', 'engine', 'topic_arn', 'queue_url', 'path_part', 'parent_id', 'stage_name', 'route_key']) {
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
    if (inner.includes('${')) {
      const one = /^\$\{\s*([^{}]+?)\s*\}$/.exec(inner.trim());
      return one ? { kind: 'ref', expr: one[1] } : { kind: 'unknown' };   // 混合補間は未解決
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
      } else if (HTTP_VERB.test(verb)) {
        meta.apiPath = raw.startsWith('/') ? raw : `/${raw}`;
        meta.endpoint = `${verb} ${meta.apiPath}`;
      }
    }
  }
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
