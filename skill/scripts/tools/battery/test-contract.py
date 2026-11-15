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


def negative(name, fn, guard=None, message=None, clean=True, fallback=None):
    """失敗しなければならない制御。**その見張り番が落ちたこと**まで確かめる

    第 55 ラウンド agy P1 の実測で、負控制の 3 件は「別の一の見張り番が先に落ちる」だけで
    合格していた（対象の見張り番を無効化しても制御がまだ落ちる＝その見張り番を測っていない
    空振り）。だからここで 2 度走らせる:

    1. **素の実行**: 落ちて、`message`（対象の見張り番の案内）が含まれること
    2. **`guard` を消した実行**: `message` が出ないこと。`clean`（既定）なら**通ること**も
       要求する（他の見張り番に遮われている間は、その制御は対象を測っていない）

    `clean=False` は「見張り番を消すと後が読めずに別の手前で落ちる」実行系の制御だけ
    （JSON を書かない、JSON が壊れている）。その場合は `fallback` に**その別の手前の文面**を
    書く（第 56 ラウンド agy P2-3）。文面を宣言させていないと、Run 2 が何で落ちたか不明の
    まま「別の一で落ちた＝検出成功」と数えてしまう"""
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
    elif not clean:
        # 見張り番を消しても実行系が最後まで読めない制御は、**何が落ちたか**を宣言させる
        if not fallback:
            failed.append(f'{name}: clean=False は fallback に「別の手前の文面」を書く'
                          '（何も言わないと Run 2 が何で止まったか不明のまま通る）')
        elif not det2 or fallback not in text2:
            failed.append(f'{name}: 見張り番 {" / ".join(names)} を消した実行が'
                          f'「{fallback}」で止まらない（想定と違う所で落ちた）: {text2[:200]}')


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


