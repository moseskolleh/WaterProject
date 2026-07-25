// Put the single-file build inside the Python package.
//
// The demo mounts the package into an in-browser filesystem where ui/ does not
// exist, so the static workspace has to travel with the package rather than
// sitting beside it in the repository.
import { copyFileSync, mkdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const src = resolve(here, '..', 'dist-inline', 'inline.html');
const dest = resolve(
  here, '..', '..', '..',
  'src', 'groundwater', 'depth_spine', 'static', 'workspace.html',
);

mkdirSync(dirname(dest), { recursive: true });
copyFileSync(src, dest);
console.log(`placed ${dest}`);
