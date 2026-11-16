# 回帰バッテリーの道具と固定入力

`report.mjs` の出力契約が変わっていないかを測る道具と、それが入力にする固定データ。
**実行手順と順序は `out/loop/protocol.md` §4-3**（最初に必ず
`python3 skill/scripts/tools/check-battery-inputs.py` を走らせる）。

第 50 ラウンド双人レビュー（agy P2）で `out/tmp-*` からここへ移した。`out/tmp-*` はディスク
掃除の対象で、そこに唯一のコピーを置くのが過去 2 回の事故（第 48 ラウンドの全 250 回 ENOENT
なのに「適合」、第 49 ラウンドの入力表が実在しないファイルを指していた）の元凶。

## 入力の置き場所と終了コード（このフォルダの約束）

第 51 ラウンド双人レビュー（Codex・agy、両名 P2）で、検査器が**入力の欠落と子プロセスの失敗を
成功としていた**のが両名から出た（存在しない `report.mjs` を渡すと `allperm.py` は
「24 通り / 表 1 通り」、`find-splits.py` は「割れた例 0」、`same-output.py` は「不一致 0 件」と
答えて終了 0）。ここで扱うのは 3 つ。

- `_inputs.py` が共通の土台。`repo_root()`（`skill/scripts/report.mjs` を含む祖先を根にする）、
  `require()`（入力が無いなら**測る前に**終了 1）、`report_paths()`（レポートディレクトリが
  無い・空・期待件数と違うなら終了 1）、`require_script()` / `run_json()`（対象の `report.mjs`
  が無い、子が非 0 で終わったら終了 1）、`extra_graphs()`（不変条件・親子整合が足す実グラフの
  **正本の一覧**。`check-battery-inputs.py` も同じ一覧を読む）
- `baseline-v1/` の 18 条件は `summary.graph` に作者環境の一時出力先を記録している。実体は
  `graphs/` に移し、`graph_path()` が対応表 `RELOCATED` でたどる。記録そのものは歴史なので
  書き換えない（基準データは人が「差し替えない」と決まっている）
- 検査器は**終了コードで合否を返す**（`allperm.py`・`cmp-head-proto.py`・`edge-order.py` は
  割れた／差分がある／不一致があれば終了 1）。件数だけ見て人が判断する道具にしない
- `graph_path()` は**対応表を先に引く**（第 52 ラウンド Codex・agy P2）。作者環境に残骸が有る日も、
  別クローンで作者の絶対パスが残り記録も読む。ルート前の付かない相対パスでたどるので `/tmp` と
  `/private/tmp` の違いで落ちない。解決できない日は**作り直し手順付きで終了 1**（素通ししない）
- `input-fingerprints.json` は入力の指紋台帳で、**二種類の指紋**を持つ。
  - `inputs` … `out/` の固定入力 3 本の**構造指紋**（ノード id と縁 `source|kind|target` の
    sha256。`generatedAt` と `rootPath` は機械ごとに違うのでバイトは使わない）。出所（elsa-core
    commit `b74bc3c7…`）と作り直しコマンドもここに置く。**3 本ともコマンドを作り直して指紋が
    戻ることを実測**した（第 53 ラウンド。前に書いていた手順は `--exclude` と `--root` が違って
    別物になっていた。手順を書き直したら走らせて確かめる）
  - `contents` … **52 件の入力その物**の SHA-256（fixture 19 本・検査のグラフ・順列入力・
    `baseline-v1/` 18 本・`out/` 固定入力・注釈・変更一覧のテキスト）。構造指紋だけでは
    「fixture の `edges` を全部空にした日」「起点でないノードを 1 つ rename した日」
    「`parent` / `kind` / `provenance` を壊した日」に**指紋が変わらなかった**（第 54 ラウンド
    双人レビュー Codex 指摘 1 の実測）。JSON はキー順だけ正規化して配列順・重複・全フィールドを
    見る（縁の並び順その物が検査の対象なので集合にしない）。`r43-before.mjs` と `baseline-v1/` は
    **バイト列**で固定する（人が方針を変えないと更新しない）。台帳の更新は
    `python3 skill/scripts/tools/check-battery-inputs.py --emit skill/scripts/tools/battery/input-fingerprints.json`
    を人が作り直しを認めたあとに走らせる（通常の検証では付けない）
- `known-v1-diffs.json` は v1 基準との**既知差分 74 件の内容**（行 id・欄・向き・tier・段数・
  根拠の縁の種類と summary キーの、変更前と変更後の値）。`v1diff.py --verify-known` がこれと
  完全一致のときだけ終了 0（Astra 裁定。件数だけ的一致は同件数の入れ替わりを通すので使わない）。
  `--emit-known` は人が作り直しを認めたあとの作成手順で、実行結果から自動更新しない
- `required-checks.json` は回帰検査が使う**要求一覧と期待値の正本**で、3 つの内訳を持つ
  （別々の JSON に増やさない）。
  - `fixtures`（19 本）… glob の実体と**双方向**で一致必須。有るのに一覧に無い fixture は
    黙って走らない
  - `conditions`（219 件）… 起動条件の**正準形**。合否は `case` / `graph` / `kind` / `args` の
    中身の比較で決める。`id` は中身から再計算できる導物で、**id の集合だけ**を見た比較は
    「要求一覧の graph / kind / args を書き換えて id を据え置く」日を通した（第 54 ラウンド
    Codex 指摘 2）。`case`（レポート名、fixture 発は null）が有るのは audit 条件の
    `elsa-1` ↔ `elsa-folder`、`elsa-50` ↔ `elsa-limit` が**グラフ・kind・args まで同じ**で、
    起動内容を区別する唯一の材料がレポート名だから。「219 件＝219 とおりの起動内容」では無い
    （第 55 ラウンド Astra 裁定が指摘した私の前提の誤り）
  - `expectations` … 実際に測った件数（次節）。`_inputs.launch_conditions()` は一覧の形を
    検査し（重複・id の再計算・形の壊れた args）、条件が要求に無い／要求にあるのに走らない日を
    **測る前に**終了 1 にする。条件の組み方は `_inputs.condition_args()` に一本化した
  - 作り直しは `python3 emit-required.py <その JSON> --measured <測った件数の JSON>` で人が行う
    （`--verify-known` と同じ約束。通常の検証から正本は更新しない）
- パスの約束（第 55 ラウンド Astra 裁定 問 5 = 案 1）。**既定の置き場所はリポジトリ根基準**、
  **明示した引数と環境変数は実行時の cwd 基準**。`_inputs.resolve_cli_path()` が一箇所で決めるので
  `battery/` から `../../out/...` のように書ける（`out/` はリポジトリの直下なので
  `battery/` からは `../../../../out/`）。存在しない相対パスを根から補って黙って通すことはしない
- `require()` は**相対パスをリポジトリの根から引く**（手順書の書き方はリポジトリ相対なので、
  道具をサブディレクトリから実行しても同じ物を見る。第 53 ラウンド agy: `v1diff.py` を
  `battery/` から走れると基準ディレクトリを見失っていた）。`rel_of_recorded()` は今の
  リポジトリの根が前に付いていればそれを捨て、そうでなければ**最後**の `out` から取る
  （親ディレクトリが `out` という名前のリポジトリで最初の `out` から切ると別物になった。
  第 53 ラウンド Codex が `/tmp/out/clone` で実測）

## v1 の出力契約を突き合わせる

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `../regen-audit.py` | `python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs out/audit-current --force` | 18 件の JSON を今の版で作り直す |
| `v1diff.py` | `CGD_AUDIT_OUT=out/audit-current python3 skill/scripts/tools/battery/v1diff.py` | 「**レポート 18 件 / 差分 74 件**」（行 58 + 集計 16。人が差し替えないと決めた既知の定数なので**終了 1 が正常**。内訳は決 69 / 決 71） |
| `v1diff.py --verify-known` | `python3 skill/scripts/tools/battery/v1diff.py --verify-known skill/scripts/tools/battery/known-v1-diffs.json` | 「差分の内容が既知差分と完全一致」で**終了 0**（バッテリーの機械判定）。新規差分・消えた既知差分・同じ値への入れ替わり・不良（実行失敗 / 読みけない JSON / `unresolved` / 行 id 重複）はすべて終了 1 |
| `check-dir-rule.py --profile current`（`--profile` は必須。無しモードは合否を出さないので第 56 ラウンドで無くした） | `python3 skill/scripts/tools/battery/check-dir-rule.py --profile current out/audit-current` | 「一致 441 / 不一致 0 / 並行縁で不定 0 / 経路を読めない 0 / 向き の値域外 0」＋**期待値と一致**（内訳とレポート別の比較件数まで照合。違えば終了 1） |
| `check-dir-rule.py --profile v1` | `python3 skill/scripts/tools/battery/check-dir-rule.py --profile v1` | 「一致 386 / 不一致 55」で、55 件は `known-v1-diffs.json` の行差分 58 件のうち**向きが変わった 55 件**と中身まで一致（`IN.expected_direction_diffs()` が導出。件数だけの一致は使わない） |
| `count-none.py` | `python3 skill/scripts/tools/battery/count-none.py out/audit-current` | 「none の行 28 件（同じ API 17 / 定義上の関連 9 / 兄弟 2 / うち primary 2）・期待値（`expectations.directionless`）と一致」。裁定のハードコードは第 55 ラウンドで追跡下の一覧へ移した。行数は `summary.rows` の自己申告でなく**欄の実測**で数える |
| `cmp-head-proto.py` | `git show HEAD:skill/scripts/report.mjs > /tmp/head.mjs && python3 skill/scripts/tools/battery/cmp-head-proto.py /tmp/head.mjs skill/scripts/report.mjs` | 「動いた項目 {}」。JSON に触らない変更なら 差分のある条件 0（差分があれば終了 1） |
| `same-output.py` | `python3 skill/scripts/tools/battery/same-output.py /tmp/head.mjs skill/scripts/report.mjs` | 「18 条件中 不一致 0 件」。今日 HEAD と比べるのが意味のある使い方（`r43-before.mjs` と比べると不一致 18 件が出てよい） |

`baseline-v1/` が v1 基準の 18 レポート（人が「差し替えない」と決めたもの）。`CGD_AUDIT_BASE`
で別の基準ディレクトリに差し替えられるが、差し替えないことが決まっている

