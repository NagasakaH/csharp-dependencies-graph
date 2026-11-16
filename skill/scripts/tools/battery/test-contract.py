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
# 名前を持っていて、環境変数 `CGD_GUARD_OFF=name,name`（または制御の中の
# `with IN.guard_off('名前'):` の区間。区間は台帳 `guardCallers` のファイルだけ使える）で
# 1 個ずつ消せる。`negative(name, fn, guards=..., message=...)` は
#   1. 素の実行 → 落ちて `message`（その見張り番の案内）が出ること
#   2. `guard` を消した実行 → `message` が出ないこと。既定では**通る**ことも要求する
# を検査するので、対象の見張り番を消しても別の所で落ちるだけの**空振り制御**を通さない。
# 名前のスペルを間違えると 2 で同じ案内が出て失敗するので、名前表の管理は要らない。
import ast
import glob
# 候補の道具 `emit-guard-owners.py` の判定を制御から呼ぶ為に読み直す（末端までの経路で
# import し、`spec_from_file_location` / `module_from_spec` の登録末端だけを呼ぶ。豁免は対応表の
# `exemptions` にこのファイル名で登録済み。Astra 第 67 ラウンド 問 3）
import importlib.util
import json
import os
import pathlib
import re
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
ran = {'negative': 0, 'positive': 0, 'singleton': {}}


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
                       cwd=str(cwd or REPO), capture_output=True, text=True, env=IN.guard_env())
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
        return False, 'NotDetected: ' + str(e)   # 制御自身の故障。OFF 側で成功に数えない
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        return (code != 0), f'exit {code}: {e}'
    except Exception as e:  # noqa: BLE001 - 見張り番を消した側は文面だけ拾う
        if not tolerant:
            raise
        return True, f'{type(e).__name__}: {e}'
    if hasattr(res, '__next__') or hasattr(res, '__await__'):
        # Astra 第 69 ラウンド 問 1 の実装条件 6: 制御は区間の内で**同期的に**終わる。遅延実行を
        # 返すと本体が区間を抜けた後へ走り、無効化集合の観測（6 箇所）が総ずれする
        raise NotDetected('制御が同期的に終わらない（ジェネレータ・コルーチンを返した。'
                          '本体を区間の内で終わらせる。Astra 第 69 ラウンド 問 1）')
    if isinstance(res, tuple) and res and isinstance(res[0], int):
        return (res[0] != 0), str(res[1])
    if res is True:
        return True, ''
    return False, str(res)


def _env_restore(prev):
    """子プロセスへ渡す環境変数 `CGD_GUARD_OFF` を元へ戻す（プロセス内は `IN.guard_off` の区間）

    Astra 第 68 ラウンド 問 1 の B案まで、プロセス内の無効化は `IN.set_guard_off()`（呼び出し後も
    残る）で行っていた（両名のレビューの実測 `holes=0 before=True after=False later=False`）。
    箱の公開名を直接書き換える道も同じく穴（Astra 第 67 ラウンド 問 2: `IN.<公開名> = ...`）なので、
    箱の状態を変えるのは `with IN.guard_off('名前'):` の区間だけにした"""
    if prev is None:
        os.environ.pop('CGD_GUARD_OFF', None)
    else:
        os.environ['CGD_GUARD_OFF'] = prev


class _RealGuardState:
    """本番の見張り番の箱を読む実装（Astra 第 70 ラウンド 問 2 の注入点）

    `IN.guard_off` を**値として持ち出さず**、`with` の管理位置で直接呼ぶ。公開名への書き換えも
    しないので第 67 / 68 ラウンドの箱の規則を破らない。ここを差し替えられるのは「区間を抜けた後に
    無効化が残る」等の**偽の状態**を実行器の自己検査で作る為で、実在の箱を汚す細工は要らない
    （第 70 ラウンド 問 2 の「別プロセス」「別スレッド」「規則の豁免」はどれも却下された）
    """

    def read(self):
        return set(IN.GUARD_OFF)

    def is_off(self, name):
        return name in IN.GUARD_OFF

    def inside_off(self, names, body):
        with IN.guard_off(*names):
            return body()


_REAL_STATE = _RealGuardState()


def _run_negative(name, fn, names, message, clean, fallback, out, state=None):
    """負控制を**実行するだけの共通器**（Astra 第 70 ラウンド 問 2・問 3）

    失敗は呼び出し側が渡した列 `out` へ積み、通った階級（`clean` / `fallback`）を返す。`failed` にも
    網羅 `ran` にも手を出さない — **網羅への登録は実行器の外側**でしかしない（問 3。実行器の自己検査が
    ここを呼んでも網羅へは混入しない）。状態の読みと OFF 区間は `state` 経由（既定は本番の箱）

    無効化集合は 6 箇所で**集合全体の完全一致**として見る（Astra 第 69 ラウンド 問 1。基準は制御の
    開始時に読んだ `base` ただ 1 つ）。実行は ON → OFF → 復元後 ON の 3 回で、3 回目は 1 回目と同じ
    拒否が出る事。各観測は `finally` の中で行い、失敗はその場で `out` へ転記する（区間の終了処理や
    再実行が例外を投げても失敗は残る）。`finally` から `return` して元の例外を黙らせることはしない
    """
    st = _REAL_STATE if state is None else state
    pending = []

    def _chk(label, want):
        got = st.read()
        if got != want:
            pending.append(f'{name}: {label}、見張り番の無効化集合が一致しない（期待 {sorted(want)} → '
                           f'実際 {sorted(got)[:6]}。Astra 第 69 ラウンド 問 1 の 6 観測点は集合全体の'
                           '完全一致。不一致は復旧処理の前に記録し、後で正常化されても消さない）')

    def _flush():
        if pending:
            out.extend(pending)
            del pending[:]

    base = st.read()   # 観測点 1（制御の開始時・準備前）
    if names and base & set(names):
        out.append(f'{name}: 制御の開始時にもう対象 {" / ".join(sorted(base & set(names)))} が'
                   '無効化されている（開始集合と対象が見張っている名前は交わっていない事が必要。'
                   '前の区間の戻し損ねか入れ子。Astra 第 69 ラウンド 問 1）')
        return None, False

    # ---- 実行 1（見張り番が起きている）----
    try:
        det, text = _run_control(fn)
    except NotDetected as e:
        det, text = False, f'{e}'
        pending.append(f'{name}: {e}')
    except BaseException as e:  # noqa: BLE001 - 制御自身の壊れ方を黙らせない
        det, text = False, f'{type(e).__name__}: {e}'
        pending.append(f'{name}: 制御が壊れている（{type(e).__name__}: {e}）')
    finally:
        _chk('素の実行の終了後', base)   # 観測点 2（例外で終わっても観測する）
        _flush()
    if out:
        return None, not base
    if not det:
        out.append(f'{name}: 落ちずに通った（期待は終了 1）。{text[:160]}')
        return None, not base
    if message and message not in text:
        out.append(f'{name}: 期待した見張り番「{message}」ではなく別の物で落ちた（空振り）: {text[:200]}')
        return None, not base
    if not names:
        return None, not base

    # ---- 実行 2（対象だけ消した区間の中）----
    want = base | set(names)

    def _inside():
        _chk('区間へ入った直後', want)   # 観測点 3
        try:
            return _run_control(fn, tolerant=True)
        finally:
            _chk('見張り番を消した実行の終了後・区間を抜ける前', want)   # 観測点 4

    try:
        det2, text2 = st.inside_off(names, _inside)
    finally:
        _chk('区間を抜けた直後', base)   # 観測点 5
        _flush()
    if out:
        # 状態が合わない実行の結果を次の判定に採用しない（失敗は転記済み）
        return None, not base
    if text2.startswith('NotDetected:'):
        out.append(f'{name}: 見張り番を消した実行が制御の準備失敗で終わった（制御が壊れている。'
                   f'成功ではない）: {text2[:160]}')
        return None, not base
    if message and message in text2:
        out.append(f'{name}: 見張り番 {" / ".join(names)} を消したのに同じ案内が出た'
                   f'（この制御が見ているのは別物）: {text2[:160]}')
        return None, not base
    tier = None
    if clean and det2:
        out.append(f'{name}: 見張り番 {" / ".join(names)} を消しても別の所で落ちる'
                   f'（他の見張り番に遮われて対象を測っていない）: {text2[:200]}')
    elif not clean:
        if not fallback:
            out.append(f'{name}: clean=False は fallback に「OFF 後も残る別の診断の文面」を書く'
                       '（何も言わないと実行 2 が何で止まったか不明のまま通る）')
        elif not det2 or fallback not in text2:
            out.append(f'{name}: 見張り番 {" / ".join(names)} を消した実行が「{fallback}」で止まらない'
                       f'（想定と違う所で落ちた）: {text2[:200]}')
        else:
            tier = 'fallback'
    else:
        tier = 'clean'
    if tier is None:
        return None, not base

    # ---- 実行 3（区間を抜けた後の ON。実行 1 と同じ拒否が出る事）----
    try:
        det3, text3 = _run_control(fn, tolerant=True)
    except BaseException as e:  # noqa: BLE001
        det3, text3 = False, f'{type(e).__name__}: {e}'
        pending.append(f'{name}: 復元後の再実行が壊れている（{type(e).__name__}: {e}）')
    finally:
        _chk('復元後の再実行の終了後', base)   # 観測点 6（`finally` の中。例外時も観測する）
        _flush()
    if out:
        return None, not base
    if not det3 or (message and message not in text3):
        out.append(f'{name}: 区間を抜けた後の再実行が実行 1 と同じ拒否を出さない（復元後に測れていない。'
                   f'実行 1「{message}」→ 実行 3 `{text3[:160]}`。Astra 第 69 ラウンド 問 1 の 3 回実行）')
        return None, not base
    return tier, not base


def negative(name, fn, guards=None, message=None, clean=True, fallback=None):
    """失敗しなければならない制御。**その見張り番が落ちたこと**まで確かめる

    実行の実装は `_run_negative()`（実行だけの共通器）に置いた。ここでは本数を数え、失敗を `failed`
    へ転記し、**通った単独名指しだけ**を網羅 `ran['singleton']` へ登録する（Astra 第 70 ラウンド 問 3:
    網羅への登録は共通実行器の外側。実行器を呼ぶ自己検査はここを通らないので網羅へ混入しない）

    契約の要点は決 92 と決 95 に書いた（6 観測点・集合の完全一致・3 回実行・`B ∩ G = ∅`・同期的な
    完了）。`clean=False` は「見張り番を消すと対象の診断は消えるが、実行は別の診断で拒否される」制御が
    使える（Astra 第 59 ラウンド 問 2）。その場合は `fallback` に **OFF 後も残る別の診断の文面**を
    書く（第 56 ラウンド agy P2-3）
    """
    ran['negative'] += 1
    names = (guards,) if isinstance(guards, str) else tuple(guards or ())
    out = []
    try:
        tier, base_empty = _run_negative(name, fn, names, message, clean, fallback, out)
    finally:
        # 実行器が積んだ失敗は、登録の段で何が起きても失敗記録へ残す
        failed.extend(out)
    if tier and len(names) == 1 and base_empty:
        # 網羅を数えるのは、ソースに書いてある制御ではなく**通った**単独名指しだけ（Astra 第 59
        # ラウンド 問 4。第 60 ラウンド 問 3 で後勝ち上書きをやめ、名前ごとに全部残す）。第 69
        # ラウンド 問 1 で**開始集合が空の実行だけ**を数える
        ran['singleton'].setdefault(names[0], []).append((name, tier))


def positive(name, fn):
    """正控制（第 61 ラウンド Astra 問 1 の裁定 (a)。戻り値も失敗に数える）

    契約:

    - 正常時は `None` を返す（偽になる値までは問わない）
    - **真になる戻り値は失敗**として `failed` に入れる。第 60 ラウンドまで戻り値を捨てており、
      失敗を文字列で返す形で書かれた控制が常に素通りしていた（Codex P2-2 / agy P2-1）
    - `failed.append` で複数件を出す控制はそのままとする
    - `NotDetected` は控制側の不成立、`SystemExit` は予定外の終了、その他例外は控制の故障
    - 子プロセスの結果を返してはいけない（`(0, '出力')` は真なので失敗になる。終了コードは
      控制の側で自分で判定する）

    負控制の `_run_control()` は共用しない。正と負では戻り値の意味が違い（正のエラー文字列は
    その控制の失敗、負の非 0 終了は対象の診断の検出成功）、共用すると「制御が故障した」と
    「控制が失敗を返した」の区別が潰れる（Astra 問 1）"""
    ran['positive'] += 1
    try:
        res = fn()
    except (NotDetected, SystemExit) as e:
        failed.append(f'{name}: 通らなければならないのに落ちた: {str(e)[:200]}')
        return
    except Exception as e:  # noqa: BLE001 - 正控制は例外も失敗
        failed.append(f'{name}: 通らなければならないのに例外: {type(e).__name__}: {e}')
        return
    if res:
        failed.append(f'{name}: 正控制が失敗を返した（正常時は `None` を返す契約）: {str(res)[:200]}')


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


def cond_graph_hash_rekeyed():
    """`graph` に `#` を混ぜ、id と条件別の期待値のキーまで作り直す（`cond-shape` だけを測る）

    第 58 ラウンド agy P2-1 の系で、`cond-shape` を名指した 3 本はすべて他の見張り番と組だった。
    素で `#` を足した細工は id が割れて `canonical-id` が手前に落ちるため、同じ中身から id を
    計算し直し、`invariantRows` と `parentChild` の条件別のキーも揃える（Astra 第 59 ラウンド
    問 1 の実測レシピ。キーを揃えないと `cov-keys` が落ちる）。そうすると `cond-shape` だけが
    落ち、スイッチを消した実行は通る"""
    spec = spec_copy()
    cond = spec['conditions'][3]
    old = cond['id']
    cond['graph'] = cond['graph'] + '#表示の残り'
    cond['id'] = IN.condition_id(IN.condition_key(cond.get('case'), cond['graph'],
                                                  cond['kind'], cond['args']))
    for key in ('invariantRows', 'parentChild'):
        by = spec['expectations'][key]['byCondition']
        if old in by:
            by[cond['id']] = by.pop(old)
    IN.validate_required_spec(spec, REPO)


def _rekey(spec, old_id, new_id):
    """条件の id が変わるとき、条件別の期待値のキーも揃える（`cov-keys` が先に落ちるため）"""
    for key in ('invariantRows', 'parentChild'):
        by = spec['expectations'].get(key, {}).get('byCondition', {})
        if old_id in by:
            by[new_id] = by.pop(old_id)


def _reid(spec, cond):
    """条件の中身から id を作り直して書き戻す（素で壊すと `canonical-id` が手前に落ちる）"""
    old = cond['id']
    cond['id'] = IN.condition_id(IN.condition_key(cond.get('case'), cond['graph'],
                                                 cond['kind'], cond['args']))
    _rekey(spec, old, cond['id'])


def cond_keys_extra_field():
    """条件オブジェクトに無い欄を 1 つ足す（`cond-keys` だけを測る）

    id は `case` / `graph` / `kind` / `args` の 4 欄から作る細工なので、余分な欄を足しても
    `canonical-id` は割れない。第 60 ラウンドまで `cond-shape` の 1 個だった箇所"""
    spec = spec_copy()
    spec['conditions'][3]['note'] = '表示の残り'
    IN.validate_required_spec(spec, REPO)


def cond_case_not_string():
    """条件の `case` に文字列以外を置く（`cond-case` だけを測る。Astra 問 2 の実測レシピ）

    Astra が A 案（スイッチの読みを 1 箇所へまとめる）の弱点として示した入力その物で、
    `case = 1` は型判定の 1 個だけを無力化すると通ってしまう。細工は id も同じ中身から作り直す"""
    spec = spec_copy()
    cond = spec['conditions'][3]
    cond['case'] = 1
    _reid(spec, cond)
    IN.validate_required_spec(spec, REPO)


def cond_args_not_strings():
    """条件の `args` の 1 つを数値にする（`cond-args` だけを測る）

    第 61 ラウンド Astra 問 3 の裁定どおり **id は据え置く**（型が不正な条件は正準形を計算しない
    ので `_reid()` は不要。計算を呼べば不正な引数が観測される）。見張り番を消した実行はこの
    条件の後続計算が飛ぶだけで他に何も出ない（`clean` の側）"""
    spec = spec_copy()
    cond = spec['conditions'][26]   # audit-full（`--hops 3 ...` の 3 を数値にする）
    cond['args'] = list(cond['args'])
    cond['args'][1] = int(cond['args'][1])
    IN.validate_required_spec(spec, REPO)


def cond_args_not_a_list():
    """条件の `args` 自体を数値にする（`cond-args` だけを測る。第 60 ラウンド Codex P2-3）

    第 60 ラウンドまでは `[str(a) for a in args]` が `TypeError: 'int' object is not iterable`
    を出し、`fail_required_spec` の共通見出しの代わりに traceback で落ちていた。今は型診断を
    出してその条件の後続計算を飛ばす"""
    spec = spec_copy()
    spec['conditions'][26]['args'] = 123
    IN.validate_required_spec(spec, REPO)


def cond_args_is_null():
    """条件の `args` を `null` にする（`cond-args` だけを測る。第 60 ラウンド agy P2-2）

    `c.get('args') or []` は `null` を空配列に潰して型検査を発火させず、`cond-args` と
    `cond-kind-args` を消した実行がそのまま通っていた。値の無い `args` に正準形は無い"""
    spec = spec_copy()
    spec['conditions'][26]['args'] = None
    IN.validate_required_spec(spec, REPO)


def cond_kind_out_of_range():
    """条件の `kind` を値域外へ変える（`cond-kind-args` だけを測る）"""
    spec = spec_copy()
    cond = spec['conditions'][3]
    cond['kind'] = 'no-such-kind'
    _reid(spec, cond)
    IN.validate_required_spec(spec, REPO)


def perm_expected_not_matched():
    """走った縁順の通り数が宣言と違う（`perm-expected` だけを測る。第 60 ラウンドの分割で生まれた名）

    `ran` が順列の通り数その物と一致するなら `perm-count` は黙るので、宣言だけ 7 件に違わせる。
    CLI 経由では組み立てる側が壊れないと作れない形なので、判定関数を直接呼ぶ（Astra 問 2 の
    「関数を直接呼ぶ制御などで短縮して構いません」）"""
    IN.permutation_guards(3, 6, 7, '制御')


def perm_count_mismatch():
    """走った縁順の通り数が順列の本数と違う（`perm-count` だけを測る）

    第 60 ラウンドの分割で「走る前の宣言との食い違い」（`perm-declared`）と「走った後の宣言との
    食い違い」（`perm-expected`）が別名になったので、**順列の本数その物と違う**判定だけの制御を
    分ける。縁 3 本の順列は 6 通りなので、そこへ 5 件を渡す"""
    IN.permutation_guards(3, 5, None, '制御')


def run_json_non_json_output():
    """終了 0 で JSON でない文字列を書く実行（`json-parse` だけを測る。共有の `run_json`）

    第 60 ラウンドまで `edge-order.py` 自身の物と名前を分かっていたので、共有側にも単独名指しが
    要る。`expect_report=False` で読んだ後の形の検査（`report-shape`）を退けて、この判定だけを測る"""
    bad = TMP / 'not-json.mjs'
    bad.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1], 'レポートではなく本文の書き出し');
""", encoding='utf-8')
    IN.run_json(str(bad), [], tmp_out('not-json'), REPO, label='制御', expect_report=False)


def sampled_runs_single():
    """間引き後に 1 とおりしか走らない比較（`perm-runs-min` だけを測る）

    CLI 経由では `r43-permute.py` の試行 1 とおりが `trial-count` に、`allperm-full.py` の上限 1 が
    `perm-cap` に先へ拾われる（実測）。関数を直接呼んでこの判定だけを測る"""
    IN.require_sampled_runs(1, '制御', cap=5)


def fixture_missing_from_spec():
    """要求一覧の `fixtures` から 1 本消す（`fixture-set` だけを測る。条件はそのまま）

    実体は glob で見つかるので「fixture が有るのに要求一覧に無い（走らない検査になる）」で止まる。
    id・条件・期待値を触らないので `canonical-id` も重複検査も `cov-keys` も素通りし、スイッチを
    消した実行は通る（第 58 ラウンド agy P2-1 で名指しが無かった 6 個のうちの 1 つ）"""
    spec = spec_copy()
    spec['fixtures'] = spec['fixtures'][1:]
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
        subprocess.run(['node', EMPTY_STUB, *argv, '--json', str(d / p.name)], env=IN.guard_env(),
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


def dir_rule_counters_rebalanced():
    """v1 の期待カウンタを 1 ずつ入れ替える（`dir-rule-counters` だけを測る）

    実測: `dir-rule-counters` を名指した 2 本はどちらも `dir-rule-report` と組で、組の手前に
    遮われて単独では測れていなかった。合計が実測と同じになるよう `agree` を 1 減らし `bad` を
    1 増やす（レポート別と v1 の中身照合はそのまま。Astra 第 59 ラウンド 問 1 の実測レシピ）。
    他の見張り番は素通りし、スイッチを消した実行は通る"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    exp = doc['expectations']['dirRule']['v1']
    if exp['agree'] < 1:
        raise NotDetected('v1 の一致の期待値が 1 未満（この制御は 1 減らす前提で組む）')
    exp['agree'] -= 1
    exp['bad'] += 1
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    try:
        return py('check-dir-rule.py', '--profile', 'v1')
    finally:
        restore()


def dir_rule_report_swapped():
    """実在する 2 本のレポートの比較件数を入れ替えた一覧（キー集合も合計もそのまま）

    前の形（実在しないレポート名 1 本に合計を寄せる）は第 60 ラウンドの入口の共通検査で
    `cov-keys` が先に落とすので、`check-dir-rule.py` の**レポート別**の照合を測れなくなった
    （実測: 「expectations.dirRule.current.byReport にレポート名が無い」で止まった）。
    Astra 第 60 ラウンド 問 1 の裁定どおり、形の検査を通る不一致にして道具自身の比較を測る"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    by = doc['expectations']['dirRule']['current']['byReport']
    names = sorted(by)
    pair = next(((x, y) for i, x in enumerate(names) for y in names[i + 1:] if by[x] != by[y]), None)
    if pair is None:
        raise NotDetected('byReport の件数がすべて同じ一覧では入れ替えで何も変わらない')
    x, y = pair
    by[x], by[y] = by[y], by[x]
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
    Astra 裁定 問 1 ③で要素の**型**を `fixture-shape` に分ける。見張り番を消した実行は、その値が
    集合比較に入る前に落ちる（Astra 第 59 ラウンド 追加穴 2 の実測で `fixtures[0] = {}` が型の
    診断のあとで `set(fx)` に投げられていた）。結果として 1 本欠けた一覧と同じ形になり、
    `fixture-set` が「fixture が有るのに要求一覧に無い」で止める（`fallback` で宣言）"""
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
    `perm-cap`（実際に走った本数）が別の診断で拾う"""
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


def fingerprint_bytes_moved():
    """台帳の**バイト数**だけを 1 件書き換える（`fp-bytes` だけを測る。第 58 ラウンド agy P2-1）

    `fp-sha` → `fp-bytes` → `fp-mode` は elif で繋がっていて、中身を変えると常に `fp-sha` が手前に
    落ちる。agy 実測: `fp-bytes` を `and False:` に完全無力化しても `test-contract.py` は終了 0
    だった（名指しは `guards=('fp-sha', 'fp-bytes')` の 1 本だけで、組の手前に遮われていた）。
    sha と mode を据え置いたまま `bytes` だけ書換えれば `fp-bytes` が単独で落ち、
    スイッチを消した実行は通る（`fp-mode` は実測の読み方と比べるので割れない）"""
    victim = _any_scope_input()
    p = stash(LEDGER)
    data = json.loads(p.read_text(encoding='utf-8'))
    rec = data[IN.CONTENTS][victim]
    if rec.get('mode') not in ('json', 'bytes'):
        raise NotDetected(f'{victim} の台帳の読み方が json / bytes でない（この制御の前提が変わった）')
    rec['bytes'] = int(rec.get('bytes', 0)) + 1
    p.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    bad = IN.require_fingerprints(REPO)
    restore()
    return (0 if not bad else 1), '\n'.join(bad)


def launch_conditions_broken_ledger():
    """要求一覧の `fixtures` を壊して**起動条件を組み立てる**（第 58 ラウンド agy P2-2）

    `IN.launch_conditions()` は要求一覧を読む前に形を検査するようになった。実測: 前は
    `required_fixtures()` が先で、入口で検証を呼ぶ `check-battery-inputs.py` だけが案内を出せ、
    `check-invariants46.py` / `self-consistency.py` は `KeyError` の生の traceback になっていた。
    `fixture-shape` を消した実行は同じ入口の `fixture-set`（実体は有るのに一覧に無い）が
    同じ「要求一覧が壊れている」案内で止める。`required_fixtures()` まで到達しないので
    traceback にはならない（`fallback` にはその別の診断の文面を書く）"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    spec = json.loads(p.read_text(encoding='utf-8'))
    spec['fixtures'][0] = 1
    p.write_text(json.dumps(spec, ensure_ascii=False), encoding='utf-8')
    try:
        IN.launch_conditions(REPO)
    finally:
        restore()
    raise NotDetected('壊れた要求一覧で起動条件が組み上がってしまった（何も言わなかった）')


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
    消した実行は `fp-mode` が別の診断で拾う（`fallback` で宣言する）"""
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

    消した実行は stdout が空なので `json-parse` が別の診断で拾う（`fallback` で宣言）"""
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

    消した実行は `d = {}` になって形検査 `edge-order-groups` が別の診断で拾う"""
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
    """正当な 0 行レポート 4 本は形として通る（一律「0 行は違反」にしない。Astra 裁定 問 4）

    第 61 ラウンド Astra 問 1 のとおり **何も返さない**（検査した名前の一覧を返していたが、
    第 60 ラウンドまで `positive()` は戻り値を捨てていたため無害に見えていた。戻り値を
    失敗に数える契約にすると毎回落ちる）"""
    legit = ['demo-readme.json', 'elsa-1.json', 'elsa-folder.json', 'real-tf.json']
    for name in legit:
        doc = json.loads((HERE / 'baseline-v1' / name).read_text(encoding='utf-8'))
        IN.validate_report(doc, f'制御 {name}')
        if doc['summary']['rows'] != 0:
            failed.append(f'{name} は 0 行では無くなった（正控制の前提が変わった）')


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


def broken_required_ledger_same_message():
    """要求一覧の `fixtures` キーを消して 2 本の道具を走らせる（第 58 ラウンド agy P2-2）

    壊れた一覧を検査する入口は `guard()` を通らない（**条件を組み立てる前に**拒否する前提なので、
    消せる見張り番にしない）。だから `negative` では測れず、ここで測るのは Astra 第 59 ラウンド
    問 3 の **同じ案内を両方の道具が出す**こと。前は `check-battery-inputs.py` だけが案内を出せ、
    `check-invariants46.py` / `self-consistency.py` は `KeyError: 'fixtures'` の traceback だった"""
    rel = f'{BATTERY}/required-checks.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    if 'fixtures' not in doc:
        raise NotDetected('要求一覧に fixtures が無い（制御の前提が変わった）')
    del doc['fixtures']
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    head = '要求一覧（required-checks.json）が壊れている'
    report = REPO / 'skill' / 'scripts' / 'report.mjs'
    try:
        for tool in ('check-invariants46.py', 'self-consistency.py'):
            rc, out = py(tool, report)
            if head not in out:
                failed.append(f'{tool} が壊れた要求一覧で「{head}」を出さない: {out[:160]}')
            if 'Traceback (most recent call last)' in out or 'KeyError' in out:
                failed.append(f'{tool} が壊れた要求一覧で生の traceback を出した: {out[:160]}')
            if '--measured' not in out:
                failed.append(f'{tool} の案内に作り直しのコマンド（`--measured`）が無い: {out[:160]}')
            if rc == 0:
                failed.append(f'{tool} が壊れた要求一覧で終了 0（通ってはいけない）')
    finally:
        restore()


def _known_diffs_break(mutate=None, text=None, kind='row'):
    """既知差分（`known-v1-diffs.json`）を壊して `expected_direction_diffs` を通す（Astra 第 61 ラウンド 問 3 の追記）

    導出関数だけを見るので v1 のレポートは走らせない。壊した一覧からの再生成は人の判断なので、
    ここで自動更新はしない（`v1diff.py --emit-known` は候補を出すだけの道具）"""
    p = stash(f'{BATTERY}/known-v1-diffs.json')
    doc = json.loads(p.read_text(encoding='utf-8'))
    rows = [i for i, d in enumerate(doc['diffs']) if isinstance(d, dict) and d.get('kind') == kind]
    if not rows:
        raise NotDetected(f'既知差分に kind が {kind} の行が無い（この制御の前提が変わった）')
    body = text
    if mutate is not None:
        mutate(doc, rows[0])
        body = json.dumps(doc, ensure_ascii=False, indent=1) + '\n'
    p.write_text(body, encoding='utf-8')
    try:
        IN.expected_direction_diffs()
    finally:
        restore()


def known_old_is_dict():
    """既知差分の `old` を空辞書にする（`d.get('old') or []` は空辞書を真偽値化して `KeyError: 0` になっていた。第 60 ラウンド Codex P2-3）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('old', {}))


def known_old_is_string():
    """既知差分の `old` に文字列を入れる（文字列の添字で `['a', 'b']` が読めて化けた値が導出へ渡る）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('old', 'abc'))


def known_old_is_null():
    """既知差分の `old` を null にする（`or []` が化けないので短さの検査へ回る）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('old', None))


def known_old_too_short():
    """既知差分の `old` を 1 要素に切る（欄と向きを読む側の検査）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('old', ['欄']))


def known_old_field_not_str():
    """既知差分の `old` の欄を数値にする（文字列として扱われる前提）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__(
        'old', [1, 'up', 'dir', 2, 'edge']))


def known_old_tail_not_str():
    """[欄, 向き] より後ろの欄（階層・縁数・縁）だけが壊れた行も形として止める

    導出は 0 番地と 1 番地しか読まないが、後ろの欄が `null` や辞書になる壊れ方は台帳を人が
    書き換えた証拠なので、読む欄だけでなく全欄の型を見る。ただし**縁数は実測で数値**なので
    「すべて文字列」にはしない（そうすると正常な一覧が 116 件壊れたことになる。第 61 ラウンドの実測台帳（追跡下の道具からは読まない測定結果））"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__(
        'old', ['a', 'up', 'dir', 2, None]))


def known_old_key_missing():
    """既知差分から `old` の欄を消す"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].pop('old'))


def known_kind_unknown():
    """既知差分の `kind` を値域外へ変える（`row` / `summary` 以外は形として止める。第 62 ラウンド agy P2-3）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('kind', 'roww'))


def known_kind_missing():
    """既知差分から `kind` を消す（無い行は導出側で黙って `row` 扱いにならない）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].pop('kind'))


def known_cond_blank():
    """既知差分の `cond` を空白だけにする（空の条件名で人が条件を探せない。第 62 ラウンド agy P2-3）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('cond', '   '))


def known_cond_not_str():
    """既知差分の `cond` を数値にする"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('cond', 3))


def known_id_not_str():
    """既知差分の `id` を数値にする（`id` で台帳を引く側の前提）"""
    _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('id', 3))


def known_summary_old_negative():
    """既知差分の `summary` 行の `old` を負数にする（`summary` は件数を出す行なので 0 以上）"""
    _known_diffs_break(kind='summary',
                       mutate=lambda doc, i: doc['diffs'][i].__setitem__('old', -1))


def known_summary_new_bool():
    """既知差分の `summary` 行の `new` を真偽値にする（`True` は Python では整数だが件数ではない）"""
    _known_diffs_break(kind='summary',
                       mutate=lambda doc, i: doc['diffs'][i].__setitem__('new', True))


def known_diffs_not_list():
    """既知差分の `diffs` を辞書にする"""
    _known_diffs_break(mutate=lambda doc, i: doc.__setitem__('diffs', {'a': 1}))


def known_doc_is_list():
    """既知差分のトップレベルを配列にする"""
    _known_diffs_break(text='[1, 2]\n')


def known_json_broken():
    """既知差分を JSON として読めない形にする（生の `JSONDecodeError` にしない）"""
    _known_diffs_break(text='{"diffs": [\n')


def known_shape_stops_before_count():
    """既知差分の形が壊れた日が **55 件の件数診断より前**に止まる（Astra 第 61 ラウンド 問 3 の順序）"""
    try:
        _known_diffs_break(mutate=lambda doc, i: doc['diffs'][i].__setitem__('new', {}))
    except SystemExit as e:
        body = str(e.code)
        if IN.KNOWN_HEADER not in body:
            raise NotDetected(f'形の変化が「{IN.KNOWN_HEADER}」で止まらない: {body[:150]}')
        if '件のはず' in body:
            failed.append('既知差分の形が壊れた日に件数の診断が先に出た（形 → 導出 → 件数の順序が逆）')
        raise
    raise NotDetected('形が壊れた既知差分が通った（導出の前に止まらない）')


