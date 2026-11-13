#!/usr/bin/env node
// 複数の断片（scan / csharp / terraform / annotations）を 1 つの graph.json に統合し、
// ビューア用の軽量ペイロード（graph.data.js）も生成する。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const NODE_KIND_ORDER = ['folder', 'solution', 'project', 'file', 'type', 'member', 'resource'];

function parseArgs(argv) {
  const opts = { fragments: [], annotations: [], out: 'graph.json', data: '', root: '', name: '', maxInlineMB: 60 };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--fragment': opts.fragments.push(resolve(argv[++i])); break;
      case '--annotation': opts.annotations.push(resolve(argv[++i])); break;
      case '--out': opts.out = argv[++i]; break;
      case '--data': opts.data = argv[++i]; break;
      case '--root': opts.root = argv[++i]; break;
      case '--name': opts.name = argv[++i]; break;
      case '--help':
        console.log('使い方: merge.mjs --fragment a.json --fragment b.json [--annotation ann.json] --out graph.json [--data graph.data.js]');
        process.exit(0);
    }
  }
  return opts;
}

function readJson(path) {
  try {
    return JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    console.error(`[merge] 読み込みに失敗: ${path}: ${error.message}`);
    process.exit(1);
  }
}

const opts = parseArgs(process.argv);
const nodes = new Map();
const edges = new Map();
const warnings = [];
const stats = {};

function mergeNode(candidate, source) {
  const existing = nodes.get(candidate.id);
  if (!existing) {
    nodes.set(candidate.id, {
      id: candidate.id,
      kind: candidate.kind,
      name: candidate.name,
      parent: candidate.parent ?? null,
      path: candidate.path,
      metadata: candidate.metadata ? { ...candidate.metadata } : undefined,
    });
    return nodes.get(candidate.id);
  }
  if (existing.kind !== candidate.kind && candidate.kind) {
    warnings.push(`kind 衝突を無視: ${candidate.id} (${existing.kind} / ${candidate.kind} @${source})`);
  }
  if (candidate.parent && !existing.parent) existing.parent = candidate.parent;
  if (candidate.path && !existing.path) existing.path = candidate.path;
  if (candidate.name && !existing.name) existing.name = candidate.name;
  if (candidate.metadata) existing.metadata = { ...(existing.metadata || {}), ...candidate.metadata };
  return existing;
}

function mergeEdge(candidate) {
  if (!nodes.has(candidate.source) || !nodes.has(candidate.target)) {
    const missing = !nodes.has(candidate.source) ? candidate.source : candidate.target;
    warnings.push(`存在しないノードへのエッジを破棄: ${candidate.kind} → ${missing}`);
    return;
  }
  const id = candidate.id || `${candidate.kind}:${candidate.source}->${candidate.target}`;
  const existing = edges.get(id);
  if (existing) {
    existing.count = (existing.count || 1) + (candidate.count || 1);
    if (candidate.detail && !existing.detail) existing.detail = candidate.detail;
    return;
  }
  edges.set(id, {
    id,
    source: candidate.source,
    target: candidate.target,
    kind: candidate.kind || 'references',
    provenance: candidate.provenance || 'static',
    detail: candidate.detail,
    count: candidate.count || 1,
    line: candidate.line,
    metadata: candidate.metadata,
  });
}

// ---- 断片の統合（scan → csharp → terraform の順でマージしても結果が変わらないよう、ノードはマージ優先）
for (const path of opts.fragments) {
  const fragment = readJson(path);
  for (const node of fragment.nodes || []) mergeNode(node, path);
  stats[`${fragment.producer || 'unknown'}Nodes`] = (fragment.nodes || []).length;
}
for (const path of opts.fragments) {
  const fragment = readJson(path);
  for (const edge of fragment.edges || []) mergeEdge(edge);
  Object.assign(stats, fragment.stats || {});
}

