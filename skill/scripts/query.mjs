#!/usr/bin/env node
// グラフ JSON に対して「ここから何に影響するか / 何から到達するか」を答える照会ツール。
// ブラウザの ⇧クリック / ⌥⇧クリック（1 ホップ）の多段版で、レビューや設計の
// 影響範囲確認をターミナルから叩けるようにする。
//
// 使い方:
//   node skill/scripts/query.mjs --graph out/demo/graph.json --from tf:aws_lambda_function.orders_api
//   node skill/scripts/query.mjs --graph out/elsa/graph.json --find ActivityExecutionContext
//   node skill/scripts/query.mjs --graph out/demo/graph.json --changed changed.txt --target-kind resource
//   node skill/scripts/query.mjs --graph ... --from 名前 --dir both --hops 3 --via-parent --json
import { readFileSync } from 'node:fs';
import { basename, resolve } from 'node:path';

const args = process.argv.slice(2);
// --group-by に選べる階層。`project` は無い: 実グラフのコードノードの parent は `folder:` で、
// csproj とも結ばれていない（`out/tmp-r42/demo` と `out/elsa` で children / 縁を全数検査して 0 件）。
// `--group-by folder` なら実測できる。csproj 単位の集計が欲しいときは `--from project:... --via-parent` を使う。
const GROUP_KINDS = ['file', 'folder', 'type'];
const opts = { graph: null, from: [], dir: 'both', hops: 2, kinds: null, drop: null, prov: null, targetKind: null, viaParent: false, json: false, find: null, changed: null, limit: 200, groupBy: null };
for (let i = 0; i < args.length; i++) {
  const a = args[i];
  const next = () => args[++i];
  switch (a) {
    case '--graph': opts.graph = resolve(next()); break;
    case '--from': opts.from.push(next()); break;
    case '--dir': opts.dir = next(); break;
    case '--hops': opts.hops = Math.max(1, parseInt(next(), 10) || 1); break;
    case '--kind': opts.kinds = new Set(next().split(',').map((s) => s.trim()).filter(Boolean)); break;
    case '--drop-kind': opts.drop = new Set(next().split(',').map((s) => s.trim()).filter(Boolean)); break;
    case '--provenance': opts.prov = new Set(next().split(',').map((s) => s.trim()).filter(Boolean)); break;
    case '--target-kind': opts.targetKind = new Set(next().split(',').map((s) => s.trim()).filter(Boolean)); break;
    case '--via-parent': opts.viaParent = true; break;
    case '--json': opts.json = true; break;
    case '--find': opts.find = next(); break;
    case '--changed': opts.changed = resolve(next()); break;
    case '--limit': opts.limit = Math.max(1, parseInt(next(), 10) || 200); break;
    case '--group-by': {
      const v = next().trim();
      if (!GROUP_KINDS.includes(v)) {
        const why = v === 'project'
          ? '（実グラフでは .cs ファイルノードの parent は folder。project が関わる縁は .csproj ファイルの contains、csproj 同士の project-reference、project からリソースへの deploys だけで、コードと csproj を結ぶ階層も縁も無いのでコードの所属プロジェクトはたどれない。csproj 単位で見たいなら --from project:... --via-parent）'
          : '';
        console.error(`[query] --group-by は ${GROUP_KINDS.join(' / ')} のいずれか: ${v}${why}`);
        process.exit(2);
      }
      opts.groupBy = v; break;
    }
    case '--help':
      console.log(`使い方: query.mjs --graph <graph.json> [--from <id や名前> ...] [--dir in|out|both] [--hops N]
              [--kind a,b] [--drop-kind a,b] [--provenance static,terraform,llm,human]
              [--target-kind type,member,resource] [--via-parent] [--changed <ファイル一覧>]
              [--find <検索語>] [--group-by file|folder|type] [--json] [--limit N]

  --from        起点。完全なノード ID、または名前（type / file / project の path でも可）。曖昧なら候補を出して終了
  --dir         in = 使用元・呼び出し元へ逆方向 / out = 依存する側へ正方向 / both = 双方向
  --via-parent  階層も辿る（out で配下へ降りる、in で所属へ登る）。csproj 止まりの注釈をコードまで伸ばすときに使う。
                罠: 実縁（calls / references など）は type / member / resource の側にしか付いていないので、
                file: / project: / folder: を起点にするとき --via-parent を付けないと階層の 1 段分しか進めず、
                実縁に辿り着けない（到達 0 件になりやすい）。その場合は stderr に案内を出す
  --group-by    到達ノードを指定階層の祖先に巻き上げて件数で並べる（file / folder / type）。
                「このファイルが依存しているファイルは何本か」を見るための集計。
                起点を巻き上げた階層（自分自身のグループ）は数えない。縁の内訳と最短段数も併記する。
                除外した件数は標準出力の 1 行目と JSON の summary に出す
                （巻き上げ対象 = 表の合計 + 起点自身の階層 + 祖先を持たない）。
                project は選べない: コードの所属プロジェクトはたどれない。実グラフの階層では .cs ファイルは
                folder の下にあり、project が関わる縁も .csproj の contains / csproj 同士の
                project-reference / project からリソースへの deploys だけで、コードと csproj は
                階層でも縁でも結ばれていない（demo と elsa-core の両方で全数検査）
  --changed     変更したファイルパスを 1 行 1 件並べたテキスト。先頭が '#' の行は無視
  --find        ノードを検索して ID を出すだけ（起点を選ぶため）。--json を併用すると
                { matched, nodes: [{ id, kind, name, path, resourceType }] } の JSON になる

読み方（誤解しやすい点）:
  - 各ノードは最初に到達した 1 経路だけ出す（別経路を重ねて数えない）。「到達 N」も
    エッジ総数ではなく到達木のノード数です。
  - --group-by の集計だけ別扱いで、到達ノードごとに**届いた実縁を全部**数える（先着 1 経路ではない）。
    同じノードへ階層の縁と実縁が同じ段で届いても、エッジの列挙順で集計は変わらない。
  - --via-parent は --kind / --drop-kind / --provenance で絞った後のエッジに階層の疑似縁を
    足す。--dir both と併用すると祖先へ登ってから兄弟配下へ広がるので到達が膨らむ。
  - --changed でグラフに無いファイルは最も近い親フォルダを起点にする（警告を stderr へ出し、
    JSON の fallbacks に元パスを残す）。階層で届いただけなので依存エッジの証拠ではない。
  - JSON の reached / matched は**いずれも起点を含まない**。matched は reached のうち
    --target-kind に合ったもので、--target-kind を付けないときは matched が reached と同じ全件。
    summary.reached は起点を引いた到達数、summary.byNodeKind は起点も含めた到達集合の内訳
    （2 つの数字がずれていて当然）。
  - --limit は標準出力の表示件数（--find の検索結果を含む）だけ絞る。BFS の --json は
    絞らないので、機械が読むなら --json。`);
      process.exit(0);
    default:
      console.error(`[query] 知らない引数: ${a}（--help を見てください）`);
      process.exit(2);
  }
}
if (!opts.graph) { console.error('[query] --graph がありません。--help を見てください。'); process.exit(2); }

