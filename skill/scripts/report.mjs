#!/usr/bin/env node
// 差分（変更ファイル一覧）→ 影響範囲レポート。
//
// 方針:
//  - 階層（parent / contains）は**起点の展開にだけ**使い、影響の walk には使わない。
//    変更ファイルからは、その中に含まれるメンバー（C# のメソッド）と、そのファイルが宣言している
//    Terraform リソースを自動で起点にする。変更ファイルがグラフに無いときは**起点にせず**一覧に出すだけ
//    （親フォルダを起点にすると配下を巻き込んで誤検出が膨らむ実測があるため）。
//  - 影響は双方向で出し分ける。「影響を受ける入口」（呼び出し元・エンドポイント）と
//    「影響する外部リソース」（変更が触れる先）では意味が違うので、行に方向を持たせる。
//  - Terraform の `references`（そのブロックを文中に書いたというだけの縁）は変更で値が動かないので、
//    依存と同じ欄に並べず**定義上の関連**として分ける。
//  - 各行に根拠エッジ（kind と provenance）を添える。注釈（llm / human）由来の行は
//    「静的解析では決まらない対応付け」として明示する（事実のように読ませないため）。
//
// 使い方: node skill/scripts/report.mjs --graph out/demo/graph.json --changed changed.txt
'use strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';

const opts = {
  graph: null, changed: null, from: [], api: [], hops: 8, provenance: null,
  dropKind: ['contains'], json: null, md: null, expect: null, noExpand: false, limit: 200,
  wiringHops: 3, includeData: false, folderStart: false,
};
const USAGE = `使い方: report.mjs --graph <graph.json> [--changed <変更ファイル一覧>] [--from <ノード id や名前>]
                [--api "POST /orders"] [--hops N] [--provenance static,terraform,llm,human]
                [--json <out>] [--md <out>] [--expect <期待一覧.json>] [--no-expand] [--folder-start]
                [--wiring-hops N] [--include-data] [--limit N]

  --changed   1 行 1 パスの一覧ファイル。`-` で標準入力（git diff --name-only をそのまま渡せる）。
              パスは graph.json の node.path と同じ表記（リポジトリ根からの相対）。
  --api       API Gateway のメソッドとパスで起点を引く（"POST /orders"）。パスの末尾の / はどちらでもよい。
  --expect    期待する着地の一覧（{"expect": [...], "direction": "in"|"out"|"both", "note": "..."}）。
              渡すと再現率・適合率を出して JSON にも書く。
  変更ファイルがグラフに見当たらないときは、既定では起点にしません（--folder-start で初めて親フォルダ起点）。`;

for (let i = 2; i < process.argv.length; i++) {
  const a = process.argv[i];
  const next = () => {
    const v = process.argv[++i];
    if (v === undefined) { console.error(`[report] ${a} に続く値がありません`); process.exit(2); }
    return v;
  };
  if (a === '--graph') opts.graph = next();
  else if (a === '--changed') opts.changed = next();
  else if (a === '--from') opts.from.push(next());
  else if (a === '--api') opts.api.push(next());
  else if (a === '--hops') opts.hops = Number(next());
  else if (a === '--provenance') opts.provenance = next().split(',');
  else if (a === '--drop-kind') opts.dropKind = next().split(',');
  else if (a === '--json') opts.json = next();
  else if (a === '--md') opts.md = next();
  else if (a === '--expect') opts.expect = next();
  else if (a === '--wiring-hops') opts.wiringHops = Number(next());
  else if (a === '--limit') opts.limit = Number(next());
  else if (a === '--no-expand') opts.noExpand = true;
  else if (a === '--folder-start') opts.folderStart = true;
  else if (a === '--include-data') opts.includeData = true;
  else if (a === '--help') { console.log(USAGE); process.exit(0); }
  else { console.error(`[report] 未対応の引数: ${a}\n${USAGE}`); process.exit(2); }
}
if (!opts.graph) { console.error(USAGE); process.exit(2); }
for (const [name, v] of [['--hops', opts.hops], ['--wiring-hops', opts.wiringHops], ['--limit', opts.limit]]) {
  if (!Number.isInteger(v) || v < 0) { console.error(`[report] ${name} は 0 以上の整数: ${v}`); process.exit(2); }
}

