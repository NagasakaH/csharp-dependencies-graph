# 2 つの report.mjs の出力が**バイト一致**かを 18 条件で確かめる（削減の手元の証明）。
# 条件は skill/scripts/tools/battery/baseline-v1 の 18 レポートから復元する。
# 使い方: python3 skill/scripts/tools/battery/same-output.py <A.mjs> <B.mjs>
import json
import os
import pathlib
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
BASE = pathlib.Path(REPO) / 'skill' / 'scripts' / 'tools' / 'battery' / 'baseline-v1'
A = os.path.abspath(sys.argv[1] if len(sys.argv) > 1
                    else os.path.join(REPO, 'skill', 'scripts', 'report.mjs'))
B = os.path.abspath(sys.argv[2]) if len(sys.argv) > 2 else None
if not B:
  raise SystemExit('使い方: same-output.py <A.mjs> <B.mjs>')

bad = 0
n = 0
with tempfile.TemporaryDirectory() as td:
  for p in sorted(BASE.glob('*.json')):
    s = json.loads(p.read_text())['summary']
    args = ['--graph', s['graph'], '--hops', str(s['hops']),
            '--wiring-hops', str(s['wiringHops']),
            '--limit', str(s.get('limit') or 100000)]
    for item in json.loads(p.read_text())['starts']:
      args += ['--from', item['id']]
    n += 1
    got = []
    for tag, script in (('a', A), ('b', B)):
      j = os.path.join(td, f'{p.name}-{tag}.json')
      m = os.path.join(td, f'{p.name}-{tag}.md')
      r = subprocess.run(['node', script] + args + ['--json', j, '--md', m],
                         cwd=REPO, capture_output=True, text=True)
      if r.returncode != 0:
        got.append(('失敗', r.stderr[-300:]))
        continue
      got.append((pathlib.Path(j).read_text(), pathlib.Path(m).read_text(), r.stderr))
    if got[0] != got[1]:
      bad += 1
      for i, kind in enumerate(('--json', '--md', 'stderr')):
        x, y = got[0][i], got[1][i]
        if x == y:
          continue
        print(f'{p.name}: {kind} が異なる（{len(x)} 字 / {len(y)} 字）')
        xs, ys = x.split('\n'), y.split('\n')
        for ln in range(max(len(xs), len(ys))):
          a = xs[ln] if ln < len(xs) else '(無し)'
          b = ys[ln] if ln < len(ys) else '(無し)'
          if a != b:
            print(f'  {ln + 1} 行目 A: {a[:200]}\n  {ln + 1} 行目 B: {b[:200]}')
            break
print(f'--- {n} 条件中 不一致 {bad} 件（A={os.path.relpath(A, REPO)}  B={os.path.relpath(B, REPO)}）')
sys.exit(1 if bad else 0)
