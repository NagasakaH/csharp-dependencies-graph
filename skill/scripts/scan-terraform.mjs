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
    const key = m[1], value = m[2].trim().replace(/,$/, '');
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
    const meta = { resourceType: block.type, terraformAddress: address, file: rel, provider: block.kind === 'resource' ? 'terraform' : block.kind };
    for (const key of ['function_name', 'name', 'handler', 'runtime', 'memory_size', 'timeout', 'filename', 's3_key', 'role', 'state_machine_type', 'execution_role_arn', 'rest_api_id', 'resource_id', 'http_method', 'integration_uri', 'uri', 'table_name', 'bucket', 'engine', 'topic_arn', 'queue_url']) {
      if (attrs[key] !== undefined) meta[key] = attrs[key];
    }
    if (block.kind === 'resource') {
      nodes.push({ id, kind: 'resource', name: block.name, parent, path: rel, metadata: { ...meta, category: categoryOf(block.type) } });
      resources.set(address, { id, type: block.type, file: rel });
    } else {
      nodes.push({ id, kind: 'resource', name: block.name, parent, path: rel, metadata: { ...meta, dataSource: true, category: categoryOf(block.type) } });
    }
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
        detail: `${rel} 内の参照`, count: 1,
      });
      if (!target) edges[edges.length - 1].metadata = { unresolvedTarget: true };
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
