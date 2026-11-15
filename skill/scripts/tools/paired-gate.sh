#!/usr/bin/env bash
# 性能の相対ゲート: 固定した変更前版と新版の report.mjs を、同じ 4 条件で 5 組交互に測る。
#   使い方: bash skill/scripts/tools/paired-gate.sh <タグ>      （タグは毎回新しくする）
#   CGD_GATE_OLD=<前の report.mjs>   ... 既定 out/wt-head/skill/scripts/report.mjs（コミット a44b7c7）
#   CGD_PERF_DIR=<out/tmp-perf>      ... 生ログと集計の書き先
# 判定（1 つでも外れれば終了 1）:
#   1. 測る前に**入力の存在**を確かめる（無ければ測らない。第 48 ラウンドで、入力が消えて
#      250 回すべて ENOENT・終了 1 なのに倍率 1.00 で「適合」になった。Codex 指摘）
#   2. 同じタグの結果が既に有れば断る（生ログは追記なので、使い回すと前の標本が混ざる）
#   3. 子プロセスの失敗回数が 1 件でもあれば不合格（倍率を見る前に落とす）
#   4. 条件ごとの倍率（新 / 旧）の中央値が 1.20 を越えたら不合格
#   5. 新側の最大 RSS が 800 MB を越えたら不合格
# ほかの測定と同時実行しない（他プロセスが混ざると倍率が読めない）
set -euo pipefail
tag="${1:?使い方: paired-gate.sh <タグ>（毎回新しいタグ。前の標本と混ざる）}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$root"
export DOTNET_ROOT=${DOTNET_ROOT:-$HOME/.dotnet}
export PATH="$DOTNET_ROOT:$PATH"
dir="${CGD_PERF_DIR:-out/tmp-perf}"
old="${CGD_GATE_OLD:-$PWD/out/wt-head/skill/scripts/report.mjs}"
new="$PWD/skill/scripts/report.mjs"

missing=0
for f in "$old" "$new" $(python3 skill/scripts/tools/perf-measure.py --inputs); do
  test -f "$f" || { echo "入力が無い: $f"; missing=1; }
done
[ "$missing" = 0 ] || exit 1
for i in 1 2 3 4 5; do
  for side in old new; do
    [ -e "$dir/perf-${tag}-${side}${i}.json" ] && {
      echo "タグ ${tag} の組 ${i}（${side}）は既に有る。使い回すと前の標本が混ざるので新しいタグを使ってください"
      exit 1; }
  done
done

for i in 1 2 3 4 5; do
  if (( i % 2 == 1 )); then
    CGD_REPORT="$old" bash skill/scripts/tools/perf-run.sh "${tag}-old${i}" >/dev/null
    CGD_REPORT="$new" bash skill/scripts/tools/perf-run.sh "${tag}-new${i}" >/dev/null
  else
    CGD_REPORT="$new" bash skill/scripts/tools/perf-run.sh "${tag}-new${i}" >/dev/null
    CGD_REPORT="$old" bash skill/scripts/tools/perf-run.sh "${tag}-old${i}" >/dev/null
  fi
  echo "組 $i 完了 $(date +%H:%M:%S) load: $(uptime | sed 's/.*users,//')"
done

CGD_PERF_DIR="$dir" python3 - "$tag" <<'PY'
import json, os, statistics, subprocess, sys

tag, d = sys.argv[1], os.environ['CGD_PERF_DIR']
conds = subprocess.run(['python3', 'skill/scripts/tools/perf-measure.py', '--cases'],
                       text=True, capture_output=True, check=True).stdout.split()


def load(t):
    with open(f'{d}/perf-{tag}-{t}.json', encoding='utf-8') as f:
        return json.load(f)


bad = []
print('| 条件 | 旧 5 組中央値 | 新 5 組中央値 | 組ごとの倍率 | 倍率の中央値 | 判定（1.20 以内） '
      '| 失敗回数 旧・新 | 旧 RSS | 新 RSS |')
print('| --- | --- | --- | --- | --- | --- | --- | --- | --- |')
for c in conds:
    old = [load(f'old{i}')[c] for i in range(1, 6)]
    new = [load(f'new{i}')[c] for i in range(1, 6)]
    for side, rows in (('旧', old), ('新', new)):
        for i, r in enumerate(rows, 1):
            # 組ごとの集計ファイルには**その組の 1 標本**が入る（標本 5 本は 5 ファイルに分かれている）。
            # 第 48 ラウンドのような「入力が消えて全実行失敗でも倍率が読める」をここで落とす
            if r.get('失敗', 0) != 0 or r.get('n', 0) < 1:
                bad.append(f'{c} {side} 組 {i}: 失敗 {r.get("失敗")} 回 / 標本 {r.get("n")} 本'
                           f'（コマンド {r.get("コマンド")}）')
    ratios = [n['秒_中央値'] / o['秒_中央値'] for o, n in zip(old, new)]
    med = statistics.median(ratios)
    if med > 1.20:
        bad.append(f'{c}: 倍率の中央値 {med:.2f} が 1.20 を超過')
    rss = max(x['最大RSS_MB'] for x in new)
    if rss > 800:
        bad.append(f'{c}: 新側の最大 RSS {rss:.1f} MB が 800 MB を超過')
    print(f"| {c} | {statistics.median(x['秒_中央値'] for x in old):.4f} "
          f"| {statistics.median(x['秒_中央値'] for x in new):.4f} "
          f"| {' / '.join(f'{r:.2f}' for r in ratios)} | {med:.2f} "
          f"| {'適合' if med <= 1.20 else '**超過**'} "
          f"| {sum(x['失敗'] for x in old)}・{sum(x['失敗'] for x in new)} "
          f"| {max(x['最大RSS_MB'] for x in old):.1f} MB | {rss:.1f} MB |")
print('load:', subprocess.run(['uptime'], text=True, capture_output=True).stdout.split('users,')[-1].strip())
if bad:
    print('ゲート不合格:')
    for b in bad:
        print('  -', b)
    raise SystemExit(1)
print(f'ゲート合格（{len(conds)} とおり・失敗 0 回・倍率中央値すべて 1.20 以内・RSS 800 MB 以内）')
PY
