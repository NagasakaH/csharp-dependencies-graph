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
# 1 個ずつ消せる。`negative(name, fn, guards=..., message=...)` は
#   1. 素の実行 → 落ちて `message`（その見張り番の案内）が出ること
#   2. `guard` を消した実行 → `message` が出ないこと。既定では**通る**ことも要求する
# を検査するので、対象の見張り番を消しても別の所で落ちるだけの**空振り制御**を通さない。
# 名前のスペルを間違えると 2 で同じ案内が出て失敗するので、名前表の管理は要らない。
import ast
import glob
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
        return False, 'NotDetected: ' + str(e)   # 制御自身の故障。OFF 側で成功に数えない
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


def negative(name, fn, guards=None, message=None, clean=True, fallback=None):
    """失敗しなければならない制御。**その見張り番が落ちたこと**まで確かめる

    第 55 ラウンド agy P1 の実測で、負控制の 3 件は「別の一の見張り番が先に落ちる」だけで
    合格していた（対象の見張り番を無効化しても制御がまだ落ちる＝その見張り番を測っていない
    空振り）。だからここで 2 度走らせる:

    1. **素の実行**: 落ちて、`message`（対象の見張り番の案内）が含まれること
    2. **`guard` を消した実行**: `message` が出ないこと。`clean`（既定）なら**通ること**も
       要求する（他の見張り番に遮われている間は、その制御は対象を測っていない）

    `clean=False` は「見張り番を消すと対象の診断は消えるが、実行は別の診断で拒否される」制御が
    使える（重複検査のように複数の見張り番が同じ細工を拾う場合を含む。Astra 第 59 ラウンド
    問 2: 「実行系の制御だけ」という但し書きは重複検査を説明できないので外した）。その場合は
    `fallback` に **OFF 後も残る別の診断の文面**を書く（第 56 ラウンド agy P2-3）。文面を
    宣言させていないと Run 2 が何で止まったか不明のまま「別の一で落ちた＝検出成功」と数える。
    対象を消したのに `message` が残る実行は `clean=False` でも失敗にする（問 2 の契約）"""
    ran['negative'] += 1
    names = (guards,) if isinstance(guards, str) else tuple(guards or ())
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
    if text2.startswith('NotDetected:'):
        # Astra 第 59 ラウンド 追加穴 1 の実測: 見張り番を消した側で制御が準備に失敗すると
        # 「拒否なし」に化けて `clean=True` を通っていた。制御自身の故障は成功ではない
        failed.append(f'{name}: 見張り番を消した実行が制御の準備失敗で終わった'
                      f'（制御が壊れている。成功ではない）: {text2[:160]}')
        return
    if message and message in text2:
        failed.append(f'{name}: 見張り番 {" / ".join(names)} を消したのに同じ案内が出た'
                      f'（この制御が見ているのは別物）: {text2[:160]}')
        return
    tier = None
    if clean and det2:
        failed.append(f'{name}: 見張り番 {" / ".join(names)} を消しても別の所で落ちる'
                      f'（他の見張り番に遮われて対象を測っていない）: {text2[:200]}')
    elif not clean:
        # 見張り番を消しても実行が別の診断で拒否される制御は、**何が落ちたか**を宣言させる
        if not fallback:
            failed.append(f'{name}: clean=False は fallback に「OFF 後も残る別の診断の文面」を書く'
                          '（何も言わないと Run 2 が何で止まったか不明のまま通る）')
        elif not det2 or fallback not in text2:
            failed.append(f'{name}: 見張り番 {" / ".join(names)} を消した実行が'
                          f'「{fallback}」で止まらない（想定と違う所で落ちた）: {text2[:200]}')
        else:
            tier = 'fallback'
    else:
        tier = 'clean'
    if tier and len(names) == 1:
        # 網羅を数える正控制は、ソースに書いてある制御ではなく**通った**単独名指しだけを使う
        # （Astra 第 59 ラウンド 問 4）。第 60 ラウンド Astra 問 3 の裁定で**後勝ち上書きをやめ**、
        # 「どの控制がどの階級で通った」を名前ごとに全部残す（`child-fail` のように clean と
        # fallback が並ぶ名前で、後に走った方の階級だけが残ることを防ぐ）
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


