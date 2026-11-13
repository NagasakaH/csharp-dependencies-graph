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
- 判断の記録と実測値: [docs/decisions.md](docs/decisions.md)

## 試した対象と実測

| 対象 | ノード / エッジ | 内容 |
| --- | --- | --- |
| [elsa-core](https://github.com/elsa-workflows/elsa-core) | 51,166 / 55,057（C# 解析 3 秒、HTML 20MB） | 336 csproj、6,754 ファイル、8,223 型、32,572 メンバ、calls 14,754 / accesses 13,498 / references 16,401、898 ファイルが AWS/DB シグナル |
| `demo/orders-api-lambda` | 70 / 60（静的 27 / Terraform 25 / LLM 8） | C# Lambda 3 csproj + Terraform 16 リソース + LLM 注釈 8 エッジ |

検証は 2 系統あり、どちらも対象プロジェクト非依存で動く。

```sh
node skill/scripts/test-analyzer.mjs                          # 静的解析の精度（23 項目、ブラウザ不要）
node skill/scripts/verify.mjs --html out/graph/graph.html --shots out/shots   # ブラウザ実操作（24 項目）
```

`verify.mjs` は検査対象を `graph.json` から自動選択するので、どのプロジェクトにもそのまま使える
（今の実測: demo 24/24、elsa-core 22/22。Terraform ノードが無い対象は該当 2 項目を省略する）。
静的解析テストは「出てはいけないエッジ」と「消えてはいけないエッジ」の両方を見る。
名前が型メンバを隠す構文（ラムダ引数・ローカル関数・兄弟ブロックの同名 var）と、
`var` / `foreach` の型推論の回帰に効く。

## 構成

```
skill/
  analyzer/            Roslyn 構文解析（net9.0, cgd）。ビルドは build.mjs がやる
  scripts/             build / scan / scan-terraform / merge / render / verify / test-analyzer
  tests/fixtures/      静的解析の精度テスト用 C#
  viewer/template.html 単一ファイルのビューア（データ埋め込み）
  reference/schema.md  データ契約
  examples/            LLM 注釈の実例
demo/orders-api-lambda Lambda + Terraform のデモ対象
out/                   生成物（gitignore 済み）
```
