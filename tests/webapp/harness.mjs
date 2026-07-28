/* Browser harness for the standalone web app.
 *
 * Loads docs/ in headless Chromium, runs a snippet against the real runtime
 * (DOMParser, DecompressionStream, canvas - none of which exist in Node) and
 * hands the result back. Used by the parity checks that compare the browser
 * engine against the Python toolkit.
 */
import { chromium } from 'playwright';
import { createServer } from 'node:http';
import { readFile, stat } from 'node:fs/promises';
import { extname, join, normalize } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = fileURLToPath(new URL('../../docs/', import.meta.url));
const TYPES = {
  '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css',
  '.json': 'application/json', '.svg': 'image/svg+xml', '.png': 'image/png',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.md': 'text/markdown',
};

export async function serveDocs() {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, 'http://localhost');
      // A bare engine page for the parity checks: loads the runtime without
      // the app shell, so a UI error cannot masquerade as a numeric one.
      if (url.pathname === '/__engine.html') {
        res.writeHead(200, { 'Content-Type': 'text/html' });
        res.end('<!doctype html><meta charset="utf-8"><title>engine</title>' +
          '<script src="/js/support.js"></script>' +
          '<script src="/js/gwt-data.js"></script>' +
          '<script src="/js/gwt-core.js"></script>');
        return;
      }
      let path = normalize(decodeURIComponent(url.pathname)).replace(/^(\.\.[/\\])+/, '');
      if (path.endsWith('/')) path += 'index.html';
      const file = join(ROOT, path);
      const info = await stat(file);
      if (info.isDirectory()) throw new Error('directory');
      res.writeHead(200, { 'Content-Type': TYPES[extname(file)] || 'application/octet-stream' });
      res.end(await readFile(file));
    } catch {
      res.writeHead(404, { 'Content-Type': 'text/plain' });
      res.end('not found');
    }
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  return { server, base: `http://127.0.0.1:${port}` };
}

export async function withPage(fn, options = {}) {
  const { server, base } = await serveDocs();
  const browser = await chromium.launch({
    executablePath: options.executablePath,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const consoleErrors = [];
  page.on('console', (m) => {
    if (m.type() === 'error') consoleErrors.push(m.text());
  });
  page.on('pageerror', (e) => consoleErrors.push('pageerror: ' + e.message));
  try {
    return await fn(page, base, consoleErrors);
  } finally {
    await browser.close();
    server.close();
  }
}
