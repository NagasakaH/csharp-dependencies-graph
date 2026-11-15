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


def py(script, *args, cwd=None):
    """battery の道具を走らせて終了コードを返す（`| tail` で測ると `tail` の値になるので気をつける）"""
    p = subprocess.run([sys.executable, str(HERE / script), *[str(a) for a in args]],
                       cwd=str(cwd or REPO), capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr)


def node_stub(body, name='stub.mjs'):
    """report.mjs の代わりになる小さな mjs を作る（壊れた実装の再現用）"""
    p = TMP / name
    p.write_text(body, encoding='utf-8')
    return str(p)


EMPTY_STUB = node_stub("""
// どの欄にも行を入れない report.mjs（第 54 ラウンド agy 指摘 2 で通った物）
import fs from 'node:fs';
const argv = process.argv.slice(2);
const out = argv[argv.indexOf('--json') + 1];
fs.writeFileSync(out, JSON.stringify({
  summary: {graph: argv[argv.indexOf('--graph') + 1], rows: 0, hops: 8, wiringHops: 3, limit: 100000},
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


TOUCHED = ['skill/tests/fixtures/ImpactFacts', f'{BATTERY}/required-checks.json',
           f'{BATTERY}/input-fingerprints.json']


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


def negative(name, fn):
    """失敗しなければならない制御。道具が落ちなければ here が違反として数える

    制御の戻り値は **`(終了コード, 出力)` の組**（subprocess を使う制御）か **True**
    （自分で確かめて「検出した」と答える制御）。例外は `SystemExit(0)` だけを
    「通った」とみなす"""
    ran['negative'] += 1
    try:
        res = fn()
    except NotDetected as e:
        failed.append(f'{name}: {e}')
        return
    except SystemExit as e:
        if isinstance(e.code, int) and e.code == 0:
            failed.append(f'{name}: 終了 0 で通った（期待は 0 以外）。{str(e)[:120]}')
        return
    except (AssertionError, ValueError, KeyError) as e:
        return
    if isinstance(res, tuple) and res and isinstance(res[0], int):
        if res[0] == 0:
            failed.append(f'{name}: 終了 0 で通った（期待は 0 以外）。{res[1][:160]}')
        return
    if res is True:
        return
    failed.append(f'{name}: 落ちずに通った（期待は 0 以外）。{str(res)[:160]}')


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
    """`args` だけ変えて id を据え置く（同じ穴の別形）"""
    spec = spec_copy()
    spec['conditions'][3]['args'] = ['--api', 'GET /vswitch']
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
    spec['expectations']['invariantRows']['byCondition'] = {}
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
    keys = sorted(k for k, v in by.items() if v != 0)
    got = dict(by)
    got[keys[0]], got[keys[1]] = by[keys[1]], by[keys[0]]
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
    victim.write_text(json.dumps({'extra': [], 'graph': {
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
    d.mkdir()
    argv = ['--graph', 'out/demo/graph.json', '--hops', '8', '--wiring-hops', '3',
            '--limit', '100000']
    for p in sorted((HERE / 'baseline-v1').glob('*.json')):
        subprocess.run(['node', EMPTY_STUB, *argv, '--json', str(d / p.name)],
                       cwd=str(REPO), capture_output=True, text=True, check=True)
    return py('check-dir-rule.py', '--profile', 'current', str(d))


def dir_rule_wrong_counts():
    """プロファイルの期待値と違う件数（向き が全部同じ方へ倒れた日など）"""
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


def run_json_silent():
    """終了 0 で JSON を書かない実行（走らなかった日を合格にしない）"""
    IN.run_json(SILENT_STUB, ['--graph', 'x'], str(TMP / 'nope.json'), REPO, label='制御')


def run_json_stale_output():
    """出力先がもう有る実行（前の実行の JSON を今回の結果と読まない）"""
    old = TMP / 'stale.json'
    old.write_text('{"summary": {}}', encoding='utf-8')
    IN.run_json(SILENT_STUB, [], str(old), REPO, label='制御')


def run_json_broken_json():
    """JSON が壊れていない実行を用意して、読む側が止まることを確かめる"""
    bad = TMP / 'broken.mjs'
    bad.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1], '{"summary": {"graph"');
""", encoding='utf-8')
    IN.run_json(str(bad), [], str(TMP / 'broken.json'), REPO, label='制御')


def run_json_wrong_shape():
    """欄の無い JSON（別の道具の出力）をレポートとして数えない"""
    odd = TMP / 'odd.mjs'
    odd.write_text("""
import fs from 'node:fs';
const argv = process.argv.slice(2);
fs.writeFileSync(argv[argv.indexOf('--json') + 1],
  JSON.stringify({summary: {graph: 'x'}, rows: []}));
""", encoding='utf-8')
    IN.run_json(str(odd), [], str(TMP / 'odd.json'), REPO, label='制御')


