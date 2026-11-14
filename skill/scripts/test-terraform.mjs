#!/usr/bin/env node
// scan-terraform.mjs の属性取得と API パス組み立てを検査する。
// API Gateway の `path_part` はリソース単体の値で、HTTP のパスは `parent_id` を辿って作る。
// レポートが `POST /orders` の形で起点を引くための値なので、外したまま黙って進まないための検査。
// 使い方: node skill/scripts/test-terraform.mjs
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
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
// 循環そのものは HCL として不正（Terraform が通らない）だが、解析側が止まらず、
// ファイル順で決定的な値に落ち着けばよい（自分の `path_part` を必ず末尾に持つ）
const loopOk = (n) => typeof meta(n).apiPath === 'string' && String(meta(n).apiPath).length > 0;
check('`parent_id` が循環しても停止せず、自分の `path_part` を末尾に持つ',
  loopOk('loop_a') && String(meta('loop_a').apiPath).endsWith('/a')
  && loopOk('loop_b') && String(meta('loop_b').apiPath).endsWith('/b'),
  JSON.stringify([meta('loop_a').apiPath, meta('loop_b').apiPath]));
check('data ソースは `dataSource: true`（レポートが既定で除外できる）',
  meta('current').dataSource === true, JSON.stringify(meta('current')));

rmSync(dir, { recursive: true, force: true });
console.log(`\n${pass}/${pass + failures.length} 件成功`);
if (failures.length) { console.log('失敗: ' + failures.join(' / ')); process.exit(1); }
