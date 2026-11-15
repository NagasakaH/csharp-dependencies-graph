#!/usr/bin/env python3
# 回帰バッテリー（`out/loop/protocol.md` §4-3）が読むファイルが揃っているか先に確かめる。
#   python3 skill/scripts/tools/check-battery-inputs.py
# 終了 1 で、無いファイルを全部挙げる。
#
# なぜ有るか: 第 48 ラウンドで `--changed` の入力（レビュー用クローンに置いていた変更一覧）が
# ディスク掃除で消え、性能ゲートの 250 回がすべて ENOENT なのに倍率 1.00 で「適合」した。
# 実行前に総点検しておくと「黙って前版を測る」「黙って条件が減る」の前に止まる。
#
# 第 50 ラウンド双人レビュー（agy P2）で、バッテリーの道具と基準データは追跡下の
# `skill/scripts/tools/battery/` へ移した（`out/tmp-*` に唯一のコピーを置くのが事故の元凶）。
#
# 第 51 ラウンド双人レビュー（両名 P2）で、この点検の穴を塞いだ。
#   1. 手書きの一覧だけを見ていた。`baseline-v1` の 18 条件が `summary.graph` に記録している
#      入力グラフ（7 条件が一時ディレクトリを指していた）を点検しておらず、42/42 で通りながら
#      `regen-audit.py` / `v1diff.py` / `via-cycle.py` / `same-output.py` / `cmp-head-proto.py` /
#      `check-dir-rule.py` が壊れていた。→ 記録パスを `_inputs.graph_path()` で解決して実在を見る
#   2. 検査側の道具が入力にしている実グラフ（`_inputs.extra_graphs()`）が点検に入っていなかった
#      → 一覧を `_inputs.py` に一本化し、ここはそれを読む
#   3. 実行される道具のコードが掃除対象の場所を指していないかを機械で確かめていなかった
#      → `skill/scripts/tools/` の道具のソースを走査して古い一時パスの残りを挙げる
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'battery'))
import _inputs as IN

REPO = IN.repo_root()
FILES = [
    # スキル本体（追跡下）
    'skill/scripts/report.mjs', 'skill/scripts/query.mjs', 'skill/scripts/merge.mjs',
    'skill/scripts/build.mjs', 'skill/scripts/verify.mjs',
    'skill/scripts/test-analyzer.mjs', 'skill/scripts/test-merge.mjs',
    'skill/scripts/test-query.mjs', 'skill/scripts/test-terraform.mjs',
    'skill/scripts/test-report.mjs',
    'skill/scripts/tools/regen-audit.py', 'skill/scripts/tools/count-kinds.py',
    'skill/scripts/tools/make-changed-list.py', 'skill/scripts/tools/make-v2-graph.py',
    'skill/scripts/tools/perf-measure.py', 'skill/scripts/tools/perf-run.sh',
    'skill/scripts/tools/paired-gate.sh', 'skill/scripts/tools/check-battery-inputs.py',
    # 性能ゲートの入力と固定した旧版（人が「消さない」と決めたもの）
    'out/wt-head/skill/scripts/report.mjs',
    'out/perf-inputs/elsa-50.txt', 'out/perf-inputs/v2-big.graph.json',
    'out/demo/graph.json', 'out/elsa/graph.json',
    # v1 比較の基準（人が「差し替えない」と決めたもの）と照合スクリプト
    'skill/scripts/tools/battery/baseline-v1', 'skill/scripts/tools/battery/v1diff.py',
    # バッテリーの道具（第 50 / 51 ラウンド双人レビューで追跡下へ）
    'skill/scripts/tools/battery/README.md', 'skill/scripts/tools/battery/_inputs.py',
    'skill/scripts/tools/battery/check-invariants46.py',
    'skill/scripts/tools/battery/self-consistency.py',
    'skill/scripts/tools/battery/check-dir-rule.py',
    'skill/scripts/tools/battery/count-none.py',
    'skill/scripts/tools/battery/allperm.py', 'skill/scripts/tools/battery/allperm-corr.py',
    'skill/scripts/tools/battery/allperm-full.py', 'skill/scripts/tools/battery/cmp-head-proto.py',
    'skill/scripts/tools/battery/min-0.json', 'skill/scripts/tools/battery/min-2.json',
    'skill/scripts/tools/battery/find-splits.py', 'skill/scripts/tools/battery/via-cycle.py',
    'skill/scripts/tools/battery/r43-permute.py',
    'skill/scripts/tools/battery/r42-calls-0.json', 'skill/scripts/tools/battery/r42-calls-1.json',
    'skill/scripts/tools/battery/same-output.py', 'skill/scripts/tools/battery/r43-before.mjs',
    # `baseline-v1` が記録する入力グラフの実体（掃除で消える場所に有った唯一のコピー）
    'skill/scripts/tools/battery/graphs/ri.graph.json',
    'skill/scripts/tools/battery/graphs/ri0.graph.json',
    'skill/scripts/tools/battery/graphs/real.graph.json',
]

