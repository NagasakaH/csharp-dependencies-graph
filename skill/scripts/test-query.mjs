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

// 13) ルートに置かれた新規ファイルは `folder:.` へフォールバックする
writeFileSync(list, 'NewFile.cs\n');
r = json('--changed', list, '--hops', '1');
check('親が無くてもルートの folder:. を起点にする', r.data?.starts?.[0] === 'folder:.',
  JSON.stringify(r.data?.starts || r.error?.stderr || ''));
check('フォールバックは元パスと理由を JSON と stderr に残す',
  r.data?.fallbacks?.[0]?.path === 'NewFile.cs' && r.data?.fallbacks?.[0]?.start === 'folder:.'
  && r.error === undefined && run('--changed', list, '--hops', '1').stderr.includes('NewFile.cs'),
  JSON.stringify(r.data?.fallbacks || '') + ' / ' + run('--changed', list, '--hops', '1').stderr.trim());

// 14) 同じ起点を繰り返しても到達数が負にならない
r = json('--from', CHARGE, '--from', CHARGE, '--kind', 'nonexistent');
check('起点の重複は 1 件にまとめ、到達 0 になる',
  r.data?.starts?.length === 1 && r.data?.summary?.reached === 0,
  JSON.stringify({ starts: r.data?.starts, reached: r.data?.summary?.reached }));

// 15) フィルタをかけたときはサマリー行に何で絞ったかを出す
r = run('--from', CHARGE, '--dir', 'out', '--kind', 'accesses', '--provenance', 'static');
check('サマリー行に kind と provenance の指定が出る',
  r.stdout.includes('kind accesses') && r.stdout.includes('provenance static'), r.stdout.split('\n')[0]);

// 16) 読み方の注記が help に入っている（初到達 1 経路 / 到達数は到達木）
r = run('--help');
check('help に到達木の読み方とフォールバックの注意を書く',
  r.stdout.includes('最初に到達した 1 経路') && r.stdout.includes('依存エッジの証拠ではない'), r.stdout.slice(-400));

// 17) --group-by file: 実縁で届いたノードをファイル単位に巻き上げる
r = json('--from', LAMBDA, '--dir', 'out', '--hops', '2', '--group-by', 'file');
const g17 = r.data?.groups || [];
check('--group-by file が接続ファイルと参照件数・縁の内訳・最短段数を出す',
  g17.length === 1 && g17[0].id === 'file:src/Pay.cs' && g17[0].nodes >= 1
  && Object.keys(g17[0].kinds).includes('handler') && g17[0].minHop === 1,
  JSON.stringify({ groups: g17, summary: r.data?.summary }));

// 18) 階層（contains）で届いただけのノードは集計に数えない
r = json('--from', 'file:src/Pay.cs', '--dir', 'out', '--via-parent', '--hops', '3', '--group-by', 'file');
check('階層で届いただけのグループは集計から外し、その件数を合計に含めない',
  (r.data?.groups || []).length === 0 && (r.data?.summary?.groupsSkippedHierarchy || 0) >= 1,
  JSON.stringify({ groups: r.data?.groups, skipped: r.data?.summary?.groupsSkippedHierarchy }));

// 19) 縁の列挙順が変わっても集計は変わらない（反転・id 順・source 順・交互の 4 とおり、
//     --via-parent ありなしの両方で `groups` と summary の集計欄が完全一致すること）
const runOn = (graph, ...argv) => {
  const proc = spawnSync('node', [QUERY, '--graph', graph, ...argv], { encoding: 'utf8' });
  try { return JSON.parse(proc.stdout); } catch { return { error: proc.stderr }; }
};
const base = JSON.parse(readFileSync(GRAPH, 'utf8'));
const perms = {
  '反転': [...base.edges].reverse(),
  'id 順': [...base.edges].sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0)),
  'source 順': [...base.edges].sort((a, b) => (a.source < b.source ? -1 : a.source > b.source ? 1 : (a.id < b.id ? -1 : 1))),
  '交互': base.edges.filter((_, i) => i % 2 === 0).concat(base.edges.filter((_, i) => i % 2 === 1)),
};
const permArgs = [['--from', LAMBDA, '--dir', 'out', '--hops', '2', '--group-by', 'file'],
  ['--from', CHARGE, '--dir', 'both', '--via-parent', '--hops', '3', '--group-by', 'file'],
  ['--from', 'file:src/Pay.cs', '--dir', 'both', '--via-parent', '--hops', '2', '--group-by', 'folder']];
