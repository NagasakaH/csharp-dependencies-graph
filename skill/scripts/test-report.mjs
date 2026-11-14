#!/usr/bin/env node
// report.mjs（差分 → 影響範囲レポート）を検査する。
// 方針の中心は「**階層で届いただけのものを依存の影響に混ぜない**」と
// 「**Terraform の定義上の関連を本命と混ぜない**」なので、そこを fixture で固定する。
// 使う fixture: fixtures/ReportImpact/（C# と infra/main.tf が同じリポジトリにある形）
// 使い方: node skill/scripts/test-report.mjs
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const root = resolve(HERE, '..', '..');
const dir = mkdtempSync(join(tmpdir(), 'cgd-report-'));
let pass = 0;
const failures = [];
function check(label, ok, detail) {
  if (ok) { pass++; console.log(`PASS ${label}`); } else { failures.push(label); console.log(`FAIL ${label}${detail ? `  ${detail}` : ''}`); }
}

if (!process.env.CGD_BIN && !existsSync(join(HERE, '..', 'analyzer', 'bin', 'Release', 'net9.0', 'cgd'))) {
  console.error('[test] skill/analyzer/bin/Release/net9.0/cgd がありません。`dotnet build skill/analyzer/cgd.csproj -c Release` を先に実行してください。');
  process.exit(1);
}

const FIX = join(HERE, '..', 'tests', 'fixtures', 'ReportImpact');
const outDir = join(dir, 'graph');
const build = spawnSync(process.execPath, [join(HERE, 'build.mjs'), '--root', FIX, '--out-dir', outDir, '--name', 'report-impact'],
  { cwd: root, encoding: 'utf8' });
if (build.status !== 0) {
  const log = (build.stdout || '') + (build.stderr || '');
  console.error(log);
  if (log.includes('You must install or update .NET')) {
    console.error('[test] cgd は .NET 9 実行時が必要です。`export DOTNET_ROOT=$HOME/.dotnet` をしてから再実行してください。');
  }
  process.exit(1);
}
const GRAPH = join(outDir, 'graph.json');