const graph = JSON.parse(readFileSync(opts.graph, 'utf8'));
const nodes = new Map(graph.nodes.map((n) => [n.id, n]));
const label = (id) => {
  const n = nodes.get(id);
  return n ? `${n.kind}:${n.name}` : id;
};

// ---- 検索
function find(text) {
  const needle = text.toLowerCase();
  const hits = [];
  for (const n of nodes.values()) {
    if (n.id.toLowerCase() === needle) return [n];
    if (n.name.toLowerCase() === needle) hits.push(n);
  }
  if (hits.length) return hits;
  for (const n of nodes.values()) {
    if (n.name.toLowerCase().includes(needle) || (n.path || '').toLowerCase().includes(needle)) hits.push(n);
    if (hits.length > opts.limit) break;
  }
  return hits;
}

if (opts.find) {
  const hits = find(opts.find);
  if (opts.json) {
    // 起点を選ぶための検索も機械で読める形で出す（--json を付けたのに素文本、では使い回せない）
    console.log(JSON.stringify({
      graph: opts.graph, find: opts.find, matched: hits.length,
      nodes: hits.map((n) => ({
        id: n.id, kind: n.kind, name: n.name, path: n.path || null,
        resourceType: n.metadata?.resourceType || null,
      })),
    }, null, 2));
    process.exit(hits.length ? 0 : 1);
  }
  if (!hits.length) { console.log(`該当なし: ${opts.find}`); process.exit(1); }
  for (const n of hits.slice(0, opts.limit)) {
    console.log(`${n.id}  ${n.kind}${n.path ? `  ${n.path}` : ''}${n.metadata?.resourceType ? `  ${n.metadata.resourceType}` : ''}`);
  }
  if (hits.length > opts.limit) console.log(`… 以下 ${hits.length - opts.limit} 件（--limit で拡張）`);
  process.exit(0);
}