def _known_diffs_break(mutate=None, text=None):
    """既知差分（`known-v1-diffs.json`）を壊して `expected_direction_diffs` を通す（Astra 第 61 ラウンド 問 3 の追記）

    導出関数だけを見るので v1 のレポートは走らせない。壊した一覧からの再生成は人の判断なので、
    ここで自動更新はしない（`v1diff.py --emit-known` は候補を出すだけの道具）"""
    p = stash(f'{BATTERY}/known-v1-diffs.json')
    doc = json.loads(p.read_text(encoding='utf-8'))
    rows = [i for i, d in enumerate(doc['diffs']) if isinstance(d, dict) and d.get('kind') == 'row']
    if not rows:
        raise NotDetected('既知差分に kind が row の行が無い（この制御の前提が変わった）')
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
_DYNAMIC_LOOKUP = {'globals', 'locals', 'vars'}
_DYNAMIC_EXEC = {'exec', 'eval'}


def _bound_names(node):
    """代入の左辺に現れる名前（タプル・リスト・`*` を展開して返す）"""
    if isinstance(node, ast.Name):
        yield node.id
    elif isinstance(node, (ast.Tuple, ast.List)):
        for elt in node.elts:
            yield from _bound_names(elt)
    elif isinstance(node, ast.Starred):
        yield from _bound_names(node.value)


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


def _guard_symbols(tree, origin):
    """見張り番の入った箱（`import _inputs as IN` の `IN`）と、読み方を壊す束縛を調べる

    Astra 第 61 ラウンド 問 2 のとおり「呼び出されるか」まで追う解析はしない。**見張り番の入った
    名前を別のに束縛する形その物**を穴にする（呼び出しの実体が静的に決まらない為）"""
    boxes, holes = set(), []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name == _INPUTS_MODULE or a.name.endswith('.' + _INPUTS_MODULE):
                    boxes.add(a.asname or a.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if (mod == _INPUTS_MODULE or mod.endswith('.' + _INPUTS_MODULE)) and any(
                    a.name == _GUARD_NAME for a in node.names):
                got = '、'.join(sorted({a.asname or a.name for a in node.names
                                        if a.name == _GUARD_NAME}))
                holes.append(f'{origin}:{node.lineno} 見張り番を import で取り出している（{got}。'
                             '取り出した先で `guard` / `IN.guard` の直接呼び出し以外で呼ばれた物は'
                             'このファイルの網羅から見えない）')
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for tgt in targets:
                for nm in _bound_names(tgt):
                    if nm == _GUARD_NAME or nm in boxes:
                        holes.append(f'{origin}:{node.lineno} 見張り番の入った名前「{nm}」へ別のを'
                                     '束縛する（呼び出しの実体が静的に決まらない）')
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.comprehension)):
            for nm in _bound_names(node.target):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」をループ変数に束縛する')
        elif isinstance(node, ast.NamedExpr):
            for nm in _bound_names(node.target):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を `:=` で束縛する')
        elif isinstance(node, ast.ExceptHandler) and node.name in {_GUARD_NAME} | boxes:
            holes.append(f'{origin}:{node.lineno} 見張り番の名前「{node.name}」を例外の変数に束縛する')
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            for nm in node.names:
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を '
                                 f'`{type(node).__name__.lower()}` で宣言する')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            a = node.args
            params = [x.arg for x in list(a.posonlyargs) + list(a.args) + list(a.kwonlyargs)]
            params += [x.arg for x in (a.vararg, a.kwarg) if x is not None]
            for nm in params:
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を仮引数に使う'
                                 '（その関数の中だけなら別物でも、呼び出しは同じ `nm(...)` に見える）')
        elif isinstance(node, (ast.withitem,)) and node.optional_vars is not None:
            for nm in _bound_names(node.optional_vars):
                if nm == _GUARD_NAME or nm in boxes:
                    holes.append(f'{origin}:{node.lineno} 見張り番の名前「{nm}」を `with` の変数に束縛する')
    return boxes, holes


