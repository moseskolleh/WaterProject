"""Build the field team's user guide as a web page (PLAN.md step 9.5).

``docs/user_guide.md`` is the guide, and stays the one place it is written.
It used to be published as it is written, so a reader on a phone was handed
2,500 lines of Markdown source. This turns it into ``docs/user_guide.html``:
the same words, with a list of contents, tables that scroll sideways instead
of pushing the page wide, the pictures at a size a phone can show, light and
dark to follow the device, and a print sheet.

    python web/build_guide.py            write docs/user_guide.html
    python web/build_guide.py --check    fail if the committed page is not
                                         what the guide builds to, or the
                                         guide and its pictures disagree
    python web/build_guide.py --shrink docs/guide/a.png ...
                                         repack screenshots in a palette

The pictures are the app's own pages, taken by ``web/guide_shots.mjs`` and
never by hand; that script's header says how they are kept from going
stale. What is checked here is that the guide and the pictures are one set:
every picture the guide shows exists, every picture in ``docs/guide`` is
shown, and the list in ``web/guide/shots.json`` is that same set, each with
the record of the words it was taken of.

Markdown is read by markdown-it-py at the version pinned in the dev extra,
as CommonMark with tables and no raw HTML, so that the page is a function of
the guide and of nothing else: no date, no version, no machine.

``--shrink`` is called by ``web/guide_shots.mjs`` on each picture it takes.
A screenshot of this app is a few dozen flat colours, and a palette of 128
of them is a third the size of the true-colour file; the pictures go on the
device with the app (``web/build_offline.py``), where the size is paid for
in somebody's mobile data.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import struct
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"
SOURCE = DOCS / "user_guide.md"
OUT = DOCS / "user_guide.html"
PICTURES = DOCS / "guide"
RECORD = REPO / "web" / "guide"

# How many colours a repacked screenshot keeps. The app's pages are flat
# greys and one green; the maps and charts are the most colourful thing in
# them and show no banding at this many.
PALETTE = 128


class GuideError(Exception):
    """The guide could not be built, or it and its pictures disagree."""


def _slug(text: str, taken: set[str]) -> str:
    """An address for a heading: its words, lower case, joined by hyphens."""
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "section"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def _png_size(path: Path) -> tuple[int, int]:
    """The width and height a PNG declares, read from its header."""
    head = path.read_bytes()[:24]
    if len(head) < 24 or head[:8] != b"\x89PNG\r\n\x1a\n" or head[12:16] != b"IHDR":
        raise GuideError(f"{path.relative_to(REPO)} is not a PNG")
    return struct.unpack(">II", head[16:24])


def pictures_shown(markdown: str) -> list[str]:
    """The pictures the guide shows, as paths relative to docs/, in order."""
    return re.findall(r"!\[[^\]]*\]\((guide/[^)\s]+)", markdown)


def check_pictures(markdown: str) -> None:
    """The guide, docs/guide and web/guide/shots.json name one set of pictures."""
    shown = pictures_shown(markdown)
    repeated = sorted({p for p in shown if shown.count(p) > 1})
    if repeated:
        raise GuideError("the guide shows a picture twice: " + ", ".join(repeated))
    missing = [p for p in shown if not (DOCS / p).is_file()]
    if missing:
        raise GuideError(
            "the guide shows pictures that do not exist: " + ", ".join(missing)
            + "\nAdd each to SHOTS in web/guide_shots.mjs and run: nox -s guide"
        )
    on_disk = sorted(p.name for p in PICTURES.glob("*") if p.is_file())
    unused = [name for name in on_disk if f"guide/{name}" not in shown]
    if unused:
        raise GuideError(
            "docs/guide holds pictures the guide does not show: " + ", ".join(unused)
            + "\nShow each in docs/user_guide.md, or take it off SHOTS in "
            "web/guide_shots.mjs and run: nox -s guide"
        )
    lock = RECORD / "shots.json"
    listed = json.loads(lock.read_text(encoding="utf-8"))["shots"] if lock.is_file() else []
    if sorted(f"{name}.png" for name in listed) != on_disk:
        raise GuideError(
            "web/guide/shots.json does not list the pictures in docs/guide; run: nox -s guide"
        )
    unrecorded = [name for name in listed if not (RECORD / f"{name}.txt").is_file()]
    if unrecorded:
        raise GuideError(
            "no record of the words these pictures were taken of: "
            + ", ".join(unrecorded) + "; run: nox -s guide"
        )


def _figure(src: str, alt: str, caption: str) -> str:
    width, height = _png_size(DOCS / src)
    # A picture taller than it is wide is a phone's, taken at two device
    # pixels to one; the stylesheet shows it at a phone's width.
    shape = "tall" if height > width else "wide"
    said = f"<figcaption>{html.escape(caption)}</figcaption>" if caption else ""
    return (
        f'<figure class="shot {shape}">'
        f'<img src="{html.escape(src)}" alt="{html.escape(alt)}" '
        f'width="{width}" height="{height}" loading="lazy" decoding="async">'
        f"{said}</figure>\n"
    )


def render(markdown: str) -> tuple[str, str, list[tuple[str, str]]]:
    """The guide's title, its body as HTML, and its contents (address, heading)."""
    try:
        from markdown_it import MarkdownIt
        from markdown_it.token import Token
    except ImportError as exc:  # pragma: no cover - an install problem
        raise GuideError(
            "markdown-it-py is not installed; it comes with the dev extra:\n"
            "  python -m pip install -e '.[dev]'"
        ) from exc

    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = parser.parse(markdown)

    title = ""
    contents: list[tuple[str, str]] = []
    taken: set[str] = set()
    out: list = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if token.type == "heading_open":
            words = "".join(
                child.content for child in (tokens[i + 1].children or [])
                if child.type in ("text", "code_inline")
            )
            if token.tag == "h1" and not title:
                title = words
            else:
                slug = _slug(words, taken)
                token.attrSet("id", slug)
                if token.tag == "h2":
                    contents.append((slug, words))
        # A paragraph that is one picture and nothing else is a figure; its
        # caption is the title given after the address, in quotes.
        if (token.type == "paragraph_open" and i + 2 < len(tokens)
                and tokens[i + 1].type == "inline"
                and len(tokens[i + 1].children or []) == 1
                and tokens[i + 1].children[0].type == "image"):
            image = tokens[i + 1].children[0]
            figure = Token("html_block", "", 0)
            figure.content = _figure(
                str(image.attrGet("src")), image.content, str(image.attrGet("title") or "")
            )
            out.append(figure)
            i += 3
            continue
        out.append(token)
        i += 1

    renderer = parser.renderer
    # a wide table scrolls inside its own box instead of widening the page
    renderer.rules["table_open"] = lambda *a, **k: '<div class="table-wrap"><table>\n'
    renderer.rules["table_close"] = lambda *a, **k: "</table></div>\n"
    body = renderer.render(out, parser.options, {})
    if not title:
        raise GuideError("the guide has no heading of the first level to take its title from")
    return title, body, contents


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>__TITLE__ - Groundwater Toolkit</title>
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="css/guide.css">
</head>
<body>
<!-- GENERATED FILE - do not edit. The guide is written in docs/user_guide.md;
     rebuild this page with: python web/build_guide.py -->
