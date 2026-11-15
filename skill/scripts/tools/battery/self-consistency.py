# 親と子の表示経路が「無方向の連鎖で 同じ 向き になるか」を検査する（第 46 ラウンド裁定 (b)）
#
# 裁定のフォールド規則:
#   起点の方向 = none
#   無方向の定義縁 → 直前の方向をそのまま継承（最初は none のまま）
#   動きの縁       → 既存の矢印規則・実装側へ入る例外で決定
#   その他の有向縁 → その縁の矢印で決定
# つまり **無方向の定義縁で届いた行の `向き` は、その一歩の親の行の `向き` と必ず同じ**
# でなければならない（`none` ⇔ `none` も含む）。親がレポートに行として立っていない場合は
# 比較できないので数えない。
#
# 基準は今のディレクトリの skill/scripts/report.mjs。期待値は 不一致 0 件。
# 使い方: python3 skill/scripts/tools/battery/self-consistency.py [report.mjs のパス]
import json
import os
import pathlib
import subprocess
import sys
import tempfile
from collections import Counter

# リポジトリの根・入力の所在・失敗の扱いを `_inputs.py` にまとめた（第 51 ラウンド双人レビュー）
import _inputs as IN

# 起動条件の数え方は `required-checks.json` との集合比較に置き換えた（`IN.launch_conditions()`）。
# 「200 件未満で走り終えたあとに止める」見張り番は fixture を 2 本消した日（219 → 201 件）を
# 通したので削除（第 53 ラウンド双人レビュー両名 P2）

REPO = IN.repo_root()
REPORT = str(IN.require_script(sys.argv[1] if len(sys.argv) > 1 else 'skill/scripts/report.mjs'))
MOVEMENT = {'triggers', 'invokes', 'handler', 'exposed-by'}
BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out', 'artifacts.in', 'artifacts.out',
           'sameApi', 'siblingEndpoints', 'wiring']

TMP = tempfile.mkdtemp(prefix='cgd-selfcons-')
# 起動条件は `_inputs.launch_conditions()` が組み、`required-checks.json` と集合で突き合わせる
# （条件の組み方が 2 本の道具に分かれていたのもここで一本化した）
CONDS = IN.launch_conditions(REPO)

def rows_of(result):
  for b in BUCKETS:
    part = result[b.split('.')[0]][b.split('.')[1]] if '.' in b else result[b]
    for x in part:
      yield b, x


def run_report(graph_path, extra_args):
  # 失敗を「実行しなかった」に変えない（第 51 ラウンド双人レビュー）
  return IN.run_json(REPORT, ['--graph', str(graph_path), *extra_args],
                     os.path.join(TMP, 'r-%d.json' % len(os.listdir(TMP))),
                     REPO, label=str(graph_path))


mismatches = []
notes = Counter()
conditions = 0
compared = 0
undirected_only = 0


def check_run(label, graph_doc, result):
  """各行の 表示経路 の親一歩が無方向なら、その親の行と同じ 向き を持つこと"""
  global conditions, compared, undirected_only
  conditions += 1
  pairs = {}
  for e in graph_doc['edges']:
    pairs.setdefault((e['source'], e['target']), []).append(e)
    pairs.setdefault((e['target'], e['source']), []).append(e)
  by_id = {}
  for _, r in rows_of(result):
    by_id.setdefault(r['id'], r)          # 同じ id が複数欄に出ることは無い（欄は一意）
  for _, r in rows_of(result):
    path = r.get('path') or []
    if len(path) < 2:
      continue
    parent = by_id.get(path[-2])
    if parent is None:
      notes['親がレポートに行として立っていない'] += 1
      continue
    # 親の表示経路が自分の経路の**接頭辞**であること（別の経路で立っている親とは比べない）
    if (parent.get('path') or []) != path[:-1]:
      notes['親の表示経路が自分の経路の接頭辞ではない'] += 1
      continue
    cands = pairs.get((path[-2], path[-1]), [])
    if not cands:
      notes['表示経路の隣接ペアを結ぶ縁が無い'] += 1
      continue
    undirected = [e for e in cands if e['provenance'] == 'terraform' and e['kind'] not in MOVEMENT]
    if len(undirected) != len(cands):
      # 並行縁に 動きの縁 や 向きを持つ縁 が混ざる一歩は、実装がどれを選んだか JSON だけでは
      # 決まらないので数えない（向き の再計算は check-invariants46.py の検査 6 が見る）
      notes['並行縁に 向き を決める縁が混ざる一歩'] += 1
      continue
    compared += 1
    if r['direction'] != parent['direction']:
      mismatches.append((label, r['id'], parent['id'],
                         f"子={r['direction']} 親={parent['direction']} 縁={undirected[0]['kind']} "
                         f"経路={'|'.join(path)}"))
    # 同じ規則を**根**へ適用した形: 表示経路の 1 本目が無方向の定義縁なら、その行の 向き は
    # 起点の 向き（= none）から始まる。経路全体が無方向なら 向き は none のままのはず
    # （第 45 ラウンドまであった「無方向の最初の一歩を端点から種にする」規則は
    # 第 46 ラウンド裁定 (b) で却下されたので、その実装ではここが違反になる）
    step_edges = [e for a, b in zip(path, path[1:]) for e in pairs.get((a, b), [])]
    if step_edges and all(e['provenance'] == 'terraform' and e['kind'] not in MOVEMENT
                          for e in step_edges):
      undirected_only += 1
      if r['direction'] != 'none':
        mismatches.append((label + ' / 経路全体が無方向', r['id'], path[0],
                           f"子={r['direction']} 期待=none 経路={'|'.join(path)}"))


for cond in CONDS:
  label = f'{cond["rel"].split("#")[0]}[{cond["kind"]}]'
  doc = json.loads(cond['graph'].read_text())
  check_run(label, doc, run_report(cond['graph'], IN.materialize(cond, TMP)))

print(f'検査した起動条件 {conditions} 件（要求一覧 required-checks.json と集合一致） / '
      f'無方向の一歩で親と突き合わせた行 {compared} 件'
      f'（うち 表示経路全体が無方向の行 {undirected_only} 件）')
print(f'不一致 {len(mismatches)} 件')
for k, c in notes.most_common():
  print(f'（参考）{k}: {c}')
for m in mismatches[:20]:
  print(f'  不一致: {m[0]} / 子={m[1]} / 親={m[2]} / {m[3]}')
sys.exit(1 if mismatches else 0)
