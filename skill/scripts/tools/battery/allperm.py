#!/usr/bin/env python3
# 全縁順（n! 通り、最大 7 縁 = 5040 は多いので 6 縁まで）で表を比較し、割れる並びを列挙する
import json, sys, itertools, tempfile, os, collections
import _inputs as IN

REPO = IN.repo_root()

# 存在しない report.mjs を渡して「全通り一致」で合格しない（第 51 ラウンド双人レビュー Codex P2）
script = str(IN.require_script(sys.argv[1] if len(sys.argv) > 1 else None))
graph_file = str(IN.require(IN.resolve_cli_path(sys.argv[2] if len(sys.argv) > 2 else None,
                                          default='skill/scripts/tools/battery/min-0.json'),
                            '順列検査の固定グラフ', want_file=True))
extra = json.load(open(graph_file)).get('extra', [])
# 3 番目の引数で期待する縁順の通り数を明示できる（allperm-full.py と同じ決まり）
EXPECT = int(sys.argv[3]) if len(sys.argv) > 3 else None
g = json.load(open(graph_file))['graph']
def run(edges):
    gg = dict(g); gg['edges'] = edges
    # 子の JSON は `IN.run_json` で読む（終了 0 で書かない・空・壊れた JSON・別の形を
    # ここで落とす。第 55 ラウンド agy 指摘: `json.load` 直読みだと traceback だけ残す）
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'g.json')
        with open(path, 'w') as f:
            json.dump(gg, f)
        d = IN.run_json(script, ['--graph', path, *extra], os.path.join(td, 'r.json'),
                        repo=REPO, label='allperm.py（縁順 1 とおりの実行）')
    # 6 欄（external/entries/artifacts x in/out）だけを突き合わせているとここで宣言する
    rows = []
    for r in IN.projection_rows(d, 'allperm.py', ('id', 'bucket', 'direction', 'hops', 'switches')):
        rows.append(f"{r['id']}={r['bucket']}/{r['direction']}/h{r['hops']}/sw{r['switches']}/e{(r.get('evidence') or {}).get('id','-')}/mv{(r.get('movementEvidence') or {}).get('id','-')}")
    # 行が 0 件の実行を「1 通りに一致」で合格にしない（第 54 ラウンド agy 指摘 2）
    IN.require_comparison_rows(rows, 'allperm.py（縁順 1 とおりの実行）', what='比較する行')
    return '\n'.join(sorted(rows))
IN.permutation_guards(len(g['edges']), None, EXPECT, 'allperm.py')
res = collections.OrderedDict()
for perm in itertools.permutations(range(len(g['edges']))):
    edges = [g['edges'][i] for i in perm]
    res[','.join('e%d' % i for i in perm)] = run(edges)
IN.permutation_guards(len(g['edges']), len(res), EXPECT, 'allperm.py')
uniq = collections.defaultdict(list)
for k, v in res.items(): uniq[v].append(k)
print(f"縁順 {len(res)} 通り / 表 {len(uniq)} 通り")
for v, ks in uniq.items():
    print(f"-- {len(ks)} 通り（例: {ks[0]}）")
    for line in v.split('\n'): print('   ', line)
    if len(uniq) > 1: print('    ...')

# 割れたら終了 1（検査器は終了コードで合否を返す。第 47 ラウンドの約束）
sys.exit(1 if len(uniq) > 1 else 0)
