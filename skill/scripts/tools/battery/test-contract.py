# 検査の検査（第 55 ラウンド Astra 裁定 問 6）
#
# 「見張り番が増えた」だけでは検査は強くならない。第 54 ラウンドの双人レビューは
# **合格を出したまま中身が空**になる穴を 4 つ突いた（要求一覧の集合比較だけ・id 据え置きの
# 書き換え・0 行レポートを「1 通りに一致」と数える・壊れた JSON を読んで黙る）。
# それらを**実際に起こして**、検出されることを確かめる道具がここ。自分の検査が
# 期待どおりに失敗を拾えなかった日は終了 1 にするので、「検査を通った」が
# 「検査が働いた」を意味するようになる。
#
# やる事
#   * 負控制（**落ちなければならない**）: 0 行の report.mjs、要求一覧の条件を消す・
#     中身だけ書き換える（id は据え置き）・重複させる、fixture を 1 本増やす、
#     指紋台帳の登録を 1 件消す、期待値の件数を 1 件ずらす・2 件を入れ替える、
#     存在しない相対パス、JSON を書かない実行、出力先が既にある実行
#   * 正控制（**通らなければならない**）: 正当な 0 行レポート 4 本の実在、
#     条件別の期待値が一致している現状、リポジトリ根からでも `battery/` からでも同じ
#     結果になる相対パスの扱い
#
# 使い方: python3 skill/scripts/tools/battery/test-contract.py
#
# 第 56 ラウンド: 負控制は **2 度走らせる**。agy がやった破壊実験（クローンで個々の見張り番を
# 無効化して「制御がまだ落ちるか」を見る）を道具の中へ入れた。見張り番は `_inputs.py` 側で
# 名前を持っていて、環境変数 `CGD_GUARD_OFF=name,name`（または `IN.set_guard_off(...)`）で
# 1 個ずつ消せる。`negative(name, fn, guard=..., message=...)` は
#   1. 素の実行 → 落ちて `message`（その見張り番の案内）が出ること
#   2. `guard` を消した実行 → `message` が出ないこと。既定では**通る**ことも要求する
# を検査するので、対象の見張り番を消しても別の所で落ちるだけの**空振り制御**を通さない。
# 名前のスペルを間違えると 2 で同じ案内が出て失敗するので、名前表の管理は要らない。
import glob
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

import _inputs as IN

REPO = IN.repo_root()
HERE = IN.HERE
BATTERY = 'skill/scripts/tools/battery'
TMP = pathlib.Path(tempfile.mkdtemp(prefix='r55-contract-'))
# 触った追跡下のファイルは**読み直した bytes を戻す**（`git checkout` は人が意図して
# 直した物を消すので使わない）
ORIGINALS = {}
failed = []
ran = {'negative': 0, 'positive': 0}


def script_path(script):
    """道具の実体を `battery/` と `tools/` から探す。無いなら**制御の欠陥**として終わらせる

    第 55 ラウンド Codex P2: `check-battery-inputs.py` は `skill/scripts/tools/` に有るのに
    `battery/` から呼んでいた。python は終了 2（can't open file）を返し、`negative()` はそれを
    「検出できた」と数えた。中身の指紋検査が働かない日でも制御が通っていた"""
    for d in (HERE, HERE.parent):
        q = d / script
        if q.exists():
            return q
    raise NotDetected(f'制御が呼ぼうとした道具が見つからない: {script}'
                      f'（{HERE} と {HERE.parent} を見た。制御の書き直し）')


def py(script, *args, cwd=None):
    """道具を走らせて `(終了コード, 出力)` を返す（`| tail` で測ると `tail` の値になる）"""
    p = subprocess.run([sys.executable, str(script_path(script)), *[str(a) for a in args]],
                       cwd=str(cwd or REPO), capture_output=True, text=True)
    out = p.stdout + p.stderr
    if "can't open file" in out:
        raise NotDetected(f'道具を起動できなかった（制御が壊れている）: {script}\n{out[:200]}')
    return p.returncode, out


def node_stub(body, name='stub.mjs'):
    """report.mjs の代わりになる小さな mjs を作る（壊れた実装の再現用）"""
    p = TMP / name
    p.write_text(body, encoding='utf-8')
    return str(p)


