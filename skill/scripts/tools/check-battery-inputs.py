#!/usr/bin/env python3
# 回帰バッテリー（`out/loop/protocol.md` §4-3）が読むファイルが揃っているか先に確かめる。
#   python3 skill/scripts/tools/check-battery-inputs.py
# 終了 1 で、無いファイルを全部挙げる。
#
# なぜ有るか: 第 48 ラウンドで `--changed` の入力（レビュー用クローンに置いていた変更一覧）が
# ディスク掃除で消え、性能ゲートの 250 回がすべて ENOENT なのに倍率 1.00 で「適合」した。
# バッテリーの道具と基準データは現在 `out/tmp-*`（掃除対象）に置いているので、同じ形で作動停止が
# 起こり得る。実行前に総点検しておくと「黙って前版を測る」「黙って条件が減る」の前に止まる。
# 追跡下にあるもの（`skill/scripts/` と `out/perf-inputs/`）も一緒に見る
import pathlib
import sys

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
    'skill/scripts/tools/paired-gate.sh',
    # 性能ゲートの入力と固定した旧版
    'out/wt-head/skill/scripts/report.mjs',
    'out/perf-inputs/elsa-50.txt', 'out/perf-inputs/v2-big.graph.json',
    'out/demo/graph.json', 'out/elsa/graph.json',
    # v1 比較の基準（人が「差し替えない」と決めたもの）と照合スクリプト
    'out/tmp-r29/audit-full', 'out/tmp-r29/v1diff.py',
    # 不変条件・順列・入れ替えの道具（掃除対象に置いたままの分）
    'out/tmp-r46/check-invariants46.py', 'out/tmp-r46/self-consistency.py',
    'out/tmp-r46/check-dir-rule.py', 'out/tmp-r46/count-none.py',
    'out/tmp-r44/allperm.py', 'out/tmp-r44/allperm-corr.py',
    'out/tmp-r44/min-0.json', 'out/tmp-r44/min-2.json', 'out/tmp-r44/cmp-head-proto.py',
    'out/tmp-r47/allperm-full.py', 'out/tmp-r48/find-splits-r48.py',
    'out/tmp-r40/via-cycle.py', 'out/tmp-r43/r43-permute.py', 'out/tmp-r43/same-output.py',
    'out/tmp-r43/r43-before.mjs',
]

missing = [p for p in FILES if not pathlib.Path(p).exists()]
if missing:
    print(f'バッテリーの入力が {len(missing)} 件無い（無い状態で走ると、黙って前版を測るか、'
          '黙って条件が減る）:', file=sys.stderr)
    for p in missing:
        print(f'  - {p}', file=sys.stderr)
    print('out/tmp-* はディスク掃除の対象。git 履歴から取り戻すか（追跡下のものは '
          'git checkout -- <パス>）、掃除で消えたものはもう一度同じ道具として作り直して使う',
          file=sys.stderr)
    raise SystemExit(1)
print(f'バッテリーの入力 {len(FILES)} 件が揃っている')