def _guard_reference_holes(tree, boxes, parents, origin):
    """見張り番を**呼び出し以外**で参照している箇所を穴にする（Astra 問 2: 取り出した時点で穴）

    第 60 ラウンドまでは `ast.Assign` だけを見ていた。`g: object = guard`（注釈付き代入）、
    `(g := guard)`（ウォルラス）、`a, b = guard, x`（分割代入）、`SimpleNamespace(guard=IN.guard)`
    （コンテナへの格納）、`return guard`（返り値）は全部ここに通る"""
    holes = []
    for node in ast.walk(tree):
        if not _is_guard_ref(node, boxes) or not isinstance(node.ctx, ast.Load):
            continue
        parent = parents.get(id(node))
        if isinstance(parent, ast.Call) and parent.func is node:
            continue   # 呼び出しの形その物は `_guard_scan` の側で検査する
        holes.append(f'{origin}:{node.lineno} 見張り番を呼び出し以外で参照している（別名への代入・'
                     '返り値・関数への受け渡し・コンテナへの格納など。この先で何が呼ばれるか'
                     '静的に決まらないので網羅の分母に入れない）')
    return holes


def _dynamic_holes(tree, boxes, origin):
    """`getattr` / `globals()['guard']` / `exec` / `eval` / `__getattr__` を穴にする（Astra 問 2 の禁止構文）

    AST を読む為の `getattr(node, 'id', '')` まで禁止しない。文字列の中身を実行構文として走査
    もしない"""
    holes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            called = _call_name(node)
            texts = [_const_str(a) for a in list(node.args) + [kw.value for kw in node.keywords]]
            hits_guard = _GUARD_NAME in [x for x in texts if x is not None]
            if called == 'getattr' and node.args and _is_guard_ref(node.args[0], boxes):
                hits_guard = True
            if called in _DYNAMIC_LOOKUP or called == 'getattr':
                if hits_guard:
                    holes.append(f'{origin}:{node.lineno} `{called}(...)` で見張り番を取り出している'
                                 '（動的な取り出しはこのファイルの網羅から見えない）')
            if called in _DYNAMIC_EXEC:
                holes.append(f'{origin}:{node.lineno} `{called}` による動的実行（この中で呼ばれた'
                             '見張り番は網羅から見えない）')
        elif isinstance(node, ast.Subscript):
            if _const_str(node.slice) != _GUARD_NAME:
                continue
            v = node.value
            via = isinstance(v, ast.Call) and _call_name(v) in _DYNAMIC_LOOKUP
            via = via or (isinstance(v, ast.Attribute) and v.attr == '__dict__')
            if via:
                holes.append(f'{origin}:{node.lineno} `{_GUARD_NAME}` を辞書経由で取り出している'
                             '（`globals()` / `locals()` / `vars()` / `__dict__` 経由の呼び出しは'
                             'このファイルの網羅から見えない）')
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == '__getattr__':
            holes.append(f'{origin}:{node.lineno} `__getattr__` を定義している（見張り番を'
                         '動的に公開できるので網羅の外）')
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
            """返り値・代入の右辺が見張り番の読み（呼び出し / その物 / それに束縛した名前）か"""
            if _is_guard_ref(expr, boxes):
                return True
            if isinstance(expr, ast.Call) and _is_guard_ref(expr.func, boxes):
                return True
            return isinstance(expr, ast.Name) and expr.id in handed

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


