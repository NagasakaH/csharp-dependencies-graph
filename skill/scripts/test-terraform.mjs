#!/usr/bin/env node
// scan-terraform.mjs の属性取得と API パス組み立てを検査する。
// API Gateway の `path_part` はリソース単体の値で、HTTP のパスは `parent_id` を辿って作る。
// レポートが `POST /orders` の形で起点を引くための値なので、外したまま黙って進まないための検査。
// 使い方: node skill/scripts/test-terraform.mjs
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const root = resolve(HERE, '..', '..');
const dir = mkdtempSync(join(tmpdir(), 'cgd-tf-'));
let pass = 0;
const failures = [];
function check(label, ok, detail) {
  if (ok) { pass++; console.log(`PASS ${label}`); } else { failures.push(label); console.log(`FAIL ${label}${detail ? `  ${detail}` : ''}`); }
}

const out = join(dir, 'graph.terraform.json');
const proc = spawnSync(process.execPath, [join(HERE, 'scan-terraform.mjs'),
  '--root', join(HERE, '..', 'tests', 'fixtures', 'TerraformApi'), '--out', out],
  { cwd: root, encoding: 'utf8', timeout: 60_000 });
if (proc.status !== 0) {
  console.error((proc.stdout || '') + (proc.stderr || ''));
  process.exit(1);
}
const graph = JSON.parse(readFileSync(out, 'utf8'));
const byName = new Map(graph.nodes.filter((n) => n.kind === 'resource').map((n) => [n.name, n]));
const meta = (name) => byName.get(name)?.metadata || {};

check('`path_part` と `parent_id` を metadata に取る',
  meta('orders').path_part === 'orders' && String(meta('orders').parent_id || '').includes('root_resource_id')
  && String(meta('orders_item').parent_id || '').includes('aws_api_gateway_resource.orders.id'),
  JSON.stringify([meta('orders'), meta('orders_item').parent_id]));
check('rest_api の root 直下は `/<path_part>` だけになる（親名を連結しない）',
  meta('orders').apiPath === '/orders', `apiPath=${meta('orders').apiPath}`);
check('別の resource を指す `parent_id` は親のパスへ連結する',
  meta('orders_item').apiPath === '/orders/{id}', `apiPath=${meta('orders_item').apiPath}`);
check('method には `apiPath` と表示名 `endpoint`（POST /orders）を付ける',
  meta('post_order').apiPath === '/orders' && meta('post_order').endpoint === 'POST /orders',
  JSON.stringify([meta('post_order').apiPath, meta('post_order').endpoint]));
check('入れ子リソースの method は `GET /orders/{id}`',
  meta('get_item').endpoint === 'GET /orders/{id}', `endpoint=${meta('get_item').endpoint}`);
check('`stage_name` を取る（デプロイがどのステージか）',
  meta('live').stage_name === 'prod', `stage_name=${meta('live').stage_name}`);
check('HTTP API（v2）は `route_key` から endpoint を作る',
  meta('cancel').endpoint === 'DELETE /orders/{id}/cancel' && meta('cancel').apiPath === '/orders/{id}/cancel',
  JSON.stringify([meta('cancel').endpoint, meta('cancel').apiPath]));
check('パスが決まらない method に推測で `endpoint` を張らない',
  byName.has('orphan') && meta('orphan').http_method === 'DELETE'
  && meta('orphan').endpoint === undefined && meta('orphan').apiPath === undefined,
  JSON.stringify([meta('orphan').endpoint, meta('orphan').apiPath]));
// 循環そのものは HCL として不正（Terraform が通らない）。解析側が止まらないことと、
// 親が確定できないのにパスを張らないことを見る（昔は「親が解決できない＝直下」と読んで
// 自分の `path_part` だけの値を返していた。`var.parent_id` でも同じことになるのでやめた）
check('`parent_id` が循環しても止まらず、パスを張らない',
  meta('loop_a').apiPath === undefined && meta('loop_a').endpoint === undefined
  && meta('loop_b').apiPath === undefined,
  JSON.stringify([meta('loop_a').apiPath, meta('loop_b').apiPath]));
