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

import glob
import hashlib
import json
import os
import pathlib
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent

# 見張り番を**名前 1 個ずつ**消すスイッチ（`CGD_GUARD_OFF=fp-sha,fp-bytes` のように渡す）
#
# 第 55 ラウンド agy P1 の実測で、負控制の 3 件が「別の一の見張り番が先に落ちる」だけで
# 合格していた（対象の見張り番を無効化しても制御がまだ落ちる＝その見張り番を測っていない
# 空振り）。人がクローンで 18 回かけた破壊実験を `test-contract.py` の中に組み込むため、
# 各見張り番に名前を付けた。**日常の実行・レビューでの実行では付けない**
GUARD_OFF = frozenset(x.strip() for x in os.environ.get('CGD_GUARD_OFF', '').split(',')
                      if x.strip())


def guard(name):
    """その名前の見張り番が生きているか（`CGD_GUARD_OFF` に無ければ生きている）"""
    return name not in GUARD_OFF


def set_guard_off(*names):
    """プロセス内で見張り番を消す（`test-contract.py` の制御から）。前の値を返す"""
    global GUARD_OFF
    prev = GUARD_OFF
    GUARD_OFF = frozenset(names)
    return prev


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


# `baseline-v1` の 18 条件が `summary.graph` に記録しているのは**作者環境の絶対パス**
# （`<作者のリポジトリ>/out/...`）。うち 7 条件は第 19 ラウンドの一時出力先で、実体を追跡下の
# `battery/graphs/` へ移した。`real` の元プロジェクトも第 53 ラウンドで作り直せると実測した
# （`node skill/scripts/build.mjs --root repos/terraform-demos/api-lambda --out-dir <所> --name x` →
# 24 ノード / 22 縁で id・縁の集合が一致。元は https://github.com/Pondidum/Terraform-Demos.git の
# commit `050c2f3`（2020-06-10）。`repos/` は gitignore 済みなので別クローンは自前で clone する）。
# `ri` / `ri0` は第 19 ラウンドの手作り最小グラフで、追跡下のファイルそのものが正本。
# 残りの 11 条件（`demo-*` 6 と `elsa-*` 5）は `out/` の作り直せる入力を指す
# （コマンドと指紋は `input-fingerprints.json`）。
#
# 第 52 ラウンド双人レビュー（両名 P2）でこの解決順が 3 とおり壊れたと実測された:
#   1. `p.exists()` を対応表より先に通すと、同じマシンの別クローンが**元のチェックアウトの
#      一時グラフへ素通し**する（追跡下の `graphs/` が一度も使われない）
#   2. `p.relative_to(repo)` は作者の根が違うと `ValueError` になり、対応表に届かずに
#      **全 18 条件が失敗**する
#   3. macOS の `/tmp` → `/private/tmp` のような解決差でも同じ `ValueError`
# そこで **根のプレフィックスを捨てて `out/...` の相対形**を取り出し、対応表を先に引く
# （移設済みは元の残骸が生きていても必ず追跡下の実体を使う）

RELOCATED = {
    'out/tmp-r19/ri/graph.json': 'graphs/ri.graph.json',
    'out/tmp-r19/ri0/graph.json': 'graphs/ri0.graph.json',
    'out/tmp-r19/real/graph.json': 'graphs/real.graph.json',
}

# 無いときに「どう作るか」を告げる（黙って件数を減らさないための案内）
# コマンドは第 53 ラウンドで**実際に走らせて指紋一致を実測**したもの（`input-fingerprints.json`）。
# 前にここに書いていた手順は `--exclude` と `--root` が違って、走らせても別のグラフになった
# （第 52 ラウンド Astra 裁定 3「省略のない生成コマンドを記録し、同じ入力を作り直せることを
# 示せ」への対応）
REGEN = {
    'out/demo/graph.json': 'node skill/scripts/build.mjs --root demo/orders-api-lambda --out-dir out/demo '
                           '--name demo --annotation skill/examples/annotations.orders-api.json '
                           '--annotation skill/examples/annotations.storage.json',
    'out/elsa/graph.json': 'git clone https://github.com/elsa-workflows/elsa-core.git repos/elsa-core && '
                           'git -C repos/elsa-core checkout b74bc3c7740929106d52807d1d89f88a72eed8a7 && '
                           'export DOTNET_ROOT=$HOME/.dotnet PATH="$HOME/.dotnet:$PATH" '
                           'CGD_BIN=$PWD/skill/analyzer/bin/Release/net9.0/cgd && '
                           'node skill/scripts/build.mjs --root repos/elsa-core --out-dir out/elsa '
                           '--name elsa-core --exclude test,docs',
    'out/perf-inputs/v2-big.graph.json': 'python3 skill/scripts/tools/make-v2-graph.py '
                                         'out/perf-inputs/v2-big.graph.json',
}


def rel_of_recorded(recorded, repo=None):
    """記録されたパスから**今のリポジトリでの相対形**を取り出す。
    第 53 ラウンド双人レビュー（Codex P2）で、リポジトリの親ディレクトリが `out` という
    名前だと**最初の** `out` で切れて別物になるのを実測された（`/tmp/out/clone/out/demo/…` →
    `out/clone/out/demo/…`）。なので順序を決める:

      1. 今のリポジトリの根が前に付いているなら、それ以降（今回の生成物が確実に正しくなる）
      2. そうでなければ**最後**の `out` からの形（作者環境の歴史的パス・別の場所のクローン）
    """
    parts = [x for x in str(recorded).replace('\\', '/').split('/') if x]
    root = [x for x in str(pathlib.Path(repo or repo_root()).resolve()).split('/') if x]
    if parts[:len(root)] == root:
        return '/'.join(parts[len(root):]) or None
    if 'out' in parts:
        return '/'.join(parts[len(parts) - 1 - parts[::-1].index('out'):])
    return None


def graph_path(recorded, repo=None):
    """`baseline-v1` の `summary.graph` に記録されたパスを**今のリポジトリの実体**へ解決する。
    移設済みは対応表を先に引く（元の一時残骸が生きていても使わない）。
    解けない・実体が無いなら**測る前に**終了 1（0 件合格にしない）"""
    repo = pathlib.Path(repo or repo_root())
    rel = rel_of_recorded(recorded, repo)
    if rel in RELOCATED:
        return require(HERE / RELOCATED[rel], f'追跡下へ移設したグラフ（{rel} の実体）')
    if rel is None:
        # `out/` を含まない記録は作者環境の絶対パスのまま。在ることを確かめてから返す
        p = pathlib.Path(recorded)
        return require(p if p.is_absolute() else repo / p, 'グラフ')
    p = repo / rel
    if p.exists():
        return p
    hint = REGEN.get(rel)
    raise SystemExit(
        f'グラフの実体が見つからない: {p}\n'
        f'  （記録されたパス: {recorded} → 今のリポジトリでの相対形 {rel}）\n'
        + (f'  作り直し: {hint}\n' if hint else
           '  対応表は skill/scripts/tools/battery/_inputs.py の RELOCATED。\n')
        + '  無いまま続行して条件数を減らした合格はしない（第 51 / 52 ラウンド双人レビュー）')


