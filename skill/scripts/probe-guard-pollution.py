#!/usr/bin/env python3
"""実行器の自己検査（`_runner_self_check`）が **5 規則すべて**で細工を検出する事を測る道具

`test-contract.py` は「記録の形が壊れる / 実在のキーへの未登録の混入 / 同じ記録の二重計上 /
登録と逆の階級 / 階級が unknown になる」の 5 規則を診断の目印 `[規則=…]` で持ちます。自己検査は
**偽の記録を細工して目印が 1 件増える**事を測るので、その細工が 5 規則すべてに効いている事を
ここで独立に確かめます（双人レビュー Codex 第 74 ラウンド P2-1 / agy 第 74 ラウンド P2-1、
agy 第 75 ラウンド P2-4 で「細工が 3 形だけ」だった取り残しの再発止め）。

```sh
python3 skill/scripts/probe-guard-pollution.py     # 不一致 0 なら終了 0
```

見張り番の走査（`skill/scripts/tools/**/*.py`）の対象外に置く。`import` の登録を要求する走査に
新しい `import` を増やさない為で、規則の弱体化ではありません（双人レビュー第 78 ラウンドの実測）
"""
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'tools' / 'battery'))
sp = importlib.util.spec_from_file_location('tc', HERE / 'tools' / 'battery' / 'test-contract.py')
tc = importlib.util.module_from_spec(sp)
sp.loader.exec_module(tc)
失敗 = []


class _One:
    """`read_text` だけ返す假的なファイル（`_negative_calls` の読みを単体で見る）"""

    def __init__(self, s):
        self.s = s

    def read_text(self, **kw):
        return self.s


def run(base, tiers, title, 期待形):
    print(f'--- {title}')
    tc.ran['singleton'] = base
    forms = tc._record_pollutions(tiers)
    前 = tc.singleton_record_errors({k: list(v) for k, v in base.items()}, set(tiers), tiers)
    if len(forms) != 期待形:
        失敗.append(f'{title}: 細工が {len(forms)} 形（期待 {期待形}）')
    for label, forge, why, mark in forms:
        cp = {k: list(v) for k, v in base.items()}
        forge(cp)
        後 = tc.singleton_record_errors(cp, set(tiers), tiers)
        n前 = sum(1 for e in 前 if e.startswith(f'[規則={mark}]'))
        n後 = sum(1 for e in 後 if e.startswith(f'[規則={mark}]'))
        print(f'  {label}: 目印「{mark}」 {n前} -> {n後}')
        if n後 != n前 + 1:
            失敗.append(f'{title} / {label}: 目印「{mark}」が {n前} -> {n後}（1 件増が期待）')
        if cp == base:
            失敗.append(f'{title} / {label}: 細工が記録を変えていない（空振り）')


def run_ast(label, code, 動的と期待):
    読めない = tc._negative_unreadable(_One(code))
    出た = any(動的 in x for x in 読めない)
    print(f'{label}: 読めない={読めない}')
    if 出た != 動的と期待:
        失敗.append(f'{label}: 「{動的}」が{"出ない" if 動的と期待 else "出た"}')


# 細工の形: 正常な記録は 5 形。重複済みのキーしか無い日は重複の細工を作らないので 4 形
# （agy 第 74 ラウンド P2-1: 既に重複の有るキーへ細工すると「3 件並ぶ」になり目印が消えた）
run({'a': [('x', 'clean')], 'b': [('c1', 'clean')], 'c': [('c2', 'fallback')]},
    {('c1', 'b'): {'clean'}, ('c2', 'c'): {'clean'}}, '正常な記録', 5)
run({'b': [('c1', 'fallback'), ('c1', 'clean')]}, {('c1', 'b'): {'clean'}},
    '同名の先頭が既に逆階級（Codex 第 74 ラウンド P2-2）', 5)
run({'b': [('c1', 'clean'), ('c1', 'clean')]}, {('c1', 'b'): {'clean'}},
    '重複済みのキーしか無い日（agy 第 74 ラウンド P2-1）', 4)
run({'g': [('probe が宣言と逆', 'fallback'), ('probe が宣言と逆', 'clean')]},
    {('probe が宣言と逆', 'g'): {'clean'}}, '控制名が目印を含む日（Codex 第 74 ラウンド P2-1）', 5)

# `*args` と動的な引数: 静的に階級が決まらない控制は「読めない」へ出す。`*[]` の時に
# 「guards を位置とキーワードの両方に書いた」等の筋の違う案内を出さない（agy 第 74 ラウンド P2-2）
動的 = '単独名指しの控制が静的に読めない引数を持つ'
run_ast('*args が後ろに付く呼び出し', "negative('x', fn, 'g', *('msg', False, 'fb'))", False)
run_ast('guards に変数を渡す', "negative('x', fn, guards=FAKE, clean=flag)", False)
run_ast('単独名指しで clean が変数', "negative('x', fn, guards='g', clean=flag)", True)
run_ast('*[] とキーワード guards', "negative('a', fn, *[], guards='fp-sha')", True)
run_ast('*[] とキーワード clean=False', "negative('a', fn, *[], guards='g', clean=False)", True)
print(f'\n不一致 {len(失敗)} 件')
for x in 失敗:
    print('  x', x)
sys.exit(1 if 失敗 else 0)
