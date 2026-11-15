# スキーマリファレンス

`graph.json`・ビューア用ペイロード・ノード/エッジ ID・注釈（annotations.json）の形。
数値は elsa-core を走らせたときの実出力にあわせてある。
**レポート出力（`report.mjs --json`）の形は下の「レポート出力」に分けて書く**（このファイルでも
値域を正本として宣言する。README は読み方の説明）。

## レポート出力（`report.mjs --json`）

出力全体のトップレベルは `{ summary, external, entries, artifacts, sameApi, siblingEndpoints, wiring, ... }`。
6 つの枠のどれか 1 つに必ず入り、`summary.rows` と各枠の合計が一致する。行の 向き は `direction`。

- `direction` の値域は **`in` / `out` / `none`**（文字列。`null` は使わない）
  - `in` = 影響を受ける入口、`out` = 影響する先
  - `none` = **この表示経路に 向き を決める関係が無い**（Terraform の定義の縁だけを辿った行）。
    「そのノードに他の有向関係が存在しない」意味ではない。動きの根拠 が無いこととは同義でもない
    （以前の有向縁から 向き を継承した行もある）
  - `null` を使わない理由: 「まだ調べていない」「値が未取得」は `evidence` / `movementEvidence`
    の側で `null` を使うので、`direction` まで `null` にすると「未取得」と「関係が無い」が
    区別できなくなる。値域を文字列 3 つに揃えれば、読み手は未知の値も同じ経路で扱える
  - `none` の行は `tier` を保ったまま中立欄（`wiring` / `sameApi` / `siblingEndpoints`）で受ける。
    Markdown の**向き 列**は「—」と書く（Markdown の先頭注記では Terraform の定義閉包を
    「無方向で閉じる」と書くので、「無方向」という語自体を避けているわけではない）
- **契約の版**: レポート出力のトップレベルには `schemaVersion` が無い（v1 の出力契約のまま）。
  第 46 ラウンドで `direction` の値域に `none` を足したので、**列挙値の追加という旧読者を壊し
  得る拡張**が入っている。旧出力との見分け方は `summary.directionless` キーの有無
  （無い出力が `in` / `out` のみの旧版）。読み手は `direction` の**未知の値を「方向を持たない」
  ものとして扱い**、方向別の欄へ落とさないこと（既定値を中立にしておけば新版の出力でも行が
  消えない）。同じ版で `summary.directionless` / `summary.directionlessPrimary` の 2 キーを
  追加している。**`schemaVersion` はレポート出力へ入れない**（2026-11-15 に人が決定。
  `docs/decisions.md` の決 71）。上の 2 キーの有無で判別する運用で確定させる。
  比較基準の `out/tmp-r29/audit-full`（v1 基準）も**差し替えない**ので、同じ条件で再生成しても
  **既知差分 74 件**が残る（内訳と理由も決 69 / 決 71 に書いてある）
- `direction === "none"` と `movementEvidence === null` は同義ではない（無方向の連鎖でも以前の
  有向縁から 向き を継承して `in` / `out` になる行がある）
- `summary.directionless` = `direction === "none"` の行数、`summary.directionlessPrimary` =
  **`none` の行のうち** 本命（`tier === "primary"`）の行数。**方向別のカウンタ（`entryIn` /
  `entryOut` など）は `none` を数えない**ので、`in` と `out` の合計が 総行数より少なくなるのが正しい
- `--expect` の `direction` は `in` / `out` / `none` / `both` を受ける（既定 `both`）。`both` は
  「向き で絞り込まない」意味で `none` ではない。`none` を指定したときの対象は none の行のうち
  **本命（`tier === "primary"`）で、`sameApi` と兄弟に回らない行**（**`wiring` に回った本命は対象に
  入る**。採点の分母はさらにそのうち `kind === "resource"` の外部リソースだけ）。保存済み 18 レポート
  では **0 行**（`none` の 本命 2 行はいずれも `sameApi` に並ぶ）で、`facts-preempt-none` の回帰テストは
  `wiring` に回った本命を指定する使い方になる
- 実測: 保存済み 18 レポート 441 行中 28 行が `none`（同じ API を定義するノード 17 /
  定義上の関連 9 / 同じコードを使う別の API 2、うち 本命 2）。「同じコードを使う別の API」の
  一覧は Markdown に 向き 列を出さないので、そこは JSON の `siblingEndpoints` で見る

## graph.json（生成物の本体）