def extra_graphs(repo=None):
    """不変条件・親子整合の検査に足す実グラフ。掃除対象の `out/tmp-*` は読まない
    （第 51 ラウンド双人レビュー両名 P2）。`check-battery-inputs.py` も同じ関数を読むので、
    検査側と点検側で入力一覧が食い違わない"""
    repo = repo or repo_root()
    return [repo / 'skill' / 'tests' / 'fixtures' / 'query' / 'graph.json',
            repo / 'out' / 'demo' / 'graph.json',
            repo / 'out' / 'elsa' / 'graph.json',
            repo / 'out' / 'perf-inputs' / 'v2-big.graph.json']


def require(p, what='入力', want_file=False):
    """入力が無いなら**測る前に**終了 1。無いものを無視して 0 件合格を作らない。
    相対パスは**リポジトリの根**から引く（第 53 ラウンド agy P2: v1diff をサブディレクトリから
    実行すると `skill/scripts/tools/battery/baseline-v1` を見失った。手順書の書き方は
    リポジトリ相対なので、道具の作業ディレクトリに依存しないほうが正しい）"""
    p = pathlib.Path(p)
    if not p.is_absolute():
        p = repo_root() / p
    if not p.exists():
        raise SystemExit(
            f'{what}が無い: {p}\n'
            '  作り直し方は skill/scripts/tools/battery/README.md と '
            'skill/scripts/tools/check-battery-inputs.py に書く。'
            '無いまま続行して 0 件で合格にはしない')
    if want_file and p.is_dir():
        # ディレクトリを `read_text()` して IsADirectoryError の山にするより、
        # 「何を渡すべきか」を出して終了 1 のほうが次の一手が決まる（第 54 ラウンド実測）
        raise SystemExit(f'{what}はファイル 1 本を渡す（ディレクトリを渡した）: {p}')
    return p


def report_paths(d, expect=None, what='レポート'):
    """ディレクトリのレポート JSON。無い・空・expected と違う件数なら終了 1"""
    d = pathlib.Path(d)
    if not d.is_dir():
        raise SystemExit(f'{what}のディレクトリが無い: {d}')
    ps = sorted(d.glob('*.json'))
    if guard('path-empty') and not ps:
        raise SystemExit(f'{what}が 0 件: {d}（空で合格にしない。再生成は '
                         f'python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs {d} --force）')
    if guard('path-count') and expect is not None and len(ps) != expect:
        raise SystemExit(f'{what}が {len(ps)} 件（{expect} 件のはず）: {d}')
    return ps


def fingerprint(graph):
    """`graph.json` の**構造指紋**。`generatedAt` と `rootPath` は機械と実行のたびに違うので
    バイト一致は使えない。ノード id の集合と縁 `source|kind|target` の集合のハッシュで
    「中身が同じグラフか」を見る（第 52 ラウンド Astra 裁定 3: 固定入力の再現手順には
    ハッシュと元ソースの版がいる）"""
    d = json.loads(pathlib.Path(graph).read_text(encoding='utf-8'))
    ids = '\n'.join(sorted(str(n.get('id')) for n in d.get('nodes', [])))
    rels = '\n'.join(sorted(f"{e.get('source')}|{e.get('kind')}|{e.get('target')}"
                            for e in d.get('edges', [])))
    return {'nodes': len(d.get('nodes', [])), 'edges': len(d.get('edges', [])),
            'ids': hashlib.sha256(ids.encode('utf-8')).hexdigest(),
            'rels': hashlib.sha256(rels.encode('utf-8')).hexdigest()}


def check_fingerprints(repo=None):
    """`input-fingerprints.json` に固定した out/ 入力の指紋を確かめ、食い違いを**文字列の一覧**で返す。
    入力が無い・読みけないも不良として返す（点検側が他の項目も続けて見られるようにする。
    第 53 ラウンド agy P2）。黙って「一致」にしない"""
    repo = pathlib.Path(repo or repo_root())
    spec_path = require(HERE / 'input-fingerprints.json', '入力の構造指紋（input-fingerprints.json）')
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    bad = []
    for rel, want in spec['inputs'].items():
        p = repo / rel
        if not p.exists():
            # 第 53 ラウンド agy P2: ここで `require` して SystemExit すると、入力点検が
            # 「無い物の一覧をまとめて出す」前に止まり、`out/wt-head` の作り直し案内へ
            # 届かなかった。欠落は不良として数え、他の点検を続けさせる
            bad.append(f'{rel} が無い（指紋 {want["nodes"]} ノードの基準がある入力）。'
                       f'作り直し: {REGEN.get(rel, "不明")}')
            continue
        try:
            got = fingerprint(p)
        except (OSError, ValueError, KeyError) as e:
            bad.append(f'{rel} が読めない（{e}）')
            continue
        if not guard('fp-structural'):
            continue
        for k in ('nodes', 'edges', 'ids', 'rels'):
            if got[k] != want[k]:
                bad.append(f'{rel} の {k} が基準と違う（基準 {want[k]} / 今 {got[k]}。'
                           '作り直した graphs が元と違う可能性。基準の更新は人の判断）')
    return bad


def resolve_cli_path(value, *, default=None):
    """道具の呼び口で相対パスを解決する基準（第 55 ラウンド Astra 裁定 問 5 の案 1）

    * 未指定（既定）: リポジトリの根から `default` を読む。手順書はリポジトリ相対で
      書かれているので、どのディレクトリから走っても既定は同じ物を指す
    * 明示された相対値・環境変数: 実行時の cwd から解決（通常のコマンドラインの慣習。
      `battery/` から `../../..` 相当を渡す書き方もこれで通る）
    * 絶対値: そのまま

    存在する物で解決先を変える方式は、同じコマンドが別の対象を測る原因になるため採らない。
    ここで一度絶対パスへ直して `require()` / `report_paths()` / 子プロセスへ渡す
    （台帳の中のパスはコマンドライン引数ではないので、常にリポジトリ基準の `require()` を使う）"""
    if value is None:
        if default is None:
            raise SystemExit('パスを渡す（この検査に既定の置き場所はない）')
        return (repo_root() / default).resolve()
    p = pathlib.Path(str(value)).expanduser()
    got = p if p.is_absolute() else pathlib.Path.cwd() / p
    # `CGD_GUARD_OFF=path-cwd-only` は**第 54 ラウンドまでの古い挙動**（cwd に無い物を
    # リポジトリ根で探す）を戻す。`test-contract.py` が「その挙動へ戻した日にこの制御が
    # 検出できるか」を確かめるためだけで、通常の実行では入れない
    if not guard('path-cwd-only') and not got.exists():
        alt = repo_root() / str(value)
        if alt.exists():
            return alt.resolve()
    return got.resolve()


def require_script(script=None, default='skill/scripts/report.mjs'):
    """測る対象の report.mjs が有ることを確かめる（存在しないパスで「全件一致」を作らない）。
    第 1 引数で渡された物は cwd 基準、既定はリポジトリ根基準（`resolve_cli_path` を参照）"""
    p = resolve_cli_path(script, default=default)
    require(p, '測る対象の report.mjs', want_file=True)
    return p


# レポート JSON に揃っていなければならない欄（`skill/scripts/report.mjs` の出力契約）
REPORT_BUCKETS = ('external.in', 'external.out', 'entries.in', 'entries.out',
                  'artifacts.in', 'artifacts.out', 'sameApi', 'siblingEndpoints', 'wiring')


