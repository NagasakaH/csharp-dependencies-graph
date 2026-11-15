#!/usr/bin/env python3
# 保存済み 18 条件（既定 `skill/scripts/tools/battery/baseline-v1`）で今の report.mjs を走らせ、指定ディレクトリへ
# レポート JSON を再生成する。条件は保存済みレポートの `summary`（graph / hops / wiringHops /
# limit）と `starts[].id` から復元する。**この 18 条件に限った復元**である（元の引数配列・標準入力・
# 入力グラフのハッシュは保存していないので、汎用の再生成には使えない。第 48 ラウンド Codex 意見）
#
#   python3 skill/scripts/tools/regen-audit.py <report.mjs> <出力ディレクトリ> [--force]
#
# 出力先に基準ディレクトリ自身を渡すと比較相手ごと壊すので拒否する。中身のあるディレクトリも
# 黙って上書きしない（`--force` が要る）。子プロセスが 1 件でも非 0 で終われば非 0 で終了する
import json, os, pathlib, subprocess, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'battery'))
import _inputs as IN

args = [a for a in sys.argv[1:] if a != '--force']
force = '--force' in sys.argv
script = str(IN.require_script(args[0] if len(args) > 0 else None))
REPO = IN.repo_root()
base = IN.resolve_cli_path(os.environ.get('CGD_AUDIT_BASE'),
                           default='skill/scripts/tools/battery/baseline-v1')
out = IN.resolve_cli_path(args[1] if len(args) > 1 else None, default='out/audit-current')
if not base.is_dir():
    raise SystemExit(f'条件の保存先が無い: {base}')
if out.resolve() == base.resolve():
    raise SystemExit(f'出力先に基準ディレクトリ {base} は使えない（比較相手を壊す）')
if out.exists() and any(out.glob('*.json')) and not force:
    raise SystemExit(f'{out} に既に JSON がある（上書きするには --force）')
out.mkdir(parents=True, exist_ok=True)

# 条件の数を先に確かめる（1〜17 件を「成功」として再生成しない。第 52 ラウンド Codex P2）
n = 0
for p in IN.report_paths(base, expect=18, what='再生成する条件（baseline-v1）'):
    doc = json.loads(p.read_text(encoding='utf-8'))
    s = doc['summary']
    # `summary.graph` の記録パスが掃除で消えたものは移設した実体へ（第 51 ラウンド双人レビュー agy P2）
    cmd = ['--graph', str(IN.graph_path(s['graph'])), '--hops', str(s['hops']), '--wiring-hops', str(s['wiringHops']),
           '--limit', str(s.get('limit') or 100000)]
    for item in doc['starts']:
        cmd += ['--from', item['id']]
    q = subprocess.run(['node', script] + cmd + ['--json', str(out / p.name)],
                       cwd=str(REPO), capture_output=True, text=True)
    if q.returncode != 0:
        raise SystemExit(f'{p.name} 失敗（終了コード {q.returncode}）: {q.stderr[-400:]}')
    n += 1
if n == 0:
    raise SystemExit(f'{base} に JSON が 1 件もない')
print(f'レポート {n} 件を {out} へ再生成')
