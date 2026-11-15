# 親と子の表示経路が「無方向の連鎖で 同じ 向き になるか」を検査する（第 46 ラウンド裁定 (b)）
#
# 裁定のフォールド規則:
#   起点の方向 = none
#   無方向の定義縁 → 直前の方向をそのまま継承（最初は none のまま）
#   動きの縁       → 既存の矢印規則・実装側へ入る例外で決定
#   その他の有向縁 → その縁の矢印で決定
# つまり **無方向の定義縁で届いた行の `向き` は、その一歩の親の行の `向き` と必ず同じ**
# でなければならない（`none` ⇔ `none` も含む）。親がレポートに行として立っていない場合は
# 比較できないので数えない。
#
# 基準は今のディレクトリの skill/scripts/report.mjs。期待値は 不一致 0 件。
# 使い方: python3 skill/scripts/tools/battery/self-consistency.py [report.mjs のパス]
import itertools
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections import Counter

def _repo_root(start):
    # __file__ からの段数ハードコードはやめる（道具の置き場所を動かした日に黙って別の
    # ディレクトリをリポジトリの根と誤認した。第 50 ラウンド双人レビュー後に実測）
    for a in [start, *start.parents]:
        if (a / 'skill' / 'scripts' / 'report.mjs').exists():
            return a
    raise SystemExit('リポジトリの根が見つからない（skill/scripts/report.mjs を含む祖先を探した）')


REPO = _repo_root(pathlib.Path(__file__).resolve().parent)
REPORT = sys.argv[1] if len(sys.argv) > 1 else 'skill/scripts/report.mjs'
REPORT = str(REPO / REPORT) if not os.path.isabs(REPORT) else REPORT
MOVEMENT = {'triggers', 'invokes', 'handler', 'exposed-by'}
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out', 'artifacts.in', 'artifacts.out',
           'sameApi', 'siblingEndpoints', 'wiring']

FIXTURES = sorted((REPO / 'skill' / 'tests' / 'fixtures' / 'ImpactFacts').glob('*.graph.json'))
EXTRA = [REPO / 'skill' / 'tests' / 'fixtures' / 'query' / 'graph.json',
         REPO / 'out' / 'tmp-r42' / 'demo' / 'graph.json',
         REPO / 'out' / 'tmp-r44' / 'demo' / 'graph.json',
         REPO / 'out' / 'tmp-r45' / 'dbg' / 'ri' / 'graph.json',
         REPO / 'out' / 'tmp-r45' / 'dbg' / 'ri2' / 'graph.json']
AUDIT = sorted((REPO / 'out' / 'tmp-r29' / 'audit-full').glob('*.json'))

TMP = tempfile.mkdtemp(prefix='cgd-selfcons-')


def make_list(files):
  p = os.path.join(TMP, 'changed-%d.txt' % len(os.listdir(TMP)))
  with open(p, 'w') as fh:
    fh.write('\n'.join(files) + '\n')
  return p


def runs_for(graph_path):
  """check-invariants46.py と同じ起動条件の組み方"""
  doc = json.loads(graph_path.read_text())
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
    out.append(('changed', ['--changed', make_list(files[:2])]))
  return out


def rows_of(result):
  for b in BUCKETS:
    part = result[b.split('.')[0]][b.split('.')[1]] if '.' in b else result[b]
    for x in part:
      yield b, x


def run_report(graph_path, extra_args):
  out = os.path.join(TMP, 'r-%d.json' % len(os.listdir(TMP)))
  p = subprocess.run(['node', REPORT, '--graph', str(graph_path), *extra_args, '--json', out],
                     cwd=str(REPO), capture_output=True, text=True)
  if p.returncode != 0:
    return None
  return json.loads(pathlib.Path(out).read_text())


mismatches = []
notes = Counter()
conditions = 0
compared = 0
undirected_only = 0


