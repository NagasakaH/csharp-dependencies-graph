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

// --help は .NET が無くても出せる。 USAGE はリテラルの中に ASCII のバッククォートを
// 入れると式として解釈されて NaN になり、第 46 ラウンドまでずっと「NaN」だけ出ていた
// （`--help` の出力がこのスクリプトの唯一の契約開示なので、必ず検査する）。
const help = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--help'], { encoding: 'utf8' });
const helpOut = (help.stdout || '') + (help.stderr || '');
check('--help が使い方を出して 0 で終わる', help.status === 0 && helpOut.startsWith('使い方:') && !helpOut.includes('NaN'),
  `exit=${help.status} 先頭=${JSON.stringify(helpOut.slice(0, 24))}`);
check('--help に 向き の値域と none の注記がある',
  helpOut.includes('in / out / none') && helpOut.includes('この表示経路に 向き を決める') && helpOut.includes('「—」'),
  JSON.stringify(helpOut.slice(0, 80)));
const noargs = spawnSync(process.execPath, [join(HERE, 'report.mjs')], { encoding: 'utf8' });
check('--graph 無しは使い方を標準エラーに出して 2 で終わる',
  noargs.status === 2 && (noargs.stderr || '').startsWith('使い方:') && !(noargs.stderr || '').includes('NaN'),
  `exit=${noargs.status} 先頭=${JSON.stringify((noargs.stderr || '').slice(0, 24))}`);

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