def _const_str(node):
    """AST のノードが文字列定数ならその値、そうでなければ None"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


_GUARD_NAME = 'guard'
_INPUTS_MODULE = '_inputs'
_INPUTS_FILE = '_inputs.py'
_DYNAMIC_LOOKUP = {'globals', 'locals', 'vars'}
_DYNAMIC_EXEC = {'exec', 'eval'}
_BANNED_BUILTINS = _DYNAMIC_LOOKUP | _DYNAMIC_EXEC | {'getattr', '__import__'}
_DYNAMIC_ATTRS = {'__dict__', '__globals__', '__class__'}
# agy 第 63 ラウンド P2-1: 禁止する機構を**裸の名前**でしか見ないと、`from builtins import exec as ex`
# や `import builtins; e = builtins.exec` で化ける（実測で穴 0 件・名前 0 件の素通り）
_DYNAMIC_MODULES = {'builtins', 'types', 'inspect', 'code', 'codeop'}
# 見張り番を動的に引く為の入口になる名前（`from 何か import これ` の形を穴にする）
_LOADER_NAMES = (_BANNED_BUILTINS | {'compile', 'import_module', 'FunctionType', 'make_function',
                                     'currentframe', 'getframe', 'f_locals', 'f_globals',
                                     'modules', '_getframe', 'f_builtins'})
# 何かの属性として読んだら穴になる名前（`builtins.exec` / `types.FunctionType` / `s.modules`）
_LOADER_ATTRS = _DYNAMIC_ATTRS | {'modules', 'import_module', 'FunctionType', 'make_function',
                                  'currentframe', 'getframe', 'f_locals', 'f_globals',
                                  '_getframe', 'f_builtins',
                                  # Codex 第 63 ラウンドの追加 probe: `object.__subclasses__()` と
                                  # `sys.__loader__` は上の名前一覧に無いので穴 0 件だった（第 64 ラウンド）
                                  '__subclasses__', '__bases__', '__mro__', '__loader__'}
# 走査対象のファイルが**豁免なしで import してよい**モジュール（Astra 第 64 ラウンド 問 1 裁定 (c)）
# 禁止リストの拡張では「何年持つという見積もりを置けない」との裁定で、許可する import を先に決める。
# ここに無い import は豁免台帳 `guard-owners.json` に「そのファイルで許す import と名前」として
# 人が登録した時だけ通る。豁免が通せるのは**未登録の import の禁止だけ**で、実行機構その物の
# 禁止（`_DYNAMIC_MODULES` と `_LOADER_NAMES`）と `guard` の再束縛の禁止は弱めない
# （`code.InteractiveInterpreter` と `os.system` が穴 0 件だった実測 → `code` / `codeop` は禁止側へ）
_ALLOWED_IMPORTS = frozenset({
    'argparse', 'ast', 'collections', 'glob', 'hashlib', 'itertools', 'json', 'os', 'pathlib',
    'random', 're', 'resource', 'shutil', 'statistics', 'subprocess', 'sys', 'tempfile', 'time',
})
# 見張り番の名前の字句規則（README の道具別一覧がバッククォートの中で読む形と**同じ規則**。
# Codex 第 62 ラウンド P2-3: 規則がずれると `new_guard` のような名前が「コードには有るのに
# README に無い」と誤診され、README 側の `bad_name` は黙って無視される）
_NAME_SHAPE = re.compile(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*')


def _bound_names(node):
    """代入の左辺に現れる名前（タプル・リスト・`*` を展開して返す）"""
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _bound_names(elt)
    elif isinstance(node, ast.Starred):
        yield from _bound_names(node.value)


def _pattern_names(node):
    """`match` のパターンが束縛する名前（agy 第 62 ラウンド P2-1 の `case IN:` 対策）"""
    if isinstance(node, ast.MatchValue) or isinstance(node, ast.MatchSingleton):
        return
    if isinstance(node, ast.MatchAs):
        if node.name:
            yield node.name
        if node.pattern is not None:
            yield from _pattern_names(node.pattern)
    elif isinstance(node, ast.MatchStar):
        if node.name:
            yield node.name
    elif isinstance(node, ast.MatchMapping):
        if node.rest:
            yield node.rest
    elif isinstance(node, ast.MatchOr):
        for p in node.patterns:
            yield from _pattern_names(p)
    elif isinstance(node, ast.MatchSequence):
        for p in node.patterns:
            yield from _pattern_names(p)
    elif isinstance(node, ast.MatchClass):
        for p in list(node.patterns) + list(node.kwd_patterns):
            yield from _pattern_names(p)


def _is_guard_ref(node, boxes):
    """その式が見張り番その物を指すか（裸の `guard`、または `_inputs` を指す箱の `.guard`）"""
    if isinstance(node, ast.Name):
        return node.id == _GUARD_NAME
    return (isinstance(node, ast.Attribute) and node.attr == _GUARD_NAME
            and isinstance(node.value, ast.Name) and node.value.id in boxes)


def _call_name(node):
    """呼び出しの関数名（`f(...)` なら `f`、`box.m(...)` なら `m`。それ以外は空文字）"""
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ''


def _bare_builtins(node):
    """式が**動的な機構その物**を値として束縛されうる形か（`e = exec` / `g, x = getattr, 1`）

    `rhs = getattr(node, 'value', None)` のように**呼び出した結果**を束縛するのは別物なので数えない
    （第 62 ラウンドで `ast.walk` を使った版は `test-contract.py` 自身の AST 読みを 3 件誤検出した）"""
    if isinstance(node, ast.Name) and (node.id in _BANNED_BUILTINS or node.id == 'compile'):
        return {node.id}      # `c = compile` は別名でも同じ機構（agy 第 63 ラウンド P2-1 の 2 番目）
    if isinstance(node, ast.Attribute) and node.attr in _BANNED_BUILTINS:
        return {node.attr}          # `e = builtins.exec` は別名でも同じ機構
    if isinstance(node, ast.Starred):
        return _bare_builtins(node.value)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        out = set()
        for elt in node.elts:
            out |= _bare_builtins(elt)
        return out
    if isinstance(node, ast.Dict):
        out = set()
        for val in node.values:
            out |= _bare_builtins(val)
        return out
    return set()


def _direct_refs(node, boxes):
    """式が**見張り番か箱その物**を値として含んでいるか（`IN2 = IN` / `a, b = guard, x` / `f(IN)`）

    関数の呼び出し結果は箱その物ではないので、その中は調べない（`REPO = IN.repo_root()` は正常
    な書き方。
    第 62 ラウンドで `ast.walk` をそのまま使った版はこれを 114 件の誤検出し、実ツリーで落ちた）"""
    if node is None:
        return False
    if _is_guard_ref(node, boxes) or (isinstance(node, ast.Name) and node.id in boxes):
        return True
    if isinstance(node, ast.Starred):
        return _direct_refs(node.value, boxes)
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_direct_refs(e, boxes) for e in node.elts)
    if isinstance(node, ast.Dict):
        return any(_direct_refs(v, boxes) for v in node.values if v is not None)
    if isinstance(node, ast.Call):
        return any(_direct_refs(a, boxes) for a in node.args)
    return False


def _dotted(node):
    """純粋な属性連鎖 `a.b.c` を `(根の名前, ["b", "c"])` に崩す（壊れた形は None）

    Astra 第 66 ラウンド 問 2 の裁定で、豁免由来の束縛が「どの経路を読んでいるか」を決める為に
    使う（`t = importlib.util` の様な受け渡しは崩れないので穴側になる）"""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name) or not parts:
        return None
    return node.id, list(reversed(parts))


def _expr_text(node):
    """診断に出す式の短い名前（`IN` / `repo_root` / 型名）"""
    return getattr(node, 'id', None) or getattr(node, 'attr', None) or type(node).__name__


def _is_inputs_module(name):
    """`_inputs` もしくは `何か._inputs` というモジュール名か"""
    return name == _INPUTS_MODULE or name.endswith('.' + _INPUTS_MODULE)


def _collect_boxes(tree, origin, exempt=None, switches=None):
    """見張り番の入った箱（`import _inputs as IN` の `IN`）を**最初に**集める（Astra 問 1 の二段階）

    第 61 ラウンドまでは import の収集と束縛の検査が 1 巡目の中に入っていた為、入れ子の import
    より先に束縛を見る順序だと箱を知らないまま素通りした（Astra 実測: `import battery._inputs`、
    `from battery import _inputs as X`、`import math as IN`）。許可する import の形は
    **`import _inputs`（`as` での改名は可）だけ**で、それ以外の形は箱にせず穴にする

    `exempt` は台帳 `guard-owners.json` の豁免を展開した `モジュール名 -> 許す名前の集合`
    （Astra 第 63 ラウンド 問 1 の裁定: 豁免は**名乗った import と名前だけ**を許す）。許した
    モジュールでも `exec` / `FunctionType` の様な動的機構の名前は上の名前一覧で穴のまま

    `switches` は `_guard_scan` が 1 箇所ずつ読んだ見張り番の読み方（`名前 -> 真偽`）。ここで
    `IN.guard(...)` を直接呼ぶと同じ名前を 2 箇所で呼ぶことになり、単独名指しの規則に当たる"""
    exempt = exempt or {}
    switches = switches or {}
    sw_binds_guard = switches.get('import-binds-guard', True)
    sw_unregistered = switches.get('import-unregistered', True)
    sw_granted = switches.get('import-granted', True)
    sw_star = switches.get('import-star', True)
    boxes, holes, tainted, allowed = set(), [], set(), {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                parts = a.name.split('.')
                root = parts[0]
                bound = a.asname or root
                granted = exempt.get(a.name, frozenset())
                # Astra 第 66 ラウンド 問 1 の裁定: 豁免は「完全修飾モジュール × 末端名」で持つ。
                # 自分の名前の登録が無くても、**その先が登録されている**なら末端へ進む中継として
                # 通す（`importlib.util.spec_from_file_location` が登録済みなら `import
                # importlib.util` は中継で可。`import importlib.util.machinery` は登録が無い）
                relay = any(k.startswith(a.name + '.') for k in exempt)
                # Astra 第 65 ラウンド 問 2 裁定: 見張り番と同じ名前を束縛する import は
                # `_inputs` の実体でも穴（`import _inputs as guard` + `guard('fake')` が架空の
                # 見張り番を網羅へ数えた。裸の `guard(...)` は `_inputs.py` の `def guard` だけ）
                if bound == _GUARD_NAME:
                    if sw_binds_guard:
                        holes.append(f'{origin}:{node.lineno} 見張り番と同じ名前「{_GUARD_NAME}」を'
                                     f'モジュール「{a.name}」から import している（`guard(...)` が'
                                     '誰の呼び出しなのか静的に決まらない。豁免した import、'
                                     '`import _inputs as guard` も同じ。Codex 第 62 ラウンド P2-2 / '
                                     'Astra 第 65 ラウンド 問 2）')
                    tainted.add(bound)
                    continue
                if root in _DYNAMIC_MODULES or root == 'importlib':
                    # Astra 第 66 ラウンド 問 1 裁定: 豁免は**完全修飾モジュール × 末端名**の経路で
                    # だけ効く。`importlib.util: ["spec_from_file_location"]` は `importlib.machinery`
                    # を通さず、`importlib.util` は末端へ進む中継としてだけ通る
                    if a.name not in exempt and not relay:
                        if sw_granted:
                            holes.append(f'{origin}:{node.lineno} 豁免台帳に登録していない '
                                         f'`import {a.name}`（このファイルの登録済み経路: '
                                         f'{"、".join(sorted(exempt)) or "無し"}。豁免は完全修飾の'
                                         'モジュール名か、その先の末端名まで登録された経路の中継として'
                                         'だけ通る。Astra 第 66 ラウンド 問 1）')
                        tainted.add(bound)
                        continue
                    if relay and switches.get('import-dynamic-module', True):
                        # Astra 第 67 ラウンド 問 1 の裁定: 根だけの束縛（`import importlib`）は
                        # 豁免でも通さない。第 67 ラウンド双人レビューでは `a.name not in exempt` が
                        # 残っており、`importlib: ["invalidate_caches"]` の様な形の通る根名登録で
                        # 素通りできた（Codex P2-1）。ここでは豁免を一切見ない。案内から
                        # 「豁免台帳へ登録すれば可」を撤回した（登録の
                        # 単位は末端までの経路なので、根を束縛する import は登録では解消しない）。
                        # 正当な形は `import importlib.util` の様に末端まで書くこと
                        holes.append(f'{origin}:{node.lineno} 動的な機構のモジュール「{a.name}」を'
                                     f'「{bound}」へ import している（`{bound}.exec` / '
                                     f'`{bound}.FunctionType` 経由で見張り番を呼べるので、この'
                                     'ファイルの網羅が保証できない。根だけの束縛は豁免でも通さない '
                                     '（末端までの経路を書くこと）。Astra 第 67 ラウンド 問 1）')
                        tainted.add(bound)
                        continue
                    # 束縛される名前の**経路**を覚える（`import a.b` は `a` を束縛するので経路は `a`、
                    # `import a.b as x` の `x` の経路は `a.b`）。後段の利用検査が末端までの直接呼び出し
                    # だけを通す
                    allowed[bound] = a.name if a.asname else root
                    continue
                if _is_inputs_module(a.name):
                    if a.asname is None and '.' in a.name:
                        holes.append(f'{origin}:{node.lineno} `import {a.name}` は別名を付けないと'
                                     f'「{bound}」に束縛される（見張り番の箱が静的に決まらない。'
                                     f'`import {a.name} as IN` の形にすること）')
                        continue
                    boxes.add(bound)
                    continue
                if root not in _ALLOWED_IMPORTS and a.name not in exempt and not relay:
                    if sw_unregistered:
                        holes.append(f'{origin}:{node.lineno} 未登録の import「{a.name}」'
                                     f'（走査対象のファイルが豁免なしで import してよいのは '
                                     f'{"、".join(sorted(_ALLOWED_IMPORTS))} だけ。他は '
                                     f'{IN.GUARD_LEDGER_FILE} に「そのファイルで許す import と名前」を'
                                     '人が登録する。Astra 第 64 ラウンド 問 1 裁定 (c)）')
                    tainted.add(bound)
                    continue
                # 豁免で入れた import は**由来が追える束縛**なので、利用位置の検査が掛かる
                # （許可一覧に有る import は豁免ではないので対象にしない。Astra 第 66 ラウンド）
                if root not in _ALLOWED_IMPORTS:
                    allowed[bound] = a.name if a.asname else root
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if node.level and switches.get('import-relative', True):
                # Codex 第 66 ラウンド P1-1 の実測: `from .importlib.util import
                # spec_from_file_location` が `ImportFrom.level` を無視して照合した為、標準の
                # `importlib.util` の豁免で穴 0 件だった。Astra 第 67 ラウンド 問 1 の裁定 (ア) で
                # 相対 import は**許可一覧・豁免・`_inputs` の特別扱いより先に**穴にする（豁免も
                # 許可一覧も完全修飾モジュール名で持つので、所属パッケージの決まらない名前とは
                # 照合できない。走査対象は単一ディレクトリのスクリプトで絶対 import を使う）
                holes.append(f'{origin}:{node.lineno} 相対 import「{"." * node.level}{mod}」は穴'
                             '（豁免も許可一覧も**完全修飾モジュール名**で持つ為、所属パッケージが'
                             '静的に決まらない相対 import は照合できない。`skill/scripts/tools/` 直下の'
                             '単一ディレクトリなので絶対 import を使うこと。Astra 第 67 ラウンド 問 1）')
                tainted.update(a.asname or a.name for a in node.names)
                continue
            if any(a.name == '*' for a in node.names):
                # Astra 第 65 ラウンド 問 2 裁定: `from <任意> import *` は許可一覧・豁免より先に
                # 拒否する（`from sys import *` が `modules` の様な禁止名を束縛して、`getattr(
                # modules['_inputs'], 'gua' + 'rd')('hidden')` が穴 0 件だった）。実ツリー 24 本で
                # `import *` は 0 件（Astra 実測）
                if sw_star:
                    holes.append(f'{origin}:{node.lineno} `from {mod or "<空>"} import *` は'
                                 '束縛される名前が静的に決まらない（`modules` / `exec` の様な禁止名を'
                                 '別名なしで持ち込める。Astra 第 65 ラウンド 問 2）')
                tainted.update(a.asname or a.name for a in node.names)
                continue
            if _is_inputs_module(mod):
                got = '、'.join(sorted('*' if a.name == '*' else (a.asname or a.name)
                                       for a in node.names))
                holes.append(f'{origin}:{node.lineno} 見張り番の入ったモジュールを '
                             f'`from {mod} import {got}` で開いている（取り出し先の呼び出しは'
                             'このファイルの網羅から見えない。`import _inputs as IN` の形にすること。'
                             '`from _inputs import *` も同じ理由で穴。Astra 第 62 ラウンド 問 1）')
                tainted.update(a.asname or a.name for a in node.names if a.name != '*')
                continue
            # 豁免は `from <完全修飾モジュール> import <末端名>` の形で照合する（agy 第 65
            # ラウンド P2-1: 根だけ見て名前の照合をしていた為、`urllib.request` の登録が
            # `from urllib.evil import urlopen` を通していた）
            granted = exempt.get(mod, frozenset())
            for a in node.names:
                root = mod.split('.')[0]
                bound = a.asname or a.name
                # Astra 第 64 ラウンド 問 2 裁定 (ii): 豁免の import でも見張り番の名前を束縛できない
                # （`from builtins import bool as guard` が豁免で通って `guard('fake')` を数えた実測）
                if bound == _GUARD_NAME:
                    if switches.get('import-binds-guard', True):
                        holes.append(f'{origin}:{node.lineno} 見張り番と同じ名前「{_GUARD_NAME}」を'
                                     f'「{mod}」から import している（`guard(...)` が誰の呼び出しなのか'
                                     '静的に決まらない。豁免した import でも同じ。Codex 第 62 ラウンド'
                                     ' P2-2 / Astra 第 64 ラウンド 問 2）')
                    tainted.add(bound)
                    continue
                # Astra 第 64 ラウンド 問 2 裁定 (i): 実行・取り出しの機構その物の名前は豁免で許さない
                # （豁免の判定が先に `continue` して `from types import FunctionType` が通った実測）
                if a.name in _LOADER_NAMES:
                    holes.append(f'{origin}:{node.lineno} 動的な機構「{a.name}」を「{bound}」へ'
                                 '別名で import している（`from importlib import import_module as im` '
                                 'のような書き方は呼び出し名が化けて網羅から見えない。豁免でも許さない。'
                                 'agy / Codex 第 63 ラウンド P2-2）')
                    tainted.add(bound)
                    continue
                if root in _DYNAMIC_MODULES or root == 'importlib':
                    if a.name not in granted:
                        holes.append(f'{origin}:{node.lineno} 動的な機構のモジュール「{mod}」から '
                                     f'「{a.name}」を import している（`from builtins import exec as ex` は'
                                     '別名でも同じ機構。別名経由の実行・取り出しはこのファイルの網羅から'
                                     '見えない。agy 第 63 ラウンド P2-1）')
                        tainted.add(bound)
                        continue
                elif root not in _ALLOWED_IMPORTS and a.name not in granted:
                    if switches.get('import-unregistered', True):
                        holes.append(f'{origin}:{node.lineno} 未登録の import「{mod}」（`from {mod} import` '
                                     f'の形。走査対象のファイルが豁免なしで import してよいのは '
                                     f'{"、".join(sorted(_ALLOWED_IMPORTS))} だけ。他は '
                                     f'{IN.GUARD_LEDGER_FILE} に人が登録する。'
                                     'Astra 第 64 ラウンド 問 1 裁定 (c)）')
                    tainted.add(bound)
                    continue
                if a.name == _INPUTS_MODULE:
                    holes.append(f'{origin}:{node.lineno} `from {mod} import {a.name}` の形は'
                                 '許可していない（見張り番の箱は `import _inputs as IN` でだけ手に入る）')
                    tainted.add(bound)
                    continue
                # 豁免で入れた `from` の束縛は登録した経路その物（`from importlib.util import
                # spec_from_file_location` の `spec_from_file_location` の経路は
                # `importlib.util.spec_from_file_location`）
                if mod in exempt:
                    allowed[bound] = f'{mod}.{a.name}'
    # 二段階の 2 巡目: 別のモジュールが箱と同じ名前を束縛していると、`IN.guard(...)` が
    # 見張り番かどうか静的に決まらない（Astra 第 62 ラウンド 問 1 の `import math as IN`）
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            binds = [(a.asname or a.name.split('.')[0],
                      _is_inputs_module(a.name) and (a.asname is not None or '.' not in a.name))
                     for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            binds = [((a.asname or a.name), False) for a in node.names if a.name != '*']
        else:
            continue
        for bound, ok in binds:
            if bound in boxes and not ok:
                holes.append(f'{origin}:{node.lineno} 見張り番の箱と同じ名前「{bound}」を別の物が'
                             '束縛する import（`import _inputs as IN` と `import math as IN` が並ぶと、'
                             '`IN.guard(...)` が見張り番かどうか静的に決まらない）')
                tainted.add(bound)
    return boxes, holes, tainted, allowed


def _guard_symbols(tree, boxes, origin, top_guard):
    """見張り番の読み方を壊す束縛・定義・差し替えを調べる（箱は `_collect_boxes` が先に集める）

    Astra 第 61 ラウンド 問 2 のとおり「呼び出されるか」まで追う解析はしない。**見張り番の入った
    名前を別のに束縛する形その物**を穴にする（呼び出しの実体が静的に決まらない為）。第 62 ラウンド
    問 1 で「箱を右辺にする束縛」「`.guard` への代入と削除」「見張り番の実体や箱の名前を別のに
    束縛する `def` / `class`」「`match` のパターン」まで広げた。戻り値は（穴の列、**汚れた名前の
    集合**）で、汚れた名前とは「このファイルの中で見張り番の実体で無い物が束縛された名前」のこと
    （Astra 第 62 ラウンド 問 1: 差し替えられた箱からの呼び出しは集計しない）"""
    holes, tainted = [], set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == _GUARD_NAME \
                and isinstance(node.ctx, (ast.Store, ast.Del)):
            holes.append(f'{origin}:{node.lineno} 見張り番「{_expr_text(node.value)}.{_GUARD_NAME}」を'
                         '代入・削除で差し替えている（見張り番の実体は `_inputs.py` の'
                         ' `def guard` だけ。差し替えた先の呼び出しは網羅の分母に入れない）')
            if isinstance(node.value, ast.Name):
                tainted.add(node.value.id)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = set()
            for tgt in targets:
                names |= set(_bound_names(tgt))
            rhs = getattr(node, 'value', None)
            handed = _direct_refs(rhs, boxes)
            for nm in names:
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の入った名前「{nm}」へ別のを'
                                 '束縛する（呼び出しの実体が静的に決まらない）')
                elif handed:
                    holes.append(f'{origin}:{node.lineno} 見張り番かその入った箱を「{nm}」へ'
                                 '別名として束縛する（`IN2 = IN` の別名経由の呼び出しは'
                                 'このファイルの網羅から見えない。Codex / agy 第 62 ラウンドの実測）')
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            for nm in _bound_names(node.target):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」をループ変数に束縛する')
        elif isinstance(node, ast.NamedExpr):
            for nm in _bound_names(node.target):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を `:=` で束縛する')
        elif isinstance(node, ast.Match):
            for nm in _pattern_names(node):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を `match` のパターンに'
                                 '束縛する（agy 第 62 ラウンド P2-1 の `case IN:`）')
                    tainted.add(nm)
        elif isinstance(node, ast.ExceptHandler) and node.name in {_GUARD_NAME} | boxes:
            holes.append(f'{origin}:{node.lineno} 見張り番の名前「{node.name}」を例外の変数に束縛する')
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for nm in node.names:
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を '
                                 f'`{type(node).__name__.lower()}` で宣言する')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                    and (node.name == _GUARD_NAME or node.name in boxes):
                if node is top_guard:
                    continue          # `_inputs.py` のトップレベルに 1 個だけ有る実体
                what = '見張り番の実体 `guard`' if node.name == _GUARD_NAME \
                    else f'見張り番の箱「{node.name}」'
                holes.append(f'{origin}:{node.lineno} {what}を別のに束縛する定義 '
                             f'`{type(node).__name__.lower()} {node.name}`（同じ形に見えても見張り番の'
                             '呼び出しでは無い。agy 第 62 ラウンド P2-1 の `def guard` / `class IN`）')
                tainted.add(node.name)
            a = getattr(node, 'args', None)
            if a is not None:
                params = [x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)]
                params += [x.arg for x in (a.vararg, a.kwarg) if x is not None]
                for nm in params:
                    if nm == _GUARD_NAME or nm in boxes:
                        holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を仮引数に使う'
                                     '（その関数の中だけなら別物でも、呼び出しは同じ `nm(...)` に見える）')
                        tainted.add(nm)
        elif isinstance(node, (ast.withitem,)) and node.optional_vars is not None:
            for nm in _bound_names(node.optional_vars):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を `with` の変数に束縛する')
                    tainted.add(nm)
    return holes, tainted


def _guard_reference_holes(tree, boxes, parents, origin):
    """見張り番と箱を**呼び出し以外**で参照している箇所を穴にする（Astra 問 2: 取り出した時点で穴）

    第 60 ラウンドまでは `ast.Assign` だけを見ていた。`g: object = guard`（注釈付き代入）、
    `(g := guard)`（ウォルラス）、`a, b = guard, x`（分割代入）、`SimpleNamespace(guard=IN.guard)`
    （コンテナへの格納）、`return guard`（返り値）は全部ここに通る。第 62 ラウンド 問 1 で
    **箱その物**（`IN`）も同じ扱いにした（`IN2 = IN` / `f(IN)` / `return IN` / `[IN][0].guard`）"""
    holes = []
    for node in ast.walk(tree):
        if _is_guard_ref(node, boxes) and isinstance(node.ctx, ast.Load):
            parent = parents.get(id(node))
            if not (isinstance(parent, ast.Call) and parent.func is node):
                holes.append(f'{origin}:{node.lineno} 見張り番を呼び出し以外で参照している（別名への代入・'
                             '返り値・関数への受け渡し・コンテナへの格納など。この先で何が呼ばれるか'
                             '静的に決まらないので網羅の分母に入れない）')
            continue
        if isinstance(node, ast.Name) and node.id in boxes and isinstance(node.ctx, ast.Load):
            parent = parents.get(id(node))
            if isinstance(parent, ast.Attribute) and parent.value is node:
                continue           # `IN.guard` / `IN.GUARD_OFF` など属性の受け手（実測で 41 種類）
            holes.append(f'{origin}:{node.lineno} 見張り番の箱「{node.id}」を属性の受け手以外で'
                         '使っている（別名への代入・引数・返り値・コンテナ格納。この先で何が'
                         '呼ばれるか静的に決まらない。agy 第 62 ラウンド P1-1）')
            continue
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == _GUARD_NAME:
            v = node.func.value
            if not (isinstance(v, ast.Name) and v.id in boxes):
                holes.append(f'{origin}:{node.lineno} 見張り番の箱ではない「{_expr_text(v)}」の '
                             f'`.{_GUARD_NAME}` を呼んでいる（`import _inputs as IN` の `IN` からの'
                             '呼び出し以外は網羅の分母に入れない。`import math as IN` のような'
                             '同名家が化ける為。Astra 第 62 ラウンド 問 1）')
    return holes


def _dynamic_holes(tree, boxes, origin, allowed=None, sw_scope=True, exempt=None):
    """名前空間の取り出し・動的実行・辞書経由の取り出しを穴にする（Astra 問 2 の禁止構文）

    AST を読む為の `getattr(node, 'id', '')` まで禁止しない（実測: 走査対象 23 ファイルで
    `getattr` は `test-contract.py` の 4 件だけ。見張り番とは無関係）。第 62 ラウンド 問 1 の
    拡張で、**キーが文字列リテラルでなくても**、また**取り出しただけでも**穴にする
    （`getattr(IN, k)` / `globals()[k]` / `d = globals()` / `sys.modules['_inputs']` /
    `IN.__globals__[k]` / `e = exec; e(...)` / `importlib.import_module(...)`）"""
    holes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = _call_name(node)
            texts = [_const_str(a) for a in list(node.args) + [kw.value for kw in node.keywords]]
            hits_guard = _GUARD_NAME in [x for x in texts if x is not None]
            if called == 'getattr' and node.args and _is_guard_ref(node.args[0], boxes):
                hits_guard = True
            if called == 'getattr' and node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id in boxes:
                hits_guard = True       # `getattr(IN, k)` はキーが変数でも同じ穴
            if sw_scope and called == 'getattr' and node.args and isinstance(node.args[0], ast.Name) \
                    and node.args[0].id in (allowed or {}):
                holes.append(f'{origin}:{node.lineno} `getattr({node.args[0].id}, ...)` で豁免した'
                             '名前空間を文字列から引いている（登録していない機能へ同じ経路で触れる。'
                             '`getattr(node, "id", "")` の様な AST の読み取りは今までどおり可。'
                             'Astra 第 65 ラウンド 問 1）')
            if called in _DYNAMIC_LOOKUP:
                holes.append(f'{origin}:{node.lineno} `{called}()` で名前空間を取り出している'
                             '（取り出した辞書から見張り番が引けるので、このファイルの網羅が'
                             '保証できない。Astra 第 62 ラウンド 問 1）')
            elif called == 'getattr':
                if hits_guard:
                    holes.append(f'{origin}:{node.lineno} `getattr(...)` で見張り番を取り出している'
                                 '（キーが文字列リテラルで無くても動的な取り出しは網羅から見えない）')
            elif called in _DYNAMIC_EXEC or called in ('__import__', 'import_module'):
                what = '`__import__` / `importlib.import_module`' \
                    if called in ('__import__', 'import_module') else f'`{called}` による動的実行'
                holes.append(f'{origin}:{node.lineno} {what}（この中で呼ばれた見張り番は'
                             '網羅から見えない）')
            elif called == 'compile' and isinstance(node.func, ast.Name):
                # `_call_name` は属性の呼び出しも末尾の名前で返すので、`re.compile()` を巻き込まない
                # 為に裸の `compile(...)` だけ数える（実測: 属性込みで数えると `re.compile` が
                # 9 件の誤検出になった。第 64 ラウンドの実測）
                holes.append(f'{origin}:{node.lineno} `compile(...)` で文字列を実行可能な物にしている'
                             '（`types.FunctionType(compile(...), {})()` で見張り番を呼べる。'
                             'agy / Codex 第 63 ラウンド P2-1・P2-4）')
        elif isinstance(node, ast.Attribute):
            if node.attr in _DYNAMIC_ATTRS:
                holes.append(f'{origin}:{node.lineno} `{node.attr}` を読んでいる'
                             '（モジュール辞書・クラス辞書経由の取り出しは網羅から見えない）')
            elif node.attr in _LOADER_ATTRS:
                # 禁止の検査に豁免は渡さない（Astra 第 65 ラウンド 問 1 (c) 1: 台帳の登録禁止は
                # `_LOADER_NAMES` と `_LOADER_ATTRS` の両方で受け、走査側の禁止は豁免を迂回できない）
                holes.append(f'{origin}:{node.lineno} `.{node.attr}` を読んでいる'
                             '（`sys.modules[\'_inputs\']` / `builtins.exec` / `types.FunctionType` の'
                             'ような経由の取り出し・実行は網羅から見えない。`import sys as s` の'
                             '別名でも `.modules` として拾う。agy 第 63 ラウンド P2-1）')
        elif isinstance(node, ast.Subscript):
            v = node.value
            via = isinstance(v, ast.Call) and _call_name(v) in _DYNAMIC_LOOKUP
            via = via or (isinstance(v, ast.Attribute) and v.attr == '__dict__')
            if via:
                holes.append(f'{origin}:{node.lineno} 名前空間の辞書から `{_GUARD_NAME}` を'
                             '添字で取り出している（キーが文字列リテラルで無くても穴。'
                             '`globals()` / `locals()` / `vars()` / `__dict__` 経由の呼び出しは'
                             'このファイルの網羅から見えない）')
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            rhs = getattr(node, 'value', None)
            if rhs is None:
                continue
            names = set()
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                names |= set(_bound_names(tgt))
            ban = sorted(_bare_builtins(rhs))
            if ban and names:
                holes.append(f'{origin}:{node.lineno} 動的な機構「{"、".join(sorted(set(ban)))}」を'
                             f'「{"、".join(sorted(names))}」へ別名にしている（別名経由の実行・'
                             '取り出しはこのファイルの網羅から見えない）')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '__getattr__':
            holes.append(f'{origin}:{node.lineno} `__getattr__` を定義している（見張り番を'
                         '動的に公開できるので網羅の外）')
    if sw_scope and allowed:
        # Astra 第 66 ラウンド 問 2 の裁定（構文ごとの禁止追加をやめて**許可する形の白名前**へ）:
        # 豁免由来の束縛は「登録した末端を直接呼ぶ `Call` の `func`、またはそこへ至る連続した
        # 属性参照」の中だけで読む。それ以外の出現（代入・注釈付き代入・ワルラス・仮引数の既定値・
        # 辞書の鍵・条件式・内包表記・`match` の対象・`del`・`global` / `nonlocal`・`for` / `with` の
        # 対象・`except`・`isinstance`・裸のデコレータ）はすべて穴にする。許可した呼び出しの**結果**
        # を後で使うのは穴にしない（束縛の由来は末端まで決まっている）
        terminals = {f'{m}.{n}' for m, names in (exempt or {}).items() for n in names}
        ok = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            chain = _dotted(node.func)
            if chain is None:
                if isinstance(node.func, ast.Name) and allowed.get(node.func.id) in terminals:
                    ok.add(id(node.func))        # `spec_from_file_location(...)` の直接呼び出し
                continue
            head, attrs = chain
            path = allowed.get(head)
            if path is None:
                continue
            if path + '.' + '.'.join(attrs) not in terminals:
                continue
            probe = node.func
            while isinstance(probe, ast.Attribute):
                ok.add(id(probe))
                probe = probe.value
            ok.add(id(probe))                    # 連鎖の先頭（豁免で束縛された名前）
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in allowed and id(node) not in ok:
                holes.append(f'{origin}:{node.lineno} 豁免した「{allowed[node.id]}」を登録した末端の'
                             '直接呼び出し以外で読んでいる（読み取りは `a.b.<登録名>(...)` の様な'
                             '末端を直接呼ぶ連鎖の中だけ。代入・既定値・辞書の鍵・条件式・内包・'
                             '`match`・`del`・`for` / `with` の対象・`except`・`isinstance`・裸の'
                             'デコレータは穴。`getattr` 経由も同じ。Astra 第 66 ラウンド 問 2）')
            elif isinstance(node, (ast.Global, ast.Nonlocal)):
                for nm in node.names:
                    if nm in allowed:
                        holes.append(f'{origin}:{node.lineno} 豁免した「{nm}」を '
                                     f'`{type(node).__name__.lower()}` で宣言している（読み取りでは'
                                     'ないので上の形とは別に落とす。Astra 第 66 ラウンド 問 2）')
    return holes


def _bindings_in(scope):
    """そのスコープ**自身**が束縛する名前（入れ子の関数・lambda の中は別スコープなので数えない）"""
    binds = set()
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        binds |= {x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)}
        binds |= {x.arg for x in (a.vararg, a.kwarg) if x is not None}
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                binds |= set(_bound_names(tgt))
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            binds |= set(_bound_names(node.target))
        elif isinstance(node, ast.NamedExpr):
            binds |= set(_bound_names(node.target))
        elif isinstance(node, ast.ExceptHandler) and node.name:
            binds.add(node.name)
        elif isinstance(node, ast.withitem) and node.optional_vars is not None:
            binds |= set(_bound_names(node.optional_vars))
        stack.extend(ast.iter_child_nodes(node))
    return binds


def _shadowed_scopes(tree, boxes):
    """見張り番の名前を自分のスコープで束縛し直すスコープの集合（`id` の組。モジュールも含む）

    仮引数・ローカル代入・ループ変数・`with`・`except`・`:=` で `guard`（または `_inputs` の箱）を
    束縛し直す所の中は、同じ形に見えても見張り番の呼び出しではない（Astra 第 61 ラウンド
    問 2: 「スコープ内での `IN`／`guard` の再束縛も拒否」）。拒否その物は `_guard_symbols` が
    穴として出し、ここでは**網羅に数えない**役目を担う"""
    guardish = {_GUARD_NAME} | boxes
    out = set()
    if _bindings_in(tree) & guardish:
        out.add(id(tree))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            if _bindings_in(node) & guardish:
                out.add(id(node))
    return out


def _wrapper_functions(tree, boxes):
    """見張り番の読みを呼び出し元へ手渡しするだけのラッパ関数（Astra 問 2 の区別）

    - **見張り番その物か、その結果だけを返す関数**は穴（呼ぶ側が `guard` の呼び出しとして見えない）
    - **同じ判定を実行する共有検査関数**は許可（関数の中の実際の呼び出しを数える。呼ぶ側が
      2 箇所でもソース上の見張り番は 1 箇所で、それは二重計上ではない）"""
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        if isinstance(node, ast.Lambda):
            # lambda の体は文でなく式。`lambda: IN.guard('x')` も「結果だけを返すラッパ」なので、
            # 1 文の `return` として扱う（合成ノードの行番号は使わない。穴の行は lambda 自身）
            stmts = [ast.Return(value=node.body)]
        else:
            stmts = [s for s in node.body
                     if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        if not stmts or not any(_is_guard_ref(r, boxes)
                                for s in stmts for r in ast.walk(s)):
            continue

        def is_handoff(expr, handed):
            """返り値・代入の右辺が見張り番の読みを**含んでいる**か（`return bool(IN.guard('x'))` も）

            第 61 ラウンドまでは「見張り番の呼び出しその物」だけを見ていた為、`return bool(IN.guard('x'))`
            のように包み直したラッパが通った（Astra 第 62 ラウンド 問 1 の実測）。同じ判定をその場で
            実行して別のを返す共有検査関数は、返り値に見張り番の読みを含まないので引き続き許可"""
            if expr is None:
                return False
            for sub in ast.walk(expr):
                if _is_guard_ref(sub, boxes):
                    return True
                if isinstance(sub, ast.Name) and sub.id in handed:
                    return True
            return False

        handed, count = set(), 0
        for s in stmts:
            if isinstance(s, ast.Return):
                count += 1 if is_handoff(s.value, handed) else 0
            elif isinstance(s, (ast.Assign, ast.AnnAssign)) and getattr(s, 'value', None) is not None:
                if is_handoff(s.value, handed):
                    for tgt in (s.targets if isinstance(s, ast.Assign) else [s.target]):
                        handed |= set(_bound_names(tgt))
                    count += 1
        if count and count == len(stmts) and any(isinstance(s, ast.Return) for s in stmts):
            out.append(node)
    return out


# 箱の公開名が現れる位置の扱い（Astra 第 68 ラウンド 問 2 の裁定: **既定拒否**）。第 67 ラウンド
# までは「書き換えの受け手」と「呼び出しの受け手」だけを見て、あとは全部読み取りにしていた為、
# `(IN.HERE if True else None)._str = 'x'` が穴 0 件で通って実値が変わった（Codex P2-2 の実測
# `direct_holes=1 conditional_holes=0` / `HERE_after=/tmp/r67-review`）。許可する出現位置と追跡を
# 続ける位置だけを表に書き、**未登録の位置は穴**にする（歩ける構文を足す案は「次の未対応構文が
# 同じ抜け道になる」として却下済み）

# 追跡を続ける位置（ここは連鎖の途中として上がる・下がる）
_BOX_FOLLOW = {
    'Attribute': ('value',),
    'Subscript': ('value',),
    'IfExp': ('body', 'orelse'),
    'BoolOp': ('values',),
    'BinOp': ('left', 'right'),
    'UnaryOp': ('operand',),
    'Tuple': ('elts',),
    'List': ('elts',),
    'Set': ('elts',),
    'Dict': ('keys', 'values'),
    'Starred': ('value',),
    'JoinedStr': ('values',),
    'FormattedValue': ('value',),
}

# 読み取りとして許可する出現位置（`(親の型, 親の中の field 名)`）。裁定が挙げた「代入右辺・戻り値・
# 関数の引数・他の物の添字・比較・条件判定・書式化・反復対象・単独の式」まで。`NamedExpr`・`Await`・
# 仮引数の既定値・装飾子などは**必要な利用と検査が増えるまで許可しない**
_BOX_READ_ROLES = frozenset((
    ('Assign', 'value'), ('AugAssign', 'value'), ('AnnAssign', 'value'),
    ('Return', 'value'), ('Expr', 'value'), ('keyword', 'value'),
    ('Call', 'args'), ('Subscript', 'slice'),
    ('Compare', 'left'), ('Compare', 'comparators'),
    ('If', 'test'), ('While', 'test'), ('Assert', 'test'), ('IfExp', 'test'),
    ('For', 'iter'), ('AsyncFor', 'iter'), ('comprehension', 'iter'),
    ('Raise', 'exc'), ('Yield', 'value'), ('YieldFrom', 'value'),
))


def _box_role(node, par):
    """`node` が親 `par` のどの field に有るか（`(親の型名, field 名)`。親が無いなら型名だけ）"""
    if par is None:
        return (type(node).__name__, '')
    for field, value in ast.iter_fields(par):
        if value is node:
            return (type(par).__name__, field)
        if isinstance(value, (list, tuple)):
            for item in value:
                if item is node:
                    return (type(par).__name__, field)
    return (type(par).__name__, '?')


# 呼び出しの連鎖として追跡を続ける位置。上の表から**新しい値を作る構文**を落としたもの
# （`IN.HERE / 'x'` の結果は `IN.HERE` ではないので、その結果を呼ぶのは `IN.HERE` を呼ぶことでは
# ない。実ツリーの `(IN.HERE / 'input-fingerprints.json').read_text(...)` が誤検出になった実測）。
# 条件式・論理式・コンテナは値その物になり得るので残す（`(IN.CONST if p else q).clear()` と
# `[IN.CONST][0]()` は禁止）
# 呼び出しの受け手まで追跡を続ける位置の**厳密版**（演算・単項演算・書式化は新しい値を作るので
# そこで受け手の追跡をやめる。`(IN.HERE / 'x').read_text()` が素通しになる側の表）
_BOX_CALL_STRICT = {k: v for k, v in _BOX_FOLLOW.items()
                    if k not in ('BinOp', 'UnaryOp', 'JoinedStr', 'FormattedValue')}
# Astra 第 69 ラウンド 問 3-1 (c) の裁定: **コンテナリテラルを一度でも通った経路**は、後続の
# 演算・条件式・属性・添字で追跡を打ち切らない（`([IN.CONST] * 2)[0]()` が素通しになった
# agy 第 68 ラウンド P1-2 の実測。直下の子だけを見る (a) は演算を 1 段重ねるだけで破れる）
_BOX_CONTAINERS = (ast.List, ast.Tuple, ast.Set, ast.Dict, ast.Starred)


def _box_follow(name, field, table=None):
    """`(親の型名, field 名)` が追跡を続ける位置か（`table` を渡すと呼び出し用の表も使える）"""
    return field in (table or _BOX_FOLLOW).get(name, ())


def _box_chain_top(node, parents):
    """箱の公開名から**追跡を続ける位置**を上がった所の、連鎖の一番外側のノードと親"""
    cur = node
    while True:
        par = parents.get(id(cur))
        if par is None:
            return cur, None
        kind, field = _box_role(cur, par)
        if _box_follow(kind, field):
            cur = par
            continue
        return cur, par


def _box_walk_down(node, out, table=None):
    """書き換えの受け手・呼び出しの受け手から、追跡を続ける位置だけ下って連鎖の構成員を数える"""
    out.add(id(node))
    kind = type(node).__name__
    for field, value in ast.iter_fields(node):
        if field not in (table or _BOX_FOLLOW).get(kind, ()):
            continue
        items = value if isinstance(value, (list, tuple)) else [value]
        for item in items:
            if isinstance(item, ast.AST):
                _box_walk_down(item, out, table)


def _box_write_targets(tree):
    """`<箱>.<名前>` が**書き換え・削除の受け手**になっているノードの id を集める

    `IN.G = 1` / `IN.G.x = 1` / `IN.G[0] = 1` / `del IN.G` / `IN.G |= 1` はみな代入の受け手で、
    Python は連鎖の内の `IN.G` を `Load` にする（Astra 第 67 ラウンド 問 2）。第 68 ラウンドでは
    受け手から**追跡を続ける位置だけ**下るので、`(IN.HERE if True else None)._str = 'x'` の様な
    条件式を挟んだ書き換えも数に入る（Codex P2-2）。`d[IN.CONST] = 1` の様な**別の物**の受け手の
    中の読み取りは `slice` 側へ下らないので入らない"""
    out = set()
    for node in ast.walk(tree):
        ctx = getattr(node, 'ctx', None)
        if not isinstance(ctx, (ast.Store, ast.Del)):
            continue
        _box_walk_down(node, out)
    return out


def _box_is_call_receiver(node, parents):
    """箱の公開名から上って呼び出しの受け手へ至るか。至り方を `call-chain` / `make` で返す

    出現から**上って**決める。`IN.CONST()` は直接の受け手、`IN.CONST.clear()` と
    `(IN.CONST if p else q).clear()` と `[IN.CONST][0]()` は受け手へ至る連鎖（禁止）。
    `(IN.HERE / 'x').read_text()` は演算が新しい値を作るので受け手ではない（許可）。
    Astra 第 69 ラウンド 問 3-1 (c) の裁定で、**経路上にコンテナリテラルを 1 つでも通った場合は
    演算・書式化を挟んでも**受け手への連鎖として拒否する（`([IN.CONST] * 2)[0]()` と
    `(f'{[IN.CONST]}').lower()`）。他の物の添字 `Subscript.slice` と関数の引数から受け手側へは
    飛び移らない（`local[IN.CONST]()` と `f([IN.CONST])` は読み取りのままで止まる）"""
    cur, through = node, False
    while True:
        if isinstance(cur, _BOX_CONTAINERS):
            through = True
        par = parents.get(id(cur))
        if par is None:
            return False
        if isinstance(par, ast.Call) and par.func is cur:
            return True
        kind, field = _box_role(cur, par)
        # 厳密版は演算・書式化で追跡をやめる（`(IN.HERE / 'x').read_text()` の受け手は演算の
        # 結果で別の値。下の `_box_form` が `('Call', 'func')` を読み取りに分類する）。コンテナを
        # 通った後だけ完全版を使い、`([IN.CONST] * 2)[0]()` を受け手への連鎖として拒否する
        if not _box_follow(kind, field, _BOX_FOLLOW if through else _BOX_CALL_STRICT):
            return False
        cur = par


def _box_form(node, parents, writes):
    """箱の公開名の 1 箇所の出現を `write` / `call` / `call-chain` / `read` / `unsupported` へ分類する

    走査と候補収集で同じ分類を使う（Astra 第 67 ラウンド 問 2: 候補だけが読み取りに数えて用途を
    塗り替えるのを防ぐ）。`call` は「その名前その物の呼び出し」だけ。`call-chain` は呼び出しへ至る
    連鎖の途中（`IN.<const>.clear()`）。`read` は許可した読み取り位置。それ以外は `unsupported`
    （Astra 第 68 ラウンド 問 2 の既定拒否）。分類はスイッチから見独立した純粋な構文判定"""
    top, par = _box_chain_top(node, parents)
    if id(node) in writes or id(top) in writes:
        return 'write'
    direct = parents.get(id(node))
    if isinstance(direct, ast.Call) and direct.func is node:
        return 'call'
    if _box_is_call_receiver(node, parents):
        return 'call-chain'
    role = _box_role(top, par)
    if role in _BOX_READ_ROLES:
        return 'read'
    if role == ('Call', 'func'):
        # 上の受け手の判定を抜けてここへ来るということは、箱の値から**新しい値を作る構文**
        # （`IN.HERE / 'x'` の様な演算・書式化）を経由して呼び出しの相手を作っていることになる。
        # 箱の値その物を呼んではいないので読み取り（実ツリー
        # `(IN.HERE / 'input-fingerprints.json').read_text(...)` がこれ。Astra 第 68 ラウンド 問 2 の
        # 「演算のオペランドは追跡を続けるが、結果は別の値」という表の範囲）
        return 'read'
    return 'unsupported'


def _box_name_holes(tree, boxes, box, parents, origin, sw):
    """見張り番の箱 `IN` の公開名を**用途付きの許可表**と較べる（Astra 第 66 ラウンド 追記 問 (ア)）

    `IN` は豁免ではなく許可一覧に入っている箱なので、豁免の末端経路の規則は掛けない。代わりに
    表へ載せた公開名だけを、載せた用途の形で使うことを求める。表の用途と形の判定は 6 マスで
    `call` は呼び出しだけ・`const` は値の読み取りだけ・**書き換えと削除は両方の用途で穴**
    （Astra 第 67 ラウンド 問 2。`IN.GUARD_OFF = {...}` が穴 0 件で通って見張り番を殺せた実測）。
    `IN.guard(...)` は別の規則で 1 形に限定済みなのでここで数えない。`box` を渡さない制御
    （架空のソース）では検査しない（実ツリーの走査と台帳の照合で必ず渡す）

    第 67 ラウンドの双人レビューで、スイッチの辞書 `sw` を `if not sw` で見た為に**名前を消して
    も 4 規則のうち 3 規則が発火し続けた**（agy P1-2。`CGD_GUARD_OFF=in-public-name` で穴 3 件、
    控制は閾値のせいでそれを検出できなかった）。第 68 ラウンド Astra 問 2 条件 3 / 問 3 条件 3 の
    とおり、**分類はスイッチから見独立**させて常に同じ結果を返し、スイッチは自分が担当する
    診断の出力だけをまとめて止める"""
    if not boxes or box is None:
        return []
    name_on = bool(sw.get('in-public-name', True))
    write_on = bool(sw.get('in-public-write', True))
    if not name_on and not write_on:
        return []
    writes = _box_write_targets(tree)
    holes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id not in boxes:
            continue
        if node.attr == _GUARD_NAME:
            continue
        kind = box.get(node.attr)
        form = _box_form(node, parents, writes)
        if form == 'write':
            if not write_on:
                continue
            holes.append(f'{origin}:{node.lineno} 見張り番の箱の公開名「{node.attr}」を'
                         '書き換え・削除の対象にしている（`IN.<公開名> = ...` と `del IN.<公開名>` は'
                         '見張り番を無効にする仕掛けその物を書き換えられる。無効化は制御の側で'
                         '`with IN.guard_off(\'名前\'):` の区間（台帳 `guardCallers` のファイルだけ）か'
                         '環境変数 `CGD_GUARD_OFF` だけでやる。'
                         'Astra 第 67 ラウンド 問 2 の裁定）')
            continue
        if not name_on:
            continue
        if form == 'unsupported':
            holes.append(f'{origin}:{node.lineno} 箱の公開名「{node.attr}」の現れ方が未登録の位置'
                         f'（{form}。親は {type(parents.get(id(node))).__name__}）'
                         '（Astra 第 68 ラウンド 問 2 の既定拒否: 箱の公開名は許可した読み取り位置と'
                         '呼び出しにだけ現れる。条件式・論理式・コンテナを経由した書き換えや'
                         '呼び出しを静的に掴む為、表に無い位置は穴にする）')
            continue
        if kind is None:
            holes.append(f'{origin}:{node.lineno} 見張り番の箱の公開名「{node.attr}」が'
                         f'{IN.GUARD_LEDGER_FILE} の `boxNames` に登録されていない（箱の公開名は'
                         '用途付きの表に登録した物だけ。`emit-guard-owners.py --emit` が実ツリーから'
                         '候補を出す。Astra 第 66 ラウンド 追記の裁定 (ア)）')
        elif kind == 'call' and form != 'call':
            holes.append(f'{origin}:{node.lineno} 箱の公開名「{node.attr}」は呼び出し専用の登録なのに'
                         '呼び出さずに読んでいる（関数を別名へ移すと呼び出し元が網羅から見えない。'
                         'Astra 第 66 ラウンド 追記の裁定 (ア)）')
        elif kind == 'const' and form in ('call', 'call-chain'):
            holes.append(f'{origin}:{node.lineno} 箱の公開名「{node.attr}」は値の読み取りの登録なのに'
                         '呼び出しへ至る連鎖にしている（`IN.<const>.clear()` の様に連鎖の先を呼ぶのは'
                         '値の読み取りではない。Astra 第 67 ラウンド 問 2）')
    return holes


# 台帳 `boxNames` の語彙（`call` / `const`）への写像。ここへ乗らない形（`write` / `call-chain` /
# `unsupported`）は候補を作る側が拒否する
_BOX_LEDGER_FORM = {'call': 'call', 'read': 'const'}


def _box_used_attrs():
    """実ツリーで見張り番の箱 `IN` の公開名を**使っている形ごと**に集める（`名前 -> 形の集合`）

    台帳 `boxNames` の用途（`call` / `const`）はここで決める。形は走査と同じ `_box_form` で数える
    （Astra 第 67 ラウンド 問 2: 候補だけが読み取りに数えて用途を塗り替えるのを防ぐ）。書き換えは
    台帳に書けない形なので `write` として集め、候補を作る側が拒否する"""
    got = {}
    for path in _guard_scan_files():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        boxes, _holes, tainted, _allowed = _collect_boxes(tree, path, None)
        parents = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[id(child)] = node
        writes = _box_write_targets(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.value, ast.Name):
                continue
            # `tainted` は**束縛名の集合**なので箱の名前で引く（agy 第 66 ラウンドの付記:
            # `node.attr in tainted` は属性名を引いていて常に空だった）
            if node.value.id not in boxes or node.attr == _GUARD_NAME or node.value.id in tainted:
                continue
            # 台帳の語彙（`call` / `const`）へここで揃える（読み取りは `const`。書き換えは台帳に
            # 書けない形なので `write` のまま返し、候補を作る側が拒否する）
            form = _box_form(node, parents, writes)
            got.setdefault(node.attr, set()).add(_BOX_LEDGER_FORM.get(form, form))
    return got


def _box_table_errors(doc):
    """台帳の `boxNames` と実ツリーで使っている公開名を突き合わせる（Astra 第 66 ラウンド 追記 (ア)）"""
    got = _box_used_attrs()
    want = doc.get('boxNames')
    if not isinstance(want, dict):
        # 形の悪さは `box-shape` が名指す（ここで同じ事を言うと 1 個の細工が 2 名前の落ち方になり、
        # 単独名指しの検査が測れなくなる）
        return []
    errs = []
    extra = sorted(set(want) - set(got))
    missing = sorted(set(got) - set(want))
    if extra:
        errs.append(f'台帳の boxNames に登録した公開名 {extra[:6]} が実ツリーで使われていない'
                    f'{" …ほか " + str(len(extra) - 6) + " 件" if len(extra) > 6 else ""}'
                    '（使わない登録は次の細工を通す土台になる。`emit-guard-owners.py --emit` で作り直す）')
    if missing:
        errs.append(f'実ツリーが使う箱の公開名 {missing[:6]} が台帳の boxNames に無い'
                    f'{" …ほか " + str(len(missing) - 6) + " 件" if len(missing) > 6 else ""}'
                    '（走査側も同じ表で穴にしているので、登録か使い方のどちらかを直す）')
    both = sorted(n for n, kinds in got.items() if len(kinds) > 1)
    if both:
        errs.append(f'箱の公開名 {both[:6]} が呼び出しと読み取りの両方で使われている'
                    '（表は 1 名 1 用途なので、呼び出す側か読む側のどちらかに揃える）')
    # 用途の語彙（`call` / `const`）自体は `box-shape` が名指すので、ここでは実測の形と違うかだけ見る
    # （`_inputs` の語彙をここが読むと、その名前自体が表に要る為の循環になる）
    wrong = sorted(n for n in set(want) & set(got)
                   if isinstance(want[n], str) and {want[n]} != got[n])
    if wrong:
        errs.append(f'台帳の boxNames の用途が実測と違う名前 {wrong[:6]}'
                    f'{" …ほか " + str(len(wrong) - 6) + " 件" if len(wrong) > 6 else ""}'
                    '（`call` は `IN.<名前>(...)` の呼び出しだけ、`const` は値の読み取りだけ）')
    return errs


# 見張り番を消す区間を作る箱の公開名（Astra 第 68 ラウンド 問 1 の B案）。`_inputs` の側で
# `with` の管理として返す物だけ作って、他の場所で作る道を走査で落とす
_SWITCH_METHODS = ('guard_off', 'guards_on')


def _origin_key(origin):
    """走査対象の origin を台帳と同じ正準相対パスへ直す（制御の `<制御>` はそのまま）"""
    try:
        return pathlib.Path(str(origin)).resolve().relative_to(REPO).as_posix()
    except ValueError:
        return str(origin)


def _box_switch_calls(tree, boxes):
    """`IN.guard_off(...)` / `IN.guards_on()` の呼び出しを `(呼び出した行, with の管理か)` で集める"""
    managers = {id(item.context_expr) for node in ast.walk(tree) if isinstance(node, ast.With)
                for item in node.items}
    managers |= {id(item.context_expr) for node in ast.walk(tree)
                 if isinstance(node, ast.AsyncWith) for item in node.items}
    got = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id not in boxes:
            continue
        if node.func.attr not in _SWITCH_METHODS:
            continue
        got.append((node, node.func.attr, id(node) in managers))
    return got


def _box_switch_holes(tree, boxes, parents, origin, callers, sw):
    """無効化の区間を作る呼び出しを台帳 `guardCallers` と照合する（Astra 第 68 ラウンド 問 1）

    裁定の実装条件 2: 許可するのは **登録ファイル内の `with` の管理**としての呼び出しだけ。
    無登録のファイル・使われない登録・`with` 以外（`x = IN.guard_off('a')` のように区間を
    保持して後で消す形）を穴にする"""
    holes = []
    got = _box_switch_calls(tree, boxes)
    key = _origin_key(origin)
    if sw.get('guard-caller-file', True):
        for node, attr, _ok in got:
            if key not in callers:
                holes.append(f'{origin}:{node.lineno} 台帳 `guardCallers` に無いファイルが'
                             f'見張り番を消す区間 `{attr}(...)` を呼んでいる（無効化を呼べるのは'
                             '登録した制御ファイルだけ。無効化の区間を作れる場所を増やすのは人の'
                             '登録でやる。Astra 第 68 ラウンド 問 1 の B案）')
        if key in callers and not got:
            holes.append(f'{origin} は台帳 `guardCallers` に登録されているが見張り番を消す区間を'
                         '作っていない（使われない登録は次に見直すまで残り続ける。Astra 第 68 '
                         'ラウンド 問 1 の実装条件 2）')
    if sw.get('guard-caller-form', True):
        for node, attr, ok in got:
            if not ok:
                holes.append(f'{origin}:{node.lineno} `{attr}(...)` が `with` の管理ではない位置で'
                             '呼ばれている（区間を作らずに無効化だけ残す形。`with '
                             'IN.guard_off(\'名前\'):` の 1 形だけ許可する。Astra 第 68 ラウンド '
                             '問 1 の B案）')
    return holes


def _guard_scan(text, origin, exempt=None, box=None, callers=None):
    """見張り番の呼び出しを AST で読む。**許可した構文以外で見張り番に触れたら穴**（第 61 ラウンド Astra 問 2 の裁定 (ii)）

    第 60 ラウンドまでは「`ast.Assign` で別名を作ったか」を列挙する方式だった。Codex と agy の実測で
    `from _inputs import guard as g` / `g: object = guard` / `(g := guard)` / `getattr(IN, 'guard')` /
    `SimpleNamespace(guard=IN.guard)` / `globals()['guard']` / `functools.partial(IN.guard)` が名前の
    集合にも穴の列にも出ない（網羅の分母から黙って消える）と判った。束縛の形を足し続ける方式是
    続きが無いので、**数えるのは `guard('名前')` と `IN.guard('名前')` の直接呼び出しだけ**に決め、
    それ以外で見張り番に届いた物は**取り出した時点**で穴にする（Astra 問 2: 呼び出されるかまでの
    追跡はしない。未使用の束縛も穴。`return IN.guard('x')` のようなラッパも穴）

    `box` は見張り番の箱の公開名の一覧（`boxNames`）。`None` の時はその検査をしない
    （架空のソースを見る制御用。実ツリーの走査は必ず渡す）

    戻り値は（名前の集合、穴の説明文の列、名前の呼び出し回数の辞書）。回数は
    「1 名前 = 呼び出し 1 箇所」の規則を見る（Astra 第 60 ラウンド 問 2）"""
    tree = ast.parse(text)
    # 見張り番の読み方はここで 1 箇所ずつ読む（同じ名前を 2 箇所で呼ぶと単独名指しの規則に当たる）
    switches = {'import-binds-guard': IN.guard('import-binds-guard'),
                'import-unregistered': IN.guard('import-unregistered'),
                'import-granted': IN.guard('import-granted'),
                'import-star': IN.guard('import-star'),
                'guard-unbound': IN.guard('guard-unbound'),
                'exempt-use-form': IN.guard('exempt-use-form'),
                'in-public-name': IN.guard('in-public-name'),
                'in-public-write': IN.guard('in-public-write'),
                'import-relative': IN.guard('import-relative'),
                'import-dynamic-module': IN.guard('import-dynamic-module'),
                'guard-caller-file': IN.guard('guard-caller-file'),
                'guard-caller-form': IN.guard('guard-caller-form')}
    boxes, holes, tainted, allowed = _collect_boxes(tree, origin, exempt, switches)   # 箱を先に全件集める
    top_guard = None
    if pathlib.Path(str(origin)).name == _INPUTS_FILE:
        defs = [n for n in tree.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == _GUARD_NAME]
        if len(defs) == 1:
            top_guard = defs[0]                      # 見張り番の実体はここにある 1 個だけ
        else:
            holes.append(f'{origin} のトップレベルに `def {_GUARD_NAME}` が {len(defs)} 個'
                         '（見張り番の実体は 1 個だけ。同名の再定義や入れ子定義は実体に数えない）')
    sym_holes, sym_tainted = _guard_symbols(tree, boxes, origin, top_guard)
    holes += sym_holes
    tainted |= sym_tainted
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    shadow = _shadowed_scopes(tree, boxes) | {id(x) for x in _wrapper_functions(tree, boxes)}
    found, counts, calls = set(), {}, []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_guard_ref(node.func, boxes)):
            continue
        # **穴で落とす前の呼び出し候補**を先に残す（Astra 第 64 ラウンド 問 2 裁定 (iii): 豁免を
        # 渡した走査と渡さない走査で、この候補が名前・所属・ファイル・呼び出し箇所まで一致して
        # いることを照合する。落とした後の集合だけ較べると、消した側が黙って少なくなる細工を見る）
        if isinstance(node.func, ast.Name) and top_guard is None:
            # Astra 第 65 ラウンド 問 2 裁定: 裸の `guard('名前')` は正式な `_inputs.py` の
            # トップレベル `def guard` に結び付く場合だけ数える。外部ファイルの裸の呼び出しは
            # 黙って捨てず穴にする（`guard` を束縛する import は `_collect_boxes` で既に穴）
            if switches['guard-unbound']:
                holes.append(f'{origin}:{node.lineno} 見張り番を呼ぶ `guard(...)` が箱経由では'
                             'ない（外部のファイルは `import _inputs as IN` の箱経由 '
                             '`IN.guard("名前")` にすること。Astra 第 65 ラウンド 問 2）')
            continue
        probe0 = node.args[0] if len(node.args) == 1 and not node.keywords else None
        lit0 = _const_str(probe0) if probe0 is not None else None
        if isinstance(lit0, str):
            calls.append((pathlib.Path(str(origin)).name, lit0, node.lineno))
        if (isinstance(node.func, ast.Name) and node.func.id in tainted) \
                or (isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in tainted):
            continue     # 見張り番の実体でない物が束縛された名前の呼び出しは数えない（Astra 問 1）
        probe = node
        inside_shadow = False
        while probe is not None:
            probe = parents.get(id(probe))
            if id(probe) in shadow:
                inside_shadow = True
                break
        if inside_shadow:
            continue
        one = node.args[0] if len(node.args) == 1 and not node.keywords else None
        lit = _const_str(one) if one is not None else None
        if lit and _NAME_SHAPE.fullmatch(lit):
            found.add(lit)
            counts[lit] = counts.get(lit, 0) + 1
        elif lit:
            holes.append(f'{origin}:{node.lineno} 見張り番の名前「{lit}」が字句規則に合わない'
                         f'（{_NAME_SHAPE.pattern}。README の道具別一覧がバッククォートの中で読む形と'
                         '同じ規則に揃えないと、一覧の検査がこの名前を黙って無視する。'
                         'Codex 第 62 ラウンド P2-3）')
        else:
            holes.append(f'{origin}:{node.lineno} `guard()` の呼び出しが許可した形ではない'
                         '（引数 1 個の空でない文字列リテラル、キーワード引数無し以外は'
                         '網羅の分母に入らない）')
    holes += _guard_reference_holes(tree, boxes, parents, origin)
    holes += _dynamic_holes(tree, boxes, origin, allowed,
                            switches['exempt-use-form'], exempt)
    holes += _box_name_holes(tree, boxes, box, parents, origin, switches)
    # 無効化の区間を作る呼び出し元を台帳と照合する（Astra 第 68 ラウンド 問 1 の B案）。
    # `callers` を渡さない走査（架空のソースを見る制御）は空の一覧 = 何でも穴
    holes += _box_switch_holes(tree, boxes, parents, origin, list(callers or ()), switches)
    for node in _wrapper_functions(tree, boxes):
        holes.append(f'{origin}:{node.lineno} 関数「{getattr(node, "name", "<lambda>")}」は'
                     '見張り番の読みを呼び出したり受け取ったりして結果だけを返すラッパ（呼ぶ側は '
                     '`guard` の呼び出しとして見えない。同じ判定をする共有検査関数は、その場で'
                     '判定すること）')
    return found, holes, counts, calls


def _guard_call_names(path):
    """`_guard_scan` が読んだ名前集合だけ返す（穴を数えない所で使う）"""
    names, _, _counts, _calls = _guard_scan(path.read_text(encoding='utf-8'), path)
    return names


def _negative_calls(path):
    """`negative(...)` の呼び出しを**1 本**で読み、`(説明, 名前組, 階級, 読めない理由)` で返す

    階級と登録の判定は、以前 `_singleton_tiers()` と `_negative_guard_groups()` の 2 本が別々に AST を
    読んでいた（双人レビュー Codex 第 70 / 71 ラウンドと agy 第 72 ラウンドで「片方だけ直った」ズレが
    4 ラウンド続いた）。ここを唯一の読み取りにして、`guards` の位置引数・キーワード・タプル、`name=`
    のキーワード、`clean` / `fallback` の位置とキーワードを 1 か所で解釈する。

    静的に読めない引数（`guards` の位置とキーワードの両記、`**kwargs` の展開、`clean` に定数以外の式、
    名前の文字列定数でない書き方）は**黙って読み落とさず** 4 番目に理由を返す。`_negative_unreadable()`
    がそれを失敗にするので、読めない控制が階級の検査を素通りする事が起きない
    """
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not (isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'negative'):
            continue
        why = []
        clean, dyn, dyn_clean = True, False, False
        # `*args` の展開が有ると位置引数の番号がズレるので**位置を読まない**（agy 第 74 ラウンド
        # P2-2: `negative('a', fn, *[], guards='g')` で位置の guards を無い物と読み、キーワードと
        # 両方に書いたという誤った理由を出していた）。キーワードの読み取りはズレないので使う
        starred = any(isinstance(a, ast.Starred) for a in node.args)

        def pos(i):
            return None if starred else (node.args[i] if len(node.args) > i else None)

        first = node.args[0] if node.args and not isinstance(node.args[0], ast.Starred) else None
        label = _const_str(first) if first is not None else None
        for kw in node.keywords:
            if kw.arg == 'name':
                label = _const_str(kw.value)
        # guards: 位置 2 番目かキーワード。単独名指しは 1 要素のタプルに揃える
        gnode = pos(2)
        names = None
        for kw in node.keywords:
            if kw.arg != 'guards':
                continue
            if gnode is not None:
                why.append('guards を位置引数とキーワードの両方に書いた')
            gnode = kw.value
        if gnode is not None:
            one = _const_str(gnode)
            if one:
                names = (one,)
            elif isinstance(gnode, (ast.Tuple, ast.List)):
                got = [_const_str(e) for e in gnode.elts]
                if not gnode.elts:
                    names = ()            # `guards=()` は見張り番を名指さない控制（契約走査に有る）
                elif all(got):
                    names = tuple(got)
                else:
                    dyn = True            # 要素に式が混ざる（偽名を組む契約走査）。単独登録しない
            else:
                dyn = True                # `guards=FAKE` の様な動的な名前。単独登録しない
        # clean: 位置 4 番目かキーワード。階級は実行器と同じくこの値だけで決まる
        cnode = pos(4)
        for kw in node.keywords:
            if kw.arg != 'clean':
                continue
            if cnode is not None:
                why.append('clean を位置引数とキーワードの両方に書いた')
            cnode = kw.value
        has_fb = pos(5) is not None or any(kw.arg == 'fallback' for kw in node.keywords)
        if any(kw.arg is None for kw in node.keywords):
            dyn = True                    # `**kwargs` の展開。単独名指しの時のみ失敗にする
        if starred:
            dyn = True                    # `*args` の展開。単独名指しの時のみ失敗にする
        dyn_clean = cnode is not None and not isinstance(cnode, ast.Constant)
        if dyn_clean:
            dyn = True                    # 式の `clean`。単独名指しの時のみ失敗にする
        elif isinstance(cnode, ast.Constant):
            clean = bool(cnode.value)
        # 静的に読めない事を失敗にするのは、**単独名指しとして登録される控制**だけにする
        # （`guards` を書かない控制と、`guards=FAKE` のように動的に組む控制（契約走査の偽名）は
        #  網羅へ登録されない為、読めなくても階級の検査を素通りしない）
        if names and len(names) == 1:
            if not label:
                why.append('単独名指しの控制の説明が文字列定数でない（網羅の登録と照合できない）')
            if dyn or dyn_clean:
                why.append('単独名指しの控制が静的に読めない引数を持つ（階級が実行時とズレる）')
            if not clean and not has_fb:
                why.append('clean=False は fallback に「OFF 後も残る別の診断の文面」を書く')
        if why:
            out.append((label, names, None, ' / '.join(sorted(set(why)))))
        else:
            out.append((label, names, 'clean' if clean else 'fallback', None))
    return out


def _negative_unreadable(path):
    """静的に読めない `negative(...)` の呼び出しを `説明: 理由` で返す（制御が失敗にする）"""
    return [f'{c[0]!r}: {c[3]}' for c in _negative_calls(path) if c[3]]


def _negative_guard_groups(path):
    """`negative(...)` に**書いてある** `guards=` の名前組を集める（`_negative_calls()` から作る）

    ここは「書かれている名前」を見る（検査器に無い名前を制御に書いた日を探すため）。実際に
    網羅したかは、実行後に通った制御だけを数える
    """
    return [c[1] for c in _negative_calls(path) if c[1]]


def _singleton_controls(path):
    """`negative(...)` に**書いてある単独名指しの控制**を `(説明, 名前)` で集める

    第 60 ラウンド Astra 問 3 の裁定は「登録した控制はすべて実行・成功を必須とし、片方の成功で
    他方の失敗や未実行を埋め合わせない」。ここでは**登録**を見て、実行後に通った記録と突き合わせる
    """
    return sorted(_singleton_tiers(path))


def _singleton_tiers(path):
    """単独名指しの控制が取り得る階級を `(控制名, 見張り番名)` で返す（`_negative_calls()` から作る）

    階級は実行器 `_run_negative()` と同じく `clean` の値だけで決まる（`clean=True` → `clean`、
    `clean=False` → `fallback`）。よって取り得る階級は常に 1 つで、逆の階級の記録は反則である。
    静的に読めない控制はここに出ない（`_negative_unreadable()` 側で失敗になる為、階級の検査を
    素通りできない。双人レビュー agy 第 72 ラウンド P2-1・P2-2）
    """
    return {(c[0], c[1][0]): {c[2]} for c in _negative_calls(path)
            if c[3] is None and c[0] and c[1] and len(c[1]) == 1}


def _guard_scan_files():
    """見張り番の走査が読む .py の集合（対応表の `scannedFiles` と**同じ 1 本**で数える）"""
    return sorted((REPO / 'skill' / 'scripts' / 'tools').rglob('*.py'))


def _guard_owners_from_scan(exempt_by_file=None):
    """走査から `名前 -> 直接呼ぶ道具のファイル名` の組を作る（対応表と同じ作り方）"""
    names, direct, _counts, holes, _calls = _guard_names_by_file(exempt_by_file)
    if holes:
        failed.append(f'見張り番の走査に穴が {len(holes)} 件ある（対応表の照合の前に直す）: '
                      f'{holes[0][:120]}')
    return names, {n: sorted(tool for tool, got in direct.items() if n in got) for n in sorted(names)}


def _exempt_index_of(doc):
    """台帳の豁免を `リポジトリからの正準相対パス -> 許す import と名前` に直す（控制と共有する）

    キーはファイル名ではない（走査対象に同名の `.py` が別ディレクトリに有る為、、名前で引くと
    所属の違う豁免が漏れる。agy 第 65 ラウンド P2-1）"""
    out = {}
    for path in _guard_scan_files():
        rel = path.relative_to(REPO).as_posix()
        got = IN.guard_exempt_map(doc, rel)
        if got:
            out[rel] = got
    return out


def _guard_scan_candidates(exempt_by_file=None):
    """穴で落とす**前の**呼び出し候補（ファイル・名前・行番号）を並べる（Astra 第 64 ラウンド 問 2 裁定 (iii)）

    穴の数はここで見ない。豁免を渡さない走査は未登録の import を穴として挙げるので、
    「豁免なしの走査がそれ自体で通る」ことは要求しない（要求するのは候補の一致）"""
    out = []
    for path in _guard_scan_files():
        _n, _h, _c, calls = _guard_scan(path.read_text(encoding='utf-8'), path,
                                        (exempt_by_file or {}).get(
                                            path.relative_to(REPO).as_posix()))
        out += calls
    return sorted(out)


def _exempt_parity_errors(plain, armed):
    """豁免あり・なしの呼び出し候補を較べて説明文の列で返す（見張り番はここ 1 箇所）

    比較するのは `(ファイル, 名前, 行番号)` の組の集合で、**穴で落とす前**の物を使う
    （落とした後の集合だけ較べると、細工で消えた側が黙って少なくなる。Astra 第 64 ラウンド
    問 2 裁定 (iii)）。ここを引数受け取りにしているのは、控制が細工した 2 組を直接渡して
    「比較が消えたら落ちない」を確かめられるようにする為（実ツリーの一致は正控制がみる）"""
    if not IN.guard('exempt-scan-parity'):
        return []
    if plain == armed:
        return []
    gone = sorted(set(plain) - set(armed))[:4]
    added = sorted(set(armed) - set(plain))[:4]
    return [f'豁免を渡した走査で呼び出し候補が変わった（豁免前 {len(plain)} 件・豁免後 {len(armed)} 件。'
            f'消えた {gone} / 増えた {added}）。豁免は import の禁止だけを緩める物で、見張り番の'
            '呼び出しの読み方（名前・所属・ファイル・行）を動かしてはいけない。'
            'Astra 第 64 ラウンド 問 2 裁定 (iii)）']


def _loader_cover_errors(loader_names=None):
    """台帳の登録禁止が走査側の禁止の名前一覧を**両方**含むか（Astra 第 65 ラウンド 問 1 (c) 1）

    禁止の検査に豁免を渡さない為には、台帳側が `_LOADER_NAMES`（箱経由の取り出し）と
    `_LOADER_ATTRS`（属性名の取り出し）の両方を拒否していなければならない。属性名だけを
    書いた豁免で `importlib.__loader__` を解禁できた実測。見張り番 `exempt-loader-attrs` はここ 1 箇所
    （制御が単独で名指せるように、報告は戻り値で返す）"""
    if not IN.guard('exempt-loader-attrs'):
        return []
    # 制御が箱を書き換えない為、比較する一覧を引数で差し替えられる（既定は `_inputs` の一覧。
    # Astra 第 67 ラウンド 問 2 の移行）
    ledger = IN._LEDGER_LOADER_NAMES if loader_names is None else loader_names
    errs = []
    for label, src in (('`_LOADER_NAMES`', _LOADER_NAMES), ('`_LOADER_ATTRS`', _LOADER_ATTRS)):
        miss = sorted(x for x in src if x not in ledger)
        if miss:
            errs.append(f'豁免の登録禁止が {label} を避けていない {miss[:6]}'
                        '（`_inputs._LEDGER_LOADER_NAMES` へ両方を反映する。'
                        'Astra 第 65 ラウンド 問 1 (c) 1）')
    return errs


def _exempt_map_errors(doc, exempt_by_file):
    """走査へ渡した豁免マップが、検証済みの台帳から作り直した物と一致するか（Astra 問 4 (c) 4）

    候補の一致は豁免マップの正しさを検証しない（Astra 実測: 使われない対象外キーを足しても候補は
    全部一致した）。ここで台帳から**もう一度作り直して**比べる（欠落・余剰・宛先・許可内容のどれが
    変わっても名指す。見張り番 `exempt-map-expand` はここ 1 箇所）"""
    if not IN.guard('exempt-map-expand'):
        return []
    fresh = _exempt_index_of(doc)
    got = dict(exempt_by_file or {})
    errs = []
    for name in sorted(set(fresh) | set(got)):
        want, have = fresh.get(name), got.get(name)
        if want == have:
            continue
        errs.append(f'走査へ渡した豁免が台帳から作り直した物と違う（{name}: '
                    f'台帳 {dict((k, sorted(v)) for k, v in (want or {}).items()) or "無し"} / '
                    f'渡した物 {dict((k, sorted(v)) for k, v in (have or {}).items()) or "無し"}）。'
                    '豁免は `IN.load_guard_ledger` の台帳から `_exempt_index_of` で作る（手で書いた'
                    '物や古い物を渡すと、走査だけが許す形になる）。Astra 第 65 ラウンド 問 4 裁定')
    return errs


def _guard_ledger_errors(doc, exempt_by_file=None):
    """対応表と今の走査を突き合わせて説明文の列で返す（空なら台帳が実測と一致している）

    Astra 第 63 ラウンド 問 4 の裁定で増やした照合（**合計値の固定だけでは同数の入れ替わりが
    通る**）。見るのは 3 つで、それぞれに見張り番を置く。
    `own-names` … 名前集合その物 / `own-tools` … 名前と所属道具の対応 /
    `own-files` … 走査対象のファイル集合と豁免が挙げるファイル

    主にする走査は**豁免を渡した方**（Astra 第 64 ラウンド 問 2 裁定 (iii)）。豁免なしの走査を主に
    すると、正当な豁免を登録した日に「走査に穴が 1 件ある」が先に落ちて台帳の照合へ進めない
    （Codex 第 63 ラウンド P2-1 の実測）。代わりに 2 つを較べる。

    1. 豁免つきの最終的な名前・所属・走査対象と台帳の対応
    2. 豁免あり・なしの両方で走った**穴で落とす前の呼び出し候補**（名前・所属・ファイル・行）が
       完全一致すること（豁免が見張り番の集計その物を動かせないことの確認）

    名前の集合が違う日は**所属の比較をしない**（同じ名前が消えたまま所属を並べると、
    直したのか潰したのか判別できない案内が並ぶ。Astra 第 63 ラウンド 問 2「検証と照合を一体に」）"""
    errs = []
    files = [str(p.relative_to(REPO)) for p in _guard_scan_files()]
    if IN.guard('own-files'):
        got = doc.get('scannedFiles')
        if isinstance(got, list) and all(isinstance(x, str) for x in got):
            miss, extra = sorted(set(files) - set(got)), sorted(set(got) - set(files))
            if miss:
                errs.append(f'対応表の走査対象に無いファイルがある {miss[:6]}（実測 {len(files)} 本・'
                            '台帳 ' + str(len(got)) + f' 本。道具を足した日・走査から脱落した日）。'
                            f'作り直しは `python3 {BATTERY}/emit-guard-owners.py`（候補の書き出し）')
            if extra:
                errs.append(f'対応表が挙げる走査対象 {extra[:6]} が実測に無い'
                            '（台帳が古いか、走査の glob が変わった）')
        for e in doc.get('exemptions') or []:
            f = e.get('file') if isinstance(e, dict) else None
            if isinstance(f, str) and f.strip() and f not in files:
                errs.append(f'対応表の豁免が挙げる {f} は走査対象に無い（豁免は走査の下でだけ'
                            '働くので、走査しないファイルの豁免は無効なまま残り続ける）')
    names, owners = _guard_owners_from_scan(exempt_by_file)
    led = doc.get('owners')
    if isinstance(led, dict):
        if IN.guard('own-names'):
            gone = sorted(set(led) - names)
            new = sorted(names - set(led))
            if gone or new:
                errs.append(f'対応表の見張り番と実測の名前集合が違う（台帳 {len(led)} 名・実測 '
                            f'{len(names)} 名）: '
                            + (f'台帳にある {_format_guard_names(gone)} ' if gone else '')
                            + (f'実測にある {_format_guard_names(new)}' if new else '')
                            + f'（作り直しは `python3 {BATTERY}/emit-guard-owners.py` の候補を'
                            '人がレビューしてコミットする。自動更新はしない）')
                return errs       # 集合が違う日で所属を並べると、直したのか潰したのか判別できない
        if IN.guard('own-tools'):
            moved = [(n, led[n], owners[n]) for n in sorted(set(led) & names) if led[n] != owners[n]]
            if moved:
                errs.append(f'対応表の所属道具と実測が違う見張り番が {len(moved)} 件: '
                            + ', '.join(f'{n}（台帳 {"/".join(a) if isinstance(a, list) else a} / '
                                        f'実測 {"/".join(b)}）' for n, a, b in moved[:5])
                            + '（同じ名前が別の道具へ移った日。一覧を作り直して人がレビューすること）')
    # Astra 第 65 ラウンド 問 4 裁定: 同じ豁免マップでの再走査・比較（旧 `owners2`）は常に
    # 無差分で空回りし、同じ穴の診断を 2 回数えていた（Astra 実測: 豁免 1 件を消すと診断が 2 件）。
    # 削除して、**展開した豁免マップと台帳**の照合に置き換える（作っただけのマップを検査せずに
    # 候補比較へ渡す道を閉じる）
    errs += _exempt_map_errors(doc, exempt_by_file)
    # 見張り番の箱の公開名の一覧と実ツリーの使用（Astra 第 66 ラウンド 追記の裁定 (ア)。
    # 見張り番 `in-public-table` はここで 1 箇所だけ読む）
    if IN.guard('in-public-table'):
        errs += _box_table_errors(doc)
    # 豁免あり・なしの候補比較は豁免マップが空でも走らせる（Astra 問 4 (c) 1: `or None` で空を
    # None に置き換えると、空の作り間違いが検出から消えた。Astra 実測: 明示的な `{}` は穴 2 件、
    # 同じ空を `or None` で渡すと失敗 0 件）
    errs += _exempt_parity_errors(_guard_scan_candidates(),
                                  _guard_scan_candidates(exempt_by_file))
    return errs


def guard_owner_ledger_holds():
    """対応表 `guard-owners.json` と今の走査が一致していることを確かめる正控制（Astra 問 4）"""
    doc = IN.load_guard_ledger(REPO)
    exempt = _exempt_index_of(doc)
    for msg in _loader_cover_errors():
        failed.append(f'{IN.GUARD_LEDGER_FILE}: {msg}')
    for msg in _guard_ledger_errors(doc, exempt):
        failed.append(f'{IN.GUARD_LEDGER_FILE}: {msg}')


def _ledger_mutate(victim_how, mut):
    """対応表を一時的に細工して制御を走らせる（`stash` / `restore` で必ず戻す）"""
    rel = f'{BATTERY}/guard-owners.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    if victim_how == 'names' and len(doc.get('owners') or {}) < 3:
        raise NotDetected('対応表の名前が 3 未満（制御の前提が変わった）')
    # 細工後の台帳から豁免マップを作り直す（Astra 第 65 ラウンド 問 4: 細工前のマップとマージする
    # と、落とすはずの豁免がそのまま走り、展開の間違いも黙って直されていた）。豁免を丸ごと差し替える
    # 細工が「未登録の import」の穴を先に出す問題は、測る対象を関数の直接呼びに絞った控制で避ける
    # （`ledger_exemption_removed` は豁免を 1 件落とした台帳で走査その物を見る）
    mut(doc)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                 encoding='utf-8')
    try:
        return _guard_ledger_errors(doc, _exempt_index_of(doc))
    finally:
        restore()


def ledger_name_missing():
    """台帳から 1 名を消して照合が止まること（`own-names`）"""
    def mut(doc):
        del doc['owners'][sorted(doc['owners'])[-1]]
    errs = _ledger_mutate('names', mut)
    return (1, errs[0]) if errs else False


def ledger_owner_moved():
    """台帳の 1 名の所属道具を別へ動かして止まること（`own-tools`）"""
    def mut(doc):
        name = sorted(doc['owners'])[-1]
        others = sorted({x for v in doc['owners'].values() for x in v if x not in doc['owners'][name]})
        if not others:
            raise NotDetected('所属の宛先になる道具が他に無い（制御の前提が変わった）')
        doc['owners'][name] = [others[0]]
    errs = _ledger_mutate('owners', mut)
    return (1, errs[0]) if errs else False


def ledger_file_missing():
    """台帳の走査対象から 1 ファイル消して止まること（`own-files`）"""
    def mut(doc):
        del doc['scannedFiles'][-1]
    errs = _ledger_mutate('files', mut)
    return (1, errs[0]) if errs else False


def ledger_exemption_unscanned():
    """豁免に走査対象外のファイルを登録して止まること（`own-files`）"""
    def mut(doc):
        # 既存の豁免は無傷に保って 1 件足す（Astra 第 65 ラウンド 問 4: 豁免を差し替えると必要な
        # 豁免が落ちて、測りたい照合まで進まなかった）
        doc['exemptions'] = list(doc.get('exemptions') or []) + [
            {'file': 'skill/scripts/tools/battery/_never_scanned.py',
             'imports': {'types': ['SimpleNamespace']}, 'note': '細工'}]
    errs = _ledger_mutate('exemptions', mut)
    return (1, errs[0]) if errs else False


def ledger_shape_broken():
    """台帳の `owners` の値を配列でなくして、形の検査が同じ見出しで止まること（`own-shape`）"""
    rel = f'{BATTERY}/guard-owners.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    if len(doc.get('owners') or {}) < 3:
        raise NotDetected('対応表の名前が 3 未満（制御の前提が変わった）')
    doc['owners'][sorted(doc['owners'])[-1]] = '_inputs.py'
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                 encoding='utf-8')
    try:
        IN.load_guard_ledger(REPO)
    finally:
        restore()
    return False        # 止まらなかった = 検出無し（見張り番を消した側はここを通って成功する）


def _ledger_doc_mutated(mut):
    """対応表を一時的に細工した**テキスト**を置いて `load_guard_ledger` を通す（Astra 問 2 の控制）

    `raw` を渡すと JSON を組み直さずその文字列をそのまま置く（同じ鍵を 2 度書く細工は
    `json.dumps` では作れない為）。戻り値は `load_guard_ledger` が止まったら `(1, 文面)`、
    止まらなかったら `False`（見張り番を消した側は必ずこっちへ来る）"""
    rel = f'{BATTERY}/guard-owners.json'
    p = stash(rel)
    try:
        if 'raw' in mut:
            p.write_text(mut['raw'], encoding='utf-8')
        else:
            doc = json.loads(p.read_text(encoding='utf-8'))
            mut['fn'](doc)
            p.write_text(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                         encoding='utf-8')
        try:
            IN.load_guard_ledger(REPO)
        except SystemExit as exc:
            return (1, str(exc) or f'exit {exc.code}')
        return False
    finally:
        restore()


def _one_scanned_file(doc):
    """控制が豁免に書くファイル名を台帳から 1 本選ぶ（走査対象外を混ぜない為）"""
    files = doc.get('scannedFiles') or []
    if not files:
        raise NotDetected('対応表に走査対象が 1 本も無い（制御の前提が変わった）')
    return files[0]


def exempt_loader_name_registered():
    """豁免に `FunctionType` の様な動的機構の名前を登録して台帳が止まること（`exempt-loader-name`）

    Astra 第 64 ラウンド 問 2 裁定 (i) の「登録を拒否する」側。見張り番を消すと形の検査自体が
    止まるので同じ細工がそのまま通る（＝この控制はこの見張り番だけを名指している）"""
    def mut(doc):
        doc['exemptions'] = [{'file': _one_scanned_file(doc),
                              'imports': {'types': ['FunctionType']}, 'note': '制御の細工'}]
    return _ledger_doc_mutated({'fn': mut})


def exempt_dup_entry_registered():
    """同じファイルの豁免を 2 件に分裂させて台帳が止まること（`exempt-dup-entry`）

    Astra 第 64 ラウンド 問 2 裁定 (iv) の「同じ import の重複登録」側。2 件とも単体では正しい
    形なので、重複を見ない実装だと黙って通る"""
    def mut(doc):
        f = _one_scanned_file(doc)
        doc['exemptions'] = [
            {'file': f, 'imports': {'importlib': ['util']}, 'note': '制御の細工（1 件目）'},
            {'file': f, 'imports': {'importlib': ['util']}, 'note': '制御の細工（2 件目）'}]
    return _ledger_doc_mutated({'fn': mut})


def ledger_json_dup_key():
    """対応表の JSON に同じ鍵を 2 度書いたら止まること（`json-dup-key`）

    `json.loads` は後の値で黙って畳むので、禁止名を書いた鍵とその取り消しを並べる細工が作れる
    （Astra 第 64 ラウンド 問 2 裁定 (iv)）。`note` を 2 度書く形にして、他の欄を壊さずに
    見張り番を消した側が通るようにする"""
    rel = f'{BATTERY}/guard-owners.json'
    text = (REPO / rel).read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)
    at = [i for i, x in enumerate(lines) if x.startswith(' "note":')]
    if len(at) != 1:
        raise NotDetected(f'対応表のトップレベルの note が {len(at)} 行（制御の前提が変わった）')
    dup = ''.join(lines[:at[0] + 1]) + ' "note": "重複した鍵（制御の細工）",\n' \
        + ''.join(lines[at[0] + 1:])
    return _ledger_doc_mutated({'raw': dup})


def import_unregistered_hole():
    """許可一覧に無い import を走査が穴として挙げるか（`import-unregistered`）

    Astra 第 64 ラウンド 問 1 裁定 (c) で禁止一覧から許可一覧へ切り替えた実測。`socket` は
    走査対象のどこも import していないので、豁免なしでは必ず穴になる"""
    _n, holes, _c, _cl = _guard_scan(f'{_SCAN_HEAD}import socket\nif IN.guard("ok-import"): '
                                     'raise SystemExit(1)\n', '<制御>')
    bad = [h for h in holes if '未登録の import' in h]
    return (1, bad[0]) if bad else False


def import_binds_guard_hole():
    """豁免した import が `guard` を束縛したら穴になるか（`import-binds-guard`）

    Codex 第 64 ラウンド相当の実測（`from builtins import bool as guard` + `guard('fake')` が
    豁免で通り、架空の名前が見張り番として数えた）を、豁免を必要としない形（`json` は
    許可一覧に有る）で再現する。見張り番を消すと束縛の穴だけが消えて他は無傷で通る"""
    src = (f'{_SCAN_HEAD}from json import bool as guard\nif guard("ok-binds"): '
           'raise SystemExit(1)\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>')
    bad = [h for h in holes if '見張り番と同じ名前' in h]
    return (1, bad[0]) if bad else False


def exempt_parity_moved():
    """豁免あり・なしの呼び出し候補の違いを比較が消すか（`exempt-scan-parity`）

    Astra 第 64 ラウンド 問 2 裁定 (iii) の 2 つ目の照合。実ツリーでは差分が出てはいけないので、
    細工で差が出た場合を直接 `_exempt_parity_errors` へ渡す（見張り番を消すと報告が消える）"""
    plain = [('check-dir-rule.py', 'dir-rule-v1', 42)]
    armed = []
    errs = _exempt_parity_errors(plain, armed)
    return (1, errs[0]) if errs else False


def guard_exemption_scope_holds():
    """豁免が**名乗った import と名前だけ**を許すことを対で確かめる（Astra 第 63 ラウンド 問 1）

    受理側（豁免どおりの使い方）と拒否側（同じモジュールでも動的機構の名前）を同じ走査で測る。
    豁免に動的機構の名前を書いても穴が消えないことまで見る（豁免が他の規則を弱めない為の対）"""
    grants = {'types': {'SimpleNamespace'}}
    cases = (
        (True, '豁免どおりの `types.SimpleNamespace`',
         "import types\nns = types.SimpleNamespace()\nimport _inputs as IN\nIN.guard('ex-a')\n",
         grants),
        (False, '同じモジュールの `types.FunctionType`',
         "import types\ntypes.FunctionType(compile('x', 'f', 'exec'), {})\n"
         "import _inputs as IN\nIN.guard('ex-b')\n", grants),
        (False, '豁免に動的機構の名前を書いても穴',
         "import types\ntypes.FunctionType(compile('x', 'f', 'exec'), {})\n"
         "import _inputs as IN\nIN.guard('ex-c')\n", {'types': {'FunctionType'}}),
        (True, '豁免どおりの `from types import SimpleNamespace`',
         "from types import SimpleNamespace\nimport _inputs as IN\nIN.guard('ex-d')\n", grants),
        (False, '豁免に無い名前の `from types import FunctionType`',
         "from types import FunctionType\nimport _inputs as IN\nIN.guard('ex-e')\n", grants),
        (False, '豁免が無いファイルの `import types`',
         "import types\nimport _inputs as IN\nIN.guard('ex-f')\n", None),
    )
    for want_ok, label, src, ex in cases:
        _names, holes, _counts, _calls = _guard_scan(src, 'exempt-probe.py', ex)
        if want_ok and holes:
            failed.append(f'豁免の対の検査「{label}」が通らない（穴 {len(holes)} 件）: {holes[0][:110]}')
        if not want_ok and not holes:
            failed.append(f'豁免の対の検査「{label}」が穴を出さない（豁免が他の規則を弱めた）')


def _guard_switch_callers():
    """見張り番を消す区間を作っているファイルの正準相対パス（候補の `guardCallers`）

    走査と同じ `_box_switch_calls` で数える（候補だけが別の歩き方をして「登録の要らない日」を
    作らない為。Astra 第 67 ラウンド 問 2 の分類共有と同じ筋）"""
    out = set()
    for path in _guard_scan_files():
        tree = ast.parse(path.read_text(encoding='utf-8'))
        boxes, _holes, _tainted, _allowed = _collect_boxes(tree, path, None)
        if _box_switch_calls(tree, boxes):
            out.add(_origin_key(path))
    return sorted(out)


def _guard_caller_ghost_holes(callers, scan_files):
    """台帳 `guardCallers` の登録が走査対象に実在するか（`guard-callers-scope`）

    Codex 第 68 ラウンド P2-1・agy 第 68 ラウンド P1-1 の実測: `missing.py` のような架空の登録・
    走査しない `.mjs` の登録は、台帳の形の検査もファイル別の照合も通る（ファイル別の照合は走査中の
    ファイルについてだけ走る為、存在しない登録はどこからも見られない）。「走査対象に在るか」は
    走査側しか知らない（`_inputs.py` の形の検査はファイルを見ない）"""
    if not IN.guard('guard-callers-scope'):
        return []
    seen = set(scan_files)
    return [f'台帳 `guardCallers` に登録した「{x}」が走査対象の道具に無い'
            '（区間を作れるファイルの登録は走査対象の実在する .py と一致する事。架空の登録は'
            '人が消すまで残り続ける。Codex 第 68 ラウンド P2-1・agy 第 68 ラウンド P1-1）'
            for x in callers if x not in seen]


def _guard_names_by_file(exempt_by_file=None, box=None, callers=None):
    """見張り番の名前をツリーから走査して `(全体名, ファイル別の直接呼び出し, 呼び出し回数, 穴)` を返す

    `box` を渡した走査は**その表**で箱の公開名を検査する（候補生成が古い台帳に縛られない為。
    Astra 第 67 ラウンド 問 3 の裁定 2: 候補表を明示的な引数として共通の走査へ渡し、台帳・
    グローバル状態・既定値は差し替えない）。既定は台帳の `boxNames`

    網羅の正控制と README の名前検査が**同じ走査**を共有する（走査を 2 本持つと、片方だけを直して
    「README は通るが網羅の実測は嘘」が作れる。第 60 ラウンド Codex P2-2 の別名穴と同じ形）"""
    doc = IN.load_guard_ledger(REPO)
    if exempt_by_file is None:
        # 既定も台帳の豁免を渡す。**主は豁免つきの走査**なので、豁免なしの走査が挙げる
        # 「未登録の import」の穴をここで失敗にすると、正当な豁免を登録した日に網羅の検査が
        # 全部止まる（Codex 第 63 ラウンド P2-1 と同じ形。Astra 第 64 ラウンド 問 2 裁定 (iii)）
        exempt_by_file = _exempt_index_of(doc)
    # 見張り番の箱の公開名の一覧（Astra 第 66 ラウンド 追記の裁定 (ア)）。実ツリーの走査は必ず
    # 表を渡すので、表に無い `IN.<名前>` はここから穴として出る
    if box is None:
        box = doc.get('boxNames')
    if callers is None:
        callers = list(doc.get('guardCallers') or [])
    names, direct, counts, holes, calls = set(), {}, {}, [], []
    scan_files = _guard_scan_files()
    for path in scan_files:
        got, got_holes, got_counts, got_calls = _guard_scan(
            path.read_text(encoding='utf-8'), path,
            (exempt_by_file or {}).get(path.relative_to(REPO).as_posix()), box, callers)
        calls += got_calls
        names |= got
        holes += got_holes
        if got:
            if path.name in direct and direct[path.name] != got:
                failed.append(f'{path.name} が同名の道具ファイルとして 2 箇所に見つかる'
                              '（README の道具別一覧はファイル名で対応付けている）')
            direct.setdefault(path.name, set()).update(got)
        for k, v in got_counts.items():
            counts[k] = counts.get(k, 0) + v
    holes += _guard_caller_ghost_holes(callers, [p.relative_to(REPO).as_posix()
                                                for p in scan_files])
    return names, direct, counts, holes, calls


def _format_guard_names(names, limit=6):
    """名前の列を人が読む形に整える（空なら「無し」。第 60 ラウンド agy P2-4 の `[]` 直連結をやめる）"""
    items = sorted(set(names))
    if not items:
        return '無し'
    tail = f' 他 {len(items) - limit} 名' if len(items) > limit else ''
    return ' / '.join(items[:limit]) + tail


README_REGION_HEAD = '<!-- 見張り番の道具別一覧 -->'
README_REGION_END = '<!-- /見張り番の道具別一覧 -->'
# 見張り番の名前一覧の専用区画（Astra 第 65 ラウンド 問 3 の裁定）。「1 列目の見出しが `名前` の
# 表」という形式だけの照合は、同じ形の表を区画の外に置く・マーカーへ文字を足す細工で空になった
# （Astra 実測）。名前一覧はここ専用のマーカーで括り、**その区画だけ**を読む
README_NAMES_HEAD = '<!-- 見張り番の名前一覧:この区画の表だけを見張り番の名前として読む -->'
README_NAMES_END = '<!-- /見張り番の名前一覧 -->'
README_NAMES_COLS = 3
# 見張り番の名前らしき語（小文字と `-` のみ。`coverage` のように `-` を含まない名前的な語も拾う）。
# `.py` / `.json` / `min-0.json` は閉じバッククォートが続けて来ないのでマッチせず、`--オプション` は
# 先頭が `-` なので入らない。読むのは下の 2 区画だけなので、旧名を載せた歴史説明は対象外
# 名前一覧の欄でバッククォートに囲まれた語は**すべて見張り番の名前の候補**とする（Astra 第 62 ラウンド
# 問 2: 規則に合う物だけ拾う読み方をすると、`bad_name` のような誤字を「名前ではない語」として黙って
# 捨てる。候補として拾い、字句規則に合わなければ失敗にする）
BACKTICK = re.compile(r'`([^`]+)`')
README_TOOL_HEAD = re.compile(r'^-\s+`([^`]+)`')
BAD_BULLET = '（箇条書きの形が不正）'


def _name_words(part):
    """名前一覧の欄からバッククォートの語を読み、規則に合わない物は失敗の印として返す

    `_NAME_SHAPE`（コード側と同じ字句規則）に合う物は名前として返し、`.py` / `.json` のような
    ファイル名は読み飛ばし、**それ以外は失敗の印**にします（`new_guard` / `bad_name` / `GuardOne`）"""
    out = []
    for tok in BACKTICK.findall(part):
        if _NAME_SHAPE.fullmatch(tok):
            out.append(tok)
        elif tok.endswith('.py') or tok.endswith('.json') or tok.endswith('.mjs'):
            continue
        else:
            out.append(f'（形が不正な語: {tok}）')
    return out


def _readme_guard_refs(text):
    """README の**見張り番を載せると決めた 2 区画**から `(名前, 道具, 行番号)` を読む（Astra 第 61 ラウンド 問 5）

    読むのは次の 2 区画だけで、どちらも**行全体がちょうどマーカー**の行で括る:

    1. `README_REGION_HEAD` / `README_REGION_END` の箇条書き。行頭のバッククォートが道具のファイル名、
       残りがその道具で**直接呼ぶ**見張り番（共有ヘルパー `_inputs.py` は経由側として明記する）
    2. `README_NAMES_HEAD` / `README_NAMES_END` の表。1 列目だけ名前として読む（`README_NAMES_COLS`
       欄。同じ名前を 2 度載せた行と、1 欄内の重複は失敗。Astra 第 65 ラウンド 問 3）

    区画の外に 1 列目が `名前` の表を置くのは失敗（名前一覧を区画の外へ逃がす細工）。歴史説明に
    旧名を書いた行はどちらの区画にも入らないので検査に混ざらない。形が崩れた行は黙って数えず
    「（ … ）」の印を ref として返す（`_readme_guard_errors` が失敗にする）"""
    refs, in_region, in_names, seen = [], False, False, {}
    lines = text.splitlines()
    fenced = _md_fence_mask(lines)          # フェンスの中は表でも箇条書きでもない（agy 第 63 ラウンド P2-2）
    for no, line in enumerate(lines, 1):
        s = line.strip()
        if fenced[no - 1]:
            continue
        if s in (README_REGION_END, README_NAMES_END):
            in_region, in_names = False, False
            continue
        if s == README_REGION_HEAD:
            in_region = True
            continue
        if s == README_NAMES_HEAD:
            in_names = True
            continue
        if in_region:
            if not s:
                continue
            if not s.startswith('- '):
                # `* ` や `+ ` の箇条書き、ただの文章は**読まないのではなく失敗**（黙って 0 件にしたのが
                # agy 第 63 ラウンド P2-2 の `* ` の細工）
                refs.append((f'（箇条書きの形が不正な行: {s[:24]}）', None, no))
                continue
            m = README_TOOL_HEAD.match(s)
            if not m or not m.group(1).endswith('.py'):
                refs.append((BAD_BULLET, None, no))
                continue
            tool = m.group(1)
            for w in _name_words(s[m.end():]):
                refs.append((w, tool, no))
            continue
        if in_names:
            if not s.startswith('|'):
                refs.append((f'（名前一覧の区画に表ではない行がある: {s[:24]}）', None, no))
                continue
            cells = _md_cells(s)
            if cells and set(''.join(cells)) <= set('-: '):
                continue
            if cells and cells[0].strip('`* ') == '名前':
                if len(cells) != README_NAMES_COLS:
                    refs.append((f'（名前一覧の見出しが {README_NAMES_COLS} 欄ではない: {len(cells)} 欄）',
                                 None, no))
                continue
            if len(cells) != README_NAMES_COLS:
                refs.append((f'（名前一覧の行が {README_NAMES_COLS} 欄ではない: {len(cells)} 欄）',
                             None, no))
                continue
            for w in _name_words(cells[0]):
                if not w.startswith('（'):
                    if w in seen:
                        # Astra 第 65 ラウンド 問 3: 行の重複も 1 欄内の重複も失敗（同じ名前を 2 度
                        # 数えると「名前 1 個 = 控制 1 本」の網羅が水増しになる）
                        refs.append((f'（同じ名前を 2 度載せている: {w}（初めては {seen[w]} 行目））',
                                     None, no))
                        continue
                    seen[w] = no
                refs.append((w, None, no))
            continue
        if not s.startswith('|'):
            continue
        cells = _md_cells(s)
        if len(cells) >= 2 and cells[0].strip('`* ') == '名前':
            refs.append((f'（区画の外に名前一覧と同じ形の表がある: {s[:32]}）', None, no))
    return refs


def _readme_guard_errors(refs, code, direct, text):
    """読んだ名前と実コードを突き合わせて説明文の列で返す（空なら一致。Astra 第 61 ラウンド 問 5）

    検査する向き（agy / Codex 第 62 ラウンド P2 の実測で増やした）:

    1. README の名前 ⊆ 実コード全体（旧名の残りの検出）
    2. 道具別の箇条書き ⇔ その道具の**直接呼び出し**を等価（別経路で現役な名前を別の道具の説明に
       載せた残りと、新しい見張り番を文書へ足さない残りの両方）
    3. 表の「名前」列 ⇔ 実コード**全体**を等価（agy 第 62 ラウンド P2-2 の実測: 表から 1 名を消しても
       箇条書きに残っている為だけに通っていた。Astra 裁定は「箇条書きは道具別に等価、表の名前列は
       実コード全体と等価」。両方が立てば相互一致も自動で決まるので第三の比較は持たない）
    4. 区画マーカーその物の有無（終了マーカーを消すと区画が消えても検査が黙って通っていた）
    5. 形が不正な行（`BAD_BULLET`）。第 61 ラウンドまでは読んだ側で捨てて**黙って 0 件**だった"""
    errs = []
    ls = text.splitlines()
    errs += _marker_errors(ls, 'README.md', README_REGION_HEAD, README_REGION_END, '道具別一覧')
    errs += _marker_errors(ls, 'README.md', README_NAMES_HEAD, README_NAMES_END, '名前一覧')
    bad = [(no, name) for name, _tool, no in refs if name.startswith('（')]
    if bad:
        errs.append(f'README の見張り番一覧に形が不正な語・行が {len(bad)} 件ある'
                    f'（{bad[0][1]} {bad[0][0]} 行目など。箇条書きは「- 道具.py: `名前`」の形、'
                    '名前は英小文字・数字・`-` のみ（`new_guard` も `bad_name` も見張り番の名前では'
                    '無い）。黙って数えない。Codex 第 62 ラウンド P2-3 の「`new_guard` は誤検出、'
                    '`bad_name` は無視」を両方なくした）')
    if not refs:
        errs.append('README の道具別一覧と「名前」列から 1 件も読めない（区画が消えて空集合で成功する）')
        return errs
    unknown = sorted({n for n, _t, _l in refs if not n.startswith('（')} - code)
    if unknown:
        errs.append(f'README に載った見張り番 {_format_guard_names(unknown)} は実コードに無い'
                    '（改名の残りか、実在しない名前の記入）')
    lost = sorted(code - {n for n, tool, _l in refs
                          if tool is None and not n.startswith('（')})
    if lost:
        errs.append(f'実コードの見張り番 {_format_guard_names(lost)} が README の「名前」列に無い'
                    '（表は全件一覧だと宣言している。箇条書きに残っていても表が古いなら不合格。'
                    'agy 第 62 ラウンド P2-2）')
    region = [r for r in refs if r[1]]
    if not region:
        errs.append('README の「見張り番の道具別一覧」の箇条書きが 1 行も読めない（区画が消えた）')
    for tool in sorted({r[1] for r in region}):
        want = {r[0] for r in region if r[1] == tool}
        got = direct.get(tool)
        if got is None:
            errs.append(f'README の道具別一覧が挙げる {tool} は実コードに見つからない')
            continue
        extra = sorted(want - got)
        if extra:
            errs.append(f'{tool} の箇条書きの見張り番 {_format_guard_names(extra)} はその道具で直接'
                        '呼んでいない（別経路で現役な名前の残り。共有ヘルパー経由なら `_inputs.py` の行へ書く）')
        miss = sorted(got - want)
        if miss:
            errs.append(f'{tool} が直接呼ぶ見張り番 {_format_guard_names(miss)} が'
                        ' README の道具別一覧に無い（一覧が古い）')
    missing = sorted(code - {r[0] for r in region})
    if missing:
        errs.append(f'実コードの見張り番 {_format_guard_names(missing)} が'
                    ' README の道具別一覧に無い（新しい見張り番を文書へ足していない）')
    return errs


def readme_guard_names_match_code():
    """README の見張り番の名前が実コードと一致していることを機械に確かめる（第 60 ラウンド agy P2-4。Astra 第 61 ラウンド 問 5）

    第 60 ラウンドの実物で、`edge-order.py` の行は改名前の `child-fail` / `json-parse` と
    **実在しない** `edge-order-groups` を載せていた。`child-fail` と `json-parse` は別経路で現役なので、
    全体名との部分集合検査だけでは通る（Astra 問 5 の理由）。だから道具別の直接呼び出しと突き合わせ、
    検査器自身も偽の入力で測る（Astra 問 5 ④）。歴史説明の旧名は検査しない（読む区画を絞る）"""
    text = (REPO / BATTERY / 'README.md').read_text(encoding='utf-8')
    code, direct, _counts, _holes, _calls = _guard_names_by_file()
    for msg in _readme_guard_errors(_readme_guard_refs(text), code, direct, text):
        failed.append(f'README の見張り番の名前: {msg}')

    def errs_of(mut):
        mut_text = mut(text)
        return _readme_guard_errors(_readme_guard_refs(mut_text), code, direct, mut_text)

    probes = (
        ('実在しない名前へ書き換える',
         lambda s: s.replace('`edge-child-fail`', '`edge-order-groups`'), '実コードに無い'),
        ('別経路で現役な名前へ書き換える',
         lambda s: s.replace('- `edge-order.py`: `edge-child-fail`',
                             '- `edge-order.py`: `child-fail`'), '直接'),
        ('一覧に無い道具を挙げる',
         lambda s: s.replace('- `edge-order.py`:', '- `edge-order-x.py`:'), '実コードに見つからない'),
        ('道具別一覧の区画を消す',
         lambda s: s.replace(README_REGION_HEAD, '<!-- 区画を消した -->'),
         '箇条書きが 1 行も読めない'),
        ('道具別一覧から 1 名を消す',
         # 行の末尾を起点にすると、後に名前を足した日で細工が空振りになる（第 63 ラウンドの実測:
         # `_inputs.py` の行末に `own-shape` を足したら ` / \`v1-derivation\`` が末尾でなくなって
         # 何も消えず、期待した失敗が 0 件になった）。道具 1 行まるごとを書き換える形にして、
         # 名前の並び順に依存しないようにする
         lambda s: s.replace('- `count-none.py`: `none-counters` / `none-expectations`',
                             '- `count-none.py`: `none-counters`', 1), '道具別一覧に無い'),
        ('終了マーカーを消す',
         lambda s: s.replace('<!-- /見張り番の道具別一覧 -->', ''), '終了マーカー'),
        ('表の「名前」列から 1 名を消す',
         lambda s: s.replace('`fp-structural` / ', '', 1), '「名前」列に無い'),
        ('箇条書きの形を崩す',
         lambda s: s.replace('<!-- /見張り番の道具別一覧 -->',
                             '- `README.md`: `child-fail`\n<!-- /見張り番の道具別一覧 -->'),
         '形が不正'),
        ('字句規則に合わない名前を箇条書きへ足す',
         lambda s: s.replace('- `edge-order.py`: `edge-child-fail`',
                             '- `edge-order.py`: `new_guard` / `edge-child-fail`'), '形が不正な語'),
        ('表の「名前」列に `_` 入りの語を足す',
         lambda s: s.replace('`fp-structural`', '`bad_name` / `fp-structural`', 1), '形が不正な語'),
        ('終了マーカーを開始マーカーより前に置く',
         lambda s: s.replace(README_REGION_END + '\n', '', 1)
         .replace(README_REGION_HEAD, README_REGION_END + '\n' + README_REGION_HEAD, 1),
         '開始マーカーより前'),
        # Astra 第 65 ラウンド 問 3: 語尾へ説明を足したマーカー行を正式なマーカーとして読む細工
        ('区画マーカーの行へ文字を足す',
         lambda s: s.replace(README_REGION_HEAD, README_REGION_HEAD + ' この箇所だけ', 1),
         '他の文字が付いている'),
        # 名前一覧を区画の外へ逃がす細工（Astra 第 65 ラウンド 問 3）
        ('名前一覧と同じ形の表を区画の外に置く',
         lambda s: s + '\n\n| 名前 | 見ている物 | 控制 |\n| --- | --- | --- |\n'
                   '| `own-names` | 外に置いた表 | 制御 |\n',
         '区画の外に名前一覧と同じ形の表'),
        # 同じ名前を 2 度載せて網羅を水増しする細工（Astra 第 65 ラウンド 問 3）
        ('名前一覧に同じ名前を 2 度載せる',
         lambda s: s.replace('| `md-fence-form` |', '| `md-fence-form` / `own-names` |', 1),
         '同じ名前を 2 度載せている'),
        ('名前一覧の区画を消す',
         lambda s: s.replace(README_NAMES_HEAD, '<!-- 区画を消した -->'),
         '名前一覧の開始マーカーが 0 個'),
        ('区画をコードフェンスで括る',
         lambda s: s.replace(README_REGION_HEAD, '```\n' + README_REGION_HEAD, 1)
         .replace(README_REGION_END, README_REGION_END + '\n```', 1), 'コードフェンス'),
        ('区画の中に `* ` の箇条書きを足す',
         lambda s: s.replace(README_REGION_END, '* `README.md`: `bad_name`\n' + README_REGION_END, 1),
         '形が不正な行'),
        ('表から消した名前をフェンス内の偽の表へ移す',
         lambda s: s.replace('`fp-structural` / ', '', 1)
         + '\n```\n| 名前 | x |\n| --- | --- |\n| `fp-structural` | x |\n```\n',
         '「名前」列に無い'),
        # agy 第 63 ラウンド P2-3: `~~~` をフェンスとして認識しないと偽の表がフェンスの外に見えた
        ('表から消した名前を `~~~` の偽の表へ移す',
         lambda s: s.replace('`fp-structural` / ', '', 1)
         + '\n~~~\n| 名前 | x |\n| --- | --- |\n| `fp-structural` | x |\n~~~\n',
         '「名前」列に無い'),
    )
    for label, mut, want in probes:
        got = errs_of(mut)
        if not any(want in x for x in got):
            failed.append(f'README 検査の自己検査「{label}」が「{want}」で落ちない: {got[:2]}')
    # 歴史説明に旧名を書いても失敗しない（読む区画を外側に置く約束）
    hist = text + '\n\n第 57 ラウンドでは `edge-order-errors` という名前を使っていた（第 61 ラウンドで廃止）\n'
    if errs_of(lambda s: hist) != errs_of(lambda s: s):
        failed.append('README の歴史説明に書いた旧名が現在名の検査に混ざった（読む区画が広すぎる）')


def guard_names_have_singleton_controls():
    """見張り番に名前を付けた判定すべてに、**その 1 個だけを消して通った**負控制が有る

    README の「全 N 名に個別負控制が有る」を毎回機械に数えさせる。第 57 ラウンド agy P2-2 は
    表に載った制御が実在しない嘘、第 58 ラウンド agy P2-1 は組での名指しだけだったので
    `fp-bytes` を `and False:` に完全無力化しても検出されなかった。Astra 第 59 ラウンド 問 4 の
    裁定どおり、**ソースに書いてある制御は数えず、通った単独名指しだけ**を数える
    （例外台帳は作らない。網羅不足は失敗にする）"""
    tree, _direct, counts, holes, _calls = _guard_names_by_file()
    if holes:
        failed.append(f'見張り番の呼び出し {len(holes)} 件が静的に読めない'
                      f'（網羅の分母から黙って消える）: {holes[:4]}。'
                      '`guard()` の引数は文字列リテラルだけ書き、`guard` を別名に代入しない')
    # **1 名前 = 呼び出し 1 箇所**（Astra 第 60 ラウンド 問 2 の裁定）。同じ名前を複数箇所で
    # 使うと、1 個だけを無力化しても他の箇所が生きているので「その 1 個だけを消して成功」する
    # 控制がそのまま通る（第 59 ラウンド agy P2-3 の 2 の実測）。判定が違うなら名前を分け、
    # 同じ判定ならスイッチの読みを 1 箇所へまとめる（第 60 ラウンドで `none-counters` を実装）
    multi = {k: v for k, v in sorted(counts.items()) if v > 1}
    if multi:
        failed.append(f'見張り番 {list(multi)[:5]} が呼び出し {multi} 箇所で使われている'
                      '（1 箇所だけを消した無力化を単独名指しの控制が検出できない。判定ごとに'
                      '名前を分けるか、同じ判定ならスイッチの読みを 1 箇所にまとめる）')
    print(f'  見張り番 {len(counts)} 名 = 呼び出し {sum(counts.values())} 箇所'
          f'（1 名前 1 箇所{"を満たす" if not multi else f" の規則の破れ {len(multi)} 名"}）')
    declared = set()
    for grp in _negative_guard_groups(pathlib.Path(__file__)):
        declared.update(grp)
    if sorted(tree - declared):
        failed.append(f'見張り番 {_format_guard_names(sorted(tree - declared))} を名指す負控制が 1 本も無い'
                      '（README の網羅の文が嘘になる）')
    if sorted(declared - tree):
        failed.append(f'負控制が名指す {_format_guard_names(sorted(declared - tree))} は検査器で呼ばれていない'
                      '（見張り番の名前の書き間違い）')
    passed = ran['singleton']
    missing = sorted(tree - set(passed))
    if missing:
        failed.append(f'見張り番 {len(missing)} 個は「その 1 個だけを消した」負控制が通っていない'
                      f'（複数名を同時に消す制御は網羅に数えない）: {missing[:8]}')
    # 登録した単独名指しの控制が 1 本でも走っていなければ失敗（Astra 第 60 ラウンド 問 3。
    # 失敗した控制は `negative()` が `failed` に入れるので、ここでは**走っていない**物を見る）
    never = sorted(set(_singleton_controls(pathlib.Path(__file__))) -
                   {(lbl, n) for n, recs in passed.items() for lbl, _t in recs})
    if never:
        failed.append(f'登録だけの単独名指し控制 {len(never)} 本が走っていない'
                      f'（通った控制だけを網羅に数える規則では黙って減る）: {never[:4]}')
    # 網羅の記録が**登録済みの控制からしか生まれていない**事の検査（Astra 第 70 ラウンド 問 3）。
    # キー集合の完全一致だけでは、実在の見張り番の名前へ余計な記録が混入した事を読めない
    unread = _negative_unreadable(pathlib.Path(__file__))
    if unread:
        failed.append('`negative(...)` の呼び出しが静的に読めない（階級と登録の判定が黙って狂う）: '
                      + ' / '.join(unread[:4]))
    registered = {(lbl, n) for lbl, n in _singleton_controls(pathlib.Path(__file__))}
    for e in singleton_record_errors(passed, registered, _singleton_tiers(pathlib.Path(__file__))):
        failed.append(f'網羅の記録が登録済みの控制と対応しない: {e}')
    both = tree & set(passed)
    tiers = {n: {tier for _lbl, tier in recs} for n, recs in passed.items()}
    ok = sorted(n for n in both if tiers[n] == {'clean'})
    fb = sorted(n for n in both if tiers[n] == {'fallback'})
    mix = sorted(n for n in both if len(tiers[n]) > 1)
    print(f'  見張り番 {len(tree)} 個のうち {len(both)} 個に単独名指しの負控制が有り'
          f'（成功だけの控制 {len(ok)} 名 / 診断消失確認だけ {len(fb)} 名 / 両方が並ぶ {len(mix)} 名'
          f'（{_format_guard_names(mix)}）。通った控制 {sum(len(v) for v in passed.values())} 本を'
          '名前ごとに保持し、'
          '後勝ちで潰さない')


def singleton_record_errors(passed, registered, tiers=None):
    """網羅の記録が**登録済みの控制からしか生まれていない**かの検査（Astra 第 70 ラウンド 問 3）

    キー集合の完全一致だけでは、実在の見張り番の名前へ余計な記録が混入した事を読めない。ここでは
    記録 1 件ずつが登録（控制名・見張り番名・階級）と対応する事、同じ記録が二重に並んでいない事を
    見る。`tiers`（`_singleton_tiers()`）を渡した日は、控制の宣言が許さない階級も落とす。自己検査の記録が
    網羅へ入る経路は `_run_negative()` に無いが、将来そこへ手を入れた日を
    この検査が落とす
    """
    errs = []
    for n in sorted(passed):
        recs = passed[n]
        for rec in recs:
            if not isinstance(rec, tuple) or len(rec) != 2:
                errs.append(f'[規則=形] {n}: 網羅の記録の形が壊れている（{rec!r}）')
                continue
            if rec[1] not in ('clean', 'fallback'):
                errs.append(f'[規則=階級未知] {n}: 網羅の記録の階級「{rec[1]}」が未知'
                            '（clean / fallback のどちらか）')
            if tiers is not None and (rec[0], n) in tiers and rec[1] not in tiers[(rec[0], n)]:
                errs.append(f'[規則=階級逆] {n}: 控制「{rec[0]}」の記録の階級「{rec[1]}」が宣言と逆'
                            f'（この控制が取り得るのは {sorted(tiers[(rec[0], n)])}）')
            if (rec[0], n) not in registered:
                errs.append(f'[規則=未登録] {n}: 控制「{rec[0]}」は見張り番 {n} を名指す登録が'
                            '無いのに網羅へ載った'
                            '（実行器の自己検査や未登録の控制が混入した）')
        for rec in set(recs):
            if recs.count(rec) > 1:
                errs.append(f'[規則=重複] {n}: 網羅の記録 {rec!r} が {recs.count(rec)} 件並んでいる'
                            '（集合化して重複を消さない契約）')
    return errs


class _IntervalBoom(BaseException):
    """区間の中で制御が**握り潰さない**例外（`_run_control` の `tolerant` を通り抜ける）"""


class _LeakOnExitState:
    """区間を抜けた後も無効化が残る偽の状態（Astra 第 70 ラウンド 問 2 の③）"""

    def __init__(self):
        self.held = set()

    def read(self):
        return set(self.held)

    def is_off(self, name):
        return name in self.held

    def inside_off(self, names, body):
        self.held |= set(names)
        return body()   # 戻さない


class _RestoreOnExceptionState:
    """例外の時だけ復元される偽の状態（Astra 第 70 ラウンド 問 2 の④）"""

    def __init__(self):
        self.held = set()

    def read(self):
        return set(self.held)

    def is_off(self, name):
        return name in self.held

    def inside_off(self, names, body):
        self.held |= set(names)
        try:
            res = body()
        except BaseException:
            self.held -= set(names)
            raise
        return res   # 正常終了では戻さない


class _DirtyAtSixthReadState:
    """復元後の再実行（観測点⑥）の時にだけ集合が汚れる偽の状態（Codex 第 70 ラウンドの実測の再現）"""

    def __init__(self):
        self.held = set()
        self.reads = 0

    def read(self):
        self.reads += 1
        got = set(self.held)
        return got | {'unrelated'} if self.reads >= 6 else got

    def is_off(self, name):
        return name in self.held

    def inside_off(self, names, body):
        self.held |= set(names)
        try:
            return body()
        finally:
            self.held -= set(names)


def _state_dependent_control(state, gname, mark):
    """`state` を見て落ちる偽制御（実行器の自己検査専用。実行 1 と 3 で落ち、実行 2 で通る）"""

    def _f():
        if state.is_off(gname):
            return (0, '見張り番を消したので通った')
        raise SystemExit(f'{mark}が出た')
    return _f


def _shrinking_control(mark):
    """実行 1 は 4 件、見張り番を消すと 3 件へ減るが**対象の診断は残る**偽制御（問 2 の②）"""
    calls = [0]

    def _f():
        calls[0] += 1
        k = 4 if calls[0] == 1 else 3
        raise SystemExit(f'{mark}の診断が {k} 件')
    return _f


def _record_pollutions(tiers):
    """本番の網羅記録にありそうな**混入の形**を `(ラベル, 細工, 案内, 期待する診断の目印)` で返す

    細工は「実在の見張り番のキーに、実在の控制名と実在の階級を乗せる」までが本物なので、キー集合の
    一致だけでは読めない。加えて第 73 ラウンドで双人レビューが同じ所を突いた:

    - 混入の名前を既存の記録や登録と衝突させると、細工が「未登録の混入」ではなく「二重計上」に
      化ける（Codex P2-1）。なので**まだ使われていない名前**を選んで足す
    - 記録の書き換えを control 名で探すと同名の先頭記録を掴んで、**選んだ物と違う記録**を上書きし、
      結果として変更ゼロになり得る（Codex P2-2）。なので**記録の位置**で書き換える
    - 各細工は自分はどの診断を増やすべきか（4 番目の目印）を添える。自己検査は差分の**件数**をその
      目印で数えて確かめる（別の診断が増えただけで「検出した」と通るのを防ぐ。agy P2-1）
    """
    out = []
    keys = [n for n in sorted(ran['singleton']) if ran['singleton'][n]]
    if not keys:
        return out
    used = {lbl for recs in ran['singleton'].values() for lbl, _ in recs}
    used |= {lbl for lbl, _ in tiers}
    intruder = next(f'網羅に有り得ない控制 {i}' for i in range(1000)
                    if f'網羅に有り得ない控制 {i}' not in used)
    victim = keys[0]
    out.append(('記録の形が壊れる',
                lambda c: c[victim].append('記録でない物'),
                '網羅の記録の形が壊れても網羅の検査が黙っている',
                '形'))
    out.append(('実在のキーへの未登録の混入',
                lambda c: c[victim].append((intruder, 'clean')),
                '実在の見張り番のキーへ登録の無い記録を足しても網羅の検査が黙っている',
                '未登録'))
    dup_key = next((n for n in keys if len(set(ran['singleton'][n])) == len(ran['singleton'][n])),
                   None)
    # 既に重複の有るキーへ戻すと、細工は「3 件並んでいる」を出して目印の件数が**減る**
    # （agy 第 74 ラウンド P2-1: 重複済みのキーしか無い日に細工が空振りになった）
    if dup_key is not None:
        out.append(('同じ記録の二重計上',
                    lambda c: c[dup_key].append(list(c[dup_key])[0]),
                    '同じ記録が 2 件並んでも網羅の検査が黙っている',
                    '重複'))
    for n in keys:
        for pos, (lbl, tier) in enumerate(ran['singleton'][n]):
            if (lbl, n) not in tiers:
                continue                  # 未登録の記録は階級の検査自体が働かない（選んでも無意味）
            other = 'clean' if tier == 'fallback' else 'fallback'
            if other in tiers.get((lbl, n), set()):
                continue                  # 宣言が両階級を許す控制では反則にならない
            out.append(('登録と逆の階級',
                        lambda c, n=n, pos=pos, lbl=lbl, other=other: c[n].__setitem__(
                            pos, (lbl, other)),
                        f'控制「{lbl}」の階級を宣言が許さない `{other}` に替えても網羅の検査が黙っている',
                        '階級逆'))
            out.append(('階級が unknown になる',
                        lambda c, n=n, pos=pos, lbl=lbl: c[n].__setitem__(pos, (lbl, '知らない値')),
                        f'控制「{lbl}」の記録の階級が clean / fallback のどちらでもなくても黙っている',
                        '階級未知'))
            return out
    return out


def _runner_self_check():
    """実行器自身の自己検査（Astra 第 70 ラウンド 問 2 (エ)。網羅とは別建てで数えない）

    偽の状態と偽の制御を `_run_negative()` へ渡して、**実行器が失敗を記録するか**だけを見る。偽物が
    自分で期待する失敗を返す検査はしない。実在の箱 `IN` は汚さず、`failed` と `ran` へ手を出さない
    こともここで確かめる
    """
    mark = '自己検査の対象の見張り番'
    bad = []
    n_failed = len(failed)
    snapshot = {k: list(v) for k, v in ran['singleton'].items()}

    def _one(label, fn, gname, state, expect_sub, expect_raise=False):
        out = []
        ctl = _state_dependent_control(state or _REAL_STATE, gname, mark) if fn is None else fn
        try:
            _run_negative(label, ctl, (gname,), mark, True, None, out, state)
        except BaseException as e:  # noqa: BLE001 - 例外を成功にしない事を確かめる為に見る
            if not expect_raise:
                bad.append(f'{label}: 実行器が例外を投げて終わった（失敗として記録する）: '
                           f'{type(e).__name__}: {e}')
                return
            out.append(f'（実行器から例外が抜けた: {type(e).__name__}）')
            return
        if expect_raise:
            bad.append(f'{label}: 例外が実行器から伝わらない（握り潰して成功にした）')
            return
        got = ' / '.join(out)
        if expect_sub is None:
            if out:
                bad.append(f'{label}: 正常な実行が失敗を記録した: {got[:200]}')
        elif not out:
            bad.append(f'{label}: 実行器が失敗を記録しなかった（偽合格）')
        elif expect_sub not in got:
            bad.append(f'{label}: 期待した失敗「{expect_sub}」が違う: {got[:200]}')

    # ① 見張り番を消した側でも同じ診断が残る偽制御
    _one('① 無効化しても同じ診断が出続ける偽制御', lambda: (1, f'{mark}が出続ける'), 'self-check-a',
         None, '消したのに同じ案内が出た')
    # ② 4 件 → 3 件へ減る偽制御（件数だけ減っても対象の診断が消えていない）
    _one('② 診断が 4 件から 3 件へ減る偽制御', _shrinking_control(mark), 'self-check-b', None,
         '消したのに同じ案内が出た')
    # ③ 区間を抜けた後に無効化が残る
    _one('③ 区間を抜けた後に無効化が残る', None, 'self-check-c', _LeakOnExitState(),
         '区間を抜けた直後')
    # ④ 例外の時だけ復元される区間（正常終了では戻らない）
    _one('④ 例外の時だけ復元される区間（正常終了）', None, 'self-check-d',
         _RestoreOnExceptionState(), '区間を抜けた直後')
    # ④の続き。例外で終わるときは復元されており、実行器は例外を成功にしない
    st_e = _RestoreOnExceptionState()

    def _boom():
        if st_e.is_off('self-check-e'):
            raise _IntervalBoom('区間の中で制御が壊れた')
        raise SystemExit(f'{mark}が出た')
    _one('④の続き 例外で終わる区間は復元され例外はそのまま抜ける', _boom, 'self-check-e',
         st_e, None, expect_raise=True)
    # ⑥ 復元後の再実行の時にだけ集合が汚れる（Codex 第 70 ラウンドの実測の再現）
    _one('⑥ 復元後の再実行の時にだけ集合が汚れる', None, 'self-check-f',
         _DirtyAtSixthReadState(), '復元後の再実行の終了後')
    # 本番の箱を通す正常系（3 回実行して失敗が無い事）
    _one('本番の箱での正常な 3 回実行', None, 'self-check-g', None, None)

    # 網羅の記録の検査が 3 形の混入を落とす事（Astra 第 70 ラウンド 問 3 と双人レビュー Codex P2）
    # 本番の記録のコピーで測るので、網羅その物は壊さない
    if ran['singleton']:
        registered = {(lbl, n) for lbl, n in _singleton_controls(pathlib.Path(__file__))}
        tiers = _singleton_tiers(pathlib.Path(__file__))
        if not tiers:
            bad.append('`negative(...)` の宣言が 1 件も読めず、階級の検査が空振りしている')
        forms = _record_pollutions(tiers)
        if not forms:
            bad.append('網羅の記録が 1 件も無く、混入の細工を 1 つも測れない')
        # 本番の記録自体が既に違反している日に検出が隠れない様に、また**別の診断が増えただけ**で
        # 通らない様に、細工が宣言した目印の件数で確かめる（agy 第 72 P2-3 / Codex・agy 第 73）
        base = singleton_record_errors({k: list(v) for k, v in ran['singleton'].items()},
                                       registered, tiers)
        for label, forge, why, mark in forms:
            copy = {k: list(v) for k, v in ran['singleton'].items()}
            forge(copy)
            前 = sum(1 for e in base if e.startswith(f'[規則={mark}]'))
            後 = sum(1 for e in singleton_record_errors(copy, registered, tiers)
                     if e.startswith(f'[規則={mark}]'))
            if 後 <= 前:
                bad.append(f'{label}: {why}（目印「{mark}」の診断が {前} 件から {後} 件）')
        作れなかった = {'記録の形が壊れる', '実在のキーへの未登録の混入', '同じ記録の二重計上',
                    '登録と逆の階級', '階級が unknown になる'} - {f[0] for f in forms}
        if 作れなかった:
            bad.append(f'混入の細工を {sorted(作れなかった)} 作れず、自己検査が黙って省略した')
    if len(failed) != n_failed:
        bad.append(f'自己検査が本番の失敗記録へ手を出した（{n_failed} 件 → {len(failed)} 件）')
    if ran['singleton'] != snapshot:
        違い = {k: (snapshot.get(k), ran['singleton'].get(k)) for k in sorted(
            set(snapshot) | set(ran['singleton'])) if snapshot.get(k) != ran['singleton'].get(k)}
        bad.append(f'自己検査が網羅の記録その物を変えた（共通実行器は網羅へ登録しない契約）: {違い}')
    return ' / '.join(bad) if bad else None


_SCAN_HEAD = 'import _inputs as IN\n'


def _scan_of(body):
    """制御用の短いソースを `_guard_scan` に読ませて（名前集合、穴、件数）を返す"""
    names, holes, counts, _calls = _guard_scan(_SCAN_HEAD + body, '<制御>')
    return names, holes, counts


def scanner_reads_only_allowed_syntax():
    """見張り番の読み方として**許可した構文以外**を、スキャナが穴として出す（第 60 ラウンド双人レビューの [2]）

    第 60 ラウンドまでは `ast.Assign` だけの列挙で、Codex と agy が挙げた形が名前集合にも
    穴の列にも出なかった。第 61 ラウンド Astra 問 2 の裁定 (ii) は「数えるのは `guard('名前')` と
    `IN.guard('名前')` の直接呼びだけ。それ以外で見張り番に触れたら取り出した時点で穴」なので、
    下の表の各行が**穴を出し、しかも網羅に名前を足さない**ことを見る。対照（通る側）は
    正規の呼び出し・コメント・説明文・通常の AST 属性取得

    報告は `failed.append`（`positive()` は戻り値も見るが、他の正控制と同じ形に揃える）"""
    IN_ = 'IN'
    bad_forms = [
        ('変数引数', "if guard(name):\n    raise SystemExit(1)\n"),
        ('別名代入', "check = IN.guard\nif check('uncovered'):\n    raise SystemExit(1)\n"),
        ('注釈付き代入', "g: object = IN.guard\nif g('uncovered'):\n    raise SystemExit(1)\n"),
        ('分割代入', "a, b = IN.guard, 1\nif b:\n    a('uncovered')\n"),
        ('ウォルラス', "if (g := IN.guard)('uncovered'):\n    raise SystemExit(1)\n"),
        ('import で取り出し', "from _inputs import guard as g\nif g('uncovered'):\n    raise SystemExit(1)\n"),
        ('getattr', "if getattr(IN, 'guard')('uncovered'):\n    raise SystemExit(1)\n"),
        ('functools.partial', "import functools\np = functools.partial(IN.guard)\np('uncovered')\n"),
        ('コンテナへ格納', "from types import SimpleNamespace\n"
                          "box = SimpleNamespace(guard=IN.guard)\nbox.guard('uncovered')\n"),
        ('globals 経由', "if globals()['guard']('uncovered'):\n    raise SystemExit(1)\n"),
        ('__dict__ 経由', "import _inputs\n"
                          "if _inputs.__dict__['guard']('uncovered'):\n    raise SystemExit(1)\n"),
        ('exec', "exec(\"IN.guard('uncovered')\")\n"),
        ('eval', "if eval(\"IN.guard('uncovered')\"):\n    raise SystemExit(1)\n"),
        ('__getattr__ 定義', "def __getattr__(name):\n    return IN.guard(name)\n"),
        ('結果だけ返すラッパ', "def mycheck():\n    return IN.guard('uncovered')\n"),
        ('lambda ラッパ', "w = lambda: IN.guard('uncovered')\nw()\n"),
        ('ローカル変数経由のラッパ', "def mycheck():\n    ok = IN.guard('uncovered')\n    return ok\n"),
        ('仮引数が guard', "def f(guard):\n    return guard('uncovered')\n"),
        ('ループ変数が guard', "for guard in [IN.guard]:\n    guard('uncovered')\n"),
        ('見張り番を返す', "def give():\n    return IN.guard\n"),
        # Codex 第 63 ラウンドが実測で穴 0 件と出した 6 形（第 64 ラウンドで潰した）
        ('`object.__subclasses__()`', "subs = object.__subclasses__()\n"),
        ('`sys.__loader__`', "import sys\nl = sys.__loader__\n"),
        ('`sys._getframe()`', "import sys\nf = sys._getframe()\n"),
        ('`ctypes` import', "import ctypes\ndll = ctypes.PyDLL(None)\n"),
        ('`code` module 経由', "import code\ncode.InteractiveInterpreter().runsource("
                               "\"IN.guard('uncovered')\")\n"),
        ('`compile` から作った関数', "f = compile(\"IN.guard('uncovered')\", '<s>', 'eval')\n"),
        ('`from sys import modules`', "from sys import modules\n"),
        ('許可一覧に無い import', "import socket\ns = socket.socket()\n"),
    ]
    for label, body in bad_forms:
        names, holes, counts = _scan_of(body)
        if not holes:
            failed.append(f'許可していない見張り番の読み方「{label}」を穴として報告しない')
        if 'uncovered' in names or counts.get('uncovered'):
            failed.append(f'許可していない見張り番の読み方「{label}」の名前を網羅に数えた: '
                          f'{sorted(names)} / {counts}')
        if len(holes) > 24:
            failed.append(f'制御「{label}」で穴が {len(holes)} 件出た（同じ形を何度も数えすぎ）')
    good_forms = [
        ('正規の直接呼び', "if IN.guard('ok-direct'):\n    raise SystemExit(1)\n"),
        ('許可一覧に有る import を併用', "import json\nd = json.loads('{}')\n"
                                      "if IN.guard('ok-import'):\n    raise SystemExit(1)\n"),
        ('同じ名前を 2 箇所', "if IN.guard('ok-twice'):\n    raise SystemExit(1)\n"
                             "if IN.guard('ok-twice'):\n    raise SystemExit(1)\n"),
        ('コメントと説明文', "# IN.guard('ok-comment') は実行されない\n"
                             "def d():\n    \"IN.guard(\"\")\"\n    return 1\n"),
        ('通常の AST 属性取得', "def e(node):\n    return getattr(node, 'id', '')\n"),
        ('同じ判定をする共有検査関数', "def shared(tag):\n    if IN.guard('ok-shared'):\n"
                                   "        return f'{tag} が消えた'\n    return None\n"),
    ]
    for label, body in good_forms:
        names, holes, counts = _scan_of(body)
        if holes:
            failed.append(f'正規の見張り番の読み方「{label}」を穴として報告した: {holes[:1]}')
    _names, _holes, counts = _scan_of("if IN.guard('ok-twice'):\n    pass\n"
                                      "if IN.guard('ok-twice'):\n    pass\n")
    if counts.get('ok-twice') != 2:
        failed.append(f'同じ名前の 2 箇所が呼び出し回数に載らない: {counts}')
    if IN_ != 'IN':
        raise NotDetected('制御の前提（`IN` という別名）が変わった')


def runner_contract_holds():
    """正控制・負控制の**実行契約**を偽控制で直接試す（第 60 ラウンド双人レビューの [1]。Astra 問 4）

    「AST を読めば失敗の伝達が保証できる」メタ控制は採らない。`return legit`（成功時の残り物）と
    `return \'検出漏れ\'`（失敗）は構文が同じで意味が違うから、意味は実行で確かめる。ここでの
    報告は `positive()` 経由ではなく自分の `failed.append` で出す（**`positive()` が戻り値を捨てる
    変種に戻しても落ちる**為。Astra 問 4 ③）"""
    keep_failed, keep_ran = list(failed), dict(ran)
    # `singleton` は名前ごとの list を**作り直して**持つ（同じオブジェクトを共有したまま
    # 契約の偽控制を走らせると、見張り番に存在しない名前が網羅の数へ混ざる）
    keep_ran['singleton'] = {k: list(v) for k, v in ran.get('singleton', {}).items()}

    def probe_pos(label, fn, want_failure):
        del failed[:]
        ran['positive'] = 0
        positive(f'契約-{label}', fn)
        got = [x for x in failed if x.startswith(f'契約-{label}')]
        if want_failure and not got:
            out.append(f'正控制の契約: {label} が失敗として記録されない（{failed}）')
        if not want_failure and got:
            out.append(f'正控制の契約: {label} が失敗になった（成功しなければならない）: {got[:1]}')

    out = []
    probe_pos('None を返す', lambda: None, False)
    probe_pos('失敗の文字列を返す', lambda: 'スキャナが穴を見逃した', True)
    probe_pos('真になる値を返す', lambda: ['検査したファイル'], True)
    probe_pos('子プロセスの結果を返す', lambda: (0, 'ok'), True)
    probe_pos('NotDetected', lambda: (_ for _ in ()).throw(NotDetected('準備失敗')), True)
    probe_pos('SystemExit', lambda: (_ for _ in ()).throw(SystemExit(1)), True)
    probe_pos('例外', lambda: (_ for _ in ()).throw(ValueError('制御が壊れている')), True)

    LBL_APPEND = 'failed に足して None を返す'

    def appends_then_none():
        failed.append(f'契約-{LBL_APPEND}: 自分で出した診断')
    probe_pos(LBL_APPEND, appends_then_none, True)

    def probe_run(label, fn, want_detected, want_text=None):
        try:
            det, text = _run_control(fn)
        except NotDetected as e:
            det, text = False, 'NotDetected: ' + str(e)
        except Exception as e:  # noqa: BLE001 - tolerant でない側は再throwなので捕捉する
            det, text = True, f'{type(e).__name__}: {e}'
        if det != want_detected:
            out.append(f'負控制の契約: {label} の検出判定が {det}（期待 {want_detected}）: {text[:60]}')
        if want_text is not None and want_text not in text:
            out.append(f'負控制の契約: {label} の文面に「{want_text}」が無い: {text[:60]}')

    probe_run('非 0 終了', lambda: (_ for _ in ()).throw(SystemExit(1)), True, 'exit 1')
    probe_run('0 終了', lambda: (_ for _ in ()).throw(SystemExit(0)), False, 'exit 0')
    probe_run('文字列 return', lambda: 'ただの文字列', False)
    probe_run('(1, 文面) タプル', lambda: (1, 'REJECTED: args'), True, 'REJECTED')
    probe_run('(0, 文面) タプル', lambda: (0, '通った'), False, '通った')
    probe_run('NotDetected', lambda: (_ for _ in ()).throw(NotDetected('x')), False, 'NotDetected')

    def probe_neg(label, fn, want_reason, **kw):
        """`negative()` へ偽控制を渡して**どの理由で記録されたか**を見る（Astra 問 4 ④）

        `guards` には実在しない名前 `FAKE` を入れる（実在の名前にすると `ran['singleton']` の
        網羅へ混ざる。最後で `ran` を戻すので記録は残らない）"""
        del failed[:]
        ran['negative'] = 0
        negative(f'契約-{label}', fn, guards=FAKE, **kw)
        got = [x for x in failed if x.startswith(f'契約-{label}')]
        if want_reason is None:
            if got:
                out.append(f'負控制の契約: {label} が失敗になった（成功しなければならない）: {got[:1]}')
        elif not any(want_reason in x for x in got):
            out.append(f'負控制の契約: {label} が「{want_reason}」で記録されない: {got[:1]}')

    FAKE = '契約-見張り番'

    def always_fail():
        raise SystemExit('契約-常に落ちる: 見張り番の有無とか関係無く落ちる')

    # 偽控制が見張り番の ON / OFF を見るのは `IN.GUARD_OFF` を直接読む形にする。`IN.guard(FAKE)` のように
    # **変数で引数を渡す書き方は許可構文ではない**ので、実ツリーの網羅検査が穴として落とす
    # （そのことを第 61 ラウンドの実測で確認した: `IN.guard(FAKE)` を 2 箇所書いた実行は
    # 「見張り番の呼び出し 2 件が静的に読めない」で終了 1 になった）。ここは検査器自身の状態を
    # 見るだけで、合否判定の見張り番ではない
    def switched_on():
        return FAKE not in IN.GUARD_OFF

    def switch_fail():
        """見張り番が立っている間は対象の案内、消すと**別の診断**で落ちる偽控制"""
        if switched_on():
            raise SystemExit('契約-対象の診断: 形が壊れている')
        raise SystemExit('契約-別の診断: 後段の検査で拒否した')

    def off_not_detected():
        """見張り番を消すと**制御自身の準備に失敗**する偽控制（成功に化けてはいけない）"""
        if switched_on():
            raise SystemExit('契約-対象の診断: 形が壊れている')
        raise NotDetected('見張り番を消した側で準備が終わらない')

    probe_neg('見張り番を消しても同じ案内が残る', always_fail, '消したのに同じ案内が出た',
              message='契約-常に落ちる')
    probe_neg('見張り番を消した側が準備失敗', off_not_detected, '制御の準備失敗で終わった',
              message='契約-対象の診断')
    probe_neg('clean=True で OFF 側が別の診断', switch_fail, '消しても別の所で落ちる',
              message='契約-対象の診断')
    probe_neg('clean=False で fallback 未宣言', switch_fail, 'clean=False は fallback に',
              clean=False, message='契約-対象の診断')
    probe_neg('clean=False と fallback が揃う', switch_fail, None,
              clean=False, fallback='契約-別の診断', message='契約-対象の診断')

    with IN.guards_on():
        # 制御の契約を見る区間だけ見張り番を全部生かす（区間が抜けたら外の設定へ戻る）。
        # 第 67 ラウンドまでは `IN.set_guard_off()` で消して戻していた（Astra 第 68 ラウンド 問 1）
        del failed[:]
        ran['negative'] = 0
        negative('契約-見張り番なしで通る制御', lambda: None, guards=())
        if not [x for x in failed if '見張り番なし' in x]:
            out.append('負控制の契約: 落ちずに通った制御が失敗として記録されていない')
    del failed[:]
    ran['positive'] = 0
    positive('契約-生の実行は何も返さない', lambda: None)
    if failed:
        out.append(f'契約用の走りで失敗が残った: {failed[:1]}')

    failed[:] = keep_failed
    ran.clear()
    ran.update(keep_ran)
    for line in out:
        failed.append(line)


DECISIONS_HEAD = '<!-- 決めの表:この区画の全データ行が 4 欄であることを検査の検査が確かめる -->'
DECISIONS_END = '<!-- /決めの表 -->'
DECISIONS_FILE = 'docs/decisions.md'
DECISIONS_COLS = 4
DECISIONS_HEADER = ('| # | 決定 | 根拠（実測） | 取り替える条件 |', '| --- | --- | --- | --- |')
_DECISION_NUM = re.compile(r'\d+(?:-\d+)*')


FENCE = '```'
_FENCE_LOOK = ('```', '~~~')


_MD_PREFIX = re.compile(r'^(?:>\s*|[-*+]\s+|\d+[.)]\s+)')


def _fence_looks(line):
    """行がコードフェンスの行に**見える**か（Astra 第 64 ラウンド 問 3 裁定 (b)）

    禁止の形（`~~~`・4 個以上・情報文字列付き・字下げ・引用・箇条書きの中）も「見える」に含まれる。
    見える行を全部フェンスとして扱うのではなく、**禁止形その物を失敗にする**のが裁定の要点
    （「許可したフェンス以外は普通の文章として扱う」実装では細工が残る）。Astra 第 65 ラウンド
    問 3 の裁定で、引用の空白なし（`>`）と番号付きの書き出し（`1. ` / `2) `）の接頭辞も剥がす
    （`> ``` ` と `1. ``` ` が候補として見えていなかった実測）"""
    # 接頭辞の**前に空白が有る**形（`  - ``` ` / `  1. ``` ` / `  > ``` `）もフェンスに見える。
    # 第 65 ラウンドまでは接頭辞を行く前に空白を詰めていなかったので、字下げの中のフェンスが
    # 候補に見えていなかった（agy 第 65 ラウンド P2-2 の実測: 3 形で 0 件）
    body = line.expandtabs().lstrip()
    while True:
        m = _MD_PREFIX.match(body)
        if not m:
            break
        body = body[m.end():].lstrip()
    return body.startswith(_FENCE_LOOK)


def _md_fence_state(lines, origin=''):
    """(各行がフェンス内か, 形の問題) を**1 回の読み**で返す（Astra 第 65 ラウンド 問 3）

    フェンスとして数えるのは**改行を除いた行全体がバッククォート 3 個だけ**の行だけ。末尾の空白・
    TAB を含む行、4 個以上、`~~~`、情報文字列付き、字下げ、引用、番号付きの書き出しは「フェンスらしく
    見える行」として失敗にし、**開閉としては数えない**（Astra 実測: 形検査では失敗、集計では閉じた
    と読む実装のズレで `s = "```"` の細工が生きた。フェンスの中で孤立した 4 個の行も同じ規則で
    失敗にする）"""
    mask, errs, inside = [], [], False
    for i, line in enumerate(lines, start=1):
        if line == FENCE:
            inside = not inside
            mask.append(True)
            continue
        if _fence_looks(line):
            errs.append(f'{origin}:{i} コードフェンスの行が許可した形ではない '
                        f'（`{line.strip()[:24]}`。フェンスは**行全体がバッククォート 3 個だけ**で、'
                        '末尾の空白や TAB も付けない。情報文字列・4 個以上・`~~~`・字下げ・引用・'
                        '番号付きの書き出しは許可しない。Astra 第 64 ラウンド 問 3 / 第 65 ラウンド 問 3）')
        mask.append(inside)
    if inside:
        errs.append(f'{origin} コードフェンスが閉じられていない（開いた行と閉じた行の数が合わない。'
                    '閉じ忘れは以後の行が全部フェンス内に見えてしまう）')
    return mask, errs


def _fence_form_raw_errors(lines, origin):
    """文書全体のコードフェンスの形を見る（Astra 第 64 ラウンド 問 3 裁定 (b)）

    許可するのは**行全体がバッククォート 3 個だけ**の行。情報文字列（``` に `sh` を足す形）、
    4 個以上のフェンス、`~~~`、字下げ・引用・箇条書きの中、閉じ忘れを失敗にする。
    開閉の素朴なトグルは「4 個のフェンスの中に 3 個の行を置く」細工で途中閉じと誤認された
    （agy / Codex 第 63 ラウンド P2-3 の `~~~` と 4 個の実測）。見張り番を消した制御の自己検査が
    使えるように、ここは `guard` を読まない（報告は `_fence_form_errors` が 1 箇所で行う）"""
    return _md_fence_state(lines, origin)[1]


def _fence_form_errors(lines, origin):
    """上の報告を見張り番 `md-fence-form` でまとめて出す（見張り番の呼び出しはここ 1 箇所）"""
    if not IN.guard('md-fence-form'):
        return []
    return _fence_form_raw_errors(lines, origin)


def _md_fence_mask(lines):
    """各行がコードフェンス（``` の行で挟まれた区間）の中か、フェンス行自身か（agy 第 63 ラウンド P2-2）

    フェンスの中は**表でも箇条書きでもない**（Markdown のレンダリングでもそうなる）。中を表として
    読むと、リアルな表から名前を消してフェンス内の偽の表へ移す細工が通る。禁止形（`~~~`・4 個以上・
    情報文字列付き）もフェンスとして**中は読まない**（読んでしまうのが agy / Codex 第 63 ラウンド
    P2-3 の `~~~` の細工）。禁止形その物は `_fence_form_errors` が別に落とす"""
    # 形検査と同じ読みを共有する（Astra 第 65 ラウンド 問 3: 禁止形をここで開閉に数えると、
    # 「形は失敗・集計は通る」のズレが残る）
    return _md_fence_state(lines)[0]


def _ends_unescaped_pipe(line):
    """表の行が**エスケープされていない**縦棒で閉じているか（agy 第 63 ラウンド P2-3）

    `| 88 | a | b | c | trailing_garbage` は閉じ縦棒が無くても 4 欄に見えた（最初の縦棒と最後の
    疑似欄を落として数える為）"""
    s = line.rstrip()
    if not s.endswith('|'):
        return False
    back, j = 0, len(s) - 2
    while j >= 0 and s[j] == '\\':
        back += 1
        j -= 1
    return back % 2 == 0


def _marker_errors(lines, origin, head, end, what):
    """区画マーカーの行の形・個数・順序・フェンスの有無を見て説明文の列で返す

    Astra 第 65 ラウンド 問 3 の裁定: マーカーは**行全体がちょうどその文字列**の物だけを採用し、
    語尾に説明を足す・引用や番号付きの書き出しの中に入れる・コードフェンスの中に来る行を「マーカーに見える行」
    として挙げて失敗にする（Astra 実測: 語尾へ文字を足したマーカーは README で容認、`docs/
    decisions.md` は正しい区画を残したまま偽のマーカー行を足すと 0 件で通った）。
    見張り番 `md-marker-form` はこの関数で 1 箇所だけ読む（README と決めの表で共有する）"""
    if not IN.guard('md-marker-form'):
        return []
    errs = []
    mask = _md_fence_mask(lines)
    heads = [i for i, x in enumerate(lines) if x == head]
    ends = [i for i, x in enumerate(lines) if x == end]
    for i, x in enumerate(lines):
        if (head in x or end in x) and x != head and x != end:
            errs.append(f'{origin}:{i + 1} {what}の区画マーカーに他の文字が付いている'
                        f'（`{x.strip()[:44]}`。マーカーは行全体がちょうどその文字列。語尾に説明を'
                        '足す・引用や番号付きの書き出しの中に入れる・フェンスの中に入る行は区画のマーカーとして'
                        '読まない。Astra 第 65 ラウンド 問 3）')
    for label, got in (('開始', heads), ('終了', ends)):
        if len(got) != 1:
            errs.append(f'{origin} {what}の{label}マーカーが {len(got)} 個ある'
                        '（1 個でなければならない。0 個は区画が消えた日、2 個以上は**最初の 1 組'
                        'しか読まれない**ので壊れた区画を後に隠せる。agy 第 63 ラウンド P2-2 / '
                        'Astra 第 65 ラウンド 問 3）')
    if len(heads) >= 1 and len(ends) >= 1 and heads[0] > ends[0]:
        errs.append(f'{origin} {what}の区画で終了マーカーが開始マーカーより前に有る'
                    '（区画が空になり、実末尾の終了マーカーを消しても通った。agy 第 63 ラウンド P2-2）')
    if len(heads) == 1 and len(ends) == 1:
        if mask[heads[0]] or mask[ends[0]]:
            errs.append(f'{origin} {what}の区画マーカーがコードフェンスの中に有る'
                        '（フェンスで括られた区画はレンダリングでも表・箇条書きにならない。'
                        'マーカーをフェンスの外へ出すこと。agy 第 63 ラウンド P2-2）')
        if any(mask[i] for i in range(heads[0] + 1, ends[0])):
            errs.append(f'{origin} {what}の区画の中にコードフェンスが有る'
                        '（フェンスで括ると中身が表にも箇条書きにもならなくなる。区画の外へ出すこと。'
                        'agy 第 63 ラウンド P2-2）')
    return errs


def _md_cells(line):
    """Markdown の表の行を欄の列に割る（直前のバックスラッシュが奇数本の `|` は欄の区切りではない）"""
    cells, buf, i = [], [], 0
    while i < len(line):
        ch = line[i]
        if ch == '|':
            back = 0
            j = i - 1
            while j >= 0 and line[j] == '\\':
                back += 1
                j -= 1
            if back % 2 == 0:
                cells.append(''.join(buf).strip())
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    cells.append(''.join(buf).strip())
    return cells[1:-1] if line.startswith('|') else cells


def _decisions_region_errors(text):
    """`docs/decisions.md` の決めの表の形を見て説明文の列で返す（空なら揃っている）

    agy 第 62 ラウンド P2-4 は決 85 の行が 2 欄だと指摘したが、実測では**同じ表に不揃いの行が
    20 行以上有った**（区切り 3 / 4 / 6 / 7 / 12 個の行）。Astra 裁定 B で全部 4 欄に揃え、ここから
    機械に確かめる。見るのは列数・見出し・区画マーカー・番号の形・行の形だけ（中身の良し悪しは
    人が読む。Astra 問 5「列数だけを機械で見て、中身の良し悪しは人が読む」）"""
    lines = text.splitlines()
    where = '決めの表'
    # Astra 第 65 ラウンド 問 3: 語尾へ文字を足したマーカー行は正式なマーカーとして読まれず、
    # 正しい区画を残したまま偽のマーカー行を足すと 0 件で通った（Astra 実測）。形の検査だけを
    # 先に返す（個数と順序の検査は下の既存のものを使い、同じ穴を 2 回数えない）
    cand = [x for x in _marker_errors(lines, DECISIONS_FILE, DECISIONS_HEAD, DECISIONS_END, where)
            if '他の文字が付いている' in x]
    if cand:
        return cand
    if DECISIONS_HEAD not in lines or DECISIONS_END not in lines:
        return [f'{DECISIONS_FILE} に{where}の区画マーカーが無い'
                f'（`{DECISIONS_HEAD[:24]}...` と `{DECISIONS_END}`。マーカーが無い日は列数を確かめられない）']
    heads = [i for i, x in enumerate(lines) if x == DECISIONS_HEAD]
    ends = [i for i, x in enumerate(lines) if x == DECISIONS_END]
    if len(heads) != 1 or len(ends) != 1:
        return [f'{DECISIONS_FILE} に{where}の区画マーカーが開始 {len(heads)} 個・終了 {len(ends)} 個'
                f'（区画は 1 つだけ。2 つ目を作ると**最初の 1 組しか読まれず**、壊れた表を後の区画に'
                '隠せる。agy 第 63 ラウンド P2-3）']
    fenced = _md_fence_mask(lines)
    if any(fenced[i] for i in heads + ends):
        return [f'{DECISIONS_FILE} の{where}の区画マーカーがコードフェンスの中に有る'
                '（フェンス内の疑似区画を本体として読ませない為、マーカーはフェンスの外に置く。'
                'agy 第 63 ラウンド P2-3）']
    a, b = heads[0], ends[0]
    if a >= b:
        return [f'{DECISIONS_FILE} の{where}の区画マーカーが逆順（終了が開始より {b - a} 行前）']
    body = lines[a + 1:b]
    errs = []
    if tuple(body[:2]) != DECISIONS_HEADER:
        errs.append(f'{where}の先頭 2 行が見出しと区切り行ではない（1 行目: `{body[0][:40] if body else ""}`）')
    for k, line in enumerate(body):
        no = a + 2 + k
        if line.startswith('```'):
            errs.append(f'{DECISIONS_FILE}:{no} 区画の中にコードフェンスが有る'
                        '（フェンスの中を表の行として数える手があったので区画外へ出すこと）')
            continue
        if not line.startswith('|'):
            errs.append(f'{DECISIONS_FILE}:{no} が表の行ではない（区画の中には表の行だけを書く）')
            continue
        if not _ends_unescaped_pipe(line):
            errs.append(f'{DECISIONS_FILE}:{no} が行末の縦棒で閉じていない（閉じ縦棒の後ろに'
                        '余剰の欄が続くと 4 欄に見えてしまう。文末を `|` で閉じること。'
                        'agy 第 63 ラウンド P2-3）')
            continue
        cells = _md_cells(line)
        if len(cells) != DECISIONS_COLS:
            errs.append(f'{DECISIONS_FILE}:{no} の列数が {len(cells)} 欄（{where}は {DECISIONS_COLS} 欄。'
                        f'番号 `{cells[0] if cells else "?"}`。文中に縦棒を書くなら `\\|` にエスケープし、'
                        '続きの行に割らないこと）')
    nums = []
    for line in body[2:]:
        if not line.startswith('|') or line.startswith('```'):
            continue
        cells = _md_cells(line)
        if not cells:
            continue
        if not _DECISION_NUM.fullmatch(cells[0]):
            errs.append(f'{DECISIONS_FILE} の {where}の番号「{cells[0][:24]}」が番号の形'
                        '（`数字` または `数字-数字`）に合わない')
            continue
        nums.append(cells[0])
    dup = sorted({x for x in nums if nums.count(x) > 1})
    if dup:
        errs.append(f'{where}の番号が重複: {", ".join(dup[:6])}（同じ番号の行が 2 本有ると決定がどれか決まらない）')
    return errs


def decisions_table_columns_hold():
    """`docs/decisions.md` の決めの表が 4 欄で揃っていることを機械に確かめる（agy 第 62 ラウンド P2-4）"""
    text = (REPO / DECISIONS_FILE).read_text(encoding='utf-8')
    for msg in _decisions_region_errors(text):
        failed.append(f'{DECISIONS_FILE}: {msg}')

    lines = text.splitlines()
    a, b = lines.index(DECISIONS_HEAD), lines.index(DECISIONS_END)
    row = next(i for i in range(a + 3, b) if lines[i].startswith('|'))

    def mutate(s, drop=None, add=False, fence=False, prose=False, dup=False, num=None, esc=None):
        ls = s.splitlines()
        i = next(x for x in range(a + 3, len(ls)) if ls[x].startswith('|'))
        cells = _md_cells(ls[i])
        if drop is not None:
            cells = [c for j, c in enumerate(cells) if j != drop]
        if add:
            cells = cells[:2] + ['追加分の欄'] + cells[2:]
        if esc:
            cells[1] = cells[1] + '。`a \\| b` のような表記も有る'
        if num is not None:
            cells[0] = num
        if dup:
            ls.insert(i + 1, ls[i])
        ls[i] = '| ' + ' | '.join(cells) + ' |'
        if fence:
            ls.insert(i + 1, '```')
        if prose:
            ls.insert(i + 1, '表の行ではない文章')
        return '\n'.join(ls)

    probes = (
        ('欄を 1 本落とす', lambda s: mutate(s, drop=3), f'{DECISIONS_COLS - 1} 欄'),
        ('欄を 1 本足す', lambda s: mutate(s, add=True), f'{DECISIONS_COLS + 1} 欄'),
        ('文中の縦棒をエスケープした行は通る', lambda s: mutate(s, esc=True), None),
        ('番号の形を壊す', lambda s: mutate(s, num='八五'), '番号の形'),
        ('同じ番号を 2 本にする', lambda s: mutate(s, dup=True), '重複'),
        ('区画の中にコードフェンスを足す', lambda s: mutate(s, fence=True), 'コードフェンス'),
        ('区画の中に表でない行を足す', lambda s: mutate(s, prose=True), '表の行ではない'),
        ('見出し行を消す', lambda s: s.replace(DECISIONS_HEADER[0], '| # | 決定 |', 1),
         '見出しと区切り行ではない'),
        ('終了マーカーを消す', lambda s: s.replace(DECISIONS_END, ''), '区画マーカーが無い'),
        ('区画を 2 つ目の末尾に足す（2 欄の行を含む）',
         lambda s: s + f'\n{DECISIONS_HEAD}\n' + '\n'.join(DECISIONS_HEADER)
         + '\n| 999 | 壊れた 2 欄 |\n' + DECISIONS_END + '\n', '区画マーカーが開始 2 個'),
        ('コードフェンスの中に偽の区画マーカーを置く',
         lambda s: '```md\n' + DECISIONS_HEAD + '\n' + '\n'.join(DECISIONS_HEADER)
         + '\n| 1 | ok | ok | ok |\n' + DECISIONS_END + '\n```\n' + s, '区画マーカー'),
        # Codex 第 63 ラウンド P2-3: `~~~` をフェンスとして認識しないとマーカーがフェンス外に見えた
        ('チルダのフェンスの中に偽の区画マーカーを置く',
         lambda s: '~~~\n' + DECISIONS_HEAD + '\n' + '\n'.join(DECISIONS_HEADER)
         + '\n| 1 | ok | ok | ok |\n' + DECISIONS_END + '\n~~~\n' + s, '区画マーカー'),
        ('閉じ縦棒の後ろに余剰の欄を足す',
         lambda s: s.replace('| 86 |', '| 86x | a | b | c | 余剰\n| 86 |', 1), '行末の縦棒'),
    )
    for label, mut, want in probes:
        got = _decisions_region_errors(mut(text))
        if want is None:
            if got:
                failed.append(f'{DECISIONS_FILE} 検査の自己検査「{label}」が通らないはずで落ちた: {got[:2]}')
            continue
        if not any(want in x for x in got):
            failed.append(f'{DECISIONS_FILE} 検査の自己検査「{label}」が「{want}」で落ちない: {got[:2]}')


MD_FENCE_DOCS = ((BATTERY + '/README.md', 'README.md'), (DECISIONS_FILE, 'decisions.md'))


def _cn_glyph_lines(rel_path):
    """文書 1 本を走査し、中国語簡体字のコードポイントを `(行, 字)` で返す

    一覧は AGENTS.md の頻出混入例に、双人レビューで実際に混入していた 6 字
    （U+9488 / U+7EC6 / U+8FC7 / U+8D1F / U+67E5 / U+5BF9）を足した物。
    手元の字形検査（`~/.agents/scripts/check-cn-glyphs.py`）は JIS で
    符号化**できない**字を自動で落とすが、符号化できる変体字は明示リストに足すまで素通りする
    （双人レビュー agy 第 73 ラウンド P2-3: 追跡下の `check-invariants46.py` の U+8FC7 を見逃した）。
    一覧はコードポイントで持つ。説明文に簡体字その物を書くと自分の検査で落ちる為、下に並べるのは
    **日本表記側だけ**である。
    価・関・検・験・変・間・聞・長・門・説・語・読・車・馬・鳥・魚・島・書・買・発・電・風・飛・東・
    頁・業・術・機・権・図・夢・極・遷・聴・復・創・撃・欠・陥
    （U+4E8E は日本語で使わない字なので日本表記の対応を書かない）
    """
    cps = (0x4ef7, 0x5173, 0x68c0, 0x9a8c, 0x53d8, 0x95f4, 0x95fb, 0x957f, 0x95e8, 0x8bf4,
           0x8bed, 0x8bfb, 0x8f66, 0x9a6c, 0x9e1f, 0x9c7c, 0x5c9b, 0x4e66, 0x4e70, 0x53d1,
           0x7535, 0x98ce, 0x98de, 0x4e1c, 0x9875, 0x4e1a, 0x672f, 0x6743, 0x56fe,
           0x68a6, 0x6781, 0x8fc1, 0x542c, 0x590d, 0x521b, 0x51fb, 0x4e8e, 0x7f3a, 0x9677,
           0x9488, 0x7ec6, 0x8fc7, 0x8d1f, 0x67e5, 0x5bf9)
    # U+673A（机）は簡体字「機」に対応するが、日本語の「机（つくえ）」でもあるので禁止しない
    # （双人レビュー Codex 第 74 ラウンド P2-2: 「机上の空論」が通らなくなる）
    bad = set(chr(c) for c in cps)
    out = []
    for n, line in enumerate(REPO.joinpath(rel_path).read_text(encoding='utf-8').splitlines(), 1):
        for c in line:
            if c in bad:
                out.append((n, f'U+{ord(c):04X}'))
    return out


def japanese_glyphs_only():
    """追跡下の一覧対象に中国語簡体字が混ざっていないか（AGENTS.md の全セッション共通ルール）

    「手元の字形検査を通った」では足りない。あの検査は JIS で符号化できない字しか自動で落とさず、
    符号化できる変体字（上の一覧）は明示リストに足すまで素通りする。fresh clone の人にも同じ約束を
    守ってもらう為、**この検査器の中にリストを持つ**。frozen な `battery/r43-before.mjs` の注釈に
    残る U+5E76 は昔の物なので対象に含めない
    """
    for rel in _text_docs(('.md', '.py', '.mjs', '.html')):
        for n, where in _cn_glyph_lines(rel)[:2]:
            failed.append(f'{rel}:{n}: 日本表記ではない字形 {where} が混ざっている'
                          '（AGENTS.md の一覧を直す）')
    for n, where in _cn_glyph_lines('README.md')[:2]:
        if n:
            failed.append(f'README.md:{n}: 日本表記ではない字形 {where} が混ざっている')


MD_PATH_RE = re.compile(r'`((?:skill|docs|demo)/[A-Za-z0-9_./+-]+|README\.md)`')
MD_TOOL_RE = re.compile(r'([A-Za-z0-9_./+-]+\.(?:mjs|py|sh))')
# 括弧の中の実測値を読む。「（26 項目）」と「（.NET 不要、28 項目）」の両方に効く
MD_COUNT_RE = re.compile(r'（[^（）]*?([0-9]+) 項目')
# リンクの宛先は山括弧形 `[説明](<path>)` とタイトル付き `[説明](path "題名")` の両方を読む
# （Codex 第 76 ラウンド P2: 山括弧を実在しないファイル名と読んで誤検出し、タイトル付きを見逃した）
MD_LINK_RE = re.compile(r'\[[^\]]*\]\(\s*(?:<([^>]*)>|([^)\s]+))(?:\s+[^)]*)?\)')
MD_REF_RE = re.compile(r'\[[^\]]+\]\[[^\]]*\]')      # 参照リンク。この一覧対象では使わない
MD_CODE_RE = re.compile(r'`[^`]*`')                     # 行内のコード部分。記法の検査からは見ない


def _text_docs(suffixes):
    """走査対象の文書・検査器の相対パス（追跡下の `skill/` と `docs/`、およびルートの README）"""
    return sorted(p.relative_to(REPO).as_posix() for d in ('skill', 'docs')
                  for p in (REPO / d).rglob('*')
                  if p.is_file() and p.suffix in suffixes)


def doc_pointers_resolve():
    """文書の案内先が実在し、同じ道具の数え上げが文書間で食い違わないか（双人レビュー第 72 / 73 / 74 ラウンド）

    同じ類の P2 が 3 ラウンド続いた（実在しない見出しへの案内、`python3 <README>` という実行不能な案内、
    README を分割した後の案内の張り替え漏れ、`test-report.mjs` の `117 項目` が `130 項目` になった後の
    取り残し）。人の目だけでは更新漏れが再発する。ここでは機械で読める 4 規則だけ守る:

    1. バッククォートで囲まれた `skill/` `docs/` `demo/` `README.md` の形は**実在するパス**だけにする
       （`out/` は gitignore 済みの作業台帳なので対象外。新しい道具を増やした日の案内漏れを落とす）
    2. 行末注釈 `# 説明（… N 項目 …）` は**実測値を書く場所**と決める。同じ行に道具名が並ぶ書き方を
       道具名で集め、道具ごとに 1 つの値しか持てない（`（.NET 必要、130 項目）` の様な書き方も読む。
       README を分割した後に片方だけ更新される事故が実例）
    3. Markdown リンク `[説明](宛先)` の宛先が実在する事。`http(s)` / `mailto:` と文内アンカー（`#`
       始まり）は外へ出す。山括弧 `[x](<path>)` とタイトル付き `[x](path "題名")` も読む。折り返しの
       せいで `[説明]` と `(宛先)` が別々の行に割れた物はリンクとして解釈されない為、その形自体を落とす
       （agy 第 75 ラウンド P2-2 で `docs/review-usage.md` のリンクが実体へ付かなかった）
    4. **参照リンク `[説明][定義]` を使わない**。定義の一覧まで追わないと実在が確かめられないので、
       この一覧対象では行内リンクだけを書く（使った日を落とす。見逃しの穴を塞ぐ為の規則）
    """
    項目 = {}
    for rel in _text_docs(('.md',)) + ['README.md']:
        lines = REPO.joinpath(rel).read_text(encoding='utf-8').splitlines()
        for n, line in enumerate(lines, 1):
            # コード部分（`perms[::step][:cap]` の様な `][` ）を参照リンクと取り違えない
            if MD_REF_RE.search(MD_CODE_RE.sub(' ', line)):
                failed.append(f'{rel}:{n}: 参照リンクの形がある（この一覧対象では行内リンクで書く）')
            for angle, bare in MD_LINK_RE.findall(line):
                link = angle or bare
                if link.startswith(('http://', 'https://', 'mailto:', '#')):
                    continue
                target = (REPO / rel).parent / link.split('#')[0]
                if not target.exists():
                    failed.append(f'{rel}:{n}: Markdown リンクの宛先 `{link}` が実在しない')
            if line.rstrip().endswith(']') and n < len(lines) and lines[n].lstrip().startswith('('):
                failed.append(f'{rel}:{n}: リンクの `[...]` と `(...)` が改行で割れている'
                              '（Markdown がリンクとして解釈しない形）')
            for path in MD_PATH_RE.findall(line):
                if not (REPO / path.split('#')[0]).exists():
                    failed.append(f'{rel}:{n}: 案内先の `{path}` が実在しない'
                                  '（ファイルを動かした日は案内も張り替える）')
            got = MD_COUNT_RE.findall(line)
            # 実測値を書くのは道具の呼び出し例の**行末の注釈**（` # 説明（N 項目）`）と決める。
            # 決め表や本文の「5 項目」を道具の実測値と取り違えない為、この形以外は見ない
            if got and ' # ' in line:
                # 鍵は**ファイル名だけ**にする。`$SKILL/scripts/x.mjs` と `skill/scripts/x.mjs` の様に
                # 書き方が違っても同じ実測値を指す為、この一覧対象で名前の重複が無い前提で揃える
                for tool in MD_TOOL_RE.findall(line):
                    項目.setdefault(tool.rsplit('/', 1)[-1], set()).update(got)
    for tool in sorted(項目):
        if len(項目[tool]) > 1:
            failed.append(f'{tool}: 項目数の記載が文書間で食い違う {sorted(項目[tool])}'
                          '（実測して 1 つに揃える）')



def fence_form_bypass():
    """情報文字列付きのフェンスを形検査が見逃すか（Astra 第 64 ラウンド 問 3 裁定 (b) の単独名指し）

    実文書を書き換えるのではなく、落ちるはずの 3 行を直接 `_fence_form_errors` へ渡す。
    `md-fence-form` を消すと報告が消える（＝この控制はその見張り番だけを名指している）"""
    errs = _fence_form_errors(['```sh', 'demo', '```'], 'README.md')
    if not errs:
        return False
    # agy 第 65 ラウンド P2-2: 字下げの中のフェンス（箇条書き・番号・引用の中）も落ちることを
    # 同じ控制で測る（この 3 形が 0 件だと「候補が見えていない」まま表の検査が通ってしまう）
    nested = _fence_form_errors(['  - ```', '  1. ```', '  > ```'], 'README.md')
    if len(nested) != 3:
        return False
    return (1, errs[0])


def markdown_fences_hold():
    """検査が読む 2 つの文書でコードフェンスが許可した形だけか（Astra 第 64 ラウンド 問 3 裁定 (b)）

    約束は表の区画内だけでなく**文書全体**に適用する。第 63 ラウンド双人レビューで `~~~` と
    4 個のバッククォートのフェンスが偽の「名前」表を通した（`out/review-agy63.log` P2-3、
    `out/review-codex63.log` P2-3）。裁定は「CommonMark の模倣」ではなく「書ける形を先に固定し、
    禁止形を検出して失敗させる」なので、下の控制は禁止形が**失敗になること**と、許可した
    1 組が**通ること**の対で測る"""
    for rel, where in MD_FENCE_DOCS:
        lines = (REPO / rel).read_text(encoding='utf-8').splitlines()
        for msg in _fence_form_errors(lines, where):
            failed.append(msg)

    base = (REPO / BATTERY / 'README.md').read_text(encoding='utf-8').splitlines()
    if _fence_form_errors(base, 'README.md'):
        failed.append('README.md 自身のフェンスの形が今の検査で落ちる（実文書を先に直す）: '
                      f'{_fence_form_raw_errors(base, "README.md")[:2]}')
    probes = (
        ('`~~~` で括ったフェンス', lambda ls: ls + ['~~~', '| 名前 | x |', '~~~'],
         '許可した形ではない'),
        ('情報文字列を付けたフェンス', lambda ls: ls + ['```sh', 'x', '```'], '情報文字列'),
        ('4 個のバッククォートのフェンス', lambda ls: ls + ['````', '```', 'x', '```', '````'],
         '許可した形ではない'),
        ('字下げしたフェンス', lambda ls: ls + ['  ```', 'x', '  ```'], '許可した形ではない'),
        ('引用の中へ置いたフェンス', lambda ls: ls + ['> ```', 'x', '> ```'], '許可した形ではない'),
        ('箇条書きの中へ置いたフェンス', lambda ls: ls + ['- ```', 'x', '- ```'],
         '許可した形ではない'),
        ('フェンスを閉じ忘れる', lambda ls: ls + ['```', 'x'], '閉じられていない'),
        ('許可した 1 組は通る', lambda ls: ls + ['```', 'x', '```'], None),
    )
    for label, mut, want in probes:
        got = _fence_form_raw_errors(mut(base), 'README.md')
        if want is None:
            if got:
                failed.append(f'フェンス形検査の自己検査「{label}」が通るはずで落ちた: {got[:1]}')
            continue
        if not any(want in x for x in got):
            failed.append(f'フェンス形検査の自己検査「{label}」が「{want}」で落ちない: {got[:1]}')


def import_granted_hole():
    """豁免に登録していないサブモジュールの import を走査が穴として挙げるか（`import-granted`）

    Astra 第 65 ラウンド 問 1 裁定 (ア) 修正版: 豁免は完全修飾名で効く。`importlib: ["util"]` を
    登録したファイルでも `import importlib.machinery` は通らない（第 64 ラウンドまでは根の
    `importlib` を見ただけで通していた）。`as` を付けても付けなくても同じ"""
    _n, holes, _c, _cl = _guard_scan(f'{_SCAN_HEAD}import importlib.machinery\n'
                                     'import importlib.util as u\n', '<制御>',
                                     {'importlib': {'util'}})
    bad = [h for h in holes if '豁免台帳に登録していない' in h]
    return (1, bad[0]) if bad else False


def import_star_hole():
    """`from <任意のモジュール> import *` を許可一覧・豁免より前に穴として挙げるか（`import-star`）

    Astra 第 65 ラウンド 問 2 裁定の実測: `from sys import *` が `modules` を別名なしで束縛し、
    `getattr(modules['_inputs'], 'gua' + 'rd')('hidden')` が穴 0 件で通った"""
    _n, holes, _c, _cl = _guard_scan(f'{_SCAN_HEAD}from os import *\n', '<制御>')
    bad = [h for h in holes if 'import *' in h]
    return (1, bad[0]) if bad else False


def guard_unbound_hole():
    """`_inputs.py` 以外での裸の `guard(...)` を数えずに穴へ落とすか（`guard-unbound`）

    Astra 第 65 ラウンド 問 2 裁定: 裸の呼び出しは `_inputs.py` のトップレベルの `def guard` に
    結び付く場合だけ数える。結び付かない物は黙って捨てず穴にする（第 64 ラウンドまでは架空の
    見張り番として網羅に数えていた）"""
    _n, holes, _c, _cl = _guard_scan("if guard('probe-unbound'):\n    raise SystemExit(1)\n",
                                     pathlib.Path('probe.py'))
    bad = [h for h in holes if '箱経由ではない' in h]
    return (1, bad[0]) if bad else False


def exempt_use_form_hole():
    """豁免由来の束縛を末端の直接呼び出し以外で読む形を穴として挙げるか（`exempt-use-form`）

    Astra 第 66 ラウンド 問 2 の裁定（構文ごとの禁止リストをやめて**許可する形の白名前**）を実測する。
    `importlib.util` へ `spec_from_file_location` を登録したファイルで、(1) `t = importlib.util` の
    受け取り (2) 条件式だけの読み取り (3) `getattr` 経由 (4) 登録していない `importlib.util.__dict__`
    への連鎖。登録した末端を直接呼ぶ 1 行だけは穴にならない"""
    src = ('import importlib.util\n'
           'importlib.util.spec_from_file_location("x", "y")\n'
           't = importlib.util\n'
           'if importlib.util:\n'
           '    pass\n'
           'getattr(importlib.util, "module_from_spec")\n'
           'd = importlib.util.__dict__\n')
    _n, holes, _c, _cl = _guard_scan(
        src, '<制御>', {'importlib.util': {'spec_from_file_location'}})
    bad = [h for h in holes if '登録した末端の直接呼び出し以外' in h]
    if bad and len(bad) != 4:
        return (len(bad), f'豁免の形の穴 が期待した 4 件のうち {len(bad)} 件しか出ていない'
                          '（閾値で合否を決める形はやめた。1 形見逃すと別の一の数で通る。'
                          'Astra 第 69 ラウンド 問 2） / ' + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def ledger_box_shape_loose():
    """台帳の `boxNames` の形の悪さを形の検査が見逃すか（`box-shape`。Astra 問 1 (c)・追記 (ア)）

    公開名の一覧を辞書以外へ組み替える。見張り番を消すとこの案内だけが消える（用途の照合は
    形の悪い表では何も言わない作りなので、別の所から同じ文は出ない）"""
    def mut(doc):
        doc['boxNames'] = []
    return _ledger_doc_mutated({'fn': mut})


def ledger_path_overlap():
    """豁免の同じ経路を中継と末端で 2 度登録する併記を形の検査が見逃すか（`exempt-path-overlap`）

    Astra 第 66 ラウンド 問 1 の裁定で豁免は末端までの完全な経路で持つ。`importlib.util` の
    登録へ `spec_from_file_location` の名前が有るまま、その先をもう 1 段深く登録する細工（実物の
    台帳では `importlib: ["util"]` と `importlib.util: [...]` の併記になった）。形の検査だけが名指す"""
    def mut(doc):
        for e in doc['exemptions']:
            imps = e.get('imports')
            if isinstance(imps, dict) and 'importlib.util' in imps:
                imps['importlib.util.spec_from_file_location'] = ['x']
                return
        raise NotDetected('対応表に `importlib.util` の豁免が無い（制御の前提が変わった）')
    return _ledger_doc_mutated({'fn': mut})


def in_public_name_hole():
    """箱の公開名を用途付きの表と違う形で使うのを走査が見逃すか（`in-public-name`）

    Astra 第 66 ラウンド 追記の裁定 (ア): `IN` は豁免でなく許可一覧に有る箱なので、表に載せた
    公開名だけを載せた用途で使う。ここでは (1) 表に無い `IN.<名前>` (2) 呼び出し専用の名前を
    呼び出さずに読む (3) 値の読み取りの登録を呼び出す、の 3 形を並べる"""

    # Astra 第 67 ラウンド 問 2 で形が 1 つ増えた（`const` の名前が呼び出しへ至る連鎖の根に
    # なっている場所。`IN.GUARD_OFF.clear()` は代入の受け手ではないので `write` ではないが、
    # 値の読み取りでもない）
    src = (f'{_SCAN_HEAD}IN.repo_root()\nIN.not_registered\n'
           'f = IN.load_guard_ledger\nsys = IN.read_only()\nsys2 = IN.read_only.clear()\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None,
                                     {'repo_root': 'call', 'load_guard_ledger': 'call',
                                      'read_only': 'const'})
    bad = [h for h in holes if '箱の公開名' in h]
    if bad and len(bad) != 4:
        return (len(bad), f'箱の公開名の穴 が期待した 4 件のうち {len(bad)} 件しか出ていない'
                          '（閾値で合否を決める形はやめた。1 形見逃すと別の一の数で通る。'
                          'Astra 第 69 ラウンド 問 2） / ' + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def in_public_table_extra():
    """箱の公開名の表に実ツリーで使わない登録が残るのを照合が見逃すか（`in-public-table`）

    Astra 第 66 ラウンド 追記の裁定 (ア): 表は実ツリーの使用から作る。使わない名前を 1 個足した
    台帳を照合が名指す（走査側は使い道の無い登録を穴にしないので、別の所では落ちない）"""
    doc = IN.load_guard_ledger(REPO)
    doc['boxNames']['unused_in_public_table'] = 'const'
    errs = _guard_ledger_errors(doc, _exempt_index_of(doc))
    bad = [x for x in errs if 'boxNames に登録した公開名' in x]
    if bad and len(bad) != 1:
        return (len(bad), f'期待した 1 件に対して {len(bad)} 件の診断が出た'
                          '（細工が別の一に効いたか診断が混ざった。残った診断を'
                          '件数の条件で捨てない。Astra 第 70 ラウンド 問 4） / '
                          + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


_EMIT = None


def _emit_tool():
    """候補の道具 `emit-guard-owners.py` を読み直す（制御からその判定を呼ぶ為）

    同じ `_inputs` を共有するので見張り番の ON / OFF がそのまま渡る。`sys.modules` へは載せない
    （載せると自分の走査が別の実体と突き合わさる。候補の道具自身が同じ手順で `test-contract.py`
    を読むので、読み直し方は両側で揃っている）"""
    global _EMIT
    if _EMIT is None:
        spec = importlib.util.spec_from_file_location('emit_guard_owners',
                                                      HERE / 'emit-guard-owners.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _EMIT = mod
    return _EMIT


def relative_import_hole():
    """相対 import を豁免・許可一覧より先に穴にしているか（`import-relative`。Codex P1-1）

    `from .os import path` は許可一覧の `os` と同じ綴りだが、所属パッケージが静的に決まらないので
    完全修飾名の照合ができない。見張り番を消すと許可一覧の `os` として素通りするので、この控制は
    この見張り番だけを名指す（`from .importlib.util import …` は別の見張り番も動くので使わない）"""
    src = f'{_SCAN_HEAD}from .os import path\nprint(path)\n'
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {})
    bad = [h for h in holes if '相対 import' in h]
    if bad and len(bad) != 1:
        return (len(bad), f'期待した 1 件に対して {len(bad)} 件の診断が出た'
                          '（細工が別の一に効いたか診断が混ざった。残った診断を'
                          '件数の条件で捨てない。Astra 第 70 ラウンド 問 4） / '
                          + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def dynamic_root_import_hole():
    """末端の登録が有るファイルの根だけの動的機構 import を独立の名前で名指すか

    `import-dynamic-module`（Codex 第 66 ラウンド P2-1 で報告された形。Astra 第 67 ラウンド 問 1 の
    裁定で根だけの束縛は豁免でも通さない）。案内が「豁免台帳へ登録すれば可」と言い戻していけない
    のもここで見る（登録の単位は末端までの経路なので、根の束縛は登録では解消しない）"""
    src = (f'{_SCAN_HEAD}import importlib\nimport importlib.util\n'
           'importlib.util.spec_from_file_location("a", "b")\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>',
                                     {'importlib.util': {'spec_from_file_location'}}, {})
    bad = [h for h in holes if '動的な機構のモジュール「importlib」を' in h]
    if [h for h in holes if '登録すれば可' in h]:
        return False
    if bad and len(bad) != 1:
        return (len(bad), f'期待した 1 件に対して {len(bad)} 件の診断が出た'
                          '（細工が別の一に効いたか診断が混ざった。残った診断を'
                          '件数の条件で捨てない。Astra 第 70 ラウンド 問 4） / '
                          + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def public_write_hole():
    """箱の公開名の書き換え・削除を走査が名指すか（`in-public-write`。Codex P1-2 / agy P2-2）

    `IN.GUARD_OFF = {...}` が穴 0 件で通って、その後の `IN.guard(...)` が `False` を返した実測。
    Astra 第 67 ラウンド 問 2 は 6 マスの表で、書き換えと削除は両方の用途で穴。ここでは 4 形
    （代入・複合代入・削除・登録した名前の属性への書き換え）を並べ、見張り番を消すと 4 形とも
    素通りことを同じ控制で測る"""
    src = (f'{_SCAN_HEAD}IN.CONST = frozenset()\nIN.CONST |= frozenset()\n'
           'del IN.CONST\nIN.CONST.x = 1\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'CONST': 'const'})
    bad = [h for h in holes if '書き換え・削除' in h]
    if bad and len(bad) != 4:
        return (len(bad), f'期待した 4 件に対して {len(bad)} 件の診断が出た'
                          '（細工が別の一に効いたか診断が混ざった。残った診断を'
                          '件数の条件で捨てない。Astra 第 70 ラウンド 問 4） / '
                          + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def emit_box_diff_blind():
    """候補の道具が箱の公開名と豁免の差分を表示するか（`emit-diff`。Codex P2-2 / agy P2-1）

    第 66 ラウンドの `diff_lines()` は `owners` と `scannedFiles` しか比較せず、使わない公開名を
    1 個足した台帳でも「今の台帳との差分: 無し」と報告した（照合側は検出するので、実ツリーの
    検査だけが正しく、候補の道具が嘘を言った）。追加・削除・用途の変わり目・豁免の差し替えの
    5 種が 1 行ずつ出ることを測る"""
    em = _emit_tool()
    old = {'owners': {'a': ['x.py']}, 'scannedFiles': ['x.py'],
           'guardCallers': ['skill/scripts/tools/battery/test-contract.py'],
           'boxNames': {'keep': 'const', 'gone': 'const', 'flip': 'call'},
           'exemptions': [{'file': 'x.py',
                           'imports': {'importlib.util': ['spec_from_file_location']}}]}
    new = {'owners': {'a': ['x.py']}, 'scannedFiles': ['x.py'],
           'guardCallers': ['skill/scripts/tools/battery/test-contract.py',
                            'skill/scripts/tools/battery/other.py'],
           'boxNames': {'keep': 'const', 'flip': 'const', 'added': 'call'},
           'exemptions': [{'file': 'x.py',
                           'imports': {'importlib.util': ['module_from_spec']}}]}
    got = em.diff_lines(old, new)
    # 呼び出し元の一覧の変わり目も差分に出ること（`IN.guard` をここで読むと 1 名前 1 箇所の
    # 規則を破るので、無条件に文面だけ見る。見張り番を消した側はこの行が出ない）
    if not [x for x in got if '無効化の区間を使えるファイル 追加' in x]:
        return False
    want = ('箱の公開名 追加', '箱の公開名 削除', '用途の変わり目', '豁免 追加', '豁免 削除')
    hit = [w for w in want if [x for x in got if w in x]]
    return (len(hit), hit[0]) if len(hit) == len(want) else False


def candidate_refusal_blind():
    """候補の道具が書けない形と残った穴を拒否するか（`emit-candidate-valid`。Astra 問 3 の裁定 1）

    書き換えを `const` へ塗り替えないこと（Astra: 候補の表で検証してよいが、書き換えや禁止構文を
    許可用途へ変換しない）。3 種の拒否（書き換え・2 用途・残った穴）が揃うことを測る"""
    em = _emit_tool()
    errs = em.candidate_refusals({'wrote': {'call', 'write'}, 'both': {'call', 'const'}},
                                 ['<制御>:1 走査の穴の実例'])
    if errs and len(errs) != 3:
        return (len(errs), f'期待した 3 種の拒否に対して {len(errs)} 件出た'
                          '（細工が別の一に効いたか診断が混ざった。残った診断を'
                          '件数の条件で捨てない。Astra 第 70 ラウンド 問 4） / '
                          + errs[0][:60])
    return (len(errs), errs[0]) if errs else False


def emit_caller_approval_blind():
    """候補の道具が観測した区間の呼び出し元をそのまま許可に載せるか（`emit-caller-approval`）

    Codex 第 68 ラウンド P2-2 の実測: 走査で観測した呼び出し元を候補の `guardCallers` へそのまま
    載せていた為、未承認のファイルが候補だけで区間を作れるようになっていた。Astra 第 69 ラウンド
    問 3-2 の裁定で候補は承認済みを引き継ぎ、未承認の観測は終了 1 で拒否する"""
    gap = _emit_tool().approval_gap(['skill/scripts/tools/battery/new-control.py'],
                                    ['skill/scripts/tools/battery/test-contract.py'])
    return (len(gap), gap[0]) if gap else False


def emit_target_blind():
    """`--emit` が運用中の台帳その物への書き出しを拒否するか（`emit-target`。Astra 問 3 の裁定 4）

    書き先は生かしたまま比較する（`./` を挟んだ表記でも同じファイルなら拒否）。候補の別の
    書き先は通すことも同じ控制で見る。実際の書き込みはしない（拒否の判定だけを読む）"""
    em = _emit_tool()
    live = IN.repo_root() / IN.GUARD_LEDGER_FILE
    alt = pathlib.Path(str(live.parent) + '/./' + live.name)
    errs = em.target_errors(live, alt)
    other = em.target_errors(live, live.parent / 'guard-owners.candidate.json')
    if errs and len(errs) != 1:
        return (len(errs), f'期待した 1 件の拒否に対して {len(errs)} 件出た'
                          '（細工が別の一に効いたか診断が混ざった。残った診断を'
                          '件数の条件で捨てない。Astra 第 70 ラウンド 問 4） / '
                          + errs[0][:60])
    return (1, errs[0]) if len(errs) == 1 and not other else False


def public_use_forms_clean():
    """箱の公開名の**通る形**が穴にならないこと（Astra 第 67 ラウンド 問 2 の表の白側の正控制）

    `x = IN.CONST`（読み取り）・`IN.call_it()`（呼び出し専用の呼び出し）・
    `local[IN.CONST] = 1`（別の物の受け手の添字の中で読むだけ）を通す。最後の形は
    代入の受け手が `local[...]` なので箱の名前は書き換えにならない"""
    src = (f'{_SCAN_HEAD}x = IN.CONST\nlocal = {{}}\nlocal[IN.CONST] = 1\n'
           'IN.call_it()\nprint(IN.CONST)\ns = IN.CONST + IN.CONST\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None,
                                     {'CONST': 'const', 'call_it': 'call'})
    bad = [h for h in holes if '公開名' in h]
    return bad[0] if bad else None


def candidate_uses_own_box_table():
    """候補が自分の表で走査できること（Codex 第 66 ラウンド P2-3 の循環が解けた正控制）

    実ツリーの台帳の箱の公開名を 1 個落とした表を渡すと穴が出て、完全な表を渡すと穴 0 件になる
    （走査が都度その表で検査している証左。旧台帳の表を要求する設計のままなら、新しい公開名を
    足した日は候補が作れない）"""
    doc = IN.load_guard_ledger(REPO)
    full = dict(doc['boxNames'])
    thin = dict(full)
    thin.pop(sorted(full)[0])
    _n1, _d1, _c1, holes1, _k1 = _guard_names_by_file(None, thin)
    _n2, _d2, _c2, holes2, _k2 = _guard_names_by_file(None, full)
    if not [h for h in holes1 if 'boxNames' in h]:
        return '表を 1 個落として渡した走査に穴が無い（渡した表で検査していない）'
    if holes2:
        return '今の台帳の表を渡した走査に穴が有る（' + holes2[0][:90] + '）'
    return None


def guard_callers_file_hole():
    """台帳に無いファイルが見張り番を消す区間を作れるか（`guard-caller-file`。Astra 問 1 の B案）

    第 67 ラウンドの `set_guard_off()` は誰でも・いつ呼んでも無効化が残った（両名 P1）。B案は
    区間を呼べるファイルを台帳 `guardCallers` に絞る。登録の無いソースで `with IN.guard_off(...)`
    を作ると穴になり、見張り番を消すと素通りする"""
    src = f"{_SCAN_HEAD}with IN.guard_off('x'):\n    pass\n"
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'guard_off': 'call'}, [])
    bad = [h for h in holes if 'guardCallers` に無いファイル' in h]
    return (len(bad), bad[0]) if bad else False


def guard_callers_unused_hole():
    """区間を作っていないファイルが台帳に登録されたまま通るか（`guard-caller-file`）

    Astra 第 68 ラウンド 問 1 の実装条件 2: 登録は使われている物だけ。使われない登録は次の見直し
    まで残り、後に別の一が同じファイルを無断で区間に使える足場になる"""
    src = f'{_SCAN_HEAD}x = 1\n'
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'guard_off': 'call'}, ['<制御>'])
    bad = [h for h in holes if '見張り番を消す区間を作っていない' in h]
    return (len(bad), bad[0]) if bad else False


def guard_callers_ghost_hole():
    """実在しないファイルの登録が通るか（`guard-caller-file`）

    Codex 第 68 ラウンド P2-1 の実測をそのまま細工にする。台帳の形の検査はファイルを見ないので
    ここで名指すのは走査側。「走査対象 24 ファイルに在るか」だけを見る安い入力にする
    （`guard-caller-file` は「登録に無いファイルが区間を作る」別の検査責務。1 名前 1 箇所）"""
    bad = _guard_caller_ghost_holes(['skill/scripts/tools/battery/missing.py'],
                                    ['skill/scripts/tools/battery/test-contract.py'])
    return (len(bad), bad[0]) if bad else False


def guard_caller_form_hole():
    """`with` の管理以外で見張り番を消す区間を作れるか（`guard-caller-form`。Astra 問 1 の B案）

    `IN.guard_off('x')` を文として呼ぶと区間を作らずに無効化だけ残る（抜ける約束が無い）。
    登録済みのファイルでも形が `with` の管理でなければ穴"""
    src = f"{_SCAN_HEAD}IN.guard_off('x')\n"
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'guard_off': 'call'}, ['<制御>'])
    bad = [h for h in holes if '`with` の管理ではない位置' in h]
    return (len(bad), bad[0]) if bad else False


def guard_callers_shape_hole():
    """台帳の `guardCallers` の形を人が決めた検査が名指すか（`guard-callers-shape`）

    空の列（= どの制御も区間を作れない）と欠損を弾く。第 66 ラウンドに `boxNames` を足した時も
    同じ形の検査を先に用意した（Astra 第 68 ラウンド 問 1 の実装条件 1: 台帳の形・候補・差分）"""
    doc = IN.load_guard_ledger(REPO)
    thin = dict(doc)
    thin['guardCallers'] = []
    bad = [x for x in IN.guard_ledger_shape_errors(thin) if 'guardCallers' in x]
    if not bad:
        return False
    thin2 = {k: v for k, v in doc.items() if k != 'guardCallers'}
    if not [x for x in IN.guard_ledger_shape_errors(thin2) if 'guardCallers' in x]:
        return False
    # agy 第 68 ラウンド P1-1 の実測: 重複と途中の `.` を交ぜた綴りが素通りしていた。同じ形の
    # 検査なので同じ名前で名指す（1 ファイル 1 登録が崩れると「同じファイルの 2 本」が並ぶ）
    bad2 = []
    for label, val in (
            ('重複', list(doc['guardCallers']) + list(doc['guardCallers'])),
            ('途中の `.`', ['skill/scripts/./tools/battery/test-contract.py']),
            ('終端の `/`', ['skill/scripts/tools/battery/']),
            ('.py でない', ['skill/viewer/template.html'])):
        thin3 = dict(doc)
        thin3['guardCallers'] = val
        if not [x for x in IN.guard_ledger_shape_errors(thin3) if 'guardCallers' in x]:
            bad2.append(label)
    if bad2:
        return (len(bad2), f'台帳の guardCallers の形 {bad2[:4]} を弾かない'
                           '（agy 第 68 ラウンド P1-1）')
    return (1, bad[0])


def public_call_via_condition():
    """条件式・コンテナを経由した呼び出しの受け手を走査が名指すか（`in-public-name`。Codex P2-2）

    第 67 ラウンドの歩きは `Attribute` / `Subscript` しか通さず、`(IN.CONST if True else None)
    ._str = ...` を読み取りに降格させて実値を変えられた（実測 `conditional_holes=0` /
    `HERE_after=/tmp/r67-review`）。Astra 第 68 ラウンド 問 2 は既定拒否（条件式・論理式・
    コンテナは値その物になり得るので追跡を続ける）。条件形とコンテナ形の 2 形を並べる"""
    # Astra 第 69 ラウンド 問 3-1 (c) の反例 1: 直下の子だけを見る判定への退行を、演算を 2 段
    # 重ねた形と条件式+演算の混成で見る（`([IN.CONST] * 2)[0]()` は agy 第 68 ラウンド P1-2 の実測）
    src = (f'{_SCAN_HEAD}(IN.CONST if True else None).clear()\n'
           '[IN.CONST][0]()\n'
           '([IN.CONST] * 2)[0]()\n'
           '((([IN.CONST] * 2) * 2)[0])()\n'
           '(([IN.CONST] if p else []) * 2)[0].clear()\n'
           "(f'{[IN.CONST]}').lower()\n")
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'CONST': 'const'})
    bad = [h for h in holes if '呼び出しへ至る連鎖' in h]
    # 見張り番を消した再実行では 0 件でなければならない（0 件を「期待と違う」で失敗にすると、
    # 控制自身が消したはずの診断を要求して別の所で落ちる。Astra 第 68 ラウンド 問 3 条件 3）
    if bad and len(bad) != 6:
        return (len(bad), f'コンテナを経由した呼び出しの受け手が {len(bad)} 件しか出ない'
                          '（6 形を期待。Astra 第 69 ラウンド 問 3-1 (c)・'
                          'agy 第 68 ラウンド P1-2） / ' + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def container_paths_read_side_clean():
    """コンテナ・演算の許可側が誤検出にならないか（Astra 第 69 ラウンド 問 3-1 の反例 2）

    拒否だけを増やす実装は「式全体にコンテナが有ったら何でも拒否」へ退化しやすい。Astra の裁定は
    他の物の添字と関数の引数を明示的に許可するので、対で固定する。`(IN.HERE / 'x').read_text()` と
    `('%s' % IN.CONST).lower()` は演算が新しい値を作る側の既存の許可（第 68 ラウンド 問 2 の表）
    （`(+IN.CONTENTS)()` のような単項演算の受け手は (c) ではコンテナ経路ではないので読み取りに
    数える。独自の `__pos__` が自分自身を返さない限り箱その物ではない。Astra 第 69 ラウンド
    問 3-1 の「直接オペランドの演算一般では説明しない」の範囲。agy 第 68 ラウンド P1-2 の期待と
    は違う為、README と決め 94 に残る穴として書く）"""
    src = _SCAN_HEAD + chr(10).join([
        "(IN.HERE / 'x').read_text()",
        "('%s' % IN.CONST).lower()",
        'local[IN.CONST]()',
        'f([IN.CONST])',
        'x = [IN.CONST]',
        "d = {'a': IN.CONST}",
    ]) + chr(10)
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'CONST': 'const', 'HERE': 'const'})
    if holes:
        return f'許可すべき形で穴が出た: {holes[0][:120]}'
    return None


def public_write_via_expression():
    """条件式を挟んだ書き換え・削除を走査が名指すか（`in-public-write`。Codex P2-2 の実測形）

    `IN.CONST._str = 'x'` は第 67 ラウンドでも落ちたが、`(IN.CONST if True else None)._str = 'x'`
    は穴 0 件で通った（`direct_holes=1 conditional_holes=0`）。受け手からの下がりが条件式を
    通るように直したことを、同じ控制の 2 形で測る"""
    src = (f'{_SCAN_HEAD}(IN.CONST if True else None)._str = \'x\'\n'
           '[IN.CONST, 0][0]._x = 1\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'CONST': 'const'})
    bad = [h for h in holes if '書き換え・削除' in h]
    return (len(bad), bad[0]) if bad else False


def public_role_unsupported_hole():
    """許可していない出現位置を走査が名指すか（`in-public-name`。Astra 問 2 の既定拒否）

    第 67 ラウンドまでは「書き換えの受け手でも呼び出しの受け手でもなければ読み取り」だったため、
    新しい構文は毎回抜け道になった。装飾子（`@IN.CONST`）と仮引数の既定値（`def f(a=IN.CONST)`）は
    実ツリーに使わないので許可していない位置。見張り番を消すと 2 形とも素通りする"""
    src = (f'{_SCAN_HEAD}@IN.CONST\ndef f():\n    pass\n\ndef g(a=IN.CONST):\n    pass\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'CONST': 'const'})
    bad = [h for h in holes if '未登録の位置' in h]
    return (len(bad), bad[0]) if bad else False


def public_new_value_reads_clean():
    """新しい値を作る式の中の読み取りが通ること（既定拒否の白名前の側。Astra 問 2 の表）

    `local[IN.CONST] = 1`（他の物の添字）・`f(IN.CONST)`（引数）・`x = IN.CONST if p else 2`
    （条件判定と代入右辺）・`{IN.CONST: 1}`（辞書のキー）・`(IN.CONST / 'x').read_text()`
    （演算で新しい値を作った物の呼び出し）・`for c in IN.CONST:`（反復対象）はみな箱の値を
    変えない。`call` の名前を直接呼ぶ形も通る"""
    src = (f'{_SCAN_HEAD}local = {{}}\nlocal[IN.CONST] = 1\nf = lambda *a: a\n'
           'f(IN.CONST)\nx = IN.CONST if True else 2\ny = {IN.CONST: 1}\n'
           "z = IN.CONST in ()\nw = (IN.CONST / 'x').read_text()\n"
           'print(IN.CONST / \'x\')\nfor c in IN.CONST:\n    pass\nIN.FN()\n')
    _n, holes, _c, _cl = _guard_scan(src, '<制御>', None, {'CONST': 'const', 'FN': 'call'})
    bad = [h for h in holes if '箱の公開名' in h or '未登録の位置' in h]
    return '通る形が穴になった: ' + bad[0][:110] if bad else None


def emit_relative_dest_from_other_cwd():
    """`--emit` の相対パスを打った場所から解決すること（agy P2-1）

    第 67 ラウンドまでは `root / p` でリポジトリ基準にしていた為、`battery/` から相対で打つと
    リポジトリ直下へ書かれた（他の道具は `IN.resolve_cli_path` で cwd 基準）。一時ディレクトリを
    cwd にして候補を書かせ、そこに有り、リポジトリ直下に無いことを確かめる"""
    with tempfile.TemporaryDirectory(prefix='r68-emit-') as td:
        out = pathlib.Path(td) / 'guard-owners.candidate.json'
        got = subprocess.run([sys.executable, str(HERE / 'emit-guard-owners.py'),
                              '--emit', 'guard-owners.candidate.json'],
                             cwd=td, capture_output=True, text=True, env=IN.guard_env())
        if got.returncode not in (0, 3):
            return '一時ディレクトリからの実行が終了 ' + str(got.returncode) + ': ' + \
                (got.stderr or got.stdout)[:160]
        if not out.exists():
            return '打った場所（一時ディレクトリ）へ候補が書かれていない: ' + \
                (got.stdout or '')[-160:]
        stray = REPO / 'guard-owners.candidate.json'
        if stray.exists():
            stray.unlink()
            return 'リポジトリ直下へ書かれた（cwd 基準になっていない）'
    return None


def md_marker_form_bypass():
    """区画マーカーの行に他の文字が付いている形を見るか（`md-marker-form`。Astra 問 3）

    語尾へ説明を足した行は正式なマーカーとして採用せず、マーカーに見える行として名指す
    （第 64 ラウンドまでは README で容認、`docs/decisions.md` は偽のマーカー行を足しても 0 件）"""
    lines = ['説明', README_NAMES_HEAD + ' この箇所だけ読む', '本文']
    errs = _marker_errors(lines, '<制御>', README_NAMES_HEAD, README_NAMES_END, '名前一覧')
    bad = [x for x in errs if '他の文字が付いている' in x]
    return (1, bad[0]) if bad else False


def exempt_map_expanded_wrong():
    """走査へ渡した豁免マップが台帳から作り直した物と違うことを名指すか（`exempt-map-expand`）

    Astra 第 65 ラウンド 問 4 (c) 4 の実測: 使われない対象外のキーを足しても呼び出し候補は全部
    一致した（候補の一致は豁免マップの正しさを検証しない）。宛先を 1 本足し、許可内容を 1 個
    減らしたマップを直接渡して測る"""
    doc = IN.load_guard_ledger(REPO)
    fresh = _exempt_index_of(doc)
    if not fresh:
        raise NotDetected('対応表に豁免が 1 件も無い（制御の前提が変わった）')
    broken = {k: {m: set(v) for m, v in got.items()} for k, got in fresh.items()}
    first = sorted(broken)[0]
    mod = sorted(broken[first])[0]
    broken[first][mod] = set()
    broken['_never_scanned.py'] = {'types': {'SimpleNamespace'}}
    errs = _exempt_map_errors(doc, broken)
    bad = [x for x in errs if '台帳から作り直した物と違う' in x]
    if bad and len(bad) != 2:
        return (len(bad), f'台帳の展開の穴 が期待した 2 件のうち {len(bad)} 件しか出ていない'
                          '（閾値で合否を決める形はやめた。1 形見逃すと別の一の数で通る。'
                          'Astra 第 69 ラウンド 問 2） / ' + bad[0][:60])
    return (len(bad), bad[0]) if bad else False


def exempt_loader_attrs_gap():
    """台帳の登録禁止が走査側の禁止属性を避けているか（`exempt-loader-attrs`。Astra 問 1 (c) 1）

    実行時の名前一覧を一時的に 1 個薄めて測る（`_inputs` の方を書き換える制御は他の 23 本の走査に
    波及するので、内包の検査だけを関数へ出して呼ぶ）"""
    thin = frozenset(x for x in IN._LEDGER_LOADER_NAMES if x != '__loader__')
    errs = _loader_cover_errors(thin)
    bad = [x for x in errs if '避けていない' in x]
    return (1, bad[0]) if bad else False


def ledger_exemption_removed():
    """実ツリーで必要とされている豁免を 1 件落とすと、走査が未登録の import を名指すか

    Astra 第 65 ラウンド 問 4 (c) 2 の裁定: 未登録 import の拒否を 1 つの判定に整理し、必要豁免の
    欠落を名指す控制を置く（第 64 ラウンドまでは `socket` の対照だけでした（`import-unregistered`
    を消しても豁免の穴が残った）。豁免を 1 件落とした台帳からマップを作り直して 24 本を走らせる
    （見張り番を消すとこの穴だけが消えて他は無傷なので、この控制はこの見張り番だけを名指す）。
    実際に出る穴は「豁免台帳に登録していない import importlib.util」（登録済みの名前が 0 個に
    なるので完全修飾名の検査が名指す。`import-unregistered` の `socket` の対照とは別の見張り番で
    消えることをここで見る）"""
    doc = json.loads(json.dumps(IN.load_guard_ledger(REPO)))
    if len(doc.get('exemptions') or []) < 2:
        raise NotDetected('対応表の豁免が 2 件未満（制御の前提が変わった）')
    del doc['exemptions'][0]
    exp = _exempt_index_of(doc)
    holes = []
    for path in _guard_scan_files():
        _n, got, _c, _cl = _guard_scan(
            path.read_text(encoding='utf-8'), path,
            exp.get(path.relative_to(REPO).as_posix()))
        holes += got
    bad = [h for h in holes if '豁免台帳に登録していない' in h]
    return (len(bad), bad[0]) if bad else False


def ledger_exempt_imports_empty():
    """豁免の `imports` を空の辞書に書いた台帳が形の検査で止まること（`own-shape`。Astra 問 4 (c) 3）

    第 64 ラウンドまでの形の控制は `owners` を壊して測っていた（Astra 実測: `imports` が空の豁免は
    自分で測っていない）。`imports` が空の豁免を直接置いて測る"""
    def mut(doc):
        doc['exemptions'] = [{'file': _one_scanned_file(doc), 'imports': {}, 'note': '制御の細工'}]
    return _ledger_doc_mutated({'fn': mut})


def main():
    print(f'# 検査の検査（一時作業: {TMP}）')
    # Astra 第 68 ラウンド 問 1 の実装条件 4: 通常実行の開始時に無効化が残っていたら、それを
    # 黙って消して合格させない（`CGD_GUARD_OFF` を付けた実行は負控制の為の実行だけ）
    if IN.GUARD_OFF or os.environ.get('CGD_GUARD_OFF', '').strip():
        print('見張り番の箱の読み方の照合: 失敗', file=sys.stderr)
        print('  開始時に見張り番を消した実行になっている: '
              + str(sorted(IN.GUARD_OFF)[:8])
              + '（通常の検査は全部生きた状態だけで走る。無効化を消して合格させない。'
              'Astra 第 68 ラウンド 問 1 の実装条件 4）', file=sys.stderr)
        raise SystemExit(1)
    baseline = git_touches()
    try:
        # 第 56 ラウンド: 各制御に `guard`（消す見張り番）と `message`（その見張り番の案内）を
        # 書く。無効化しても別の所で落ちる制御は「空振り」として失敗する（agy P1）
        negative('要求一覧の graph を書き換えて id を据え置く', cond_graph_tampered,
                 guards='canonical-id', message='id が中身から再計算できない')
        # 第 63 ラウンド Astra 問 4 の裁定で増えた対応表の照合（合計値が同数のまま名前を
        # 入れ替える細工を止める為の 3 本）と問 1 の豁免の形の検査
        negative('対応表から 1 名を消す', ledger_name_missing,
                 guards='own-names', message='名前集合が違う')
        negative('対応表の 1 名の所属道具を別へ動かす', ledger_owner_moved,
                 guards='own-tools', message='所属道具と実測が違う')
        negative('対応表の走査対象から 1 ファイル消す', ledger_file_missing,
                 guards='own-files', message='走査対象に無いファイル')
        negative('豁免に走査対象外のファイルを登録する', ledger_exemption_unscanned,
                 guards='own-files', message='豁免が挙げる')
        negative('対応表の owners を配列でなくす', ledger_shape_broken,
                 guards='own-shape', message=IN.GUARD_LEDGER_HEADER)
        # 第 64 ラウンド Astra 問 3 裁定 (b): 文書で書けるフェンスの形を固定し、禁止形を失敗にする
        negative('情報文字列付きのフェンスを形検査が見逃す', fence_form_bypass,
                 guards='md-fence-form', message='許可した形ではない')
        # 第 64 ラウンド Astra 問 1 裁定 (c)（許可一覧へ切替）と問 2 裁定 (i)(ii)(iii)(iv) の
        # 単独名指し。「禁止機能の除外登録」「`bool as guard`」「台帳の不正」「比較を消す細工」は
        # 人が必ず対で確認するよう求められた物（`out/astra64.log`）
        negative('許可一覧に無い import を走査が見逃す', import_unregistered_hole,
                 guards='import-unregistered', message='未登録の import')
        negative('豁免でも通る `guard` の束縛を走査が見逃す', import_binds_guard_hole,
                 guards='import-binds-guard', message='見張り番と同じ名前')
        negative('豁免に動的機構の名前を登録する台帳を形の検査が見逃す',
                 exempt_loader_name_registered, guards='exempt-loader-name',
                 message='動的機構の名前')
        negative('同じファイルの豁免を 2 件並べた台帳を形の検査が見逃す',
                 exempt_dup_entry_registered, guards='exempt-dup-entry', message='重複登録')
        negative('対応表の JSON の重複した鍵を読み込みが見逃す', ledger_json_dup_key,
                 guards='json-dup-key', message=IN.GUARD_LEDGER_HEADER)
        negative('豁免あり・なしの呼び出し候補の比較を丸ごと消す', exempt_parity_moved,
                 guards='exempt-scan-parity', message='呼び出し候補が変わった')
        # 第 60 ラウンド Astra 問 2 の裁定で分割した判定それぞれの単独名指し（旧 `cond-shape` の
        # 5 箇所・`perm-count` の 3 箇所・`perm-cap` の 2 箇所）
        negative('条件オブジェクトに無い欄を 1 つ足す', cond_keys_extra_field,
                 guards='cond-keys', message='の欄が期待と違う')
        negative('条件の case に文字列以外（1）を置く', cond_case_not_string,
                 guards='cond-case', message='の case は null か文字列')
        negative('条件の args の 1 つを数値にする', cond_args_not_strings,
                 guards='cond-args', message='の args は文字列の配列')
        negative('条件の args 自体を数値にする', cond_args_not_a_list,
                 guards='cond-args', message='の args は文字列の配列')
        negative('条件の args を null にする', cond_args_is_null,
                 guards='cond-args', message='の args は文字列の配列')
        negative('既知差分の old を空辞書にする', known_old_is_dict,
                 message='の old が配列ではない')
        negative('既知差分の old に文字列を入れる', known_old_is_string,
                 message='の old が配列ではない')
        negative('既知差分の old を null にする', known_old_is_null,
                 message='の old が配列ではない')
        negative('既知差分の old を 1 要素に切る', known_old_too_short,
                 message='が 5 欄ではない')
        negative('既知差分の old の欄を数値にする', known_old_field_not_str,
                 message='欄・向きが文字列ではない')
        negative('既知差分の old の後ろの欄を null にする', known_old_tail_not_str,
                 message='階層・縁数・縁に文字列でも数値でもない欄がある')
        negative('既知差分から old の欄を消す', known_old_key_missing,
                 message='に old が無い')
        negative('既知差分の diffs を辞書にする', known_diffs_not_list,
                 message='diffs が配列ではない')
        negative('既知差分のトップレベルを配列にする', known_doc_is_list,
                 message='トップレベルが辞書ではない')
        negative('既知差分を JSON として読めない形にする', known_json_broken,
                 message='を JSON として読み取れない')
        negative('既知差分の形が壊れた日は件数の診断より先に止まる', known_shape_stops_before_count,
                 message=IN.KNOWN_HEADER)
        negative('既知差分の kind を値域外へ変える', known_kind_unknown,
                 message='kind が未知')
        negative('既知差分から kind を消す', known_kind_missing,
                 message='に kind が無い')
        negative('既知差分の cond を空白だけにする', known_cond_blank,
                 message='cond が空')
        negative('既知差分の cond を数値にする', known_cond_not_str,
                 message='cond が文字列ではない')
        negative('既知差分の id を数値にする', known_id_not_str,
                 message='id が文字列ではない')
        negative('既知差分の summary 行の old を負数にする', known_summary_old_negative,
                 message='old が 0 以上の整数ではない')
        negative('既知差分の summary 行の new を真偽値にする', known_summary_new_bool,
                 message='new が 0 以上の整数ではない')
        negative('条件の kind を値域外へ変える', cond_kind_out_of_range,
                 guards='cond-kind-args', message='kind が値域外')
        negative('走った縁順の通り数が宣言と違う', perm_expected_not_matched,
                 guards='perm-expected', message='件に対して 6 件走った')
        negative('間引き後に走るのが 1 とおりしかない比較', sampled_runs_single,
                 guards='perm-runs-min', message='実際に走らせた縁順が 1 とおりしかない')
        negative('要求一覧の args だけ書き換えて id を据え置く', cond_args_tampered,
                 guards='canonical-id', message='id が中身から再計算できない')
        negative('要求一覧に同じ起動内容を 2 件並べる', cond_duplicated,
                 guards='dup-condition', message='起動条件の正準形が重複',
                 clean=False, fallback='id が重複')
        negative('要求一覧に同じ起動内容を 2 件並べる（id 側の目）', cond_duplicated,
                 guards='dup-id', message='id が重複',
                 clean=False, fallback='起動条件の正準形が重複')
        negative('要求一覧に id だけを重複させる', cond_id_duplicated,
                 guards=('dup-id', 'canonical-id'), message='id が重複')
        negative('要求一覧の graph に # を混ぜ id と条件別キーを作り直す',
                 cond_graph_hash_rekeyed, guards='cond-graph',
                 message='の graph に `#` が混ざっている')
        negative('要求一覧の fixtures から 1 本消す（条件はそのまま）',
                 fixture_missing_from_spec, guards='fixture-set',
                 message='fixture が有るのに要求一覧に無い')
        negative('v1 の向きカウンタを 1 ずつ入れ替える', dir_rule_counters_rebalanced,
                 guards='dir-rule-counters', message='一致: 期待')
        negative('要求一覧から case を消す', cond_case_missing,
                 guards=('cond-keys', 'canonical-id', 'dup-condition', 'dup-id'),
                 message='の欄が期待と違う')
        negative('縁 3 本の順列 6 通りに対して 5 件走った', perm_count_mismatch,
                 guards='perm-count', message='は 3 本の順列 6 通りと違う')
        negative('終了 0 で JSON でない文字列を書く実行', run_json_non_json_output,
                 guards='json-parse', message='JSON が読めない')
        negative('要求一覧に値域外の kind を置く', cond_bad_kind,
                 guards=('cond-kind-args', 'canonical-id'), message='kind が値域外')
        negative('期待値の合計を条件別の合計からずらす', expectations_totals_off,
                 guards='cov-shape', message='total が条件別の合計と違う')
        negative('期待値の条件別の内訳を空にする', expectations_empty,
                 guards=('cov-shape', 'cov-keys'), message='byCondition が空')
        negative('走査した行数を 1 件ずらす', coverage_one_off,
                 guards='coverage', message='が期待値と違う')
        negative('突き合わせた親子数を件数の違う 2 件で入れ替える', coverage_swapped,
                 guards='coverage', message='が期待値と違う')
        negative('1 条件を測らない', coverage_missing_condition,
                 guards='coverage', message='が期待値と違う')
        negative('0 行の report.mjs で via-cycle.py', stub_via_cycle,
                 guards='rows-zero', message='比較する行が無い')
        negative('0 行の report.mjs で allperm.py', stub_allperm,
                 guards='rows-zero', message='比較する行が無い')
        negative('0 行の report.mjs で allperm-corr.py', stub_allperm_corr,
                 guards='rows-zero', message='比較する行が無い')
        negative('0 行の report.mjs で r43-permute.py', stub_r43_permute,
                 guards='rows-zero', message='比較する行が無い')
        negative('縁が 1 本だけのグラフで allperm.py', allperm_one_edge_graph,
                 guards='perm-edges', message='しかないグラフでは縁順を変えても比較に')
        negative('allperm.py に期待縁順の通り数違いを渡す', allperm_wrong_expected_permutations,
                 guards='perm-declared', message='走る前に分かる食い違い',
                 clean=False, fallback='件に対して 720 件走った')
        negative('allperm.py の行から突き合わせる欄が消える', allperm_row_missing_field,
                 guards='proj-fields', message='行に欄が無い', clean=False, fallback='KeyError')
        negative('実グラフの縁を全部抜いて edge-order.py', edge_order_no_edges,
                 guards='edge-group-empty', message='すべて群が 0 件')
        negative('18 本とも 0 行のレポートで check-dir-rule.py --profile current',
                 dir_rule_all_empty_reports,
                 guards=('dir-rule-counters', 'dir-rule-report'), message='一致: 期待')
        negative('向き別の合計は同じまま byReport の按分だけ入れ替えた一覧',
                 dir_rule_wrong_reports,
                 guards='dir-rule-report', message='の比較件数（レポート別）')
        negative('18 本そろえたうえで 1 本だけ行を消す（v1 プロファイル）',
                 dir_rule_broken_rows,
                 guards=('dir-rule-counters', 'dir-rule-report', 'dir-rule-v1'),
                 message='の比較件数（レポート別）')
        # 第 56 ラウンド Codex P2-1: 上の制御は行を消すので件数の見張り番が先に落ちる。
        # v1 の**内容**照合を単独で測るため、件数を動かさずに不一致の中身だけずらす
        negative('既知差分の id を別ノードへ動かす（不一致 55 件のまま）',
                 dir_rule_v1_ledger_moved,
                 guards='dir-rule-v1', message='既知差分に無い不一致')
        negative('byReport の実在する 2 本の比較件数を入れ替える（合計とキー集合はそのまま）',
                 dir_rule_report_swapped,
                 guards='dir-rule-report', message='の比較件数（レポート別）')
        negative('向き別の件数に負の値を置く（agree を増やして bad を引く）',
                 dir_rule_negative_counter, guards='cov-shape', message='負の整数')
        negative('要求一覧の fixtures に同じパスを 2 度書く',
                 fixtures_duplicated, guards='dup-fixture', message='fixtures に重複')
        negative('allperm-full.py の順列上限を 1 にする',
                 allperm_full_cap_one, guards='perm-cap', message='順列上限に 1 を渡している',
                 clean=False, fallback='実際に走らせた縁順が 1 とおりしかない')
        negative('終了 0 で JSON を書かない実行', run_json_silent,
                 guards='json-missing', message='終了 0 なのに JSON を書いていない',
                 clean=False, fallback='出力先が無い')
        negative('出力先が既にある実行', run_json_stale_output,
                 guards='out-exists', message='出力先がもう有る')
        # 第 56 ラウンド agy P2-3: `json-parse` だけ消すと `doc = {}` が `report-shape` で
        # 落ち、別の一で止まっていた。壊れた JSON を読む制御が測るのは「読めないこと」なので、
        # 読み終わった後の形検査もまとめて消して**通る**ことを要求する
        negative('壊れた JSON を読む実行', run_json_broken_json,
                 guards=('json-parse', 'report-shape'), message='JSON が読めない')
        negative('欄の無い JSON をレポートとして読む実行', run_json_wrong_shape,
                 guards='report-shape', message='にレポートの欄が揃っていない')
        negative('battery/ から渡した根からなら実在する相対パスを補わない', bad_relative_path,
                 guards='path-cwd-only', message='ディレクトリが無い')
        negative('指紋台帳の登録を 1 件消す', fingerprint_entry_removed,
                 guards='fp-unregistered', message='が指紋台帳に未登録')
        negative('fixture の縁を全部空にする', fixture_edges_emptied,
                 guards=('fp-sha', 'fp-bytes'), message='中身が基準と違う')
        negative('fixture のノード id を同じ長さで書き換える', fixture_renamed_same_length,
                 guards='fp-sha', message='中身が基準と違う')
        negative('fixture を 1 本増やす', fixture_added,
                 guards=('fixture-set', 'condition-set'), message='fixture が有るのに要求一覧に無い')
        negative('要求一覧から条件を 1 件消す', condition_removed_from_ledger,
                 guards='condition-set', message='起動条件が要求一覧')
        # 第 57 ラウンド agy P2 の 4 件（実測は `out/review-agy57.log`）。形・入口・標本の実り
        # を直した裁定は `out/astra58.log`
        negative('要求一覧の graph を絶対パスにする（id も揃えた細工）', cond_graph_absolute,
                 guards=('cond-graph', 'cov-keys'), message='リポジトリ相対ではない')
        negative('要求一覧の fixtures に文字列でない値を置く', fixtures_non_string,
                 guards='fixture-shape', message='文字列でない要素',
                 clean=False, fallback='fixture が有るのに要求一覧に無い')
        negative('byReport のキーを 1 本だけ実在しない名前に差し替える',
                 dir_rule_report_unknown_key, guards='cov-keys',
                 message='baseline-v1 へ無いレポート名がある')
        negative('byCondition の id を 1 件だけ要求一覧に無い値へ差し替える',
                 coverage_condition_unknown_key, guards='cov-keys',
                 message='要求一覧へ無い id がある')
        negative('向き none の数えに true を置く', directionless_bool_counter,
                 guards='cov-shape', message='が整数ではない')
        negative('向き none の数えに負の値を置く', directionless_negative_none,
                 guards='cov-shape', message='が負の整数')
        negative('expectations.directionless から none を消す', directionless_missing_none,
                 guards='cov-shape', message='が整数ではない')
        negative('レポート 0 件のディレクトリを report_paths へ直接渡す',
                 report_dir_empty_direct, guards='path-empty', message='が 0 件')
        negative('1 本のディレクトリに 18 件を期待して渡す',
                 report_dir_wrong_count_direct, guards='path-count', message='（18 件のはず）')
        negative('正しい JSON を書いて非 0 で終わる実行', run_json_child_fails_with_output,
                 guards='child-fail', message='report.mjs 失敗')
        negative('終了 0 で空のファイルを書く実行', run_json_empty_output,
                 guards='json-empty', message='JSON が空',
                 clean=False, fallback='JSON が読めない')
        negative('external.out が無い JSON を projection_rows へ渡す',
                 projection_bucket_missing, guards='proj-buckets', message='突き合わせる 6 欄',
                 clean=False, fallback='KeyError')
        negative('builder へ重複した fixture 列を渡す（要求一覧は正常）',
                 built_conditions_duplicated, guards='dup-built', message='今回組み上げた起動条件に重複')
        negative('allperm-full.py の順列上限を 0 にする', allperm_full_cap_zero,
                 guards='perm-cap', message='順列上限に 0 を渡している',
                 clean=False, fallback='実際に走らせた縁順が 1 とおりしかない')
        negative('r43-permute.py の入れ替え試行を 1 とおりにする', r43_trial_limit_one,
                 guards='trial-count', message='入れ替えの試行を 1 とおりに指定している',
                 clean=False, fallback='縁順が 1 とおりしかない')
        negative('expectations.directionless.none を 1 増やして count-none.py',
                 none_expectations_off_by_one, guards='none-expectations', message='期待値と**不一致**')
        negative('1 本の summary.rows を 1 増やして count-none.py',
                 none_counters_moved, guards='none-counters', message='サマリカウンタが割れているので不合格')
        negative('既知差分の 1 件を向きが変わらない形へ直す（導出 54 件）',
                 v1_derivation_rows_four, guards='v1-derivation', message='向き の差分が 54 件')
        negative('edge-order.py の子実行が非 0 で終わる', edge_order_child_fails,
                 guards='edge-child-fail', message='query.mjs 失敗',
                 clean=False, fallback='query.mjs の JSON が読めない')
        negative('edge-order.py が読めない出力を受け取る', edge_order_bad_json,
                 guards='edge-json-parse', message='JSON が読めない',
                 clean=False, fallback='出力が --json の形ではない')
        negative('edge-order.py に --json の形でない出力を渡す', edge_order_json_shape,
                 guards='edge-out-shape', message='出力が --json の形ではない')
        negative('要求一覧を壊して入力点検を走らせる', input_check_validates_ledger,
                 guards='dup-fixture', message='fixtures に重複')
        negative('指紋台帳に入力の一覧に無い物を 1 件足す', fingerprint_ledger_extra_entry,
                 guards='fp-ledger-extra', message='指紋台帳に有るが入力の一覧に無い')
        negative('指紋台帳のバイト数だけを 1 件書き換える', fingerprint_bytes_moved,
                 guards='fp-bytes', message='のバイト数が基準と違う')
        negative('要求一覧を壊して起動条件を組み立てる', launch_conditions_broken_ledger,
                 guards='fixture-shape', message='fixtures に文字列でない要素がある',
                 clean=False, fallback='fixture が有るのに要求一覧に無い')
        negative('指紋台帳の読み方だけを 1 件書き換える', fingerprint_mode_moved,
                 guards='fp-mode', message='の読み方が基準と違う')
        negative('指紋台帳の読み方に json でも bytes でもない値を置く', fingerprint_type_unknown,
                 guards='fp-type', message='指紋の型が台帳で不明',
                 clean=False, fallback='の読み方が基準と違う')
        negative('固定入力の構造指紋（ノード数）を 1 ずらす', fingerprint_structural_nodes_moved,
                 guards='fp-structural', message='の nodes が基準と違う')

        # 第 65 ラウンド Astra 問 1〜問 4 の裁定で増えた判定の単独名指し（`out/astra65.log`）
        negative('豁免のサブモジュール登録を走査が見逃す', import_granted_hole,
                 guards='import-granted', message='豁免台帳に登録していない')
        negative('`import *` を走査が見逃す', import_star_hole,
                 guards='import-star', message='import *')
        negative('箱経由でない `guard` の呼び出しを網羅へ数える', guard_unbound_hole,
                 guards='guard-unbound', message='箱経由ではない')
        negative('豁免由来の束縛を末端の直接呼び出し以外で読む', exempt_use_form_hole,
                 guards='exempt-use-form', message='登録した末端の直接呼び出し以外')
        negative('箱の公開名の表の形を形の検査が見逃す', ledger_box_shape_loose,
                 guards='box-shape', message='boxNames が辞書ではない')
        negative('豁免の同じ経路の中継と末端の併記を形の検査が見逃す', ledger_path_overlap,
                 guards='exempt-path-overlap', message='中継と末端の両方')
        negative('箱の公開名を用途と違う形で使うのを走査が見逃す', in_public_name_hole,
                 guards='in-public-name', message='箱の公開名')
        negative('箱の公開名の表に使わない登録を残すのを照合が見逃す', in_public_table_extra,
                 guards='in-public-table', message='boxNames に登録した公開名')
        negative('相対 import を豁免・許可一覧より先に落とす', relative_import_hole,
                 guards='import-relative', message='相対 import')
        negative('末端の登録が有るファイルの根だけの動的機構 import を名指す',
                 dynamic_root_import_hole, guards='import-dynamic-module',
                 message='動的な機構のモジュール「importlib」を')
        negative('箱の公開名の書き換え・削除を走査が見逃す', public_write_hole,
                 guards='in-public-write', message='書き換え・削除')
        negative('候補の道具が箱の公開名と豁免の差分を表示しない', emit_box_diff_blind,
                 guards='emit-diff', message='箱の公開名 追加')
        negative('候補の道具が書けない形と残った穴で候補を出してしまう', candidate_refusal_blind,
                 guards='emit-candidate-valid', message='書き換え・削除に使っている')
        negative('候補の道具が運用中の台帳へ直接書ける', emit_target_blind,
                 guards='emit-target', message='直接書いてはいけない')
        negative('候補の道具が観測した呼び出し元を自動で許可に載せる', emit_caller_approval_blind,
                 guards='emit-caller-approval', message='観測されたが未承認の区間の呼び出し元')
        negative('台帳に無いファイルが見張り番を消す区間を作る', guard_callers_file_hole,
                 guards='guard-caller-file', message='guardCallers` に無いファイル')
        negative('区間を作らないファイルが台帳の呼び出し元に残る', guard_callers_unused_hole,
                 guards='guard-caller-file', message='見張り番を消す区間を作っていない')
        negative('台帳の呼び出し元に実在しないファイルが載る', guard_callers_ghost_hole,
                 guards='guard-callers-scope', message='走査対象の道具に無い')
        negative('`with` の管理以外で見張り番を消す区間を作る', guard_caller_form_hole,
                 guards='guard-caller-form', message='`with` の管理ではない位置')
        negative('台帳の guardCallers の形を検査しない', guard_callers_shape_hole,
                 guards='guard-callers-shape', message='guardCallers')
        negative('条件式・コンテナを経由した呼び出しの受け手を走査が見逃す',
                 public_call_via_condition, guards='in-public-name',
                 message='呼び出しへ至る連鎖')
        negative('条件式・コンテナを経由した書き換えを走査が見逃す',
                 public_write_via_expression, guards='in-public-write',
                 message='書き換え・削除')
        negative('箱の公開名の未登録の出現位置を走査が見逃す', public_role_unsupported_hole,
                 guards='in-public-name', message='未登録の位置')
        positive('箱の公開名の通る形（読み取り・呼び出し・添字の中の読み）は穴ではない',
                 public_use_forms_clean)
        positive('新しい値を作る式の中の読み取りは穴ではない（既定拒否の白名前の側）',
                 public_new_value_reads_clean)
        positive('コンテナ・演算の許可側が誤検出にならない', container_paths_read_side_clean)
        positive('候補は自分の箱の表で走査できる（旧台帳に縛られない）',
                 candidate_uses_own_box_table)
        positive('`--emit` の相対パスを打った場所から解決する',
                 emit_relative_dest_from_other_cwd)
        negative('語尾へ文字を足した区画マーカーを正式に読む', md_marker_form_bypass,
                 guards='md-marker-form', message='他の文字が付いている')
        negative('手で作った豁免マップを検査せずに走査へ渡す', exempt_map_expanded_wrong,
                 guards='exempt-map-expand', message='台帳から作り直した物と違う')
        negative('台帳の登録禁止が禁止属性を避けている', exempt_loader_attrs_gap,
                 guards='exempt-loader-attrs', message='避けていない')
        negative('必要豁免を 1 件落とした台帳で走査する', ledger_exemption_removed,
                 guards='import-granted', message='豁免台帳に登録していない')
        negative('豁免の imports を空にした台帳を形の検査が見逃す', ledger_exempt_imports_empty,
                 guards='own-shape', message=IN.GUARD_LEDGER_HEADER)
        positive('正当な 0 行レポート 4 本は形として通る', legit_empty_reports)
        positive('期待値の合計が条件別の合計と導出で一致', coverage_current_matches)
        positive('リポジトリ根と battery/ の両方から同じ相対パス', relative_paths_from_both_cwds)
        positive('追跡下の一覧が自分の形を検査して通る', ledger_self_valid)
        positive('指紋台帳と入力が揃っている', fingerprint_ledger_clean)
        positive('入力点検の道具が実際に起動して終了 0 で通る', input_check_tool_runs)
        positive('要求一覧を壊した日に 2 本の道具が同じ案内を出す', broken_required_ledger_same_message)
        positive('許可していない見張り番の読み方（別名・import・getattr・ラッパ・再束縛）を穴として出す',
                 scanner_reads_only_allowed_syntax)
        positive('正控制・負控制の実行契約を偽控制で確かめる', runner_contract_holds)
        positive('見張り番の名前すべてに単独名指しの負控制が通っている', guard_names_have_singleton_controls)
        positive('README に載った見張り番の名前が実コードと道具別に対応している', readme_guard_names_match_code)
        positive('docs/decisions.md の決めの表が 4 欄で揃っている', decisions_table_columns_hold)
        positive('見張り番の対応表 guard-owners.json が今の走査と一致している', guard_owner_ledger_holds)
        positive('豁免が名乗った import と名前だけを許すことを対で確かめる', guard_exemption_scope_holds)
        positive('README と決めの表のコードフェンスが許可した形だけになっている', markdown_fences_hold)
        positive('追跡下の一覧対象が日本表記の漢字だけを使う', japanese_glyphs_only)
        positive('文書の案内先が実在し項目数の記載が文書間で揃う', doc_pointers_resolve)
        positive('負控制の実行器が 6 観測点と網羅の記録契約を守っている', _runner_self_check)

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
