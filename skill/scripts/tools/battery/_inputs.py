# バッテリーの道具が共有する入力の解決と、失敗を成功にしないための実行関数
#
# 第 51 ラウンド双人レビュー（Codex `gpt-6.1-sol` と agy `gemini-4-hydrogen-high`、対象 HEAD
# `4ae3365`）で両名から同じ種類の指摘が出た。
#
#   1. 道具が入力を `out/tmp-*`（ディスク掃除の対象）から読んでおり、**消えた日は 0 件で
#      終了 0**（`check-invariants46.py` / `self-consistency.py` の `AUDIT` と `EXTRA`、
#      `baseline-v1` の 7 条件が記録する `out/tmp-r19/...` のグラフ）
#   2. 子プロセスの失敗を「値が揃っている」として成功扱いする（存在しない `report.mjs` を
#      渡すと `allperm.py` は「24 通り / 表 1 通り」、`find-splits.py` は「割れた例 0」を返す）
#
# ここで (1) リポジトリの根を辿って見つけ、(2) 掃除対象に置いていた入力を実体ごと追跡下の
# `battery/graphs/` へ移した対応表を引き、(3) **入力の欠落と子プロセスの失敗をその場で
# 終了 1** にする。各道具はこの関数を使う（検査の本体ではなく、入力の所在と終了コードを揃える）。

import json
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent


def repo_root(start=None):
    """`skill/scripts/report.mjs` を含む祖先をリポジトリの根とする。
    `__file__` からの段数ハードコードは、道具の置いてあるディレクトリを動かした日に
    別のディレクトリを根と誤認した（第 50 ラウンド実測）"""
    a = (start or HERE).resolve()
    for cand in [a] + list(a.parents):
        if (cand / 'skill' / 'scripts' / 'report.mjs').exists():
            return cand
    raise SystemExit('リポジトリの根が見つからない（skill/scripts/report.mjs を含む祖先が必要）: '
                     f'{a} から親を辿った')


# `baseline-v1` の 18 条件が `summary.graph` に記録しているのは作者環境の一時的な出力先。
# 実体を追跡下へ移いたので、記録パスが無いときはこの対応表でたどる
# （agy P2: 7 条件が `out/tmp-r19/{ri,ri0,real}/graph.json` を指し、掃除と別クローンで壊れた。
# `real` の元プロジェクト `ExampleLambdaApi` はこのリポジトリに無いので作り直せない）
RELOCATED = {
    'out/tmp-r19/ri/graph.json': 'graphs/ri.graph.json',
    'out/tmp-r19/ri0/graph.json': 'graphs/ri0.graph.json',
    'out/tmp-r19/real/graph.json': 'graphs/real.graph.json',
}


def extra_graphs(repo=None):
    """不変条件・親子整合の検査に足す実グラフ。掃除対象の `out/tmp-*` は読まない
    （第 51 ラウンド双人レビュー両名 P2）。`check-battery-inputs.py` も同じ関数を読むので、
    検査側と点検側で入力一覧が食い違わない"""
    repo = repo or repo_root()
    return [repo / 'skill' / 'tests' / 'fixtures' / 'query' / 'graph.json',
            repo / 'out' / 'demo' / 'graph.json',
            repo / 'out' / 'elsa' / 'graph.json',
            repo / 'out' / 'perf-inputs' / 'v2-big.graph.json']


def require(p, what='入力'):
    """入力が無いなら**測る前に**終了 1。無いものを無視して 0 件合格を作らない"""
    p = pathlib.Path(p)
    if not p.exists():
        raise SystemExit(
            f'{what}が無い: {p}\n'
            '  作り直し方は skill/scripts/tools/battery/README.md と '
            'skill/scripts/tools/check-battery-inputs.py に書く。'
            '無いまま続行して 0 件で合格にはしない')
    return p


def graph_path(recorded, repo=None):
    """`baseline-v1` の `summary.graph` に記録されたパスを実在する実体へ解決する"""
    repo = repo or repo_root()
    p = pathlib.Path(recorded)
    if not p.is_absolute():
        p = repo / p
    if p.exists():
        return p
    try:
        rel = p.relative_to(repo).as_posix()
    except ValueError:
        rel = None
    if rel in RELOCATED:
        return require(HERE / RELOCATED[rel], f'移設したグラフ（{rel} の実体）')
    raise SystemExit(
        f'グラフの実体が見つからない: {recorded}\n'
        '  baseline-v1 の記録パスが掃除で消えた可能性がある。移設した実体の対応表は '
        'skill/scripts/tools/battery/_inputs.py の RELOCATED')


def report_paths(d, expect=None, what='レポート'):
    """ディレクトリのレポート JSON。無い・空・expected と違う件数なら終了 1"""
    d = pathlib.Path(d)
    if not d.is_dir():
        raise SystemExit(f'{what}のディレクトリが無い: {d}')
    ps = sorted(d.glob('*.json'))
    if not ps:
        raise SystemExit(f'{what}が 0 件: {d}（空で合格にしない。再生成は '
                         f'python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs {d} --force）')
    if expect is not None and len(ps) != expect:
        raise SystemExit(f'{what}が {len(ps)} 件（{expect} 件のはず）: {d}')
    return ps


def require_script(script):
    """測る対象の report.mjs が有ることを確かめる（存在しないパスで「全件一致」を作らない）"""
    p = pathlib.Path(script)
    if not p.is_absolute():
        p = repo_root() / p
    require(p, '測る対象の report.mjs')
    return p


def run_json(script, args, out, repo=None, label=''):
    """report.mjs を走らせて `--json` のファイルを読む。失敗は即座に終了 1"""
    repo = repo or repo_root()
    cmd = ['node', str(script)] + [str(a) for a in args] + ['--json', str(out)]
    p = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f'report.mjs 失敗 (exit {p.returncode}) {label}:\n{p.stderr[-800:]}')
    return json.loads(pathlib.Path(out).read_text())
