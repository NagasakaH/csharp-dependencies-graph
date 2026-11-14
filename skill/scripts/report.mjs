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
  wiringHops: 3, includeData: false, folderStart: false, maxRounds: null,
  listSiblings: false,
};
const USAGE = `使い方: report.mjs --graph <graph.json> [--changed <変更ファイル一覧>] [--from <ノード id や名前>]
                [--api "POST /orders"] [--hops N] [--provenance static,terraform,llm,human]
                [--json <out>] [--md <out>] [--expect <期待一覧.json>] [--no-expand] [--folder-start]
                [--wiring-hops N] [--include-data] [--limit N] [--max-rounds N] [--list-siblings]

  --changed   1 行 1 パスの一覧ファイル。「-」で標準入力（git diff --name-only をそのまま渡せる）。
              パスは graph.json の node.path と同じ表記（リポジトリ根からの相対）。
  --api       API Gateway のメソッドとパスで起点を引く（"POST /orders"）。パスの末尾の / はどちらでもよい。
  --list-siblings 兄弟ルート（同じコードを使う別のエンドポイント）の**一覧**を出す。既定は件数だけの
              要約（一覧を変えても結果は同じだと分かっていても、数百本が画面を埋めて見直しの
              候補が見えなくなるため）。一覧を出すときの本数は --limit に従う。
  --expect    期待する着地の一覧（{"expect": [...], "direction": "in"|"out"|"none"|"both", "note": "..."}）。
              渡すと再現率・適合率を出して JSON にも書く。direction を書かなかった（= both）ときは
              向き を持つ行と none の行をまとめて数えるので、none の着地も取りこぼさない。
              none を書くと 向き を決める関係が無い行だけを選んで割る。
  向き（JSON の行の direction。値域は in / out / none）:
              in = 影響を受ける入口、out = 影響する先、none = **この表示経路に 向き を決める
              関係が無い**（Terraform の定義の縁だけを辿った行）。Markdown の一覧の 向き 列では「—」と書く。
              none は「そのノードに他の有向関係が存在しない」意味ではなく、動きの根拠が
              無いこと同義でもない（以前の有向縁から 向き を継承した行もある）。none の行は
              定義上の関連 / 同じ API の定義 / 同じコードを使う別の API の欄に並び、
              tier（本命の資格）はそのまま保つ。
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
  else if (a === '--max-rounds') opts.maxRounds = Number(next());
  else if (a === '--limit') opts.limit = Number(next());
  else if (a === '--no-expand') opts.noExpand = true;
  else if (a === '--folder-start') opts.folderStart = true;
  else if (a === '--include-data') opts.includeData = true;
  else if (a === '--list-siblings') opts.listSiblings = true;
  else if (a === '--help') { console.log(USAGE); process.exit(0); }
  else { console.error(`[report] 未対応の引数: ${a}\n${USAGE}`); process.exit(2); }
}
if (!opts.graph) { console.error(USAGE); process.exit(2); }
for (const [name, v] of [['--hops', opts.hops], ['--wiring-hops', opts.wiringHops],
  ['--limit', opts.limit], ['--max-rounds', opts.maxRounds]]) {
  // `--max-rounds` は未指定（null）が正しい既定。グラフ中のノード数から決めた値を使う
  if (v === null) continue;
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
  // walk の一歩が根拠に握るのは 5 項目だけの**表示用コピー**（`--json` の `evidence` の契約）。
  // 縁その物を隣エントリへ入れると `detail` / `line` / `count` / `metadata` まで `evidence` へ
  // 漏れて出力契約が変わる（実測 out/tmp-r43/edge-ref-diff.txt: demo-api の 27 行中 22 行の
  // keys が変わった）。だからと言って到着ごとに作ると walk の到着数ぶんの確保になる
  // （実測 elsa-folder で到着 157,300 件）。縁の実体を 1 個の表で共有しても表引きが到着ごとに
  // 効いて同じだけ遅い（第 43 ラウンドの切り分け A 0.736 秒 / B 1.101 秒。ゲート
  // out/tmp-r43/gate43g-repro.log）。縁は読み取り専用（`rec.edge` への書き込みは grep で 0 件）
  // なので、**隣エントリを作るこの場で 1 個だけ**作っておく。到着は自分の隣を 1 回読むだけで
  // 縁の表示コピーが揃う（確保も表引きも到着ごとには起きない）
  const view = { id: e.id, kind: e.kind, provenance: e.provenance, source: e.source, target: e.target };
  const push = (map, from, to) => {
    if (!map.has(from)) map.set(from, []);
    map.get(from).push({ e, to, corr, view });
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
// ---- 「route 宣言か」は HTTP の表示名とは別の軸 ----
// `endpointOf` は「`POST /orders` という表示名を持つか」で、`--api` で引けることと endpoint 欄に
// 出すことを決める。一方 `$default`（v2 の既定ルート）や WebSocket の `$connect` は表示名を
// 作らないが、Terraform 上は他の route と同じ route 宣言で `target` に委譲先を書く。だから
// **起点に選んだときの制限**（同じ API を参照する別ルートの Lambda を起点の実行に数えない）は
// 表示名の有無ではなく route 宣言かどうかで掛けないといけない。表示名で分類していたため
// `$default` だけが制限から外れ、`--from tf:aws_apigatewayv2_route.fallback` で別ルート用の
// `cancel_fn` と `Shop.Orders.Cancel` が 本命 になった（双人レビュー第 30 ラウンド指摘 B）
const isRouteStart = (node) => {
  const m = (node && node.metadata) || {};
  return !!m.endpoint || typeof m.route_key === 'string' || !!m.http_method;
};
// 「起点と同じ API を定義している」を **`rest_api_id` の参照先** で決める。
// `category === 'apigateway'` だけの条件だと、同じ Lambda を共有する**別 API** の
// rest_api / resource / deployment まで「起点と同じ API」に分類してしまう（実測で取り違え）。
// 群が決まらないもの（`aws_apigatewayv2_*` は `api_id` を採っていない）は推測せず、定義上の関連に残す
// 値**全体**が `aws_apigatewayv2_api.<name>`（`.id` 付き・`resource.` 付き・`\${...}` 1 個だけ）
// であるときだけ所属を決める。三項式や文字列混在の中で部分一致して群を決めるのは誤り
// （`rest_api_id` の `refAddressOf` は v1 の既存出力を守るためそのまま）
const strictRefAddress = (value, type) => {
  const v = String(value === undefined || value === null ? '' : value).trim();
  const quoted = /^"([\s\S]*)"$/.exec(v);
  const inner = (quoted ? quoted[1] : v).trim();
  const one = quoted ? /^\$\{\s*([^{}]+?)\s*\}$/.exec(inner) : null;
  const expr = one ? one[1].trim() : inner;
  const m = new RegExp(`^(?:resource\\.)?${type}\\.([a-zA-Z0-9_-]+)(?:\\[[^\\]]*\\])?(?:\\.[a-zA-Z0-9_-]+)*$`).exec(expr);
  return m ? `${type}.${m[1]}` : null;
};
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
  // HTTP API（`aws_apigatewayv2_*`）。本体の `aws_apigatewayv2_api` が群そのもの。
  // `route` / `integration` / `stage` / `deployment` は `api_id` が単一の参照のときだけ同じ群。
  // `api_id` が決まらないとき（`var` / `local` / 混合補間など）は推測せず群なし＝定義上の関連
  if (m.resourceType === 'aws_apigatewayv2_api') {
    const self = (m.terraformAddress || '').replace(/^module\.[^.]+\./, '');
    if (self) { apiGroupCache.set(node.id, self); return self; }
    apiGroupCache.set(node.id, null); return null;
  }
  const v2 = strictRefAddress(m.api_id, 'aws_apigatewayv2_api');
  if (v2) { apiGroupCache.set(node.id, v2); return v2; }
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
// 統合ノード（v1 / v2）。method との対応が決まっているかの判定と、対応未確定の理由を
// 行に立てる判定の両方で使う（第 29 ラウンドの裁定）
const INTEGRATION_TYPES = new Set(['aws_api_gateway_integration', 'aws_apigatewayv2_integration']);
const isIntegrationNode = (node) => !!node && INTEGRATION_TYPES.has(((node.metadata) || {}).resourceType || '');
// 統合が method / route と**対応が決まっている**か。入力のどこかに method（endpoint を持つノード）と
// 統合を結ぶ縁（`http_method` から出た `invokes` でも注釈でも method への直接参照でも）が
// 1 本でもあれば決まっていると見る。第 29 ラウンドの裁定で作らない橋渡し
// （「その API の下に method が 1 件しかない」での断定）に頼らない
const methodCorrKnown = new Set();
for (const e of graph.edges) {
  const a = byId.get(e.source); const b = byId.get(e.target);
  const isMethod = (n) => !!n && !!endpointOf(n);
  if ((isIntegrationNode(a) && isMethod(b)) || (isIntegrationNode(b) && isMethod(a))) {
    methodCorrKnown.add(e.source); methodCorrKnown.add(e.target);
  }
}
// ---- 「API の定義を越えて届いた」旗 ----
// 統合・method・route は **その API が実行したときに通る地点**。そこを越えて届いたノードは
// 「起点が呼びに出した先の実装の下流」なので、対応未確定で 定義上の関連 に落ちても
// コード側の 2 段目の walk の種にする。種にしないと `Handler.Handle` の先の `writes` が
// **行ごと消える**（双人レビュー第 30 ラウンド指摘 C。`touched-api-nocorr` の
// `--from tf:aws_lambda_function.a` で `ext:rds-table/orders` が全欄から消えた）。
// 立てないのは定義の縁だけで届いたノード（IAM ロールを共有するだけの別 Lambda など）なので、
// ポリシー起点が膨らまないという以前の意図はそのまま残る
const apiTailFrom = (node) => isIntegrationNode(node) || isRouteStart(node);
// 旗を立てるのは **起点の実装の連鎖にいるまま定義を越えた**一歩だけ。連鎖が既に
// 切れている（= 定義の縁で届いただけ）状態で定義ノードに着いても、そこからの一歩は
// 「起点が呼びに出した先の実装の下流」ではない。IAM ロールを共有するだけの別 Lambda の
// 統合を越えたところで、その Lambda の実装を起点の影には数えない
// （双人レビュー第 31 ラウンド。`apiTail` を連鎖の資格なしで立てたまま再展開を認めると、
// IAM ポリシー起点が 15 行 → 18 行に膨らんだ）
// `!back` も実測して保つ（双人レビュー第 33 ラウンド agy の注記への回答）。外すと循環の縁を
// 渡って旗が広がり、v1 基準の `demo-proj` で `get_order` の向きが out → in に動いた（差分 1 件。
// 第 35 ラウンド agy 指摘 3 を実測で確認: 基準の `wiring/out`（段数 3）が `wiring/in` へ移る）
const crossesApiTail = (cur, back) => !back && !!cur.chain && apiTailFrom(byId.get(cur.id));

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

// ---- 起点が「route（エンドポイント）」かどうか ----
// `--api "POST /orders"` や、変更した `.tf` に宣言された method のように、**起点そのものが
// route を宣言しているノード**のときだけ使うルールを分ける。表示名を持つ HTTP route に限らず
// `$default` / `$connect` もここに入る（上の `isRouteStart`。表示名で括ると `$default` だけが
// 別ルートを広げる制限から外れた）。一方、起点の展開で入ったファイルのメンバーや、
// `--folder-start` の受け皿のフォルダは起点そのものではないので数えない
// （実測: `folder:.` 起点で「起点にしたエンドポイント」が並んでいた）
const startSet = new Set(startIds);
const directStartIds = new Set(starts.filter((x) => x.exact).map((x) => x.id));
const startIsEndpoint = startIds.some((id) => directStartIds.has(id) && isRouteStart(byId.get(id)));
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
// **表示する代表経路**の候補集合。id -> 非支配の実経路 [{ mask, budget, rec }]。
// 展開側の枝刈り（`expandedAt` の予算表）とは**別物**で、この集合と `wiringMap` の中身は
// 表示の根拠を選ぶためだけに存在する。循環判定・`cut`・旗の決定・受理は展開中の実経路
// （キュー状態の `parent` 連鎖）だけで決まり、ここは読まない（第 37 ラウンド指摘 1。
// 仕様 out/loop/r38-decision.md）
const repCands = new Map();
// **代表の選び方は展開・循環・旗の決定に一切影響しない**（仕様 out/loop/r38-decision.md、
// 原則 4）。候補集合はこの 2 つの関数だけで形が決まる。
//  - `repDominates`: 支配。比較項目は `repCmp` の接頭辞（第 1〜6 項）とまったく同じで、
//    すべての項目で劣らず 1 つ以上でstrict に優れる候補が他を捨てる。**接頭辞で負けた候補は
//    最終タイブレークまで行けない**ので、支配で捨てられる候補が代表になることはなく、
//    集合の形も代表も加える順に依らない（第 37 ラウンド agy 指摘 3-1: 支配と到着順の
//    挿入ゲート（旧 `demote` / `shorter`）が同値でないと、`cut: true, apiTail` 付きと
//    `cut: false` の対決が到着順で割れた）
//  - `repCmp`: 全順序。到着順は入らない。旧 `demote`（定義上の関連を最後に）と
//    旧 `shorter`（根付きを先に）は挿入ゲートではなくこの順序の第 1・2 項として持つ。
//    旧ゲートはどちらか一方でも当たれば候補を止めていたので、実測で両立しない対
//    （根付きの定義上の関連 vs 途中で切れた実経路）が起きた。根が起点でない経路は
//    代表の土台に立たない方を先にした（第 37 ラウンドの v1 突合で `IAM ポリシー →
//    role → notify` の根付き経路が、根が `order_process` の経路に追い出された）
// 真の支配（`repCmp` の接頭辞を項目ごとに比べ、ひとつも劣らず 1 つ以上strict に良い）
const repDominates = (a, b) => {
  const wa = a.rec.wiring === true ? 1 : 0; const wb = b.rec.wiring === true ? 1 : 0;
  if (wa > wb) return false; const s1 = wa < wb;
  const ca = a.rec.cut ? 1 : 0; const cb = b.rec.cut ? 1 : 0;
  if (ca > cb) return false; const s2 = ca < cb;
  if (a.budget > b.budget) return false; const s3 = a.budget < b.budget;
  if (a.rec.hops > b.rec.hops) return false; const s4 = a.rec.hops < b.rec.hops;
  const ta = (a.mask & CLOSURE_API_TAIL) ? 0 : 1; const tb = (b.mask & CLOSURE_API_TAIL) ? 0 : 1;
  if (ta > tb) return false; const s5 = ta < tb;
  const cha = (a.mask & CLOSURE_CHAIN) ? 0 : 1; const chb = (b.mask & CLOSURE_CHAIN) ? 0 : 1;
  if (cha > chb) return false; const s6 = cha < chb;
  return s1 || s2 || s3 || s4 || s5 || s6;
};
// **代表経路の全順序**。並べた順に比較し、差が出たところで切る:
//  1. 昇格を止められていない経路（`wiring !== true`）を先に（旧 `promoteTo` / `demote` の意図。
//     定義上の関連の記録が本命の記録を塗り替えない）
//  2. 根付き（`cut === false`）を先に（旧 `shorter` / `recoverCut` の意図。根が起点でない
//     経路を代表にしない）
//  3. 定義段数 `budget` が小さい順（近い実経路を先に。双人レビュー（agy）が提案した
//     「予算 → 段数」の順序をそのまま採用）
//  4. 記録段数 `rec.hops` が小さい順（同じ資格なら短い経路が読める）
//  5. `apiTail` 旗（API の定義を越えて届いた）を持つ経路を先に（旧 `carryTail` の意図。
//     着地まで運んだ経路が代表になれないと 2 段目の種が育たない系列が最優先）
//  6. `chain` 旗（起点の実装関係で結ばれた連鎖）を持つ経路を先に
//  7. 根拠の縁 id → 親 id (`via`) の辞書順（最終タイブレーク。向きは選考基準でなく
//     経路の結果なのでここでの介入はない）
// 旧 `repCmp` の第 3 項（`demote` の `dma`/`dmb`）は同一ノードの候補同士では第 1 項が
// 同値なら必ず同値になる不死の比較だったので削除した（第 37 ラウンド agy 指摘 3-3）
// 接頭辞の 6 項目は表示の確定（`coreCmp`）でもそのまま使うので関数に分けた
const coreCmp = (a, b) => {
  const wa = a.rec.wiring === true ? 1 : 0; const wb = b.rec.wiring === true ? 1 : 0;
  if (wa !== wb) return wa - wb;
  const ca = a.rec.cut ? 1 : 0; const cb = b.rec.cut ? 1 : 0;
  if (ca !== cb) return ca - cb;
  if (a.budget !== b.budget) return a.budget - b.budget;
  if (a.rec.hops !== b.rec.hops) return a.rec.hops - b.rec.hops;
  const ta = (a.mask & CLOSURE_API_TAIL) ? 0 : 1; const tb = (b.mask & CLOSURE_API_TAIL) ? 0 : 1;
  if (ta !== tb) return ta - tb;
  const cha = (a.mask & CLOSURE_CHAIN) ? 0 : 1; const chb = (b.mask & CLOSURE_CHAIN) ? 0 : 1;
  if (cha !== chb) return cha - chb;
  return 0;
};
const repCmp = (a, b) => {
  const d = coreCmp(a, b);
  if (d !== 0) return d;
  const ka = `${a.rec.edge ? a.rec.edge.id : ''}\u0000${a.rec.via || ''}`;
  const kb = `${b.rec.edge ? b.rec.edge.id : ''}\u0000${b.rec.via || ''}`;
  return ka < kb ? -1 : (ka > kb ? 1 : 0);
};
// 候補集合へ 1 経路加える。除くのは**同一親（同じ `via`）の候補から見て真に支配されている
// 既存候補**だけ。第 40 ラウンドまで異親の候補同士も支配し合っていたが、表示経路を
// 「親が確定済みの候補だけ」で選び直す方式（仕様 out/loop/r40-decision.md）では、支配した
// 候補の親が未確定のときに支配された候補で選び直す必要があり、捨てると経路が作れない。
// 同一親に限定しても探索中の代表は変わらない（候補集合が上位集合になり、捨てられていた
// 候補は常に旧集合に残る支配候補を持つので `repCmp` の最小にはなれない）。代表は常に
// `repCmp` の最小なので、加える順に依らず集合と代表は同じになる。
// 保存は親ごとのグループ分け（`groups`）。到着ごとの支配判定は同一親グループ内だけ見れば
// よく、総当たりだと候補の多いノード（共有 IAM ロールなど）で届いた件数の二乗のコストに
// なる（第 40 ラウンド実測: 全リストスキャンで `v2-big` が 0.10 秒 → 0.18 秒）。`repCmp`
// 最小（`best`）は増分で保つ — 追加時に古い代表を消したなら新人がそれを支配したので新人が
// 最小、何も消さなければ古い代表と新人の小さいほう、不追加なら不変。だから全集合の再計算と
// 同じ結果になる（支配は推移的、`repDominates` は `repCmp` の接頭辞で勝つ）
const addRepCandidate = (id, mask, budget, rec) => {
  // `rec` はコピーしない。呼び出し側が隣ループで作り立てのリテラルか、種の時点の
  // コピー（`combined` の walk 記録は `promote` が後から変更するので実体を渡さない。
  // 双人レビュー第 37 ラウンド agy 指摘 3-2）なので、候補は加わった時点の経路の事実を
  // そのまま見る
  const cand = { id, mask, budget, rec };
  let entry = repCands.get(id);
  if (!entry) {
    entry = { groups: new Map(), best: null };
    repCands.set(id, entry);
  }
  const key = rec.via || '';
  const group = entry.groups.get(key);
  let added = false;
  if (!group) {
    entry.groups.set(key, [cand]);
    added = true;
  } else {
    const kept = group.filter((c) => !repDominates(cand, c));
    const removed = kept.length !== group.length;
    if (removed && entry.best && kept.indexOf(entry.best) < 0) {
      // 古い代表が新人に消された。新人はそれを支配するので全集合の最小（支配は推移的で、
      // `repDominates` は `repCmp` の接頭辞 6 項目で一つも劣らず 1 つ以上 strict に良い）
      entry.best = cand;
    }
    if (!kept.some((c) => repDominates(c, cand))) {
      kept.push(cand);
      added = true;
    }
    if (kept.length) entry.groups.set(key, kept); else entry.groups.delete(key);
  }
  if (added && (!entry.best || repCmp(cand, entry.best) < 0)) entry.best = cand;
  // 候補の実体をそのまま渡さない。`mergeWiring → promote` が `combined` 側を後から変更するとき、
  // `wiringMap` を経由して候補（`repCands`）と実体を共有していると比較の材料が書き換わる
  // （双人レビュー第 38 ラウンド agy 指摘 P2 / codex 指摘 P2。実測 `fixture-api` で候補 4 件の
  // `wiring` が書き換わった。検査 out/tmp-review38/check-mutation.py）
  wiringMap.set(id, { ...entry.best.rec });
};
// ---- walk の到着も表示候補として数える（仕様 out/loop/r41-decision.md）----
// 第 40 ラウンドまで候補集合（`repCands`）へ乗っていたのは**閉包の到着だけ**だった。walk は
// `found` の**先着**で `via` / 根拠の縁 / 段数 を決めていたため、同じ資格の別経路が後から
// 届いても表示は縁の並び順で決まった（実測 `out/tmp-r41/wobble-before.txt`: `r34-fixture` /
// `demo-order` / `fixture-api` の 3 件が段数・根拠込みで 2 通り）。閉包でやったのと同じ
// 「到着順を代表選びに使わない」を walk へも及ぼす。
// ここは表示のためだけの集合で、探索（`found` の受理・展開・循環カット・旗・`bestState`）は
// ここを一切読まない（第 38 ラウンド不変原則 4 のまま。受理表・予算・支配の意味も不変）。
// 閉包の候補と同じ `repCands` へは入れない — `addRepCandidate` は `wiringMap` にも書き、
// `wiringMap` は循環判定（`recOf`）が読むので、walk の候補を混ぜると探索そのものが変わる
const walkCands = new Map();
// 根拠の縁の同一性は **縁 id** で見る（第 43 ラウンド指摘 1）。到着ごとに作った `edge`
// オブジェクトの実体比較だと、同じ (親, 縁) の一歩が 1 件も突き合わず、候補がまるごと
// 2 倍に水増しされた（実測 elsa-folder: 到着 157,300 / (via, 縁 id) の一意集合 78,650、
// 候補 2 件以上のノード 3,935 件。検査 out/tmp-r43/dedup-count.py）
const edgeIdOf = (e) => (e ? e.id : '');
// 保存は (親 `via`, 根拠の縁 id) ごとの 1 件だけの**並び**。同じ親・同じ縁の一歩は `via` と根拠が
// 同一で、表示と選考が見る残りの項目（段数・昇格資格・切り旗・2 つの旗）は `repCmp` で
// 比べるので、それだけ違う到着は表示に差が出ない（同一視できる到着を数え直さないための
// 絞り込みで、選考の基準は変えない。向き変え回数はここで凍結せず確定の段で数え直す）
const addWalkCandidate = (id, rec, cur) => {
  // **循環境避で切った一歩（`cut`）も、表示候補では実際の一歩として数える**。`back` は walk が
  // `found` の先着で作った連鎖を見て立つので縁の並び順で変わり、それを候補のままにすると
  // 候補集合そのものが並び順で変わった（実測 `out/tmp-r41/pool-dump.py`: `r34-fixture` の
  // `tf:aws_api_gateway_integration.i` にTrial 3 だけ `via=member:C` の候補が現れる）。
  // 表示を循環させない保証はここではなく確定の段で持つ — `settlePool` は「親が確定済みの
  // 候補だけ」を選ぶので、親がまだ未確定の時点で自分に指す候補は選されない。
  // `apiTail` は `crossesApiTail` が `back` を見るので、切っていない一歩として数え直す
  const src = rec.cut
    ? { ...rec, via: cur.id, cut: false, apiTail: !!cur.apiTail || crossesApiTail(cur, false) }
    : rec;
  const mask = (src.chain ? CLOSURE_CHAIN : 0) | (src.apiTail ? CLOSURE_API_TAIL : 0);
  // walk の一歩は Terraform の定義段数を数えないので `budget` は 0。walk の候補は同じノードの
  // 閉包の候補と同じ集合で比べない（walk が根付かせた行は walk の候補から選び、walk が
  // 根付かせられなかった行だけ第 40 ラウンドどおり閉包の候補から選ぶ）ので、`repCmp` の
  // 第 3 項は walk の中では常に同値になる
  // 候補は到着の記録を**そのまま**握る。到着の記録が後から書き換わらない保証は候補の側では
  // 持たず、`combined` へ入れる側が写しで持つ（下の `mergeRecords`）。`promote` が書き換えるの
  // は `combined` の実体だけなので、到着の記録＝候補の実体は不変のまま共有できる。到着ごとに
  // 実体を 2 個作る必要はなく、実測 elsa-folder で候補 78,650 件・新設 21,455 件ぶん（第 38
  // ラウンド agy 指摘 P2 の意味はそのまま。検査 out/tmp-review38/check-mutation.py）
  const list = walkCands.get(id);
  if (!list) { walkCands.set(id, [{ id, mask, budget: 0, rec: src }]); return; }
  // 同じ (親, 縁) の一歩は表示も選考も見るところが同じで 1 件で足りる。キーの文字列を
  // 組み直すより先に並びを調べて、同じ一歩の実体コピーを作らない（実測 elsa-folder で
  // 到着 157,300 件のうち同じ一歩の再到着が 78,650 件。表示候補のためだけに実体を
  // 倍作って実行時間が 0.1 秒伸びた）。根拠の縁は隣エントリが 1 個だけ持つ表示用コピーなので、
  // 同じ縁なら実体も一致する（実体が違えば `id` を比べる。`id` が同じなら表示も選考も同じ）
  for (const best of list) {
    if (best.rec.via !== src.via) continue;
    if (best.rec.edge !== src.edge && edgeIdOf(best.rec.edge) !== edgeIdOf(src.edge)) continue;
    // 同じ親・同じ縁の一歩なので `repCmp` の最終項目は同値。選考が見る残り（昇格資格・
    // 切り旗・定義段数・段数・2 つの旗）も同じなら、表示に出る項目も同じで 1 件で足りる
    // （実測: elsa-folder / demo / fixture-api / real-api の同じ (親, 縁) の到着どうしで
    // 違うのは `hops` だけで、他は `dir` / `down` / 旗まで一致。
    // out/tmp-r43/dbg2.mjs）。`hops` が違う対は `repCmp` の第 4 項で短い方が残り、
    // 残った側の `switches` は比較の材料にしない（確定の段で親の確定済み連鎖から数え直す）
    const sameCore = best.rec.hops === src.hops && best.rec.cut === src.cut
      && (best.rec.wiring === true) === (src.wiring === true)
      && !!best.rec.apiTail === !!src.apiTail && !!best.rec.chain === !!src.chain;
    const d = sameCore ? 0 : repCmp({ id, mask, budget: 0, rec: src }, best);
    if (d < 0) { best.rec = src; best.mask = mask; }
    return;
  }
  list.push({ id, mask, budget: 0, rec: src });
};
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
// 閉包の循環境避は `runClosure` の中の `fillPath` / `pathHas` を見る。表示の代表を選ぶ途中で
// 書き換わる `wiringMap` を循環判定に読むと「代表の選び方」が循環判定 → `cut` / `apiTail` →
// 候補の合否へ逆流し、候補集合そのものが縁の到着順で変わった（双人レビュー第 37 ラウンド
// 指摘 1、両名。再現 out/tmp-r38/path-counter.json: `s → x1 → target` の 2 段実経路が、`b` の
// 代表に選ばれた `s → x1 → target → b` の経路に `target` が居たせいで循環と誤判定され、
// 候補から落ちた）

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
  // ---- 展開の受理は「支配判定」で決める ----
  // 以前は `found.has(to)` の**ノード id だけの先着**で打ち切っていた。そのため
  // `chain: false`（`calls` を逆向きに渡る一歩など）が先に着くと、後から届いた
  // `chain: true` の正規の連鎖が同じノードで捨てられ、その先まで 定義上の関連 に落ちていた
  // （双人レビュー第 30 ラウンド指摘 D、両名実測。`Handler.A → M1 → X` に対して
  // `Caller.C → X` の逆向き一歩が先着すると `X` がいつまでも wiring のままだった）。
  // 閉包側（runClosure）はすでに `(chain, elig, down, apiTail)` の 16 枠 + 予算で支配判定をしている。
  // walk も同じ形にするが、枠は下の 6 つ + 向き（下記）で、旗が立つほど広い（= 上の枠が下を支配する）。
  // 旗は `mergeFlags` で単調に立つだけなので、1 ノードあたりの再展開は高々 64 枠ぶん有限回
  const WALK_CHAIN = 1;        // 起点の実装関係で結ばれた連鎖
  const WALK_DOWN = 2;         // 実装側（この先は 影響する先）
  const WALK_INVOKES = 4;      // 起点が呼びに出した一歩で着いた
  const WALK_PROMOTABLE = 8;   // 昇格を止められていない（`wiring` でない）
  const WALK_UNBLOCKED = 16;   // 兄弟エンドポイントからの外出ではない
  const WALK_IN = 32;          // このノードから `in` 側を辿れる
  const WALK_OUT = 64;         // このノードから `out` 側を辿れる
  const WALK_API_TAIL = 128;   // この経路が API の定義（統合・method・route）を越えて届いた
  // 辿れる向きは「両方向」なら `in` と `out` の両方のビットを立てる。包含で支配判定をするので、
  // 両方向を辿れる枠は片方向だけの枠を自動的に支配する。
  // `apiTail` も枠に入れる（双人レビュー第 32 ラウンド agy 指摘の案 A）。前ラウンドまでは
  // 「旗は記録（`combined`）へ寄せれば足りる、walk は着いたノードをその場で展開し続けるので
  // 先まで届く」と外していた。が、それは旗を結んだ縁を walk も辿れる場合の話。
  // 旗を結ぶ一歩が注釈（`human` / `llm`）だと、閉包（`runClosure`）は `provenance: 'terraform'`
  // の縁しか辿らないので旗を中継できず、枠に入れないと着地ごと消える。実測
  // （`out/tmp-r33/agy-repro2.py`）: `u` への 2 経路のうち旗を立てる側が定義側の先着に負けて
  // 再展開されず、`u -> invokes(注釈) -> V.Entry` の先 `ext:rds-table/orders` が縁の並び順だけで
  // 消えた（`orig` 6 行 / `rev` 7 行）。
  // `apiTail` の項は **旗そのものではなく「連鎖に入ったまま API の定義ノードにいる」こと**でも
  // 立てる（双人レビュー第 33 ラウンド agy 指摘の案）。`apiTailFrom` のノードに `chain: true` が
  // あれば、その先の一歩は `crossesApiTail` で `apiTail: true` を受け事実に渡せるので、
  // `WALK_API_TAIL` **だけ**を理由にそのノードを再展開する必要がない。言い換えると定義ノードでは
  // `chain` を持った時点で旗の枠も埋まっており、`apiTail` だけを新たに立てる再展開は枠の上で
  // 初めから存在しない。これで v1 基準の実測（`--from tf:aws_api_gateway_method.post_order` の
  // `orders_path` / `rest_api.orders` が 向き in・hops 1・根拠 `references` のまま）は、実体 id
  // でも段数でもなく**枠の同値関係**で守られる（実測: 起点の枠が 121 → 249 に広がり、
  // `Order.Create --exposed-by--> post_order` の帰還の一歩は key 249 / hops 2 で支配される）。
  // 循環境避の一歩を `back` で止める限定ガード（「`back` × API の定義ノード」で再展開しない）は
  // 同じ条件を `back` で書き直したものだった。`back` は**先着経路の `via`** に依存するので、
  // 定義ノードへ後から届いた `chain: true` の正規の連鎖の再展開まで潰し、注釈 `invokes` を複数
  // 持つ統合の形で並び順依存が残った（`out/tmp-r34/agy-repro3.py` の `orig` 6 行 / `rev` 7 行）。
  // ガードを別の形へ広げる打ち手も実測して落ちた（`out/tmp-r33/try-candidates.log`、
  // `out/tmp-r33/try-edge-detail.py`）: `back` 全般は `demo-order` の `entryIn` 3 → 1、
  // `resource` 全般は `real-api` の `aws_lambda_permission` の向き、段数で閉じる案は
  // `out/tmp-r33/deep-tail.py` で着地が消える
  const stateKey = (r) => (r.chain ? WALK_CHAIN : 0)
    | ((r.apiTail || (r.chain && apiTailFrom(byId.get(r.id)))) ? WALK_API_TAIL : 0)
    | (r.down ? WALK_DOWN : 0)
    | (r.reachedByInvokes ? WALK_INVOKES : 0)
    | (r.wiring !== true ? WALK_PROMOTABLE : 0)
    | (!r.sibBlocked ? WALK_UNBLOCKED : 0)
    | (r.switches < 1 ? WALK_IN | WALK_OUT
      : ((r.mdir || r.dir) === 'in' ? WALK_IN : WALK_OUT));
  // id -> [{枠, hops}]。同じ枠（またはビットの包含でそれより広い枠）で、しかも **自分より
  // 浅い段数**で既に展開済みなら支配されているとみなす。段数も枠と一緒に持つ理由は、
  // 起点がノードごとに別々の段数から始まるため（2 段目の walk は前ラウンドの記録を種にする）
  // 「先に展開した方が残りホップを多く持っている」とは限らない。実体 id だけの先着や、
  // 段数を見ない支配判定は、`chain: false, budget 小` の先着が `chain: true, budget 大` の
  // 再展開を止めてその先を丸ごと消す（双人レビュー第 30 ラウンド指摘 D）
  const expandedState = new Map();
  const accepts = (id, key, hops) => {
    const done = expandedState.get(id);
    if (!done) return true;
    return !done.some((d) => (d.key & key) === key && d.hops <= hops);
  };
  const markExpanded = (id, key, hops) => {
    const done = expandedState.get(id);
    if (done) done.push({ key, hops });
    else expandedState.set(id, [{ key, hops }]);
  };
  // 先着の記録へ新しい一歩の**旗だけ**を寄せる。`via` / `hops` / `dir` / 根拠の縁は
  // 書き換えない（`promote` と同じ約束）
  const mergeFlags = (prev, rec) => {
    // `wiring` は**本命の事実を落とす方向に合わせない**。後から届いた一歩がそれ自体
    // 本命 の資格（昇格を止められていない && 連鎖に入っている）を持つなら、先着の
    // `wiring: true` を解く。兄弟エンドポイント経由の到着が先着しても、正規の `calls`
    // 経路が後から届いたときに 定義上の関連 のまま残っていた（双人レビュー第 31 ラウンド
    // 指摘 1。`A → H → M → X → D` に兄弟 B が H と X を公開する形で、縁の並び順だけで
    // `X` が primary / wiring に割れた）。逆に後から届いた定義の縁（`references` など）が
    // 先着の本命を落とすことはない。判定式は `promote` の `primary` と同じ 1 歩分の条件で、
    // 別の経路の旗を足し合わせた架空の経路は作らない
    const promotable = rec.wiring !== true && rec.chain !== false;
    const wiring = promotable ? false : prev.wiring;
    return {
      ...prev,
      chain: !!(prev.chain || rec.chain),
      down: !!(prev.down || rec.down),
      reachedByInvokes: !!(prev.reachedByInvokes || rec.reachedByInvokes),
      apiTail: !!(prev.apiTail || rec.apiTail),
      sibBlocked: !!(prev.sibBlocked && rec.sibBlocked),
      switches: Math.min(prev.switches, rec.switches),
      wiring,
    };
  };
  for (const id of new Set(seedIds)) {
    if (!byId.has(id)) continue;
    const prev = combined.get(id);
    // `down` を受け事実に合わせて選び替えるので `let`（`const` のままだと
    // `TypeError: Assignment to constant variable.` で落ちる。双人レビュー第 23 ラウンド）
    let seed = prev || {
      id, dir: first, mdir: first, switches: 0, hops: 0, via: null, edge: null,
      down: false, reachedByInvokes: false, apiTail: false,
    };
    // 種は 2 通りある。**起点そのもの**（新しい種）は連鎖の入り口。前ラウンドの記録を
    // 種に使うときは、そのノードが連鎖に入っていたかだけを見る（`bestState` の `elig` は
    // 「同じ API を定義している」だけでも立つので、それを種にするとグループ全体へ伝播した）
    seed = { ...seed, chain: prev ? !!bestState.get(id)?.chain : true };
    // 経路の記録は循環境避で更新が見送られることがある。受けられた事実は `bestState` にあるので、
    // 閉包の種と同じ読み方をする（`down` を見落とすと、その先が 影響する先 ではなく
    // 影響を受ける入口 に行き着く）
    if (prev && !seed.down && bestState.get(id)?.down) seed = { ...seed, down: true };
    found.set(id, seed);
    markExpanded(id, stateKey(seed), seed.hops);
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
        for (const { e, to, corr, view } of (d === 'in' ? inn : out).get(cur.id) || []) {
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
          // 起点がエンドポイントのとき、実装の中の **呼び出し元へ戻る一歩**（`calls` を逆向きに
          // 渡る一歩）は、このエンドポイントの実行ではない別経路を覗いている。実測: 全員が呼ぶ
          // `Shared()` 起点の fixture で、`Shared` から呼び出し元 200 個が「このエンドポイントの
          // 実装の一部」になって 影響する先 に並んだ
          const backToCaller = startIsEndpoint && e.kind === 'calls' && !arrowAt(e, to);
          const down = ((cur.down && !(movement && !arrowAt(e, to)) && !backToCaller)
            || (startIsEndpoint && d === 'in' && FLIP_INTO_IMPL.has(e.kind))) ? true : false;
          // 「呼ばれて成立する」は**この一歩が `invokes` だった**こと。しかも矢印どおりに
          // 辿った一歩（呼ばれる側へ着いた一歩）だけ。経路に `invokes` が含まれるという判定に
          // すると、呼び出しの先で更に届いた無関係な別エンドポイント（同じ Lambda を使う
          // 兄弟）まで「呼びに出した先」に化けて兄弟欄から消えた。逆にたどった一歩
          // （呼び出し元へ着いた一歩）に立てるのも間違い
          const calledOut = e.kind === 'invokes' && arrowAt(e, to) && !internalInvokes(cur.id, to);
          // 兄弟エンドポイントの判定は**この一歩が呼び出しである**なら立たせない。
          // `bestState` の旗は同じラウンドのまだ書き終わっていないので、呼びに出した先が
          // 兄弟扱いになって連鎖が切れた（実測: `Handler.A → invokes → POST /b` の先が
          // 全部 定義上の関連 に落ちた）
          const sibHere = isSiblingEndpointNode(to) && !calledOut;
          const rec = {
            id: to, mdir: d, down, switches,
            // 記録の `dir` は**機械的な 辿った向き だけ**（`mdir` と同じ値）。第 46 ラウンド裁定まで
            // ここは表示用の 向き（実装側に入ったら 影響する先）を持っていたが、表示の 向き は
            // `displayFacts` が表示経路を根からフォールドして決めるので、記録の 向き を表示へ
            // 返すと別経路の旗が混ざる（`mergeFlags` は旗を論理和で引き継ぐ）。残りの読み手は
            // `stateKey` の `mdir` の代用と、選び直しの候補が同値だったときの比較だけ
            dir: d,
            // Terraform の `references` は「そのブロックを文中に書いた」だけで値が動かない。
            // walk で辿っても定義上の関連のままにする（実測: `admin_users` / `admin_api` が
            // 「動きの根拠: `references`」付きで本命に昇格した）
            wiring: (e.kind === 'references' && e.provenance === 'terraform')
              // 兄弟エンドポイントから外へ進む一歩は、その API の実装を巻き込むので昇格しない
              || !!cur.sibBlocked
              // 起点がエンドポイントのとき、実装の対応縁（`handler` / `exposed-by`）を
              // **逆に**渡った先は「同じコードを実行する別の入口」。起点の実行ではないので
              // 兄弟として出し、影響する先には数えない（起点がコードのときは逆に渡った先が
              // 本命 = 「このメソッドを実行している Lambda」の逆引きなので、そこは昇格させる）
              || (startIsEndpoint && FLIP_INTO_IMPL.has(e.kind) && !arrowAt(e, to)
                && flipAmbiguous(e.kind, cur.id)),
            hops: cur.hops + 1, via: back ? null : cur.id, cut: back,
            reachedByInvokes: calledOut,
            // **API の定義（統合・method・route）を越えて届いた**経路の旗。この旗が立った
            // コードは 2 段目の walk の種にする（指摘 C）。親が既に立てているなら引き継ぐ
            apiTail: !!cur.apiTail || crossesApiTail(cur, back),
            edge: view,
            sibBlocked: sibHere,
            // 実装側へ**入った**一歩（`handler` / `exposed-by` を逆向きに渡った一歩）。
            // 一度入ったら、その実装の対応縁をもう一度渡る一歩は「同じコードを使う別の入口」を
            // 覗く一歩になるので昇格させない（fan-out が 1 のときだけ断定できる）
            // **起点の実装関係で結ばれた連鎖**。親が連鎖に入っていて、この一歩が
            //  (a) 兄弟エンドポイントから外へ進む一歩ではなく
            //  (b) 実装の対応縁を**逆向きに**渡った先が断定できない（もう一方側が 2 つ以上）一歩でもなく
            //  (c) Terraform の `references` なら「**連鎖を参照している側**へ進む一歩」
            // こと。(c) を認めるのは v1 の `method` ← `integration`（integration が method を参照する）で
            // 連鎖を保つため。`wiring` と違って (c) の一歩は連鎖に残るが、動きの伝播は `primary` 側が
            // 動きの縁を見るので、定義の縁だけで本命へは昇格しない
            chain: !!cur.chain && !sibHere && !backToCaller
              && !(startIsEndpoint && FLIP_INTO_IMPL.has(e.kind) && !arrowAt(e, to)
                && flipAmbiguous(e.kind, cur.id))
              && !refCutsChain(e, cur.id, to),
          };
          // 表示候補には**受理されたかどうかで見ずに**全ての到着を数える（閉包の
          // `noteArrival` と同じ型）。先に `found` の先着で打ち切ると、同じ資格の別経路が
          // 後から届いても表示が縁の並び順で決まる（第 41 ラウンド）
          addWalkCandidate(to, rec, cur);
          // **到着した全ての一歩**の事実を受理の表へ寄せる。`found` で先着と合流させられた
          // 一歩の縁は `mergeFlags` が旗だけを寄せて捨て、`promote`（＝ここ）へは届かない。
          // 同じノードへ届いた**全ての一歩**を事実へ寄せるのは閉包側（`noteArrival`）と同じで、
          // 後着の一歩が立てる旗（本命・連鎖・`down`・`reachedByInvokes`・`apiTail`）を
          // 先着の枠で捨てないため。第 44 ラウンドまではここに「動きの縁」も集めて表示の根拠に
          // したが、別経路の縁は表示へ出さない（第 45 ラウンド Astra 裁定・案 D。`displayFacts` が
          // 表示に確定した連鎖の縁だけから決める）
          noteFacts(to, {
            primary: rec.wiring !== true && rec.chain !== false,
            elig: rec.wiring !== true, chain: rec.chain !== false,
            down: rec.down, reachedByInvokes: rec.reachedByInvokes, apiTail: rec.apiTail,
          });
          const prevRec = found.get(to);
          if (!prevRec) {
            found.set(to, rec);
            markExpanded(to, stateKey(rec), rec.hops);
            next.push(rec);
            continue;
          }
          // 同じノードへ別の経路が着いた。先着の記録（`via` / `hops` / `dir` / 根拠の縁）は
          // 書き換えずに**旗だけ**寄せる（`promote` と同じ約束）。以前はここを `found.has(to)` の
          // ノード id だけの先着で打ち切っていたので、`chain: false` の先着が後の
          // `chain: true` を潰していた（双人レビュー第 30 ラウンド指摘 D）
          found.set(to, mergeFlags(prevRec, rec));
          // もう一度展開するのは、この一歩の状態が**まだ展開していない枠**に立つときだけ。
          // 展開に渡すのはこの一歩が実際に持っていた状態そのもの。A 経路の `chain` と
          // B 経路の `down` を足した架空の経路を作らないため
          const key = stateKey(rec);
          if (accepts(to, key, rec.hops)) {
            markExpanded(to, key, rec.hops);
            next.push(rec);
          }
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
//  - `wiring = false`: 別の経路に**動きの縁**があった = 定義上ではなく本命
// 表示する 動きの根拠 はここから読まない（第 45 ラウンド Astra 裁定・案 D）。別経路の動きの縁を
// 記録へ集めると、その縁が 4 枠のどれへ入るか（＝表示で読むか）が `onChain` の循環境避判定＝
// **先着の連鎖**で決まり、同じ表示経路なのに 向き と 欄 まで入れ替わった
// （実測 `out/tmp-r44/min2-1.json` ほか 7 例）。表示は `displayFacts` が表示経路の縁だけから決める
function promote(cur, rec) {
  // walk 側で分かった事実も同じ場所へ合流させる（行の本命判定はここを見る）
  noteFacts(cur.id, {
    // 昇格は **昇格を止められていない一歩** かつ **起点の実装関係で結ばれた連鎖** の両方を
    // 満たすときだけ。以前は前者だけだったので、`references` で着いた定義ノードが閉包の種に
    // 並び、翌ラウンドで `triggers` を渡る一歩が「新しい記録の縁の種類」だけで本命に昇格した
    // （実測: 40 API × 20 route の fixture で 1 本の route 起点から 先 800 件）
    primary: rec.wiring !== true && rec.chain !== false,
    elig: rec.wiring !== true, chain: rec.chain !== false,
    down: rec.down, reachedByInvokes: rec.reachedByInvokes,
    apiTail: rec.apiTail,
  });
  if (rec.reachedByInvokes) cur.reachedByInvokes = true;
  // 「API の定義を越えて届いた」も単調に立つだけ（一度経路に入ったら消さない）
  if (rec.apiTail) cur.apiTail = true;
  // 「起点のエンドポイントの実装の中にある」という事実は一方通行（後から強い方の情報に
  // なるだけ）なので、先着の記録がまだ実装側に入る前のものでも反転させる。
  // `Step Functions → invokes → notify` のような**手前を向く縁**で先に着地すると
  // 「影響を受ける入口」になり、同じノードが実装の一部だと分かっても戻らなかった
  if (rec.down) cur.down = true;
  // 昇格は**動きの縁か注釈の縁**で届いたときだけ。Terraform の `references` は
  // 定義を書いただけなので、それが別の経路で届いても本命にはしない
  // 循環境避のために切った経路より、ちゃんと根まで辿れる経路の方がマシ。後から来た方の
  // `via` を引き取って経路を伸ばす。`edge` も同じ到着の一歩へ同時に差し替える —
  // 表示経路は `via` の連鎖なので、`edge` を最初の一歩のまま残すと「表示経路の最後の 1 本」が
  // 実際にその親を結んでいない行になる（第 45 ラウンド裁定の不変条件「根拠縁 ∈ 表示経路」に反する。
  // 実測 `annotations.report.json` の `GET /users`: 表示経路の親は handler を持つ Lambda なのに
  // 根拠縁は別経路の `invokes: method → integration` として残り、`呼ばれて成立` が立たなかった）
  if (cur.cut && rec.via) {
    cur.via = rec.via || null;
    cur.edge = rec.edge || null;
    cur.cut = false;
  }
  const kind = rec.edge ? rec.edge.kind : null;
  const prov = rec.edge ? rec.edge.provenance : null;
  if (cur.wiring === true && rec.wiring !== true
    && (MOVEMENT.has(kind) || CORRESPONDENCE.has(prov))) {
    // 別経路の動きの縁（または注釈の縁）が本命の資格を戻す。表示の 動きの根拠 はこの縁を
    // 読まない（第 45 ラウンド裁定）。ここで直すのは 定義上 / 本命 の資格だけ
    cur.wiring = false;
  }
}
function mergeRecords(found) {
  for (const [id, rec] of found) {
    const cur = combined.get(id);
    // `combined` へは必ず写しで入れる。`promote` が書き換えるのはこの実体だけなので、到着の
    // 記録（`found` と walk の候補が握る実体）は不変のまま共有できる。写しをここで 1 回作れば
    // 候補は到着ごとに実体を増やさない（第 38 ラウンド agy 指摘 P2 の意味は不変。検査
    // out/tmp-review38/check-mutation.py）
    if (!cur) combined.set(id, { ...rec });
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
// この一歩が縁の**どちらの端点に届いた**かという機械的な 辿った向き。矢印の意味は問わない
// （`arrowAt` と違い `exposed-by` の反転も看得ない）。表示の 向き（`in` / `out` / `none`）では
// なく、隣接表のえらび方（walk の `mdir`）と 向き変え回数（`switches`）の材料に使う。
// 第 46 ラウンド裁定 (b): 無方向の一歩の 向き をここから作ってはいけない
const endpointDirOf = (id, edge) => {
  if (!edge) return null;
  if (edge.target === id) return 'out';
  if (edge.source === id) return 'in';
  return null;   // 縁の端点がこのノードではない（あってはならない形）
};
// `handler` / `exposed-by` を**逆向き**に越える一歩（コード側から実体側へ戻る一歩）が、
// 唯一の実体を指しているのか、同じメソッドを実装する複数の中身のどれかを指しているのかを数える。
// 2 件以上あれば「どれがこのエンドポイントの実装か」は決まらないので推測しない。逆向き
// `handler` を無制限に認めた結果、1 本のエンドポイント起点から 800 本の Lambda が本命に
// 並んだ（1 エンドポイント 1 Lambda を共有する形の大規模 fixture で実測。双人レビューの P1）
// 実装の対応縁（`handler` / `exposed-by`）は 1 対 1 でない。**どちら側から渡るにせよ、その
// ノードにもう一方側の実体が 2 つ以上**なら「どれがこの経路の実装 / 入口か」を断定できないので
// 昇格しない。下流側への fan-in だけ見ていた初版は、実装から入口へ渡る一歩（`handler` の
// 順方向）を測っておらず、同じメソッドを実装する 40 個の Lambda が全部本命に着地した
// （40 API × 20 route の fixture で 1 本の route 起点から 先 800 件。双人レビュー P1）
const implPeers = new Map();   // `kind\u0000ノード` -> その縁でもう一方側にいる実体の集合
for (const e of graph.edges) {
  if (!FLIP_INTO_IMPL.has(e.kind)) continue;
  for (const [from, to] of [[e.source, e.target], [e.target, e.source]]) {
    const key = `${e.kind}\u0000${from}`;
    if (!implPeers.has(key)) implPeers.set(key, new Set());
    implPeers.get(key).add(to);
  }
}
const flipAmbiguous = (kind, fromId) => ((implPeers.get(`${kind}\u0000${fromId}`) || new Set()).size > 1);
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
// `X → references → Y` は「X が Y の定義の一部を書いた」（integration が method を参照する）と
// 読む。`refersInto(edge, fromId, toId)` は **参照されている側 Y から参照している側 X へ進む
// 一歩**（= 矢印を逆向きに辿る一歩）であることを表す
const refersInto = (edge, fromId, toId) => edge.target === fromId && edge.source === toId;
// `method` / `route` から自分の API の `integration` への `invokes` は **その API の実装へ入る
// 一歩**なので、「起点が呼びに出した先」の旗（`reachedByInvokes`）を立てない。同じ API の定義
// 同士でこの旗が立つと、兄弟欄の判定（呼びに出した先は兄弟にしない）が壊れて
// `integration.get_users` が兄弟欄から消えた（第 29 ラウンドの実測）
const internalInvokes = (fromId, toId) => {
  const g = apiGroupOf(byId.get(toId));
  return g !== null && g !== undefined && apiGroupOf(byId.get(fromId)) === g;
};
// Terraform の汎用 `references`（ブロック中にアドレスを書いただけで、値が動くわけではない）の
// 一歩を連鎖から落とす判定。**進む向きで意味が違う**ので、向きで切り分ける。どちらの向きも
// 実測で壊れた形がある（第 29 ラウンド）
//  - **起点がエンドポイント**のときは `refersInto` が立つ一歩だけ連鎖に残す。
//    `integration → references → method` は **その method を特定できる直接参照**なので、
//    ここを逆向きに辿った先（= integration）は起点の実装。一方 `method → references →
//    resource / rest_api` を連鎖に残すと、同じ resource を共有する別メソッド（`GET /orders`）の
//    integration まで起点の実装に昇格する（`method → resource ← integration` は両端が同じ定義を
//    参照しているだけで、HTTP 動詞を見なければ GET と POST を区別できない）。第 29 ラウンドの
//    裁定どおり「その API の下に method が 1 件しかない」での橋渡しは作らない（候補が 1 件なのは
//    対応が確定した証拠にならない）。method を特定できる直接参照も注釈もない integration は
//    本命にしない
//  - **起点がコード / Lambda などエンドポイント以外**のときは逆向き（`refersInto`）を一歩で
//    切る。`Lambda → references → テーブル` は起点の実行が実際に触れる定義なので連鎖に残す
//    （実測デモ `demo-proj`）。逆に `IAM ロール ← references ← 別 Lambda` は「自分を参照して
//    いる側」への扇出なので落とす（実測: IAM ポリシー起点でロールを介して全 Lambda とその
//    handler が本命になった）
const refCutsChain = (edge, fromId, toId) => {
  if (edge.kind !== 'references' || edge.provenance !== 'terraform') return false;
  if (!refersInto(edge, fromId, toId)) return startIsEndpoint;
  if (startIsEndpoint) return false;
  // 逆向きの一歩を切る理由「自分を参照している側への扇出」は、参照している側が**何でも**成り立つ。
  // ただし `統合 → references → method / route` はその一歩を逆に辿った先が **起点の実装本体**なので、
  // コード起点でも連鎖に残す（双人レビュー第 30 ラウンド指摘 E。v1 の「統合がメソッドを直接
  // 参照している」実データ形で Lambda に届かず、`--from` の Lambda が 定義上の関連 に落ちていた）。
  // IAM ロールやテーブルを参照している別 Lambda への扇出は `to` が統合でないので今までどおり切る
  return !(isIntegrationNode(byId.get(toId)) && isRouteStart(byId.get(fromId)));
};
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
// エンドポイント（`GET /orders` のように HTTP のメソッドとパスで引けるノード）の集合
const endpointIdSet = new Set();
for (const [id, n] of byId) if (endpointOf(n)) endpointIdSet.add(id);
// **兄弟エンドポイント**: 起点ではないエンドポイントで、起点から**動きとして届いていない**もの
// （同じコードを使う別の API、または同じ API の別の route）。そこ先を「起点が実行する実装」と
// して広げない。`api_id` が同じ／同じメソッドを公開しているという事実は「一緒に見る対象」で
// あり、起点の実行の一部ではない（双人レビュー第 25 ラウンドの合意: API グループの一致と
// 起点の `target` が示す実装関係は区別する）。逆に起点から `invokes` で呼びに出した先は
// 起点の実行の一部なので広める（`Handler → invokes → API B` の既存のふるまいを守る）
const isSiblingEndpointNode = (id) => {
  if (!startIsEndpoint || startSet.has(id) || !endpointIdSet.has(id)) return false;
  const st = bestState.get(id);
  return !(st ? st.reachedByInvokes : false);
};
// 隣エントリごとの事前計算。閉包の不受理到着の再辿り（`candQueue`）は到着ごとに隣を
// 評価し直すので、隣ごとの helper 呼び出しがそのまま倍の回数になっていた（第 40 ラウンドの
// 性能 gate 実測）。**到着の状態に依らない項目だけ**をここに置く。`sib`（`bestState` を読む）と
// `inTouchedApiGroup`（`touchedApiGroups` を読む）は到着ごとに変わり得るので動的のまま
for (const [fromId, list] of tfAdj) {
  const tailFromHome = apiTailFrom(byId.get(fromId));
  for (const nb of list) {
    const e = nb.edge;
    nb.mv = MOVEMENT.has(e.kind);
    nb.arrow = arrowAt(e, nb.to);
    nb.rInto = e.target === fromId && e.source === nb.to;
    nb.kindInv = e.kind === 'invokes';
    nb.flipKind = FLIP_INTO_IMPL.has(e.kind);
    nb.flipAmb = nb.flipKind ? flipAmbiguous(e.kind, fromId) : false;
    nb.cuts = refCutsChain(e, fromId, nb.to);
    nb.intInv = nb.kindInv && internalInvokes(fromId, nb.to);
    nb.tailFrom = tailFromHome;
  }
}
const bestState = new Map();   // id -> { budget, primary, elig, down, reachedByInvokes, chain, apiTail }
// **表示する動きの根拠はここに集めない**（第 45 ラウンド Astra 裁定・案 D）。第 44 ラウンドまで
// は「同じノードへ届いた動きの縁」を 4 枠（対応縁×到着 / 対応縁×循環境避 / 流れの縁×到着 /
// 流れの縁×循環境避）に分けて `movementWins`（縁 id の辞書順最小）で選び直し、枠の優先順で
// 表示へ出していた。枠のどちらへ入るかは `onChain` の循環境避判定が**先着の連鎖**を読むので
// 縁の並び順で変わり、同じ表示経路なのに 動きの根拠 → 向き → 欄 まで入れ替わった（実測
// `out/tmp-r44/min2-0.json` 〜 `min2-5.json` と `min-3.json` の 7 例、`out/tmp-r44/FINDINGS2.md`）。
// 表示の根拠は `displayFacts` が**表示に確定した連鎖の縁だけ**から決める。ここに積む
// `primary`（本命）や旗は受理事実としてそのまま残す — 別経路の事実は「一覧に出す資格」の材料で、
// 表示値の材料にしない
// **受理した事実（本命か / 動きの根拠 / 旗）はここ、経路（`via` と表示する縁）は記録側**に置く。
// 両方を記録に持たせていたため、経路を循環境避で切ったときに受理済みの本命情報まで捨てた
// （双人レビュー P1: タグ参照が 1 本増えただけで実際の `invokes` が定義上の関連へ落ちた）
// 閉包が「どの資格で展開したか」をここ別で持つ。事実（`bestState`）と同じ入れ物にすると、
// walk が後から事実を強くしたとき、その資格での展開をまだしていないのに `offer()` が
// 「改善なし」と判断して再展開を省いた（双人レビュー第 20 ラウンド P1: 定義参照が 1 本
// 増えただけで上流の Step Functions が 定義上の関連 に落ちた）
// 展開記録は `budgets` を `(chain, elig, down, apiTail)` の 16 通り（0..15）ごとに持つ。1 つの `budget` に
// 平坦に合併すると、積束で比較不能な 2 状態（`chain: false, budget: 1` と `chain: true, budget: 3`）が
// `{ chain: true, budget: 1 }` に化けて、一度も展開していない `(chain: true, budget: 2)` を
// 「展開済み」と誤判定した（双人レビュー第 22 ラウンドの最小反例 B、第 29 ラウンドで `chain` の枠を足す）
// 枠のビットは下の名前で持つ（立った枠が、その旗だけを落とした下位の枠を同じ予算で支配する）
const CLOSURE_DOWN = 1;        // 実装側（この先は 影響する先）
const CLOSURE_ELIG = 2;        // 伝播の資格
const CLOSURE_CHAIN = 4;       // 起点の実装関係で結ばれた連鎖
const CLOSURE_API_TAIL = 8;    // API の定義（統合・method・route）を越えて届いた
const NO_BUDGETS = new Array(CLOSURE_API_TAIL * 2).fill(Infinity);
const expandedAt = new Map();   // id -> { primary, gen, budgets: [8] }
// `touchedApiGroups` が増えると、同じ資格の種でも子側の伝播資格 (`inTouchedApiGroup`) が変わる。
// 世代を持たないと「同じ資格だから展開済み」と却下されて、届いた API の定義が
// 定義上の関連 に残った（双人レビュー第 21 ラウンド P1、両名の反例）
let apiGen = 0;
function noteFacts(id, f) {
  const prev = bestState.get(id)
    || { primary: false, elig: false, down: false, reachedByInvokes: false, chain: false, apiTail: false };
  bestState.set(id, {
    ...prev,
    primary: prev.primary || !!f.primary,
    elig: prev.elig || !!f.elig,
    down: prev.down || !!f.down,
    reachedByInvokes: prev.reachedByInvokes || !!f.reachedByInvokes,
    // **起点の実装関係で結ばれた連鎖**に入っていること。`elig`（一覧に出す資格）より厳しい。
    // 連鎖に入っていないノードは動きの縁を渡っても本命へ昇格しない
    chain: prev.chain || !!f.chain,
    // 「API の定義を越えて届いた」も他の旗と同じく単調（一度立ったら消さない）。共有ロールなど
    // 定義の縁だけで届いた一歩が先着しても、後から `apiTail` を立てて届いた事実を捨てない
    // （双人レビュー第 31 ラウンド agy 指摘 1）
    apiTail: prev.apiTail || !!f.apiTail,
  });
}
// closure の状態は (段数, 定義の縁の残り予算, 本命か, 動きを伝播してよいか)。
// **訪問済み をノード id だけで決めると**、予算を多く使った経路が先着した瞬間に
// 同じノードへの少ない予算の経路が捨てられ、辺の並び順だけで着地が変わる（実測: 53 ノードの
// fixture で `kms_key` が出る順と消える順が作れた）。だから「同じノードでも予算が減った／
// 定義上から本命へ昇格した」なら再展開する
function runClosure(seedIds) {
  const queue = [];
  // 資格のマスク。展開の受理表と表示候補の両方が同じ資格を見る
  const maskOf = (state) => (state.chain ? CLOSURE_CHAIN : 0) | (state.elig ? CLOSURE_ELIG : 0)
    | (state.down ? CLOSURE_DOWN : 0) | (state.apiTail ? CLOSURE_API_TAIL : 0);
  // 到着の事実と表示候補の記録。届いた一歩は**展開に受理されたか否か・`cut`・`wiring`・
  // 受理済み事実に関わらず**ここに全部残す。事実は一度立ったら消えないので、弱い方の状態が
  // 後から来ても旗を戻さないよう、ここで合流させる
  const noteArrival = (state) => {
    noteFacts(state.id, {
      primary: state.primary, elig: state.elig, down: state.down, reachedByInvokes: state.reachedByInvokes,
      chain: state.chain, apiTail: state.apiTail,
    });
    // **表示する代表経路の候補集合**（仕様 out/loop/r38-decision.md、原則 4）。
    // r37 までここに有った 2 つの到着順ゲート（旧 `demote` / `shorter`）は削除した。ゲートは
    // 「既に何が候補に入っているか」と「`bestState` の到着順の旗」を読むので、同じ経路でも
    // 加わる順で合否が変わり、支配関係との非対称性を作っていた（双人レビュー第 37 ラウンド
    // agy 指摘 3-1）。旧ゲートの意図（定義上の関連を最後に、根付きを先に）は `repDominates` と
    // `repCmp` の第 1・2 項が同じ比較項目で持っているので、代表の選び方は変わらない
    const mask = maskOf(state);
    if (state.rec) addRepCandidate(state.id, mask, state.budget, state.rec);
    return mask;
  };
  // 受理したら true。**受理された状態だけを展開する**（受理不看で queue に入れると、
  // 古い状態が隣を又呼び、隣が又戻ってきて列が伸び続けて終わらなくなる）
  const offer = (state) => {
    // `via` が循環して `path[0]` が起点でなくなる行が出た（実測: 実プロジェクトの
    // `--api "POST /messages"` で 9 行中 5 行、`--from tf:aws_iam_role_policy.…` で全 15 行が
    // 2 ノードの循環）。表示の連鎖の打ち切り・循環そのものは収束後の確定処理で防ぐ
    // （仕様 out/loop/r40-decision.md）
    // 展開するのは (a) 今の世代ではまだ展開していない、(b) 初めて本命として展開する、
    // (c) 同じ `(chain, elig, down, apiTail)` の資格で前回より小さい予算で届いた、のいずれかのとき。
    // (c) は本命でなくても効く（定義上の関連にも `--wiring-hops` の予算は及ぶ）。第 22 ラウンドの
    // 最小反例では `references` で budget 2 のノードが、`invokes` を越えて budget 1 で届き直したとき
    // に却下され、その先 1 ノードがどの欄にも出なかった
    const mask = noteArrival(state);
    const done = expandedAt.get(state.id);
    const fresh = !done || done.gen !== apiGen;
    // 予算は非負整数で (c) ごとに厳密に減り、(a)(b) は高々 1 回、世代はグループ増でしか上がらない。
    // だから 1 ノード 1 世代あたりの再展開は高々 `16 * (予算 + 1) + 1` 回、世代は高々
    // `API グループ数 + 1` なので有限に止まる
    const prevBudget = fresh ? Infinity : done.budgets[mask];
    const better = fresh || (state.primary && !done.primary) || state.budget < prevBudget;
    if (!better) return false;
    // 予算表は納めた条目の中身を更新するだけ（到着ごとに 16 個の配列を作り直さない）。
    // この表を取り出して他所で保持する箇所は無いので、その場で書き換えても見る人は同じ
    const budgets = fresh ? [...NO_BUDGETS] : done.budgets;
    budgets[mask] = Math.min(prevBudget, state.budget);
    // `chain` / `elig` / `apiTail` は立つほど展開が広い旗（同じ予算なら同じ一歩を全て辿れる）。
    // だから立った資格は、その旗だけを落とした下位の資格も同じ予算で支配する。更新を忘れると
    // 後から来た弱い資格の状態が無意味に再展開される。逆に `apiTail` の支配を効かせないと、
    // IAM ロールを共有するだけの経路（`apiTail: false`）が先着した瞬間に、後から `apiTail` を
    // 立てて届いた経路が却下され、その先のテーブルが全欄から消える（双人レビュー第 31 ラウンド
    // agy 指摘 1）
    if (state.chain) {
      budgets[mask & ~CLOSURE_CHAIN] = Math.min(budgets[mask & ~CLOSURE_CHAIN], budgets[mask]);
    }
    if (state.elig) {
      budgets[mask & ~CLOSURE_ELIG] = Math.min(budgets[mask & ~CLOSURE_ELIG], budgets[mask]);
    }
    if (state.apiTail) {
      budgets[mask & ~CLOSURE_API_TAIL] = Math.min(budgets[mask & ~CLOSURE_API_TAIL], budgets[mask]);
    }
    if (fresh) {
      expandedAt.set(state.id, { primary: !!state.primary, gen: apiGen, budgets });
    } else {
      done.primary = !!state.primary || !!done.primary;
      done.gen = apiGen;
    }
    // `bestState` も同じ条目の `budget` を更新するだけ（毎回 `{ ...obj }` で実体を
    // 作り直すと、到着の数だけ合流の材料が増えて合流のたびに高くなる）
    const bs = bestState.get(state.id);
    if (bs) {
      if (state.budget < bs.budget) bs.budget = state.budget;
    } else {
      bestState.set(state.id, { budget: state.budget });
    }
    return true;
  };

  // 展開中の実経路のノード（第 37 ラウンドの `onPath` と同じ材料・同じ上限 64: キュー状態の
  // `parent` 連鎖と種の walk 記録（`combined`）の `via` 連鎖。閉包の最中に `combined` は
  // 変わらないので見てよい。表示の代表は**読まない**）。隣ごとの循環判定と背面パターンの符号で
  // 同じ連鎖を何度も辿るのは高いので、1 状態 1 回だけ再利用配列へ写す（Set を不受理到着の
  // 全件分作ったのが `elsa-folder` の主コストの一つ。実測 1.01 → 0.70 秒）
  const pathBuf = [];
  const pathStamp = new Map();
  let pathEpoch = 0;
  const fillPath = (state) => {
    pathEpoch += 1;
    let n = 0;
    let s = state;
    for (let i = 0; s && i < 64; i += 1) {
      pathBuf[n] = s.id; n += 1;
      if (!s.parent) {
        let rec = combined.get(s.id);
        rec = rec && rec.via ? combined.get(rec.via) : null;
        for (let j = 0; rec && j < 64; j += 1) {
          pathBuf[n] = rec.id; n += 1;
          rec = rec.via ? combined.get(rec.via) : null;
        }
        break;
      }
      s = s.parent;
    }
    for (let i = 0; i < n; i += 1) pathStamp.set(pathBuf[i], pathEpoch);
    return n;
  };
  // 経路上の判定は書き込み時の刻印（`pathStamp`）で見る。隣ごとの総当り（`pathBuf` の
  // 線形走査を隣の数だけ繰り返す）は背面パターンの符号と合わせて主コストだった
  const pathHas = (n, id) => pathStamp.get(id) === pathEpoch;
  // 隣ごとの背面フラグを書き出す再利用配列（`pathBuf` が子の判定で書き換わるため、
  // 隣ループは先にフラグだけ確保してから進む。`pathHas` を先に読むため値は常に真偽）
  const backBuf = [];
  // 背面パターン: この状態の隣が「展開中の経路上に居るか」の 0/1 並び（`tfAdj` の順は
  // グラフから決まり到着順に依らない）。同じ隣を辿る状態は同じ結論になるので、不受理到着の
  // 重複の識別に使う。**共有配列なので呼んだ人が `pathHas` を読み終わるまで
  // 他の `fillPath` を挟まない**こと（隣ループでは背面フラグを先に書き出してから使う）
  const sigOf = (state) => {
    const n = fillPath(state);
    const arr = [];
    for (const nb of tfAdj.get(state.id) || []) arr.push(pathHas(n, nb.to) ? 1 : 0);
    // 不受理到着として再辿るとき、pop 後の背面フラグはここで測ったものと同一になる
    // （同じ `tfAdj` の並びを同じ経路で見る）。配列を置いておけば pop 時の `fillPath` を
    // _walk_しなくて済む（第 40 ラウンド実測: 不受理再辿りの主コストが到着ごとの `fillPath` 二重計算）
    state.candBack = arr;
    return arr.join('');
  };
  // **不受理の到着も 1 回は隣へ事実と候補を残す**（双人レビュー第 38 ラウンド codex 指摘 P1）。
  // 受理表は展開を増やさないための枝刈りだが、循環境避（`onPath`）は展開中の実経路を読むので、
  // 同じ (資格, 予算) で親だけ違う到着のどちらが展開されるかで「ある一歩が到着か背面カットか」が
  // 変わり、候補集合と動きの根拠そのものが縁の並び順で揺れた（再現
  // `out/tmp-review38/repro.py` の `core-minimal-lambda`: `c` が orig 3 段 / rev 1 段、
  // `minimal-lambda`: `t` の動きの根拠が e4 / e2）。不受理の到着から隣をもう 1 周辿るが、
  // 事実と候補の記録だけ（受理表には触れない）で、その先の展開はしない。展開の受理は
  // この処理に一切影響しないので探索の広がり・終了性は不変。同じ
  // (ノード, 資格, 予算, 隣に対する背面パターン) の不受理到着は 1 回だけなので有限で終わる
  const candQueue = [];
  // `id -> (キー -> 再辿り済みの最小段数)`。キーは (資格, 予算, 背面パターン, `sibBlocked`)。
  // `sibBlocked` は子の `primary`（=`wiring`）を決めるので資格のマスクに入っていなくても
  // キーに必要。段数だけが違う不受理到着は多い方が子の候補で支配される（同じ `via` 群で
  // 段数以外同じ候補は段数の小さい方に負ける）ため、少ない方だけ辿れば着地は同じ
  const candRelaxed = new Map();
  // `gateKind` は展開側の受理と同じ門（種の時点はノード種別を問わないが、一歩ごとの展開は
  // Terraform の資源ノードだけ。メンバで展開しないのはコード側の縁を辿るのを本命 walk
  // だけにさせるため）
  const offerOrQueue = (state, gateKind) => {
    const isResource = (byId.get(state.id) || {}).kind === 'resource';
    if (offer(state)) {
      if (!gateKind || isResource) queue.push(state);
      return;
    }
    if (gateKind && !isResource) return;
    const sig = sigOf(state);
    const key = `${maskOf(state)}|${state.budget}|${sig}|${state.sibBlocked ? 1 : 0}`;
    const keys = candRelaxed.get(state.id) || new Map();
    const known = keys.get(key);
    if (known !== undefined && state.hops >= known) return;
    keys.set(key, state.hops);
    candRelaxed.set(state.id, keys);
    state.candOnly = true;
    candQueue.push(state);
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
      // 根となる一歩を持たない記録なので 辿った向き は `null`（機械的な向きも、表示の 向きも
      // 縁の無い一歩からは決まらない）
      rec = { id, edge: null, hops: 0, switches: 0, via: null, cut: true, dir: null, wiring: false };
    }
    // 経路の記録（`rec`）は循環境避で `wiring` のまま残ることがあるので、資格は受理事実を優先する
    const st = bestState.get(id);
    // 連鎖の資格は walk が決めたものだけを使う。「同じ API を定義している」は
    // 一覧に出す資格（`elig`）であって、動きを伝える資格ではない
    const chain = st ? !!st.chain : rec.chain !== false;
    // 出発点の本命も連鎖の資格がないといけない。`wiring` だけ見ていた初版では、
    // 「昇格を止められていないが連鎖外」の記録（実装が呼ぶ `Shared()` から見た呼び出し元など）が
    // 閉包の種になった瞬間に本命へ昇格し、その先 200 件が 影響を受ける入口 の本命に並んだ
    const primary = chain && (st ? st.primary : rec.wiring !== true);
    // `parent` は実経路の親（キュー状態）。循環境避（`onPath`）はこれだけを辿る。
    // 種の歩みは walk 記録（`combined`）にあり、ラウンド途中で書き換わらない
    const state = {
      id, hops: rec.hops, budget: 0, down: st ? st.down : !!rec.down,
      reachedByInvokes: rec ? !!rec.reachedByInvokes : false,
      primary, elig: primary || inTouchedApiGroup(id),
      chain,
      apiTail: !!rec.apiTail,
      via: null, rec: { ...rec }, parent: null,
    };
    offerOrQueue(state, false);
  }
  let guard = 0;
  while ((queue.length || candQueue.length) && guard++ < MAX_CLOSURE_STEPS * 2) {
    // 受理された状態の列が先。**`candOnly` の再辿りは受理 BFS が空になった後だけ**に流す。
    // 再辿りの子は事実（`noteFacts`）へ直接寄せるので、受理の到着と混ぜると事実の
    // 「先に着いた記録」の順序が揺れて、支配判定の及ばない項目（定義上の関連の段数など）が
    // 食い違った（第 40 ラウンド実測: 交差優先にすると `real-handler.json` の `example_api` が
    // in/3 段 → out/4 段 へ反転）。受理 BFS の処理順は `candQueue` の有無で変わらない
    const cur = queue.length ? queue.shift() : candQueue.shift();
    // 循環境避は**展開中の実経路**（`fillPath`。キュー状態の `parent` 連鎖と種の walk 記録）
    // だけで決める。表示の代表が入る `wiringMap` を読むと、代表の選び方が循環判定 →
    // `cut` / `apiTail` → 候補の合否へ逆流して候補集合自体が到着順で変わる
    // （双人レビュー第 37 ラウンド指摘 1。仕様 out/loop/r38-decision.md）。
    // 背面フラグは隣へ進む前に全部書き出しておく。共有の `pathBuf` は子の受理・不受理の
    // 判定（`sigOf`）で書き換わるので、間に挟んだ `pathHas` は信用できない
    const nbs = tfAdj.get(cur.id) || [];
    if (cur.candBack) {
      for (let qi = 0; qi < nbs.length; qi += 1) backBuf[qi] = cur.candBack[qi];
    } else {
      const pn = fillPath(cur);
      for (let qi = 0; qi < nbs.length; qi += 1) backBuf[qi] = pathHas(pn, nbs[qi].to);
    }
    for (let qi = 0; qi < nbs.length; qi += 1) {
      const nb = nbs[qi];
      const { to, edge } = nb;
      // 段数の上限は「Terraform の定義単位をどこまで閉じるか」なので、予算を課すのは
      // `references`（定義を辿る縁）だけ。**動きの縁を越えたところでは数え直す**
      const back = !!backBuf[qi];   // 循環させる一歩は出発点を切り直す
      const movement = nb.mv;
      const budget = movement ? 0 : cur.budget + 1;
      if (budget > opts.wiringHops) continue;
      // **伝播の資格**: 動きの縁を辿っても、辿ってきたノードが「起点 / 本命として届いたノード /
      // 起点と同じ API を定義しているノード」でなければ、その先は定義上の関連のままにする。
      // これを忘れると、IAM ロールだけを共有する別 Lambda 専用の integration や
      // その handler まで本命に伝播した（双人レビュー P1。`references` をまたいだ伝播資格を
      // 縁の種類だけ見ていたのが原因）
      // 起点がエンドポイントのとき、`handler` / `exposed-by` を**逆向き**に越えた一歩は
      // 「そのコードを実装している別の入口」を覗いているだけなので、そこからは伝播させない。
      // 逆向き `handler` 経由で別 API の Lambda やその handler まで本命になっていた（双人レビュー P1）
      const flipped = startIsEndpoint && nb.flipKind && !nb.arrow && nb.flipAmb;
      // 本命は**動きの縁 × 連鎖**。`cur.elig`（同じ API を定義しているだけ）をここに使っていたのが
      // 過剰昇格の door で、グループ全体が種になって翌ラウンドで昇格した
      const primary = movement && !!cur.chain && !cur.sibBlocked && !flipped;
      // 定義の縁を渡るときは**参照している側へ進む一歩だけ**資格を受け継ぐ。
      // 「自分が使っているもの」（Lambda → IAM ロール、Lambda → テーブル名）へ渡った先は
      // 資格を失うので、そこで繋がっているだけの第三者にまでは広がらない
      // 兄弟エンドポイントそのものは 定義上の関連 / 兄弟欄 に出す。ただしそこから先の
      // 伝播の資格は与えない（`api_id` が同じだけの別 route の実装を本命にしない）
      const sib = isSiblingEndpointNode(to);
      const elig = !sib && !flipped && (primary || inTouchedApiGroup(to)
        || (!movement && cur.elig && nb.rInto));
      // 閉包でも連鎖は同じ規則で受け継ぐ（walk と同じ `refCutsChain`）
      const chain = !!cur.chain && !sib && !flipped && !nb.cuts;
      const rec = {
        id: to, edge,
        hops: cur.hops + 1, switches: 0, via: back ? null : cur.id, cut: back, wiring: !primary,
        down: !!cur.down && !(movement && !nb.arrow),
        // `reachedByInvokes` は**この一歩が `invokes` だった**こと。しかも矢印どおりに辿った
        // 一歩（呼ばれる側へ着いた一歩）だけ。逆にたどった一歩（呼び出し元へ着いた一歩）に
        // 立てると「自分が呼んだ」と読める旗が上流に立った（双人レビュー第 20 ラウンド P2）
        reachedByInvokes: nb.kindInv && nb.arrow && !nb.intInv,
        // walk と同じ「API の定義を越えて届いた」旗。閉包は Terraform の定義を無方向に閉じるので、
        // `integration → references → resource` のような定義側もここを通る。旗は**この経路が
        // 運んできたもの**だけを使う（`bestState` の寄せ集めを種に渡すと、別の経路で立った旗が
        // 無い経路にも付く。実測: IAM ポリシー起点が 19 行に膨らんだ）。立てる条件は walk と同じ
        apiTail: !!cur.apiTail || (!back && !!cur.chain && nb.tailFrom),
        sibBlocked: sib,
        chain,
        // 機械的な 辿った向き（このノードが縁のどちらの端点かに届いた一歩か）だけを持つ。
        // walk の `mdir` と同じ意味で、表示の 向き は `displayFacts` が表示経路を根から
        // フォールドして決める（第 46 ラウンド裁定）。以前はここで 実装側の旗 `cur.down` と
        // 親レコードの 向き を継いだ表示用の値を持っていた。`combined.get(cur.id).dir` は
        // 同じノードへ別経路から届いた先着値なので、それを読む組み立て自体が裁定で却下された
        dir: endpointDirOf(to, edge),
      };
      const state = {
        id: to, hops: rec.hops, budget, primary, elig, via: rec.via, rec, chain,
        down: rec.down, reachedByInvokes: rec.reachedByInvokes, sibBlocked: rec.sibBlocked,
        apiTail: !!rec.apiTail, parent: cur,
      };
      // メンバ（`handler` の届く先）では展開しない。コード側の縁を辿るのは本命の walk だけにさせる
      if (cur.candOnly) {
        // 記録のみの状態からの子は事実と候補だけ残す（受理表に触れないので展開の広さは不変）
        noteArrival(state);
      } else {
        offerOrQueue(state, true);
      }
    }
  }
  return wiringMap;
}
function mergeWiring() {
  for (const [id, info] of wiringMap) {
    const cur = combined.get(id);
    // `combined` にもコピーを入れる（双人レビュー第 38 ラウンド P2。候補や `wiringMap` と
    // 同じ実体を握ったまま `promote` が書き換えると、後から来た候補との比較がマージ順に
    // 左右される）
    if (!cur) combined.set(id, { ...info });
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
    // 兄弟エンドポイント（起点から動きとして届いていない別の API）の群を増やすと、その API の
    // `integration` が「同じ API の定義」として伝播の資格を得て、別 route の Lambda まで本命になる
    if (isSiblingEndpointNode(id)) continue;
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
// 非終端のラウンドは「まだ歩いていない member / type」か「未登録の API グループ」を
// 少なくとも 1 つ消費するので、両者の総数に終端確認ぶんを足した数が収束上界になる。
// グループ数だけの式だと、API を含まない Lambda の連鎖で打ち切りが先に効く
// （第 23 ラウンドの 26 ノード反例）。`--max-rounds` で明示的に絞れる（未収束は旗を出すので隠れない）
const codeNodeTotal = [...byId.values()]
  .filter((n) => n.kind === 'member' || n.kind === 'type').length;
const maxRounds = opts.maxRounds ?? (MAX_ROUNDS + apiGroupTotal + codeNodeTotal + 2);
let rounds = 0;
let unresolved = false;
let pending = true;
while (pending && rounds < maxRounds) {
  pending = false;
  runClosure(closureSeeds);
  mergeWiring();
  // コードの種は **本命として届いたコード** と **API の定義を越えて届いたコード**。
  // 本命だけを種にしていた版だと、対応未確定で 定義上の関連 に落ちたハンドルの先
  // （呼び出し・アノテーションの先）がどの欄にも出なくなった（実測: `POST /orders` の統合が
  // method を特定できていない fixture で `Handler.Handle` は 定義上の関連 に出るのに、その先の
  // `Save` / `Order.Create` / 書き込み先テーブルが丸ごと消えた）。
  // 「起点がエンドポイントなら届いたコードを全部種にする」以前のgate は、その逆で
  // **コード起点のときだけ同じ形をした行が消えていた**（双人レビュー第 30 ラウンド指摘 C。
  // `touched-api-nocorr` を `--from tf:aws_lambda_function.a` で引くと `ext:rds-table/orders` が
  // 行ごと消えた）。だから gate は起点の種別ではなく **経路が API の定義（統合・method・route）を
  // 越えたか** で見る。IAM ロールやポリシーだけを辿って届いたコードは種にならないので、
  // ポリシー起点が膨らまない以前の意図もそのまま守れる。
  // 種にしたからといって昇格はしない（昇格は連鎖 + 動き/注釈の縁が条件）ので、出てきた先は
  // 定義上の関連 のまま並ぶ
  const codeSeeds = [...combined.keys()].filter((id) => {
    const k = (byId.get(id) || {}).kind;
    const st = bestState.get(id);
    const rec = combined.get(id);
    const primary = st ? st.primary : !!rec && rec.wiring !== true;
    // 「API の定義を越えて届いた」も `primary` と同じく受理済みの単調な事実を見る。
    // 記録（`combined`）側だけ読むと、比較不能な資格の経路が後着上書きで旗を落としたとき、
    // 実際に旗を運んだ経路が存在しても種から外れて着地が消える（双人レビュー第 35 ラウンド
    // agy 指摘 1。再現 `out/tmp-r36/agy-repro-a.py`）。種は昇格の資格ではなく walk の出発点
    // なので、別の経路で立った旗を拾っても架空の経路は生まれない（第 31 ラウンドで
    // 避けたいのは「寄せた事実を展開の資格に渡す」ことで、ここと使う向きが逆）
    const tail = st ? st.apiTail : !!rec && !!rec.apiTail;
    return (k === 'member' || k === 'type') && !walkedCode.has(id)
      && (primary || tail);
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
  rounds++;
}
// 上限に達して仕事が残ったなら、切り詰めた結果を完全な結果として出さない
if (pending) {
  unresolved = true;
  process.stderr.write(`[report] 警告: 探索が収束する前にラウンド上限 ${maxRounds} に達しました（結果は不完全です）\n`);
}

// walk の到着はここまで。根拠の縁の表示用コピーは隣エントリ（上の `view`）が 1 本につき 1 個
// だけ持つので、到着ごとに数えた表は作っていない（以前はここで捨てていたが、実測 elsa-folder
// で 53,521 個ぶんの表を到着のあいだ生やして 0.35 秒払っていた）
// ---- 表示経路を「起点まで遡れる単一の連鎖」に確定する（仕様 out/loop/r40-decision.md、
//      walk の到着を候補へ加えた改修は out/loop/r41-decision.md）----
// 探索の受理・循環カット・旗・`bestState` は一切変えない（第 38 ラウンド不変原則 4）。
// ここは収束後の表示だけを見る。代表は 2 つの候補集合から選ぶ:
//  - `walkCands`（walk の到着。第 41 ラウンドで追加）… walk が起点まで遡れる連鎖で届けた
//    行の代表。ここまでの walk の行は `found` の**先着**がそのまま表示され、同じ資格の
//    別経路が後から届いても縁の並び順で段数と根拠が変わった（実測
//    `out/tmp-r41/wobble-before.txt` の `r34-fixture` / `demo-order` / `fixture-api`）
//  - `repCands`（閉包の到着）… walk が起点まで遡れる連鎖で届けられなかった行の代表
//    （第 40 ラウンドまでの役割のまま）
// 選び方は両集合で同じ — **親が確定済みの候補だけ**を対象に、確定済み親を持つ候補の
// うち最小をグラフ全体で一番小さいものから順に確定していく（親の確定順）。選び直した
// 一歩は常に「確定済み親の確定経路 + 1 縁」なので、後から何が確定しても連鎖は閉じない。
// 比較の順は:
//  1. walk の候補同士では**段数**（`heapLtWalk`）。閉包の候補は第 40 ラウンドどおり資格順
//  2. `coreCmp`（`repCmp` の接頭辞 6 項目。昇格資格 → 根付き → 定義段数 → 段数 →
//     `apiTail` 旗 → `chain` 旗）
//  3. **根から並べた縁 id の連鎖の辞書順**。第 40 ラウンドまでの第 7 項「根拠の縁 id →
//     親 id」を経路全体へ広げたもの。最後の縁だけを見ると、親のたどりまで同じ候補が
//     並んだときだけ決め手になり、親のたどりが違う同値な対では最後の縁が決め手の資格を
//     持たない（実測 `fixture-api` の `type:ReportImpact.Order`: 最後の縁 id だけだと
//     `Order.Create --creates--> Order` が勝つが、根から並べると
//     `calls:...Handler.Handle->...IOrderRepository.Save` が `calls:...->...Order.Create`
//     より先なので `IOrderRepository.Save --references--> Order` に決まる）
//  4. 向き変え回数 `switches` が少ない順（行の並び順と「一段 / 二段」の区別に合わせる）
//  5. ノード id
// 候補集合は到着順に依らず（第 38 ラウンド）、この比較は全順序で、最後にノード id が
// 来る。よって結果は縁の並び順・到着順に依らない（第 39 ラウンド Astra 裁定
// 「決定論性は絶対」）。探索中の `wiringMap` の中身は触らないので、欄・向き・本命区分の
// 判定材料（`bestState`）も不変。表示の根拠縁と段数だけがこの経路から決まる。
// walk の選び直した一歩が**閉包の候補にも同じ一歩（同じ親・同じ縁）である**ときは
// 閉包側の記録を表示へ使う（`dir` の値だけが食い違うため。向き変え回数 `switches` は
// walk の値を残す。閉包の候補集合は支配の生き残りで到着順に依存して中身が変わるので、
// `switches` をそこから拾うと行の並び順が揺れた。実測 第 33 ラウンド fixture の
// `member:C` と `member:V` の並び）
const rooted = new Set();
const isRooted = (id) => {
  if (rooted.has(id)) return true;
  const stack = []; const seen = new Set();
  let cur = id; let ok = false;
  for (;;) {
    if (rooted.has(cur)) { ok = true; break; }
    if (seen.has(cur)) { ok = false; break; }        // via 連鎖が循環
    const rec = combined.get(cur);
    if (!rec) { ok = false; break; }                 // via が存在しないレコードを指す
    seen.add(cur); stack.push(cur);
    if (!rec.via) { ok = !rec.cut; break; }          // 根（起点そのもの）で着地したか
    cur = rec.via;
  }
  if (ok) for (const n of stack) rooted.add(n);
  return ok;
};
for (const id of combined.keys()) isRooted(id);
// 表示の根そのもの（起点など、`via` 無しで着いた記録）は動かさない。ここを候補で
// 選び直すと「起点 → A → 起点」のように親と子が互いを指して `via` が循環する
const isRootRecord = (id) => {
  const rec = combined.get(id);
  return !!rec && !rec.via && !rec.cut;
};
// 確定済みのノードの「根から並べた縁 id の連鎖」。比較の 2 項目目（辞書順）の材料で、
// 確定は常に「確定済み親 + 1 縁」で進むので親の連鎖を継ぐだけでできる
const picked = new Map();
const chainMemo = new Map();
const chainOf = (id) => {
  const hit = chainMemo.get(id);
  if (hit !== undefined) return hit;
  const rec = picked.get(id) || combined.get(id);
  let acc = '';
  if (rec && rec.via) acc = chainOf(rec.via);
  if (rec && rec.edge) acc += `\u0000${rec.edge.id}`;
  chainMemo.set(id, acc);
  return acc;
};
// 選ぶたびに候補集合を全スキャンすると候補の数千件で二乗のコストになる（実測の主要因）。
// 二分ヒープで保つ。取り出し順は全スキャンと同じ — 上の比較を小さい順に、取り出し時に
// より良い候補へ差し替えられた古い条目を捨てる
const heap = [];
// ヒープの並びに使う比較。`settlePool` が入るときにその回の比較へ差し替える（walk の
// 候補と閉包の候補で先に置く項目が違う。下の `heapLt` と `heapLtWalk`）
let heapCmp = null;
const heapLt = (a, b) => {
  const d = coreCmp(a.c, b.c);
  if (d !== 0) return d < 0;
  const ca = itemChain(a); const cb = itemChain(b);
  if (ca !== cb) return ca < cb;
  const sa = a.sw; const sb = b.sw;   // 向き変え回数は確定値（`settlePool` の `derive`）
  if (sa !== sb) return sa < sb;
  return a.id < b.id;
};
// walk の候補同士は**段数が短い順**を先に置く。行の並び順（`switches` → 段数 → id）と
// 「表示する段数は経路の長さ」という表示の意味を先に守るためで、資格順（`coreCmp`）を
// 先に読むと 第 40 ラウンドまで 1 段だった行が 3 段へ伸びた（実測 `demo-api` の
// `tf:aws_api_gateway_integration.post_order`: 1 段 `references` の行が 3 段 `triggers` へ）。
// 閉包の候補は第 40 ラウンドの資格順（`coreCmp` が先）のままとする
const heapLtWalk = (a, b) => {
  const ha = a.c.rec.hops || 0; const hb = b.c.rec.hops || 0;
  if (ha !== hb) return ha < hb;
  const d = coreCmp(a.c, b.c);
  if (d !== 0) return d < 0;
  const ca = itemChain(a); const cb = itemChain(b);
  if (ca !== cb) return ca < cb;
  const sa = a.sw; const sb = b.sw;   // 向き変え回数は確定値（`settlePool` の `derive`）
  if (sa !== sb) return sa < sb;
  return a.id < b.id;
};
// `from` から確定済みの `via` を辿った先に `target` があるか。確定は常に「確定済み親 + 1 縁」
// で進むので、親の連鎖を見れば循環を確かめられる
const chainCap = Math.max(opts.hops, opts.wiringHops) + 2;
const onPickedChain = (from, target) => {
  let node = from;
  for (let i = 0; node && i < chainCap; i++) {
    if (node === target) return true;
    const rec = picked.get(node) || combined.get(node);
    node = rec ? rec.via : null;
  }
  return false;
};
// 比較の 3 項目目（根から並べた縁 id の連鎖）の文字列は、`coreCmp` が決着をつけたら
// 要らない。アイテムを作るときに組み立てると候補の件数ぶん（実測 elsa-folder で
// 4 万件超）の文字列確保になるので、比較で必要になったとき に 1 回だけ組んで覚える
const itemChain = (it) => {
  if (it.chain === undefined) {
    it.chain = `${chainOf(it.c.rec.via)}\u0000${it.c.rec.edge ? it.c.rec.edge.id : ''}`;
  }
  return it.chain;
};
const hpush = (item) => {
  heap.push(item);
  let i = heap.length - 1;
  while (i > 0) {
    const p = (i - 1) >> 1;
    if (!heapCmp(heap[i], heap[p])) break;
    const t = heap[p]; heap[p] = heap[i]; heap[i] = t; i = p;
  }
};
const hpop = () => {
  const top = heap[0];
  const last = heap.pop();
  if (heap.length) {
    heap[0] = last;
    let i = 0;
    for (;;) {
      const l = 2 * i + 1; const r = l + 1;
      let m = i;
      if (l < heap.length && heapCmp(heap[l], heap[m])) m = l;
      if (r < heap.length && heapCmp(heap[r], heap[m])) m = r;
      if (m === i) break;
      const t = heap[m]; heap[m] = heap[i]; heap[i] = t; i = m;
    }
  }
  return top;
};
// ---- 向き変え回数 `switches` は確定した連鎖から数え直す（第 43 ラウンド指摘 2）----
// walk は到着のたびに `cur.switches`（その時点で先に着いていた経路の値）を候補へ凍結していた。
// `found` の記録は `mergeFlags` で**向き（`mdir`）は先着のまま・回数だけ最小**へ寄せるので、
// 実在しない経路の値（`mdir: 'out'` なのに `switches: 0`）が 2 段目の種とそこから届く候補に
// 混ざる。それを凍結したままにすると、表示経路が同じなのに向き変え回数だけが縁の並び順で
// 揺れた（実測 `out/tmp-r43/r42-calls-0.json` / `-1.json`: 表示経路はどちらも
// `N0 → N1 → N6 → N2` に決まるのに `member:N2` の `switches` だけ 0 / 1 に割れる。
// 検査 out/tmp-r43/r43-permute.py は第 42 ラウンド版で 2 通りになることを示す）
//
// 向き変え回数は「親の確定した連鎖から決まる値」なので、確定の段で親の確定済み連鎖から
// 数え直す（到着時に凍結しない）。選び直しの比較（`heapLt` / `heapLtWalk`）が読むのも、
// 表示が読むのもこの確定値で、**読む項目と順序は変えない**
const settledSw = new Map();   // 確定済みのノード id -> 根から数えた向き変え回数
// この一歩がどの向きで縁を渡った一歩か。**表示に使う縁の端点から決める** — walk が持つ機械的な
// 向き `mdir` は到着した経路ごとの値で、`mergeFlags` が向きだけ先着のまま残すと実在しない組合せ
// （`mdir: 'out'` なのに親は別経路）になり得る。端点から決めれば同じ一歩（同じ親・同じ縁）は
// どの到着から来ても同じ向きになる（実測 `out/tmp-r43-review/switch-a.json` の 5 ノードで
// `mdir` を読んだ版は `switches` が 2 / 1 に割れた。双人レビュー第 43 ラウンド指摘 2）
const stepDirOf = (rec) => (rec ? endpointDirOf(rec.id, rec.edge) : null);
// 1 歩が向きを変えているか。walk の展開と同じ規則で見る — 親の一歩の向きと違い、かつ
// 対応付け（注釈）の縁のときだけ数える。機械的な向きを持たない一歩（Terraform の定義を
// 無方向に閉じる閉包の一歩）は向きを変えない（下の `switchCount` がそこで打ち切る）
const stepSwitches = (parentRec, rec) => {
  const d = stepDirOf(rec);
  const p = stepDirOf(parentRec);
  if (!d || !p || d === p) return 0;
  // 対応付け（注釈）の縁を渡る向き替えは数えない（walk の展開と同じ）。**この一歩の縁の
  // 由来**で決める。第 44 ラウンドまで持っていた記録の `corr` は `mergeFlags` が同じノードへ
  // 届いた別の一歩の値を引き継ぐ（論理和）ので、表示の一歩が注釈縁でなくても true になり
  // 向き変え回数が割れた（実測 `member:Mid → member:C` の `calls`（static）の行が、別経路の
  // `invokes`（human）との合流で `corr: true` になった）。記録の `corr` は第 45 ラウンドで削除
  if (rec.edge && CORRESPONDENCE.has(rec.edge.provenance)) return 0;
  return 1;
};
// `id` の一歩から根へ向かって `via` を辿った連鎖の向き変え回数。各一歩の向きは**表示に使う
// 縁の端点**から決める（上の `stepDirOf`）ので、walk の到着から作った記録でも閉包の到着から
// 作った記録でも同じ一歩は同じ向きになる。縁の無い一歩（起点）で打ち切る。
// `lookup` は経路の記録の引き方（選び直し中は `picked` を優先し、表示は `combined`）。
// `done` は確定済みの値の表（無くても数えられるが、確定値があればそこから）
const switchCount = (id, lookup, done) => {
  const seen = new Set();
  let total = 0;
  let cur = lookup(id);
  for (let i = 0; cur && i <= chainCap; i += 1) {
    if (done) {
      const hit = done.get(cur.id);
      if (hit !== undefined) return total + hit;
    }
    if (!cur.edge) break;   // 起点など、縁の無い一歩で打ち切る（これより上に数える材料はない）
    const p = cur.via ? lookup(cur.via) : null;
    total += stepSwitches(p, cur);
    if (!p || seen.has(cur.id)) break;        // `via` が循環している（あってはならない形）
    seen.add(cur.id);
    cur = p;
  }
  return total;
};
// 候補の一歩の向き変え回数。`settlePool` は親が確定した候補だけを見るので、親の確定値に
// この一歩の向き変えを足したものが確定値になる。親が土台（選び直さないノード）のときは
// その `combined` の連鎖を同じ規則で根まで数える
const deriveWalkSwitches = (id, c) => {
  const lookup = (x) => picked.get(x) || combined.get(x);
  return switchCount(c.rec.via, lookup, settledSw) + stepSwitches(lookup(c.rec.via), c.rec);
};
// `items` は [ノード id, 候補の並び]。`settled` は確定済み（土台）のノードで、選び直して
// はいけないノードは呼び出し側が `items` から除いてある。ここは確定済みの親を持つ候補
// だけを見て、確定のたびに子を見に行く（第 40 ラウンドと同じ形）
// `derive(id, c)` はこの一歩の表示用の値（向き変え回数）を**親の確定済み連鎖から**決める関数。
// 渡さない候補集合（閉包の一歩）は記録の値をそのまま使う
const settlePool = (items, settled, lt, derive) => {
  heapCmp = lt;
  const byParent = new Map();
  for (const [id, list] of items) {
    if (settled.has(id)) continue;
    for (const c of list) {
      // 循環境避で切った一歩（`via = null`）は起点へ遡れないので確定の土台にしない
      if (!c.rec.via) continue;
      if (!byParent.has(c.rec.via)) byParent.set(c.rec.via, []);
      byParent.get(c.rec.via).push([id, c]);
    }
  }
  const tentative = new Map();
  const considerCand = (id, c) => {
    // 親の確定経路に自分自身が既にいる候補は使わない。循環境避で切った一歩も表示候補へ
    // 数えるので（上の `addWalkCandidate`）、この対が起こり得る。通すと `via` が循環して
    // 起点へ遡れなくなる。連鎖の長さは walk が `opts.hops`、閉包が `opts.wiringHops` で
    // 打ち切るので、それより長くなることは無い（超えたら壊れている = 使わない）
    if (onPickedChain(c.rec.via, id)) return;
    // 連鎖の文字列は比較で必要になった時に組む（`itemChain`）。`sw` は見込みの確定値で、
    // 親が確定した時点で決まる（=`derive`）。決まらない候補はここに来ない
    const item = { id, c, sw: derive ? derive(id, c) : c.rec.switches || 0 };
    const cur = tentative.get(id);
    if (!cur || lt(item, cur)) { tentative.set(id, item); hpush(item); }
  };
  const picks = new Map();
  for (const [p, entries] of byParent) {
    if (settled.has(p)) for (const [id, c] of entries) if (!settled.has(id)) considerCand(id, c);
  }
  while (heap.length) {
    const item = hpop();
    if (tentative.get(item.id) !== item) continue;   // より良い候補に差し替え済みの古い条目
    tentative.delete(item.id);
    if (settled.has(item.id)) continue;
    settled.add(item.id);
    settledSw.set(item.id, item.sw);   // 確定値（子の一歩の向き変え回数を数え出す起点）
    picks.set(item.id, item.c.rec);
    picked.set(item.id, item.c.rec);
    for (const [nid, nc] of byParent.get(item.id) || []) if (!settled.has(nid)) considerCand(nid, nc);
  }
  return picks;
};

// ---- 1. walk が起点まで遡れる連鎖で届けた行を、walk の到着から選び直す ----
// 選び直さないノード（walk の候補に親のある一歩が無いノード。閉包の記録だけで着いたノード
// など）は、起点まで遡れるなら土台としてそのまま残す。walk の候補は `repCands` と違って
// 定義段数を持たないので、閉包の候補と同じ集合で比べることはない
// 選び直し対象は「今 `combined` に乗っている一歩が walk の到着として候補にあるノード」。
// 自分の現レコードの一歩が候補に無いノード（レコードを Terraform の閉包や 2 段目の種が
// 作ったノード）は walk の候補では再現できないので土台にし、現レコードを残す
// （実測 `fixture-api` の `member:ReportImpact.Handler.Handle`: 2 段目の種で、候補は自分の
// 子たちから戻ってくる一歩だけ。ここを土台にすると子 12 ノードが軒並み選び直しできなく
// なった。検査 out/tmp-r41/pool-dump2.py）
const repKey = (rec) => `${rec.via || ''}\u0000${rec.edge ? rec.edge.id : ''}`;
const walkItems = [];
let dupKeys = 0;   // 選び直し候補に見た (親, 縁 id) の重複
for (const [id, list] of walkCands) {
  // 候補が 1 件なら選び直しても今と同じ一歩が選ばれるだけなので対象外（土台のまま）。
  // 実測 elsa-folder で 21,455 ノード中 2,393 ノードだけが候補 2 件以上だった
  // （実体比較で重複排除が効いていなかった第 42 ラウンドまでは 3,935 件）
  if (list.length < 2) continue;
  const rec = combined.get(id);
  if (!rec || !rec.via || !rooted.has(id)) continue;
  // 今の表示の一歩が walk の到着に無いノード（Terraform の閉包や 2 段目の種が作った記録）は
  // walk の候補では再現できないので土台にし、現レコードを残す。（縁の対応は **縁 id** で見る。
  // 実体比較だと上の重複排除と同じで 1 件も突き合わず、選び直し対象が正しく決まらない）
  if (!list.some((c) => c.rec.via === rec.via && edgeIdOf(c.rec.edge) === edgeIdOf(rec.edge))) continue;
  // 候補は (親, 縁 id) で 1 件ずつのはず（上の `addWalkCandidate`）。重複が残っていると
  // 選び直しの比較が**同じ一歩の別実体**を並べて並び順で決めることになる（第 43 ラウンド
  // 指摘 1）。黙らずに出す（`stranded` の警告と同じ方針。実測は out/tmp-r43/dedup-count.py）
  const seenKeys = new Set();
  for (const c of list) {
    const k = repKey(c.rec);
    if (seenKeys.has(k)) dupKeys += 1; else seenKeys.add(k);
  }
  walkItems.push([id, list]);
}
// 土台（選び直さないノード）は「根そのもの」と上記のノード。加えて、候補の連鎖がどの土台へも
// 届かないノードを土台へ足す固定点を取る。届かないノードを土台にせず残すと、その子が親を
// 待てずに選び直せず、子の子へ波及する。土台は `combined` の現レコード（起点まで遡れる）を
// そのまま使うので表示は壊れない。選び直しできない行は第 40 ラウンドどおり閉包の候補に任せる
const walkRepick = new Set(walkItems.map(([id]) => id));
// 土台は「選び直されないノード」すべてではない。今の `combined` の連鎖が選び直し対象を横切る
// ノード（候補が 1 件だけで、親が選び直し対象になっているノード）を土台にすると、その子は
// 親の確定前に `considerCand` され、**確定前の連鎖**から向き変え回数と連鎖の文字列を計算して
// 凍結する（双人レビュー第 43 ラウンド agy 指摘 1。10 ノードの反例で表示経路が同じなのに
// `switches` が 2 と 0 に割れた）。そのようなノードは土台にせず、今の表示の一歩を単一候補として
// 選び直しへ参加させ、親の確定を待たせる
const baseState = new Map();   // id -> true 土台 / false 親の確定を待つ
const baseDecide = (start) => {
  const stack = [];
  const seen = new Set();
  let cur = start;
  let val = false;
  for (;;) {
    const known = baseState.get(cur);
    if (known !== undefined) { val = known; break; }
    if (seen.has(cur)) { val = false; break; }          // 連鎖が循環（あってはならない形）
    seen.add(cur);
    if (walkRepick.has(cur)) { val = false; break; }    // 連鎖が選び直し対象を横切る
    const rec = combined.get(cur);
    if (!rec) { val = false; break; }                   // 連鎖が記録の外へ出た
    if (!rec.via) { val = true; break; }                // 根（起点など）へ届いた
    stack.push(cur);
    cur = rec.via;
  }
  for (const n of stack) if (!baseState.has(n) && !walkRepick.has(n)) baseState.set(n, val);
  if (!walkRepick.has(start)) baseState.set(start, val);
  return val;
};
const settledWalk = new Set();
for (const id of rooted) {
  if (walkRepick.has(id)) continue;
  if (baseDecide(id)) { settledWalk.add(id); continue; }
  const rec = combined.get(id);
  // 単一候補の条目として選び直しへ入れる。選ばれる一歩は今と同じなので表示は変わらない
  // （この条目が選ばれると `picked` と `combined` へ同じ記録を書き戻す）
  if (rec && rec.via && rooted.has(rec.via)) walkItems.push([id, [{ rec }]]);
  else settledWalk.add(id);   // 親が根に届かないなら待つ先が無いので土台（下の警告で出る）
}

for (;;) {
  const reach = new Set(settledWalk);
  let grew = true;
  while (grew) {
    grew = false;
    for (const [id, list] of walkItems) {
      if (reach.has(id)) continue;
      if (list.some((c) => !!c.rec.via && reach.has(c.rec.via))) { reach.add(id); grew = true; }
    }
  }
  const add = [...rooted].filter((id) => !reach.has(id));
  if (!add.length) break;
  for (const id of add) settledWalk.add(id);
}
const baseWalk = new Set(settledWalk);
// 表示に書く一歩の連鎖を、確定の段と同じ規則で根まで数える（`deriveWalkSwitches` と同じ組み方
// で、数え出す一歩を引数で受け取る）。`settlePool` が確定できなかった行の受け皿
const walkChainSwitches = (r) => {
  const lookup = (x) => picked.get(x) || combined.get(x);
  return switchCount(r.via, lookup, settledSw) + stepSwitches(lookup(r.via), r);
};
const walkPick = settlePool(walkItems, settledWalk, heapLtWalk, deriveWalkSwitches);
for (const [id, rec] of walkPick) {
  // walk の選び直した一歩（同じ親・同じ縁）が閉包の候補にもあるなら、**閉包側の記録**を
  // 表示に使う。経路は同じなのに walk 側は `dir`（表示の向き）だけ違う値を持つからで、
  // walk は 2 段目の種から同じ定義へ入り直すと「辿った向き」を持つ（実測 v1 との差分
  // `demo-api` の `tf:aws_api_gateway_resource.orders_path` / `tf:aws_api_gateway_rest_api.orders`:
  // 1 段 `references` の 向き が in → out へ動いた）。閉包側に無い一歩（コードを歩いた行）は
  // walk の記録がそのまま表示になる
  const key = repKey(rec);
  let alt = null;
  for (const group of (repCands.get(id) || { groups: [] }).groups.values()) {
    for (const c of group) {
      if (repKey(c.rec) !== key) continue;
      // `coreCmp` の 6 項目（昇格を止めたか / 循環境避 / 予算 / 段数 / API の定義尾根 / 連鎖旗）が
      // 同値で、しかも (親, 縁) も土台と同じなら、**表示が読む項目はすべて同一**（表示は
      // `displayFacts` の通り (親, 縁) と `coreCmp` の項目しか読まない）。同じ (親, 縁) の候補が
      // 2 件並ぶ形は上の `dupKeys` で警告する異常形で、実測 18 レポートは 0 件。第 45 ラウンドまで
      // ここで 記録の `dir`（旧・表示用の向き）を最終タイブレークに読んでいたが、記録の `dir` が
      // 機械的な 辿った向き になった今は同じ一歩では必ず同値になるので比較を外した
      const d = alt ? coreCmp(c, alt) : -1;
      if (d < 0) alt = c;
    }
  }
  // 向き変え回数は確定の段で数え直した値（`settledSw`）を乗せる。候補が持っていた到着時点の
  // 値（親の先着経路の値。`mergeFlags` で `mdir` と対応の取れない寄せ方をした混ざり得る）は
  // 表示で見ない。親が確定しなかった行（候補の連鎖がどの土台にも届かなかった行）も同じ規則で
  // 表示に書く一歩から根まで数え直す — ここを凍結値のままにすると、実測 demo-api の
  // `tf:aws_api_gateway_rest_api.orders` のように「表示経路は向きを変えていないのに 1」と
  // いう行が残る（検査 out/tmp-r43/flip-proof.py）
  const sw = settledSw.has(id) ? settledSw.get(id) : walkChainSwitches(rec);
  combined.set(id, alt ? { ...alt.rec, switches: sw } : { ...rec, switches: sw });
}
if (dupKeys) {
  process.stderr.write(`[report] 警告: walk の選び直し候補に同じ (親, 縁) の重複が ${dupKeys} 件残りました\n`);
}
// 候補集合は選び直し対象の並びが実体を握っているので、集合そのものは用済み（実測
// elsa-folder で候補 7.8 万件。表示の組み立てと JSON 化の前に捨てて、合流が眺める実体を減らす）
walkCands.clear();
const walkMiss = walkItems.filter(([id]) => !baseWalk.has(id) && !walkPick.has(id)).length;
if (walkMiss) {
  // walk の候補に親のある一歩があり、土台でもないのに起点へ繋がらなかった行。第 40 ラウンドの
  // `stranded` と同じく黙って打ち切らない（検査 out/tmp-r40/via-cycle.py が失敗するので隠れない）
  process.stderr.write(`[report] 警告: ${walkMiss} ノードの walk 経路を起点へ繋げませんでした\n`);
}

// ---- 2. walk が起点まで遡れなかった行を、閉包の到着から選び直す（第 40 ラウンドまでと同じ）----
const closureItems = [];
for (const [id, entry] of repCands) {
  if (rooted.has(id)) continue;
  const list = [];
  for (const group of entry.groups.values()) for (const c of group) list.push(c);
  closureItems.push([id, list]);
}
const displayPick = settlePool(closureItems, new Set(rooted), heapLt);
const stranded = [];
for (const [id] of repCands) {
  if (rooted.has(id)) continue;
  if (displayPick.has(id)) combined.set(id, { ...displayPick.get(id) });
  else stranded.push(id);
}
if (stranded.length) {
  // どの候補の親も起点に届かないノードは表示を壊したまま残す。黙って打ち切った経路を
  // 出さないための警告（検査 out/tmp-r40/via-cycle.py と test-report.mjs が失敗するので隠れない）
  process.stderr.write(`[report] 警告: ${stranded.length} ノードの表示経路を起点へ繋げませんでした（打ち切りのまま残します）\n`);
}

// 表示する向き変え回数。**表示に決まった連鎖だけの関数**として、行を組み立てる直前に数え直す。
// 選び直しの途中で確定した値（`settledSw`）は比較の材料として使うが、表示へは乗せない —
// 閉包側の記録への差し替え（上の `alt`）で `via` の連鎖は行の組み立て直前まで動くし、
// 選び直せなかった行（土台・閉包だけ）は確定値を持っていない。確定値を表示に使うと、表示経路が
// 同じなのに値だけ縁の並び順で揺れる（双人レビュー第 43 ラウンド指摘 2）。ここを通すと
// 表示される連鎖に向きの変え方が 2 回ある行は正直に `2` と出る（walk は 1 回の予算でしか歩かない
// ので、そうした経路は選び直しが独立に親を選び直した結果として組み上がった連鎖であり、walk が歩いた
// 経路そのものではない。段数・根拠・欄は変えない）
const displaySwitches = (id) => switchCount(id, (x) => combined.get(x), null);

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
// ---- 1 歩の 向き（表示）。第 46 ラウンド Astra 裁定（`out/review-astra46.log`）----
// 表示の 向き は表示経路を**根からフォールド**して決める。起点の 向き は `none`
// （起点そのものには 向き が無い）で、各一歩は次のどれか。
//  (1) **動きの縁**（`triggers` / `invokes` / `handler` / `exposed-by`）の一歩 → 縁の矢印の先が
//      下流。`exposed-by` は矢印が逆（コード → 公開するもの）なので矢印の元側が下流になる。
//      **実装側へ入る例外（`handler` / `exposed-by` を逆向きに越える一歩）はこの枝の中にだけ
//      ある**（裁定 (a-2): 「既存の実装側へ入る例外は規則 1 に限定してください」）
//  (2) **無方向の定義縁** → 直前の 向き をそのまま継承する（最初は `none` のまま）。
//      継承するのは「定義閉包で、向きを意味として採用しない縁」だけ。判定式は
//      `provenance === 'terraform'` かつ 動きの縁でないこと。
//      根拠は縁の**由来**ではなく関係の意味で、「無方向の隣接表（`tfAdj`）に登録されているから」
//      ではない — `tfAdj` は到達対象を両方向に探すための隣接表で、**動きの縁も登録されている**
//      （`handler` / `triggers` / `invokes` が通る）。到達を両方向に探すことと、表示上でその
//      矢印に意味を持たせないことは別（裁定 (a)）
//  (3) その他の一歩（静的解析と注釈が結んだ**向きを持つ縁**。`calls` / `writes` / `reads` /
//      `accesses` / `creates` / `deploys` / `project-reference` など）→ その縁の矢印で決める。
//      裁定 (a-2) は有向縁の矢印を優先するので、**`down`（実装側に入った旗）による上書きは
//      向き決定から外した**。実測 `demo-api` の `Orders.Api.csproj` は最後の縁が
//      `project --deploys--> Lambda` で Lambda 側から辿った行なので 上流（`in`）。
//      「起点 API の実装に関係する成果物」であることを理由に矢印を反転させない
//      （`down` 優先の版だと `artifacts.out` になった。裁定の表どおり `artifacts.in`）
// 有向縁の判定に縁の端点是使えるが、**無方向の一歩の 向き を端点から作ることはしない**
// （裁定 (b): 無方向と決めた縁から最初の一歩だけ方向を作る根拠が無い）。端点から決まる
// `stepDirOf` は `switches`（向き変え回数）の相対比較にだけ使う
const dirOfStep = (id, edge, inherited) => {
  if (!edge) return inherited;
  if (MOVEMENT.has(edge.kind)) {
    if (arrowAt(edge, id)) return 'out';
    // `handler` / `exposed-by` は「実装の対応」を表す縁で、呼び出し元を示さない。起点が
    // API エンドポイントなら、その対応縁で繋がる側（実装を載せた Lambda など）も下流側。
    // ここを矢印だけで 影響を受ける入口 にすると、起点のエンドポイント自身の
    // 実装 Lambda が「呼びにくる側」に並んだ（実測: demo の `--api "POST /orders"` で
    // `orders_api` と `notify` が 影響を受ける入口 に移った）
    if (FLIP_INTO_IMPL.has(edge.kind) && startIsEndpoint) return 'out';
    return 'in';
  }
  // (2) 無方向の定義縁。`none` でもそのまま返す（無方向の一歩は最初も途中も同じ規則）
  if (edge.provenance === 'terraform') return inherited;
  // (3) 向きを持つ縁は自分の矢印で決める
  return arrowAt(edge, id) ? 'out' : 'in';
};
// ---- 表示値は「表示に確定した連鎖」だけを根から読む（第 45 ラウンド Astra 裁定・案 D）----
// 裁定（`out/review-astra45.log`）: 表示する値は、表示に確定した連鎖（`combined` の `via` を親へ
// 辿った列）だけから決める。**別経路に動きの縁があればそれを読む**規則は捨て、欄・向き・段数・
// 対応を同じ経路から再計算する。探索が別経路から寄せた値は表示へ読まない —
//  - `bestState` の動きの根拠の 4 枠（第 44 ラウンドまであった。到着 / 循環境避 × 対応縁 / 流れの縁
//    の組み合わせ）: 枠のどれに入るかは `onChain` の循環境避判定が**先着の連鎖**を読むので縁の並び順で変わる。実測
//    `out/tmp-r44/min2-1.json`（4 ノード 4 縁）は表示経路がどちらの縁順でも `N0 ←e3← N4` の
//    1 段・根拠縁も `e3` で同じなのに、別経路の `e0` が到着の枠に入る並びだけ 動きの根拠 が `e0` に
//    なり、`向き` と 欄 まで入れ替わった（min2-0〜min2-5 と min-3 の計 7 例）
//  - `mergeFlags` が論理和で引き継いだ `corr`: 同じノードへ届いた**別の一歩**の注釈縁を真にする。
//    実測 `out/tmp-r44/min-0.json`（6 縁）は縁の 720 とおりの半数で `member:N2` の 対応 が反転し、
//    `summary.correspondenceRows` が 4 / 3 に割れた
//  - 機械的な `mdir` / `info.dir`: `mergeFlags` は向きを先着のまま残すので、実在しない一歩の
//    向きが混ざる（第 43 ラウンド実測 `out/tmp-r43-review/switch-a.json`）
// 循環は `seen` で打ち切り、上限は選び直しと同じ `chainCap`、`edge` の無い一歩（起点）で打ち切る。
// `tier`（本命 / 定義上）だけは受理事実（`bestState`）のままでよい — 「別経路に昇格の一歩が
// あったか」は縁順に依らない事実なので、ここは表示経路の純関数にしない（裁定の「据えてよいもの」）
const displayFacts = (id) => {
  // `via` を親へ辿った列を**根から順**に並べる（walk と閉包の一歩が混ざっても同じ読み方をする）
  const chain = [];
  const seen = new Set();
  let cur = combined.get(id);
  for (let i = 0; cur && i <= chainCap; i += 1) {
    if (seen.has(cur.id)) break;              // `via` が循環している（あってはならない形）
    seen.add(cur.id);
    chain.unshift(cur);
    if (!cur.edge) break;                     // 縁の無い一歩（起点）で打ち切る
    cur = cur.via ? combined.get(cur.via) : null;
  }
  // 対応は表示経路に含まれる注釈縁（`llm` / `human`）の論理和
  let correspondence = false;
  // 表示の 向き は連鎖を**根から受け継ぐ**（第 46 ラウンド裁定）。起点の 向き は `none`
  // （「この表示経路に、向きを決める関係が無い」）。端点から 向き の種を作らないので、
  // Terraform の定義の縁だけの連鎖は `none` のまま残る（裁定 (b)・(c)）
  let dir = 'none';
  for (let i = 1; i < chain.length; i += 1) {
    const rec = chain[i];
    const e = rec.edge;
    if (CORRESPONDENCE.has(e.provenance)) correspondence = true;
    dir = dirOfStep(rec.id, e, dir);
  }
  const last = chain[chain.length - 1];
  const edge = last ? last.edge : null;
  // `呼ばれて成立` は**当該ノードへ入る最終一歩**だけを見る（walk の `calledOut` と同じ条件）。
  // 同じ API の定義同士の `invokes`（method → integration）は旗を立てない
  const reachedByInvokes = !!(edge && edge.kind === 'invokes' && last.via && arrowAt(edge, id)
    && !internalInvokes(last.via, id));
  return {
    edge,
    // 動きの根拠は表示経路に実際に含まれる縁だけから選ぶ。表示経路の最後の 1 本（当該ノードへ
    // 入る一歩）が動きの縁のときそれ、そうでなければ無し
    movementEvidence: edge && MOVEMENT.has(edge.kind) ? edge : null,
    // 向き は上の連鎖を根から順に読んで決めた値をそのまま出す（規則は `dirOfStep`）。
    // 機械的な `mdir` / `info.dir` は読まない。`none` は「この表示経路に、向きを決める関係が
    // 無い」で、「このノードに他の有向関係が無い」意味ではない（第 46 ラウンド裁定 (c)）
    direction: dir,
    reachedByInvokes, correspondence,
  };
};
const rows = [];
for (const [id, info] of combined) {
  if (!info.edge || insideStart(id)) continue;
  const { path: p, root } = pathOf(id);
  // 表示値（動きの根拠 / 実装側 / 呼ばれて成立 / 対応 / 一歩の向き）は上の `displayFacts` が
  // **表示に確定した連鎖だけ**から作る。受理済みの事実（`bestState`）と記録の寄せ値は
  // 表示へ読まない（第 45 ラウンド Astra 裁定・案 D）
  const facts = displayFacts(id);
  // 本命か（`tier`）だけが受理事実を見る。本命は「別経路に昇格の一歩があったか」で決まるので
  // 表示経路の純関数ではない（裁定で据えてよいとされた項目）
  const st = bestState.get(id);
  rows.push({
    // 向きは `displayFacts` が表示経路を根から順に読んで決めた値（規則は `dirOfStep`）
    direction: facts.direction,
    id, name: label(id), kind: byId.get(id).kind, category: category(id),
    resourceType: (byId.get(id).metadata || {}).resourceType || null,
    endpoint: endpointOf(byId.get(id)),
    // 表示する段数は**経路の長さ**。探索側が持つ段数は「定義単位をまたいだ数」で、
    // 動きの縁を越えたら数え直す予算なので、そのまま出すと `path` と食い違った
    // （実測: demo の `--api` で 1 行が 8 段 / 経路 6 ノード）
    hops: p.length - 1, switches: displaySwitches(id),
    // 対応は**表示経路全体の注釈縁の有無**（経路内の縁の論理和）。記録の `corr` は
    // `mergeFlags` が同じノードへ届いた別の一歩の値を引き継ぐので読まない（第 45 ラウンド裁定）
    correspondence: facts.correspondence,
    pathRoot: root, via: info.via || null,
    // 動きの根拠は表示経路に実際に含まれる縁だけ（`displayFacts`）。別経路で動きの縁が見つかって
    // いてもここへ出さない。表示の根拠（`evidence`）と同じ 1 本が動きの縁のときだけ、その 1 本が出る
    movementEvidence: facts.movementEvidence,
    // 本命かどうかも受理済みの事実で決める（経路を切った行が定義上の関連に落ちないようにする）
    // 未受理の行は record 自身で決める。`wiring` だけでなく**連鎖に入っているか**も見る。
    // `wiring` は一歩ごとの昇格停止なので、親が連鎖外でも false になれる。実測: 起点の
    // エンドポイントの実装が呼ぶ `Shared()` から呼び出し元 200 個が 影響を受ける入口 の
    // 本命に並んだ（昇格は `promote` で止まっても、record をそのまま見たここで本命になっていた）
    tier: (st ? st.primary : (info.wiring !== true && info.chain !== false)) ? 'primary' : 'wiring',
    // 起点が API エンドポイントのとき、method / resource / rest_api / integration / deployment は
    // **起点となる API 自身を定義している**ので「影響を受ける外部リソース」に数えない
    sameApi: startIsEndpoint && !endpointOf(byId.get(id)) && startApiGroups.has(apiGroupOf(byId.get(id))),
    reachedByInvokes: facts.reachedByInvokes, evidence: info.edge, path: p,
  });
}
rows.sort((a, b) => a.switches - b.switches || a.hops - b.hops || a.id.localeCompare(b.id));
const byDirection = (d) => rows.filter((r) => r.direction === d);
// 向き が `none` の行（第 46 ラウンド裁定 (c）。意味は「この表示経路に、向きを決める関係が
// 無い」で「このノードに他の有向関係が無い」ではない）。方向を持つ欄（外部 / コードの入口 /
// 成果物の 先・受）に並べると in / out の意味をでっち上げることになるので中立欄へ寄せる。
// 中立欄（同じ API の定義・同じコードを使う別の API）はそのまま、それ以外は `tier` を保ったまま
// 「定義上の関連」で受ける（裁定: 判定を `tier === 'wiring'` に限定しない。実測で
// `tier === 'primary'` の `none` 行が出る）
const directionless = (r) => r.direction === 'none';
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
// ---- 兄弟欄の行に**理由コード**を立てる（双人レビュー第 30 ラウンド指摘 F）----
// 既定の一覧表示をやめたので、JSON だけで読んだ人が「この行は何なのか」を理由まで
// 分かるようにする。`shared-code-endpoint` は同じコードを実装している別のエンドポイント、
// `sibling-api-definition` はそのエンドポイントを定義している resource / rest_api など
for (const r of rows) {
  if (isSiblingEndpoint(r)) r.siblingReason = 'shared-code-endpoint';
  else if (siblingGroupOf(r)) r.siblingReason = 'sibling-api-definition';
}
// 定義上の関連 = 他の枠（本命の外部リソース / コードの入口 / 同じ API の定義 / 兄弟）に
// 入らなかった行の引き取り手。ここに条件を足し忘れると行がどこにも出なくなるので、
// 「本命として列挙した行」だけを明示的に除外する形にする。`向き` が `none` の行は
// 方向を持つ欄に列挙しないので、ここでも「列挙済み」に数えない（数えると行がどこにも出ない）
const listedElsewhere = (r) => !directionless(r) && r.tier === 'primary' && !r.sameApi && !isSibling(r)
  && (isExternal(r.id) || r.kind === 'member' || r.kind === 'type');
// リポジトリ内の**成果物**（プロジェクト・ファイル・フォルダ・solution）。外部リソースでも
// コードの入口でもないので「定義上の関連」に混ぜない。混ぜると csproj が本命なのに
// 「変更で値が動かなくても見直しの候補」と書かれた欄に並ぶ（双人レビュー P2）
const ARTIFACT_KINDS = new Set(['project', 'file', 'folder', 'solution']);
const isArtifact = (r) => ARTIFACT_KINDS.has(r.kind);
const artifactRows = (rs) => rs.filter((r) => !isApiDefinition(r) && !isSibling(r) && !listedElsewhere(r) && isArtifact(r));
// 成果物欄は 先・受 の 2 欄だけで 向き を持つ行しか置けない。向き が `none` の成果物の行は
// ここから落ちるとどの欄にも入らなくなるので「定義上の関連」で受ける
const wiringRows = () => rows.filter((r) => !isApiDefinition(r) && !isSibling(r) && !listedElsewhere(r)
  && (!isArtifact(r) || directionless(r)));
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
  // （第 46 ラウンド裁定 (c): 向き を決める関係が無い行 `none` も値域なので、それを指定できる。
  // both は 向き の有無で絞り込まないので、none の着地を方向別フィルターで落とさない）
  const dir = ['in', 'out', 'none'].includes(spec.direction) ? spec.direction : 'both';
  const list = dir === 'both' ? rows.filter((r) => r.tier === 'primary' && !r.sameApi && !isSibling(r))
    : primaryRows(byDirection(dir));
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
// ---- 対応未確定の候補であることを**行ごとに**残す（第 29 ラウンドの裁定） ----
// HTTP 動詞を含む直接参照も注釈もない API Gateway の定義は、メソッドと統合の対応を入力から
// 確認できないので本命にしない。代わりに 本命にしないこと を黙らせず、行に短い理由を立てて
// サマリの 1 行でまとめて教える（理由が画面から消えると「影響がない」と誤読される）
const UNRESOLVED_REASON = '対応未確定：HTTP動詞・メソッドへの直接参照なし';
const UNRESOLVED_WARNING = '対応未確定の関連があります。メソッドと統合の対応を入力から確認できないため、'
  + '候補を「定義上の関連」に表示しています。';
for (const r of rows) {
  r.unresolvedCorr = r.tier === 'wiring' && !!r.resourceType && INTEGRATION_TYPES.has(r.resourceType)
    && !methodCorrKnown.has(r.id);
  // 理由を**行のデータ**として残す。Markdown の注記だけだと JSON を独力で読んだ人が
  // 「なぜ 本命 でないのか」を説明できない（双人レビュー第 30 ラウンド指摘 F）
  if (r.unresolvedCorr) r.unresolvedCorrReason = 'no-method-correspondence';
}
const unresolvedCorrRows = rows.filter((r) => r.unresolvedCorr);
// JSON の一覧は `--limit` で切り詰める。だから「欄の合計 == 総行数」の不変条件は
// **カウンタ側**（`summary` の各欄）に対して見る。一覧が切れているときは
// `listTruncated` を true にして、切り詰めを隠さない
// ---- JSON 単体で「どの欄の、なぜこの行なのか」が読めるようにする（双人レビュー第 30 ラウンド指摘 F）----
// 既定の一覧表示を件数だけに絞ったので、画面に出ない分は JSON で理由まで読める必要がある。
// `bucket` は実際に印刷した欄名と同じ文字列を入れる（`tier` は内部の昇格状態なので、兄弟欄に
// 寄せた行が `primary` をそのまま持つことがあり、それだけだと「本命なのに別欄に並んでいる」ように
// 見える。欄名が正しいので欄名を立てる）
const BUCKET_NAMES = [['external.out', () => externalRows(outRows)], ['external.in', () => externalRows(inRows)],
  ['entries.out', () => entryRows(outRows)], ['entries.in', () => entryRows(inRows)],
  ['artifacts.out', () => artifactRows(outRows)], ['artifacts.in', () => artifactRows(inRows)],
  ['sameApi', () => sameApiRows()], ['siblingEndpoints', () => siblingRows()], ['wiring', () => wiringRows()]];
const bucketById = new Map();
for (const [name, get] of BUCKET_NAMES) for (const r of get()) bucketById.set(r.id, name);
for (const r of rows) r.bucket = bucketById.get(r.id) || null;

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
  // **向き を決める関係が無い行**（`direction === "none"`。第 46 ラウンド裁定 (c)）の件数。
  // 方向別のカウンタ（`primaryIn` / `primaryOut` / `entryIn` / `entryOut` / `artifactsIn` /
  // `artifactsOut`）は `none` の行を数えないので、ここを出さないと「黙って消えた」ように読める
  directionless: rows.filter(directionless).length,
  // `none` の行のうち **本命 の資格を持っていた行数**。欄は「定義上の関連」へ寄せるが
  // `tier` は保つ（裁定: 判定を `tier === 'wiring'` に限定しない）
  directionlessPrimary: rows.filter((r) => directionless(r) && r.tier === 'primary').length,
  // **向きを変えて届いた行の数**（`switches` が 1 以上の行）。向き変え回数は表示に決まった
  // 根拠経路の属性なので、選び直しが組み上げた経路は walk の探索予算（1 回）を超えることがある
  // （実測 fixture-api で 15 行が 2 回。Astra 裁定 A、`out/review-astra44.log`）。かつては
  // `switches === 1` を数えていたため、2 回以上の行を「向きを変えていない」側へ落としていた。
  // 欄の名前は v1 の出力契約のまま残す（`--json` を読む側を壊さない。意味はここで決める）
  secondOrder: rows.filter((r) => r.switches >= 1).length,
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
  // 対応未確定のまま 定義上の関連 に出している行の件数（0 なら警告行を出さない）
  unresolvedCorr: unresolvedCorrRows.length,
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
// 向き の表内表記。JSON の `direction` をそのまま出さず日本語のラベルに落とす。
// `none` は「この表示経路に 向き を決める関係が無い」なので「—」（第 46 ラウンド裁定 (c)）。
// 継承した in / out は、その一歩の縁自体が動作方向を証明した値ではないことに注意
const DIR_CELL = { in: '影響を受ける入口', out: '影響する先', none: '—' };
function mdSection(title, rs, limit) {
  if (!rs.length) return `### ${title}\n\n該当なし\n\n`;
  const head = `### ${title}\n\n| 着地 | 種別 | 向き | 表示経路の段数<br>（最短とは限りません） | 根拠 | 由来 |\n| --- | --- | --- | --- | --- | --- |\n`;
  const body = rs.slice(0, limit).map((r) => {
    // 経路の根拠（最初に辿れた縁）と、本命にした**動きの縁**を両方出す。後者だけを見て
    // 「経路に無い縁を根拠にしている」とは読ませない
    const mv = r.movementEvidence
      ? ` <br>動きの根拠: \`${r.movementEvidence.kind}\`（${provLabel(r.movementEvidence.provenance)}）`
      : '';
    const why = r.unresolvedCorr ? ` <br>${UNRESOLVED_REASON}` : '';
    return `| ${r.name} | ${r.category} | ${DIR_CELL[r.direction] ?? r.direction} | ${r.hops} | \`${r.evidence.kind}\` ${r.evidence.source.split(':').pop()} → ${r.evidence.target.split(':').pop()}${mv} | ${provLabel(r.evidence.provenance)}${r.correspondence ? '（対応）' : ''}${why} |`;
  }).join('\n');
  const more = rs.length > limit ? `\n\n（他 ${rs.length - limit} 件は --json 参照）` : '';
  return head + body + '\n' + more + '\n\n';
}
const epLine = (e) => `- \`${e.name}\`（\`${e.id}\`）`;
// ---- 兄弟ルートの一覧は既定では出さない（双人レビュー第 30 ラウンド指摘 F）----
// 第 29 ラウンドの裁定 3 は「既定は件数要約、一覧は明示的な詳細表示」を求めたのに、
// 表示側は暗黙の 12 本（`EP_LIST_CAP`）で切った一覧を既定で並べていた。一覧は
// `--list-siblings` を立てたときだけ出し、本数は他の欄と同じ `--limit` に従う
// （`--limit 5` でも `--limit 50` でも 12 本で切る不整合をなくす）。
// 兄弟ルートは 本命 の結果に影響しない（別の欄に要約する）ので、既定の画面から消しても
// 見直しの候補は減らない
const siblingEpIds = new Set(siblingRows().filter((r) => !!r.endpoint).map((r) => r.id));
const reachedRealEndpoints = reachedEndpoints.filter((e) => !siblingEpIds.has(e.id));
const reachedSiblingEndpoints = reachedEndpoints.filter((e) => siblingEpIds.has(e.id));
const SIBLING_LIST_HINT = '一覧は `--list-siblings`（本数は `--limit`）';
let md = `# 影響範囲レポート\n\n- グラフ: \`${summary.graph}\`\n- 起点 ${summary.starts} 件（展開後 ${summary.expandedStarts} 件、グラフに無く起点にしなかった変更 ${summary.fallbacks} 件）\n- 探索 ${summary.hops} ホップ（向きの変えは探索中 1 回まで許可、表示経路で向き変えを含む行 ${summary.secondOrder} 件）/ Terraform の定義単位は ${summary.wiringHops} 段まで無方向で閉じる / 階層（parent・contains）は起点の展開にのみ使用\n- 本命: 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コード 出口 ${summary.entryOut}・入口 ${summary.entryIn} / 成果物 先 ${summary.artifactsOut}・受 ${summary.artifactsIn} / 定義上の関連 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 同じコードを使う別の API ${summary.siblings}（エンドポイント ${summary.siblingEndpointsOnly}・定義ノード ${summary.siblingDefs}）/ 向き を決める関係が無い行 ${summary.directionless}（うち 本命 の資格を持つ行 ${summary.directionlessPrimary}）。**「本命」は「最短」を意味しません**\n- 行の 向き（JSON の direction）は in（影響を受ける入口）/ out（影響する先）/ none（**この表示経路に 向き を決める関係が無い**。Terraform の定義の縁だけを辿った行。一覧の 向き 列では「—」と書きます）。none は「そのノードに他の有向関係が存在しない」意味ではなく、動きの根拠 が無いこと同義でもありません（以前の有向縁から 向き を継承した行があります）。継承した in / out は、その無方向の縁自体が動作方向を証明した値ではありません。none の行は 定義上の関連・同じ API の定義・同じコードを使う別の API に並び、tier（本命の資格）はそのまま保ちます\n- 各段数欄は**表示経路の段数**です（起点 0 段、表示経路の関係 1 本を 1 段。表の値と行の経路表示は一致させます）。**最短とは限りません**。経路全体の整合性を保つため、より長い代表経路を表示する場合があります。この段数は影響の強さやレビューの優先度を示しません\n- 根拠の由来: ${Object.entries(summary.byProvenance).map(([k, v]) => `${provLabel(k)} ${v}`).join(' / ') || 'なし'}（**注釈由来 ${summary.annotationRows} 件**は静的解析では決まらない対応付け）\n\n`;
if (result.score) {
  const s = result.score;
  md += `## 精度（期待一覧との突き合わせ）\n\n- ケース: ${s.case}（方向 ${s.direction}）\n- 期待 ${s.expected} 件 / 外部リソースへの着地 ${s.landedExternal} 件 / 的中 ${s.hitExternal} 件\n- **再現率 ${s.recall} / 適合率 ${s.precision}**\n- 取りこぼし: ${s.missed.map((x) => `\`${x}\``).join(', ') || 'なし'}\n- 余分な着地: ${s.extraExternal.map((x) => `\`${label(x)}\``).join(', ') || 'なし'}\n- 取りこぼしのうち到達はしていた（定義上の関連に回ったもの）: ${s.wiringOnly} 件\n${s.note ? `\n> ${s.note}\n` : ''}\n`;
}
if (fallbacks.length) {
  md += `## 起点にできなかった変更\n\nグラフに対応するノードが無く、**起点にはしていません**（親フォルダを起点にすると配下を巻き込んで誤検出が膨らむため）。`
    + `最も近い親: ${fallbacks.map((f) => `\`${f.path}\` → \`${f.used}\``).join('、') || 'なし'}\n\n`;
}
if (summary.unresolved) {
  // 打ち切りを隠さない。上限で切った結果を完全な結果として出さない
  md += ['> **注意: 探索が収束していません**。探索 ' + summary.rounds + ' ラウンドで仕事が残ったまま上限 '
    + summary.maxRounds + ' に達しました。**影響が抜けている可能性があります**。',
    '>',
    '> 回避策: 起点を絞り込む（変更ファイルを単位にする）、`--hops` / `--wiring-hops` を絞る、',
    '> `--max-rounds` を上げて代償を承知で広く歩く。',
    // 最後の '' を 2 つ並べるのは、この次に来る `##` 見出しとの間に空行を 1 行入れるため
    //（1 つだと `\n` しか入らず、見出しが引用ブロックに張り付く）
    '', ''].join('\n');
}
// 本命 0 件 と 対応未確定 の 2 つは、そのまま読むと「影響がない」と誤読されるので、
// 結論の直下に 1 行ずつだけ出す（各行にも短い理由を立てている）
const primaryTotal = summary.primaryOut + summary.primaryIn;
if (primaryTotal === 0 && summary.rows > 0) {
  md += '> 本命 0 件は、影響がないことを意味しません。対応未確定の候補を確認してください。\n\n';
}
if (summary.unresolvedCorr > 0) {
  md += `> ${UNRESOLVED_WARNING}\n\n`;
}
md += `## 影響を受ける API エンドポイント\n\n`;
md += startEndpoints.length
  ? `起点にしたエンドポイント:\n\n${startEndpoints.map(epLine).join('\n')}\n\n`
  : '';
md += reachedRealEndpoints.length
  ? `${startEndpoints.length ? 'それを使う' : '到達した'}エンドポイント（**起点の定義ではない**同じコードを使う別エンドポイントを含む${reachedRealEndpoints.length > opts.limit ? `。他 ${reachedRealEndpoints.length - opts.limit} 件は \`--json\` 参照` : ''}）:\n\n${reachedRealEndpoints.slice(0, opts.limit).map(epLine).join('\n')}\n\n`
  : (startEndpoints.length ? '' : '該当なし\n\n');
// 兄弟ルートは 本命 の結果に影響しないので、この欄には**件数だけ**出す（指摘 F）
if (reachedSiblingEndpoints.length) {
  md += `同じコードを使う別のルート ${reachedSiblingEndpoints.length} 件（起点の実行には入りません。${SIBLING_LIST_HINT}）\n\n`;
}
md += mdSection('影響する外部リソース（変更が読み書きする先）', externalRows(outRows), opts.limit);
md += mdSection('影響を受ける入口（変更を使う呼び出し元・リソース）', externalRows(inRows), opts.limit);
md += mdSection('影響を受けるコード側の入口（メソッド・型）', entryRows(inRows).slice(0, opts.limit), opts.limit);
// JSON には `entries.out` が入るのに Markdown に出ていなかった（実測 11 件が画面から見えない）。
// エンドポイント起点のとき「Lambda が実際に実行するコード」がこれなので、欄を分けて出す
md += mdSection('影響するコード側の出口（起点から届くメソッド・型）', entryRows(outRows).slice(0, opts.limit), opts.limit);
if (startIsEndpoint) md += mdSection('起点と同じ API を定義するノード（変更で値は動かないので見直しの候補）', sameApiRows(), opts.limit);
if (startIsEndpoint && siblingRows().length) {
  md += `### 同じコードを使う別の API（エンドポイント ${summary.siblingEndpointsOnly} 件と、それを定義するノード ${summary.siblingDefs} 件。起点の定義ではなく、共有しているコードを変えたときに一緒に見る）\n\n`;
  md += `兄弟ルート ${summary.siblingEndpointsOnly} 件 / その API を定義しているノード ${summary.siblingDefs} 件`
    + `（**起点の 本命 の結果には入りません**。全件は \`--json\` の \`siblingEndpoints\`、${SIBLING_LIST_HINT}）\n\n`;
if (opts.listSiblings) {
    const shown = siblingRows().filter((r) => !!r.endpoint).slice(0, opts.limit);
    md += (shown.map((r) => `- \`${r.name}\`（\`${r.id}\`、段数 ${r.hops}（最短とは限りません）、根拠 \`${r.evidence.kind}\`、理由 \`${r.siblingReason}\`）`).join('\n') || '（なし）') + '\n\n';
    const rest = siblingRows().filter((r) => !!r.endpoint).length - shown.length;
    if (rest > 0) md += `他のルート ${rest} 件（\`--limit\` を上げるか \`--json\` 参照）\n\n`;
  }
}
// 先（影響する側）と受（影響を受ける側）を 1 表に混ぜると、集計行の
// 「成果物 先 X・受 Y」と対応が読めなかった（レビュー指摘）。分けて出す
md += mdSection('影響するリポジトリ内の成果物（プロジェクト・ファイル。ビルドし直しが必要な範囲）',
  artifactRows(outRows), opts.limit);
