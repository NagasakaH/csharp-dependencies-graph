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
node skill/scripts/test-report.mjs                            # 影響範囲レポート（63 項目）
node skill/scripts/test-query.mjs                             # 逆引き・影響範囲の照会（17 項目、.NET 不要）
node skill/scripts/test-merge.mjs                             # Lambda handler の解決規則（12 項目、.NET 必要）
node skill/scripts/test-terraform.mjs                         # API Gateway のパス組み立てと HTTP API (v2) の `target`（38 項目、.NET 不要）
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

出方は次の 6 枠に分ける。混ぜるほど読み間違えるため、**どの行も必ずどれか 1 つの枠にしか入らない**
（`summary.rows` と各枠の合計が必ず一致する。検査でも固定している）。

- 影響する外部リソース / 影響を受ける入口 — 動きの縁（`triggers` / `invokes` / `handler` / `calls` / 注釈）で届いたもの
- 影響を受けるコード側の入口 / 出口 — 上記のうちコード（メソッド・型）のもの
- リポジトリ内の成果物 — 経路上にあった `.csproj`・`.cs`・フォルダ・solution。触る可能性のある**ビルド単位**
  を示すだけで、動きが伝わっている意味ではない（ここを「定義上の関連」に混ぜると「触っていない設定」と
  読めてしまう）
- 同じ API を定義するノード — 起点がエンドポイントのとき、その API を定義している `resource` /
  `rest_api` / `integration` / `deployment`。変更で値は動かないので「見直しの候補」として分ける
- 同じコードを使う別の API — 兄弟として見つかったエンドポイントと、それを定義しているノード
  （`summary.siblingEndpointsOnly` / `siblingDefs` に内訳を出す）。実装を共有しているだけで、
  **別 API から自分の API へ流入している意味ではない**（`影響を受ける入口` に並べると誤読できる）
- 定義上の関連 — Terraform の `references`（ブロックを文中に書いただけ）

枠と、Markdown の見出しと、JSON の欄名と、`summary` のカウンタの対応は次どおり
（Markdown の見出しは `## 影響を受ける API エンドポイント` をのぞいてすべて `###`）。

| 枠 | Markdown の見出し | JSON の欄 | `summary` のカウンタ |
| --- | --- | --- | --- |
| 影響する外部リソース / 影響を受ける入口 | `### 影響する外部リソース（…）` / `### 影響を受ける入口（…）` | `external.out` / `external.in` | `primaryOut` / `primaryIn` |
| コード側の出口 / 影響を受ける入口 | `### 影響するコード側の出口（…）` / `### 影響を受けるコード側の入口（…）` | `entries.out` / `entries.in` | `entryOut` / `entryIn` |
| リポジトリ内の成果物 | `### 影響するリポジトリ内の成果物（…）` / `### 影響を受けるリポジトリ内の成果物（…）` | `artifacts.out` / `artifacts.in` | `artifactsOut` / `artifactsIn` |
| 同じ API を定義するノード | `### 起点と同じ API を定義するノード（…）` | `sameApi` | `sameApi` |
| 同じコードを使う別の API | `### 同じコードを使う別の API（…）` | `siblingEndpoints` | `siblings`（内訳は `siblingEndpointsOnly` / `siblingDefs`） |
| 定義上の関連 | `### 定義上の関連（…）` | `wiring` | `wiring` |

向きは縁の意味で決める。(1) 動きの縁（`triggers` / `invokes` / `handler` / `exposed-by`）で届いていれば
**矢印の先が下流**（`exposed-by` だけ逆向きで、コード側が下流）。(2) 起点がエンドポイントで、その
**実装側**に入ったなら（`exposed-by` や `handler` を手前に渡ったところ）そこから先は全部 影響する先。
ただしこの旗は**自分を呼び出している側へは受け継がない**。(3) それ以外（定義・静的解析の縁）は実際に
辿った向きを使う。だから `Step Functions → invokes → この Lambda` は 影響を受ける入口（この Lambda を
呼びにくる側）として出る。コードを変更したときはそのコードが公開しているエンドポイントも
影響を受ける入口に出る（`exposed-by` の矢印はコード側を向く）。