// ---- 起点の解決
const starts = [];
const startNotes = [];
const fallbacks = [];
// 同じ起点を複数渡されたら 1 回にまとめる（到達数の集計が負にならないようにする）
function pushStart(id, note) {
  if (starts.includes(id)) return;
  starts.push(id);
  startNotes.push(`${id}${note ? ` (${note})` : ''}`);
}
function addStart(spec, note) {
  if (nodes.has(spec)) { pushStart(spec, note); return true; }
  const hits = find(spec);
  if (hits.length === 1) { pushStart(hits[0].id, note); return true; }
  if (hits.length > 1) {
    console.error(`[query] 起点が曖昧です（${hits.length} 件）: ${spec}`);
    for (const n of hits.slice(0, 12)) console.error(`  ${n.id}`);
    console.error('  → 上の ID を --from に直接指定してください。');
    process.exit(2);
  }
  return false;
}
if (opts.changed) {
  for (const line of readFileSync(opts.changed, 'utf8').split('\n')) {
    const path = line.trim();
    if (!path || path.startsWith('#')) continue;
    const rel = path.replace(/^\.\//, '');
    const direct = `file:${rel}`;
    if (nodes.has(direct)) { pushStart(direct, '変更ファイル'); continue; }
    // 変更ファイルがグラフに出ていない（除外された等）ときは、存在する一番近い親フォルダを起点にする。
    // ルートのフォルダノードの ID は `folder:.` なので、親がなくなるまで下りたらそれを狙う
    let dir = rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '';
    let found = null;
    for (;;) {
      const candidate = dir ? `folder:${dir}` : 'folder:.';
      if (nodes.has(candidate)) { found = candidate; break; }
      if (!dir) break;
      dir = dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : '';
    }
    if (found) {
      pushStart(found, `変更ファイル ${rel} の最も近い親`);
      fallbacks.push({ path: rel, start: found, reason: 'グラフにファイルノードが無いので最も近い親フォルダを起点にした' });
      console.error(`[query] 変更ファイルがグラフに見当たりません: ${rel} → ${found} を起点にします（階層で届いただけで依存の証拠ではありません）`);
      continue;
    }
    console.error(`[query] 変更ファイルがグラフに見当たりません: ${rel}`);
  }
}
for (const spec of opts.from) {
  if (!addStart(spec, null)) console.error(`[query] 起点が見つからないため無視: ${spec}`);
}
if (!starts.length) { console.error('[query] 起点がありません（--from / --changed / --find で指定）。'); process.exit(2); }

// ---- エッジのインデックス
const out = new Map();
const inn = new Map();
const push = (map, key, value) => { const list = map.get(key); if (list) list.push(value); else map.set(key, [value]); };
// 階層の疑似縁ではなく実際に張られた縁。--group-by は先着 1 経路ではなくこの全数で集計するので、
// フィルタをくぐった実縁を列挙順に依存しない形で別に持っておく
const realEdges = [];
let usedEdges = 0;
for (const e of graph.edges || []) {
  if (opts.kinds && !opts.kinds.has(e.kind)) continue;
  if (opts.drop && opts.drop.has(e.kind)) continue;
  if (opts.prov && !opts.prov.has(e.provenance)) continue;
  if (!nodes.has(e.source) || !nodes.has(e.target)) continue;
  push(out, e.source, { other: e.target, edge: e });
  push(inn, e.target, { other: e.source, edge: e });
  realEdges.push(e);
  usedEdges++;
}
if (opts.viaParent) {
  for (const n of nodes.values()) {
    if (!n.parent || !nodes.has(n.parent)) continue;
    push(out, n.parent, { other: n.id, edge: { kind: 'contains', provenance: 'hierarchy', source: n.parent, target: n.id } });
    push(inn, n.id, { other: n.parent, edge: { kind: 'contains', provenance: 'hierarchy', source: n.id, target: n.parent } });
  }
}

const neighbors = (id) => {
  const list = [];
  if (opts.dir === 'in' || opts.dir === 'both') for (const hit of inn.get(id) || []) list.push(hit);
  if (opts.dir === 'out' || opts.dir === 'both') for (const hit of out.get(id) || []) list.push(hit);
  return list;
};

// ---- BFS
// `reached` は表示用の「最初に到達した 1 経路」。集計は別管理にする:
// 縁を 1 本調べるたびに `realHits`（実縁の内訳）と `hierReached`（階層の縁でも届いたか）へ
// 積み増すので、同じノードへ階層の縁と実縁が同じ段で届いても、縁の列挙順で集計は変わらない。
const seen = new Set(starts);
const reached = [];
const realHits = new Map();
const addRealHit = (id, edge) => {
  let hit = realHits.get(id);
  if (!hit) { hit = { edges: 0, kinds: {}, provenances: {} }; realHits.set(id, hit); }
  hit.edges += 1;
  hit.kinds[edge.kind] = (hit.kinds[edge.kind] || 0) + 1;
  hit.provenances[edge.provenance] = (hit.provenances[edge.provenance] || 0) + 1;
};
const hierReached = new Set();
let frontier = [...starts];
for (let hop = 1; hop <= opts.hops && frontier.length; hop++) {
  const next = [];
  for (const id of frontier) {
    for (const { other, edge } of neighbors(id)) {
      if (edge.provenance === 'hierarchy') hierReached.add(other);
      else addRealHit(other, edge);
      if (seen.has(other)) continue;
      seen.add(other);
      next.push(other);
      reached.push({ hop, id: other, via: id, kind: edge.kind, provenance: edge.provenance, detail: edge.detail || null });
    }
  }
  frontier = next;
}

// 階層ノード（file / folder / project）は実縁を直接持たないので、--via-parent 無しでは
// 階層の 1 段分しか進めない。到達 0 件のときだけ、結果を作らずに案内を出す。
const HIERARCHY_START_KINDS = new Set(['file', 'folder', 'project']);
if (!opts.viaParent && !reached.length) {
  const hierStarts = starts.filter((id) => HIERARCHY_START_KINDS.has(nodes.get(id).kind));
  if (hierStarts.length) {
    console.error(`[query] 到達 0 件です。起点 ${hierStarts.join(', ')} は階層ノードで、実縁（calls / references など）は型・メンバー・リソースの側に付いています。階層も辿る --via-parent を付けて再実行してください（--via-parent は到達範囲を膨らませます）`);
  }
}

const filtered = opts.targetKind ? reached.filter((r) => opts.targetKind.has(nodes.get(r.id).kind)) : reached;
const kinds = {};
for (const r of reached) kinds[`${r.kind}·${r.provenance}`] = (kinds[`${r.kind}·${r.provenance}`] || 0) + 1;
const byNodeKind = {};
for (const id of seen) { const k = nodes.get(id).kind; byNodeKind[k] = (byNodeKind[k] || 0) + 1; }
const annotated = reached.filter((r) => r.provenance === 'llm' || r.provenance === 'human');

// ---- 集計（--group-by）: 到達ノードを指定階層の祖先に巻き上げ、接続本数を出す
// 縁は型・メンバー単位でしか張っていないので、「この cs ファイルが繋がっている cs ファイルは何本か」
// はここで階層を登って集計する。集計元は `realHits`（そのノードに届いた実縁の全数）なので、
// 到達木として残る 1 経路のえり好みや縁の列挙順で結果が変わらない。
// 並べ方は 参照ノード数の多さ → 最短段数 → ID の順（実行順に依存しない）。
const groupOf = (id, want) => {
  let cur = id;
  for (let guard = 0; cur && guard < 100; guard++) {
    const n = nodes.get(cur);
    if (!n) return null;
    if (n.kind === want) return cur;
    cur = n.parent || null;
  }
  return null;
};
const groups = [];
let groupReached = 0;
let groupSkippedHierarchy = 0;
let groupSkippedStart = 0;
let groupSkippedNoAncestor = 0;
let groupBothEdges = 0;
let groupsEdges = 0;
let groupsNodes = 0;
if (opts.groupBy) {
  // 起点を指定階層へ巻き上げた集合。ここにいるノードは「自分自身」なので数えない
  // （member: / type: 起点でも効くように、起点の id ではなく巻き上げた階層で比べる）
  const startGroups = new Set();
  for (const s of starts) {
    const g = groupOf(s, opts.groupBy);
    if (g) startGroups.add(g);
  }
  const map = new Map();
  for (const r of reached) {
    const hit = realHits.get(r.id);
    if (hit && hierReached.has(r.id)) groupBothEdges++;
    // 実縁が 1 本も届いていないノードは「階層で届いただけ」なので繋がっているとは数えない
    if (!hit) { groupSkippedHierarchy++; continue; }
    groupReached++;
    const key = groupOf(r.id, opts.groupBy);
    if (!key) { groupSkippedNoAncestor++; continue; }
    if (startGroups.has(key)) { groupSkippedStart++; continue; }
    let g = map.get(key);
    if (!g) {
      g = { id: key, name: label(key), path: nodes.get(key).path || null, nodes: 0, edges: 0, kinds: {}, provenances: {}, minHop: r.hop };
      map.set(key, g);
    }
    g.nodes += 1;
    g.edges += hit.edges;
    for (const [k, v] of Object.entries(hit.kinds)) g.kinds[k] = (g.kinds[k] || 0) + v;
    for (const [k, v] of Object.entries(hit.provenances)) g.provenances[k] = (g.provenances[k] || 0) + v;
    if (r.hop < g.minHop) g.minHop = r.hop;
  }
  groups.push(...map.values());
  // 列挙順で JSON の鍵順が変わらないよう、内訳は keyed 順で揃え直す
  for (const g of groups) {
    g.kinds = Object.fromEntries(Object.entries(g.kinds).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)));
    g.provenances = Object.fromEntries(Object.entries(g.provenances).sort((a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0)));
  }
  groups.sort((a, b) => b.nodes - a.nodes || b.edges - a.edges || a.minHop - b.minHop || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  for (const g of groups) { groupsEdges += g.edges; groupsNodes += g.nodes; }
}

