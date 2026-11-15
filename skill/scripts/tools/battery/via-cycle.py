# 第 40 ラウンド: 表示経路の連鎖検査（診断を兼ねる）
#
# 検査する不変条件（Astra 裁定 out/loop/r39-astra.md）:
#   表示される経路は常に起点まで遡れる単一の連鎖でなければならない。
#   つまり全ての行で pathRoot == 'start'、path[0] が起点のいずれか、
#   path の中に同じノードが二度出てこない（循環の兆候）、path[-1] == id。
#
# 3 段構え:
#   (1) 最小再現グラフ: policy が role を参照し、lambda `notify` と state machine
#       `order_process` が role を参照、`order_process --invokes--> notify`。
#       閉包側がノードごとに代表を独立に選ぶと notify の代表 via=order_process、
#       order_process の代表 via=notify の相互循環になる（第 39 ラウンド agy 指摘 1）
#   (2) 実事例: demo-iam（起点 tf:aws_iam_role_policy.lambda_dynamo_policy）の 4 行
#   (3) 保存済み 18 レポート（skill/scripts/tools/battery/baseline-v1 と同じ条件）の全行
import json
import os
import pathlib
import subprocess
import sys
import tempfile

import _inputs as IN

def _repo_root(start):
    # __file__ からの段数ハードコードはやめる（道具の置き場所を動かした日に黙って別の
    # ディレクトリをリポジトリの根と誤認した。第 50 ラウンド双人レビュー後に実測）
    for a in [start, *start.parents]:
        if (a / 'skill' / 'scripts' / 'report.mjs').exists():
            return a
    raise SystemExit('リポジトリの根が見つからない（skill/scripts/report.mjs を含む祖先を探した）')


ROOT = _repo_root(pathlib.Path(__file__).resolve().parent)
HERE = pathlib.Path(__file__).resolve().parent
REPORT = str(ROOT / 'skill' / 'scripts' / 'report.mjs')
BUCKETS = [('external', 'in'), ('external', 'out'), ('entries', 'in'), ('entries', 'out'),
           ('artifacts', 'in'), ('artifacts', 'out'), ('sameApi', None),
           ('siblingEndpoints', None), ('wiring', None)]


def run(args):
    with tempfile.TemporaryDirectory() as td:
        out = pathlib.Path(td) / 'o.json'
        p = subprocess.run(['node', REPORT] + args + ['--json', str(out)],
                           cwd=ROOT, capture_output=True, text=True)
        if p.returncode != 0:
            raise SystemExit(f'report.mjs 失敗: {p.stdout[-400:]}{p.stderr[-400:]}')
        return json.loads(out.read_text())


def rows_of(r):
    for sec, sub in BUCKETS:
        for x in (r[sec] if sub is None else r[sec][sub]):
            yield x


def check(r, label):
    # 経路の先頭は起点そのものか、2 段目 walk の種（その行がレポート内にあり、
    # その経路がさらに起点へ繋がる）なら可。起点展開（`startIds` は `--limit` で
    # 切り詰められる。実展開数は `expandedStarts`）や limit で一覧に出ていない
    # 起点レコード行きは正当なので再帰先が無くても通す
    starts = set(r['summary']['startIds'])
    by_id = {x['id']: x for x in rows_of(r)}

    def head_ok(head, seen):
        if head in seen:
            return False  # 先頭連鎖が循環
        if head in starts:
            return True
        up = by_id.get(head)
        if up is None or not up.get('path'):
            return True  # 起点展開・limit 落ちの一覧外レコード
        return head_ok(up['path'][0], seen | {head})

    bad = []
    for x in rows_of(r):
        path = x.get('path') or []
        why = []
        if x.get('pathRoot') != 'start':
            why.append(f"pathRoot={x.get('pathRoot')}")
        if not path:
            why.append('path 空')
        else:
            if not head_ok(path[0], {x['id']}):
                why.append(f'先頭 {path[0]} から起点へ遡れない')
            if len(set(path)) != len(path):
                why.append('path に重複（循環）')
            if path[-1] != x['id']:
                why.append(f'末尾 {path[-1]} != id')
        if why:
            bad.append((x['id'], '; '.join(why)))
    print(f'[{label}] 行 {sum(1 for _ in rows_of(r))} / 連鎖違反 {len(bad)}')
    for bid, why in bad[:12]:
        print(f'  - {bid}: {why}')
    return bad


