# コードレビュー・設計レビューでのグラフの使い方

グラフは「作る」より「どう使うか」が価値なので、レビューと設計で効く型をここにまとめる。
コマンドは [`../scripts/query.mjs`](../scripts/query.mjs)（影響範囲の照会）とブラウザのビューア、
および [`../reference/schema.md`](schema.md) のノード ID を前提にしている。

数値例は elsa-core を `--exclude test,docs` で解析した実測（51,179 ノード / 53,521 エッジ、
うち静的解析の C# エッジ 52,351 本）。

## 0. 始め方（1 回だけ）

```sh
export DOTNET_ROOT=$HOME/.dotnet
node skill/scripts/build.mjs --root /path/to/repo --out-dir out/graph --name my-service --exclude test,docs
open out/graph/graph.html
```

レビュー用にもう 1 点だけやると効くのが**変更ファイル一覧との合わせ込み**（下の 1 番）。

## 1. PR の影響範囲をレビュー前に決める

変更したファイル一覧をそのまま渡すと、**影響を受ける入口（呼び出し元・API エンドポイント）**と
**影響する外部リソース（読み書きする先）**を一覧にしたレポートが出る。

```sh
git diff --name-only origin/main... | node skill/scripts/report.mjs \
  --graph out/graph/graph.json --changed - --md out/impact.md --json out/impact.json
```

出方は枠に分けてある（混ぜるほど読み間違えるので分けたまま読む）。**どの行も必ずどれか 1 つの枠にしか
入らない**ので、`summary.rows` と各枠の合計は常に一致する:

| 枠 | 意味 | 縁 |
| --- | --- | --- |
| 影響する外部リソース | 変更が読み書きする先、呼びに出す先。マイグレーション・権限・デプロイの確認対象 | `writes` `reads` `accesses` `calls` `invokes` `triggers` `handler` |
| 影響を受ける入口 | 変更を使う呼び出し元と、その経路にある Lambda / API Gateway | 同上（逆向き） |
| 影響を受けるコード側の入口 / 出口 | 上の 2 つのうちコード（メソッド・型）のもの。出口は「起点から実際に届くコード」 | `calls` `accesses` `references`（コード内）`handler` |
| 同じ API の定義 / 同じコードを使う別エンドポイント | 起点がエンドポイントのとき、起点自身を定義するノードと、同じ Lambda を共有する兄弟 | 起点の数に含めない |
| 定義上の関連 | Terraform の `references`（そのブロックを文中に書いた）。**値が動くとは限らないが、定義を書き換えたら効く範囲** | IAM・rest_api・deployment など見直しの候補 |

段数の数え方は「**定義の縁（`references`）だけ数えて、動きの縁（`triggers` / `invokes` / `handler`）を
越えたら数え直し**」。Terraform の定義単位をどこまで閉じるかの上限（`--wiring-hops`、既定 3）を
動きの縁にまで適用すると、同じ Lambda を使う別 API が既定の段数で完全に消えた（実測: 3 段で 0 件、
6 段上げてようやく出る）。だから縁の種類で分けている。

- 起点は**変更ファイルの中身**から作る。`.cs` はその中のメソッド、`.tf` はそのファイルが宣言している
  リソース（`metadata.file` で照らす。リソースの `parent` はフォルダなので階層ではたどれない）
- 変更ファイルがグラフに無いときは**起点にしない**（`fallbacks` に出すだけ）。`--folder-start` は
  配下を巻き込んで適合率が下がるので、理由があるときだけ（demo で `README.md` を渡すと
  起点 1 件 → **49 件**に膨らんで外部着地 0 件・コードの入口 6 件だけ出た実測）
- 起点を 1 ノードに絞っても**着地が減るとは限らない**（実測で 8 着地）。起点の近さより、動きの縁が
  何本延びているかで決まる。絞って長く出るなら、それは本当に共有部分を変えている
