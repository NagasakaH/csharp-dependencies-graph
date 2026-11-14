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
// 手作りのグラフをそのまま渡す実行（双人レビューの最小反例を回帰テストとして固定する）
const FACTS = join(HERE, '..', 'tests', 'fixtures', 'ImpactFacts');
function runOn(graphFile, args, label) {
  const json = join(dir, `${label}.json`);
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', join(FACTS, graphFile),
    ...args, '--json', json], { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  return { result: JSON.parse(readFileSync(json, 'utf8')), stdout: proc.stdout, stderr: proc.stderr };
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
  const proc = spawnSync(process.execPath, [join(HERE, 'report.mjs'), '--graph', file, ...args, '--json', json],
    { cwd: root, encoding: 'utf8' });
  if (proc.status !== 0) { console.error((proc.stdout || '') + (proc.stderr || '')); return null; }
  return { result: JSON.parse(readFileSync(json, 'utf8')), stdout: proc.stdout };
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
const nested = {
  nodes: ['tf:method.a', 'tf:integration.a', 'tf:lambda.a', 'member:Handler.A', 'tf:method.b',
    'tf:integration.b', 'tf:lambda.b', 'member:Handler.B', 'tf:table.b']
    .map((id) => synNode(id, id.startsWith('member:') ? 'member' : 'resource')),
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
const epMeta = (t, cat, api) => ({ resourceType: t, category: cat, rest_api_id: api });
const flip = {
  nodes: [
    synNode('tf:aws_api_gateway_method.post_x', 'resource', epMeta('aws_api_gateway_method', 'api-gateway', 'tf:aws_api_gateway_rest_api.g')),
    synNode('tf:aws_api_gateway_integration.post_x', 'resource', epMeta('aws_api_gateway_integration', 'api-gateway', 'tf:aws_api_gateway_rest_api.g')),
    synNode('tf:aws_lambda_function.x', 'resource', epMeta('aws_lambda_function', 'lambda', null)),
    synNode('tf:aws_sfn_state_machine.p', 'resource', epMeta('aws_sfn_state_machine', 'step-functions', null)),
    synNode('member:X.Handle', 'member'),
  ],
  edges: [
    synEdge('references', 'tf:aws_api_gateway_integration.post_x', 'tf:aws_api_gateway_method.post_x'),
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

// 経路は必ず起点から始まる。`via` が循環すると長さ 2 の循環でも `hops === path.length - 1` を
// 素通りしてしまう（第 18 ラウンド両名: 実プロジェクトの 9 行中 5 行、IAM ポリシー起点の全 15 行）
const rootBad = hopReports.flatMap((x) => {
  const starts = new Set(x.result.summary.startIds || []);
  return allRows(x.result)
    .filter((r) => r.pathRoot === 'broken' || (r.pathRoot === 'second-stage' && starts.has(r.path[0])))
    .map((r) => `${x.name || ''}${r.id} ${r.pathRoot} path[0]=${r.path[0]}`);
});
check('経路は起点から始まるか、2 段階目として切れた地点から始まる（壊れた経路を出さない）',
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
  check('経路を循環境避で切っても、動きの縁で受理した本命は定義上の関連へ落とさない',
    !!r && ['c', 'b'].every((n) => { const x = g(`sfn_state_machine.${n}`); return x && x.tier === 'primary'
      && x.direction === 'in' && x.movementEvidence && x.movementEvidence.kind === 'invokes'; })
    && ['d', 'e'].every((n) => { const x = g(`aws_lambda_function.${n}`); return x && x.tier === 'primary' && x.direction === 'out'; })
    && r.result.summary.wiring === 0,
    r ? JSON.stringify([...byId.values()].map((x) => [x.id, x.tier, x.direction])) : '実行失敗');
}
// (2) 向きの判定は「動きの縁の矢印」を先に読む。実装側に入った旗より優先する
{
  const r = runOn('arrow-priority.graph.json', ['--api', 'POST /orders'], 'facts-arrow');
  const sfnId = 'tf:aws_sfn_state_machine.up';
  const hit = r ? [...r.result.external.in, ...r.result.external.out].find((x) => x.id === sfnId) : null;
  check('この Lambda を呼びにくる側は、実装側に入った旗よりも動きの縁の矢印で 影響を受ける入口 に出す',
    !!hit && hit.direction === 'in' && !!hit.movementEvidence
    && hit.movementEvidence.kind === 'invokes' && hit.tier === 'primary',
    hit ? JSON.stringify([hit.direction, hit.tier, hit.movementEvidence && hit.movementEvidence.kind])
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
  check('定義参照が 1 本増えても、実際の呼び出し元は 定義上の関連 に落ちない',
    !!up && up.tier === 'primary' && up.direction === 'in'
    && !!up.movementEvidence && up.movementEvidence.kind === 'invokes' && r.result.summary.wiring === 0,
    up ? JSON.stringify([up.tier, up.direction, up.movementEvidence && up.movementEvidence.kind, r.result.summary.wiring])
      : (r ? 'external / wiring に出ていない' : '実行失敗'));
  const r2 = runOn('promote-skip.graph.json', ['--from', 'tf:aws_lambda_function.start'], 'facts-promote');
  const all2 = r2 ? [...r2.result.external.in, ...r2.result.external.out, ...r2.result.wiring] : [];
  const r3 = all2.find((x) => x.id === 'tf:aws_lambda_function.r3');
  check('walk が後から本命にしたノードから先も、閉包の 2 ラウンド目で本命まで育つ',
    !!r3 && r3.tier === 'primary' && r3.direction === 'out' && r2.result.summary.wiring === 0,
    r3 ? JSON.stringify([r3.tier, r3.direction, r2.result.summary.wiring]) : (r2 ? 'r3 が出ていない: ' + JSON.stringify(all2.map((x) => [x.id, x.tier])) : '実行失敗'));
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
    !!r && r.result.summary.primaryOut === 3 && r.result.summary.entryOut === 2
    && (byId.get('tf:aws_lambda_function.b') || {}).tier === 'primary'
    && (byId.get('ext:rds-table/orders') || {}).tier === 'primary',
    r ? JSON.stringify([r.result.summary.primaryOut, r.result.summary.entryOut,
      [...byId].map(([k, v]) => [k.replace('tf:aws_', ''), v.tier])]) : '実行失敗');
  for (const [name, file] of [['定義を辿る縁だけの API グループ', 'group-cache.graph.json'],
    ['コードの種が無いラウンドでもグループ追加で定義を拡げる', 'group-late.graph.json']]) {
    const rr = runOn(file, ['--from', 'tf:aws_lambda_function.s'], `group-${file}`);
    const same = rr ? allOf(rr.result).find((x) => x.id === 'tf:aws_lambda_function.b') : null;
    check(`${name}: 同じ API を起動する Lambda は本命で 影響する先`,
      !!same && same.tier === 'primary' && same.direction === 'out',
      same ? JSON.stringify([same.tier, same.direction, same.evidence.kind]) : (rr ? '出ていない' : '実行失敗'));
  }
}

// (6) 予算（`--wiring-hops`）は `(elig, down)` の資格ごとに数える
{
  const r = runOn('budget-min.graph.json', ['--from', 's', '--wiring-hops', '1'], 'budget-min');
  const ids = r ? r.result.wiring.map((x) => x.id) : [];
  check('定義上の関連でも予算の届け直しで先まで出る（`t` が脱落しない）',
    !!r && r.result.summary.wiring === 3 && ids.includes('t'),
    r ? JSON.stringify([r.result.summary.wiring, ids]) : '実行失敗');

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
  check('動きの縁で予算が戻った経路の先（`lam2`）がどこにも出ないことがない',
    !!lam2 && lam2.tier === 'primary' && lam2.direction === 'out',
    lam2 ? JSON.stringify([lam2.tier, lam2.direction]) : (c ? '出ていない' : '実行失敗'));

  const d = runOn('six-groups.graph.json', ['--from', 's', '--hops', '32'], 'six-groups');
  check('API の連鎖が 6 組あってもラウンド上限で黙って切らない（未収束なら旗を出す）',
    !!d && d.result.summary.primaryOut === 12 && d.result.summary.primaryIn === 6
    && d.result.summary.wiring === 6 && d.result.summary.unresolved === false,
    d ? JSON.stringify([d.result.summary.primaryOut, d.result.summary.primaryIn,
      d.result.summary.wiring, d.result.summary.rounds, d.result.summary.maxRounds,
      d.result.summary.unresolved]) : '実行失敗');
}

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
