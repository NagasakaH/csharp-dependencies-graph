#!/usr/bin/env node
// アナライザの静的解析の正確性テスト。fixtures/ 下の C# を cgd にかけ、
// 「出てはいけないエッジ」と「出るべきエッジ」を検査する。
// 使い方: node skill/scripts/test-analyzer.mjs [--cgd <パス>]
import { spawnSync } from 'node:child_process';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
const flag = (name) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : null; };

function findCgd() {
  const given = flag('--cgd') || process.env.CGD_BIN;
  if (given) return resolve(given);
  const candidates = ['Release', 'Debug'].flatMap((c) => ['net9.0', 'net8.0'].map((t) => join(HERE, '..', 'analyzer', 'bin', c, t, 'cgd')));
  for (const c of candidates) if (existsSync(c)) return c;
  console.error('[test] cgd が見つかりません。先に `dotnet build skill/analyzer/cgd.csproj -c Release` か、--cgd で指定してください。');
  process.exit(1);
}

const cgd = findCgd();
const dir = mkdtempSync(join(tmpdir(), 'cgd-test-'));
let pass = 0;
const failures = [];

function check(label, ok, detail) {
  if (ok) { pass++; console.log(`PASS ${label}`); } else { failures.push(label); console.log(`FAIL ${label}${detail ? `  ${detail}` : ''}`); }
}

function analyze(fixture) {
  const out = join(dir, `${fixture}.json`);
  const proc = spawnSync(cgd, ['--root', join(HERE, '..', 'tests', 'fixtures', fixture), '--out', out, '--quiet'], { encoding: 'utf8' });
  if (proc.status !== 0) {
    const log = (proc.stdout || '') + (proc.stderr || '');
    if (log.includes('You must install or update .NET')) {
      console.error('[test] cgd は .NET 9 実行時が必要です。`export DOTNET_ROOT=$HOME/.dotnet` をしてから再実行してください。');
      console.error(log.trim().split('\n').slice(0, 4).join('\n'));
    } else console.error(log);
    process.exit(1);
  }
  return JSON.parse(readFileSync(out, 'utf8'));
}

const g = analyze('StaticAccuracy');
const shortName = (id) => id.replace(/^member:/, '').split('.').slice(-2).join('.');
const edges = g.edges.filter((e) => e.kind !== 'contains');
const has = (kind, from, to) => edges.some((e) => e.kind === kind && shortName(e.source) === from && e.target === to);
const member = (n) => `member:Fixtures.StaticAccuracy.${n}`;

// 1) 局所変数がメソッド名を隠すケースで this.X を断定しない
check('ローカル変数のデリゲート呼び出しを this.Go にしない', !has('calls', 'Caller.DelegateInVariable', member('Caller.Go')),
  JSON.stringify(edges.filter((e) => shortName(e.source) === 'Caller.DelegateInVariable' && shortName(e.target) === 'Caller.Go').map((e) => `${e.kind}:${e.detail}`)));

// 2) デリゲート型フィールドの呼び出しも同じ
check('デリゲート型フィールドの呼び出しを this.Go にしない', !has('calls', 'Caller.DelegateField', member('Caller.Go')));

// 3) 本物の this.Call() は残す（過剰な抑制にしない）
check('this.Go() の呼び出しは検出する', has('calls', 'Caller.RealCalls', member('Caller.Go')));

// 4) var の型推論（var を見落とすと x.Bar() のエッジが黙って消える）
check('var で作った型のメソッド呼び出しを検出する', has('calls', 'Caller.RealCalls', member('Worker.Go')));

// 5) 明示型のローカル変数
check('明示型のローカル変数の呼び出しを検出する', has('calls', 'Caller.RealCalls', member('Worker.Go')) &&
  edges.some((e) => e.kind === 'creates' && shortName(e.source) === 'Caller.RealCalls' && e.target === 'type:Fixtures.StaticAccuracy.Worker'));

// 6) new の型参照
check('new Worker() を creates にする', edges.some((e) => e.kind === 'creates' && e.target === 'type:Fixtures.StaticAccuracy.Worker'));

// 7) member の親は必ず type
const byId = new Map(g.nodes.map((n) => [n.id, n]));
check('member ノードの親は type ノード', g.nodes.filter((n) => n.kind === 'member').every((n) => byId.get(n.parent)?.kind === 'type'));

// 8) 同名メソッドの区別（overloads）
check('partial / overload の id が重複しない', new Set(g.nodes.map((n) => n.id)).size === g.nodes.length);

// ---- ScopeAccuracy: 名前解決の位置対応（レビュー指摘の回帰テスト）
const sg = analyze('ScopeAccuracy');
const sEdges = sg.edges.filter((e) => e.kind !== 'contains');
const sHas = (kind, from, to) => sEdges.some((e) => e.kind === kind && shortName(e.source) === from && e.target === `member:Fixtures.ScopeAccuracy.${to}`);
const sCount = (kind, from, to) => {
  const e = sEdges.find((x) => x.kind === kind && shortName(x.source) === from && x.target === `member:Fixtures.ScopeAccuracy.${to}`);
  return e ? e.count || 1 : 0;
};
const sScopeEdges = (from) => JSON.stringify(sEdges.filter((e) => shortName(e.source) === from)
  .map((e) => `${e.kind}:${e.target.split('.').slice(-2).join('.')}`));

