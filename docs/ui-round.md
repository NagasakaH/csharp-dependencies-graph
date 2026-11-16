# UI ラウンドの実装仕様（関連候補の一覧と中心指定のグラフ）

出典: `out/tmp-r63/ui-round-spec.md`（第 63 ラウンドに人が決めた形）。`out/tmp-*` はディスク掃除の
対象なので、作業中の上書きを避けてリポジトリ追跡下へ写した。行番号は**着手時に `grep -n` で
数え直す**こと（2026-11-16 実測で `skill/viewer/template.html` 893 行、検査は `skill/scripts/verify.mjs`
の 26 項目）。

## -1. 第 85 ラウンドで追加した目的（人の指示）

「API のエンドポイントや DB のテーブルから調べるのを重点的にできるようにしたい」。なので §2 の
一覧とあわせて、次をこのラウンドの本体にする:

- **エンドポイントの形のまま検索できる**こと。`scan-terraform.mjs` は `aws_api_gateway_method` へ
  `endpoint`（実測 `POST /orders`）と `apiPath` を既に入れるので、ビューア側は名前だけでなく
  `endpoint` / `apiPath` / `http_method` / `terraformAddress` / `table` / 列の型も検索対象にする
- **DB のテーブルと列が名前で引っかかる**こと（`ext:rds-table/...` の `metadata.table`、
  `ext:rds-column/...` の `name` と親のテーブル）。列は `status` のようにコードの型名と衝突するので、
  結果行に「どのテーブルの列か」を出す
- **入口を一覧から選べる**こと。検索語を打たなくても API エンドポイントとテーブルの一覧から
  クリックで調査を始められるパネルを左欄に置く
- **逆に辿れる**こと。エンドポイントから Lambda → handler → C# の handler へは `exposed-by` と
  `triggers` が**コード側からリソース側へ向く**縁なので、`--dir out` では届かない（demo で実測）。
  弊害検証一覧と、そこに添える `query.mjs` のコマンドは **`--dir both`** を使う（§2 の `--dir out` は
  この実測で置き換える）

## 0. 着手条件とゲート

- **`1496821`（第 63 ラウンド）以降のコミットで、新しい双人 ACCEPT**（`out/review-codex63.log` の
  `VERDICT`/最終行と `out/review-agy63.log` の最終行を必ず読む。第 62 ラウンドは codex が判定行を
  出さずに絶命したので「前回通った」を根拠にしない）
- 触ってよいのは `skill/viewer/template.html` と `skill/scripts/verify.mjs`（＋ドキュメント）。
  **`skill/scripts/*.mjs` を 1 行でも変えたら性能ゲート**（`out/tmp-r50/gate-p51a.log` の作り方、
  比較対象は固定ビルド `out/wt-head`＝`a44b7c7`。**消さない・除外しない**）を通す
- ビューアの実測は playwright（`node skill/scripts/verify.mjs --html <graph.html> --shots <dir>`）と、
  `elsa` の実グラフ（48 MB / 51,179 ノード）で打ち切りラベルが実際に動くことを確認する

## 1. 黙って切る 6 箇所を「表示 N 件 / 全 M 件」にする

`template.html` の打ち切り（2026-11-16 実測の行番号）:

| 場所 | 行 | 今 | 決め方 |
| --- | --- | --- | --- |
| 中心の周辺ノード | `:256` `MAX_FOCUS = 120` | 黙って 120 件 | 見出しの右に「表示 120 / 全 412 件」 |
| 子ノード | `:257` `MAX_KIDS = 400` / `kids.slice` `:277` | 黙って 400 件 | 同じ書式 |
| グラフの縁 | `:337` `MAX_EDGES = 900` | 黙って 900 本 | 凡例の近くに 1 行 |
| 詳細パネルの縁一覧 | `:555` `sorted.slice(0, 60)` | 黙って 60 本 | 一覧の上に出す |
| 検索候補 | `:593` `.slice(0, 60)` | 黙って 60 件 | 候補欄の末尾に 1 行 |
| 検索結果 | `:739` `scored.slice(0, 200)` | 黙って 200 件 | 結果見出しに出す |

- 「全 M 件」の M は**実際の総数**（`length` を切る前に取る）。0 件のときはラベルを出さない
- 数値のラベルは 1 箇所のヘルパ（`truncLabel(shown, total)`）に集約し、6 箇所で使い回す
  （6 本別々に書くと、後から 1 箇所だけ書式が変わって機械検査が追えない）

## 2. クリック → 弊害検証一覧（**一覧を主**・20 行・4 区分）

人が決めた形（確定。再質問しない）: **グラフより一覧が主**。20 行表示。4 区分。

- きっかけ: 詳細パネル（`:519` のボタン列のある所）に「弊害検証一覧」のボタンを足す（クリック→一覧）
- 4 区分（上から順。各区分に件数と「表示 20 / 全 M 件」）:
  1. **コード**（同じファイル / 同じクラスの他の箇所。`kind` が `file` / `class` / `method` の実縁）
  2. **呼び出し**（`handler` 縁とその先の実縁。`realEdges > 0` の届いたノード）
  3. **リソース**（`lambda` / `sfn` / `api` / `table` / `column` など Terraform 側のノード）
  4. **不確か**（階層の縁だけで届いた物＝`reachedByHierarchy` が真、および annotations 由来の縁）
- 並びは区分内 `hop` 昇順 → `realEdges` 降順 → `id` 昇順（`query.mjs` の整列規則と同じ keys を使う）
- **照合を機械にさせる**: ブラウザ側の一覧は `query.mjs --json` と**同じ規則**で計算するので、
  `verify.mjs` に「同じノードについて `query.mjs --json` の `reached` と照合して一致」項目を足す
  （規則が 2 本に化けるのを防ぐ。第 60 ラウンド Codex P2-2 の「検査を 2 本持つ」と同じ失敗）