missing = [p for p in FILES if not (REPO / p).exists()]

# 18 条件が記録している入力グラフ（作者環境の一時出力先）が実在するか。
# 掃除や別クローンで壊れたら、ここで終了 1 にする（第 51 ラウンド agy P2）
base = REPO / 'skill' / 'scripts' / 'tools' / 'battery' / 'baseline-v1'
if base.is_dir():
    for p in sorted(base.glob('*.json')):
        rec = p.name
        try:
            got = IN.graph_path(json.loads(p.read_text())['summary']['graph'])
            if not got.exists():
                missing.append(f'{rec} の記録グラフ → {got}（解決先が無い）')
        except SystemExit as e:
            missing.append(f'{rec} の記録グラフ: {e}')

# 検査の道具が足す実グラフ（一覧は `_inputs.extra_graphs()` が正本）
for g in IN.extra_graphs(REPO):
    if not g.exists():
        missing.append(f'{g.relative_to(REPO)}（_inputs.extra_graphs が足す検査のグラフ）')

# 道具のソースに掃除対象の一時パスが残っていないか。保存済み条件（`baseline-v1`）の中の
# 記録パスは歴史の記録なので対象外。`_inputs.py` の対応表も移設の実体へ橋渡しするための記述
STALE = re.compile(r"out/tmp-r\d+/[^\s)`,、。]*?(?:graph\.json|audit-full)")
stale = []
tools = REPO / 'skill' / 'scripts' / 'tools'
for p in sorted(tools.rglob('*')):
    if not p.is_file() or p.suffix not in ('.py', '.sh', '.mjs'):
        continue
    if p.name == '_inputs.py':
        continue
    for i, line in enumerate(p.read_text(encoding='utf-8', errors='ignore').split('\n'), 1):
        for m in STALE.finditer(line):
            stale.append(f'{p.relative_to(REPO)}:{i}: {m.group(0)}')

if missing:
    print(f'バッテリーの入力が {len(missing)} 件無い（無い状態で走ると、黙って前版を測るか、'
          '黙って条件が減る）:', file=sys.stderr)
    for p in missing:
        print(f'  - {p}', file=sys.stderr)
    print('out/tmp-* はディスク掃除の対象。追跡下のものは git checkout -- <パス>、'
          '作り直せるものは README.md の手順（build.mjs / make-v2-graph.py / make-changed-list.py）で'
          '再生成して使う', file=sys.stderr)
    raise SystemExit(1)
if stale:
    print(f'バッテリーの道具 {len(stale)} 箇所に掃除対象の一時パスが有る'
          '（消えた日に黙って件数が減る。実体は skill/scripts/tools/battery/graphs/ へ移す）:',
          file=sys.stderr)
    for s in stale:
        print(f'  - {s}', file=sys.stderr)
    raise SystemExit(1)
print(f'バッテリーの入力 {len(FILES)} 件 + 記録グラフ {len(list(base.glob("*.json")))} 件 + '
      f'検査のグラフ {len(IN.extra_graphs(REPO))} 件が揃っている（道具のソースに一時パスの残り 0 件）')