EMPTY_STUB = node_stub("""
// どの欄にも行を入れない report.mjs（第 54 ラウンド agy 指摘 2 で通った物）
// `summary` の欄は本物の report.mjs と揃える。行だけ出ない正当な 0 行レポートの形なので、
// 見張り番を消した実行が「形の不足」で落ちない（`rows-zero` だけを測るための整え）
import fs from 'node:fs';
const argv = process.argv.slice(2);
const out = argv[argv.indexOf('--json') + 1];
fs.writeFileSync(out, JSON.stringify({
  summary: {graph: argv[argv.indexOf('--graph') + 1], rows: 0, hops: 8, wiringHops: 3,
            limit: 100000, startIds: [], expandedStarts: 0, secondOrder: 0,
            entryOut: 0, entryIn: 0},
  external: {in: [], out: []}, entries: {in: [], out: []}, artifacts: {in: [], out: []},
  sameApi: [], siblingEndpoints: [], wiring: [],
}));
""", 'empty.mjs')

SILENT_STUB = node_stub("""
// 終了 0 で何も JSON を書かない実行（「走らなかった」が「合格」にならないか）
const argv = process.argv.slice(2);
process.exit(0);
""", 'silent.mjs')


def stash(rel):
    """追跡下のファイルを改変する前に元 bytes を控える（最後に戻す）"""
    p = REPO / rel
    ORIGINALS.setdefault(rel, p.read_bytes())
    return p


def restore():
    for rel, data in ORIGINALS.items():
        (REPO / rel).write_bytes(data)
    ORIGINALS.clear()


TOUCHED = ['skill']  # 残骸は未追跡も含めて見える場所なら広く見る（`out` は gitignore 済み）


def git_touches():
    """この道具が触る追跡下のファイルの状態（変更前の基準と比べて残骸を確かめる）"""
    p = subprocess.run(['git', 'status', '--porcelain', '--', *TOUCHED],
                       cwd=str(REPO), capture_output=True, text=True)
    return [x for x in p.stdout.splitlines() if not x.split(' ')[-1].endswith('.pyc')]


def spec_copy():
    """要求一覧の**写し**を作る（本物を触らずに `validate_required_spec` を試す）"""
    return json.loads((HERE / 'required-checks.json').read_text(encoding='utf-8'))


class NotDetected(Exception):
    """制御自身が見つけた「検査が失敗を拾わなかった」事実（＝この道具の終了 1 の理由）"""


def _run_control(fn, tolerant=False):
    """制御を 1 回走らせて `(検出したか, 検出の文面)` に揃える

    `tolerant` は見張り番を消した側で使う。ここでは例外も「まだ落ちている」と数える
    （**何が落ちたか**の文面を見て、対象の見張り番が消えたかを判定するため）"""
    try:
        res = fn()
    except NotDetected as e:
        return False, str(e)
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        return (code != 0), f'exit {code}: {e}'
    except Exception as e:  # noqa: BLE001 - 見張り番を消した側は文面だけ拾う
        if not tolerant:
            raise
        return True, f'{type(e).__name__}: {e}'
    if isinstance(res, tuple) and res and isinstance(res[0], int):
        return (res[0] != 0), str(res[1])
    if res is True:
        return True, ''
    return False, str(res)


def _guards_off(names):
    """見張り番を消す（プロセス内の `IN` と、子プロセスが読む環境変数の両方）"""
    prev = (IN.GUARD_OFF, os.environ.get('CGD_GUARD_OFF'))
    IN.GUARD_OFF = frozenset(names)
    os.environ['CGD_GUARD_OFF'] = ','.join(names)
    return prev


def _guards_restore(state):
    prev_in, prev_env = state
    IN.GUARD_OFF = prev_in
    if prev_env is None:
        os.environ.pop('CGD_GUARD_OFF', None)
    else:
        os.environ['CGD_GUARD_OFF'] = prev_env


