#!/usr/bin/env node
// ビューア HTML にグラフデータを埋め込んで単一 HTML を作る。
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const opts = { template: join(HERE, '..', 'viewer', 'template.html'), data: '', out: 'graph.html' };
  for (let i = 2; i < argv.length; i++) {
    switch (argv[i]) {
      case '--template': opts.template = resolve(argv[++i]); break;
      case '--data': opts.data = resolve(argv[++i]); break;
      case '--out': opts.out = argv[++i]; break;
      case '--help':
        console.log('使い方: render.mjs --data graph.data.js --out graph.html [--template template.html]');
        process.exit(0);
    }
  }
  return opts;
}

const opts = parseArgs(process.argv);
if (!opts.data) { console.error('render.mjs: --data が必要です'); process.exit(1); }
const template = readFileSync(opts.template, 'utf8');
const payload = readFileSync(opts.data, 'utf8');
if (!template.includes('__CSDG_INLINE__')) { console.error('テンプレートに __CSDG_INLINE__ がありません'); process.exit(1); }
const html = template.replace('__CSDG_INLINE__', () => payload);
mkdirSync(dirname(resolve(opts.out)) || '.', { recursive: true });
writeFileSync(opts.out, html);
console.log(`[render] ${opts.out} (${(html.length / 1024 / 1024).toFixed(1)}MB)`);