const graph = JSON.parse(readFileSync(resolve(opts.graph), 'utf8'));
const byId = new Map(graph.nodes.map((n) => [n.id, n]));
const kidsOf = new Map();
for (const n of graph.nodes) {
  if (!n.parent) continue;
  if (!kidsOf.has(n.parent)) kidsOf.set(n.parent, []);
  kidsOf.get(n.parent).push(n.id);
}
// 依存縁（静的 / Terraform）は向きを持つ。**対応付け（注釈）は双方向**で扱う。
// 「この列があのプロパティに対応する」「この csproj をこの Lambda がデプロイする」を
// 片側だけで見る意味がないため。行に対応印を付けて区別できるようにする
const CORRESPONDENCE = new Set(['llm', 'human']);
const out = new Map(); const inn = new Map();
for (const e of graph.edges) {
  if (opts.dropKind.includes(e.kind)) continue;
  if (opts.provenance && !opts.provenance.includes(e.provenance)) continue;
  const corr = CORRESPONDENCE.has(e.provenance);
  const push = (map, from, to) => {
    if (!map.has(from)) map.set(from, []);
    map.get(from).push({ e, to, corr });
  };
  // `source → target` を **順に辿れば out、逆から辿れば in** の 1 本ずつだけ入れる。
  // 注釈（対応付け）だからといって双方向に重複登録すると、同じ着地に in と out の両方が付き、
  // BFS の先着で `writes` の先が「影響を受ける入口」になる（実測でテーブルが逆ラベルになった）。
  // 双方向に「届く」のはこの 1 本ずつで達成できる（テーブルからは逆方向 = in で書く側へ届く）
  push(out, e.source, e.target);
  push(inn, e.target, e.source);
}

const label = (id) => {
  const n = byId.get(id);
  if (!n) return id;
  const m = n.metadata || {};
  if (n.kind === 'resource') return `${m.endpoint || `${m.resourceType || 'resource'}:${n.name}`}`;
  return n.name || basename(n.path || id);
};
const category = (id) => (byId.get(id)?.metadata || {}).category || byId.get(id)?.kind || '';
// API の表示名。scan-terraform.mjs が `path_part` / `parent_id` から組み立てた `endpoint` を使い、
// 無い method は `http_method` と `apiPath` から作る。どちらも無ければ出さない（推測しない）
function endpointOf(node) {
  const m = (node && node.metadata) || {};
  if (m.endpoint) return m.endpoint;
  if (m.http_method && m.apiPath) return `${String(m.http_method).toUpperCase()} ${m.apiPath}`;
  return null;
}
const endpointNodes = graph.nodes.filter((n) => endpointOf(n));
// 「起点と同じ API を定義している」を **`rest_api_id` の参照先** で決める。
// `category === 'apigateway'` だけの条件だと、同じ Lambda を共有する**別 API** の
// rest_api / resource / deployment まで「起点と同じ API」に分類してしまう（実測で取り違え）。
// 群が決まらないもの（`aws_apigatewayv2_*` は `api_id` を採っていない）は推測せず、定義上の関連に残す
const refAddressOf = (value, type) => {
  const m = new RegExp(`\\b(?:resource\\.)?${type}\\.([a-zA-Z0-9_-]+)\\b`).exec(String(value === undefined || value === null ? '' : value));
  return m ? `${type}.${m[1]}` : null;
};
const apiGroupCache = new Map();
function apiGroupOf(node) {
  if (!node || apiGroupCache.has(node.id)) return apiGroupCache.get(node.id);
  const m = (node.metadata) || {};
  if (m.category !== 'apigateway') { apiGroupCache.set(node.id, null); return null; }
  if (m.resourceType === 'aws_api_gateway_rest_api') { apiGroupCache.set(node.id, node.id.slice(3)); return node.id.slice(3); }
  const direct = refAddressOf(m.rest_api_id, 'aws_api_gateway_rest_api');
  if (direct) { apiGroupCache.set(node.id, direct); return direct; }
  // resource 経由（`parent_id` を辿る）。循環しても有限回でやめる
  apiGroupCache.set(node.id, null);
  let res = refAddressOf(m.parent_id, 'aws_api_gateway_resource');
  for (let i = 0; res && i < 12; i++) {
    const owner = byId.get(`tf:${res}`);   // 51,000 ノードでも線形探索しない
    if (!owner) break;
    const om = owner.metadata || {};
    const g = refAddressOf(om.rest_api_id, 'aws_api_gateway_rest_api');
    if (g) { apiGroupCache.set(node.id, g); return g; }
    res = refAddressOf(om.parent_id, 'aws_api_gateway_resource');
  }
  return null;
}

