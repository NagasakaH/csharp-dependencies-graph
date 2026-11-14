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

// ---- TypeResolution フィクスチャ: 型名の誤バインド（同名 BCL / 到達性 / global using）----
const t = analyze('TypeResolution');
const tEdges = t.edges.filter((e) => e.kind !== 'contains');
const tHas = (kind, from, to) => tEdges.some((e) => e.kind === kind && e.source === `member:${from}` && e.target === `type:${to}`);
const tTo = (to) => tEdges.filter((e) => e.target === `type:${to}`);
const uiDict = 'Fixtures.TypeResolution.Ui.Dictionary';
const sharedBox = 'Fixtures.TypeResolution.Shared.Box';
const farLease = 'Fixtures.TypeResolution.Far.Lease';

// 型引数の数が違う候補は張らない（`Dictionary<string, int>` を非ジェネリックの同名クラスに化かさない）
check('型引数の数が合わないと同名クラスに結ばない', tTo(uiDict).filter((e) => e.source.includes('.Core.')).length === 0,
  JSON.stringify(tTo(uiDict).map((e) => `${e.kind}:${e.source}`)));
check('BCL 側の Dictionary 利用は拒否として .cs ノードに残す',
  (t.nodes.find((n) => n.id === 'file:Core.cs' || (n.path || '') === 'Core.cs')?.metadata?.rejectedTypes || []).includes('Dictionary'),
  JSON.stringify(t.nodes.filter((n) => n.metadata?.rejectedTypes).map((n) => [n.id, n.metadata.rejectedTypes])));

// 到達性のゲート: 候補が 1 件でも、名前空間がどこからも見えないなら張らない
check('using も global using も無い同名候補は張らない', tTo(farLease).length === 0,
  JSON.stringify(tTo(farLease).map((e) => `${e.kind}:${e.source}`)));

// 対照: 届いているケースは必ず結ぶ（ゲートの過剰適用にしない）
check('using で届き型引数の数が合えば結ぶ', tHas('creates', 'Fixtures.TypeResolution.Explicit.BoxUser.Make', sharedBox)
  || tHas('references', 'Fixtures.TypeResolution.Explicit.BoxUser.Make', sharedBox));
check('global using だけで届いている型も結ぶ', tHas('creates', 'Fixtures.TypeResolution.Core.GlobalBoxUser.Make', sharedBox)
  || tHas('references', 'Fixtures.TypeResolution.Core.GlobalBoxUser.Make', sharedBox));
check('同じ名前空間の非ジェネリック型は従来どおり結ぶ', tHas('creates', 'Fixtures.TypeResolution.Ui.PanelHost.Make', 'Fixtures.TypeResolution.Ui.Panel')
  || tHas('references', 'Fixtures.TypeResolution.Ui.PanelHost.Make', 'Fixtures.TypeResolution.Ui.Panel'));

// ---- BindingRegression フィクスチャ: 前ラウンドレビューで出た過剰除去の再発防止 ----
const b = analyze('BindingRegression');
const bEdges = b.edges.filter((e) => e.kind !== 'contains');
const bHas = (kind, sourceStart, target) => bEdges.some(
  (e) => e.kind === kind && e.source.startsWith(sourceStart) && e.target === target);
const bTo = (target) => bEdges.filter((e) => e.target === target);
const bFile = (relPath) => b.nodes.find((n) => n.kind === 'file' && (n.path || '').endsWith(relPath));
const bRejected = (relPath) => (bFile(relPath)?.metadata?.rejectedTypes) || [];

// 同じノード ID に畳まれた別アリティ（`Activity` と `Activity<T>`）は受けつける
check('同名で型パラメータ数の違う基底型を結ぶ（内側名前空間・using 無し）',
  bHas('inherits', 'type:Fix.Regress.Core.Activities.Dispatch', 'type:Fix.Regress.Core.Activity')
  && bHas('inherits', 'type:Fix.Regress.Core.Activities.If', 'type:Fix.Regress.Core.Activity'),
  JSON.stringify(bTo('type:Fix.Regress.Core.Activity').map((e) => `${e.kind}:${e.source}`)));
