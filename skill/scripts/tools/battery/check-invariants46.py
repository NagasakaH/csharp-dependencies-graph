# 表示値の不変条件を検査する（第 45 ラウンド Astra 裁定・案 D の検査 + 第 46 ラウンド裁定の 向き）
#
#   1. `evidence.id` が `path` を順に辿った隣接ペアを結ぶ縁の id のどれかと一致する
#      （`path` が start / 予算などで切れている行は、その手前までを許す。理由無く不一致なら違反）
#   2. `hops === len(path) - 1`
#   3. `correspondence` は `path` 上の縁に `llm` / `human` の注釈縁が 1 本でもあるか と一致する
#      （根拠の 1 本の注釈有無ではない）
#
# おまけ（案 D の「根拠縁 ∈ 表示経路」を直接見る項目）:
#   4. `movementEvidence` は無し、または `path` を結ぶ縁の 1 本で、かつ 動きの縁 の種類である
#
# ---- 第 46 ラウンド Astra 裁定（`out/review-astra46.log`）で足した検査 -------------------
#   5. `direction` の値域が `in` / `out` / `none` のいずれか（`null` を返さない）
#   6. `direction` が表示経路（`path`）の根から裁定どおりにフォールドした値と一致する
#      （起点の 向き = none、無方向の定義縁は継承、動きの縁は矢印 + 実装側へ入る例外、
#       その他の有向縁は矢印。`down`（実装側）による上書きは無い）
#   7. `none` の行の最終一歩が 動きの縁 でも 向きを持つ縁 でもない
#      （= none は「経路に 向き を決める関係が無かった」行だけ）
#   8. `none` の行が 方向を持つ欄（external / entries / artifacts の in・out）に並んでいない
#   9. 向き を持つ行は 表示経路の最後の 動き / 向きを持つ 一歩の矢印と向きが一致する
#  10. `summary.directionless` と `summary.directionlessPrimary` が実際の行数と一致し、
#      総行数 == 各欄の合計（`--limit` で一覧が切れていないとき）
#
# 使い方: python3 skill/scripts/tools/battery/check-invariants46.py [report.mjs のパス]
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections import Counter

# リポジトリの根・入力の所在・失敗の扱いを `_inputs.py` にまとめた（第 51 ラウンド双人レビュー）
import _inputs as IN

# 起動条件の数は `required-checks.json` との**集合比較**で決める（`IN.launch_conditions()` が
# 測る前に落とす）。第 53 ラウンド双人レビューまであった「200 件未満で走り終えたあとに止める」
# 見張り番は、fixture を 2 本消した日（219 → 201 件）を通したため削除した（両名 P2）

REPO = IN.repo_root()
REPORT = str(IN.require_script(sys.argv[1] if len(sys.argv) > 1 else 'skill/scripts/report.mjs'))
ANNOTATION = 'human'
CORRESPONDENCE = {'llm', 'human'}
MOVEMENT = {'triggers', 'invokes', 'handler', 'exposed-by'}
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out', 'artifacts.in', 'artifacts.out',
           'sameApi', 'siblingEndpoints', 'wiring']
# 第 46 ラウンド裁定の実装側と同じ集合（`skill/scripts/report.mjs` の定義と対応させている）
MOVEMENT = {'triggers', 'invokes', 'handler', 'exposed-by'}
FLIP_INTO_IMPL = {'exposed-by', 'handler'}
ARROW_REVERSED = {'exposed-by'}
DIRECTIONED_BUCKETS = {'external.in', 'external.out', 'entries.in', 'entries.out',
                       'artifacts.in', 'artifacts.out'}

# 起動条件は `_inputs.launch_conditions()` が組み、`required-checks.json`（追跡下）と集合で
# 突き合わせる。fixture・検査のグラフ・v1 基準 18 条件のいずれかの一部が欠けた日、
# ここは**測る前に**終了 1（第 53 ラウンド両名 P2 で集計した）
CONDS = IN.launch_conditions(REPO)