if (opts.json) {
  console.log(JSON.stringify({
    graph: opts.graph, starts, dir: opts.dir, hops: opts.hops, viaParent: opts.viaParent,
    reached: reached.map((r) => ({
      ...r, name: nodes.get(r.id).name, nodeKind: nodes.get(r.id).kind, path: nodes.get(r.id).path || null,
      // 集計はここで持つ全数の実縁で決める（階層の縁でも届いたかどうかは別旗）
      realEdges: realHits.get(r.id)?.edges || 0, reachedByHierarchy: hierReached.has(r.id),
    })),
    matched: filtered.map((r) => ({ ...r, name: nodes.get(r.id).name, nodeKind: nodes.get(r.id).kind, path: nodes.get(r.id).path || null })),
    groupBy: opts.groupBy, groups,
    startNotes, fallbacks,
    summary: {
      reached: seen.size - starts.length, byEdge: kinds, byNodeKind, annotatedEdges: annotated.length, graphEdgesUsed: usedEdges,
      groups: groups.length,
      // --group-by の内訳（すべてノード数。reached = groupsNodes + 除外 3 種 + 階層だけで届いた分）
      groupsReached: groupReached, groupsNodes, groupsEdges,
      groupsSkippedHierarchy: groupSkippedHierarchy,
      groupsSkippedStartHierarchy: groupSkippedStart,
      groupsSkippedNoAncestor: groupSkippedNoAncestor,
      nodesReachedByRealAndHierarchy: groupBothEdges,
    },
  }, null, 2));
  process.exit(0);
}

