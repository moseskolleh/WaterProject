/* Every function gwt-core.js puts on GWT.core has a JSDoc type for each of
 * its parameters.
 *
 *     node web/jscheck/public-api.mjs
 *
 * tsc checks gwt-core.js with noImplicitAny off, because the engine's own
 * helpers and callbacks are not typed, so tsc alone would not notice a new
 * export arriving untyped. This does: it reads every Object.assign(C, {...})
 * and every C.name = ..., follows each name to its function declaration,
 * and fails on a parameter with no type. It parses with the TypeScript that
 * ui/depth-spine pins, the same one tsc runs, so `npm ci` there first.
 */
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', '..');
const require = createRequire(path.join(root, 'ui', 'depth-spine', 'package.json'));
const ts = require('typescript');

const file = path.join(root, 'docs', 'js', 'gwt-core.js');
const source = ts.createSourceFile(file, readFileSync(file, 'utf8'),
  ts.ScriptTarget.Latest, true, ts.ScriptKind.JS);

const declared = new Map();
const exported = [];
(function visit(node) {
  if (ts.isFunctionDeclaration(node) && node.name) declared.set(node.name.text, node);
  if (ts.isCallExpression(node) && node.expression.getText(source) === 'Object.assign' &&
      node.arguments.length === 2 && node.arguments[0].getText(source) === 'C' &&
      ts.isObjectLiteralExpression(node.arguments[1])) {
    for (const property of node.arguments[1].properties) {
      if (ts.isPropertyAssignment(property)) {
        exported.push([property.name.getText(source), property.initializer]);
      } else if (ts.isShorthandPropertyAssignment(property)) {
        exported.push([property.name.text, property.name]);
      }
    }
  }
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
      ts.isPropertyAccessExpression(node.left) && node.left.expression.getText(source) === 'C') {
    exported.push([node.left.name.text, node.right]);
  }
  ts.forEachChild(node, visit);
}(source));

let functions = 0;
const untyped = [];
for (const [name, value] of exported) {
  // A function written in place is held to the same rule as one declared
  // by name, so that `C.x = function (a) {...}` is no way round it.
  const fn = ts.isFunctionExpression(value) || ts.isArrowFunction(value)
    ? value : declared.get(value.getText(source));
  if (!fn) continue;   // a constant, a table or a namespace object
  functions += 1;
  const missing = fn.parameters.filter((p) => !ts.getJSDocType(p))
    .map((p) => p.name.getText(source));
  if (missing.length) {
    const line = source.getLineAndCharacterOfPosition(fn.getStart(source)).line + 1;
    untyped.push(`docs/js/gwt-core.js:${line}: C.${name} has no JSDoc type for ` +
      missing.join(', '));
  }
}

if (untyped.length) {
  console.error(untyped.join('\n'));
  console.error(`${untyped.length} of the ${functions} functions on GWT.core ` +
    `${untyped.length === 1 ? 'takes' : 'take'} a parameter with no JSDoc type; ` +
    'add an @param {type} for each.');
  process.exit(1);
}
console.log(`All ${functions} functions on GWT.core have typed parameters.`);
