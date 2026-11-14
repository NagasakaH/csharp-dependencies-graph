# 決定記録

自律実行で切り続けた判断と、その根拠になった実測値を残す。やり直しが必要な箇所は
「再検討」に書いた。

| # | 決定 | 根拠（実測） | 取り替える条件 |
| --- | --- | --- | --- |
| 1 | 静的解析は Roslyn の構文解析のみ（MSBuild / SemanticModel を使わない） | elsa-core はビルドできない状態でも 6,754 ファイルを 3 秒で解析。`dotnet restore` 不要なので任意リポジトリに置ける | 解決できない呼び出し 96,772 件が実用上つらくなったら SemanticModel 版を追加する |
| 2 | csharp-ls は依存に入れない | 目的は「静的解析ツールで機械的に関連付ける」こと。Language Server は対話用でバッチ向かない。自作の構文走査で要求エッジ（calls / creates / accesses / references / inherits / implements / attribute）を出せた | シンボル解決精度が壁になったら LSP クライアントとして併用する |
| 3 | ノード ID は producers 間の契約として文字列規則に固定 | 注釈（LLM）が ID を書いても再生成で生き、ビューアの手動注釈もエクスポート後に同一 ID で解決できる | ID 規則の変更は注釈の移行を伴うので、スキーマ変更として扱う |
| 4 | オーバーロードと部分クラスは 1 ノードに集約 | 40,795 ノード / 8,223 型（部分クラス 273 型を統合）。オーバーロード別ノードは探索時のノード爆発を起こす | 呼び出し sites をオーバーロード別に区別したい需要が出たら edge 側に `detail` を足す |
| 5 | フォルダ集計（型・メンバー数）は merge 側の再帰で持つ | フォルダ 2,826 件それぞれに配下数を出さないと、上位ビューで「どこを開くか」が判断できない。ロールアップ未実装時は全フォルダが `型 0` を表示し、誤情報だった | 集計が再生成時間を押すなら増分計算へ |
| 6 | 上位ビューは依存エッジを表示中の祖先へ持ち上げる | ルート 15 ノード・描画 40 エッジまで畳めて、core→studio 等のmodule 間依存が見える。全 52,221 生エッジを描画していたら用途を失う | 持ち上げ後の重みが意味をなさない場合は件数でなく edge 種別で集計 |
| 7 | `references` / `accesses` は初期状態で隠す | elsa のルートビューで 62 本 → 40 本に減り、カオスだった初期表示が読めるようになった | チップで即出せるので既定の議論は不要 |
| 8 | レイアウトは深さ別レイヤ＋重心緩和をやめ、ツリー沿った整列レイアウトへ全面交換 | 重心版は同一レイヤの y が層ごとに 0 から始まり、51k ノードのグラフで箱が重なって読めなかった（スクリーンショットで確認）。整列版は重なりゼロ | 深さ 6 以上の破線が長く交差するならリーフの折返し引入れ |
| 9 | ラベルは `textLength` で幅固定に切る | ラベルが box を超えて はみ出すと `<g>` の bbox が広がり、クリックが空振りした（`elementFromPoint` が svg を返した実測）。依存展開が全滅していた | 文字種で切り出しが粗い場合は描画時測定に寄せる |
| 10 | 依存先ノードは「ゴースト」として起点ノードの子に置く | `isAncestorVisible` による除外が、畳んだ型の兄弟を誤って弾き「出力 5」でも 0 増（18 → 18）だった。ゴースト専用配置にして 18 → 22 | 起点が増えると混むため、ホップ数は初期 1 にして周辺ボタンで明示 |
| 11 | 外部情報は `annotations.json` を再生成時にマージする（ビューア側は localStorage のみ） | 画面操作で作った注釈も JSON 出力 → リポジトリへ追記 → 再生成で本物になる。単一方向のフローにしないと同期地獄になる | 複数人同時編集が起きたら注釈の分離ファイル運用（1 ファイル 1 チーム）を勧める |
| 12 | Terraform は brace 計数の簡易パーサで十分 | デモ 16 リソースを取り逃しなく拾い、`invokes` / `triggers` が自動生成。HCL 完全対応は Lambda 紐づけの要求に対して過剰 | `for_each` / module 展開が必要になったら python-hcl2 等を足す |
| 13 | 検証は「グラフに効く操作」を 24 項目に固定し、対象は graph.json から自動選択 | 手動クリック確認 → `verify.mjs` で自動化。demo 24/24、elsa 22/22（Terraform 検査は該当が無いとき自動省略）。検索語・ファイル・型・メソッドを自動選択なので新規プロジェクトでもそのまま通る | 新機能追加時は検査を 1 項目増やす（検査が増えない機能は怪しい） |
| 14 | 静的解析は「決まらない関係を作らない」を精度テストで固定する | `System.Action Go = b.Run; Go();` が `this.Go()` として `static` エッジになっていた（レビュー指摘）。receiver 不在の呼び出しはスコープ変数・デリゲード型メンバーを弾く。`skill/scripts/test-analyzer.mjs` が 43 項目を回す | 誤エッジを見つけたら fixture を足して回帰テストにする（常に） |
| 15 | `var` は構文木の両形を受けつける | `IsVar` が `PredefinedTypeSyntax` しか見ず、`var x = new Foo(); x.Bar();` の calls が黙って落ちていた。修正で elsa-core のエッジが 52,221 → 54,776（+2,555）、未解決呼び出し 96,772 → 95,851 | 型推論を足すときは必ず「増えた件数」を実測して記録する |
| 16 | ビューアの後付け注釈は `human`、書き出し＝復元対象 | `llm` 扱いだった手動追記の出所を契約どおり `human` に。localStorage 復元を `exportable` にも載せ、リロード → 注釈 JSON → `merge --annotation` の往復を検査項目にした | 注釈の上書き・削除の UI は未実装（Needed 時に） |
| 17 | 局所名は「出現位置 + 宣言領域（ブロック）」で解決する（メソッド全体で 1 辞書にしない） | `{ var x = new A(); x.Go(); } { var x = new B(); x.Go(); }` が B に一本化され A 側が消えていた（レビュー指摘）。宣言を `(位置, 型)` の列で持ち、識別子の直前に見えた宣言で引く。ラムダ引数（型省略）・ローカル関数・LINQ の範囲変数も名前は塞ぐので `this.X` に化けない。ローカル関数は宣言前でも呼べるため、位置ではなくメンバ全体で遮蔽する | 宣言の列は常に Pos 昇順を保ち、2 ラウンド目の推論結果は同じ宣言位置へ書き戻す（末尾に足すと後勝ちになり、後続ブロックの宣言を潰した）。宣言領域は `DeclarationSpace` が C# の宣言領域に近い節まで上る。内側ブロックの変数が外側の後続に漏れて同名フィールドを隠す誤りが消え、elsa-core −24 エッジ（55,081 → 55,057、未解決 +12） |
| 18 | 型表記はジェネリックを畳む前のものを残す | `Normalize` が `List<Item>` を `List` に畳むため `foreach (var x in items)` の要素型が決まらず、calls / accesses が黙って消えていた。`ExprType.RawType` を持ち、要素型は畳む前の文字列から取る（`await` の内側も畳む前に剥がす） | 型推論を足すときは増減件数を必ず記録する |
| 20 | ラムダ引数・catch 変数・switch の節と腕を宣言領域の境界にする（`if` は境界にしない） | 第 4 ラウンドレビュー両名の実測: ラムダ引数と catch 変数が外側へ漏れて後続の同名フィールドを化かし、逆に `if (o is not Gadget x) return;` の `x` を `if` の中に閉じるとガード節の後の参照がフィールドに化けた | 境界の集合は推測せず `dotnet build` で実測して決めた（`if` 条件の out var / パターン変数は外側ブロックまで見える。`while` / `do` / `for` / `using` / `catch` / switch の節・腕はその中だけ）。`out var` は呼び出し先の out 引数を見ないと型が決まらないので決めず、名前だけ塞ぐ。実測 elsa-core +24 エッジ・削除 0（55,057 → 55,081） |
| 21 | 境界は「ノードの種類」ではなく「宣言の種類と位置」で決める | 第 5 ラウンドレビュー（codex）の実測: 通常のローカルは `switch` の節をまたいで別節に見えるのに節で閉じていた／ブロックなしの入れ子 `if` のパターン変数が外側に出る。C# は `if` の**条件** out var・パターン変数を外側ブロックに出すが、入れ子 `if` の**本体**で宣言されたものはその入れ子まで。`switch` は条件式のパターン変数だけ節に閉じ、本体のローカル宣言は switch ブロック全体で共有する | `DeclarationSpace` は `IfStatementSyntax` を通すか閉じるかを「宣言ノードが条件の内側か」で、`SwitchSectionSyntax` を「節のラベルの内側か」で判断する。`using var x = ...`（本体なし）も境界にしない。タプル分割（`var (a, b) = ...`）と LINQ の `join` / `into` の範囲変数は型を決めず名前だけ塞ぐ。実測: elsa-core の静的エッジは 33ebd9e と同一（追加 0・削除 0＝化けの解消は既存エッジを変えない）、解析テスト 29 → 37 項目 |
| 23 | パターン宣言の名前も漏れなく宣言する（型は書かれていれば使い、無ければ名前だけ塞ぐ） | 第 6 ラウンドレビュー（agy）の実測: `is var x` / `case var x:` の `VarPatternSyntax` を宣言していなく、`x` が外側の同名フィールドに化けて誤エッジになっていた（`dotnet build` 0 エラーの再現付き） | `VarPatternSyntax` は型を決められないので `""` で名前だけ塞ぐ。`RecursivePatternSyntax` の末尾 designation（`is Widget { Size: > 0 } x`）は型がパターンに書かれているのでその型で宣言する。実測 elsa-core +2 エッジ・削除 0（55,081 → 55,083）。追加 2 本は `is ParticipantEffect { Undo: true } effect` の `effect.Slot` と `is BpmnProcess { IsRootScope: true } nested` の `nested.Id` で、どちらも実コードの正しい解決 |
| 24 | 分割形式の foreach（`foreach ((Gadget item, int n) in ...)`）も `DeclarationSpace` の境界にする | 第 7 ラウンドレビュー（agy）実測: 型付き・`var` どちらのタプル分割 foreach でもループ変数がループ後の同名フィールドに化けていた（`dotnet build` 0 エラーの再現、フィールドを消すと CS0103） | `ForEachStatementSyntax` だけ見ていた境界に `ForEachVariableStatementSyntax` を追加した。宣言を拾う `case` と境界の型のリストは対で増やさないと、素通りして外側ブロックまで漏れる。実測 elsa-core は追加 0・削除 0（この形が存在しない）、再現 probe は期待どおり `Gadget.Handle` 1 / `Widget.Handle` 1 |
| 25 | パターンの designation はノード種類ごとに漏れなく拾う（`var` / 再帰 / リスト） | 第 6・7 ラウンドで `VarPatternSyntax` → `RecursivePatternSyntax` → `ListPatternSyntax` の順に漏れが出た。Roslyn のパターンは型ごとにノードが別なので、1 種類直しても隣が残り続ける | 型がソースコードに書かれているもの（`is Widget { Size: > 0 } x`）はその型で宣言し、書かれていないもの（`is var x`、`case var x`、`is [1, 2, ..] rest`）は名前だけ塞ぐ。それぞれ `dotnet build` を通る fixture を追加して回帰テストに入れる |
| 26 | 同名型が複数あり判別できないとき、得点が並んだ候補に張って `ambiguous` と印す | 1 つに絞ると間違った方を 1 本張ることになり、0 件にすると正しい `creates` を大量に失う（意味解析なしでは `using` と名前空間しか手がかりがない） | 得点は「同じ名前空間 6 / 内側 3 / `using` 完全一致 5 / `using` 内側 1」。並んだ上位は最大 2 本まで張り `detail` に `ambiguous:` を付ける（UI ではエッジのツールチップに出る）。得点 0 の并列は張らない。実測 elsa-core 429 本（`creates` 312 / `references` 104 / `calls` 13） |
| 27 | 注釈でテーブル / カラムを後付けするとき、単位を入れ子のノードにする（`parent` を辿るだけ） | エッジを増やさず、既存ノードの `metadata` に文字列で押し込むより段階展開できるし孤児にもならない | 実例 `examples/annotations.storage.json`（`ext:rds` → `ext:rds-table` → `ext:rds-column`）。作成時に ID を 1 件まちがえたが `merge.mjs` が `アノテーションのエッジ解決失敗` で警告し、修正後は警告 0 件・74 / 64 で裏づけた |
| 28 | 同名型の候補は「到達できるか」と「型引数の数」で絞る。張れなかった名前は `.cs` ノードに残す | ユーザーがグラフをレビューに使った逆引きの質問で、`Elsa.Studio.UIHints.Components.Dictionary`（BCL の `Dictionary<string, object>` を使っているだけ）に **799 本**（うち 471 本が `core/` から）誤バインドしていた。単純名一致 1 件なら即張る短絡と、到達性の無しが原因 | ①  usage 側に型引数が書かれていれば宣言の `Arity` と一致する候補だけ（書かれていなければ発動しない＝一方向のみ）② どの候補にも到達できない（同じ名前空間・内側名前空間・`using` 完全一致・`using` 内側のいずれでもない）場合は単一候補でも張らない。`global using` は宣言ディレクトリをキーに子孫から見えて、MSBuild の暗黙 global using（`obj/*.GlobalUsings.g.cs`）は cgd の視野に無いので「到達不能」と判定される＝仕様。拒否した名前は `metadata.rejectedTypes` に残し注釈の候補にする。実測 elsa-core 静的エッジ 53,913 → 52,192（除去 2,005 / 追加 284、`references` −687・`creates` −583・`calls` −237・`attribute` −213・`inherits` −14・`accesses` +11・`implements` +2）、`Dictionary` の誤バインド 799 → 3（残りは正しい studio 側）、除去上位は `Dictionary` 796 / `JsonSerializer` 217 / `ShellFeature` 187（実体は外部パッケージ `CShells.Features`）/ `List` 123。結合ハブの上位一覧もこの修正後才有効（修正前は同名異物が上位を占めていた） |
| 29 | Terraform の `handler` 文字列は merge 側で `member:` に解決し、当たらなければ警告して張らない | 逆引きが `project:` で止まり「この Lambda の実装はどこか」に答えられなかった。推測で csproj に落とし込むと以降の辿り先が汚れる | `Assembly::NS.Type::Method` と `NS.Outer+Inner::Method` に対応（ネストは `NS.Outer/Inner` に正規化）。実在ノードに当たったときだけ `kind: handler` / `provenance: terraform` を張り、外れたらは `handler の解決失敗` 警告（＝注釈で埋めるべき箇所）。HCL の文字列メタデータは outer の引用符を除いて保存（`"NS.Type::Method"` のままでは照合・検索に使えない）。実測 demo 74 / 64 → 74 / 66、警告 0 件。Lambda から 3 ホップで実装 5 メソッド + `exposed-by` の公開経路まで出る |
| 30 | 影響範囲・逆引きはビューアではなく `query.mjs`（CLI）で提供し、曖昧な起点は推測しない | ブラウザの ⇧ / ⌥⇧クリックは 1 ホップまで。レビューでは「変更ファイル → 外部リソースに着くか」を多段で問いたく、CI にも出したい | BFS + `--dir in|out|both` / `--kind` / `--provenance` / `--target-kind` / `--via-parent`（階層を降りて csproj 注釈をコードへ伸ばす）/ `--changed <ファイル一覧>`（無いパスは最も近い親フォルダへ）/ `--json`。名前が複数ヒットしたら候補を印して exit 2（merge のセレクタと同じ規律）。検査は `fixtures/query/graph.json` + `test-query.mjs` の 12 項目（.NET 不要）。実測: 変更ファイル → 3 ホップで `deploys` の Lambda、カラム → `Order.Id` → `CreateOrder` → 呼び出し 4 件 + `POST /orders` |
| 22 | Roslyn の API 名は推測せず実測する | `IVariableDesignationSyntax` / `VariableDeclaratorSyntax.Designation` / `ForEachVariableStatementSyntax.Designation` / `GroupClauseSyntax.Into` / `QueryContinuationSyntax.Into` はこの Roslyn 4.12 には存在せず、推測で書いて 6 回ビルドを壊した | リフレクションで実際のプロパティ一覧を出してから書く（`/tmp` の使い捨てプロジェクトで `GetType().GetProperties()`）。`ForEachVariableStatementSyntax.Variable` は `ExpressionSyntax` なので `is DeclarationExpressionSyntax` で下りる |
| 19 | メンバ内の型決めは 3 ラウンド（宣言順 → 初期値の推論 → `foreach` の要素型） | `var items = Build();` の型が決まる前に `foreach (var x in items)` を処理すると要素型が空のままだった。遅らせた foreach を 3 ラウンド目で埋め、`new T().P` も型の出所として認める。elsa-core で +117 エッジ・未解決 −111（54,964 → 55,081） | 推論を追加するたびに「増えた edge」と「減った unresolved」を両方記録する（片方だけだと化けた可能性がある） |

## 再検討

- ルート直下に `.cs` が 1 枚も多いリポジトリ（モノレポ直置き）では、ルートビューが縦に長くなる。
  列の分割またはフォルダ単位の折りたたみが必要になるかもしれない。
- 51k ノードの HTML は 20MB。別ファイル配布（`graph.data.js` を分ける）は用意したが、
  ビューア側の初期描画をさらに絞る余地がある。
- `deploys` / `exposed-by` の向きは運用の語彙に依存する。チーム語彙が決まったら
  `reference/schema.md` の kind 表を締める。
- 型引数の数による絞り込みは一方向だけ（使用側に `<...>` が書かれていない参照は、同名の
  ジェネリック宣言にそのまま張る）。宣言側がジェネリックで利用側が裸のケースが残るため、
  誤バインダの残存率は未測定。次に取り組むなら `using` の解決を厳密化して得点を締める方向。
