# v1 の出力契約が変わっていないかの突き合わせ（第 29 ラウンドの更新後基準）。
# 基準値は skill/scripts/tools/battery/baseline-v1（第 24 ラウンドの監査レポートを第 29
# ラウンドの裁定で作り直したもの。**人が「差し替えない」と決めた基準**で、第 50 ラウンドまで
# 一時ディレクトリ（第 29 ラウンドの監査出力）に有った唯一のコピーをここへ移した
# （掃除で消える場所には置かない）。
# 同じ条件で今の report.mjs を走らせ、行（id / 向き / tier / 段数 / 根拠の縁）と欄の件数を比べる。
import json, os, pathlib, subprocess, sys

import _inputs as IN

BASE = pathlib.Path(os.environ.get('CGD_AUDIT_BASE', 'skill/scripts/tools/battery/baseline-v1'))
OUT = pathlib.Path(os.environ.get('CGD_AUDIT_OUT', 'out/audit-current'))
OUT.mkdir(parents=True, exist_ok=True)
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out',
           'artifacts.in', 'artifacts.out', 'sameApi', 'siblingEndpoints', 'wiring']

def rows_of(r):
    out = {}
    for b in BUCKETS:
        part = r[b.split('.')[0]][b.split('.')[1]] if '.' in b else r[b]
        for x in part:
            out[x['id']] = (b, x['direction'], x['tier'], x['hops'], (x['evidence'] or {}).get('kind'))
    return out

diffs = []
REPORTS = IN.report_paths(BASE, expect=18, what='v1 基準の 18 条件')
for p in REPORTS:
    old = json.loads(p.read_text())
    s = old['summary']
    args = ['node', str(IN.require_script(os.environ.get('CGD_V1DIFF_REPORT', 'skill/scripts/report.mjs'))),
            '--graph', str(IN.graph_path(s['graph'])),
            '--hops', str(s['hops']), '--wiring-hops', str(s['wiringHops']),
            '--limit', str(s.get('limit') or 100000)]
    for item in old['starts']:
        args += ['--from', item['id']]
    dest = OUT / p.name
    args += ['--json', str(dest)]
    run = subprocess.run(args, text=True, capture_output=True, cwd=str(IN.repo_root()))
    if run.returncode != 0:
        diffs.append((p.name, '実行失敗', run.stdout[-300:] + run.stderr[-300:]))
        continue
    new = json.loads(dest.read_text())
    o, n = rows_of(old), rows_of(new)
    for k in sorted(set(o) | set(n)):
        if o.get(k) != n.get(k):
            diffs.append((p.name, k, f'old={o.get(k)} new={n.get(k)}'))
    for key in ['rows', 'primaryIn', 'primaryOut', 'entryIn', 'entryOut', 'artifactsIn',
                'artifactsOut', 'wiring', 'sameApi', 'siblings', 'siblingEndpointsOnly', 'siblingDefs']:
        if s.get(key) != new['summary'].get(key):
            diffs.append((p.name, f"summary.{key}", f"old={s.get(key)} new={new['summary'].get(key)}"))
    if new['summary']['unresolved']:
        diffs.append((p.name, 'unresolved', 'true'))

print(f'レポート {len(REPORTS)} 件 / 差分 {len(diffs)} 件')
for d in diffs[:int(os.environ.get('CGD_V1DIFF_SHOW', '60'))]:
    print(' -', d[0], d[1], d[2] if len(d) > 2 else '')
sys.exit(1 if diffs else 0)
