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
const wiringMap = new Map();
// 閉包の出発点として**根になったノード**（起点そのものではないが、起点の定義グループなので
// 経路の先頭として出してよい）。

// 根拠経路の祖先 lookup。合并前の一時的な記録（`found` / `wiringMap`）も祖先として見る。
// そこを見落とすと 1 回の閉包の中で互いを指す 2 件の記録ができて `via` が循環した
// （実測: 注釈なし fixture の `POST /orders` で lambda_function.orders_api ⇄
// api_gateway_integration.post_order、実プロジェクトで 9 行中 5 行）
const recOf = (id, extra) => (extra && extra.get(id)) || combined.get(id) || wiringMap.get(id);
const onChain = (fromId, id, extra, cap = 64) => {
  let cur = recOf(fromId, extra);
  const seen = new Set();
  for (let i = 0; cur && i < cap; i += 1) {
    if (cur.id === id) return true;
    if (seen.has(cur.id)) return false;
    seen.add(cur.id);
    cur = cur.via ? recOf(cur.via, extra) : null;
  }
  return false;
};

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
      corr: false, down: false, reachedByInvokes: false,
    };
    // 経路の記録は循環境避で更新が見送られることがある。受けられた事実は `bestState` にあるので、
    // 閉包の種と同じ読み方をする（`down` を見落とすと、その先が 影響する先 ではなく
    // 影響を受ける入口 に行き着く）
    if (prev && !seed.down && bestState.get(id)?.down) seed = { ...seed, down: true };
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
          // 根拠経路を循環させる一歩は捨てない。ただしそこを**新しい出発点**として切る
          // （`via` を付けない）。付けたままにすると経路が起点にたどり着けなくなる
          const back = onChain(cur.id, to, found);
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
          const movement = MOVEMENT.has(e.kind);
          // 「実装側」の旗は動きの縁を渡っても引き継がない。矢印の先が次のノードでなければ
          // （= そこがこの経路を**呼び出している側**なら）別のもので、実装の一部ではない
          // （実測バグ: `Step Functions → invokes → この Lambda` が 影響する先 に反転した）
          const down = ((cur.down && !(movement && !arrowAt(e, to)))
            || (startIsEndpoint && d === 'in' && FLIP_INTO_IMPL.has(e.kind))) ? true : false;
          const rec = {
            id: to, mdir: d, down, switches,
            // 動きの縁は矢印で向きを決める（`exposed-by` は反転）。定義や注釈の縁は、
            // 実装側に入っているなら 影響する先、そうでなければ辿った向きをそのまま使う
            dir: movement ? (arrowAt(e, to) ? 'out' : 'in') : (down ? 'out' : d),
            // Terraform の `references` は「そのブロックを文中に書いた」だけで値が動かない。
            // walk で辿っても定義上の関連のままにする（実測: `admin_users` / `admin_api` が
            // 「動きの根拠: `references`」付きで本命に昇格した）
            wiring: e.kind === 'references' && e.provenance === 'terraform',
            hops: cur.hops + 1, via: back ? null : cur.id, cut: back, corr,
            // 「呼ばれて成立する」は**この一歩が `invokes` だった**こと。しかも矢印どおりに
            // 辿った一歩（呼ばれる側へ着いた一歩）だけ。経路に `invokes` が含まれるという判定に
            // すると、呼び出しの先で更に届いた無関係な別エンドポイント（同じ Lambda を使う
            // 兄弟）まで「呼びに出した先」に化けて兄弟欄から消えた。逆にたどった一歩
            // （呼び出し元へ着いた一歩）に立てるのも間違い
            reachedByInvokes: e.kind === 'invokes' && arrowAt(e, to),
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
//  - `reachedByInvokes`: 呼ばれる側へ着いた一歩で着いた（兄弟エンドポイントと区別する判定に使う）
//  - `movementEvidence` / `wiring = false`: 別の経路に**動きの縁**があった = 定義上ではなく本命
function promote(cur, rec) {
  // walk 側で分かった事実も同じ場所へ合流させる（行の本命判定と向きはここを見る）
  noteFacts(cur.id, {
    primary: rec.wiring !== true, elig: rec.wiring !== true,
    down: rec.down, reachedByInvokes: rec.reachedByInvokes, edge: rec.edge,
  });
  if (rec.reachedByInvokes) cur.reachedByInvokes = true;
  // 「起点のエンドポイントの実装の中にある」という事実は一方通行（後から強い方の情報に
  // なるだけ）なので、先着の記録がまだ実装側に入る前のものでも反転させる。
  // `Step Functions → invokes → notify` のような**手前を向く縁**で先に着地すると
  // 「影響を受ける入口」になり、同じノードが実装の一部だと分かっても戻らなかった
  if (rec.down) cur.down = true;
  // 昇格は**動きの縁か注釈の縁**で届いたときだけ。Terraform の `references` は
  // 定義を書いただけなので、それが別の経路で届いても本命にはしない
  // 循環境避のために切った経路より、ちゃんと根まで辿れる経路の方がマシ。後から来た方の
  // `via` を引き取って経路を伸ばす（表示する根拠の縁は最初のものまま）
  if (cur.cut && rec.via) {
    cur.via = rec.via || null;
    cur.cut = false;
  }
  const kind = rec.edge ? rec.edge.kind : null;
  const prov = rec.edge ? rec.edge.provenance : null;
  if (cur.wiring === true && rec.wiring !== true
    && (MOVEMENT.has(kind) || CORRESPONDENCE.has(prov))) {
    cur.wiring = false;
    if (MOVEMENT.has(kind)) cur.movementEvidence = rec.edge || cur.movementEvidence || null;
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
// 動きが伝わる縁。`exposed-by`（コードがこのエンドポイントを公開している）も動きの縁で、
// `ARROW_REVERSED` のどおり**コード側が下流**。コードを変更したときにそのエンドポイントを
// 「読み書きする先」でなく「このコードを呼び込む側（影響を受ける入口）」と読む
const MOVEMENT = new Set(['triggers', 'invokes', 'handler', 'exposed-by']);
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
//    integration / handler / その先にあるテーブルまで本命になることはない（双人レビュー P1）
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
const bestState = new Map();   // id -> { budget, primary, elig, down, reachedByInvokes, movementEvidence }
// **受理した事実（本命か / 動きの根拠 / 旗）はここ、経路（`via` と表示する縁）は記録側**に置く。
// 両方を記録に持たせていたため、経路を循環境避で切ったときに受理済みの本命情報まで捨てた
// （双人レビュー P1: タグ参照が 1 本増えただけで実際の `invokes` が定義上の関連へ落ちた）
// 閉包が「どの資格で展開したか」をここ別で持つ。事実（`bestState`）と同じ入れ物にすると、
// walk が後から事実を強くしたとき、その資格での展開をまだしていないのに `offer()` が
// 「改善なし」と判断して再展開を省いた（双人レビュー第 20 ラウンド P1: 定義参照が 1 本
// 増えただけで上流の Step Functions が 定義上の関連 に落ちた）
// 展開記録は `budgets` を `(elig, down)` の 4 通り（0..3）ごとに持つ。1 つの `budget` に
// 平坦に合併すると、積束で比較不能な 2 状態（`elig: false, budget: 1` と `elig: true, budget: 3`）が
// `{ elig: true, budget: 1 }` に化けて、一度も展開していない `(elig: true, budget: 2)` を
// 「展開済み」と誤判定した（双人レビュー第 22 ラウンドの最小反例 B）
const NO_BUDGETS = [Infinity, Infinity, Infinity, Infinity];
const expandedAt = new Map();   // id -> { primary, gen, budgets: [4] }
// `touchedApiGroups` が増えると、同じ資格の種でも子側の伝播資格 (`inTouchedApiGroup`) が変わる。
// 世代を持たないと「同じ資格だから展開済み」と却下されて、届いた API の定義が
// 定義上の関連 に残った（双人レビュー第 21 ラウンド P1、両名の反例）
let apiGen = 0;
function noteFacts(id, f) {
  const prev = bestState.get(id)
    || { primary: false, elig: false, down: false, reachedByInvokes: false, movementEvidence: null };
  const kind = f.edge ? f.edge.kind : null;
  bestState.set(id, {
    ...prev,
    primary: prev.primary || !!f.primary,
    elig: prev.elig || !!f.elig,
    down: prev.down || !!f.down,
    reachedByInvokes: prev.reachedByInvokes || !!f.reachedByInvokes,
    movementEvidence: prev.movementEvidence
      || f.movementEvidence || (MOVEMENT.has(kind) ? f.edge : null) || null,
  });
}
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
    // **受理した状態だけ**を記録に残して展開する。不受理の状態でも書き込むようにすると、
    // `via` が循環して `path[0]` が起点でなくなる行が出た（実測: 実プロジェクトの
    // `--api "POST /messages"` で 9 行中 5 行、`--from tf:aws_iam_role_policy.…` で全 15 行が
    // 2 ノードの循環）
    // 事実は一度立ったら消えない。弱い方の状態が後から来ても旗を戻さないよう、ここで合流させる
    noteFacts(state.id, {
      primary: state.primary, elig: state.elig, down: state.down, reachedByInvokes: state.reachedByInvokes,
      edge: state.rec ? state.rec.edge : null,
    });
    // 展開するのは (a) 今の世代ではまだ展開していない、(b) 初めて本命として展開する、
    // (c) 同じ `(elig, down)` の資格で前回より小さい予算で届いた、のいずれかのとき。
    // (c) は本命でなくても効く（定義上の関連にも `--wiring-hops` の予算は及ぶ）。第 22 ラウンドの
    // 最小反例では `references` で budget 2 のノードが、`invokes` を越えて budget 1 で届き直したとき
    // に却下され、その先 1 ノードがどの欄にも出なかった
    const done = expandedAt.get(state.id);
    const fresh = !done || done.gen !== apiGen;
    // 予算は非負整数で (c) ごとに厳密に減り、(a)(b) は高々 1 回、世代はグループ増でしか上がらない。
    // だから 1 ノードあたりの再展開は高々 `4 * (予算 + 1)` 回で有限に止まる
    const mask = (state.elig ? 2 : 0) | (state.down ? 1 : 0);
    const prevBudget = fresh ? Infinity : done.budgets[mask];
    const better = fresh || (state.primary && !done.primary) || state.budget < prevBudget;
    if (!better) return false;
    const budgets = fresh ? [...NO_BUDGETS] : [...done.budgets];
    budgets[mask] = Math.min(prevBudget, state.budget);
    // `elig` が立った資格は同じ予算の `elig` が立たない資格を支配する（拡げ方の結果が広いだけ）。
    // 支配された側も更新しておかないと、後から来た弱い資格の状態が再度展開される
    if (state.elig) {
      const weaker = mask & ~2;
      budgets[weaker] = Math.min(budgets[weaker], budgets[mask]);
    }
    expandedAt.set(state.id, { primary: !!state.primary || !!done?.primary, gen: apiGen, budgets });
    bestState.set(state.id, {
      ...bestState.get(state.id),
      budget: Math.min(bestState.get(state.id)?.budget ?? Infinity, state.budget),
    });
    if (state.rec) {
      const old = wiringMap.get(state.id);
      // 記録の置き換えをやめるのは 2 つの場合。
      // (1) 根が確定している経路を、循環境避で切った経路に置き換えるとき（`path[0]` が起点でなくなる）
      // (2) 本命として受理済みの行を、定義上の関連の縁で塗り替えようとするとき（根拠が弱い方に変わる）
      const demote = !!old && bestState.get(state.id).primary && state.rec.wiring === true;
      const shorter = !!old && !!old.via && state.rec.cut;
      if (!demote && !shorter) wiringMap.set(state.id, state.rec);
    }
    return true;
  };

  for (const id of new Set(seedIds)) {
    if (!byId.has(id)) continue;
    // 記録が無い出発点（起点と同じ API を定義しているノードなど）には、**そこを根にした記録**を作る。
    // `rec: null` のまま隣へ `via` だけを付けると、その `via` がどの記録も指さない宙ぶらりんになり、
    // 後から別の方向から到着した一歩がそこを親に選んで `via` が循環した
    // （実測: 注釈なし fixture の `POST /orders` で lambda ⇄ integration の 2 ノード循環）
    // 閉包の出発点は必ず walk の記録を持つ（`closureSeeds` は `combined` のキーから作る）。
    // 持たないときは組み立ての間違いなので音をたてる。以前はここに「定義の種」という枝を
    // 用意していたが、到達不能な上に説明コストだけかかった（双人レビュー第 20 ラウンド両名）
    let rec = combined.get(id);
    if (!rec) {
      process.stderr.write(`[report] 警告: 閉包の出発点 ${id} に walk の記録がありません\n`);
      rec = { id, edge: null, hops: 0, switches: 0, via: null, cut: true, dir: 'out', wiring: false };
    }
    // 経路の記録（`rec`）は循環境避で `wiring` のまま残ることがあるので、資格は受理事実を優先する
    const st = bestState.get(id);
    const primary = st ? st.primary : rec.wiring !== true;
    const state = {
      id, hops: rec.hops, budget: 0, down: st ? st.down : !!rec.down,
      reachedByInvokes: rec ? !!rec.reachedByInvokes : false,
      primary, elig: primary || inTouchedApiGroup(id),
      via: null, rec,
    };
    if (offer(state)) queue.push(state);
  }
  let guard = 0;
  while (queue.length && guard++ < MAX_CLOSURE_STEPS) {
    const cur = queue.shift();
    for (const { to, edge } of tfAdj.get(cur.id) || []) {
      // 段数の上限は「Terraform の定義単位をどこまで閉じるか」なので、予算を課すのは
      // `references`（定義を辿る縁）だけ。**動きの縁を越えたところでは数え直す**
      const back = onChain(cur.id, to, wiringMap);   // 循環させる一歩は出発点を切り直す
      const movement = MOVEMENT.has(edge.kind);
      const budget = movement ? 0 : cur.budget + 1;
      if (budget > opts.wiringHops) continue;
      // **伝播の資格**: 動きの縁を辿っても、辿ってきたノードが「起点 / 本命として届いたノード /
      // 起点と同じ API を定義しているノード」でなければ、その先は定義上の関連のままにする。
      // これを忘れると、IAM ロールだけを共有する別 Lambda 専用の integration や
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
        hops: cur.hops + 1, switches: 0, via: back ? null : cur.id, cut: back, wiring: !primary,
        down: !!cur.down && !(movement && !arrowAt(edge, to)),
        // `reachedByInvokes` は**この一歩が `invokes` だった**こと。しかも矢印どおりに辿った
        // 一歩（呼ばれる側へ着いた一歩）だけ。逆にたどった一歩（呼び出し元へ着いた一歩）に
        // 立てると「自分が呼んだ」と読める旗が上流に立った（双人レビュー第 20 ラウンド P2）
        reachedByInvokes: edge.kind === 'invokes' && arrowAt(edge, to),
        // 向きは「縁の向き × その行が矢印のどちら側か」。動きの縁なら矢印の先が下流。
        // `references`（定義）は向きに意味無いので辿ってきたノードの向きを継ぐ
        // 動きの縁は矢印の先が下流。`SFN → invokes → この Lambda` は SFN が上流なので
        // 影響を受ける入口（実測バグ: 「実装側に入った」旗を先に読んで 影響する先 に反転した）
        dir: movement ? (arrowAt(edge, to) ? 'out' : 'in')
          : cur.down ? 'out'
            : ((combined.get(cur.id) || {}).dir || (edge.target === cur.id ? 'in' : 'out')),
      };
      const state = {
        id: to, hops: rec.hops, budget, primary, elig, via: rec.via, rec,
        down: rec.down, reachedByInvokes: rec.reachedByInvokes,
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
// 本命として届いた endpoint が属する API を覚えておく（次の往復からその API の定義も伝播できる）
const refreshGroups = () => {
  const before = touchedApiGroups.size;
  for (const [id, rec] of combined) {
    const st = bestState.get(id);
    if (!(st ? st.primary : rec.wiring !== true)) continue;
    const g = apiGroupOf(byId.get(id));
    if (g !== null && g !== undefined) touchedApiGroups.add(g);
  }
  if (touchedApiGroups.size > before) { apiGen++; return true; }
  return false;
};
// API グループが増えるたびに 1 ラウンド使うので、グラフ中のグループ数ぶんは猶予する。
// 固定値で切って成功終了すると、増えた世代の仕事が黙って捨てることになる（第 22 ラウンドの
// 6 グループ反例）。上限に達して仕事が残ったときは `unresolved` として明示する
const apiGroupTotal = new Set([...byId.values()]
  .map((n) => apiGroupOf(n)).filter((g) => g !== null && g !== undefined)).size;
const maxRounds = MAX_ROUNDS + apiGroupTotal + 2;
let rounds = 0;
let unresolved = false;
let pending = true;
while (pending && rounds < maxRounds) {
  pending = false;
  runClosure(closureSeeds);
  mergeWiring();
  const codeSeeds = [...wiringMap.keys()].filter((id) => {
    const k = (byId.get(id) || {}).kind;
    const rec = combined.get(id);
    const st = bestState.get(id);
    // 本命かどうかは受理事実で判断する（経路の記録は循環境避で `wiring` のまま残ることがある）
    const primary = st ? st.primary : !!rec && rec.wiring !== true;
    return (k === 'member' || k === 'type') && primary && !walkedCode.has(id);
  });
  const groupGrew = refreshGroups();
  // コードの種が無くても、API グループが増えたなら仕事がある（新しいグループの下で定義を
  // 広げ直す）。どちらも無いときが終わり
  if (!codeSeeds.length && !groupGrew) break;
  pending = true;
  if (codeSeeds.length) {
    for (const id of codeSeeds) walkedCode.add(id);
    const found = walkWithSwitch(codeSeeds, 'out');
    mergeRecords(found);
    // walk で新しいエンドポイントに届いたなら、グループをその場で増やす。次ラウンドまで
    // まつと古いグループで 1 回空回しして、API の連鎖 1 段に 2 ラウンド使う
    refreshGroups();
  }
  // 種は受け-record の全ノード。直前の walk が触ったノードだけにすると、既に届いた
  // エンドポイントや同じ API の定義が再種まきされず、新しいグループの下で広げられない
  closureSeeds = [...combined.keys()];
}

// ---- 行を組み立てる ----
// 根拠経路を `via` を辿って組み立てる。止め所は 3 つで、どれで止まったかを行に書く：
// - `start` 起点（`via` 無し）まで辿れた。いちばん正直な経路
// - `second-stage` `via` が循環しそうな所で切った所から始まる経路。2 段階目
//   （昇格したコード側から歩き直す walk）は、その地点を新しい起点として扱うので正しい姿
// - `broken` `via` が別の記録を指しているのにその記録が無い。あってはならない
const pathOf = (id) => {
  const acc = []; let cur = combined.get(id);
  const guard = new Set();
  let cut = 'start';
  while (cur && cur.id && !guard.has(cur.id)) {
    acc.unshift(cur.id); guard.add(cur.id);
    if (!cur.via) { cut = cur.cut ? 'second-stage' : 'start'; break; }
    const nxt = combined.get(cur.via);
    if (!nxt) { cut = 'broken'; break; }
    if (guard.has(nxt.id)) { cut = 'second-stage'; break; }
    cur = nxt;
  }
  return { path: acc, root: cut };
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
const directionOf = (id, facts) => {
  // (1) 動きの縁（`triggers` / `invokes` / `handler` / `exposed-by`）で届いた → 矢印の先が下流。
  //     同じノードへ至る動きの縁が別の経路にもあれば、そちらを `movementEvidence` として出す
  // (2) 起点がエンドポイントで、その**実装側**に入っている → そこから先は全部 影響する先
  // (3) それ以外（定義・静的解析の縁） → 実際に辿った向き
  const e = MOVEMENT.has(facts.edge.kind) ? facts.edge : (facts.movementEvidence || null);
  if (e) {
    if (arrowAt(e, id)) return 'out';
    // `handler` / `exposed-by` は「実装の対応」を表す縁で、呼び出し元を示さない。起点が
    // API エンドポイントなら、その対応縁で繋がる側（実装を載せた Lambda など）も下流側。
    // ここを矢印だけで 影響を受ける入口 にすると、起点のエンドポイント自身の
    // 実装 Lambda が「呼びにくる側」に並んだ（実測: demo の `--api "POST /orders"` で
    // `orders_api` と `notify` が 影響を受ける入口 に移った）
    if (FLIP_INTO_IMPL.has(e.kind) && startIsEndpoint) return 'out';
    return 'in';
  }
  if (facts.down) return 'out';
  return facts.dir;
};
for (const [id, info] of combined) {
  if (!info.edge || insideStart(id)) continue;
  const { path: p, root } = pathOf(id);
  // 受理済みの事実（本命か / 動きの根拠 / 旗）は記録より強い。経路を循環境避で切った行は
  // 記録側だけが弱いままになるので、行は事実側を優先して読む
  const st = bestState.get(id);
  const facts = {
    ...info,
    down: !!(st ? st.down : info.down),
    reachedByInvokes: !!(st ? st.reachedByInvokes : info.reachedByInvokes),
    movementEvidence: (st && st.movementEvidence) || info.movementEvidence || null,
  };
  rows.push({
    // 向きは (1) 動きの縁の矢印の先が下流 (2) 実装側に入った旗 (3) 実際に辿った向き
    // （`down` を先に読むと `Step Functions → invokes → この Lambda` が 影響する先 に反転した）
    direction: directionOf(id, facts),
    id, name: label(id), kind: byId.get(id).kind, category: category(id),
    resourceType: (byId.get(id).metadata || {}).resourceType || null,
    endpoint: endpointOf(byId.get(id)),
    // 表示する段数は**経路の長さ**。探索側が持つ段数は「定義単位をまたいだ数」で、
    // 動きの縁を越えたら数え直す予算なので、そのまま出すと `path` と食い違った
    // （実測: demo の `--api` で 1 行が 8 段 / 経路 6 ノード）
    hops: p.length - 1, switches: info.switches, correspondence: !!info.corr,
    pathRoot: root, via: info.via || null,
    // 動きの縁（`triggers` / `invokes` / `handler`）が別の経路で見つかっていれば、
    // 定義を辿っただけの縁が先着していても本命にする。その縁は `movementEvidence` として
    // 残す（表示の根拠は最初に辿れた縁のままにして、経路と食い違わないようにする）
    movementEvidence: facts.movementEvidence || null,
    // 本命かどうかも受理済みの事実で決める（経路を切った行が定義上の関連に落ちないようにする）
    tier: (st ? st.primary : info.wiring !== true) ? 'primary' : 'wiring',
    // 起点が API エンドポイントのとき、method / resource / rest_api / integration / deployment は
    // **起点となる API 自身を定義している**ので「影響を受ける外部リソース」に数えない
    sameApi: startIsEndpoint && !endpointOf(byId.get(id)) && startApiGroups.has(apiGroupOf(byId.get(id))),
    reachedByInvokes: facts.reachedByInvokes, evidence: info.edge, path: p,
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
const isSiblingEndpoint = (r) => startIsEndpoint && !!r.endpoint && !startSet.has(r.id) && !r.reachedByInvokes;
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
  // コードから `invokes` したエンドポイントは兄弟ではなく 影響する先。同じ API に兄弟が
  // いるだけで兄弟欄へ引っ越すと、一番知りたい着地が消える
  if (r.reachedByInvokes) return null;
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
// JSON の一覧は `--limit` で切り詰める。だから「欄の合計 == 総行数」の不変条件は
// **カウンタ側**（`summary` の各欄）に対して見る。一覧が切れているときは
// `listTruncated` を true にして、切り詰めを隠さない
const overLimit = (n) => n > opts.limit;
const bucketCounts = [
  externalRows(outRows).length, externalRows(inRows).length,
  entryRows(outRows).length, entryRows(inRows).length,
  artifactRows(outRows).length, artifactRows(inRows).length,
  wiringRows().length, sameApiRows().length, siblingRows().length,
];
const summary = {
  graph: resolve(opts.graph), starts: starts.length, expandedStarts: startIds.length,
  limit: opts.limit, listTruncated: bucketCounts.some(overLimit),
  fallbacks: fallbacks.length, hops: opts.hops, wiringHops: opts.wiringHops,
  primaryIn: externalRows(inRows).length, primaryOut: externalRows(outRows).length,
  entryIn: entryRows(inRows).length, entryOut: entryRows(outRows).length,
  artifactsIn: artifactRows(inRows).length, artifactsOut: artifactRows(outRows).length,
  wiring: wiringRows().length, sameApi: sameApiRows().length, siblings: siblingRows().length,
  // 兄弟欄は「同じコードを使う別のエンドポイント」と、それを定義しているノード
  // （method / resource / rest_api など）を混ぜて数える。内訳を出さないと見出しと件数の
  // 対応が読めなかった（レビュー指摘）
  siblingEndpointsOnly: siblingRows().filter((r) => !!r.endpoint).length,
  siblingDefs: siblingRows().filter((r) => !r.endpoint).length,
  secondOrder: rows.filter((r) => r.switches === 1).length,
  // 総行数。各欄（外部 / 入口 / 成果物 / 定義上 / 同じ API / 兄弟）の合計と必ず同じになる。
  // 過去に「primary かつ sameApi の行がどの欄にも入らず消える」不具合があったので、
  // この 2 つが一致することを検査で固定する（JSON を渡して誰も生データを読まなくても確かめられる）
  rows: rows.length,
  // 探索ラウンドの実数と上限。`unresolved` が true のとき、上限に達して仕事が残った
  // （= 出ていない影響がある）。黙って切り詰めた結果を完全な結果として出さない
  rounds, maxRounds, unresolved,
  startIsEndpoint,
  startEndpoints, reachedEndpoints,
  // 展開後の**起点の ID**。各行の `path[0]` がここに含まれることが不変条件
  // （`via` が循環すると起点でないノードから始まる行が出る。JSON だけを渡して確かめられるように出す）
  startIds: startIds.slice(0, 50), startIdsTruncated: startIds.length > 50,
  pathsByRoot: (() => {
    const c = { start: 0, 'second-stage': 0, broken: 0 };
    for (const r of rows) c[r.pathRoot] = (c[r.pathRoot] || 0) + 1;
    return c;
  })(),
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
  // すべての欄を `--limit` で切る。切っていない欄があると「一覧の合計 != 総行数」になり、
  // 見ている人が切り詰めを判別できない（実測: `--limit 3` で entries.out が 99 件残った）。
  // カウンタ（`summary`）は常に切り詰め前の値
  external: { in: externalRows(inRows).slice(0, opts.limit), out: externalRows(outRows).slice(0, opts.limit) },
  entries: { in: entryRows(inRows).slice(0, opts.limit), out: entryRows(outRows).slice(0, opts.limit) },
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
let md = `# 影響範囲レポート\n\n- グラフ: \`${summary.graph}\`\n- 起点 ${summary.starts} 件（展開後 ${summary.expandedStarts} 件、グラフに無く起点にしなかった変更 ${summary.fallbacks} 件）\n- 探索 ${summary.hops} ホップ（方向の切り替え 1 回まで許可、二段到達 ${summary.secondOrder} 件）/ Terraform の定義単位は ${summary.wiringHops} 段まで無方向で閉じる / 階層（parent・contains）は起点の展開にのみ使用\n- 本命: 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コード 出口 ${summary.entryOut}・入口 ${summary.entryIn} / 成果物 先 ${summary.artifactsOut}・受 ${summary.artifactsIn} / 定義上の関連 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 同じコードを使う別の API ${summary.siblings}（エンドポイント ${summary.siblingEndpointsOnly}・定義ノード ${summary.siblingDefs}）\n- 根拠の由来: ${Object.entries(summary.byProvenance).map(([k, v]) => `${provLabel(k)} ${v}`).join(' / ') || 'なし'}（**注釈由来 ${summary.annotationRows} 件**は静的解析では決まらない対応付け）\n\n`;
if (result.score) {
  const s = result.score;
  md += `## 精度（期待一覧との突き合わせ）\n\n- ケース: ${s.case}（方向 ${s.direction}）\n- 期待 ${s.expected} 件 / 外部リソースへの着地 ${s.landedExternal} 件 / 的中 ${s.hitExternal} 件\n- **再現率 ${s.recall} / 適合率 ${s.precision}**\n- 取りこぼし: ${s.missed.map((x) => `\`${x}\``).join(', ') || 'なし'}\n- 余分な着地: ${s.extraExternal.map((x) => `\`${label(x)}\``).join(', ') || 'なし'}\n- 取りこぼしのうち到達はしていた（定義上の関連に回ったもの）: ${s.wiringOnly} 件\n${s.note ? `\n> ${s.note}\n` : ''}\n`;
}
if (fallbacks.length) {
  md += `## 起点にできなかった変更\n\nグラフに対応するノードが無く、**起点にはしていません**（親フォルダを起点にすると配下を巻き込んで誤検出が膨らむため）。`
    + `最も近い親: ${fallbacks.map((f) => `\`${f.path}\` → \`${f.used}\``).join('、') || 'なし'}\n\n`;
}
if (summary.unresolved) {
  // 切り詰めを隠さない。上限で切った結果を完全な結果として出さない
  md += `> **注意: 探索が収束していません**。探索 ${summary.rounds} ラウンドで上限 ${summary.maxRounds} に\n`
    + `仕事が残ったまま達しました。**影響が抜けている可能性があります**（起点を絞り込むか、hops と\n`
    + `wiring-hops を調整してください）。\n\n`;
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
md += mdSection('影響するコード側の出口（起点から届くメソッド・型）', entryRows(outRows).slice(0, opts.limit), opts.limit);
if (startIsEndpoint) md += mdSection('起点と同じ API を定義するノード（変更で値は動かないので見直しの候補）', sameApiRows(), opts.limit);
if (startIsEndpoint && siblingRows().length) {
  md += `### 同じコードを使う別の API（エンドポイント ${summary.siblingEndpointsOnly} 件と、それを定義するノード ${summary.siblingDefs} 件。起点の定義ではなく、共有しているコードを変えたときに一緒に見る）\n\n`
    + siblingRows().map((r) => `- \`${r.name}\`（\`${r.id}\`、距離 ${r.hops}、根拠 \`${r.evidence.kind}\`）`).join('\n') + '\n\n';
}
// 先（影響する側）と受（影響を受ける側）を 1 表に混ぜると、集計行の
// 「成果物 先 X・受 Y」と対応が読めなかった（レビュー指摘）。分けて出す
md += mdSection('影響するリポジトリ内の成果物（プロジェクト・ファイル。ビルドし直しが必要な範囲）',
  artifactRows(outRows), opts.limit);
md += mdSection('影響を受けるリポジトリ内の成果物（この変更を参照している側）',
  artifactRows(inRows), opts.limit);
md += mdSection('定義上の関連（Terraform の定義を辿っただけ。動きが伝わるとは限らない）', wiringRows(), opts.limit);
if (opts.md) writeFileSync(resolve(opts.md), md);

console.log(`API エンドポイント: ${[...startEndpoints, ...reachedEndpoints].map((e) => e.name).join(', ') || '該当なし'}`);
console.log(`起点 ${summary.starts} 件（展開後 ${summary.expandedStarts}）/ 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コード 出口 ${summary.entryOut}・入口 ${summary.entryIn} / 成果物 先 ${summary.artifactsOut}・受 ${summary.artifactsIn} / 定義上 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 別の API ${summary.siblings}（エンドポイント ${summary.siblingEndpointsOnly}・定義 ${summary.siblingDefs}） / 注釈由来 ${summary.annotationRows}`);
if (result.score) console.log(`精度: 再現率 ${result.score.recall} / 適合率 ${result.score.precision}（期待 ${result.score.expected} / 外部着地 ${result.score.landedExternal} / 的中 ${result.score.hitExternal} / 余分 ${result.score.extraExternal.length}）`);
for (const r of externalRows(outRows).slice(0, 12)) console.log(`  [out ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
for (const r of externalRows(inRows).slice(0, 12)) console.log(`  [in  ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
