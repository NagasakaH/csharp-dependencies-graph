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
| この cs ファイルが実縁で繋がっているファイルは何本か | `query.mjs --from file:<パス> --dir both --via-parent --hops 3 --group-by file` |
| 繋がった関係を csproj 単位で集計したい | `--group-by project` は選べない（実グラフでは `.cs` ファイルノードの `parent` が `folder` で、`project` が関わる縁も `.csproj` の `contains` / csproj 同士の `project-reference` / `deploys` だけ。コードから所属 csproj はたどれない）。`--from project:<csproj> --via-parent` で csproj 起点に切り替える |
| 意図どおりに動くか確かめる | `node $SKILL/scripts/verify.mjs --html out/graph/graph.html --shots out/shots` |
| ノード・エッジの型や ID が知りたい | [reference/schema.md](reference/schema.md) |

`--help` を各スクリプトに付けるとオプションの一覧が出る。個別の断片だけ作り直して
`merge.mjs` で組み直す運用（走査は速いので再生成より編集が速い）もできる。

`query.mjs` の `--via-parent` には罠がある。実縁（`calls` / `references` など）は型・メンバー・
リソースの側にしか付いていないので、`file:` / `project:` / `folder:` を起点にした照会は
`--via-parent` を付けないと階層の 1 段で止まり到達 0 件になる（そのときだけ stderr に案内を出す）。
逆に `--via-parent` を付けると到達範囲が階層ぶん膨らむので、`--dir in` の逆引きは型・メンバーを
起点にするほうが速い（実測と手順は [reference/review-workflows.md](reference/review-workflows.md) の 5-2）。

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
- **6 つの枠に分けて出す**（`;` が枠の区切り。docs/review-usage.md の 6 つの枠と同じ組み方）:
  影響する外部リソース・影響を受ける入口; コード側の出口・入口;
  リポジトリ内の成果物（`.csproj`・`.cs`・フォルダ。ビルドし直しが必要な範囲）;
  同じ API を定義するノード; 同じコードを使う別の API（エンドポイントと定義ノードの内訳を出す）;
  定義上の関連（Terraform の `references`。値そのものは変わるとは限らないが、定義を書き換えたら効く範囲）。
  **どの行も必ずどれか 1 つの枠にしか入らない**（`summary.rows` と各枠の合計が一致する）。
  枠と Markdown の見出しと JSON の欄名の対応表は `docs/review-usage.md` にある。
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
- **Terraform の定義閉包は無方向で閉じる**（`--wiring-hops` 既定 3 段）。到達対象を両方向に探すことと、
  表示上その矢印に意味を持たせないことは別で、`triggers` / `invokes` / `handler` は動きとして伝わるので
  本命、`references` だけ定義上に回す。
  `data` ソースはほとんどを参照するので既定では閉じない（`--include-data`）
- **向き（`direction`。値域 `in` / `out` / `none`）は表示に確定した経路を根からフォールドして決める**
  （第 45 / 46 ラウンド裁定）。動きの縁 → その縁の矢印、向きを持つ縁（静的解析・注釈）→ その縁の矢印、
  無方向の定義縁 → 直前の 向き を継承、の順で、起点は `none`。`none` は「この表示経路に 向き を決める
  関係が無い」意味で「そのノードに他の有向関係が無い」意味ではない。`none` の行は `tier` を保ったまま
  中立欄（定義上の関連 / 同じ API / 兄弟）で受け、Markdown の 向き 列は「—」、件数は
  `summary.directionless` / `summary.directionlessPrimary` に出す。**方向別の一覧で黙って行を消さない**。
  詳細は `docs/review-usage.md`「縁の向き」の項
- **段数欄は「表示経路の段数」**: 起点 0 段、表示経路の関係 1 本を 1 段。表の値と行の経路表示を
  一致させる。**最短とは限らない**（見出しの近くに常時表示する）。「本命」も「最短」を意味しない。
  経路全体の整合性を保つため、より長い代表経路を表示する場合があります。この段数は影響の強さや
  レビューの優先度を示しません（第 39 ラウンド裁定 `out/loop/r39-astra.md`）
