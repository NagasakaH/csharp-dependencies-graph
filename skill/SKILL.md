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
全体 30 秒弱、`graph.json` 45MB / `graph.html` 20MB。

## 使い方を選ぶ

| やりたいこと | 手段 |
| --- | --- |
| 初めてグラフを作る | 上の `build.mjs` を 1 回 |
| 巨大リポジトリが遅い／見たい所だけ | `--exclude obj,bin,test,docs` を足す（部分再実行より速い） |
| 外部リソースや担当者を後から紐づける | [注釈を書く](#外部情報を後から紐づける) → `--annotation` を足して再生成 |
| ビューア上で暫定的に紐づけた分を定着させる | 画面の「注釈 JSON」でダウンロード → リポジトリの `annotations.json` に追記 |
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
  `invokes` `triggers` `deploys` `exposes` `exposed-by` `reads` `writes` `annotates`（外部世界）
- 部分クラスとオーバーロードは 1 ノードにまとめる（`metadata.overloads`、`metadata.alsoDeclaredIn`）
- 解決できなかった呼び出し名はノードの `metadata.unresolvedCalls` に残す
  （意味は構文だけからは決められないので、ここを LLM が注釈で埋める）

`.csproj` からは `targetFramework` `rootNamespace` `assemblyName` `packageReferences`
`projectReferences` を取り、`.cs` / `.csproj` のテキストから AWS/DB のヒント
（`aws-lambda-sdk` `lambda-handler` `api-gateway-proxy` `dynamodb` `s3` `sqs`
`step-functions` `relational-db` `ef-core` `redis` など）を `metadata.signals` に入れる。
**この signals が、LLM が注釈を書くときの入口**になる。

Terraform がある場合は `resource "aws_lambda_function" "orders_api"` のような宣言から
`tf:aws_lambda_function.orders_api` ノードを作り、`uri = aws_lambda_function.x.invoke_arn`
のような参照から `invokes` / `triggers` / `references` を張る。HCL は brace を数える
簡易パーサなので、モジュール展開や動的定義までは追わない（そこは注釈で埋める）。

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

1. **先に `graph.json` を読んでする。** 存在しないノード ID へのエッジは merge で
   警告を出して捨てられる。`sourceMatch`/`targetMatch`（`kind` + `path`/`name` の部分一致で
   探す）も使えるが、複数のノードに当たると警告して採用されない。曖昧なら ID で書く。
2. **根拠を `note` に必ず書く。** handler 文字列の一致、環境変数名、テーブル名、
   Terraform のアドレスなど、あとで他人が検証できる手がかり。
3. **`confidence` をつける。** コードに現れない運用知識（「毎週 Redshift へエクスポート」）は
   0.6 台にとどめ、`provenance` は `llm`、静的解析由来は `static`、Terraform 由来は `terraform`。
   ビューアではこの provenance をチップで絞り込める。
4. **csproj と Lambda の紐づけは handler 文字列から決める。** `.tf` の
   `handler = "Orders.Api::Orders.Api.Functions::CreateOrder"` は
   `アセンブリ名::型名::メソッド名`。`assemblyName` と `type:`/`member:` の ID を突き合わせれば
   機械的に決められるので、推測で書かない。
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

## 検証する

### 静的解析の精度（ブラウザ不要）

```sh
node $SKILL/scripts/test-analyzer.mjs        # cgd がビルド済みなら即実行（16 項目）
```

`skill/tests/fixtures/` の C# を `cgd` にかけて、期待するエッジと「出してはいけない
エッジ」を照合する（fixture は `dotnet build` で通ることを確認して置いてある）。押さえるのは
ローカル変数・型を省略したラムダ引数・ローカル関数・兄弟ブロックの同名 var といった
「名前が型メンバを隠す」構文と、`var` / `foreach` の型推論の回帰。

### ブラウザ実操作

```sh
node $SKILL/scripts/verify.mjs --html out/graph/graph.html --shots out/shots
```

ヘッドレス Chromium で実際にクリックし、24 項目を確かめる。検査対象は `graph.json`
から自動選択するので、どのプロジェクトにもそのまま効く（Terraform ノードが無い場合は
該当チェックを省略して 22 項目）。主な確認項目:

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
- ビューアの操作: クリック=展開 / ⇧クリック=出力エッジをたどる / ⌥⇧クリック=入力エッジ /
  ホイール=拡大縮小 / ドラッグ=スクロール / 「表示を共有」=現在の展開を URL にコピー
  （`#expand=<id,id>&select=<id>` のディープリンクで同じ画面を開ける）
