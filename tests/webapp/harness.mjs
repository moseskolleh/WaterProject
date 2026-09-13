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
  '.webmanifest': 'application/manifest+json',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  '.md': 'text/markdown',
};

/* Serve docs/ over http on a free port.
 *
 * `overlay` replaces or removes individual files for the life of one run,
 * without touching the working tree: a pathname maps to `{ body, type }` to
 * answer with something else, or to `null` to answer 404. The offline checks
 * need this to stage a release that cannot install - a worker listing a file
 * the server will not serve - and a deploy that is missing a file is not
 * something to reproduce by deleting it out of docs/ mid-test.
 *
 * `network` is how those checks take the network away. Setting `network.down`
 * makes the server drop connections rather than answer them, which is what
 * the service worker sees on a site with no signal: a fetch that fails, not a
 * server that says no. Emulated offline mode is not enough here - it does not
 * reliably reach a worker's own fetches, and a check that quietly still had a
 * network would pass while proving nothing.
 */
export async function serveDocs(options = {}) {
  const overlay = options.overlay || {};
  const network = options.network || {};
  const server = createServer(async (req, res) => {
    try {
      if (network.down) { req.socket.destroy(); return; }
      const url = new URL(req.url, 'http://localhost');
      if (Object.prototype.hasOwnProperty.call(overlay, url.pathname)) {
        const entry = overlay[url.pathname];
        if (!entry) throw new Error('withheld');
        res.writeHead(200, { 'Content-Type': entry.type || 'text/javascript' });
        res.end(entry.body);
        return;
      }
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
  const { server, base } = await serveDocs(options);
  const browser = await chromium.launch({
    executablePath: options.executablePath,
    args: ['--no-sandbox', '--disable-dev-shm-usage'],
  });
  /* an explicit context rather than browser.newPage(), which creates one that
   * refuses a second page: the offline checks need to close every tab and
   * open a fresh one to let a waiting service worker take over */
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
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