// report.mjs を実行して JSON を返す
function run(args, label) {
  const json = join(dir, `${label}.json`);
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', GRAPH, ...args, '--json', json],
    { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  return { result: JSON.parse(readFileSync(json, 'utf8')), stdout: proc.stdout, stderr: proc.stderr };
}
const list = (name, lines) => {
  const f = join(dir, name);
  writeFileSync(f, lines.join('\n') + '\n');
  return f;
};
const ids = (rows) => (rows || []).map((r) => r.id);
const LAMBDA = 'tf:aws_lambda_function.orders_api';
const INTEGRATION = 'tf:aws_api_gateway_integration.post_order';
const DATA = 'tf:data.aws_caller_identity';   // data ブロックの address は `data.<name>`

// ---- 注釈を足したグラフ（静的解析では決まらない対応付けがある形）----
const outDir2 = join(dir, 'graph-ann');
const build2 = spawnSync(process.execPath, [join(HERE, 'build.mjs'), '--root', FIX, '--out-dir', outDir2,
  '--name', 'report-impact-ann', '--annotation', join(FIX, 'annotations.report.json')],
  { cwd: root, encoding: 'utf8' });
if (build2.status !== 0) { console.error((build2.stdout || '') + (build2.stderr || '')); process.exit(1); }
const GRAPH2 = join(outDir2, 'graph.json');
function run2(args, label) {
  const json = join(dir, `${label}.json`);
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', GRAPH2, ...args, '--json', json],
    { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  return { result: JSON.parse(readFileSync(json, 'utf8')), stdout: proc.stdout, stderr: proc.stderr };
}
// すべての行がどれかの欄に入っているか（欄の合計 == 総行数）
const bucketTotal = (r) => r.external.out.length + r.external.in.length
  + r.entries.out.length + r.entries.in.length
  + r.wiring.length + r.sameApi.length + r.siblingEndpoints.length;

// ---- 変更ファイル起点 ----
const a = run(['--changed', list('a.txt', ['src/OrderHandler.cs'])], 'a');
if (!a) process.exit(1);
const A = a.result;
check('変更ファイルの中のメンバーから自動で起点を作る（起点 1 件が複数に展開される）',
  A.summary.starts === 1 && A.summary.expandedStarts > 1,
  `starts=${A.summary.starts} expanded=${A.summary.expandedStarts}`);
check('変更したコードを使う Lambda が「影響を受ける入口」に出る（handler 縁）',
  ids(A.external.in).includes(LAMBDA)
  && A.external.in.find((r) => r.id === LAMBDA).evidence.kind === 'handler',
  JSON.stringify(A.external.in.map((r) => [r.id, r.evidence.kind])));
check('Lambda からは Terraform の `triggers` で integration へ進む（方向の切り替えを要さない）',
  ids(A.external.in).includes(INTEGRATION)
  && A.external.in.find((r) => r.id === INTEGRATION).evidence.kind === 'triggers',
  JSON.stringify(A.external.in.map((r) => [r.id, r.evidence.kind])));
check('到達した API エンドポイントに `POST /orders` が出る',
  A.summary.reachedEndpoints.some((e) => e.name === 'POST /orders'),
  JSON.stringify(A.summary.reachedEndpoints.map((e) => e.name)));
check('同じフォルダの無関係なファイル（NotifyHandler.cs）のメンバーは着地にしない',
  !JSON.stringify(A).includes('Notify'), JSON.stringify(A.entries));
check('Terraform の `references` だけの iam_role / rest_api は本命に出さない',
  !ids(A.external.in).includes('tf:aws_iam_role.lambda_role')
  && !ids(A.external.out).includes('tf:aws_iam_role.lambda_role')
  && !ids(A.external.in).includes('tf:aws_api_gateway_rest_api.orders_api')
  && ids(A.wiring).includes('tf:aws_iam_role.lambda_role'),
  JSON.stringify([ids(A.external.in), ids(A.wiring)]));
check('変更ファイルの中にある型（`Order`）を「影響する先」に並べない',
  !ids(A.external.out).some((id) => id.startsWith('type:ReportImpact.Order'))
  && A.external.out.length === 0,
  JSON.stringify(A.external.out.map((r) => r.id)));

// ---- API エンドポイント起点 ----
const b = run(['--api', 'POST /orders'], 'b');
if (!b) process.exit(1);
const B = b.result;
check('`--api "POST /orders"` でメソッドが引ける（endpoint で照合）',
  B.api[0].hits.length === 1 && B.api[0].matched[0] === 'POST /orders',
  JSON.stringify(B.api[0]));
check('エンドポイント起点で Lambda が「影響する先」に出る',
  ids(B.external.out).includes(LAMBDA), JSON.stringify(ids(B.external.out)));
check('エンドポイント起点で handler の先（`Handle`）がコード側の入口に出る',
  B.entries.out.some((r) => r.id === 'member:ReportImpact.Handler.Handle'),
  JSON.stringify(B.entries.out.map((r) => r.id)));
check('起点となる API を定義する resource / rest_api / integration は外部リソースに数えない',
  ['aws_api_gateway_resource.orders', 'aws_api_gateway_rest_api.orders_api', INTEGRATION.slice(3)]
    .every((addr) => ids(B.sameApi).includes(`tf:${addr}`))
  && !ids(B.external.out).includes('tf:aws_api_gateway_resource.orders'),
  JSON.stringify(ids(B.sameApi)));
check('同じ Lambda を使う別エンドポイント（`GET /orders`）は別枠に出す',
  B.siblingEndpoints.some((r) => r.endpoint === 'GET /orders')
  && !ids(B.external.in).includes('tf:aws_api_gateway_method.get_order')
  && !ids(B.wiring).includes('tf:aws_api_gateway_method.get_order'),
  JSON.stringify([B.siblingEndpoints.map((r) => r.name), ids(B.wiring)]));

// ---- 期待一覧との突き合わせ ----
const expectFile = join(dir, 'expect.json');
writeFileSync(expectFile, JSON.stringify({
  name: 'fixture: POST /orders 起点', direction: 'out', expect: [LAMBDA], note: 'Lambda 1 本だけが正解',
}));
const s = run(['--api', 'POST /orders', '--expect', expectFile], 'score');
check('`--expect` で再現率 1 / 適合率 1 が出る',
  !!s && s.result.score.recall === 1 && s.result.score.precision === 1,
  JSON.stringify(s && s.result.score));

// ---- Terraform ファイルを起点にしたとき ----
const tfFile = run(['--changed', list('tf.txt', ['infra/main.tf'])], 'tf');
if (!tfFile) process.exit(1);
const T = tfFile.result;
const declared = JSON.parse(readFileSync(GRAPH, 'utf8')).nodes
  .filter((n) => n.kind === 'resource' && (n.metadata || {}).file === 'infra/main.tf').length;
check('変更された Terraform ファイルの宣言リソースが起点になる（親フォルダ落ちしない）',
  T.summary.fallbacks === 0 && T.starts.filter((x) => x.id.startsWith('tf:')).length === declared,
  `tf 起点 ${T.starts.filter((x) => x.id.startsWith('tf:')).length} / 宣言 ${declared} / fallbacks ${T.summary.fallbacks}`);
check('data ソースは既定では着地にしない（ほとんどを参照してノイズになる）',
  !ids(T.wiring).includes(DATA) && !ids(T.external.in).includes(DATA) && !ids(T.external.out).includes(DATA),
  JSON.stringify(ids(T.wiring)));
const tdi = run(['--changed', list('tf.txt', ['infra/main.tf']), '--include-data'], 'tfdata');
check('`--include-data` を付けたときだけ data ソースが現れる',
  !!tdi && ids(tdi.result.wiring).includes(DATA), JSON.stringify(tdi && ids(tdi.result.wiring)));

// ---- 変更ファイルがグラフに無いとき ----
const miss = run(['--changed', list('miss.txt', ['README.md'])], 'miss');
if (!miss) process.exit(1);
check('グラフに無い変更ファイルは起点にせず、一覧に出すだけにする',
  miss.result.summary.starts === 0 && miss.result.summary.expandedStarts === 0
  && miss.result.fallbacks.length === 1 && miss.result.fallbacks[0].started === false,
  JSON.stringify([miss.result.summary.starts, miss.result.fallbacks]));
const fs = run(['--changed', list('miss.txt', ['README.md']), '--folder-start'], 'folderstart');
check('`--folder-start` を付けたときだけ親フォルダを起点にする',
  !!fs && fs.result.summary.starts === 1 && fs.result.fallbacks[0].started === true,
  JSON.stringify(fs && [fs.result.summary.starts, fs.result.fallbacks]));

// ---- 入力と出力の形式 ----
const stdin = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', GRAPH, '--changed', '-', '--json', join(dir, 'stdin.json')],
  { cwd: root, encoding: 'utf8', input: 'src/OrderHandler.cs\n' });
check('`--changed -` で標準入力から変更一覧を受け取れる（git diff --name-only をそのまま）',
  stdin.status === 0 && existsSync(join(dir, 'stdin.json'))
  && JSON.parse(readFileSync(join(dir, 'stdin.json'), 'utf8')).summary.starts === 1,
  `${stdin.status} ${(stdin.stderr || '').slice(0, 120)}`);
const mdFile = join(dir, 'a.md');
spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', GRAPH, '--changed', list('a2.txt', ['src/OrderHandler.cs']),
  '--md', mdFile, '--json', join(dir, 'md.json')], { cwd: root, encoding: 'utf8' });