def dir_rule_v1_ledger_moved():
    """既知差分の 1 件目の `id` を別ノードへ動かす（**件数も向き別も動かさない**）

    第 56 ラウンド Codex P2-1: 上の `dir_rule_broken_rows` は行を消すので向き別とレポート別の
    見張り番が先に落ち、`CGD_GUARD_OFF=dir-rule-v1` でも検出成功になっていた（＝v1 の内容照合を
    単独で測っていなかった）。ここでは不一致 55 件という件数を変えずに**中身だけ**ずらすので、
    他の見張り番は素通りし、`dir-rule-v1` を消した実行は通る"""
    rel = f'{BATTERY}/known-v1-diffs.json'
    p = stash(rel)
    led = json.loads(p.read_text(encoding='utf-8'))
    rows = [d for d in led['diffs'] if d.get('kind') == 'row'
            and len(d.get('old') or []) >= 2 and len(d.get('new') or []) >= 2
            and d['old'][1] != d['new'][1]]
    if len(rows) != 55:
        raise NotDetected(f'既知差分の「向きが変わる行差分」が {len(rows)} 件'
                          '（この制御は 55 件の前提で組む。台帳の作り直しは人の判断）')
    moved = None
    for d in rows:
        used = {x['id'] for x in rows if x['cond'] == d['cond']}
        doc = json.loads((HERE / 'baseline-v1' / d['cond']).read_text(encoding='utf-8'))
        cand = sorted({r['id'] for _, r in _rows_of(doc)
                       if r.get('id') and r['id'] not in used and r['id'] != d['id']})
        if cand:
            d['id'], moved = cand[0], d['cond']
            break
    if not moved:
        raise NotDetected('id を動かす先が 1 件も無い（この制御が空振りになるので中断）')
    p.write_text(json.dumps(led, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        return py('check-dir-rule.py', '--profile', 'v1')
    finally:
        restore()


def dir_rule_report_fake_key():
    """`byReport` を実在しないレポート名 1 本に集め替えた一覧（合計は同じ。agy P2-2 の ①）

    形の検査は 18 本という実体を知らない。ここで測るのは `check-dir-rule.py` が**レポート別**に
    実測と突き合わせる一かどうか。第 57 ラウンド agy P2-4 の実測でこの形は要求一覧の検査も
    通っていたので、キー集合その物を見る `cov-keys` を別制御で用意した
    （`dir_rule_report_unknown_key` / `coverage_condition_unknown_key`）"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    by = doc['expectations']['dirRule']['current']['byReport']
    total = sum(by.values())
    doc['expectations']['dirRule']['current']['byReport'] = {'not-a-report.json': total}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        return py('check-dir-rule.py', '--profile', 'current', 'out/audit-current')
    finally:
        restore()


def dir_rule_negative_counter():
    """向き別の件数に負の値を置く（`agree` を 1 増やして `bad` を 1 引く。合計は同じ。agy P2-2 の ③）

    形を検査する `coverage_shape_errors` は 0 以上の整数を見ていたが、向き別の 5 欄は
    「整数かどうか」だけを見ていた（`bad = -1` が通る）。+1 / -1 の組みにして、`bad` が 0 の
    プロファイル（current は 441 / 0）でも同じ制御が働くようにした"""
    spec = spec_copy()
    e = spec['expectations']['dirRule']['current']
    e['agree'], e['bad'] = e['agree'] + 1, e['bad'] - 1
    IN.validate_required_spec(spec, REPO)


def fixtures_duplicated():
    """要求一覧の `fixtures` に同じパスを 2 度書く（集合にすると消える。第 56 ラウンド agy P2-1）"""
    spec = spec_copy()
    spec['fixtures'].append(spec['fixtures'][0])
    IN.validate_required_spec(spec, REPO)


def allperm_full_cap_one():
    """`allperm-full.py` の順列上限を 1 にする（間引き後の 1 とおり比較は空振り。Codex P2-2）

    実測（第 56 ラウンド Codex）: 縁順で出力が変わる stub に対して上限 1 は「縁順 1 通り /
    レポート JSON 1 通り / 判定: JSON 完全一致」で終了 0、上限 24 なら割れて終了 1"""
    return py('allperm-full.py', str(REPO / 'skill/scripts/report.mjs'),
              str(REPO / BATTERY / 'min-2.json'), '1')


def _rows_of(doc):
    """レポート JSON の行を (欄名, 行) でならべる（`check-dir-rule.py` の `rows_of` と同じもの）"""
    for b in ('external.in', 'external.out', 'entries.in', 'entries.out',
              'artifacts.in', 'artifacts.out', 'sameApi', 'siblingEndpoints', 'wiring'):
        part = doc[b.split('.')[0]][b.split('.')[1]] if '.' in b else doc[b]
        for x in part:
            yield b, x


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
    """要求一覧から条件を 1 件消す（今回走るのは 219 件のまま）

    消した条件の id は期待値の内訳から**一緒に**消し、合計と条件数も作り直す。そうしないと
    第 58 ラウンドの `cov-keys`（キー集合の実体検査）が先に落ちて、この制御が
    `condition-set` を測っていない空振りになる（agy P2-4 で増えた見張り番との取り合わせ）"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    removed = doc['conditions'].pop(5)
    for kind in IN.COVERAGE_KINDS:
        e = doc['expectations'][kind]
        e['byCondition'].pop(removed['id'], None)
        e['total'], e['conditions'] = sum(e['byCondition'].values()), len(e['byCondition'])
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


# ------------------------------------------------------------ 第 58 ラウンド agy P2 の制御 --
def cond_graph_absolute():
    """`graph` を絶対パスにする（`cond-shape` だけを測る。第 57 ラウンド agy P2-2 の ①）

    `graph` の `#`・絶対パス・`..` を見る検査は `guard()` を通っておらず、`cond-shape` を
    消しても消せなかった（実測「`cond-shape` を消したのに REJECTED」。Astra 裁定 問 1 ②で
    `cond-shape` へまとめる）。id を据え置く細工だと `canonical-id` が先に落ちるので、
    **id も同じ中身から作り直した**一覧を渡す（第 56 ラウンド Codex P2-1 と同じ孤立の作り方）。
    id を作り直すので期待値のキー集合を見る `cov-keys` が別の手前で落ちる。それも一緒に消して
    単独に測る（第 58 ラウンド実測: `cond-shape` だけ消すと `cov-keys` が割れた）"""
    spec = spec_copy()
    c = spec['conditions'][3]
    c['graph'] = '/' + c['graph']
    c['id'] = IN.condition_id(IN.condition_key(c.get('case'), c['graph'], c['kind'], c['args']))
    IN.validate_required_spec(spec, REPO)


def fixtures_non_string():
    """`fixtures` の 1 本を文字列でない値にする（`fixture-shape` だけを測る。agy P2-2 の ②）

    実測（第 57 ラウンド agy）は `dup-fixture` と `fixture-set` を消しても int 混入が通らなかった。
    Astra 裁定 問 1 ③で要素の**型**を `fixture-shape` に分ける。見張り番を消した実行は
    値がそのまま集合比較へ入るので `fixture-set` が別の手前で止める（`fallback` で宣言）"""
    spec = spec_copy()
    spec['fixtures'][0] = 1
    IN.validate_required_spec(spec, REPO)


def dir_rule_report_unknown_key():
    """`byReport` のキーを 1 本だけ実在しない名前に差し替える（件数も合計もそのまま）

    第 57 ラウンド agy P2-4 の実測で `{"": 441}`、実在 17 本 + 余剰 1 本、1 本への全件寄せが
    すべて通っていた。`cov-keys` はキー集合を `baseline-v1/*.json` の 18 本と突き合わせる
    （Astra 裁定 問 2: ここが見るのは**どのレポートを数えるか**。件数の正しさは
    `dir-rule-report` が実測と比べる）"""
    spec = spec_copy()
    by = spec['expectations']['dirRule']['current']['byReport']
    victim = sorted(by)[0]
    by[victim + '.ghost'] = by.pop(victim)
    IN.validate_required_spec(spec, REPO)


def coverage_condition_unknown_key():
    """`byCondition` の id を 1 件だけ要求一覧に無い値へ差し替える（件数も合計もそのまま）

    `byCondition = {"fake": 5033}` が通っていた穴の別形（agy P2-4）。要求一覧の条件 id と
    キー集合を突き合わせる `cov-keys` が止める"""
    spec = spec_copy()
    by = spec['expectations']['invariantRows']['byCondition']
    ghost = '0' * 16
    if ghost in by or ghost in {c['id'] for c in spec['conditions']}:
        raise NotDetected('化け id が実在してしまう（この制御の前提が変わった）')
    by[ghost] = by.pop(sorted(by)[0])
    IN.validate_required_spec(spec, REPO)


def directionless_bool_counter():
    """向き none の数えに `true` を置く（`dirRule` に入れた整数検査の横展開漏れ。agy P2-2）

    `dirRule` の 5 欄は第 56 ラウンドで「整数かどうか + 0 以上」を見たが、`directionless` は
    「整数かどうか」だけだった。実測で `rows = true` / `none = -1` / `none` 欠落が通った"""
    spec = spec_copy()
    spec['expectations']['directionless']['rows'] = True
    IN.validate_required_spec(spec, REPO)


def directionless_negative_none():
    """`expectations.directionless.none` に負の値を置く（同じ穴の別形）"""
    spec = spec_copy()
    spec['expectations']['directionless']['none'] = -1
    IN.validate_required_spec(spec, REPO)


def directionless_missing_none():
    """`expectations.directionless` から `none` を消す（`count-none.py` が読む欄。agy P2-2）"""
    spec = spec_copy()
    del spec['expectations']['directionless']['none']
    IN.validate_required_spec(spec, REPO)


def report_dir_empty_direct():
    """レポート 0 件のディレクトリを `report_paths` へ直接渡す（`path-empty` だけを測る）

    README は「1/18 のディレクトリ」を `path-empty` と `path-count` 両方の制御と書いていたが、
    その実行は `path-count` が先に落ちていた（第 57 ラウンド agy P2-2: 表に載っているのに
    走っていない）。道具側から単独の制御にできないので関数へ直接渡す（Astra 裁定 問 3）"""
    d = TMP / 'empty-reports'
    d.mkdir(exist_ok=True)
    IN.report_paths(d, expect=None, what='制御')
    return f'0 件でも通った（0 件で合格にしない見張り番が居ない）: {d}'


def report_dir_wrong_count_direct():
    """1 本だけのディレクトリに 18 件を期待して渡す（`path-count` だけを測る。同上）"""
    d = TMP / 'one-report'
    if d.exists():
        shutil.rmtree(d)
    d.mkdir()
    shutil.copy(HERE / 'baseline-v1' / 'demo-api.json', d / 'demo-api.json')
    IN.report_paths(d, expect=18, what='制御')
    return f'1 本で 18 件期待を通った: {d}'


def run_json_child_fails_with_output():
    """正しい JSON を書いて**非 0 で終わる**実行（`child-fail` だけを測る。Astra 裁定 問 3）

    以前 README は `child-fail` に「終了 0 で JSON を書かない」制御を載せていたが、それは
    `json-missing` の制御で消すと `json-missing` が落ちる空振りだった（第 57 ラウンド agy
    P2-2）。出力を先に書かせておくと、`child-fail` を消した実行は JSON がそのまま読めて
    **通る**（第 58 ラウンド実測。だから `clean=True` のままで測れる）"""
    bad = TMP / 'fail-with-output.mjs'
    bad.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1], JSON.stringify({
  summary: {rows: 1},
  external: {in: [{id: 'x', bucket: 'external', direction: 'in', hops: 1}], out: []},
  entries: {in: [], out: []}, artifacts: {in: [], out: []},
  sameApi: [], siblingEndpoints: [], wiring: [],
}));
process.exit(3);
""", encoding='utf-8')
    IN.run_json(str(bad), [], tmp_out('fail'), REPO, label='制御')


def run_json_empty_output():
    """終了 0 で**空のファイル**を書く実行（`json-empty` だけを測る）

    消した実行は空ファイルの `json.loads` で `json-parse` に拾われる（`fallback` で宣言）"""
    bad = TMP / 'empty-file.mjs'
    bad.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1], '');
""", encoding='utf-8')
    IN.run_json(str(bad), [], tmp_out('empty'), REPO, label='制御')


