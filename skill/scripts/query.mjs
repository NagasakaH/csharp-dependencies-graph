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
      if (!['file', 'project', 'folder', 'type'].includes(v)) {
        console.error(`[query] --group-by は file / project / folder / type のいずれか: ${v}`);
        process.exit(2);
      }
      opts.groupBy = v; break;
    }
    case '--help':
      console.log(`使い方: query.mjs --graph <graph.json> [--from <id や名前> ...] [--dir in|out|both] [--hops N]
              [--kind a,b] [--drop-kind a,b] [--provenance static,terraform,llm,human]
              [--target-kind type,member,resource] [--via-parent] [--changed <ファイル一覧>]
              [--find <検索語>] [--group-by file] [--json] [--limit N]

  --from        起点。完全なノード ID、または名前（type / file / project の path でも可）。曖昧なら候補を出して終了
  --dir         in = 使用元・呼び出し元へ逆方向 / out = 依存する側へ正方向 / both = 双方向
  --via-parent  階層も辿る（out で配下へ降りる、in で所属へ登る）。csproj 止まりの注釈をコードまで伸ばすときに使う
  --group-by    到達ノードを指定階層の祖先に巻き上げて件数で並べる（file / project / folder / type）。
                「このファイルが依存しているファイルは何本か」を見るための集計。起点と同じ階層の
                グループ（自分自身）は数えない。縁の内訳と最短段数も併記する
  --changed     変更したファイルパスを 1 行 1 件並べたテキスト。先頭が '#' の行は無視
  --find        ノードを検索して ID を出すだけ（起点を選ぶため）。--json を併用すると
                { matched, nodes: [{ id, kind, name, path, resourceType }] } の JSON になる

読み方（誤解しやすい点）:
  - 各ノードは最初に到達した 1 経路だけ出す（別経路を重ねて数えない）。「到達 N」も
    エッジ総数ではなく到達木のノード数です。
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
let usedEdges = 0;
for (const e of graph.edges || []) {
  if (opts.kinds && !opts.kinds.has(e.kind)) continue;
  if (opts.drop && opts.drop.has(e.kind)) continue;
  if (opts.prov && !opts.prov.has(e.provenance)) continue;
  if (!nodes.has(e.source) || !nodes.has(e.target)) continue;
  push(out, e.source, { other: e.target, edge: e });
  push(inn, e.target, { other: e.source, edge: e });
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
const seen = new Set(starts);
const reached = [];
let frontier = [...starts];
for (let hop = 1; hop <= opts.hops && frontier.length; hop++) {
  const next = [];
  for (const id of frontier) {
    for (const { other, edge } of neighbors(id)) {
      if (seen.has(other)) continue;
      seen.add(other);
      next.push(other);
      reached.push({ hop, id: other, via: id, kind: edge.kind, provenance: edge.provenance, detail: edge.detail || null });
    }
  }
  frontier = next;
}

const filtered = opts.targetKind ? reached.filter((r) => opts.targetKind.has(nodes.get(r.id).kind)) : reached;
const kinds = {};
for (const r of reached) kinds[`${r.kind}·${r.provenance}`] = (kinds[`${r.kind}·${r.provenance}`] || 0) + 1;
const byNodeKind = {};
for (const id of seen) { const k = nodes.get(id).kind; byNodeKind[k] = (byNodeKind[k] || 0) + 1; }
const annotated = reached.filter((r) => r.provenance === 'llm' || r.provenance === 'human');

// ---- 集計（--group-by）: 到達ノードを指定階層の祖先に巻き上げ、接続本数を出す
// 縁は型・メンバー単位でしか張っていないので、「この cs ファイルが繋がっている cs ファイルは何本か」
// はここで階層を登って集計する。並べ方は 参照件数の多さ → 最短段数 → ID の順（実行順に依存しない）。
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
let groupSkippedHierarchy = 0;
if (opts.groupBy) {
  const map = new Map();
  for (const r of reached) {
    // 階層（contains）で届いただけのノードは「繋がっている」とは数えない
    if (r.provenance === 'hierarchy') { groupSkippedHierarchy++; continue; }
    const key = groupOf(r.id, opts.groupBy);
    if (!key || starts.includes(key)) continue;
    let g = map.get(key);
    if (!g) {
      g = { id: key, name: label(key), path: nodes.get(key).path || null, nodes: 0, kinds: {}, provenances: {}, minHop: r.hop };
      map.set(key, g);
    }
    g.nodes += 1;
    g.kinds[r.kind] = (g.kinds[r.kind] || 0) + 1;
    g.provenances[r.provenance] = (g.provenances[r.provenance] || 0) + 1;
    if (r.hop < g.minHop) g.minHop = r.hop;
  }
  groups.push(...map.values());
  groups.sort((a, b) => b.nodes - a.nodes || a.minHop - b.minHop || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

if (opts.json) {
  console.log(JSON.stringify({
    graph: opts.graph, starts, dir: opts.dir, hops: opts.hops, viaParent: opts.viaParent,
    reached: reached.map((r) => ({ ...r, name: nodes.get(r.id).name, nodeKind: nodes.get(r.id).kind, path: nodes.get(r.id).path || null })),
    matched: filtered.map((r) => ({ ...r, name: nodes.get(r.id).name, nodeKind: nodes.get(r.id).kind, path: nodes.get(r.id).path || null })),
    groupBy: opts.groupBy, groups,
    startNotes, fallbacks,
    summary: { reached: seen.size - starts.length, byEdge: kinds, byNodeKind, annotatedEdges: annotated.length, graphEdgesUsed: usedEdges, groups: groups.length, groupsSkippedHierarchy: groupSkippedHierarchy },
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
  console.log(`\n${opts.groupBy} 単位の集計: ${groups.length} 件（実縁で届いた ${reached.length - groupSkippedHierarchy} 件を階層で巻き上げ。階層で届いただけの ${groupSkippedHierarchy} 件と起点自身の階層は数えません）`);
  for (const g of groups.slice(0, opts.limit)) {
    const kd = Object.entries(g.kinds).sort((a, b) => b[1] - a[1] || (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0))
      .map(([k, v]) => `${k} ${v}`).join(' / ');
    const ann = (g.provenances.llm || 0) + (g.provenances.human || 0);
    console.log(`  ${label(g.id).padEnd(46)} 参照 ${String(g.nodes).padStart(3)} 件（${kd}）最短 ${g.minHop} 段${ann ? `  ※注釈 ${ann}` : ''}`);
  }
  if (groups.length > opts.limit) console.log(`… 以下 ${groups.length - opts.limit} 件（--limit で拡張）`);
}
console.log(`\nブラウザでも見たい場合: graph.html の検索で ID を選ぶか、#expand=${encodeURIComponent(starts[0])}`);
