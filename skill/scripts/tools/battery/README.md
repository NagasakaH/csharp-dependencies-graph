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

```sh
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

```sh
python3 skill/scripts/tools/battery/test-contract.py
```

`test-contract.py` は**検査の検査**（負控制 37 件・正控制 6 件。負控制は**見張り番を消した
再実行つき**。上の「見張り番を名前 1 個ずつ消せる」参照）。0 行の `report.mjs`、要求一覧の
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

```sh
CGD_GUARD_OFF=fp-sha python3 skill/scripts/tools/check-battery-inputs.py   # 実行系から
```

中から消すのは `IN.set_guard_off('fp-sha')`（`IN.guard('fp-sha')` が `False` になる）。
`test-contract.py` の `negative(..., guard=..., message=...)` は各制御を **2 度**走らせる —
素の実行で `message`（その見張り番の案内）が出る → `guard` を消した実行で `message` が
**出ない**（既定では**通る**ことも要求）— ので、名前を間違えたり別の一の見で通したりした
制御はその場で失敗する。見張り番を消すと**対象の案内は消えるが、実行は別の診断で拒否される**
制御は `clean=False` を附け、`fallback` に **OFF 後も残る別の診断の文面**を宣言させる
（宣言が無い・想定と違う所で落ちた、はどちらも失敗。第 56 ラウンド agy P2-3）。第 59 ラウンド
Astra 問 2 で「実行系の制御（JSON を書かない、JSON が壊れている）だけ」という但し書きを外した
― 重複検査のように複数の見張り番が同じ細工を拾う場合もまったく同じ形で、但し書きがそれを
説明できなかった。対象を消したのに**対象の案内が残る**実行は `clean=False` でも失敗にする

| 名前 | 見ている物 | それを測る個別負控制（**見張り番を消した再実行で実在を確かめた物だけ**書く） |
| --- | --- | --- |
| `fp-structural` / `fp-unregistered` / `fp-ledger-extra` / `fp-sha` / `fp-bytes` / `fp-mode` / `fp-type` | 入力点検の 7 見（構造指紋・登録漏れ・台帳の余剰・中身の sha・バイト数・読み方・`any` 区分） | 台帳の登録を 1 件消す（`fp-unregistered`）/ fixture の縁を全部空にする（`fp-sha`・`fp-bytes`）/ **ノード id を同じ長さで書き換える**（`fp-sha`。バイト数は不変）/ **台帳に入力の一覧に無い物を 1 件足す**（`fp-ledger-extra`）/ **台帳の読み方だけを 1 件書き換える**（`fp-mode`）/ **読み方に json でも bytes でもない値を置く**（`fp-type`。消した実行は `fp-mode` が別の診断で拾う）/ **固定入力のノード数を台帳だけ 1 ずらす**（`fp-structural`）/ **台帳のバイト数だけを 1 件書き換える**（`fp-bytes`。sha と読み方を据え置くので `fp-sha` が手前に落ちない。第 58 ラウンド agy P2-1: `and False:` に完全無力化しても検査の検査が終了 0 だった。名指しが `guard=(fp-sha, fp-bytes)` の組だけだった） |
| `out-exists` / `child-fail` / `json-missing` / `json-empty` / `json-parse` / `report-shape` | 子を実行して JSON を読む 6 段階 | 出力先が既にある実行（`out-exists`）/ **正しい JSON を書いて非 0 で終わる実行**（`child-fail`。第 57 ラウンド agy P2-2: ここに「終了 0 で JSON を書かない」を載せていたが、あれは `json-missing` の制御で消すと `json-missing` が落ちる空振りだった）/ 終了 0 で JSON を書かない（`json-missing`）/ **終了 0 で空のファイルを書く**（`json-empty`。消した実行は `json-parse` が止める）/ 壊れた JSON（`json-parse` と `report-shape` を**まとめて**消す。第 56 ラウンド agy P2-3: `json-parse` だけ消すと `doc = {}` が後の形検査で落ちて、別の一で止まっていた）/ 欄の無い JSON（`report-shape`）。`edge-order.py` の子実行でも同じ 3 見を 1 本ずつ（非 0 終了・読めない出力・`--json` の形違い。Astra 裁定 問 4「追加した判定は**当該呼び出し経路**で確かめよ」）|
| `cov-shape` / `cov-keys` / `coverage` | 期待値一覧の形（型・非負整数・必須欄・合計は条件別の導出。`dirRule` は向き別の合計と `byReport` の合計が同じ行の数え直し。向き別と向き none の数えは**負の値も `true` も欄の欠落も弾く**）、**どのレポート・条件を数えるか**のキー集合、走った件数の条件別比較 | 合計をずらす / 内訳を空にする / 1 件ずらす / **件数の違う 2 件**を入れ替える / 1 条件測らない / **`agree` を 1 増やして `bad` を 1 引く**（合計は同じまま負の値。第 56 ラウンド agy P2-2）/ 向き none の数えに `true`・負の値・`none` の欠落（第 57 ラウンド agy P2-2 の横展開漏れ）/ **`byCondition` の id を 1 件だけ要求一覧に無い値へ差し替える**、**`byReport` のキーを 1 本だけ実在しない名前に差し替える**（`cov-keys`。件数も合計もそのままなので形の検査は素通りする。第 57 ラウンド agy P2-4 の `{"": 441}` 系）|
| `cond-shape` / `canonical-id` / `dup-condition` / `dup-id` / `dup-fixture` / `fixture-shape` / `fixture-set` / `condition-set` / `dup-built` | 要求一覧の形（`graph` の型・空・`#`・絶対パス・`..` を含む）・id の再計算・正準形と id の重複・**fixtures の重複**・**fixtures の要素の型**・fixture 集合・起動条件の集合・**組み上げた条件の重複** | `graph` / `args` を書き換えて id を据え置く / 重複 / `case` を消す / 値域外の kind / **`graph` を絶対パスにする**（id も同じ中身から作り直す。`cov-keys` も一緒に消して単独に測る）/ **`fixtures` に文字列でない値を置く**（`fixture-shape`。消した実行は `fixture-set` が別の診断で拾う）/ fixture を 1 本増やす / `fixtures` に同じパスを 2 度書く / **要求一覧を壊して入力点検を走らせる**（`dup-fixture`。測定道具と同じ入口を通るようになった証拠。第 57 ラウンド agy P2-3）/ 条件を 1 件消す / **builder へ重複した fixture 列を渡す**（`dup-built`。要求一覧は壊さない。第 57 ラウンド agy P2-2 で名前だけだった）/ **`graph` に `#` を混ぜて id と条件別の期待値のキーまで揃える**（`cond-shape`。素で `#` を足すと id が割れて `canonical-id` が手前に落ちる。第 59 ラウンド Astra 問 1 の実測レシピ）/ **`fixtures` から 1 本消す**（`fixture-set`。条件はそのままなので重複検査は素通り）/ **要求一覧を壊して起動条件を組み立てる**（`fixture-shape` を `launch_conditions()` の入口で測る。第 58 ラウンド agy P2-2: `check-invariants46.py` / `self-consistency.py` が `KeyError` の traceback だった）/ **同じ起動内容を 2 件並べる制御を目の違う 2 本に割った**（`dup-condition` と `dup-id`。相手の案内を `fallback` に宣言。第 58 ラウンド agy P2-1 でこの 2 名前は組の名指しだけだった）|
| `trial-count` / `rows-zero` / `proj-buckets` / `proj-fields` / `perm-edges` / `perm-count` / `perm-cap` | **入れ替え試行の本数**・0 行で合否を出さない・付き合わせる 6 欄と欄の名前・縁の本数・順列の通り数・**順列の上限と間引き後に実際に走った通り数** | **`r43-permute.py` の試行を 1 とおりにする**（`trial-count`。実測は「表 1 通り」で終了 0 だった。消した実行は `perm-cap` が別の診断で拾う）/ 0 行の `report.mjs` × 4 道具 / **`external.out` が無い JSON を `projection_rows` へ直接渡す**（`proj-buckets`。9 欄の形その物が崩れた JSON は道具の手前で `report-shape` が止まるので、内側のこの見張り番は関数へ直接渡して測る）/ 欄が消える（`proj-fields`）/ 縁が 1 本だけ / 期待縁順の通り数違い / 順列上限に **1** と **0** を渡す（`perm-cap`。0 は割り算の前で止める。第 57 ラウンド agy P2-1 の `ZeroDivisionError`）|
| `dir-rule-counters` / `dir-rule-report` / `dir-rule-v1` | 向き別の件数・**レポート別の按分**・v1 の既知差分との中身照合 | 18 本とも 0 行 / **`byReport` の按分だけ**入れ替えた一覧（向き別の合計は同じ）/ `byReport` を**実在しないレポート名 1 本**に集め替えた一覧（合計は同じ。実在しない名前の**キー集合**は `cov-keys` 側でも測る）/ 18 本そろえて 1 本だけ行を消す / **既知差分の `id` を別ノードへ動かす**（不一致 55 件のまま中身だけずらす。`dir-rule-v1` を単独で測る。第 56 ラウンド Codex P2-1）/ **v1 の `agree` を 1 減らして `bad` を 1 増やす**（`dir-rule-counters`。合計は実測のまま。第 58 ラウンドまで `dir-rule-report` と組で、手前に遮われて単独に測れていなかった） |
| `edge-order-groups` / `none-expectations` / `none-counters` | `edge-order.py` の `--json` の形と 4 起動すべて 0 群・`count-none.py` の期待値とサマリカウンタ | **実グラフの縁を全部抜いて 4 起動すべて 0 群**、**`--json` の形でない出力**（`edge-order-groups`。群の出力は比較の相手なので形も見る）/ **`expectations.directionless.none` を 1 増やして `count-none.py`**（`none-expectations`）/ **1 本の `summary.rows` を 1 増やす**（`none-counters`）。第 57 ラウンド agy P2-2: 「実グラフの縁を全部抜く」を 3 名前ぶん載せていたが、走っていたのは `edge-order-groups` だけだった |
| `path-empty` / `path-count` / `path-cwd-only` | レポート 0 件・期待件数違い・明示した相対パスを cwd から解決する | **0 件のディレクトリを `report_paths` へ直接渡す**（`path-empty`）/ **1 本のディレクトリに 18 件を期待して渡す**（`path-count`）。第 57 ラウンド agy P2-2: 「1/18 のディレクトリ」を両方の制御として載せていたが、その実行は `path-count` が先に落ちていた（道具側から単独に作れないので関数へ直接渡す）/ `battery/` から `out/audit-current` を渡す（`path-cwd-only`） |
| `v1-derivation` | 既知差分から導いた 向き の差分が 55 件であること | **既知差分の 1 件を「向きが変わらない」形へ直す**（導出が 54 件になる。第 57 ラウンド agy P2-2: 「`dir-rule-v1` の制御が同時に落とす」と書いていたが、それは `v1-derivation` を測っていなかった）|

