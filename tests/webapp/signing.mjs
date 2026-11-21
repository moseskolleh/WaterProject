/* Signed statements in the browser engine (PLAN.md step 8.2).
 *
 * The rules of a statement's text, of a members' file and of who stands
 * where are held to the Python engine by parity.mjs, case by case. What
 * only a browser can show is here: that a signature made by Web Crypto, the
 * way the app will make one, is one the engine's own written-out check
 * accepts, and that the same check refuses whatever Web Crypto refuses.
 *
 * It also keeps fixtures/signing_webcrypto.json: statements signed here,
 * once, by keys that were then thrown away. A signature is different every
 * time one is made, so the file is written on request and committed, and
 * both engines are held to reading it the same way (tests/test_signing.py
 * and the parity suite read the same file).
 *
 *     node tests/webapp/signing.mjs                   # check
 *     node tests/webapp/signing.mjs --write-fixtures   # make the file anew
 *
 * Every name in it is made up.
 */
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { withPage } from './harness.mjs';

const WRITE = process.argv.includes('--write-fixtures');
const FIXTURES = new URL('./fixtures/', import.meta.url);
const FIXTURE = new URL('signing_webcrypto.json', FIXTURES);
const CORE = new URL('../../docs/js/gwt-core.js', import.meta.url);

