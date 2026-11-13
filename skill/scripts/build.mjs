#!/usr/bin/env node
// ワンコマンドでグラフを作る: C# 解析 → ディレクトリ/csproj 解析 → (Terraform) → 統合 → HTML
import { spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, statSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const opts = { root: process.cwd(), outDir: 'out', name: '', annotations: [], exclude: ['bin', 'obj', 'node_modules', 'TestResults', 'artifacts', 'packages'], quiet: false };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--root': opts.root = resolve(argv[++i]); break;
      case '--out-dir': opts.outDir = resolve(argv[++i]); break;
      case '--name': opts.name = argv[++i]; break;
      case '--exclude': opts.exclude.push(...argv[++i].split(',').map((s) => s.trim()).filter(Boolean)); break;
      case '--annotation': opts.annotations.push(resolve(argv[++i])); break;
      case '--quiet': opts.quiet = true; break;
      case '--help':
        console.log(`使い方: build.mjs --root <リポジトリ> [--out-dir out] [--annotation a.json] [--exclude test,docs]
  生成物: <out-dir>/graph.json（グラフ本体） / <out-dir>/graph.html（ビューア）`);
        process.exit(0);
    }
  }
  if (!opts.name) opts.name = opts.root.split('/').filter(Boolean).pop() || 'graph';
  return opts;
}

function run(cmd, args, label) {
  const result = spawnSync(cmd, args, { stdio: ['ignore', 'inherit', 'inherit'] });
  if (result.error) { console.error(`[build] ${label} 起動失敗: ${result.error.message}`); process.exit(1); }
  if (result.status !== 0) { console.error(`[build] ${label} が失敗 (exit ${result.status})`); process.exit(result.status || 1); }
}

function findCgd() {
  const candidates = [
    process.env.CGD_BIN,
    join(HERE, '..', 'analyzer', 'bin', 'Release', 'net9.0', 'cgd'),
    join(HERE, '..', 'analyzer', 'bin', 'Debug', 'net9.0', 'cgd'),
    join(HERE, '..', 'analyzer', 'bin', 'Release', 'net8.0', 'cgd'),
    join(HERE, '..', 'analyzer', 'bin', 'Debug', 'net8.0', 'cgd'),
  ].filter(Boolean);
  for (const c of candidates) if (existsSync(c)) return c;
  return null;
}

function buildCgd() {
  const project = join(HERE, '..', 'analyzer', 'cgd.csproj');
  for (const dotnet of [process.env.DOTNET_ROOT && join(process.env.DOTNET_ROOT, 'dotnet'), 'dotnet'].filter(Boolean)) {
    const probe = spawnSync(dotnet, ['--version'], { encoding: 'utf8' });
    if (probe.status === 0) {
      console.log(`[build] cgd をビルドします (${dotnet})`);
      run(dotnet, ['build', project, '-c', 'Release', '-v', 'q', '--nologo'], 'dotnet build');
      return findCgd();
    }
  }
  console.error('[build] dotnet SDK が見つかりません。`dotnet --version` が通る状態で再実行するか、CGD_BIN に cgd 実行ファイルを指定してください。');
  process.exit(1);
}

function findTfFiles(root, excludes, limit = 500) {
  const out = [];
  const walk = (dir) => {
    if (out.length >= limit) return;
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const abs = join(dir, e.name);
      if (e.isDirectory()) { if (!excludes.includes(e.name) && !e.name.startsWith('.')) walk(abs); }
      else if (/\.(tf|tfvars)$/i.test(e.name)) out.push(abs);
    }
  };
  walk(root);
  return out;
}

const opts = parseArgs(process.argv);
if (!existsSync(opts.root) || !statSync(opts.root).isDirectory()) { console.error(`[build] ルートが見つかりません: ${opts.root}`); process.exit(1); }
mkdirSync(opts.outDir, { recursive: true });

const cgdPath = join(opts.outDir, 'graph.csharp.json');
const scanPath = join(opts.outDir, 'graph.scan.json');
const tfPath = join(opts.outDir, 'graph.terraform.json');
const graphPath = join(opts.outDir, 'graph.json');
const dataPath = join(opts.outDir, 'graph.data.js');
const htmlPath = join(opts.outDir, 'graph.html');

let cgd = findCgd() || buildCgd();
if (!cgd) cgd = buildCgd();
const cgdArgs = ['--root', opts.root, '--out', cgdPath, '--exclude', opts.exclude.join(',')];
if (opts.quiet) cgdArgs.push('--quiet');
run(cgd, cgdArgs, 'cgd');

run(process.execPath, [join(HERE, 'scan.mjs'), '--root', opts.root, '--out', scanPath, '--exclude', opts.exclude.join(',')], 'scan.mjs');

const tfFiles = findTfFiles(opts.root, opts.exclude);
const fragments = [scanPath, cgdPath];
if (tfFiles.length) {
  run(process.execPath, [join(HERE, 'scan-terraform.mjs'), '--root', opts.root, '--out', tfPath], 'scan-terraform.mjs');
  fragments.push(tfPath);
} else {
  console.log('[build] .tf ファイルなし（Terraform スキャンはスキップ）');
}

const mergeArgs = [join(HERE, 'merge.mjs'), '--root', opts.root, '--name', opts.name, '--out', graphPath, '--data', dataPath];
for (const f of fragments) mergeArgs.push('--fragment', f);
for (const a of opts.annotations) mergeArgs.push('--annotation', a);
run(process.execPath, mergeArgs, 'merge.mjs');
run(process.execPath, [join(HERE, 'render.mjs'), '--data', dataPath, '--out', htmlPath], 'render.mjs');

console.log(`\n完了: ${htmlPath}`);
console.log(`  グラフデータ: ${graphPath}`);
console.log(`  注釈の追加: merge.mjs に --annotation annotations.json を渡して再生成`);
