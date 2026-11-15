# 2 つの report.mjs の出力が**バイト一致**かを 18 条件で確かめる（削減の手元の証明）。
# 条件は skill/scripts/tools/battery/baseline-v1 の 18 レポートから復元する。
# 使い方: python3 skill/scripts/tools/battery/same-output.py <A.mjs> <B.mjs>
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import _inputs as IN

REPO = IN.repo_root()
if len(sys.argv) < 3:
  raise SystemExit('使い方: same-output.py <A.mjs> <B.mjs>')
# 両方が存在しない report.mjs を渡すと「不一致 0 件」と出ていた（第 51 ラウンド双人レビュー Codex P2）
A = str(IN.require_script(sys.argv[1]))
B = str(IN.require_script(sys.argv[2]))

bad = 0
n = 0
with tempfile.TemporaryDirectory() as td:
  for p in IN.report_paths(IN.HERE / 'baseline-v1', expect=18, what='v1 基準の 18 条件'):
    s = json.loads(p.read_text())['summary']
    # 記録パスが掃除で消えたものは移設した実体へ（両側が同じ失敗をして「一致」に見えないようにする）
    args = ['--graph', str(IN.graph_path(s['graph'])), '--hops', str(s['hops']),
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
        raise SystemExit(f'report.mjs 失敗 (exit {r.returncode}) {p.name} [{tag}]: {r.stderr[-800:]}')
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
def show(p):
  q = os.path.relpath(p, REPO)
  return p if q.startswith('..') else q


print(f'--- {n} 条件中 不一致 {bad} 件（A={show(A)}  B={show(B)}）')
sys.exit(1 if bad else 0)