def _guard_scan(text, origin):
    """見張り番の呼び出しを AST で読む。**許可した構文以外で見張り番に触れたら穴**（第 61 ラウンド Astra 問 2 の裁定 (ii)）

    第 60 ラウンドまでは「`ast.Assign` で別名を作ったか」を列挙する方式だった。Codex と agy の実測で
    `from _inputs import guard as g` / `g: object = guard` / `(g := guard)` / `getattr(IN, 'guard')` /
    `SimpleNamespace(guard=IN.guard)` / `globals()['guard']` / `functools.partial(IN.guard)` が名前の
    集合にも穴の列にも出ない（網羅の分母から黙って消える）と判った。束縛の形を足し続ける方式是
    続きが無いので、**数えるのは `guard('名前')` と `IN.guard('名前')` の直接呼び出しだけ**に決め、
    それ以外で見張り番に届いた物は**取り出した時点**で穴にする（Astra 問 2: 呼び出されるかまでの
    追跡はしない。未使用の束縛も穴。`return IN.guard('x')` のようなラッパも穴）

    戻り値は（名前の集合、穴の説明文の列、名前の呼び出し回数の辞書）。回数は
    「1 名前 = 呼び出し 1 箇所」の規則を見る（Astra 第 60 ラウンド 問 2）"""
    tree = ast.parse(text)
    boxes, holes = _guard_symbols(tree, origin)
    parents = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    shadow = _shadowed_scopes(tree, boxes) | {id(x) for x in _wrapper_functions(tree, boxes)}
    found, counts = set(), {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _is_guard_ref(node.func, boxes)):
            continue
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
        if lit:
            found.add(lit)
            counts[lit] = counts.get(lit, 0) + 1
        else:
            holes.append(f'{origin}:{node.lineno} `guard()` の呼び出しが許可した形ではない'
                         '（引数 1 個の空でない文字列リテラル、キーワード引数無し以外は'
                         '網羅の分母に入らない）')
    holes += _guard_reference_holes(tree, boxes, parents, origin)
    holes += _dynamic_holes(tree, boxes, origin)
    for node in _wrapper_functions(tree, boxes):
        holes.append(f'{origin}:{node.lineno} 関数「{getattr(node, "name", "<lambda>")}」は'
                     '見張り番の読みを呼び出したり受け取ったりして結果だけを返すラッパ（呼ぶ側は '
                     '`guard` の呼び出しとして見えない。同じ判定をする共有検査関数は、その場で'
                     '判定すること）')
    return found, holes, counts


def _guard_call_names(path):
    """`_guard_scan` が読んだ名前集合だけ返す（穴を数えない所で使う）"""
    names, _, _counts = _guard_scan(path.read_text(encoding='utf-8'), path)
    return names


def _negative_guard_groups(path):
    """`negative(...)` に**書いてある** `guards=` の名前組を AST で集める

    ここは「書かれている名前」を見る（検査器に無い名前を制御に書いた日を探すため）。実際に
    網羅したかは、実行後に通った制御だけを数える"""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not (isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'negative'):
            continue
        for kw in node.keywords:
            if kw.arg != 'guards':
                continue
            one = _const_str(kw.value)
            if one:
                out.append((one,))
            elif isinstance(kw.value, (ast.Tuple, ast.List)):
                names = [_const_str(e) for e in kw.value.elts]
                if names and all(names):
                    out.append(tuple(names))
    return out


def _singleton_controls(path):
    """`negative(...)` に**書いてある単独名指しの控制**を `(説明, 名前)` で集める

    第 60 ラウンド Astra 問 3 の裁定は「登録した控制はすべて実行・成功を必須とし、片方の成功で
    他方の失敗や未実行を埋め合わせない」。ここでは**登録**を見て、実行後に通った記録と突き合わせる"""
    out = []
    for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
        if not (isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'negative'):
            continue
        label = _const_str(node.args[0]) if node.args else None
        for kw in node.keywords:
            if kw.arg == 'guards':
                one = _const_str(kw.value)
                if one and label:
                    out.append((label, one))
    return out


