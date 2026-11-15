#!/usr/bin/env python3
# report.mjs の経過時間と最大 RSS を 5 回測って中央値・最大を出す（性能ゲートの測定 1 組）。
# 使い方:
#   python3 skill/scripts/tools/perf-measure.py <タグ> [条件]
#   CGD_REPORT=<前の report.mjs>     ... 比較元に前の版を差し替える
#   CGD_PERF_DIR=<out/tmp-perf>      ... 生ログと集計の書き先（既定 out/tmp-perf）
#   python3 skill/scripts/tools/perf-measure.py --inputs   ... 必要な入力パスを 1 行 1 件で出す
#
# 第 50 ラウンド双人レビュー（Codex 指摘 F4）で、この測定道具の唯一のコピーが `out/tmp-*`
# （ディスク掃除の対象）にあると指摘された。`out/tmp-r26/perf.py` の追跡下における正式版。
# 前版からの違い:
#   - **入力の存在を測る前に自分で確かめる**。第 48 ラウンドでは入力（`--changed` の変更一覧）が
#     消えて 250 回すべて ENOENT・終了 1 なのに、集計が倍率だけを見てゲートが「適合」になった。
#     入力が無ければ**測らずに**終了 1。条件が黙って減る形（`if os.path.exists(...)` で
#     ケースを足していた前版の `v2-mix`）も同じ事故なので、条件は 4 とおりに固定した
#   - `v2-mix` の入力は `out/perf-inputs/v2-big.graph.json`（`skill/scripts/tools/make-v2-graph.py`
#     で作り直せる）。`out/tmp-r26/` の残骸は測定の入力にしない
import json, os, pathlib, resource, statistics, subprocess, sys, time

PERF_DIR = os.environ.get('CGD_PERF_DIR', 'out/tmp-perf')
CASES = {
    'demo-api': ['--graph', 'out/demo/graph.json', '--api', 'POST /orders'],
    # 入力は out/perf-inputs/ に固定（レビュー用クローンは掃除で消える。第 48 ラウンドで
    # 全 250 回 ENOENT だった）。再生成:
    #   python3 skill/scripts/tools/make-changed-list.py out/elsa/graph.json out/perf-inputs/elsa-50.txt
    'elsa-50': ['--graph', 'out/elsa/graph.json', '--changed', 'out/perf-inputs/elsa-50.txt'],
    'elsa-folder': ['--graph', 'out/elsa/graph.json', '--from', 'folder:.', '--limit', '100000'],
    # 再生成: python3 skill/scripts/tools/make-v2-graph.py out/perf-inputs/v2-big.graph.json
    'v2-mix': ['--graph', 'out/perf-inputs/v2-big.graph.json', '--api', 'POST /v2/a7/r3'],
}
REPORT = os.environ.get('CGD_REPORT', 'skill/scripts/report.mjs')


def inputs():
    """ゲートが事前に確かめる入力パス（測定側とゲート側で条件表を二重に持たない）"""
    paths = {REPORT}
    for args in CASES.values():
        for i, a in enumerate(args):
            if a in ('--graph', '--changed', '--from-list'):
                paths.add(args[i + 1])
    return sorted(paths)


def check_inputs():
    missing = [p for p in inputs() if not pathlib.Path(p).exists()]
    if missing:
        print('[perf] 入力が無いので測らない（測ると失敗が中央値に混ざる）:', file=sys.stderr)
        for p in missing:
            print(f'  - {p}', file=sys.stderr)
        print('  作り直し: out/demo/graph.json は build.mjs --root demo --annotation '
              'skill/examples/annotations.orders-api.json --annotation '
              'skill/examples/annotations.storage.json / out/elsa/graph.json は elsa のグラフ生成 / '
              'out/perf-inputs/elsa-50.txt は make-changed-list.py / '
              'out/perf-inputs/v2-big.graph.json は make-v2-graph.py', file=sys.stderr)
    return missing


def one(args):
    t0 = time.perf_counter()
    p = subprocess.run(['node', REPORT] + args + ['--json', os.devnull],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    dt = time.perf_counter() - t0
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return p.returncode, dt, ru.ru_maxrss / 1024.0 / 1024.0   # macOS の ru_maxrss はバイト。MB に直す


def main():
    if sys.argv[1:2] == ['--cases']:
        for c in CASES:
            print(c)
        return 0
    if sys.argv[1:2] == ['--inputs']:
        for p in inputs():
            print(p)
        return 0
    # 注意: getrusage(RUSAGE_CHILDREN) の ru_maxrss は「このプロセスが見た子プロセスの最大値」の
    # 単調増加。1 プロセスで複数ケースを測ると後勝ちになるので、**1 ケース 1 プロセス**で呼ぶ
    tag = sys.argv[1] if len(sys.argv) > 1 else 'run'
    only = sys.argv[2] if len(sys.argv) > 2 else None
    if only and only not in CASES:
        print(f'[perf] 知らない条件: {only}（選べるのは {", ".join(CASES)}）', file=sys.stderr)
        return 2
    if check_inputs():
        return 1
    sel = CASES if not only else {only: CASES[only]}
    out = {}
    for label, args in sel.items():
        one(args)                      # ウォームアップ 1 回
        rows = [one(args) for _ in range(5)]
        ts = sorted(r[1] for r in rows)
        out[label] = {'秒_中央値': round(statistics.median(ts), 4), '秒_最大': round(ts[-1], 4),
                      '最大RSS_MB': round(max(r[2] for r in rows), 1),
                      '失敗': sum(1 for r in rows if r[0] != 0), 'コマンド': ' '.join(args)}
    if only:
        print(json.dumps(out, ensure_ascii=False))
        return 1 if any(v['失敗'] for v in out.values()) else 0
    path = f'{PERF_DIR}/perf-{tag}.json'
    pathlib.Path(PERF_DIR).mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False))
    return 1 if any(v['失敗'] for v in out.values()) else 0


if __name__ == '__main__':
    sys.exit(main())