// ---- 起点を作る ----
const starts = [];
const fallbacks = [];
const normPath = (p) => p.replace(/^\.\//, '').replace(/\\/g, '/');
function fileNode(p) {
  const norm = normPath(p);
  for (const n of graph.nodes) if (n.path && normPath(n.path) === norm) return n;
  return null;
}
function nearestFolder(p) {
  const segs = normPath(p).split('/');
  for (let i = segs.length - 1; i > 0; i--) {
    const cand = `folder:${segs.slice(0, i).join('/')}`;
    if (byId.has(cand)) return cand;
  }
  return 'folder:.';
}
if (opts.changed) {
  const text = opts.changed === '-' ? readFileSync(0, 'utf8') : readFileSync(resolve(opts.changed), 'utf8');
  for (const line of text.split('\n')) {
    const p = line.trim();
    if (!p || p.startsWith('#')) continue;
    const norm = normPath(p);
    const node = fileNode(norm);
    if (!node) {
      fallbacks.push({ path: norm, used: nearestFolder(norm), started: !!opts.folderStart });
      if (!opts.folderStart) continue;   // 既定は起点にしない（誤検出の膨らみを防ぐ）
      starts.push({ id: nearestFolder(norm), why: `変更ファイル ${norm} の最も近い親（階層で届いただけ。依存の証拠ではない）` });
      continue;
    }
    starts.push({ id: node.id, why: '変更ファイル', exact: true });
    // Terraform ファイルの「中身」はメソッドではなく宣言しているリソース。
    // リソースノードの parent はフォルダなので、階層ではたどれない（metadata.file で照らす）
    for (const n of graph.nodes) {
      if (n.kind === 'resource' && n.metadata && normPath(n.metadata.file || '') === norm) {
        starts.push({ id: n.id, why: `${norm} が宣言している Terraform リソース`, exact: true });
      }
    }
  }
}
for (const f of opts.from) {
  const hit = byId.has(f) ? [f] : graph.nodes.filter((n) => n.name === f || n.id === f || n.path === f).map((n) => n.id);
  if (!hit.length) { console.error(`[report] 起点が見つからない: ${f}`); process.exit(2); }
  for (const id of hit) starts.push({ id, why: `指定 (${f})` });
}
// `--api "POST /orders"`: verb とパスの両方で照合する（スラッシュの前後はどちらに有っても同じ）
const strip = (s) => String(s).replace(/^\/+|\/+$/g, '').toLowerCase();
function resolveApi(spec) {
  const m = /^\s*([A-Za-z]+)\s+(\/\S*)?\s*$/.exec(spec);
  if (!m) { console.error(`[report] --api の形が不正（例: "POST /orders"）: ${spec}`); process.exit(2); }
  const verb = m[1].toUpperCase();
  const path = m[2] ? strip(m[2]) : null;
  const hits = [];
  for (const n of endpointNodes) {
    const name = endpointOf(n);
    const mm = /^(\S+)\s+(\S*)$/.exec(name);
    if (!mm || mm[1].toUpperCase() !== verb) continue;
    if (path !== null && strip(mm[2]) !== path) continue;
    hits.push({ id: n.id, name });
  }
  return { spec, verb, path, hits: hits.map((h) => h.id), matched: hits.map((h) => h.name) };
}
const apiResolved = opts.api.map(resolveApi);
for (const r of apiResolved) {
  if (!r.hits.length) console.error(`[report] --api "${r.spec}" に一致する API メソッドが無い（endpoint / http_method + apiPath で照合）`);
  for (const id of r.hits) starts.push({ id, why: `API エンドポイント ${r.verb} ${r.path || ''}`, exact: true });
}

// 起点は、その中に**含まれるもの**へ展開する。C# ではメソッド、Terraform では宣言されている
// リソース。リソースの `parent` は置かれたフォルダなので、フォルダ起点では `parent` 側に現れる
// （ファイル起点は `metadata.file` で拾う側の規則を使う）
function membersUnder(id) {
  const acc = [];
  const stack = [id];
  while (stack.length) {
    const cur = stack.pop();
    for (const k of kidsOf.get(cur) || []) {
      const kind = byId.get(k).kind;
      if (kind === 'member' || kind === 'resource') acc.push(k);
      stack.push(k);
    }
  }
  return acc;
}
// `project:` 起点は階層では展開できない。実グラフでは csproj と `.cs` ファイルは**同じフォルダの
// 子**で、プロジェクトの子になっていない（`contains` 縁は持たない）。なのでパスの所属で拾う
function filesOfProject(node) {
  const projPath = normPath(node.path || node.id.replace(/^project:/, ''));
  const dir = projPath.includes('/') ? projPath.slice(0, projPath.lastIndexOf('/')) : '';
  const acc = [];
  for (const n of graph.nodes) {
    if (n.kind === 'file') {
      const np = normPath(n.path || '');
      if (dir === '' || np.startsWith(`${dir}/`)) acc.push(n.id);
    } else if (n.kind === 'resource' && n.metadata && n.metadata.file) {
      const np = normPath(String(n.metadata.file));
      if (np.endsWith('.tf') && (dir === '' || np.startsWith(`${dir}/`))) acc.push(n.id);
    }
  }
  return acc;
}
const seenStart = new Set();
const startIds = [];
const addStart = (id) => { if (byId.has(id) && !seenStart.has(id)) { seenStart.add(id); startIds.push(id); } };
for (const s of starts) {
  if (!byId.has(s.id)) continue;
  addStart(s.id);
  const node = byId.get(s.id);
  if (opts.noExpand) continue;
  if (node.kind === 'file' || node.kind === 'project' || node.kind === 'folder') {
    for (const m of membersUnder(s.id)) addStart(m);
  }
  if (node.kind === 'project') {
    // プロジェクトの下のファイル自体も起点に含める。含まないと「プロジェクトの変更」に対して
    // 自分のファイルが「影響する先」として並ぶ（起点自身は着地に数えない）
    for (const f of filesOfProject(node)) {
      addStart(f);
      for (const m of membersUnder(f)) addStart(m);
    }
  }
}
if (!startIds.length) console.error('[report] 起点が 0 件です。変更ファイルがグラフに無い可能性がありますが、その場合は起点にしません（--folder-start は誤検出を増やします）');

// ---- walk（階層は使わない） ----
// 影響は「変更を使う側（in）」と「変更が触れる先（out）」で意味が違う。ただ片方向だけだと
// `Order.cs` の変更がリポジトリ実装（in）に届いても、そこから `reads → テーブル`（out）へ進めず、
// 実際に必要な着地が落ちる。そこで**方向の切り替えを 1 回だけ**許し、切り替えた行は
// `switches: 1` として「一段（直接）」と「二段（経由）」を区別できるまま出す。
function walkWithSwitch(seedIds, first) {
  const seen = new Map();
  const best = new Map();
  let frontier = [...new Set(seedIds)].map((id) => ({ id, dir: first, switches: 0, via: null, edge: null, corr: false, hops: 0 }));
  const keep = (rec) => {
    const cur = best.get(rec.id);
    if (!cur || rec.switches < cur.switches || (rec.switches === cur.switches && rec.hops < cur.hops)) {
      best.set(rec.id, rec);
      return true;
    }
    return false;
  };
  for (const f of frontier) { seen.set(`${f.id}|${f.dir}|0`, f); best.set(f.id, f); }
  let hop = 0;
  while (hop < opts.hops && frontier.length) {
    hop++;
    const next = [];
    for (const cur of frontier) {
      // 方向の切り替えは**コードノードでだけ**認める。リソースノード（Lambda など）で切り替えると、
      // Terraform の `references` を伝って「変更していない設定」まで影響に巻き込む
      // （実測で `iam_role` / `rest_api` / `resource` が余分に着地した）
      const canSwitch = cur.switches < 1 && (byId.get(cur.id) || {}).kind !== 'resource';
      const dirs = canSwitch ? [cur.dir, cur.dir === 'in' ? 'out' : 'in'] : [cur.dir];
      for (const d of dirs) {
        for (const { e, to, corr } of (d === 'in' ? inn : out).get(cur.id) || []) {
          // 向きが変わるときだけ予算を使う。ただし**対応付け（注釈）を渡る切り替えは数えない**
          // （注釈は「コードと外部リソースが同じ物の両側」という定義なので、そこを越えたものを
          // 二段扱いにしたくない）。 resource ノードでの向き変えは相変わらず認めない
          let switches = cur.switches;
          if (d !== cur.dir) {
            if ((byId.get(cur.id) || {}).kind === 'resource' && !corr) continue;
            if (!corr) switches = cur.switches + 1;
            if (switches > 1) continue;
          }
          const key = `${to}|${d}|${switches}`;
          if (seen.has(key)) continue;
          const rec = {
            id: to, dir: d, switches, hops: hop, via: cur.id, corr,
            edge: { id: e.id, kind: e.kind, provenance: e.provenance, source: e.source, target: e.target },
          };
          seen.set(key, rec);
          keep(rec);
          next.push(rec);
        }
      }
    }
    frontier = next;
  }
  return best;
}
const combined = walkWithSwitch(startIds, 'in');

// ---- Terraform の定義単位を結ぶ wiring closure ----
// API Gateway の method / integration / resource / deployment / lambda_permission は Terraform の
// `references` でしか繋がらず、**向きに意味が無い**（「そのブロックを文中に書いた」だけ）。
// 方向付き walk だけだと `method → integration` で止まり、Lambda に届かなかった（実データで実測）。
// そこで Terraform の縁だけは**無方向で閉じ**る。data ソース（`provider: data`）は
// ほとんどをを参照してノイズになるので既定では閉じない。
// Terraform の縁のうち「動きが実際に伝わる」縁。ここを越えたら段数を数え直す
const MOVEMENT = new Set(['triggers', 'invokes', 'handler']);
const tfAdj = new Map();
for (const e of graph.edges) {
  if (e.provenance !== 'terraform') continue;
  // `--provenance` と `--drop-kind` は探索の**全段階**で守る。closure だけが素通りすると、
  // 「静的解析だけ」の指定なのに Terraform の `triggers` で着地に混入する
  if (opts.dropKind.includes(e.kind)) continue;
  if (opts.provenance && !opts.provenance.includes(e.provenance)) continue;
  const a = byId.get(e.source); const b = byId.get(e.target);
  if (!a || !b) continue;
  if (a.kind === 'folder' || b.kind === 'folder' || a.kind === 'file' || b.kind === 'file') continue;
  for (const [from, to] of [[e.source, e.target], [e.target, e.source]]) {
    const m = byId.get(to).metadata || {};
    if (!opts.includeData && (m.provider === 'data' || m.resourceType === 'data' || m.dataSource)) continue;
    if (!tfAdj.has(from)) tfAdj.set(from, []);
    tfAdj.get(from).push({ to, edge: e });
  }
}
const wiringMap = new Map();
const wiringSeen = new Set();
// closure を関数にして呼び直せるようにする（`handler` でコード側に届いたあと、そこからも閉じ直す）
function runClosure(seedIds) {
  const queue = [];
  for (const id of new Set(seedIds)) {
    if (!byId.has(id) || wiringSeen.has(id)) continue;
    wiringSeen.add(id);
    queue.push({ id, hops: 0, budget: 0, via: null });
  }
  while (queue.length) {
    const cur = queue.shift();
    for (const { to, edge } of tfAdj.get(cur.id) || []) {
      if (wiringSeen.has(to)) continue;
      // 段数の上限は「Terraform の定義単位をどこまで閉じるか」なので、予算を課すのは
      // `references`（定義を辿る縁）だけ。**動きの縁（`triggers` / `invokes` / `handler`）を越えたところでは
      // 数え直す**と決める。そうしないと `method → resource → rest_api → integration` で予算を使い切り、
      // 同じ Lambda を使う別 API が既定の段数で完全に消える（実測: 3 段では何も出ず、6 段で出る）
      const nbudget = MOVEMENT.has(edge.kind) ? 0 : cur.budget + 1;
      if (nbudget > opts.wiringHops) continue;
      wiringSeen.add(to);
      // Terraform の縁も `triggers` / `invokes` / `handler` は**動きとして伝わる**ので本命、
      // `references`（ブロックを文中に書いた）だけ定義上の関連に回す。
      // `via` を入れておかないと Markdown / JSON の根拠経路が `[null]` になる
      wiringMap.set(to, {
        id: to, edge,
        // 向きは「縁の向き × その行が矢印のどちら側か」で決める。
        // **動きの縁**なら矢印の先が下流（影響する先）、元が上流（影響を受ける入口）。
        // 実測バグ: 2 段目で `edge.target === cur.id` を見ると、Lambda 着地が常に「影響を受ける入口」に
        // 回り、実プロジェクト（api-lambda）で `POST /messages` の着地が 0 件になった。
        // `references`（定義）は向きに意味が無いので、辿ってきたノードの向きを継ぐ
        dir: MOVEMENT.has(edge.kind) ? (edge.target === to ? 'out' : 'in')
          : ((combined.get(cur.id) || {}).dir || (edge.target === cur.id ? 'in' : 'out')),
        hops: cur.hops + 1, switches: 0, via: cur.id, wiring: !MOVEMENT.has(edge.kind),
      });
      // メンバ（`handler` の届く先）では展開しない。コード側の縁をたどるのは本命の walk だけにさせる
      if (byId.get(to).kind === 'resource') queue.push({ id: to, hops: cur.hops + 1, budget: nbudget });
    }
  }
  return wiringMap;
}

// 昇格: `references` で着地したノードでも、**そのノードへ向かっている動きの縁**が
// 「方向付き walk が本命として届けたノード」から来ていれば本命へ昇格する。
// 根拠にできるのは walk が届けたノードだけ。closure だけで届いたノードを根拠にすると循環する
// （実測: IAM ロールだけを共有する Lambda A / B で、B 経由で届いた B 専用の integration を
// B 自身の昇格根拠にして A 起点の本命にしていた）
const primaryPool = new Set(startIds);
function refreshPool() {
  for (const [id, rec] of combined) if (!rec.wiring) primaryPool.add(id);
}
function upgradeWiring() {
  refreshPool();
  for (const [id, info] of wiringMap) {
    if (!info.wiring || info.upgraded) continue;
    for (const { to, edge } of tfAdj.get(id) || []) {
      if (!MOVEMENT.has(edge.kind) || edge.target !== id || to === id) continue;
      if (!primaryPool.has(to)) continue;
      // 昇格の根拠は「そのノードへ向かっている動きの縁」なので、その行は必ず下流側
      info.wiring = false; info.edge = edge; info.dir = edge.target === id ? 'out' : 'in';
      info.via = to; info.upgraded = true;
      break;
    }
  }
}
function mergeWiring() {
  for (const [id, info] of wiringMap) {
    const cur = combined.get(id);
    if (!cur) combined.set(id, info);
    else if (cur.wiring === true && info.wiring === false) combined.set(id, info);
  }
}

runClosure(combined.keys());
upgradeWiring();
mergeWiring();

// closure が `handler` でコード側のメンバーに届いたら、**そこからも歩き直す**。
// ここで止めると「API 起点 → Lambda → handler → その Lambda が書くテーブル」の最後の一歩が落ちて、
// レビューで一番知りたい着地が全欄から消えた（注釈で `writes` を付けていても出なかった）
const codeReached = [...combined.keys()].filter((id) => {
  const k = (byId.get(id) || {}).kind;
  return k === 'member' || k === 'type';
});
if (codeReached.length) {
  const second = walkWithSwitch(codeReached, 'out');
  for (const [id, rec] of second) {
    const cur = combined.get(id);
    if (!cur) combined.set(id, rec);
    else if (cur.wiring === true && !rec.wiring) combined.set(id, rec);
  }
  runClosure(second.keys());
  upgradeWiring();
  mergeWiring();
}

// ---- 行を組み立てる ----
const pathOf = (id) => {
  const acc = []; let cur = combined.get(id);
  const guard = new Set();
  while (cur && cur.id && !guard.has(cur.id)) {
    acc.unshift(cur.id); guard.add(cur.id);
    cur = cur.via ? combined.get(cur.via) : null;   // 起点（via 無し）で止める。undefined を並べない
  }
  return acc;
};
const isExternal = (id) => (byId.get(id) || {}).kind === 'resource';
const startSet = new Set(startIds);
// 「起点の中にあるノードは着地に数えない」の判定対象は **ファイルとプロジェクトだけ**。
// `folder:.` を起点にするとその下に全部が入るので、判定を適用すると全ノードが消えて
// 起点だけ出して着地 0 件になる（`--folder-start` の既定の落ち込みがこれ）
const insideContainers = new Set(startIds.filter((id) => {
  const k = (byId.get(id) || {}).kind;
  return k === 'file' || k === 'project';
}));
const startIsEndpoint = starts.some((x) => endpointOf(byId.get(x.id) || {}));
const startApiGroups = new Set(starts.map((x) => apiGroupOf(byId.get(x.id))).filter((g) => g !== null && g !== undefined));
// 起点の**中にあるノード**（変更ファイルの中の型やメソッド）は起点自身の一部なので着地に数えない。
// 変更ファイル起点だと、同じファイルの中の型を「影響する先」として並べてしまい、
// 「変更そのもの」と「変更の先」の区別がなくなるため（親をたどって判定する。階層は walk に使わない）
const insideStart = (id) => {
  let cur = byId.get(id);
  for (let i = 0; cur && cur.parent && i < 12; i++) {
    if (insideContainers.has(cur.parent)) return true;
    cur = byId.get(cur.parent);
  }
  return false;
};
const rows = [];
for (const [id, info] of combined) {
  if (!info.edge || insideStart(id)) continue;
  rows.push({
    direction: info.dir, id, name: label(id), kind: byId.get(id).kind, category: category(id),
    resourceType: (byId.get(id).metadata || {}).resourceType || null,
    endpoint: endpointOf(byId.get(id)),
    hops: info.hops, switches: info.switches, correspondence: !!info.corr,
    tier: info.wiring || (info.edge.kind === 'references' && info.edge.provenance === 'terraform') ? 'wiring' : 'primary',
    // 起点が API エンドポイントのとき、method / resource / rest_api / integration / deployment は
    // **起点となる API 自身を定義している**ので「影響を受ける外部リソース」に数えない
    sameApi: startIsEndpoint && !endpointOf(byId.get(id)) && startApiGroups.has(apiGroupOf(byId.get(id))),
    evidence: info.edge, path: pathOf(id),
  });
}
rows.sort((a, b) => a.switches - b.switches || a.hops - b.hops || a.id.localeCompare(b.id));
const byDirection = (d) => rows.filter((r) => r.direction === d);
const primaryRows = (rs) => rs.filter((r) => r.tier === 'primary' && !r.sameApi && !isSibling(r));
// `sameApi` の行は **tier に関係なく** ここへ寄せる。`tier === 'wiring'` だけを見ると、
// `triggers` で昇格した integration が「本命でもない／同じ API の定義でもない」枠になり、
// どの一覧にも入らず消える（実測: JSON のバケット合計が総行数より 1 件少ない）
const isApiDefinition = (r) => r.sameApi && !isSibling(r);
// 起点がエンドポイントのとき、到着した別のエンドポイント（同じ Lambda を使う兄弟）は
// 「影響を受けたエンドポイント」ではなく**同じコードを共有している**という別情報なので混ぜない
const siblingRows = () => rows.filter(isSibling);
// 兄弟 = **同じコードを共有しているだけ**の別エンドポイント。コード側から `invokes` で
// 呼びに出しているエンドポイントは「呼び出している先」なので兄弟にしない（実測で
// `Handler → invokes → 別 API` が兄弟に分類され、影響する先から消えた）
const isSibling = (r) => startIsEndpoint && !!r.endpoint && !startSet.has(r.id)
  && r.evidence.kind !== 'invokes';
// 定義上の関連 = 他の枠（本命の外部リソース / コードの入口 / 同じ API の定義 / 兄弟）に
// 入らなかった行の引き取り手。ここに条件を足し忘れると行がどこにも出なくなるので、
// 「本命として列挙した行」だけを明示的に除外する形にする
const listedElsewhere = (r) => r.tier === 'primary' && !r.sameApi && !isSibling(r)
  && (isExternal(r.id) || r.kind === 'member' || r.kind === 'type');
const wiringRows = () => rows.filter((r) => !isApiDefinition(r) && !isSibling(r) && !listedElsewhere(r));
const sameApiRows = () => rows.filter(isApiDefinition);
// 「外部リソースへの着地」と「コード側の入口」は別の数える対象。同じ一覧を両方の欄に流すと、
// エンドポイント起点のときにコードのメソッドが「外部リソース」として数えてしまう
const externalRows = (rs) => primaryRows(rs).filter((r) => isExternal(r.id));
const entryRows = (rs) => primaryRows(rs).filter((r) => r.kind === 'member' || r.kind === 'type');
const endpointsOf = (ids) => ids.map((id) => {
  const n = byId.get(id); const m = n.metadata || {};
  return { id, kind: n.kind, name: endpointOf(n), resourceType: m.resourceType, category: m.category };
});

// ---- 再現率・適合率 ----
function score() {
  if (!opts.expect) return null;
  const spec = JSON.parse(readFileSync(resolve(opts.expect), 'utf8'));
  // 「影響する先（out）」と「影響を受ける入口（in）」を混ぜて割ると適合率が意味をなくす
  // （呼び出し元は外部リソースなのに分母に入ってしまう）。期待側に direction を書いてもらい、既定は both
  const dir = spec.direction === 'in' || spec.direction === 'out' ? spec.direction : 'both';
  const list = dir === 'in' ? primaryRows(byDirection('in'))
    : dir === 'out' ? primaryRows(byDirection('out'))
      : rows.filter((r) => r.tier === 'primary' && !r.sameApi && !isSibling(r));
  const got = new Set(list.map((r) => r.id));
  const want = new Set(spec.expect || []);
  const landedExt = [...got].filter(isExternal);
  const hitExt = landedExt.filter((id) => want.has(id));
  const precision = landedExt.length ? hitExt.length / landedExt.length : (want.size ? 0 : 1);
  const recall = want.size ? hitExt.length / want.size : 1;
  return {
    case: spec.name || basename(resolve(opts.expect)), direction: dir,
    expected: want.size, landedExternal: landedExt.length, hitExternal: hitExt.length,
    missed: [...want].filter((id) => !got.has(id)),
    extraExternal: landedExt.filter((id) => !want.has(id)),
    wiringOnly: [...want].filter((id) => !got.has(id) && combined.has(id)).length,
    precision: Number(precision.toFixed(3)), recall: Number(recall.toFixed(3)),
    note: spec.note || '',
  };
}

const inRows = byDirection('in'); const outRows = byDirection('out');
const startEndpoints = endpointsOf([...startSet].filter((id) => endpointOf(byId.get(id))));
const reachedEndpoints = endpointsOf([...combined.keys()].filter((id) => endpointOf(byId.get(id)) && !startSet.has(id)));
const annotationRows = rows.filter((r) => r.evidence.provenance === 'llm' || r.evidence.provenance === 'human');
const summary = {
  graph: resolve(opts.graph), starts: starts.length, expandedStarts: startIds.length,
  fallbacks: fallbacks.length, hops: opts.hops, wiringHops: opts.wiringHops,
  primaryIn: externalRows(inRows).length, primaryOut: externalRows(outRows).length,
  entryIn: entryRows(inRows).length, entryOut: entryRows(outRows).length,
  wiring: wiringRows().length, sameApi: sameApiRows().length, siblings: siblingRows().length,
  secondOrder: rows.filter((r) => r.switches === 1).length,
  // 総行数。各欄（外部 / 入口 / 定義上 / 同じ API / 兄弟）の合計と必ず同じになる。
  // 過去に「primary かつ sameApi の行がどの欄にも入らず消える」不具合があったので、
  // この 2 つが一致することを検査で固定する（JSON を渡して誰も生データを読まなくても確かめられる）
  rows: rows.length,
  startIsEndpoint,
  startEndpoints, reachedEndpoints,
  correspondenceRows: rows.filter((r) => r.correspondence).length,
  annotationRows: annotationRows.length,
  byProvenance: (() => {
    const c = {};
    for (const r of rows) c[r.evidence.provenance] = (c[r.evidence.provenance] || 0) + 1;
    return c;
  })(),
};
const result = {
  summary,
  starts: starts.map((s) => ({ id: s.id, why: s.why })),
  api: apiResolved,
  fallbacks,
  score: score(),
  external: { in: externalRows(inRows), out: externalRows(outRows) },
  entries: { in: entryRows(inRows), out: entryRows(outRows) },
  sameApi: sameApiRows().slice(0, opts.limit),
  siblingEndpoints: siblingRows().slice(0, opts.limit),
  wiring: wiringRows().slice(0, opts.limit),
};
if (opts.json) writeFileSync(resolve(opts.json), JSON.stringify(result, null, 2));

const provLabel = (p) => ({
  static: '静的', terraform: 'Terraform', llm: '注釈 (LLM)', human: '注釈 (人)',
  merge: 'マージ', 'directory-scanner': '階層', viewer: 'ブラウザ',
}[p] || p);
function mdSection(title, rs, limit) {
  if (!rs.length) return `### ${title}\n\n該当なし\n\n`;
  const head = `### ${title}\n\n| 着地 | 種別 | 距離 | 根拠 | 由来 |\n| --- | --- | --- | --- | --- |\n`;
  const body = rs.slice(0, limit).map((r) =>
    `| ${r.name} | ${r.category} | ${r.hops} | \`${r.evidence.kind}\` ${r.evidence.source.split(':').pop()} → ${r.evidence.target.split(':').pop()} | ${provLabel(r.evidence.provenance)}${r.correspondence ? '（対応）' : ''} |`).join('\n');
  const more = rs.length > limit ? `\n\n（他 ${rs.length - limit} 件は --json 参照）` : '';
  return head + body + '\n' + more + '\n\n';
}
const epLine = (e) => `- \`${e.name}\`（\`${e.id}\`）`;
let md = `# 影響範囲レポート\n\n- グラフ: \`${summary.graph}\`\n- 起点 ${summary.starts} 件（展開後 ${summary.expandedStarts} 件、グラフに無く起点にしなかった変更 ${summary.fallbacks} 件）\n- 探索 ${summary.hops} ホップ（方向の切り替え 1 回まで許可、二段到達 ${summary.secondOrder} 件）/ Terraform の定義単位は ${summary.wiringHops} 段まで無方向で閉じる / 階層（parent・contains）は起点の展開にのみ使用\n- 本命: 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コードの入口 先 ${summary.entryOut}・受 ${summary.entryIn} / 定義上の関連 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 同じコードを使う別エンドポイント ${summary.siblings}\n- 根拠の由来: ${Object.entries(summary.byProvenance).map(([k, v]) => `${provLabel(k)} ${v}`).join(' / ') || 'なし'}（**注釈由来 ${summary.annotationRows} 件**は静的解析では決まらない対応付け）\n\n`;
if (result.score) {
  const s = result.score;
  md += `## 精度（期待一覧との突き合わせ）\n\n- ケース: ${s.case}（方向 ${s.direction}）\n- 期待 ${s.expected} 件 / 外部リソースへの着地 ${s.landedExternal} 件 / 的中 ${s.hitExternal} 件\n- **再現率 ${s.recall} / 適合率 ${s.precision}**\n- 取りこぼし: ${s.missed.map((x) => `\`${x}\``).join(', ') || 'なし'}\n- 余分な着地: ${s.extraExternal.map((x) => `\`${label(x)}\``).join(', ') || 'なし'}\n- 取りこぼしのうち到達はしていた（定義上の関連に回ったもの）: ${s.wiringOnly} 件\n${s.note ? `\n> ${s.note}\n` : ''}\n`;
}
if (fallbacks.length) {
  md += `## 起点にできなかった変更\n\nグラフに対応するノードが無く、**起点にはしていません**（親フォルダを起点にすると配下を巻き込んで誤検出が膨らむため）。`
    + `最も近い親: ${fallbacks.map((f) => `\`${f.path}\` → \`${f.used}\``).join('、') || 'なし'}\n\n`;
}
md += `## 影響を受ける API エンドポイント\n\n`;
md += startEndpoints.length
  ? `起点にしたエンドポイント:\n\n${startEndpoints.map(epLine).join('\n')}\n\n`
  : '';
