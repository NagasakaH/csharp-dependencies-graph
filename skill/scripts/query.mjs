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
const opts = { graph: null, from: [], dir: 'both', hops: 2, kinds: null, drop: null, prov: null, targetKind: null, viaParent: false, json: false, find: null, changed: null, limit: 200 };
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
    case '--help':
      console.log(`使い方: query.mjs --graph <graph.json> [--from <id や名前> ...] [--dir in|out|both] [--hops N]
              [--kind a,b] [--drop-kind a,b] [--provenance static,terraform,llm,human]
              [--target-kind type,member,resource] [--via-parent] [--changed <ファイル一覧>]
              [--find <検索語>] [--json] [--limit N]

  --from        起点。完全なノード ID、または名前（type / file / project の path でも可）。曖昧なら候補を出して終了
  --dir         in = 使用元・呼び出し元へ逆方向 / out = 依存する側へ正方向 / both = 双方向
  --via-parent  階層も辿る（out で配下へ降りる、in で所属へ登る）。csproj 止まりの注釈をコードまで伸ばすときに使う
  --changed     変更したファイルパスを 1 行 1 件並べたテキスト。先頭が '#' の行は無視
  --find        ノードを検索して ID を出すだけ（起点を選ぶため）`);
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
function addStart(spec, note) {
  if (nodes.has(spec)) { starts.push(spec); startNotes.push(`${spec}${note ? ` (${note})` : ''}`); return true; }
  const hits = find(spec);
  if (hits.length === 1) { starts.push(hits[0].id); startNotes.push(`${hits[0].id}${note ? ` (${note})` : ''}`); return true; }
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
    if (nodes.has(direct)) { starts.push(direct); startNotes.push(`${direct} (変更ファイル)`); continue; }
    // 変更ファイルがグラフに出ていない（除外された等）ときは、存在する一番近い親フォルダを起点にする
    let dir = rel.includes('/') ? rel.slice(0, rel.lastIndexOf('/')) : '';
    let found = null;
    for (;;) {
      const candidate = `folder:${dir}`;
      if (nodes.has(candidate)) { found = candidate; break; }
      if (!dir) break;
      dir = dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : '';
    }
    if (found) { starts.push(found); startNotes.push(`${found} (変更ファイル ${rel} の最も近い親)`); continue; }
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

if (opts.json) {
  console.log(JSON.stringify({
    graph: opts.graph, starts, dir: opts.dir, hops: opts.hops, viaParent: opts.viaParent,
    reached: reached.map((r) => ({ ...r, name: nodes.get(r.id).name, nodeKind: nodes.get(r.id).kind, path: nodes.get(r.id).path || null })),
    matched: filtered.map((r) => ({ ...r, name: nodes.get(r.id).name, nodeKind: nodes.get(r.id).kind, path: nodes.get(r.id).path || null })),
    summary: { reached: seen.size - starts.length, byEdge: kinds, byNodeKind, annotatedEdges: annotated.length, graphEdgesUsed: usedEdges },
  }, null, 2));
  process.exit(0);
}

console.log(`起点 ${startNotes.length} 件 / 方向 ${opts.dir} / ${opts.hops} ホップ / 辿ったエッジ種別 ${opts.kinds ? [...opts.kinds].join(',') : 'すべて'}${opts.viaParent ? ' / 階層も含む' : ''}`);
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
console.log(`\nブラウザでも見たい場合: graph.html の検索で ID を選ぶか、#expand=${encodeURIComponent(starts[0])}`);
