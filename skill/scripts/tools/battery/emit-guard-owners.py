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
# 終了コード（Astra 第 67 ラウンド 問 3 の裁定 3）:
#   0 = 今の台帳と候補が一致   3 = 候補は有効だが差分が有る   1 = 候補が作れない・検証が通らない
# 「差分が有るのに 0」を通さない為、`--emit` で書いた後も差分が有る日は 3 を返す。
# `--emit` は**運用中の台帳へ直接書けない**（同じ裁定 4。候補は別のファイルへ書き、人が差分を
# レビューしてからのせ替える）。検証した候補・表示した差分・書き出した JSON は同一の物を使う
# （同じ裁定 5。表示し直して別の物を書かない）
#
# 使い方:
#   python3 skill/scripts/tools/battery/emit-guard-owners.py                      # 差分を表示するだけ
#   python3 skill/scripts/tools/battery/emit-guard-owners.py --emit <候補のpath>  # 候補を書く（人はレビュー）
#
# 豁免（`exemptions`）はこの道具では**作らない**。現在の値をそのまま引き継ぐ。豁免を 1 件登録する
# のは人の判断で、登録するときは `imports` に許す名前を書く（Astra 第 63 ラウンド 問 1）。
# 承認の重みは豁免 > `boxNames` > `owners`（Astra 第 67 ラウンド 問 3 の裁定: 豁免は従来拒否して
# いた import と利用経路を解禁し、`boxNames` は箱の公開面と用途を決め、`owners` は観測の写し。
# どれか 1 つでも人の採用を省略してよい区分にはしない）
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
        '作る（Astra 第 66 ラウンド 追記の裁定 (ア)、第 67 ラウンド 問 2 の 6 マス）')


def _exempt_keys(doc):
    """豁免を 1 行のキーへ潰す（差分表示用。`imports` の中身まで同じなら同じキー）"""
    out = set()
    for e in doc.get('exemptions') or []:
        mods = e.get('imports') or {}
        body = ';'.join(f'{m}={",".join(sorted(v))}' for m, v in sorted(mods.items()))
        out.add(f"{e.get('file')}?{body}")
    return out


def candidate_refusals(used, holes):
    """候補を出す前に拒否する理由を並べる（`emit-candidate-valid`。Astra 第 67 ラウンド 問 3）

    候補の表を渡した走査に穴が残る場合と、箱の公開名に台帳へ書けない形（書き換え・2 用途）が
    有る場合。制御が単独で名指せるように報告は戻り値で返し、`IN.guard` はここ 1 箇所で読む"""
    if not IN.guard('emit-candidate-valid'):
        return []
    out = []
    wrote = sorted(n for n, kinds in used.items() if 'write' in kinds)
    if wrote:
        out.append(f'見張り番の箱の公開名 {wrote[:6]} を書き換え・削除に使っているファイルが有る'
                   f'{" …ほか " + str(len(wrote) - 6) + " 件" if len(wrote) > 6 else ""}'
                   '（`boxNames` は `call` / `const` のどちらか 1 つしか書けず、書き換えは用途に'
                   'できない。Astra 第 67 ラウンド 問 2）')
    both = sorted(n for n, kinds in used.items() if len(kinds) > 1)
    if both:
        out.append(f'見張り番の箱の公開名 {both[:6]} が呼び出しと読み取りの両方で使われている'
                   f'{" …ほか " + str(len(both) - 6) + " 件" if len(both) > 6 else ""}'
                   '（`boxNames` は 1 名 1 用途。使い方を揃えてから候補を作り直す）')
    if holes:
        out.append(f'走査に穴が {len(holes)} 件有る（{holes[0][:100]}）。対応表の候補を作る前に'
                   '見張り番の走査の穴を 0 件にすること（穴が残った対応表は「読めた範囲」を'
                   '台帳に書き写すだけになる）')
    return out


def target_errors(live, dest):
    """`--emit` の書き先が運用中の台帳その物かを見る（`emit-target`。Astra 第 67 ラウンド 問 3 の裁定 4）

    候補は別のファイルへ書き、人が差分をレビューしてから運ぶ。自動で運用台帳を上書きする道を
    置かない為の検査なので、書き先の比較は `resolve()` でした違いの表記（`./` など）でも拒否する"""
    if not IN.guard('emit-target'):
        return []
    if dest.resolve() == live.resolve():
        return [f'運用中の台帳 {IN.GUARD_LEDGER_FILE} へ直接書いてはいけない（候補は別のファイルへ'
                '書き、人が差分をレビューしてから運ぶ。Astra 第 67 ラウンド 問 3 の裁定 4）']
    return []