def node_endpoints(doc):
  """graph.json から (id -> endpoint) と (縁 id -> 縁) を引く"""
  edges = {e['id']: e for e in doc['edges']}
  # 同じ 2 点を結ぶ縁は 1 本とは限らない（`invokes` と `calls` の並行縁など）。ペア -> 縁の一覧
  pairs = {}
  for e in doc['edges']:
    pairs.setdefault((e['source'], e['target']), []).append(e)
    pairs.setdefault((e['target'], e['source']), []).append(e)
  return edges, pairs


TMP = tempfile.mkdtemp(prefix='cgd-invariants-')


def rows_of(result):
  for b in BUCKETS:
    part = result[b.split('.')[0]][b.split('.')[1]] if '.' in b else result[b]
    for x in part:
      yield b, x


violations = []
notes = Counter()
checked = Counter()


def check_run(label, graph_doc, result):
  edges, pairs = node_endpoints(graph_doc)
  for bucket, r in rows_of(result):
    checked['行'] += 1
    path = r.get('path') or []
    rid = r['id']
    # --- 2. 段数 = 経路長 - 1 ---
    if r['hops'] != max(len(path) - 1, 0):
      violations.append(('hops', label, rid, f"hops={r['hops']} path={len(path)}"))
    if path and path[-1] != rid:
      violations.append(('path 末尾', label, rid, f"path[-1]={path[-1]}"))
    # 隣接ペアを結ぶ縁（表示経路に実際に含まれる縁の候補）
    on_path = []
    for a, b in zip(path, path[1:]):
      on_path += pairs.get((a, b), [])
    on_path_ids = {e['id'] for e in on_path}
    truncated = r.get('pathRoot') != 'start'
    # --- 1. evidence は表示経路の隣接ペアを結ぶ縁 ---
    ev = (r.get('evidence') or {}).get('id')
    if ev is None:
      notes['evidence 無し'] += 1
    elif ev not in on_path_ids:
      head = path[0] if path else None
      # 切り詰め行は先頭のさらに先が経路に出ていない。evidence が先頭に接する縁なら理由あり
      head_edge = (truncated and ev in {e['id'] for e in edges.values()
                                        if head in (e['source'], e['target'])})
      if head_edge:
        notes['evidence が切り詰め先頭に接する（理由あり）'] += 1
      else:
        violations.append(('evidence が表示経路に無い', label, rid,
                           f"evidence={ev} path={'|'.join(path)} root={r.get('pathRoot')}"))
    # --- 3. 対応 = 経路上の注釈縁の有無 ---
    if on_path or not truncated:
      annotated = any(e['provenance'] in CORRESPONDENCE for e in on_path)
      parallel = sum(1 for a, b in zip(path, path[1:]) if len(pairs.get((a, b), [])) > 1)
      if annotated != r['correspondence']:
        kind = '対応 が経路上の注釈縁と不一致' + ('（並行縁あり）' if parallel else '')
        violations.append((kind, label, rid,
                           f"correspondence={r['correspondence']} 経路={annotated} "
                           f"{'|'.join(path)}"))
    else:
      notes['対応: 経路が切り詰めで見えない（検査外）'] += 1
    # --- 4. 動きの根拠は表示経路の縁で、動きの縁の種類 ---
    mv = (r.get('movementEvidence') or {}).get('id')
    if mv is not None:
      if mv not in on_path_ids:
        if (truncated and mv in {e['id'] for e in edges.values()
                                 if path and path[0] in (e['source'], e['target'])}):
          notes['動きの根拠が切り詰め先頭に接する（理由あり）'] += 1
        else:
          violations.append(('動きの根拠が表示経路に無い', label, rid,
                             f"mv={mv} path={'|'.join(path)} root={r.get('pathRoot')}"))
      elif edges[mv]['kind'] not in MOVEMENT:
        violations.append(('動きの根拠が動きの縁でない', label, rid,
                           f"mv={mv} kind={edges[mv]['kind']}"))
    # 案 D の固定規則: 動きの根拠は「当該ノードへ入る最終一歩の縁」が動きの縁ならそれ、
    # そうでなければ無し。最終一歩の縁はその行の `evidence` なので、そこから直接見る
    # （同じ 2 点を結ぶ並行縁があっても判定に効かない）
    if ev is not None:
      is_mv = edges[ev]['kind'] in MOVEMENT
      if is_mv and mv != ev:
        violations.append(('最終一歩が動きの縁なのに動きの根拠が別', label, rid,
                           f"evidence={ev} kind={edges[ev]['kind']} mv={mv}"))
      if not is_mv and mv is not None:
        violations.append(('最終一歩が動きの縁で無いのに動きの根拠がある', label, rid,
                           f"evidence={ev} kind={edges[ev]['kind']} mv={mv}"))
    if mv is not None and ev is not None and mv != ev:
      violations.append(('動きの根拠が最終一歩ではない', label, rid, f"mv={mv} 最終一歩={ev}"))
    check_direction(label, result, bucket, r, edges, pairs)