```jsonc
{
  "schemaVersion": 1,
  "name": "elsa-core",                 // --name、省略時はルートディレクトリ名
  "root": "folder:.",                  // ルートノードの ID
  "generatedAt": "2026-11-14T03:40:00+09:00",
  "rootPath": "/abs/path/to/repo",
  "producers": [                      // どの断片がこのグラフを作ったかの監査情報
    { "producer": "directory-scanner", "fragment": "graph.scan.json", "role": "fragment", "nodes": 10384, "edges": 1344 },
    { "producer": "csharp-analyzer", "fragment": "graph.csharp.json", "role": "fragment", "nodes": 41805, "edges": 52351 },
    { "producer": "annotation", "fragment": "annotations.orders-api.json", "role": "annotation", "nodes": 1, "edges": 8, "metadata": 3 }
  ],
  "stats": { "directory-scannerNodes": 10384, "csharp-analyzerNodes": 41805, "folders": 2839, "files": 7207, "projects": 336, "solutions": 2, "signalFiles": 898, "csharpFiles": 6754, "csharpParseFailures": 0, "csharpTypes": 8223, "csharpMembers": 32572, "csharpEdges": 52351, "csharpUnresolvedCalls": 96644, "csharpRejectedTypeFiles": 1010, "csharpRejectedTypes": 1260, "csharpEdge_accesses": 13788, "csharpEdge_attribute": 1004, "csharpEdge_calls": 14607, "csharpEdge_creates": 4303, "csharpEdge_implements": 1700, "csharpEdge_inherits": 1316, "csharpEdge_references": 15633, "handlerEdges": 0, "nodes": 51179, "edges": 53521, "orphans": 0, "warnings": 97 },
  "nodes": [ /* Node */ ],
  "edges": [ /* Edge  */ ]
}
```

`producers[].nodes` は断片ごとの生成数で、マージ後のノード数とは一致しない（同じ ID は 1 つに畳まれる）。
csharp-analyzer の断片は「型 8,223 + メンバ 32,572 + `rejectedTypes` を持つ .cs ファイル 1,010 = 41,805」。
`.cs` の file ノードは階層側（directory-scanner）が全ファイル分を作るので、アナライザ側は
`rejectedTypes` を乗せるファイルだけ、明示的に file ノードを出す。

### Node

| フィールド | 意味 |
| --- | --- |
| `id` | グラフ全体で一意。下の「ID 規則」を参照 |
| `kind` | `folder` `solution` `project` `file` `type` `member` `resource` |
| `name` | 表示名（フォルダ名、クラス名、メソッドシグネチャの短い形） |
| `parent` | 階層の親ノード ID。**階層は `parent` だけで決まる**（ビューアもこれでツリーを作る）。ルートは `null` |
| `path` | リポジトリルートからの相対パス（`resource` は `.tf` のパス） |
| `metadata` | 自由な辞書。静的解析の属性と注釈の `set` がマージされる |

以下は demo / elsa-core の実出力から採取した、`kind` ごとの実際の key だけ。
（未知の key が来てもビューアはそのまま表に表示するので、注釈で自由に増やしてよい）

- `folder` — `rollup: { types, members, files, projects, resources, folders }`（配下の再帰集計。merge が計算）
- `project` — `targetFramework` `rootNamespace` `assemblyName` `packageReferences[]` `signals[]`
- `file` — `language` `signals[]`（AWS / DB のヒント） `rejectedTypes[]`
  （候補は見つかったが張れなかった型名。型引数の数が合わない／`using` も `global using` も無く
  到達不能。13 件目以降は `rejectedTypeKinds` に種類数。）注釈で正しい候補を張すための入力になる
- `type` — `csKind`(`class`/`struct`/`interface`/`enum`/`record`/`delegate`) `namespace` `line` `file` `modifiers[]` `baseTypes[]` `memberCount` `static` `abstract` `generic` `alsoDeclaredIn[]`（partial の他ファイル）
- `member` — `memberKind`(`method`/`property`/`constructor`/`field`/`event`/`enum-member`) `signature` `line` `visibility` `returns` `static` `async` `overloads`（2 以上のときの件数のみ） `otherSignatures[]`（オーバーロードの残りのシグネチャ） `unresolvedCalls[]`（決まらなかった呼び出しの表記。並列走で順が決まらないので辞書順に並べた先頭 8 件を載せる） `unresolvedKinds`（種類数。掲載した 8 件を超えたときだけ出る） `unresolvedTotal`（出現の総数。同じ表記の重複や上限超過で、掲載した件数より総数が多いときに出る。8 種類に満たなくても重複があれば付く）
- `resource` — `resourceType`(`aws_lambda_function` など) `category`(`lambda`/`stepfunctions`/`apigateway`/`dynamodb`/`rds`/`s3`/`sqs`/`sns`/`secretsmanager`/`iam`/`custom`) `terraformAddress` `file` `filename` `provider` `managedBy` `referencedOnly`、リソース種別固有の値（`function_name` `handler` `runtime` `memory_size` `uri` `http_method` `rest_api_id` `path_part` `parent_id` `stage_name` `route_key` …）。
  API Gateway は `path_part` 単体では HTTP のパスにならないため、`parent_id` を辿って組み立てた値を
  `apiPath`、method と組んだ表示名を `endpoint`（`POST /orders`）として付ける（決まらないときは張らない）。
  `data` ブロック由来は `provider: "data"` と `dataSource: true`
  HCL の文字列リテラルから取った値は outer の引用符を除いて保存する（`handler` をそのまま
  検索や `member:` との照合に使えるようにするため）

