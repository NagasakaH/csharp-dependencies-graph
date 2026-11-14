#!/usr/bin/env node
// 複数の断片（scan / csharp / terraform / annotations）を 1 つの graph.json に統合し、
// ビューア用の軽量ペイロード（graph.data.js）も生成する。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { basename, dirname, resolve } from 'node:path';

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
const producers = [];
for (const path of opts.fragments) {
  const fragment = readJson(path);
  for (const node of fragment.nodes || []) mergeNode(node, path);
  stats[`${fragment.producer || 'unknown'}Nodes`] = (fragment.nodes || []).length;
  producers.push({ producer: fragment.producer || 'unknown', fragment: basename(path), role: 'fragment', nodes: (fragment.nodes || []).length, edges: (fragment.edges || []).length });
}
for (const path of opts.fragments) {
  const fragment = readJson(path);
  for (const edge of fragment.edges || []) mergeEdge(edge);
  Object.assign(stats, fragment.stats || {});
}

// ---- Lambda の handler 指定を C# の実装メソッドへ結ぶ（逆引きがコードまで届くようにする）
// AWS の .NET handler は `Assembly::NS.Type::Method` / `NS.Type::Method` / `NS.Outer+Inner::Method` の形。
// 実在する member ノードに当たったときだけ張り、外れたらは警告に出す（推測で張らない）。
let handlerEdges = 0;
// プロジェクトのアセンブリ名。csproj に `<AssemblyName>` があれば**それだけ**を使う
//   （アセンブリ名を変えたプロジェクトで、古い csproj 名のままの handler を通さないため）。
//   未宣言のときだけ MSBuild の既定どおりファイル名がアセンブリ名になる
function assemblyNamesOf(project) {
  const declared = project.metadata?.assemblyName ? String(project.metadata.assemblyName) : '';
  if (declared) return [declared];
  const file = String(project.name || '').replace(/\.csproj$/i, '');
  return file ? [file] : [];
}
// ノードの所属プロジェクトをパスの最長一致で求める（csproj と同じディレクトリ配下がそのプロジェクトのファイル）。
// ファイルノードはフォルダの下にぶら下がり、プロジェクトノードは兄弟なので parent 辿りでは決まらない
const projectNodes = [...nodes.values()].filter((n) => n.kind === 'project' && n.path);
function ownerProject(start) {
  const seen = new Set();
  let cur = start;
  let filePath = '';
  while (cur && !seen.has(cur.id)) {
    seen.add(cur.id);
    if (cur.path) { filePath = cur.path; break; }
    cur = cur.parent ? nodes.get(cur.parent) : null;
  }
  if (!filePath) return null;
  let best = null;
  for (const project of projectNodes) {
    const cut = project.path.lastIndexOf('/');
    const dir = cut < 0 ? '' : project.path.slice(0, cut + 1);
    if (filePath.startsWith(dir) && (!best || dir.length > best.dir.length)) best = { project, dir };
  }
  return best ? best.project : null;
}
for (const node of [...nodes.values()]) {
  const raw = typeof node.metadata?.handler === 'string' ? node.metadata.handler.trim() : '';
  const handler = raw.replace(/^["']|["']$/g, '');
  if (!handler.includes('::')) continue;
  // data ソースは実行体ではないので結ばない（`data.aws_lambda_function` 等に handler が現れることがある）
  if (node.metadata?.dataSource === true) continue;
  // AWS の .NET handler は `Assembly::NS.Type::Method`（または Assembly を省く）。
  // 空要素を消してから数えると `Assembly::::A+B+C::Handle` のような指定ミスが 3 要素に化けるので、
  // 空要素を保ったまま要素数を検査する
  const parts = handler.split('::').map((p) => p.trim());
  const empty = parts.some((p) => p.length === 0);
  if (empty || parts.length < 2 || parts.length > 3) {
    warnings.push(
      `handler の形が不正（要素数 ${parts.length}${empty ? '、空要素を含む' : ''}）: ${node.id} → ${handler}`,
    );
    continue;
  }
  const method = parts.pop();
  const rawType = parts.pop();
  const assembly = parts.pop() || '';
  if (!method || !rawType) continue;
  const qualified = rawType.replace(/\+/g, '/');
  const memberId = `member:${qualified}.${method}`;
  const member = nodes.get(memberId);
  if (!member) {
    warnings.push(`handler の解決失敗: ${node.id} → ${handler}（このリポジトリに対応するメソッドが見つからないため注釈で紐づけてください）`);
    continue;
  }
  // アセンブリ名を省かない形では、実装が属するプロジェクトのアセンブリ名と突き合わせる
  //   （同名の型・メソッドが別アセンブリにあっても張らない）
  if (assembly) {
    const project = ownerProject(member);
    const names = project ? assemblyNamesOf(project) : [];
    if (!names.includes(assembly)) {
      warnings.push(
        `handler のアセンブリ名が実装プロジェクトと一致しない: ${node.id} → ${handler}` +
          `（実装プロジェクト ${project ? project.id : '不明'} のアセンブリ名は ` +
          `${names.length ? names.join(' / ') : '不明'}。` +
          `handler 側を実装のアセンブリ名へ直すのが典型的な修正です。` +
          `意図的に別アセンブリを指しているなら注釈で紐づけてください）`,
      );
      continue;
    }
  }
  mergeEdge({ source: node.id, target: memberId, kind: 'handler', provenance: 'terraform', detail: `handler = ${handler}` });
  handlerEdges++;
}
stats.handlerEdges = handlerEdges;

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
  producers.push({
    producer: annotation.producer || 'annotation',
    fragment: basename(path),
    role: 'annotation',
    nodes: (annotation.nodes || []).length,
    edges: (annotation.edges || []).length,
    metadata: (annotation.metadata || []).length,
  });
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
      count: edge.count || 1,
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
  // root は必ずノード ID（他の producer や注釈と同じ契約）。absolute パスは rootPath に入れる
  root: nodes.has('folder:.') ? 'folder:.' : opts.root,
  rootPath: opts.root || null,
  name: opts.name,
  producers,
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
    root: graph.root,
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
