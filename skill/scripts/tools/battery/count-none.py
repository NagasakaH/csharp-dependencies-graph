# 18 レポートの `向き = none` の行を数えて、裁定の再集計（441 行中 28 行 /
# 同じ API 17 / 定義上の関連 9 / 兄弟 2 / うち tier=primary 2）と突き合わせる。
# 使い方: python3 skill/scripts/tools/battery/count-none.py <レポートディレクトリ>
import json
import pathlib
import sys
from collections import Counter

import _inputs as IN


if len(sys.argv) > 1:
    AUDIT = pathlib.Path(sys.argv[1])
else:
    # 既定を out/tmp-* にしない（掃除で消えた場所を黙って指す）。渡されたディレクトリだけ見る
    print('使い方: python3 skill/scripts/tools/battery/count-none.py <レポートディレクトリ>')
    raise SystemExit(1)
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out', 'artifacts.in', 'artifacts.out',
           'sameApi', 'siblingEndpoints', 'wiring']
# 裁定（out/review-astra46.log）の再集計
RULING = {'rows': 441, 'none': 28, 'sameApi': 17, 'wiring': 9, 'siblingEndpoints': 2, 'primary': 2}
LABEL = {'sameApi': '同じ API', 'siblingEndpoints': '兄弟', 'wiring': '定義上の関連'}

total_rows = 0
none_rows = []
by_bucket = Counter()
per_file = Counter()
bad_counters = []
REPORTS = IN.report_paths(AUDIT, expect=18, what='向き none 数えのレポート')
for p in REPORTS:
  doc = json.loads(p.read_text())
  s = doc['summary']
  total_rows += s['rows']
  rows = []
  for b in BUCKETS:
    part = doc[b.split('.')[0]][b.split('.')[1]] if '.' in b else doc[b]
    for x in part:
      rows.append((b, x))
  got = [(b, x) for b, x in rows if x['direction'] == 'none']
  for b, x in got:
    if '.' in b:                      # external / entries / artifacts は 向き で割る欄
      bad_counters.append((p.name, f'none の行が方向を持つ欄 {b} にある: {x["id"]}'))
    by_bucket[b] += 1
    per_file[p.name] += 1
    none_rows.append((p.name, x['id'], b, x['tier'], x['hops'], (x['evidence'] or {})['kind']))
  if s.get('directionless') is None:
    bad_counters.append((p.name, 'directionless が無い'))
  elif s['directionless'] != len(got) and not s.get('listTruncated'):
    bad_counters.append((p.name, f"directionless={s['directionless']} 実測={len(got)}"))
  pri = sum(1 for _, x in got if x['tier'] == 'primary')
  if s.get('directionlessPrimary') is not None and not s.get('listTruncated') \
      and s['directionlessPrimary'] != pri:
    bad_counters.append((p.name, f"directionlessPrimary={s['directionlessPrimary']} 実測={pri}"))

print(f'レポート {len(REPORTS)} 件 / 総行数 {total_rows}'
      f'（裁定の再集計 {RULING["rows"]} 行）')
print(f'none の行 {len(none_rows)} 件（裁定 {RULING["none"]} 件）')
for b in ['sameApi', 'wiring', 'siblingEndpoints']:
  print(f'  {LABEL[b]:<12} {by_bucket[b]} 件（裁定 {RULING[b]} 件）')
print(f'  うち tier=primary {sum(1 for r in none_rows if r[3] == "primary")} 件'
      f'（裁定 {RULING["primary"]} 件）')
print('内訳（ none の行が方向を持つ欄に並んでいないかもここで見る）:')
for b, c in sorted(by_bucket.items()):
  print(f'  欄 {b}: {c}')
print('レポート別:')
for f, c in sorted(per_file.items()):
  print(f'  {f}: {c}')
for r in none_rows:
  print(f'  * {r[0]} {r[1]} 欄={r[2]} tier={r[3]} 段={r[4]} 根拠={r[5]}')
print(f'サマリカウンタ不一致 {len(bad_counters)} 件')
for b in bad_counters:
  print(f'  {b}')
agree = (total_rows == RULING['rows'] and len(none_rows) == RULING['none']
         and by_bucket['sameApi'] == RULING['sameApi'] and by_bucket['wiring'] == RULING['wiring']
         and by_bucket['siblingEndpoints'] == RULING['siblingEndpoints']
         and sum(1 for r in none_rows if r[3] == 'primary') == RULING['primary'])
print('裁定の再集計と一致' if agree else '裁定の再集計と**不一致**（1 行ずつ説明が必要）')
sys.exit(0 if agree and not bad_counters else 1)