- 20 行を超える場合は「残り M 件を `query.mjs` で見る」コマンドを 1 行コピー可能に出す
  （`node skill/scripts/query.mjs --graph <path> --start <id> --dir out --hops 2 --json`）

## 3. 中心 + N ホップの残り

- `:519` のボタン列は現在「出力 N」「入力 N」「周辺 1」「周辺 2」の 4 個（`focusNeighbors(i, hops)` は
  定義 `:427` / ボタン `:519` / `window.__csdg` 公開 `:859` の 3 箇所。**ui-plan.md の「呼ばれていない」は古い**）。
  「周辺 3」「周辺 4」「周辺 5」を同じ `mkBtn` で足す
- 「中心に戻す」を足す（`state.ghost` を空にして `state.selected` を保つ）。既存の大域的
  `#btn-collapse`「1 階層に戻る」（`:144`、handlers `:870`）とは役割が違うので別名にしておく

## 4. URL ハッシュ

- `currentHash()`（`:853`）は `expand` と `select` だけを書く。**`hops` を追加**して
  `#select=<nodeId>&hops=2` の形にする（新しい `#focus=` は発明しない）
- 読み側 `:845` は `expand` / `select` を処理済み。`hops` は同じ関数で読み、`select` が無いとき無視する
- `verify.mjs` に「ハッシュを書いて再読込→同じ状態」の項目を足す（playwright で reload して比較）

## 5. 据え置く既知事項（UI ラウンドでは直さない）

- 注釈の再試行ループ、`$default` の `--api` が終了 2、`--keep-intermediates` の有無、
  csproj 所属ビュー（決 65 で「UI の後」）、契約を `schema.md` と `--help` へ寄せる整理

## 9. 第 85 ラウンドの実装記録（done）

`skill/viewer/template.html` と `skill/scripts/verify.mjs` だけを変えた（analyzer と `report.mjs` は
無変更。性能ゲートは `report.mjs` を測る道具なので、今回の変更では測れない ── 代わりに実グラフで
ビューアの応答を測った）。

- §1 の打ち切りラベルは `truncLabel(shown, total, unit)` 1 箇所にまとめ、検索結果・注釈フォームの
  候補・ツリーの子・詳細の縁一覧・周辺ホップ・状態バー（折りたたみと描画上限）で使い回す
- §2 の弊害検証一覧は **1 ノードを必ず 1 区分だけに振り分ける**（判定は 不確か → リソース → 呼び出し →
  コード の順で最初に合った方）。区分別に 20 行と「表示 20 / 全 M 件」を出す。
  計算は `query.mjs` の BFS をそのまま真似た（方向 both / 隣接の調べ順 in → out / 最初に到達した 1 経路 /
  実縁本数は調べた縁ごとに加算）。`verify.mjs` が `query.mjs --json` と突き合わせ、
  **到達順・hop・kind・provenance・実縁本数・via まで一致**することを固定している
- §3 は 周辺 1-5 を全部ボタン化し、中心に戻す を足した（ホップ数は `state.hops` に集約）
- §4 は `#select=<id>&hops=2`。hops は select と一緒にあるときだけ 1-5 を採用する
- §-1（人の指示）: 左欄に **調査の入口**（API エンドポイント / テーブル / 列 / Lambda /
  Step Functions）、`entry-filter` の select、`endpoint` / `apiPath` / `terraformAddress` /
  `table` / `dataType` / `function_name` / `handler` / 親ノード名まで検索対象、図の上も
  `displayName()`（`POST /orders` など）へ統一。入口をクリックしたら **3 ホップへ自動で上げる**
  （1 段目が Terraform 定義どうしの縁で埋まり C# が見えないため。demo 実測）

### 仕様からの逸脱（実測で置き換えた物）

| 仕様 | 実装 | 理由（実測） |
| --- | --- | --- |
| 一覧のコマンドは `--dir out` | `--dir both` | `exposed-by` と `triggers` はコード側からリソース側へ向くので、`--dir out` では `POST /orders` から Lambda へ届かない（demo で到達 0） |
| 一覧のホップは既定 2 | 入口は 3 に上げる | `POST /orders` は 3 段目で handler のメソッドへ付き、その先の呼び出しは 4 段目（demo で `--hops 3` の到達 20 件） |
| 「呼び出し」= handler 縁とその先 | 到達縁か実縁の内訳に動的な縁（calls / invokes / triggers / handler / creates）があるもの | リソースを呼び出しへ入れると「コード」と二重に数える。1 ノード 1 箇分にすれば件数が足し算になる |

### 実測（`verify.mjs` 36 項目 / 実グラフの応答）

- demo（74 ノード / 66 縁）: 36/36 件成功。`node skill/scripts/test-report.mjs` 130/130、
  `test-query` 28/28、`test-merge` 12/12、`test-terraform` 46/46
- elsa（13,000 ノード / 12,922 縁）: 初期表示 124 ms、`ExecuteAsync` 検索 118 ms（108 件 + 打ち切り行）、
  `GET /workflows` 検索 32 ms（エンドポイントが先頭）、`workflows` 検索は 200 件で打ち切り（候補欄の末尾に
  「表示 200 / 全 M 件」の行が出る）、入口クリック → 一覧 388 ms（到達 350 件）、
  最も縁の多い member（71 本）から 5 ホップの到達計算 4 ms（3,593 件）