def negative(name, fn, guard=None, message=None, clean=True):
    """失敗しなければならない制御。**その見張り番が落ちたこと**まで確かめる

    第 55 ラウンド agy P1 の実測で、負控制の 3 件は「別の一の見張り番が先に落ちる」だけで
    合格していた（対象の見張り番を無効化しても制御がまだ落ちる＝その見張り番を測っていない
    空振り）。だからここで 2 度走らせる:

    1. **素の実行**: 落ちて、`message`（対象の見張り番の案内）が含まれること
    2. **`guard` を消した実行**: `message` が出ないこと。`clean`（既定）なら**通ること**も
       要求する（他の見張り番に遮われている間は、その制御は対象を測っていない）

    `clean=False` は「見張り番を消すと後が読めずに別の手前で落ちる」実行系の制御だけ
    （JSON を書かない、JSON が壊れている）。そこは `message` が出ないことを検出とみなす"""
    ran['negative'] += 1
    names = (guard,) if isinstance(guard, str) else tuple(guard or ())
    try:
        det, text = _run_control(fn)
    except NotDetected as e:
        failed.append(f'{name}: {e}')
        return
    except Exception as e:  # noqa: BLE001 - agy P2-1: 制御自身の壊れ方を黙らせない
        failed.append(f'{name}: 制御が壊れている（{type(e).__name__}: {e}）')
        return
    if not det:
        failed.append(f'{name}: 落ちずに通った（期待は終了 1）。{text[:160]}')
        return
    if message and message not in text:
        failed.append(f'{name}: 期待した見張り番「{message}」ではなく別の物で落ちた'
                      f'（空振り）: {text[:200]}')
        return
    if not names:
        return
    state = _guards_off(names)
    try:
        det2, text2 = _run_control(fn, tolerant=True)
    finally:
        _guards_restore(state)
    if message and message in text2:
        failed.append(f'{name}: 見張り番 {" / ".join(names)} を消したのに同じ案内が出た'
                      f'（この制御が見ているのは別物）: {text2[:160]}')
        return
    if clean and det2:
        failed.append(f'{name}: 見張り番 {" / ".join(names)} を消しても別の所で落ちる'
                      f'（他の見張り番に遮われて対象を測っていない）: {text2[:200]}')


def positive(name, fn):
    ran['positive'] += 1
    try:
        fn()
    except (NotDetected, SystemExit) as e:
        failed.append(f'{name}: 通らなければならないのに落ちた: {str(e)[:200]}')
    except Exception as e:  # noqa: BLE001 - 正控制は例外も失敗
        failed.append(f'{name}: 通らなければならないのに例外: {type(e).__name__}: {e}')


# ---------------------------------------------------------------- 中身を書き換えた要求一覧 --
def cond_graph_tampered():
    """要求一覧の `graph` を書き換えて id を据え置く（第 54 ラウンド Codex 指摘 2 の再現）"""
    spec = spec_copy()
    c = spec['conditions'][3]
    c['graph'] = 'skill/tests/fixtures/ImpactFacts/minimal.graph.json'
    IN.validate_required_spec(spec, REPO)


def cond_args_tampered():
    """`args` だけ変えて id を据え置く（同じ穴の別形）

    値域外の形にすると `cond-shape` が先に落ちるので、**形は正しいが別物**という書き換えに
    する（api 条件のエンドポイントパスを 1 文字変える）"""
    spec = spec_copy()
    hit = next((c for c in spec['conditions']
                if c['kind'] == 'api' and '--api' in c['args']), None)
    if hit is None:
        raise NotDetected('kind が api の条件が無い（この制御の前提が変わった）')
    args = list(hit['args'])
    i = args.index('--api')
    args[i + 1] = args[i + 1] + '2'
    hit['args'] = args
    IN.validate_required_spec(spec, REPO)


def cond_duplicated():
    """同じ起動内容を 2 件並べる（集合化すると黙って 1 件になる）"""
    spec = spec_copy()
    spec['conditions'].append(dict(spec['conditions'][3]))
    IN.validate_required_spec(spec, REPO)


def cond_id_duplicated():
    """id だけ重複させる（正準形は別。id の集合比較では 1 件に潰れる）"""
    spec = spec_copy()
    dup = dict(spec['conditions'][7])
    dup['graph'] = 'skill/tests/fixtures/ImpactFacts/other.graph.json'
    spec['conditions'].append(dup)
    IN.validate_required_spec(spec, REPO)


def cond_case_missing():
    """`case` を消す（219 とおりの起動内容では無い。`elsa-1` と `elsa-folder` が同一視される）"""
    spec = spec_copy()
    for c in spec['conditions']:
        c.pop('case', None)
    IN.validate_required_spec(spec, REPO)


def cond_bad_kind():
    """値域外の kind（実行できない条件を一覧に置かない）"""
    spec = spec_copy()
    spec['conditions'][0]['kind'] = 'frobnicate'
    IN.validate_required_spec(spec, REPO)


def expectations_totals_off():
    """合計を条件別の合計からずらす（合計は導出。手で書ける形にすると穴）"""
    spec = spec_copy()
    spec['expectations']['invariantRows']['total'] += 1
    IN.validate_required_spec(spec, REPO)