- **向き変え回数は「表示した根拠経路」の属性**: 表示経路で進行方向が変わる一歩の回数を出す
  （注釈＝対応付けの縁を渡る向き替えは数えない）。行の並びは 向き変え回数 → 段数 → ノード id。
  経路は候補から選び直して組み上げるので、**walk の探索予算（向き変え 1 回まで）を超えることが
  ある**。予算は候補を発見するときの制約、表示値は確定した経路の属性で、別々のもの
  （Astra 裁定 `out/review-astra44.log`）。Markdown 先頭の「向き変えを含む行 N 件」は
  `switches` が 1 以上の行数（JSON の `summary.secondOrder`。名前は v1 の出力契約のまま）
- **逆向きの定義の縁が先に先着しても 本命 を潰さない**: 同一ノードへの到達は旗（本命 / 定義上 /
  `invokes` で届いた / 段数の残り）の包含関係で支配判定し、支配する旗で届いた経路は再展開する。
  先に着いた順だけで打ち切ると、`references` を逆向きに歩いた一歩が後からの `chain: true` を殺す
  （第 30 ラウンド指摘 D。実測で `demo-order` の 3 行が出力から消えていた）
- **探索の打ち切り**: 外側の探索は「まだ歩いていないコードのノード」か「未登録の API グループ」が
  無くなるまで続ける。実行したラウンド数は `summary.rounds`、上限（既定
  `6 + API グループ数 + コードのノード数 + 2`、`--max-rounds`）は `summary.maxRounds` に出る。
  上限に達して仕事が残ったら `summary.unresolved` が true になり、stderr と Markdown に警告を出す。
  一覧の `--limit` による打ち切りは `summary.listTruncated` に出る（どちらも隠さない）。
  `--limit` は Markdown・JSON・ターミナルの**すべて**に掛かるので、打った分はどの出力にも
  入らない。注記は「他の出力に出している分」と「どの出力にも入っていない分」を分けて告げる
  （ターミナルの外部リソース一覧はさらに 12 件で切り、12 件で打ったときだけそれを言う）
- **レポート JSON の版の判別**: `schemaVersion` は入れない（2026-11-15 に人が決定。
  `docs/decisions.md` 決 71）。`in` / `out` しかなかった旧版か否かは `summary.directionless` の
  有無で見分ける。読み手は `direction` の未知の値を中立（`none` 相当）として扱い、方向別の欄へ
  落とさないこと。比較基準の v1 出力 `skill/scripts/tools/battery/baseline-v1` は差し替えていないので、同じ条件で
  再生成しても**既知差分 74 件**が残る（理由を決 69 と決 71 に書く）
- `--expect` に期待する着地一覧（`{"expect": [...], "direction": "out"}`。`direction` は `in` / `out` /
  `none` / `both`、既定 `both` は 向き で絞らない）を渡すと再現率・適合率を
  出して JSON に書く。**数値を記録していないと「もっともらしく間違う」レポートになる**
- 注釈（`llm` / `human`）由来の行は「静的解析では決まらない対応付け」として件数を出す。
  粗い変更（Terraform 1 ファイルをまるごと等）で注釈由来の着地が増えて適合率が下がるので、
  `--provenance static,terraform` か `--from tf:...` で絞る

実測値は `docs/review-usage.md` の再現率・適合率の表にある（demo の `Order.cs` 変更で 外部着地 12 / 的中 11 の
再現率 0.917 / 適合率 0.917。余分な 1 着地は `ext:rds/orders-analytics` が `reads` 縁で着地したもの、
`infra/main.tf` 変更は 外部着地 2 件の適合率 0、実プロジェクト 1.000 / 1.000）。

## レポートの性能基準