**全 42 名に、その名前だけを無効化する負控制が有る。うち 31 名は無効化すると実行が成功し、
残る 11 名は対象の案内が消えたうえで宣言済みの別の診断で拒否される**（`clean=False` +
`fallback`）。複数名を同時に無効化する制御はこの網羅数に含めない。この内訳は毎回
`test-contract.py` の正控制が機械に数える — ツリーを AST で読んで `guard('名前')` を付けた
判定の集合を作り、**実際に通った単独名指しの制御だけ**を対応として数えるので、制御を 1 本
書き忘れるか、通らなくなっただけで失敗する。第 58 ラウンド agy P2-1 は `fp-bytes` を
`and False:` に完全無力化しても検出できず（組で名指した制御が手前の `fp-sha` を見ていた）、
第 59 ラウンド Astra 問 4 の裁定で「例外台帳は作らず、網羅不足は失敗にする」に決めた。
名前集計を文字列検索から AST に替えた実測: 古い文字列検索は新しい制御の追加だけで
`['utf-8']` という実在しない見張り番の名前列を作り、数も 43 に化けた
（`out/tmp-r59/contract-2.log`）。第 59 ラウンド実測: **負控制 69 件・正控制 8 件**、
単独名指し 42 / 42（成功 31・診断消失確認 11）（`out/tmp-r59/contract-6.log`）
第 57 ラウンド agy P2-2 は「表に載っているのに走っていない」制御を 13 名分数えた。Astra 裁定
問 3 は 13 個すべてを今回の必須とはしなかったが、追加できる物（`path-empty` / `path-count` /
`dup-built` / `child-fail` など）を諦める理由にもしていないので、全名前に 1 本ずつ置いた

