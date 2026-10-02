/* The browser engine as a long-lived process for the fuzz suite.
 *
 * Starts headless Chromium once, on the same bare engine page parity.mjs
 * uses, then reads one JSON request per line on stdin and answers with one
 * JSON line on stdout:
 *
 *   {"id": 7, "kind": "pumping", "name": "case.xlsx", "b64": "...", "options": {}}
 *   {"id": 7, "out": {...}}
 *
 * The bytes are the workbook Python wrote and read, so both engines parse the
 * same file. Starting a browser per case costs about a second; answering a
 * case on a page already open costs a few milliseconds, which is what lets a
 * pull request run hundreds of cases and a nightly run tens of thousands.
 */
import { withPage } from '../webapp/harness.mjs';
import { createInterface } from 'node:readline';
import { fileURLToPath } from 'node:url';

const PAGE_JS = fileURLToPath(new URL('page.js', import.meta.url));

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/__engine.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.core && window.GWT.support);
  await page.addScriptTag({ path: PAGE_JS });
  process.stdout.write(JSON.stringify({ ready: true }) + '\n');

  const lines = createInterface({ input: process.stdin, crlfDelay: Infinity });
  for await (const line of lines) {
    if (!line.trim()) continue;
    const request = JSON.parse(line);
    let out;
    try {
      out = await page.evaluate(
        ({ kind, name, b64, options }) => window.FUZZ.run(kind, name, b64, options),
        request);
    } catch (e) {
      out = { error: 'engine.mjs: ' + String(e && e.message || e) };
    }
    // A page error is not part of the answer, but it is never silent either.
    const errors = consoleErrors.splice(0);
    process.stdout.write(JSON.stringify({ id: request.id, out, errors }) + '\n');
  }
});
