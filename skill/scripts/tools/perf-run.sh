#!/usr/bin/env bash
# 1 条件 5 回を測って 1 組に集計する（性能ゲートの測定単位。ゲートはこれを旧・新で交互に呼ぶ）
#   使い方: bash skill/scripts/tools/perf-run.sh <タグ>
#   CGD_REPORT=<report.mjs> で測る対象を差し替える / CGD_PERF_DIR で書き先を変える
#
# 第 50 ラウンドで `out/tmp-r26/perf-run.sh` から移した追跡下版。違いは 2 つ:
#   - `cd /Users/haoming/...` の**絶対パス固定をなくした**（レビュー用のクローンで別の人の
#     ホームでも動くように、スクリプトの位置からリポジトリの根を求める）
#   - 条件を減らさない。入力が無ければ perf-measure.py が測らずに終了 1 になるので、
#     ここが非 0 で止まる（前版は `[ -f ... ] && cases=...` で黙って 3 条件になっていた）
set -euo pipefail
tag="${1:?使い方: perf-run.sh <タグ>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$root"
dir="${CGD_PERF_DIR:-out/tmp-perf}"
mkdir -p "$dir"
for c in demo-api elsa-50 elsa-folder v2-mix; do
  python3 skill/scripts/tools/perf-measure.py "r-${c}" "$c" >> "$dir/perf-raw-${tag}.jsonl"
done
python3 - "$tag" "$dir" <<'PY'
import collections, json, statistics, sys
tag, d = sys.argv[1], sys.argv[2]
runs = collections.defaultdict(lambda: {'t': [], 'rss': [], 'bad': 0, 'cmd': '', 'n': 0})
with open(f'{d}/perf-raw-{tag}.jsonl', encoding='utf-8') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        for k, v in json.loads(line).items():
            runs[k]['t'].append(v['秒_中央値'])
            runs[k]['rss'].append(v['最大RSS_MB'])
            runs[k]['bad'] += v['失敗']
            runs[k]['cmd'] = v['コマンド']
            runs[k]['n'] += 1
out = {k: {'秒_中央値': round(statistics.median(v['t']), 4),
           '秒_最大': round(max(v['t']), 4),
           '最大RSS_MB': round(max(v['rss']), 1), '失敗': v['bad'], 'コマンド': v['cmd'],
           'n': v['n']} for k, v in runs.items()}
json.dump(out, open(f'{d}/perf-{tag}.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
print(json.dumps(out, ensure_ascii=False, indent=1))
PY