def projection_bucket_missing():
    """6 欄の形が崩れた JSON を `projection_rows` へ直接渡す（`proj-buckets` だけを測る）

    第 57 ラウンド agy P2-2: README は「欄が消える」を `proj-buckets` と `proj-fields` 両方の
    制御として載せていたが、欄が消える実行は `proj-fields` が落としていた。9 欄の形その物が
    崩れた JSON は道具の手前で `report-shape` が止まる（その内側の見張り番なので、関数へ直接
    渡して単独に測る）。消した実行は `doc[b][side]` で KeyError になる（`fallback` で宣言）"""
    doc = json.loads((HERE / 'baseline-v1' / 'demo-api.json').read_text(encoding='utf-8'))
    if not doc['external']['out']:
        raise NotDetected('基準の 18 本で `external.out` が空（この制御の前提が変わった）')
    del doc['external']['out']
    IN.projection_rows(doc, '制御', ('id', 'bucket', 'direction', 'hops', 'switches'))


def built_conditions_duplicated():
    """組み上げる起動条件が重複する（要求一覧は**壊さない**で builder へ渡す列だけを重複させる）

    第 57 ラウンド agy P2-2: `dup-built` に載せていた制御は実在しなかった。要求一覧の
    `fixtures` を重複させる制御（`dup-fixture`）では一覧の形検査が先に落ちる。Astra 裁定 問 3
    の作り方で、追跡下の一覧は正当なまま builder だけへ重複した列を渡す"""
    fx = IN.required_fixtures(REPO)
    conds = IN.launch_conditions(REPO, fixtures=list(fx) + [fx[0]])
    return f'重複を数えずに {len(conds)} 組みが返った（要求一覧との比較の前に止める）'