ただし `handler` / `exposed-by` は**実装の対応**を示す縁で、呼び出し元を示さない。起点が API
エンドポイントのときは、その対応縁で繋がる側（実装を載せた Lambda など）も 影響する先 のままです。
ここを矢印だけで判断すると、起点のエンドポイント自身の実装 Lambda が「呼びにくる側」に並んだ（実測: demo の `--api "POST /orders"`）。

各行は根拠経路 `path` と、その経路がどこから始まっているかの `pathRoot` を持つ。`start` は起点まで
辿れた行、`second-stage` は根拠経路が循環しそうな所でそこを新しい出発点として切った行で、
`broken`（`via` が宙を指す）は出てはいけない。`summary.pathsByRoot` と `summary.startIds`
で外から確かめられる。行の `reachedByInvokes` は「`invokes` の縁を矢印どおりに辿って呼ばれる側へ
着いた」ことを示す旗で、同じ実装を共有する兄弟エンドポイントと、実際に呼び出した先を区別に使う。

「IAM ロールだけを共有する別の Lambda」経由で、その Lambda 専用の integration や handler まで本命に
伝播することはない。`references` をまたいで伝播できる資格は **起点 / 本命として届いたノード / 起点と同じ API を定義する
ノード**だけを持ち、しかも**参照している側へ進む一歩**にだけ受け継がれる（自分が使っているものへ渡った
先は資格を失う）。

JSON の一覧はすべて `--limit`（既定 200）で**打ち切る**。打ち切ったときは `summary.listTruncated` が
true になり、`summary` の各欄の数は**打ち切る前**のままなので「欄の合計 == 総行数」は常にカウンタ側で
確かめる。

探索の深さにも打ち切りがある。外側の探索は「まだ歩いていないコードのノード」か「未登録の API グループ」が
無くなるまで繰り返し、実行したラウンド数は `summary.rounds`、その上限は `summary.maxRounds` に出る。
上限は既定で `6 + グラフ中の API グループ数 + コードのノード数 + 2`（`--max-rounds` で変えられる）。
上限に達して仕事が残ったときは `summary.unresolved` が true になり、
stderr に警告、Markdown に「探索が収束していません」の注意書きを出す。どちらも結果が完全でないことを
隠さない。

既知の限界として、Terraform の **module をまたぐアドレス衝突**はファイル付きの id
（`tf:<file>#<address>`）に退避して衝突を避けるが、module 展開はしない。1 つの module を複数ファイルに
分けて同じアドレスを打つと、そのアドレス同士の参照とエンドポイントは結ばれない（未解決の属性は
ノードの `metadata.unresolved` に出て、推測した値は作らない）。

`--expect` に期待する着地を書くと再現率・適合率が出る。**期待リストは自分の手で確認した列を
書き写したもの**で、正解データではなく「前回と変わったかを見る整合の測定」だと思っている。
だからリストを作った人間と同じ前提の誤りは消えない。そこを割り引いて読んでほしい。

| 実測したケース（2026-11-14 計測） | 期待 | 外部着地 | 的中 | 再現率 | 適合率 |
| --- | --- | --- | --- | --- | --- |
| demo: `src/Orders.Domain/Order.cs` | 12 | 11 | 11 | 0.917 | 1 |
| demo: `README.md`（グラフに無い変更） | 0 | 0 | 0 | 1 | 1 |
| demo: `infra/main.tf`（Terraform 全部） | 0 | 2 | 0 | 1 | 0 |
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
外部着地 0 件・コード 出口 6 件だけ出た（`README.md` を変えたケースの実測）。雑に広げるより
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
