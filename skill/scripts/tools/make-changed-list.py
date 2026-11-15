#!/usr/bin/env python3
# 性能ゲートの `--changed` 入力（変更ファイル一覧）をグラフから決定的に作る。
# 使い方: python3 skill/scripts/tools/make-changed-list.py <graph.json> <出力.txt> [本数=50]
# ファイルノードのパスを並び順で均等にすくう（先頭から取ると 1 つのプロジェクトに偏るため）。
# **ゲートの入力をレビュー用クローンなどの掃除対象に置かない**こと（第 48 ラウンドで
# 入力ごと消えて、250 回すべて失敗したままゲートが「適合」になった）
import json, sys

if len(sys.argv) < 3:
    raise SystemExit('使い方: make-changed-list.py <graph.json> <出力.txt> [本数]')
src, dst = sys.argv[1], sys.argv[2]
want = int(sys.argv[3]) if len(sys.argv) > 3 else 50
g = json.load(open(src, encoding='utf-8'))
paths = sorted({n['path'] for n in g['nodes'] if n.get('kind') == 'file' and n.get('path')})
if len(paths) < want:
    raise SystemExit(f'{src} のファイルノードが {len(paths)} 本しか無く {want} 本取れない')
step = len(paths) / want
picked = [paths[int(i * step)] for i in range(want)]
open(dst, 'w', encoding='utf-8').write('\n'.join(picked) + '\n')
print(f'{dst} に {len(picked)} 本（{src} のファイルノード {len(paths)} 本から等間隔）')
