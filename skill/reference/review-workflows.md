# コードレビュー・設計レビューでのグラフの使い方

グラフは「作る」より「どう使うか」が価値なので、レビューと設計で効く型をここにまとめる。
コマンドは [`../scripts/query.mjs`](../scripts/query.mjs)（影響範囲の照会）とブラウザのビューア、
および [`../reference/schema.md`](schema.md) のノード ID を前提にしている。

数値例は elsa-core を `--exclude test,docs` で解析した実測（51,179 ノード / 53,344 エッジ、
うち静的解析の C# エッジ 52,174 本）。

## 0. 始め方（1 回だけ）

```sh
export DOTNET_ROOT=$HOME/.dotnet
node skill/scripts/build.mjs --root /path/to/repo --out-dir out/graph --name my-service --exclude test,docs
open out/graph/graph.html
```

レビュー用にもう 1 点だけやると効くのが**変更ファイル一覧との合わせ込み**（下の 1 番）。

## 1. PR の影響範囲をレビュー前に決める

変更したファイルから辿って、**外部リソースと公開 API に着地するかどうか**だけまず見る。

```sh
git diff --name-only origin/main... > out/changed.txt
node skill/scripts/query.mjs --graph out/graph/graph.json --changed out/changed.txt \
  --hops 3 --via-parent --target-kind resource
```

- `--via-parent` が効く: csproj 単位で付いた注釈（`deploys` など）を、変更ファイルから階層を降りて拾う。
  無いと `project:` で止まって Lambda に届かない。
- 着地が 0 件なら「内部リファクタリング寄り」、Lambda / テーブル / API Gateway に着けば
  受け入れ確認（デプロイ・マイグレーション・権限）をレビュー項目に足す。
- 変更ファイルがグラフに無いときは最も近い親フォルダを起点にして、その旨を stderr に警告として出す
  （`--changed` の性質上、削除ファイルは起点にならない）。親がルートのだけのときは `folder:.` を起点にする
  が、そこは階層で届いただけで依存エッジの証拠ではない。`--json` では `fallbacks` に元パスと落ち先が残る。

## 2. 「この変更は公開エンドポイントに載るか」

`exposed-by` の縁があるかどうかで、コードが HTTP の経路上にあるかどうかが分かる
（Terraform の API Gateway リソースと対応付いた注釈経由）。

```sh
node skill/scripts/query.mjs --graph out/graph/graph.json --from member:NS.Class.Method --dir in --hops 2
```

ブラウザなら、そのメソッドをクリックして **⌥⇧クリック**（入力エッジ）か詳細パネルの **入力 N**。
経路上に `apigateway` が現れたら、入出力契約を変えていないかを見る。

## 3. DB のテーブル・カラムから実装と入口を逆引き

「この列を読んでいるコードはどこか」「この列の型を変えるとどこが壊れるか」に使う。

```sh
node skill/scripts/query.mjs --graph out/graph/graph.json \
  --find order_summary                       # ノード ID を探す
node skill/scripts/query.mjs --graph out/graph/graph.json \
  --from ext:rds-column/db.public.t.amount --dir both --hops 3
```

実デモ（`demo/orders-api-lambda`）ではこの 1 本で
`order_id → Order.Id → Functions.CreateOrder → (calls) 4 メソッド / (exposed-by) POST /orders /
(handler) Lambda orders_api` まで出た。注釈で付いた縁は `※注釈` と注記（`detail`）付きで並ぶので、
**コードには現れないが設計上は依存**という前提をレビュー参加者と共有できる。

## 4. Lambda / Step Functions から実装コードを逆引き

Terraform の `handler` 指定（`Assembly::NS.Type::Method`）は merge 時に C# のメソッドノードへ解決して
`handler` エッジにする。だから Lambda から実装へ 1 ホップで降りられる。

```sh
node skill/scripts/query.mjs --graph out/graph/graph.json --from tf:aws_lambda_function.orders_api --dir out --hops 3
node skill/scripts/query.mjs --graph out/graph/graph.json --from tf:aws_lambda_function.orders_api --dir in --hops 3
```

- `--dir out`: 実装メソッド → そこから `calls` / `accesses` で本体、`references` で DynamoDB や IAM ロール。
- `--dir in`: 誰がこの Lambda を呼ぶか（API Gateway の `triggers`、Step Functions の `invokes`、
  csproj の `deploys`）。**デプロイ単位とトリガ元を同時にレビュー**できる。
- 解決できなかった handler は警告に出る（`handler の解決失敗`）。その場合は注釈で張る
  （[schema.md](schema.md) の注釈形式、実例は [`../examples/annotations.orders-api.json`](../examples/annotations.orders-api.json)）。

## 5. レビュー中に「この型を触ると何が壊れる」を 10 秒で見る

- ブラウザ: 型ノードをクリック → **周辺 2** → 左ツリーの**祖先を開く**で呼び出し元の所在を確認。
- ターミナル: `--from type:NS.Type --dir in --hops 2 --target-kind member`。
- 大規模リポジトリでは `--limit` と `--json`（CI やコメント投稿に使える）。

## 6. 設計レビュー: 結合ハブの棚卸し

「別 csproj から参照されている型」の多さで、境界の実質的な太さを見る。単位を間違えると判断が変わるので
2 列に分ける。**参照元ファイル数**はリポジトリ全体（同じ csproj 内を含む）、**参照している別 csproj 数**は
型自身の csproj を除いた参照元の csproj 数。elsa-core の実測上位:

| 型 | 参照元ファイル数 | 参照している別 csproj 数 |
| --- | --- | --- |
| `Elsa.Workflows.ActivityExecutionContext` | 320 | 42 |
| `Elsa.Persistence.EFCore.IElsaDbContextSchema` | 230 | 32 |
| `Elsa.Features.Services.IModule` | 197 | 99 |
| `Elsa.Workflows.Activity` | 190 | 31 |
| `Elsa.Workflows.Models.Input` | 187 | 30 |
| `Elsa.Features.Abstractions.FeatureBase` | 138 | 100 |
| `Elsa.Workflows.IActivity` | 125 | 16 |
| `Elsa.Abstractions.ElsaEndpoint` | 119 | 17 |

`FeatureBase` と `IModule` はファイル数より別 csproj 数が桁で大きい（100 / 99）。この 2 つは「少し触れば
100 プロジェクトに響く」という意味で、ファイル数の上位（`ActivityExecutionContext`）とは効き方が違う。

集計はグラフ JSON に対して次の 1 行でできる（`contains` / `project-reference` は階層なので数えない。
`attribute` は属性としての実参照なので入れている）。

```sh
node -e 'const g=require("./out/elsa/graph.json");const n=new Map(g.nodes.map(x=>[x.id,x]));
const KINDS=new Set(["references","accesses","calls","creates","inherits","implements","attribute"]);
const projs=g.nodes.filter(x=>x.kind==="project"&&(x.path||"").endsWith(".csproj")).map(x=>x.path.replace(/\/[^/]*$/,""));
const owner=p=>{let best="";for(const d of projs)if(p.startsWith(d+"/")&&d.length>best.length)best=d;return best;};
const files=new Map(),cross=new Map();
for(const e of g.edges){const t=n.get(e.target),s=n.get(e.source);if(!t||!s||t.kind!=="type"||!KINDS.has(e.kind))continue;
const p=s.path||"";if(!p)continue;
files.set(t.id,(files.get(t.id)||new Set()).add(p));
const o=owner(p),home=owner(t.path||"");if(o&&o!==home)cross.set(t.id,(cross.get(t.id)||new Set()).add(o));}
[...files].sort((a,b)=>b[1].size-a[1].size).slice(0,8).forEach(([id,s])=>console.log(s.size,(cross.get(id)||new Set()).size,n.get(id).name));'
```

**変更の前後でこの上位が動かないか**を見ると、意図せず境界を太らせていないかの判断になる。

## 7. 設計レビュー: 呼び出しの集中（blast radius）

`calls` の受信数上位（elsa-core 実測、`calls` エッジ 14,589 本 / 呼び出し先 6,204 個）:
`IModule.Configure` 128、`ActivityExecutionContext.GetRequiredService` 109、
`ElsaEndpoint.RequirePermission` 108、`ActivityExecutionContext.Get` 102、
`ActivityExecutionContext.Set` 89。**シグネチャを変えると何箇所に響くか**が即座に分かる。

`GetRequiredService` が上位に来るのは DI のサービスロケータが境界をまたいで直接叩かれている合図で、
「コンストラクタ注入に寄せる」議論の材料になる。上位リストは設計議論の議題選びにそのまま使える。

## 8. 外部境界の棚卸し（注釈だけを見る）

`--provenance llm`（または `human`）で辿ると、**静的解析で決まらず後付けした依存だけ**が出る。
= レビューすべき「コードに現れない仕様」の一覧。

```sh
node skill/scripts/query.mjs --graph out/demo/graph.json --from tf:aws_dynamodb_table.orders \
  --dir in --hops 3 --provenance llm
```

注釈が古い／壊れている検出は merge の警告に集約される（`アノテーションのエッジ解決失敗` など）。
再生成のたびに警告 0 件を保つのが運用の最低ライン。

## 9. 誤読しないための前提

- **構文解析のみ**（`SemanticModel` を使わない）。型が決まらない呼び出し名は張らずに未決着として数える
  （elsa-core で 96,592 件）。`var x = Foo();` の返し値や `out var`、タプル、`is var` の型は推定しない。
- **同名型のうち「届かない」と判断したものは張らない**。判断は (1) 使われた型引数の数が宣言のいずれかと
  合うか、(2) `using`・名前空間・同一ファイルから到達できそうか。ゲートは型引数を書いた側だけに効く
  一方向で、型引数を書かない非ジェネリック利用は従来どおり結ぶ。
- **断ったバインドは `.cs` ノードに `rejectedTypes` として残る**。ここに同名の型がリポジトリ内に
  存在するということなので、注釈で正しく張る候補リストになる（elsa-core で 1,018 ファイル / 1,268 名）。
  MSBuild が `obj/` に生成する implicit global using はアナライザから見えないので、ここで拒否に見える。
- 同名候補が同じ強さで並んだ場所では `ambiguous` を `detail` に持つ縁を最大 2 本張る。同一ファイルや
  名前空間直下の型という手掛かりで単独決定できることが多く、elsa-core の残りは **2 本**
  （429 → 301 → 2。表現内の型参照の張り分けは 0 本になり、`param (ambiguous)` が 2 本。残った 2 本は
  `Endpoint` という同名型が別名前空間に等距離にある箇所で、1 本に絞れば必ず誤りになる）。
  残った縁は断定済みの縁と混ぜて読まない。
- 描画には上限（エッジ 900 / 子ノード 400 / フォーカス 120 / 検索 200）がある。上限に当たったら
  `--exclude` か chip で絞ってから見る。数えるのは常に全データ側の `graph.json`。