check('兄弟ブロックの同名 var を混同しない',
  sHas('calls', 'SiblingBlocks.Run', 'A.Go') && sHas('calls', 'SiblingBlocks.Run', 'B.Go') &&
  sHas('accesses', 'SiblingBlocks.Run', 'A.Value') && sHas('accesses', 'SiblingBlocks.Run', 'B.Value'),
  sScopeEdges('SiblingBlocks.Run'));

check('型を省略したラムダ引数を this.Go にしない', !sHas('calls', 'Shadowing.LambdaParameter', 'Shadowing.Go'),
  sScopeEdges('Shadowing.LambdaParameter'));

check('ローカル関数を this.Go にしない', !sHas('calls', 'Shadowing.LocalFunction', 'Shadowing.Go'),
  sScopeEdges('Shadowing.LocalFunction'));

check('兄弟ブロックより前の this.Go はちゃんと検出する', sHas('calls', 'Shadowing.SiblingThenCall', 'Shadowing.Go'),
  sScopeEdges('Shadowing.SiblingThenCall'));

check('スコープ書き換え後も var 推論が壊れない', sHas('calls', 'Shadowing.InferredVar', 'Worker.Go'),
  sScopeEdges('Shadowing.InferredVar'));

// foreach の要素型（List<Item> を Item に畳むと全滅する）
check('foreach の要素型をフィールドから推論する', sHas('calls', 'ForeachElements.FromField', 'Item.Handle'),
  sScopeEdges('ForeachElements.FromField'));
check('foreach の要素型を引数から推論する', sHas('calls', 'ForeachElements.FromParameter', 'Item.Handle'),
  sScopeEdges('ForeachElements.FromParameter'));
check('foreach の要素型をプロパティの戻り値から推論する', sHas('calls', 'ForeachElements.FromProperty', 'Item.Handle'),
  sScopeEdges('ForeachElements.FromProperty'));

// 2 ラウンド目の型推論が後続ブロックの宣言を潰さない（列の順序が崩れるとの再起する）
check('遅延推論が後続ブロックの宣言を潰さない',
  sHas('calls', 'DeferredShadowing.Run', 'Widget.Handle') && sHas('calls', 'DeferredShadowing.Run', 'Gadget.Handle'),
  sScopeEdges('DeferredShadowing.Run'));

check('型が決まらない var を先頭ブロックの型に化かさない',
  !sHas('calls', 'UnknownShadowing.Run', 'Widget.Handle') && sHas('calls', 'UnknownShadowing.Guard', 'Widget.Handle'),
  sScopeEdges('UnknownShadowing.Run'));

check('宣言前で呼んだローカル関数を this.Handle にしない',
  !sHas('calls', 'EarlyLocalFunction.Run', 'EarlyLocalFunction.Handle'),
  sScopeEdges('EarlyLocalFunction.Run'));

// foreach の要素型: 遅延推論したローカル / new / await の経由
check('foreach の要素型を遅延推論したローカルから推論する', sHas('calls', 'ForeachDeferred.ViaAlias', 'Item.Handle'),
  sScopeEdges('ForeachDeferred.ViaAlias'));
check('foreach の要素型を new の型から推論する', sHas('calls', 'ForeachDeferred.ViaNew', 'Item.Handle'),
  sScopeEdges('ForeachDeferred.ViaNew'));
check('foreach の要素型を await の内側から推論する', sHas('calls', 'ForeachDeferred.ViaAwait', 'Item.Handle'),
  sScopeEdges('ForeachDeferred.ViaAwait'));

check('内側ブロックの宣言が外側の後続まで型メンバを隠さない',
  sHas('calls', 'BlockScopeLeak.Run', 'Gadget.Handle') && sHas('calls', 'BlockScopeLeak.Run', 'Widget.Handle'),
  sScopeEdges('BlockScopeLeak.Run'));

// ラムダ / catch / switch の腕と節は内側だけの名前（外側の同名フィールドを化かさない）
check('ラムダ引数が外側の同名フィールドを隠さない',
  sHas('calls', 'InnerNamesOnly.Lambda', 'Gadget.Handle') && sHas('calls', 'InnerNamesOnly.Lambda', 'Widget.Handle'),
  sScopeEdges('InnerNamesOnly.Lambda'));
check('catch 変数が catch の外に漏れない', sHas('calls', 'InnerNamesOnly.Catch', 'Widget.Handle'),
  sScopeEdges('InnerNamesOnly.Catch'));
check('switch 式の腕のパターン変数が他の腕に漏れない', sHas('accesses', 'InnerNamesOnly.Arm', 'Widget.Size'),
  sScopeEdges('InnerNamesOnly.Arm'));
