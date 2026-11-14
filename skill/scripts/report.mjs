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

// 探索の打ち切り。有限であることの保証用に置くだけで、実データでは到達しない
// （elsa-core の 51,179 ノード / 53,521 縁で `--folder-start` を投げても数万ステップで終わる）
const MAX_WALK_STEPS = 4_000_000;
const MAX_CLOSURE_STEPS = 4_000_000;
const MAX_ROUNDS = 6;

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
  for (const id of hit) starts.push({ id, why: `指定 (${f})`, exact: true });
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
// 子**で、プロジェクトの子になっていない（`contains` 縁は持たない）。なのでパスの所属で拾う。
// 所属は**そのファイルを一番よく囲んでいるプロジェクト**で決める。自分のディレクトリを
// 前方一致しただけにすると、リポジトリ直下の csproj がリポジトリ全体（別の csproj の下も含む）を
// 飲み込んで、変更していないプロジェクトまで起点にした（実測: ReportImpact で全 4 ファイルが起点化）
const projectDirs = graph.nodes.filter((n) => n.kind === 'project').map((n) => {
  const pp = normPath(n.path || n.id.replace(/^project:/, ''));
  return pp.includes('/') ? pp.slice(0, pp.lastIndexOf('/')) : '';
});
function ownerDirOf(filePath) {
  let best = null;
  for (const dir of projectDirs) {
    if (!dir) { if (best === null) best = ''; continue; }        // ルートのプロジェクトは最下位の受け皿
    if (filePath.startsWith(`${dir}/`)) { if (best === null || dir.length > best.length) best = dir; }
  }
  return best;
}
function filesOfProject(node) {
  const projPath = normPath(node.path || node.id.replace(/^project:/, ''));
  const dir = projPath.includes('/') ? projPath.slice(0, projPath.lastIndexOf('/')) : '';
  const acc = [];
  for (const n of graph.nodes) {
    if (n.kind === 'file') {
      const np = normPath(n.path || '');
      if (ownerDirOf(np) === dir) acc.push(n.id);
    } else if (n.kind === 'resource' && n.metadata && n.metadata.file) {
      const np = normPath(String(n.metadata.file));
      if (np.endsWith('.tf') && ownerDirOf(np) === dir) acc.push(n.id);
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

// ---- 起点が「エンドポイント」かどうか ----
// `--api "POST /orders"` や、変更した `.tf` に宣言された method のように、**起点そのものが
// エンドポイント**のときだけ使うルールを分ける。起点の展開で入ったファイルのメンバーや、
// `--folder-start` の受け皿のフォルダは起点そのものではないので数えない
// （実測: `folder:.` 起点で「起点にしたエンドポイント」が並んでいた）
const startSet = new Set(startIds);
const directStartIds = new Set(starts.filter((x) => x.exact).map((x) => x.id));
const startIsEndpoint = startIds.some((id) => directStartIds.has(id) && endpointOf(byId.get(id)));
// 起点が所属する API Gateway のグループ。`rest_api_id` を持つノード（method / resource /
// integration / deployment）はこれで括るので、起点と同じグループの定義は
// 「変更しても値が動かない設定」として別枠に出せる
const startApiGroups = new Set(starts.map((x) => apiGroupOf(byId.get(x.id))).filter((g) => g !== null && g !== undefined));

// ---- walk（階層は使わない） ----
// 影響は「変更を使う側（in）」と「変更が触れる先（out）」で意味が違う。ただ片方向だけだと
// `Order.cs` の変更がリポジトリ実装（in）に届いても、そこから `reads → テーブル`（out）へ進めず、
// 実際に必要な着地が落ちる。そこで**方向の切り替えを 1 回だけ**許し、切り替えた行は
// `switches: 1` として「一段（直接）」と「二段（経由）」を区別できるまま出す。
//
// 状態は (ノード, 辿った向き, 向きを変えた回数, 起点からの段数, 実装側に入ったか) を持つ。
// **一度着いたノードの記録は書き換えない。** 書き換えると `via` が循環して根拠経路が起点に
// 戻らなくなり、`hops` と `path` の長さも食い違った（実測: demo の 31 行中 29 行、実プロジェクトで 3 行）。
// 段数は常に `via` の先より 1 大きいので、`hops === path.length - 1` と
// `path[0]` が必ず起点になることが常に成り立つ
const combined = new Map();
// 向きが反転する縁。`exposed-by` は「このコードがこのエンドポイントで公開される」なので
// 動きはエンドポイント → コードへ流れ、`handler` は「この Lambda がこのコードを実行する」。
// **起点がエンドポイントのとき**に限って、これを逆向きに辿ったところから先は
// 「そのエンドポイントの実行が触れるもの」なので全部 影響する先（out）にする。
// （実測バグ: 注釈 `exposed-by` 経由で `--api "POST /orders"` を引くと、実装側の Lambda が
// 「影響を受ける入口」に逆転していた。コード起点では向きを変えないので測った値はそのまま）
const FLIP_INTO_IMPL = new Set(['exposed-by', 'handler']);
function walkWithSwitch(seedIds, first) {
  const found = new Map();
  let frontier = [];
  for (const id of new Set(seedIds)) {
    if (!byId.has(id)) continue;
    const prev = combined.get(id);
    const seed = prev || {
      id, dir: first, mdir: first, switches: 0, hops: 0, via: null, edge: null,
      corr: false, down: false, calledOut: false,
    };
    found.set(id, seed);
    frontier.push(seed);
  }
  let guard = 0;
  while (frontier.length && guard++ < MAX_WALK_STEPS) {
    const next = [];
    for (const cur of frontier) {
      if (cur.hops >= opts.hops) continue;
      // 辿る adjacency は**機械的な向き（mdir）**で決める。`dir` は表示用の向きで、
      // 起点がエンドポイントのときは反転させた値なので、これで隣接表を選ぶと辿る方向が壊れる
      const canSwitch = cur.switches < 1;
      const base = cur.mdir || cur.dir;
      const dirs = canSwitch ? [base, base === 'in' ? 'out' : 'in'] : [base];
      for (const d of dirs) {
        for (const { e, to, corr } of (d === 'in' ? inn : out).get(cur.id) || []) {
          if (found.has(to)) continue;                       // 先着のみ。記録を書き換えない
          let switches = cur.switches;
          if (d !== base) {
            // 向きが変わるときだけ予算を使う。**対応付け（注釈）を渡る切り替えは数えない**
            // （静的解析の外側で結ばれた縁を律儀に数えられない）
            if (!corr) {
              // リソースノード（Lambda・API Gateway の定義など）で向きを変えて辿ると、変更して
              // いない設定（`iam_role` / `rest_api` / 同じ Lambda を使う**別 API** の integration）
              // まで影響に巻き込む（実測で `GET /users` 側の定義が本命に着地した）。
              // Terraform の中をまたぐ広がりは向きを問わない閉包（runClosure）が担うので、
              // ここでは通さない
              if ((byId.get(cur.id) || {}).kind === 'resource') continue;
              switches = cur.switches + 1;
              if (switches > 1) continue;
            }
          }
          // 起点がエンドポイントのとき、実装側へ入った境目で向きを反転させる（上の説明どおり）。
          // 反転は**その後の経路に引き継ぐ**（実装の中の呼び出し元も、そのエンドポイントの実行の一部）
          const down = cur.down || (startIsEndpoint && d === 'in' && FLIP_INTO_IMPL.has(e.kind));
          const movement = MOVEMENT.has(e.kind);
          const rec = {
            id: to, mdir: d, down, switches,
            // 動きの縁は矢印で向きを決める（`exposed-by` は反転）。定義や注釈の縁は、
            // 実装側に入っているなら 影響する先、そうでなければ辿った向きをそのまま使う
            dir: movement ? (arrowAt(e, to) ? 'out' : 'in') : (down ? 'out' : d),
            hops: cur.hops + 1, via: cur.id, corr,
            // 「このノードは呼び出されて成立する」は**この一歩が `invokes` かどうか**だけ。
            // 経路に `invokes` が含まれるという判定にすると、呼び出しの先で更に届いた
            // 無関係な別エンドポイント（同じ Lambda を使う兄弟）まで「呼びに出した先」に
            // 化けて兄弟欄から消えた
            calledOut: e.kind === 'invokes',
            edge: { id: e.id, kind: e.kind, provenance: e.provenance, source: e.source, target: e.target },
          };
          found.set(to, rec);
          next.push(rec);
        }
      }
    }
    frontier = next;
  }
  return found;
}
// 既に記録のあるノードの **`via` / `hops` / `dir` は書き換えない**（根拠経路が循環して
// 「経路の先頭が起点でない」「`hops` と経路の長さが食い違う」壊れ方を二度と同じ場所に
// 戻さないため）。書き換えずに済む情報だけ足す:
//  - `calledOut`: 経路上に `invokes` を含む（兄弟エンドポイントと区別する判定に使う）
//  - `movementEvidence` / `wiring = false`: 別の経路に**動きの縁**があった = 定義上ではなく本命
function promote(cur, rec) {
  if (rec.calledOut) cur.calledOut = true;
  // 「起点のエンドポイントの実装の中にある」という事実は一方通行（後から強い方の情報に
  // なるだけ）なので、先着の記録がまだ実装側に入る前のものでも反転させる。
  // `Step Functions → invokes → notify` のような**手前を向く縁**で先に着地すると
  // 「影響を受ける入口」になり、同じノードが実装の一部だと分かっても戻らなかった
  if (rec.down) cur.down = true;
  if (cur.wiring === true && rec.wiring !== true) {
    cur.wiring = false;
    cur.movementEvidence = rec.edge || cur.movementEvidence || null;
  }
}
function mergeRecords(found) {
  for (const [id, rec] of found) {
    const cur = combined.get(id);
    if (!cur) combined.set(id, rec);
    else promote(cur, rec);
  }
}

// ---- Terraform の定義単位を結ぶ wiring closure ----
// API Gateway の method / integration / resource / deployment / lambda_permission は Terraform の
// `references` でしか繋がらず、**向きに意味が無い**（「そのブロックを文中に書いた」だけ）。
// 方向付き walk だけだと `method → integration` で止まり、Lambda に届かなかった（実データで実測）。
// そこで Terraform の縁だけは**無方向で閉じ**る。data ソース（`provider: data`）は
// 参照先を参照するだけなのでノイズになり、既定では閉じない
const MOVEMENT = new Set(['triggers', 'invokes', 'handler']);
// 動きの縁は**矢印の先が下流**。`exposed-by` だけが逆で、「コードがこのエンドポイントを
// 公開している」という向きなので、矢印の元側（コード）が下流になる
const ARROW_REVERSED = new Set(['exposed-by']);
const arrowAt = (edge, id) => (ARROW_REVERSED.has(edge.kind) ? edge.source : edge.target) === id;
const tfAdj = new Map();
for (const e of graph.edges) {
  if (e.provenance !== 'terraform') continue;
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
// 定義の縁を**伝播に使える向き**を決める判定。
// `X → references → Y` は「X が Y の定義の一部を書いた」（integration が method を参照する）と読む。
// だから **参照されている側 Y から参照している側 X へ進むときだけ**、その先へ動きを伝播してよい。
// 逆向き（X から Y へ = 「自分が使っているもの」へ進む）は伝播しない。これで次の 2 つが両方管まる:
//  - 起点の method → integration → (`triggers`) → Lambda: integration は method の定義の一部なので伝播する
//  - 起点の Lambda → (`references`) → IAM ロール → (`references`) → 別 Lambda: ロールは
//    Lambda が**使っている**ものなので伝播しない。ロールだけを共有する別 Lambda の
//    integration / handler / その先にあるテーブルまで本命になることはかない（双人レビュー P1）
const refersInto = (edge, fromId, toId) => edge.target === fromId && edge.source === toId;
// API Gateway の定義は**同じ API に属する限り**連鎖で伝播してよい（method → resource →
// integration → Lambda のように定義が 3 つ連なるのが普通なので、1 歩限定では届かない）。
// グループは起点のものと、**起点から動きとして届いた endpoint のもの**を増やす
// （`Handler.A → invokes → API B` と届いたら B の実装も影響範囲）。グループを持たない定義
// （IAM ロール・テーブル名・S3 など）はここに入らない
const touchedApiGroups = new Set(startApiGroups);
const inTouchedApiGroup = (id) => {
  const g = apiGroupOf(byId.get(id));
  return (g === null || g === undefined) ? false : touchedApiGroups.has(g);
};
const wiringMap = new Map();
const bestState = new Map();   // id -> { budget, primary, elig }（より良い状態で再び着いたら expand し直す）
// closure の状態は (段数, 定義の縁の残り予算, 本命か, 動きを伝播してよいか)。
// **訪問済み をノード id だけで決めると**、予算を多く使った経路が先着した瞬間に
// 同じノードへの少ない予算の経路が捨てられ、辺の並び順だけで着地が変わる（実測: 53 ノードの
// fixture で `kms_key` が出る順と消える順が作れた）。だから「同じノードでも予算が減った／
// 定義上から本命へ昇格した」なら再展開する
function runClosure(seedIds) {
  const queue = [];
  // 受理したら true。**受理された状態だけを展開する**（受理不看で queue に入れると、
  // 古い状態が隣を又呼び、隣が又戻ってきて列が伸び続けて終わらなくなる）
  const offer = (state) => {
    // 受理の可否とかかわらず、届いた記録の**旗**（実装側 / 動きの縁 / 呼び出し）は
    // 既存の行に合流させる。不受理のままだと「同じ Lambda を使う兄弟」の向きだけが
    // 古い到着のままになる
    if (state.rec) {
      const cur = combined.get(state.id);
      if (cur) promote(cur, state.rec);
      else wiringMap.set(state.id, state.rec);
    }
    const prev = bestState.get(state.id);
    // 受理の基準は「厳密に良くなる」だけ。`down` / `calledOut` は一度ついたら消えない事実なので、
    // それが付いた状態も受理する（それぞれのフラグは高々 1 回だけ立つので無限にはならない）
    const better = !prev
      || (state.primary && !prev.primary)
      || (state.elig && !prev.elig)
      || (state.down && !prev.down)
      || (state.calledOut && !prev.calledOut)
      || (state.primary === prev.primary && state.elig === prev.elig && state.budget < prev.budget);
    if (!better) return false;
    bestState.set(state.id, {
      budget: state.budget, primary: state.primary, elig: state.elig,
      down: !!state.down, calledOut: !!state.calledOut,
    });
    if (state.rec) wiringMap.set(state.id, state.rec);
    return true;
  };
  for (const id of new Set(seedIds)) {
    if (!byId.has(id)) continue;
    const rec = combined.get(id);
    const state = {
      id, hops: rec ? rec.hops : 0, budget: 0, down: rec ? !!rec.down : false,
      calledOut: rec ? !!rec.calledOut : false,
      primary: !rec || !rec.wiring, elig: !rec || !rec.wiring || inTouchedApiGroup(id),
      via: null, rec: null,
    };
    if (offer(state)) queue.push(state);
  }
  let guard = 0;
  while (queue.length && guard++ < MAX_CLOSURE_STEPS) {
    const cur = queue.shift();
    for (const { to, edge } of tfAdj.get(cur.id) || []) {
      // 段数の上限は「Terraform の定義単位をどこまで閉じるか」なので、予算を課すのは
      // `references`（定義を辿る縁）だけ。**動きの縁を越えたところでは数え直す**
      const movement = MOVEMENT.has(edge.kind);
      const budget = movement ? 0 : cur.budget + 1;
      if (budget > opts.wiringHops) continue;
      // **伝播の資格**: 動きの縁を辿っても、辿ってきたノードが「起点 / 本命として届いたノード /
      // 起点と同じ API を定義しているノード」でなければ、その先は定義上の関連のままにする。
      // これを忘れると、IAM ロールだけを共有する別 Lambda 経由で its 専用の integration や
      // その handler まで本命に伝播した（双人レビュー P1。`references` をまたいだ伝播資格を
      // 縁の種類だけ見ていたのが原因）
      const primary = movement && cur.elig;
      // 定義の縁を渡るときは**参照している側へ進む一歩だけ**資格を受け継ぐ。
      // 「自分が使っているもの」（Lambda → IAM ロール、Lambda → テーブル名）へ渡った先は
      // 資格を失うので、そこで繋がっているだけの第三者にまでは広がらない
      const elig = primary || inTouchedApiGroup(to)
        || (!movement && cur.elig && refersInto(edge, cur.id, to));
      const rec = {
        id: to, edge,
        hops: cur.hops + 1, switches: 0, via: cur.id, wiring: !primary,
        down: !!cur.down, calledOut: edge.kind === 'invokes',
        // 向きは「縁の向き × その行が矢印のどちら側か」。動きの縁なら矢印の先が下流。
        // `references`（定義）は向きに意味無いので辿ってきたノードの向きを継ぐ
        // 起点がエンドポイントで**その実装側に入っている**なら、そこから先は全部 影響する先。
        // `SFN → invokes → notify` のように矢印が手前を向いていても、その_invoke_は
        // このエンドポイントの実行の一部なので逆転させない
        dir: movement ? (arrowAt(edge, to) ? 'out' : 'in')
          : cur.down ? 'out'
            : ((combined.get(cur.id) || {}).dir || (edge.target === cur.id ? 'in' : 'out')),
      };
      const state = {
        id: to, hops: rec.hops, budget, primary, elig, via: cur.id, rec,
        down: rec.down, calledOut: rec.calledOut,
      };
      // メンバ（`handler` の届く先）では展開しない。コード側の縁を辿るのは本命の walk だけにさせる
      if (offer(state) && (byId.get(to) || {}).kind === 'resource') queue.push(state);
    }
  }
  return wiringMap;
}
function mergeWiring() {
  for (const [id, info] of wiringMap) {
    const cur = combined.get(id);
    if (!cur) combined.set(id, info);
    else promote(cur, info);
  }
}

// closure が `handler` でコード側のメンバーに届いたら、**そこからも歩き直す**。
// ここで止めると「API 起点 → Lambda → handler → その Lambda が書くテーブル」の最後の一歩が落ちて、
// レビューで一番知りたい着地が全欄から消えた（注釈で `writes` を付けていても出なかった）。
// 2 段目を繰り返すのは**その往復で新しく届いた本命のコードだけ**を起点にするためで、
// 既に歩いたコードを段数 0 から歩き直すと `--hops` が実質 2 倍になる（実測: `calls` だけの
// 列で `--hops 2` が 4 辺先まで届いた）。段数・向き・向き変えの回数は**前の記録から引き継ぐ**
mergeRecords(walkWithSwitch(startIds, 'in'));
const walkedCode = new Set();
let closureSeeds = [...combined.keys()];
for (let round = 0; round < MAX_ROUNDS; round++) {
  runClosure(closureSeeds);
  mergeWiring();
  const codeSeeds = [...wiringMap.keys()].filter((id) => {
    const k = (byId.get(id) || {}).kind;
    const rec = combined.get(id);
    return (k === 'member' || k === 'type') && rec && !rec.wiring && !walkedCode.has(id);
  });
  // 本命として届いた endpoint が属する API を覚えておく（次の往復からその API の定義も伝播できる）
  for (const [id, rec] of combined) if (!rec.wiring) {
    const g = apiGroupOf(byId.get(id));
    if (g !== null && g !== undefined) touchedApiGroups.add(g);
  }
  if (!codeSeeds.length) break;
  for (const id of codeSeeds) walkedCode.add(id);
  const found = walkWithSwitch(codeSeeds, 'out');
  mergeRecords(found);
  closureSeeds = [...found.keys()];
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
// 「起点の中にあるノードは着地に数えない」の判定対象は **ファイルとプロジェクトだけ**。
// `folder:.` を起点にするとその下に全部が入るので、判定を適用すると全ノードが消えて
// 起点だけ出して着地 0 件になる（`--folder-start` の既定の落ち込みがこれ）
const insideContainers = new Set(startIds.filter((id) => {
  const k = (byId.get(id) || {}).kind;
  return k === 'file' || k === 'project';
}));
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
// 動きの縁の**矢印の先が下流**。`exposed-by` は矢印が逆（コード → 公開するもの）なので
// 矢印の元側が下流になる
const directionOf = (id, info) => {
  // (1) 起点がエンドポイントで、その**実装側**に入っている → そこから先は全部 影響する先
  // (2) 動きの縁（`triggers` / `invokes` / `handler` / `exposed-by`）で届いた → 矢印の先が下流
  //     同じノードへ至る動きの縁が別の経路にもあれば、そちらを `movementEvidence` として出す
  // (3) それ以外（定義・静的解析の縁） → 実際に辿った向き
  if (info.down) return 'out';
  const e = MOVEMENT.has(info.edge.kind) ? info.edge : (info.movementEvidence || null);
  if (!e) return info.dir;
  return arrowAt(e, id) ? 'out' : 'in';
};
for (const [id, info] of combined) {
  if (!info.edge || insideStart(id)) continue;
  const p = pathOf(id);
  rows.push({
    // 向きは (1) 起点がエンドポイントで実装側に入っている → すべて 影響する先
    // (2) 動きの縁が分かっていれば、その矢印の先が下流 (3) それ以外は辿った向き
    direction: info.down ? 'out' : directionOf(id, info),
    id, name: label(id), kind: byId.get(id).kind, category: category(id),
    resourceType: (byId.get(id).metadata || {}).resourceType || null,
    endpoint: endpointOf(byId.get(id)),
    // 表示する段数は**経路の長さ**。探索側が持つ段数は「定義単位をまたいだ数」で、
    // 動きの縁を越えたら数え直す予算なので、そのまま出すと `path` と食い違った
    // （実測: demo の `--api` で 1 行が 8 段 / 経路 6 ノード）
    hops: p.length - 1, switches: info.switches, correspondence: !!info.corr,
    // 動きの縁（`triggers` / `invokes` / `handler`）が別の経路で見つかっていれば、
    // 定義を辿っただけの縁が先着していても本命にする。その縁は `movementEvidence` として
    // 残す（表示の根拠は最初に辿れた縁のままにして、経路と食い違わないようにする）
    movementEvidence: info.movementEvidence || null,
    tier: info.wiring === true ? 'wiring'
      : (info.edge.kind === 'references' && info.edge.provenance === 'terraform' && !info.movementEvidence) ? 'wiring' : 'primary',
    // 起点が API エンドポイントのとき、method / resource / rest_api / integration / deployment は
    // **起点となる API 自身を定義している**ので「影響を受ける外部リソース」に数えない
    sameApi: startIsEndpoint && !endpointOf(byId.get(id)) && startApiGroups.has(apiGroupOf(byId.get(id))),
    calledOut: !!info.calledOut, evidence: info.edge, path: p,
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
const isSiblingEndpoint = (r) => startIsEndpoint && !!r.endpoint && !startSet.has(r.id) && !r.calledOut;
// 兄弟エンドポイント**そのもの**だけでなく、その API を定義している resource / rest_api /
// integration も同じ欄に出す。`external.in` に並べると「別 API から自分の API へ流入して
// いる」と読めてしまう（同じ Lambda を共有しているだけの関係なので）
const siblingGroups = new Set();
if (startIsEndpoint) {
  for (const r of rows) {
    if (!isSiblingEndpoint(r)) continue;
    const g = apiGroupOf(byId.get(r.id));
    // 起点と同じ rest_api を共有する別メソッド（`GET /orders` など）を「別 API」として
    // 扱わない。その定義まで起点自身の欄から引っ越してしまう
    if (g === null || g === undefined || startApiGroups.has(g)) continue;
    siblingGroups.add(g);
  }
}
const siblingGroupOf = (r) => {
  if (!startIsEndpoint || !siblingGroups.size) return null;
  const g = apiGroupOf(byId.get(r.id));
  return g !== null && g !== undefined && siblingGroups.has(g) ? g : null;
};
const isSibling = (r) => isSiblingEndpoint(r) || !!siblingGroupOf(r);
// 定義上の関連 = 他の枠（本命の外部リソース / コードの入口 / 同じ API の定義 / 兄弟）に
// 入らなかった行の引き取り手。ここに条件を足し忘れると行がどこにも出なくなるので、
// 「本命として列挙した行」だけを明示的に除外する形にする
const listedElsewhere = (r) => r.tier === 'primary' && !r.sameApi && !isSibling(r)
  && (isExternal(r.id) || r.kind === 'member' || r.kind === 'type');
// リポジトリ内の**成果物**（プロジェクト・ファイル・フォルダ・solution）。外部リソースでも
// コードの入口でもないので「定義上の関連」に混ぜない。混ぜると csproj が本命なのに
// 「変更で値が動かなくても見直しの候補」と書かれた欄に並ぶ（双人レビュー P2）
const ARTIFACT_KINDS = new Set(['project', 'file', 'folder', 'solution']);
const isArtifact = (r) => ARTIFACT_KINDS.has(r.kind);
const artifactRows = (rs) => rs.filter((r) => !isApiDefinition(r) && !isSibling(r) && !listedElsewhere(r) && isArtifact(r));
const wiringRows = () => rows.filter((r) => !isApiDefinition(r) && !isSibling(r) && !listedElsewhere(r) && !isArtifact(r));
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
const startEndpoints = endpointsOf([...startSet].filter((id) => directStartIds.has(id) && endpointOf(byId.get(id))));
const reachedEndpoints = endpointsOf([...combined.keys()].filter((id) => endpointOf(byId.get(id)) && !startSet.has(id)));
const annotationRows = rows.filter((r) => r.evidence.provenance === 'llm' || r.evidence.provenance === 'human');
const summary = {
  graph: resolve(opts.graph), starts: starts.length, expandedStarts: startIds.length,
  fallbacks: fallbacks.length, hops: opts.hops, wiringHops: opts.wiringHops,
  primaryIn: externalRows(inRows).length, primaryOut: externalRows(outRows).length,
  entryIn: entryRows(inRows).length, entryOut: entryRows(outRows).length,
  artifactsIn: artifactRows(inRows).length, artifactsOut: artifactRows(outRows).length,
  wiring: wiringRows().length, sameApi: sameApiRows().length, siblings: siblingRows().length,
  secondOrder: rows.filter((r) => r.switches === 1).length,
  // 総行数。各欄（外部 / 入口 / 成果物 / 定義上 / 同じ API / 兄弟）の合計と必ず同じになる。
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
  artifacts: { in: artifactRows(inRows).slice(0, opts.limit), out: artifactRows(outRows).slice(0, opts.limit) },
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
  const body = rs.slice(0, limit).map((r) => {
    // 経路の根拠（最初に辿れた縁）と、本命にした**動きの縁**を両方出す。後者だけを見て
    // 「経路に無い縁を根拠にしている」とは読ませない
    const mv = r.movementEvidence
      ? ` <br>動きの根拠: \`${r.movementEvidence.kind}\`（${provLabel(r.movementEvidence.provenance)}）`
      : '';
    return `| ${r.name} | ${r.category} | ${r.hops} | \`${r.evidence.kind}\` ${r.evidence.source.split(':').pop()} → ${r.evidence.target.split(':').pop()}${mv} | ${provLabel(r.evidence.provenance)}${r.correspondence ? '（対応）' : ''} |`;
  }).join('\n');
  const more = rs.length > limit ? `\n\n（他 ${rs.length - limit} 件は --json 参照）` : '';
  return head + body + '\n' + more + '\n\n';
}
const epLine = (e) => `- \`${e.name}\`（\`${e.id}\`）`;
let md = `# 影響範囲レポート\n\n- グラフ: \`${summary.graph}\`\n- 起点 ${summary.starts} 件（展開後 ${summary.expandedStarts} 件、グラフに無く起点にしなかった変更 ${summary.fallbacks} 件）\n- 探索 ${summary.hops} ホップ（方向の切り替え 1 回まで許可、二段到達 ${summary.secondOrder} 件）/ Terraform の定義単位は ${summary.wiringHops} 段まで無方向で閉じる / 階層（parent・contains）は起点の展開にのみ使用\n- 本命: 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コードの入口 先 ${summary.entryOut}・受 ${summary.entryIn} / 成果物 ${summary.artifactsOut}・受 ${summary.artifactsIn} / 定義上の関連 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 同じコードを使う別エンドポイント ${summary.siblings}\n- 根拠の由来: ${Object.entries(summary.byProvenance).map(([k, v]) => `${provLabel(k)} ${v}`).join(' / ') || 'なし'}（**注釈由来 ${summary.annotationRows} 件**は静的解析では決まらない対応付け）\n\n`;
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
md += mdSection('影響を受けるリポジトリ内の成果物（プロジェクト・ファイル。ビルドし直しが必要な範囲）',
  [...artifactRows(outRows), ...artifactRows(inRows)], opts.limit);
md += mdSection('定義上の関連（Terraform の定義を辿っただけ。動きが伝わるとは限らない）', wiringRows(), opts.limit);
if (opts.md) writeFileSync(resolve(opts.md), md);

console.log(`API エンドポイント: ${[...startEndpoints, ...reachedEndpoints].map((e) => e.name).join(', ') || '該当なし'}`);
console.log(`起点 ${summary.starts} 件（展開後 ${summary.expandedStarts}）/ 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コードの入口 先 ${summary.entryOut}・受 ${summary.entryIn} / 成果物 ${summary.artifactsOut + summary.artifactsIn} / 定義上 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 兄弟エンドポイント ${summary.siblings} / 注釈由来 ${summary.annotationRows}`);
if (result.score) console.log(`精度: 再現率 ${result.score.recall} / 適合率 ${result.score.precision}（期待 ${result.score.expected} / 外部着地 ${result.score.landedExternal} / 的中 ${result.score.hitExternal} / 余分 ${result.score.extraExternal.length}）`);
for (const r of externalRows(outRows).slice(0, 12)) console.log(`  [out ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
for (const r of externalRows(inRows).slice(0, 12)) console.log(`  [in  ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