let permOk = true;
const permBad = [];
for (const [argsIdx, argv] of permArgs.entries()) {
  for (const [name, edges] of Object.entries(perms)) {
    const file = join(tmp, `perm-${argsIdx}-${name}.json`);
    writeFileSync(file, JSON.stringify({ ...base, edges }));
    const d = runOn(file, '--json', ...argv);
    const ref = runOn(GRAPH, '--json', ...argv);
    // 初到達の 1 経路（reached / byEdge）は到達木なので縁順で変わりうる。集計側だけ比べる
    const key = (x) => JSON.stringify({
      groups: x.groups,
      s: Object.fromEntries(Object.entries(x.summary || {}).filter(([k]) => k.startsWith('groups') || k === 'reached')),
    });
    if (key(d) !== key(ref)) { permOk = false; permBad.push(`${argsIdx}/${name}: ${key(d)} != ${key(ref)}`); }
  }
}
check('縁の列挙順 4 とおり × --via-parent ありなしで --group-by の JSON が完全一致', permOk, permBad.join(' | ').slice(0, 400));

// 19b) 報告された再現図式（実縁と階縁が同じノードへ同じ段で届く）を縁順の両順で確かめる
const repro = {
  schemaVersion: 1, producer: 'test', generatedAt: '2026-01-01T00:00:00+09:00', root: 'repro',
  nodes: [
    { id: 'folder:.', kind: 'folder', name: '.', parent: null },
    { id: 'file:A.cs', kind: 'file', name: 'A.cs', parent: 'folder:.', path: 'A.cs' },
    { id: 'type:A', kind: 'type', name: 'A', parent: 'file:A.cs', path: 'A.cs' },
    { id: 'member:A.a', kind: 'member', name: 'a', parent: 'type:A', path: 'A.cs' },
    { id: 'file:B.cs', kind: 'file', name: 'B.cs', parent: 'folder:.', path: 'B.cs' },
    { id: 'type:B', kind: 'type', name: 'B', parent: 'file:B.cs', path: 'B.cs' },
    { id: 'member:B.d', kind: 'member', name: 'd', parent: 'type:B', path: 'B.cs' },
    { id: 'file:C.cs', kind: 'file', name: 'C.cs', parent: 'folder:.', path: 'C.cs' },
    { id: 'type:C', kind: 'type', name: 'C', parent: 'file:C.cs', path: 'C.cs' },
    { id: 'member:C.c', kind: 'member', name: 'c', parent: 'type:C', path: 'C.cs' },
  ],
  edges: [
    { id: 'e1', source: 'member:A.a', target: 'type:B', kind: 'references', provenance: 'static' },
    { id: 'e2', source: 'member:A.a', target: 'member:C.c', kind: 'calls', provenance: 'static' },
    { id: 'e3', source: 'member:C.c', target: 'member:B.d', kind: 'calls', provenance: 'static' },
  ],
};
const REPRO_ARGS = ['--from', 'member:A.a', '--dir', 'out', '--via-parent', '--hops', '3', '--group-by', 'type'];
writeFileSync(join(tmp, 'repro-fwd.json'), JSON.stringify(repro));
writeFileSync(join(tmp, 'repro-rev.json'), JSON.stringify({ ...repro, edges: [...repro.edges].reverse() }));
const rf = runOn(join(tmp, 'repro-fwd.json'), '--json', ...REPRO_ARGS);
const rr = runOn(join(tmp, 'repro-rev.json'), '--json', ...REPRO_ARGS);
const bRepro = (rf.groups || []).find((g) => g.id === 'type:B');
check('実縁と階縁が同じ段で届いたノードは実縁で数え、縁順で件数が変わらない',
  JSON.stringify(rf.groups) === JSON.stringify(rr.groups) && (rf.groups || []).length > 0
  && bRepro?.nodes === 2 && rf.summary?.groupsSkippedHierarchy === 0,
  JSON.stringify({ fwd: rf.groups, rev: rr.groups, skipped: rf.summary?.groupsSkippedHierarchy }));