**スイッチにしない判定は 3 種類だけ**（Astra 裁定 問 1: 「消すと後で壊れる」という理由だけでは、
入力契約の判定を例外へ移さない）。①**引数が足りない**（調べるグラフも `report.mjs` も渡されて
いない）②**引数を整数として構文解析できない**（順列上限や試行回数に文字列を渡す）
③**ファイルを開けない・読めない**（要求一覧・既知差分・指紋台帳が無い、子プロセスが起動
しない）。いずれも**検査を始める操作その物が成立しない**ので、名前を付けずに不良として
終わらせる。逆に 0・負数・絶対パス・型違い・`#` 混ざり・配列要素の型違いは**入力契約**なので
名前を付けて消せる（第 57 ラウンド agy P2-2 でスイッチ外に残っていた `graph` の型検査と
`fixtures` の要素の型を、それぞれ `cond-shape` / `fixture-shape` へ移した）

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
| `edge-order.py` | `python3 skill/scripts/tools/battery/edge-order.py` | 「不一致 0 件（0 が期待値）/ 集計された群 13 件」。`query.mjs` の `--group-by` 集計が縁順に依存しないことの実グラフ side の証拠。**4 本の起動すべてが 0 群なら比較する相手が無いので終了 1**（単一の起動が 0 群その物は正当。`--dir in` の起点はそうなる）。`query.mjs` の子実行に対する 3 見も名前を付けた（非 0 終了は `child-fail`、stdout の JSON が読めないのは `json-parse`、`groups` / `summary` の形は `edge-order-groups`。第 57 ラウンド agy P2-2。Astra 裁定 問 4 どおり `.mjs` は変えず、追加した判定がこの呼び出し経路で働くことを制御で確かめる） |