def validate_report(doc, label):
    """読んだ JSON が**レポートの形**をしているか（第 54 ラウンド双人レビュー agy 指摘 2）

    欄が欠けた JSON（別の道具の出力・途中で壊れた出力）を渡すと、行を 1 本も数えずに
    「違反 0 / 完全一致」が出た。行が 0 本自体は正当なレポートもある（`demo-readme.json` など
    4 本）ので、ここで見るのは**形**だけ。行数は `require_comparison_rows` が見る"""
    if not isinstance(doc, dict):
        fail(f'{label} がオブジェクトではない（{type(doc).__name__}。レポート JSON の形ではない）')
    missing = []
    for bucket in REPORT_BUCKETS:
        here = doc
        for part in bucket.split('.'):
            here = here.get(part) if isinstance(here, dict) else None
        if not isinstance(here, list):
            missing.append(bucket)
    if missing:
        fail(f'{label} にレポートの欄が揃っていない: {", ".join(missing)}'
             '（9 欄すべてが配列であること。別の道具の出力や途中で切れた出力を'
             'レポートとして数えない）')
    if not isinstance(doc.get('summary'), dict):
        fail(f'{label} に summary が無い（測定条件の記録が無い JSON は比較できない）')
    return doc


def run_json(script, args, out, repo=None, label='', expect_report=True):
    """report.mjs を走らせて `--json` のファイルを読む。失敗・空・別の形は即座に終了 1

    出力先がもう有る日は止める。前回の実行の JSON を今回の結果として読むと
    「走らせていないのに合格」が起きる"""
    repo = repo or repo_root()
    out = pathlib.Path(out)
    if guard('out-exists') and out.exists():
        fail(f'{label}: 出力先がもう有る（{out}）。実行ごとに新しい名前を使う'
             '（一時ディレクトリは実行のたびに作り直している）')
    cmd = ['node', str(script)] + [str(a) for a in args] + ['--json', str(out)]
    p = subprocess.run(cmd, cwd=str(repo), capture_output=True, text=True)
    if guard('child-fail') and p.returncode != 0:
        # 第 56 ラウンド agy P2-4: `via-cycle.py` は子失敗時に標準出力の末尾も出していた。
        # `run_json` 寄せでそれが消えたので、here にまとめて出す（道具ごとに戻さない）
        raise SystemExit(f'report.mjs 失敗 (exit {p.returncode}) {label}:\n'
                         f'標準エラーの末尾:\n{p.stderr[-800:]}'
                         + (f'\n標準出力の末尾:\n{p.stdout[-400:]}' if p.stdout.strip() else ''))
    if guard('json-missing') and not out.exists():
        raise SystemExit(f'report.mjs は終了 0 なのに JSON を書いていない: {out}（{label}）'
                         f'\n標準出力の末尾: {p.stdout[-300:]}')
    if not out.exists():
        raise SystemExit(f'{label}: JSON の出力先が無いので結果を読めない（{out}）')
    raw = out.read_text(encoding='utf-8')
    if guard('json-empty') and not raw.strip():
        raise SystemExit(f'report.mjs の JSON が空（{out}・{label}）。空の出力を'
                         '「行が無いレポート」として合格にしない')
    try:
        doc = json.loads(raw)
    except ValueError as e:
        if guard('json-parse'):
            raise SystemExit(f'report.mjs の JSON が読めない: {out}（{label}。{e}）: {raw[:200]}')
        doc = {}
    if expect_report and guard('report-shape'):
        validate_report(doc, f'{label} の JSON')
    return doc


PERM_BUCKETS = ('external', 'entries', 'artifacts')
PERM_SIDES = ('in', 'out')


def projection_rows(doc, label, fields):
    """`allperm` 二種が突き合わせる 6 欄を読める形で返し、形が違えばここで終わらせる

    各道具が**何を突き合わせているか**を自分で宣言する（Astra 裁定 問 4）。
    `report.mjs` の出力契約が変わった日に `KeyError` の Traceback で死ぬと何が壊れたか
    読めないので、欄が list で無い日・行に欄が無い日を名前で指摘して終了 1 にする。
    ここは**欄の数**を見張り、行の件数は `require_comparison_rows()` が見る"""
    if not isinstance(doc, dict):
        raise SystemExit(f'{label}: JSON の最上位が object ではない（{type(doc).__name__}）')
    bad = []
    for b in PERM_BUCKETS:
        box = doc.get(b)
        if not isinstance(box, dict):
            bad.append(f'{b} が object ではない（{type(box).__name__}）')
            continue
        for side in PERM_SIDES:
            if not isinstance(box.get(side), list):
                bad.append(f'{b}.{side} が list ではない（{type(box.get(side)).__name__}）')
    if guard('proj-buckets') and bad:
        raise SystemExit(f'{label}: 突き合わせる 6 欄'
                         f'（{PERM_BUCKETS[0]}.{PERM_SIDES[0]} など {" x ".join((str(len(PERM_BUCKETS)), str(len(PERM_SIDES))))} = 6）'
                         'が契約どおりに読めない: ' + '、'.join(bad))
    rows = [r for b in PERM_BUCKETS for side in PERM_SIDES for r in doc[b][side]]
    for r in rows:
        if not isinstance(r, dict):
            raise SystemExit(f'{label}: 行が object ではない（{type(r).__name__}）')
        gone = [f for f in fields if f not in r] if guard('proj-fields') else []
        if gone:
            raise SystemExit(f'{label}: 行に欄が無い: {"、".join(gone)}'
                             '（この道具はその欄を突き合わせている。出力契約が変わったら'
                             '道具も直して起動条件の一覧を作り直す）')
    return rows


def permutation_guards(n_edges, ran, expected, label):
    """縁順の比較が**実際に起きる件数**になっているかを確かめる（Astra 裁定 問 4）

    縁が 1 本のグラフでは並び替えは 1 とおりしか無く「全通り一致」が空振りになる。
    `ran=None` は**走る前**の呼び出し（順列を組み立てる前に縁の本数と期待通り数だけ見る）"""
    if guard('perm-edges') and n_edges < 2:
        raise SystemExit(f'{label}: 縁が {n_edges} 本しかないグラフでは縁順を変えても比較に'
                         'ならない（並び替えても 1 とおり）。縁が 2 本以上ある固定グラフを渡す')
    want = 1
    for k in range(2, n_edges + 1):
        want *= k
    if ran is None:
        if guard('perm-count') and expected is not None and expected != want:
            raise SystemExit(f'{label}: 期待した縁順の通り数 {expected} 件は {n_edges} 本の順列'
                             f' {want} 通りと違う（走る前に分かる食い違い）')
        return
    if guard('perm-count') and ran != want:
        raise SystemExit(f'{label}: 縁順 {ran} 通りは {n_edges} 本の順列 {want} 通りと違う'
                         '（順列を組み立てる側が壊れている）')
    if guard('perm-count') and expected is not None and ran != expected:
        raise SystemExit(f'{label}: 期待した縁順の通り数 {expected} 件に対して {ran} 件走った'
                         f'（グラフ {n_edges} 本の順列は {want} 通り）')


def require_sampled_runs(n_ran, label, cap=None):
    """間引いたあと**1 とおりしか走らない**比較を止める（第 56 ラウンド Codex P2-2）

    順列を上限で間引くと 1 とおりだけ走ることがある。1 とおりの比較は「完全一致」と出て
    も何も言わない。実測（第 56 ラウンド Codex）: 縁順で出力が変わる stub に対して
    `allperm-full.py <stub> min-2.json 1` は「縁順 1 通り / JSON 1 通り / 判定: JSON 完全一致」
    で終了 0、同じ stub で上限 24 なら「JSON 4 通り」で終了 1"""
    if guard('perm-cap') and n_ran < 2:
        raise SystemExit(
            f'{label}: 実際に走らせた縁順が {n_ran} とおりしかない'
            + (f'（順列上限 {cap} で間引かれた）。' if cap is not None else '。')
            + '1 とおりの比較は「完全一致」になっても何も言わないので測ったことにならない。'
              '順列上限は 2 以上を渡してください')


