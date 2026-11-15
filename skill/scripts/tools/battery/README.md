# 回帰バッテリーの道具と固定入力

`report.mjs` の出力契約が変わっていないかを測る道具と、それが入力にする固定データ。
**実行手順と順序は `out/loop/protocol.md` §4-3**（最初に必ず
`python3 skill/scripts/tools/check-battery-inputs.py` を走らせる）。

第 50 ラウンド双人レビュー（agy P2）で `out/tmp-*` からここへ移した。`out/tmp-*` はディスク
掃除の対象で、そこに唯一のコピーを置くのが過去 2 回の事故（第 48 ラウンドの全 250 回 ENOENT
なのに「適合」、第 49 ラウンドの入力表が実在しないファイルを指していた）の元凶。

## v1 の出力契約を突き合わせる

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `../regen-audit.py` | `python3 skill/scripts/tools/regen-audit.py skill/scripts/report.mjs out/audit-current --force` | 18 件の JSON を今の版で作り直す |
| `v1diff.py` | `CGD_AUDIT_OUT=out/audit-current python3 skill/scripts/tools/battery/v1diff.py` | 「**レポート 18 件 / 差分 74 件**」（行 58 + 集計 16。人が差し替えないと決めた既知の定数） |
| `check-dir-rule.py` | `python3 skill/scripts/tools/battery/check-dir-rule.py out/audit-current skill/scripts/tools/battery/baseline-v1` | 「一致 441 / 不一致 0」（v1 基準との突き合わせは 386 一致 / 55 不一致で、55 は既知） |
| `count-none.py` | `python3 skill/scripts/tools/battery/count-none.py out/audit-current` | サマリカウンタ不一致 0・裁定の再集計と一致 |
| `cmp-head-proto.py` | `git show HEAD:skill/scripts/report.mjs > /tmp/head.mjs && python3 skill/scripts/tools/battery/cmp-head-proto.py /tmp/head.mjs skill/scripts/report.mjs` | 「動いた項目 {}」。JSON に触らない変更なら 差分のある条件 0 |
| `same-output.py` | `python3 skill/scripts/tools/battery/same-output.py /tmp/head.mjs skill/scripts/report.mjs` | 「18 条件中 不一致 0 件」。今日 HEAD と比べるのが意味のある使い方（`r43-before.mjs` と比べると不一致 18 件が出てよい） |

`baseline-v1/` が v1 基準の 18 レポート（人が「差し替えない」と決めたもの）。`CGD_AUDIT_BASE`
で別の基準ディレクトリに差し替えられるが、差し替えないことが決まっている

## 縁順・入れ替えで表示が変わらないことを確かめる

| 道具 | 実行例 | 期待する出力 |
| --- | --- | --- |
| `allperm.py` / `allperm-corr.py` | `python3 skill/scripts/tools/battery/allperm.py skill/scripts/report.mjs skill/scripts/tools/battery/min-0.json` | 「縁順 720 通り / 表 1 通り」 |
| `allperm-full.py` | `python3 skill/scripts/tools/battery/allperm-full.py skill/scripts/report.mjs skill/scripts/tools/battery/min-2.json 24` | 「判定: JSON 完全一致」。入力が無い・全実行失敗なら **測らずに**終了 1 |
| `r43-permute.py` | `python3 skill/scripts/tools/battery/r43-permute.py skill/scripts/report.mjs` | 固定 2 条件（`r42-calls-*.json`）で 120 入れ替え → 表 1 通り |
| `find-splits.py` | `python3 skill/scripts/tools/battery/find-splits.py skill/scripts/report.mjs 250 <種> out/tmp-rNN/splits.json` | 「入れ替えで割れた例 0 / 試行 250」。**種は毎回新しく**（使った種は protocol に記録）、出力先も毎回新しいパスを渡す |
| `via-cycle.py` | `python3 skill/scripts/tools/battery/via-cycle.py skill/scripts/report.mjs` | 「18 レポート / 違反合計 0」 |

`min-0.json` / `min-2.json` / `r42-calls-*.json` は順列検査が使う最小グラフ。
`via-cycle.py` は `baseline-v1/` と同じ条件でも自分の手で組み直して走らせる

## 条件の作りかた

上の実行例は `out/loop/protocol.md` §4-3 と**同じコマンド**を貼っている。どちらか一方だけ直して
ズレるのが過去の実事故（第 48 ラウンド）なので、直すときは必ず両方同じへ直す
