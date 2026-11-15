# 回帰バッテリーの道具と固定入力

`report.mjs` の出力契約が変わっていないかを測る道具と、それが入力にする固定データ。
**実行手順と順序は `out/loop/protocol.md` §4-3**（最初に必ず
`python3 skill/scripts/tools/check-battery-inputs.py` を走らせる）。

第 50 ラウンド双人レビュー（agy P2）で `out/tmp-*` からここへ移した。`out/tmp-*` はディスク
掃除の対象で、そこに唯一のコピーを置くのが過去 2 回の事故（第 48 ラウンドの全 250 回 ENOENT
なのに「適合」、第 49 ラウンドの入力表が実在しないファイルを指していた）の元凶。

## 入力の置き場所と終了コード（このフォルダの約束）

第 51 ラウンド双人レビュー（Codex・agy、両名 P2）で、検査器が**入力の欠落と子プロセスの失敗を
成功としていた**のが両名から出た（存在しない `report.mjs` を渡すと `allperm.py` は
「24 通り / 表 1 通り」、`find-splits.py` は「割れた例 0」、`same-output.py` は「不一致 0 件」と
答えて終了 0）。ここで扱うのは 3 つ。

- `_inputs.py` が共通の土台。`repo_root()`（`skill/scripts/report.mjs` を含む祖先を根にする）、
  `require()`（入力が無いなら**測る前に**終了 1）、`report_paths()`（レポートディレクトリが
  無い・空・期待件数と違うなら終了 1）、`require_script()` / `run_json()`（対象の `report.mjs`
  が無い、子が非 0 で終わったら終了 1）、`extra_graphs()`（不変条件・親子整合が足す実グラフの
  **正本の一覧**。`check-battery-inputs.py` も同じ一覧を読む）
- `baseline-v1/` の 18 条件は `summary.graph` に作者環境の一時出力先を記録している。実体は
  `graphs/` に移し、`graph_path()` が対応表 `RELOCATED` でたどる。記録そのものは歴史なので
  書き換えない（基準データは人が「差し替えない」と決まっている）
- 検査器は**終了コードで合否を返す**（`allperm.py`・`cmp-head-proto.py`・`edge-order.py` は
  割れた／差分がある／不一致があれば終了 1）。件数だけ見て人が判断する道具にしない

## v1 の出力契約を突き合わせる

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `../regen-audit.py` | `python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs out/audit-current --force` | 18 件の JSON を今の版で作り直す |
| `v1diff.py` | `CGD_AUDIT_OUT=out/audit-current python3 skill/scripts/tools/battery/v1diff.py` | 「**レポート 18 件 / 差分 74 件**」（行 58 + 集計 16。人が差し替えないと決めた既知の定数なので**終了 1 が正常**。内訳は決 69 / 決 71） |
| `check-dir-rule.py` | `python3 skill/scripts/tools/battery/check-dir-rule.py out/audit-current skill/scripts/tools/battery/baseline-v1` | 「一致 441 / 不一致 0」（v1 基準との突き合わせは 386 一致 / 55 不一致で、55 は既知） |
| `count-none.py` | `python3 skill/scripts/tools/battery/count-none.py out/audit-current` | 「none の行 28 件（同じ API 17 / 定義上の関連 9 / 兄弟 2）」・サマリカウンタ不一致 0・裁定の再集計と一致 |
| `cmp-head-proto.py` | `git show HEAD:skill/scripts/report.mjs > /tmp/head.mjs && python3 skill/scripts/tools/battery/cmp-head-proto.py /tmp/head.mjs skill/scripts/report.mjs` | 「動いた項目 {}」。JSON に触らない変更なら 差分のある条件 0（差分があれば終了 1） |
| `same-output.py` | `python3 skill/scripts/tools/battery/same-output.py /tmp/head.mjs skill/scripts/report.mjs` | 「18 条件中 不一致 0 件」。今日 HEAD と比べるのが意味のある使い方（`r43-before.mjs` と比べると不一致 18 件が出てよい） |

