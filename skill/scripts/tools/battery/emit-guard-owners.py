#!/usr/bin/env python3
# 見張り番の対応表 `guard-owners.json` の**候補を書き出す**道具（自動更新しない）
#
# `required-checks.json` と同じ約束（第 52 ラウンド Astra 裁定 1、第 63 ラウンド Astra 裁定 問 4）。
# 実行結果から自動で上書きする仕組みは置かない。生成された候補を**人がレビューしてコミットする**
# から、人が見張り番の名前を付け替えた日・所属する道具を動かした日が機械に決まる。
#
# 何が機械に決まるか（Astra 第 63 ラウンド 問 4 の表のまま）:
#   * 名前集合の一致           … 同数のまま行われる名前の削除・置換の検出
#   * 名前と所属道具の対応の一致 … 同じ名前が別の道具へ移ったことの検出
#   * 走査対象ファイル集合の一致 … 検査対象からファイルが脱落したことの検出
#   * 穴 0 件                  … 既知の禁止形の混入の検出
#
# 使い方:
#   python3 skill/scripts/tools/battery/emit-guard-owners.py                 # 差分を表示するだけ
#   python3 skill/scripts/tools/battery/emit-guard-owners.py --emit <path>   # 候補を書く（人はレビュー）
#
# 豁免（`exemptions`）はこの道具では**作らない**。現在の値をそのまま引き継ぐ。豁免を 1 件登録する
# のは人の判断で、登録するときは `imports` に許す名前を書く（Astra 第 63 ラウンド 問 1）
import importlib.util
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location('tc', HERE / 'test-contract.py')
tc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tc)      # `sys.modules` に載せない（載せると見張り番の走査が穴と数える形）
import _inputs as IN            # noqa: E402  test-contract.py の後に読む（同じ走査を共有する為）

NOTE = ('見張り番の名前と、その名前を**直接呼ぶ**道具の対応表。走査（test-contract.py の '
        '_guard_names_by_file）から見つかる集合とその場で比べる台帳で、実行結果から自動更新しない。'
        '作り直しは emit-guard-owners.py（候補の書き出し）。exemptions は走査対象のファイルが'
        '許可一覧（test-contract.py の `_ALLOWED_IMPORTS`）に無い import を使う時に、そのファイルで'
        '許す import と名前だけを書く（Astra 第 63 ラウンド 問 1・第 64 ラウンド 問 1 裁定 (c)。'
        'ファイル全体の豁免は置けず、動的機構の名前（exec / compile / FunctionType / modules など）は'
        '豁免で登録できない。第 64 ラウンド 問 2 裁定 (i)。豁免はファイルの正準相対パス ×'
        '完全修飾モジュール × 許可する末端名で持つ（Astra 第 66 ラウンド 問 1 の裁定）。'
        'boxNames は見張り番の箱 `IN` の公開名と用途（call / const）で、実ツリーの使用から'
        '作る（Astra 第 66 ラウンド 追記の裁定 (ア)）')