check('型引数付きの利用が同名非ジェネリック宣言へ化けない（確定解決の経路でも型引数を見る）',
  bTo('type:Fix.Regress.Ui.Dictionary').length === 0 && bRejected('Ui.cs').includes('Dictionary'),
  JSON.stringify({ edges: bTo('type:Fix.Regress.Ui.Dictionary').map((e) => e.source), rejected: bRejected('Ui.cs') }));

// 戻り値型は「宣言元の using」で解決する（呼び出し元が import している必要はない）
const itemId = 'member:Fix.Regress.Models.Item.Id';
const moduleConfigure = 'member:Fix.Regress.Core.IModule.Configure';
check('プロパティの戻り値を挟んだ多段アクセス（呼び出し側は using 無し）',
  bHas('accesses', 'member:Fix.Regress.Handlers.Worker.FromParam', itemId),
  JSON.stringify(bEdges.filter((e) => e.source.includes('FromParam')).map((e) => `${e.kind}:${e.target}`)));
check('ローカル変数の連鎖も宣言元で解決', bHas('accesses', 'member:Fix.Regress.Handlers.Worker.FromLocal', itemId));
check('メソッドの戻り値を挟んだ連鎖も宣言元で解決',
  bHas('accesses', 'member:Fix.Regress.Handlers.Worker.FromCall', itemId)
  && bHas('calls', 'member:Fix.Regress.Handlers.Worker.FromCall', 'member:Fix.Regress.Services.Runner.Make'));
check('戻り値がインターフェースのメソッド呼び出し（IModule.Configure）',
  bHas('calls', 'member:Fix.Regress.Handlers.Worker.Configure', moduleConfigure),
  JSON.stringify(bEdges.filter((e) => e.source.includes('Configure')).map((e) => `${e.kind}:${e.target}`)));

// 戻り値型を `var` で一度受けても、宣言元の文脈を保つ（レビューで出た過剰除去）
for (const who of ['VarFromCall', 'VarFromProperty', 'VarInForEach', 'VarFromIndexer']) {
  check(`var で受けた戻り値の先（${who}）も宣言元で解決`,
    bHas('accesses', `member:Fix.Regress.Handlers.Worker.${who}`, itemId),
    JSON.stringify(bEdges.filter((e) => e.source.endsWith(who)).map((e) => `${e.kind}:${e.target}`)));
}

// 型引数の数が違う候補は飛ばして、届く候補まで探索を続ける（C# の探索順に合わせる）
check('型引数付きの利用が同名非ジェネリックで止まらず、using 先のジェネリックへ進む',
  bHas('references', 'member:Fix.Regress.Handlers.Worker.ArityFromParam', 'type:Fix.Regress.Boxes.Box')
  && bHas('calls', 'member:Fix.Regress.Handlers.Worker.ArityFromParam', 'member:Fix.Regress.Boxes.Box.Go')
  && bHas('accesses', 'member:Fix.Regress.Handlers.Worker.ArityFromParam', 'member:Fix.Regress.Boxes.Box.Value')
  && !bHas('references', 'member:Fix.Regress.Handlers.Worker.ArityFromParam', 'type:Fix.Regress.Handlers.Box'),
  JSON.stringify(bEdges.filter((e) => e.source.endsWith('ArityFromParam')).map((e) => `${e.kind}:${e.target}`)));
check('型引数を書かない利用は同じ名前空間の非ジェネリックに決まる',
  bHas('calls', 'member:Fix.Regress.Handlers.Worker.Go', 'member:Fix.Regress.Handlers.Box.Identity'),
  JSON.stringify(bEdges.filter((e) => e.source.endsWith('Worker.Go')).map((e) => `${e.kind}:${e.target}`)));

// グローバル名前空間の型とそのネスト型は、同じファイルから見える
check('グローバル名前空間のネスト型を到達不能にしない',
  bHas('creates', 'member:Entry.Run', 'type:Entry/Inner')
  && bHas('calls', 'member:Entry.Run', 'member:Entry/Inner.Go')
  && bHas('references', 'member:Entry.Run', 'type:Entry/BridgeRejectedException'),
  JSON.stringify(bEdges.filter((e) => e.source === 'member:Entry.Run').map((e) => `${e.kind}:${e.target}`)));