def arrow_at(edge, node):
  """縁の矢印が node を指しているか（`report.mjs` の `arrowAt` と同じ）"""
  tail = edge['source'] if edge['kind'] in ARROW_REVERSED else edge['target']
  return tail == node


def step_dir(edge, node, inherited, start_is_endpoint):
  """第 46 ラウンド裁定の 1 歩の 向き。表示経路を根からフォールドして 向き を決める規則を
  検査側で独立に書き直したもの（実装と同じ値になることを 6 で確かめる）"""
  kind = edge['kind']
  if kind in MOVEMENT:
    if arrow_at(edge, node):
      return 'out'
    # 実装側へ入る例外は 動きの縁 の枝の中にだけある（裁定 (a-2)）
    if kind in FLIP_INTO_IMPL and start_is_endpoint:
      return 'out'
    return 'in'
  # 無方向の定義縁（定義閉包で 向き を意味として採用しない縁）は直前を継承する。
  # 最初は none のまま（裁定 (b)・(c)）
  if edge['provenance'] == 'terraform':
    return inherited
  # その他の 向き を持つ縁は自分の矢印で決める（裁定 (a-2): `down` で上書きしない）
  return 'out' if arrow_at(edge, node) else 'in'


def fold(path, pairs, start_is_endpoint):
  """表示経路を根から順に読んで起こり得る `向き` の集合を返す。同じ 2 点を結ぶ並行縁が
  ある行は 実装が選んだ 1 本を JSON だけでは特定できないので、集合が 1 つに定まるかを見る"""
  vals = {'none'}
  for a, b in zip(path, path[1:]):
    cands = pairs.get((a, b), [])
    if not cands:
      return None                       # 縁が結んでいない（検査 1 が別途見る）
    nxt = set()
    for v in vals:
      for e in cands:
        nxt.add(step_dir(e, b, v, start_is_endpoint))
    vals = nxt
  return vals


def check_direction(label, result, bucket, r, edges, pairs):
  """検査 5〜10（第 46 ラウンド裁定）"""
  rid = r['id']
  path = r.get('path') or []
  s = result['summary']
  d = r.get('direction')
  if d not in ('in', 'out', 'none'):
    violations.append(('向き の値域', label, rid, f'direction={d!r}'))
    return
  # --- 6. 表示経路を根からフォールドした値と一致 ---
  vals = fold(path, pairs, bool(s.get('startIsEndpoint')))
  if vals is None:
    notes['向き: 表示経路が縁を結んでいない（6 は検査外）'] += 1
  elif len(vals) > 1:
    if d not in vals:
      violations.append(('向き が表示経路のフォールドと不一致（並行縁）', label, rid,
                         f'direction={d} 起こり得る値={sorted(vals)} path={"|".join(path)}'))
    else:
      notes['向き: 並行縁で 1 つに定まらない（値は候補内）'] += 1
  elif d != next(iter(vals)):
    violations.append(('向き が表示経路のフォールドと不一致', label, rid,
                       f'direction={d} 期待={sorted(vals)} path={"|".join(path)}'))
  # --- 7. none の行の最終一歩は 動きの縁 でも 向きを持つ縁 でもない ---
  ev = (r.get('evidence') or {}).get('id')
  if d == 'none':
    if ev is not None and ev in edges:
      e = edges[ev]
      if e['kind'] in MOVEMENT or e['provenance'] != 'terraform':
        violations.append(('none の行の最終一歩が 向き を決める縁', label, rid,
                           f"kind={e['kind']} provenance={e['provenance']}"))
    # --- 8. 方向を持つ欄に並んでいない ---
    if bucket in DIRECTIONED_BUCKETS:
      violations.append(('none の行が方向を持つ欄にある', label, rid, f'欄={bucket}'))
  # --- 9. 向き を持つ行は最終一歩の 向き を決める縁と一致 ---
  if d in ('in', 'out') and ev is not None and ev in edges:
    e = edges[ev]
    if e['kind'] in MOVEMENT or e['provenance'] != 'terraform':
      want = 'out' if arrow_at(e, rid) else 'in'
      # 動きの縁の実装側へ入る例外は 動きの縁 の枝の中にある
      if e['kind'] in MOVEMENT and not arrow_at(e, rid) and e['kind'] in FLIP_INTO_IMPL \
          and s.get('startIsEndpoint'):
        want = 'out'
      if d != want:
        violations.append(('向き が最終一歩の縁と不一致', label, rid,
                           f'direction={d} 縁={e["kind"]}/{e["provenance"]} 期待={want}'))