// 未解決の式から `endpoint` を張らない（実在しないパスを断定しないための検査）
check('`parent_id` が `var` 参照の method は endpoint を張らない',
  meta('var_parent_post').endpoint === undefined && meta('var_parent').apiPath === undefined,
  JSON.stringify([meta('var_parent_post').endpoint, meta('var_parent').apiPath]));
check('`parent_id` が module 出力の resource は apiPath を張らない',
  meta('module_parent').apiPath === undefined, `apiPath=${meta('module_parent').apiPath}`);
check('`for_each` の `each.value` を path_part にした resource はパスを決めない',
  meta('each_part').apiPath === undefined && meta('each_get').endpoint === undefined,
  JSON.stringify([meta('each_part').apiPath, meta('each_get').endpoint]));
check('補間で組み立てた `path_part` はパスを決めない',
  meta('interp_part').apiPath === undefined, `apiPath=${meta('interp_part').apiPath}`);
check('`route_key = var.route_key` は endpoint を張らない',
  meta('var_key').endpoint === undefined, `endpoint=${meta('var_key').endpoint}`);
check('`$default` は endpoint にしない（catch-all は実在の HTTP パスではない）。旗だけ残す',
  meta('default_key').endpoint === undefined && meta('default_key').apiPath === undefined
    && meta('default_key').defaultRoute === true,
  JSON.stringify([meta('default_key').endpoint, meta('default_key').apiPath, meta('default_key').defaultRoute]));
check('リテラルで正しく書けば決まる（上の検査が空振りしていない）',
  meta('literal_ok').apiPath === '/health', `apiPath=${meta('literal_ok').apiPath}`);
check('`"${...root_resource_id}"` のような単一の補間は解決する（実プロジェクトの大半この形）',
  meta('quoted_ref').apiPath === '/quoted' && meta('quoted_get').endpoint === 'GET /quoted',
  JSON.stringify([meta('quoted_ref').apiPath, meta('quoted_get').endpoint]));
check('data ソースは `dataSource: true`（レポートが既定で除外できる）',
  meta('current').dataSource === true, JSON.stringify(meta('current')));

// ---- 値全体がその形でなければ未解決（部分一致で参照を拾わない） ----
for (const [name, why] of [
  ['cond_parent', '三項式（分岐が未解決）'],
  ['join_parent', 'join() で組み立てている'],
  ['mixed_interp_parent', 'リテラルと補間の混合'],
  ['ssm_part', '他のリソースの属性（値が分からない）'],
]) {
  check(`${why} の parent_id / path_part はパスを決めない（${name}）`,
    meta(name).apiPath === undefined, `apiPath=${meta(name).apiPath}`);
}
check('引用されたリテラルは点を含んでいても決まる（`path_part = "local.segment"`）',
  meta('dotted_literal').apiPath === '/local.segment' && meta('dotted_get').endpoint === 'GET /local.segment',
  JSON.stringify([meta('dotted_literal').apiPath, meta('dotted_get').endpoint]));
check('`resource_id` が三項式なら endpoint を張らない（パスは決まっている）',
  meta('cond_id').endpoint === undefined && meta('cond_id').apiPath === undefined,
  JSON.stringify([meta('cond_id').apiPath, meta('cond_id').endpoint]));
check('`http_method = var.verb` から endpoint を作らない',
  meta('cond_verb').endpoint === undefined, `endpoint=${meta('cond_verb').endpoint}`);
check('`count` の添字付き参照は同じパスなので解決する',
  meta('counted_get').endpoint === 'GET /base', `endpoint=${meta('counted_get').endpoint}`);