**時間ゲートは 1 レポートあたり固定した変更前版の 1.20 倍以内**、**最大 RSS 800 MB は絶対上限**。
測り方は 同じ入力・設定・ウォームアップ条件で **旧→新 / 新→旧 を交互に最低 5 組**、
**組ごとの倍率の中央値**で合否を出す（`bash skill/scripts/tools/paired-gate.sh <毎回新しいタグ>`）。
ゲートは測る前に**入力の存在**を確かめ、同じタグの結果が既に有れば断り、子プロセスの失敗が
1 件でもあれば倍率を見る前に終了 1 になります。比較する旧版はコミットで
固定し、比較対象を毎回更新して遅延を積み上げる運用はしない。
**1.0 秒（5 回中央値）はゲートではなく UX 目標**として併記し、**最大応答時間はゲートにしない**
（保証もしない）。裁定は `out/loop/r42-decision.md` §2（2026-11-14、運用は `out/loop/protocol.md` 4-2）。
絶対値「1.0 秒 / 800 MB」をゲートとしていた第 40 ラウンドの裁定（`out/loop/r40-astra.md`）からは
時間ゲートだけが置き換わり、RSS の絶対上限はそのまま残った。混雑時の新版と静かだった過去の旧版を
直接比べて合否を出すこと、混雑を理由に倍率超過を免除することは裁定で却下されている。

相対ゲートでの実測（`out/tmp-r50/gate-p50b.log`、旧版はコミット `perf-baseline`（履歴の書き直しの為、旧 `a44b7c7` はタグで指す）を `out/wt-head` に固定、
旧→新 / 新→旧 を交互に 5 組、2026-11-15 13:19〜13:20、load average 3.31〜3.95。
第 49 ラウンド双人レビューの修正（兄弟一覧の並び順・エンドポイント欄の二重スライス・
`--md` / `--json` を付けない実行の告知文言）を当てた版。18 条件を再生成して差分を見ると、
**JSON は 2 条件（`fixture-api` と `fixture-api0`）の `siblingEndpoints` の並び順だけ**で、
その 2 条件も入る id・件数・他の欄は HEAD と同じ（一覧に出るルートを先頭に置いたため）。
標準出力と Markdown の文言は条件を問わず変わる。
子プロセスの失敗回数は旧・新とも全条件 0。前ラウンドの表は `out/tmp-r49/gate49a.log` に残す）:

| 入力 | 旧 5 組中央値 | 新 5 組中央値 | 組ごとの倍率 | 倍率の中央値 | 判定（1.20 以内） | 旧 RSS | 新 RSS |
| --- | --- | --- | --- | --- | --- | --- | --- |
| demo-api | 0.0379 秒 | 0.0386 秒 | 1.02 / 1.02 / 1.00 / 1.03 / 1.08 | 1.02 | 適合 | 52.7 MB | 53.3 MB |
| elsa-50 | 0.3043 秒 | 0.3368 秒 | 1.09 / 1.09 / 1.10 / 1.12 / 1.11 | 1.10 | 適合 | 413.2 MB | 442.3 MB |
| elsa-folder | 0.7410 秒 | 0.9482 秒 | 0.86 / 1.13 / 1.56 / 1.60 / 1.14 | 1.14 | 適合 | 601.7 MB | 639.6 MB |
| v2-mix | 0.2228 秒 | 0.2057 秒 | 0.92 / 0.92 / 0.92 / 0.93 / 0.92 | 0.92 | 適合 | 183.8 MB | 186.1 MB |

**4 とおりすべてゲート内**（合否は 5 組の倍率の中央値で判定する）。**`elsa-50` の絶対値が前の
ラウンドの 0.19 秒から 0.31 秒へ跳ねたのは入力の差し替え**です。これまで使っていた変更一覧は
レビュー用クローン（`out/review-agy17/elsa-50.txt`）に置いてあり、ディスク掃除（2026-11-15、人の
承認済み）といっしょに消えていました。同じ一覧を `skill/scripts/tools/make-changed-list.py` で
作り直し（リポジトリ全体から等間隔に 50 本）、**旧版・新版とも同じ一覧**で測り直しています。
絶対値はラウンドをまたいで比較できません。第 48 ラウンドの `elsa-50` 行（1.02）は入力欠損で
**250 回すべて失敗した実行の倍率**なので不当でした
（ゲートは失敗を数えるようになり、測る前に入力の存在を確かめます）

ゲート自体の最初の実行（タグ `p50a`）は**不合格で落ちた**。理由は速度ではなく検査の型で、
1 組の集計ファイルに入る標本は 1 本なのに検査が「標本 5 本」を要求していた（前版は
1 ファイルに 5 本まとめていた）。検査を「その組の標本が 1 本以上かつ失敗 0 回」に直し、
同じスクリプトのままタグを `p50b` に変えて測り直した。不合格で落ちたことはそのまま
`out/tmp-r50/gate-p50a.log` に残す（検査が実際に効いている証拠）