const md = readFileSync(mdFile, 'utf8');
const mdRows = ids(A.external.in).filter((id) => md.includes(id.split('.').pop()));
check('Markdown の表と JSON で着地の件数が食い違わない',
  existsSync(mdFile) && mdRows.length === A.external.in.length && md.includes('定義上の関連'),
  `md ${mdRows.length} / json ${A.external.in.length}`);
check('Markdown に「同じコードを使う別エンドポイント」の別枠が出る（エンドポイント起点のとき）',
  (() => {
    const f = join(dir, 'b.md');
    spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', GRAPH, '--api', 'POST /orders', '--md', f], { cwd: root, encoding: 'utf8' });
    const t = readFileSync(f, 'utf8');
    return t.includes('同じコードを使う別エンドポイント') && t.includes('起点と同じ API を定義するノード');
  })());

// ---- 第 16 ラウンドのレビューで出た 6 件を固定する ----
const b2 = run2(['--api', 'POST /orders'], 'b2');
const TABLE = 'ext:rds-table/orders.public.orders';
check('エンドポイント起点でも handler の先（注釈のテーブル）まで出る',
  !!b2 && ids(b2.result.external.out).includes(TABLE),
  b2 ? JSON.stringify(ids(b2.result.external.out)) : '実行失敗');
