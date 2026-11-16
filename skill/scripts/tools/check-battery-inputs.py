#!/usr/bin/env python3
# 回帰バッテリー（`out/loop/protocol.md` §4-3）が読むファイルが揃っているか先に確かめる。
#   python3 skill/scripts/tools/check-battery-inputs.py
# 終了 1 で、無いファイルを全部挙げる。
#
# なぜ有るか: 第 48 ラウンドで `--changed` の入力（レビュー用クローンに置いていた変更一覧）が
# ディスク掃除で消え、性能ゲートの 250 回がすべて ENOENT なのに倍率 1.00 で「適合」した。
# 実行前に総点検しておくと「黙って前版を測る」「黙って条件が減る」の前に止まる。
#
# 第 50 ラウンド双人レビュー（agy P2）で、バッテリーの道具と基準データは追跡下の
# `skill/scripts/tools/battery/` へ移した（`out/tmp-*` に唯一のコピーを置くのが事故の元凶）。
#
# 第 51 ラウンド双人レビュー（両名 P2）で、この点検の穴を塞いだ。
#   1. 手書きの一覧だけを見ていた。`baseline-v1` の 18 条件が `summary.graph` に記録している
#      入力グラフ（7 条件が一時ディレクトリを指していた）を点検しておらず、42/42 で通りながら
#      `regen-audit.py` / `v1diff.py` / `via-cycle.py` / `same-output.py` / `cmp-head-proto.py` /
#      `check-dir-rule.py` が壊れていた。→ 記録パスを `_inputs.graph_path()` で解決して実在を見る
#   2. 検査側の道具が入力にしている実グラフ（`_inputs.extra_graphs()`）が点検に入っていなかった
#      → 一覧を `_inputs.py` に一本化し、ここはそれを読む
#   3. 実行される道具のコードが掃除対象の場所を指していないかを機械で確かめていなかった
#      → `skill/scripts/tools/` の道具のソースを走査して古い一時パスの残りを挙げる
#
# 第 52 ラウンド双人レビュー（対象 `91b59e9`、両名 P2）で残った穴:
#   1. 記録グラフ 18 件の**件数**を要求していなかった。1 件を除くと「記録グラフ 17 件が
#      揃っている」で終了 0（Codex 実測）→ `baseline-v1` は `expect=18` で数える
#   2. `edge-order.py`（この日で追跡下へ移した）と、`build.mjs` / `verify.mjs` が読む
#      `scan.mjs` / `scan-terraform.mjs` / `render.mjs` / `skill/viewer/template.html`、
#      注釈 JSON が点検リストに入っていなかった（agy）
#   3. 一時パスの走査が、ラウンド名の付いたディレクトリ指定だけ（末尾のファイル名なし）、
#      ラウンド名に接尾辞の付いたもの（`-docs` など）、`-full` の付かない監査出力、
#      文字列を `out` と `tmp-r<数字>` に分けて結合する形を見逃していた（agy / Codex）
#
# ただし走査は**補助**である（Codex の見解どおり、完全性の保証には使わない）。文字列を
# 組み合わせたパス・変数経由・実行時に作るパスは構文を見ないので、入力の完全性は
# 上記 1 と `_inputs.py` の `require()` / `graph_path()` が測る前に落とす側で担保する
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / 'battery'))
import _inputs as IN

