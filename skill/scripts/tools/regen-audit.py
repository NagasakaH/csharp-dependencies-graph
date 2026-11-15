#!/usr/bin/env python3
# 保存済み 18 条件（既定 `out/tmp-r29/audit-full`）で今の report.mjs を走らせ、指定ディレクトリへ
# レポート JSON を再生成する。条件は保存済みレポートの `summary`（graph / hops / wiringHops /
# limit）と `starts[].id` から復元する。**この 18 条件に限った復元**である（元の引数配列・標準入力・
# 入力グラフのハッシュは保存していないので、汎用の再生成には使えない。第 48 ラウンド Codex 意見）
#
#   python3 skill/scripts/tools/regen-audit.py <report.mjs> <出力ディレクトリ> [--force]
#
# 出力先に基準ディレクトリ自身を渡すと比較相手ごと壊すので拒否する。中身のあるディレクトリも
# 黙って上書きしない（`--force` が要る）。子プロセスが 1 件でも非 0 で終われば非 0 で終了する
import json, os, pathlib, subprocess, sys

args = [a for a in sys.argv[1:] if a != '--force']
force = '--force' in sys.argv
script = args[0] if len(args) > 0 else 'skill/scripts/report.mjs'
base = pathlib.Path(os.environ.get('CGD_AUDIT_BASE', 'out/tmp-r29/audit-full'))
out = pathlib.Path(args[1] if len(args) > 1 else 'out/tmp-r29/audit')
if not base.is_dir():
    raise SystemExit(f'条件の保存先が無い: {base}')
if out.resolve() == base.resolve():
    raise SystemExit(f'出力先に基準ディレクトリ {base} は使えない（比較相手を壊す）')
if out.exists() and any(out.glob('*.json')) and not force:
    raise SystemExit(f'{out} に既に JSON がある（上書きするには --force）')
out.mkdir(parents=True, exist_ok=True)

n = 0
for p in sorted(base.glob('*.json')):
    doc = json.loads(p.read_text(encoding='utf-8'))
    s = doc['summary']
    cmd = ['--graph', s['graph'], '--hops', str(s['hops']), '--wiring-hops', str(s['wiringHops']),
           '--limit', str(s.get('limit') or 100000)]
    for item in doc['starts']:
        cmd += ['--from', item['id']]
    q = subprocess.run(['node', script] + cmd + ['--json', str(out / p.name)],
                       cwd=os.path.abspath('.'), capture_output=True, text=True)
    if q.returncode != 0:
        raise SystemExit(f'{p.name} 失敗（終了コード {q.returncode}）: {q.stderr[-400:]}')
    n += 1
if n == 0:
    raise SystemExit(f'{base} に JSON が 1 件もない')
print(f'レポート {n} 件を {out} へ再生成')