測定道具は追跡下に置いた（`skill/scripts/tools/perf-measure.py` / `perf-run.sh` /
`paired-gate.sh`。第 50 ラウンド双人レビューで、唯一のコピーが `out/tmp-*`（ディスク掃除の対象）に
あると指摘された）。入力の作り直しも同じ場所にある。`out/perf-inputs/elsa-50.txt` は
`skill/scripts/tools/make-changed-list.py`、`out/perf-inputs/v2-big.graph.json` は
`skill/scripts/tools/make-v2-graph.py`（第 48 ラウンドまで一時ディレクトリに有った旧残骸と
ノード・縁が 1 件も違わないことを実測）で生える。入力が欠けた日はゲートが測らずに落ちるので、
消えたまま合格することができない

`elsa-folder`（`--from folder:. --limit 100000`）は他の入力より重く、縁の本数ぶんの表示用コピーを
隣エントリが持つため最大 RSS も 641.9 MB まで上がる（上限 800 MB 内）。この入力は組ごとの振れが
最も大きく、このラウンドの個別組は 0.86 〜 1.60（中央値 1.14）、前のラウンドは 0.79 〜 1.58
（中央値 1.09）、その前は 1.55 まで振れました。
この入力を「遅いから」と理由に打ち切ることはしない。

かつて超過していた値はこうです（`out/loop/r42-decision.md` §3、2026-11-14 23:00、コミット `perf-baseline` との比較）:
demo-api 1.01 / elsa-50 1.00 / **elsa-folder 1.67（超過）** / v2-mix 1.02。超過の主因は
「縁順に依存しない選び直しの候補を保持すること」で、**結果を 1 バイトも変えない軽量化**
（縁の表示コピーを隣エントリで共有し、候補を写しではなく実体で持つ）で 1.09 まで下がった。
「対照が 1 件しかないノードを選び直し対象から外す」ことで速くすることは、表示結果の選択規則を
変える仕様変更として裁定で却下されている（`out/loop/r43-astra.log` 裁定 2 / 決定事項 66）。

参考（絶対値としての 5 回中央値。第 40 ラウンドの実測（当時の生ログは一時ディレクトリの
`perf-r40v.json`。掃除で消える場所に置く習慣はやめた）、commit `03d9c48`、
2026-11-14 計測、4 とおりとも失敗 0）。**この 1.0 秒をゲートとして扱う運用は終わっている**:

| 入力 | 5 回中央値 | 最大 | 最大 RSS | UX 目標 1.0 秒との関係 |
| --- | --- | --- | --- | --- |
| demo-api | 0.0363 秒 | 0.0387 秒 | 52.7 MB | どちらも内 |
| elsa-50 | 0.255 秒 | 0.2626 秒 | 391.8 MB | どちらも内 |
| elsa-folder | 0.7332 秒 | **1.1055 秒** | 601.8 MB | 中央値は内。**最大は UX 目標を超過** |
| v2-mix | 0.2259 秒 | 0.2281 秒 | 184.1 MB | どちらも内 |

4 とおりの入力とコマンド（`node $SKILL/scripts/report.mjs` の引数。JSON は破棄して実行した）:

| 名前 | 入力の実測サイズ | コマンドの引数 |
| --- | --- | --- |
| demo-api | `out/demo/graph.json` 74 ノード / 66 縁 | `--graph out/demo/graph.json --api POST /orders` |
| elsa-50 | `out/elsa/graph.json` 51,179 ノード / 53,521 縁（48.5 MB）、変更 50 件 | `--graph out/elsa/graph.json --changed out/perf-inputs/elsa-50.txt` |
| elsa-folder | 上のグラフで `folder:.` 起点、`--limit 100000`（既定の `--limit 200` を上げている） | `--graph out/elsa/graph.json --from folder:. --limit 100000` |
| v2-mix | `out/perf-inputs/v2-big.graph.json` 2,727 ノード / 5,800 縁（HTTP API v2 40 × 20 route。`make-v2-graph.py` で作り直せる） | `--graph out/perf-inputs/v2-big.graph.json --api POST /v2/a7/r3` |