def expectations_empty():
    """条件別の内訳を空にする（`expectations: {}` でも通る形を作らない）"""
    spec = spec_copy()
    # 内訳だけを空にすると合計と条件数の見張り番が先に落ちる（agy P2）。**内訳専用の
    # 制御**にするため合計と条件数も 0 へ揃えて、`byCondition が空` だけで落ちるようにする
    e = spec['expectations']['invariantRows']
    e['byCondition'], e['total'], e['conditions'] = {}, 0, 0
    IN.validate_required_spec(spec, REPO)


def coverage_one_off():
    """条件別の件数を 1 件ずらす（入力はそのままで測る範囲が縮んだ日）"""
    by = spec_copy()['expectations']['invariantRows']['byCondition']
    got = dict(by)
    key = sorted(got)[0]
    got[key] = got[key] - 1
    IN.check_coverage('invariantRows', got, REPO)


def coverage_swapped():
    """2 件の件数を入れ替える（合計は同じ。合計だけの比較では通る）"""
    by = spec_copy()['expectations']['parentChild']['byCondition']
    # 同じ件数どうしの入れ替えは無意味（agy P2）。**件数の違う 2 件**を選ぶ
    keys = sorted(k for k, v in by.items() if v != 0)
    other = [k for k in keys if by[k] != by[keys[0]]]
    if not other:
        raise NotDetected('件数の違う 2 条件が見つからない（期待値が一様になった）')
    got = dict(by)
    got[keys[0]], got[other[0]] = by[other[0]], by[keys[0]]
    IN.check_coverage('parentChild', got, REPO)


def coverage_missing_condition():
    """1 条件を測っていない（合計が減るのは分かるが、どれが減ったかで見せる）"""
    by = spec_copy()['expectations']['invariantRows']['byCondition']
    got = dict(by)
    got.pop(sorted(got)[0])
    IN.check_coverage('invariantRows', got, REPO)


# ------------------------------------------------------------------------ 実行系の制御 --
def stub_via_cycle():
    return py('via-cycle.py', EMPTY_STUB)


def stub_allperm():
    return py('allperm.py', EMPTY_STUB, f'{BATTERY}/min-0.json')


def stub_allperm_corr():
    return py('allperm-corr.py', EMPTY_STUB, f'{BATTERY}/min-0.json')


def stub_r43_permute():
    return py('r43-permute.py', EMPTY_STUB)


def allperm_one_edge_graph():
    """縁が 1 本だけのグラフで allperm.py（並び替えが 1 とおりしか無く空振りになる）"""
    victim = TMP / 'one-edge.json'
    # 起点を渡して**行が出る**状態にする。行が 0 件のままだと `rows-zero` が先に落ちて、
    # 縁の本数の見張り番をこの制御は見ていなかった（第 55 ラウンド agy P1-2）
    victim.write_text(json.dumps({'extra': ['--from', 'a'], 'graph': {
        'nodes': [{'id': 'a', 'kind': 'type', 'name': 'a'}, {'id': 'b', 'kind': 'type', 'name': 'b'}],
        'edges': [{'id': 'e0', 'source': 'a', 'target': 'b', 'kind': 'references'}]}},
        ensure_ascii=False), encoding='utf-8')
    return py('allperm.py', str(REPO / 'skill/scripts/report.mjs'), str(victim))


def allperm_wrong_expected_permutations():
    """期待する縁順の通り数をわざと違う数で渡す（min-0.json は 6 縁 = 720 通り）"""
    return py('allperm.py', str(REPO / 'skill/scripts/report.mjs'),
              str(REPO / BATTERY / 'min-0.json'), '999')


def allperm_row_missing_field():
    """6 欄の形をしていても突き合わせる欄（`switches`）が消えたら終わる"""
    stub = node_stub("""
// 行を出すが高さの欄を忘れた report.mjs（出力契約が変わった日の再現）
import fs from 'node:fs';
const argv = process.argv.slice(2);
const out = argv[argv.indexOf('--json') + 1];
fs.writeFileSync(out, JSON.stringify({
  summary: {rows: 1},
  external: {in: [{id: 'x', bucket: 'external', direction: 'in', hops: 1}], out: []},
  entries: {in: [], out: []}, artifacts: {in: [], out: []},
  sameApi: [], siblingEndpoints: [], wiring: [],
}));
""", 'no-switches.mjs')
    return py('allperm.py', str(stub), str(REPO / BATTERY / 'min-0.json'))