// ---- module をまたぐ同名アドレス（id 衝突で endpoint が黙って消えない） ----
const modEndpoints = graph.nodes
  .filter((n) => (n.metadata || {}).file && n.metadata.file.startsWith('modules/') && n.metadata.endpoint)
  .map((n) => n.metadata.endpoint)
  .sort();
check('module 内の同名アドレスはファイル付き id に分かれて両方の endpoint が残る',
  JSON.stringify(modEndpoints) === JSON.stringify(['GET /one', 'GET /two']), JSON.stringify(modEndpoints));

rmSync(dir, { recursive: true, force: true });
// 値が決まらない属性はノードに正直に書く。リテラルでも参照でもない
// `%{ if ... }` から実在しない `path` を作らない
{
  const res = byName.get('tpl_res');
  check('テンプレート指令と変数参照はノードの `metadata.unresolved` に出す',
    !!res && Array.isArray(res.metadata.unresolved)
    && res.metadata.unresolved.includes('path_part') && res.metadata.unresolved.includes('parent_id')
    && !(res.metadata.endpoint && res.metadata.endpoint.path),
    res ? JSON.stringify(res.metadata.unresolved || null) + ' ' + JSON.stringify(res.metadata.endpoint || null) : 'ノードが無い');
}


// ---- HTTP API (v2): `aws_apigatewayv2_route` の `target` と `api_id` ----
// v2 は `route` → `integration` が `references` にしか入らない形になる。レポートの伝播の資格は
// 「参照されている側 → 参照している側」にしか通らないので、`route` 起点が本命へ届かない
// （双人レビュー第 25 ラウンドで agy が実測、codex も再現）。既知の形だけを `invokes` にする
{
  const v2dir = join(dir, 'v2tf');
  const proc2 = spawnSync(process.execPath, [join(HERE, 'scan-terraform.mjs'),
    '--root', join(HERE, '..', 'tests', 'fixtures', 'V2HttpApi'), '--out', join(dir, 'v2.tf.json')],
    { cwd: root, encoding: 'utf8', timeout: 60_000 });
  if (proc2.status !== 0) { console.error((proc2.stdout || '') + (proc2.stderr || '')); process.exit(1); }
  const g2 = JSON.parse(readFileSync(join(dir, 'v2.tf.json'), 'utf8'));
  const byAddr = new Map(g2.nodes.map((n) => [n.id.slice(3), n]));
  const m2 = (addr) => (byAddr.get(addr) || {}).metadata || {};
  const RT = 'aws_apigatewayv2_route'; const IN = 'aws_apigatewayv2_integration';
  const inv = (from, to) => g2.edges.some((e) => e.kind === 'invokes' && e.source === `tf:${from}` && e.target === `tf:${to}`);
  check('v2: `target` が指す integration へ `invokes` を張る',
    inv(`${RT}.create`, `${IN}.create_item`),
    JSON.stringify(g2.edges.filter((e) => e.kind === 'invokes').map((e) => e.id)));
  check('v2: `route_key = "POST /v2/items"` から endpoint を作る',
    m2(`${RT}.create`).endpoint === 'POST /v2/items', JSON.stringify(m2(`${RT}.create`).endpoint));
  check('v2: `route_key = "$default"` は endpoint にせず `defaultRoute` を残す',
    m2(`${RT}.fallback`).endpoint === undefined && m2(`${RT}.fallback`).defaultRoute === true,
    JSON.stringify([m2(`${RT}.fallback`).endpoint, m2(`${RT}.fallback`).defaultRoute]));
  check('v2: WebSocket の `$connect` は endpoint にしない（`nonHttpRouteKey` に残す）',
    m2(`${RT}.connect`).endpoint === undefined && m2(`${RT}.connect`).nonHttpRouteKey === '$connect',
    JSON.stringify([m2(`${RT}.connect`).endpoint, m2(`${RT}.connect`).nonHttpRouteKey]));
  check('v2: `api_id` の直接参照は metadata に残す（同じ API の定義かどうかの判断材料）',
    String(m2(`${IN}.create_item`).api_id || '').includes('aws_apigatewayv2_api.shop.id'),
    JSON.stringify(m2(`${IN}.create_item`).api_id));
  const bad = (addr) => (m2(addr).unresolved || []);
  check('v2: 既知の形でない `target`（末尾に文字が足された混合補間）は縁を張らず `unresolved` に出す',
    !inv(`${RT}.mixed_target`, `${IN}.create_item`) && bad(`${RT}.mixed_target`).includes('target'),
    JSON.stringify([bad(`${RT}.mixed_target`), g2.edges.filter((e) => e.source === `tf:${RT}.mixed_target`).map((e) => e.kind + ':' + e.target)]));
  check('v2: 宣言されていない integration を指す `target` も縁を張らず `unresolved` に出す',
    !g2.edges.some((e) => e.kind === 'invokes' && e.source === `tf:${RT}.missing_target`)
    && bad(`${RT}.missing_target`).includes('target'),
    JSON.stringify([bad(`${RT}.missing_target`)]));
  check('v2: `api_id = var.*` は所属を推測せず `unresolved` に `api_id` を出す',
    bad(`${RT}.via_var`).includes('api_id'), JSON.stringify(bad(`${RT}.via_var`)));
  check('v2: `api_id` を直接参照している route / integration は未解決にしない',
    !bad(`${RT}.create`).includes('api_id') && !bad(`${IN}.create_item`).includes('api_id')
    && !bad(`${RT}.create`).includes('target'),
    JSON.stringify([bad(`${RT}.create`), bad(`${IN}.create_item`)]));

  // 宣言順（integration が route の前でも後ろでも）で結果が変わらないこと
  const apiBlk = 'resource "aws_apigatewayv2_api" "a" {\n  name = "a"\n}\n';
  const integBlk = 'resource "aws_apigatewayv2_integration" "i" {\n  api_id           = aws_apigatewayv2_api.a.id\n'
    + '  integration_type = "AWS_PROXY"\n  integration_uri  = "arn:aws:lambda:ap-northeast-1:1:function:f"\n}\n';
  const routeBlk = 'resource "aws_apigatewayv2_route" "r" {\n  api_id    = aws_apigatewayv2_api.a.id\n'
    + '  route_key = "POST /x"\n  target    = "integrations/${aws_apigatewayv2_integration.i.id}"\n}\n';
  const scanOrder = (tag, blocks) => {
    const d = join(dir, `order-${tag}`);
    mkdirSync(d, { recursive: true });
    writeFileSync(join(d, 'api.tf'), blocks.join('\n'), 'utf8');
    const o = join(dir, `order-${tag}.json`);
    const pr = spawnSync(process.execPath, [join(HERE, 'scan-terraform.mjs'), '--root', d, '--out', o],
      { cwd: root, encoding: 'utf8', timeout: 60_000 });
    if (pr.status !== 0) { console.error((pr.stdout || '') + (pr.stderr || '')); process.exit(1); }
    const gg = JSON.parse(readFileSync(o, 'utf8'));
    return {
      invokes: gg.edges.filter((e) => e.kind === 'invokes').map((e) => `${e.source}->${e.target}`).sort(),
      unresolved: gg.nodes.filter((n) => (n.metadata || {}).unresolved).map((n) => `${n.id}:${n.metadata.unresolved.join('/')}`).sort(),
    };
  };
  const fwd = scanOrder('fwd', [apiBlk, integBlk, routeBlk]);
  const rev = scanOrder('rev', [apiBlk, routeBlk, integBlk]);
  check('v2: integration の宣言が route より後ろでも同じ `invokes` が張られる（宣言順に依存しない）',
    fwd.invokes.length === 1 && JSON.stringify(fwd) === JSON.stringify(rev),
    JSON.stringify([fwd, rev]));
}

console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
