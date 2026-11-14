# csharp-dependencies-graph

C# プロジェクトを **フォルダ → csproj → cs ファイル → クラス → メソッド** の順で
クリック展開できる依存関係グラフと、それをブラウザで操作する HTML を作るスキル。
Terraform で管理する Lambda / Step Functions / API Gateway / DynamoDB などの外部リソースも
ノードとして組み込み、静的解析では決まらない対応付けは注釈（`annotations.json`）で後から足せる。

```sh
export DOTNET_ROOT=$HOME/.dotnet
node skill/scripts/build.mjs --root /path/to/repo --out-dir out/graph --name my-service \ \
  --exclude test,docs   # 既定で bin/obj/node_modules 等は除外。test は大きいので明示
open out/graph/graph.html
```

- 使い方・運用（注釈の書き方、検証、落とし穴）: [skill/SKILL.md](skill/SKILL.md)
- データ契約（ノード/エッジ/ID/注釈スキーマ）: [skill/reference/schema.md](skill/reference/schema.md)
- コードレビュー・設計レビューでの使い方（影響範囲・逆引きの実測レシピ）: [skill/reference/review-workflows.md](skill/reference/review-workflows.md)
- 判断の記録と実測値: [docs/decisions.md](docs/decisions.md)

## 試した対象と実測