def edge_order_no_edges():
    """実グラフの縁を全部抜いて `edge-order.py` を走らせる（4 本の起動すべてが 0 群）"""
    src = json.loads((REPO / 'out/demo/graph.json').read_text(encoding='utf-8'))
    src['edges'] = []
    victim = TMP / 'demo-no-edges.json'
    victim.write_text(json.dumps(src, ensure_ascii=False), encoding='utf-8')
    return py('edge-order.py', str(victim))


def dir_rule_all_empty_reports():
    """18 本とも 0 行のレポートディレクトリ（比較が 1 件も起きないのに合否を出さない）"""
    d = TMP / 'all-empty'
    if d.exists():
        shutil.rmtree(d)
    d.mkdir()
    argv = ['--graph', 'out/demo/graph.json', '--hops', '8', '--wiring-hops', '3',
            '--limit', '100000']
    for p in sorted((HERE / 'baseline-v1').glob('*.json')):
        subprocess.run(['node', EMPTY_STUB, *argv, '--json', str(d / p.name)],
                       cwd=str(REPO), capture_output=True, text=True, check=True)
    return py('check-dir-rule.py', '--profile', 'current', str(d))


def dir_rule_wrong_reports():
    """`byReport` の按分だけ入れ替えた期待値一覧（向き別の合計は同じまま。agy P2 の指摘どおり
    レポートを壊す制御では向き別の見張り番が先に落ちるので、**一覧側**を触る）"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    by = doc['expectations']['dirRule']['current']['byReport']
    a, b = sorted(by)[:2]
    if by[a] == by[b]:
        raise NotDetected('入れ替える 2 本の比較件数が同じ（按分の制御が空振りになる）')
    by[a], by[b] = by[b], by[a]
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        return py('check-dir-rule.py', '--profile', 'current', 'out/audit-current')
    finally:
        restore()


def dir_rule_broken_rows():
    """18 本そろえたうえで 1 本だけ行を消す（向き別の件数とレポート別が同時にずれる）"""
    src = TMP / 'dir-rule'
    if src.exists():
        shutil.rmtree(src)
    src.mkdir()
    # 18 本そろえたうえで 1 本だけ行を消す → `byReport` の期待値と食い違って終わる
    for p in sorted((HERE / 'baseline-v1').glob('*.json')):
        shutil.copy(p, src / p.name)
    victim = src / 'demo-api.json'
    doc = json.loads(victim.read_text(encoding='utf-8'))
    doc['artifacts']['out'] = []
    doc['external']['in'] = []
    doc['entries']['out'] = []
    victim.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return py('check-dir-rule.py', '--profile', 'v1', str(src))


SEQ = [0]


def tmp_out(name):
    """制御の出力先を実行ごとに新しい名前にする

    見張り番を消した 2 度目の実行が同じファイルを使うと `out-exists` が先に落ちて、
    対象の見張り番を確かめられない（`run_json` は出力先が有る日を止める）"""
    SEQ[0] += 1
    return str(TMP / f'{name}-{SEQ[0]}.json')


def run_json_silent():
    """終了 0 で JSON を書かない実行（走らなかった日を合格にしない）"""
    IN.run_json(SILENT_STUB, ['--graph', 'x'], tmp_out('nope'), REPO, label='制御')


def run_json_stale_output():
    """出力先がもう有る実行（前の実行の JSON を今回の結果と読まない）

    前回の中身は**正当なレポート**にしておく。無効な JSON を置くと `out-exists` を消しても
    形検査が落ちて、どちらの見張り番で落ちるか分からなくなる（第 55 ラウンド agy P1-1）"""
    old = TMP / 'stale.json'
    old.write_text((HERE / 'baseline-v1' / 'demo-api.json').read_text(encoding='utf-8'),
                   encoding='utf-8')
    IN.run_json(SILENT_STUB, [], str(old), REPO, label='制御')


def run_json_broken_json():
    """JSON が壊れていない実行を用意して、読む側が止まることを確かめる"""
    bad = TMP / 'broken.mjs'
    bad.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1], '{"summary": {"graph"');
""", encoding='utf-8')
    IN.run_json(str(bad), [], tmp_out('broken'), REPO, label='制御')


def run_json_wrong_shape():
    """欄の無い JSON（別の道具の出力）をレポートとして数えない"""
    odd = TMP / 'odd.mjs'
    odd.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1],
  JSON.stringify({summary: {graph: 'x'}, rows: []}));
