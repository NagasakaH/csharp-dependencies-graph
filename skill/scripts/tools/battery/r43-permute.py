# 第 43 ラウンド指摘 2 の検査。`calls` だけの 5 縁（N1→N0、N3→N0、N6→N1、N3→N6、
# N6→N2）で縁の列挙順を入れ替えても、表示行（欄 / 向き / 段数 / **向き変え回数** /
# 根拠の縁 / 経路）が 1 通りに決まることを見る。
# 使いところ: python3 skill/scripts/tools/battery/r43-permute.py [report.mjs のパス] [試行数]
#   既定は skill/scripts/report.mjs と全 120 通り（5 縁の順列すべて）
import itertools
import json
import os
import subprocess
import sys
import tempfile

def _repo_root(start):
    # 段数のハードコードはやめた（道具を動かした日に別ディレクトリを根と誤認した）
    a = start
    while not os.path.exists(os.path.join(a, 'skill', 'scripts', 'report.mjs')):
        up = os.path.dirname(a)
        if up == a:
            raise SystemExit('リポジトリの根が見つからない（skill/scripts/report.mjs を含む祖先）')
        a = up
    return a


REPO = _repo_root(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                         else os.path.join(REPO, 'skill', 'scripts', 'report.mjs'))
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
  return sorted(out)


bad = 0
for name in CASES:
  base = json.loads(open(os.path.join(HERE, name)).read())
  shapes = {}
  for perm in itertools.islice(itertools.permutations(base['edges']), LIMIT):
    g = {'nodes': base['nodes'], 'edges': list(perm)}
    with tempfile.TemporaryDirectory() as td:
      gp, op = os.path.join(td, 'g.json'), os.path.join(td, 'o.json')
      open(gp, 'w').write(json.dumps(g))
      p = subprocess.run(['node', REPORT, '--graph', gp, '--from', 'member:N0',
                          '--hops', '4', '--json', op],
                         cwd=REPO, capture_output=True, text=True)
      if p.returncode != 0:
        print(name, '実行失敗 rc=', p.returncode, p.stderr[-300:])
        bad += 1
        break
      r = json.load(open(op))
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
