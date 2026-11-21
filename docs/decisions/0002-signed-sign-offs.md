# 0002: Signed sign-offs

- **Status:** decided for building, 21 November 2026 (PLAN.md step 8.2). The
  six choices under "For the programme to decide" are defaults, taken so that
  work could go on; QUESTIONS.md item 32 puts them to the programme.
- **Decision:** a sign-off and a readiness override become a *signed
  statement*: a small text saying what one person decided and on which
  figures, with a signature over that exact text made by a key only they
  hold. Signing is done in the browser app; checking is done in both engines
  and from the command line, with no network and no new dependency.
- **How it was reached:** a read-only map of everything the step touches
  (five readers), then three independent designs from different angles
  (the smallest honest one, security first, the person in the field first),
  each attacked by a critic. All three came back sound once fixes were
  applied, and they agree on what follows.

## What was there before

- A Depth Spine sign-off was a few lines of display text and a typed name,
  kept only by the browser app. It was tied to no data: changing the design
  or the price afterwards left it standing. The Streamlit app showed a
  decision for the session only, under a fixed name, and kept nothing.
- A readiness override was a reason and a typed name.
- Documents (step 8.1) carry a manifest both engines write byte for byte,
  and must rebuild identically. A signature is different every time one is
  made, so one cannot be made inside anything that has to rebuild the same.

## The design

1. **The statement.** A JSON text of named values in a fixed order: text,
   whole numbers, lists of text, or one level of named text. No decimal
   numbers, which is where the two engines' writers differ: a figure is
   written as the text the person saw. It is written as `manifest.json` is,
   and read back only if writing what was read gives the same text again.
2. **What it says.** Who (a name, a role, and the identifier of their key),
   when (their device's clock, stated as a claim), which project, the
   decision, the figures decided on, and the SHA-256 of each field sheet the
   project held. The statement names its key, so no other key can claim it.
3. **Tied to the data.** A sign-off or an override is in force only while
   the project still gives the same figures and the same sheets. When it
   does not, the app says what moved; a report no longer prints the sign-off
   as one, and an override stops applying, so the document goes back to
   provisional. This is decided where the record is used, not where it is
   entered.
4. **Keys.** ECDSA over P-256, made by Web Crypto. A key is kept only in
   passphrase-protected form, in a store of its own that "Reset everything"
   does not wipe; its backup file is that same protected form. It is locked
   until its owner unlocks it for the session.
5. **Checking.** The signature check is written out with whole-number
   arithmetic in both engines, as the QR encoder's field arithmetic is, and
   held by parity, by the standard's own test signatures, by a test-only
   library that makes real keys, and by statements a browser signed.
6. **Whose key it is.** An organisation publishes one small file of its
   members' keys, with the days each is valid for and any withdrawal. A
   signer is "listed in the members' file you gave", never simply "trusted".
   A file with a fault is refused whole.
7. **A typed name stays honest.** A record with no signature prints as a
   typed name, not signed.

## What a signature shows, and what it does not

- It shows that the holder of a key approved exactly this text.
- It does not show who holds the key. The members' file does, and is only as
  good as the way the checker came by it.
- The time in a statement is the signer's own device's. A withdrawn key is
  therefore not relied on for any date.
- It does not show that a document quoting the statement is the toolkit's
  own or unchanged. The document's manifest and issue record do that.

## How it is built

In stages, each its own pull request.

1. **The foundation, in both engines (done).** `groundwater/signing.py` and
   `web/src/gwt-core/585-signing.js`: the statement's text, the strict
   readers, the members' file, the signature check, and the command
   `groundwater signature`. Nothing in either app changes yet.
2. **The browser app.** The key store and its two cards, signing a sign-off
   and an override, what makes one stale, statements kept with the project,
   and how they print.
3. **Checking in both apps.** The Verify page, the evidence bundle's
   `signatures/` folder, and what the Python app says of what only the
   browser does.

## For the programme to decide

| Choice | Default taken | The other way |
|---|---|---|
| When the passphrase is asked for | Once per session of the app | At every signing: safer on a shared device, more to type |
| A signed override whose data has changed | Stops applying | Keeps applying, with a warning |
| A sign-off with no key | Still allowed, labelled as a typed name | Refused in the browser app |
| The members' file | A plain list, known by a short code compared by voice | Signed by an organisation key: stronger, and needs a key-holder |
| Signing the issue of each document | Not in this step | Add it: larger, and the plan does not name it |
| Sign-offs in project files made before this | Shown as typed names | Stop counting until recorded again |

## What would reopen it

- A browser the programme relies on that has no whole numbers long enough
  for the check (it would say so, and the command line would have to be
  used instead).
- A decision that documents themselves must be signed at issue, which
  changes where a signature has to live.
