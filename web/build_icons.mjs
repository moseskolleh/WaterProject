/* Rasterise docs/icon.svg into the PNG sizes a web app manifest needs.
 *
 * Chromium treats a manifest without a 192 px and a 512 px raster icon as
 * not installable, so the droplet has to exist as PNG as well as SVG. The
 * rasteriser is the headless Chromium already used by the browser tests -
 * no extra dependency, and the icon that ships is the one Chrome renders.
 *
 *   node web/build_icons.mjs
 *
 * The maskable variants pad the droplet into the safe zone (the outer 20%
 * of a maskable icon can be cropped to a circle or a squircle by the
 * launcher), so the wave is never clipped on an Android home screen.
 */
import { chromium } from 'playwright';
import { readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const repo = join(dirname(fileURLToPath(import.meta.url)), '..');
const svg = readFileSync(join(repo, 'docs', 'icon.svg'), 'utf8');

/* [file, pixels, maskable] - a maskable icon keeps the artwork inside the
 * middle 80% and fills the rest with the brand blue rather than transparency. */
const TARGETS = [
  ['icon-192.png', 192, false],
  ['icon-512.png', 512, false],
  ['icon-maskable-512.png', 512, true],
];

const browser = await chromium.launch();
try {
  for (const [name, size, maskable] of TARGETS) {
    const inset = maskable ? size * 0.1 : 0;
    const page = await browser.newPage({
      viewport: { width: size, height: size },
      deviceScaleFactor: 1,
    });
    await page.setContent(`<!doctype html><meta charset="utf-8">
      <style>
        html, body { margin: 0; padding: 0; width: ${size}px; height: ${size}px; }
        body { background: ${maskable ? '#1F5C8B' : 'transparent'}; }
        svg { position: absolute; left: ${inset}px; top: ${inset}px;
              width: ${size - inset * 2}px; height: ${size - inset * 2}px; }
      </style>${svg}`);
    const png = await page.screenshot({
      omitBackground: !maskable,
      clip: { x: 0, y: 0, width: size, height: size },
    });
    writeFileSync(join(repo, 'docs', name), png);
    console.log(`wrote docs/${name} (${size}px${maskable ? ', maskable' : ''})`);
    await page.close();
  }
} finally {
  await browser.close();
}