- コード起点で `.cs` の中にある型やメソッドは「影響する先」に並ばない（起点自身の一部なので）
- 着地が 0 件なら「内部リファクタリング寄り」、Lambda / テーブル / API Gateway に着けば
  受け入れ確認をレビュー項目に足す
- 削除ファイルは起点にならない（グラフから消えたノードなので当然）。削除の影響を見たいときは
  レビュー前に `git diff --name-only --diff-filter=D` を出して `--from` で手で辿る
- 手作業の照会（1 ノードから双方向に数ホップ）は `query.mjs` のほうが早い:

```sh
node skill/scripts/query.mjs --graph out/graph/graph.json --changed out/changed.txt \
  --hops 3 --via-parent --target-kind resource
```

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
- 解決できなかった handler は警告に出る（`handler の解決失敗`）。**まず `handler` 文字列を
  実装プロジェクトのアセンブリ名へ直す**のが典型的な修正で、注釈で張るのは意図的に別アセンブリを
  指しているときだけ（[schema.md](schema.md) の注釈形式、実例は
  [`../examples/annotations.orders-api.json`](../examples/annotations.orders-api.json)）。

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

読み方は本数ではなく**別 csproj 数の割合**で決める。`FeatureBase`（参照元 138 ファイル / 別 csproj 100）と
`IModule`（197 / 99）は参照元の大半が別プロジェクトにあり、少し触れば 100 プロジェクトに響く。
一方いちばんファイル数の多い `ActivityExecutionContext`（320 / 42）は同じ 320 本でも別プロジェクトに
散っているのは 42 で、同一 csproj 内に濃く張っている。ファイル数の上位だけをみると、この違いが消える。

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

`calls` の受信数上位（elsa-core 実測、`calls` エッジ 14,607 本 / 呼び出し先 6,207 個）:
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
  （elsa-core で 96,644 件）。`var x = Foo()` の返し値は推定する（宣言元の `using` も引き継ぐ）が、
  `out var`、タプル分割、`is var` / `case var`、LINQ の `join` の範囲変数、`dynamic` は型を決めない。
- **同名型のうち「届かない」と判断したものは張らない**。判断は (1) 使われた型引数の数が宣言のいずれかと
  合うか、(2) `using`・名前空間・同一ファイルから到達できそうか。型引数の数が違う候補では張らず、
  C# とおなじように**次の候補へ探索を続ける**（別名前空間に型引数の合う同名型があればそこへ張る）。
  ゲートは型引数を書いた側だけに効く一方向で、型引数を書かない非ジェネリック利用は従来どおり結ぶ。
- **断ったバインドは `.cs` ノードに `rejectedTypes` として残る**。ここに同名の型がリポジトリ内に
  存在するということなので、注釈で正しく張る候補リストになる（elsa-core で 1,010 ファイル / 1,260 名）。
  MSBuild が `obj/` に生成する implicit global using はアナライザから見えないので、ここで拒否に見える。
- 同名候補が同じ強さで並んだ場所では `ambiguous` を `detail` に持つ縁を最大 2 本張る。同一ファイルや
  名前空間直下の型という手掛かりで単独決定できることが多く、elsa-core の残りは **2 本**
  （429 → 301 → 2。表現内の型参照の張り分けは 0 本になり、`param (ambiguous)` が 2 本）。残った 2 本は
  `Elsa.Api.Common` の `WebApplicationExtensions.CreateRateLimitingEndpoint` が引数に書く `Endpoint` で、
  正解はリポジトリ外の `Microsoft.AspNetCore.Http.Endpoint` のため**どちらも誤り**。構文解析だけでは
  外部型に辿り着けないので、`ambiguous` を持つ縁は「ここに候補が出た」という意味にしか使えず、
  断定済みの縁と混ぜて読まない。
- 描画には上限（エッジ 900 / 子ノード 400 / フォーカス 120 / 検索 200）がある。上限に当たったら
  `--exclude` か chip で絞ってから見る。数えるのは常に全データ側の `graph.json`。
