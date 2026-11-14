---
name: csharp-dependency-graph
description: >-
  C# プロジェクトをフォルダ→csproj→csファイル→クラス→メソッドの順で段階的に展開できる
  依存関係グラフと、それをブラウザで操作する HTML を生成するスキル。Terraform で管理する
  Lambda / Step Functions / API Gateway / DynamoDB / RDS / SQS などの外部リソースもノードとして
  組み込め、静的解析では決まらない対応付けは annotations.json（LLM や人が後から追記）で紐づける。
  「C# の依存グラフを作って」「この csproj と Lambda を紐づけて」「グラフに情報を後付けしたい」
  のような依存関係の可視化・追記・検証を頼まれたときに使う。
metadata:
  version: "1.0.0"
---

# C# 依存関係グラフを作る

`folder` → `project`(.csproj) → `file`(.cs) → `type`(クラス) → `member`(メソッド・プロパティ)
という階層を、クリックで 1 段ずつ展開しながら見られるグラフを作る。依存エッジは
表示中のノードどうしに自動で持ち上げられるので、最上位では「フォルダ同士がどう依存しているか」、
最下位では「このメソッドが誰を呼んでいるか」を同じ画面で追える。

C# 本体は Roslyn による構文解析で機械的に拾い、C# の外側（AWS・DB・API など）は
Terraform の走査と、LLM が書く注釈（annotations.json）で組み込む。
出力は次の 2 つで、どちらも gitignore 済みの出力ディレクトリに置く。

- `graph.json` — 完全なグラフデータ（ノード・エッジ・メタデータ、機械が読む側）
- `graph.html` — 単一ファイルのビューア（データ埋め込み込み、ブラウザで開くだけで動く）

## いちばん短い手順

```sh
export DOTNET_ROOT=$HOME/.dotnet        # .NET 9 SDK が ~/.dotnet にある前提
SKILL=$HOME/.agents/skills/csharp-dependency-graph

node $SKILL/scripts/build.mjs \
  --root /path/to/repo \
  --out-dir out/graph \
  --name my-service
```

`out/graph/graph.html` をブラウザで開く。`graph.json` が依存関係グラフのファイル、
`graph.html` がそれ表示するための HTML。実行すると何が起きたかは次の順。

1. `analyzer/`（`cgd`）を `dotnet build` して C# を構文解析 → `graph.csharp.json`
2. `scan.mjs` がディレクトリ・`.csproj`・`.sln` を走査し、AWS/DB のヒント（`metadata.signals`）を出す → `graph.scan.json`
3. `.tf` が 1 つでもあれば `scan-terraform.mjs` が AWS リソースをノード化 → `graph.terraform.json`
4. `merge.mjs` が断片を統合して `graph.json` と `graph.data.js` を作る
5. `render.mjs` がビューアへデータを埋め込んで `graph.html` を出す

よくある実行時間の実測（M マシン・syntax-only）: elsa-core 6,754 ファイル（test / docs を除外）で C# 解析 3 秒、
全体 30 秒弱、`graph.json` 46MB / `graph.html` 20MB。

## 使い方を選ぶ