def allperm_full_cap_zero():
    """`allperm-full.py` の順列上限に 0 を渡す（割り算の前で止まる。agy P2-1）

    実測（第 57 ラウンド agy）は `step = len(perms) // cap` で ZeroDivisionError の Traceback。
    `require_sample_cap` が `require_sampled_runs` より前で止める"""
    return py('allperm-full.py', str(REPO / 'skill/scripts/report.mjs'),
              str(REPO / BATTERY / 'min-2.json'), '0')


def r43_trial_limit_one():
    """`r43-permute.py` の入れ替え試行を 1 とおりにする（agy P2-1: 実測で終了 0）

    「表 1 通り（1 入れ替え）」で通っていた（`allperm-full.py` の間引き後の 1 とおり比較と同型、
    第 56 ラウンド Codex P2-2）。`trial-count` が走る前に止め、消した実行は
    `perm-cap`（実際に走った本数）が別の手前で止める"""
    return py('r43-permute.py', str(REPO / 'skill/scripts/report.mjs'), '1')


def none_expectations_off_by_one():
    """`expectations.directionless.none` を 1 増やして `count-none.py` を走らせる

    README は `none-expectations` の制御を「実グラフの縁を全部抜く」と書いていたが、その実行は
    `edge-order.py` の制御だった（第 57 ラウンド agy P2-2: 表に載っているのに走っていない）"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc['expectations']['directionless']['none'] += 1
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        return py('count-none.py', 'out/audit-current')
    finally:
        restore()


def none_counters_moved():
    """レポート 1 本の `summary.rows` を 1 増やす（欄の実測とサマリが食い違う日）

    `none-expectations` は期待値との比較で、こちらは見張り番が違う（`none-counters`）。
    欄の実測から数えた行数は変わらないので期待値側は一致したまま、カウンタだけ割れる"""
    src = TMP / 'audit-bumped'
    if src.exists():
        shutil.rmtree(src)
    src.mkdir()
    for q in sorted((REPO / 'out/audit-current').glob('*.json')):
        shutil.copy(q, src / q.name)
    victim = src / 'demo-api.json'
    doc = json.loads(victim.read_text(encoding='utf-8'))
    doc['summary']['rows'] += 1
    victim.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
    return py('count-none.py', str(src))


def v1_derivation_rows_four():
    """既知差分の 1 件を「向きが変わらない」形へ直す（導出が 55 件でなくなる。agy P2-2）

    README は `v1-derivation` を「`dir-rule-v1` の制御が同時に落とす」と書いていたが、それは
    `v1-derivation` を単独で測っていない（Astra 裁定 問 3）。導出関数へ 54 件になる一覧を
    直接渡して止まることを確かめ、見張り番を消した実行は 54 件で**通る**"""
    rel = f'{BATTERY}/known-v1-diffs.json'
    p = stash(rel)
    led = json.loads(p.read_text(encoding='utf-8'))
    rows = [d for d in led['diffs'] if d.get('kind') == 'row'
            and len(d.get('old') or []) >= 2 and len(d.get('new') or []) >= 2
            and d['old'][1] != d['new'][1]]
    if len(rows) != 55:
        raise NotDetected(f'既知差分の「向きが変わる行差分」が {len(rows)} 件'
                          '（この制御は 55 件の前提で組む。台帳の作り直しは人の判断）')
    rows[0]['new'][1] = rows[0]['old'][1]
    p.write_text(json.dumps(led, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        n = len(IN.expected_direction_diffs(REPO))
        return f'向き の差分を {n} 件と導いても通った（55 件のはず）'
    finally:
        restore()


LEDGER = 'skill/scripts/tools/battery/input-fingerprints.json'


def _any_scope_input():
    """中身の指紋で `mode='any'` と読んでいる入力（json か bytes のどちらかで読める物）を 1 本返す"""
    for rel, mode, _what in IN.content_scope(REPO):
        if mode == 'any':
            return rel
    raise NotDetected('`mode=any` の入力が無い（この制御の前提が変わった）')


def fingerprint_ledger_extra_entry():
    """指紋台帳に入力の一覧に無い物を 1 件足す（`fp-ledger-extra` だけを測る。第 57 ラウンド agy P2-2）

    README は台帳の余剰を読む見張り番に制御を載せていなかった。消した実行は台帳の条目を
    無視するだけなので他は割れない（入力の側は変わっていない）"""
    p = stash(LEDGER)
    data = json.loads(p.read_text(encoding='utf-8'))
    ghost = 'skill/tests/fixtures/ImpactFacts/ghost.graph.json'
    if ghost in data[IN.CONTENTS]:
        raise NotDetected('化けの入力が台帳に実在してしまう（この制御の前提が変わった）')
    data[IN.CONTENTS][ghost] = {'mode': 'json', 'sha': '0' * 64, 'bytes': 0}
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    bad = IN.require_fingerprints(REPO)
    restore()
    return (0 if not bad else 1), '\n'.join(bad)


def fingerprint_mode_moved():
    """台帳の**読み方**だけを 1 件書き換える（`fp-mode` だけを測る。第 57 ラウンド agy P2-2）

    `fp-sha` → `fp-bytes` → `fp-mode` は elif で繋がっている。中身を変えないと最後の 1 つは
    働かないので、sha と bytes はそのまま `mode` の値だけを変える。読み方の実体は入力の
    並び（`CONTENT_SCOPES`）から決まるので、台帳の記録がずれた日だけを拾う"""
    victim = _any_scope_input()
    p = stash(LEDGER)
    data = json.loads(p.read_text(encoding='utf-8'))
    if data[IN.CONTENTS][victim].get('mode') != 'json':
        raise NotDetected(f'{victim} の台帳の読み方が json でない（この制御の前提が変わった）')
    data[IN.CONTENTS][victim]['mode'] = 'bytes'
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    bad = IN.require_fingerprints(REPO)
    restore()
    return (0 if not bad else 1), '\n'.join(bad)


def fingerprint_type_unknown():
    """台帳の読み方に json でも bytes でもない値を置く（`fp-type` だけを測る。同上）

    `mode='any'` の入力は json か bytes のどちらかで読めるはずで、それ以外を記録している日は
    指紋の型が不明（比較の意味が無い）。`fp-mode` の elif の後ろに有るので、`fp-type` だけを
    消した実行は `fp-mode` が別の手前で止める（`fallback` で宣言する）"""
    victim = _any_scope_input()
    p = stash(LEDGER)
    data = json.loads(p.read_text(encoding='utf-8'))
    data[IN.CONTENTS][victim]['mode'] = 'text'
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    bad = IN.require_fingerprints(REPO)
    restore()
    return (0 if not bad else 1), '\n'.join(bad)


def fingerprint_structural_nodes_moved():
    """out/ 入力の構造指紋（ノード数）を台帳側だけ 1 ずらす（`fp-structural` だけを測る。同上）

    `check_fingerprints` は `out/wt-head` など固定入力のノード・縁・id・関係の数を台帳と
    比べる。実測では `fp-structural` と `fp-type` を落とす制御が走っていなかった
    （README に載っていた制御は `fp-sha` / `fp-bytes` 側を落としていた）"""
    p = stash(LEDGER)
    data = json.loads(p.read_text(encoding='utf-8'))
    victim = sorted(data['inputs'])[0]
    data['inputs'][victim]['nodes'] += 1
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    bad = IN.check_fingerprints(REPO)
    restore()
    return (0 if not bad else 1), '\n'.join(bad)


def input_check_validates_ledger():
    """要求一覧を壊して**入力点検**を走らせる（入口が揃ったか。第 57 ラウンド agy P2-3）

    実測: `fixtures` を重複させても `check-battery-inputs.py` は「バッテリーの入力 79 件
    （fixture 20 本ふくむ）」と数えて**終了 0** だった（`validate_required_spec` を呼ばずに
    `fixtures` を直読みしていた。私が第 57 ラウンドの検証 1 周目で踏んだ穴その物）。
    入力点検も測定道具と同じ入口を通るようになった"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc['fixtures'].append(doc['fixtures'][0])
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        return py('check-battery-inputs.py')
    finally:
        restore()