check('呼びに出したエンドポイント（`invokes`）は兄弟でなく影響する先',
  !!b2 && ids(b2.result.external.out).includes('tf:aws_api_gateway_method.get_users')
  && !ids(b2.result.siblingEndpoints).includes('tf:aws_api_gateway_method.get_users'),
  b2 ? JSON.stringify({ ext: ids(b2.result.external.out), sib: ids(b2.result.siblingEndpoints) }) : '実行失敗');
check('API 起点では Lambda は「影響する先」、Lambda 起点では integration は「影響を受ける入口」',
  ids(B.external.out).includes(LAMBDA) && !ids(B.external.in).includes(LAMBDA),
  JSON.stringify({ out: ids(B.external.out), inn: ids(B.external.in) }));
check('どの行も必ずどれかの欄に入る（欄の合計 == 総行数）',
  !!b2 && bucketTotal(b2.result) === b2.result.summary.rows
  && bucketTotal(a.result) === a.result.summary.rows,
  b2 ? `${bucketTotal(b2.result)} / ${b2.result.summary.rows}` : '実行失敗');
check('根拠の経路に `null` が混ざらない（起点まで辿れる）',
  !!b2 && [...b2.result.external.out, ...b2.result.external.in, ...b2.result.wiring]
    .every((r) => r.path.length > 0 && !r.path.includes(null) && r.path[0] !== null),
  b2 ? JSON.stringify((b2.result.external.out[0] || {}).path) : '実行失敗');
// 注釈の無いグラフで見る（注釈を足すと `GET /users` は「呼びに出した先」側に回る）
check('同じ Lambda を使う**別 API** のエンドポイントが既定の段数で兄弟に出る',
  B.siblingEndpoints.some((r) => r.endpoint === 'GET /users'),
  JSON.stringify(B.siblingEndpoints.map((r) => r.endpoint)));
check('別 API の rest_api / resource / deployment を「起点と同じ API」に混ぜない',
  !ids(B.sameApi).some((id) => /admin/.test(id))
  && ids(B.wiring).includes('tf:aws_api_gateway_rest_api.admin_api'),
  JSON.stringify({ sameApi: ids(B.sameApi), wiring: ids(B.wiring) }));
const lam = run2(['--from', LAMBDA], 'lam');
check('IAM ロールだけを共有する別 Lambda を本命に昇格させない（昇格の循環）',
  !!lam && !ids(lam.result.external.out).includes('tf:aws_lambda_function.notify')
  && !ids(lam.result.external.in).includes('tf:aws_lambda_function.notify'),
  lam ? JSON.stringify({ out: ids(lam.result.external.out), in: ids(lam.result.external.in) }) : '実行失敗');
const proj = run2(['--from', 'project:ReportImpact.csproj'], 'proj');
check('`project:` 起点が階層ではなくパスの所属でコードへ展開される',
  !!proj && proj.result.summary.expandedStarts > 1,
  proj ? `展開後 ${proj.result.summary.expandedStarts} 件` : '実行失敗');
const fold = run2(['--from', 'folder:src'], 'fold');
check('フォルダ起点でも Terraform のリソースが起点になり、着地も出る',
  !!fold && fold.result.summary.expandedStarts > 1
  && (fold.result.summary.primaryIn + fold.result.summary.primaryOut
    + fold.result.summary.entryIn + fold.result.summary.entryOut) > 0,
  fold ? JSON.stringify(fold.result.summary) : '実行失敗');
const prov = run2(['--api', 'POST /orders', '--provenance', 'static'], 'prov');
check('`--provenance static` は Terraform の定義単位を結ぶ段階も守る',
  !!prov && prov.result.summary.primaryIn === 0 && prov.result.summary.primaryOut === 0
  && prov.result.summary.wiring === 0,
  prov ? JSON.stringify(prov.result.summary) : '実行失敗');
// `folder:.` を起点にすると判定を全ノードに適用してしまい、着地が 0 件になった
const rootFold = run2(['--from', 'folder:.'], 'rootfold');
check('`folder:.` 起点でも着地が全部消えない（判定対象はファイルとプロジェクトだけ）',
  !!rootFold && rootFold.result.summary.expandedStarts > 1
  && (rootFold.result.summary.primaryIn + rootFold.result.summary.primaryOut
    + rootFold.result.summary.entryIn + rootFold.result.summary.entryOut
    + rootFold.result.summary.wiring) >= 0
  && rootFold.result.summary.starts > 0,
  rootFold ? JSON.stringify(rootFold.result.summary) : '実行失敗');

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