def bad_relative_path():
    """`battery/` から見て存在しない相対パスを素直に渡す（根から補わない）"""
    return py('check-dir-rule.py', '--profile', 'current', '../../out/audit-current',
              cwd=HERE)


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
    if not bad:
        raise NotDetected(f'指紋台帳から {victim} を消しても検出しなかった')
    return True


def fingerprint_content_changed():
    """fixture の縁を全部空にする（第 54 ラウンド Codex 指摘 1 そのもの）"""
    rel = 'skill/tests/fixtures/ImpactFacts/arrow-priority.graph.json'
    p = stash(rel)
    doc = json.loads(p.read_text(encoding='utf-8'))
    doc['edges'] = []
    p.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
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
            if isinstance(e.code, int) and e.code == 0:
                raise NotDetected('fixture を 1 本増やした日が終了 0')
            return True
        raise NotDetected('fixture を 1 本増やしても要求一覧との比較が通った')
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
            if isinstance(e.code, int) and e.code == 0:
                raise NotDetected('要求一覧から条件を消した日の終了コードが 0')
            return True
        raise NotDetected('要求一覧から条件を消しても通った（要求に無いのに走る日）: '
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


def main():
    print(f'# 検査の検査（一時作業: {TMP}）')
    baseline = git_touches()
    try:
        negative('要求一覧の graph を書き換えて id を据え置く', cond_graph_tampered)
        negative('要求一覧の args だけ書き換えて id を据え置く', cond_args_tampered)
        negative('要求一覧に同じ起動内容を 2 件並べる', cond_duplicated)
        negative('要求一覧に id だけを重複させる', cond_id_duplicated)
        negative('要求一覧から case を消す', cond_case_missing)
        negative('要求一覧に値域外の kind を置く', cond_bad_kind)
        negative('期待値の合計を条件別の合計からずらす', expectations_totals_off)
        negative('期待値の条件別の内訳を空にする', expectations_empty)
        negative('走査した行数を 1 件ずらす', coverage_one_off)
        negative('突き合わせた親子数を 2 件入れ替える', coverage_swapped)
        negative('1 条件を測らない', coverage_missing_condition)
        negative('0 行の report.mjs で via-cycle.py', stub_via_cycle)
        negative('0 行の report.mjs で allperm.py', stub_allperm)
        negative('0 行の report.mjs で allperm-corr.py', stub_allperm_corr)
        negative('0 行の report.mjs で r43-permute.py', stub_r43_permute)
        negative('縁が 1 本だけのグラフで allperm.py', allperm_one_edge_graph)
        negative('allperm.py に期待縁順の通り数違いを渡す', allperm_wrong_expected_permutations)
        negative('allperm.py の行から突き合わせる欄が消える', allperm_row_missing_field)
        negative('実グラフの縁を全部抜いて edge-order.py', edge_order_no_edges)
        negative('18 本とも 0 行のレポートで check-dir-rule.py --profile current',
                 dir_rule_all_empty_reports)
        negative('v1 プロファイルの比較件数を 1 本だけ減らす', dir_rule_wrong_counts)
        negative('終了 0 で JSON を書かない実行', run_json_silent)
        negative('出力先が既にある実行', run_json_stale_output)
        negative('壊れた JSON を読む実行', run_json_broken_json)
        negative('欄の無い JSON をレポートとして読む実行', run_json_wrong_shape)
        negative('battery/ から存在しない相対パス', bad_relative_path)
        negative('指紋台帳の登録を 1 件消す', fingerprint_entry_removed)
        negative('fixture の縁を全部空にする', fingerprint_content_changed)
        negative('fixture を 1 本増やす', fixture_added)
        negative('要求一覧から条件を 1 件消す', condition_removed_from_ledger)

        positive('正当な 0 行レポート 4 本は形として通る', legit_empty_reports)
        positive('期待値の合計が条件別の合計と導出で一致', coverage_current_matches)
        positive('リポジトリ根と battery/ の両方から同じ相対パス', relative_paths_from_both_cwds)
        positive('追跡下の一覧が自分の形を検査して通る', ledger_self_valid)
        positive('指紋台帳と入力が揃っている', fingerprint_ledger_clean)

        # 追跡下のファイルへの変更が残っていないか（制御が途中で落ちても戻す）
        left = git_touches()
        if left != baseline:
            failed.append('制御のあとにこの道具が触った物が変わったまま残った: '
                          + ' / '.join(sorted(set(left) ^ set(baseline))[:6]))
    finally:
        restore()
        shutil.rmtree(TMP, ignore_errors=True)

    print(f'負控制 {ran["negative"]} 件・正控制 {ran["positive"]} 件を走らせた')
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