## 表示の不変条件と親子の整合を見る

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `check-invariants46.py` | `python3 skill/scripts/tools/battery/check-invariants46.py skill/scripts/report.mjs` | 「検査した起動条件 219 件 / 行 5033 件」「**違反合計 0 件**」 |
| `emit-required.py` | `python3 skill/scripts/tools/battery/emit-required.py skill/scripts/tools/battery/required-checks.json --measured <測った JSON>` | 「fixture 19 本 / 起動条件 219 件 / 期待値 4 内訳を書き出した」。`--measured` が無いと**作れない**（前の期待値を引き継ぐと「検査範囲が縮んだ日」を通すため）。測り方はこの道具の先頭に 5 本書いてある |
| `self-consistency.py` | `python3 skill/scripts/tools/battery/self-consistency.py skill/scripts/report.mjs` | 「不一致 0 件」（件数の内訳は版で動くので**違反 0** と終了 0 を見る） |

起動条件は `skill/tests/fixtures/ImpactFacts/*.graph.json`（追跡下）+ `_inputs.extra_graphs()`
（`out/demo/graph.json`・`out/elsa/graph.json`・`out/perf-inputs/v2-big.graph.json`）+
`baseline-v1/` の 18 条件。掃除対象の `out/tmp-*` は読まない。一覧その物は
`required-checks.json`（追跡下）にあり、両検査は**測る前に**集合一致を確かめる
（第 53 ラウンドまであった「200 件未満なら走り終えたあとに止める」は、fixture 2 本消失を
通したので廃止。両名 P2）

## 測った件数の期待値と、検査の検査（第 55 ラウンド Astra 裁定 問 2・問 4・問 6）

入力指紋は「入力が差し替わった日」を止めるが、**入力はそのまま・測る範囲だけが縮んだ日**を
止めない。fixture の `edges` を全部空にした日は要求一覧との集合比較も通り、不変条件検査は
219 条件を走らせても検査する行だけが減っていた（第 54 ラウンド Codex 指摘 1）。そこで
**実際に走査した件数**を条件別に測り、`expectations` と突き合わせて違えば**測ったあと**に
終了 1 にする（件数の一致は内容一致の代用ではないので、不変条件検査と
`v1diff.py --verify-known` はそのまま残す）。

| 内訳 | 測る道具 | 今の期待値 |
| --- | --- | --- |
| `expectations.invariantRows` | `check-invariants46.py` | 219 条件 / 5,033 行（**条件別**で持つ。合計だけだと別条件の増減が相殺する） |
| `expectations.parentChild` | `self-consistency.py` | 472 件の親子突き合わせ（条件別） |
| `expectations.directionless` | `count-none.py` | 441 行 / none 28（同じ API 17・定義上の関連 9・兄弟 2・primary 2） |
| `expectations.dirRule.current` | `check-dir-rule.py --profile current` | 441 一致 / 0 不一致 / 0 不定 / 0 経路を読めない / 0 値域外 + レポート別 |
| `expectations.dirRule.v1` | `check-dir-rule.py --profile v1` | 386 一致 / 55 不一致 + レポート別（55 件は既知差分から導出） |

**要求一覧を作り直すときの測り順**（`emit-required.py --measured` の材料。`out/audit-current` は
今の `report.mjs` での再生成）:

```
M=$(mktemp -d)/measured.json
python3 skill/scripts/tools/battery/check-invariants46.py --emit-measured $M
python3 skill/scripts/tools/battery/self-consistency.py   --emit-measured $M
python3 skill/scripts/tools/battery/count-none.py         --emit-measured $M out/audit-current
python3 skill/scripts/tools/battery/check-dir-rule.py --profile current --emit-measured $M out/audit-current
python3 skill/scripts/tools/battery/check-dir-rule.py --profile v1      --emit-measured $M
python3 skill/scripts/tools/battery/emit-required.py skill/scripts/tools/battery/required-checks.json --measured $M
```

「0 行なら違反」を一律にはしない（Astra 裁定 問 4）。`demo-readme.json`・`elsa-1.json`・
`elsa-folder.json`・`real-tf.json` は**起動条件に対して正当に 0 行**で、`validate_report()` は
形だけを見る。止めるのは**比較する行が 0 件なのに合否を出そうとする日**
（`require_comparison_rows()`）と、**1 本のレポートで行を消して比較件数を減らす日**
（`dirRule.*.byReport`）。

```
python3 skill/scripts/tools/battery/test-contract.py
```

`test-contract.py` は**検査の検査**（負控制は**見張り番を消した再実行つき**。件数と網羅の
内訳は下の「見張り番を名前 1 個ずつ消せる」節に書く。書くときは必ず**いつの実測かを添える**
（「第 70 ラウンド実測」の様に日付を付ける。日付なしで今の値の様に写すと、次のラウンドで古い値が
そのまま真実に見える）。0 行の `report.mjs`、要求一覧の
`graph` / `args` を書き換えて id を据え置く、条件の重複、fixture を 1 本増やす、指紋台帳の登録を
1 件消す、`fixture` の縁を全部空にする、期待値を 1 件ずらす・2 件入れ替える、JSON を書かない実行、
出力先が既にある実行、`battery/` から存在しない相対パス、**縁を全部抜いた実グラフでの
`edge-order.py`**（4 本の起動すべてが 0 群）、**縁が 1 本だけのグラフでの `allperm.py`**、
`allperm.py` に期待縁順の通り数（第 3 引数）違いを渡す、行から突き合わせる欄（`switches`）が
消える `report.mjs`、`out-exists` だけを測るために**前回の中身を正当なレポートにした**
出力先既存の実行、**向き別の合計は同じまま `byReport` の按分だけ**入れ替えた期待値一覧、
**バイト数を変えないノード id の書き換え**、`battery/` から渡して**根からなら実在する**
相対パス（根へ倒れたら通る）を**実際に起こして**、検出されなければ終了 1。
第 55 ラウンド Codex P2 の「存在しない道具を走らせて python の終了 2 を検出と数えた」道を
消すため、道具は `battery/` と `tools/` の両方から探して**見つからなければ制御の壊れ方**として
失敗させ、入力点検が実際に起動して終了 0 であることを正控制にした（制御自身の壊れ方を
`except (AssertionError, ValueError, KeyError)` で黙ることもやめた）。追跡下のファイルは
読み直した bytes を戻するので、走ったあとも `git status` は空のまま（残っていたらそれ自体を
失敗にする。`skill` 全体を見て未追跡の残骸も拾う）。
**見張り番の件数を増やすだけでは検査は強くならない**という第 54 ラウンドの教訓を、動く形に
するための道具

## 見張り番を名前 1 個ずつ消せる（第 56 ラウンド agy P1）

「負控制が落ちた」は「その見張り番が働いた」を意味しない。agy は第 55 ラウンドでクローンを作り、
個々の見張り番を無効化して**制御がまだ落ちる**ことを実測した（3 件は別の一の見張り番が先に
落ちただけの空振り）。なので `_inputs.py` の見張り番はすべて**名前**を持っていて、1 個ずつ
消せる（`test-contract.py` が内部で使うだけ。通常の実行では入れない）:

```
CGD_GUARD_OFF=fp-sha python3 skill/scripts/tools/check-battery-inputs.py   # 実行系から
```

中から消すのは `with IN.guard_off('fp-sha'):` の**区間**（抜けたら元へ戻る。
区間を作れるのは台帳 `guardCallers` に登録した制御ファイルだけで、`with` の管理以外の
位置で呼べば穴になる。Astra 第 68 ラウンド 問 1 の B案。第 67 ラウンドまで置いていた
`IN.set_guard_off('fp-sha')` は呼び出し後も無効化が残ったので置いた）。**通常の検査は全部生きた状態でだけ走る**（`CGD_GUARD_OFF` を付けた実行は負控制の為の
実行で、`test-contract.py` は開始時に無効化が残っていればそこで終了する）。
`test-contract.py` の `negative(..., guard=..., message=...)` は各制御を **2 度**走らせる —
素の実行で `message`（その見張り番の案内）が出る → `guard` を消した実行で `message` が
**出ない**（既定では**通る**ことも要求）— ので、名前を間違えたり別の一の見で通したりした
制御はその場で失敗する。見張り番を消すと**対象の案内は消えるが、実行は別の診断で拒否される**
制御は `clean=False` を附け、`fallback` に **OFF 後も残る別の診断の文面**を宣言させる
（宣言が無い・想定と違う所で落ちた、はどちらも失敗。第 56 ラウンド agy P2-3）。第 59 ラウンド
Astra 問 2 で「実行系の制御（JSON を書かない、JSON が壊れている）だけ」という但し書きを外した
― 重複検査のように複数の見張り番が同じ細工を拾う場合もまったく同じ形で、但し書きがそれを
説明できなかった。対象を消したのに**対象の案内が残る**実行は `clean=False` でも失敗にする