// ---- アノテーション（LLM や人が後から追記した外部情報）
function resolveSelector(selector) {
  if (selector.id) return nodes.get(selector.id);
  const kind = selector.kind;
  const matches = [];
  for (const node of nodes.values()) {
    if (kind && node.kind !== kind) continue;
    if (selector.path && !(node.path || '').endsWith(selector.path.replace(/^\.?\//, ''))) continue;
    if (selector.name && node.name !== selector.name) continue;
    matches.push(node);
  }
  if (matches.length === 1) return matches[0];
  if (matches.length > 1) warnings.push(`セレクタが曖昧（${matches.length} 件）: ${JSON.stringify(selector)}`);
  return null;
}

for (const path of opts.annotations) {
  const annotation = readJson(path);
  for (const node of annotation.nodes || []) mergeNode(node, path);
  for (const edge of annotation.edges || []) {
    const source = edge.source ? nodes.get(edge.source) : resolveSelector(edge.sourceMatch || {});
    const target = edge.target ? nodes.get(edge.target) : resolveSelector(edge.targetMatch || {});
    if (!source || !target) {
      warnings.push(`アノテーションのエッジ解決失敗: ${JSON.stringify(edge.sourceMatch || edge.source)} → ${JSON.stringify(edge.targetMatch || edge.target)}`);
      continue;
    }
    mergeEdge({
      source: source.id,
      target: target.id,
      kind: edge.kind || 'annotates',
      provenance: edge.provenance || 'llm',
      detail: edge.note || edge.detail,
      count: 1,
      metadata: edge.confidence !== undefined ? { confidence: edge.confidence } : undefined,
    });
  }
  for (const entry of annotation.metadata || []) {
    const target = entry.target ? nodes.get(entry.target) : resolveSelector(entry.match || {});
    if (!target) {
      warnings.push(`アノテーションのメタデータ対象が見つからない: ${JSON.stringify(entry.match || entry.target)}`);
      continue;
    }
    target.metadata = { ...(target.metadata || {}), ...(entry.set || {}) };
  }
  stats.annotationNodes = (stats.annotationNodes || 0) + (annotation.nodes || []).length;
  stats.annotationEdges = (stats.annotationEdges || 0) + (annotation.edges || []).length;
}

// ---- 階層の補完（親が不明なノードはルート直下にぶら下げる）
const folderDepths = new Map([['folder:.', 0]]);
let orphans = 0;
for (const node of nodes.values()) {
  if (node.parent && !nodes.has(node.parent)) {
    node.parent = 'folder:.';
    orphans++;
  }
  if (!node.parent && node.id !== 'folder:.') {
    if (node.path) {
      const dir = node.path.includes('/') ? node.path.slice(0, node.path.lastIndexOf('/')) : '';
      const candidate = `folder:${dir}`;
      node.parent = nodes.has(candidate) ? candidate : 'folder:.';
    } else {
      node.parent = 'folder:.';
    }
    orphans++;
  }
}

// ---- 集計（フォルダに配下数をロールアップ）
const children = new Map();
for (const node of nodes.values()) {
  if (node.id === 'folder:.') continue;
  if (!children.has(node.parent)) children.set(node.parent, []);
  children.get(node.parent).push(node);
}
const rollupCache = new Map();
const memberCache = new Map();
function rollupMembers(typeId) {
  if (!memberCache.has(typeId)) memberCache.set(typeId, (children.get(typeId) || []).filter((c) => c.kind === 'member').length);
  return memberCache.get(typeId);
}
function rollup(id) {
  if (rollupCache.has(id)) return rollupCache.get(id);
  const totals = { types: 0, members: 0, files: 0, projects: 0, resources: 0, folders: 0 };
  rollupCache.set(id, totals);
  for (const child of children.get(id) || []) {
    if (child.kind === 'type') {
      totals.types++;
      totals.members += rollupMembers(child.id);
    } else if (child.kind === 'member') totals.members++;
    else if (child.kind === 'file' || child.kind === 'solution') {
      totals.files++;
      const inner = rollup(child.id);
      totals.types += inner.types;
      totals.members += inner.members;
    } else if (child.kind === 'project') totals.projects++;
    else if (child.kind === 'resource') totals.resources++;
    else if (child.kind === 'folder') {
      totals.folders++;
      const inner = rollup(child.id);
      totals.types += inner.types;
      totals.members += inner.members;
      totals.files += inner.files;
      totals.projects += inner.projects;
      totals.resources += inner.resources;
    }
  }
  return totals;
}
for (const node of nodes.values()) {
  if (node.kind === 'folder') {
    const totals = rollup(node.id);
    if (totals.types || totals.members || totals.files) {
      node.metadata = { ...(node.metadata || {}), rollup: totals };
    }
  }
}

const graph = {
  schemaVersion: 1,
  generatedAt: new Date().toISOString(),
  root: opts.root,
  name: opts.name,
  nodes: [...nodes.values()],
  edges: [...edges.values()],
  stats: { ...stats, nodes: nodes.size, edges: edges.size, orphans, warnings: warnings.length },
};

mkdirSync(dirname(resolve(opts.out)) || '.', { recursive: true });
writeFileSync(opts.out, JSON.stringify(graph));
console.log(`[merge] node ${nodes.size} / edge ${edges.size} → ${opts.out}`);
if (warnings.length) {
  console.warn(`[merge] 警告 ${warnings.length} 件（先頭 10 件）`);
  for (const warning of warnings.slice(0, 10)) console.warn(`  - ${warning}`);
}

// ---- ビューア用ペイロード（配列エンコードで key 重複を削る）
if (opts.data) {
  const nodeKindIndex = new Map();
  const edgeKindIndex = new Map();
  const provIndex = new Map();
  const detailIndex = new Map();
  const details = [];
  const index = new Map();
  [...nodes.keys()].sort().forEach((id, i) => index.set(id, i));
  const nodeList = [];
  for (const id of index.keys()) {
    const node = nodes.get(id);
    if (!nodeKindIndex.has(node.kind)) nodeKindIndex.set(node.kind, nodeKindIndex.size);
    const parent = node.parent && node.parent !== id ? index.get(node.parent) ?? null : null;
    nodeList.push([id, nodeKindIndex.get(node.kind), node.name, parent, node.path || null, node.metadata || null]);
  }
  const edgeList = [];
  for (const edge of edges.values()) {
    if (!edgeKindIndex.has(edge.kind)) edgeKindIndex.set(edge.kind, edgeKindIndex.size);
    if (!provIndex.has(edge.provenance)) provIndex.set(edge.provenance, provIndex.size);
    let detailIdx = null;
    if (edge.detail) {
      if (!detailIndex.has(edge.detail)) {
        detailIndex.set(edge.detail, details.length);
        details.push(edge.detail);
      }
      detailIdx = detailIndex.get(edge.detail);
    }
    edgeList.push([index.get(edge.source), index.get(edge.target), edgeKindIndex.get(edge.kind), edge.count || 1, provIndex.get(edge.provenance), detailIdx, edge.line ?? null]);
  }
  const payload = {
    v: 1,
    name: opts.name,
    root: opts.root,
    generatedAt: graph.generatedAt,
    stats: graph.stats,
    nodeKinds: [...nodeKindIndex.keys()],
    edgeKinds: [...edgeKindIndex.keys()],
    provenances: [...provIndex.keys()],
    details,
    nodes: nodeList,
    edges: edgeList,
  };
  const text = JSON.stringify(payload);
  const mb = text.length / 1024 / 1024;
  if (mb > opts.maxInlineMB) {
    console.warn(`[merge] ペイロード ${mb.toFixed(1)}MB が上限 ${opts.maxInlineMB}MB を超えています。--no-decl-refs などで解析を絞ってください。`);
  }
  mkdirSync(dirname(resolve(opts.data)) || '.', { recursive: true });
  writeFileSync(opts.data, `window.__CSDG__ = ${text};\n`);
  console.log(`[merge] ビューア用ペイロード ${mb.toFixed(1)}MB → ${opts.data}`);
}