const results = [];
function check(name, ok, detail) {
  results.push({ name, ok });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${ok || !detail ? '' : '\n     ' + detail}`);
}

/* In the page: a key pair made as the app makes one, and a statement signed
 * with it. Defined as text so that it can be put into more than one page. */
const IN_PAGE = `
  window.signingKit = (function () {
    var C = window.GWT.core;
    function hex(buffer) {
      return Array.from(new Uint8Array(buffer)).map(function (b) {
        return (b < 16 ? '0' : '') + b.toString(16);
      }).join('');
    }
    async function makeKey() {
      var pair = await crypto.subtle.generateKey({ name: 'ECDSA', namedCurve: 'P-256' }, true,
        ['sign', 'verify']);
      return { pair: pair, key: hex(await crypto.subtle.exportKey('raw', pair.publicKey)) };
    }
    async function signBytes(pair, bytes) {
      return hex(await crypto.subtle.sign({ name: 'ECDSA', hash: 'SHA-256' }, pair.privateKey, bytes));
    }
    /* the statement with the key's identifier in it, signed: the file's text */
    async function signed(made, statement) {
      var full = Object.assign({}, statement, { key: C.keyId(made.key) });
      var text = C.statementText(full);
      return C.signedText(full, made.key, await signBytes(made.pair, new TextEncoder().encode(text)));
    }
    return { hex: hex, makeKey: makeKey, signBytes: signBytes, signed: signed };
  }());
`;

/* A sign-off and an override as the app will word them, with letters
 * outside ASCII, a figure with a superscript and a reason with a quotation
 * mark and a line break in it: whatever a person may type. */
const SIGN_OFF = {
  says: 'sign-off', project: 'P-7Q2M-EXAMPLE', community: 'Example Village (Zɛdo)',
  borehole: 'EX-01', stage: 'costing', status: 'overridden', value: 'US$ 9,500',
  recommended: 'US$ 10,135', reason: 'The client fixed the price at tender: "9,500".\nSee the letter.',
  figures: { price: 'US$ 10,135', direct_cost: 'US$ 7,238', margin: '20 %', depth: '62 m',
    yield: '0.39 m³/h' },
  sheets: ['3f0a9c0e5d1b7a2244e1c5a90f6b7d8812ab34cd56ef7890a1b2c3d4e5f60718',
    '9e107d9d372bb6826bd81d3542a419d6c0ffee00112233445566778899aabbcc'],
  count: 3, name: 'A. Example', role: 'hydrogeologist', at: '2026-11-21 09:30',
};
const OVERRIDE = {
  says: 'override', project: 'P-7Q2M-EXAMPLE', community: 'Example Village (Zɛdo)',
  borehole: 'EX-01', report: 'completion', requirement: 'water_quality',
  finding: 'No water quality result is loaded.', reason: 'The laboratory result is due on Friday.',
  sheets: [], name: 'B. Sample', role: '', at: '2026-11-21 10:05',
};

await withPage(async (page, base, consoleErrors) => {
  await page.goto(base + '/__engine.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.core);
  await page.addScriptTag({ content: IN_PAGE });

  const where = await page.evaluate(() => ({
    secure: window.isSecureContext, subtle: !!(window.crypto && window.crypto.subtle),
    can: window.GWT.core.canCheckSignatures(),
  }));
  check('signing: the test page is a secure context with Web Crypto, and the engine can check signatures',
    where.secure && where.subtle && where.can, JSON.stringify(where));

  /* --- Web Crypto signs, the engine checks ------------------------------ */
  const agree = await page.evaluate(async () => {
    const C = window.GWT.core, kit = window.signingKit;
    let good = 0, refused = 0, other = 0, disagreed = 0;
    for (let i = 0; i < 24; i += 1) {
      const made = await kit.makeKey(), stranger = await kit.makeKey();
      const bytes = crypto.getRandomValues(new Uint8Array(1 + 37 * i));
      const signature = await kit.signBytes(made.pair, bytes);
      const changed = bytes.slice();
      changed[changed.length - 1] ^= 1;
      const flipped = signature.slice(0, -1) + (signature.slice(-1) === '0' ? '1' : '0');
      /* what the engine says, and what Web Crypto itself says of the same */
      const cases = [[made.key, bytes, signature, true], [made.key, changed, signature, false],
        [made.key, bytes, flipped, false], [stranger.key, bytes, signature, false]];
      for (const [key, message, sig, want] of cases) {
        const mine = C.verifyP256(key, message, sig);
        const raw = new Uint8Array(key.match(/../g).map((h) => parseInt(h, 16)));
        const imported = await crypto.subtle.importKey('raw', raw,
          { name: 'ECDSA', namedCurve: 'P-256' }, false, ['verify']);
        const theirs = await crypto.subtle.verify({ name: 'ECDSA', hash: 'SHA-256' }, imported,
          new Uint8Array(sig.match(/../g).map((h) => parseInt(h, 16))), message);
        if (mine !== theirs) disagreed += 1;
        if (mine === true && want) good += 1;
        else if (mine === false && !want) refused += 1;
        else other += 1;
      }
    }
    return { good, refused, other, disagreed };
  });
  check('signing: every signature Web Crypto makes is one the engine accepts, and it refuses what Web Crypto refuses',
    agree.good === 24 && agree.refused === 72 && agree.other === 0 && agree.disagreed === 0,
    JSON.stringify(agree));

  /* --- a statement, signed and checked ---------------------------------- */
  const made = await page.evaluate(async ([signOff, override]) => {
    const C = window.GWT.core, kit = window.signingKit;
    const a = await kit.makeKey(), b = await kit.makeKey(), c = await kit.makeKey();
    const first = await kit.signed(a, signOff), second = await kit.signed(b, override);
    const third = await kit.signed(c, Object.assign({}, override, { name: 'C. Specimen',
      at: '2027-03-02 08:00' }));
    const members = C.membersText({
      format: C.MEMBERS_FORMAT, version: 1, organisation: 'Example Water Programme',
      issued_on: '2026-11-21',
      members: [
        { name: 'A. Example', role: 'hydrogeologist', key: a.key, valid_from: '', valid_to: '', withdrawn: '' },
        { name: 'B. Sample', role: '', key: b.key, valid_from: '', valid_to: '', withdrawn: '2026-12-01' },
        { name: 'C. Specimen', role: 'supervisor', key: c.key, valid_from: '2026-01-01',
          valid_to: '2026-12-31', withdrawn: '' },
      ],
    });
    /* a statement that names another's key, under a signature that is good
     * for its text: the key it names did not sign it */
    const borrowed = Object.assign({}, signOff, { key: C.keyId(b.key) });
    const borrowedText = C.statementText(borrowed);
    const misnamed = C.signedText(borrowed, a.key,
      await kit.signBytes(a.pair, new TextEncoder().encode(borrowedText)));
    return { signed: [first, second, third], members, misnamed };
  }, [SIGN_OFF, OVERRIDE]);

  const read = (texts, members) => page.evaluate(([list, file]) => list.map((text) => {
    const said = window.GWT.core.checkSigned(text, file);
    return { verdict: said.verdict, standing: said.standing, code: said.code,
      name: said.member ? said.member.name : '', lines: said.lines };
  }), [texts, members]);

  const fresh = await read(made.signed, made.members);
  check('signing: a statement signed in the browser holds, and its signer is placed by the members\' file',
    fresh.map((r) => r.verdict).join() === 'holds,holds,holds' &&
    fresh.map((r) => r.standing).join() === 'listed,withdrawn,out_of_dates' &&
    fresh.map((r) => r.name).join() === 'A. Example,B. Sample,C. Specimen' &&
    fresh[0].lines.some((line) => line.includes('Example Water Programme')) &&
    fresh[0].lines.some((line) => line.includes('is a claim')),
    JSON.stringify(fresh));

  const alone = await read(made.signed, null);
  check('signing: with no members\' file the signature still holds and the signer is not placed',
    alone.every((r) => r.verdict === 'holds' && r.standing === 'not_checked' && !r.name),
    JSON.stringify(alone));

  /* one character of the statement changed, in the file as kept */
  const tampered = made.signed.map((text) => text.replace('EX-01', 'EX-02'));
  const spoiled = await read([...tampered, made.misnamed], made.members);
  check('signing: a statement changed after signing, or naming a key that did not sign it, does not hold',
    tampered.every((text, i) => text !== made.signed[i]) &&
    spoiled.every((r) => r.verdict === 'does_not_hold' && r.standing === 'not_checked'),
    JSON.stringify(spoiled));

  /* --- the committed fixture --------------------------------------------- */
  if (WRITE) {
    const fixture = {
      about: 'Statements signed by Web Crypto in tests/webapp/signing.mjs, by keys that were ' +
        'then thrown away. Every name is made up. Rewritten only by: node ' +
        'tests/webapp/signing.mjs --write-fixtures',
      signed: made.signed, members: made.members, misnamed: made.misnamed,
      expect: fresh.map((r) => ({ verdict: r.verdict, standing: r.standing, name: r.name })),
    };
    await mkdir(FIXTURES, { recursive: true });
    await writeFile(FIXTURE, JSON.stringify(fixture, null, 1) + '\n');
    console.log('wrote ' + FIXTURE.pathname);
  } else {
    const fixture = JSON.parse(await readFile(FIXTURE, 'utf8'));
    const kept = await read(fixture.signed, fixture.members);
    check('signing: the statements committed in fixtures/signing_webcrypto.json still read as they did',
      JSON.stringify(kept.map((r) => ({ verdict: r.verdict, standing: r.standing, name: r.name }))) ===
        JSON.stringify(fixture.expect) && fixture.signed.length === 3,
      'run: node tests/webapp/signing.mjs --write-fixtures\n     ' + JSON.stringify(kept));
    const keptBad = await read([...fixture.signed.map((t) => t.replace('EX-01', 'EX-02')),
      fixture.misnamed], fixture.members);
    check('signing: and each of them, changed, does not hold',
      keptBad.every((r) => r.verdict === 'does_not_hold'), JSON.stringify(keptBad));
  }

  check('no console errors', consoleErrors.length === 0, consoleErrors.join('\n'));
});

/* --- a browser with no whole numbers long enough -------------------------- */
/* The check is arithmetic on 256-bit numbers. A browser too old to have them
 * must still load the engine, and say that it cannot check a signature,
 * rather than refuse to start: so the engine may not write one as a literal
 * (123n), which such a browser cannot even read. */
/* (looked for in the code, not in what the code says of itself) */
const core = (await readFile(CORE, 'utf8')).replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '');
const literals = core.match(/(?<![\w$.'"])\d[\d_]*n\b/g) || [];
check('signing: the engine writes no BigInt literal, which an old browser could not load',
  literals.length === 0, literals.slice(0, 5).join(' '));

await withPage(async (page, base, consoleErrors) => {
  await page.addInitScript(() => { delete window.BigInt; window.BigInt = undefined; });
  await page.goto(base + '/__engine.html', { waitUntil: 'load' });
  await page.waitForFunction(() => window.GWT && window.GWT.core);
  const fixture = WRITE ? null : JSON.parse(await readFile(FIXTURE, 'utf8'));
  const old = await page.evaluate((text) => {
    const C = window.GWT.core;
    const said = text ? C.checkSigned(text) : null;
    return { has: typeof BigInt, can: C.canCheckSignatures(),
      raw: C.verifyP256('04' + 'a'.repeat(128), 'x', 'b'.repeat(128)),
      verdict: said ? said.verdict : 'cannot_check', lines: said ? said.lines : ['too old'],
      /* reading a statement needs no arithmetic and still works */
      reads: text ? C.readSigned(text) !== null : true };
  }, fixture ? fixture.signed[0] : null);
  check('signing: with no BigInt the engine still loads, reads a statement and says it cannot check it',
    old.has === 'undefined' && old.can === false && old.raw === null &&
    old.verdict === 'cannot_check' && old.reads && /too old/.test(old.lines[0]),
    JSON.stringify(old));
  check('no console errors without BigInt', consoleErrors.length === 0, consoleErrors.join('\n'));
});

const failed = results.filter((r) => !r.ok);
console.log(`\n${results.length - failed.length}/${results.length} signing checks passed`);
process.exit(failed.length ? 1 : 0);