def candidate(root, keep_exemptions):
    """台帳の候補を作る。箱の公開名の表は**作ったばかりの候補**で検証する

    Astra 第 67 ラウンド 問 3 の裁定: 新しい `IN.<公開名>` を足した日は旧表ですでに穴が出る為、
    旧表での走査を要求すると候補が作れない（Codex 第 66 ラウンド P2-3 の実測）。候補表を明示的な
    引数として共通の走査へ渡す（台帳・グローバル状態・既定値は差し替えない）。ここで示すのは
    「この候補を採用した場合に構文上整合する」ことで「今の台帳で合格する」ことではない。
    通常検査は旧台帳を使い続けるので、人が採用するまで実ツリーの検査は落ち続ける"""
    files = sorted(str(p.relative_to(root))
                   for p in (root / 'skill' / 'scripts' / 'tools').rglob('*.py'))
    # 見張り番の箱の公開名（Astra 第 66 ラウンド 追記の裁定 (ア): 用途付きの許可表）。走査と
    # 同じ `_box_form` で数えた形を使うので、候補だけが読み取りに数えて用途を塗り替えることが無い
    used = tc._box_used_attrs()
    # 書き換えは用途にできないので表を作らず、走査には「書き換えを除いた形」の表を渡す
    # （見張り番の公開名を書き換えに使っている日は、上の拒否で候補が出ない）
    box = {n: sorted(kinds - {'write'})[0] for n, kinds in used.items() if kinds - {'write'}}
    # 台帳の豁免を渡して走査する（豁免つきの走査が主。Astra 第 64 ラウンド 問 2 裁定 (iii)）
    exempt_by_file = tc._exempt_index_of({'exemptions': list(keep_exemptions)}) or None
    # 無効化の区間を作れるファイルの一覧も今の走査から作る（Astra 第 68 ラウンド 問 1 の B案:
    # 無効化を呼べる場所を台帳で絞る。旧台帳の表ではなく今の実測で検証する）
    callers = tc._guard_switch_callers()
    names, direct, counts, holes, _calls = tc._guard_names_by_file(exempt_by_file, box, callers)
    errs = candidate_refusals(used, holes)
    if errs:
        for x in errs:
            print(f'# {x}')
        IN.fail('候補を作れない（上の理由を直してから作り直す）')
    # `direct` は「道具 -> 名前」なので台帳の形（名前 -> 直接呼ぶ道具）へ裏返す
    owners = {n: sorted(tool for tool, got in direct.items() if n in got) for n in sorted(names)}
    return {'note': NOTE, 'scannedFiles': files, 'owners': owners,
            'exemptions': list(keep_exemptions), 'boxNames': dict(sorted(box.items())),
            'guardCallers': callers}


def diff_lines(old, new):
    """今の台帳と候補の差分を**全て**出す（Astra 第 67 ラウンド 問 3 の裁定: 差分を表示しないのは
    「台帳が一致している」との誤報。`boxNames` と `exemptions` も比較する）"""
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
    if IN.guard('emit-diff'):
        ob, nb = old.get('boxNames') or {}, new['boxNames']
        for verb, xs in (('追加', sorted(set(nb) - set(ob))), ('削除', sorted(set(ob) - set(nb)))):
            if xs:
                out.append(f'箱の公開名 {verb} {len(xs)} 件: {", ".join(xs[:8])}'
                           + (f' …ほか {len(xs) - 8} 件' if len(xs) > 8 else ''))
        changed = [(n, ob[n], nb[n]) for n in sorted(set(ob) & set(nb)) if ob[n] != nb[n]]
        if changed:
            out.append(f'箱の公開名の用途の変わり目 {len(changed)} 件: ' + ', '.join(
                f'{n}（{a} → {b}）' for n, a, b in changed[:6]))
        oc, nc = set(old.get('guardCallers') or []), set(new.get('guardCallers') or [])
        for verb, xs in (('追加', sorted(nc - oc)), ('削除', sorted(oc - nc))):
            if xs:
                out.append(f'無効化の区間を使えるファイル {verb} {len(xs)} 件: '
                           f'{", ".join(xs[:6])}'
                           + (f' …ほか {len(xs) - 6} 件' if len(xs) > 6 else ''))
        oa, na = _exempt_keys(old), _exempt_keys(new)
        for verb, xs in (('追加', sorted(na - oa)), ('削除', sorted(oa - na))):
            if xs:
                out.append(f'豁免 {verb} {len(xs)} 件: {", ".join(x[:70] for x in xs[:4])}'
                           + (f' …ほか {len(xs) - 4} 件' if len(xs) > 4 else ''))
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
          f'豁免 {len(new["exemptions"])} 件・箱の公開名 {len(new["boxNames"])} 名'
          f'（対象 {IN.GUARD_LEDGER_FILE}）')
    d = diff_lines(old, new) if old else None
    if old:
        print('# 今の台帳との差分: ' + ('無し（台帳は今の走査と合っている）'
                                     if not d else f'{len(d)} 行'))
        for x in d:
            print(f'#   {x}')
    else:
        print('# 今の台帳が無い（初めての作成）')
    written = None
    if '--emit' not in sys.argv:
        print('# 書き出しはしていない（書くには --emit <候補の path>。運用中の台帳には書けない）')
    else:
        args = sys.argv[1:]
        dest = args[args.index('--emit') + 1] if args.index('--emit') + 1 < len(args) else None
        if not dest:
            IN.fail('--emit の後に書き先（運用中の台帳以外）を 1 つ書くこと')
        # 明示した相対パスは cwd から解決する（他の道具と同じ慣習。第 67 ラウンドまでは
        # `root / p` でリポジトリ基準にしていた為、`battery/` から `--emit guard-owners.json` と
        # 打つとリポジトリ直下へ書かれた（agy P2-1 の実測 `written at repo root exists = True`）
        p = IN.resolve_cli_path(dest)
        bad = target_errors(path, p)
        if bad:
            IN.fail(bad[0])
        # 検証した候補と同じ object を書く（表示し直して別の物を書かない。同じ裁定 5）
        p.write_text(json.dumps(new, ensure_ascii=False, indent=1, sort_keys=True) + '\n',
                     encoding='utf-8')
        written = p
        print(f'# 候補を書いた: {p}（**自動更新ではなく候補**。人が差分をレビューして運ぶ）')
    if d:
        print(f'# 終了 3: 候補は有効だが今の台帳と差分が {len(d)} 行有る'
              '（人がレビューして運ぶまで実ツリーの検査は落ち続ける）')
        return 3
    return 0


if __name__ == '__main__':
    sys.exit(main())