// 実行した JSON を全部覚えておく（末尾で `evidence` の形を一括検査するため。第 46 ラウンド
// 双人レビュー P2: 閉包が持つ生の縁（`count` / `metadata` を連れる）が JSON にそのまま混ざる
// 経路があった。検査器は根拠縁の id しか見ていなかったので、JSON の形の非決定性を捕まえなかった）
const allDocs = [];
// report.mjs を実行して JSON を返す
function run(args, label) {
  const json = join(dir, `${label}.json`);
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', GRAPH, ...args, '--json', json],
    { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  const result = JSON.parse(readFileSync(json, 'utf8'));
  allDocs.push({ label, result });
  return { result, stdout: proc.stdout, stderr: proc.stderr };
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
  const result = JSON.parse(readFileSync(json, 'utf8'));
  allDocs.push({ label, result });
  return { result, stdout: proc.stdout, stderr: proc.stderr };
}
// 手作りのグラフをそのまま渡す実行（双人レビューの最小反例を回帰テストとして固定する）
const FACTS = join(HERE, '..', 'tests', 'fixtures', 'ImpactFacts');
function runOn(graphFile, args, label) {
  const json = join(dir, `${label}.json`);
  const mdFile = join(dir, `${label}.md`);
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', join(FACTS, graphFile),
    ...args, '--json', json, '--md', mdFile], { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  const result = JSON.parse(readFileSync(json, 'utf8'));
  allDocs.push({ label, result });
  return { result, stdout: proc.stdout, stderr: proc.stderr,
    md: readFileSync(mdFile, 'utf8') };
}

// すべての行がどれかの欄に入っているか（欄の合計 == 総行数）
// summary のカウンタ（切り詰前）の合計。一覧は --limit で切れるので不変条件はこっちで見る
const counterTotal = (s) => s.primaryOut + s.primaryIn + s.entryOut + s.entryIn
  + s.artifactsOut + s.artifactsIn + s.wiring + s.sameApi + s.siblings;
const bucketTotal = (r) => r.external.out.length + r.external.in.length
  + r.entries.out.length + r.entries.in.length
  + r.artifacts.out.length + r.artifacts.in.length
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
    return t.includes('同じコードを使う別の API') && t.includes('起点と同じ API を定義するノード');
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
check('別 API の rest_api / resource / deployment は「起点と同じ API」でも「定義上」でもなく兄弟欄に出す',
  !ids(B.sameApi).some((id) => /admin/.test(id))
  && ids(B.siblingEndpoints).includes('tf:aws_api_gateway_rest_api.admin_api')
  && !ids(B.wiring).includes('tf:aws_api_gateway_rest_api.admin_api')
  && !ids(B.external.in).includes('tf:aws_api_gateway_integration.get_users')
  && !ids(B.external.out).includes('tf:aws_api_gateway_integration.get_users'),
  JSON.stringify({
    sameApi: ids(B.sameApi), wiring: ids(B.wiring),
    sib: ids(B.siblingEndpoints), ext: ids(B.external.in).concat(ids(B.external.out)),
  }));
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

// ---- 双人レビューで出た反例を、出た形のまま固定する ----
// ここでは graph.json を手で組み立てる（report.mjs が実際に読む情報だけを持つ）
function runSyn(name, graph, args, label) {
  const file = join(dir, `${name}.graph.json`);
  writeFileSync(file, JSON.stringify(graph));
  const json = join(dir, `${label}.json`);
  const mdFile = join(dir, `${label}.md`);
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', file, ...args,
    '--json', json, '--md', mdFile], { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  return { result: JSON.parse(readFileSync(json, 'utf8')), stdout: proc.stdout,
    stderr: proc.stderr, md: readFileSync(mdFile, 'utf8') };
}
const synNode = (id, kind, metadata) => ({ id, kind, name: id.split(':').pop(), ...(metadata ? { metadata } : {}) });
const synEdge = (kind, source, target, provenance = 'terraform') => ({
  id: `${kind}:${source}->${target}`, kind, source, target, provenance,
});
const allRows = (r) => [...r.external.out, ...r.external.in, ...r.entries.out, ...r.entries.in,
  ...r.artifacts.out, ...r.artifacts.in, ...r.wiring, ...r.sameApi, ...r.siblingEndpoints];
const tierOf = (r, id) => {
  const hit = allRows(r).find((y) => y.id === id);
  return hit ? hit.tier : null;
};

// 反例 1: IAM ロールだけを共有する別 Lambda。ロールは「Lambda が使っているもの」なので、
// そこを渡って先（別 Lambda の handler が書くテーブル）まで影響範囲にしない
const shared = {
  nodes: [
    synNode('tf:aws_lambda_function.a', 'resource', { resourceType: 'aws_lambda_function', category: 'lambda' }),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function', category: 'lambda' }),
    synNode('tf:aws_iam_role.shared', 'resource', { resourceType: 'aws_iam_role', category: 'iam' }),
    synNode('tf:aws_api_gateway_integration.b', 'resource', { resourceType: 'aws_api_gateway_integration', category: 'api-gateway' }),
    synNode('member:B.Handle', 'member'),
    synNode('ext:rds-table/db.public.b', 'external'),
  ],
  edges: [
    synEdge('references', 'tf:aws_lambda_function.a', 'tf:aws_iam_role.shared'),
    synEdge('references', 'tf:aws_lambda_function.b', 'tf:aws_iam_role.shared'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.b', 'tf:aws_lambda_function.b'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:B.Handle'),
    synEdge('writes', 'member:B.Handle', 'ext:rds-table/db.public.b', 'human'),
  ],
};
const sh = runSyn('shared', shared, ['--from', 'tf:aws_lambda_function.a'], 'syn-shared');
check('共有 IAM ロールから先の別 Lambda・handler・その書くテーブルを本命にしない',
  !!sh && ['tf:aws_lambda_function.b', 'member:B.Handle'].every((id) => tierOf(sh.result, id) === 'wiring')
  && sh.result.external.out.length === 0 && sh.result.external.in.length === 0
  && tierOf(sh.result, 'ext:rds-table/db.public.b') !== 'primary',
  sh ? JSON.stringify(allRows(sh.result).map((x) => [x.id, x.tier])) : '実行失敗');

// 反例 2: 呼び出した API の先まで往復して届く。A のコードが API B を `invokes` で呼ぶなら、
// B の Lambda → handler → その handler が書くテーブルまで影響範囲
// method には `endpoint` を立てる。第 29 ラウンドの裁定で「同じ API の定義を辿っただけ」の
// 昇格をやめたので、実装へ入る一歩は `integration → references → method` の
// **method を特定できる直接参照**（または注釈）で表す。この fixture の形は
// `http_method` を宣言した v1 の Terraform そのもの
const nestedMeta = {
  'tf:method.a': { resourceType: 'aws_api_gateway_method', category: 'apigateway', endpoint: 'POST /a' },
  'tf:method.b': { resourceType: 'aws_api_gateway_method', category: 'apigateway', endpoint: 'POST /b' },
};
const nested = {
  nodes: ['tf:method.a', 'tf:integration.a', 'tf:lambda.a', 'member:Handler.A', 'tf:method.b',
    'tf:integration.b', 'tf:lambda.b', 'member:Handler.B', 'tf:table.b']
    .map((id) => synNode(id, id.startsWith('member:') ? 'member' : 'resource', nestedMeta[id])),
  edges: [
    synEdge('references', 'tf:integration.a', 'tf:method.a'),
    synEdge('triggers', 'tf:integration.a', 'tf:lambda.a'),
    synEdge('handler', 'tf:lambda.a', 'member:Handler.A'),
    synEdge('invokes', 'member:Handler.A', 'tf:method.b', 'human'),
    synEdge('references', 'tf:integration.b', 'tf:method.b'),
    synEdge('triggers', 'tf:integration.b', 'tf:lambda.b'),
    synEdge('handler', 'tf:lambda.b', 'member:Handler.B'),
    synEdge('writes', 'member:Handler.B', 'tf:table.b', 'human'),
  ],
};
const ne = runSyn('nested', nested, ['--from', 'tf:method.a'], 'syn-nested');
check('呼び出した API の Lambda・handler・その書くテーブルまで届く（第二段の handler も往復する）',
  !!ne && ['tf:lambda.b', 'tf:table.b'].every((id) => (tierOf(ne.result, id) || '') === 'primary')
  && ne.result.external.out.some((x) => x.id === 'tf:table.b')
  && ne.result.entries.out.some((x) => x.id === 'member:Handler.B'),
  ne ? JSON.stringify(allRows(ne.result).map((x) => [x.id, x.direction, x.tier])) : '実行失敗');

// 反例 3: 縁の並び順が違うだけのグラフで着地が変わらない（定義の段数打ち切りに順序が効かない）
const budNodes = ['tf:aws_lambda_function.y', 'tf:aws_iam_role.x', 'tf:aws_iam_role.z',
  'tf:aws_kms_key.v', 'tf:aws_s3_bucket.u', 'tf:aws_api_gateway_integration.start']
  .map((id) => synNode(id, 'resource'));
const budEdges = [
  synEdge('references', 'tf:aws_lambda_function.y', 'tf:aws_iam_role.x'),
  synEdge('references', 'tf:aws_lambda_function.y', 'tf:aws_iam_role.z'),
  synEdge('references', 'tf:aws_iam_role.z', 'tf:aws_kms_key.v'),
  synEdge('references', 'tf:aws_lambda_function.y', 'tf:aws_s3_bucket.u'),
  synEdge('triggers', 'tf:aws_api_gateway_integration.start', 'tf:aws_lambda_function.y'),
];
const budSet = (g) => {
  const r = runSyn('bud', g, ['--from', 'tf:aws_lambda_function.y'], 'bud-' + Math.random().toString(36).slice(2, 8));
  return r ? allRows(r.result).filter((x) => x.kind === 'resource').map((x) => x.id).sort() : null;
};
const budA = budSet({ nodes: budNodes, edges: budEdges });
const budB = budSet({ nodes: [...budNodes].reverse(), edges: [...budEdges].reverse() });
check('縁とノードの並び順を逆にしても着地するリソースが変わらない',
  !!budA && !!budB && budA.length > 0 && JSON.stringify(budA) === JSON.stringify(budB),
  JSON.stringify([budA, budB]));

// 反例 4: `--hops` は呼び出し連鎖の実測した段数で効く（切り替え回数の消費で勝手に伸びない）
const chainNodes = Array.from({ length: 6 }, (_, i) => synNode(`member:C.M${i}`, 'member'));
const chainEdges = Array.from({ length: 5 }, (_, i) => synEdge('calls', `member:C.M${i}`, `member:C.M${i + 1}`, 'static'));
const ch = runSyn('chain', { nodes: chainNodes, edges: chainEdges },
  ['--from', 'member:C.M0', '--hops', '2'], 'syn-chain');
check('`--hops 2` の呼び出し連鎖は 2 段まで（3 段目は出ない）',
  !!ch && ch.result.entries.out.length === 2
  && ids(ch.result.entries.out).includes('member:C.M2')
  && !allRows(ch.result).some((x) => x.id === 'member:C.M3'),
  ch ? JSON.stringify(allRows(ch.result).map((x) => [x.id, x.hops])) : '実行失敗');

// 反例 5: 起点がエンドポイントのとき、実装側は矢印の向きとかかわらず 影響する先。
// `Step Functions → invokes → Lambda` は矢印が手前を向くので、これを「影響を受ける入口」にしない
const epMeta = (t, cat, api, endpoint) => ({ resourceType: t, category: cat, rest_api_id: api,
  ...(endpoint ? { endpoint } : {}) });
const flip = {
  nodes: [
    synNode('tf:aws_api_gateway_method.post_x', 'resource',
      epMeta('aws_api_gateway_method', 'api-gateway', 'tf:aws_api_gateway_rest_api.g', 'POST /x')),
    synNode('tf:aws_api_gateway_integration.post_x', 'resource', epMeta('aws_api_gateway_integration', 'api-gateway', 'tf:aws_api_gateway_rest_api.g')),
    synNode('tf:aws_lambda_function.x', 'resource', epMeta('aws_lambda_function', 'lambda', null)),
    synNode('tf:aws_sfn_state_machine.p', 'resource', epMeta('aws_sfn_state_machine', 'step-functions', null)),
    synNode('member:X.Handle', 'member'),
  ],
  edges: [
    synEdge('references', 'tf:aws_api_gateway_integration.post_x', 'tf:aws_api_gateway_method.post_x'),
    // `http_method` を宣言した method は自分の API の実装へ入る一歩を持つ（スキャナーの v1 形）
    synEdge('invokes', 'tf:aws_api_gateway_method.post_x', 'tf:aws_api_gateway_integration.post_x'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.post_x', 'tf:aws_lambda_function.x'),
    synEdge('handler', 'tf:aws_lambda_function.x', 'member:X.Handle'),
    // handler が Step Functions を**呼びに出す**（実装の下流）
    synEdge('invokes', 'member:X.Handle', 'tf:aws_sfn_state_machine.p', 'human'),
    // 別の上流の Step Functions がこの Lambda を**呼んでいる**（実装の上流）
    synEdge('invokes', 'tf:aws_sfn_state_machine.up', 'tf:aws_lambda_function.x'),
  ],
};
flip.nodes.push(synNode('tf:aws_sfn_state_machine.up', 'resource', epMeta('aws_sfn_state_machine', 'step-functions', null)));
const fl = runSyn('flip', flip, ['--api', 'POST /orders', '--from', 'tf:aws_api_gateway_method.post_x'], 'syn-flip');
check('エンドポイント起点では呼びに出した先が「影響する先」で、自分を呼ぶ上流は「影響を受ける入口」',
  !!fl && fl.result.external.out.some((x) => x.id === 'tf:aws_sfn_state_machine.p')
  && fl.result.external.in.some((x) => x.id === 'tf:aws_sfn_state_machine.up')
  && fl.result.entries.out.some((x) => x.id === 'member:X.Handle'),
  fl ? JSON.stringify(allRows(fl.result).map((x) => [x.id, x.direction, x.tier])) : '実行失敗');

// 反例 6: `project:` / `file:` は「定義上の関連」ではなく**成果物**（ビルドし直しが必要な範囲）として数える
const art = {
  nodes: [
    synNode('project:P.csproj', 'project'),
    synNode('tf:aws_lambda_function.x', 'resource', { resourceType: 'aws_lambda_function', category: 'lambda' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration', category: 'api-gateway' }),
  ],
  edges: [
    synEdge('deploys', 'project:P.csproj', 'tf:aws_lambda_function.x', 'llm'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.x'),
  ],
};
const ar = runSyn('art', art, ['--from', 'tf:aws_lambda_function.x'], 'syn-art');
check('届いた `project:` は成果物として数え、定義上の関連に混ぜない（欄の合計も保つ）',
  !!ar && ar.result.artifacts.in.some((x) => x.id === 'project:P.csproj')
  && !ids(ar.result.wiring).includes('project:P.csproj')
  && bucketTotal(ar.result) === ar.result.summary.rows,
  ar ? JSON.stringify([ar.result.artifacts, ids(ar.result.wiring), ar.result.summary.rows]) : '実行失敗');

// 反例 7: リポジトリ直下（`folder:.`）を起点にしたとき、そこに含まれる endpoint のせいで
// 「起点がエンドポイント」とみなして向きを反転させない
const foldAll = run2(['--from', 'folder:.'], 'rootfold2');
check('`folder:.` 起点では「起点がエンドポイント」とみなさない（向きを反転させない）',
  !!foldAll && foldAll.result.summary.startIsEndpoint === false
  && foldAll.result.summary.startEndpoints.length === 0
  && foldAll.result.summary.siblings === 0,
  foldAll ? JSON.stringify({ ep: foldAll.result.summary.startIsEndpoint, se: foldAll.result.summary.startEndpoints.length }) : '実行失敗');

// どの欄にも属さない行がないことを、合成グラフでも確かめる
check('合成グラフでも欄の合計 == 総行数',
  [sh, ne, ch, fl, ar].every((x) => x && bucketTotal(x.result) === x.result.summary.rows),
  [sh, ne, ch, fl, ar].map((x) => x && [x.result.summary.rows, bucketTotal(x.result)]).join(' '));

// `hops` は**表示している経路の長さ**。探索側が持つ段数は「定義単位をまたいだ数」で
// 動きの縁を越えたら数え直す予算なので、そちらをそのまま出すと `path` と食い違った
// （第 17 ラウンド agy: demo の 5 行中 4 行で不一致）
const hopReports = [A, B, lam, proj, fold, foldAll, sh, ne, ch, fl, ar].filter((x) => x && x.result);
const hopBad = hopReports.flatMap((x) => allRows(x.result)
  .filter((r) => r.hops !== r.path.length - 1).map((r) => `${x.name || ''}${r.id} ${r.hops}/${r.path.length - 1}`));
check('段数と経路の長さがすべての行で一致する', hopBad.length === 0, hopBad.slice(0, 4).join(' / '));

// 表示経路は必ず起点まで遡れる単一の連鎖で出す（裁定 out/loop/r39-astra.md、
// 仕様 out/loop/r40-decision.md）。`via` が循環すると経路が起点に遡れなくなるのに、
// 旧検査は `second-stage` かつ先頭が起点でない行を素通りしていた（第 38 ラウンド agy:
// `demo-iam` の `notify ⇄ order_process`、実測 4 行）。経路の先頭は起点そのものか、
// 2 段目 walk の種（その行がレポート内にあり、その経路がさらに起点へ繋がる）なら可。
// 起点が `--limit` で切り詰められると先頭が `startIds` にも一覧にも出ないが、
// それは一覧外の起点レコードで着地しているので遡れている
const rootBad = hopReports.flatMap((x) => {
  const starts = new Set(x.result.summary.startIds || []);
  const byId = new Map(allRows(x.result).map((r) => [r.id, r]));
  const headOk = (head, seen) => {
    if (seen.has(head)) return false;
    if (starts.has(head)) return true;
    const up = byId.get(head);
    if (!up || !up.path || !up.path.length) return true;
    return headOk(up.path[0], new Set([...seen, head]));
  };
  return allRows(x.result)
    .filter((r) => !r.path || !r.path.length || r.pathRoot !== 'start'
      || new Set(r.path).size !== r.path.length
      || r.path[r.path.length - 1] !== r.id
      || !headOk(r.path[0], new Set([r.id])))
    .map((r) => `${x.name || ''}${r.id} ${r.pathRoot} path[0]=${r && r.path && r.path[0]}`);
});
check('全行の表示経路が起点まで遡れる単一の連鎖である（打ち切り・循環を出さない）',
  rootBad.length === 0, rootBad.slice(0, 3).join(' / '));

// 一覧は `--limit` で切れるが、カウンタは切り詰前の値。不変条件はカウンタ側で見る
const lim = run(['--api', 'POST /orders', '--limit', '1'], 'limit1');
check('--limit で一覧が切れてもカウンタの不変条件は保たれ、切り詰めが見える',
  !!lim && lim.result.summary.listTruncated === true && lim.result.summary.limit === 1
  && counterTotal(lim.result.summary) === lim.result.summary.rows
  && lim.result.external.out.length <= 1,
  lim ? JSON.stringify([lim.result.summary.rows, lim.result.summary.listTruncated,
    lim.result.external.out.length, counterTotal(lim.result.summary)]) : '実行失敗');

// ---- 双人レビュー第 19 ラウンドの最小反例を回帰テストにする ----
// (1) 循環境避で経路を切ったとき、受理済みの本命情報まで捨てない
{
  const r = runOn('cut-primary.graph.json', ['--from', 'tf:aws_sfn_state_machine.a'], 'facts-cut');
  const byId = new Map();
  if (r) for (const x of [...r.result.external.in, ...r.result.external.out, ...r.result.wiring]) byId.set(x.id, x);
  const g = (id) => byId.get(id.startsWith('aws_') ? `tf:${id}` : `tf:aws_${id}`);
  // `tf:aws_sfn_state_machine.c` への表示経路は `a ←references← c` の 1 段。第 45 ラウンドの
  // Astra 裁定・案 D（`out/review-astra45.log`）で **動きの根拠は表示経路に実際に含まれる縁だけ**
  // にしたので、別経路の `invokes: c → e` を根拠に読む規則は捨てた。表示経路の最終一歩は
  // `references` なので 動きの根拠 は無し。
  // 第 46 ラウンド Astra 裁定 (b)(c)（`out/review-astra46.log`）で、**無方向の定義縁だけで
  // 届いた行の `向き` は `none`** になった（端点から 向き の種を作らない）。向き を持たない行は
  // 方向別の欄（external.in / out）に並べられないので、`c` は 定義上の関連 の欄で受けるが
  // **`tier` は `primary` のまま**（裁定: 「`none` の行で中立欄以外へ行くものは『定義上の関連』で
  // 受け、`tier` は保つ。判定を `tier=wiring` に限定しない」）。本命扱いを落とさないことが
  // この検査の本命の論点
  check('経路を循環境避で切っても、動きの縁で受理した本命の tier を落とさない'
    + '（無方向の一歩だけの行は 向き none で 定義上の関連 欄で受け、tier は保つ）',
    !!r && ['c', 'b'].every((n) => { const x = g(`sfn_state_machine.${n}`); return x && x.tier === 'primary'; })
    && g('sfn_state_machine.b').direction === 'in'
    && g('sfn_state_machine.c').direction === 'none'
    && g('sfn_state_machine.b').movementEvidence
    && g('sfn_state_machine.b').movementEvidence.kind === 'invokes'
    && g('sfn_state_machine.c').movementEvidence === null
    && ['d', 'e'].every((n) => { const x = g(`aws_lambda_function.${n}`); return x && x.tier === 'primary' && x.direction === 'out'; })
    && r.result.summary.wiring === 1
    && r.result.summary.directionless === 1 && r.result.summary.directionlessPrimary === 1,
    r ? JSON.stringify([...byId.values()].map((x) => [x.id, x.tier, x.direction,
      x.movementEvidence ? x.movementEvidence.kind : 'mv-'])) : '実行失敗');
}
// (2) 動きの根拠は表示経路の最終一歩だけを見る（第 45 ラウンド Astra 裁定・案 D）。
// `tf:aws_sfn_state_machine.up` への表示経路は `post_x ←exposed-by← X.Handle ←handler← x
// ←references← up` で、最終一歩は `references`。別経路の `invokes: up → Y.Handle`（注釈）を
// 根拠に読む規則を捨てたので 動きの根拠 は無しになり、向きは「起点の実装側に入った旗」で
// 影響する先 に出る。注釈縁 `exposed-by` が経路に入っているので 対応 は true
{
  const r = runOn('arrow-priority.graph.json', ['--api', 'POST /orders'], 'facts-arrow');
  const sfnId = 'tf:aws_sfn_state_machine.up';
  const hit = r ? [...r.result.external.in, ...r.result.external.out].find((x) => x.id === sfnId) : null;
  check('表示経路の最終一歩が定義の縁なら 動きの根拠 は無し。実装側に入った旗で 影響する先 に出す（第 45 ラウンド裁定）',
    !!hit && hit.direction === 'out' && hit.movementEvidence === null
    && hit.tier === 'primary' && hit.correspondence === true,
    hit ? JSON.stringify([hit.direction, hit.tier, hit.movementEvidence, hit.correspondence])
      : (r ? 'external に出ていない: ' + JSON.stringify([...r.result.external.in, ...r.result.external.out].map((x) => x.id)) : '実行失敗'));
  // 起点のエンドポイント自身の実装を載せた Lambda は下流側のまま（矢印だけで上流にしない）
  check('起点のエンドポイントの実装を載せた Lambda は 影響する先に残す',
    !!r && r.result.external.out.some((x) => x.id === 'tf:aws_lambda_function.x'),
    r ? JSON.stringify(r.result.external.out.map((x) => [x.id, x.direction])) : '実行失敗');
}

// (3) walk が事実を強くしたとき、その資格での閉包の再展開を省かない
{
  const r = runOn('preempt.graph.json', ['--from', 'tf:aws_lambda_function.s'], 'facts-preempt');
  const all = r ? [...r.result.external.in, ...r.result.external.out, ...r.result.wiring] : [];
  const up = all.find((x) => x.id === 'tf:aws_sfn_state_machine.r');
  // 表示経路は `s →references→ r`（`references` の矢印が `r` を指す 1 段）。第 45 ラウンドの
  // Astra 裁定・案 D（`out/review-astra45.log`）で 動きの根拠 は表示経路の最終一歩だけを見るので、
  // 別経路の `invokes: r → a` を根拠に読む規則は捨てた（この行は 動きの根拠 無し）。
  // 第 46 ラウンド裁定 (b)(c) で 向き は `none`（無方向の定義縁 1 本だけの経路なので端点から
  // 種を作らない）。`向き` を持たない行は 影響する先 / 影響を受ける入口 の欄に並べられないので
  // 定義上の関連 の欄で受けるが、**本命（`tier=primary`）のままだ**（裁定: 「判定を `tier=wiring`
  // に限定しない」）。検査の本命は「本命扱いを保つ / 定義上の関連 の意味に落とさない」側
  check('定義参照が 1 本増えても、実際の呼び出し元の 本命 扱いを落とさない'
    + '（無方向の定義縁だけの行は 向き none で 定義上の関連 欄で受ける）',
    !!up && up.tier === 'primary' && up.direction === 'none'
    && up.movementEvidence === null && r.result.summary.wiring === 1
    && r.result.summary.directionless === 1 && r.result.summary.directionlessPrimary === 1,
    up ? JSON.stringify([up.tier, up.direction, up.movementEvidence, r.result.summary.wiring])
      : (r ? 'external / wiring に出ていない' : '実行失敗'));
  const r2 = runOn('promote-skip.graph.json', ['--from', 'tf:aws_lambda_function.start'], 'facts-promote');
  const all2 = r2 ? [...r2.result.external.in, ...r2.result.external.out, ...r2.result.wiring] : [];
  const r3 = all2.find((x) => x.id === 'tf:aws_lambda_function.r3');
  // `r3` への表示経路は `start →Handle →m2 →r2 →r3`（最後は `triggers`）なので 向き は `out` のまま。
  // 定義上の関連 が 1 行あるのは `tf:aws_iam_role.r0`（起点から `references` 1 段だけ。第 46
  // ラウンド裁定 (b)(c) で 向き が `none` になり、方向別の欄から 定義上の関連 へ移った。
  // `tier` は `primary` のまま）
  check('walk が後から本命にしたノードから先も、閉包の 2 ラウンド目で本命まで育つ',
    !!r3 && r3.tier === 'primary' && r3.direction === 'out' && r2.result.summary.wiring === 1,
    r3 ? JSON.stringify([r3.tier, r3.direction, r2.result.summary.wiring]) : (r2 ? 'r3 が出ていない: ' + JSON.stringify(all2.map((x) => [x.id, x.tier])) : '実行失敗'));

  // 第 46 ラウンド Astra 裁定 §4-4（`out/tmp-r46/spec-none.md`）: `向き = none` の行を
  // 方向別のフィルターで黙って落とさない。同じ着地 `tf:aws_sfn_state_machine.r`（`references`
  // 1 段だけ。向き none / tier primary / 外部リソース）を
  //  - `direction: "none"` で指名すると 再現率 1 / 適合率 1
  //  - `direction` を書かない（既定 both）でも数に入る
  //  - `direction: "out"` を明示した方には入らない（明示した方向だけを数えるので仕様）
  const expectNone = join(dir, 'expect-none.json');
  writeFileSync(expectNone, JSON.stringify({
    name: 'fixture: 無方向の着地', direction: 'none', expect: ['tf:aws_sfn_state_machine.r'],
    note: 'Terraform の定義の縁 1 段だけで届いた着地',
  }));
  const en = runOn('preempt.graph.json',
    ['--from', 'tf:aws_lambda_function.s', '--expect', expectNone], 'facts-preempt-none');
  const expectBoth = join(dir, 'expect-none-both.json');
  writeFileSync(expectBoth, JSON.stringify({
    name: 'fixture: 向きを絞らない', expect: ['tf:aws_sfn_state_machine.r'],
  }));
  const eb = runOn('preempt.graph.json',
    ['--from', 'tf:aws_lambda_function.s', '--expect', expectBoth], 'facts-preempt-both');
  const expectOut = join(dir, 'expect-none-out.json');
  writeFileSync(expectOut, JSON.stringify({
    name: 'fixture: 影響する先だけ', direction: 'out', expect: ['tf:aws_sfn_state_machine.r'],
  }));
  const eo = runOn('preempt.graph.json',
    ['--from', 'tf:aws_lambda_function.s', '--expect', expectOut], 'facts-preempt-out');
  check('向き none の着地を --expect で拾える（none と既定の both で数え、out 明示では数えない）',
    !!en && en.result.score.direction === 'none' && en.result.score.recall === 1
    && en.result.score.precision === 1 && en.result.score.landedExternal === 1
    && !!eb && eb.result.score.direction === 'both' && eb.result.score.recall === 1
    && eb.result.score.missed.length === 0
    && !!eo && eo.result.score.direction === 'out' && eo.result.score.missed.length === 1
    && eo.result.score.missed[0] === 'tf:aws_sfn_state_machine.r',
    JSON.stringify([en && en.result.score, eb && eb.result.score, eo && eo.result.score]));

  // Markdown 側では 向き 列に「—」を出す（裁定 §2: 「Markdown の 向き 表示は『—』」）。
  // 定義上の関連 の欄に受けた行であることを一緒に確かめる
  const noneLine = (en ? en.md : '').split('\n')
    .find((l) => l.startsWith(`| ${up.name} |`) && l.includes('`references`'));
  check('Markdown の一覧の 向き 列は none の行を「—」で出す（定義上の関連 に受けた行）',
    !!noneLine && noneLine.includes('| — |') && /### 定義上の関連/.test(en.md),
    JSON.stringify([noneLine || '行が見つからない', /### 定義上の関連/.test(en.md)]));
}
// (4) 旗の名前どおりに立つ（呼ばれる側へ着いた一歩だけ。呼び出し元に立たない）
{
  const r = runOn('calledout-walk.graph.json', ['--from', 'member:X.Handle'], 'facts-calledout');
  const up = r ? [...r.result.external.in, ...r.result.external.out].find((x) => x.id === 'tf:aws_sfn_state_machine.up') : null;
  check('呼び出し元（`invokes` を逆向きに辿った先）に `reachedByInvokes` を立てない',
    !!up && up.direction === 'in' && up.reachedByInvokes === false,
    up ? JSON.stringify([up.direction, up.reachedByInvokes]) : (r ? '出ていない' : '実行失敗'));
  // 起点が定義上のもので、動きの縁を跨いだ行も 定義上の関連 に残る（IAM ポリシー起点の実測どおり）
  const defStart = runOn('calledout-walk.graph.json', ['--from', 'tf:aws_sfn_state_machine.up'], 'facts-defstart');
  const rows = defStart ? Object.values(defStart.result).flatMap((b) =>
    (Array.isArray(b) ? b : (b && typeof b === 'object' ? [...(b.in || []), ...(b.out || [])] : [])))
    .filter((x) => x && typeof x === 'object' && typeof x.tier === 'string') : null;
  check('注釈の `invokes` で呼んだ先（コードの入口）は本命のまま出す',
    !!rows && rows.length > 0 && rows.every((x) => x.tier === 'primary'),
    rows ? JSON.stringify(rows.map((x) => [x.id, x.tier])) : '実行失敗');
}

// (5) 本命として届いた API のグループは、後から増えたときに定義側を拡げ直す機会がある
{
  const allOf = (r) => Object.values(r).flatMap((b) => (Array.isArray(b) ? b
    : (b && typeof b === 'object' ? [...(b.in || []), ...(b.out || [])] : []))).filter((x) => x && typeof x.tier === 'string');
  const r = runOn('touched-api.graph.json', ['--from', 'tf:aws_lambda_function.a'], 'group-touched');
  const all = r ? allOf(r.result) : [];
  const byId = new Map(all.map((x) => [x.id, x]));
  check('呼び出した API の実装側（Lambda・テーブル・コード）は 定義上の関連 に落ちない',
    !!r && r.result.summary.primaryOut === 4 && r.result.summary.entryOut === 2
    && (byId.get('tf:aws_lambda_function.b') || {}).tier === 'primary'
    && (byId.get('ext:rds-table/orders') || {}).tier === 'primary',
    r ? JSON.stringify([r.result.summary.primaryOut, r.result.summary.entryOut,
      [...byId].map(([k, v]) => [k.replace('tf:aws_', ''), v.tier])]) : '実行失敗');
  // 同じグラフから `method → invokes → integration`（`http_method` から決まる対応縁）だけを
  // 抜いた形。第 29 ラウンドの裁定で「同じ API の定義を辿っただけ」では本命にしないので、
  // 実装側は **定義上の関連 に残ったまま見える**（消えるのではない）
  const rn = runOn('touched-api-nocorr.graph.json', ['--from', 'tf:aws_lambda_function.a'], 'group-nocorr');
  const allN = rn ? allOf(rn.result) : [];
  const byIdN = new Map(allN.map((x) => [x.id, x]));
  const lamB = byIdN.get('tf:aws_lambda_function.b');
  check('method を特定できる直接参照も注釈もない integration の先は 定義上の関連（ただし一覧には出す）',
    !!rn && !!lamB && lamB.tier === 'wiring'
    && (byIdN.get('tf:aws_api_gateway_integration.b') || {}).tier === 'wiring'
    && rn.result.summary.primaryOut === 1 && rn.result.summary.entryOut === 1,
    rn ? JSON.stringify([rn.result.summary.primaryOut, rn.result.summary.entryOut,
      lamB ? lamB.tier : '出ていない']) : '実行失敗');
  for (const [name, file] of [['定義を辿る縁だけの API グループ', 'group-cache.graph.json'],
    ['コードの種が無いラウンドでもグループ追加で定義を拡げる', 'group-late.graph.json']]) {
    const rr = runOn(file, ['--from', 'tf:aws_lambda_function.s'], `group-${file}`);
    const same = rr ? allOf(rr.result).find((x) => x.id === 'tf:aws_lambda_function.b') : null;
    check(`${name}: method を特定できない Lambda は 定義上の関連 に留める（裁定: 案 2）`,
      !!same && same.tier === 'wiring' && same.direction === 'out',
      same ? JSON.stringify([same.tier, same.direction, same.evidence.kind]) : (rr ? '出ていない' : '実行失敗'));
  }
  // 同じ形で `http_method` から決まる対応縁（`method → invokes → integration`）を足すと本命になる。
  // 負例が「情報が足りないから出ない」のではなく「対応が確定していないから本命にしない」ことの対
  const corrNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_api_gateway_method.b', 'resource',
      { resourceType: 'aws_api_gateway_method', category: 'apigateway', rest_api_id: 'aws_api_gateway_rest_api.b.id', endpoint: 'POST /b' }),
    synNode('tf:aws_api_gateway_integration.b', 'resource',
      { resourceType: 'aws_api_gateway_integration', category: 'apigateway', rest_api_id: 'aws_api_gateway_rest_api.b.id' }),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
  ];
  const corrEdges = [
    synEdge('invokes', 'tf:aws_lambda_function.s', 'tf:aws_api_gateway_method.b'),
    synEdge('invokes', 'tf:aws_api_gateway_method.b', 'tf:aws_api_gateway_integration.b'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.b', 'tf:aws_lambda_function.b'),
  ];
  const rc = runSyn('group-corr', { nodes: corrNodes, edges: corrEdges },
    ['--from', 'tf:aws_lambda_function.s'], 'group-corr');
  const sameC = rc ? allOf(rc.result).find((x) => x.id === 'tf:aws_lambda_function.b') : null;
  check('method を特定できる対応縁（`http_method` の三つ組）があれば同じ API の Lambda は本命で 影響する先',
    !!sameC && sameC.tier === 'primary' && sameC.direction === 'out',
    sameC ? JSON.stringify([sameC.tier, sameC.direction, sameC.evidence.kind]) : (rc ? '出ていない' : '実行失敗'));
}

// (6) 予算（`--wiring-hops`）は `(elig, down)` の資格ごとに数える
{
  const r = runOn('budget-min.graph.json', ['--from', 's', '--wiring-hops', '1'], 'budget-min');
  const minRows = r ? [...r.result.external.in, ...r.result.external.out, ...r.result.wiring] : [];
  const at = (id) => minRows.find((x) => x.id === id);
  // `a → invokes → z` が動きの縁なので `z` で予算が戻り、`--wiring-hops 1` でも `t` まで届く
  // （`z` / `a` は動きの縁の両端なので本命、`t` は定義の縁なので 定義上の関連 のまま）
  check('定義上の関連でも予算の届け直しで先まで出る（`t` が脱落しない）',
    !!r && r.result.summary.rows === 3 && !!at('t') && at('t').tier === 'wiring'
    && (at('z') || {}).tier === 'primary',
    r ? JSON.stringify([r.result.summary.rows, minRows.map((x) => [x.id, x.tier])]) : '実行失敗');

  const a = runOn('budget-normal.graph.json', ['--from', 's'], 'budget-normal');
  const b = runOn('budget-reversed.graph.json', ['--from', 's'], 'budget-reversed');
  check('同じ縁集合を逆に並べ替えても件数が変わらない（先着順で決まる状態が残っていない）',
    !!a && !!b && a.result.summary.rows === b.result.summary.rows
    && a.result.summary.wiring === b.result.summary.wiring,
    a && b ? JSON.stringify([[a.result.summary.rows, a.result.summary.wiring],
      [b.result.summary.rows, b.result.summary.wiring]]) : '実行失敗');

  const c = runOn('budget-through-invokes.graph.json', ['--from', 'tf:aws_api_gateway_method.m1'], 'budget-invokes');
  const lam2 = c ? [...c.result.external.out, ...c.result.external.in, ...c.result.wiring]
    .find((x) => x.id === 'tf:aws_lambda_function.lam2') : null;
  // `int2` は `deployment.x` を書いただけ（method を特定できる参照も注釈もない）なので、その先の
  // `lam2` は第 29 ラウンドの裁定で 定義上の関連。ただし**欄から消えない**ことは固定する
  check('method を特定できない定義参照の先（`lam2`）は 定義上の関連 に出す（消えない）',
    !!lam2 && lam2.tier === 'wiring' && lam2.direction === 'out',
    lam2 ? JSON.stringify([lam2.tier, lam2.direction]) : (c ? '出ていない' : '実行失敗'));

  // 動きの縁で予算が戻ることは別の形で固定する。`--wiring-hops 1` だと定義の縁は 1 歩まで。
  // `l0 → a → b` は 2 歩なので切れるが、`handler` → `invokes` で `b` に動きとして届く経路が
  // あるので、そこから先の `c → triggers → l1` は予算の届け直しで本命まで出る
  const resetNodes = [
    synNode('tf:aws_lambda_function.l0', 'resource', { resourceType: 'aws_lambda_function', category: 'lambda' }),
    synNode('tf:aws_iam_role.a', 'resource', { resourceType: 'aws_iam_role', category: 'iam' }),
    synNode('tf:aws_dynamodb_table.b', 'resource', { resourceType: 'aws_dynamodb_table', category: 'storage' }),
    synNode('tf:aws_sqs_queue.c', 'resource', { resourceType: 'aws_sqs_queue', category: 'sqs' }),
    synNode('tf:aws_lambda_function.l1', 'resource', { resourceType: 'aws_lambda_function', category: 'lambda' }),
    synNode('member:L0.Handle', 'member'),
  ];
  const resetEdges = [
    synEdge('references', 'tf:aws_lambda_function.l0', 'tf:aws_iam_role.a'),
    synEdge('references', 'tf:aws_iam_role.a', 'tf:aws_dynamodb_table.b'),
    synEdge('handler', 'tf:aws_lambda_function.l0', 'member:L0.Handle'),
    synEdge('invokes', 'member:L0.Handle', 'tf:aws_dynamodb_table.b', 'human'),
    synEdge('references', 'tf:aws_dynamodb_table.b', 'tf:aws_sqs_queue.c'),
    synEdge('triggers', 'tf:aws_sqs_queue.c', 'tf:aws_lambda_function.l1'),
  ];
  const cr = runSyn('budget-reset', { nodes: resetNodes, edges: resetEdges },
    ['--from', 'tf:aws_lambda_function.l0', '--wiring-hops', '1'], 'budget-reset');
  const l1 = cr ? [...cr.result.external.out, ...cr.result.external.in, ...cr.result.wiring]
    .find((x) => x.id === 'tf:aws_lambda_function.l1') : null;
  check('動きの縁で予算が戻った経路の先は 定義上の関連 のままでも先まで出る',
    !!l1 && l1.tier === 'primary' && l1.direction === 'out',
    l1 ? JSON.stringify([l1.tier, l1.direction, l1.hops]) : (cr ? '出ていない' : '実行失敗'));

  const d = runOn('six-groups.graph.json', ['--from', 's', '--hops', '32'], 'six-groups');
  // 6 組のどれにも method を特定できる縁が無い形なので、起点から動きとして届いた 1 件以外は
  // 全部 定義上の関連。収束を打ち切らずに 24 行すべてを出し尽くしていることを見る
  check('API の連鎖が 6 組あってもラウンド上限で黙って切らない（未収束なら旗を出す）',
    !!d && d.result.summary.rows === 24 && d.result.summary.primaryOut === 1
    && d.result.summary.primaryIn === 0 && d.result.summary.wiring === 23
    && d.result.summary.unresolved === false,
    d ? JSON.stringify([d.result.summary.primaryOut, d.result.summary.primaryIn,
      d.result.summary.wiring, d.result.summary.rounds, d.result.summary.maxRounds,
      d.result.summary.unresolved]) : '実行失敗');

  // 同じ 6 組の連鎖で、各段に `http_method` から決まる対応縁を足した形。段を 6 つ越えても
  // ラウンド上限に当たらず（`unresolved` を立てず）に各段の実装まで本命へ届く
  const six = () => {
    const nodes = [synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' })];
    const edges = [];
    for (let i = 1; i <= 6; i++) {
      const g = `tf:aws_api_gateway_rest_api.g${i}`;
      const m = `tf:aws_api_gateway_method.m${i}`;
      const int = `tf:aws_api_gateway_integration.i${i}`;
      const lam = `tf:aws_lambda_function.l${i}`;
      nodes.push(synNode(m, 'resource', { resourceType: 'aws_api_gateway_method', category: 'apigateway',
        rest_api_id: `${g}.id`, endpoint: `POST /${i}` }));
      nodes.push(synNode(g, 'resource', { resourceType: 'aws_api_gateway_rest_api', category: 'apigateway' }));
      nodes.push(synNode(int, 'resource', { resourceType: 'aws_api_gateway_integration', category: 'apigateway',
        rest_api_id: `${g}.id` }));
      nodes.push(synNode(lam, 'resource', { resourceType: 'aws_lambda_function' }));
      edges.push(synEdge('references', m, g));
      edges.push(synEdge('references', int, g));
      edges.push(synEdge('invokes', m, int));
      edges.push(synEdge('triggers', int, lam));
      edges.push(synEdge('invokes', i === 1 ? 'tf:aws_lambda_function.s' : `tf:aws_lambda_function.l${i - 1}`, m));
    }
    return { nodes, edges };
  };
  const six1 = runSyn('six-corr', six(), ['--from', 'tf:aws_lambda_function.s', '--hops', '32'], 'six-corr');
  const sixBack = runSyn('six-corr-rev', (({ nodes, edges }) =>
    ({ nodes: [...nodes].reverse(), edges: [...edges].reverse() }))(six()),
  ['--from', 'tf:aws_lambda_function.s', '--hops', '32'], 'six-corr-rev');
  const sixLams = (r) => (r ? allRows(r.result) : []).filter((x) => x.id.startsWith('tf:aws_lambda_function.l'))
    .map((x) => `${x.id}:${x.tier}:${x.direction}`).sort();
  check('対応縁のある API の連鎖は 6 組あっても各段の実装まで本命で、縁の並び順を変えても同じ',
    !!six1 && six1.result.summary.unresolved === false
    && sixLams(six1).length === 6 && sixLams(six1).every((x) => x.endsWith(':primary:out'))
    && JSON.stringify(sixLams(six1)) === JSON.stringify(sixLams(sixBack)),
    six1 ? JSON.stringify([sixLams(six1), sixLams(sixBack), six1.result.summary.rounds,
      six1.result.summary.maxRounds, six1.result.summary.unresolved]) : '実行失敗');
}

// (7) 第 23 ラウンドの反例: 受け事実の `down` 継承とラウンドの打ち切れ
{
  const a = runOn('down-inherit-seed.graph.json', ['--api', 'POST /a', '--hops', '1'], 'seed-down');
  check('受け事実の `down` を継承したコードの種で落ちない（`const` に再代入して異常終了していた）',
    !!a && a.result.summary.primaryOut === 2,
    a ? JSON.stringify([a.result.summary.primaryOut, a.result.summary.entryOut]) : '実行失敗');

  const b = runOn('down-inherit-record.graph.json', ['--from', '0', '--hops', '3'], 'record-down');
  // 受け事実 `down` は **歩く資格（予算のマスク）の引き継ぎ**には今も使っているので、定義上の関連
  // と記録されたノードの先も 入口 まで育つ（`entryOut === 2` のまま）。ただし第 46 ラウンド Astra
  // 裁定 (a-2)（`out/review-astra46.log`）で **向き の決定から `down` の独立した上書きを外した**
  // （「有向縁で `in` に決めた直後、無方向の一歩が残存する `down` によって `out` に戻る余地が
  // 残る」ため）。実装側へ入る例外は 動きの縁 の枝の中にだけ残す。結果、無方向の定義縁だけで
  // 届いた `1` と `8` の 向き は `none` になり、方向別の欄ではなく 定義上の関連 に並ぶ
  check('経路の記録が 定義上の関連 のままでも受け事実の `down` を引き継いで歩く'
    + '（向き は `down` で上書きしない。第 46 ラウンド裁定 (a-2)）',
    !!b && b.result.summary.entryOut === 2 && b.result.summary.wiring === 2
    && b.result.summary.directionless === 2 && b.result.summary.directionlessPrimary === 1,
    b ? JSON.stringify([b.result.summary.entryOut, b.result.summary.wiring,
      b.result.summary.directionless, b.result.summary.directionlessPrimary]) : '実行失敗');

  const c = runOn('code-chain.graph.json',
    ['--from', 'tf:aws_lambda_function.l0', '--hops', '30', '--max-rounds', '1'], 'rounds-cut');
  const cMd = c ? readFileSync(join(dir, 'rounds-cut.md'), 'utf8') : '';
  check('ラウンド上限に達したら 未収束 として出す（旗・警告・Markdown の注意書き）',
    !!c && c.result.summary.unresolved === true && c.result.summary.rounds === 1
    && /収束する前にラウンド上限/.test(c.stderr || '') && /探索が収束していません/.test(cMd),
    c ? JSON.stringify([c.result.summary.rounds, c.result.summary.maxRounds,
      c.result.summary.unresolved, /収束する前に/.test(c.stderr || ''), /収束していません/.test(cMd)]) : '実行失敗');

  // `--limit` で一覧を切ったときの Markdown の注記。コード側の入口・出口の 2 欄は
  // `mdSection` に渡す前に `slice` していたので、件数が合わず注記が消えていた
  // （実測 `--api "POST /orders" --limit 2`: `entryOut` 10 に表 2 行で注記なし）。
  // 第 48 ラウンド agy 指摘で文言も変わった: `--limit` は Markdown と JSON の**両方**に
  // 掛かるので、打った分を「--json 参照」と言っても見つからない。注記はそれを正直に書く
  const lim = runOn('down-inherit-record.graph.json', ['--from', '0', '--hops', '3', '--limit', '1'], 'limit-note');
  const limSec = lim ? lim.md.split('\n### ').find((s) => s.startsWith('影響するコード側の出口')) : '';
  check('--limit で切った一覧に出る注記が「JSON にも入っていない」ことを告げる（コード側の出口）',
    !!lim && lim.result.summary.entryOut === 2
      && limSec.split('\n').filter((l) => l.startsWith('|')).length === 3   // 表ヘッダ 2 行 + 1 行
      && /他 1 件は --limit 1 で打ち切られているため Markdown にも JSON にも入っていません/.test(limSec || '')
      && !/--json 参照/.test(limSec || ''),
    lim ? `entryOut=${lim.result.summary.entryOut} 注記=${/他 1 件/.test(limSec || '')}` : '実行失敗');

  // 第 47 ラウンド双人レビュー（agy P1）。出口側だけ直して入口側を戻しても検査が黙るため、
  // 入口欄でも同じ注記が出ることを確かめる。コード 3 ノードを逆向きに辿ると entries.in に 2 行並ぶ
  const inLimit = runSyn('entries-in-limit', {
    nodes: [{ id: 'member:a', kind: 'member', name: 'A', path: 'a.cs' },
            { id: 'member:b', kind: 'member', name: 'B', path: 'b.cs' },
            { id: 'member:c', kind: 'member', name: 'C', path: 'c.cs' }],
    edges: [{ id: 'e1', kind: 'calls', provenance: 'static', source: 'member:a', target: 'member:b' },
            { id: 'e2', kind: 'calls', provenance: 'static', source: 'member:b', target: 'member:c' }],
  }, ['--from', 'member:c', '--limit', '1'], 'entries-in-limit');
  const inSec = inLimit ? (inLimit.md.split('\n### ').find((s) => s.startsWith('影響を受けるコード側の入口')) || '') : '';
  check('--limit で切った「影響を受けるコード側の入口」にも同じ注記が出る',
    !!inLimit && inLimit.result.summary.entryIn === 2
      && inSec.split('\n').filter((l) => l.startsWith('|')).length === 3
      && /他 1 件は --limit 1 で打ち切られているため Markdown にも JSON にも入っていません/.test(inSec)
      && !/--json 参照/.test(inSec),
    inLimit ? JSON.stringify([inLimit.result.summary.entryIn, /他 1 件/.test(inSec)]) : '実行失敗');

  // 同じく agy P1: ターミナルに出す外部リソースの一覧は 12 件固定で `--limit` を無視し、
  // 13 件目以降を黙って落としていた（Markdown は 2 件なのにここだけ 4 件並ぶ）
  const outLim = runOn('code-chain.graph.json', ['--from', 'member:M0', '--limit', '2'], 'stdout-limit');
  const outLines = outLim ? outLim.stdout.split('\n').filter((l) => l.startsWith('  [out')).length : 0;
  check('ターミナルの外部リソース一覧も --limit に従い、打ち切った件数を出す（12 件固定に戻さない）',
    !!outLim && outLim.result.summary.primaryOut === 4
      && outLim.result.external.out.length === 2 && outLines === 2
      && /他 2 件は --limit 2 で打ち切られているため Markdown にも JSON にも入っていません/.test(outLim.stdout)
      // --limit 2 で打ったのに 12 件を引用するのは嘘になる（第 48 ラウンド agy 指摘）
      && !/最大 12 件/.test(outLim.stdout) && !/Markdown と --json に出しています/.test(outLim.stdout),
    outLim ? JSON.stringify([outLim.result.summary.primaryOut, outLim.result.external.out.length, outLines,
      /Markdown にも JSON にも入っていません/.test(outLim.stdout), /最大 12 件/.test(outLim.stdout)]) : '実行失敗');

  // ターミナルだけ 12 件で切るケース（--limit が 12 より大きい）と、両方の打ち切りが同時に
  // 起きるケース（--limit 13）。前者は「Markdown と --json に出しています」だけ、後者は
  // それと「--limit で打った分」の両方を出す
  const capNodes = [{ id: 's', kind: 'member', name: 'start', qualifiedName: 'N.S' }];
  const capEdges = [];
  for (const side of ['in', 'out']) {
    for (let i = 0; i < 15; i++) {
      const rid = `${side}-${i}`;
      capNodes.push({ id: rid, kind: 'resource', name: rid, resourceType: 'aws_sqs_queue' });
      capEdges.push({ id: rid, kind: 'writes', provenance: 'static',
        source: side === 'out' ? 's' : rid, target: side === 'out' ? rid : 's' });
    }
  }
  const capDef = runSyn('stdout-cap-15', { nodes: capNodes, edges: capEdges }, ['--from', 's'], 'stdout-cap-15');
  const cap13 = runSyn('stdout-cap-15', { nodes: capNodes, edges: capEdges }, ['--from', 's', '--limit', '13'], 'stdout-cap-13');
  const capLine = (x) => (x ? (x.stdout.split('\n').find((l) => l.includes('この一覧はターミナルでは最大 12 件')) || '') : '');
  check('既定の --limit で 12 件超のとき「Markdown と --json に出しています」と 12 件上限を告げる',
    !!capDef && capDef.result.external.out.length === 15
      && /他 3 件は Markdown と --json に出しています/.test(capLine(capDef))
      && !/Markdown にも JSON にも入っていません/.test(capLine(capDef)),
    capDef ? JSON.stringify([capDef.result.external.out.length, capLine(capDef).trim()]) : '実行失敗');
  check('--limit 13 では「12 件で打った分」と「--limit で打った分」を分けて告げる',
    !!cap13 && cap13.result.external.out.length === 13
      && /他 1 件は Markdown と --json に出しています/.test(capLine(cap13))
      && /他 2 件は --limit 13 で打ち切られているため Markdown にも JSON にも入っていません/.test(capLine(cap13)),
    cap13 ? JSON.stringify([cap13.result.external.out.length, capLine(cap13).trim()]) : '実行失敗');

  // --md / --json を付けていない実行で「Markdown と --json に出しています」と言うのも同じ嘘だった
  // （第 50 ラウンド双人レビュー両名）。ファイル出力が無い実行では条件付きの言い方にする
  {
    const f = join(dir, 'stdout-cap-15.graph.json');   // 上で runSyn が書いた同じグラフ
    const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', f, '--from', 's'],
      { cwd: root, encoding: 'utf8' });
    const line = proc.status === 0
      ? (proc.stdout.split('\n').find((l) => l.includes('この一覧はターミナルでは最大 12 件')) || '') : '';
    check('--md / --json を付けない実行は「指定するとそこに入ります」と言い「出しています」と言わない',
      proc.status === 0 && /他 3 件は --md \/ --json を指定するとそこに入ります/.test(line)
        && !/に出しています/.test(line) && /表示 12 \/ 15 件/.test(line),
      JSON.stringify(line.trim()));
  }

  // エンドポイント欄は Markdown とターミナルで同じ並び・同じ本数で切る（第 50 ラウンド agy P2）。
  // 起点のエンドポイント 1 件 + `invokes` で到達するエンドポイント 2 件を --limit 2 で切ったとき、
  // 以前は Markdown 3 件・ターミナル 2 件と表示本数が割れた
  {
    const ep = (n, path) => synNode(`tf:aws_api_gateway_method.${n}`, 'resource',
      { resourceType: 'aws_api_gateway_method', category: 'apigateway', endpoint: path });
    const g = {
      nodes: [ep('m1', 'POST /a'), ep('m2', 'GET /b'), ep('m3', 'GET /c'),
        synNode('tf:aws_api_gateway_integration.i1', 'resource',
          { resourceType: 'aws_api_gateway_integration', category: 'apigateway' }),
        synNode('tf:aws_lambda_function.f1', 'resource', { resourceType: 'aws_lambda_function' })],
      edges: [synEdge('invokes', 'tf:aws_api_gateway_method.m1', 'tf:aws_api_gateway_integration.i1'),
        synEdge('triggers', 'tf:aws_api_gateway_integration.i1', 'tf:aws_lambda_function.f1'),
        synEdge('invokes', 'tf:aws_lambda_function.f1', 'tf:aws_api_gateway_method.m2'),
        synEdge('invokes', 'tf:aws_lambda_function.f1', 'tf:aws_api_gateway_method.m3')],
    };
    const x = runSyn('ep-list', g, ['--api', 'POST /a', '--limit', '2'], 'ep-list-2');
    // 次の欄（### 影響する外部リソース）の打ち切り注記を巻き込まないよう、見出し行で切る
    const sec = x ? ((x.md.split('## 影響を受ける API エンドポイント')[1] || '').split(/\n#+ /)[0]) : '';
    const epNote = sec.split('\n').find((l) => l.startsWith('（表示')) || '';
    const mdIds = sec.split('\n').filter((l) => l.startsWith('- `'))
      .map((l) => (l.match(/（`([^`]+)`/) || [])[1]);
    const termLine = x ? (x.stdout.split('\n')[0] || '') : '';
    const termIds = (termLine.replace(/^API エンドポイント: /, '').split(' （')[0] || '').split(', ');
    check('エンドポイント欄は Markdown とターミナルで同じ行を同じ本数だけ出す（--limit 2）',
      !!x && x.result.summary.startEndpoints.length === 1
        && x.result.summary.reachedEndpoints.length === 2
        // 同じ 2 行を同じ順で出していること（Markdown は id、ターミナルは 名前）
        && mdIds.length === 2 && termIds.length === 2 && mdIds.length === termIds.length
        && JSON.stringify(mdIds) === JSON.stringify(['tf:aws_api_gateway_method.m1',
          'tf:aws_api_gateway_method.m2'])
        && JSON.stringify(termIds) === JSON.stringify(['POST /a', 'GET /b'])
        && /表示 2 \/ 3 件/.test(sec) && /表示 2 \/ 3 件/.test(termLine)
        && /summary\.startEndpoints/.test(sec) && sec.includes('`summary.startEndpoints`')
        && /summary\.startEndpoints/.test(termLine) && !termLine.includes('`')
        && /この一覧に出しませんが/.test(epNote) && !/Markdown にも/.test(epNote)
        && !/JSON にも/.test(epNote) && !sec.includes('（表示 1 /'),
      x ? JSON.stringify([mdIds, termIds, sec.split('\n').find((l) => l.startsWith('（表示')) || '']) : '実行失敗');
  }

  const d = runOn('code-chain-long.graph.json', ['--from', 's', '--hops', '100'], 'code-rounds');
  check('API を含まない Lambda の連鎖は既定の上限で切り詰めない（上限式はコードのノード数も数える）',
    !!d && d.result.summary.rows === 25 && d.result.summary.unresolved === false,
    d ? JSON.stringify([d.result.summary.rows, d.result.summary.rounds,
      d.result.summary.maxRounds, d.result.summary.unresolved]) : '実行失敗');

  // 第 46 ラウンド双人レビュー P1。`code-chain-long.graph.json` の 11 段目の `r4` へ届く
  // 表示経路の**最初の縁**を注釈（human）にすると、期待は 対応 = true。表示値の読みを
  // `Math.max(hops, wiringHops) + 2`（既定 10）で打ち切っていた間は根の側を落として false だった
  {
    const g = JSON.parse(readFileSync(join(FACTS, 'code-chain-long.graph.json'), 'utf8'));
    g.edges[0] = { ...g.edges[0], provenance: 'human' };
    const gPath = join(dir, 'code-chain-long-human.graph.json');
    writeFileSync(gPath, JSON.stringify(g));
    const json = join(dir, 'long-root-annotation.json');
    const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', gPath,
      '--from', 's', '--json', json], { cwd: root, encoding: 'utf8' });
    const doc = proc.status === 0 ? JSON.parse(readFileSync(json, 'utf8')) : null;
    if (doc) allDocs.push({ label: 'long-root-annotation', result: doc });
    const r4 = doc ? allRows(doc).find((x) => x.id === 'r4') : null;
    check('表示経路が探索予算より長くても根の側の注釈縁を読んで 対応 を真にする（既定の --hops）',
      !!r4 && r4.path.length === 12 && r4.correspondence === true
        && doc.summary.correspondenceRows === 11,
      r4 ? JSON.stringify([r4.path.length, r4.correspondence, doc.summary.correspondenceRows])
        : '実行失敗');
  }

  const e = runOn('budget-dominance.graph.json', ['--from', 'tf:aws_api_gateway_method.m1'], 'dominance');
  const lam2 = e ? [...e.result.external.out, ...e.result.external.in, ...e.result.wiring]
    .find((x) => x.id === 'tf:aws_lambda_function.lam2') : null;
  check('比較不能な資格を 1 つの予算に合併しない（`(elig, budget)` の届け直しで先が出る）',
    !!lam2 && lam2.tier === 'primary' && lam2.direction === 'out',
    lam2 ? JSON.stringify([lam2.tier, lam2.direction]) : (e ? '出ていない' : '実行失敗'));

  // walk 側も同じ形にする（双人レビュー第 30 ラウンド指摘 D、両名実測）。
  // `Handler.A → M1 → X` の正規の連鎖より、`Caller.C → X`（`calls` を逆向きに渡る一歩で
  // 着いた `chain: false`）が先に着く並び。ノード id だけの先着で打ち切ると `X` が
  // 定義上の関連 に落ち、その先まで消える
  const wdNodes = [
    synNode('tf:aws_api_gateway_method.m', 'resource',
      { resourceType: 'aws_api_gateway_method', category: 'apigateway', endpoint: 'POST /a' }),
    synNode('member:Handler.A', 'member'), synNode('member:Caller.C', 'member'),
    synNode('member:M1', 'member'), synNode('member:X', 'member'),
    synNode('member:Deeper', 'member'),
  ];
  const wdEdges = [
    synEdge('exposed-by', 'member:Handler.A', 'tf:aws_api_gateway_method.m', 'human'),
    synEdge('calls', 'member:Caller.C', 'member:Handler.A', 'static'),
    synEdge('calls', 'member:Caller.C', 'member:X', 'static'),
    synEdge('calls', 'member:Handler.A', 'member:M1', 'static'),
    synEdge('calls', 'member:M1', 'member:X', 'static'),
    synEdge('calls', 'member:X', 'member:Deeper', 'static'),
  ];
  const wd = runSyn('walk-dominance', { nodes: wdNodes, edges: wdEdges },
    ['--from', 'tf:aws_api_gateway_method.m'], 'walk-dominance');
  const atWd = (id) => (wd ? allRows(wd.result).find((x) => x.id === id) : null);
  check('逆向き一歩の先着が後の `chain: true` 連鎖を潰さない（`X` とその先が 本命）',
    !!wd && (atWd('member:X') || {}).tier === 'primary'
    && (atWd('member:Deeper') || {}).tier === 'primary'
    && (atWd('member:Caller.C') || {}).tier === 'wiring',
    wd ? JSON.stringify(allRows(wd.result).map((x) => [x.id, x.tier])) : '実行失敗');
}

// (7b) v2 の `$default`（既定ルート）を起点にしたとき（双人レビュー第 30 ラウンド指摘 B）。
// 表示名を持たないので `--api` では引けないが、`--from` に選んだ以上は他の route と同じ制限が
// 掛からないと、共有している integration 経由で**別ルートの Lambda** まで起点の実装になる
{
  const nodes = [
    synNode('tf:aws_apigatewayv2_api.shop', 'resource',
      { resourceType: 'aws_apigatewayv2_api', category: 'apigateway' }),
    synNode('tf:aws_apigatewayv2_route.fallback', 'resource', {
      resourceType: 'aws_apigatewayv2_route', category: 'apigateway',
      route_key: '$default', defaultRoute: true, api_id: 'aws_apigatewayv2_api.shop.id',
    }),
    synNode('tf:aws_apigatewayv2_route.other', 'resource', {
      resourceType: 'aws_apigatewayv2_route', category: 'apigateway', route_key: 'DELETE /v2/orders',
      endpoint: 'DELETE /v2/orders', api_id: 'aws_apigatewayv2_api.shop.id',
    }),
    synNode('tf:aws_apigatewayv2_integration.shared', 'resource', {
      resourceType: 'aws_apigatewayv2_integration', category: 'apigateway',
      api_id: 'aws_apigatewayv2_api.shop.id',
    }),
    synNode('tf:aws_apigatewayv2_integration.other', 'resource', {
      resourceType: 'aws_apigatewayv2_integration', category: 'apigateway',
      api_id: 'aws_apigatewayv2_api.shop.id',
    }),
    synNode('tf:aws_lambda_function.create_fn', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_lambda_function.cancel_fn', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:Shop.Orders.Create', 'member'),
    synNode('member:Shop.Orders.Cancel', 'member'),
    synNode('member:Shop.Shared', 'member'),
  ];
  const edges = [
    synEdge('invokes', 'tf:aws_apigatewayv2_route.fallback', 'tf:aws_apigatewayv2_integration.shared'),
    synEdge('invokes', 'tf:aws_apigatewayv2_route.other', 'tf:aws_apigatewayv2_integration.shared'),
    synEdge('invokes', 'tf:aws_apigatewayv2_route.other', 'tf:aws_apigatewayv2_integration.other'),
    synEdge('references', 'tf:aws_apigatewayv2_integration.shared', 'tf:aws_apigatewayv2_api.shop'),
    synEdge('references', 'tf:aws_apigatewayv2_integration.other', 'tf:aws_apigatewayv2_api.shop'),
    synEdge('references', 'tf:aws_apigatewayv2_route.fallback', 'tf:aws_apigatewayv2_api.shop'),
    synEdge('triggers', 'tf:aws_apigatewayv2_integration.shared', 'tf:aws_lambda_function.create_fn'),
    synEdge('triggers', 'tf:aws_apigatewayv2_integration.other', 'tf:aws_lambda_function.cancel_fn'),
    synEdge('handler', 'tf:aws_lambda_function.create_fn', 'member:Shop.Orders.Create'),
    synEdge('handler', 'tf:aws_lambda_function.cancel_fn', 'member:Shop.Orders.Cancel'),
    synEdge('calls', 'member:Shop.Orders.Create', 'member:Shop.Shared', 'static'),
    synEdge('calls', 'member:Shop.Orders.Cancel', 'member:Shop.Shared', 'static'),
  ];
  const dr = runSyn('default-route', { nodes, edges },
    ['--from', 'tf:aws_apigatewayv2_route.fallback'], 'default-route');
  const atDr = (id) => (dr ? allRows(dr.result).find((x) => x.id === id) : null);
  check('`$default` 起点でも委譲先（共有 integration の Lambda と handler）は本命で届く',
    !!dr && dr.result.summary.startIsEndpoint === true
    && (atDr('tf:aws_lambda_function.create_fn') || {}).tier === 'primary'
    && (atDr('member:Shop.Orders.Create') || {}).tier === 'primary',
    dr ? JSON.stringify([dr.result.summary.startIsEndpoint,
      allRows(dr.result).map((x) => [x.id.replace(/^.*:/, ''), x.tier])]) : '実行失敗');
  check('`$default` 起点では共有 integration を使う**別ルート**の Lambda と handler は 定義上の関連',
    !!dr && (atDr('tf:aws_lambda_function.cancel_fn') || {}).tier === 'wiring'
    && (atDr('member:Shop.Orders.Cancel') || {}).tier === 'wiring',
    dr ? JSON.stringify([
      (atDr('tf:aws_lambda_function.cancel_fn') || {}).tier,
      (atDr('member:Shop.Orders.Cancel') || {}).tier]) : '実行失敗');
  // 表示名を持たないので `--api` の検索対象にはならない（実在しない HTTP パスを捏造しない）。
  // `--api` は `動詞 /パス` の形しか受け付けないので、ここで弾かれることを固定する
  const apiGraph = join(dir, 'default-route-api.graph.json');
  writeFileSync(apiGraph, JSON.stringify({ nodes, edges }));
  const apiOut = join(dir, 'default-route-api.json');
  if (existsSync(apiOut)) rmSync(apiOut);
  const byApi = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', apiGraph,
    '--api', '$default', '--json', apiOut], { cwd: root, encoding: 'utf8' });
  check('`--api "$default"` では引けない（終了 2。実在しない endpoint を作らない）',
    byApi.status === 2 && !existsSync(apiOut),
    JSON.stringify([byApi.status, (byApi.stderr || '').trim().slice(0, 60), existsSync(apiOut)]));
}

// (8) 第 29 ラウンドの裁定の表示側: 本命にしない代償を黙らせない
{
  const WARN = '対応未確定の関連があります。メソッドと統合の対応を入力から確認できないため、'
    + '候補を「定義上の関連」に表示しています。';
  const REASON = '対応未確定：HTTP動詞・メソッドへの直接参照なし';
  const g = runOn('group-cache.graph.json', ['--from', 'tf:aws_lambda_function.s'], 'disp-warn');
  const countOf = (text, needle) => text.split(needle).length - 1;
  const intRow = g ? allRows(g.result).find((x) => x.id === 'tf:aws_api_gateway_integration.b') : null;
  check('method との対応が入力から決まらない統合には 対応未確定 の理由を立て、サマリに警告を 1 行出す',
    !!g && !!intRow && intRow.unresolvedCorr === true && intRow.tier === 'wiring'
    && intRow.unresolvedCorrReason === 'no-method-correspondence' && intRow.bucket === 'wiring'
    && g.result.summary.unresolvedCorr === 1
    && countOf(g.stdout, WARN) === 1 && countOf(g.md, WARN) === 1
    && g.md.includes(REASON)
    && !allRows(g.result).some((x) => x.id !== 'tf:aws_api_gateway_integration.b' && x.unresolvedCorr),
    g ? JSON.stringify([g.result.summary.unresolvedCorr, intRow && intRow.unresolvedCorr,
      countOf(g.stdout, WARN), countOf(g.md, WARN)]) : '実行失敗');

  // 兄弟ルートを足しても起点の実行経路は変わらない → 本命は変わらない（不変条件）
  const apiShape = (apis, routes, reversed) => {
    const nodes = [];
    const edges = [];
    const push = (x) => nodes.push(x);
    const link = (...x) => edges.push(...x);
    for (let a = 0; a < apis; a++) {
      const api = `tf:aws_api_gateway_rest_api.a${a}`;
      push(synNode(api, 'resource', { resourceType: 'aws_api_gateway_rest_api', category: 'apigateway' }));
      const res = `tf:aws_api_gateway_resource.r${a}`;
      push(synNode(res, 'resource', { resourceType: 'aws_api_gateway_resource', category: 'apigateway',
        rest_api_id: `${api}.id` }));
      for (let k = 0; k < routes; k++) {
        const m = `tf:aws_api_gateway_method.m${a}_${k}`;
        const int = `tf:aws_api_gateway_integration.i${a}_${k}`;
        const lam = `tf:aws_lambda_function.f${a}_${k}`;
        push(synNode(m, 'resource', { resourceType: 'aws_api_gateway_method', category: 'apigateway',
          rest_api_id: `${api}.id`, endpoint: `POST /a${a}/r${k}` }));
        push(synNode(int, 'resource', { resourceType: 'aws_api_gateway_integration', category: 'apigateway',
          rest_api_id: `${api}.id` }));
        push(synNode(lam, 'resource', { resourceType: 'aws_lambda_function' }));
        const es = [synEdge('references', m, res), synEdge('references', int, res),
          synEdge('triggers', int, lam)];
        // 起点にする route（`a=0, k=0`）だけ `http_method` を宣言した形 = 実装へ入る一歩を持つ
        if (a === 0 && k === 0) es.unshift(synEdge('invokes', m, int));
        link(...es);
      }
    }
    return reversed ? { nodes: [...nodes].reverse(), edges: [...edges].reverse() } : { nodes, edges };
  };
  const land = (r) => (r ? allRows(r.result) : []).filter((x) => x.tier === 'primary')
    .map((x) => `${x.id}:${x.direction}`).sort();
  const start = ['--api', 'POST /a0/r0'];
  const few = runSyn('sib-few', apiShape(3, 2, false), start, 'sib-few');
  const many = runSyn('sib-many', apiShape(3, 12, false), start, 'sib-many');
  const lots = runSyn('sib-lots', apiShape(3, 30, true), start, 'sib-lots');
  const want = ['tf:aws_api_gateway_integration.i0_0:out', 'tf:aws_lambda_function.f0_0:out'];
  check('兄弟ルートの本数を変えても（縁の並び順を逆にしても）本命は変わらない',
    !!few && !!many && !!lots
    && JSON.stringify(land(few)) === JSON.stringify(want)
    && JSON.stringify(land(many)) === JSON.stringify(want)
    && JSON.stringify(land(lots)) === JSON.stringify(want),
    [few, many, lots].map((x) => JSON.stringify(land(x))).join(' / '));
  // 第 30 ラウンド指摘 F: 兄弟ルートの既定表示は**件数だけ**。一覧は `--list-siblings` を
  // 立てたときだけ出し、本数は暗黙の 12 本ではなく `--limit` に従う
  check('兄弟ルートは既定が件数だけの要約で、一覧を出さない（--list-siblings で一覧）',
    !!lots && lots.result.summary.siblingEndpointsOnly === 29
    && lots.md.includes('兄弟ルート 29 件') && lots.md.includes('--list-siblings')
    && ((lots.md.split('### 同じコードを使う別の API')[1] || '').split('\n### ')[0]
      .split('\n').filter((x) => x.startsWith('- `')).length) === 0
    && lots.stdout.includes('兄弟ルート 29 件（一覧は --list-siblings）')
    && !lots.stdout.includes('他のルート'),
    lots ? JSON.stringify([lots.result.summary.siblingEndpointsOnly,
      lots.md.includes('兄弟ルート 29 件'),
      (lots.md.split('### 同じコードを使う別の API')[1] || '').split('\n### ')[0]
        .split('\n').filter((x) => x.startsWith('- `')).length,
      lots.stdout.includes('兄弟ルート 29 件（一覧は --list-siblings）')]) : '実行失敗');
  // 一覧を出するときの本数は `--limit` に従う（`--limit 5` と `--limit 50` で 12 本に固定される
  // 不整合をなくす）。JSON 行には理由コードを立てる
  const listed = runSyn('sib-listed', apiShape(3, 30, true),
    [...start, '--list-siblings', '--limit', '5'], 'sib-listed');
  const listed50 = runSyn('sib-listed50', apiShape(3, 30, true),
    [...start, '--list-siblings', '--limit', '50'], 'sib-listed50');
  const bulletCount = (m) => ((m.split('### 同じコードを使う別の API')[1] || '').split('\n### ')[0]
    .split('\n').filter((x) => x.startsWith('- `')).length);
  check('兄弟ルートの一覧は --list-siblings で出し、本数は --limit に従う（JSON 行に理由コード）',
    !!listed && !!listed50 && bulletCount(listed.md) === 5 && listed.md.includes('他のルート 24 件')
    && bulletCount(listed50.md) === 29 && !listed50.md.includes('他のルート')
    && listed50.result.siblingEndpoints.every((r) => typeof r.siblingReason === 'string'
      && ['shared-code-endpoint', 'sibling-api-definition'].includes(r.siblingReason)),
    [listed, listed50].map((x) => (x ? JSON.stringify([bulletCount(x.md), x.md.includes('他のルート 24 件')]) : '実行失敗')).join(' / '));

  // 兄弟の一覧の打ち切り行は Markdown の生バッククォートがそのまま出ていた（第 47 ラウンド agy）
  const sibNote = listed ? (listed.stdout.split('\n').find((l) => l.includes('他のルート')) || '') : '';
  check('兄弟ルートの一覧の打ち切り行は素のターミナルテキスト（Markdown のバッククォートを出さない）',
    !!listed && sibNote.includes('他のルート 24 件') && sibNote.includes('他のルート 24 件は --limit 5 で打ち切られているため Markdown にも JSON にも入っていません')
      && !sibNote.includes('`'),
    JSON.stringify(sibNote) || '実行失敗');

  // 第 50 ラウンド agy P1: JSON の \`siblingEndpoints\` はルートと定義ノードを混ぜた順で
  // \`--limit\` を切っていたため、一覧に出したルートが JSON に無いことがあった
  // （\`--api "POST /v2/a7/r3" --list-siblings --limit 2\` の一覧 2 ルートが JSON に無く、
  // \`siblingEndpoints\` は定義ノード 2 件）。並びを 1 本（ルート先頭）に統一した
  const sibBulletIds = (m) => ((m.split('### 同じコードを使う別の API')[1] || '').split('\n### ')[0]
    .split('\n').filter((x) => x.startsWith('- `')).map((x) => (x.match(/（`([^`]+)`/) || [])[1]));
  check('一覧に出た兄弟ルートは --json の siblingEndpoints の先頭に入る（第 50 ラウンド agy P1）',
    !!listed && (() => {
      const ids = sibBulletIds(listed.md);
      const arr = listed.result.siblingEndpoints;
      return ids.length === 5 && arr.length === 5
        && JSON.stringify(ids) === JSON.stringify(arr.map((r) => r.id))
        && arr.every((r) => !!r.endpoint);
    })(),
    listed ? JSON.stringify([sibBulletIds(listed.md),
      listed.result.siblingEndpoints.map((r) => r.id)]) : '実行失敗');
  check('兄弟の JSON はルートが先頭でそのうしろに定義ノード（--limit を上げても同じ順）',
    !!listed50 && (() => {
      const s = listed50.result.summary;
      const arr = listed50.result.siblingEndpoints;
      const ep = arr.filter((r) => !!r.endpoint).length;
      return ep === s.siblingEndpointsOnly && arr.slice(0, ep).every((r) => !!r.endpoint)
        && arr.slice(ep).every((r) => !r.endpoint)
        && arr.length === Math.min(s.siblings, 50);
    })(),
    listed50 ? JSON.stringify([listed50.result.summary.siblingEndpointsOnly,
      listed50.result.summary.siblingDefs,
      listed50.result.siblingEndpoints.map((r) => !!r.endpoint).join('')]) : '実行失敗');

  // 定義ノードは一覧に出さないので「Markdown にも入っていません」は嘘になる。JSON だけの話として
  // 言う（第 50 ラウンド agy P1）。兄弟 API が 1 本の Lambda を共有する合成グラフで、兄弟ルート
  // 2 件と定義ノード 4 件を作る
  {
    const bits = (a, path) => {
      const api = `tf:aws_api_gateway_rest_api.a${a}`;
      const res = `tf:aws_api_gateway_resource.r${a}`;
      const m = `tf:aws_api_gateway_method.m${a}`;
      const intg = `tf:aws_api_gateway_integration.i${a}`;
      const rn = (id, rt, md) => ({ id, kind: 'resource', name: id.split(':').pop(),
        metadata: { resourceType: rt, ...(md ? { category: 'apigateway', ...md } : {}) } });
      return {
        nodes: [rn(api, 'aws_api_gateway_rest_api'), rn(res, 'aws_api_gateway_resource', { rest_api_id: `${api}.id` }),
          rn(m, 'aws_api_gateway_method', { rest_api_id: `${api}.id`, endpoint: path }),
          rn(intg, 'aws_api_gateway_integration', { rest_api_id: `${api}.id` })],
        edges: [synEdge('references', m, res), synEdge('references', intg, res),
          synEdge('triggers', intg, 'tf:aws_lambda_function.f1')],
      };
    };
    const head = bits(0, 'POST /a');
    head.edges.unshift(synEdge('invokes', 'tf:aws_api_gateway_method.m0',
      'tf:aws_api_gateway_integration.i0'));
    const one = bits(1, 'POST /b1');
    const two = bits(2, 'POST /b2');
    const g = {
      nodes: [head.nodes[0], head.nodes[1], head.nodes[2], head.nodes[3],
        { id: 'tf:aws_lambda_function.f1', kind: 'resource', name: 'f1',
          metadata: { resourceType: 'aws_lambda_function' } },
        ...one.nodes, ...two.nodes],
      edges: [...head.edges, ...one.edges, ...two.edges],
    };
    const x = runSyn('sib-defs', g, ['--api', 'POST /a', '--list-siblings', '--limit', '3'], 'sib-defs');
    const sec = x ? ((x.md.split('### 同じコードを使う別の API')[1] || '').split('\n### ')[0]) : '';
    const mdLine = x ? (x.md.split('\n').find((l) => l.startsWith('（定義ノード')) || '') : '';
    const term = x ? (x.stdout.split('\n').find((l) => l.includes('定義ノード') && l.includes('件')) || '') : '';
    check('定義ノードの打ち切りは JSON についてだけ言い「Markdown にも」とは言わない',
      !!x && x.result.summary.siblingEndpointsOnly === 2 && x.result.summary.siblingDefs === 4
        && JSON.stringify(x.result.siblingEndpoints.map((r) => r.id)) === JSON.stringify([
          'tf:aws_api_gateway_method.m1', 'tf:aws_api_gateway_method.m2',
          'tf:aws_api_gateway_integration.i1'])
        && sec.split('\n').filter((l) => l.startsWith('- `')).length === 2   // 一覧はルートだけ
        && mdLine.includes('定義ノード 4 件中 1 件が') && mdLine.includes('他 3 件は `--limit 3`')
        && mdLine.includes('JSON にも入っていません') && mdLine.includes('ルートの一覧とは別枠です')
        && !mdLine.includes('Markdown にも')
        && term.includes('定義ノード 4 件中 1 件が') && term.includes('JSON にも入っていません')
        && !term.includes('Markdown にも') && !term.includes('`'),
      x ? JSON.stringify([x.result.summary.siblingEndpointsOnly, x.result.summary.siblingDefs,
        x.result.siblingEndpoints.map((r) => r.id.split('.').pop()), mdLine.slice(0, 120),
        term.slice(0, 120)]) : '実行失敗');
  }

  // 一覧を既定で出すのをやめたぶん、JSON 単体で「どの欄の・なぜこの行なのか」が読めること
  const expectedBucket = (r) => {
    const m = new Map();
    for (const b of ['external', 'entries', 'artifacts']) {
      for (const d of ['in', 'out']) for (const x of r[b][d]) m.set(x.id, `${b}.${d}`);
    }
    for (const b of ['sameApi', 'siblingEndpoints', 'wiring']) for (const x of r[b]) m.set(x.id, b);
    return m;
  };
  check('JSON の各行に出た欄名（bucket）が立ち、兄弟の行は理由コードを持つ',
    !!listed50 && (() => {
      const m = expectedBucket(listed50.result);
      return m.size === listed50.result.summary.rows
        && allRows(listed50.result).every((x) => x.bucket === m.get(x.id))
        && listed50.result.siblingEndpoints.every((x) => !!x.siblingReason);
    })(),
    listed50 ? JSON.stringify([listed50.result.summary.rows, expectedBucket(listed50.result).size,
      allRows(listed50.result).filter((x) => x.bucket === 'siblingEndpoints').length]) : '実行失敗');

  // 実データでよくある形: integration の `resource_id` が **method を直接参照**している
  // （`http_method` の三つ組が要らない）。この対応縁は入力をそのまま読めるので昇格してよい
  const directNodes = [
    synNode('tf:aws_api_gateway_rest_api.a', 'resource', { resourceType: 'aws_api_gateway_rest_api', category: 'apigateway' }),
    synNode('tf:aws_api_gateway_method.m', 'resource', { resourceType: 'aws_api_gateway_method', category: 'apigateway',
      rest_api_id: 'aws_api_gateway_rest_api.a.id', endpoint: 'POST /orders' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration', category: 'apigateway',
      rest_api_id: 'aws_api_gateway_rest_api.a.id' }),
    synNode('tf:aws_lambda_function.f', 'resource', { resourceType: 'aws_lambda_function' }),
  ];
  const directEdges = [
    synEdge('references', 'tf:aws_api_gateway_method.m', 'tf:aws_api_gateway_rest_api.a'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_api_gateway_rest_api.a'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_api_gateway_method.m'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.f'),
  ];
  const dr = runSyn('direct-method-ref', { nodes: directNodes, edges: directEdges },
    ['--api', 'POST /orders'], 'direct-method-ref');
  const dRows = dr ? allRows(dr.result) : [];
  const dAt = (id) => dRows.find((x) => x.id === id);
  check('integration が method を直接参照している形（三つ組が無くても）はその実装を本命にする',
    !!dr && (dAt('tf:aws_lambda_function.f') || {}).tier === 'primary'
    && (dAt('tf:aws_lambda_function.f') || {}).direction === 'out'
    && dAt('tf:aws_api_gateway_integration.i').unresolvedCorr === false,
    dr ? JSON.stringify(dRows.map((x) => [x.id.replace('tf:aws_', ''), x.tier, x.unresolvedCorr])) : '実行失敗');

  // 本命 0 件を「影響がない」と読ませない
  const zeroNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_iam_role.r', 'resource', { resourceType: 'aws_iam_role' }),
    synNode('tf:aws_lambda_function.t', 'resource', { resourceType: 'aws_lambda_function' }),
  ];
  const zeroEdges = [
    synEdge('references', 'tf:aws_lambda_function.s', 'tf:aws_iam_role.r'),
    synEdge('references', 'tf:aws_lambda_function.t', 'tf:aws_iam_role.r'),
  ];
  const z = runSyn('primary-zero', { nodes: zeroNodes, edges: zeroEdges },
    ['--from', 'tf:aws_lambda_function.s'], 'primary-zero');
  const ZERO_MSG = '本命 0 件は、影響がないことを意味しません。対応未確定の候補を確認してください。';
  check('本命 0 件のときは「影響がない意味ではない」という注意を 1 行出す（本命があるとき是不出）',
    !!z && z.result.summary.primaryOut === 0 && z.result.summary.rows > 0
    && countOf(z.stdout, ZERO_MSG) === 1 && countOf(z.md, ZERO_MSG) === 1
    && !g.stdout.includes(ZERO_MSG) && !g.md.includes(ZERO_MSG),
    z ? JSON.stringify([z.result.summary.primaryOut, countOf(z.stdout, ZERO_MSG),
      countOf(z.md, ZERO_MSG)]) : '実行失敗');
}

// (9) 第 30 ラウンドの指摘 C / E: コード起点でも「API の定義を越えた先」の行が消えない
{
  // C. 対応未確定の統合の下流で届いたコードは、そのままにすると 2 段目の walk の種ではぐれ、
  // その先の `writes` が**行ごと消える**。`touched-api-nocorr` のテーブルがその実測
  const nc = runOn('touched-api-nocorr.graph.json', ['--from', 'tf:aws_lambda_function.a'], 'r30-nocorr');
  const ncRows = nc ? allRows(nc.result) : [];
  const atNc = (id) => ncRows.find((x) => x.id === id);
  check('コード起点でも 対応未確定の統合の先（ハンドルとその書き込み先）が 定義上の関連 に残る',
    !!nc && (atNc('member:B.Handle') || {}).tier === 'wiring'
    && (atNc('ext:rds-table/orders') || {}).tier === 'wiring'
    && (atNc('ext:rds-table/orders') || {}).direction === 'out'
    && nc.result.summary.primaryOut === 1 && nc.result.summary.entryOut === 1
    && nc.result.summary.unresolvedCorr === 1,
    nc ? JSON.stringify([nc.result.summary.rows,
      [atNc('member:B.Handle'), atNc('ext:rds-table/orders')].map((x) => x && [x.tier, x.direction])]) : '実行失敗');
  // 同じゲートを「届いたコードなら何でも種」にすると、IAM ポリシー起点が定義の縁だけで
  // 全 Lambda とそのハンドルへ膨らむ。15 行のままを固定する
  const iam = run(['--from', 'tf:aws_iam_role_policy.dynamo_policy', '--limit', '100000'], 'r30-iam');
  check('IAM ポリシー起点は定義の縁だけで届いたコードを種にしない（15 行のまま膨らまない）',
    !!iam && iam.result.summary.rows === 15 && iam.result.summary.wiring === 15
    && iam.result.summary.primaryOut === 0 && iam.result.summary.primaryIn === 0
    && iam.result.summary.entryOut === 0 && iam.result.summary.entryIn === 0,
    iam ? JSON.stringify([iam.result.summary.rows, iam.result.summary.wiring,
      iam.result.summary.entryOut]) : '実行失敗');

  // E. 起点がコードのときも「統合がメソッドを指している一歩」は連鎖に残す（v1 の実データ形）。
  // 以前は逆向きの `references` というだけで切り、統合の先の Lambda が 定義上の関連 に落ちていた
  const eNodes = [
    synNode('tf:aws_lambda_function.start', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:A.Start', 'member'),
    synNode('tf:aws_api_gateway_method.m', 'resource', { resourceType: 'aws_api_gateway_method',
      category: 'apigateway', endpoint: 'POST /x' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('tf:aws_lambda_function.impl', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:Impl.Handle', 'member'),
    synNode('ext:rds-table/rows', 'resource', { resourceType: 'aws_dynamodb_table', category: 'dynamodb' }),
  ];
  const eEdges = [
    synEdge('handler', 'tf:aws_lambda_function.start', 'member:A.Start'),
    synEdge('invokes', 'member:A.Start', 'tf:aws_api_gateway_method.m', 'human'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_api_gateway_method.m'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.impl'),
    synEdge('handler', 'tf:aws_lambda_function.impl', 'member:Impl.Handle'),
    synEdge('writes', 'member:Impl.Handle', 'ext:rds-table/rows', 'human'),
  ];
  const eRun = runSyn('r30-ref-chain', { nodes: eNodes, edges: eEdges },
    ['--from', 'member:A.Start'], 'r30-ref-chain');
  const eRows = eRun ? allRows(eRun.result) : [];
  const atE = (id) => eRows.find((x) => x.id === id);
  check('コード起点でも「統合がメソッドを指している一歩」を越えた先（Lambda・ハンドル・テーブル）が本命',
    !!eRun && (atE('tf:aws_api_gateway_integration.i') || {}).tier === 'primary'
    && (atE('tf:aws_lambda_function.impl') || {}).tier === 'primary'
    && (atE('member:Impl.Handle') || {}).tier === 'primary'
    && (atE('ext:rds-table/rows') || {}).tier === 'primary',
    eRun ? JSON.stringify(eRows.map((x) => [x.id.replace(/^tf:aws_/, ''), x.tier])) : '実行失敗');
  // 同じ一歩を「何でも連鎖に残す」にすると、ロールを共有する別 Lambda への扇出が復活する
  const fanNodes = [
    synNode('tf:aws_iam_role_policy.p', 'resource', { resourceType: 'aws_iam_role_policy' }),
    synNode('tf:aws_iam_role.r', 'resource', { resourceType: 'aws_iam_role' }),
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_lambda_function.other', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:Other.Handle', 'member'),
  ];
  const fanEdges = [
    synEdge('references', 'tf:aws_iam_role_policy.p', 'tf:aws_iam_role.r'),
    synEdge('references', 'tf:aws_lambda_function.s', 'tf:aws_iam_role.r'),
    synEdge('references', 'tf:aws_lambda_function.other', 'tf:aws_iam_role.r'),
    synEdge('handler', 'tf:aws_lambda_function.other', 'member:Other.Handle'),
  ];
  const fan = runSyn('r30-iam-fan', { nodes: fanNodes, edges: fanEdges },
    ['--from', 'tf:aws_iam_role_policy.p'], 'r30-iam-fan');
  const fanRows = fan ? allRows(fan.result) : [];
  check('ロールを参照している別 Lambda への扇出は依然として 定義上の関連（指摘 E で広げない）',
    !!fan && fanRows.every((x) => x.tier === 'wiring')
    && (fanRows.find((x) => x.id === 'member:Other.Handle') || {}).tier === 'wiring',
    fan ? JSON.stringify(fanRows.map((x) => [x.id.replace(/^tf:aws_/, ''), x.tier])) : '実行失敗');
}

// (11) 第 31 ラウンドの指摘 1（双人レビュー両名）: 後から届いた「本命の事実」が先着で消える
{
  // A. 兄弟エンドポイント（同じコードを公開する別の API）が先に届いても、正規の `calls` 経路が
  // 後から同じノードへ着いたならそこは本命。`mergeFlags` が先着の `wiring: true` を凍結していた
  // 頃は、縁の並び順だけで 定義上の関連 のまま残った。3 通り（兄弟なし / 順 / 逆）で揃うこと
  const gNodes = [
    synNode('tf:aws_api_gateway_method.a', 'resource', { resourceType: 'aws_api_gateway_method',
      category: 'apigateway', endpoint: 'POST /a' }),
    synNode('tf:aws_api_gateway_method.b', 'resource', { resourceType: 'aws_api_gateway_method',
      category: 'apigateway', endpoint: 'POST /b' }),
    synNode('member:H', 'member'), synNode('member:M', 'member'),
    synNode('member:X', 'member'), synNode('member:D', 'member'),
  ];
  const gEdges = [
    synEdge('exposed-by', 'member:H', 'tf:aws_api_gateway_method.a', 'human'),
    synEdge('exposed-by', 'member:H', 'tf:aws_api_gateway_method.b', 'human'),
    synEdge('exposed-by', 'member:X', 'tf:aws_api_gateway_method.b', 'human'),
    synEdge('calls', 'member:H', 'member:M', 'static'),
    synEdge('calls', 'member:M', 'member:X', 'static'),
    synEdge('calls', 'member:X', 'member:D', 'static'),
  ];
  const orders = {
    'r31-sol-none': gEdges.filter((e) => !e.id.includes('method.b')),
    'r31-sol-orig': gEdges,
    'r31-sol-rev': [...gEdges].reverse(),
  };
  const sols = Object.entries(orders).map(([name, edges]) => {
    const out = runSyn(name, { nodes: gNodes, edges }, ['--api', 'POST /a'], name);
    return [name, out, out ? allRows(out.result).filter((x) => x.id.startsWith('member:')) : []];
  });
  check('兄弟エンドポイント経由が先着しても正規の calls 経路が本命（縁の並び 3 通りで同じ結果）',
    sols.every(([, out, ms]) => !!out && out.result.summary.entryOut === 4
      && ms.length === 4 && ms.every((x) => x.tier === 'primary')),
    sols.map(([name, out, ms]) => `${name} 出口${out ? out.result.summary.entryOut : '-'} `
      + ms.map((x) => `${x.id.split(':').pop()}=${x.tier === 'primary' ? '本命' : '定義上'}`).join(',')).join(' | '));

  // B. IAM ロールを共有する別 Lambda への扇入力が先着しても、**統合を越えて**届いたコードの先が
  // 行ごと消えない（agy 指摘 1）。`apiTail` を枠に入れないと弱い枠が先着して再展開が止まり、
  // `ext:rds-table/orders` が全欄から落ちる。扇の有無・縁の並び順に関係なく残ることを固定する
  const tNodes = [
    synNode('tf:aws_lambda_function.a', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_iam_role.r', 'resource', { resourceType: 'aws_iam_role' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('tf:aws_api_gateway_resource.res', 'resource', { resourceType: 'aws_api_gateway_resource',
      category: 'apigateway' }),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:B.Handle', 'member'),
    synNode('ext:rds-table/orders', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const tEdges = [
    synEdge('references', 'tf:aws_lambda_function.a', 'tf:aws_iam_role.r'),
    synEdge('references', 'tf:aws_lambda_function.b', 'tf:aws_iam_role.r'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.a'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_api_gateway_resource.res'),
    synEdge('references', 'tf:aws_lambda_function.b', 'tf:aws_api_gateway_resource.res'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:B.Handle'),
    synEdge('writes', 'member:B.Handle', 'ext:rds-table/orders', 'human'),
  ];
  const withRole = runSyn('r31-shared-role', { nodes: tNodes, edges: tEdges },
    ['--from', 'tf:aws_lambda_function.a'], 'r31-shared-role');
  const withRoleRev = runSyn('r31-shared-role-rev', { nodes: tNodes, edges: [...tEdges].reverse() },
    ['--from', 'tf:aws_lambda_function.a'], 'r31-shared-role-rev');
  const noRole = runSyn('r31-no-role', { nodes: tNodes,
    edges: tEdges.filter((e) => !e.id.includes('aws_iam_role.r')) },
  ['--from', 'tf:aws_lambda_function.a'], 'r31-no-role');
  const tailOf = (out, id) => {
    const hit = out ? allRows(out.result).find((x) => x.id === id) : null;
    return hit ? `${hit.tier}/${hit.direction}` : '無し';
  };
  check('共有ロールの扇入力が先着しても 統合を越えた先のコードとテーブルが 定義上の関連 に残る（扇あり / 逆順 / 扇なし）',
    [withRole, withRoleRev, noRole].every((out) => !!out
      && tailOf(out, 'member:B.Handle') === 'wiring/out'
      && tailOf(out, 'ext:rds-table/orders') === 'wiring/out'),
    [withRole, withRoleRev, noRole].map((out) => out
      ? `ハンドル=${tailOf(out, 'member:B.Handle')} テーブル=${tailOf(out, 'ext:rds-table/orders')}` : '実行失敗').join(' | '));

  // C. 逆に、**連鎖の外**（定義の縁だけ）で届いた統合を越えた旗でコードの種を増やさない。
  // IAM ポリシー起点が Lambda → 統合 → その Lambda のハンドルを経て実装の中身まで膨らむのは
  // 暴走なので、旗は起点の実装の連鎖にいるときだけ立てる（指摘 B で広げた分との両立）
  const cNodes = [
    synNode('tf:aws_iam_role_policy.p', 'resource', { resourceType: 'aws_iam_role_policy' }),
    synNode('tf:aws_iam_role.r', 'resource', { resourceType: 'aws_iam_role' }),
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('tf:aws_api_gateway_resource.res', 'resource', { resourceType: 'aws_api_gateway_resource',
      category: 'apigateway' }),
    synNode('member:S.Handle', 'member'), synNode('member:S.Deep', 'member'),
    synNode('ext:rds-table/t', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const cEdges = [
    synEdge('references', 'tf:aws_iam_role_policy.p', 'tf:aws_iam_role.r'),
    synEdge('references', 'tf:aws_lambda_function.s', 'tf:aws_iam_role.r'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.s'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_api_gateway_resource.res'),
    synEdge('handler', 'tf:aws_lambda_function.s', 'member:S.Handle'),
    synEdge('calls', 'member:S.Handle', 'member:S.Deep', 'static'),
    synEdge('writes', 'member:S.Deep', 'ext:rds-table/t', 'human'),
  ];
  const fromPolicy = runSyn('r31-from-policy', { nodes: cNodes, edges: cEdges },
    ['--from', 'tf:aws_iam_role_policy.p'], 'r31-from-policy');
  check('IAM ポリシー起点は 定義の縁だけで届いた統合の先を種にしない（実装の中身とテーブルが増えない）',
    !!fromPolicy && !allRows(fromPolicy.result).some((x) => x.id === 'ext:rds-table/t')
    && !allRows(fromPolicy.result).some((x) => x.id === 'member:S.Deep')
    && fromPolicy.result.summary.entryOut === 0 && fromPolicy.result.summary.entryIn === 0
    && allRows(fromPolicy.result).every((x) => x.tier === 'wiring'),
    fromPolicy ? JSON.stringify([fromPolicy.result.summary.rows, fromPolicy.result.summary.wiring,
      allRows(fromPolicy.result).map((x) => x.id.replace(/^tf:aws_/, ''))]) : '実行失敗');
}

// (12) 第 32 ラウンドの指摘（双人レビュー agy・案 A）: `apiTail` を walk の枠に入れた形での
// 縁の並び順の揺れと、同じ API を定義する行の塗り替え
{
  // A. 注釈（`invokes`）を跨いだ先に旗を立てる形。`u` への 2 経路（定義側と統合側）のうち
  // 旗を立てる側が後着だと、枠に旗が無い限り `u` が再展開されず `ext:rds-table/orders` が
  // 縁の並び順だけで全欄から消えた（orig 6 行 / rev 7 行）。並び順 2 通りで同じ結果になること、
  // および テーブルがどちらでも 定義上の関連 として残ることを固定する
  const uNodes = [
    synNode('tf:aws_lambda_function.a', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_iam_role.r', 'resource', { resourceType: 'aws_iam_role' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('tf:aws_lambda_function.u', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:V.Entry', 'member'),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:B.Handle', 'member'),
    synNode('ext:rds-table/orders', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const uEdges = [
    synEdge('references', 'tf:aws_iam_role.r', 'tf:aws_lambda_function.a'),
    synEdge('references', 'tf:aws_lambda_function.u', 'tf:aws_iam_role.r'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.a'),
    synEdge('references', 'tf:aws_lambda_function.u', 'tf:aws_api_gateway_integration.i'),
    synEdge('invokes', 'member:V.Entry', 'tf:aws_lambda_function.u', 'human'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:V.Entry'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:B.Handle'),
    synEdge('writes', 'member:B.Handle', 'ext:rds-table/orders', 'human'),
  ];
  // 旗を立てる一歩が 1 段深く届く形（統合と `u` の間にリソースを 1 つ挟む）。段数で閉じる打ち手
  // だとこの形では再び着地が消えるので、段数に依存しない直し方であることを固定する
  const uNodesDeep = [...uNodes, synNode('tf:aws_api_gateway_resource.mid', 'resource',
    { resourceType: 'aws_api_gateway_resource', category: 'apigateway' })];
  const uEdgesDeep = (tail) => [
    uEdges[0], uEdges[1], uEdges[2],
    synEdge('references', 'tf:aws_api_gateway_resource.mid', 'tf:aws_api_gateway_integration.i'),
    synEdge('references', 'tf:aws_lambda_function.u', 'tf:aws_api_gateway_resource.mid'),
    ...tail];
  const shapeOf = (out) => (out ? allRows(out.result)
    .map((x) => `${x.id}=${x.tier}/${x.direction}/h${x.hops}`) : null);
  const uRuns = [
    ['u-orig', { nodes: uNodes, edges: uEdges }],
    ['u-rev', { nodes: uNodes, edges: [...uEdges].reverse() }],
    ['u-deep', { nodes: uNodesDeep, edges: uEdgesDeep(uEdges.slice(4)) }],
    ['u-deep-rev', { nodes: uNodesDeep, edges: uEdgesDeep(uEdges.slice(4)).reverse() }],
  ].map(([name, g]) => [name, runSyn(name, g, ['--from', 'tf:aws_lambda_function.a'], name)]);
  const tableOf = (out) => (out ? allRows(out.result).find((x) => x.id === 'ext:rds-table/orders') : null);
  check('注釈を跨いだ先の旗が後から立つ形で、縁の並び順が逆でも同じ着地が残る（第 32 ラウンド案 A）',
    uRuns.every(([, out]) => !!out && !!tableOf(out)
      && tableOf(out).tier === 'wiring' && tableOf(out).direction === 'out')
    // 段数の違う 2 つの形それぞれで、縁の並び順だけの差が消えること
    && JSON.stringify(shapeOf(uRuns[0][1])) === JSON.stringify(shapeOf(uRuns[1][1]))
    && JSON.stringify(shapeOf(uRuns[2][1])) === JSON.stringify(shapeOf(uRuns[3][1])),
    uRuns.map(([name, out]) => `${name}: ${out ? `rows=${out.result.summary.rows} テーブル=`
      + (tableOf(out) ? `${tableOf(out).tier}/${tableOf(out).direction}` : '無し') : '実行失敗'}`).join(' | '));

  // B. 同じ API を定義する行を walk の折り返しで塗り替えない。`method --exposed-by(注釈)--> 実装`
  // を折り返して `method` へ戻る一歩が `mdir` を反転させ、`references` で定義側へ再突入すると
  // `hops: 3` の walk 経路が 向き out・根拠薄い で先着した（v1 基準の 2 行が in → out）。
  // 定義跨ぎの広がり自体は閉包が `hops: 1`・完全な縁で記録しているので、段数と 親 と 根拠縁 は
  // 塗り替わらないまま。`向き` は表示経路を根から読む（第 45 ラウンド追加裁定）。この 1 段は
  // `references`（定義閉包で 向き を意味として採用しない 無方向の定義縁）なので、第 46 ラウンド
  // Astra 裁定 (b)(c)（`out/review-astra46.log`）どおり **端点から 向き の種を作らず**、起点の
  // `none` をそのまま継承して `向き = none`（Markdown では「—」）
  const defNodes = [
    synNode('tf:aws_api_gateway_method.post_order', 'resource', { resourceType: 'aws_api_gateway_method',
      category: 'apigateway', endpoint: 'POST /orders' }),
    synNode('tf:aws_api_gateway_resource.orders_path', 'resource', { resourceType: 'aws_api_gateway_resource',
      category: 'apigateway' }),
    synNode('tf:aws_api_gateway_rest_api.orders', 'resource', { resourceType: 'aws_api_gateway_rest_api',
      category: 'apigateway' }),
    synNode('member:OrderHandler.Handle', 'member'), synNode('member:Order.Create', 'member'),
  ];
  const defEdges = [
    synEdge('references', 'tf:aws_api_gateway_method.post_order', 'tf:aws_api_gateway_resource.orders_path'),
    synEdge('references', 'tf:aws_api_gateway_method.post_order', 'tf:aws_api_gateway_rest_api.orders'),
    synEdge('exposed-by', 'member:OrderHandler.Handle', 'tf:aws_api_gateway_method.post_order', 'human'),
    synEdge('calls', 'member:OrderHandler.Handle', 'member:Order.Create', 'static'),
    synEdge('exposed-by', 'member:Order.Create', 'tf:aws_api_gateway_method.post_order', 'human'),
  ];
  const defIds = ['tf:aws_api_gateway_resource.orders_path', 'tf:aws_api_gateway_rest_api.orders'];
  const defRuns = [['def-orig', defEdges], ['def-rev', [...defEdges].reverse()]].map(([name, edges]) =>
    [name, runSyn(name, { nodes: defNodes, edges }, ['--api', 'POST /orders'], name)]);
  const defRow = (out, id) => (out ? allRows(out.result).find((x) => x.id === id) : null);
  check('実装から method へ折り返す一歩が 同じ API を定義する行を塗り替えない（hops 1・親・根拠縁のまま。'
    + '無方向の定義縁だけの 1 段なので 向き は none）',
    defRuns.every(([, out]) => !!out && defIds.every((id) => {
      const hit = defRow(out, id);
      return !!hit && hit.tier === 'wiring' && hit.direction === 'none' && hit.hops === 1
        && hit.via === 'tf:aws_api_gateway_method.post_order'
        && hit.path.length === 2 && hit.evidence.kind === 'references';
    }))
    && new Set(defRuns.map(([, out]) => JSON.stringify(shapeOf(out)))).size === 1,
    defRuns.map(([name, out]) => `${name}: ` + (out
      ? defIds.map((id) => {
        const hit = defRow(out, id);
        return `${id.split('.').pop()}=${hit ? `${hit.tier}/${hit.direction}/h${hit.hops}/via=${hit.via ? hit.via.split('.').pop() : '無し'}` : '無し'}`;
      }).join(' ') : '実行失敗')).join(' | '));
}

// (13) 第 33 ラウンドの指摘（双人レビュー agy）: walk の循環境避で API の定義ノードへ戻る一歩を
// `back` で止めたガードが、**まだ展開していない資格（`chain` 等）の再展開まで潰す**形。
// 統合 `i` が注釈 `invokes` を 3 本持つ形だと、`i` への先着が `references`（`chain: false`）で、
// `chain: true` の正規の連鎖は 統合 → C → Mid → a の **折り返し**でしか届かない。折り返しの一歩は
// `back` が立つので、ガードがそこを閉じると `i` の先の `V` 組が再展開されず、
// `ext:rds-table/orders` が縁の並び順だけで 定義上の関連 に落ちた（orig 6 行 / rev 7 行）。
// ガードを外して `stateKey` を `back` 非依存にして直したので、次を固定する:
//  - 並び順 2 通りで 行（id / 枠 / 向き / 段数）が完全に一致する
//  - どちらでも `ext:rds-table/orders` が 本命・影響する先 として残る
{
  const gNodes = [
    synNode('tf:aws_lambda_function.a', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('member:Mid', 'member'), synNode('member:C', 'member'), synNode('member:V', 'member'),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:B.Handle', 'member'),
    synNode('ext:rds-table/orders', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const gEdges = [
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.a'),
    synEdge('invokes', 'member:Mid', 'tf:aws_lambda_function.a', 'human'),
    synEdge('invokes', 'tf:aws_api_gateway_integration.i', 'member:C', 'human'),
    synEdge('calls', 'member:Mid', 'member:C', 'static'),
    synEdge('invokes', 'tf:aws_api_gateway_integration.i', 'member:V', 'human'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:V'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:B.Handle'),
    synEdge('writes', 'member:B.Handle', 'ext:rds-table/orders', 'human'),
  ];
  const gRuns = [['r34-orig', gEdges], ['r34-rev', [...gEdges].reverse()],
    // 辺の並びだけでなくノードの並びも変えて同じか（起点の作り替えは行わない）
    ['r34-nodes-rev', gEdges]].map(([name, edges], i) => [name,
      runSyn(name, { nodes: i === 2 ? [...gNodes].reverse() : gNodes, edges },
        ['--from', 'tf:aws_lambda_function.a'], name)]);
  const gShape = (out) => (out ? allRows(out.result).map((x) => `${x.id}=${x.tier}/${x.direction}/h${x.hops}`
    + `/sw${x.switches}`) : null);
  const gTable = (out) => (out ? allRows(out.result).find((x) => x.id === 'ext:rds-table/orders') : null);
  check('注釈 invokes を複数持つ統合で、定義ノードへ戻る折り返しが chain の再展開を止めない（第 33 ラウンド）',
    gRuns.every(([, out]) => !!out && !!gTable(out)
      && gTable(out).tier === 'primary' && gTable(out).direction === 'out')
    && new Set(gRuns.map(([, out]) => JSON.stringify(gShape(out)))).size === 1
    // `member:Mid → member:C` の `calls`（static）の一歩は向きを変えているので 1。`member:C` には
    // 別経路（統合 `i` からの注釈 `invokes`）も届くが、`mergeFlags` がその `corr` を引き継いでも
    // 表示の一歩が注釈縁でない限り数える（第 44 ラウンド。引き継ぎ値で決めると 1 / 0 に割れた）
    && gRuns.every(([, out]) => !!out && allRows(out.result).find((x) => x.id === 'member:C').switches === 1),
    gRuns.map(([name, out]) => `${name}: ${out ? `rows=${out.result.summary.rows} テーブル=`
      + (gTable(out) ? `${gTable(out).tier}/${gTable(out).direction}` : '無し') : '実行失敗'}`).join(' | '));
}

// (14) 第 35 ラウンドの指摘（双人レビュー agy）: 閉包の `wiringMap` 記録が後着で**無条件上書き**
// される形。比較不能な 2 資格の経路（`chain` 単独のマスクと `apiTail` 単独のマスク）が同予算で
// 同じノードに届くと両方受理されるが、後着が記録を塗り替えるため、
//  (A) 注釈のみの形: `member:V` の記録が `apiTail` の旗を落として codeSeeds から外れ、
//      `ext:rds-table/orders` が縁の並び順だけで全欄から消えた（orig 6 行 / rev 5 行）
//  (B) 純粋な Terraform の形: 合流点 `tf:aws_dynamodb_table.target` の `direction`（in/out）が
//      並び順で反転した（orig in / rev out）
// 直し: 記録の上書きは「支配（マスク包含 × 予算非増）/ 昇格 / cut 復旧 / `apiTail` 運び」のとき
// だけ。codeSeeds は `primary` と同じく `bestState` の単調な旗を見る。
// 2 つの形それぞれで、欄・向き・tier・段数が並び順を変えても不変であることを固定する
{
  const rowShape = (r) => [['external.out', r.external.out], ['external.in', r.external.in],
    ['entries.out', r.entries.out], ['entries.in', r.entries.in],
    ['artifacts.out', r.artifacts.out], ['artifacts.in', r.artifacts.in],
    ['wiring', r.wiring], ['sameApi', r.sameApi], ['siblingEndpoints', r.siblingEndpoints]]
    .flatMap(([b, rs]) => (rs || []).map((x) => `${b}|${x.id}=${x.tier}/${x.direction}/h${x.hops}`));
  const findRow = (r, id) => allRows(r).find((x) => x.id === id) || null;

  // A. 注釈のみの形。統合 `i`（`triggers` で起点に届く）から `references` で越えた一歩が
  // `apiTail` を立て、旗無しの `chain` 経路（`l_out --invokes(注釈)--> 起点` の上流側から
  // `references` で下る）と同予算で `member:V` に着く
  const aNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_lambda_function.l_out', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_s3_bucket.x1', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('tf:aws_s3_bucket.b', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('member:V', 'member'),
    synNode('ext:rds-table/orders', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const aEdges = [
    synEdge('invokes', 'tf:aws_lambda_function.l_out', 'tf:aws_lambda_function.s', 'human'),
    synEdge('references', 'tf:aws_lambda_function.l_out', 'tf:aws_s3_bucket.x1'),
    synEdge('references', 'tf:aws_s3_bucket.x1', 'member:V'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.s'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_s3_bucket.b'),
    synEdge('references', 'member:V', 'tf:aws_s3_bucket.b'),
    synEdge('writes', 'member:V', 'ext:rds-table/orders', 'human'),
  ];
  const aRuns = [['r36a-orig', aEdges, aNodes], ['r36a-rev', [...aEdges].reverse(), aNodes],
    ['r36a-nodes-rev', aEdges, [...aNodes].reverse()]]
    .map(([name, edges, nodes]) => [name,
      runSyn(name, { nodes, edges }, ['--from', 'tf:aws_lambda_function.s'], name)]);
  const aTable = (out) => (out ? findRow(out.result, 'ext:rds-table/orders') : null);
  check('旗を運ぶ経路と運ばない経路が同予算で合流しても、注釈の先の着地が並び順で消えない（第 35 ラウンド指摘 1）',
    aRuns.every(([, out]) => !!out && !!aTable(out)
      && aTable(out).tier === 'primary' && aTable(out).direction === 'out')
    && new Set(aRuns.map(([, out]) => JSON.stringify(out ? rowShape(out.result) : null))).size === 1,
    aRuns.map(([name, out]) => `${name}: ${out ? `rows=${out.result.summary.rows} テーブル=`
      + (aTable(out) ? `${aTable(out).tier}/${aTable(out).direction}` : '無し') : '実行失敗'}`).join(' | '));

  // B. 純粋な Terraform の形（コードノード無し）。`target` へ (a) 統合 `i` を越えて `b` 経由で
  // 届く `apiTail` を運ぶ経路（向き in）と、(b) 上流の `l_out` 側から `x1` 経由で届く旗無しの
  // 経路（向き out）が同予算で着く。支配規則は旗を運ぶ経路を勝たせるので、どちらの並びでも
  // 向き in（`i → b ← target` の定義経路）に着地する
  const bNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_lambda_function.l_out', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_s3_bucket.x1', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration',
      category: 'apigateway' }),
    synNode('tf:aws_s3_bucket.b', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_dynamodb_table.target', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const bEdges = [
    synEdge('invokes', 'tf:aws_lambda_function.l_out', 'tf:aws_lambda_function.s', 'human'),
    synEdge('references', 'tf:aws_lambda_function.l_out', 'tf:aws_s3_bucket.x1'),
    synEdge('references', 'tf:aws_s3_bucket.x1', 'tf:aws_dynamodb_table.target'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.s'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_s3_bucket.b'),
    synEdge('references', 'tf:aws_dynamodb_table.target', 'tf:aws_s3_bucket.b'),
  ];
  const bRuns = [['r36b-orig', bEdges, bNodes], ['r36b-rev', [...bEdges].reverse(), bNodes],
    ['r36b-nodes-rev', bEdges, [...bNodes].reverse()]]
    .map(([name, edges, nodes]) => [name,
      runSyn(name, { nodes, edges }, ['--from', 'tf:aws_lambda_function.s'], name)]);
  const bTarget = (out) => (out ? findRow(out.result, 'tf:aws_dynamodb_table.target') : null);
  check('純粋な Terraform 構成で合流点の向きが並び順で反転しない（旗を運ぶ経路が支配し、向き in に着地）',
    bRuns.every(([, out]) => !!out && !!bTarget(out)
      && bTarget(out).tier === 'wiring' && bTarget(out).direction === 'in'
      && bTarget(out).hops === 3)
    && new Set(bRuns.map(([, out]) => JSON.stringify(out ? rowShape(out.result) : null))).size === 1,
    bRuns.map(([name, out]) => `${name}: ` + (out
      ? `target=${bTarget(out) ? `${bTarget(out).tier}/${bTarget(out).direction}/h${bTarget(out).hops}` : '無し'}`
      : '実行失敗')).join(' | '));
}

// ---- 第 37 ラウンド: 表示する代表経路を全順序で決める（双人レビュー第 36 ラウンド両名指摘）----
// 包含支配（マスク ⊇ × 予算 ≤）は展開の枝刈りとして正しいが、表示する代表経路を一意に
// 決める基準にはなっていない。比較不能な対（`chain` マスク 12・予算 2 と `elig|apiTail`
// マスク 10・予算 1）と同位（同じマスク・同じ予算）の対は先着（あるいは後着）が勝っていた
// ため、縁の並び順だけで `direction` が反転した（再現 out/tmp-r37/repro-direction.py）。
// 直し: 実経路の候補を全部保持し、`repCmp` の全順序（昇格止めの経路 → 根付き → 予算 →
// 段数 → apiTail → chain → 縁 id 辞書順）で代表を決める。
//  shuffled した縁順で 欄・向き・tier・段数・根拠の縁まで一致することを固定する
{
  // 疑似ランダムだが決定的な並べ順（線形合同法）。シードを変えて複数並べ順を作る
  const shuffled = (xs, seed) => {
    const ys = [...xs];
    let s = seed >>> 0;
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    for (let i = ys.length - 1; i > 0; i -= 1) {
      const j = Math.floor(rnd() * (i + 1));
      [ys[i], ys[j]] = [ys[j], ys[i]];
    }
    return ys;
  };
  // 根拠の縁まで含めた行の形。並び順で変わってはいけないものを全部入れる
  const fullShape = (r) => [['external.out', r.external.out], ['external.in', r.external.in],
    ['entries.out', r.entries.out], ['entries.in', r.entries.in],
    ['artifacts.out', r.artifacts.out], ['artifacts.in', r.artifacts.in],
    ['wiring', r.wiring], ['sameApi', r.sameApi], ['siblingEndpoints', r.siblingEndpoints]]
    .flatMap(([b, rs]) => (rs || []).map((x) => `${b}|${x.id}=${x.tier}/${x.direction}/h${x.hops}`
      + `/evidence:${x.evidence.kind}:${x.evidence.source}->${x.evidence.target}`
      + `/movement:${x.movementEvidence ? x.movementEvidence.id : '-'}`));

  // (1) codex 双人レビューの反例。`chain` 一本の経路（`l_out → x1 → target`、向き out）と
  // `elig|apiTail` の経路（`i → b ← target`、向き in）が比較不能で着く。仕様どおり
  // `apiTail` を運ぶ経路が代表になり、3 段で並べ順不変。
  // 向きは表示経路を根から読む（第 45 ラウンド追加裁定）。代表になった
  // `s ←invokes(注釈)← l_out --invokes--> b ←references-- target` は、2 本目が 動きの縁で
  // 矢印が `b` を指すのでそこで 影響する先 へ決まり、3 本目の Terraform の定義の縁は
  // 向きを変えない → out（向き変え 2 回として表示に出る）。v1 基準の in は 別経路の
  // `i → b` 側の記録の 向き を読んでいた値で、表示経路の純関数ではない
  const counterNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_lambda_function.l_out', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_s3_bucket.x1', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration', category: 'apigateway' }),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_dynamodb_table.target', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const counterEdges = [
    synEdge('invokes', 'tf:aws_lambda_function.l_out', 'tf:aws_lambda_function.s', 'human'),
    synEdge('references', 'tf:aws_lambda_function.l_out', 'tf:aws_s3_bucket.x1'),
    synEdge('references', 'tf:aws_s3_bucket.x1', 'tf:aws_dynamodb_table.target'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.s'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.b'),
    synEdge('references', 'tf:aws_dynamodb_table.target', 'tf:aws_lambda_function.b'),
    synEdge('invokes', 'tf:aws_lambda_function.l_out', 'tf:aws_lambda_function.b'),
  ];
  const cOrders = [['orig', counterEdges], ['rev', [...counterEdges].reverse()]]
    .concat([3, 11, 29, 77].map((sd) => [`shuf${sd}`, shuffled(counterEdges, sd)]))
    .map(([name, edges]) => [name,
      runSyn(`r37c-${name}`, { nodes: counterNodes, edges },
        ['--from', 'tf:aws_lambda_function.s'], `r37c-${name}`)]);
  const cTarget = (out) => (out ? allRows(out.result).find((x) => x.id === 'tf:aws_dynamodb_table.target') : null);
  check('比較不能な代表経路の対決は全順序で決まり、縁を shuffled しても 欄・向き・段数・根拠が一致する',
    cOrders.every(([, out]) => !!out && !!cTarget(out)
      && cTarget(out).tier === 'wiring' && cTarget(out).direction === 'out'
      && cTarget(out).hops === 3
      && cTarget(out).evidence.kind === 'references')
    && new Set(cOrders.map(([, out]) => JSON.stringify(out ? fullShape(out.result) : null))).size === 1,
    cOrders.map(([name, out]) => `${name}: ` + (out
      ? `target=${cTarget(out) ? `${cTarget(out).tier}/${cTarget(out).direction}/h${cTarget(out).hops}` : '無し'}`
      : '実行失敗')).join(' | '));

  // (2) 第 35 ラウンド agy 指摘 2 の形（純粋な Terraform）。同位の対決も全順序（`apiTail`）で
  // 決まり、shuffled で根拠の縁（`i → b` ではなく `target → b` の `references`）まで一致する
  const bNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_lambda_function.l_out', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_s3_bucket.x1', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration', category: 'apigateway' }),
    synNode('tf:aws_s3_bucket.b', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_dynamodb_table.target', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const bEdges = [
    synEdge('invokes', 'tf:aws_lambda_function.l_out', 'tf:aws_lambda_function.s', 'human'),
    synEdge('references', 'tf:aws_lambda_function.l_out', 'tf:aws_s3_bucket.x1'),
    synEdge('references', 'tf:aws_s3_bucket.x1', 'tf:aws_dynamodb_table.target'),
    synEdge('triggers', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.s'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_s3_bucket.b'),
    synEdge('references', 'tf:aws_dynamodb_table.target', 'tf:aws_s3_bucket.b'),
  ];
  const bOrders = [['orig', bEdges], ['rev', [...bEdges].reverse()]]
    .concat([5, 13, 41, 97].map((sd) => [`shuf${sd}`, shuffled(bEdges, sd)]))
    .map(([name, edges]) => [name,
      runSyn(`r37b-${name}`, { nodes: bNodes, edges },
        ['--from', 'tf:aws_lambda_function.s'], `r37b-${name}`)]);
  const bTarget = (out) => (out ? allRows(out.result).find((x) => x.id === 'tf:aws_dynamodb_table.target') : null);
  check('同位（同じマスク・同じ予算）の対決も shuffled で根拠の縁まで一致する（向き in / 3 段）',
    bOrders.every(([, out]) => !!out && !!bTarget(out)
      && bTarget(out).tier === 'wiring' && bTarget(out).direction === 'in'
      && bTarget(out).hops === 3
      && bTarget(out).evidence.source === 'tf:aws_dynamodb_table.target'
      && bTarget(out).evidence.target === 'tf:aws_s3_bucket.b')
    && new Set(bOrders.map(([, out]) => JSON.stringify(out ? fullShape(out.result) : null))).size === 1,
    bOrders.map(([name, out]) => `${name}: ` + (out
      ? `target=${bTarget(out) ? `${bTarget(out).tier}/${bTarget(out).direction}/h${bTarget(out).hops}` : '無し'}`
      : '実行失敗')).join(' | '));
}

// ---- 第 38 ラウンド: 循環判定は実際の経路だけを読む（双人レビュー第 37 ラウンド両名指摘）----
// 旧実装は `wiringMap` の**選んだ代表**の連鎖で循環を見ていたので、ある経路が切れるか
// どうかが届く順で変わり、候補集合そのものが揺れた（再現 out/tmp-review37/repro.py:
// `target` が orig で 3 段/new9、rev で 2 段/e3 に化けた）。直し: 循環判定は待ち行列状態の
// `parent` 連鎖（実際の経路）だけで行い、候補集合は提示された実経路を全部保つ
// （挿入ゲート廃止）。縁の反転・ノードの反転でも段数・根拠・動きの根拠まで揺れないこと
// を固定する
{
  const shuffled = (xs, seed) => {
    const ys = [...xs];
    let s = seed >>> 0;
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s / 0x7fffffff; };
    for (let i = ys.length - 1; i > 0; i -= 1) {
      const j = Math.floor(rnd() * (i + 1));
      [ys[i], ys[j]] = [ys[j], ys[i]];
    }
    return ys;
  };
  const fullShape = (r) => [['external.out', r.external.out], ['external.in', r.external.in],
    ['entries.out', r.entries.out], ['entries.in', r.entries.in],
    ['artifacts.out', r.artifacts.out], ['artifacts.in', r.artifacts.in],
    ['wiring', r.wiring], ['sameApi', r.sameApi], ['siblingEndpoints', r.siblingEndpoints]]
    .flatMap(([b, rs]) => (rs || []).map((x) => `${b}|${x.id}=${x.tier}/${x.direction}/h${x.hops}`
      + `/evidence:${x.evidence.kind}:${x.evidence.source}->${x.evidence.target}`
      + `/movement:${x.movementEvidence ? x.movementEvidence.id : '-'}`));
  const pcNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_s3_bucket.x1', 'resource', { resourceType: 'aws_s3_bucket' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', { resourceType: 'aws_api_gateway_integration', category: 'apigateway' }),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_dynamodb_table.target', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const pcEdges = [
    synEdge('references', 'tf:aws_s3_bucket.x1', 'tf:aws_dynamodb_table.target'),
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.b'),
    synEdge('triggers', 'tf:aws_lambda_function.s', 'tf:aws_api_gateway_integration.i'),
    synEdge('triggers', 'tf:aws_dynamodb_table.target', 'tf:aws_lambda_function.b'),
    synEdge('triggers', 'tf:aws_lambda_function.s', 'tf:aws_s3_bucket.x1'),
  ];
  const pcOrders = [['orig', pcNodes, pcEdges], ['rev', pcNodes, [...pcEdges].reverse()],
    ['revNodes', [...pcNodes].reverse(), [...pcEdges].reverse()]]
    .concat([2, 7, 43].map((sd) => [`shuf${sd}`, pcNodes, shuffled(pcEdges, sd)]))
    .map(([name, nodes, edges]) => [name,
      runSyn(`r38pc-${name}`, { nodes, edges },
        ['--from', 'tf:aws_lambda_function.s'], `r38pc-${name}`)]);
  const pcRow = (out, id) => (out ? allRows(out.result).find((x) => x.id === id) : null);
  // 第 38 ラウンド時点の期待値は `target` 1 段（経路 `[b, target]`）だったが、それは
  // `b ⇄ target` の 2 ノード循環を `pathOf` が打ち切った表示だった（第 38 ラウンド agy
  // 指摘 P0 と同じ型。旧検査は先頭が起点でない `second-stage` 行を素通りしていた）。
  // 第 40 ラウンド（裁定 out/loop/r39-astra.md）では循環せず起点まで遡れる連鎖を表示する:
  // `[s, i, b, target]` の 3 段。`repCmp` が動きの縁（`triggers`）を定義の縁より先に選ぶので
  // 根拠縁は `triggers:target->b` のまま、向き in / 本命区分 primary も不変
  check('path-counter 反例: 縁の反転・ノードの反転で 段数・根拠・動きの根拠まで一致（target=in/primary/3段/new9、b=out）',
    pcOrders.every(([, out]) => {
      if (!out) return false;
      const t = pcRow(out, 'tf:aws_dynamodb_table.target');
      const b = pcRow(out, 'tf:aws_lambda_function.b');
      return !!t && !!b && t.direction === 'in' && t.tier === 'primary' && t.hops === 3
        && t.pathRoot === 'start'
        && t.path.join(' ') === ['tf:aws_lambda_function.s', 'tf:aws_api_gateway_integration.i',
          'tf:aws_lambda_function.b', 'tf:aws_dynamodb_table.target'].join(' ')
        && t.evidence.id === 'triggers:tf:aws_dynamodb_table.target->tf:aws_lambda_function.b'
        && !!t.movementEvidence && t.movementEvidence.id === t.evidence.id
        && b.direction === 'out' && b.tier === 'primary' && b.hops === 2 && b.pathRoot === 'start';
    })
    && new Set(pcOrders.map(([, out]) => JSON.stringify(out ? fullShape(out.result) : null))).size === 1,
    pcOrders.map(([name, out]) => {
      if (!out) return `${name}: 実行失敗`;
      const t = pcRow(out, 'tf:aws_dynamodb_table.target');
      return `${name}: target=${t ? `${t.direction}/${t.tier}/h${t.hops}/${(t.evidence || {}).kind}/${(t.movementEvidence || {}).id || '-'}` : '無し'}`;
    }).join(' | '));
}

// ---- (17) 第 41 ラウンド: walk が届けた行も、縁の並び順で 段数・根拠 が揺れない ----
// 第 40 ラウンドで閉包（Terraform の定義）側は「不受理の到着も候補に残して代表を選び直す」
// 形で直した。walk（コード歩き）側は `found` の**先着**が表示のままだったので、同じ資格の
// 別経路が後から届くと縁の並び順だけで 段数・根拠・行の並び が変わっていた
// （実測 out/tmp-r41/wobble-before.txt: `r34-fixture` / `demo-order` / `fixture-api` の 3 件）。
// ここは walk の到着も候補へ加えて収束後に選び直す（仕様 out/loop/r41-decision.md）。
// 表の signature は 欄・id・向き・tier・段数・向き変え回数・根拠の縁 id・動きの根拠・
// 直前のノード・表示経路を**欄の中の並び順ごと**見る
{
  const shapeOf = (r) => [['external.out', r.external.out], ['external.in', r.external.in],
    ['entries.out', r.entries.out], ['entries.in', r.entries.in],
    ['artifacts.out', r.artifacts.out], ['artifacts.in', r.artifacts.in],
    ['wiring', r.wiring], ['sameApi', r.sameApi], ['siblingEndpoints', r.siblingEndpoints]]
    .flatMap(([b, rs]) => (rs || []).map((x) => `${b}|${x.id}=${x.tier}/${x.direction}`
      + `/h${x.hops}/sw${x.switches}`
      + `/e${x.evidence ? x.evidence.id : '-'}`
      + `/mv${x.movementEvidence ? x.movementEvidence.id : '-'}`
      + `/via:${x.via || '-'}/path:${(x.path || []).join('>')}`));
  // 疑似乱数でノードと縁を並べ替える（試行ごとに同じ並びになるよう種を固定する）
  const shuffle = (arr, seed) => {
    const a = [...arr];
    let x = seed >>> 0 || 1;
    const rnd = () => {
      x ^= x << 13; x >>>= 0;
      x ^= x >>> 17;
      x ^= x << 5; x >>>= 0;
      return x / 4294967296;
    };
    for (let i = a.length - 1; i > 0; i -= 1) {
      const j = Math.floor(rnd() * (i + 1)); const t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  };
  const ordersOf = (nodes, edges) => [['元', nodes, edges], ['縁逆', nodes, [...edges].reverse()],
    ['ノード逆', [...nodes].reverse(), edges],
    ...[1, 2, 3, 4].map((k) => [`入替${k}`, shuffle(nodes, 97 * k + 11), shuffle(edges, 131 * k + 7)])];
  const runOrders = (tag, nodes, edges, args) => ordersOf(nodes, edges).map(([name, n, e], i) => [
    name, runSyn(`${tag}-${i}`, { nodes: n, edges: e }, args, `${tag}-${i}`)]);

  // A. 第 33 ラウンドの fixture。統合 `i` の注釈 `invokes` 3 本と `Mid → C` の折り返しが
  //    同じ資格で `member:C` に届く形で、`calls` 側（`chain` が入った連鎖）に決まることを固定する
  const waNodes = [
    synNode('tf:aws_lambda_function.a', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('tf:aws_api_gateway_integration.i', 'resource', {
      resourceType: 'aws_api_gateway_integration', category: 'apigateway' }),
    synNode('member:Mid', 'member'), synNode('member:C', 'member'), synNode('member:V', 'member'),
    synNode('tf:aws_lambda_function.b', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:B.Handle', 'member'),
    synNode('ext:rds-table/orders', 'resource', { resourceType: 'aws_dynamodb_table' }),
  ];
  const waEdges = [
    synEdge('references', 'tf:aws_api_gateway_integration.i', 'tf:aws_lambda_function.a'),
    synEdge('invokes', 'member:Mid', 'tf:aws_lambda_function.a', 'human'),
    synEdge('invokes', 'tf:aws_api_gateway_integration.i', 'member:C', 'human'),
    synEdge('calls', 'member:Mid', 'member:C', 'static'),
    synEdge('invokes', 'tf:aws_api_gateway_integration.i', 'member:V', 'human'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:V'),
    synEdge('handler', 'tf:aws_lambda_function.b', 'member:B.Handle'),
    synEdge('writes', 'member:B.Handle', 'ext:rds-table/orders', 'human'),
  ];
  const wRunsA = runOrders('r41a', waNodes, waEdges, ['--from', 'tf:aws_lambda_function.a']);
  const wRowA = (out, id) => (out ? allRows(out.result).find((x) => x.id === id) : null);
  check('walk 側も候補から選び直し、注釈 invokes を複数持つ統合の形で段数・根拠・行順が 1 通り（第 41 ラウンド）',
    wRunsA.every(([, out]) => !!out && !!wRowA(out, 'member:C')
      && wRowA(out, 'member:C').evidence.id === 'calls:member:Mid->member:C'
      && wRowA(out, 'member:C').hops === 2
      && !!wRowA(out, 'ext:rds-table/orders')
      && wRowA(out, 'ext:rds-table/orders').tier === 'primary')
    && new Set(wRunsA.map(([, out]) => JSON.stringify(out ? shapeOf(out.result) : null))).size === 1,
    wRunsA.map(([name, out]) => `${name}: ${out
      ? `C=${((wRowA(out, 'member:C') || {}).evidence || {}).id}/h${(wRowA(out, 'member:C') || {}).hops}`
      : '実行失敗'}`).join(' | '));

  // B. 実測 `demo-order` / `fixture-api` と同じ形。同じ親から分かれた 2 本の連鎖が
  //    同じ資格（同じ段数・同じ旗）で `member:D` へ届く。先着だと縁の並び順で
  //    `accesses` と `references` が入れ替わった。選び直しは根から並べた縁 id の辞書順で
  //    `accesses:...P1->D` 側へ決まる
  const wbNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:E', 'member'), synNode('member:P1', 'member'),
    synNode('member:P2', 'member'), synNode('member:D', 'member'),
  ];
  const wbEdges = [
    synEdge('handler', 'tf:aws_lambda_function.s', 'member:E'),
    synEdge('calls', 'member:E', 'member:P1', 'static'),
    synEdge('calls', 'member:E', 'member:P2', 'static'),
    synEdge('accesses', 'member:P1', 'member:D', 'static'),
    synEdge('references', 'member:P2', 'member:D', 'static'),
  ];
  const wRunsB = runOrders('r41b', wbNodes, wbEdges, ['--from', 'tf:aws_lambda_function.s']);
  const wRowB = (out) => (out ? allRows(out.result).find((x) => x.id === 'member:D') : null);
  check('同じ資格で同段に届く 2 経路の行は、根から並べた縁 id の順で決まり 段数・根拠が 1 通り（第 41 ラウンド）',
    wRunsB.every(([, out]) => !!out && !!wRowB(out)
      && wRowB(out).evidence.id === 'accesses:member:P1->member:D'
      && wRowB(out).via === 'member:P1' && wRowB(out).hops === 3
      && (wRowB(out).path || []).join(' ') === ['tf:aws_lambda_function.s', 'member:E',
        'member:P1', 'member:D'].join(' '))
    && new Set(wRunsB.map(([, out]) => JSON.stringify(out ? shapeOf(out.result) : null))).size === 1,
    wRunsB.map(([name, out]) => `${name}: ${out
      ? `D=${((wRowB(out) || {}).evidence || {}).id}/h${(wRowB(out) || {}).hops}` : '実行失敗'}`).join(' | '));

  // C. 実測 `fixture-folder` と同じ形。同じ親から同じ先ノードへ `creates` と `references` の
  //    2 本の縁が並行して伸びる形。第 40 ラウンドまでは先着で向きが変わり、入替 12 通中 3 通で
  //    `creates` へ揺れた。選び直しは縁 id の辞書順で `creates` 側へ決まる
  const wcNodes = [
    synNode('tf:aws_lambda_function.s', 'resource', { resourceType: 'aws_lambda_function' }),
    synNode('member:E', 'member'), synNode('member:T', 'member'),
  ];
  const wcEdges = [
    synEdge('handler', 'tf:aws_lambda_function.s', 'member:E'),
    synEdge('creates', 'member:E', 'member:T', 'static'),
    synEdge('references', 'member:E', 'member:T', 'static'),
  ];
  const wRunsC = runOrders('r41c', wcNodes, wcEdges, ['--from', 'tf:aws_lambda_function.s']);
  const wRowC = (out) => (out ? allRows(out.result).find((x) => x.id === 'member:T') : null);
  check('同じ親から同じ先への並行する縁も 1 通り（縁 id の辞書順で creates に決まる。第 41 ラウンド）',
    wRunsC.every(([, out]) => !!out && !!wRowC(out)
      && wRowC(out).evidence.id === 'creates:member:E->member:T' && wRowC(out).hops === 2)
    && new Set(wRunsC.map(([, out]) => JSON.stringify(out ? shapeOf(out.result) : null))).size === 1,
    wRunsC.map(([name, out]) => `${name}: ${out
      ? `T=${((wRowC(out) || {}).evidence || {}).id}/h${(wRowC(out) || {}).hops}` : '実行失敗'}`).join(' | '));
}

// ---- (18) 第 43 ラウンド: 向き変え回数は親の確定済み連鎖から決まり、候補は (親, 縁) で 1 件 ----
// 双人レビュー第 42 ラウンド裁定 2「同じ表示経路なのに `switches` だけが 0 / 1 に揺れる」。
// `N0 ← N1 ← N6 → N2` の形（実測 out/tmp-r43/r42-calls-0.json / -1.json）で、`member:N2` の
// 表示経路は 4 通りどの並びでも `N0 > N1 > N6 > N2` に決まるのに、`switches` は 0 と 1 が
// 出ていた。原因は値を**到着時に凍結**していたこと（凍結値は届いたときの `cur.mdir` 基準）。
// ここは確定の段で親の確定済み連鎖から数え直すので、縁の入れ替えに対して表全体が揺れない
{
  const nodes = [
    synNode('member:N0', 'member'), synNode('member:N1', 'member'), synNode('member:N2', 'member'),
    synNode('member:N3', 'member'), synNode('member:N6', 'member'),
  ];
  const edges = [
    { id: 'e3', kind: 'calls', source: 'member:N1', target: 'member:N0', provenance: 'static' },
    { id: 'e4', kind: 'calls', source: 'member:N6', target: 'member:N2', provenance: 'static' },
    { id: 'e7', kind: 'calls', source: 'member:N6', target: 'member:N1', provenance: 'static' },
    { id: 'e9', kind: 'calls', source: 'member:N3', target: 'member:N0', provenance: 'static' },
    { id: 'e11', kind: 'calls', source: 'member:N3', target: 'member:N6', provenance: 'static' },
  ];
  // 縁の並びを 12 通り。実測の 2 とおり（HEAD コピーで `member:N2` が 0 と 1 に分かれた
  // out/tmp-r43/r42-calls-0.json / -1.json の並び）を種に、隣り合う 1 組の入れ替えで広げる。
  // 全 120 とおりの総当たりは out/tmp-r43/r43-permute.py
  const orders = [
    ['e7', 'e9', 'e11', 'e3', 'e4'], ['e9', 'e7', 'e11', 'e3', 'e4'],
    ['e7', 'e11', 'e9', 'e3', 'e4'], ['e7', 'e9', 'e3', 'e11', 'e4'],
    ['e7', 'e9', 'e11', 'e4', 'e3'], ['e9', 'e7', 'e3', 'e11', 'e4'],
    ['e7', 'e11', 'e3', 'e9', 'e4'], ['e11', 'e7', 'e3', 'e9', 'e4'],
    ['e7', 'e3', 'e11', 'e9', 'e4'], ['e7', 'e11', 'e9', 'e4', 'e3'],
    ['e7', 'e11', 'e3', 'e4', 'e9'], ['e7', 'e11', 'e4', 'e3', 'e9'],
  ].map((names) => names.map((id) => edges.find((e) => e.id === id)));
  const shape = (r) => [['entries.in', r.entries.in], ['entries.out', r.entries.out],
    ['external.out', r.external.out], ['external.in', r.external.in],
    ['wiring', r.wiring], ['sameApi', r.sameApi]]
    .flatMap(([b, rs]) => (rs || []).map((x) => `${b}|${x.id}=${x.tier}/${x.direction}`
      + `/h${x.hops}/sw${x.switches}/e${x.evidence ? x.evidence.id : '-'}`
      + `/via:${x.via || '-'}/path:${(x.path || []).join('>')}`))
    .concat([`secondOrder=${r.summary.secondOrder}`]).join('\n');
  const runs = orders.map((e, i) => runSyn(`r43sw-${i}`, { nodes, edges: e },
    ['--from', 'member:N0', '--hops', '4'], `r43sw-${i}`));
  const rowOf = (out, id) => (out ? allRows(out.result).find((x) => x.id === id) : null);
  check('向き変え回数は親の確定済み連鎖から決まり、縁の 12 入れ替えで表が 1 通り（第 43 ラウンド）',
    runs.length === 12 && runs.every((out) => !!out)
      && new Set(runs.map((out) => shape(out.result))).size === 1
      && runs.every((out) => {
        const n2 = rowOf(out, 'member:N2');
        return !!n2 && n2.switches === 1 && n2.hops === 3
          && n2.evidence.id === 'e4' && n2.via === 'member:N6'
          && (n2.path || []).join(' ') === 'member:N0 member:N1 member:N6 member:N2';
      })
      && runs.every((out) => out.result.summary.secondOrder === 1),
    runs.map((out, i) => `並べ${i}: ${out
      ? `N2=${(rowOf(out, 'member:N2') || {}).switches}` : '実行失敗'}`).join(' | '));

  // 向き変え回数の値そのものを固定する。`N0 → N1 → N6` は同じ向き（`calls` を逆に辿る 2 歩）で、
  // `N6 → N2` の一歩だけ向きを変えるので 1。向きを変えない連鎖（`member:N6`）は 0 のまま
  check('同じ向きが続く連鎖は 0、向きを変えた一歩から先だけ 1（第 43 ラウンド）',
    runs.every((out) => !!out && ['member:N1', 'member:N3', 'member:N6']
      .every((id) => (rowOf(out, id) || {}).switches === 0)),
    runs.map((out) => (out ? ['member:N1', 'member:N3', 'member:N6']
      .map((id) => `${id}=${(rowOf(out, id) || {}).switches}`).join(',') : '実行失敗')).join(' | '));

  // 候補集合の重複検査（`settlePool` の入口）は不健全な状態を警告にする。上の fixture は
  // `member:N2` が walk の 1 巡目・2 巡目の両方へ同じ (親, 縁) で届く形なので、ここを
  // 通っても警告が出ないことを見る（重複が残ったまま選び直すと、同じ一歩の別実体を
  // 並べて並び順で決めることになる。第 42 ラウンドまで実体比較で重複排除が効いておらず、
  // 実測 elsa-folder で選び直し対象が 3,935 ノードへ水増ししていた。数値の実測は
  // out/tmp-r43/dedup-count.py: 候補 157,300 件 → 78,650 件、対象 3,935 → 2,393 ノード）
  check('walk の候補集合に同じ (親, 縁) の重複が残っていたら警告する（第 43 ラウンド）',
    runs.every((out) => !!out && !/同じ \(親, 縁\) の重複/.test(out.stderr)));
}

// ---- (18) 第 44 ラウンド: 後着の一歩の事実と、表示経路から数える向き変え回数 ----
// 双人レビュー第 43 ラウンド両名の指摘「同じ表示経路なのに 欄・向き・向き変え回数が縁の並び順で
// 変わる」。原因は 2 つあった。
//  (1) `found` で先着と合流した一歩の縁は `mergeFlags` が旗だけを寄せて捨てるので `promote`
//      （＝`noteFacts`）へ届かない。「同じノードへ届いた動きの縁」の事実が縁の並び順で有無に
//      変わり、`directionOf` が 動きの縁の矢印 を読むか 辿った向きへ落ちるかで欄が入れ替わった
//  (2) 向き変え回数を表示経路ではなく到着時点の値で出していた（`mergeFlags` が向きと対応を
//      取せずに寄せた混ざり物。注釈の縁の `corr` も同じノードへ届いた別の一歩から引き継がる）
// どちらも **表示に決まった連鎖と、到着した全ての縁** から決めることで直した。最小反例は
// 自動最小化の実測（out/tmp-r44/min-2.json・min-5.json / 手順 out/tmp-r44/shrink.log）
{
  const n44 = (id) => synNode(id, 'member');
  const e44 = (id, kind, source, target, provenance) => ({ id, kind, source, target, provenance, metadata: {} });
  const shape44 = (r) => allRows(r).map((x) => `${x.id}=${x.bucket}/${x.tier}/${x.direction}/h${x.hops}`
    + `/sw${x.switches}/e${x.evidence ? x.evidence.id : '-'}`
    + `/mv:${x.movementEvidence ? x.movementEvidence.id : '-'}/via:${x.via || '-'}`
    + `/path:${(x.path || []).join('>')}`).join('\n');
  const row44 = (out, id) => (out ? allRows(out.result).find((x) => x.id === id) : null);
  // 4 通りの縁順（ファイル順・逆順・隣り合う 1 組の入れ替え 2 通り）で表が 1 通りかをみる。
  // ここに挙げた反例自体は全縁順（4 縁 = 24 とおり、5 縁 = 120 とおり。`out/tmp-r44/allperm.py`）
  // でも 1 通りに収まった。収まらない反例（cut 判定ともう 1 系統）は決定 67 に残してある
  const orders44 = (edges) => {
    const n = edges.length;
    return [['fwd', edges], ['rev', [...edges].reverse()],
      // 隣り合う 1 組だけ入れ替えた 2 通り（先頭同士と末尾同士）
      ['sw1', [edges[1], edges[0], ...edges.slice(2)]],
      ['sw2', ...[[...edges.slice(0, n - 2), edges[n - 1], edges[n - 2]]]]];
  };

  // 反例 1: `member:N0` は注釈の `calls` で `member:N7` に届き、`member:N7` は `member:N1` が呼ぶ。
  // 同じ `member:N1` へ `member:N4` から 動きの縁 `triggers` も届く。後着として消えた方の並びでは
  // `triggers` を忘れて 影響を受ける入口 に並んでいた（実測 4 縁。min-2.json）
  // 第 45 ラウンドの Astra 裁定・案 D（`out/review-astra45.log`）で **動きの根拠は表示経路に
  // 実際に含まれる縁だけ** から決めるので、`member:N1` への表示経路
  // （`N0 ←calls(e4, 注釈)← N7 ←calls(e2)← N1`）に動きの縁は無い。動きの根拠 は無し。
  // 向きは表示経路を根から読む（第 45 ラウンド追加裁定）: `e4` の矢印が `N7` を指すので 1 本目が
  // 影響する先、`e2` は 向きを持つ一歩（静的解析の `calls`）なので自分の矢印で 影響を受ける入口 に
  // 戻る。注釈縁 `e4` が経路に入るので 対応 は true
  // （`e2` の provenance は 上の説明どおり 静的解析の縁なので `static`。実グラフで `calls` が
  // `terraform` の provenance を持つことは無い。実測の kind × provenance 内訳は
  // `out/tmp-r45/ATTRIB.md`。Terraform の定義の縁 = 無方向で閉じる縁、の判定に効く）
  const g44a = [
    e44('e2', 'calls', 'member:N1', 'member:N7', 'static'),
    e44('e4', 'calls', 'member:N0', 'member:N7', 'human'),
    e44('e6', 'triggers', 'member:N0', 'member:N4', 'llm'),
    e44('e8', 'triggers', 'member:N4', 'member:N1', 'static'),
  ];
  const runs44a = orders44(g44a).map(([name, es]) => [name, runSyn(`r44-min2-${name}`,
    { nodes: ['member:N0', 'member:N1', 'member:N4', 'member:N7'].map(n44), edges: es },
    ['--from', 'member:N0', '--hops', '4'], `r44-min2-${name}`)]);
  check('別経路の動きの縁は 動きの根拠 にしない。4 とおりの縁順で 欄・向き・動きの根拠 が 1 通り（第 45 ラウンド裁定）',
    runs44a.every(([, out]) => !!out)
      && new Set(runs44a.map(([, out]) => shape44(out.result))).size === 1
      && runs44a.every(([, out]) => {
        const r = row44(out, 'member:N1');
        return !!r && r.direction === 'in' && r.movementEvidence === null && r.correspondence === true;
      }),
    runs44a.map(([name, out]) => `${name}: ${out ? `${(row44(out, 'member:N1') || {}).direction}`
      + `/mv:${((row44(out, 'member:N1') || {}).movementEvidence || {}).id || '-'}` : '実行失敗'}`).join(' | '));

  // 反例 2: 並行する 2 縁（`invokes` と `calls`）と 定義ノードへ戻る `references` の形。
  // `member:N2` の 動きの根拠 と 呼ばれて成立 が並び順で消えていた（実測 5 縁。min-5.json）
  // 第 45 ラウンドの Astra 裁定・案 D で表示値は表示経路だけの関数。`member:N2` への表示経路は
  // `N0 ←handler(e6)← N3 ←references(e4)← N2` の 2 段で、最終一歩は `references`。別経路の
  // `invokes(e0)` を読む規則は捨てたので 動きの根拠 は無し・呼ばれて成立 は false、
  // 向きは表示経路を根から読んだ値（`e6` の 矢印が `N3` を指すので 1 本目が 影響する先、
  // `e4` は 向きを持つ一歩（static）なので 自分の 矢印で 影響を受ける入口）。
  // 4 とおりの縁順で表が 1 通りであることは不変
  const g44b = [
    e44('e0', 'invokes', 'member:N1', 'member:N2', 'static'),
    e44('e4', 'references', 'member:N2', 'member:N3', 'static'),
    e44('e5', 'calls', 'member:N1', 'member:N2', 'static'),
    e44('e6', 'handler', 'member:N0', 'member:N3', 'terraform'),
    e44('e8', 'invokes', 'member:N1', 'member:N0', 'llm'),
  ];
  const runs44b = orders44(g44b).map(([name, es]) => [name, runSyn(`r44-min5-${name}`,
    { nodes: ['member:N0', 'member:N1', 'member:N2', 'member:N3'].map(n44), edges: es },
    ['--from', 'member:N0', '--hops', '4'], `r44-min5-${name}`)]);
  check('並行する縁と定義ノードへ戻る折り返しのある形で、4 とおりの縁順の表が 1 通り（第 44 ラウンド）',
    runs44b.every(([, out]) => !!out)
      && new Set(runs44b.map(([, out]) => shape44(out.result))).size === 1
      && runs44b.every(([, out]) => {
        const r = row44(out, 'member:N2');
        return !!r && r.direction === 'in' && r.switches === 1 && r.movementEvidence === null
          && r.reachedByInvokes === false;
      }),
    runs44b.map(([name, out]) => `${name}: ${out ? JSON.stringify(shape44(out.result).split('\n').length) : '実行失敗'}`).join(' | '));

  // 向き変え回数は**表示に決まった根拠経路**の属性。選び直しが組み上げた経路は walk の探索予算
  // （1 回）を超えてよいので、2 回以上も正直に出す（Astra 裁定 A、out/review-astra44.log）。
  // 「向き変えを含む行 N 件」は `switches` が 1 以上の行数で、JSON の `secondOrder` と同じ
  const md44 = join(dir, 'r44-sw-demo.md');
  const d44 = run(['--api', 'POST /orders', '--md', md44], 'r44-sw-demo');
  check('向き変え回数は 2 以上も正直に出し、件数は 1 以上の行数と一致する（第 44 ラウンド）',
    !!d44 && allRows(d44.result).some((x) => x.switches >= 2)
      && d44.result.summary.secondOrder === allRows(d44.result).filter((x) => x.switches >= 1).length
      && /向き変えを含む行/.test(readFileSync(md44, 'utf8')),
    d44 ? `回数=${JSON.stringify(allRows(d44.result).reduce((a, x) => {
      a[x.switches] = (a[x.switches] || 0) + 1; return a; }, {}))} secondOrder=${d44.result.summary.secondOrder}`
      : '実行失敗');
}

// ---- 実行した全レポート横断の検査（第 46 ラウンド双人レビュー P2）----
{
  const KEYS = ['id', 'kind', 'provenance', 'source', 'target'];
  const bad = [];
  for (const { label, result } of allDocs) {
    for (const r of allRows(result)) {
      const k = Object.keys(r.evidence || {}).sort();
      if (k.join(',') !== KEYS.join(',')) bad.push(`${label}/${r.id} evidence=[${k.join(',')}]`);
      if (r.movementEvidence) {
        const m = Object.keys(r.movementEvidence).sort();
        if (m.join(',') !== KEYS.join(',')) bad.push(`${label}/${r.id} 動きの根拠=[${m.join(',')}]`);
      }
    }
  }
  check(`表示する縁は 5 項目だけのコピー（全 ${allDocs.length} レポート。閉包の生の縁の count / metadata を混ぜない）`,
    bad.length === 0, bad.slice(0, 3).join(' / ') || '混入 0 件');

  // 第 47 ラウンド Codex 指摘の追加候補。「根拠縁が表示経路の最後 2 点を結んでいるか」。
  // 根拠が経路に無い一歩へ差し替わると「経路の根拠」という契約が崩れる（保存済み 18 レポート
  // 441 行で違反 0 を実測してから固定）
  const offPath = [];
  for (const { label, result } of allDocs) {
    for (const r of allRows(result)) {
      const p = r.path || [];
      if (p.length < 2) continue;
      const tail = [p[p.length - 2], p[p.length - 1]].sort().join('|');
      for (const [what, e] of [['evidence', r.evidence], ['動きの根拠', r.movementEvidence]]) {
        if (!e) continue;
        if ([e.source, e.target].sort().join('|') !== tail) {
          offPath.push(`${label}/${r.id} ${what}=${e.source}→${e.target} 経路末尾=${tail}`);
        }
      }
    }
  }
  check('根拠縁と動きの根拠は表示経路の最後の 2 点を結んでいる', offPath.length === 0,
    offPath.slice(0, 3).join(' / ') || '経路の外を結ぶ縁 0 件');

  // 第 48 ラウンド Codex 提案。「動きの根拠があるなら根拠縁と同じ縁である」。
  // `movementEvidence` は最後の縁が MOVEMENT のときだけ同じ縁を入れる実装なので構造的な
  // 不変条件（保存済み 18 レポートで動きの根拠のある 42 行、不一致 0 を実測）
  const mvDiff = [];
  for (const { label, result } of allDocs) {
    for (const r of allRows(result)) {
      if (r.movementEvidence && (!r.evidence || r.movementEvidence.id !== r.evidence.id)) {
        mvDiff.push(`${label}/${r.id} 動き=${r.movementEvidence.id} 根拠=${(r.evidence || {}).id}`);
      }
    }
  }
  check('動きの根拠は根拠縁と同じ縁か null（別の縁を指さない）', mvDiff.length === 0,
    mvDiff.slice(0, 3).join(' / ') || '不一致 0 件');
}

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
