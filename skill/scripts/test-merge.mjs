#!/usr/bin/env node
// merge.mjs の handler 解決ルールを検査する。
// Lambda の handler 指定（`Assembly::NS.Type::Method`）は、実在するメソッドに当たり、
// かつアセンブリ名が実装プロジェクトと合うときだけ結ぶ。外れたら張らずに警告を出す。
// 使い方: node skill/scripts/test-merge.mjs
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const root = resolve(HERE, '..', '..');
const dir = mkdtempSync(join(tmpdir(), 'cgd-merge-'));
let pass = 0;
const failures = [];

function check(label, ok, detail) {
  if (ok) { pass++; console.log(`PASS ${label}`); } else { failures.push(label); console.log(`FAIL ${label}${detail ? `  ${detail}` : ''}`); }
}

if (!process.env.CGD_BIN && !existsSync(join(HERE, '..', 'analyzer', 'bin', 'Release', 'net9.0', 'cgd'))) {
  console.error('[test] skill/analyzer/bin/Release/net9.0/cgd がありません。`dotnet build skill/analyzer/cgd.csproj -c Release` を先に実行してください。');
  process.exit(1);
}

const outDir = join(dir, 'graph');
const proc = spawnSync(process.execPath, [join(HERE, 'build.mjs'),
  '--root', join(HERE, '..', 'tests', 'fixtures', 'HandlerLambda'),
  '--out-dir', outDir, '--name', 'handler-lambda'], { cwd: root, encoding: 'utf8' });
if (proc.status !== 0) {
  console.error((proc.stdout || '') + (proc.stderr || ''));
  const log = (proc.stdout || '') + (proc.stderr || '');
  if (log.includes('You must install or update .NET')) {
    console.error('[test] cgd は .NET 9 実行時が必要です。`export DOTNET_ROOT=$HOME/.dotnet` をしてから再実行してください。');
  }
  process.exit(1);
}

const buildLog = (proc.stdout || '') + (proc.stderr || '');
const graph = JSON.parse(readFileSync(join(outDir, 'graph.json'), 'utf8'));
const handlers = graph.edges.filter((e) => e.kind === 'handler');
const linked = new Set(handlers.map((e) => `${e.source}->${e.target}`));
// 警告は graph.json には残らずビルド出力に出るので、そちらを読む
const warnings = buildLog;

check('AssemblyName が合えば結ぶ',
  linked.has('tf:aws_lambda_function.valid->member:HandlerNs.A.Handle'),
  JSON.stringify([...linked]));
check('アセンブリ名を省いた 2 要素形も結ぶ',
  linked.has('tf:aws_lambda_function.without_assembly->member:HandlerNs.A.Handle'));
check('ネスト型（`Outer+Inner`）は `Outer/Inner` の member に解決する',
  linked.has('tf:aws_lambda_function.nested->member:HandlerNs.A/Inner.Handle'));
check('同じメソッド名でも別の型ならその型へ結ぶ',
  linked.has('tf:aws_lambda_function.other_type->member:HandlerNs.B.Handle'));

check('2 段以上のネスト型（`Outer+Middle+Inner`）も解決する',
  linked.has('tf:aws_lambda_function.nested3->member:HandlerNs.Outer/Middle/Inner.Handle'),
  JSON.stringify([...linked]));

// 張ってはいけない 5 とお
check('アセンブリ名が違う指定は張らずに警告',
  ![...linked].some((k) => k.startsWith('tf:aws_lambda_function.wrong_assembly->'))
  && warnings.includes('アセンブリ名'),
  warnings.split('\n').filter((l) => l.includes('wrong_assembly')).join(' / '));
check('4 要素以上の handler は形が不正として張らない',
  ![...linked].some((k) => k.startsWith('tf:aws_lambda_function.four_parts->'))
  && warnings.includes('要素数 4'),
  warnings.split('\n').filter((l) => l.includes('four_parts')).join(' / '));
check('アセンブリ名を宣言している csproj でファイル名を受理しない（別アセンブリへの handler を張らない）',
  ![...linked].some((k) => k.startsWith('tf:aws_lambda_function.csproj_name->'))
  && warnings.includes('csproj_name') && warnings.includes('RealAssembly'),
  JSON.stringify([...linked]));
check('空要素を含む handler は要素数検査をすり抜けない',
  ![...linked].some((k) => k.startsWith('tf:aws_lambda_function.empty_parts->'))
  && warnings.includes('空要素'),
  JSON.stringify([...linked]));
check('存在しない型は張らずに注釈を促す警告',
  ![...linked].some((k) => k.startsWith('tf:aws_lambda_function.unknown_type->'))
  && warnings.includes('handler の解決失敗'),
  warnings.split('\n').filter((l) => l.includes('unknown_type')).join(' / '));
check('data ソースの handler は実行体ではないので結ばない',
  ![...linked].some((k) => k.startsWith('tf:data.aws_lambda_function.existing->')),
  JSON.stringify([...linked]));
check('stats.handlerEdges は実際の handler エッジ数と一致',
  graph.stats.handlerEdges === handlers.length, `${graph.stats.handlerEdges} / ${handlers.length}`);

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
