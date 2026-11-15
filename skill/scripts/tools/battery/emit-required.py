# 起動条件の要求一覧 `required-checks.json` を**作り直す**道具（作成手順。自動更新しない）
#
# 要求一覧が無いと `check-invariants46.py` / `self-consistency.py` は測れない
# （`_inputs.launch_conditions()` が要求一覧との集合比較をする）。fixture を増やした・
# 起動条件の組み方を人が変えると決めたときは、ここで作り直して**人が差分をレビュー**する。
# 実行結果から自動で上書きする仕組みは置かない（第 52 ラウンド Astra 裁定 1 と同じ約束）
#
# 使い方: python3 skill/scripts/tools/battery/emit-required.py skill/scripts/tools/battery/required-checks.json
import glob
import json
import pathlib
import sys

import _inputs as IN

if len(sys.argv) != 2:
    raise SystemExit('使い方: python3 skill/scripts/tools/battery/emit-required.py '
                     '<書き出す JSON のパス>（作られた一覧を人がレビューしてコミットする）')
REPO = IN.repo_root()
out = pathlib.Path(sys.argv[1])
fixture_paths = sorted(glob.glob(str(REPO / IN.FIXTURE_GLOB)))
conds = IN.launch_conditions(REPO, check_required=False, fixtures=fixture_paths)
fixtures = sorted(str(pathlib.Path(f).resolve().relative_to(REPO.resolve())).replace('\\', '/')
                  for f in fixture_paths)
out.write_text(json.dumps({
    'note': ('回帰検査（`check-invariants46.py` / `self-consistency.py`）が走らせる**起動条件の要求一覧**。'
             '`_inputs.launch_conditions()` がこの集合と実際に組み上げた条件の集合を突き合わせ、'
             '消えた・新規の条件があれば測る前に終了 1 にする（第 53 ラウンド双人レビュー両名 P2: '
             'fixture を 2 本消しても 201 条件で終了 0 だった。200 件の見張り番はこれで不要にした）。'
             '作り直しは `python3 skill/scripts/tools/battery/emit-required.py <このファイル>` で人が行う'),
    'fixtures': fixtures,
    'conditions': [{'id': c['id'], 'graph': c['rel'], 'kind': c['kind'], 'args': c['args']}
                   for c in sorted(conds, key=lambda c: c['id'])],
}, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print(f'要求一覧: fixture {len(fixtures)} 本 / 起動条件 {len(conds)} 件を {out} に書き出した'
      '（人が差分をレビューしてコミットする。実行結果からの自動更新はしない）')
