# csharp-dependencies-graph

C# プロジェクトを **フォルダ → csproj → cs ファイル → クラス → メソッド** の順で
クリック展開できる依存関係グラフと、それをブラウザで操作する HTML を作るスキル。
Terraform で管理する Lambda / Step Functions / API Gateway / DynamoDB などの外部リソースも
ノードとして組み込み、静的解析では決まらない対応付けは注釈（`annotations.json`）で後から足せる。

```sh
export DOTNET_ROOT=$HOME/.dotnet
node skill/scripts/build.mjs --root /path/to/repo --out-dir out/graph --name my-service \
  --exclude test,docs   # 既定で bin/obj/node_modules 等は除外。test は大きいので明示
open out/graph/graph.html
```

- 使い方・運用（注釈の書き方、検証、落とし穴）: [skill/SKILL.md](skill/SKILL.md)
- データ契約（ノード/エッジ/ID/注釈スキーマ）: [skill/reference/schema.md](skill/reference/schema.md)
- コードレビュー・設計レビューでの使い方（影響範囲・逆引きの実測レシピ）: [skill/reference/review-workflows.md](skill/reference/review-workflows.md)

## 必要になる物

- .NET SDK 9 と Node.js 20 以上。`.NET` が要るのは静的解析（`cgd` を `build.mjs` が
  `dotnet build` する）と `test-merge.mjs` だけで、照会・Terraform 走査・ビューアは `.NET`
  不要。ビューアは生成された `graph.html` をブラウザで開くだけで、追加の配信基盤を要しない
- `skill/analyzer/bin/` は追跡しないので、**新しくクローンした日は初回の `build.mjs` が
  アナライザをビルドする**（数秒）

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

## 作りを調べる人へ

- 実測の記録（対象別のノード / 縁の件数、性能ゲートの実測）: [docs/measurements.md](docs/measurements.md)
- グラフをレビュー・設計で使うときの運用解説（6 つの枠、縁の向き、欄名と JSON の対応）: [docs/review-usage.md](docs/review-usage.md)
- 検査器の置き場所と終了コード、台帳と入力の所在: [docs/maintenance.md](docs/maintenance.md)
- なぜこの形にしたかの記録（決めの表と実測値）: [docs/decisions.md](docs/decisions.md)

