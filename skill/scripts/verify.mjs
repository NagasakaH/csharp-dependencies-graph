#!/usr/bin/env node
// ビューアを実際のブラウザで操作して期待どおりか検査する（playwright）。
// 検査対象は graph.json から自動で選ぶので、どのプロジェクトのグラフにもそのまま使える。
import { execSync } from 'node:child_process';
import { readFileSync, readdirSync, existsSync, mkdirSync } from 'node:fs';
import { join, dirname, basename, resolve } from 'node:path';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';

function candidateRoots() {
  const roots = [process.cwd()];
  try {
    const globalRoot = execSync('npm root -g', { encoding: 'utf8' }).trim();
    roots.push(globalRoot);
    for (const entry of readdirSync(globalRoot, { withFileTypes: true })) {
      const abs = join(globalRoot, entry.name);
      if (entry.name.startsWith('@')) {
        for (const sub of readdirSync(abs)) { roots.push(join(abs, sub)); roots.push(join(abs, sub, 'node_modules')); }
      } else { roots.push(abs); roots.push(join(abs, 'node_modules')); }
    }
  } catch {}
  return roots;
}

async function loadChromium() {
  for (const root of candidateRoots()) {
    try {
      const req = createRequire(join(root, 'package.json'));
      const mod = await import(pathToFileURL(req.resolve('playwright')).href);
      const chromium = mod.chromium || mod.default?.chromium;
      if (chromium) return chromium;
    } catch {}
  }
  console.error('playwright が見つかりません。`npm i -g @playwright/cli` を実行してください。');
  process.exit(1);
}
const chromium = await loadChromium();

function parseArgs(argv) {
  const opts = { shots: 'out/shots', query: null, browser: null };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--html': opts.html = resolve(argv[++i]); break;
      case '--graph': opts.graph = resolve(argv[++i]); break;
      case '--shots': opts.shots = resolve(argv[++i]); break;
      case '--query': opts.query = argv[++i]; break;
      case '--browser': opts.browser = resolve(argv[++i]); break;
      case '--help': console.log('使い方: verify.mjs --html graph.html [--graph graph.json] [--shots out/shots] [--query ExecuteAsync] [--browser /path/to/Chrome]'); process.exit(0);
    }
  }
  if (!opts.html) { console.error('--html graph.html を指定してください'); process.exit(1); }
  return opts;
}

const opts = parseArgs(process.argv);
if (!existsSync(opts.html)) { console.error(`見つかりません: ${opts.html}`); process.exit(1); }
const graphPath = opts.graph || join(dirname(opts.html), 'graph.json');
if (!existsSync(graphPath)) { console.error(`graph.json が見つかりません: ${graphPath}（--graph で指定）`); process.exit(1); }
mkdirSync(opts.shots, { recursive: true });

// ---- 検査対象をグラフから選ぶ（ハードコードしない）
const graph = JSON.parse(readFileSync(graphPath, 'utf8'));
const childCount = new Map();
for (const n of graph.nodes) if (n.parent) childCount.set(n.parent, (childCount.get(n.parent) || 0) + 1);
const outCount = new Map();
for (const e of graph.edges) if (e.kind !== 'contains') outCount.set(e.source, (outCount.get(e.source) || 0) + 1);

const methodsOf = (typeId) => graph.nodes.filter((n) => n.parent === typeId && n.kind === 'member' && (n.metadata.memberKind || 'method') === 'method');
const fileWithTypes = graph.nodes
  .filter((n) => n.kind === 'file' && (childCount.get(n.id) || 0) > 0)
  .sort((a, b) => (childCount.get(b.id) || 0) - (childCount.get(a.id) || 0))[0];
const types = graph.nodes.filter((n) => n.kind === 'type' && methodsOf(n.id).length > 0);
const typeTarget = types.find((t) => t.parent === (fileWithTypes && fileWithTypes.id) && methodsOf(t.id).length > 1)
  || types.sort((a, b) => methodsOf(b.id).length - methodsOf(a.id).length)[0];
const fileTarget = fileWithTypes && typeTarget && fileWithTypes.id === typeTarget.parent ? fileWithTypes
  : graph.nodes.find((n) => n.id === (typeTarget && typeTarget.parent));
const memberTarget = methodsOf(typeTarget ? typeTarget.id : null)
  .filter((m) => (outCount.get(m.id) || 0) > 0)
  .sort((a, b) => (outCount.get(b.id) || 0) - (outCount.get(a.id) || 0))[0]
  || methodsOf(typeTarget ? typeTarget.id : null)[0];
const resourceTarget = graph.nodes.find((n) => n.kind === 'resource');