md += reachedEndpoints.length
  ? `${startEndpoints.length ? 'それを使う' : '到達した'}エンドポイント（**起点の定義ではない**同じコードを使う別エンドポイントを含む）:\n\n${reachedEndpoints.map(epLine).join('\n')}\n\n`
  : (startEndpoints.length ? '' : '該当なし\n\n');
md += mdSection('影響する外部リソース（変更が読み書きする先）', externalRows(outRows), opts.limit);
md += mdSection('影響を受ける入口（変更を使う呼び出し元・リソース）', externalRows(inRows), opts.limit);
md += mdSection('影響を受けるコード側の入口（メソッド・型）', entryRows(inRows).slice(0, opts.limit), opts.limit);
// JSON には `entries.out` が入るのに Markdown に出ていなかった（実測 11 件が画面から見えない）。
// エンドポイント起点のとき「Lambda が実際に実行するコード」がこれなので、欄を分けて出す
md += mdSection('影響を受けるコード側の出口（起点から届くメソッド・型）', entryRows(outRows).slice(0, opts.limit), opts.limit);
if (startIsEndpoint) md += mdSection('起点と同じ API を定義するノード（変更で値は動かないので見直しの候補）', sameApiRows(), opts.limit);
if (startIsEndpoint && siblingRows().length) {
  md += `## 同じコードを使う別エンドポイント（起点の定義ではない。共有しているコードを変えたときに一緒に見る）\n\n`
    + siblingRows().map((r) => `- \`${r.name}\`（\`${r.id}\`、距離 ${r.hops}、根拠 \`${r.evidence.kind}\`）`).join('\n') + '\n\n';
}
md += mdSection('定義上の関連（変更で値は動かなくても見直しの候補）', wiringRows(), opts.limit);
if (opts.md) writeFileSync(resolve(opts.md), md);

console.log(`API エンドポイント: ${[...startEndpoints, ...reachedEndpoints].map((e) => e.name).join(', ') || '該当なし'}`);
console.log(`起点 ${summary.starts} 件（展開後 ${summary.expandedStarts}）/ 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コードの入口 先 ${summary.entryOut}・受 ${summary.entryIn} / 定義上 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 兄弟エンドポイント ${summary.siblings} / 注釈由来 ${summary.annotationRows}`);
if (result.score) console.log(`精度: 再現率 ${result.score.recall} / 適合率 ${result.score.precision}（期待 ${result.score.expected} / 外部着地 ${result.score.landedExternal} / 的中 ${result.score.hitExternal} / 余分 ${result.score.extraExternal.length}）`);
for (const r of externalRows(outRows).slice(0, 12)) console.log(`  [out ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
for (const r of externalRows(inRows).slice(0, 12)) console.log(`  [in  ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
