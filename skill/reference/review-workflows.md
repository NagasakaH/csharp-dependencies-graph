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
| 影響する外部リソース / 影響を受ける入口 | 変更が読み書きする先、呼びに出す先（マイグレーション・権限・デプロイの確認対象）と、変更を使う呼び出し元・その経路の Lambda / API Gateway | `writes` `reads` `accesses` `calls` `invokes` `triggers` `handler`（入口側は逆向き） |
| コード側の出口 / 影響を受ける入口 | 上の 2 つのうちコード（メソッド・型）のもの。出口は「起点から実際に届くコード」 | `calls` `accesses` `references`（コード内）`handler` |
| 同じ API を定義するノード | 起点がエンドポイントのとき、起点自身を定義している `resource` / `rest_api` / `integration` / `deployment` | 起点の数に含めない |
| 同じコードを使う別の API | 同じ Lambda を共有する兄弟エンドポイントと、それを定義するノード | 同上 |
| リポジトリ内の成果物 | 経路上にあった `.csproj` / `.cs` / フォルダ / solution。触るかもしれないビルド単位 | 動きの証拠ではない。レビューの分担に使う |
| 定義上の関連 | Terraform の `references`（そのブロックを文中に書いた）。**値が動くとは限らないが、定義を書き換えたら効く範囲** | IAM・rest_api・deployment など見直しの候補 |

**実行経路とみなす条件**（第 29 ラウンドの裁定。第 30 ラウンドの双人レビューで両名が文書化を要求）:
`method → invokes → integration`（v2 の `target`、v1 の三点組）または統合からメソッドへの直接参照・
注釈があるときだけ実行経路とみなす。無いものは 定義上の関連 に残して対応未確定の警告を出す
（「その API の下に method が 1 件しかない」での橋渡しは作らない。候補が 1 件なのは対応が確定した
証拠にならない）。

**兄弟ルートは 本命 の結果に影響せず、別欄に要約する**。同じ Lambda / handler を共有しているだけの
別エンドポイント（`$default` を含める）は起点の実行経路に数えない。一覧は既定では出さず **件数だけ**
出す（実測: 40 API × 20 route のグラフで 799 本を並べていた）。一覧を出すのは `--list-siblings` を
立てたときだけで、本数は暗黙の 12 本ではなく `--limit` に従う。
JSON の各行には、実際に印刷した欄名と同じ `bucket` と理由コード（`siblingReason` =
`shared-code-endpoint` / `sibling-api-definition`、`unresolvedCorrReason` = `no-method-correspondence`）を
立てるので、エクスポート単体で「なぜこの欄のこの行なのか」を説明できる（`tier` は内部の昇格状態なので
兄弟欄の行が `primary` を持つことがある。欄の判定は `bucket` を見る）。

段数の数え方は「**定義の縁（`references`）だけ数えて、動きの縁（`triggers` / `invokes` / `handler`）を
越えたら数え直し**」。Terraform の定義単位をどこまで閉じるかの上限（`--wiring-hops`、既定 3）を
動きの縁にまで適用すると、同じ Lambda を使う別 API が既定の段数で完全に消えた（実測: 3 段で 0 件、
6 段上げてようやく出る）。だから縁の種類で分けている。

- 起点は**変更ファイルの中身**から作る。`.cs` はその中のメソッド、`.tf` はそのファイルが宣言している
  リソース（`metadata.file` で照らす。リソースの `parent` はフォルダなので階層ではたどれない）
- 変更ファイルがグラフに無いときは**起点にしない**（`fallbacks` に出すだけ）。`--folder-start` は
  配下を巻き込んで適合率が下がるので、理由があるときだけ（demo で `README.md` を渡すと
  起点 1 件 → **49 件**に膨らんで外部着地 0 件・コード 出口 4 件（入口 0 件）・成果物 先 1 件・受 2 件だけ出た実測）
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
- `--dir in`: 誰がこの Lambda を呼ぶか。demo の `orders_api` なら API Gateway の `triggers` 2 本と
  csproj の `deploys` 1 本（+ 統合の `references`）が出て、**デプロイ単位とトリガ元を同時にレビュー**できる。
  ただし `invokes` は State Machine から `notify` の側に張られているので `orders_api` では出ない
  （`--from tf:aws_lambda_function.notify --dir in --hops 1` で見える）
