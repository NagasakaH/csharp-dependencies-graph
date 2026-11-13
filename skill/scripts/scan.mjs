#!/usr/bin/env node
// ディレクトリ階層・csproj・cs ファイルなどのノードを作るスキャナ。
// C# アナライザ（cgd）と同じ ID 規約で断片（fragment）を出力する。
import { readdirSync, statSync, readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, relative, dirname, basename, extname } from 'node:path';

const DEFAULT_EXCLUDES = new Set(['bin', 'obj', '.git', '.vs', '.vscode', '.idea', 'node_modules', 'TestResults', 'artifacts', 'packages', '.nuget']);
const FILE_EXT = new Set(['.cs', '.csproj', '.sln', '.tf', '.tfvars', '.hcl', '.props', '.targets', '.cshtml', '.razor']);
const CONFIG_NAMES = /^(appsettings(\..*)?\.json|serverless\.(yml|yaml)|template\.(yml|yaml)|docker-compose[^/]*\.ya?ml|Dockerfile(\..*)?)$/i;

function parseArgs(argv) {
  const opts = { root: process.cwd(), out: 'graph.scan.json', excludes: new Set(DEFAULT_EXCLUDES), quiet: false };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--root': opts.root = argv[++i]; break;
      case '--out': opts.out = argv[++i]; break;
      case '--exclude': for (const e of argv[++i].split(',')) if (e) opts.excludes.add(e.trim()); break;
      case '--quiet': opts.quiet = true; break;
      case '--help':
        console.log('使い方: scan.mjs --root <repo> --out <graph.scan.json> [--exclude a,b]');
        process.exit(0);
    }
  }
  return opts;
}

const LAMBDA_SIGNALS = [
  [/Amazon\.Lambda/, 'aws-lambda-sdk'],
  [/ILambdaContext/, 'lambda-handler'],
  [/FunctionHandler\s*\(/, 'lambda-handler'],
  [/APIGatewayProxyRequest|APIGatewayProxyResponse/, 'api-gateway-proxy'],
  [/AddAWSLambdaHosting/, 'lambda-hosting'],
  [/Amazon\.DynamoDB/, 'dynamodb'],
  [/Amazon\.S3\b/, 's3'],
  [/Amazon\.SQS|Amazon\.SQS\./, 'sqs'],
  [/Amazon\.SNS/, 'sns'],
  [/Amazon\.StepFunctions|AmazonSFN/, 'step-functions'],
  [/Npgsql|SqlConnection|MySqlConnection|Microsoft\.Data\.SqlClient/, 'relational-db'],
  [/DbContext/, 'ef-core'],
  [/StackExchange\.Redis|ConnectionMultiplexer/, 'redis'],
  [/BucketName|SecretsManager|Configuration\.AddSecret/, 'aws-config-store'],
  [/GraphQL|HotChocolate/, 'graphql'],
  [/RabbitMq|Kafka|EventHub/, 'messaging'],
];

function detectSignals(text) {
  const found = new Set();
  for (const [pattern, label] of LAMBDA_SIGNALS) if (pattern.test(text)) found.add(label);
  return [...found];
}

function parseCsproj(text) {
  const meta = {};
  const grab = (tag) => {
    const m = text.match(new RegExp(`<${tag}>([^<]*)</${tag}>`, 'i'));
    return m ? m[1].trim() : undefined;
  };
  if (grab('TargetFramework')) meta.targetFramework = grab('TargetFramework');
  if (grab('TargetFrameworks')) meta.targetFrameworks = grab('TargetFrameworks');
  if (grab('RootNamespace')) meta.rootNamespace = grab('RootNamespace');
  if (grab('AssemblyName')) meta.assemblyName = grab('AssemblyName');
  if (grab('OutputType')) meta.outputType = grab('OutputType');
  if (grab('Exe') === 'true') meta.exe = true;
  const projectRefs = [...text.matchAll(/<ProjectReference\s+[^>]*Include\s*=\s*"([^"]+)"/gi)].map((m) => m[1]);
  const packageRefs = [...text.matchAll(/<PackageReference\s+[^>]*Include\s*=\s*"([^"]+)"/gi)].map((m) => m[1]);
  return { meta, projectRefs, packageRefs };
}

function walk(dir, root, opts, nodes, edges, files) {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    const abs = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (opts.excludes.has(entry.name) || (entry.name.startsWith('.') && entry.name !== '.')) continue;
      const rel = relative(root, abs).split(/[\\/]/).join('/');
      nodes.push({ id: `folder:${rel}`, kind: 'folder', name: entry.name, parent: rel.includes('/') ? `folder:${dirname(rel).split(/[\\/]/).join('/')}` : 'folder:.' });
      walk(abs, root, opts, nodes, edges, files);
    } else if (entry.isFile()) {
      const rel = relative(root, abs).split(/[\\/]/).join('/');
      const ext = extname(entry.name).toLowerCase();
      const isConfig = CONFIG_NAMES.test(entry.name);
      if (!FILE_EXT.has(ext) && !isConfig) continue;
      files.push({ abs, rel, ext });
    }
  }
}