REPO = IN.repo_root()
# 要求一覧の**中身**を先に点検する（第 57 ラウンド agy P2-3 実測: この道具は `fixtures` を
# 直読みするだけで `validate_required_spec` を呼ばないので、`fixtures` の重複も
# `expectations.dirRule.current.bad = -1` も終了 0 で通過していた。Astra 裁定 問 2 の末尾
# 「入力の所在だけでなく要求一覧の内容も測る入口なら共有検証を呼ぶ」。測定道具 4 本と同じ
# 入口なので、壊れた一覧は指紋検査より手前で「要求一覧が壊れている」案内に落ちる）
IN.validate_required_spec(IN.required_spec(REPO), REPO)
# 追跡下の fixture は `required-checks.json` の一覧が正本（glob で減らさない。第 53 ラウンド
# 双人レビュー両名 P2: 2 本消しても点検も不変条件検査も終了 0 だった）
FIXTURES = IN.required_spec()['fixtures']
FILES = [
    # スキル本体（追跡下）
    'skill/scripts/report.mjs', 'skill/scripts/query.mjs', 'skill/scripts/merge.mjs',
    'skill/scripts/build.mjs', 'skill/scripts/verify.mjs',
    'skill/scripts/test-analyzer.mjs', 'skill/scripts/test-merge.mjs',
    'skill/scripts/test-query.mjs', 'skill/scripts/test-terraform.mjs',
    'skill/scripts/test-report.mjs',
    'skill/scripts/tools/regen-audit.py', 'skill/scripts/tools/count-kinds.py',
    'skill/scripts/tools/make-changed-list.py', 'skill/scripts/tools/make-v2-graph.py',
    'skill/scripts/tools/perf-measure.py', 'skill/scripts/tools/perf-run.sh',
    'skill/scripts/tools/paired-gate.sh', 'skill/scripts/tools/check-battery-inputs.py',
    # 性能ゲートの入力と固定した旧版（人が「消さない」と決めたもの）
    'out/wt-head/skill/scripts/report.mjs',
    'out/perf-inputs/elsa-50.txt', 'out/perf-inputs/v2-big.graph.json',
    'out/demo/graph.json', 'out/elsa/graph.json',
    # v1 比較の基準（人が「差し替えない」と決めたもの）と照合スクリプト
    'skill/scripts/tools/battery/baseline-v1', 'skill/scripts/tools/battery/v1diff.py',
    # バッテリーの道具（第 50 / 51 ラウンド双人レビューで追跡下へ）
    'skill/scripts/tools/battery/README.md', 'skill/scripts/tools/battery/_inputs.py',
    'skill/scripts/tools/battery/check-invariants46.py',
    'skill/scripts/tools/battery/self-consistency.py',
    'skill/scripts/tools/battery/check-dir-rule.py',
    'skill/scripts/tools/battery/count-none.py',
    'skill/scripts/tools/battery/allperm.py', 'skill/scripts/tools/battery/allperm-corr.py',
    'skill/scripts/tools/battery/allperm-full.py', 'skill/scripts/tools/battery/cmp-head-proto.py',
    'skill/scripts/tools/battery/min-0.json', 'skill/scripts/tools/battery/min-2.json',
    'skill/scripts/tools/battery/find-splits.py', 'skill/scripts/tools/battery/via-cycle.py',
    'skill/scripts/tools/battery/r43-permute.py',
    'skill/scripts/tools/battery/r42-calls-0.json', 'skill/scripts/tools/battery/r42-calls-1.json',
    'skill/scripts/tools/battery/same-output.py', 'skill/scripts/tools/battery/r43-before.mjs',
    'skill/scripts/tools/battery/edge-order.py',
    # 第 52 ラウンド agy P2: ビルドと検証が読む本体とテンプレート、注釈の見本
    'skill/scripts/scan.mjs', 'skill/scripts/scan-terraform.mjs', 'skill/scripts/render.mjs',
    'skill/viewer/template.html',
    'skill/examples/annotations.orders-api.json', 'skill/examples/annotations.storage.json',
    # 解析機の実体（再生成とスイートが読む。`dotnet clean` の日で黙って落ちないように）
    'skill/analyzer/bin/Release/net9.0/cgd',
    'skill/scripts/tools/battery/input-fingerprints.json',
    'skill/scripts/tools/battery/known-v1-diffs.json',
    'skill/scripts/tools/battery/required-checks.json',
    'skill/scripts/tools/battery/emit-required.py',
    # `baseline-v1` が記録する入力グラフの実体（掃除で消える場所に有った唯一のコピー）
    'skill/scripts/tools/battery/graphs/ri.graph.json',
    'skill/scripts/tools/battery/graphs/ri0.graph.json',
    'skill/scripts/tools/battery/graphs/real.graph.json',
]

FILES = FILES + list(FIXTURES)
missing = [p for p in FILES if not (REPO / p).exists()]
# 0 バイトの固定入力は「在るが空」。性能ゲートの入力 `out/perf-inputs/elsa-50.txt` が空に
# なった日は測る物が無いので、在るかだけでなく中身も見る（第 53 ラウンド agy の指摘）
empty = [p for p in FILES if (REPO / p).is_file() and (REPO / p).stat().st_size == 0]