def _edge_order_module():
    """`edge-order.py` を import する（本体は `main()` へ移したので import では走らない）

    Astra 裁定 問 4: 追加した判定が実際に働くことは**この呼び出し経路**で見る。
    `IN.run_json` の制御だけでは別経路の証拠にしかならない"""
    import importlib.util
    sp = importlib.util.spec_from_file_location('edge_order_under_test', HERE / 'edge-order.py')
    mod = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(mod)
    return mod


def edge_order_child_fails():
    """`edge-order.py` の子実行が非 0 で終わる（`child-fail` を query.mjs 経路で測る）

    消した実行は stdout が空なので `json-parse` が別の手前で止める（`fallback` で宣言）"""
    stub = node_stub("""
// query.mjs が落ちた日の再現（--json は標準出力なので出力は空のまま終わる）
process.stderr.write('query.mjs が落ちた\\n');
process.exit(4);
""", 'query-fail.mjs')
    mod = _edge_order_module()
    mod.QUERY = stub
    return mod.key(str(REPO / 'out/demo/graph.json'), ['--from', 'a'], REPO)


def edge_order_bad_json():
    """`edge-order.py` が読めない出力を受け取る（`json-parse` を query.mjs 経路で測る）

    消した実行は `d = {}` になって形検査 `edge-order-groups` が別の手前で止める"""
    stub = node_stub("""
process.stdout.write('{ "groups": [');
""", 'query-broken.mjs')
    mod = _edge_order_module()
    mod.QUERY = stub
    return mod.key(str(REPO / 'out/demo/graph.json'), ['--from', 'a'], REPO)