md += mdSection('影響を受けるリポジトリ内の成果物（この変更を参照している側）',
  artifactRows(inRows), opts.limit);
md += mdSection('定義上の関連（Terraform の定義を辿っただけ。動きが伝わるとは限らない）', wiringRows(), opts.limit);
if (opts.md) writeFileSync(resolve(opts.md), md);

// 兄弟ルートは既定では**件数だけ**出す（指摘 F）。一覧は `--list-siblings`、本数は `--limit`
const shownEps = [...startEndpoints, ...reachedRealEndpoints];
const sibEpCount = summary.siblingEndpointsOnly;
console.log(`API エンドポイント: ${shownEps.slice(0, opts.limit).map((e) => e.name).join(', ') || '該当なし'}`
  + (shownEps.length > opts.limit ? ` / 他のエンドポイント ${shownEps.length - opts.limit} 件` : '')
  + (sibEpCount ? ` / 兄弟ルート ${sibEpCount} 件（${opts.listSiblings ? '下に一覧' : '一覧は --list-siblings'}）` : ''));
console.log(`起点 ${summary.starts} 件（展開後 ${summary.expandedStarts}）/ 影響する先 ${summary.primaryOut} / 影響を受ける入口 ${summary.primaryIn} / コード 出口 ${summary.entryOut}・入口 ${summary.entryIn} / 成果物 先 ${summary.artifactsOut}・受 ${summary.artifactsIn} / 定義上 ${summary.wiring} / 同じ API の定義 ${summary.sameApi} / 別の API ${summary.siblings}（エンドポイント ${summary.siblingEndpointsOnly}・定義 ${summary.siblingDefs}） / 向き を決める関係が無い ${summary.directionless}（本命の資格 ${summary.directionlessPrimary}） / 注釈由来 ${summary.annotationRows}`);
if (primaryTotal === 0 && summary.rows > 0) {
  console.log('本命 0 件は、影響がないことを意味しません。対応未確定の候補を確認してください。');
}
if (summary.unresolvedCorr > 0) console.log(UNRESOLVED_WARNING);
if (result.score) console.log(`精度: 再現率 ${result.score.recall} / 適合率 ${result.score.precision}（期待 ${result.score.expected} / 外部着地 ${result.score.landedExternal} / 的中 ${result.score.hitExternal} / 余分 ${result.score.extraExternal.length}）`);
for (const r of externalRows(outRows).slice(0, 12)) console.log(`  [out ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
for (const r of externalRows(inRows).slice(0, 12)) console.log(`  [in  ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${provLabel(r.evidence.provenance)})`);
// `--list-siblings` を立てたら一覧も並べる（本数は --limit。既定は上の 1 行の件数だけ）
if (opts.listSiblings) {
  const sibEps = siblingRows().filter((r) => !!r.endpoint);
  for (const r of sibEps.slice(0, opts.limit)) {
    console.log(`  [sib ${r.hops}] ${r.name}  <- ${r.evidence.kind} (${r.siblingReason})`);
  }
if (sibEps.length > opts.limit) {
    console.log(`  他のルート ${sibEps.length - opts.limit} 件（\`--limit\` を上げるか \`--json\` 参照）`);
  }
}