メソッドの `name` は `ExecuteAsync`、`signature` は `public Task<...> ExecuteAsync(CancellationToken)`。
オーバーロードは同じ ID に集約し、件数を `overloads`、2 件目以降のシグネチャを `otherSignatures[]` に入れる。
引数リスト単独の key（`params`）や `virtual` / `override` は出さない（`signature` に modifier が含まれる）。

### Edge

```jsonc
{ "id": "calls:member:A.B->member:C.D", "source": "...", "target": "...",
  "kind": "calls", "count": 3, "provenance": "static", "line": 42,
  "detail": "この呼び出しの根拠（receiver 式など）。注釈の note もここに入る",
  "metadata": { "confidence": 0.9 } }
```

エッジの key は `id` `source` `target` `kind` `provenance` `count` `line` `detail` `metadata` の 9 つ。
注釈ファイル側の `note` は `detail` に、`confidence` は `metadata.confidence` に写るので、
トップレベルの `note` / `confidence` は存在しない。

`id` は `${kind}:${source}->${target}`。同じきょう着の別呼び出しは `count` を増やし、
`line` は最初の発生箇所に固定するので、生エッジを畳んでも行番号は残る。

| `kind` | 出所 | 意味 |
| --- | --- | --- |
| `contains` | scan | `.sln` → csproj の包含だけ。フォルダ→…→メンバーの階層は `contains` ではなく `parent` で持つ |
| `project-reference` | scan | csproj → csproj |
| `calls` `creates` `accesses` `references` `inherits` `implements` `attribute` | cgd | C# 構文から決まる依存。`provenance` は `static` |
| `invokes` `triggers` `references` | scan-terraform | `.tf` 内の参照。`invokes` は Step Functions→Lambda、`triggers` は API Gateway→Lambda |
| `deploys` `exposes` `exposed-by` `reads` `writes` `annotates` | annotation | csproj / メンバ と外部リソースの対応付け。普通 `provenance: llm` |
| `handler` | merge | Terraform の `handler = "Assembly::NS.Type::Method"` を C# の `member:` に解決した縁。`provenance: terraform`。解決できない handler は張らず merge の警告に出す（注釈で埋める） |

`provenance` は `static`（静的解析）/ `terraform`（HCL と Terraform 由来の解決）/ `llm`（注釈）/ `human`（人がビューアで追記）。
ビューアの上部チップは `kind` と `provenance` の両方で絞り込める。

## ID 規則（生成側の契約）

producers（C# 解析・ディレクトリ走査・Terraform 走査・注釈）が同じ ID を使うための規則。

| ノード | 形 | 例 |
| --- | --- | --- |
| folder | `folder:.<relDir を / で連結>`（ルートは `folder:.`） | `folder:core/src/modules/Elsa.Workflows.Core` |
| file | `file:<相対パス>` | `file:src/App/Program.cs` |
| project | `project:<csproj の相対パス>` | `project:src/App/App.csproj` |
| solution | `solution:<sln の相対パス>` | `solution:Elsa.sln` |
| type | `type:<名前空間>.<外側クラス>/<内側クラス>` | `type:Orders.Api.Functions` |
| member | `member:<型の qualified>.<メンバ名>`（コンストラクタは `.ctor`） | `member:Orders.Api.Functions.CreateOrder` |
| resource（terraform） | `tf:<address>` | `tf:aws_lambda_function.orders_api` |
| resource（注釈で追加） | `ext:<種別>/<名前>` | `ext:rds/orders-analytics` |

