#!/usr/bin/env python3
# 性能ゲートの `v2-mix` 条件が入力グラフを作る道具（第 50 ラウンド Codex 指摘 F4 対応）。
#
#   python3 skill/scripts/tools/make-v2-graph.py <出力 graph.json> [apis=40] [routes=20]
#
# `v2-mix` は「API Gateway v2 のルート 800 本が 200 個の Lambda ハンドルを共有する」形の
# 合成グラフで測る。これまでこの入力は**一度きりの生成物の残骸**（第 48 ラウンドまで一時
# ディレクトリに有った）で、生成手順はどこにも残っていなかった。`out/tmp-*` は掃除の対象なので、
# 消えた日にゲートの 4 条件のうちの 1 条件が黙って消える（第 48 ラウンドで実際に
# `--changed` の入力が消えて 250 回全失敗した事故と同じ形）。ここで作り直せるようにする。
#
# 形（apis=40, routes=20 の既定値で、昔の残骸と同じ counts になる。実測で_nodes 2727 / edges 5800）:
#   - フォルダ 3（`folder:.` / `folder:infra` / `folder:src`）、ファイル 41（api{a}.tf 40 + Handlers.cs）
#   - csproj 1 とクラス 1（`type:Shop.Orders`）、メソッド 201（Handle0..Handle199 と Shared）
#   - API 40・IAM role 40・route / integration / lambda 各 800（route は `POST /v2/a{api}/r{route}`）
#   - 縁は references 3200（route→api、integration→api、route→integration、lambda→role）、
#     invokes 800（route→integration）、triggers 800（integration→lambda）、
#     handler 800（lambda→Handle{(api*routes+route) % 200}）、calls 200（Handle{i}→Shared）
# `--api "POST /v2/a7/r3"` での期待値: 先 1 / 出口 2 / 定義上の関連 1038、
# 兄弟ルート 799 件と定義ノード 819 件（`skill/scripts/tools/count-kinds.py` で数え直せる）
import json, sys, time, pathlib

args = sys.argv[1:]
if not args:
    raise SystemExit('使い方: make-v2-graph.py <出力 graph.json> [apis=40] [routes=20]')
out = pathlib.Path(args[0])
apis = int(args[1]) if len(args) > 1 else 40
routes = int(args[2]) if len(args) > 2 else 20
HANDLERS = 200      # 共有するハンドルの数（route 本数より少なくして兄弟ルートを作る）

nodes, edges = [], []
n_resources = apis * (routes * 3 + 2)
n_members = HANDLERS + 1


def node(i, kind, name, parent=None, path=None, metadata=None):
    n = {'id': i, 'kind': kind, 'name': name, 'parent': parent}
    if path is not None:
        n['path'] = path
    if metadata is not None:
        n['metadata'] = metadata
    nodes.append(n)


def edge(kind, source, target, detail, provenance='terraform', extra=None):
    e = {'id': f'{kind}:{source}->{target}', 'kind': kind, 'source': source,
         'target': target, 'provenance': provenance, 'detail': detail, 'count': 1}
    if extra:
        e.update(extra)
    edges.append(e)


def rollup(types, members, files, projects, resources, folders):
    return {'rollup': {'types': types, 'members': members, 'files': files,
                       'projects': projects, 'resources': resources, 'folders': folders}}


node('folder:.', 'folder', 'v2big', None, '', rollup(1, n_members, apis + 1, 1, n_resources, 2))
node('folder:infra', 'folder', 'infra', 'folder:.', None, rollup(0, 0, apis, 0, n_resources, 0))
node('folder:src', 'folder', 'src', 'folder:.', None, rollup(1, n_members, 1, 0, 0, 0))
for a in range(apis):
    node(f'file:infra/api{a}.tf', 'file', f'api{a}.tf', 'folder:infra', f'infra/api{a}.tf',
         {'language': 'terraform'})
node('file:src/Handlers.cs', 'file', 'Handlers.cs', 'folder:src', 'src/Handlers.cs')
node('project:V2HttpApi.csproj', 'project', 'V2HttpApi.csproj', 'folder:.', 'V2HttpApi.csproj',
     {'targetFramework': 'net9.0', 'assemblyName': 'ShopAssembly'})
node('type:Shop.Orders', 'type', 'Orders', 'file:src/Handlers.cs', 'src/Handlers.cs',
     {'csKind': 'class', 'namespace': 'Shop', 'line': 2, 'file': 'src/Handlers.cs',
      'modifiers': ['public'], 'memberCount': n_members})
