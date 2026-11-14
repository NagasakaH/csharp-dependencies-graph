#!/usr/bin/env node
// query.mjs（影響範囲・逆引きの照会）の検査。fixtures/query/graph.json を使うので
// .NET も実プロジェクトも不要。
// 使い方: node skill/scripts/test-query.mjs
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const GRAPH = join(HERE, '..', 'tests', 'fixtures', 'query', 'graph.json');
const QUERY = join(HERE, 'query.mjs');
const tmp = mkdtempSync(join(tmpdir(), 'cgd-query-'));
let pass = 0;
const failures = [];

function check(label, ok, detail) {
  if (ok) { pass++; console.log(`PASS ${label}`); } else { failures.push(label); console.log(`FAIL ${label}${detail ? `  ${detail}` : ''}`); }
}

function run(...argv) {
  const proc = spawnSync('node', [QUERY, '--graph', GRAPH, ...argv], { encoding: 'utf8' });
  return { status: proc.status, stdout: proc.stdout || '', stderr: proc.stderr || '' };
}

function json(...argv) {
  const r = run('--json', ...argv);
  if (r.status !== 0) return { error: r };
  try { return { data: JSON.parse(r.stdout) }; } catch { return { error: r }; }
}

const LAMBDA = 'tf:aws_lambda_function.pay';
const COLUMN = 'ext:rds-column/db.public.payments.amount';
const CHARGE = 'member:Pay.Handler.Charge';
const READ = 'member:Pay.Handler.ReadRow';
const TABLE = 'ext:rds-table/db.public.payments';

// 1) handler エッジで Lambda から実装メソッドへ届く
let r = json('--from', LAMBDA, '--dir', 'out', '--hops', '1');
check('Lambda から handler 経由で実装メソッドに届く',
  (r.data?.reached || []).some((x) => x.id === CHARGE && x.kind === 'handler'),
  JSON.stringify(r.data?.reached || r.error?.stderr || ''));

// 2) DB のカラムから双方向で、メソッドを経由して Lambda まで辿る
r = json('--from', COLUMN, '--dir', 'both', '--hops', '3');
const ids = new Set((r.data?.reached || []).map((x) => x.id));
check('カラムからメソッドを経由して Lambda まで逆引きできる',
  ids.has(READ) && ids.has(CHARGE) && ids.has(LAMBDA),
  JSON.stringify([...ids]));

// 3) --kind で辿る縁を絞れる
r = json('--from', COLUMN, '--dir', 'both', '--hops', '1', '--kind', 'references');
check('--kind references だけの 1 ホップになる',
  (r.data?.reached || []).length === 1 && r.data.reached[0].id === READ,
  JSON.stringify(r.data?.reached || []));

// 4) --provenance で注釈の縁だけ／静的解析の縁だけに分けられる
const llm = json('--from', TABLE, '--dir', 'in', '--hops', '3', '--provenance', 'llm');
const stat = json('--from', TABLE, '--dir', 'in', '--hops', '3', '--provenance', 'static');
check('--provenance llm は注釈の縁だけを辿る',
  (llm.data?.reached || []).some((x) => x.id === READ) && !(stat.data?.reached || []).some((x) => x.id === READ),
  JSON.stringify([llm.data?.summary, stat.data?.summary]));

// 5) --target-kind は到達集合の絞り込み
r = json('--from', CHARGE, '--dir', 'both', '--hops', '3', '--target-kind', 'resource');
check('--target-kind resource で外部リソースだけ取り出せる',
  (r.data?.matched || []).length > 0 && (r.data.matched || []).every((x) => x.nodeKind === 'resource')
    && (r.data?.matched || []).some((x) => x.id === TABLE),
  JSON.stringify(r.data?.matched || []));

// 6) --via-parent で階層を降りる（csproj 注釈をコードへ伸ばす）
r = json('--from', 'file:src/Pay.cs', '--dir', 'out', '--hops', '2', '--via-parent');
const withParent = new Set((r.data?.reached || []).map((x) => x.id));
r = json('--from', 'file:src/Pay.cs', '--dir', 'out', '--hops', '2');
const withoutParent = new Set((r.data?.reached || []).map((x) => x.id));
check('--via-parent で階層を降りてメソッドに届く',
  withParent.has(CHARGE) && withParent.has('member:Pay.Retry.Charge') && withoutParent.size === 0,
  JSON.stringify([[...withParent], [...withoutParent]]));

// 7) 名前で起点を指定できる（完全 ID でなくてもよい）
r = json('--from', 'ReadRow', '--hops', '1');
check('名前だけで起点を解決できる', r.data?.starts?.[0] === READ, JSON.stringify(r.data?.starts || r.error?.stderr || ''));

// 8) 曖昧な名前は推測せず候補を出して終了する
r = run('--from', 'Charge', '--hops', '1');
check('曖昧な起点は終了して候補を出す', r.status === 2 && r.stderr.includes('曖昧'), r.stdout + r.stderr);

// 9) --find は ID 一覧を返す
r = run('--find', 'ledger');
check('--find がノード ID を出す', r.status === 0 && r.stdout.includes('tf:aws_dynamodb_table.ledger'), r.stdout);

// 10) --changed のファイル一覧から起点を作る
const list = join(tmp, 'changed.txt');
writeFileSync(list, '# 変更一覧\nsrc/Pay.cs\n');
r = json('--changed', list, '--hops', '1');
check('--changed のファイルが起点になる', r.data?.starts?.[0] === 'file:src/Pay.cs', JSON.stringify(r.data?.starts || r.error?.stderr || ''));

// 11) 変更ファイルがグラフに無いときは親フォルダに落として警告だけ出す
writeFileSync(list, 'src/deleted/File.cs\n');
r = json('--changed', list, '--hops', '1');
check('変更ファイルが無くても近い親フォルダを起点にする', r.data?.starts?.[0] === 'folder:src', JSON.stringify(r.data?.starts || r.error?.stderr || ''));

// 12) 起点が無いときは使い方を出して終了
r = run('--hops', '1');
check('起点が無ければ終了', r.status === 2 && r.stderr.includes('起点'), r.stderr);

rmSync(tmp, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