def require_comparison_rows(rows, label, what='表示行'):
    """行数 0 を「違反 0」「1 通りに一致」と数えない（第 54 ラウンド双人レビュー agy 指摘 1・2）

    何も行を出さない `report.mjs`（壊れた物・中立 3 欄に全行が落ちる物）を渡すと、順列検査は
    空と空が一致して「1 通り」、連鎖検査は「違反 0」になり、**測る物が無い日が合格**した。
    比較する行が 0 件の日は、合否を判定する材料が無いので終了 1 にする"""
    n = len(rows)
    if guard('rows-zero') and n == 0:
        raise SystemExit(
            f'{label}: {what}が 0 件。比較する行が無い日は「違反 0」「1 通りに一致」になるため'
            '合格にしない（測る対象が出る条件で走らせているか、`report.mjs` が行を出しているか'
            'を先に確かめる）')
    return n


# ---- 起動条件の正本（第 53 ラウンド双人レビュー両名 P2。Astra 裁定 2 の実装） --------------
#
# 以前は `check-invariants46.py` と `self-consistency.py` がそれぞれ fixture を glob で集め、
# 「10 本以上」「200 条件以上」という**件数の見張り番**だけで走らせていた。fixture を 2 本
# 消した日（19 → 17 本、219 → 201 条件）は**両方の検査が終了 0**（第 53 ラウンド両名が別クローンで
# 実測）。件数の下限では「一部だけ減る」を捕まえられないので、**追跡下の要求一覧との集合比較**へ移す。
#   * `required-checks.json` が必須の fixture と起動条件の一覧（`--emit-required` で人が作る）
#   * ここが起動条件を組み立て、検査は同じ一覧を読む（組み方が 2 ところに分かれていたのも直す）
#   * 一覧に無い条件は走らせない。有る条件が消えた日・増えた日は**測る前に終了 1**
FIXTURE_GLOB = 'skill/tests/fixtures/ImpactFacts/*.graph.json'
REQUIRED = HERE / 'required-checks.json'


def required_spec(repo=None):
    """起動条件の要求一覧（追跡下の JSON）。無い日は作り直し手順付きで終了 1"""
    if not REQUIRED.exists():
        raise SystemExit(
            f'起動条件の要求一覧が無い: {REQUIRED}\n'
            '  作り直し: python3 skill/scripts/tools/battery/emit-required.py '
            'skill/scripts/tools/battery/required-checks.json\n'
            '  （書き出した一覧を人がレビューしてコミットする。追跡下のファイルなので '
            'git checkout -- でも戻せる）')
    return json.loads(REQUIRED.read_text(encoding='utf-8'))


def fail(msg):
    """検査の失敗をひとか所に（診断は標準エラーへ出て終了 1。`SystemExit('文字列')` は exit 1）"""
    raise SystemExit(msg)


# 起動の種類と、その引数配列の形（要求一覧が「もっともらしいが実行できない条件」を
# 通さないために見る。第 55 ラウンド Astra 裁定 問 3）
KINDS = ('from', 'api', 'changed', 'audit-full')


def _flag_pairs(args, flag):
    """`--flag 値 --flag 値 …` が並び続けた物なら値の列を返す。壊れていれば None"""
    vals = []
    i = 0
    while i < len(args):
        if args[i] != flag or i + 1 >= len(args):
            return None
        vals.append(args[i + 1])
        i += 2
    return vals


def spec_shape_errors(kind, args):
    """`kind` に対して `args` の形が正しいか（実行できない条件を要求一覧に置かない）"""
    if kind not in KINDS:
        return [f'kind が値域外: {kind}（{" / ".join(KINDS)} のどれか）']
    if kind == 'from':
        vals = _flag_pairs(args, '--from')
        return [] if vals else ['from 条件は `--from <id>` の並びでなければならない']
    if kind == 'api':
        return [] if (len(args) == 2 and args[0] == '--api' and args[1]) else \
            ['api 条件は `--api <endpoint>` 2 個でなければならない']
    if kind == 'changed':
        if len(args) != 2 or args[0] != '--changed' or not str(args[1]).startswith('@'):
            return ['changed 条件は `--changed @a,b` の形（一覧は文字列で持ち、比較できるようにする）']
        body = str(args[1])[1:]
        if '\n' in body:
            return ['changed の一覧に改行が入っている（`@a,b` 表記では区別できない。区切りの無い名前に直す）']
        return []
    # audit-full: `--hops n --wiring-hops n --limit n` のうしろに `--from <id>` が並ぶ
    # （起点 0 個を許す: v1 基準の 18 条件のうち `demo-readme.json` と `real-tf.json` は
    # 記録の `starts` が空で、組み直すと `--from` が付かない。この 2 本は 0 行レポートとして
    # `expectations.dirRule` 側で押さえる。Astra 裁定 問 4 が「正当な 0 行レポート 4 本」と
    # 数えた物とかぶる）
    if len(args) < 6 or args[0] != '--hops' or args[2] != '--wiring-hops' or args[4] != '--limit':
        return ['audit-full 条件は `--hops n --wiring-hops n --limit n` で始まらなければならない']
    for k in (1, 3, 5):
        try:
            int(args[k])
        except ValueError:
            return [f'audit-full 条件の数値が読めない: {args[k]}']
    tail = args[6:]
    if tail and _flag_pairs(tail, '--from') is None:
        return ['audit-full 条件の起点が `--from <id>` の並びになっていない'
                f'（6 個目以降: {" ".join(tail[:6])}）']
    return []


# ---- 測った件数の期待値（第 55 ラウンド Astra 裁定 問 2） --------------------------------
#
# 入力指紋は「入力が変わった日」を止めるが、「入力はそのままで検査範囲が縮んだ日」を
# 止めてくれない。fixture の縁を空にした日は要求一覧との集合比較も通り、不変条件は
# 219 条件を走らせても検査する行が減っていた（第 54 ラウンド Codex 指摘 1 の実測）。
# そこで**実際に走査した行数・比較した親子数**を条件別に正準化して追跡下に置く。
# 合計は条件別から導出し（合計だけでは条件間の増減が相殺する）、測った後に突き合わせて
# 違えば終了 1。件数一致は内容一致の代用にはしないので、不変条件検査と
# `v1diff.py --verify-known` はそのまま残す
COVERAGE_KINDS = ('invariantRows', 'parentChild')


