# v1 の出力契約が変わっていないかの突き合わせ（第 29 ラウンドの更新後基準）。
# 基準値は skill/scripts/tools/battery/baseline-v1（第 24 ラウンドの監査レポートを第 29
# ラウンドの裁定で作り直したもの。**人が「差し替えない」と決めた基準**で、第 50 ラウンドまで
# 一時ディレクトリ（第 29 ラウンドの監査出力）に有った唯一のコピーをここへ移した
# （掃除で消える場所には置かない）。
# 同じ条件で今の report.mjs を走らせ、行（id / 向き / tier / 段数 / 根拠の縁）と欄の件数を比べる。
#
# 終了コードの形（第 52 ラウンド双人レビューで agy と Codex の見解が割れ、Astra の裁定で確定）:
#   既定             … 差分が 1 件でもあれば終了 1。差分一覧を人が読むための動作で従来どおり
#   --verify-known   … 差分の**内容**が固定した既知差分と完全一致のときだけ終了 0。件数が同じで
#                      中身が入れ替わっていれば不一致（第 52 ラウンド Codex「74 という件数だけだと
#                      同件数の別 Regression を通す」）。変更前・変更後の値まで見る（Astra 裁定 1）
#   --emit-known     … 今の差分を既知差分ファイルへ書き出す**作成手順**。人が作り直しを認めた
#                      あとのみ（実行結果からの自動更新はしない）
# 実行失敗・読みけない JSON・`unresolved`・記録グラフの未解決・行 id の重複は**既知差分に混ぜない**
# （その日は測れていないので、照合モードでも必ず非 0）
# 比較するのは行の `欄 / 向き / tier / 段数 / 根拠の縁の種類` と summary の 12 キーだけ。行順・
# `path`・根拠縁の id は比較しない（比較範囲外は不変条件検査と順列検査が担う）
import json, os, pathlib, subprocess, sys

import _inputs as IN

BASE = pathlib.Path(os.environ.get('CGD_AUDIT_BASE', 'skill/scripts/tools/battery/baseline-v1'))
OUT = pathlib.Path(os.environ.get('CGD_AUDIT_OUT', 'out/audit-current'))
OUT.mkdir(parents=True, exist_ok=True)
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out',
           'artifacts.in', 'artifacts.out', 'sameApi', 'siblingEndpoints', 'wiring']
SUMMARY_KEYS = ['rows', 'primaryIn', 'primaryOut', 'entryIn', 'entryOut', 'artifactsIn',
                'artifactsOut', 'wiring', 'sameApi', 'siblings', 'siblingEndpointsOnly', 'siblingDefs']

MODE, KNOWNS = 'plain', None
if '--verify-known' in sys.argv:
    MODE, KNOWNS = 'verify', sys.argv[sys.argv.index('--verify-known') + 1]
elif '--emit-known' in sys.argv:
    MODE, KNOWNS = 'emit', sys.argv[sys.argv.index('--emit-known') + 1]


def rows_of(r, cond):
    """欄別の行を `{行 id: [欄, 向き, tier, 段数, 根拠の縁の種類]}` に畳む。同じ id が 2 回出たら
    畳み込みで上書きして区別できなくなるので、その場で落とす（Astra 裁定 1「重複 id は
    指紋化前に拒否」）"""
    out = {}
    for b in BUCKETS:
        part = r[b.split('.')[0]][b.split('.')[1]] if '.' in b else r[b]
        for x in part:
            if x['id'] in out:
                raise ValueError(f'{cond}: 行 id が重複している（{x["id"]}）。'
                                 '行を id で畳むので区別できず、比較の保証が崩れる')
            out[x['id']] = [b, x['direction'], x['tier'], x['hops'], (x['evidence'] or {}).get('kind')]
    return out


def canonical(rec):
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


