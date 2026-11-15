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

import hashlib
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
    if not ps:
        raise SystemExit(f'{what}が 0 件: {d}（空で合格にしない。再生成は '
                         f'python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs {d} --force）')
    if expect is not None and len(ps) != expect:
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
        for k in ('nodes', 'edges', 'ids', 'rels'):
            if got[k] != want[k]:
                bad.append(f'{rel} の {k} が基準と違う（基準 {want[k]} / 今 {got[k]}。'
                           '作り直した graphs が元と違う可能性。基準の更新は人の判断）')
    return bad


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


def condition_id(rel, kind, args):
    """起動条件の指紋。リポジトリ内の相対形・種類・引数だけを見る（一時ファイルのパスは入れない）"""
    body = f'{rel}\0{kind}\0' + '\0'.join(str(a) for a in args)
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
    rel = rel_of_recorded(s['graph'], repo) or graph.name
    return {'rel': f'{pathlib.Path(report_path).name}#{rel}', 'graph': graph,
            'kind': 'audit-full', 'args': args,
            'id': condition_id(pathlib.Path(report_path).name, 'audit-full', args)}


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
            conds.append({'rel': rel, 'graph': pathlib.Path(g), 'kind': kind, 'args': list(args),
                          'id': condition_id(rel, kind, args)})
    for rep_ in report_paths(HERE / 'baseline-v1', expect=18, what='v1 基準の 18 条件'):
        conds.append(audit_condition(rep_, repo))
    if not check_required:
        return conds
    want = required_spec()['conditions']
    want_ids = {c['id'] for c in want}
    got_ids = {c['id'] for c in conds}
    gone, added = sorted(want_ids - got_ids), sorted(got_ids - want_ids)
    by_id = {c['id']: c for c in want}
    if gone or added:
        lines = [f'起動条件が要求一覧（{REQUIRED.name}）と違う: 要求 {len(want_ids)} 件 / '
                 f'今回 {len(got_ids)} 件（消えた {len(gone)} 件・新規 {len(added)} 件）。'
                 '入力の欠落なら作り直し、意図して変えたなら '
                 '`python3 skill/scripts/tools/battery/emit-required.py <このファイル>` で'
                 '人が作り直してレビューする（自動更新しない）']
        for i in gone[:12]:
            c = by_id[i]
            lines.append(f'  - 消えた {i}: {c["graph"]} [{c["kind"]}] {" ".join(c["args"])[:90]}')
        for i in added[:12]:
            c = next(x for x in conds if x['id'] == i)
            lines.append(f'  + 新規 {i}: {c["rel"]} [{c["kind"]}] {" ".join(str(a) for a in c["args"])[:90]}')
        raise SystemExit('\n'.join(lines))
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