check('switch の節の変数が他の節に漏れない',
  sHas('calls', 'InnerNamesOnly.Section', 'Gadget.Handle') && sHas('calls', 'InnerNamesOnly.Section', 'Widget.Handle'),
  sScopeEdges('InnerNamesOnly.Section'));

// `if` 条件の out var / パターン変数は外側ブロックまで見える
check('ガード節の後でパターン変数をフィールドに化かさない',
  sHas('calls', 'GuardClause.Pattern', 'Gadget.Handle') && !sHas('calls', 'GuardClause.Pattern', 'Widget.Handle'),
  sScopeEdges('GuardClause.Pattern'));
check('out var の型は決めないが名前は塞いでフィールドに化かさない',
  !sHas('calls', 'GuardClause.OutVar', 'Widget.Handle'),
  sScopeEdges('GuardClause.OutVar'));

// using var・タプル分割・LINQ の join の名前も外側の同名フィールドに化かさない
check('using var の型で後続の同名フィールドを隠す',
  sHas('calls', 'MoreNames.UsingVar', 'Lease.Handle') && !sHas('calls', 'MoreNames.UsingVar', 'Widget.Handle'),
  sScopeEdges('MoreNames.UsingVar'));
check('using 文のブロックの変数はブロックの外に出ない',
  sHas('calls', 'MoreNames.UsingBlock', 'Lease.Handle') && sHas('calls', 'MoreNames.UsingBlock', 'Widget.Handle'),
  sScopeEdges('MoreNames.UsingBlock'));
check('タプル分割の名前をフィールドに化かさない',
  !sHas('calls', 'MoreNames.Destruct', 'Gadget.Handle') && sHas('calls', 'MoreNames.Destruct', 'Widget.Handle'),
  sScopeEdges('MoreNames.Destruct'));
check('foreach のタプル分割が外側の同名フィールドと潰れない',
  !sHas('calls', 'MoreNames.ForeachDestruct', 'Gadget.Handle') && sCount('calls', 'MoreNames.ForeachDestruct', 'Widget.Handle') === 1,
  sScopeEdges('MoreNames.ForeachDestruct'));
check('LINQ の join の範囲変数をフィールドに化かさない',
  !sHas('accesses', 'MoreNames.Join', 'Widget.Size') && sHas('calls', 'MoreNames.Join', 'Widget.Handle'),
  sScopeEdges('MoreNames.Join'));

// switch の節と入れ子 if の宣言領域（コンパイラの実測どおり）
check('switch の通常のローカルは節をまたいで見え、ブロックの外では消える',
  sCount('calls', 'SwitchLocals.Local', 'Gadget.Handle') === 2 && sCount('calls', 'SwitchLocals.Local', 'Widget.Handle') === 1,
  sScopeEdges('SwitchLocals.Local'));
check('ブロックなし入れ子 if のパターン変数を外に漏らさない',
  sCount('calls', 'EmbeddedIfs.Embedded', 'Gadget.Handle') === 1 && sCount('calls', 'EmbeddedIfs.Embedded', 'Widget.Handle') === 1,
  sScopeEdges('EmbeddedIfs.Embedded'));
check('ガード節のパターン変数は if の外でも見える（過剰な抑制にしない）',
  sCount('calls', 'EmbeddedIfs.Guard', 'Gadget.Handle') === 1 && !sHas('calls', 'EmbeddedIfs.Guard', 'Widget.Handle'),
  sScopeEdges('EmbeddedIfs.Guard'));

// `is var x` / `case var x:` / プロパティパターンの末尾 designation も名前を塞ぐ
check('`is var` の名前をフィールドに化かさない', !sHas('accesses', 'VarPatterns.VarPattern', 'Gadget.Size'),
  sScopeEdges('VarPatterns.VarPattern'));
check('`case var` の名前をフィールドに化かさない', !sHas('accesses', 'VarPatterns.CaseVar', 'Gadget.Size'),
  sScopeEdges('VarPatterns.CaseVar'));
check('プロパティパターンの末尾 designation をフィールドに化かさない',
  sHas('calls', 'VarPatterns.Recursive', 'Widget.Handle') && !sHas('calls', 'VarPatterns.Recursive', 'Gadget.Handle'),
  sScopeEdges('VarPatterns.Recursive'));

// 分割形式の foreach はループ変数を外へ漏らさない（レビュー指摘の誤エッジ）
check('タプル foreach の型付きループ変数はループ内だけ',
  sCount('calls', 'TupleForeach.Typed', 'Gadget.Handle') === 1
    && sCount('calls', 'TupleForeach.Typed', 'Widget.Handle') === 1,
  sScopeEdges('TupleForeach.Typed'));
check('タプル foreach の var ループ変数はループ後に見えない',
  sCount('calls', 'TupleForeach.Untyped', 'Widget.Handle') === 1
    && !sHas('calls', 'TupleForeach.Untyped', 'Gadget.Handle'),
  sScopeEdges('TupleForeach.Untyped'));
check('リストパターンの末尾 designation をフィールドに化かさない',
  !sHas('accesses', 'ListRest.Rest', 'Gadget.Length'), sScopeEdges('ListRest.Rest'));

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
