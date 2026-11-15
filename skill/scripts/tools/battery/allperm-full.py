#!/usr/bin/env python3
# 縁順の全順列で **レポート JSON 全体**を突き合わせる（第 46 ラウンド双人レビュー P2）。
# `skill/scripts/tools/battery/allperm-corr.py` は行の id / 欄 / 向き / 段数 / 対応 / 向き変え / 根拠縁 id
# だけを比べ、中立 3 欄（sameApi / siblingEndpoints / wiring）と JSON の形（`evidence` に
# `metadata` や `count` が混ざる問題）を見ていなかった。ここでは生 JSON を正規化して丸ごと比べる。
#
# 使い方: python3 skill/scripts/tools/battery/allperm-full.py <report.mjs> <ケース json> [順列上限]
def _diff(ra, rb):
    if ra is None: return '行が無い → 有る'
    if rb is None: return '行が有る → 無い'
    return ' / '.join(f"{k}: {ra.get(k)!r}→{rb.get(k)!r}"
                      for k in sorted(set(ra) | set(rb)) if ra.get(k) != rb.get(k))
import json, subprocess, sys, itertools, tempfile, os, collections

script, graph_file = sys.argv[1], sys.argv[2]
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
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump(gg, f); path = f.name
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        out = f.name
    p = subprocess.run(['node', script, '--graph', path, *extra, '--json', out],
                       capture_output=True, text=True)
    os.unlink(path)
    if p.returncode:
        os.unlink(out)
        raise SystemExit(f'実行失敗（report.mjs が動いていない）: {p.stderr[-300:]}')
    d = json.load(open(out)); os.unlink(out)
    return norm(d)

perms = list(itertools.permutations(range(len(g['edges']))))
if len(perms) > cap:
    step = len(perms) // cap
    perms = perms[::step][:cap]
res = collections.OrderedDict()
for perm in perms:
    res[','.join('e%d' % i for i in perm)] = run([g['edges'][i] for i in perm])

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
