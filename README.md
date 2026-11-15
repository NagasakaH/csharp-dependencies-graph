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
- いま進めているゴールと完了条件（条件の追加・緩和はここを書き換える）: [GOAL.md](GOAL.md)

## 試した対象と実測

| 対象 | ノード / エッジ | 内容 |
| --- | --- | --- |
| [elsa-core](https://github.com/elsa-workflows/elsa-core) | 51,179 / 53,521（C# 解析 3 秒、HTML 20MB） | 336 csproj、6,754 個の `.cs`（ファイル計 7,207）、8,223 型、32,572 メンバ、calls 14,607 / accesses 13,788 / references 15,633、898 ファイルが AWS/DB シグナル、1,010 ファイル（1,260 名）が「張れなかった同名候補」の記録あり |
| `demo/orders-api-lambda` | 74 / 66（静的 27 / Terraform 27 / 注釈 12） | C# Lambda 3 csproj + Terraform 15 リソース + Terraform の handler 解決 2 + 注釈 12 エッジ（RDS をテーブル → カラムまで `parent` で入れ子にした例を含む） |

レポートの性能基準は **1 レポートあたり固定した変更前版の 1.20 倍以内**（旧→新 / 新→旧 を交互に
最低 5 組、組ごとの倍率の中央値で判定）**と 最大 RSS 800 MB（絶対上限）** で、**1.0 秒はゲートではなく
UX 目標**、最大応答時間はゲートにしない。4 とおりの入力の倍率・最大 RSS・測定環境は
[skill/SKILL.md](skill/SKILL.md) の「レポートの性能基準」に実測どおり置いてある
（第 50 ラウンドの実測で 4 とおりすべて適合、重い `elsa-folder` でも倍率中央値 1.14 / 最大 RSS 639.6 MB。
かつて 1.67 で超過したときは、結果を 1 バイトも変えない軽量化で収束させ、時間で切り捨てる対応は採っていない）。

検証は 2 系統あり、どちらも対象プロジェクト非依存で動く。

```sh
node skill/scripts/test-analyzer.mjs                          # 静的解析の精度（96 項目、ブラウザ不要）
node skill/scripts/test-report.mjs                            # 影響範囲レポート（130 項目）
node skill/scripts/test-query.mjs                             # 逆引き・影響範囲の照会（28 項目、.NET 不要）
node skill/scripts/test-merge.mjs                             # Lambda handler の解決規則（12 項目、.NET 必要）
node skill/scripts/test-terraform.mjs                         # API Gateway のパス組み立てと HTTP API (v2) の `target`（46 項目、.NET 不要）
node skill/scripts/verify.mjs --html out/graph/graph.html --shots out/shots   # ブラウザ実操作（26 項目）
```

`verify.mjs` は検査対象を `graph.json` から自動選択するので、どのプロジェクトにもそのまま使える
（今の実測: demo 26/26、elsa-core 24/24。Terraform ノードが無い対象は該当 2 項目を省略する）。
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

# この cs ファイルが実縁で繋がっているファイルは何本か（import / 参照 / 呼び出し単位）
node skill/scripts/query.mjs --graph out/demo/graph.json \
  --from file:src/Orders.Domain/Order.cs --dir both --via-parent --hops 3 --group-by file
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

Markdown 先頭の**集計行**だけ「同じ API を定義するノード」を**「同じ API の定義」**と短縮して書く
（一覧の見出しは上の表の `### …` のとおり、JSON のキーと行の `bucket` は `sameApi` /
`siblingEndpoints` / `wiring` の英字のままで、指している欄は同じ）。ターミナルの 1 行集計はさらに
短く「定義上」「別の API」と書く。

**実行経路とみなす条件**（第 29 ラウンドの裁定）: `method → invokes → integration`（v2 の `target`、
v1 の三点組）または統合からメソッドへの直接参照・注釈があるときだけ実行経路とみなす。無いものは
定義上の関連 に残して対応未確定の警告を出す（「その API の下に method が 1 件しかない」で橋を掛けたり、
同じ API の定義を辿っただけで実装側を昇格したりしない）。

**兄弟ルートは 本命 の結果に影響せず、別欄に要約する**（第 29 / 30 ラウンド）。同じ Lambda・handler を
共有しているだけの別エンドポイント（`route_key = "$default"` を含む）は起点の実行経路に数えない。
既定の表示は **件数だけ**で、一覧は `--list-siblings` を立てたときだけ `--limit` 本並べる
（実測: 40 API × 20 route のグラフで 799 本が画面を埋めていた）。JSON の各行には印刷した欄名と同じ
`bucket` と理由コード（`siblingReason` = `shared-code-endpoint` / `sibling-api-definition`、
`unresolvedCorrReason` = `no-method-correspondence`）を立てる。`tier` は内部の昇格状態なので、
欄の判定は `bucket` を見る。

**向き（JSON の `direction`。値域は `in` / `out` / `none`）は、表示に確定した経路を根からフォールドして
決める**。探索が別経路から寄せた値は読まない（第 45 / 46 ラウンド裁定 `out/review-astra45.log`、
`out/review-astra46.log`）。起点の 向き は `none` で、表示経路の一歩ごとに次を適用する:

1. **動きの縁**（`triggers` / `invokes` / `handler` / `exposed-by`）で届いた一歩 → **矢印の先が下流**
   （`exposed-by` だけ逆向きで、コード側が下流）。だから `Step Functions → invokes → この Lambda` は
   影響を受ける入口（この Lambda を呼びにくる側）として出る。ただし `handler` / `exposed-by` は
   **実装の対応**を示す縁で呼び出し元を示さないので、起点が API エンドポイントのときはその対応縁で
   繋がる側（実装を載せた Lambda など）も 影響する先 のまま（ここを矢印だけで判断すると、起点自身の
   実装 Lambda が「呼びにくる側」に並んだ。実測: demo の `--api "POST /orders"`）
2. **向きを持つ縁**（静的解析と注釈が結んだ `calls` / `writes` / `accesses` / `creates` /
   `project-reference` / `deploys` など）→ **その縁の矢印で決める**。「実装側に入った」旗より
   こちらを優先する（実測: `demo-api` の `Orders.Api.csproj` は `project →deploys→ Lambda` を
   Lambda 側から辿った行なので 影響を受けるリポジトリ内の成果物 が正）
3. **無方向の定義縁**（Terraform の定義閉包で向きを意味として採用しない縁）→ **直前の 向き をそのまま
   継ぐ**。無方向の一歩は最初も途中も同じ規則で、端点から 向き を作らない

1 本でも **1 か 2 の縁**を越えるまで `none` のまま残る（動きの縁でも有向縁でも 向き が決まる）。`none` の意味は「**この表示経路に 向き を決める
関係が無い**」であって、「そのノードに他の有向関係が存在しない」意味でもない（有向縁を越えた先で
`in` / `out` を継承した行もある）。`none` の行は `tier` を保ったまま 定義上の関連 / 同じ API を定義する
ノード / 同じコードを使う別の API の中立欄で受け、Markdown の 向き 列は「—」。方向を持つ欄
（外部・コードの入口・成果物の 先 / 受）に並べると `in` / `out` の意味をでっち上げることになるため。
ただし「同じコードを使う別の API」の一覧は Markdown では 向き 列を出さないので、そこは JSON の
`siblingEndpoints` で見る。件数は `summary.directionless`（うち本命は `summary.directionlessPrimary`）に
出す（実測: 保存済み 18 レポート 441 行中 28 行 = 同じ API を定義するノード 17 / 定義上の関連 9 /
同じコードを使う別の API 2、うち本命 2）。`--expect` の `direction` は `in` / `out` / `none` / `both` を
受け、既定の `both` は 向き で絞らないので `none` の着地を取りこぼさない。`none` を指定したときの
対象は none の行のうち **本命（`tier === "primary"`）で、「同じ API を定義するノード」「同じコードを
使う別の API」に回らないもの**（定義上の関連に回った本命は数える）で、再現率・適合率の分母は
外部リソースだけ（保存済み 18 レポートでは該当 0 行。`none` の 本命 2 行はどちらも「同じ API を定義する
ノード」に並ぶ）。契約の版はレポート出力に `schemaVersion` が無いままなので、**旧版の見分け方は
`summary.directionless` キーの有無、未知の `direction` は中立扱い**（詳細は
[skill/reference/schema.md](skill/reference/schema.md) の「レポート出力」）。

**動きの根拠（`movementEvidence`）も同じ表示経路から**決め、表示経路の最終一歩が動きの縁のときだけ
その縁を立てる（定義の縁なら `null`）。`movementEvidence === null` と `direction === "none"` は
同義ではない。`correspondence` は表示経路内の注釈縁の論理和、`switches`（向き変え回数）は同じ
表示経路を端点基準で数え直した値。

各行は根拠経路 `path` と、その経路がどこから始まっているかの `pathRoot` を持つ。`start` は起点まで
辿れた行、`second-stage` は根拠経路が循環しそうな所でそこを新しい出発点として切った行で、
`broken`（`via` が宙を指す）は出てはいけない。`summary.pathsByRoot` と `summary.startIds`
で外から確かめられる。行の `reachedByInvokes` は「`invokes` の縁を矢印どおりに辿って呼ばれる側へ
着いた」ことを示す旗で、同じ実装を共有する兄弟エンドポイントと、実際に呼び出した先を区別に使う。

「IAM ロールだけを共有する別の Lambda」経由で、その Lambda 専用の integration や handler まで本命に
伝播することはない。`references` をまたいで伝播できる資格は **起点 / 本命として届いたノード / 起点と同じ API を定義する
ノード**だけを持ち、しかも**参照している側へ進む一歩**にだけ受け継がれる（自分が使っているものへ渡った
先は資格を失う）。

JSON の一覧は `--limit`（既定 200）で**打ち切る**。打ち切ったときは `summary.listTruncated` が
true になり、`summary` の各欄の数は**打ち切る前**のままなので「欄の合計 == 総行数」は常にカウンタ側で
確かめる。**例外が 2 つある**（注記が「--json 参照」と指すのはこの 2 つの意味。第 50 ラウンド実測）:

- `summary.startEndpoints` と `summary.reachedEndpoints` は `--limit` で切らず**全件**入る
- `summary.startIds` は 50 件で打ち切り、切れたら `summary.startIdsTruncated` が立つ

ターミナルに出す外部リソースの一覧も `--limit` に従い、さらに見やすさのため**12 件**で切る。
各一覧の注記は冒頭に `表示 M / N 件` を置き、そのあとに「他の出力に出している分」と
「`--limit` で打たれて**どの出力にも入っていない分**」を分けて出し、12 件で打ったときだけ
それを告げる（黙って 13 件目を落とさない）。「Markdown と `--json` に出しています」は
**`--md` / `--json` を付けた実行だけ**の真実なので、付けていない実行では
「`--md` / `--json` を指定するとそこに入ります（いまはターミナルだけ）」と書く
（第 50 ラウンド双人レビュー。前の版はファイルを 1 つも出していない実行で同じ嘘を言っていた）。
「（いまはターミナルだけ）」も同じ理屈で、**どちらの旗も付いていない実行だけ**が書ける
（前の版は `--md` だけの実行が Markdown の本文でそれを言っていた。第 50 ラウンド Codex P2 / agy）。
同じく「どの出力にも入っていない」注記も、その実行が**実際に書いたファイルを名指ししない**
（存在しない出力を指さない）
`--limit` は Markdown・JSON・ターミナルのすべてに掛かるので、`--limit` で打った分が
`--json` の中から見つかることはない（第 48 ラウンド双人レビューの実測）

表示対象が 0 件という結果は無いので、`--limit 0` の一覧は「該当なし」「（なし）」にせず
「`--limit` で全部打ち切りました」と書く（第 50 ラウンド双人レビュー。「該当なし」は
直後の「（表示 0 / 3 件 …）」と矛盾していた）

同じ理屈で、**JSON の欄を指す案内も `--json` を出した実行だけが断定できる**。`--json` を
付けていない実行では「`--json` を指定すると `summary.startEndpoints` … に全件入ります」
「`--json` を付けると出る `siblingEndpoints` は」と言い方を変える（第 50 ラウンド。
一覧の注記を直したあと、定義ノードの注記と Markdown の見出しに「`--json` に入る」言い方が
残っていたので検査にした）

同じコードを使う別の API の一覧は、**ルートを先頭・そのうしろに定義ノード**という 1 本の順で
`--limit` を切る（JSON の `siblingEndpoints`・Markdown・ターミナルが同じ順を向く）。
一覧に出すのはルートだけなので、定義ノードは「`--json` に入った分 / 打たれた分」だけを別枠で告げる
（第 50 ラウンド agy 指摘。前の版はルートを混ぜて切っていたため、一覧に出たルートが
`--json` に入らないことがあった）。API エンドポイント欄も Markdown とターミナルで
**同じ並び・同じ本数**で切る（以前は Markdown 3 件・ターミナル 2 件と割れた）

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

| 実測したケース（2026-11-15 計測） | 期待 | 外部着地 | 的中 | 再現率 | 適合率 |
| --- | --- | --- | --- | --- | --- |
| demo: `src/Orders.Domain/Order.cs` | 12 | 12 | 11 | 0.917 | 0.917 |
| demo: `README.md`（グラフに無い変更） | 0 | 0 | 0 | 1 | 1 |
| demo: `infra/main.tf`（Terraform 全部） | 0 | 2 | 0 | 1 | 0 |
| 実プロジェクト: `--api "POST /messages"` | 1 | 1 | 1 | 1 | 1 |
| 実プロジェクト: `cs/ExampleLambdaApi/Handler.cs` | 2 | 2 | 2 | 1 | 1 |

demo の 1 件の「もれ」は届いていないのではなく**枠の分け方**の結果。
`tf:aws_api_gateway_deployment.live` まで辿れているが、縁が `references` なので定義上の関連に落ちる
（JSON の `score.wiringOnly` が 1 で、それがその 1 件）。着地そのものは出ている。
適合率 1 でないのは余分な着地 1 件。`ext:rds/orders-analytics` が、Lambda `notify` を経て届いた
DynamoDB テーブル `orders` から注釈由来の `reads` 縁（注記「DynamoDB → Redshift への週次エクスポート」）を
辿って着地した（`score.extraExternal` がその 1 件で、期待リストには入れていない）。

実プロジェクトは [Pondidum/Terraform-Demos](https://github.com/Pondidum/Terraform-Demos) の
`api-lambda`（C# と Terraform が同じリポジトリにある最小の実例）で、**注釈を 1 件も使わず**に
`POST /messages` → Lambda → `Handler.Handle` まで Terraform だけ出ている。
`infra/main.tf` をまとめて変えたケースが適合率 0 になるのは、Terraform 経由で注釈由来の
外部リソース（`ext:rds/…`）まで届くため。粒度の荒い変更は `--provenance static,terraform` で
注釈由来を切るか、`--from tf:aws_lambda_function.…` と 1 リソースに絞る。
`--provenance` は Terraform の定義単位を結ぶ段階にも効くので、`static` だけなら API 起点でも着地 0 件になる。

変更ファイルがグラフに無いときの `--folder-start` は、同じデモで **起点 1 件 → 49 件**に膨らんで
外部着地 0 件・コード 出口 4 件（入口 0 件）・成果物 先 1 件・受 2 件だけ出た（`README.md` を変えたケースの実測）。雑に広げるより
「そのファイルはグラフに無い」と出したほうがマシなので、既定はオフのままにしている。

レシピ集（結合ハブの棚卸し、呼び出し集中の blast radius、注釈だけの依存のレビュー、
誤読しないための前提）は [skill/reference/review-workflows.md](skill/reference/review-workflows.md)。

## 構成

```
skill/
  analyzer/            Roslyn 構文解析（net9.0, cgd）。ビルドは build.mjs がやる
  scripts/             build / scan / scan-terraform / merge / render / query / report / verify
                       + test-analyzer / test-query / test-merge / test-terraform / test-report（回帰テスト）
  scripts/tools/       測定と再生成の道具（regen-audit / count-kinds / make-changed-list /
                       make-v2-graph / perf-measure.py / perf-run.sh / paired-gate.sh /
                       check-battery-inputs.py）
  scripts/tools/battery/  v1 の出力契約を突き合わせる照合器・順列と入れ替えの検査器と、
                       それが入力に固定する 18 レポート（開発側の回帰バッテリー）。
                       入力の所在と終了コードを揃える `_inputs.py`、`baseline-v1` が記録する
                       入力グラフの実体 `graphs/` もここ
  tests/fixtures/      静的解析と照会のテスト用データ（C# と graph.json）
  viewer/template.html 単一ファイルのビューア（データ埋め込み）
  reference/schema.md  データ契約
  reference/review-workflows.md  レビュー・設計で使うレシピ
  examples/            LLM 注釈の実例
demo/orders-api-lambda Lambda + Terraform のデモ対象
out/                   生成物（gitignore 済み）
```

### 回帰バッテリーの置き場所と終了コード（保守向け）

`skill/scripts/tools/battery/` の検査器は、次の 5 つを約束している（第 48 〜 55 ラウンドの
双人レビューで実際に出た事故の形。`out/loop/protocol.md` §4-3 が実行手順）。

- **入力を目の前の `out/tmp-*` から読まない。** `out/tmp-*` はディスク掃除の対象で、消えた日に
  検査が「該当 0 件」で終了 0 になる。追跡下に必要な実体（`baseline-v1` と `graphs/`）を置き、
  `out/` に残すものは作り直しが決まっているもの（`out/demo/graph.json`、`out/perf-inputs/` など）だけにする
- **実行前に所在と中身を点検する。** `python3 skill/scripts/tools/check-battery-inputs.py` が
  道具・固定入力（空 = 0 バイトも不良）・v1 基準 18 条件・追跡下の fixture 19 本・
  検査が足す実グラフの所在と、`input-fingerprints.json` に登録した**入力の指紋 52 件**
  （`out/` 固定入力の構造指紋 + 全入力の SHA-256）の差し替えなしを確かめる（第 52 ラウンド両名 P2
  で件数要求と指紋検査を足し、第 53 ラウンド agy P2 で「無い物と空の一覧を出してから指紋を見る」順に
  直し、第 55 ラウンド Codex 指摘 1 で**中身の指紋**を足した。fixture の `edges` を全部空にする、
  起点にならないノードを 1 つ rename する、のような「構造は同じで中身が違う」差し替えを止める）
- **何を走らせるかを追跡下の一覧で決める。** 回帰検査の起動条件は
  `skill/scripts/tools/battery/required-checks.json`（fixture 19 本 / 219 条件）が正本で、
  `_inputs.launch_conditions()` が組み上げた条件と**中身（`case` / `graph` / `kind` / `args`）が
  一致しない日は測る前に終了 1**。集合だけ・id だけの比較は、中身を書き換えて id を据え置く日を
  通す（第 54 ラウンド Codex 指摘 2）
- **測った件数でも見張る。** 同じ入力で**測る範囲だけが縮んだ日**を入力指紋は止められないので、
  走査した行数・突き合わせた親子数・無方向の行の内訳・`向き` の比較内訳を条件別に
  `required-checks.json` の `expectations` へ追跡下で置き、測ったあとに突き合わせて違えば終了 1
  （`python3 skill/scripts/tools/battery/README.md` の 5 本の測定コマンドで作り直す）
- **無いものと失敗を成功にしない。** 入力が無い・子が失敗したら測る前に終了 1。JSON を書かない
  実行・壊れた JSON・欄の無い JSON・前回の出力をそのまま読む実行は終了 1。比較する行が 0 件なのに
  「違反 0」「1 通りに一致」と出る検査も終了 1（正当な 0 行レポートまで違反にはしない）。
  そして**その検査が実際に落ちることを確かめる道具**が
  `python3 skill/scripts/tools/battery/test-contract.py`（負控制 69 件・正控制 8 件。
  検出できなかった失敗が 1 件でもあれば終了 1）
- **見張り番は 1 個ずつ消せる。** 検査器の合否判定はすべて名前を持っていて、
  `CGD_GUARD_OFF=name,name` で任意の名前で見張り番を消せる。`test-contract.py` の負控制は
  **素の実行と、その見張り番を消した実行の 2 度**を走らせ、後者にその案内が出ないことを
  確かめる（別の一の見で落ちるだけの空振りを測らないため。名前のスペル違いもその場で失敗）。見張り番を消すと後が読めない実行系の制御は、**別の手前の文面**を `fallback` に宣言させて、それ以外の所で落ちたら失敗にする（第 56 ラウンド agy P2-3）
