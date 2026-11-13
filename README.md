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
| [elsa-core](https://github.com/elsa-workflows/elsa-core) | 51,166 / 52,221（C# 解析 3 秒、HTML 20MB） | 336 csproj、6,754 ファイル、8,223 型、32,572 メンバ、898 ファイルが AWS/DB シグナル |
| `demo/orders-api-lambda` | 71 / 59（静的 25 / Terraform 26 / LLM 8） | C# Lambda 3 csproj + Terraform 16 リソース + LLM 注釈 8 エッジ |

検証はヘッドレス Chromium で実操作する（`skill/scripts/verify.mjs`）。
検査対象は `graph.json` から自動選択するので、どのプロジェクトにもそのまま使える。

```sh
node skill/scripts/verify.mjs --html out/graph/graph.html --shots out/shots
```

## 構成

```
skill/
  analyzer/            Roslyn 構文解析（net9.0, cgd）。ビルドは build.mjs がやる
  scripts/             build / scan / scan-terraform / merge / render / verify
  viewer/template.html 単一ファイルのビューア（データ埋め込み）
  reference/schema.md  データ契約
  examples/            LLM 注釈の実例
demo/orders-api-lambda Lambda + Terraform のデモ対象
out/                   生成物（gitignore 済み）
```
