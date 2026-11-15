# 既存のレポート JSON を、第 46 ラウンド裁定の 向き 規則で検査し直す（実行せず読むだけ）。
# v1 基準（skill/scripts/tools/battery/baseline-v1）の 向き が 今回の規則で表示経路から再現できるかを測るためのもので、
# REBASE.md の「どちらが正直か」の実測根拠にする。
# 使い方: python3 skill/scripts/tools/battery/check-dir-rule.py --profile current <レポートディレクトリ>
#         python3 skill/scripts/tools/battery/check-dir-rule.py --profile v1 [ディレクトリ]
#         （`--profile` 無しは合否を出さないので第 56 ラウンドで無くした）
import json
import pathlib
import sys

import _inputs as IN

# `skill/scripts/tools/battery/check-invariants46.py` の `arrow_at` / `step_dir` / `fold` と同じ規則を、
# レポート JSON を読むだけのために書き写したもの（あの検査器は import すると 18 起動条件を
# 実行してしまうので、ここでは import しない）。実装 `report.mjs` の `dirOfStep` との一致は
# 検査器側が 2217 行で 0 違反を測っているので、そちらを正本にする
MOVEMENT = {'triggers', 'invokes', 'handler', 'exposed-by'}
FLIP_INTO_IMPL = {'exposed-by', 'handler'}
ARROW_REVERSED = {'exposed-by'}


def arrow_at(edge, node):
  tail = edge['source'] if edge['kind'] in ARROW_REVERSED else edge['target']
  return tail == node


def step_dir(edge, node, inherited, start_is_endpoint):
  kind = edge['kind']
  if kind in MOVEMENT:
    if arrow_at(edge, node):
      return 'out'
    if kind in FLIP_INTO_IMPL and start_is_endpoint:
      return 'out'
    return 'in'
  if edge['provenance'] == 'terraform':
    return inherited
  return 'out' if arrow_at(edge, node) else 'in'


def fold(path, pairs, start_is_endpoint):
  vals = {'none'}
  for a, b in zip(path, path[1:]):
    cands = pairs.get((a, b), [])
    if not cands:
      return None
    nxt = set()
    for v in vals:
      for e in cands:
        nxt.add(step_dir(e, b, v, start_is_endpoint))
    vals = nxt
  return vals


BUCKETS = ['external.in', 'external.out', 'entries.in', 'entries.out', 'artifacts.in', 'artifacts.out',
           'sameApi', 'siblingEndpoints', 'wiring']


def rows_of(doc):
  out = []
  for b in BUCKETS:
    part = doc[b.split('.')[0]][b.split('.')[1]] if '.' in b else doc[b]
    for x in part:
      out.append((b, x))
  return out


def check_dir(d):
  """18 本を読んで 向き を照合し、レポート別の実測を返す

  以前は合計だけ出していた。18 本あっても行が空なら「一致 0 / 不一致 0」で終了 0 に
  なったので（第 54 ラウンド agy 指摘 2）、レポート別の件数と不一致の内訳も返す"""
  agree = bad = loose = nopath = bad_domain = 0
  by_report, diffs, examples = {}, [], []
  # 18 条件ぶんを要求する（1 本だけのディレクトリで「一致 N / 不一致 0」を出して
  # 終了 0 にしない。第 53 ラウンド agy P2: 1/18 でも通っていた）
  for p in IN.report_paths(IN.require(IN.resolve_cli_path(d, default=None), 'レポートディレクトリ'), expect=18,
                           what='照合する 18 条件'):
    doc = json.loads(p.read_text())
    # 記録された作者パスは今のリポジトリの実体へ解決する（第 52 ラウンド双人レビュー両名 P2:
    # ここを生パスで開くと別クローンと掃除後に FileNotFoundError になった）
    graph = json.loads(IN.graph_path(doc['summary']['graph']).read_text())
    pairs = {}
    for e in graph['edges']:
      pairs.setdefault((e['source'], e['target']), []).append(e)
      pairs.setdefault((e['target'], e['source']), []).append(e)
    sie = bool(doc['summary'].get('startIsEndpoint'))
    here = {'agree': 0, 'bad': 0, 'loose': 0, 'nopath': 0, 'badDomain': 0}
    by_report[p.name] = here
    for b, r in rows_of(doc):
      path = r.get('path') or []
      if len(path) < 2:
        nopath += 1
        here['nopath'] += 1
        continue
      vals = fold(path, pairs, sie)
      if vals is None:
        nopath += 1
        here['nopath'] += 1
        continue
      if len(vals) > 1:
        loose += 1
        here['loose'] += 1
        continue
      want = next(iter(vals))
      if r.get('direction') not in ('in', 'out', 'none'):
        bad_domain += 1
        here['badDomain'] += 1
        continue
      if r['direction'] == want:
        agree += 1
        here['agree'] += 1
      else:
        bad += 1
        here['bad'] += 1
        # 不一致は「何件」だけでなく中身を持つ（v1 基準では既知差分 55 件と突き合わせる）
        diffs.append((p.name, r['id'], r['direction'], want))
        if len(examples) < 4:
          examples.append(f'{p.name} {r["id"]} v1/記録={r["direction"]} 今回の規則なら={want}'
                          f' 欄={b} 経路={"|".join(path)}')
  return {'agree': agree, 'bad': bad, 'loose': loose, 'nopath': nopath,
          'badDomain': bad_domain, 'byReport': by_report, 'diffs': diffs,
          'examples': examples}