// 名前空間直下に型があれば単純名は単独決定する（同名のネスト型へ張り分けない）
check('名前空間直下の型が単純名で決まったときは張り分けない',
  bHas('creates', 'member:Fix.Regress.Ambiguous.ProbeUser.Make', 'type:Fix.Regress.Ambiguous.Probe')
  && !bEdges.some((e) => e.source === 'member:Fix.Regress.Ambiguous.ProbeUser.Make'
    && e.target !== 'type:Fix.Regress.Ambiguous.Probe'),
  JSON.stringify(bEdges.filter((e) => e.source.includes('ProbeUser')).map((e) => `${e.kind}:${e.target}`)));

// ---- 型引数を畳んだせいで別物の同名型へ化けないか（第 11 ラウンドの P1） ----
// 第 10 ラウンドで「畳む前の表記を優先する」ときに漏れたのは、式の途中を解決する経路と
// foreach の要素宣言だった。式の一部は正しいジェネリック型に繋がり、その先だけ
// 別物の非ジェネリック型に化けるので、経路ごとに検査する
const c = analyze('GenericChain');
const cEdges = c.edges.filter((e) => e.kind !== 'contains');
const cHas = (kind, from, to) => cEdges.some((e) => e.kind === kind && e.source === from && e.target === to);
const consumer = (n) => `member:Fix.Chain.App.Consumer.${n}`;
const cOf = (who) => cEdges.filter((e) => e.source === consumer(who)).map((e) => `${e.kind}:${e.target}`);
const realItemId = 'member:Fix.Chain.Models.RealItem.Id';
const wrongItemId = 'member:Fix.Chain.Wrong.WrongItem.Id';
const modelsBoxGo = 'member:Fix.Chain.Models.Box.Go';
const wrongBoxGo = 'member:Fix.Chain.Wrong.Box.Go';

for (const who of ['ForeachImmediate', 'ForeachDeferred', 'ViaIndexer', 'ForEachParam']) {
  check(`要素型の経路（${who}）は型引数を保った宣言元で解決する`,
    cHas('calls', consumer(who), modelsBoxGo) && !cHas('calls', consumer(who), wrongBoxGo), JSON.stringify(cOf(who)));
}
for (const who of ['ChainCall', 'ChainProperty', 'VarCallChain']) {
  check(`式の連鎖（${who}）は型引数を畳まず要素型のメンバーへ張る`,
    cHas('accesses', consumer(who), realItemId) && !cHas('accesses', consumer(who), wrongItemId), JSON.stringify(cOf(who)));
}
check('Consumer から化ける側（Fix.Chain.Wrong）には一切辿らない',
  !cEdges.some((e) => e.source.startsWith(consumer('').slice(0, -1)) && e.target.includes('Fix.Chain.Wrong.')),
  JSON.stringify(cEdges.filter((e) => e.target.includes('Fix.Chain.Wrong.')).map((e) => `${e.source}->${e.target}`)));

// ---- タプルを型引数に受けた連鎖（型引数の数を構文どおり数えるか） ----
// 型引数の数を `<` と `,` だけで数えると `Box<(int, string)>` のカンマを型引数の区切りと数えて
// 1 引数の `Box<T>` を 2 引数として拒否し、その先へ張るべき連鎖ごと消える（第 12 ラウンドの再現）
const targ = analyze('TupleArg');
const targEdges = targ.edges.filter((e) => e.kind !== 'contains');
const targHas = (kind, from, to) => targEdges.some((e) => e.kind === kind && e.source === from && e.target === to);
const tupConsumer = (n) => `member:Fix.TupleArg.Models.Consumer.${n}`;
const tupOf = (who) => targEdges.filter((e) => e.source === tupConsumer(who)).map((e) => `${e.kind}:${e.target}`);
const tupleItemId = 'member:Fix.TupleArg.Models.Item.Id';
const tupleBoxMake = 'member:Fix.TupleArg.Models.Box.MakeItem';