def check_summary(label, result):
  """検査 10: `none` のカウンタと 欄の合計 == 総行数"""
  s = result['summary']
  rows = list(rows_of(result))
  none_rows = [x for _, x in rows if x.get('direction') == 'none']
  if 'directionless' not in s:
    violations.append(('summary.directionless が無い', label, '', ''))
  elif not s.get('listTruncated') and s['directionless'] != len(none_rows):
    # 一覧は --limit で切るので、切り詰めていないときだけ件数を突き合わせる
    violations.append(('summary.directionless が実数と不一致', label, '',
                       f"summary={s['directionless']} 一覧={len(none_rows)}"))
  if 'directionlessPrimary' in s and not s.get('listTruncated'):
    want = sum(1 for x in none_rows if x.get('tier') == 'primary')
    if s['directionlessPrimary'] != want:
      violations.append(('summary.directionlessPrimary が実数と不一致', label, '',
                         f"summary={s['directionlessPrimary']} 一覧={want}"))
    # none の行で 中立欄（同じ API / 兄弟）以外へ行くものは 定義上の関連 で受けている
    away = [x['id'] for x in none_rows
            if x.get('tier') == 'primary' and x['bucket'] not in
            ('sameApi', 'siblingEndpoints', 'wiring', None)]
    if away:
      violations.append(('none の本命行が中立欄以外へ並んでいる', label, away[0], str(away[:3])))
  if not s.get('listTruncated'):
    if len(rows) != s['rows']:
      violations.append(('欄の合計 != 総行数', label, '', f"欄={len(rows)} rows={s['rows']}"))


def run_report(graph_path, extra_args):
  # 失敗を「実行しなかった」に変えない（第 51 ラウンド双人レビュー。失敗を数えて continue すると
  # 全滅しても違反 0 で終了 0 になった）
  return IN.run_json(REPORT, ['--graph', str(graph_path), *extra_args],
                     os.path.join(TMP, 'r.json'), REPO, label=str(graph_path))


seen_conditions = 0
for cond in CONDS:
  # ラベルは以前と同じ形（`<グラフ名>[<種類>]`。v1 基準の条件はレポート名で出す）
  label = f'{cond["rel"].split("#")[0]}[{cond["kind"]}]'
  doc = json.loads(cond['graph'].read_text())
  res = run_report(cond['graph'], IN.materialize(cond, TMP))
  seen_conditions += 1
  check_run(label, doc, res)
  check_summary(label, res)

print(f'検査した起動条件 {seen_conditions} 件 / 行 {checked["行"]} 件'
      f'（要求一覧 required-checks.json と集合一致）')
print(f'違反合計 {len(violations)} 件')
for kind, cnt in Counter(v[0] for v in violations).most_common():
  print(f'  - {kind}: {cnt}')
for k, c in notes.most_common():
  print(f'（参考）{k}: {c}')
for v in violations[:20]:
  print(f'  違反: {v[0]} / {v[1]} / {v[2]} / {v[3]}')
sys.exit(1 if violations else 0)