| やりたいこと | 手段 |
| --- | --- |
| 初めてグラフを作る | 上の `build.mjs` を 1 回 |
| 巨大リポジトリが遅い／見たい所だけ | `--exclude obj,bin,test,docs` を足す（部分再実行より速い） |
| 外部リソースや担当者を後から紐づける | [注釈を書く](#外部情報を後から紐づける) → `--annotation` を足して再生成 |
| ビューア上で暫定的に紐づけた分を定着させる | 画面の「注釈 JSON」でダウンロード → リポジトリの `annotations.json` に追記 |
| レビュー・設計で影響範囲や逆引きをする | `node $SKILL/scripts/query.mjs --graph out/graph/graph.json --from <id や名前>` → [reference/review-workflows.md](reference/review-workflows.md) |
| 意図どおりに動くか確かめる | `node $SKILL/scripts/verify.mjs --html out/graph/graph.html --shots out/shots` |
| ノード・エッジの型や ID が知りたい | [reference/schema.md](reference/schema.md) |

`--help` を各スクリプトに付けるとオプションの一覧が出る。個別の断片だけ作り直して
`merge.mjs` で組み直す運用（走査は速いので再生成より編集が速い）もできる。

## 静的解析が機械的に拾えるもの

`analyzer/` は MSBuild を実行せず構文だけ見るため、ビルドできないリポジトリ・
部分チェックアウト・生成コード混在でも動く（csharp-ls とは依存関係にない、独立実装）。

- ノード: `folder` / `solution` / `project` / `file` / `type` / `member` / `resource`
- エッジ: `contains`（階層）、`project-reference`（csproj 間）、`calls` `creates` `accesses`
  `references` `inherits` `implements` `attribute`（C# 内）、
  `invokes` `triggers` `deploys` `exposes` `exposed-by` `reads` `writes` `annotates`（外部世界）、
  `handler`（Terraform の handler 指定 → C# のメソッド）
- 部分クラスとオーバーロードは 1 ノードにまとめる（`metadata.overloads`、`metadata.alsoDeclaredIn`）
- 解決できなかった呼び出し名はノードの `metadata.unresolvedCalls` に残す
  （意味は構文だけからは決められないので、ここを LLM が注釈で埋める）
- **張れない同名候補は黙って張らず**、`.cs` ノードの `metadata.rejectedTypes` に型名として残す
  （型引数の数が宣言と違う／`using` も `global using` も無いので到達不能）。型バインドを付ける前の版と
  エッジ集合を突き合わせると elsa-core で **張らなくなった 2,076 本 / 新しく張った 514 本**、
  1,010 ファイル（1,260 名）に `rejectedTypes` が付く（張らなくなった筆頭は `Dictionary` 798 本）。
  ここが「注釈で正しく張るべき候補」のリストになる。上の 2 本数は集合の差分本数であって全件の正誤ではない ——
  張らなくなった側は 20 本を抜き出して原文と突き合わせ、誤バインドであることを確かめた。先に張っていた
  11 類（`Dictionary` / `ShellFeature` / `ServiceDescriptor` など）が復活していないことも全数で確かめた。
  再現形は `tests/fixtures/BindingRegression/` に固定している
- **メソッド・プロパティの戻り値型は「宣言元の `using`」で解決する**（呼び出し元がその名前空間を
  import している必要は C# にはない）。`r.Current.Id` のように戻り値を挟んだ多段アクセスで
  真ん中が切れるのを防ぐ。`var item = r.Make()` と `var` で一度受けたときも型表記が書かれていた
  ファイルの `using` を引き継ぐ（`foreach (var x in r.All())` と `var first = list[0]` も同じ）。
  実測 elsa-core で `IModule.Configure` 128 本、`ActivityExecutionContext.Get` 102 本 / `Set` 89 本、
  `IWorkflowDefinitionStore.FindAsync` 9 本、`BinaryContent.Name` / `.Stream` が張れている
- 型の単純名が複数の名前空間にあり、宣言元の名前空間と `using` でも判別できないときは、
  得点が並んだ候補に最大 2 本張って `detail` に `ambiguous` を残す。同一ファイル・名前空間直下
  という手掛かりで単独決定できることが多く、実測 elsa-core は 429 → 301 → **2 本**（表現内の型参照の
  張り分け `ambiguous: …` は 0 本、`param (ambiguous)` が 2 本）。残った 2 本は `Elsa.Api.Common` の
  `WebApplicationExtensions.CreateRateLimitingEndpoint` が引数に書く `Endpoint` で、正解はリポジトリ外の
  `Microsoft.AspNetCore.Http.Endpoint` なので**どちらも誤り**（`using Elsa.Workflows;` からの
  「内側名前空間 +1」という近似が生き残らせている）。得点 0 の曖昧さは張らないが、
  `ambiguous` を持つ縁は断定済みの縁と混ぜて読まない
- **ネストした構築済み汎用型（`Outer<T>.Items<U>`）のプロパティ / メソッドは外側の型でメンバを探す**。
  indexer（`p[0].Id`）は型引数の付いている `Items<U>` 側から要素型を解くので内側の型へ正しく張るが、
  `p.Deep.Id` は畳んだ `Outer` で `Deep` を探すため届かない（内側にしかない名前は未到達どまり。
  逆に `Outer` の側に同名メンバがあると誤って張る可能性がある）。`type:` ID が外側の型へ畳まれる
  問題と同じ根なので、内側の型を別ノードとして区別する話とあわせて再検討する（判断記録 47）
- 型がソースコードに書かれていない名前（`out var`、`is var x` / `case var x`、タプル分割、
  `foreach ((var a, b) in ...)`、LINQ の `join` の範囲変数、`dynamic`、外部型）は
  名前だけ塞いで未解決にする。外側の同名フィールドに化けるより未解決のほうが正しい
- **同じ入力なら同じバイト列**。2 周目は並列走なので、そのまま書き出すとエッジの順も、同じ edge ID に
  partial の別ファイルから届いた代表（行・detail）もスレッド順序に左右される。断片はエッジを ID の
  順序に整列して書き、代表は「行が若い順、同順なら detail の辞書順」で固定する。未決着の呼び出し名は
  順を持たない集合に集めて、出力時に並べてから上限を掛ける。elsa-core で断片 43 MB と `graph.json` 46 MB を
  2 回ずつ作り、`generatedAt` を除いたバイト列が一致することを実測した
  （`test-analyzer.mjs` の決定性検査は「ソートして比較」ではなくバイト比較で、partial の fixture を
  12 回連続で走らせている）

`.csproj` からは `targetFramework` `rootNamespace` `assemblyName` `packageReferences`
`projectReferences` を取り、`.cs` / `.csproj` のテキストから AWS/DB のヒント
（`aws-lambda-sdk` `lambda-handler` `api-gateway-proxy` `dynamodb` `s3` `sqs`
`step-functions` `relational-db` `ef-core` `redis` など）を `metadata.signals` に入れる。
**この signals が、LLM が注釈を書くときの入口**になる。

Terraform がある場合は `resource "aws_lambda_function" "orders_api"` のような宣言から
`tf:aws_lambda_function.orders_api` ノードを作り、`uri = aws_lambda_function.x.invoke_arn`
のような参照から `invokes` / `triggers` / `references` を張る。HCL は brace を数える
簡易パーサなので、モジュール展開や動的定義までは追わない（そこは注釈で埋める）。

`handler = "Assembly::NS.Type::Method"` の指定は `merge.mjs` が C# のメソッドノードへ解決して
`handler` エッジにする（`NS.Outer+Inner::Method` のネスト形式にも対応）。当たらないものは
張らずに警告へ回すので、Lambda から実装コードへ 1 ホップで降りられる。

## 外部情報を後から紐づける

グラフの面白さはここからで、`annotations.json` を `merge.mjs --annotation` に渡す。
ノードの追加・エッジの追加・既存ノードへのメタデータ付与の 3 種類が書ける。

```jsonc
{
  "schemaVersion": 1,
  "producer": "llm",
  "nodes": [
    { "id": "ext:rds/orders-analytics", "kind": "resource", "name": "orders-analytics",
      "parent": "folder:.", "metadata": { "resourceType": "aws-rds-postgres", "category": "rds" } }
  ],
  "edges": [
    { "source": "member:Orders.Infrastructure.DynamoDbOrderRepository.SaveAsync",
      "target": "tf:aws_dynamodb_table.orders", "kind": "writes",
      "provenance": "llm", "confidence": 0.9,
      "note": "DynamoDBContext.SaveAsync(order, \"orders\") のテーブル名が terraform のテーブル名と一致" }
  ],
  "metadata": [
    { "match": { "kind": "project", "path": "src/Orders.Api/Orders.Api.csproj" },
      "set": { "owner": "orders-team", "environment": "prod" } }
  ]
}
```

LLM が書くときの決まりごと（これをやらないとグラフが嘘をつく）:

1. **先に `graph.json` を読んでから書く。** 存在しないノード ID へのエッジは merge で
   警告を出して捨てられる。`sourceMatch`/`targetMatch`（`kind` + `path`/`name` の部分一致で
   探す）も使えるが、複数のノードに当たると警告して採用されない。曖昧なら ID で書く。
2. **根拠を `note` に必ず書く。** handler 文字列の一致、環境変数名、テーブル名、
   Terraform のアドレスなど、あとで他人が検証できる手がかり。
3. **`confidence` をつける。** コードに現れない運用知識（「毎週 Redshift へエクスポート」）は
   0.6 台にとどめ、`provenance` は `llm`、静的解析由来は `static`、Terraform 由来は `terraform`。
   ビューアではこの provenance をチップで絞り込める。
4. **csproj と Lambda の紐づけは handler 文字列から決める。** `.tf` の
   `handler = "Orders.Api::Orders.Api.Functions::CreateOrder"` は
   `アセンブリ名::型名::メソッド名`（アセンブリ名を省く 2 要素形もあり、ネスト型は `Outer+Inner`）。
   アセンブリ名は csproj の `<AssemblyName>` とだけ突き合わせる —— 宣言があるプロジェクトでは
   csproj のファイル名が一致しても張らない（リネーム前の名前が残った指定を検出するため）。
   `assemblyName` と `type:`/`member:` の ID を突き合わせれば機械的に決められるので、推測で書かない。
   突き合わせが外れたら張らずにビルド出力へ警告を出す（アセンブリ名が実装プロジェクトと違う／
   要素数が 2〜3 に収まらない／空要素がある／型やメソッドが実在しない）。警告が出たら
   **まず `handler` 文字列を実装プロジェクトのアセンブリ名へ直す**（プロジェクトをリネームしたときに
   旧名が残るのが主な原因）。意図的に別アセンブリの実装を指しているときだけ注釈で手動に張る。
   `data "aws_lambda_function"` の `handler` は既存 Lambda の読み取りなので結ばない。
5. **外部ストレージはノードを追加する。** RDS・Redshift・S3 バケットなど、このリポジトリに
   定義がないものは `ext:<種別>/<名前>` のノードを作り、`parent` は `folder:.` か
   該当ディレクトリの `folder:` を指定する。

書き換えた後は必ず再生成する（`build.mjs` に `--annotation path/to/annotations.json` を
追加するだけ。複数渡せる）。

### ブラウザから後付けする（人・LLM の両方向）

詳細パネルの下に 3 つのフォームがあり、いずれも `provenance: human` でブラウザに保存される。

1. **既存ノードと紐づける** — 相手ノードを検索して選択。`csproj → tf:aws_lambda_function.…`
   のように、すでにグラフにいるノードどうしを結べる
2. **外部リソースを後付けする** — `ext:<種別>/<名前>` を作って結ぶ（既存 ID と衝突したら結ぶだけ）
3. **メタデータを後付けする** — 選択中のノード（csproj でも `.cs` でも）に任意の key / value

「注釈 JSON」で書き出してリポジトリに置き、`--annotation` で再生成すると恒久化される。
書き出しには localStorage から復元した注釈も含まれるので、リロードしても失えない。

## 差分 → 影響範囲のレポート

「この変更で影響を受けるエンドポイントとテーブルは?」に答えるのが `report.mjs`。
`git diff --name-only` をそのまま渡せる（`--changed -`）。

```sh
git diff --name-only origin/main... | node $SKILL/scripts/report.mjs \
  --graph out/graph/graph.json --changed - --md out/impact.md --json out/impact.json
node $SKILL/scripts/report.mjs --graph out/graph/graph.json --api "POST /orders" --md out/orders.md
```

- **起点は変更ファイルの中身**。`.cs` はその中のメソッドへ自動で展開し、`.tf` はそのファイルが宣言して
  いるリソースを起点にする。グラフに無い変更ファイルは**起点にしない**（`fallbacks` に出すだけ。
  `--folder-start` は誤検出を膨らませるので理由があるときだけ）
- **6 つの枠に分けて出す**（`;` が枠の区切り。README の 6 枠と同じ組み方）:
  影響する外部リソース・影響を受ける入口; コード側の出口・入口;
  リポジトリ内の成果物（`.csproj`・`.cs`・フォルダ。ビルドし直しが必要な範囲）;
  同じ API を定義するノード; 同じコードを使う別の API（エンドポイントと定義ノードの内訳を出す）;
  定義上の関連（Terraform の `references`。値そのものは変わるとは限らないが、定義を書き換えたら効く範囲）。
  **どの行も必ずどれか 1 つの枠にしか入らない**（`summary.rows` と各枠の合計が一致する）。
  枠と Markdown の見出しと JSON の欄名の対応表は README にある。
  段数は定義の縁（`references`）だけ数え、動きの縁を越えたら数え直す。
- 起点がエンドポイントのときは、起点を定義する `resource` / `rest_api` / `integration` /
  `deployment` を「影響を受ける外部リソース」に数えない。
- **実行経路とみなす条件**: `method → invokes → integration`（v2 の `target`、v1 の三点組）または
  統合からメソッドへの直接参照・注釈があるときだけ実行経路とみなす。無いものは 定義上の関連 に残して
  対応未確定の警告を出す（「その API の下に method が 1 件しかない」での橋渡しは作らない）
- **兄弟ルートは 本命 の結果に影響せず、別欄に要約する**: 同じ Lambda / handler を共有しているだけの
  別エンドポイント（`route_key = "$default"` を含める）は起点の実行経路に数えない。既定の一覧は出さず
  **件数だけ**出す（一覧は `--list-siblings`、本数は `--limit`）。JSON 行には理由コードを立てる
  （`siblingReason` = `shared-code-endpoint` / `sibling-api-definition`、
  `unresolvedCorrReason` = `no-method-correspondence`）。各行には印刷した欄名と同じ `bucket` も立てる
  （`tier` は内部の昇格状態。欄の判定は `bucket` で見る）
- **Terraform の縁は向きに意味がない**ので無方向で閉じる（`--wiring-hops` 既定 3 段）。ただし
  `triggers` / `invokes` / `handler` は動きとして伝わるので本命、`references` だけ定義上に回す。
  `data` ソースはほとんどを参照するので既定では閉じない（`--include-data`）
- **段数欄は「表示経路の段数」**: 起点 0 段、表示経路の関係 1 本を 1 段。表の値と行の経路表示を
  一致させる。**最短とは限らない**（見出しの近くに常時表示する）。「本命」も「最短」を意味しない。
  経路全体の整合性を保つため、より長い代表経路を表示する場合があります。この段数は影響の強さや
  レビューの優先度を示しません（第 39 ラウンド裁定 `out/loop/r39-astra.md`）
- **逆向きの定義の縁が先に先着しても 本命 を潰さない**: 同一ノードへの到達は旗（本命 / 定義上 /
  `invokes` で届いた / 段数の残り）の包含関係で支配判定し、支配する旗で届いた経路は再展開する。
  先に着いた順だけで打ち切ると、`references` を逆向きに歩いた一歩が後からの `chain: true` を殺す
  （第 30 ラウンド指摘 D。実測で `demo-order` の 3 行が出力から消えていた）
- **探索の打ち切り**: 外側の探索は「まだ歩いていないコードのノード」か「未登録の API グループ」が
  無くなるまで続ける。実行したラウンド数は `summary.rounds`、上限（既定
  `6 + API グループ数 + コードのノード数 + 2`、`--max-rounds`）は `summary.maxRounds` に出る。
  上限に達して仕事が残ったら `summary.unresolved` が true になり、stderr と Markdown に警告を出す。
  一覧の `--limit` による打ち切りは `summary.listTruncated` に出る（どちらも隠さない）
- `--expect` に期待する着地一覧（`{"expect": [...], "direction": "out"}`）を渡すと再現率・適合率を
  出して JSON に書く。**数値を記録していないと「もっともらしく間違う」レポートになる**
- 注釈（`llm` / `human`）由来の行は「静的解析では決まらない対応付け」として件数を出す。
  粗い変更（Terraform 1 ファイルをまるごと等）で注釈由来の着地が増えて適合率が下がるので、
  `--provenance static,terraform` か `--from tf:...` で絞る

実測値は README の表にある（demo の `Order.cs` 変更で 再現率 0.917 / 適合率 1、
`infra/main.tf` 変更は 外部着地 2 件の適合率 0、実プロジェクト 1.000 / 1.000）。

## 検証する

### 静的解析の精度（ブラウザ不要）

```sh
node $SKILL/scripts/test-analyzer.mjs        # cgd がビルド済みなら即実行（96 項目）
```

`skill/tests/fixtures/` の C# を `cgd` にかけて、期待するエッジと「出してはいけない
エッジ」を照合する（fixture は `dotnet build` で通ることを確認して置いてある）。押さえるのは
ローカル変数・型を省略したラムダ引数・ローカル関数・兄弟ブロックの同名 var といった
「名前が型メンバを隠す」構文と、`var` / `foreach` の型推論（別メソッド由来の値、`new`、
`await` の内側、遅延推論したローカルを経由したコレクション）の回帰。
`fixtures/TypeResolution/` では型解決側の回帰を見る（型引数の数が合わない同名クラスに張らない、
`using` も `global using` も無い同名候補に張らない、逆に `using` / `global using` / 同一名前空間で
届くものは張る、拒否した型名が `.cs` ノードに残る）。
`fixtures/BindingRegression/` ではレビューで出た過剰除去の再発を見る（`Activity` と `Activity<T>` が
同居する基底型、戻り値型を宣言元で解決する多段アクセス、グローバル名前空間のネスト型、`var` で受けた
戻り値の先（プロパティ / `foreach` 要素 / indexer）、型引数の数が違う候補を飛ばして次へ進む探索）。
`fixtures/GenericChain/` では型引数つきコレクションの要素を**式の中でさらに辿ったとき**の解決を見る
（`foreach` を即座に書く場合と `var` を経由する場合、indexer 経由、`p.All()[0].Make().Id` の連鎖。
畳んだ型表記を使うと別名前空間の非ジェネリック同名型に化けるので、化ける側へ張っていないことも確かめる）。
`fixtures/TupleArg/` は型引数の数を構文どおり数えるかの回帰で、`Box<(int, string)>` のように
**タプルを型引数に受けた連鎖**（プロパティ / 呼び出し / タプルキーの indexer / `foreach` 要素 /
`var` 経由 / 2 引数の `Pair<(int, int), string>` / フィールド宣言）が要素型のメンバーへ張ることを見る。
型引数の数を `<` と `,` だけで数えるとタプル内のカンマを区切りと数え、連鎖ごと消える。
`fixtures/TrickyType/` は型表記の文字列を数えるときの 2 つの取り違えの回帰で、コメントを構文上の括弧として数えてしまう誤り（`Pair<int /* index [start */, string>` の `[`）と、型引数が付いていない左側の name セグメントを拾う誤り（`Outer<Wrong>.Items<Correct>` の indexer が `Wrong.Id` へ断定したエッジを張る）に効く。コメント付きの `Dictionary` 宣言から値型が取れること、化ける側へ一切辿らないことも同じ fixture で確かめる。
`fixtures/NestedArity/` は型引数の数で候補を絞るときのセグメントの回帰で、`Outer<int, string>.Inner<Item>` のように**解決するのが外側・型引数を拾うのが内側**という形で、内側型を持たない別名前空間の `App.Outer<A>` を誤って通さないことを見る。`fixtures/LineEndComment/` は行コメントの終端の回帰で、CR 単独や NEL（U+0085）の後もコメント扱いを続けて型引数を消していないか（LF は対照）。
`fixtures/PartialOrder/` は出力の決定性で、partial 型の別ファイルにある同名オーバーロードが同じ edge ID に
畳まれたとき、断片のバイト列が 12 回連続で一致することと、代表の行が行の若い側で固定されることを見る。
demo と `BindingRegression/` でも同じ入力を 2 回走らせて、`rejectedTypes` を含む出力が揺れないことを確かめる。

### 照会（逆引き・影響範囲）のテスト

```sh
node $SKILL/scripts/test-query.mjs           # fixtures/query/graph.json を使う（.NET 不要、17 項目）
node $SKILL/scripts/test-merge.mjs           # Lambda handler の解決規則（.NET 必要、12 項目）
node $SKILL/scripts/test-terraform.mjs       # API Gateway のパス組み立てと HTTP API (v2) の `target`（46 項目、.NET 不要）
node $SKILL/scripts/test-report.mjs          # 差分 → 影響範囲レポート（85 項目、.NET 必要）
```

`test-merge.mjs` は `fixtures/HandlerLambda/`（`AssemblyName` を置いた csproj と `main.tf`）を
`build.mjs` まで通し、張る 5 とおり（一致／アセンブリ名省略／`Outer+Inner`／`Outer+Middle+Inner`／別型）と
張らない 5 とおり（アセンブリ名違い／アセンブリ名を宣言している csproj のファイル名／空要素を含む形／
4 要素以上／型が実在しない）を照合する。警告文はビルド出力に出るので、テストはそちらを読む。

`test-report.mjs` は `fixtures/ReportImpact/`（C# と `infra/main.tf` が同じリポジトリにある形）を
`build.mjs` まで通し、変更ファイル起点の展開、兄弟ファイルの巻き込み回避、Terraform の
`references` を本命に混ぜないこと、`--api` の解決、`--include-data`、グラフに無い変更を起点にしないこと、
`--changed -`、Markdown と JSON の件数の一致を照合する。加えて **どの行もどれか 1 つの枠にしか入らない**
（欄の合計 == `summary.rows`）、根拠経路に `null` が混ざらない、IAM ロールだけを共有する別 Lambda を
昇格させない、`project:` 起点がパスの所属で展開される、`--provenance static` が closure にも効く、
呼びに出したエンドポイント（`invokes`）を兄弟にしない、向き（影響する先 / 受ける入口）が
縁の矢印と食い違わない、逆向きの定義の縁が先着しても 本命 が潰れない、`route_key = "$default"` を
起点にすると委譲先は本命で別ルートは定義上になる、兄弟ルートは既定で件数だけ出して `--list-siblings`
で `--limit` 本まで並べる、IAM ポリシー起点が定義の縁だけで届いたコードを種にせず 15 行のまま、
コード起点でも「統合がメソッドを指している一歩」を越えた先が本命、を確かめる。

`test-terraform.mjs` は `fixtures/TerraformApi/`（C# を置かない Terraform だけの fixture）と
`fixtures/V2HttpApi/`（HTTP API v2 の fixture。`route` の `target` と `api_id` を通す形と崩れる形を両方置く）に
`scan-terraform.mjs` だけを走らせ、`path_part` と `parent_id` から `/orders/{id}` の形になるか、
method に `POST /orders` の表示名 `endpoint` が付くか、`stage_name` と v2 の `route_key` を取るか、
**パスが決まらない method に推測で `endpoint` を張らないか**、`parent_id` が循環しても停止しないか、
v2 では `target` の既知の形だけを `invokes` 縁にして、読めない `target` と `api_id` を
`metadata.unresolved` に出すか、`integration` の宣言順を入れ替えても同じ縁になるかを照合する。
特に `parent_id = var.x` / `module.x.parent_id` / `each.value` / 補間だけ / `route_key = var.x` /
v2 の `$default` のように**未解決の式からエンドポイントを作らない**ことを fixture で固定している
（実在しない `POST /orders` が検索に出ると、レビューの起点として嘘になる）。「`${aws_api_gateway_rest_api.x.root_resource_id}`」のように
**単一の参照を補間しただけ**の書き方は解決する（実プロジェクトの大半がこの形）

### ブラウザ実操作

```sh
node $SKILL/scripts/verify.mjs --html out/graph/graph.html --shots out/shots
```

ヘッドレス Chromium で実際にクリックし、25 項目を確かめる。検査対象は `graph.json`
から自動選択するので、どのプロジェクトにもそのまま効く（Terraform ノードが無い場合は
該当チェックを省略して 23 項目）。主な確認項目:

- ルート 1 段だけの初期表示／クリックしたフォルダだけの子展開
- `.cs` クリック → 型 → メンバ（メソッド）の段階展開、ロールアップ値
- メソッド検索 → グラフ上で選択 → 詳細パネルにシグネチャ
- ⇧クリックの周辺 N ホップ、`#expand=/#select=` ディープリンク
- 注釈の 3 フォーム（既存ノード間リンク / 外部リソース後付け / メタデータ後付け）が
  localStorage に残り、**リロード後も再現され、`注釈 JSON` 書き出しに `provenance: human`
  で乗る**（→ `merge.mjs --annotation` で恒久化できる）。同じノードに 2 回後付けした
  メタデータは書き出しでマージされる
- UI で作った新しい edge kind がチップに登録され、表示フィルタを通過して描画される
  （900 本上限で絞られる場合はその旨を検査が許容する）
- コンソールエラーゼロ

`--shots` にスクリーンショット（`01-root.png` ほか）が出るので、目でも確かめる。
`--query <メソッド名>` で検索対象をそのプロジェクトらしい名前に変える。
5 万ノード級でも前処理含め 20 秒程度。

ブラウザ起動に失敗する環境（playwright の期待ビルドが無い、サンドボックスで起動制限）では:

```sh
node $SKILL/scripts/verify.mjs --html out/graph/graph.html --browser "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
```

`--browser` / 環境変数 `CSDG_BROWSER` 指定 → playwright 既定 → キャッシュ済みビルド
（macOS / Linux）→ システムの Chrome の順に試し、全失敗時は試行理由を並べて落ちる。

## よくある落とし穴

- **`You must install or update .NET`** → `DOTNET_ROOT` が未設定。`export DOTNET_ROOT=$HOME/.dotnet`
  （システム側の dotnet が SDK 8 しかない環境では `~/.dotnet` の SDK 9 を使う）。
- **`graph.html` が重い** → 60MB を超えると merge が警告を出す。`--exclude` で対象を絞るか、
  `graph.json` を別配付して `--data` で薄い断片から HTML だけ作る。
- **フォルダの型数が 0** → そのフォルダ直下に `.cs` がないだけ（型はファイルの子、
  ファイルはフォルダの子）。ロールアップはフォルダ→ファイル→型→メンバーまで再帰する。
- **検索で 200 件超** → 先頭 200 件だけ表示。kind フィルタか語を絞る。
- **日本語の字形** → このリポジトリの日本語は日本表記のみ。
  `python3 ~/.agents/scripts/check-cn-glyphs.py <ファイル>` で点検する。

## 参照

- [reference/schema.md](reference/schema.md) — `graph.json` / ペイロード / ID 規則 / 注釈スキーマ
- [examples/annotations.orders-api.json](examples/annotations.orders-api.json) — Lambda + Terraform プロジェクトに
  LLM が注釈を書いた実例（csproj→Lambda、メソッド→API Gateway / DynamoDB / SQS、外部 RDS ノード追加）
- [examples/annotations.storage.json](examples/annotations.storage.json) — RDS を**テーブル → カラム**まで段階展開できる
  形で後付けした実例。`--annotation` は繰り返し指定できるので、このように注釈を単位ごとに分けて足せる
- ビューアの操作: クリック=展開 / ⇧クリック=出力エッジをたどる / ⌥⇧クリック=入力エッジ /
  ホイール=拡大縮小 / ドラッグ=スクロール / 「表示を共有」=現在の展開を URL にコピー
  （`#expand=<id,id>&select=<id>` のディープリンクで同じ画面を開ける）