第 56 ラウンドで `allperm.py` / `allperm-corr.py` / `allperm-full.py` / `via-cycle.py` /
`r43-permute.py` の**子の JSON 読みを `IN.run_json` へ寄せた**（それまで `json.load(open(out))`
の直読みで、終了 0 で何も書かない実行や空の出力に対して traceback だけ残していた。今は
`json-missing` / `json-empty` / `json-parse` / `report-shape` が名前で止める）

`min-0.json` / `min-2.json` / `r42-calls-*.json` は順列検査が使う最小グラフ。
`via-cycle.py` は `baseline-v1/` と同じ条件でも自分の手で組み直して走らせる

## 性能ゲート（バッテリーの後に、単独で）

バッテリーが全部緑の日にだけ、ほかの測定を止めてから実行する。タグは毎回新しくする
（同じタグの集計・生ログが 1 本でも有れば測る前に終了 1）。

```sh
bash skill/scripts/tools/paired-gate.sh <新しいタグ>      # 5 組交互・中央値 1.20 以内・RSS 800 MB 以内
```

落ちた日は組ごとの倍率の幅とそのときの load を印字する。**混雑を理由に免除はしない**ので、
静かな窓で新しいタグを使って測り直すのが唯一の通り方（第 50 ラウンド p50d は load 4.7 で
`elsa-folder` 1.49 が出て不合格、静かな窓の p50e で 1.04 を採用）。
生ログ `perf-raw-*.jsonl` が残った実行は不合格として扱う

## 条件の作りかた

上の実行例は `out/loop/protocol.md` §4-3 と**同じコマンド**を貼っている。どちらか一方だけ直して
ズレるのが過去の実事故（第 48 ラウンド）なので、直すときは必ず両方同じへ直す
