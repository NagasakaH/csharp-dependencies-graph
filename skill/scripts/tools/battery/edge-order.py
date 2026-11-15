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
BASE = str(IN.require(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1
                      else REPO / 'out' / 'demo' / 'graph.json', '実グラフ', want_file=True))

CMDS = [
    ['--from', 'file:src/Orders.Domain/Order.cs', '--dir', 'both', '--via-parent', '--hops', '3', '--group-by', 'file'],
    ['--from', 'member:Orders.Domain.Order.Id', '--dir', 'both', '--via-parent', '--hops', '3', '--group-by', 'file'],
    ['--from', 'tf:aws_lambda_function.orders_api', '--dir', 'both', '--via-parent', '--hops', '2', '--group-by', 'type'],
    ['--from', 'file:src/Orders.Api/Functions.cs', '--dir', 'in', '--via-parent', '--hops', '2', '--group-by', 'file'],
]


def key(graph, argv, repo):
    p = subprocess.run(['node', str(QUERY), '--graph', graph, '--json', *argv],
                       cwd=str(repo), capture_output=True, text=True)
    # 失敗を「不一致 0 件」に混ぜない（check=True だと Traceback で終わる）
    if p.returncode != 0:
        raise SystemExit(f'query.mjs 失敗 (exit {p.returncode}) {" ".join(argv)}: {p.stderr[-500:]}')
    d = json.loads(p.stdout)
    s = {k: v for k, v in d['summary'].items() if k.startswith('group') or k == 'reached'}
    return json.dumps({'groups': d['groups'], 'summary': s}, sort_keys=True, ensure_ascii=False)


base = json.loads(pathlib.Path(BASE).read_text())
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
print(f"\n不一致 {bad} 件（0 が期待値）")
sys.exit(1 if bad else 0)
