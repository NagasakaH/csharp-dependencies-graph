# 縁の列挙順を変えても `--group-by` の JSON が同じかを調べる（`query.mjs` の集計が縁順に
# 依存しないことの証拠。第 43 ラウンド双人レビューの系譜）。
#
#   python3 skill/scripts/tools/battery/edge-order.py [graph.json]
#
# 入力グラフの既定は `out/demo/graph.json`（作り直し: `node skill/scripts/build.mjs --root demo
# --out-dir out/demo --annotation skill/examples/annotations.orders-api.json --annotation
# skill/examples/annotations.storage.json`）。並び変えた中間ファイルは一時ディレクトリに書く
# （第 51 ラウンド双人レビューまで、この道具は `out/tmp-*` に唯一のコピーが有り、
# 同一ディレクトリに中間ファイルを吐いていた。掃除で消えると参照だけが残る）
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile

import _inputs as IN

REPO = IN.repo_root()
QUERY = IN.require(REPO / 'skill' / 'scripts' / 'query.mjs', 'query.mjs')
BASE = str(IN.require(IN.resolve_cli_path(sys.argv[1] if len(sys.argv) > 1 else None,
                                          default='out/demo/graph.json'),
                      '実グラフ', want_file=True))

CMDS = [
    ['--from', 'file:src/Orders.Domain/Order.cs', '--dir', 'both', '--via-parent', '--hops', '3', '--group-by', 'file'],
    ['--from', 'member:Orders.Domain.Order.Id', '--dir', 'both', '--via-parent', '--hops', '3', '--group-by', 'file'],
    ['--from', 'tf:aws_lambda_function.orders_api', '--dir', 'both', '--via-parent', '--hops', '2', '--group-by', 'type'],
    ['--from', 'file:src/Orders.Api/Functions.cs', '--dir', 'in', '--via-parent', '--hops', '2', '--group-by', 'file'],
]


def key(graph, argv, repo):
    """`query.mjs` を 1 回走らせて比較の鍵（群と集計）を取り出す

    第 57 ラウンド agy P2-2: この子実行だけ `IN.run_json` を通っていなくて、リターンコード・
    パース・形の判定に**名前が無かった**（見張り番を 1 個ずつ消す設計の外側）。`.mjs` を
    触らないまま名前を付ける裁定（Astra 裁定 問 4: `--json <path>` を増やさない）"""
    p = subprocess.run(['node', str(QUERY), '--graph', graph, '--json', *argv],
                       cwd=str(repo), capture_output=True, text=True)
    # 失敗を「不一致 0 件」に混ぜない（check=True だと Traceback で終わる）
    if IN.guard('child-fail') and p.returncode != 0:
        raise SystemExit(f'query.mjs 失敗 (exit {p.returncode}) {" ".join(argv)}: {p.stderr[-500:]}')
    try:
        d = json.loads(p.stdout)
    except ValueError as e:
        if IN.guard('json-parse'):
            raise SystemExit(f'query.mjs の JSON が読めない ({" ".join(argv)}。{e}): {p.stdout[:200]}')
        d = {}
    if not isinstance(d, dict) or not isinstance(d.get('groups'), list) or \
            not isinstance(d.get('summary'), dict):
        # 「比較に使う群出力の契約」も `edge-order-groups` の範囲（Astra 裁定 問 4。
        # 全起動 0 群の検査と同じ名前所以、README の範囲説明に両方書く）
        if IN.guard('edge-order-groups'):
            raise SystemExit(f'query.mjs の出力が --json の形ではない'
                             f'（{" ".join(argv)}: keys={sorted(d)[:5] if isinstance(d, dict) else type(d).__name__}）')
    s = {k: v for k, v in d['summary'].items() if k.startswith('group') or k == 'reached'}
    return json.dumps({'groups': d.get('groups', []), 'summary': s}, sort_keys=True, ensure_ascii=False)


def main():
    """本体（第 58 ラウンド: `if __name__ == "__main__"` で括った。制御が `key()` を
    呼んで子実行の判定 3 個を**この経路で**確かめるため、import だけで走らないようにする）

    （Astra 裁定 問 4: 追加した判定が実際に働くことは、この呼び出し経路で見る。
      `run_json` の制御だけでは別の経路の証拠にしかならない）"""
    base = json.loads(pathlib.Path(BASE).read_text())
    total_groups = 0
    print(f"# 縁の列挙順を変えても --group-by の JSON が同じか"
          f"（{os.path.relpath(BASE, REPO)}: {len(base['nodes'])} ノード / {len(base['edges'])} 縁）")
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        variants = {'原順': str(BASE)}
        for name, eds in (('反転', list(reversed(base['edges']))),
                          ('id順', sorted(base['edges'], key=lambda e: e['id'])),
                          ('シャッフル', random.Random(7).sample(base['edges'], len(base['edges'])))):
            q = pathlib.Path(td) / f'demo-edges-{name}.json'
            q.write_text(json.dumps({**base, 'edges': eds}, ensure_ascii=False))
            variants[name] = str(q)
        for i, argv in enumerate(CMDS, 1):
            print(f"\n[{i}] query.mjs {' '.join(argv)}")
            ref = key(BASE, argv, REPO)
            for name, path in variants.items():
                if name == '原順':
                    continue
                same = key(path, argv, REPO) == ref
                bad += 0 if same else 1
                print(f"   {name}: {'一致' if same else '不一致'}")
            g = json.loads(ref)['groups']
            print('   groups: ' + (', '.join(
                f"{x['id']} 参照{x['nodes']}ノード/実縁{x['edges']}本" for x in g) or '(0 件)'))
            total_groups += len(g)
            # 単一の起動が 0 群その物は正当（`--dir in` で届く先が無い起点が 1 本ある）。
            # 見るのは **4 本の合計**。すべて 0 なら 4 とおりの並び順を突き合わせる相手が
            # 無いので合格にしない（Astra 裁定 問 4: 一律に 0 行を違反にはしない）
    # （この見張り番の実装は下の合計判定。群の数え上げだけここで足す）
    if IN.guard('edge-order-groups') and total_groups == 0:
        raise SystemExit(f'edge-order.py: {len(CMDS)} 本の起動ですべて群が 0 件（{BASE}）。'
                         '並び順を変えた 4 通りを突き合わせる相手が無いので合格にしない。'
                         '空のグラフや起点が無いグラフを渡していないか確かめる')
    print(f"\n不一致 {bad} 件（0 が期待値）/ 集計された群 {total_groups} 件")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