def edge_order_json_shape():
    """`--json` の形をしていない出力（`groups` が配列でない）を弾く（`edge-order-groups`）

    第 57 ラウンド agy P2-2 で名前を付けた 3 判定のうち**形**の判定を単独で測る。
    消した実行は鍵の文字列を返して通る（比較する相手が無い実行になる）"""
    stub = node_stub("""
process.stdout.write(JSON.stringify({groups: 3, summary: {reached: 0}}));
""", 'query-shape.mjs')
    mod = _edge_order_module()
    mod.QUERY = stub
    return mod.key(str(REPO / 'out/demo/graph.json'), ['--from', 'a'], REPO)


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


def _call_guard_names(text):
    """検査器側が見張り番に付けた名前を集める（`guard` の呼び形。説明文に呼びの生文字列を
    置くと自分の集合に混ざるので書かない）
    """
    found = set()
    marker = "guard" + "(" + "'"   # マーカーは組み立てて、自分の走査対象に入らないようにする
    i = 0
    while True:
        j = text.find(marker, i)
        if j < 0:
            return found
        i = j + len(marker)
        end = text.find("'", i)
        if end < 0:
            return found
        found.add(text[i:end])


def _off_guard_names(text):
    """制御が消す見張り番（`guard` に書く 1 個または組の名前）を集める。案内文の引用符を
    誤って数えないように、組は最初の `,` で切る
    """
    found = set()
    marker = "guard" + "="   # 同上
    i = 0
    while True:
        j = text.find(marker, i)
        if j < 0:
            return found
        i = j + len(marker)
        grp = text[i:]
        if grp.startswith('('):
            cut = grp.find(')')
        else:
            cut = grp.find(',')
        if cut >= 0:
            grp = grp[:cut]
        k = 0
        while True:
            a = grp.find("'", k)
            if a < 0:
                break
            b = grp.find("'", a + 1)
            if b < 0:
                break
            found.add(grp[a + 1:b])
            k = b + 1


