# 第 43 ラウンド指摘 2 の検査。`calls` だけの 5 縁（N1→N0、N3→N0、N6→N1、N3→N6、
# N6→N2）で縁の列挙順を入れ替えても、表示行（欄 / 向き / 段数 / **向き変え回数** /
# 根拠の縁 / 経路）が 1 通りに決まることを見る。
# 使いところ: python3 skill/scripts/tools/battery/r43-permute.py [report.mjs のパス] [試行数]
#   既定は skill/scripts/report.mjs と全 120 通り（5 縁の順列すべて）
import itertools
import json
import os
import sys
import tempfile

import _inputs as IN   # 根の探索と入力の所在はここに一本化（第 52 ラウンド agy 指摘の未使用関数を削除）

REPO = IN.repo_root()
REPORT = str(IN.require_script(sys.argv[1] if len(sys.argv) > 1 else None))
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 10 ** 9
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out',
           'artifacts.in', 'artifacts.out', 'sameApi', 'siblingEndpoints', 'wiring']

HERE = os.path.dirname(os.path.abspath(__file__))
CASES = [f'r42-calls-{i}.json' for i in (0, 1)]


def rows_of(r):
  out = []
  for b in BUCKETS:
    part = r[b.split('.')[0]][b.split('.')[1]] if '.' in b else r[b]
    for x in part:
      out.append((x['id'], b, x['direction'], x['tier'], x['hops'], x['switches'],
                  (x['evidence'] or {}).get('id'), '->'.join(x['path'])))
  # 行 0 件の並びを「1 通りに決まった」と数えない（第 54 ラウンド agy 指摘 2 と同じ型）
  IN.require_comparison_rows(out, 'r43-permute.py（1 起動）', what='比較する行')
  return sorted(out)


bad = 0
for name in CASES:
  base = json.loads(open(os.path.join(HERE, name)).read())
  shapes = {}
  # 縁が 1 本の条件だと「入れ替えても 1 とおり」で空振りになる（allperm と同じ決まり）
  IN.permutation_guards(len(base['edges']), None, None, f'r43-permute.py {name}')
  for perm in itertools.islice(itertools.permutations(base['edges']), LIMIT):
    g = {'nodes': base['nodes'], 'edges': list(perm)}
    with tempfile.TemporaryDirectory() as td:
      gp, op = os.path.join(td, 'g.json'), os.path.join(td, 'o.json')
      open(gp, 'w').write(json.dumps(g))
      # 子の JSON は `IN.run_json`。実行失敗・空・壊れた JSON・別の形をここで終了 1 にする
      # （失敗を数えて続けると**全実行失敗でも「表 1 通り」**になった。第 47 ラウンド Codex 指摘）
      r = IN.run_json(REPORT, ['--graph', gp, '--from', 'member:N0', '--hops', '4'], op,
                      repo=REPO, label='r43-permute.py の縁順実行')
      shape = json.dumps({'rows': rows_of(r), 'secondOrder': r['summary']['secondOrder'],
                          'entryOut': r['summary']['entryOut'],
                          'entryIn': r['summary']['entryIn']},
                         ensure_ascii=False)
      shapes.setdefault(shape, []).append('->'.join(e['id'] for e in perm))
  print(f'{name}: 表 {len(shapes)} 通り（{sum(len(v) for v in shapes.values())} 入れ替え）')
  if len(shapes) != 1:
    bad += 1
    for shape, ps in sorted(shapes.items(), key=lambda kv: -len(kv[1])):
      print(f'  {len(ps)} 通り目: {shape[:400]}')
      print(f'    縁順の例: {ps[:3]}')
sys.exit(1 if bad else 0)