for (const who of ['ChainProperty', 'ChainCall', 'ThroughDictionary', 'ThroughForEach', 'ViaVar']) {
  check(`タプル型引数の連鎖（${who}）は要素型のメンバーへ張る`,
    targHas('accesses', tupConsumer(who), tupleItemId), JSON.stringify(tupOf(who)));
}
check('タプル型引数の呼び出し（ChainCall / ThroughForEach）は Box<T> の MakeItem に張る',
  targHas('calls', tupConsumer('ChainCall'), tupleBoxMake) && targHas('calls', tupConsumer('ThroughForEach'), tupleBoxMake),
  JSON.stringify([...tupOf('ChainCall'), ...tupOf('ThroughForEach')]));
check('型引数が 2 つの宣言にタプルを渡しても個数を誤らない（Pair<(int, int), string>）',
  targHas('calls', tupConsumer('TwoArgs'), 'member:Fix.TupleArg.Models.Provider.TwoArgs')
  && targHas('accesses', tupConsumer('TwoArgs'), 'member:Fix.TupleArg.Models.Pair.Key'),
  JSON.stringify(tupOf('TwoArgs')));
check('フィールド宣言の型がタプル型引数でも同じ解決になる（Provider.FromField）',
  targHas('calls', 'member:Fix.TupleArg.Models.Provider.FromField', tupleBoxMake),
  JSON.stringify(targEdges.filter((e) => e.source.endsWith('Provider.FromField')).map((e) => `${e.kind}:${e.target}`)));
check('Consumer から化ける側（Fix.TupleArg.Wrong）には一切辿らない',
  !targEdges.some((e) => e.target.includes('Fix.TupleArg.Wrong.')),
  JSON.stringify(targEdges.filter((e) => e.target.includes('Fix.TupleArg.Wrong.')).map((e) => `${e.source}->${e.target}`)));

// ---- 決定性: 同じ入力を 2 回走らせてもノード・エッジ・後付け候補が揺れない ----
// 生成日時だけをのぞいた**バイト列そのもの**を比べる。並列走りの結果を後から並べ替えると
// 集合は同じでも出力順が揺れるので、「ソートしてから比較」では見逃してしまう
function runTwice(root) {
  const outs = [1, 2].map((i) => {
    const out = join(dir, `twice-${i}.json`);
    const proc = spawnSync(cgd, ['--root', root, '--out', out, '--quiet'], { encoding: 'utf8' });
    if (proc.status !== 0) { console.error(proc.stdout + proc.stderr); process.exit(1); }
    return readFileSync(out, 'utf8').replace(/"generatedAt":\s*"[^"]*"/g, '"generatedAt":""');
  });
  return outs[0] === outs[1];
}
check('同じ入力を 2 回実行して rejectedTypes を含む出力が揺れない',
  runTwice(resolve(HERE, '..', '..', 'demo', 'orders-api-lambda'))
  && runTwice(join(HERE, '..', 'tests', 'fixtures', 'BindingRegression')));

// partial 型の別ファイルにある同名オーバーロードは同じ edge ID に畳まれるため、代表の行・detail を
// 先着順に選ぶと並列走りの順でファイルのバイト列が変わる。多数回まわして固定できているか見る
function runManyTimes(root, times) {
  const seen = new Set();
  for (let i = 0; i < times; i++) {
    if (!runTwiceAt(root, join(dir, `many-${i}.json`))) return false;
    seen.add(readFileSync(join(dir, `many-${i}.json`), 'utf8').replace(/"generatedAt":\s*"[^"]*"/g, '"generatedAt":""'));
  }
  return seen.size === 1;
}
function runTwiceAt(root, out) {
  const proc = spawnSync(cgd, ['--root', root, '--out', out, '--quiet'], { encoding: 'utf8' });
  if (proc.status !== 0) { console.error(proc.stdout + proc.stderr); process.exit(1); }
  return true;
}
check('partial の別ファイルで同じ edge ID になっても 12 回とも同じバイト列',
  runManyTimes(join(HERE, '..', 'tests', 'fixtures', 'PartialOrder'), 12));

const poEdges = analyze('PartialOrder').edges.filter((e) => e.kind === 'calls' && e.target === 'member:Fix.Partial.Target.Go');
check('同じ edge ID に別ファイルの行が届いても代表は行が若い側で固定される',
  poEdges.length === 1 && poEdges[0].line === 7 && poEdges[0].count === 2, JSON.stringify(poEdges));

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