const filterParts = [];
if (opts.kinds) filterParts.push(`kind ${[...opts.kinds].join(',')}`);
if (opts.drop) filterParts.push(`kind 除外 ${[...opts.drop].join(',')}`);
if (opts.prov) filterParts.push(`provenance ${[...opts.prov].join(',')}`);
console.log(`起点 ${starts.length} 件 / 方向 ${opts.dir} / ${opts.hops} ホップ / 辿ったエッジ ${filterParts.length ? filterParts.join(' / ') : 'すべて'}${opts.viaParent ? ' / 階層も含む' : ''}`);
for (const note of startNotes) console.log(`  ${note}`);
console.log(`到達 ${seen.size - starts.length} ノード（到達集合の内訳: ${Object.entries(byNodeKind).map(([k, v]) => `${k} ${v}`).join(' / ')}）`);
console.log('');
for (const r of reached.slice(0, opts.limit)) {
  const mark = r.provenance === 'llm' || r.provenance === 'human' ? ' ※注釈' : '';
  console.log(`${'  '.repeat(r.hop)}[${r.hop}] ${r.kind.padEnd(11)} ${label(r.id).padEnd(38)} (${r.provenance})${mark}  ← ${nodes.get(r.via).name}`);
}
if (reached.length > opts.limit) console.log(`… 以下 ${reached.length - opts.limit} 件（--limit で拡張）`);