| 対象 | ノード / エッジ | 内容 |
| --- | --- | --- |
| [elsa-core](https://github.com/elsa-workflows/elsa-core) | 51,179 / 53,521（C# 解析 3 秒、HTML 20MB） | 336 csproj、6,754 個の `.cs`（ファイル計 7,207）、8,223 型、32,572 メンバ、calls 14,607 / accesses 13,788 / references 15,633、898 ファイルが AWS/DB シグナル、1,010 ファイル（1,260 名）が「張れなかった同名候補」の記録あり |
| `demo/orders-api-lambda` | 74 / 66（静的 27 / Terraform 27 / 注釈 12） | C# Lambda 3 csproj + Terraform 15 リソース + Terraform の handler 解決 2 + 注釈 12 エッジ（RDS をテーブル → カラムまで `parent` で入れ子にした例を含む） |

検証は 2 系統あり、どちらも対象プロジェクト非依存で動く。

```sh
node skill/scripts/test-analyzer.mjs                          # 静的解析の精度（96 項目、ブラウザ不要）
node skill/scripts/test-report.mjs                            # 影響範囲レポート（33 項目）
node skill/scripts/test-query.mjs                             # 逆引き・影響範囲の照会（17 項目、.NET 不要）
node skill/scripts/test-merge.mjs                             # Lambda handler の解決規則（12 項目、.NET 必要）
node skill/scripts/test-terraform.mjs                         # API Gateway のパス組み立て（18 項目、.NET 不要）
node skill/scripts/verify.mjs --html out/graph/graph.html --shots out/shots   # ブラウザ実操作（25 項目）
```

`verify.mjs` は検査対象を `graph.json` から自動選択するので、どのプロジェクトにもそのまま使える
（今の実測: demo 25/25、elsa-core 23/23。Terraform ノードが無い対象は該当 2 項目を省略する）。
静的解析テストは「出てはいけないエッジ」と「消えてはいけないエッジ」の両方を見る。
名前が型メンバを隠す構文（ラムダ引数・ローカル関数・兄弟ブロックの同名 var）と、
`var` / `foreach` の型推論の回帰、型解決（型引数の数、`using` / `global using` による到達性、戻り値型を
宣言元で解決する）の回帰、型表記のコメント（CR・NEL で終わる行コメントを含む）や型引数の付いている名前セグメントの取り違え、同じ入力を 2 回走らせて出力が揺れないこと（決定性）に効く。

## レビュー・設計での使い方

できたグラフは「眺める」より「照会する」ほうが役に立つ。`query.mjs` はブラウザの
⇧クリック / ⌥⇧クリック（1 ホップ）の多段版で、影響範囲と逆引きをターミナルから叩ける。

```sh
# PR の変更ファイル → 外部リソース・公開 API に着地するか
git diff --name-only origin/main... > out/changed.txt
node skill/scripts/query.mjs --graph out/graph/graph.json \
  --changed out/changed.txt --hops 3 --via-parent --target-kind resource

# DB のカラム → それを読むコード → 出口（API Gateway / Lambda）
node skill/scripts/query.mjs --graph out/demo/graph.json \
  --from ext:rds-column/orders-analytics.public.order_summary.order_id --dir both --hops 3
```

`report.mjs` は同じ照会を**差分まるごとのレポート**にする。レビューに貼れる Markdown と JSON が出る。

```sh
# PR の変更ファイル → 影響を受ける入口と外部リソース（git diff をそのまま渡せる）
git diff --name-only origin/main... | node skill/scripts/report.mjs \
  --graph out/graph/graph.json --changed - --md out/impact.md --json out/impact.json

# HTTP のメソッドとパスでも引ける
node skill/scripts/report.mjs --graph out/demo/graph.json --api "POST /orders"
```

出方は次の 5 枠に分ける。混ぜるほど読み間違えるため、**どの行も必ずどれか 1 つの枠にしか入らない**
（`summary.rows` と各枠の合計が必ず一致する）。

- 影響する外部リソース / 影響を受ける入口 — 動きの縁（`triggers` / `invokes` / `handler` / `calls` / 注釈）で届いたもの
- 影響を受けるコード側の入口 / 出口 — 上記のうちコード（メソッド・型）のもの
- 同じ API を定義するノード / 同じコードを使う別エンドポイント — 定義上で繋がっているだけ
- 定義上の関連 — Terraform の `references`（ブロックを文中に書いただけ）

`--expect` に期待する着地を書くと再現率・適合率が出る。**期待リストは自分の手で確認した列を
書き写したもの**で、正解データではなく「前回と変わったかを見る整合の測定」だと思っている。
だからリストを作った人間と同じ前提の誤りは消えない。そこを割り引いて読んでほしい。

| 実測したケース（2026-11-14 計測） | 期待 | 外部着地 | 的中 | 再現率 | 適合率 |
| --- | --- | --- | --- | --- | --- |
| demo: `src/Orders.Domain/Order.cs` | 12 | 11 | 11 | 0.917 | 1 |
| demo: `README.md`（グラフに無い変更） | 0 | 0 | 0 | 1 | 1 |
| demo: `infra/main.tf`（Terraform 全部） | 0 | 3 | 0 | 1 | 0 |
| 実プロジェクト: `--api "POST /messages"` | 1 | 1 | 1 | 1 | 1 |
| 実プロジェクト: `cs/ExampleLambdaApi/Handler.cs` | 2 | 2 | 2 | 1 | 1 |

demo の 1 件の「もれ」は届いていないのではなく**枠の分け方**の結果。
`tf:aws_api_gateway_deployment.live` まで辿れているが、縁が `references` なので定義上の関連に落ちる
（JSON の `score.wiringOnly` が 1 で、それがその 1 件）。着地そのものは出ている。

実プロジェクトは [Pondidum/Terraform-Demos](https://github.com/Pondidum/Terraform-Demos) の
`api-lambda`（C# と Terraform が同じリポジトリにある最小の実例）で、**注釈を 1 件も使わず**に
`POST /messages` → Lambda → `Handler.Handle` まで Terraform だけ出ている。
`infra/main.tf` をまとめて変えたケースが適合率 0 になるのは、Terraform 経由で注釈由来の
外部リソース（`ext:rds/…`）まで届くため。粒度の荒い変更は `--provenance static,terraform` で
注釈由来を切るか、`--from tf:aws_lambda_function.…` と 1 リソースに絞る。
`--provenance` は Terraform の定義単位を結ぶ段階にも効くので、`static` だけなら API 起点でも着地 0 件になる。

変更ファイルがグラフに無いときの `--folder-start` は、同じデモで **起点 1 件 → 49 件**に膨らんで
外部着地 0 件・コードの入口 6 件だけ出た（`README.md` を変えたケースの実測）。雑に広げるより
「そのファイルはグラフに無い」と出したほうがマシなので、既定はオフのままにしている。

レシピ集（結合ハブの棚卸し、呼び出し集中の blast radius、注釈だけの依存のレビュー、
誤読しないための前提）は [skill/reference/review-workflows.md](skill/reference/review-workflows.md)。

## 構成

```
skill/
  analyzer/            Roslyn 構文解析（net9.0, cgd）。ビルドは build.mjs がやる
  scripts/             build / scan / scan-terraform / merge / render / query / report / verify
                       + test-analyzer / test-query / test-merge / test-terraform / test-report（回帰テスト）
  tests/fixtures/      静的解析と照会のテスト用データ（C# と graph.json）
  viewer/template.html 単一ファイルのビューア（データ埋め込み）
  reference/schema.md  データ契約
  reference/review-workflows.md  レビュー・設計で使うレシピ
  examples/            LLM 注釈の実例
demo/orders-api-lambda Lambda + Terraform のデモ対象
out/                   生成物（gitignore 済み）
```