<a class="skip" href="#guide">Skip to the guide</a>
<header class="top">
  <a class="brand" href="index.html"><img src="icon.svg" alt="" width="24" height="24">Groundwater Toolkit</a>
  <span class="here">User guide</span>
  <a class="open-app" href="index.html">Open the app</a>
</header>
<div class="frame">
<nav class="contents" aria-label="Contents">
<details open>
<summary>Contents</summary>
<ol>
__CONTENTS__
</ol>
</details>
</nav>
<main id="guide">
<h1>__TITLE__</h1>
__BODY__
</main>
</div>
<script>
/* Two conveniences; without this script the page is whole. */
(function () {
  /* On a phone the contents sit above the guide and would fill the first
   * two screens, so there they start closed, and choosing a section closes
   * them again. */
  var box = document.querySelector('.contents details');
  if (box && window.matchMedia) {
    var narrow = window.matchMedia('(max-width: 899px)');
    if (narrow.matches) box.open = false;
    box.addEventListener('click', function (event) {
      if (narrow.matches && event.target.closest && event.target.closest('a')) box.open = false;
    });
  }
  /* A table or a listing too wide for the screen scrolls sideways in its
   * own box. A finger can do that anywhere; the keyboard only in a box it
   * can reach, so the ones that scroll, and only those, take a place in the
   * Tab order. */
  function reach() {
    var boxes = document.querySelectorAll('.table-wrap, pre');
    for (var i = 0; i < boxes.length; i += 1) {
      if (boxes[i].scrollWidth > boxes[i].clientWidth) boxes[i].setAttribute('tabindex', '0');
      else boxes[i].removeAttribute('tabindex');
    }
  }
  reach();
  window.addEventListener('resize', reach);
})();
</script>
</body>
</html>
"""


def build() -> str:
    """The whole page, as text."""
    markdown = SOURCE.read_text(encoding="utf-8")
    check_pictures(markdown)
    title, body, contents = render(markdown)
    # the first-level heading is the page's own, written by the template
    body = re.sub(r"\A<h1>.*?</h1>\n", "", body, count=1, flags=re.S)
    listed = "\n".join(
        f'<li><a href="#{slug}">{html.escape(words)}</a></li>' for slug, words in contents
    )
    return (PAGE.replace("__TITLE__", html.escape(title))
            .replace("__CONTENTS__", listed).replace("__BODY__", body.rstrip("\n")))


def shrink(paths: list[str]) -> None:
    """Repack each PNG in a palette of PALETTE colours, in place."""
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - an install problem
        raise GuideError("Pillow is not installed; it comes with matplotlib") from exc
    for name in paths:
        path = Path(name)
        before = path.stat().st_size
        with Image.open(path) as picture:
            packed = picture.convert("RGB").quantize(
                colors=PALETTE, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE
            )
        packed.save(path, "PNG", optimize=True)
        print(f"{path.name}: {before:,} -> {path.stat().st_size:,} bytes")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("--check", action="store_true",
                        help="fail if docs/user_guide.html is not what the guide builds to")
    parser.add_argument("--shrink", nargs="+", metavar="PNG",
                        help="repack these screenshots in a palette, in place")
    args = parser.parse_args(argv)
    try:
        if args.shrink:
            shrink(args.shrink)
            return 0
        page = build()
    except GuideError as exc:
        print(f"build_guide: {exc}", file=sys.stderr)
        return 1
    if args.check:
        if not OUT.is_file() or OUT.read_text(encoding="utf-8") != page:
            print("build_guide: docs/user_guide.html is not what docs/user_guide.md "
                  "builds to. Rebuild it with:\n  python web/build_guide.py",
                  file=sys.stderr)
            return 1
        print(f"docs/user_guide.html is current ({len(pictures_shown(SOURCE.read_text(encoding='utf-8')))} pictures)")
        return 0
    OUT.write_text(page, encoding="utf-8")
    print(f"wrote {OUT.relative_to(REPO)} ({len(page):,} characters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