""", encoding='utf-8')
    IN.run_json(str(odd), [], tmp_out('odd'), REPO, label='制御')


def bad_relative_path():
    """`battery/` から渡した `out/audit-current` を**リポジトリ根で補わない**こと

    第 55 ラウンド agy P1-3: どの cwd からも存在しないパスを渡すと、根から補る古い挙動に
    戻しても同じ結果になり、制御が穴を検出できなかった。ここは**根からなら実在する**相対
    パスを `battery/` から渡す（今の挙動なら終了 1、根へ倒れたら終了 0）"""
    return py('check-dir-rule.py', '--profile', 'current', 'out/audit-current', cwd=HERE)


def fingerprint_entry_removed():
    """指紋台帳の登録を 1 件消す（新しい入力が増えた日に黙って通らない）"""
    rel = 'skill/scripts/tools/battery/input-fingerprints.json'
    p = stash(rel)
    data = json.loads(p.read_text(encoding='utf-8'))
    victim = sorted(data[IN.CONTENTS])[0]
    data[IN.CONTENTS].pop(victim)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    bad = IN.require_fingerprints(REPO)
    restore()
    return (0 if not bad else 1), '\n'.join(bad)


FIXTURE = 'skill/tests/fixtures/ImpactFacts/arrow-priority.graph.json'


def fixture_edges_emptied():
    """fixture の縁を全部空にする（第 54 ラウンド Codex 指摘 1 そのもの）

    縁を消すと**バイト数も変わる**ので中身の指紋だけが働く制御ではない（agy P2）。
    バイト数が変わらない別制御を次に置く"""
    p = stash(FIXTURE)
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc['edges'] = []
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    try:
        return py('check-battery-inputs.py')
    finally:
        restore()


def fixture_renamed_same_length():
    """ノード id を**同じ長さのまま**書き換える（中身の指紋だけが働く日。agy P2 の提案）

    バイト数は 1 も変わらない。縁を空にする制御と違い、長さの変化では気づけない"""
    p = stash(FIXTURE)
    raw = p.read_text(encoding='utf-8')
    doc = json.loads(raw)
    ids = [x['id'] for x in doc['nodes']]
    victim = next((i for i in ids if len(i) >= 5 and i[-1] != i[-2]), None)
    if not victim:
        raise NotDetected('長さを変えずに書き換えられるノード id が無い')
    twin = victim[:-2] + victim[-1] + victim[-2]
    if twin in ids:
        raise NotDetected('書き換え後の id が既に有って制御が成立しない')
    swapped = raw.replace('"' + victim + '"', '"' + twin + '"')
    if len(swapped.encode('utf-8')) != len(raw.encode('utf-8')):
        raise NotDetected('書き換えで長さが変わった（バイト数の見張り番も反応する）')
    p.write_text(swapped, encoding='utf-8')
    try:
        return py('check-battery-inputs.py')
    finally:
        restore()


def fixture_added():
    """fixture を 1 本増やす（要求一覧に無い入力はある、という日）"""
    victim = TMP / 'contract-extra.graph.json'
    src = REPO / 'skill/tests/fixtures/ImpactFacts/arrow-priority.graph.json'
    shutil.copy(src, victim)
    dest = REPO / 'skill/tests/fixtures/ImpactFacts/zz-contract-extra.graph.json'
    shutil.copy(victim, dest)
    try:
        try:
            IN.launch_conditions(REPO)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            return code, f'exit {code}: {e}'
        return 0, 'fixture を 1 本増やしても要求一覧との比較が通った'
    finally:
        dest.unlink(missing_ok=True)


def condition_removed_from_ledger():
    """要求一覧から条件を 1 件消す（今回走るのは 219 件のまま）"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    removed = doc['conditions'].pop(5)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        try:
            IN.launch_conditions(REPO)
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
            return code, f'exit {code}: {e}'
        return 0, ('要求一覧から条件を消しても通った（要求に無いのに走る日）: '
                   + str(removed.get('case')))
    finally:
        restore()


# -------------------------------------------------------------------------- 正控制 --
def legit_empty_reports():
    """正当な 0 行レポート 4 本は形として通る（一律「0 行は違反」にしない。Astra 裁定 問 4）"""
    legit = ['demo-readme.json', 'elsa-1.json', 'elsa-folder.json', 'real-tf.json']
    for name in legit:
        doc = json.loads((HERE / 'baseline-v1' / name).read_text(encoding='utf-8'))
        IN.validate_report(doc, f'制御 {name}')
        if doc['summary']['rows'] != 0:
            failed.append(f'{name} は 0 行では無くなった（正控制の前提が変わった）')
    return legit


