# スキーマリファレンス

`graph.json`・ビューア用ペイロード・ノード/エッジ ID・注釈（annotations.json）の形。
数値は elsa-core を走らせたときの実出力にあわせてある。

## graph.json（生成物の本体）

```jsonc
{
  "schemaVersion": 1,
  "name": "elsa-core",                 // --name、省略時はルートディレクトリ名
  "root": "folder:.",                  // ルートノードの ID
  "generatedAt": "2026-11-14T03:40:00+09:00",
  "rootPath": "/abs/path/to/repo",
  "producers": ["scan", "csharp", "terraform", "annotation:annotations.json"],
  "stats": { "nodes": 51309, "edges": 52174, "byKind": { "type": 8216, "member": 32541 }, "byProvenance": { "static": 51004, "llm": 8 } },
  "nodes": [ /* Node */ ],
  "edges": [ /* Edge  */ ]
}
```

### Node

| フィールド | 意味 |
| --- | --- |
| `id` | グラフ全体で一意。下の「ID 規則」を参照 |
| `kind` | `folder` `solution` `project` `file` `type` `member` `resource` |
| `name` | 表示名（フォルダ名、クラス名、メソッドシグネチャの短い形） |
| `parent` | 階層の親ノード ID。`contains` エッジと同時に張られる。ルートは `null` |
| `path` | リポジトリルートからの相対パス（`resource` は `.tf` のパス） |
| `metadata` | 自由な辞書。静的解析の属性と注釈の `set` がマージされる |

`kind` ごとの決まった `metadata`:

- `folder` — `rollup: { types, members, files, projects, resources, folders }`（配下の再帰集計、merge が計算）
- `project` — `targetFramework` `rootNamespace` `assemblyName` `outputType` `packageReferences[]` `signals[]`
- `file` — `lines` `usings[]` `signals[]`（AWS/DB のヒント）
- `type` — `typeKind`(`class`/`struct`/`interface`/`enum`/`record`/`delegate`) `visibility` `sealed` `static` `partial` `alsoDeclaredIn[]`
- `member` — `memberKind`(`method`/`property`/`constructor`/`field`/`event`/`enumMember`) `signature` `line` `visibility` `returns` `params[]` `async` `static` `virtual` `override` `abstract` `overloads` `unresolvedCalls[]`
- `resource` — `resourceType`(`aws_lambda_function` など) `category`(`lambda`/`stepfunctions`/`apigateway`/`dynamodb`/`rds`/`s3`/`sqs`/`sns`/`secretsmanager`/`iam`/`custom`) `terraformAddress` `file` `function_name` `handler` `runtime`

メソッドの `name` は `ExecuteAsync`、`signature` は `public Task<...> ExecuteAsync(CancellationToken)`。
オーバーロードは同じ ID に集約され、`metadata.overloads` に件数と全シグネチャが入る。

### Edge

```jsonc
{ "id": "calls:member:A.B->member:C.D", "source": "...", "target": "...",
  "kind": "calls", "count": 3, "provenance": "static", "line": 42,
  "note": "注釈のときだけ入る根拠", "confidence": 0.9, "detail": "optional" }
```

`id` は `${kind}:${source}->${target}`。同じきょう着の別呼び出しは `count` を増やし、
`line` は最初の発生箇所に固定するので、生エッジを畳んでも行番号は残る。

| `kind` | 出所 | 意味 |
| --- | --- | --- |
| `contains` | scan/cgd | 階層（フォルダ→ファイル→型→メンバー）。`parent` とは別軸で常にある |
| `project-reference` | scan | csproj → csproj |
| `calls` `creates` `accesses` `references` `inherits` `implements` `attribute` | cgd | C# 構文から決まる依存。`provenance` は `static` |
| `invokes` `triggers` `references` | scan-terraform | `.tf` 内の参照。`invokes` は Step Functions→Lambda、`triggers` は API Gateway→Lambda |
| `deploys` `exposes` `exposed-by` `reads` `writes` `annotates` | annotation | csproj / メンバ と外部リソースの対応付け。普通 `provenance: llm` |

`provenance` は `static`（静的解析）/ `terraform`（HCL）/ `llm`（注釈）/ `human`（人がビューアで追記）。
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

- `localStorage` キー `csdg:annotations` に、画面で「紐づける」で作った注釈を JSON 配列で保存する。
  「注釈 JSON」ボタンで `annotations.json` としてダウンロードでき、リポジトリの注釈ファイルへ
  追記すれば再生成時に本物になる（`provenance` は `human`）。
- URL ハッシュ `#expand=<id,id,...>&select=<id>` で展開状態を共有する（「表示を共有」ボタン）。
- 描画エッジが 900 本を超えると、`count` の大きい順に絞って上部に警告を出す。
  `references` / `accesses` はノイズになるので初期状態では隠している（チップで出せる）。
- 1 ノードの子は 400 件まで描画（ツリーパネルは 400 件まで）。`--exclude` で対象を絞るのが正しい解決。