def check_run(label, graph_doc, result):
  """各行の 表示経路 の親一歩が無方向なら、その親の行と同じ 向き を持つこと"""
  global conditions, compared, undirected_only
  conditions += 1
  pairs = {}
  for e in graph_doc['edges']:
    pairs.setdefault((e['source'], e['target']), []).append(e)
    pairs.setdefault((e['target'], e['source']), []).append(e)
  by_id = {}
  for _, r in rows_of(result):
    by_id.setdefault(r['id'], r)          # 同じ id が複数欄に出ることは無い（欄は一意）
  for _, r in rows_of(result):
    path = r.get('path') or []
    if len(path) < 2:
      continue
    parent = by_id.get(path[-2])
    if parent is None:
      notes['親がレポートに行として立っていない'] += 1
      continue
    # 親の表示経路が自分の経路の**接頭辞**であること（別の経路で立っている親とは比べない）
    if (parent.get('path') or []) != path[:-1]:
      notes['親の表示経路が自分の経路の接頭辞ではない'] += 1
      continue
    cands = pairs.get((path[-2], path[-1]), [])
    if not cands:
      notes['表示経路の隣接ペアを結ぶ縁が無い'] += 1
      continue
    undirected = [e for e in cands if e['provenance'] == 'terraform' and e['kind'] not in MOVEMENT]
    if len(undirected) != len(cands):
      # 並行縁に 動きの縁 や 向きを持つ縁 が混ざる一歩は、実装がどれを選んだか JSON だけでは
      # 決まらないので数えない（向き の再計算は check-invariants46.py の検査 6 が見る）
      notes['並行縁に 向き を決める縁が混ざる一歩'] += 1
      continue
    compared += 1
    if r['direction'] != parent['direction']:
      mismatches.append((label, r['id'], parent['id'],
                         f"子={r['direction']} 親={parent['direction']} 縁={undirected[0]['kind']} "
                         f"経路={'|'.join(path)}"))
    # 同じ規則を**根**へ適用した形: 表示経路の 1 本目が無方向の定義縁なら、その行の 向き は
    # 起点の 向き（= none）から始まる。経路全体が無方向なら 向き は none のままのはず
    # （第 45 ラウンドまであった「無方向の最初の一歩を端点から種にする」規則は
    # 第 46 ラウンド裁定 (b) で却下されたので、その実装ではここが違反になる）
    step_edges = [e for a, b in zip(path, path[1:]) for e in pairs.get((a, b), [])]
    if step_edges and all(e['provenance'] == 'terraform' and e['kind'] not in MOVEMENT
                          for e in step_edges):
      undirected_only += 1
      if r['direction'] != 'none':
        mismatches.append((label + ' / 経路全体が無方向', r['id'], path[0],
                           f"子={r['direction']} 期待=none 経路={'|'.join(path)}"))


for gp in FIXTURES + [p for p in EXTRA if p.exists()]:
  doc = json.loads(gp.read_text())
  for kind, args in runs_for(gp):
    res = run_report(gp, args)
    if res is None:
      continue
    check_run(f'{gp.name}[{kind}]', doc, res)

for cond in AUDIT:
  doc = json.loads(cond.read_text())
  s = doc['summary']
  args = ['--hops', str(s['hops']), '--wiring-hops', str(s['wiringHops']),
          '--limit', str(s.get('limit') or 100000)]
  for item in doc['starts']:
    args += ['--from', item['id']]
  gp = pathlib.Path(s['graph'])
  if not gp.is_absolute():
    gp = REPO / gp
  if not gp.exists():
    continue
  res = run_report(gp, args)
  if res is None:
    continue
  check_run(f'{cond.name}[audit-full]', json.loads(gp.read_text()), res)

print(f'検査した起動条件 {conditions} 件 / 無方向の一歩で親と突き合わせた行 {compared} 件'
      f'（うち 表示経路全体が無方向の行 {undirected_only} 件）')
print(f'不一致 {len(mismatches)} 件')
for k, c in notes.most_common():
  print(f'（参考）{k}: {c}')
for m in mismatches[:20]:
  print(f'  不一致: {m[0]} / 子={m[1]} / 親={m[2]} / {m[3]}')
sys.exit(1 if mismatches else 0)