- 解決できなかった handler は警告に出る（`handler の解決失敗`）。**まず `handler` 文字列を
  実装プロジェクトのアセンブリ名へ直す**のが典型的な修正で、注釈で張るのは意図的に別アセンブリを
  指しているときだけ（[schema.md](schema.md) の注釈形式、実例は
  [`../examples/annotations.orders-api.json`](../examples/annotations.orders-api.json)）。

## 5. レビュー中に「この型を触ると何が壊れる」を 10 秒で見る

- ブラウザ: 型ノードをクリック → **周辺 2** → 左ツリーの**祖先を開く**で呼び出し元の所在を確認。
- ターミナル: `--from type:NS.Type --dir in --hops 2 --target-kind member`。
- 大規模リポジトリでは `--limit` と `--json`（CI やコメント投稿に使える）。

## 5-2. ファイル単位で「繋がっているファイルは何本か」を見る

縁は型・メンバー単位でしか張っていないので、ファイル同士の接続本数は `--group-by file` で
階層を登って集計する。**実縁（`calls` / `references` など）が 1 本も届かなかったノードは
「繋がっている」とは数えない**（階層の `contains` で並び順に並べただけの兄弟ファイルは除外）。

```sh
node $SKILL/scripts/query.mjs --graph out/graph/graph.json \
  --from file:src/Orders.Domain/Order.cs --dir both --via-parent --hops 3 --group-by file
```

`demo/orders-api-lambda` をビルドしたグラフ（`out/demo/graph.json`、74 ノード / 66 エッジ）で
実行した実測:

```
file 単位の集計: 4 グループ（表 4 行）（実縁で届いた 17 ノードを file へ巻き上げ → 集計対象 7 ノード。集計対象 7 = 17 − 起点自身の file 4 − file の祖先を持たない 6。実縁の無い 14 ノードは階層で届いただけなので数えない）
  file:Functions.cs                              参照   2 ノード（calls 3 / accesses 1 / 実縁 4 本）最短 3 段
  file:IOrderRepository.cs                       参照   2 ノード（references 2）最短 2 段
  file:DynamoDbOrderRepository.cs                参照   2 ノード（references 2）最短 2 段
  file:NotifyHandler.cs                          参照   1 ノード（calls 3 / 実縁 3 本）最短 3 段
```

- `参照 N ノード` はそのファイルに届いた到達ノード数、括弧内は届いた実縁の縁種
  （`実縁 M 本`）。同じ内訳が JSON の `summary` にも出る（`groupsReached` / `groupsNodes` /
  `groupsSkippedStartHierarchy` / `groupsSkippedNoAncestor` / `groupsSkippedHierarchy`）。
  上の例は **到達 31 = 集計対象 7 ノード（表 4 行）+ 起点自身の file 4 + `file` の祖先を持たない 6 + 実縁の無い 14**。
  表の行はグループ数、`集計対象` は巻き上げ元のノード数で単位が違うので、両数を比べないこと
  （`--json` の `summary.reached` が 31。表示される「到達集合の内訳」は
  起点を含むので合計は 1 多い）
- 集計は「最初に届いた 1 経路」ではなく**そのノードに届いた実縁の全数**で決める。実縁と階縁が
  同じ段で届いたノードは実縁として数えるので、縁の列挙順を入れ替えても JSON は変わらない
  （`test-query.mjs` が反転・id 順・source 順・交互の 4 とおり × `--via-parent` ありなしで一致を固定し、
  実グラフ side でも `out/tmp-r43-docs/check-edge-order.py` で不一致 0 件を確かめた）