型の `qualified` は名前空間とクラス名を `.`、ネストを `/` でつなぐ。
**型パラメータ（アリティ）は ID に含まない**ため、同じ名前空間に `Box` と `Box<T>` が併存すると両者は同じ `type:` ID に統合される
（別々に知りたいならどちらかを別名前空間に置くか、注釈で区別する）。
この ID を変えると既存の注釈が全部はがれるので、変えたい場合は注釈側の移行も一緒にやる。

## ビューア用ペイロード（graph.data.js）

HTML に埋め込むときは key 名を省いた配列エンコードにする（20MB 程度まで圧縮される）。

```js
window.__CSDG__ = {
  v: 1, name, root, stats,
  nodeKinds: ['folder','file',...], edgeKinds: [...], provenances: [...], details: [...],
  nodes: [[id, kindIdx, name, parentIdx, path, meta], ...],
  edges: [[sourceIdx, targetIdx, kindIdx, count, provIdx, detailIdx, line], ...]
};
```

`render.mjs` が `viewer/template.html` の `__CSDG_INLINE__`（`<script id="graph-data">` の中身）を
この 1 行で置き換える。データと HTML を分けて配りたいときは、その `<script>` タグを
`<script src="graph.data.js"></script>` に差し替えたテンプレートを `render.mjs --template` に渡す。

## annotations.json（後付け情報のスキーマ）

`merge.mjs --annotation <file>` に渡す。複数ファイルの指定可、順序は結果に影響しない。

```jsonc
{
  "schemaVersion": 1,
  "producer": "llm",                       // llm | human | <任意の工具名>
  "generatedAt": "ISO-8601",               // 任意
  "nodes": [                               // 既存ノードと同形のオブジェクト（id 必須）
    { "id": "ext:s3/orders-archive", "kind": "resource", "name": "orders-archive",
      "parent": "folder:infra", "metadata": { "category": "s3" } }
  ],
  "edges": [
    { "source": "member:...",              // source か sourceMatch のどちらか
      "sourceMatch": { "kind": "project", "path": "src/A/A.csproj", "name": null },
      "target": "tf:aws_lambda_function.x",// target か targetMatch
      "kind": "deploys",                   // 上の Edge 表のいずれか（新 kind も可）
      "provenance": "llm",
      "confidence": 0.9,                   // 0..1、任意
      "note": "根拠",                       // 必須と思ってよい
      "detail": "任意の補足" }
  ],
  "metadata": [
    { "match": { "kind": "file", "path": "src/A/Repo.cs" },   // match か target
      "set": { "owner": "orders-team" } }                      // メタデータへマージ
  ]
}
```

`resolveSelector` は `kind` / `path`（部分一致）/ `name`（部分一致）/ `id` で候補を選び、
- 0 件 → 警告出してスキップ
- 1 件 → 採用
- 2 件以上 → 曖昧として警告してスキップ（`merge` の stderr に出る）

なので **LLM は `graph.json` を読んでから書く**、が前提。ID が既知なら `source`/`target` を直接書く。

## ビューアの動作状態

- `localStorage` キー `csdg:annotations` に、画面で後付けした注釈を JSON 配列で保存する。
  起動時にこれを読み直してグラフへ適用し、「注釈 JSON」ボタンの書き出し対象にも入れるので
  **リロード → 書き出し → `merge.mjs --annotation` の往復が壊れない**（リロード前にブラウザの
  注釈を追加した場合も、書き出しにはマージ後の 1 件として出る）。
- 詳細パネルの注釈フォームは 3 種類。すべて `provenance: human` で保存する。
  1. **既存ノードと紐づける** — 相手ノードを検索して選び、`csproj → tf:aws_lambda_function.…` のように既存ノードどうしを結ぶ
  2. **外部リソースを後付けする** — `ext:<種別>/<名前>` のノードを作って結ぶ（既存 ID と衝突したら既存に結ぶだけ）。
     テーブル / カラムのように単位が入れ子のものは `parent` を入れ子にすればそのまま段階展開になる
     （実例 [examples/annotations.storage.json](../examples/annotations.storage.json)）
  3. **メタデータを後付けする** — 選択中のノード（csproj でも .cs でも）に任意の key / value を足す
  同一の (source, target, kind) をもう一度追加した場合はエッジを増やさず `count` を加算する。
- URL ハッシュ `#expand=<id,id,...>&select=<id>` で展開状態を共有する（「表示を共有」ボタン）。
- 描画エッジが 900 本を超えると、`count` の大きい順に絞って上部に警告を出す。
  `references` / `accesses` はノイズになるので初期状態では隠している（チップで出せる）。
- 1 ノードの子は 400 件まで描画（ツリーパネルは 400 件まで）。`--exclude` で対象を絞るのが正しい解決。
