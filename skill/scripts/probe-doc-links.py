#!/usr/bin/env python3
"""`doc_pointers_resolve` が**縮小後の契約**どおりに動く事を示す道具

Astra 第 21 ラウンドの裁定で、この検査は**固定書式の案内（コードで囲まれた `skill/…` `docs/…`
`demo/…` `README.md` の path）の実在だけ**を見る事にしました。Markdown の記法（リンクの宛先・
見出しのアンカー・`][`・フェンスとコードの読み分け・項目数の文書間一致）は測りません。なので本見本は
**測る物が落ちる**事と、**測らない物が通る**事を並べます（撤去した保証を静かに消さない為の実演）。

```sh
python3 skill/scripts/probe-doc-links.py
```

`tempfile` に仮のリポジトリを作って測ります。本リポジトリの `out/` 配下でやると `.gitignore` の
`out/` のせいで「git に無視される物」の規則が正しく測れない為です。
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

Q = '`'
CASES = [
    # --- 測る物: コードで囲まれた path の実在 ---
    (f'{Q}README.md{Q}', '通る', '実在する README への案内'),
    (f'{Q}skill/a.md{Q}', '通る', '実在する文書への案内'),
    (f'{Q}skill/no-such-1.md{Q}', '落ちる', '実在しない案内を落とす'),
    (f'{Q}docs/no-such-2.md{Q}', '落ちる', 'docs 配下も同じ'),
    (f'{Q}demo/no-such-3/orders.tf{Q}', '落ちる', 'demo 配下も同じ。階層が深くても同じ'),
    ('```', '通る', 'フェンス開き'),
    (f'{Q}skill/no-such-4.py{Q}', '落ちる', 'フェンスの中の設定例の path も案内'),
    ('```', '通る', 'フェンス閉じ'),
    (f'{Q}skill/analyzer/bin/x.js{Q}', '通る', 'git に無視されるビルド成果物は落とさない'),
    (f'{Q}skill/a.md{Q} と {Q}skill/no-such-5.md{Q}', '落ちる', '1 行に 2 つ有れば欠けた方だけ落とす'),
    # --- 測らない物: 撤去した保証を人の目へ返した事を見せておく ---
    ('[壊](no-such-6.md)', '通る', 'Markdown リンクの宛先は測らない（人の目へ返した）'),
    ('[壊](<no-such-7.md>)', '通る', '山括弧形も同じ'),
    ('[飛ぶ](#no-such-8)', '通る', '見出しのアンカー検査は撤去した'),
    ('[説明][定義]', '通る', '参照リンクの禁止は撤去した（別の文書規約）'),
    ('[壊', '通る', '改行で割れているリンクを測らない'),
    ('](', '通る', '読めない書き方を理由に落とす規則も撤去した'),
    ('node skill/scripts/report.mjs # 説明（130 項目）', '通る', '道具の呼び出し例'),
    ('node skill/scripts/report.mjs # 説明（131 項目）',
     '通る', '項目数の食い違いは測らない（本体の実測へ返した）'),
    ('skill/no-such-9.md', '通る', 'コードで囲んでいない path は固定書式ではない'),
    (f'{Q}../no-such-10.md{Q}', '通る', '固定書式は 4 種の頭（skill / docs / demo / README）だけ'),
]
lines = [txt for txt, _, _ in CASES]
(ROOT / 'README.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
(ROOT / 'skill' / 'a.md').write_text('# 実在確認\n', encoding='utf-8')

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
    print(f'{印}  {i:2} {名前:36} 期待={期待} 実際={実}  {hits[:1]}')
print(f'診断の総数: {len(got)} / 不一致 {bad} 件')
shutil.rmtree(BASE, ignore_errors=True)
sys.exit(1 if bad else 0)