def coverage_shape_errors(exp):
    """expectations の形を検査する（作り直した一覧が黙って空にならないようにする）"""
    bad = []
    if not guard('cov-shape'):
        return []
    if not isinstance(exp, dict):
        return ['expectations がオブジェクトではない']
    for kind in COVERAGE_KINDS:
        e = exp.get(kind)
        if not isinstance(e, dict):
            bad.append(f'expectations.{kind} が無い（測った件数を条件別に置く）')
            continue
        by = e.get('byCondition')
        if not isinstance(by, dict) or not by:
            bad.append(f'expectations.{kind}.byCondition が空（条件別の件数が正本。合計は導出）')
            continue
        if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in by.values()):
            bad.append(f'expectations.{kind}.byCondition に 0 以上の整数でない値がある')
        if e.get('total') != sum(by.values()):
            bad.append(f'expectations.{kind}.total が条件別の合計と違う'
                       f'（記録 {e.get("total")} / 合計 {sum(by.values())}。合計は導出する物）')
        if e.get('conditions') != len(by):
            bad.append(f'expectations.{kind}.conditions が件数と違う'
                       f'（記録 {e.get("conditions")} / 件数 {len(by)}）')
    d = exp.get('directionless')
    if not isinstance(d, dict) or any(not isinstance(d.get(k), int) for k in
                                      ('rows', 'sameApi', 'wiring', 'siblingEndpoints', 'primary')):
        bad.append('expectations.directionless に rows / sameApi / wiring / siblingEndpoints / '
                   'primary の件数が要る（向き none の数えを裁定のハードコードから離す）')
    dr = exp.get('dirRule')
    if not isinstance(dr, dict):
        bad.append('expectations.dirRule が無い（`check-dir-rule.py --profile current|v1` が使う）')
    else:
        for prof in ('current', 'v1'):
            e = dr.get(prof)
            if not isinstance(e, dict):
                bad.append(f'expectations.dirRule.{prof} が無い')
                continue
            for k in ('agree', 'bad', 'loose', 'nopath', 'badDomain'):
                v = e.get(k)
                if isinstance(v, bool) or not isinstance(v, int):
                    bad.append(f'expectations.dirRule.{prof}.{k} が整数ではない（true/false は数にしない）')
                elif v < 0:
                    # 第 56 ラウンド agy P2-2: ここは「整数かどうか」だけを見ていた。`agree` を
                    # 増やして `bad` を引けば合計は同じまま、現実にあり得ない件数で通れた
                    bad.append(f'expectations.dirRule.{prof}.{k} が負の整数 {v}'
                               '（同じ行を 2 度数えたり引いた形。件数は 0 以上）')
            by = e.get('byReport')
            if not isinstance(by, dict) or not by:
                bad.append(f'expectations.dirRule.{prof}.byReport が空（レポート別の比較件数が正本）')
                continue
            if any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in by.values()):
                bad.append(f'expectations.dirRule.{prof}.byReport に 0 以上の整数でない値がある')
                continue
            # 第 56 ラウンド agy P2: 向き別の合計とレポート別の合計は**同じ行を数え直した物**
            # なので必ず一致する。片方だけいじった一覧（比較件数を減らす細工）をここで落とす
            s = sum(by.values())
            d = sum(e.get(k, 0) for k in ('agree', 'bad', 'loose', 'nopath', 'badDomain'))
            if s != d:
                bad.append(f'expectations.dirRule.{prof}.byReport の合計 {s} 件が向き別の合計 '
                           f'{d} 件と違う（同じ行を別々に数えた物。片方だけ変えた一覧は認めない）')
    return bad


def expectations(repo=None):
    """追跡下の期待値（要求一覧の中に入れて別の正本を増やさない。Astra 裁定 問 6）"""
    exp = required_spec(repo).get('expectations')
    if not isinstance(exp, dict):
        fail('要求一覧に expectations が無い（要求一覧の作り直し: '
             f'python3 skill/scripts/tools/battery/emit-required.py {REQUIRED}）')
    return exp


def expected_direction_diffs(repo=None):
    """既知差分（`known-v1-diffs.json`）から **向き が変わった行差分**を導く

    v1 基準との照合は 55 件不一致が正しい。新しい一覧を増やさないため、人が承認済みの
    行差分 58 件の組（`[欄, 向き, 階層, 縁数, 縁]`）のうち `向き` が違う 55 件を here で
    導出して突き合わせる（第 55 ラウンド Astra 裁定 問 4）"""
    p = require(HERE / 'known-v1-diffs.json', '既知差分の一覧', want_file=True)
    doc = json.loads(p.read_text(encoding='utf-8'))
    out = set()
    for i, d in enumerate(doc['diffs']):
        if d.get('kind') != 'row':
            continue
        old, new = d.get('old') or [], d.get('new') or []
        if len(old) < 2 or len(new) < 2:
            raise SystemExit(f'既知差分の行差分 {i} 件目の組が短い（欄と向きを読む）: {d}')
        if old[1] == new[1]:
            continue
        out.add((d['cond'], d['id'], old[1], new[1]))
    if guard('v1-derivation') and len(out) != 55:
        raise SystemExit(f'既知差分から導いた 向き の差分が {len(out)} 件（55 件のはず。'
                         '既知差分の作り直しは人の判断。`v1diff.py --emit-known` で候補が出る）')
    return out


# ---- 入力の中身の指紋（第 54 ラウンド双人レビュー Codex 指摘 1。Astra 裁定 問 1） ----------
#
# `input-fingerprints.json` の構造指紋（ノード id の集合と縁 `source|kind|target` の集合）
# だけでは、fixture の `edges` を全部空にしても、起点でないノードを 1 つ rename しても、
# `parent` / `kind` / `metadata` / 縁の `provenance` を壊しても**指紋は同じ**だった
# （第 54 ラウンド Codex が別クローンで実測: 入力点検・不変条件・親子整合がすべて終了 0）。
# そこで**中身その物**の SHA-256 を持つ。JSON はキー順だけ正規化し、配列順・重複・
# 全フィールドを保つ（実行ごとに違うのはトップレベルの `generatedAt` / `rootPath` だけと
# 確認できているので、そこだけ除く。`root` / `roots` は残す）。前の版の `report.mjs` と
# v1 の記録は**バイト列**で固定する（人が方針を変えないと更新しない）
VOLATILE_TOP = ('generatedAt', 'rootPath')
CONTENTS = 'contents'

# （glob またはファイル、指紋の型、何の入力か）
CONTENT_SCOPES = (
    ('skill/tests/fixtures/ImpactFacts/*.graph.json', 'any', '回帰検査の fixture'),
    ('skill/tests/fixtures/query/graph.json', 'any', 'query.mjs のテストが読むグラフ'),
    ('skill/scripts/tools/battery/graphs/*.json', 'any', 'v1 基準の条件が読む検査のグラフ'),
    ('skill/scripts/tools/battery/min-*.json', 'any', '縁順検査のケース（extra を含むケース全体）'),
    ('skill/scripts/tools/battery/r42-calls-*.json', 'any', '入れ替え検査のケース'),
    ('skill/scripts/tools/battery/r43-before.mjs', 'bytes', '固定した前の版の report.mjs'),
    ('skill/scripts/tools/battery/baseline-v1/*.json', 'bytes', 'v1 の出力契約の記録（人が差し替えない）'),
    ('out/perf-inputs/elsa-50.txt', 'bytes', '変更一覧の固定入力'),
    ('out/demo/graph.json', 'any', '実測の固定入力（demo）'),
    ('out/elsa/graph.json', 'any', '実測の固定入力（elsa-core）'),
    ('out/perf-inputs/v2-big.graph.json', 'any', '性能ゲートの固定入力'),
    ('skill/examples/annotations.orders-api.json', 'any', 'demo の再生成が読む注釈'),
    ('skill/examples/annotations.storage.json', 'any', 'demo の再生成が読む注釈（保存先）'),
)