# 18 条件が記録している入力グラフ（作者環境の一時出力先）が実在するか。
# 掃除や別クローンで壊れたら、ここで終了 1 にする（第 51 ラウンド agy P2）
base = REPO / 'skill' / 'scripts' / 'tools' / 'battery' / 'baseline-v1'
# 件数を先に要求する（17 件でも「揃っている」と言っていた。第 52 ラウンド Codex P2）
reps = IN.report_paths(base, expect=18, what='v1 基準の条件（baseline-v1）')
for p in reps:
    # 0 バイト・壊れた JSON は `json.loads` が ValueError を投げて、下の「無い・空の一覧と
    # 作り直し方」へ届かず Traceback で落ちた（第 54 ラウンド agy 指摘 3）。読めない物も
    # 一覧へまとめて、測る前に終わらせる
    try:
        got = IN.graph_path(json.loads(p.read_text())['summary']['graph'])
        if not got.exists():
            missing.append(f'{p.name} の記録グラフ → {got}（解決先が無い）')
    except SystemExit as e:
        missing.append(f'{p.name} の記録グラフ: {e}')
    except (OSError, ValueError, KeyError, TypeError) as e:
        missing.append(f'{p.name} が読めない（{type(e).__name__}: {str(e)[:60]}。'
                       f'追跡下の記録なので `git checkout -- {p.relative_to(REPO)}`）')

# 検査の道具が足す実グラフ（一覧は `_inputs.extra_graphs()` が正本）
for g in IN.extra_graphs(REPO):
    if not g.exists():
        missing.append(f'{g.relative_to(REPO)}（_inputs.extra_graphs が足す検査のグラフ）')

# 道具のソースに掃除対象の一時パスが残っていないか。保存済み条件（`baseline-v1`）の中の
# 記録パスは歴史の記録なので対象外。`_inputs.py` の対応表も移設の実体へ橋渡しするための記述
STALE = re.compile(r"out[/\\]tmp-r\d+(?:[-A-Za-z0-9_]*)?(?:[/\\][^\s)`,、'\"]*)?")
STALE_JOIN = re.compile(r"['\"]out['\"]\s*/\s*['\"]tmp-r\d+")
# 走査から除く 2 本: `_inputs.py` は掃除対象の記録を移設実体へ橋渡しする対応表そのもの、
# `r43-before.mjs` は第 43 ラウンドの比較に使う固定コピーで、内部のコメントは当時の作業記録
# （書き換えると「前版と同一」の比較対象が崩れる。実行結果には出ない）
SKIP_SCAN = {'_inputs.py', 'r43-before.mjs'}
stale = []
tools = REPO / 'skill' / 'scripts' / 'tools'
for p in sorted(tools.rglob('*')):
    if not p.is_file() or p.suffix not in ('.py', '.sh', '.mjs'):
        continue
    if p.name in SKIP_SCAN:
        continue
    for i, line in enumerate(p.read_text(encoding='utf-8', errors='ignore').split('\n'), 1):
        for m in list(STALE.finditer(line)) + list(STALE_JOIN.finditer(line)):
            stale.append(f'{p.relative_to(REPO)}:{i}: {m.group(0)}')

if missing or empty:
    # 2 行目に `f` が無く「{len(empty)}」がそのまま印字された（第 54 ラウンド agy 指摘 3）
    print(f'バッテリーの入力が {len(missing)} 件無い（無い状態で走ると、黙って前版を測るか、'
          f'黙って条件が減る）。空（0 バイト）{len(empty)} 件:', file=sys.stderr)
    for p in missing:
        print(f'  - 無い: {p}', file=sys.stderr)
    for p in empty:
        print(f'  - 空: {p}', file=sys.stderr)
    print('out/tmp-* はディスク掃除の対象。追跡下のものは git checkout -- <パス>、'
          '作り直せるものは README.md の手順（build.mjs / make-v2-graph.py / make-changed-list.py）で'
          '再生成して使う。'
          '性能ゲートの固定旧版 out/wt-head/ が無いときは '
          '`git worktree add out/wt-head perf-baseline`（人が「消さない」と決めた比較対象。'
          '作らないまま測ると旧版の標本が消えてゲートが落ちる）', file=sys.stderr)
    raise SystemExit(1)
if stale:
    print(f'バッテリーの道具 {len(stale)} 箇所に掃除対象の一時パスが有る'
          '（消えた日に黙って件数が減る。実体は skill/scripts/tools/battery/graphs/ へ移す）:',
          file=sys.stderr)
    for s in stale:
        print(f'  - {s}', file=sys.stderr)
    raise SystemExit(1)