def candidate(root, keep_exemptions):
    files = sorted(str(p.relative_to(root))
                   for p in (root / 'skill' / 'scripts' / 'tools').rglob('*.py'))
    # 台帳の豁免を渡して走査する（豁免つきの走査が主。Astra 第 64 ラウンド 問 2 裁定 (iii)）
    exempt_by_file = tc._exempt_index_of({'exemptions': list(keep_exemptions)}) or None
    names, direct, counts, holes, _calls = tc._guard_names_by_file(exempt_by_file)
    if holes:
        print(f'# 走査に穴が {len(holes)} 件有る（{holes[0][:100]}）')
        IN.fail('対応表の候補を作る前に見張り番の走査の穴を 0 件にすること'
                '（穴が残った対応表は「読めた範囲」を台帳に書き写すだけになる）')
    # `direct` は「道具 -> 名前」なので台帳の形（名前 -> 直接呼ぶ道具）へ裏返す
    owners = {n: sorted(tool for tool, got in direct.items() if n in got) for n in sorted(names)}
    # 見張り番の箱の公開名（Astra 第 66 ラウンド 追記の裁定 (ア): 用途付きの許可表）。実ツリーで
    # 呼び出しにしか使っていない名前は `call`、読み取りだけなのは `const`。両方の名前はここで
    # 止める（表が 1 名 1 用途しか書けない為、人の側で使い方を揃えないと候補が出せない）
    used = tc._box_used_attrs()
    both = sorted(n for n, kinds in used.items() if len(kinds) > 1)
    if both:
        IN.fail(f'見張り番の箱の公開名 {both[:6]} が呼び出しと読み取りの両方で使われている'
                f'{" …ほか " + str(len(both) - 6) + " 件" if len(both) > 6 else ""}'
                '（`boxNames` は 1 名 1 用途。使い方を揃えてから候補を作り直す）')
    box = {n: sorted(kinds)[0] for n, kinds in used.items()}
    return {'note': NOTE, 'scannedFiles': files, 'owners': owners,
            'exemptions': list(keep_exemptions), 'boxNames': dict(sorted(box.items()))}


def diff_lines(old, new):
    out = []
    for label, a, b in (('名前', set(old.get('owners') or {}), set(new['owners'])),
                        ('走査対象', set(old.get('scannedFiles') or []), set(new['scannedFiles']))):
        for verb, xs in (('追加', sorted(b - a)), ('削除', sorted(a - b))):
            if xs:
                out.append(f'{label} {verb} {len(xs)} 件: {", ".join(xs[:8])}'
                           + (f' …ほか {len(xs) - 8} 件' if len(xs) > 8 else ''))
    moved = [(n, old['owners'][n], new['owners'][n]) for n in sorted(set(old.get('owners') or {})
             & set(new['owners'])) if old['owners'][n] != new['owners'][n]]
    if moved:
        out.append(f'所属の変わり目 {len(moved)} 件: ' + ', '.join(
            f'{n}（{"/".join(a)} → {"/".join(b)}）' for n, a, b in moved[:6]))
    return out


def main():
    root = IN.repo_root()
    path = root / IN.GUARD_LEDGER_FILE
    old = {}
    if path.exists():
        old = json.loads(path.read_text(encoding='utf-8'))
        bad = IN.guard_ledger_shape_errors(old)
        if bad:
            IN.fail_guard_ledger(bad)
    new = candidate(root, old.get('exemptions') or [])
    bad = IN.guard_ledger_shape_errors(new)
    if bad:
        IN.fail_guard_ledger(['作ろうとした候補自体が壊れている'] + bad)
    print(f'# 候補: 見張り番 {len(new["owners"])} 名・走査対象 {len(new["scannedFiles"])} ファイル・'
          f'豁免 {len(new["exemptions"])} 件（対象 {IN.GUARD_LEDGER_FILE}）')
    if old:
        d = diff_lines(old, new)
        print('# 今の台帳との差分: ' + ('無し（台帳は今の走査と合っている）' if not d else ''))
        for x in d:
            print(f'#   {x}')
    else:
        print('# 今の台帳が無い（初めての作成）')
    if '--emit' not in sys.argv:
        print('# 書き出しはしていない（書くには --emit <path>。書いた後は人がレビューしてコミット）')
        return 0
    args = sys.argv[1:]
    dest = args[args.index('--emit') + 1] if args.index('--emit') + 1 < len(args) else None
    if not dest:
        IN.fail('--emit の後に書き先を 1 つ書くこと')
    p = pathlib.Path(dest)
    if not p.is_absolute():
        p = root / p
    p.write_text(json.dumps(new, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                 encoding='utf-8')
    print(f'# 候補を書いた: {p}（**自動更新ではなく候補**。人が差分をレビューしてコミットする）')
    return 0


if __name__ == '__main__':
    sys.exit(main())
