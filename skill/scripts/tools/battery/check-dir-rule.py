# 既存のレポート JSON を、第 46 ラウンド裁定の 向き 規則で検査し直す（実行せず読むだけ）。
# v1 基準（skill/scripts/tools/battery/baseline-v1）の 向き が 今回の規則で表示経路から再現できるかを測るためのもので、
# REBASE.md の「どちらが正直か」の実測根拠にする。
# 使い方: python3 skill/scripts/tools/battery/check-dir-rule.py <レポートディレクトリ> [.. 追加のディレクトリ]
import json
import pathlib
import sys

# `skill/scripts/tools/battery/check-invariants46.py` の `arrow_at` / `step_dir` / `fold` と同じ規則を、
# レポート JSON を読むだけのために書き写したもの（あの検査器は import すると 18 起動条件を
# 実行してしまうので、ここでは import しない）。実装 `report.mjs` の `dirOfStep` との一致は
# 検査器側が 2217 行で 0 違反を測っているので、そちらを正本にする
MOVEMENT = {'triggers', 'invokes', 'handler', 'exposed-by'}
FLIP_INTO_IMPL = {'exposed-by', 'handler'}
ARROW_REVERSED = {'exposed-by'}


def arrow_at(edge, node):
  tail = edge['source'] if edge['kind'] in ARROW_REVERSED else edge['target']
  return tail == node


def step_dir(edge, node, inherited, start_is_endpoint):
  kind = edge['kind']
  if kind in MOVEMENT:
    if arrow_at(edge, node):
      return 'out'
    if kind in FLIP_INTO_IMPL and start_is_endpoint:
      return 'out'
    return 'in'
  if edge['provenance'] == 'terraform':
    return inherited
  return 'out' if arrow_at(edge, node) else 'in'


def fold(path, pairs, start_is_endpoint):
  vals = {'none'}
  for a, b in zip(path, path[1:]):
    cands = pairs.get((a, b), [])
    if not cands:
      return None
    nxt = set()
    for v in vals:
      for e in cands:
        nxt.add(step_dir(e, b, v, start_is_endpoint))
    vals = nxt
  return vals


BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out', 'artifacts.in', 'artifacts.out',
           'sameApi', 'siblingEndpoints', 'wiring']


def rows_of(doc):
  out = []
  for b in BUCKETS:
    part = doc[b.split('.')[0]][b.split('.')[1]] if '.' in b else doc[b]
    for x in part:
      out.append((b, x))
  return out


def check_dir(d):
  agree = bad = loose = nopath = bad_domain = 0
  examples = []
  for p in sorted(pathlib.Path(d).glob('*.json')):
    doc = json.loads(p.read_text())
    gp = pathlib.Path(doc['summary']['graph'])
    graph = json.loads(gp.read_text())
    pairs = {}
    for e in graph['edges']:
      pairs.setdefault((e['source'], e['target']), []).append(e)
      pairs.setdefault((e['target'], e['source']), []).append(e)
    sie = bool(doc['summary'].get('startIsEndpoint'))
    for b, r in rows_of(doc):
      path = r.get('path') or []
      if len(path) < 2:
        nopath += 1
        continue
      vals = fold(path, pairs, sie)
      if vals is None:
        nopath += 1
        continue
      if len(vals) > 1:
        loose += 1
        continue
      want = next(iter(vals))
      if r.get('direction') not in ('in', 'out', 'none'):
        bad_domain += 1
        continue
      if r['direction'] == want:
        agree += 1
      else:
        bad += 1
        if len(examples) < 4:
          examples.append(f'{p.name} {r["id"]} v1/記録={r["direction"]} 今回の規則なら={want}'
                          f' 欄={b} 経路={"|".join(path)}')
  return agree, bad, loose, nopath, bad_domain, examples


for d in sys.argv[1:]:
  agree, bad, loose, nopath, bad_domain, examples = check_dir(d)
  print(f'{d}: 一致 {agree} / 不一致 {bad} / 並行縁で不定 {loose} / 経路を読めない {nopath}'
        f' / 向き の値域外 {bad_domain}')
  for x in examples:
    print('   ', x)