def _guard_names_by_file():
    """見張り番の名前をツリーから走査して `(全体名, ファイル別の直接呼び出し, 呼び出し回数, 穴)` を返す

    網羅の正控制と README の名前検査が**同じ走査**を共有する（走査を 2 本持つと、片方だけを直して
    「README は通るが網羅の実測は嘘」が作れる。第 60 ラウンド Codex P2-2 の別名穴と同じ形）"""
    names, direct, counts, holes = set(), {}, {}, []
    for path in sorted((REPO / 'skill' / 'scripts' / 'tools').rglob('*.py')):
        got, got_holes, got_counts = _guard_scan(path.read_text(encoding='utf-8'), path)
        names |= got
        holes += got_holes
        if got:
            if path.name in direct and direct[path.name] != got:
                failed.append(f'{path.name} が同名の道具ファイルとして 2 箇所に見つかる'
                              '（README の道具別一覧はファイル名で対応付けている）')
            direct.setdefault(path.name, set()).update(got)
        for k, v in got_counts.items():
            counts[k] = counts.get(k, 0) + v
    return names, direct, counts, holes


def _format_guard_names(names, limit=6):
    """名前の列を人が読む形に整える（空なら「無し」。第 60 ラウンド agy P2-4 の `[]` 直連結をやめる）"""
    items = sorted(set(names))
    if not items:
        return '無し'
    tail = f' 他 {len(items) - limit} 名' if len(items) > limit else ''
    return ' / '.join(items[:limit]) + tail


README_REGION_HEAD = '<!-- 見張り番の道具別一覧'
README_REGION_END = '<!-- /見張り番の道具別一覧 -->'
# 見張り番の名前らしき語（小文字と `-` のみ。`coverage` のように `-` を含まない名前的な語も拾う）。
# `.py` / `.json` / `min-0.json` は閉じバッククォートが続けて来ないのでマッチせず、`--オプション` は
# 先頭が `-` なので入らない。読むのは下の 2 区画だけなので、旧名を載せた歴史説明は対象外
GUARD_WORD = re.compile(r'`([a-z][a-z0-9]*(?:-[a-z0-9]+)*)`')
README_TOOL_HEAD = re.compile(r'^-\s+`([^`]+)`')
BAD_BULLET = '（箇条書きの形が不正）'


def _readme_guard_refs(text):
    """README の**見張り番を載せると決めた箇所**から `(名前, 道具, 行番号)` を読む（Astra 第 61 ラウンド 問 5）

    バッククォート語を全部数える方式は避ける。歴史説明に旧名を書いた行まで現在名の検査に混ざり、
    「旧名を記録に残す」というこの README の約束と衝突する。読むのは次の 2 箇所だけ:

    1. `<!-- 見張り番の道具別一覧 -->` に挟まれた箇条書き。行頭のバッククォートが道具のファイル名、
       残りがその道具で**直接呼ぶ**見張り番（共有ヘルパー `_inputs.py` は経由側として明記する）
    2. 1 列目の見出しが `名前` の表（判定のまとめ。道具とは対応付けていないので道具別の検査はしない）

    箇条書きの形が崩れた行は `BAD_BULLET` を返す（黙って 0 件にしない）"""
    refs, in_region, name_table = [], False, False
    for no, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if s.startswith(README_REGION_END):
            in_region, name_table = False, False
            continue
        if in_region:
            if not s.startswith('- '):
                continue
            m = README_TOOL_HEAD.match(s)
            if not m or not m.group(1).endswith('.py'):
                refs.append((BAD_BULLET, None, no))
                continue
            tool = m.group(1)
            for w in GUARD_WORD.findall(s[m.end():]):
                refs.append((w, tool, no))
            continue
        if s.startswith(README_REGION_HEAD):
            in_region = True
            continue
        if not s.startswith('|'):
            name_table = False
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if not cells or set(''.join(cells)) <= set('-: '):
            continue
        first = cells[0].strip('`* ')
        if first == '名前':
            name_table = True
            continue
        if name_table:
            for w in GUARD_WORD.findall(cells[0]):
                refs.append((w, None, no))
    return refs


