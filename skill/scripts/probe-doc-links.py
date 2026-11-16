#!/usr/bin/env python3
"""文書の案内先を検査する `doc_pointers_resolve` が、指摘された形を実際に落とす事を示す道具

双人レビュー（Codex / agy）で出たリンクの読み方の指摘を 1 本ずつ並べ、**期待とおりに通る・落ちる**を
終了コードで返します（不一致 0 なら終了 0）。仮のリポジトリを `tempfile` で作って測ります。本リポジトリの
`out/` 配下でやると `.gitignore` の `out/` のせいで「git に無視される物」の規則が正しく測れない為です。

```sh
python3 skill/scripts/probe-doc-links.py
```
"""
import importlib.util
import pathlib
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'tools' / 'battery'))

BASE = pathlib.Path(tempfile.mkdtemp(prefix='probe-doc-links-'))
ROOT = BASE / 'wt'
subprocess.run(['git', 'init', '-q', str(ROOT)], check=True)
(ROOT / 'skill' / 'analyzer' / 'bin').mkdir(parents=True)
(ROOT / '.gitignore').write_text('bin/\n', encoding='utf-8')
# 双人レビュー第 76 / 77 ラウンドの指摘を 1 本ずつ。期待は「通る」「落ちる」の 2 つだけ
CASES = [
    ('[ok](README.md)', '通る', '素'),
    ('[ok](<README.md>)', '通る', '山括弧'),
    ('[ok](README.md "題名")', '通る', 'タイトル付き'),
    ('[外](https://example.com/)', '通る', '外部'),
    ('`[broken](no-such.md)` はコード内の例', '通る', 'コード内の例'),
    ('`perms[::step][:cap]` はコード内の ][', '通る', 'コード内の ]['),
    ('``a` b`` 本文 [壊](no-such-8.md)', '落ちる', '同じ長さの組だけコード'),
    ('```', '通る', 'フェンス開き'),
    ('[ref][1] フェンス内の参照リンク風', '通る', 'フェンス中は記法を見ない'),
    ('```', '通る', 'フェンス閉じ'),
    ('[broken](does-not-exist.md "title")', '落ちる', 'タイトル付きの壊れ'),
    ('[broken](does-not-exist.md)', '落ちる', '素の壊れ'),
    ('[壊](no-such-2.md) は素の相対リンク', '落ちる', '素の相対リンク'),
    ('[ref][1] 参照リンク', '落ちる', '参照リンク'),
    ('[空](<>)', '落ちる', '空の宛先'),
    ('[脱](../../etc/passwd)', '落ちる', 'リポジトリの外へ出る'),
    ('[a[b]](no-such-3.md)', '落ちる', '角括弧のネストは読めない'),
    ('`skill/analyzer/bin/x.js` はビルドで建つ', '通る', 'git に無視される物は実在を見ない'),
    ('[ビルド](skill/analyzer/bin/x.js)', '通る', 'リンクも同じ'),
]
lines = [txt for txt, _, _ in CASES]
(ROOT / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
(ROOT / 'skill' / 'a.md').write_text('# 実在確認\n', encoding='utf-8')

sys.path.insert(0, 'skill/scripts/tools/battery')
sp = importlib.util.spec_from_file_location('tc', 'skill/scripts/tools/battery/test-contract.py')
tc = importlib.util.module_from_spec(sp)
sp.loader.exec_module(tc)
tc.REPO = ROOT.resolve()
tc.doc_pointers_resolve()
got = tc.failed
bad = 0
for i, (txt, 期待, 名前) in enumerate(CASES, 1):
    hits = [g for g in got if g.startswith(f'README.md:{i}:')]
    実 = '落ちる' if hits else '通る'
    印 = 'OK' if 実 == 期待 else '不一致'
    bad += 印 != 'OK'
    print(f'{印}  {i:2} {名前:26} 期待={期待} 実際={実}  {hits[:1]}')
print(f'診断の総数: {len(got)} / 不一致 {bad} 件')
shutil.rmtree(BASE, ignore_errors=True)
sys.exit(1 if bad else 0)