// 20) 除外の内訳が JSON と標準出力の両方に出て、表の合計と説明がつく
r = json('--from', LAMBDA, '--dir', 'both', '--hops', '3', '--group-by', 'file');
const s20 = r.data?.summary || {};
const sumNodes = (r.data?.groups || []).reduce((a, g) => a + g.nodes, 0);
check('集計の除外内訳が JSON に出て表の合計と合う（巻き上げ対象 = 表 + 起点階層 + 祖先なし）',
  (s20.groupsNodes || 0) === sumNodes
  && s20.groupsReached === sumNodes + (s20.groupsSkippedStartHierarchy || 0) + (s20.groupsSkippedNoAncestor || 0)
  && (s20.groupsReached || 0) + (s20.groupsSkippedHierarchy || 0) === s20.reached
  && (s20.groupsSkippedNoAncestor || 0) > 0,
  JSON.stringify(s20) + ' / 表合計 ' + sumNodes);
const txt20 = run('--from', LAMBDA, '--dir', 'both', '--hops', '3', '--group-by', 'file').stdout;
check('同じ内訳が標準出力の 1 行目にも出る（巻き上げ対象と除外の件数）',
  txt20.includes(`実縁で届いた ${s20.groupsReached} 件を file に巻き上げ。表 ${sumNodes} 件`)
  && txt20.includes(`起点自身の階層 ${s20.groupsSkippedStartHierarchy}`)
  && txt20.includes(`file の祖先を持たない ${s20.groupsSkippedNoAncestor}`),
  txt20.split('\n').find((l) => l.includes('単位の集計')) || '');

// 21) member: 起点でも「起点自身の階層は数えません」が効く（起点を巻き上げた階層を除く）
r = json('--from', CHARGE, '--dir', 'both', '--hops', '3', '--group-by', 'file');
const g21 = r.data?.groups || [];
check('member: 起点でも起点の所属ファイルを参照一覧から除く',
  !g21.some((g) => g.id === 'file:src/Pay.cs') && (r.data?.summary?.groupsSkippedStartHierarchy || 0) >= 1,
  JSON.stringify({ ids: g21.map((g) => g.id), skipped: r.data?.summary?.groupsSkippedStartHierarchy }));

// 22) project は選べない（実グラフでコードの所属プロジェクトはたどれないため）
const proj = run('--from', LAMBDA, '--group-by', 'project');
check('--group-by project は「たどれない」と理由を出して終了コード 2',
  proj.status === 2 && proj.stderr.includes('project') && proj.stderr.includes('たどれない'),
  `${proj.status} / ${proj.stderr.trim()}`);
const help22 = run('--help').stdout;
check('help に集計階層が file / folder / type と project が選べない理由を書く',
  help22.includes('file / folder / type') && help22.includes('project は選べない') && help22.includes('たどれない'),
  help22.slice(0, 1600));

// 23) 実縁を持たない階層起点を --via-parent 無しで投げたら stderr に案内を出す（結果は作らない）
const noVia = run('--from', 'file:src/Pay.cs', '--dir', 'out', '--hops', '1');
const withVia = json('--from', 'file:src/Pay.cs', '--dir', 'out', '--via-parent', '--hops', '1');
check('階層起点で --via-parent 無くし到達 0 件のときだけ stderr に案内を出す',
  noVia.status === 0 && noVia.stdout.includes('到達 0 ノード') && noVia.stderr.includes('--via-parent')
  && noVia.stderr.includes('file:src/Pay.cs') && (withVia.data?.reached || []).length > 0
  && !withVia.error, `${noVia.status} / ${noVia.stderr.trim()}`);

// 24) 不正な --group-by は終了コード 2 で拒否する
const bad = spawnSync('node', [QUERY, '--graph', GRAPH, '--from', LAMBDA, '--group-by', 'member'], { encoding: 'utf8' });
check('--group-by は file / folder / type 以外なら終了コード 2',
  bad.status === 2 && bad.stderr.includes('--group-by'), `${bad.status} / ${bad.stderr.trim()}`);

rmSync(tmp, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