const counts = Object.entries(kinds).sort((a, b) => b[1] - a[1]);
console.log('\nエッジの内訳:');
for (const [k, n] of counts) console.log(`  ${k.padEnd(24)} ${n}`);
if (annotated.length) {
  console.log('\nコードに現れない依存（注釈で付いた縁）:');
  for (const r of annotated.slice(0, 20)) console.log(`  ${r.kind}  ${label(r.id)}  ← ${nodes.get(r.via).name}  ${r.detail ? `// ${r.detail}` : ''}`);
}
if (opts.targetKind) {
  console.log(`\n--target-kind ${[...opts.targetKind].join(',')} に該当 ${filtered.length} 件`);
  for (const r of filtered.slice(0, opts.limit)) console.log(`  ${label(r.id)}  (${r.kind}, ${r.provenance}, ${r.hop} ホップ目)`);
}
if (opts.groupBy) {
  // 単位を混ぜない: 「件」はグループ（表の行）数、「ノード」は巻き上げ元の到達ノード数。
  // 表の行は groups.length で、ここに出す groupsNodes はノード数である（17 ノード -> 4 グループ等）
  console.log(`\n${opts.groupBy} 単位の集計: ${groups.length} グループ（表 ${groups.length} 行）`
    + `（実縁で届いた ${groupReached} ノードを ${opts.groupBy} へ巻き上げ → 集計対象 ${groupsNodes} ノード。`
    + `集計対象 ${groupsNodes} = ${groupReached} − 起点自身の ${opts.groupBy} ${groupSkippedStart}`
    + ` − ${opts.groupBy} の祖先を持たない ${groupSkippedNoAncestor}。`
    + `実縁の無い ${groupSkippedHierarchy} ノードは階層で届いただけなので数えない）`);
  for (const g of groups.slice(0, opts.limit)) {
    const kd = Object.entries(g.kinds).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
      .map(([k, v]) => `${k} ${v}`).join(' / ');
    const ann = (g.provenances.llm || 0) + (g.provenances.human || 0);
    const perNode = g.nodes === g.edges ? '' : ` / 実縁 ${g.edges} 本`;
    console.log(`  ${label(g.id).padEnd(46)} 参照 ${String(g.nodes).padStart(3)} ノード（${kd}${perNode}）最短 ${g.minHop} 段${ann ? `  ※注釈 ${ann}` : ''}`);
  }
  if (groups.length > opts.limit) console.log(`… 以下 ${groups.length - opts.limit} 件（--limit で拡張）`);
}
console.log(`\nブラウザでも見たい場合: graph.html の検索で ID を選ぶか、#expand=${encodeURIComponent(starts[0])}`);