def content_fingerprint(p, mode=None):
    """ファイルの中身の指紋。`(型, sha256, バイト数)` を返す

    `mode='bytes'` を明示した物は JSON に読めても**バイト列**で見る（v1 の記録と前の版の
    `report.mjs` は人が方針を変えないと更新しないので、キー順の並び替えのような変化も
    見つける）。それ以外では JSON に読める物だけキー順を正規化して全文を見る
    （配列順と重複は**意味があるので保つ**。縁の並び順その物が検査の対象だから集合にしない）"""
    path = pathlib.Path(p)
    raw = path.read_bytes()
    if mode == 'bytes':
        return 'bytes', hashlib.sha256(raw).hexdigest(), len(raw)
    try:
        doc = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError):
        return 'bytes', hashlib.sha256(raw).hexdigest(), len(raw)
    if isinstance(doc, dict):
        doc = {k: v for k, v in doc.items() if k not in VOLATILE_TOP}
    body = json.dumps(doc, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    enc = body.encode('utf-8')
    # 第 56 ラウンド Codex P2: ここが生バイト長を返すと、`rootPath` を除いたハッシュが
    # 同じでも「パスの長さが違うクローン」で入力が通らなくなった（除いた値を別で戻す）。
    # JSON モードのバイト数は**正規化後**の長さにする
    return 'json', hashlib.sha256(enc).hexdigest(), len(enc)


def content_scope(repo=None):
    """指紋台帳に載っていなければならない入力ファイルの一覧

    `(相対パス, 指紋の型, 何の入力か)` の組を並べた物返す。glob の実体をここで広げるので、
    台帳との双方向比較と同じ一覧を見る"""
    repo = pathlib.Path(repo or repo_root())
    out = []
    for pat, mode, what in CONTENT_SCOPES:
        hits = sorted(glob.glob(str(repo / pat)))
        if not hits:
            raise SystemExit(f'指紋で固定する入力が見つからない: {pat}'
                             f'（{what}。欠けた日の作り直しは skill/scripts/tools/battery/'
                             'README.md と check-battery-inputs.py に書く）')
        for h in hits:
            rel = str(pathlib.Path(h).resolve().relative_to(repo.resolve())).replace('\\', '/')
            out.append((rel, mode, what))
    return sorted(out)


def require_fingerprints(repo=None):
    """中身の指紋を台帳と突き合わせ、食い違いを**全部**返す（終了は呼び手がまとめて決める）

    台帳に無い入力がある日（新しい fixture を増えたのに登録していない）も、台帳に有る物が
    消えた日も、中身が変わった日も、ここで終わる。fixture は「glob の実体」「要求一覧の
    fixtures」「指紋台帳」の三者一致が要る（Astra 裁定 問 1: 2 ファイルの更新忘れを
    同期検査の失敗に変える）"""
    repo = pathlib.Path(repo or repo_root())
    spec_path = require(HERE / 'input-fingerprints.json', '入力の指紋台帳', want_file=True)
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    reg = spec.get(CONTENTS)
    if not isinstance(reg, dict) or not reg:
        return [f'{spec_path.name} に {CONTENTS} が無い（中身の指紋の登録漏れ。'
                '作り直し: python3 skill/scripts/tools/check-battery-inputs.py '
                '--emit skill/scripts/tools/battery/input-fingerprints.json）']
    bad = []
    scope = {}
    for rel, mode, what in content_scope(repo):
        scope[rel] = (mode, what)
    if guard('fp-unregistered'):
        for rel in sorted(set(scope) - set(reg)):
            bad.append(f'{scope[rel][1]}が指紋台帳に未登録: {rel}（`--emit` で候補を書き出して人がレビュー）')
    if guard('fp-ledger-extra'):
        for rel in sorted(set(reg) - set(scope)):
            bad.append(f'指紋台帳に有るが入力の一覧に無い: {rel}（台帳の書き直し、または'
                       ' CONTENT_SCOPES へ登録し直す）')
    for rel in sorted(set(scope) & set(reg)):
        mode, what = scope[rel]
        p = repo / rel
        if not p.exists():
            bad.append(f'{what}が無い: {rel}')
            continue
        try:
            got_mode, got_sha, got_bytes = content_fingerprint(p, mode)
        except OSError as e:
            bad.append(f'{what}が読めない: {rel}（{e.strerror}）')
            continue
        want = reg[rel]
        if guard('fp-sha') and want.get('sha') != got_sha:
            bad.append(f'{what}の中身が基準と違う: {rel}（基準 {str(want.get("sha"))[:12]}… / '
                       f'今 {got_sha[:12]}…）。入力の差し替えは人の判断なので書き換えない。'
                       '追跡下の物なら `git checkout -- {rel}`、out/ の物なら台帳に載る'
                       '生成コマンドで作り直す'.replace('{rel}', rel))
        elif guard('fp-bytes') and want.get('bytes') != got_bytes:
            bad.append(f'{what}のバイト数が基準と違う: {rel}（基準 {want.get("bytes")} / 今 {got_bytes}）')
        elif guard('fp-mode') and want.get('mode') != got_mode:
            bad.append(f'{what}の読み方が基準と違う: {rel}（基準 {want.get("mode")} / 今 {got_mode}。'
                       'JSON として読めるようになった/読めなくなった変化）')
        if (guard('fp-type') and mode == 'any'
                and want.get('mode') not in ('json', 'bytes')):
            bad.append(f'{rel} の指紋の型が台帳で不明: {want.get("mode")}'
                       '（any の入力は json / bytes のどちらかで登録する）')
    return bad


def parse_flags(argv, value_flags=('--emit-measured', '--profile')):
    """`--旗 値` を取り除いた位置引数と、旗の値の辞書を返す

    旗の**値**を位置引数と取り違えると、測る対象のパスが `--emit-measured` の書き先に
    なってしまう（第 55 ラウンドの実行で実際に踏んだ）"""
    vals, pos = {}, []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in value_flags:
            if i + 1 >= len(argv):
                raise SystemExit(f'{a} の値が無い')
            vals[a] = argv[i + 1]
            i += 2
            continue
        pos.append(a)
        i += 1
    return vals, pos


def emit_measured(path, kind, measured):
    """測った件数を要求一覧の材料へ書き出す（`--emit-measured`。既成ファイルがあればその鍵だけ更新）

    通常の検証では正本を更新しない。これは人が要求一覧を作り直すときだけ走らせる"""
    p = resolve_cli_path(path, default=None)
    doc = {}
    if p.exists():
        doc = json.loads(p.read_text(encoding='utf-8'))
    # 値はそのまま置く（件数の別名表も入れ子の内訳もここを通す。形の見直しは
    # `validate_required_spec` / `check_coverage` が一覧の側でやる）
    doc[kind] = measured
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, sort_keys=True, indent=1) + '\n',
                 encoding='utf-8')
    return p


