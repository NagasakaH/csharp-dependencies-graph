# 起動条件の要求一覧 `required-checks.json` を**作り直す**道具（作成手順。自動更新しない）
#
# 要求一覧が無いと `check-invariants46.py` / `self-consistency.py` は測れない
# （`_inputs.launch_conditions()` が要求一覧と実際に組み上げた条件の集合を突き合わせる）。
# fixture を増やした・起動条件の組み方を人が変えると決めたときは、ここで作り直して
# **人が差分をレビュー**する。実行結果から自動で上書きする仕組みは置かない
# （第 52 ラウンド Astra 裁定 1 と同じ約束。第 55 ラウンド Astra 裁定 問 6 でも
# 「生成コマンドは候補を書き出すだけ」に留める）
#
# 第 55 ラウンドで一覧は 3 つの材料を一緒に持つようになった（新しい正本を増やさないため、
# 同じファイルの中に入れている）:
#   * `fixtures`     … 走らせる fixture の一覧（glob の実体と双方向で一致する）
#   * `conditions`   … 起動条件の正準形（`case` / `graph` / `kind` / `args` と、その id）
#   * `expectations` … 測った件数（走査した行数・突き合わせた親子数・向き の数え・
#                      向き 規則の照合）。入力は同じなのに検査範囲だけ縮む日を止める
#
# 使い方（**先に測ってから**作る。測らずに作ると終了 1）:
#   M=$(mktemp -d)/measured.json
#   python3 skill/scripts/tools/battery/check-invariants46.py --emit-measured $M
#   python3 skill/scripts/tools/battery/self-consistency.py   --emit-measured $M
#   python3 skill/scripts/tools/battery/count-none.py         --emit-measured $M out/audit-current
#   python3 skill/scripts/tools/battery/check-dir-rule.py --profile current --emit-measured $M out/audit-current
#   python3 skill/scripts/tools/battery/check-dir-rule.py --profile v1      --emit-measured $M
#   python3 skill/scripts/tools/battery/emit-required.py skill/scripts/tools/battery/required-checks.json --measured $M
# （`out/audit-current` は今の `report.mjs` での再生成。作り方は
#   `python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs out/audit-current --force`）
import glob
import json
import pathlib
import sys

import _inputs as IN

args = [a for a in sys.argv[1:]]
measured = None
if '--measured' in args:
    k = args.index('--measured')
    if k + 1 >= len(args):
        raise SystemExit('使い方: emit-required.py <書き出す JSON のパス> '
                         '--measured <測った件数の JSON のパス>')
    measured = args[k + 1]
    args = args[:k] + args[k + 2:]
if len(args) != 1:
    raise SystemExit('使い方: python3 skill/scripts/tools/battery/emit-required.py '
                     '<書き出す JSON のパス> --measured <測った件数の JSON>'
                     '（測り方はこのファイルの先頭に 5 本の手順として書いてある）')
REPO = IN.repo_root()
# 書き先は明示された引数なので cwd 基準（第 55 ラウンド Astra 裁定 問 5。既定の無い道具なので
# 「既定は根」も無い）。絶対パスを渡すこともできる
out = IN.resolve_cli_path(args[0], default=None)
if measured is None:
    raise SystemExit('測った件数が無い（`--measured <JSON>` が要る）。前の一覧の expectations を'
                     'そのまま引き継ぐと「入力はそのままで検査範囲が縮んだ日」を通してしまうので、'
                     '測り直しを必須にしている。測り方はこのファイルの先頭に書いてある')

m = json.loads(IN.require(IN.resolve_cli_path(measured, default=None), '測った件数の JSON',
                          want_file=True).read_text(encoding='utf-8'))
# `dirRule.current` のように点で書かれた鍵は入れ子の形へ直して expectations に置く
expectations = {}
for key, val in m.items():
    here = expectations
    parts = key.split('.')
    for p in parts[:-1]:
        here = here.setdefault(p, {})
    if not isinstance(here, dict):
        raise SystemExit(f'測った JSON の鍵が入れ子と衝突している: {key}')
    if key in IN.COVERAGE_KINDS and isinstance(val, dict) and 'byCondition' not in val:
        # 検査が測るのは `{条件の id: 件数}`。合計と件数はここで導出する（合計を手で
        # 書けるようにすると、条件間の増減を相殺させた一覧が作れてしまう）
        val = {'byCondition': val, 'total': sum(val.values()), 'conditions': len(val)}
    here[parts[-1]] = val
want_kinds = ('invariantRows', 'parentChild', 'directionless', 'dirRule')
miss = [k for k in want_kinds if k not in expectations]
if miss:
    raise SystemExit('測った JSON に無い内訳: ' + ' / '.join(miss) +
                     '\n  先に測ってから作る（このファイルの先頭に 5 本の手順を書いてある）')

fixture_paths = sorted(glob.glob(str(REPO / IN.FIXTURE_GLOB)))
conds = IN.launch_conditions(REPO, check_required=False, fixtures=fixture_paths)
fixtures = sorted(str(pathlib.Path(f).resolve().relative_to(REPO.resolve())).replace('\\', '/')
                  for f in fixture_paths)
doc = {
    'note': ('回帰検査（`check-invariants46.py` / `self-consistency.py` / `count-none.py` / '
             '`check-dir-rule.py --profile`）が使う**要求一覧と期待値の正本**。3 つの内訳を持つ。'
             '`fixtures` は走らせる fixture の一覧で、glob の実体と双方向で一致していないと終了 1'
             '（有るのに一覧に無い fixture は黙って走らない。`conditions` は起動条件の正準形で、'
             '合否は `case` / `graph` / `kind` / `args` の中身の比較が決める。`id` は中身から'
             '再計算できる導物で、id だけを見た比較は要求一覧の書き換えを通した'
             '（第 54 ラウンド双人レビュー Codex 指摘 2）。`expectations` は実際に測った件数'
             '（走査した行数・突き合わせた親子数・向き の数え・向き 規則の照合）を条件別置いた物で、'
             '合計は条件別から導出する。入力はそのままで検査範囲だけ縮んだ日はここで止める'
             '（第 55 ラウンド Astra 裁定 問 2）。`_inputs.launch_conditions()` が集合を突き合わせ、'
             '消えた・新規の条件があれば測る前に終了 1 にする（第 53 ラウンド双人レビュー両名 P2: '
             'fixture を 2 本消しても 201 条件で終了 0 だった）。'
             '作り直しは `python3 skill/scripts/tools/battery/emit-required.py '
             '<このファイル> --measured <測った件数の JSON>` で人が行う（自動更新しない）'),
    'fixtures': fixtures,
    'conditions': [{'id': c['id'], 'case': c['case'], 'graph': c['graphRel'],
                    'kind': c['kind'], 'args': c['args']}
                   for c in sorted(conds, key=lambda c: c['id'])],
    'expectations': expectations,
}
# 作るときに自分の形を検査しておく（人がレビューする前に壊れた一覧を書かない）
IN.validate_required_spec(doc, REPO)
out.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
print(f'要求一覧: fixture {len(fixtures)} 本 / 起動条件 {len(conds)} 件 / '
      f'期待値 {len(expectations)} 内訳を {out} に書き出した'
      '（人が差分をレビューしてコミットする。実行結果からの自動更新はしない）')