USE = ('使い方: python3 skill/scripts/tools/battery/check-dir-rule.py '
       '--profile current <レポートディレクトリ>\n'
       '        python3 skill/scripts/tools/battery/check-dir-rule.py --profile v1 [ディレクトリ]\n'
       '  （--profile を付けない走らせ方は数を眺めるためのもので、合否は出さない。'
       '合否は期待値 expectations.dirRule と突き合わせる --profile で決める）')


def _profile_main(prof, d, emit=None):
  """期待値 expectations.dirRule.<prof> と突き合わせて合否を決める"""
  exp = IN.expectations()['dirRule'].get(prof)
  if not isinstance(exp, dict):
    IN.fail(f'期待値に expectations.dirRule.{prof} が無い（作り直し: '
            'python3 skill/scripts/tools/battery/emit-required.py '
            'skill/scripts/tools/battery/required-checks.json）')
  got = check_dir(d)
  print(f'{d}: 一致 {got["agree"]} / 不一致 {got["bad"]} / 並行縁で不定 {got["loose"]}'
        f' / 経路を読めない {got["nopath"]} / 向き の値域外 {got["badDomain"]}')
  for x in got['examples']:
    print('   ', x)
  if emit:
    # 要求一覧の expectations.dirRule.<prof> を作り直す材料（レポート別の比較件数も持つ）
    _e = IN.emit_measured(emit, f'dirRule.{prof}', {
        'agree': got['agree'], 'bad': got['bad'], 'loose': got['loose'],
        'nopath': got['nopath'], 'badDomain': got['badDomain'],
        'byReport': {k: sum(v.values()) for k, v in got['byReport'].items()}})
    print(f'向き 規則の実測を書き出した: {_e}')
  bad = []
  for k, name in (('agree', '一致'), ('bad', '不一致'), ('loose', '並行縁で不定'),
                  ('nopath', '経路を読めない'), ('badDomain', '向き の値域外')):
    if IN.guard('dir-rule-counters') and got[k] != exp[k]:
      bad.append(f'{name}: 期待 {exp[k]} / 今回 {got[k]}')
  # 合計が同じでも条件間の増減が相殺するので、レポート別の比較件数を正本にする
  want_by, got_by = exp['byReport'], {k: sum(v.values()) for k, v in got['byReport'].items()}
  for name in sorted(set(want_by) | set(got_by)):
    if IN.guard('dir-rule-report') and want_by.get(name) != got_by.get(name):
      bad.append(f'{name} の比較件数（レポート別）: 期待 {want_by.get(name)} / 今回 {got_by.get(name)}')
  if prof == 'v1':
    # v1 基準は 55 件不一致が出る**前提**。新しい一覧は作らず、既知差分 JSON の行差分
    # 58 件のうち 向き が変わった 55 件から導いて照合する（件数だけでなく中身も）
    want_diffs = IN.expected_direction_diffs()
    got_diffs = set(got['diffs'])
    if IN.guard('dir-rule-v1'):
      for x in sorted(got_diffs - want_diffs)[:8]:
        bad.append('既知差分に無い不一致: %s %s 記録=%s → 今回の規則=%s' % x)
      for x in sorted(want_diffs - got_diffs)[:8]:
        bad.append('既知差分にある不一致が今回出ない: %s %s 記録=%s → 今回の規則=%s' % x)
  if bad:
    print(f'期待値と食い違う {len(bad)} 件:', file=sys.stderr)
    for x in bad[:20]:
      print('  ', x, file=sys.stderr)
    return 1
  print(f'期待値（expectations.dirRule.{prof}）と一致: 比較 {got["agree"] + got["bad"]} 件の内訳まで同じ')
  return 0


def main(argv):
  flags, args = IN.parse_flags(list(argv))
  emit = flags.get('--emit-measured')
  prof = flags.get('--profile')
  # 第 56 ラウンド agy P2: `--profile` を付けないと「不一致が出ても終了 0」で通った。
  # 探索専用だったその道を消す（何も比較していない日の見張り番はプロファイル側の
  # `dir-rule-counters` と `path-empty` が同じ働きをしているので、検査は減らない）
  if prof is None:
    raise SystemExit('--profile current / v1 を付ける（付け忘れた実行は合否を出さない。'
                     '第 56 ラウンドで無しモードを無くした）\n' + USE)
  if prof not in ('current', 'v1'):
    raise SystemExit(f'--profile は current / v1 のどちらか: {prof}')
  if prof == 'v1' and not args:
    return _profile_main(prof, str(IN.HERE / 'baseline-v1'), emit)
  if not args:
    raise SystemExit('--profile current はレポートディレクトリを渡す'
                     '（既定の置き場所を勝手に決めない）\n' + USE)
  # 明示した相対パスは実行時の cwd から解決する（第 55 ラウンド Astra 裁定 問 5）
  return _profile_main(prof, str(IN.resolve_cli_path(args[0])), emit)


if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))