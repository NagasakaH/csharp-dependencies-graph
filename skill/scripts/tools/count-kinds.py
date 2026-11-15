#!/usr/bin/env python3
# レポート JSON の枠別・縁別の延べ回数を出す（`skill/reference/review-workflows.md` の枠表の根拠）。
# 使い方: python3 skill/scripts/tools/count-kinds.py <監査ディレクトリ>
#   例: python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs out/tmp-r49/audit
#       python3 skill/scripts/tools/count-kinds.py out/tmp-r49/audit
import collections, glob, json, sys

if len(sys.argv) < 2:
    raise SystemExit('使い方: count-kinds.py <監査ディレクトリ>')
root = sys.argv[1]
files = sorted(glob.glob(f'{root}/*.json'))
if not files:
    raise SystemExit(f'{root} に JSON が無い')
PAIR = [('external', 'in'), ('external', 'out'), ('entries', 'in'), ('entries', 'out'),
        ('artifacts', 'in'), ('artifacts', 'out')]
FLAT = ['sameApi', 'siblingEndpoints', 'wiring']
cnt = collections.defaultdict(collections.Counter)
for p in files:
    d = json.load(open(p, encoding='utf-8'))
    for sec, side in PAIR:
        for r in d[sec][side]:
            cnt[f'{sec}.{side}'][(r['evidence'] or {}).get('kind')] += 1
    for k in FLAT:
        for r in d[k]:
            cnt[k][(r['evidence'] or {}).get('kind')] += 1
print(f'レポート {len(files)} 件（{root}）')
for k in ['external.out', 'external.in', 'entries.out', 'entries.in', 'artifacts.out',
          'artifacts.in', 'sameApi', 'siblingEndpoints', 'wiring']:
    print(f'{k:18s}', ' / '.join(f'{kind} {c}' for kind, c in cnt[k].most_common()) or '（縁なし）')