def main():
    fail = 0

    # ---- (1) 最小再現 ----
    g = {
        'nodes': [
            {'id': 'tf:aws_iam_role_policy.p', 'kind': 'resource', 'name': 'p',
             'metadata': {'resourceType': 'aws_iam_role_policy'}},
            {'id': 'tf:aws_iam_role.r', 'kind': 'resource', 'name': 'r',
             'metadata': {'resourceType': 'aws_iam_role'}},
            {'id': 'tf:aws_lambda_function.n', 'kind': 'resource', 'name': 'n',
             'metadata': {'resourceType': 'aws_lambda_function'}},
            {'id': 'tf:aws_sfn_state_machine.o', 'kind': 'resource', 'name': 'o',
             'metadata': {'resourceType': 'aws_sfn_state_machine'}},
        ],
        'edges': [
            {'id': 'refs:p->r', 'kind': 'references', 'provenance': 'terraform',
             'source': 'tf:aws_iam_role_policy.p', 'target': 'tf:aws_iam_role.r'},
            {'id': 'refs:n->r', 'kind': 'references', 'provenance': 'terraform',
             'source': 'tf:aws_lambda_function.n', 'target': 'tf:aws_iam_role.r'},
            {'id': 'refs:o->r', 'kind': 'references', 'provenance': 'terraform',
             'source': 'tf:aws_sfn_state_machine.o', 'target': 'tf:aws_iam_role.r'},
            {'id': 'inv:o->n', 'kind': 'invokes', 'provenance': 'terraform',
             'source': 'tf:aws_sfn_state_machine.o', 'target': 'tf:aws_lambda_function.n'},
        ],
    }
    with tempfile.TemporaryDirectory() as td:
        gp = pathlib.Path(td) / 'g.json'
        gp.write_text(json.dumps(g))
        r = run(['--graph', str(gp), '--from', 'tf:aws_iam_role_policy.p', '--hops', '0'])
    print('== (1) 最小再現（policy -> role; n,o -> role; o --invokes--> n）==')
    for x in rows_of(r):
        print(f"  {x['id']}: hops={x['hops']} root={x['pathRoot']} via={x.get('via')} "
              f"ev={(x['evidence'] or {}).get('kind')} path={' -> '.join(x['path'])}")
    fail += len(check(r, '最小再現'))

    # ---- (2) 実事例 demo-iam ----
    print('== (2) demo-iam 実測 ==')
    r = run(['--graph', 'out/demo/graph.json', '--from',
             'tf:aws_iam_role_policy.lambda_dynamo_policy', '--hops', '8',
             '--wiring-hops', '3', '--limit', '100000'])
    # 保存先を既定で道具の置いてあるディレクトリ（追跡下）にしない。前の実行の結果を
    # 黙って上書きし、`git status` を汚す（第 50 ラウンドでバッテリーを追跡下へ移した直後の実測）
    dump = os.environ.get('CGD_VIA_CYCLE_DUMP')
    if dump:
        pathlib.Path(dump).write_text(json.dumps(r, ensure_ascii=False, indent=1))
    for x in rows_of(r):
        print(f"  {x['id']}: hops={x['hops']} tier={x['tier']} dir={x['direction']} "
              f"root={x['pathRoot']} ev={(x['evidence'] or {}).get('kind')} "
              f"path={' -> '.join(i.split(':')[-1] for i in x['path'])}")
    fail += len(check(r, 'demo-iam'))

    # ---- (3) 18 レポート全行 ----
    print('== (3) 保存済み 18 レポートと同じ条件 ==')
    nrep = 0
    for p in IN.report_paths(IN.HERE / 'baseline-v1', expect=18, what='v1 基準の 18 条件'):
        old = json.loads(p.read_text())
        s = old['summary']
        # 記録パスのまま渡すと report.mjs が ENOENT（第 52 ラウンド双人レビュー両名 P2）
        args = ['--graph', str(IN.graph_path(s['graph'])), '--hops', str(s['hops']),
                '--wiring-hops', str(s['wiringHops']), '--limit', str(s.get('limit') or 100000)]
        for st in old['starts']:
            args += ['--from', st['id']]
        fail += len(check(run(args), p.name))
        nrep += 1
    print(f'== 結果: {nrep} レポート / 違反合計 {fail} ==')
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())