測定環境: macOS 26.3（ビルド 25D125）、Apple M4（`Mac16,10`）・16 GB・arm64、Node v26.5.0。
測定方法: 同じ道具の現在地 `bash skill/scripts/tools/perf-run.sh <タグ>`（第 40 ラウンド当時は
一時ディレクトリに有った）。4 とおりを交互に
5 ラウンド回し、1 とおりにつきウォームアップ 1 回のあと 5 回実行して中央値と最大を取る
（1 とおり 25 実行）。集計は ラウンド中央値の中央値 を 5 回中央値、ラウンド最大の最大 を 最大
として出し、RSS は `getrusage(RUSAGE_CHILDREN)` の最大を使う（同じプロセスで複数とおりを測ると
後勝ちになるので 1 とおり 1 プロセス）。

**保証する表**: 同じ入力・設定・ツール版なら、縁の列挙順が違っても同じ表が出る（出力は ID 順に
整列して書き、断片と `graph.json` は `generatedAt` を除くバイト列が一致する。`test-analyzer.mjs` の
決定性検査はソート比較ではなくバイト比較でこれを確かめている）。表示する行は本命・参考を問わず
起点まで辿れる単一の連鎖のまま出す。

**時間で切り捨てない**: 速くするために候補や探索を途中で打ち切って、実行ごとに違う表を出すことは
しない（第 40 ラウンド裁定で却下）。表示する行は起点まで辿れる単一の連鎖のまま保証する。
待たせる側は表示で認める — ビューアは表の計算・描画が始まるとヘッダに「レポートを生成中」を
出す（`skill/viewer/template.html` の `#busy`。CSS と `requestAnimationFrame` だけで動き、
外部 JS・CDN に依存しない）。表示が消えるのは選択と並び順が確定した表が DOM へ入りきったあとで、
半途の表を見せない。

## 検証する

### 保存した条件でレポートを再生成して比べる

```sh
python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs out/audit-check --force
python3 skill/scripts/tools/count-kinds.py out/audit-check
```

保存済み 18 条件（`skill/scripts/tools/battery/baseline-v1`。`CGD_AUDIT_BASE` で変更可）で今の `report.mjs` を
走らせて枠別・縁別の延べ回数を出す。**出力先に基準ディレクトリ自身は渡せない**（比較相手を壊す）。
中身のある出力先の上書きは `--force` が要る。子プロセスが 1 件でも失敗すれば非 0 で終わる

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
node $SKILL/scripts/test-query.mjs           # fixtures/query/graph.json を使う（.NET 不要、28 項目）
node $SKILL/scripts/test-merge.mjs           # Lambda handler の解決規則（.NET 必要、12 項目）
node $SKILL/scripts/test-terraform.mjs       # API Gateway のパス組み立てと HTTP API (v2) の `target`（46 項目、.NET 不要）
node $SKILL/scripts/test-report.mjs          # 差分 → 影響範囲レポート（117 項目、.NET 必要）
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

ヘッドレス Chromium で実際にクリックし、26 項目を確かめる。検査対象は `graph.json`
から自動選択するので、どのプロジェクトにもそのまま効く（Terraform ノードが無い場合は
該当チェックを省略して 24 項目）。主な確認項目:

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
- 表の計算・描画が始まるときヘッダに「レポートを生成中」が出ること（`#busy`。`role=status` と
  `aria-live=polite` を持ち、発火直後に表示中、確定した表のあとは非表示）。第 40 ラウンド裁定
  `out/loop/r40-astra.md` の待ち時間の表示
- コンソールエラーゼロ

`#busy` は CSS と `requestAnimationFrame` だけで動き、外部 JS・CDN に依存しない。合図を出してから
2 フレーム待って計算に入り、表示が消えるのは確定した表が DOM へ入りきったあとなので半途の表を
見せない。待ち時間が長くなる実測（elsa-core 51,179 ノード / HTML 20.4 MB）での検査と、表示中のみかけ
の状態を撮ったスクリーンショットは `out/tmp-r41-viewer/` に置いてある（`check-busy.mjs` 11/11、
`check-busy-large.mjs` 3/3、`busy-appearance.png`）

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