- `--dir both` にするのは、参照する側（`out`）と参照される側（`in`）を合わせて見たいから。
  **逆向きだけが見たいときは起点を型かメンバーにする**。ファイル起点の `--dir in` は
  `--via-parent` を付けても階層を登るだけで実縁に届かず、2 段でも 3 段でも集計は 0 件のまま
  （`--via-parent` を付けないと階層の 1 段で止まり、stderr に案内が出る）:

```
# 効かない: ファイル起点の逆引き（到達はするが全部階層で届いただけ）
$ node $SKILL/scripts/query.mjs --graph out/demo/graph.json \
    --from file:src/Orders.Api/Functions.cs --dir in --via-parent --hops 3 --group-by file
file 単位の集計: 0 グループ（表 0 行）（実縁で届いた 0 ノードを file へ巻き上げ → 集計対象 0 ノード。集計対象 0 = 0 − 起点自身の file 0 − file の祖先を持たない 0。実縁の無い 3 ノードは階層で届いただけなので数えない）

# 効く: 型を起点にする（--via-parent 不要）
$ node $SKILL/scripts/query.mjs --graph out/demo/graph.json \
    --from type:Orders.Domain.IOrderRepository --dir in --hops 2 --group-by file
file 単位の集計: 3 グループ（表 3 行）（実縁で届いた 5 ノードを file へ巻き上げ → 集計対象 5 ノード。集計対象 5 = 5 − 起点自身の file 0 − file の祖先を持たない 0。実縁の無い 0 ノードは階層で届いただけなので数えない）
  file:Functions.cs                              参照   2 ノード（references 2）最短 1 段
  file:NotifyHandler.cs                          参照   2 ノード（references 2）最短 1 段
  file:DynamoDbOrderRepository.cs                参照   1 ノード（implements 1）最短 1 段
```

- `--group-by` に選べるのは `file` / `folder` / `type`。**`project` は選べない** — 実グラフでは
  `.cs` ファイルノードの `parent` が `folder` で、`project` が関わる縁も `.csproj` の `contains` /
  csproj 同士の `project-reference` / `project` からリソースへの `deploys` だけ。**コードノードから
  所属 csproj はたどれない**（`project:` を親に持つコードノードは demo でも elsa-core でも 0 件。
  csproj 単位が見たいなら逆に csproj を起点にする）:

```
$ node $SKILL/scripts/query.mjs --graph out/demo/graph.json \
    --from project:src/Orders.Domain/Orders.Domain.csproj --dir both --via-parent --hops 4 --group-by file
file 単位の集計: 6 グループ（表 6 行）（実縁で届いた 38 ノードを file へ巻き上げ → 集計対象 20 ノード。集計対象 20 = 38 − 起点自身の file 0 − file の祖先を持たない 18。実縁の無い 24 ノードは階層で届いただけなので数えない）
  file:Functions.cs                              参照   5 ノード（references 4 / calls 1 / handler 1 / 実縁 6 本）最短 3 段
  file:Order.cs                                  参照   4 ノード（calls 2 / references 2 / accesses 1 / 実縁 5 本）最短 4 段
  file:IOrderRepository.cs                       参照   3 ノード（calls 4 / references 2 / 実縁 6 本）最短 4 段
  file:DynamoDbOrderRepository.cs                参照   3 ノード（references 2 / implements 1 / reads 1 / writes 1 / 実縁 5 本）最短 4 段  ※注釈 2
  file:NotifyHandler.cs                          参照   3 ノード（references 2 / handler 1 / writes 1 / 実縁 4 本）最短 3 段  ※注釈 1
  file:StepFunctionsOrderProcessLauncher.cs      参照   2 ノード（implements 1 / invokes 1）最短 4 段  ※注釈 1
```

  段数は csproj → folder → file → 型 → メンバーの順に広がるので、ファイル同士の接続を見るには
  `--hops 4` が要る（`--hops 2` だと実縁 4 件がすべて `file` の祖先を持たない resource / project に
  巻上がるだけで表は 0 件）

  選べない理由を自分のグラフで確かめる 1 行（`project:` を親に持つコードノードと、`project` が
  端点になっている縁の種類を出す）:

```
$ node -e 'const g=require("./out/elsa/graph.json");const byid=new Map(g.nodes.map(x=>[x.id,x]));
const kids=g.nodes.filter(x=>(x.parent||"").startsWith("project:")).length;
const pk={};for(const x of g.nodes){if(!["file","type","member"].includes(x.kind))continue;const p=byid.get(x.parent);const k=p?p.kind:"(親なし)";pk[k]=(pk[k]||0)+1;}
const ek={};for(const e of g.edges){if(e.source.startsWith("project:")||e.target.startsWith("project:")){const k=e.kind+" "+e.source.split(":")[0]+"->"+e.target.split(":")[0];ek[k]=(ek[k]||0)+1;}}
console.log(JSON.stringify({ノード数:g.nodes.length, projectを親に持つノード:kids, コードノードのparentのkind:pk, projectが端点の縁:ek}));'
{"ノード数":51179,"projectを親に持つノード":0,"コードノードのparentのkind":{"folder":7207,"file":8223,"type":32572},"projectが端点の縁":{"contains file->project":309,"project-reference project->project":861}}
```

  demo（`out/demo/graph.json`）も `projectを親に持つノード: 0`、端点の縁は
  `project-reference 3` と `deploys 2` だけだった
- elsa-core でも同じ照会がそのまま使える（`out/elsa/graph.json` は 51,179 ノード / 53,521 エッジ、
  下の照会は 0.23 秒）。`--find HttpEndpoint` は `type:Elsa.Http.HttpEndpoint` と
  `member:Elsa.Http.HttpStimulusNames.HttpEndpoint` の 2 件を返し、ファイルノードは
  `--find HttpEndpoint.cs` で出る（`file:core/src/modules/Elsa.Http/Activities/HttpEndpoint.cs`）。
  そのファイルを `--dir both --via-parent --hops 2 --group-by file` すると **4 ファイル**
  （`HttpEndpointTriggerPayloadValidator.cs` を `references`、`Activity.cs` と `Output.cs` を
  `attribute`、`Trigger.cs` を `inherits`）。到達 75 ノードのうち 68 件は階縁で並べただけなので
  数えず、起点自身のファイルへ巻上がる実縁 3 件も表には出さない:

```
$ node $SKILL/scripts/query.mjs --graph out/elsa/graph.json \
    --from file:core/src/modules/Elsa.Http/Activities/HttpEndpoint.cs --dir both --via-parent --hops 2 --group-by file
file 単位の集計: 4 グループ（表 4 行）（実縁で届いた 7 ノードを file へ巻き上げ → 集計対象 4 ノード。集計対象 4 = 7 − 起点自身の file 3 − file の祖先を持たない 0。実縁の無い 68 ノードは階層で届いただけなので数えない）
  file:HttpEndpointTriggerPayloadValidator.cs    参照   1 ノード（references 1）最短 2 段
  file:Activity.cs                               参照   1 ノード（attribute 1）最短 2 段
  file:Trigger.cs                                参照   1 ノード（inherits 1）最短 2 段
  file:Output.cs                                 参照   1 ノード（attribute 1）最短 2 段
```

- 同じ例で `--find RouteDataWorkflow` と `--find SimpleHttpApiWorkflow` はどちらも「該当なし」。
  このグラフにノードも縁も無い（以前のこの文書が挙げていた `creates` 2 本は実在しなかった）

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
`attribute` は属性としての実参照なので入れている）。**csproj の判定は `path` の最長一致でやっている** —
グラフの階層はコードを `folder` の下に置くだけで csproj とは結ばれていないので、`parent` を辿っても
所属プロジェクトは決まらない（上の `--group-by project` が無いのと同じ理由）。

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