diffs = []     # 人が読む差分一覧（従来どおりの出力形式）
records = []   # 既知差分と突き合わせるレコード（変更前と変更後の値を両方持つ）
bad = []       # 既知差分にできない不良（1 件でもあれば必ず非 0）
REPORTS = IN.report_paths(BASE, expect=18, what='v1 基準の 18 条件')
for p in REPORTS:
    try:
        old = json.loads(p.read_text())
    except (OSError, ValueError) as e:
        bad.append(f'{p.name} の基準が読みけない: {e}')
        continue
    s = old['summary']
    try:
        graph = str(IN.graph_path(s['graph']))
    except SystemExit as e:
        bad.append(f'{p.name} の記録グラフが解決できない: {e}')
        continue
    args = ['node', str(IN.require_script(os.environ.get('CGD_V1DIFF_REPORT', 'skill/scripts/report.mjs'))),
            '--graph', graph,
            '--hops', str(s['hops']), '--wiring-hops', str(s['wiringHops']),
            '--limit', str(s.get('limit') or 100000)]
    for item in old['starts']:
        args += ['--from', item['id']]
    dest = OUT / p.name
    args += ['--json', str(dest)]
    run = subprocess.run(args, text=True, capture_output=True, cwd=str(IN.repo_root()))
    if run.returncode != 0:
        bad.append(f'{p.name} 実行失敗 ' + run.stdout[-300:] + run.stderr[-300:])
        continue
    try:
        new = json.loads(dest.read_text())
    except ValueError as e:
        bad.append(f'{p.name} の再生成 JSON が不正: {e}')
        continue
    try:
        o, n = rows_of(old, p.name), rows_of(new, p.name)
    except ValueError as e:
        bad.append(str(e))
        continue
    for k in sorted(set(o) | set(n)):
        if o.get(k) != n.get(k):
            ov = tuple(o[k]) if o.get(k) is not None else None
            nv = tuple(n[k]) if n.get(k) is not None else None
            diffs.append((p.name, k, f'old={ov} new={nv}'))
            records.append({'cond': p.name, 'kind': 'row', 'id': k, 'old': o.get(k), 'new': n.get(k)})
    for key in SUMMARY_KEYS:
        if s.get(key) != new['summary'].get(key):
            diffs.append((p.name, f'summary.{key}', f"old={s.get(key)} new={new['summary'].get(key)}"))
            records.append({'cond': p.name, 'kind': 'summary', 'id': f'summary.{key}',
                            'old': s.get(key), 'new': new['summary'].get(key)})
    if new['summary']['unresolved']:
        bad.append(f"{p.name} unresolved {new['summary']['unresolved']}")

if bad:
    print(f'既知差分にできない不良 {len(bad)} 件（実行失敗・読みけない JSON・unresolved・'
          '記録グラフの未解決・行 id の重複。この日は測れていない）:', file=sys.stderr)
    for b in bad[:int(os.environ.get('CGD_V1DIFF_SHOW', '60'))]:
        print(f'  - {b}', file=sys.stderr)

if MODE == 'emit':
    out = pathlib.Path(KNOWNS)
    out.write_text(json.dumps({
        'note': ('v1 基準（`baseline-v1`）と今の report.mjs の差分のうち、既知と認めた一覧。'
                 '人が v1 基準を差し替えないと決めている間の許容差分で、`--verify-known` が'
                 '内容の一致を見る。このファイル自体が「何を許容したか」の記録なので実行結果から'
                 '自動更新しない（更新は `--emit-known` で作り直して人がレビューする）'),
        'diffs': sorted(records, key=canonical),
    }, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'既知差分 {len(records)} 件を {out} に書き出した（作成手順。人がレビューするまで使わない）')
    raise SystemExit(1 if bad else 0)

print(f'レポート {len(REPORTS)} 件 / 差分 {len(diffs)} 件')
for d in diffs[:int(os.environ.get('CGD_V1DIFF_SHOW', '60'))]:
    print(' -', d[0], d[1], d[2] if len(d) > 2 else '')

if MODE == 'verify':
    want = json.loads(pathlib.Path(KNOWNS).read_text())['diffs']
    want_set, got_set = {canonical(r) for r in want}, {canonical(r) for r in records}
    new_ones, gone = got_set - want_set, want_set - got_set
    print(f'既知差分 {len(want)} 件（重複を除くと {len(want_set)} 件）との照合: '
          f'新規 {len(new_ones)} 件 / 消えた既知 {len(gone)} 件 / 今回の重複 {len(records) - len(got_set)} 件')
    for x in sorted(new_ones)[:20]:
        print('  +', x)
    for x in sorted(gone)[:20]:
        print('  -', x)
    if bad or new_ones or gone or len(records) != len(got_set) or len(want) != len(want_set):
        raise SystemExit(1)
    print('差分の内容が既知差分と完全一致（件数だけでなく、変更前・変更後の値まで一致）')
    raise SystemExit(0)

sys.exit(1 if diffs or bad else 0)