# out/ の固定入力が「別のもの」に差し替わっていないか（構造指紋）。第 52 ラウンド Astra 裁定 3。
# 第 53 ラウンド agy P2: 指紋検査は `require` で落ちる所以前にやると、上の「無い物の一覧」と
# `out/wt-head` の作り直し案内へ届かないので、**missing と stale を出したあと**にやる
EMIT = '--emit' in sys.argv
if EMIT:
    out = IN.resolve_cli_path(sys.argv[sys.argv.index('--emit') + 1], default=None)
    spec = json.loads((IN.HERE / 'input-fingerprints.json').read_text(encoding='utf-8'))
    for rel in spec['inputs']:
        d = IN.fingerprint(IN.require(REPO / rel, f'指紋を書き出す入力（{rel}）'))
        spec['inputs'][rel].update({'nodes': d['nodes'], 'edges': d['edges'],
                                    'ids': d['ids'], 'rels': d['rels']})
        spec['inputs'][rel].pop('freshAtHead', None)
    # 中身の指紋（第 55 ラウンド Astra 裁定 問 1）。一覧の一掃を書き直すので、
    # 入力が減った日に古い登録が残らない
    contents = {}
    for rel, mode, what in IN.content_scope(REPO):
        sha_mode, sha, nbytes = IN.content_fingerprint(REPO / rel, mode)
        contents[rel] = {'mode': sha_mode, 'sha': sha, 'bytes': nbytes, 'what': what}
    spec[IN.CONTENTS] = contents
    spec['note'] = ('バッテリーが入力として読むファイルの指紋台帳。`inputs` は out/ 固定入力の'
                    '構造指紋（ノード id と縁 `source|kind|target` の集合）で、第 52 ラウンド '
                    'Astra 裁定 3。`' + IN.CONTENTS + '` は**中身その物**の SHA-256（第 54 ラウンド'
                    '双人レビュー Codex 指摘 1: 構造指紋だけでは fixture の edges を空にしたり、'
                    '起点でないノードを rename したりしても変わらなかった）。JSON はキー順だけを'
                    '正規化して配列順・重複・全フィールドを保ち、実行ごとに違うトップレベルの'
                    ' `generatedAt` / `rootPath` だけ除く。前の版の report.mjs と v1 の記録は'
                    'バイト列。台帳の更新は人が作り直しが妥当と認めたあとに '
                    '`python3 skill/scripts/tools/check-battery-inputs.py --emit '
                    'skill/scripts/tools/battery/input-fingerprints.json` で行う')
    out.write_text(json.dumps(spec, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')
    print(f'今の指紋を {out} に書き出した（構造 {len(spec["inputs"])} 件 / '
          f'中身 {len(contents)} 件。作り直しを人が認めたあとの作成手順。'
          '日常の実行では --emit を付けない）')
    raise SystemExit(0)

# 二つの指紋検査は**まとめて**落とす。片方で `raise SystemExit` すると、もう片方の
# 食い違いが出ている日にそれを見せられない（第 54 ラウンド双人レビューの点検で確かめた）
bad_fp = IN.check_fingerprints(REPO)
bad_ct = IN.require_fingerprints(REPO)
if bad_fp or bad_ct:
    if bad_fp:
        print(f'out/ の固定入力 {len(bad_fp)} 件の構造指紋が基準と違う（入力が別のものに'
              '差し替わった。作り直してよいは人の判断。`--emit <ファイル>` は人が作り直しを'
              '認めたあとの作成手順）:', file=sys.stderr)
        for m in bad_fp:
            print(f'  - {m}', file=sys.stderr)
    if bad_ct:
        print(f'入力の中身の指紋 {len(bad_ct)} 件が基準と違う／揃っていない（差し替え・登録漏れは'
              '人の判断。自動では直さない）:', file=sys.stderr)
        for m in bad_ct:
            print(f'  - {m}', file=sys.stderr)
    raise SystemExit(1)

print(f'バッテリーの入力 {len(FILES)} 件（fixture {len(FIXTURES)} 本ふくむ）+ '
      f'記録グラフ {len(reps)} 件 + 検査のグラフ {len(IN.extra_graphs(REPO))} 件が揃っている'
      f'（道具のソースに一時パスの残り 0 件 / out/ 固定入力の構造指紋・中身の指紋 '
      f'{len(IN.content_scope(REPO))} 件の差し替えなし）')