for h in range(HANDLERS):
    node(f'member:Shop.Orders.Handle{h}', 'member', f'Handle{h}', 'type:Shop.Orders',
         'src/Handlers.cs', {'memberKind': 'method', 'signature': f'public void Handle{h}()',
                             'line': 3 + h, 'visibility': 'public', 'returns': 'void'})
node('member:Shop.Orders.Shared', 'member', 'Shared', 'type:Shop.Orders', 'src/Handlers.cs',
     {'memberKind': 'method', 'signature': 'public void Shared()', 'line': 3 + HANDLERS,
      'visibility': 'public', 'returns': 'void'})
for h in range(HANDLERS):
    edge('calls', f'member:Shop.Orders.Handle{h}', 'member:Shop.Orders.Shared', 'this.Shared',
         'static', {'line': 3 + h})

for a in range(apis):
    api, role, f = f'tf:aws_apigatewayv2_api.api{a}', f'tf:aws_iam_role.role{a}', f'infra/api{a}.tf'
    node(api, 'resource', f'api{a}', 'folder:infra', f,
         {'resourceType': 'aws_apigatewayv2_api', 'terraformAddress': api[3:], 'file': f,
          'provider': 'terraform', 'name': f'api{a}', 'category': 'apigateway'})
    node(role, 'resource', f'role{a}', 'folder:infra', f,
         {'resourceType': 'aws_iam_role', 'terraformAddress': role[3:], 'file': f,
          'provider': 'terraform', 'name': f'role-{a}', 'category': 'iam'})
    for k in range(routes):
        rt, it, fn = (f'tf:aws_apigatewayv2_route.rt{a}_{k}',
                      f'tf:aws_apigatewayv2_integration.int{a}_{k}',
                      f'tf:aws_lambda_function.fn{a}_{k}')
        path = f'/v2/a{a}/r{k}'
        node(rt, 'resource', f'rt{a}_{k}', 'folder:infra', f,
             {'resourceType': 'aws_apigatewayv2_route', 'terraformAddress': rt[3:], 'file': f,
              'provider': 'terraform', 'route_key': f'POST {path}', 'api_id': f'{api[3:]}.id',
              'target': f'integrations/${{{it[3:]}.id}}', 'category': 'apigateway',
              'apiPath': path, 'endpoint': f'POST {path}'})
        node(it, 'resource', f'int{a}_{k}', 'folder:infra', f,
             {'resourceType': 'aws_apigatewayv2_integration', 'terraformAddress': it[3:],
              'file': f, 'provider': 'terraform', 'integration_uri': f'{fn[3:]}.arn',
              'api_id': f'{api[3:]}.id', 'category': 'apigateway'})
        h = k % HANDLERS   # 昔の残骸は route の添字をそのままハンドル番号にしていた
        node(fn, 'resource', f'fn{a}_{k}', 'folder:infra', f,
             {'resourceType': 'aws_lambda_function', 'terraformAddress': fn[3:], 'file': f,
              'provider': 'terraform', 'function_name': f'fn-{a}-{k}',
              'handler': f'ShopAssembly::Shop.Orders::Handle{h}', 'role': f'{role[3:]}.arn',
              'category': 'lambda'})
        mem = f'member:Shop.Orders.Handle{h}'
        edge('references', rt, api, f'{f} 内の参照')
        edge('references', it, api, f'{f} 内の参照')
        edge('references', rt, it, f'{f} 内の参照')
        # role への参照は `role = aws_iam_role.role0.arn` という文字列なので、スキャナーは
        # 解決できなかった印（`unresolvedTarget`）を付ける。昔の残骸と同じ形にして、その符号を
        # 通す費用も性能比較に含める
        edge('references', fn, role, f'{f} 内の参照', 'terraform',
             {'metadata': {'unresolvedTarget': True}})
        edge('invokes', rt, it, '`aws_apigatewayv2_route` の `target` が integration に委譲する先')
        edge('triggers', it, fn, f'{f} 内の参照')
        edge('handler', fn, mem, f'handler = ShopAssembly::Shop.Orders::Handle{h}')

doc = {'schemaVersion': 1, 'generatedAt': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
       'root': 'folder:.', 'rootPath': str(out.resolve().parent / 'v2big'), 'name': 'v2big',
       'producers': [{'producer': 'make-v2-graph.py', 'fragment': '-', 'role': 'synthetic',
                      'nodes': len(nodes), 'edges': len(edges)}],
       'nodes': nodes, 'edges': edges,
       'stats': {'folders': 3, 'files': apis + 1, 'projects': 1, 'solutions': 0,
                 'nodes': len(nodes), 'edges': len(edges)}}
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(doc, ensure_ascii=False), encoding='utf-8')
print(f'ノード {len(nodes)} / 縁 {len(edges)} を {out} へ書いた')
