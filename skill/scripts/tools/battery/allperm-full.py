#!/usr/bin/env python3
# 縁順の全順列で **レポート JSON 全体**を突き合わせる（第 46 ラウンド双人レビュー P2）。
# `skill/scripts/tools/battery/allperm-corr.py` は行の id / 欄 / 向き / 段数 / 対応 / 向き変え / 根拠縁 id
# だけを比べ、中立 3 欄（sameApi / siblingEndpoints / wiring）と JSON の形（`evidence` に
# `metadata` や `count` が混ざる問題）を見ていなかった。ここでは生 JSON を正規化して丸ごと比べる。
#
# 使い方: python3 skill/scripts/tools/battery/allperm-full.py <report.mjs> <ケース json> [順列上限]
#   順列上限は既定 720。**2 以上**を渡す（1 を渡すと間引き後に比較が起きないので終了 1）
def _diff(ra, rb):
    if ra is None: return '行が無い → 有る'
    if rb is None: return '行が有る → 無い'
    return ' / '.join(f"{k}: {ra.get(k)!r}→{rb.get(k)!r}"
                      for k in sorted(set(ra) | set(rb)) if ra.get(k) != rb.get(k))
import json, sys, itertools, tempfile, os, collections

import _inputs as IN

REPO = IN.repo_root()
if len(sys.argv) < 3:
    raise SystemExit('使い方: python3 skill/scripts/tools/battery/allperm-full.py '
                     '<report.mjs> <ケース json> [順列上限（既定 720。2 以上）]')
# 対象と入力の所在を先に確かめる（第 52 ラウンド agy: 入力が無いと Traceback になっていた）
script = str(IN.require_script(sys.argv[1]))
graph_file = str(IN.require(IN.resolve_cli_path(sys.argv[2], default=None),
                            '順列検査のケース', want_file=True))
cap = int(sys.argv[3]) if len(sys.argv) > 3 else 720
case = json.load(open(graph_file))
extra = case.get('extra', [])
g = case['graph']

# 順列で変わり得ない外部要因（一時ファイルのパス・実行時刻・実行環境）を落として比べる
VOLATILE = ('graph', 'generatedAt', 'elapsedMs', 'graphPath', 'outDir')

def norm(doc):
    d = json.loads(json.dumps(doc))          # ディープコピー
    s = d.get('summary', {})
    for k in VOLATILE:
        s.pop(k, None)
    return json.dumps(d, sort_keys=True, ensure_ascii=False)

def run(edges):
    # 失敗を文字列で返して正常 JSON と混ぜて比較すると、**全実行失敗でも「1 通り = 完全一致」に
    # なる**（第 47 ラウンド Codex 指摘。`python3 skill/scripts/tools/battery/allperm-full.py /nonexistent/report.mjs
    # skill/scripts/tools/battery/min-2.json 24` が 24 回すべて失敗して終了コード 0 だった）。失敗はここで出す
    gg = dict(g); gg['edges'] = edges
    # 子の JSON は `IN.run_json` で読む（実行失敗を文字列として戻さないので、
    # **全実行失敗でも「1 通り = 完全一致」**になる形に戻らない。第 55 ラウンド agy 指摘）
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'g.json')
        with open(path, 'w') as f:
            json.dump(gg, f)
        d = IN.run_json(script, ['--graph', path, *extra], os.path.join(td, 'r.json'),
                        repo=REPO, label='allperm-full.py（縁順 1 とおりの実行）')
    # 9 欄すべて空の JSON を「判定: JSON 完全一致」で合格にしない（第 54 ラウンド agy 指摘 2）
    ids = [r['id'] for b in ('external', 'entries', 'artifacts') for s in ('in', 'out')
           for r in d[b][s]] + [r['id'] for b in ('sameApi', 'siblingEndpoints', 'wiring')
                                for r in d.get(b, [])]
    IN.require_comparison_rows(ids, 'allperm-full.py（縁順 1 とおりの実行）', what='レポートの行')
    return norm(d)

all_perms = list(itertools.permutations(range(len(g['edges']))))
# 縁が 1 本だと順列は 1 とおりしか無く「1 通り = 完全一致」が空振りになる
# （allperm.py / allperm-corr.py と同じ決まり。第 55 ラウンド agy 指摘）
IN.permutation_guards(len(g['edges']), None, None, 'allperm-full.py')
perms = all_perms
if len(perms) > cap:
    step = len(perms) // cap
    perms = perms[::step][:cap]
# 間引いたあとの**実際に走る通り数**を見る（第 56 ラウンド Codex P2-2: 上限 1 では
# 「縁順 1 通り / レポート JSON 1 通り / 判定: JSON 完全一致」で終了 0 になった）
IN.require_sampled_runs(len(perms), 'allperm-full.py', cap)
res = collections.OrderedDict()
for perm in perms:
    res[','.join('e%d' % i for i in perm)] = run([g['edges'][i] for i in perm])
# 上限で間引いていないときだけ、走った順列の通り数も期待値と突き合わせる
if len(perms) == len(all_perms):
    IN.permutation_guards(len(g['edges']), len(res), None, 'allperm-full.py')

uniq = collections.defaultdict(list)
for k, v in res.items():
    uniq[v].append(k)
print(f"縁順 {len(res)} 通り / レポート JSON {len(uniq)} 通り")
if len(uniq) > 1:
    base = list(uniq)[0]
    for v, ks in list(uniq.items())[1:]:
        a, b = json.loads(base), json.loads(v)
        bad = []
        for bkt in ('external', 'entries', 'artifacts'):
            for side in ('in', 'out'):
                da = {r['id']: r for r in a[bkt][side]}
                db = {r['id']: r for r in b[bkt][side]}
                for i in sorted(set(da) | set(db)):
                    if da.get(i) != db.get(i):
                        bad.append(f"{bkt}.{side}/{i}: {_diff(da.get(i), db.get(i))}")
        for bkt in ('sameApi', 'siblingEndpoints', 'wiring'):
            da = {r['id']: r for r in a[bkt]}
            db = {r['id']: r for r in b[bkt]}
            for i in sorted(set(da) | set(db)):
                if da.get(i) != db.get(i):
                    bad.append(f"{bkt}/{i}: {_diff(da.get(i), db.get(i))}")
        sa, sb = a['summary'], b['summary']
        for k in sorted(set(sa) | set(sb)):
            if sa.get(k) != sb.get(k):
                bad.append(f"summary.{k}: {sa.get(k)!r} → {sb.get(k)!r}")
        print(f"  割れ {len(ks)} 並び（例 {ks[0]}）: {bad[:6]}")
print('判定:', 'JSON 完全一致' if len(uniq) == 1 else '割れあり')
# 検査器が通っただけで終了コード 0 を返すと、上の print を読まない運用（ゲートの合否を
# 終了コードで受ける約束）で素通りする。割れたら必ず非 0 で終わる
sys.exit(0 if len(uniq) == 1 else 1)