def coverage_current_matches():
    """期待値の内訳が実在する（条件別の合計と内訳が自分で自分に一致している）"""
    exp = IN.expectations(REPO)['invariantRows']
    if exp['total'] != sum(exp['byCondition'].values()):
        failed.append('期待値の合計が条件別の合計と違う（一覧が壊れている）')


def relative_paths_from_both_cwds():
    """リポジトリ根からでも `battery/` からでも同じ結果になる（Astra 裁定 問 5）"""
    rc_root, _ = py('check-dir-rule.py', '--profile', 'current', 'out/audit-current')
    rc_here, _ = py('check-dir-rule.py', '--profile', 'current',
                    '../../../../out/audit-current', cwd=HERE)
    if rc_root != 0 or rc_here != 0:
        failed.append(f'相対パスのプロファイル実行が通らない（根 {rc_root} / battery {rc_here}）')


def ledger_self_valid():
    """今追跡下の一覧は自分の形を検査して通る"""
    IN.validate_required_spec(IN.required_spec(REPO), REPO)


def fingerprint_ledger_clean():
    """入力点検が通る（指紋の登録漏れが無い）"""
    bad = IN.require_fingerprints(REPO)
    if bad:
        failed.append(f'入力点検が {len(bad)} 件の食い違いを報告: {bad[0][:120]}')


def input_check_tool_runs():
    """入力点検が**道具として**起動して通る（第 55 ラウンド Codex P2 の再発防止）

    制御が存在しないパスを走らせると python は終了 2 を返す。負控制側はその 2 を
    「検出」と数えてしまうので、**通るはずの実行が実際に 0 であること**を正控制で見る"""
    rc, out = py('check-battery-inputs.py')
    if rc != 0:
        failed.append(f'check-battery-inputs.py が終了 {rc} で通らない: {out[:200]}')