def check_coverage(kind, measured, repo=None, what='走査した件数'):
    """測った件数を条件別で期待値と突き合わせ、違えば**測ったあと**に終了 1

    `measured` は `{条件の id: 実際に走査した件数}`。報告された summary の自己申告だけでは
    数えない（実際に検査が回したループの回数をここで渡す）"""
    exp = expectations(repo).get(kind)
    if not isinstance(exp, dict):
        fail(f'expectations.{kind} が要求一覧に無い（作り直し: '
             f'python3 skill/scripts/tools/battery/emit-required.py {REQUIRED}）')
    want, got = exp['byCondition'], dict(measured)
    gone = sorted(set(want) - set(got))
    added = sorted(set(got) - set(want))
    changed = sorted((i, want[i], got[i]) for i in set(want) & set(got) if want[i] != got[i])
    if guard('coverage') and (gone or added or changed):
        lines = [f'{kind} の{what}が期待値と違う: 期待 {len(want)} 件合計 {exp["total"]} / '
                 f'今回 {len(got)} 件合計 {sum(got.values())}'
                 '（入力は同じなのに測る範囲だけ動いた日の合図。意図した変更なら測った値を'
                 '一覧へ反映して人がレビューする）']
        for i in gone[:10]:
            lines.append(f'  - 今回測れていない {i}: 期待 {want[i]} 件')
        for i in added[:10]:
            lines.append(f'  + 期待に無い {i}: 今回 {got[i]} 件')
        for i, a, b in changed[:14]:
            lines.append(f'  ~ {i}: 期待 {a} 件 / 今回 {b} 件')
        fail('\n'.join(lines))
    return sum(got.values())


def validate_required_spec(spec, repo=None):
    """要求一覧の**中身**を検査する（第 55 ラウンド Astra 裁定 問 3）

    id が合っているか、ケース重複が無いが、`graph` / `kind` / `args` を見ていない検査は
    偽成功の通り道だった（Codex 指摘 2）。ここでは型・必須欄・種類と引数の整合・
    fixture の重複・glob との実体比較まで、集合比較より前に全部落とす"""
    repo = pathlib.Path(repo or repo_root())
    bad = []
    if not isinstance(spec, dict):
        fail(f'要求一覧が JSON のオブジェクトではない: {type(spec).__name__}')
    for k in ('fixtures', 'conditions', 'expectations'):
        if k not in spec:
            bad.append(f'要求一覧に {k} が無い（第 55 ラウンドの形へ作り直す: '
                       f'python3 skill/scripts/tools/battery/emit-required.py {REQUIRED}）')
    if bad:
        fail('\n'.join(bad))
    fx = spec['fixtures']
    if not isinstance(fx, list) or not all(isinstance(x, str) for x in fx):
        bad.append('fixtures は文字列の配列')
        fx = []
    if guard('dup-fixture') and len(fx) != len(set(fx)):
        # 集合にすると重複が消える。「19 本ある」と言い張れて走らない検査が隠れる
        # （第 56 ラウンド agy P2-1: ここだけ `guard()` を通っていなかった）
        for dup in sorted({x for x in fx if fx.count(x) > 1}):
            bad.append(f'fixtures に重複: {dup}')
    # glob の実体と要求一覧を双方向で比べる（新しい fixture を一覧に書かない日は
    # 「走らない fixture がある」状態なので止める。第 54 ラウンド agy 指摘）
    on_disk = sorted(str(pathlib.Path(p).resolve().relative_to(repo.resolve())).replace('\\', '/')
                     for p in glob.glob(str(repo / FIXTURE_GLOB)))
    if guard('fixture-set'):
        for miss in sorted(set(on_disk) - set(fx)):
            bad.append(f'fixture が有るのに要求一覧に無い（走らない検査になる）: {miss}')
        for extra_ in sorted(set(fx) - set(on_disk)):
            bad.append(f'要求一覧に有るのに fixture が無い: {extra_}')
    conds = spec['conditions']
    if not isinstance(conds, list):
        fail('conditions は配列でなければならない')
    seen_key, seen_id = {}, {}
    for i, c in enumerate(conds):
        where = f'conditions[{i}]'
        if not isinstance(c, dict):
            bad.append(f'{where} がオブジェクトではない')
            continue
        want_keys = {'id', 'case', 'graph', 'kind', 'args'}
        if set(c) != want_keys and guard('cond-shape'):
            bad.append(f'{where} の欄が期待と違う（有る欄 {sorted(c)} / 必要 {sorted(want_keys)}）')
        cid, graph, kind = c.get('id'), c.get('graph'), c.get('kind')
        args, case = c.get('args') or [], c.get('case')
        if not isinstance(graph, str) or not graph:
            bad.append(f'{where} の graph が文字列ではない')
            continue
        if '#' in graph:
            bad.append(f'{where} の graph に `#` が混ざっている（表示は case が持つ。'
                       f'実際に読むファイルの相対パスだけを書く: {graph}）')
        if pathlib.PurePosixPath(graph).is_absolute() or graph.startswith('..'):
            bad.append(f'{where} の graph がリポジトリ相対ではない: {graph}')
        if case is not None and not isinstance(case, str) and guard('cond-shape'):
            bad.append(f'{where} の case は null か文字列')
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            if guard('cond-shape'):
                bad.append(f'{where} の args は文字列の配列')
            args = [str(a) for a in args]
        if guard('cond-shape'):
            for e in spec_shape_errors(kind, args):
                bad.append(f'{where} {graph} [{kind}]: {e}')
        key = condition_key(case, graph, kind, args)
        # dict はそのままではキーにできないので正準形の文字列で数える（第 55 ラウンド実測）
        flat = json.dumps(key, ensure_ascii=False, sort_keys=True)
        got_id = condition_id(key)
        if guard('canonical-id') and cid != got_id:
            bad.append(f'{where} の id が中身から再計算できない（記録 {cid} / 計算 {got_id}。'
                       '中身を変えたなら一覧の作り直し、作り直せない差分なら入力の差し替え）')
        if guard('dup-condition') and flat in seen_key:
            bad.append(f'起動条件の正準形が重複: {case} / {graph} [{kind}] '
                       f'{" ".join(args)[:70]}（conditions[{seen_key[flat]}] と conditions[{i}]）')
        if guard('dup-id') and cid in seen_id and seen_id[cid] != i:
            bad.append(f'id が重複: {cid}（conditions[{seen_id[cid]}] と conditions[{i}]。'
                       '別の正準形が同じ 16 桁に衝突した日は一覧を作り直す）')
        seen_key.setdefault(flat, i)
        seen_id.setdefault(cid, i)
    bad += coverage_shape_errors(spec['expectations'])
    if bad:
        fail('要求一覧（required-checks.json）が壊れている:\n  ' + '\n  '.join(bad[:24]) +
             (f'\n  …ほか {len(bad)} 件' if len(bad) > 24 else '') +
             '\n  作り直し: python3 skill/scripts/tools/battery/emit-required.py '
             f'{REQUIRED}（作られた一覧を人がレビューしてコミットする）')
    return spec


def required_fixtures(repo=None):
    """要求一覧に有る fixture の実体（欠けていれば `require` が終了 1。glob で減らさない）"""
    repo = pathlib.Path(repo or repo_root())
    return [require(repo / rel, '追跡下の fixture（required-checks.json が要求）')
            for rel in required_spec()['fixtures']]