def _readme_guard_errors(refs, code, direct):
    """読んだ名前と実コードを突き合わせて説明文の列で返す（空なら一致。Astra 第 61 ラウンド 問 5）

    検査は 3 方向: README の名前 ⊆ 実コード全体（旧名の残りの検出）、道具別の名前 ⊆ その道具の
    直接呼び出し（`child-fail` のように**別経路で現役**な名前を別の道具の説明に載せた残りの検出）、
    実コードの全名前 ⊆ 道具別一覧（一覧が古くて新しい見張り番を落とさない）。
    部分集合だけでなく全件一覧との等価も見る（Astra 問 5: 「全件一覧と宣言している表には等価比較」）"""
    errs = []
    if not refs:
        errs.append('README の道具別一覧と「名前」列から 1 件も読めない（区画が消えて空集合で成功する）')
        return errs
    unknown = sorted({n for n, _t, _l in refs if not n.startswith('（')} - code)
    if unknown:
        errs.append(f'README に載った見張り番 {_format_guard_names(unknown)} は実コードに無い'
                    '（改名の残りか、実在しない名前の記入）')
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
    code, direct, _counts, _holes = _guard_names_by_file()
    for msg in _readme_guard_errors(_readme_guard_refs(text), code, direct):
        failed.append(f'README の見張り番の名前: {msg}')

    def errs_of(mut):
        return _readme_guard_errors(_readme_guard_refs(mut(text)), code, direct)

    probes = (
        ('実在しない名前へ書き換える',
         lambda s: s.replace('`edge-child-fail`', '`edge-order-groups`'), '実コードに無い'),
        ('別経路で現役な名前へ書き換える',
         lambda s: s.replace('- `edge-order.py`: `edge-child-fail`',
                             '- `edge-order.py`: `child-fail`'), '直接'),
        ('一覧に無い道具を挙げる',
         lambda s: s.replace('- `edge-order.py`:', '- `edge-order-x.py`:'), '実コードに見つからない'),
        ('道具別一覧の区画を消す',
         lambda s: s.replace('<!-- 見張り番の道具別一覧:この箇条書きだけを解析する -->',
                             '<!-- 区画を消した -->'),
         '箇条書きが 1 行も読めない'),
        ('道具別一覧から 1 名を消す',
         lambda s: s.replace(' / `v1-derivation`\n', '\n'), '道具別一覧に無い'),
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
    tree, _direct, counts, holes = _guard_names_by_file()
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


_SCAN_HEAD = 'import _inputs as IN\n'


def _scan_of(body):
    """制御用の短いソースを `_guard_scan` に読ませて（名前集合、穴、件数）を返す"""
    return _guard_scan(_SCAN_HEAD + body, '<制御>')


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

    keep_in = IN.GUARD_OFF
    del failed[:]
    ran['negative'] = 0
    negative('契約-見張り番なしで通る制御', lambda: None, guards=())
    if not [x for x in failed if '見張り番なし' in x]:
        out.append('負控制の契約: 落ちずに通った制御が失敗として記録されていない')
    IN.GUARD_OFF = keep_in
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


def main():
    print(f'# 検査の検査（一時作業: {TMP}）')
    baseline = git_touches()
    try:
        # 第 56 ラウンド: 各制御に `guard`（消す見張り番）と `message`（その見張り番の案内）を
        # 書く。無効化しても別の所で落ちる制御は「空振り」として失敗する（agy P1）
        negative('要求一覧の graph を書き換えて id を据え置く', cond_graph_tampered,
                 guards='canonical-id', message='id が中身から再計算できない')
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