`baseline-v1/` が v1 基準の 18 レポート（人が「差し替えない」と決めたもの）。`CGD_AUDIT_BASE`
で別の基準ディレクトリに差し替えられるが、差し替えないことが決まっている

## 表示の不変条件と親子の整合を見る

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `check-invariants46.py` | `python3 skill/scripts/tools/battery/check-invariants46.py skill/scripts/report.mjs` | 「検査した起動条件 219 件 / 行 5033 件」「**違反合計 0 件**」 |
| `self-consistency.py` | `python3 skill/scripts/tools/battery/self-consistency.py skill/scripts/report.mjs` | 「不一致 0 件」（件数の内訳は版で動くので**違反 0** と終了 0 を見る） |

起動条件は `skill/tests/fixtures/ImpactFacts/*.graph.json`（追跡下）+ `_inputs.extra_graphs()`
（`out/demo/graph.json`・`out/elsa/graph.json`・`out/perf-inputs/v2-big.graph.json`）+
`baseline-v1/` の 18 条件。掃除対象の `out/tmp-*` は読まない。条件数が極端に減ったら
（200 件未満）入力が減った日なので途中で止める

## 縁順・入れ替えで表示が変わらないことを確かめる

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `allperm.py` / `allperm-corr.py` | `python3 skill/scripts/tools/battery/allperm.py skill/scripts/report.mjs skill/scripts/tools/battery/min-0.json` | 「縁順 720 通り / 表 1 通り」（割れたら終了 1） |
| `allperm-full.py` | `python3 skill/scripts/tools/battery/allperm-full.py skill/scripts/report.mjs skill/scripts/tools/battery/min-0.json` | 「判定: JSON 完全一致」。24 とおり想看うなら第 3 引数に `min-2.json 24`。入力が無い・全実行失敗なら **測らずに**終了 1 |
| `r43-permute.py` | `python3 skill/scripts/tools/battery/r43-permute.py skill/scripts/report.mjs` | 固定 2 条件（`r42-calls-*.json`）で 120 入れ替え → 表 1 通り |
| `find-splits.py` | `python3 skill/scripts/tools/battery/find-splits.py skill/scripts/report.mjs 250 <種> out/splits/splits-rNN.json` | 「入れ替えで割れた例 0 / 試行 250」（割れた例があれば終了 1）。**種は毎回新しく**（使った種は protocol に記録）、出力先も毎回新しいパスを渡す。親ディレクトリは作る |
| `via-cycle.py` | `python3 skill/scripts/tools/battery/via-cycle.py skill/scripts/report.mjs` | 「18 レポート / 違反合計 0」。書き出し先を指定しない限りリポジトリへ何も書かない |
| `edge-order.py` | `python3 skill/scripts/tools/battery/edge-order.py` | 「不一致 0 件（0 が期待値）」。`query.mjs` の `--group-by` 集計が縁順に依存しないことの実グラフ side の証拠 |

`min-0.json` / `min-2.json` / `r42-calls-*.json` は順列検査が使う最小グラフ。
`via-cycle.py` は `baseline-v1/` と同じ条件でも自分の手で組み直して走らせる

## 性能ゲート（バッテリーの後に、単独で）

バッテリーが全部緑の日にだけ、ほかの測定を止めてから実行する。タグは毎回新しくする
（同じタグの集計・生ログが 1 本でも有れば測る前に終了 1）。

```sh
bash skill/scripts/tools/paired-gate.sh <新しいタグ>      # 5 組交互・中央値 1.20 以内・RSS 800 MB 以内
```

落ちた日は組ごとの倍率の幅とそのときの load を印字する。**混雑を理由に免除はしない**ので、
静かな窓で新しいタグを使って測り直すのが唯一の通り方（第 50 ラウンド p50d は load 4.7 で
`elsa-folder` 1.49 が出て不合格、静かな窓の p50e で 1.04 を採用）。
生ログ `perf-raw-*.jsonl` が残った実行は不合格として扱う

## 条件の作りかた

上の実行例は `out/loop/protocol.md` §4-3 と**同じコマンド**を貼っている。どちらか一方だけ直して
ズレるのが過去の実事故（第 48 ラウンド）なので、直すときは必ず両方同じへ直す