if (!fileTarget || !typeTarget || !memberTarget) {
  console.error('.cs → 型 → メソッド の関係が見つからず、検査できません');
  process.exit(1);
}
const query = opts.query || memberTarget.name;
const fileBase = basename(fileTarget.path);

const results = [];
const record = (name, ok, info = '') => { results.push({ name, ok, info }); console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${info ? '  — ' + info : ''}`); };

async function launchBrowser() {
  // 依存している playwright が期待する Chromium ビルドは、このマシンに無いことがある。
  // 明示指定 → 既定 → キャッシュ済みビルド → システムの Chrome の順に試し、全部失敗したら理由を並べて落とす。
  const attempts = [];
  const tried = [];
  if (opts.browser) attempts.push({ path: opts.browser, why: '--browser' });
  if (process.env.CSDG_BROWSER) attempts.push({ path: process.env.CSDG_BROWSER, why: 'CSDG_BROWSER' });
  attempts.push({ path: null, why: 'playwright 既定' });
  const cache = join(process.env.HOME || '~', 'Library', 'Caches', 'ms-playwright');
  try {
    for (const dir of readdirSync(cache).sort().reverse()) {
      if (!dir.startsWith('chromium')) continue;
      for (const candidate of [
        join(cache, dir, 'chrome-headless-shell-mac-arm64', 'chrome-headless-shell'),
        join(cache, dir, 'chrome-mac-arm64', 'Chromium.app', 'Contents', 'MacOS', 'Chromium'),
      ]) if (existsSync(candidate)) attempts.push({ path: candidate, why: `キャッシュ ${dir}` });
    }
  } catch {}
  for (const candidate of [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Chromium.app/Contents/MacOS/Chromium',
  ]) if (existsSync(candidate)) attempts.push({ path: candidate, why: 'システムのブラウザ' });

  for (const attempt of attempts) {
    try {
      const browser = await chromium.launch(attempt.path ? { executablePath: attempt.path } : {});
      if (attempt.path) console.log(`[verify] ブラウザ: ${attempt.why} → ${attempt.path}`);
      return browser;
    } catch (error) {
      tried.push(`${attempt.why}: ${String(error.message || error).split('\n')[0]}`);
    }
  }
  console.error('[verify] ブラウザを起動できませんでした。`--browser <パス>` か環境変数 CSDG_BROWSER で Chrome を指定してください。');
  for (const line of tried) console.error('  試行: ' + line);
  process.exit(1);
}

console.log(`[verify] ${basename(opts.html)} / 検索語 "${query}" / ファイル ${fileBase}`);
const browser = await launchBrowser();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on('pageerror', (e) => errors.push(String(e)));
page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
const shot = (name) => page.screenshot({ path: join(opts.shots, name) });
const selectedId = () => page.locator('#nodes .gnode.selected').first().getAttribute('data-id').catch(() => null);

await page.goto(pathToFileURL(opts.html).href, { waitUntil: 'load', timeout: 120000 });
await page.waitForTimeout(700);

// 1. 初期表示はルート 1 段だけ
const stats = (await page.textContent('#stats')).trim();
record('グラフヘッダに統計が出る', /node \d+ \/ edge \d+/.test(stats), stats);
const treeRows = await page.locator('#tree .tnode').count();
record('ルート直下のフォルダがツリーに出る', treeRows > 2, `${treeRows} 行`);
const initialNodes = await page.locator('#nodes .gnode').count();
record('初期表示はルート階層のみ（段階的展開）', initialNodes > 0 && initialNodes < 80, `${initialNodes} ノード`);
await shot('01-root.png');

// 2. フォルダをクリックすると配下だけが 1 段増える
const targetFolderRow = page.locator('#tree .tnode', { hasText: '▸' }).first();
await targetFolderRow.click();
await page.waitForTimeout(500);
const afterExpand = await page.locator('#nodes .gnode').count();
record('フォルダクリックで配下だけがグラフに増える', afterExpand > initialNodes, `${initialNodes} → ${afterExpand}`);
const treeRowsAfter = await page.locator('#tree .tnode').count();
record('ツリーもクリックしたフォルダだけ展開する', treeRowsAfter > treeRows, `${treeRows} → ${treeRowsAfter} 行`);
await shot('02-folder-expanded.png');

// 3. .cs ファイル → 型 → メソッドと段階的に広がる
const expandSelected = async (label) => {
  const node = page.locator('#nodes .gnode.selected').first();
  if (!(await node.count())) { record(label, false, '選択ノードなし'); return; }
  const before = await page.locator('#nodes .gnode').count();
  await node.click({ force: true });
  await page.waitForTimeout(600);
  const after = await page.locator('#nodes .gnode').count();
  record(label, after > before, `${before} → ${after}`);
};

await page.selectOption('#kind-filter', 'file');
await page.fill('#q', fileBase);
await page.waitForTimeout(800);
await page.press('#q', 'Enter');
await page.waitForTimeout(700);
const pickedFile = await selectedId();
record('検索した cs ファイルがグラフ上で選択される', pickedFile === fileTarget.id, `${pickedFile}`);
await expandSelected('cs ファイルクリックでクラス（型）が現れる');
await shot('03-file-types.png');

await page.selectOption('#kind-filter', 'type');
await page.fill('#q', typeTarget.name);
await page.waitForTimeout(800);
await page.press('#q', 'Enter');
await page.waitForTimeout(700);
await expandSelected('クラスクリックでメソッド（メンバー）が現れる');
await shot('03b-type-members.png');
await page.selectOption('#kind-filter', '');

// 4. メソッド検索と詳細パネル
await page.fill('#q', query);
await page.waitForTimeout(800);
const rows = await page.locator('#results .row').count();
record('メソッド検索がヒットを返す', rows > 0, `${rows} 件`);
await shot('04-search.png');
await page.press('#q', 'Enter');
await page.waitForTimeout(700);
const detail = (await page.textContent('#detail-body')).replace(/\s+/g, ' ');
record('検索結果を開くと詳細パネルにメタデータが出る', /memberKind/.test(detail) && detail.includes(query), detail.slice(0, 60));
await shot('05-method-detail.png');

// 5. 依存をたどる／周辺ホップ展開
const outBtn = page.locator('#detail-body button', { hasText: '出力' }).first();
if (await outBtn.count()) {
  const before = await page.locator('#nodes .gnode').count();
  await outBtn.click();
  await page.waitForTimeout(600);
  const after = await page.locator('#nodes .gnode').count();
  record('出力エッジをたどると依存先がグラフに足される', after > before, `${before} → ${after}`);
} else record('出力エッジをたどると依存先がグラフに足される', false, 'ボタンなし');
await shot('06-dependencies.png');

const focusBtn = page.locator('#detail-body button', { hasText: '周辺 2' }).first();
if (await focusBtn.count()) {
  const before = await page.locator('#nodes .gnode').count();
  await focusBtn.click();
  await page.waitForTimeout(700);
  const after = await page.locator('#nodes .gnode').count();
  record('周辺 2 ホップで近傍が広がる', after > before, `${before} → ${after}`);
} else record('周辺 2 ホップで近傍が広がる', false, 'ボタンなし');
await shot('06b-focus.png');

// 6. 外部世界（Terraform）がノードとして乗っているか
const resourceCount = graph.nodes.filter((n) => n.kind === 'resource').length;
if (resourceCount) {
  const chip = await page.locator('.chip', { hasText: 'terraform' }).count();
  record('Terraform リソースがノードとして入っている', chip > 0, `${resourceCount} 件 / provenance チップ ${chip}`);
}

// 7. 外部リソースを後から紐づけて保存できる
await page.selectOption('#kind-filter', 'member');
await page.fill('#q', query);
await page.waitForTimeout(800);
await page.press('#q', 'Enter');
await page.waitForTimeout(600);
const nameInput = page.locator('#detail-body input[placeholder^="リソース名"]').first();
await nameInput.scrollIntoViewIfNeeded();
await nameInput.fill('verify-orders-api');
const linkBtn = page.locator('#detail-body button', { hasText: '紐づける' }).first();
await linkBtn.scrollIntoViewIfNeeded();
await linkBtn.click();
await page.waitForTimeout(500);
const resourceVisible = await page.locator('#nodes .gnode', { hasText: 'verify-orders-api' }).count();
record('外部リソースを後から紐づけられる', resourceVisible > 0, `${resourceVisible} ノード`);
const stored = await page.evaluate(() => localStorage.getItem('csdg:annotations'));
record('ブラウザ内に注釈が保存される', !!stored && stored.includes('verify-orders-api'), '');
await shot('07-annotation.png');

// 8. ディープリンクで同じ展開状態を開ける
const baseUrl = page.url().split('#')[0];
await page.goto('about:blank');
await page.goto(`${baseUrl}#expand=${encodeURIComponent(`${graph.root},${fileTarget.id}`)}&select=${encodeURIComponent(memberTarget.id)}`, { waitUntil: 'load' });
await page.waitForTimeout(1000);
const deep = await selectedId();
record('ディープリンクで同じ展開状態を開ける', deep === memberTarget.id, `${deep}`);
await shot('08-deeplink.png');

record('ブラウザコンソールエラーなし', errors.length === 0, errors.slice(0, 3).join(' | '));
await browser.close();

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} 件成功  スクリーンショット: ${opts.shots}`);
if (failed.length) console.log('失敗: ' + failed.map((f) => f.name).join(' / '));
process.exit(failed.length ? 1 : 0);