def condition_args(doc):
    """グラフ 1 本にかける起動条件（`--from` / `--api` / `--changed`）を組み立てる。
    第 53 ラウンドまで `check-invariants46.py` と `self-consistency.py` に**同じ関数が 2 本**
    あって、一方だけ直す余地が残っていた。ここで一本化する
    （`--changed` の一覧は一時ファイルのパスにせず `@a,b` の文字列で持つ＝比較に一時パスを入れない）"""
    import itertools
    out = []
    ids = [n['id'] for n in doc['nodes']]
    picks = ids[:3] + ids[len(ids) // 2:len(ids) // 2 + 2] + ids[-1:]
    picks = list(dict.fromkeys(picks))
    for k in (1, 2):
        for combo in itertools.islice(itertools.combinations(picks, k), 4):
            args = []
            for x in combo:
                args += ['--from', x]
            out.append(('from', args))
    apis = []
    for n in doc['nodes']:
        ep = (n.get('metadata') or {}).get('endpoint') or n.get('endpoint')
        if ep and ep not in apis:
            apis.append(ep)
    for ep in apis[:3]:
        out.append(('api', ['--api', ep]))
    files = []
    for n in doc['nodes']:
        f = (n.get('metadata') or {}).get('file') or n.get('file')
        if f and f not in files:
            files.append(f)
    if files:
        out.append(('changed', ['--changed', '@' + ','.join(files[:2])]))
    return out


def condition_key(case, graph_rel, kind, args):
    """起動条件の**正準形**（第 55 ラウンド双人レビュー Codex 指摘 2 と Astra 裁定 問 3）

    id だけを見て合否を決めたため、要求一覧の `graph` / `kind` / `args` を好きに書き換えても
    （id をそのまま置き去りにすれば）合格した。**合否はこの正準形その物の比較**で決める。
    id は検索・表示・期待値台帳のキーに使う導物で、`condition_id()` で必ず再計算できる
      * `case` どの基準レポートに対する条件か（v1 基準の 18 条件だけ持つ。同じ起動内容を
        別の基準ケースとして残す意図をここに書く。`elsa-1` と `elsa-folder`、
        `elsa-50` と `elsa-limit` がそれで、219 件＝219 とおりの起動内容ではない）
      * `graph` 実際に読むファイルのリポジトリ相対パス（`レポート名#旧パス` のような
        表示のための複合文字列はここに入れない。表示は `case` が持つ）
      * `kind` / `args` 起動の種類と引数配列（順はそのまま。並べ替えない）"""
    return {'case': case, 'graph': graph_rel, 'kind': kind,
            'args': [str(a) for a in args]}


def condition_id(key):
    """正準形から作る 16 桁の指紋。入力の位置と重複を保った JSON の sha256"""
    body = json.dumps(key, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(body.encode('utf-8')).hexdigest()[:16]


def audit_condition(report_path, repo=None):
    """v1 基準の 1 レポートが記録している起動条件を、今のリポジトリの実体で組み直す"""
    doc = json.loads(pathlib.Path(report_path).read_text(encoding='utf-8'))
    s = doc['summary']
    args = ['--hops', str(s['hops']), '--wiring-hops', str(s['wiringHops']),
            '--limit', str(s.get('limit') or 100000)]
    for item in doc['starts']:
        args += ['--from', item['id']]
    graph = graph_path(s['graph'], repo)
    # 実際に読むグラフのリポジトリ相対形をここに置く（第 54 ラウンドまでレポート名を
    # `#` で繋いでいたため、記録された 3 項目から id を再計算できなかった。Codex 指摘 2）
    rel = rel_of_recorded(s['graph'], repo) or graph.name
    case = pathlib.Path(report_path).name
    key = condition_key(case, rel, 'audit-full', args)
    return {'rel': case, 'case': case, 'graph': graph, 'graphRel': rel,
            'kind': 'audit-full', 'args': args, 'key': key, 'id': condition_id(key)}


def launch_conditions(repo=None, check_required=True, fixtures=None):
    """回帰検査が走らせる起動条件の**一覧**。要求一覧と集合で突き合わせてから返すので、
    条件を組み立てる側が黙って減った日・増えた日は測る前に終了 1（200 件の見張り番は不要になった）。
    `fixtures` は `emit-required.py`（要求一覧その物を作る道具）だけが渡す。通常は要求一覧が正本"""
    repo = pathlib.Path(repo or repo_root())
    if fixtures is None:
        fixtures = required_fixtures(repo)
    conds = []
    for g in list(fixtures) + [require(x, '検査のグラフ') for x in extra_graphs(repo)]:
        rel = str(pathlib.Path(g).resolve().relative_to(repo.resolve())).replace('\\', '/')
        doc = json.loads(pathlib.Path(g).read_text(encoding='utf-8'))
        for kind, args in condition_args(doc):
            key = condition_key(None, rel, kind, args)
            conds.append({'rel': rel, 'case': None, 'graph': pathlib.Path(g), 'graphRel': rel,
                          'kind': kind, 'args': list(args), 'key': key, 'id': condition_id(key)})
    for rep_ in report_paths(HERE / 'baseline-v1', expect=18, what='v1 基準の 18 条件'):
        conds.append(audit_condition(rep_, repo))
    if not check_required:
        return conds
    spec = validate_required_spec(required_spec(), repo)
    # 組み上げた側も、集合比較の前に重複を拒否する。id の集合にすると重複が消えて
    # 「219 件」と言い張れた（第 54 ラウンド agy 指摘）
    flat_got = [json.dumps(c['key'], ensure_ascii=False, sort_keys=True) for c in conds]
    dup = sorted({f for f in flat_got if flat_got.count(f) > 1}) if guard('dup-built') else []
    if dup:
        lines = [f'今回組み上げた起動条件に重複がある: {len(conds)} 組み / 重複 {len(dup)} 組'
                 '（要求一覧との比較の前に止める。同じ起動内容を 2 度走らせるのは検査ではなく、'
                 '入力の組み方が崩れている合図）']
        for f in dup[:10]:
            lines.append('  x ' + f[:150])
        fail('\n'.join(lines))
    # 合否は**正準形の比較**で決める。id の集合だけを見ると、要求一覧の graph / kind / args を
    # 好きに書き換えて id を据え置いた日が通った（第 54 ラウンド Codex 指摘 2）
    want_by = {json.dumps(condition_key(c.get('case'), c['graph'], c['kind'], c['args']),
                          ensure_ascii=False, sort_keys=True): c for c in spec['conditions']}
    got_by = dict(zip(flat_got, conds))
    gone, added = sorted(set(want_by) - set(got_by)), sorted(set(got_by) - set(want_by))
    if guard('condition-set') and (gone or added):
        lines = [f'起動条件が要求一覧（{REQUIRED.name}）と違う: 要求 {len(want_by)} 件 / '
                 f'今回 {len(got_by)} 件（要求にあるのに今回走らない {len(gone)} 件 / '
                 f'要求に無いのに走る {len(added)} 件）。入力の欠落なら作り直し、意図して変えたなら '
                 '`python3 skill/scripts/tools/battery/emit-required.py <このファイル>` で'
                 '人が作り直してレビューする（自動更新しない）']
        for f in gone[:12]:
            c = want_by[f]
            lines.append(f'  - 走らない {c["case"] or c["graph"]} [{c["kind"]}] '
                         f'{" ".join(c["args"])[:80]}')
        for f in added[:12]:
            c = got_by[f]
            lines.append(f'  + 未知 {c["case"] or c["graphRel"]} [{c["kind"]}] '
                         f'{" ".join(str(a) for a in c["args"])[:80]}')
        fail('\n'.join(lines))
    return conds


def materialize(cond, tmpdir):
    """`--changed @a,b` を一時ファイルへ展開して実行用の引数にする（一覧の文字列は比較対象）"""
    args = []
    n = 0
    for a in cond['args']:
        if isinstance(a, str) and a.startswith('@'):
            n += 1
            f = pathlib.Path(tmpdir) / f'changed-{cond["id"]}-{n}.txt'
            f.write_text(a[1:].replace(',', '\n') + '\n', encoding='utf-8')
            args.append(str(f))
        else:
            args.append(a)
    return args