const opts = parseArgs(process.argv);
const root = opts.root;
const nodes = [{ id: 'folder:.', kind: 'folder', name: basename(root) || root, parent: null, path: '' }];
const edges = [];
const files = [];
walk(root, root, opts, nodes, edges, files);

let signalFiles = 0;
for (const file of files) {
  const node = { id: `file:${file.rel}`, kind: 'file', name: basename(file.rel), parent: file.rel.includes('/') ? `folder:${dirname(file.rel)}` : 'folder:.', path: file.rel };
  const meta = {};
  if (file.ext === '.csproj') {
    node.kind = 'project';
    node.id = `project:${file.rel}`;
    let text = '';
    try {
      text = readFileSync(file.abs, 'utf8');
    } catch {}
    const { meta: projectMeta, projectRefs, packageRefs } = parseCsproj(text);
    Object.assign(meta, projectMeta);
    if (packageRefs.length) meta.packageReferences = packageRefs;
    const lambdaSignals = detectSignals(text);
    if (lambdaSignals.length) meta.signals = lambdaSignals;
    for (const ref of projectRefs) {
      const normalized = relative(root, join(dirname(file.abs), ref.replace(/\\/g, '/'))).split(/[\\/]/).join('/');
      edges.push({ id: `project-reference:project:${file.rel}->project:${normalized}`, source: `project:${file.rel}`, target: `project:${normalized}`, kind: 'project-reference', provenance: 'static', count: 1 });
    }
  } else if (file.ext === '.sln') {
    node.kind = 'solution';
    let text = '';
    try {
      text = readFileSync(file.abs, 'utf8');
    } catch {}
    const projects = [...text.matchAll(/Project\("\{[^"]+}"\)\s*=\s*"([^"]+)",\s*"([^"]+)"/g)]
      .map((m) => ({ name: m[1], path: m[2].replace(/\\/g, '/') }))
      .filter((p) => p.path.toLowerCase().endsWith('.csproj'));
    if (projects.length) meta.projects = projects.map((p) => p.name);
    for (const project of projects) {
      const normalized = relative(root, join(dirname(file.abs), project.path)).split(/[\\/]/).join('/');
      edges.push({ id: `contains:${node.id}->project:${normalized}`, source: node.id, target: `project:${normalized}`, kind: 'contains', provenance: 'static', count: 1 });
    }
  } else if (file.ext === '.cs') {
    let text = '';
    try {
      text = readFileSync(file.abs, 'utf8');
      const signals = detectSignals(text);
      if (signals.length) {
        meta.signals = signals;
        signalFiles++;
      }
    } catch {}
  }
  if (Object.keys(meta).length) node.metadata = meta;
  nodes.push(node);
}

const fragment = {
  schemaVersion: 1,
  producer: 'directory-scanner',
  generatedAt: new Date().toISOString(),
  root,
  nodes,
  edges,
  stats: {
    folders: nodes.filter((n) => n.kind === 'folder').length,
    files: nodes.filter((n) => n.kind === 'file').length,
    projects: nodes.filter((n) => n.kind === 'project').length,
    solutions: nodes.filter((n) => n.kind === 'solution').length,
    signalFiles,
  },
};

mkdirSync(dirname(opts.out) || '.', { recursive: true });
writeFileSync(opts.out, JSON.stringify(fragment));
if (!opts.quiet) {
  console.log(`[scan] folder ${fragment.stats.folders} / file ${fragment.stats.files} / project ${fragment.stats.projects} / solution ${fragment.stats.solutions} → ${opts.out}`);
  console.log(`[scan] AWS/DB シグナルを検出した .cs ファイル: ${signalFiles} 件`);
}