def main():
    print(f'# 検査の検査（一時作業: {TMP}）')
    baseline = git_touches()
    try:
        # 第 56 ラウンド: 各制御に `guard`（消す見張り番）と `message`（その見張り番の案内）を
        # 書く。無効化しても別の所で落ちる制御は「空振り」として失敗する（agy P1）
        negative('要求一覧の graph を書き換えて id を据え置く', cond_graph_tampered,
                 guard='canonical-id', message='id が中身から再計算できない')
        negative('要求一覧の args だけ書き換えて id を据え置く', cond_args_tampered,
                 guard='canonical-id', message='id が中身から再計算できない')
        negative('要求一覧に同じ起動内容を 2 件並べる', cond_duplicated,
                 guard=('dup-condition', 'dup-id'), message='起動条件の正準形が重複')
        negative('要求一覧に id だけを重複させる', cond_id_duplicated,
                 guard=('dup-id', 'canonical-id'), message='id が重複')
        negative('要求一覧から case を消す', cond_case_missing,
                 guard=('cond-shape', 'canonical-id', 'dup-condition', 'dup-id'),
                 message='の欄が期待と違う')
        negative('要求一覧に値域外の kind を置く', cond_bad_kind,
                 guard=('cond-shape', 'canonical-id'), message='kind が値域外')
        negative('期待値の合計を条件別の合計からずらす', expectations_totals_off,
                 guard='cov-shape', message='total が条件別の合計と違う')
        negative('期待値の条件別の内訳を空にする', expectations_empty,
                 guard='cov-shape', message='byCondition が空')
        negative('走査した行数を 1 件ずらす', coverage_one_off,
                 guard='coverage', message='が期待値と違う')
        negative('突き合わせた親子数を件数の違う 2 件で入れ替える', coverage_swapped,
                 guard='coverage', message='が期待値と違う')
        negative('1 条件を測らない', coverage_missing_condition,
                 guard='coverage', message='が期待値と違う')
        negative('0 行の report.mjs で via-cycle.py', stub_via_cycle,
                 guard='rows-zero', message='比較する行が無い')
        negative('0 行の report.mjs で allperm.py', stub_allperm,
                 guard='rows-zero', message='比較する行が無い')
        negative('0 行の report.mjs で allperm-corr.py', stub_allperm_corr,
                 guard='rows-zero', message='比較する行が無い')
        negative('0 行の report.mjs で r43-permute.py', stub_r43_permute,
                 guard='rows-zero', message='比較する行が無い')
        negative('縁が 1 本だけのグラフで allperm.py', allperm_one_edge_graph,
                 guard='perm-edges', message='しかないグラフでは縁順を変えても比較に')
        negative('allperm.py に期待縁順の通り数違いを渡す', allperm_wrong_expected_permutations,
                 guard='perm-count', message='期待した縁順の通り数')
        negative('allperm.py の行から突き合わせる欄が消える', allperm_row_missing_field,
                 guard='proj-fields', message='行に欄が無い', clean=False)
        negative('実グラフの縁を全部抜いて edge-order.py', edge_order_no_edges,
                 guard='edge-order-groups', message='すべて群が 0 件')
        negative('18 本とも 0 行のレポートで check-dir-rule.py --profile current',
                 dir_rule_all_empty_reports,
                 guard=('dir-rule-counters', 'dir-rule-report'), message='一致: 期待')
        negative('向き別の合計は同じまま byReport の按分だけ入れ替えた一覧',
                 dir_rule_wrong_reports,
                 guard='dir-rule-report', message='の比較件数（レポート別）')
        negative('18 本そろえたうえで 1 本だけ行を消す（v1 プロファイル）',
                 dir_rule_broken_rows,
                 guard=('dir-rule-counters', 'dir-rule-report', 'dir-rule-v1'),
                 message='の比較件数（レポート別）')
        negative('終了 0 で JSON を書かない実行', run_json_silent,
                 guard='json-missing', message='終了 0 なのに JSON を書いていない', clean=False)
        negative('出力先が既にある実行', run_json_stale_output,
                 guard='out-exists', message='出力先がもう有る')
        negative('壊れた JSON を読む実行', run_json_broken_json,
                 guard='json-parse', message='JSON が読めない', clean=False)
        negative('欄の無い JSON をレポートとして読む実行', run_json_wrong_shape,
                 guard='report-shape', message='にレポートの欄が揃っていない')
        negative('battery/ から渡した根からなら実在する相対パスを補わない', bad_relative_path,
                 guard='path-cwd-only', message='ディレクトリが無い')
        negative('指紋台帳の登録を 1 件消す', fingerprint_entry_removed,
                 guard='fp-unregistered', message='が指紋台帳に未登録')
        negative('fixture の縁を全部空にする', fixture_edges_emptied,
                 guard=('fp-sha', 'fp-bytes'), message='中身が基準と違う')
        negative('fixture のノード id を同じ長さで書き換える', fixture_renamed_same_length,
                 guard='fp-sha', message='中身が基準と違う')
        negative('fixture を 1 本増やす', fixture_added,
                 guard=('fixture-set', 'condition-set'), message='fixture が有るのに要求一覧に無い')
        negative('要求一覧から条件を 1 件消す', condition_removed_from_ledger,
                 guard='condition-set', message='起動条件が要求一覧')

        positive('正当な 0 行レポート 4 本は形として通る', legit_empty_reports)
        positive('期待値の合計が条件別の合計と導出で一致', coverage_current_matches)
        positive('リポジトリ根と battery/ の両方から同じ相対パス', relative_paths_from_both_cwds)
        positive('追跡下の一覧が自分の形を検査して通る', ledger_self_valid)
        positive('指紋台帳と入力が揃っている', fingerprint_ledger_clean)
        positive('入力点検の道具が実際に起動して終了 0 で通る', input_check_tool_runs)

        # 追跡下のファイルへの変更が残っていないか（制御が途中で落ちても戻す）
        left = git_touches()
        if left != baseline:
            failed.append('制御のあとにこの道具が触った物が変わったまま残った: '
                          + ' / '.join(sorted(set(left) ^ set(baseline))[:6]))
    finally:
        restore()
        shutil.rmtree(TMP, ignore_errors=True)

    print(f'負控制 {ran["negative"]} 件（見張り番を消した再実行つき）・'
          f'正控制 {ran["positive"]} 件を走らせた')
    if failed:
        print(f'検出できなかった失敗 / 通らなかった正控制 {len(failed)} 件:', file=sys.stderr)
        for f in failed:
            print(f'  x {f}', file=sys.stderr)
        raise SystemExit(1)
    print('期待した失敗はすべて検出し、通るべき物は通った（検査が実際に働いている）')


if __name__ == '__main__':
    # 終了時にも残骸を掃除する（`fixture を 1 本増やす` は本物のディレクトリに書く）
    try:
        main()
    finally:
        for p in glob.glob(str(REPO / 'skill/tests/fixtures/ImpactFacts/zz-contract-extra*')):
            pathlib.Path(p).unlink(missing_ok=True)
