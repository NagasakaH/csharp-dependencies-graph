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
# ここに残る `out/` の入力は **作り直せるもの**（`out/demo/graph.json` は build.mjs、
# `out/elsa/graph.json` は elsa のグラフ生成、`out/perf-inputs/` は make-changed-list.py と
# make-v2-graph.py）と、人が「消さない」と決めた固定版 `out/wt-head/` だけ
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
    # 第 50 ラウンドで `out/tmp-r29/audit-full` の中身をここへ移した（元の名残は掃除してよい）
    'skill/scripts/tools/battery/baseline-v1', 'skill/scripts/tools/battery/v1diff.py',
    # 不変条件・順列・入れ替えの道具（第 50 ラウンド双人レビュー agy P2 で追跡下へ）
    'skill/scripts/tools/battery/README.md',
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