def guard_names_all_covered():
    """`guard` で名前を付けた合否判定を、**個別負控制が 1 本ずつ名指している**

    README の「見張り番すべてに個別負控制が有る」という文を毎回機械に数えさせる（第 57
    ラウンド agy P2-2 は「表に載った個別負控制が 13 名前ぶん実在しなかった」なので、同じ
    嘘を次に書けないようにここで止める）
    """
    tree = set()
    for path in (REPO / 'skill' / 'scripts' / 'tools').rglob('*.py'):
        tree |= _call_guard_names(path.read_text(encoding='utf-8'))
    own = _off_guard_names(pathlib.Path(__file__).read_text(encoding='utf-8'))
    missing = sorted(tree - own)
    unknown = sorted(own - tree)
    if missing:
        failed.append(f'見張り番 {len(missing)} 個を名指した個別負控制が無い: {missing[:6]}')
    if unknown:
        failed.append(f'制御が消す見張り番が実在しない（名前のスペル違い）: {unknown[:6]}')
    print(f'  見張り番 {len(tree)} 個すべてに個別負控制が名指しされている')


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
                 guard=('cov-shape', 'cov-keys'), message='byCondition が空')
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
                 guard='proj-fields', message='行に欄が無い', clean=False, fallback='KeyError')
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
        # 第 56 ラウンド Codex P2-1: 上の制御は行を消すので件数の見張り番が先に落ちる。
        # v1 の**内容**照合を単独で測るため、件数を動かさずに不一致の中身だけずらす
        negative('既知差分の id を別ノードへ動かす（不一致 55 件のまま）',
                 dir_rule_v1_ledger_moved,
                 guard='dir-rule-v1', message='既知差分に無い不一致')
        negative('byReport を実在しないレポート名 1 本に集め替えた一覧',
                 dir_rule_report_fake_key,
                 guard='dir-rule-report', message='の比較件数（レポート別）')
        negative('向き別の件数に負の値を置く（agree を増やして bad を引く）',
                 dir_rule_negative_counter, guard='cov-shape', message='負の整数')
        negative('要求一覧の fixtures に同じパスを 2 度書く',
                 fixtures_duplicated, guard='dup-fixture', message='fixtures に重複')
        negative('allperm-full.py の順列上限を 1 にする',
                 allperm_full_cap_one, guard='perm-cap', message='順列上限に 1 を渡している')
        negative('終了 0 で JSON を書かない実行', run_json_silent,
                 guard='json-missing', message='終了 0 なのに JSON を書いていない',
                 clean=False, fallback='出力先が無い')
        negative('出力先が既にある実行', run_json_stale_output,
                 guard='out-exists', message='出力先がもう有る')
        # 第 56 ラウンド agy P2-3: `json-parse` だけ消すと `doc = {}` が `report-shape` で
        # 落ち、別の一で止まっていた。壊れた JSON を読む制御が測るのは「読めないこと」なので、
        # 読み終わった後の形検査もまとめて消して**通る**ことを要求する
        negative('壊れた JSON を読む実行', run_json_broken_json,
                 guard=('json-parse', 'report-shape'), message='JSON が読めない')
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
        # 第 57 ラウンド agy P2 の 4 件（実測は `out/review-agy57.log`）。形・入口・標本の実り
        # を直した裁定は `out/astra58.log`
        negative('要求一覧の graph を絶対パスにする（id も揃えた細工）', cond_graph_absolute,
                 guard=('cond-shape', 'cov-keys'), message='リポジトリ相対ではない')
        negative('要求一覧の fixtures に文字列でない値を置く', fixtures_non_string,
                 guard='fixture-shape', message='文字列でない要素',
                 clean=False, fallback='要求一覧に有るのに fixture が無い')
        negative('byReport のキーを 1 本だけ実在しない名前に差し替える',
                 dir_rule_report_unknown_key, guard='cov-keys',
                 message='baseline-v1 へ無いレポート名がある')
        negative('byCondition の id を 1 件だけ要求一覧に無い値へ差し替える',
                 coverage_condition_unknown_key, guard='cov-keys',
                 message='要求一覧へ無い id がある')
        negative('向き none の数えに true を置く', directionless_bool_counter,
                 guard='cov-shape', message='が整数ではない')
        negative('向き none の数えに負の値を置く', directionless_negative_none,
                 guard='cov-shape', message='が負の整数')
        negative('expectations.directionless から none を消す', directionless_missing_none,
                 guard='cov-shape', message='が整数ではない')
        negative('レポート 0 件のディレクトリを report_paths へ直接渡す',
                 report_dir_empty_direct, guard='path-empty', message='が 0 件')
        negative('1 本のディレクトリに 18 件を期待して渡す',
                 report_dir_wrong_count_direct, guard='path-count', message='（18 件のはず）')
        negative('正しい JSON を書いて非 0 で終わる実行', run_json_child_fails_with_output,
                 guard='child-fail', message='report.mjs 失敗')
        negative('終了 0 で空のファイルを書く実行', run_json_empty_output,
                 guard='json-empty', message='JSON が空',
                 clean=False, fallback='JSON が読めない')
        negative('external.out が無い JSON を projection_rows へ渡す',
                 projection_bucket_missing, guard='proj-buckets', message='突き合わせる 6 欄',
                 clean=False, fallback='KeyError')
        negative('builder へ重複した fixture 列を渡す（要求一覧は正常）',
                 built_conditions_duplicated, guard='dup-built', message='今回組み上げた起動条件に重複')
        negative('allperm-full.py の順列上限を 0 にする', allperm_full_cap_zero,
                 guard='perm-cap', message='順列上限に 0 を渡している')
        negative('r43-permute.py の入れ替え試行を 1 とおりにする', r43_trial_limit_one,
                 guard='trial-count', message='入れ替えの試行を 1 とおりに指定している',
                 clean=False, fallback='縁順が 1 とおりしかない')
        negative('expectations.directionless.none を 1 増やして count-none.py',
                 none_expectations_off_by_one, guard='none-expectations', message='期待値と**不一致**')
        negative('1 本の summary.rows を 1 増やして count-none.py',
                 none_counters_moved, guard='none-counters', message='サマリカウンタが割れているので不合格')
        negative('既知差分の 1 件を向きが変わらない形へ直す（導出 54 件）',
                 v1_derivation_rows_four, guard='v1-derivation', message='向き の差分が 54 件')
        negative('edge-order.py の子実行が非 0 で終わる', edge_order_child_fails,
                 guard='child-fail', message='query.mjs 失敗',
                 clean=False, fallback='query.mjs の JSON が読めない')
        negative('edge-order.py が読めない出力を受け取る', edge_order_bad_json,
                 guard='json-parse', message='JSON が読めない',
                 clean=False, fallback='出力が --json の形ではない')
        negative('edge-order.py に --json の形でない出力を渡す', edge_order_json_shape,
                 guard='edge-order-groups', message='出力が --json の形ではない')
        negative('要求一覧を壊して入力点検を走らせる', input_check_validates_ledger,
                 guard='dup-fixture', message='fixtures に重複')
        negative('指紋台帳に入力の一覧に無い物を 1 件足す', fingerprint_ledger_extra_entry,
                 guard='fp-ledger-extra', message='指紋台帳に有るが入力の一覧に無い')
        negative('指紋台帳の読み方だけを 1 件書き換える', fingerprint_mode_moved,
                 guard='fp-mode', message='の読み方が基準と違う')
        negative('指紋台帳の読み方に json でも bytes でもない値を置く', fingerprint_type_unknown,
                 guard='fp-type', message='指紋の型が台帳で不明',
                 clean=False, fallback='の読み方が基準と違う')
        negative('固定入力の構造指紋（ノード数）を 1 ずらす', fingerprint_structural_nodes_moved,
                 guard='fp-structural', message='の nodes が基準と違う')

        positive('正当な 0 行レポート 4 本は形として通る', legit_empty_reports)
        positive('期待値の合計が条件別の合計と導出で一致', coverage_current_matches)
        positive('リポジトリ根と battery/ の両方から同じ相対パス', relative_paths_from_both_cwds)
        positive('追跡下の一覧が自分の形を検査して通る', ledger_self_valid)
        positive('指紋台帳と入力が揃っている', fingerprint_ledger_clean)
        positive('入力点検の道具が実際に起動して終了 0 で通る', input_check_tool_runs)
        positive('見張り番の名前すべてに個別負控制が名指しされている',
                guard_names_all_covered)

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