<!-- 見張り番の名前一覧:この区画の表だけを見張り番の名前として読む -->
| 名前 | 見ている物 | それを測る個別負控制（**見張り番を消した再実行で実在を確かめた物だけ**書く） |
| --- | --- | --- |
| `fp-structural` / `fp-unregistered` / `fp-ledger-extra` / `fp-sha` / `fp-bytes` / `fp-mode` / `fp-type` | 入力点検の 7 見（構造指紋・登録漏れ・台帳の余剰・中身の sha・バイト数・読み方・`any` 区分） | 台帳の登録を 1 件消す（`fp-unregistered`）/ fixture の縁を全部空にする（`fp-sha`・`fp-bytes`）/ **ノード id を同じ長さで書き換える**（`fp-sha`。バイト数は不変）/ **台帳に入力の一覧に無い物を 1 件足す**（`fp-ledger-extra`）/ **台帳の読み方だけを 1 件書き換える**（`fp-mode`）/ **読み方に json でも bytes でもない値を置く**（`fp-type`。消した実行は `fp-mode` が別の診断で拾う）/ **固定入力のノード数を台帳だけ 1 ずらす**（`fp-structural`）/ **台帳のバイト数だけを 1 件書き換える**（`fp-bytes`。sha と読み方を据え置くので `fp-sha` が手前に落ちない。第 58 ラウンド agy P2-1: `and False:` に完全無力化しても検査の検査が終了 0 だった。名指しが `guard=(fp-sha, fp-bytes)` の組だけだった） |
| `out-exists` / `child-fail` / `json-missing` / `json-empty` / `json-parse` / `report-shape` / `edge-child-fail` / `edge-json-parse` / `edge-out-shape` | 子を実行して JSON を読む 6 段階 と `edge-order.py` 自身の子実行の 3 段階 | 出力先が既にある実行（`out-exists`）/ **正しい JSON を書いて非 0 で終わる実行**（`child-fail`。第 57 ラウンド agy P2-2: ここに「終了 0 で JSON を書かない」を載せていたが、あれは `json-missing` の制御で消すと `json-missing` が落ちる空振りだった）/ 終了 0 で JSON を書かない（`json-missing`）/ **終了 0 で空のファイルを書く**（`json-empty`。消した実行は `json-parse` が止める）/ 壊れた JSON（`json-parse` と `report-shape` を**まとめて**消す。第 56 ラウンド agy P2-3: `json-parse` だけ消すと `doc = {}` が後の形検査で落ちて、別の一で止まっていた）/ **終了 0 で JSON でない文字列を書く実行**（`json-parse`。`expect_report=False` で後段の `report-shape` を退けて単独に測る）/ 欄の無い JSON（`report-shape`）。`edge-order.py` の子実行は**別名の 3 本**（`edge-child-fail` / `edge-json-parse` / `edge-out-shape`。第 60 ラウンドの分割まで共有の名前を借りていたので、`edge-order.py` の 1 箇所だけを消す無力化を単独名指しが検出できていなかった。Astra 裁定 問 4「追加した判定は**当該呼び出し経路**で確かめよ」）|
| `cov-shape` / `cov-keys` / `coverage` | 期待値一覧の形（型・非負整数・必須欄・合計は条件別の導出。`dirRule` は向き別の合計と `byReport` の合計が同じ行の数え直し。向き別と向き none の数えは**負の値も `true` も欄の欠落も弾く**）、**どのレポート・条件を数えるか**のキー集合、走った件数の条件別比較 | 合計をずらす / 内訳を空にする / 1 件ずらす / **件数の違う 2 件**を入れ替える / 1 条件測らない / **`agree` を 1 増やして `bad` を 1 引く**（合計は同じまま負の値。第 56 ラウンド agy P2-2）/ 向き none の数えに `true`・負の値・`none` の欠落（第 57 ラウンド agy P2-2 の横展開漏れ）/ **`byCondition` の id を 1 件だけ要求一覧に無い値へ差し替える**、**`byReport` のキーを 1 本だけ実在しない名前に差し替える**（`cov-keys`。件数も合計もそのままなので形の検査は素通りする。第 57 ラウンド agy P2-4 の `{"": 441}` 系）|
| `cond-keys` / `cond-graph` / `cond-case` / `cond-args` / `cond-kind-args` / `canonical-id` / `dup-condition` / `dup-id` / `dup-fixture` / `fixture-shape` / `fixture-set` / `condition-set` / `dup-built` | 要求一覧の形（`graph` の型・空・`#`・絶対パス・`..` を含む）・id の再計算・正準形と id の重複・**fixtures の重複**・**fixtures の要素の型**・fixture 集合・起動条件の集合・**組み上げた条件の重複** | `graph` / `args` を書き換えて id を据え置く / 重複 / `case` を消す / 値域外の kind / **`graph` を絶対パスにする**（id も同じ中身から作り直す。`cov-keys` も一緒に消して単独に測る）/ **`fixtures` に文字列でない値を置く**（`fixture-shape`。消した実行は `fixture-set` が別の診断で拾う）/ fixture を 1 本増やす / `fixtures` に同じパスを 2 度書く / **要求一覧を壊して入力点検を走らせる**（`dup-fixture`。測定道具と同じ入口を通るようになった証拠。第 57 ラウンド agy P2-3）/ 条件を 1 件消す / **builder へ重複した fixture 列を渡す**（`dup-built`。要求一覧は壊さない。第 57 ラウンド agy P2-2 で名前だけだった）/ **`graph` に `#` を混ぜて id と条件別の期待値のキーまで揃える**（`cond-graph`。素で `#` を足すと id が割れて `canonical-id` が手前に落ちる。第 59 ラウンド Astra 問 1 の実測レシピ）/ **`fixtures` から 1 本消す**（`fixture-set`。条件はそのままなので重複検査は素通り）/ **要求一覧を壊して起動条件を組み立てる**（`fixture-shape` を `launch_conditions()` の入口で測る。第 58 ラウンド agy P2-2: `check-invariants46.py` / `self-consistency.py` が `KeyError` の traceback だった）/ **同じ起動内容を 2 件並べる制御を目の違う 2 本に割った**（`dup-condition` と `dup-id`。相手の案内を `fallback` に宣言。第 58 ラウンド agy P2-1 でこの 2 名前は組の名指しだけだった）/**条件に無い欄を 1 つ足す**（`cond-keys`。id は 4 欄から作る細工なので `canonical-id` は割れない）/**`case` に文字列以外（1）を置く**（`cond-case`。Astra 第 60 ラウンド 問 2 が A 案の弱点として示した入力）/**`args` の 1 つを数値にする**（`cond-args`。id は欄を文字列化して作る細工なので消した実行はそのまま通る）/**`kind` を値域外へ変える**（`cond-kind-args`。id を同じ中身から作り直す）|
| `trial-count` / `rows-zero` / `proj-buckets` / `proj-fields` / `perm-edges` / `perm-declared` / `perm-count` / `perm-expected` / `perm-cap` / `perm-runs-min` | **入れ替え試行の本数**・0 行で合否を出さない・付き合わせる 6 欄と欄の名前・縁の本数・順列の通り数・**順列の上限と間引き後に実際に走った通り数** | **`r43-permute.py` の試行を 1 とおりにする**（`trial-count`。実測は「表 1 通り」で終了 0 だった。消した実行は `perm-cap` が別の診断で拾う）/ 0 行の `report.mjs` × 4 道具 / **`external.out` が無い JSON を `projection_rows` へ直接渡す**（`proj-buckets`。9 欄の形その物が崩れた JSON は道具の手前で `report-shape` が止まるので、内側のこの見張り番は関数へ直接渡して測る）/ 欄が消える（`proj-fields`）/ 縁が 1 本だけ / 期待縁順の通り数違い（`perm-declared`。走る前の食い違いを名指し、消した実行は `perm-expected` が「999 件に対して 720 件走った」で拾うので `fallback` 宣言）/ 縁 3 本の順列 6 通りに 5 件走った（`perm-count`）/ 宣言 7 件に 6 件走った（`perm-expected`。組み立てる側が壊れないと CLI では作れない形なので関数へ直接渡す）/ 順列上限に **1** と **0** を渡す（`perm-cap`。0 は割り算の前で止める。第 57 ラウンド agy P2-1 の `ZeroDivisionError`。消した実行は `perm-runs-min` が別の診断で拾う）/ 間引き後に 1 とおりしか走らない比較（`perm-runs-min`。CLI では `trial-count` と `perm-cap` が先に拾うので関数へ直接渡す）|
| `dir-rule-counters` / `dir-rule-report` / `dir-rule-v1` | 向き別の件数・**レポート別の按分**・v1 の既知差分との中身照合 | 18 本とも 0 行 / **`byReport` の按分だけ**入れ替えた一覧（向き別の合計は同じ）/ **`byReport` の実在する 2 本の件数を入れ替える**（キー集合も合計もそのまま。実在しない名前に集め替える形は第 60 ラウンドの入口の共通検査 `cov-keys` が先に落とすので、道具自身の比較を測れなくなった。Astra 第 60 ラウンド 問 1 の裁定。「キー集合その物」は `cov-keys` 側で引き続き測る）/ 18 本そろえて 1 本だけ行を消す / **既知差分の `id` を別ノードへ動かす**（不一致 55 件のまま中身だけずらす。`dir-rule-v1` を単独で測る。第 56 ラウンド Codex P2-1）/ **v1 の `agree` を 1 減らして `bad` を 1 増やす**（`dir-rule-counters`。合計は実測のまま。第 58 ラウンドまで `dir-rule-report` と組で、手前に遮われて単独に測れていなかった） |
| `edge-group-empty` / `none-expectations` / `none-counters` | `edge-order.py` の 4 起動すべて 0 群（`--json` の形は上の行の `edge-out-shape`）・`count-none.py` の期待値とサマリカウンタ | **実グラフの縁を全部抜いて 4 起動すべて 0 群**（`edge-group-empty`。`--json` の形でない出力は `edge-out-shape` として別名にした。同じ名前を 2 箇所で使っていたため 1 箇所だけの無力化が検出できなかった。第 60 ラウンド Astra 問 2）/ **`expectations.directionless.none` を 1 増やして `count-none.py`**（`none-expectations`）/ **1 本の `summary.rows` を 1 増やす**（`none-counters`）。第 57 ラウンド agy P2-2: 「実グラフの縁を全部抜く」を 3 名前ぶん載せていたが、走っていたのは `edge-order-groups` だけだった |
| `path-empty` / `path-count` / `path-cwd-only` | レポート 0 件・期待件数違い・明示した相対パスを cwd から解決する | **0 件のディレクトリを `report_paths` へ直接渡す**（`path-empty`）/ **1 本のディレクトリに 18 件を期待して渡す**（`path-count`）。第 57 ラウンド agy P2-2: 「1/18 のディレクトリ」を両方の制御として載せていたが、その実行は `path-count` が先に落ちていた（道具側から単独に作れないので関数へ直接渡す）/ `battery/` から `out/audit-current` を渡す（`path-cwd-only`） |
| `own-shape` / `own-names` / `own-tools` / `own-files` | 見張り番の対応表 `guard-owners.json` の形・名前集合・名前と所属道具の対応・走査対象のファイル集合（合計値が同数のまま名前を入れ替える細工を止める為の台帳。豁免は許す import と名前だけを書く） | 台帳から 1 名を消す（`own-names`）/ 1 名の所属道具を別へ動かす（`own-tools`）/ 走査対象から 1 ファイル消す（`own-files`）/ 豁免に走査対象外のファイルを登録する（`own-files`）/ `owners` の値を配列でなくす（`own-shape`） |
| `md-fence-form` | 検査が読む 2 つの文書（この README と `docs/decisions.md`）のコードフェンスが許可した形（行全体がバッククォート 3 個）でない。`~~~`・4 個以上・情報文字列・字下げ・引用・箇条書きの中はフェンスの中の偽の表を区画の外に見せていた（Astra 第 64 ラウンド 問 3 裁定 (b)） | 情報文字列を付けたフェンスの 3 行を形検査に渡す |
| `import-unregistered` | 走査対象のファイルが**許可一覧に無い import** をした（一覧は `test-contract.py` の `_ALLOWED_IMPORTS`。第 63 ラウンドまで「禁止する import を足す」方式で、`socket`・`code.InteractiveInterpreter`・`object.__subclasses__()` が穴 0 件で素通りした。Astra 第 64 ラウンド 問 1 裁定 (c) は許可する import を先に決める側へ切替） | `import socket` を足した 1 行を走査へ渡す（豁免なしで穴が出る） |
| `import-binds-guard` | 豁免した import が `guard` の名前を束縛する（`from builtins import bool as guard` + `guard('fake')` が豁免で通り、架空の名前が見張り番として数えた実測。Codex 第 63 ラウンド P2-4） | 豁免つきの `from builtins import bool as guard` を走査へ渡す |
| `exempt-loader-name` | 豁免台帳に `exec`・`compile`・`FunctionType`・`modules` の様な**動的機構の名前**を登録しようとする（豁免は未登録の import を通す物で禁止の解禁ではない。Astra 第 64 ラウンド 問 2 裁定 (i)） | 豁免の `imports` に `{'types': ['FunctionType']}` を登録する |
| `exempt-dup-entry` | 同じファイル・同じ import の豁免を二重に登録する（片方で許し片方で消す置き方が作れる。Astra 第 64 ラウンド 問 2 裁定 (iv)） | 同じファイルの豁免を 2 件に分裂させて照合する |
| `json-dup-key` | 対応表の JSON に同じオブジェクト内での重複した鍵が有る（`json.loads` は後勝ちで畳むので禁止名を並べて消す細工が通る。裁定 (iv)） | 同じ鍵を 2 度書いた JSON を `_dup_json_keys` へ渡す |
| `exempt-scan-parity` | 豁免を渡した走査と渡さない走査で**穴で落とす前の呼び出し候補**（名前・所属・ファイル・行）が違う（豁免が見張り番の集計を動かした。Astra 第 64 ラウンド 問 2 裁定 (iii)） | 豁免つきの走査で 1 名を消す細工を差し込んで照合する |
| `v1-derivation` | 既知差分から導いた 向き の差分が 55 件であること | **既知差分の 1 件を「向きが変わらない」形へ直す**（導出が 54 件になる。第 57 ラウンド agy P2-2: 「`dir-rule-v1` の制御が同時に落とす」と書いていたが、それは `v1-derivation` を測っていなかった）|
| `import-granted` / `import-star` / `guard-unbound` / `exempt-use-form` | 豁免台帳に登録していないモジュールの import（豁免は**完全修飾モジュール × 末端名**で効き、登録済みのサブモジュールは通らない）、`from <任意> import *`、`_inputs.py` 以外での裸の `guard(...)`、豁免由来の束縛を**登録した末端を直接呼ぶ連鎖の外**で読む（代入・既定値・辞書の鍵・条件式・内包・`match`・`getattr` 経由など。Astra 第 66 ラウンド 問 1・問 2 の裁定） | 各形を `_guard_scan` へ渡して穴として挙がり、その名前だけを消すと穴が消えることを 1 本ずつ確かめる |
| `md-marker-form` | 区画マーカーの行に他の文字が付いている、マーカーが 0 個か 2 個以上、開始と終了の順序が逆、マーカーや区画がコードフェンスの中（README の 2 区画と決めの表で共有。Astra 第 65 ラウンド 問 3 の裁定） | 語尾へ説明を足したマーカー行を README と `docs/decisions.md`にそれぞれ差し込む |
| `exempt-map-expand` / `exempt-loader-attrs` | 走査へ渡した豁免マップが検証済みの台帳から作り直した物と違う（欠落・余剰・宛先・許可内容）、台帳の登録禁止が走査側の禁止属性を避けている（Astra 第 65 ラウンド 問 4・問 1 の裁定） | 使わないキーを足したマップを渡す控制と、豁免を 1 件落とした台帳での照合を別名で置く |
| `box-shape` / `exempt-path-overlap` | 対応表の `boxNames`（見張り番の箱 `IN` の公開名と用途）が辞書でない・用途が `call`/`const` のどちらでもない・`guard` が載っている（`box-shape`）、豁免で同じ経路を中継と末端の両方に登録する併記（`exempt-path-overlap`。Astra 第 66 ラウンド 問 1・追記の裁定 (ア)） | `boxNames` を辞書以外へ組み替える台帳、`importlib.util` の登録の子経路をもう 1 段深く足す台帳をそれぞれの検査が見逃すか |
| `in-public-name` / `in-public-table` | 見張り番の箱 `IN` の公開名を用途付きの表と違う形で使う（表に無い名前、`call` の呼び出さない読み取り、`const` の呼び出しと**呼び出しへ至る連鎖の根**にする（`IN.GUARD_OFF.clear()`）。`in-public-name`）、表と実ツリーの使用が違う（使わない登録・無い名前・両方の形で使う名前。`in-public-table`。Astra 第 66 ラウンド 追記の裁定 (ア)） | 表に無い名前・用途違いの 3 形を `_guard_scan` へ渡す控制と、使わない名前を 1 個足した台帳を照合が見逃すか |
| `in-public-write` | 見張り番の箱 `IN` の公開名を**書き換え・削除**する（`IN.GUARD_OFF = frozenset()`・`del IN.CONST`・`IN.CONST \|=`・`IN.CONST.x = 1` の様な属性と添字の連鎖の受け手。用途が `call` でも `const` でも穴で、表の 6 マスの黒側。`local[IN.CONST] = 1` のように**別の物**の受け手の中で読むのは通り、`IN.CONST[...] = 1` は穴。Astra 第 67 ラウンド 問 2 の表） | 代入・複合代入・削除・属性への書き換えの 4 形を `_guard_scan` へ渡す（見張り番を消すと 4 形とも素通りすること、通る形の正控制と対で測る） |
| `import-relative` | `from .x import y` の様な**相対 import** を許可一覧・豁免・`_inputs` の特別扱いより先に穴にする（豁免も許可一覧も**完全修飾モジュール名**で持つので、所属パッケージが静的に決まらない名前とは照合できない。`level` を捨てて絶対名として照合すると `from .importlib.util import spec_from_file_location` が標準の `importlib.util` の豁免で穴 0 件だった。Codex 第 66 ラウンド P1-1 / Astra 第 67 ラウンド 問 1 の裁定 (ア)） | 許可一覧に有る綴りをそのまま相対で import した 1 行を走査へ渡す（見張り番を消すと許可一覧の `os` として通るので単独で名指せる） |
| `import-dynamic-module` | `exec` / `compile` / `types` / `builtins` の様な**動的機構のモジュールを根だけ import する**（登録末端を使うファイルでも `import importlib` は `importlib.exec` 経由で見張り番を殺せる。根だけの束縛は豁免でも通さず、案内から「豁免台帳へ登録すれば可」を撤回した。Astra 第 67 ラウンド 問 1） | 登録末端を使うファイルに `import importlib` を足した 1 行を走査へ渡す（末端までの経路の `import importlib.util` は通ることも同じ控制で見る） |
| `guard-caller-file` / `guard-caller-form` / `guard-callers-shape` / `guard-callers-scope` | 見張り番を消す区間（`IN.guard_off(...)` と `IN.guards_on()`）を**作れる場所と形**（呼べるのは台帳 `guardCallers` に登録した制御ファイルだけ。無登録のファイルの区間と、登録されているのに区間を作っていないファイルが `guard-caller-file`。`with` の管理以外の位置での呼び出しが `guard-caller-form`（区間を作らずに無効化だけ残す形）。台帳の `guardCallers` が空でない正準相対パスの列かどうか（重複・途中の `.` / `..`・`.py` でない綴りを弾く）を `guard-callers-shape`。登録したファイルが走査対象に実在することを `guard-callers-scope`（agy 第 68 ラウンド P1-1・Codex 第 68 ラウンド P2-1 の実測: 架空の登録は形の検査もファイル別の照合も通った。第 69 ラウンドで分けた）。Astra 第 68 ラウンド 問 1 の B案: 第 67 ラウンドまでの「無効化は環境変数に限定」を改め、区間を認める代わりに呼び出し元を台帳で絞った） | 区間の呼び出しを `_guard_scan` へ渡す 3 控制（無登録のファイル / 区間を作らない登録ファイル / `with` の管理ではない位置）と、`guardCallers` を空の列・重複・途中の `.` を交ぜた綴りにした台帳を `guard_ledger_shape_errors()` へ渡す控制と、実在しないファイルの登録を `_guard_caller_ghost_holes()` へ渡す控制 |
| `emit-candidate-valid` / `emit-diff` / `emit-target` / `emit-caller-approval` | 対応表の候補を出す道具 `emit-guard-owners.py` 自身の 4 検査。候補を出してよい形か（箱の公開名を書き換えに使う・1 名が 2 用途を持つ・候補の表を渡した走査に穴が残る、のいずれかを拒否する。`emit-candidate-valid`。Astra 第 67 ラウンド 問 3 の裁定 1 は候補の表での検証を認めたが、書き換えを許可用途へ塗り替える事は認めない）、今の台帳との差分を `boxNames` と `exemptions` まで**全て**表示するか（`emit-diff`。第 66 ラウンドは `owners` と `scannedFiles` しか比較せず「差分無し」と報告していた）、`--emit` が運用中の台帳その物への書き出しを拒否するか（`emit-target`。同じ裁定 4）、観測した区間の呼び出し元が承認済みの `guardCallers` に在るか（`emit-caller-approval`。Astra 第 69 ラウンド 問 3-2: 未承認の観測は表示した上で終了 1。観測を自動で許可へ載せない） | 3 種の拒否を `candidate_refusals()` へ渡す / 公開名の追加・削除・用途の変わり目と豁免の差し替えを `diff_lines()` へ渡す / 運用中の台帳を別表記で指した書き先を `target_errors()` へ渡す |
<!-- /見張り番の名前一覧 -->

**全 85 名に、その名前だけを無効化する負控制が有る。うち 72 名は無効化すると実行が成功し、
残る 13 名は対象の案内が消えたうえで宣言済みの別の診断で拒否される**（`clean=False` +
`fallback`）。複数名を同時に無効化する制御はこの網羅数に含めない。
**1 名前 = 呼び出し 1 箇所**も同じ正控制が数える（呼び出し回数を AST で数え、2 箇所以上の名前を
失敗にする）。同じ名前を複数箇所で使った第 59 ラウンドまでの形では、1 箇所だけを `and False:` に
しても他の箇所が生きているので単独名指しの控制がそのまま通り、網羅の実測が空振りになった
（第 59 ラウンド agy P2-3 の 2 の実測）。**判定が違うなら名前を分け、同じ判定ならスイッチの読みを
1 箇所へまとめる**（`none-counters` の 2 箇所を実測でまとめた）。

見張り番を**直接呼んでいるファイル**別の一覧（Astra 第 61 ラウンド 問 5 の機械検査 `readme_guard_names_match_code` はこの箇条書きと上の「名前」列だけを読む。歴史説明に旧名を書くのは自由だが、この一覧と「名前」列に旧名や実在しない名を残すと失敗する。上の表は判定のまとめで道具と対応付けていないので、道具別の対応はここで宣言する）:

<!-- 見張り番の道具別一覧 -->
- `_inputs.py`（共有ヘルパー。各道具はここを経由して呼ぶ。直接呼ぶのは `_inputs.py` を読む下の道具だけ）: `canonical-id` / `child-fail` / `cond-args` / `cond-case` / `cond-graph` / `cond-keys` / `cond-kind-args` / `condition-set` / `cov-keys` / `cov-shape` / `coverage` / `dup-built` / `dup-condition` / `dup-fixture` / `dup-id` / `fixture-set` / `fixture-shape` / `fp-bytes` / `fp-ledger-extra` / `fp-mode` / `fp-sha` / `fp-structural` / `fp-type` / `fp-unregistered` / `json-empty` / `json-missing` / `json-parse` / `out-exists` / `path-count` / `path-cwd-only` / `path-empty` / `perm-cap` / `perm-count` / `perm-declared` / `perm-edges` / `perm-expected` / `perm-runs-min` / `proj-buckets` / `proj-fields` / `report-shape` / `rows-zero` / `trial-count` / `v1-derivation` / `own-shape` / `exempt-loader-name` / `exempt-dup-entry` / `json-dup-key` / `box-shape` / `exempt-path-overlap` / `guard-callers-shape`
- `check-dir-rule.py`: `dir-rule-counters` / `dir-rule-report` / `dir-rule-v1`
- `count-none.py`: `none-counters` / `none-expectations`
- `edge-order.py`: `edge-child-fail` / `edge-group-empty` / `edge-json-parse` / `edge-out-shape`
- `test-contract.py`: `own-names` / `own-tools` / `own-files` / `md-fence-form` / `import-binds-guard` / `import-unregistered` / `exempt-scan-parity` / `import-granted` / `import-star` / `guard-unbound` / `exempt-use-form` / `in-public-name` / `in-public-table` / `md-marker-form` / `exempt-map-expand` / `exempt-loader-attrs` / `in-public-write` / `import-relative` / `import-dynamic-module` / `guard-caller-file` / `guard-caller-form` / `guard-callers-scope`（第 63 ラウンド Astra 問 4 の対応表の照合と第 64 ラウンド 問 1〜3 の import 一覧・文書の書き方の検査。形の検査は `_inputs.py` が読む）
- `emit-guard-owners.py`（対応表の候補の書き出し。自動更新はしない。差分が有る日は終了 3、運用中の台帳その物への書き出しは拒否する）: `emit-candidate-valid` / `emit-diff` / `emit-target` / `emit-caller-approval`
<!-- /見張り番の道具別一覧 -->
この内訳は毎回
`test-contract.py` の正控制が機械に数える — ツリーを AST で読んで `guard('名前')` を付けた
判定の集合を作り、**実際に通った単独名指しの制御だけ**を対応として数えるので、制御を 1 本
書き忘れるか、通らなくなっただけで失敗する。第 58 ラウンド agy P2-1 は `fp-bytes` を
`and False:` に完全無力化しても検出できず（組で名指した制御が手前の `fp-sha` を見ていた）、
第 59 ラウンド Astra 問 4 の裁定で「例外台帳は作らず、網羅不足は失敗にする」に決めた。
名前集計を文字列検索から AST に替えた実測: 古い文字列検索は新しい制御の追加だけで
`['utf-8']` という実在しない見張り番の名前列を作り、数も 43 に化けた
（`out/tmp-r59/contract-2.log`）。第 62 ラウンド実測: **負控制 97 件・正控制 12 件**、
見張り番 **52 名 = 呼び出し 52 箇所**、単独名指し 52 / 52（成功だけの控制 39 名・診断消失確認だけ
13 名・両方が並ぶ 0 名（無し）。通った控制 69 本を名前ごとに保持し、後勝ちで潰さない）
（`out/tmp-r62/contract-1.log`）。第 63 ラウンド実測: **負控制 102 件・正控制 14 件**、
見張り番 **56 名 = 呼び出し 56 箇所**、単独名指し 56 / 56（成功だけの控制 43 名・診断消失確認だけ
13 名・両方が並ぶ 0 名（無し）。通った控制 74 本）（`out/tmp-r62/contract-8.log`。名前を無力化する細工を回した後も同じ値）。同じラウンドで
Astra 裁定 問 1・問 4 の台帳 **`guard-owners.json`**（見張り番の名前集合・名前と所属道具の対応・
走査対象のファイル集合の 3 照合と、許す import と名前だけを書く豁免）を足した。合計値が同数のまま
名前を入れ替える細工は台帳が止め、豁免は名乗った名前以外の動的機構を弱めないことを対で測る
（`out/tmp-r62/repro-12.log`）。第 64 ラウンド実測: **負控制 109 件・正控制 15 件**、
見張り番 **63 名 = 呼び出し 63 箇所**、単独名指し 63 / 63（成功だけの控制 50 名・診断消失確認だけ
13 名・両方が並ぶ 0 名（無し）。通った控制 81 本）（`out/tmp-r63/contract-6.log`）。同じラウンドで
走査を「禁止する import を足す側」から **`_ALLOWED_IMPORTS` の許可一覧へ**切り替え（Astra 問 1 裁定
(c)）、豁免台帳は `importlib.util` の 2 件のみ（人が登録）。裸の `compile`・`sys._getframe()`・
`object.__subclasses__()`・`sys.__loader__`・`ctypes`・`code` が穴 0 で素通りしていた実測を潰し
（`out/tmp-r63/repro-2.log` が 6 欠陥 0 件）、豁免つきの走査を主にして豁免あり・なしの**呼び出し候補
一致**を照合する前にした（Astra 問 2 裁定 (iii)。正当な豁免を登録した日に網羅の検査が止まる細工を
`out/tmp-r63/contract-3.log` で実測）。第 65 ラウンド実測: **負控制 118 件・正控制 15 件**、
見張り番 **70 名 = 呼び出し 70 箇所**、単独名指し 70 / 70（成功だけの控制 57 名・診断消失確認だけ
13 名・両方が並ぶ 0 名（無し）。通った控制 90 本）（`out/tmp-r64/contract-6.log`）。同じラウンドで
豁免を**完全修飾名 × 名前**の照合へ直し（`importlib: ["util"]` で
`import importlib.machinery as M` が通る実測を潰した。Astra 問 1 裁定 (ア) 修正版）、禁止の検査は
豁免を一切見ないようにし（`importlib.__loader__` が解禁できた実測を潰した。同 問 1 (c)）、
`from <任意のモジュール> import *` を一律の穴にして 2 形の束縛源を固定し（同 問 2）、区画マーカーを
行全体の全文一致にして README の名前一覧を専用区画へ移し（同 問 3）、台帳の照合から同じ入力の
再走査を消して**展開した豁免マップの照合**を第 2 の照合に据え直した（同 問 4）。第 64 ラウンドまでの
9 形は `out/tmp-r64/repro-5.log` が期待と違った行 0 件。変種検査
（`out/tmp-r61/mutate-guards-r61.sh`）は 24 名（第 64 ラウンドまでの 17 名に今回の 7 名）を 1 個ずつ
無力化して全名 終了 1 / クラッシュ 0 / NG 0（`out/tmp-r64/mutate-1.log` と `mutate-2.log`）
第 66 ラウンド実測: **負控制 122 件・正控制 15 件**、見張り番 **74 名 = 呼び出し 74 箇所**、
単独名指し 74 / 74（成功だけの控制 61 名・診断消失確認だけ 13 名・両方が並ぶ 0 名（無し）。
通った控制 94 本）（`out/tmp-r66/contract-5.log`）。同じラウンドで豁免を**ファイルの正準相対パス ×
完全修飾モジュール × 許可する末端名**へ直し（キーを根へ畳んだので `importlib.resources: ["abc"]` が
別経路の `importlib.abc` を通し、正当な `import importlib.util as u` を拒否していた。Astra 第 66
ラウンド 問 1 の裁定）、ファイルの照合は語尾一致をやめて**正準相対パスの完全一致**にした
（同名の `.py` が別ディレクトリに有る為、所属の違う豁免が漏れた。agy 第 65 ラウンド P2-1）。
豁免由来の束縛の読み取りは構文ごとの禁止リストを捨てて**登録した末端を直接呼ぶ形だけの白名前**に
し（注釈付き代入・ワルラス・既定値・辞書の鍵・条件式・内包・`match`・`del`・`global`・`for` / `with` の
対象・`except` / `isinstance`・デコレータ・`getattr` 経由が穴 0 件で素通りしていた。同 問 2）、
見張り番の箱 `IN` の公開名を台帳 `boxNames`（`call` / `const`）で見るようにした（同 追記の裁定 (ア)。
実測 47 名）。フェンスは接頭辞を剥がすたびに空白を詰め、字下げの中の 3 形が落ちることを同じ控制で
測る（agy P2-2）。`out/tmp-r66/repro-1.py` の 32 形は期待と違った行 0 件、変種検査は今回直した 6 名で
全名 終了 1 / クラッシュ 0 / NG 0（`out/tmp-r66/mutate-1.log`）、全測定は 120 項目 NG 0
（`out/tmp-r66/verify-1.log`）
第 67 ラウンド実測: **負控制 128 件・正控制 17 件**、見張り番 **80 名 = 呼び出し 80 箇所**、
単独名指し 80 / 80（成功だけの控制 67 名・診断消失確認だけ 13 名・両方が並ぶ 0 名（無し）。
通った控制 100 本）（`out/tmp-r67/contract-5.log`）。`out/tmp-r67/repro-1.py` の 18 行は期待と違った行 0 件
（`out/tmp-r67/repro-1.log`）。`EXPECT=122 bash out/tmp-r61/verify.sh` は実施 122 項目 NG 0
（`out/tmp-r67/verify-1.log`。追加した 2 項目は候補が実測と一致することと運用中の台帳への書き出しの拒否）。変種検査は今回足した 6 名を 1 個ずつ無力化して全名 終了 1 / クラッシュ 0 / NG 0
（`out/tmp-r67/mutate-1.log`）。同じラウンドで (1) **相対 import を許可一覧・
豁免・`_inputs` の特別扱いより先に穴**にした（`ImportFrom.level` を捨てて絶対名として照合し、
`from .importlib.util import spec_from_file_location` が標準の `importlib.util` の豁免で穴 0 件だった
実測。Codex 第 66 ラウンド P1-1 / Astra 第 67 ラウンド 問 1 の裁定 (ア)。根だけの動的機構 import
も `import-dynamic-module` へ分け、案内の「豁免台帳へ登録すれば可」を撤回した。同じ問 1）、
(2) 見張り番の箱の公開名の**書き換え・削除**を穴にした（`IN.GUARD_OFF = frozenset()` が穴 0 件で
通り、その後の `IN.guard(...)` が `False` を返した実測。Codex P1-2 / agy P2-2。Astra 問 2 の
6 マス（`call` は呼出のみ / `const` は読取のみ / 書き換え・削除は両用途で穴）を `in-public-write`
と `in-public-name` に分け、走査と候補生成が**同じ分類関数** `_box_form` を使う。制御側が箱を
書き換えていた 3 箇所（`_guards_off` / `_guards_restore` / 契約用の走りと `_LEDGER_LOADER_NAMES` の
薄め）は `_inputs` の公開関数の呼び出しと関数への引数へ移した（同じ問 2 の移行の条件））、
(3) 候補の道具 `emit-guard-owners.py` が自分の作る `boxNames` を**明示的な引数として共通走査へ
渡す**ようにした（旧台帳の表で検証していた為、新しい公開名を足した日に候補自体が作れなかった。
Codex P2-3 / Astra 問 3 の裁定 2）。差分に `boxNames` と `exemptions` を足し（Codex P2-2・agy P2-1
の「差分無し」の嘘）、終了コードを 0 = 一致 / 3 = 候補は有効だが差分有り / 1 = 失敗へ分け、
`--emit` は運用中の台帳その物を拒否する（同じ問 3 の裁定 3・4。復旧手順の案内も直した）
同じ AST 走査は `guard()` の引数が文字列リテラルでない呼び出しと `guard` の別名代入も見て、
**静的に読めない形を穴として失敗にする**（第 59 ラウンド Codex P2-1。`before= 42 after= 42` で
網羅の分母から黙って消える穴。第 61 ラウンド Codex P2-2 は `IN2 = IN` という別名を付けた呼び出しを実ツリーへ混ぜれば穴 0 のまま通過できることを実測した。Astra 第 61 ラウンド 問 2 の
裁定で **`IN.guard('名前')` / `guard('名前')` の 2 形だけを数え**、見張り番の別名代入・
`getattr` / `globals()` などの動的な取り出し・見張り番を返しただけのラッパ・仮引数やループ
変数での `IN` / `guard` への再束縛まで穴として落ちるようにした。**2 形の束縛源は決まっている**
（Astra 第 65 ラウンド 問 2 の裁定）: `IN.guard(...)` は `import _inputs as IN` の箱だけ、
`guard(...)` の裸の呼び出しは `_inputs.py` のトップレベルに 1 個ある `def guard` の定義だけ。
それ以外（`import _inputs as guard`、`_inputs` を import していないファイルでの裸の呼び出し）は
数えずに穴へ落とす。`from <任意のモジュール> import *` は許可一覧・豁免より前に一律の穴
（第 64 ラウンドまでは `import _inputs as guard` を穴にせず、豁免した import のサブモジュールを
別名で通していた。`out/tmp-r64/repro-1.log`）実ツリーは 70 名・呼び出し
70 箇所・穴 0 を実測（`out/tmp-r64/contract-6.log`）
第 57 ラウンド agy P2-2 は「表に載っているのに走っていない」制御を 13 名分数えた。Astra 裁定
問 3 は 13 個すべてを今回の必須とはしなかったが、追加できる物（`path-empty` / `path-count` /
`dup-built` / `child-fail` など）を諦める理由にもしていないので、全名前に 1 本ずつ置いた
第 68 ラウンド実測: **負控制 135 件・正控制 19 件**、見張り番 **83 名 = 呼び出し 83 箇所**、
単独名指し 83 / 83（成功だけの控制 70 名・診断消失確認だけ 13 名・両方が並ぶ 0 名（無し）。
通った控制 107 本）（`out/tmp-r68/contract-6.log`）。`out/tmp-r68/repro-1.py` の 17 確認は期待と違った行
0 件（`out/tmp-r68/repro-1.log`）。全測定は実施 122 項目 NG 0（`out/tmp-r68/verify-1.log`）。変種検査は
今回足した 3 名と手を入れた 4 名を 1 個ずつ無力化して全名 終了 1 / クラッシュ 0 / NG 0
（`out/tmp-r68/mutate-1.log`）。同じラウンドで (1) 見張り番を消す仕組みを `with IN.guard_off('名前'):`
の**区間**へ改め、区間を作れる場所を台帳 `guardCallers` に登録した制御ファイルへ絞った
（第 67 ラウンドまでの `IN.set_guard_off(...)` は呼び出し後も無効化が残った。両名 P1。Astra
第 68 ラウンド 問 1 の B案。決 92 を改訂し、静的に読める利用と実行境界だけの保証という残存リスクを
同じ行へ書いた）、(2) 箱の公開名の出現を**位置で分類する既定拒否**にした（条件式を挟んだ書き換え
`(IN.CONST if True else None)._str = 'x'` が穴 0 件で通り、`HERE_after=/tmp/r67-review` と実値まで
変わった実測。Codex P2-2 / agy P1-1 / Astra 問 2。許可した読み取り位置に無い現れ方は `unsupported`
として穴）、(3) `in-public-name` を消した日に名前側の規則だけ消えるよう、診断の側でスイッチを 1 個ずつ
読んだ（agy P1-2）。

第 69 ラウンド実測: **負控制 137 件・正控制 20 件**、見張り番 **85 名 = 呼び出し 85 箇所**、
単独名指し 85 / 85（成功だけの控制 72 名・診断消失確認だけ 13 名）（`out/tmp-r69/contract-7.log`）。
全測定は実施 122 項目 NG 0（`out/tmp-r69/verify-1.log`）。同じラウンドで (1) 台帳 `guardCallers` の
権限を**人が承認した物に絞った**（形の検査で重複・途中の `.` / `..` / 空の区間・終端の `/`・`.py`
でない綴りを拒否し、読み込み時に正準化しない。実走査対象に実在することを新名前 `guard-callers-scope`
で検査し、候補生成は承認済みを一覧へ引き継いで観測との差は案内だけ出す。未承認の観測は
`emit-caller-approval` が表示した上で終了 1。Codex P2-1 / P2-2・agy P1-1・Astra 問 3-2。決 94）、
(2) 呼び出しの受け手を**コンテナリテラルを通った経路で断つ**形にした（Astra 問 3-1 の (c)。
`([IN.X] * 2)[0]()`・`(((…) * 2) * 2)[0]()`・`((… if p else []) * 2)[0].clear()`・`(IN.X,)[0]()`・
`(f'{[IN.X]}').lower()` を拒否し、`(IN.HERE / 'x').read_text()`・`('%s' % IN.X).lower()`・
`local[IN.X]()`・`f([IN.X])` を許可する 22 形を対で控制に固定。agy P1-2）。**残る穴として決 94 に
書いたのは単項演算だけを経た受け手**（`(+IN.X)()`）で、Astra は「直接オペランドの演算一般は
必ず別の値になるとは説明しない」として演算の受け手の全面禁止 (b) を却下した。独自の `__pos__` /
`__add__` が自分自身を返す型が現れた日は人が許可を増やす

第 69 ラウンドで負控制の実行器は **3 回実行**（ON → 対象だけ消す区間の中 → 区間を抜けた後の ON）に
改め、無効化集合の観測を 6 箇所・**集合全体の完全一致**へ改めた（Astra 問 1。決 95）。基準は制御の
開始時に保存した集合だけで、素の実行が漏らした無効化を復元元として採用しない。区間の終了処理は
`finally` の内側と外側に分け、失敗の転記を外側の `finally` の中でする（`finally` から `return` して
元の例外を成功にすることがないようにする）。子プロセスは `IN.guard_env()` が**今の区間の集合から
毎回作った `env`** で起こす（親の `os.environ` を切り替える方式は、切り替え忘れと区間を抜ける前に
子を起動した時の誤った集合を子へ伝える。問 1 条件 5）。制御がジェネレータやコルーチンを返した日は
制御の欠陥として落とす（本体が区間を抜けた後へ走ると観測が総ずれする）

第 70 ラウンドで実行器を **2 層に割った**（Astra 問 2・問 3。決 96）。`_run_negative()` は**実行だけ**
をして失敗は呼び出し側が渡した列へ積み、通った階級を返す。`failed` にも網羅 `ran` にも手を出さず、
**網羅への登録は `negative()` の側**だけが行う。無効化集合の読みと OFF 区間は**状態オブジェクト経由**
（本番は `_RealGuardState`。`IN.guard_off` を値として持ち出さず `with` の管理位置で直接呼ぶので
第 67 / 68 ラウンドの箱の規則を破らない）。これで**偽の状態**を実在の箱を汚さずに作れるので、実行器
自身の自己検査を正控制 1 本（`_runner_self_check`。7 確認）で持つ — ① 消しても同じ診断が出続ける
偽制御 ② 4 件 → 3 件へ減るだけの偽制御 ③ 区間を抜けた後に無効化が残る ④ 例外の時だけ復元される
区間（正常終了と例外終了の両方）⑥ 復元後の再実行の時にだけ集合が汚れる、そして本番の箱を通す
正常系。偽物が自分で期待する失敗を返す検査はしていない。観測点⑥は `finally` の中で観測して
その場で転記する（Codex 第 70 ラウンドの実測: 3 回目だけ汚れると `failed=[]` で通った）。**診断を
件数の条件で捨てる控制**（`len(bad) == N` で無視）も 6 本を全件照合へ改めた（実測: `public_write_hole`
が ON 4 件 → OFF 3 件で `failed=[]`、clean の単独名指しとして記録されていた）。網羅の記録は
**登録済みの単独名指し控制からしか生まれない**事を `singleton_record_errors` が検査する（キー集合の
一致だけでは実在の名前への混入を読めない。問 3）。第 70 ラウンド実測: **負控制 137 件・正控制 21 件**、
単独名指し 85 / 85（`out/tmp-r69/contract-14.log`）

双人レビュー（Codex の P2 2 件）は同じ根から出ていた — 網羅の記録の検査が**階級の字が既知なら
何でも通す**形と、自己検査が `ran['singleton']` の**キー集合しか前後を比べない**形。前者は
`_singleton_tiers()` が `negative(...)` の呼び出しを AST で読んで `fallback=` を書いていない控制は
`clean` しか取り得ないと宣言から決め、逆の階級の記録を落とす。後者は**記録その物**（キーと値の
完全一致）を比べる形へ改め、細工の 3 形を `_record_pollutions()` として自己検査の中に入れた —
実在のキーへの未登録の混入 / 同じ記録の二重計上 / 宣言が `clean` だけの控制への `fallback` の記録。
細工は本番の記録のコピーで測るので網羅は壊さない。Codex の再現（実行のたびに既存キーへ記録が
足される）は `自己検査が網羅の記録その物を変えた` で落ちる（`out/tmp-r69/probeH4.py`）

同じラウンドの Codex で P2 を 3 件もらった。① 宣言が許す階級を `fallback=` の有無で決めており、
`clean=False` の控制の `clean` の記録を通していた — 実行器は階級を `clean` の値だけで決める
（`clean=True` → `clean`、`clean=False` → `fallback`）ので、宣言から読む階級は常に一つ。実測で
109 控制すべてが単一の階級に決まる（`clean` 94 / `fallback` 15）。② `_singleton_controls()` が
`guards` をキーワードでしか読まなかったので、読み取りを `_singleton_tiers()` と同じ 1 本へ寄せた
（2 本置いたままがズレの場所）。③ 細工の「登録と逆の階級」は、選んだキーに `clean` だけの控制が
無い日を作れず黙って 2 形に減っていた — 細工は階級を問わず選べる形へ改め、自己検査は 3 形が揃わ
なかった日、網羅の記録が 1 件もない日、`negative(...)` の宣言が 1 件も読めない日を失敗にする

同じ所の Codex で P2 を 2 件もらった（どちらも実在の控制では起きないが規則として誤っていた類）。
位置引数 5 番目の `clean` が定数でなく式（`not True` の様な物）の日を、キーワード形だけ両階級を許す
側に立てていた — 位置形は読み落として `clean` と決め、その控制が実際に取る `fallback` の記録を
「宣言と逆」として落とす。式の評価はここでしないので、**正常な記録を誤って落とさない方**（両方を
許す）へ揃えた。細工の「登録と逆の階級」は `ran['singleton']` の先頭のキーだけ見ており、そこに
宣言が両階級を許す控制しか無いと、別のキーに作れる細工があっても `混入の細工を [...] 作れず` の
偽の失敗を出していた — キーをまたいで探す形へ改めたので、細工が 0 本になるのは網羅の記録が 1 件も
無い日だけになった（`out/tmp-r69/probeH6.py`）

第 72 ラウンドの双人レビュー（Codex P2 1 件 / agy P2 4 件）で根本が出た。階級を読む `_singleton_tiers()`
と名前組を読む `_negative_guard_groups()` が**別々に AST を歩いていた**ので、同じ `negative(...)` でも
読み取れる形が違った（タプルの `guards`、`name=` のキーワード、`**kwargs` の展開、位置引数の `clean`
が式の日）。3 ラウンド続けて「片方だけ直った」が出た訳なので、読み取りを `_negative_calls()` の
**1 本**へ寄せて両者をそこから導出した。静的に読めない引数は黙って読み流さず、**単独名指しとして網羅へ
登録される控制**に限り `_negative_unreadable()` が失敗にする（`guards` を書かない控制と、契約走査が組む
動的な偽名は網羅へ入らないので対象外）。細工の検出は本番の記録との**差分**で見る形にした（別のキーの
既存違反が先頭に返るだけで「細工を検出した」と通っていた）。階級を反転させる細工は登録済みの記録だけ
から選ぶ（未登録の記録を選ぶと階級の検査自体が働かず、差分が 0 件になった）。実測: 139 本の呼び出しから
名前組 119 / 単独名指し 109 を導き、読めない物は 0。汚れた記録を混ぜても 3 形すべてが差分 1 件を出す
事は `out/tmp-r69/probeH7.py` で測る

第 73 ラウンドの双人レビュー（Codex P2 2 件 / agy P2 4 件）で、細工の作り方がもう一段本物に近づいた。
① 混入の名前を既存の記録・登録と衝突しない選び方にした（固定の名前が既に有る日、細工は「未登録の
混入」ではなく「二重計上」に化けていた）。② 記録の書き換えは控制名ではなく**記録の位置**でする形に
した（同名の先頭記録を掴んで、選んだ物と違う記録を上書きし変更ゼロになり得た）。③ 各細工が「自分は
どの診断を増やすべきか」の目印を添え、自己検査は**その目印の件数**が増えたかで確かめる（別の診断が
増えただけで「検出した」と通るのを防ぐ）。`_negative_calls()` は `*args` の展開を動的と読む様にし、
`dyn` の初期化を `guards` の読み取りより前へ寄せ（後に初期化して上書きしていた）、式の `clean` は
単独名指しの控制だけを失敗にする。文書側は追跡下の `check-invariants46.py` に残っていた U+8FC7 を直し、
**この検査器自身の持ち物として** `japanese_glyphs_only` を足した（手元の字形検査は JIS で符号化できる
変体字を明示リストに足すまで素通りする為）。frozen な `battery/r43-before.mjs` の注釈に残る U+5E76 は
昔の物なので意図的にそのまま（新しい控制の対象にも入れない）

同じ走査で自分も落ちた。新控制の説明文を書いた直後に U+9488 と U+7EC6 の誤字を混入させて suite が終了 1
になった（**検査が働いている証拠**）。説明は字形その物を書かずコードポイントで書く運用にして通した。
この 2 字と U+8FC7（「過」の簡体字）・U+8D1F（「負」の簡体字）・U+67E5（「査」の簡体字）・U+5BF9（「対」の
簡体字）は、足す前の手元の字形検査の明示リストにも入っていなかったので、**両方**の一覧へ足した
（今のリストには入っているので、上の再現コマンドで「無い」とは出ない）。U+673A（机）は簡体字
「機」に対応するが日本語の「机（つくえ）」でもあるので禁止していない（双人レビュー Codex 第 74 ラウンド
P2-2）。追跡下の一覧対象での再発は 0 件

第 74 ラウンドの双人レビュー（Codex P2 2 件 / agy P2 4 件）で、細工の目印を**文字列の部分一致**から
**規則名の接頭辞**へ変えた。`singleton_record_errors` の診断が `[規則=未登録]` の様に規則を先頭へ持つ
ようになり、自己検査は `e.startswith(f'[規則={mark}]')` で数える（部分一致だと控制名が目印の文を含む
だけで見かけ上増えて通る。Codex P2-1）。細工の 3 形の目印は `未登録` / `重複` / `階級逆` の 3 つ。
重複の細工は**既に重複の有るキーへ戻さない**（3 件並んでいるという診断が出て目印の件数が**減る**。agy P2-1）。
`_negative_calls()` は `*args` が有る日に**位置引数を一切読まない**（キーワードはズレないので読む。
agy P2-2: `negative('a', fn, *[], guards='g')` で位置とキーワードの両記という誤った理由を出していた）。
案内と実体の機械検査 `doc_pointers_resolve` を足した（双人レビューで 3 ラウンド続いた案内漏れ・
実行不能な案内・実測値の取り残しへの回答。① バッククォートの `skill/` `docs/` `demo/` `README.md` は
実在する事 ② 行末の注釈 `# 説明（N 項目）` の項目数は道具名ごとに 1 つ）。①は `out/` を見ない
（gitignore 済みの作業台帳）。②で `117 項目` と `130 項目` が並んでいた実物を実測 130 に揃え、決め表の
「5 項目」を実測値と取り違えない為に行末注釈に限定した。正控制なので見張り番の台帳は変えていない

**スイッチにしない判定は 4 種類だけ**（Astra 裁定 問 1: 「消すと後で壊れる」という理由だけでは、
入力契約の判定を例外へ移さない）。①**引数が足りない**（調べるグラフも `report.mjs` も渡されて
いない）②**引数を整数として構文解析できない**（順列上限や試行回数に文字列を渡す）
③**ファイルを開けない・読めない**（要求一覧・既知差分・指紋台帳が無い、子プロセスが起動
しない）④**要求一覧の形が壊れていて起動条件を組み立てられない**（`IN.launch_conditions()` は
要求一覧を**読む前に** `validate_required_spec()` を通し、`fail_required_spec()` が同じ見出しと
復旧手順を出して終了 1）。④は見張り番を消して組み立てを続けると後段が traceback になるという
構造上の前提なので、やはり名前を付けない。だからその時の網羅の数の話とは別枠で、**正控制**
`broken_required_ledger_same_message` が 2 本の道具（`check-invariants46.py` と
`self-consistency.py`）の同じ案内を毎回検査する。いずれも**検査を始める操作その物が成立しない**
ので、名前を付けずに不良として終わらせる。逆に 0・負数・絶対パス・型違い・`#` 混ざり・配列要素の型違いは**入力契約**なので
名前を付けて消せる（第 57 ラウンド agy P2-2 でスイッチ外に残っていた `graph` の型検査と
`fixtures` の要素の型を、それぞれ `cond-graph` / `fixture-shape` へ移した）

`path-cwd-only` だけ意味が逆で、**第 54 ラウンドまでの古い挙動**（cwd に無い相対パスを
リポジトリ根で探す）を**戻す**スイッチ。その挙動へ戻した日に制御が検出できるかを見るため
だけのもので、通常の実行では入れない

## 縁順・入れ替えで表示が変わらないことを確かめる

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `allperm.py` / `allperm-corr.py` | `python3 skill/scripts/tools/battery/allperm.py skill/scripts/report.mjs skill/scripts/tools/battery/min-0.json` | 「縁順 720 通り / 表 1 通り」（割れたら終了 1）。**付き合わせているのは 6 欄**（`external` / `entries` / `artifacts` × `in` / `out`）とその欄（`id` / `bucket` / `direction` / `hops` / `switches`。corr は `correspondence` も）で、形が崩れた日は名前で終了 1。第 3 引数で**期待する縁順の通り数**を明示できる（違う数なら走る前に終了 1。縁が 1 本以下のグラフも空振りなので終了 1） |
| `allperm-full.py` | `python3 skill/scripts/tools/battery/allperm-full.py skill/scripts/report.mjs skill/scripts/tools/battery/min-0.json` | 「判定: JSON 完全一致」。24 通りを見たいなら第 3 引数に `min-2.json 24`。**上限は 2 以上**（`0` は割り算の前で、`1` は比較が起きないので終了 1。第 56 ラウンド Codex P2-2 → 第 57 ラウンド agy P2-1 で `0` の `ZeroDivisionError` を実測）。入力が無い・全実行失敗なら **測らずに**終了 1。第 55 ラウンド agy 指摘で `allperm.py` / `allperm-corr.py` と同じ**縁が 1 本以下なら空振り**検査を足した。間引きは `floor(i × (通り数−1) / (上限−1))` 番目を選ぶ**等間隔標本**で、**原順と完全逆順が必ず入る**（Astra 裁定 問 5。第 57 ラウンドまでの `perms[::step][:cap]` は辞書順の先側ばかりで、完全逆順が標本から抜ける日を黙っていた） |
| `r43-permute.py` | `python3 skill/scripts/tools/battery/r43-permute.py skill/scripts/report.mjs` | 固定 2 条件（`r42-calls-*.json`）で 120 入れ替え → 表 1 通り。第 3 引数で試行を変える（**1 以下は走る前に終了 1**。第 57 ラウンド agy P2-1 実測: 旧実装は 1 とおりで「表 1 通り」と合格した）。間引きは `allperm-full.py` と同じ等間隔標本（原順・完全逆順を含む） |
| `find-splits.py` | `python3 skill/scripts/tools/battery/find-splits.py skill/scripts/report.mjs 250 <種> out/splits/splits-rNN.json` | 「入れ替えで割れた例 0 / 試行 250」（割れた例があれば終了 1）。**種は毎回新しく**（使った種は protocol に記録）、出力先も毎回新しいパスを渡す。親ディレクトリは作る |
| `via-cycle.py` | `python3 skill/scripts/tools/battery/via-cycle.py skill/scripts/report.mjs` | 「18 レポート / 違反合計 0」。書き出し先を指定しない限りリポジトリへ何も書かない |
| `edge-order.py` | `python3 skill/scripts/tools/battery/edge-order.py` | 「不一致 0 件（0 が期待値）/ 集計された群 13 件」。`query.mjs` の `--group-by` 集計が縁順に依存しないことの実グラフ side の証拠。**4 本の起動すべてが 0 群なら比較する相手が無いので終了 1**（単一の起動が 0 群その物は正当。`--dir in` の起点はそうなる）。`query.mjs` の子実行まわりは**子実行の 3 判定＋合計 0 群の 1 判定**の 4 個に別名で名前を付けた（子実行の非 0 終了は `edge-child-fail`、stdout の JSON が読めないのは `edge-json-parse`、`groups` / `summary` の形は `edge-out-shape`、4 起動の合計が 0 群は `edge-group-empty`。第 60 ラウンド双人レビューでこの行が改名前の 3 名前と`edge-order-groups` を載せたままだった（第 61 ラウンド agy P2-4）。第 57 ラウンド agy P2-2。Astra 裁定 問 4 どおり `.mjs` は変えず、追加した判定がこの呼び出し経路で働くことを制御で確かめる） |

第 56 ラウンドで `allperm.py` / `allperm-corr.py` / `allperm-full.py` / `via-cycle.py` /
`r43-permute.py` の**子の JSON 読みを `IN.run_json` へ寄せた**（それまで `json.load(open(out))`
の直読みで、終了 0 で何も書かない実行や空の出力に対して traceback だけ残していた。今は
`json-missing` / `json-empty` / `json-parse` / `report-shape` が名前で止める）

`min-0.json` / `min-2.json` / `r42-calls-*.json` は順列検査が使う最小グラフ。
`via-cycle.py` は `baseline-v1/` と同じ条件でも自分の手で組み直して走らせる

## 性能ゲート（バッテリーの後に、単独で）

バッテリーが全部緑の日にだけ、ほかの測定を止めてから実行する。タグは毎回新しくする
（同じタグの集計・生ログが 1 本でも有れば測る前に終了 1）。

```
bash skill/scripts/tools/paired-gate.sh <新しいタグ>      # 5 組交互・中央値 1.20 以内・RSS 800 MB 以内
```

落ちた日は組ごとの倍率の幅とそのときの load を印字する。**混雑を理由に免除はしない**ので、
静かな窓で新しいタグを使って測り直すのが唯一の通り方（第 50 ラウンド p50d は load 4.7 で
`elsa-folder` 1.49 が出て不合格、静かな窓の p50e で 1.04 を採用）。
生ログ `perf-raw-*.jsonl` が残った実行は不合格として扱う

## 条件の作りかた

上の実行例は `out/loop/protocol.md` §4-3 と**同じコマンド**を貼っている。どちらか一方だけ直して
ズレるのが過去の実事故（第 48 ラウンド）なので、直すときは必ず両方同じへ直す

第 75 ラウンドの双人レビュー（Codex ACCEPT / agy P2 4 件）で、細工を 3 形から **5 形**へ増やした。
`[規則=形]` と `[規則=階級未知]` は細工の対象外で、規則を付けるのを忘れた診断に自己検査が気づけない
所を突かれた（agy P2-4）。今は 形 / 未登録 / 重複 / 階級逆 / 階級未知 の 5 規則すべてへ細工を当て、
件数が 1 件ずつ増える事を確認している。`doc_pointers_resolve` は ① の対象に Markdown リンクの宛先と
改行で割れているリンクを一時増やしたが、**Astra 第 21 ラウンド裁定で撤去した**（下の「区域の切り直し」）。
② の実測値は
「（.NET 不要、28 項目）」の様な**括弧の後ろに項目数が来る**書き方を読む（agy P2-1）。行数の記載は
「いつの実測か」を添えて書く運用に改めた（agy P2-3）

## 文書の案内先の実在を見る検査の区域の切り直し（Astra 第 21 ラウンド裁定）

`doc_pointers_resolve` は**固定書式の案内だけ**を見る。コード（バッククォート）で囲まれた
`skill/…` `docs/…` `demo/…` `README.md` の path を拾って実在と照合し、git に無視される物
（ビルドで建つ物）は落とさない。フェンスの中も見る（設定例に書いた path も案内だから）。

**Markdown の記法は解釈しない。** リンクの宛先、見出しのアンカー、`][`、改行で割れているリンク、
フェンスとコードの読み分け、そして「読めない書き方を黙って通さない」規則。道具の呼び出し例に書いた
項目数の文書間一致も外した。外した物と影響は `docs/maintenance.md` §保留一覧 に書き、双人レビューが
文書を人の目で辿って見る。見本 `skill/scripts/probe-doc-links.py` は「測る物が落ちる」5 件と
**「測らない物が通る」15 件**を並べて、撤去した保証を静かに消さない（20 とおり、不一致 0 で終了 0）。

実行器の自己検査（細工を 5 規則すべて 1 件ずつ増える形で測る）の見本は
`python3 skill/scripts/probe-guard-pollution.py`（不一致 0 で終了 0）。2 つとも**見張り番の走査対象**
（`skill/scripts/tools/**/*.py`）の外に置いてある。走査は新しい `import` に台帳の登録を要求する為、
見本を台帳の内側に入れると台帳を動かさないと追加できない。規則の弱体化ではなく、道具の置き場所の
決め事として `docs/maintenance.md` に書いてある。

### 第 76 〜 80 ラウンドの履歴（この区域で 3 ラウンド連続 REQUEST_CHANGES を受けた）

- **76**: 山括弧形 `[説明](<path>)` を「`<` を含むファイル名」と読んで誤検出し、タイトル付き
  `[説明](path "題名")` を読めず壊れたリンクを素通していた
- **77**: **検査が自分の説明文を落として** suite が通らなかった（agy P0。README に書いた例の示しが
  壊れたリンクに見えた）。角括弧のネストとエスケープで参照リンクの禁止を迂回できた。ビルドで建つ物
  （git に無視される `skill/analyzer/bin/`）の実在を落とした
- **78**: 閉じていないバッククォートで後続の本文を捨て、壊れたリンクを素通した。行頭の 3 連だけ見て
  フェンスを切り替え、行内の `` ```x``` `` をフェンス開始と誤認した。`][` はラベルを解釈しない限り穴が
  塞げないので、書く事自体を禁じる形へ切り替えた
- **79**: 前ラウンドの直しが退行を生んだ。フェンスごと行を飛ばして**実在と件数の検査まで捨て**、閉じ
  フェンスに情報文字列を許して ` ```sh ` で閉じたと読み、閉じない列の後ろを本文と読んで誤拒否した
- **80**: フェンスの中の `## 見出し` の例で本文の壊れたアンカーが通り、空白を含む見出しの標準的な
  スラッグ（空白が `-` になる形）を誤拒否した

5 ラウンドで出た指摘は**1 件も実文書の案内の欠落ではなく**、検査の側の読みと説明文の誤記だった。
「読めない構文は落とす」を人が普通に書く文書へ適用すると、指摘と修正が記法解釈の堂々巡りになる。
Astra 第 21 ラウンド（問 1〜3、xhigh）の裁定で区域を切り直し、記法解釈を人の目へ返した。裁定は
`docs/maintenance.md` §基盤整備の区切りと保留一覧に書いてある。
