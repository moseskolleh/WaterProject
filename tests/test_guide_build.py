"""The user guide as a web page (PLAN.md step 9.5).

``docs/user_guide.md`` is the guide; ``web/build_guide.py`` builds
``docs/user_guide.html`` from it, and ``web/guide_shots.mjs`` takes the
pictures it shows from the app. These hold the three together without a
browser: the committed page is what the guide builds to, the guide and the
pictures are one set, and what the guide says of the app's pages is so.
``tests/webapp/guide.mjs`` opens the page in a browser, and
``node web/guide_shots.mjs --check`` asks whether each picture still shows
its page as it reads.
"""

import importlib.util
import json
import re
import struct
import subprocess
import sys
import zlib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GUIDE = REPO / "docs" / "user_guide.md"
PAGE = REPO / "docs" / "user_guide.html"


def _builder():
    spec = importlib.util.spec_from_file_location(
        "build_guide", REPO / "web" / "build_guide.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _png(path: Path, width: int, height: int, colour=(27, 122, 46)) -> None:
    """A real PNG of one flat colour, without a library."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(colour) * width
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


@pytest.fixture
def staged(tmp_path, monkeypatch):
    """The builder, pointed at an empty docs/ and web/guide of its own."""
    builder = _builder()
    docs, record = tmp_path / "docs", tmp_path / "web" / "guide"
    (docs / "guide").mkdir(parents=True)
    record.mkdir(parents=True)
    monkeypatch.setattr(builder, "REPO", tmp_path)
    monkeypatch.setattr(builder, "DOCS", docs)
    monkeypatch.setattr(builder, "PICTURES", docs / "guide")
    monkeypatch.setattr(builder, "RECORD", record)
    monkeypatch.setattr(builder, "SOURCE", docs / "user_guide.md")
    monkeypatch.setattr(builder, "OUT", docs / "user_guide.html")

    def stage(names):
        for name in names:
            _png(docs / "guide" / f"{name}.png", 40, 20)
            (record / f"{name}.txt").write_text("words\n", encoding="utf-8")
        (record / "shots.json").write_text(
            json.dumps({"app": "", "shots": list(names)}), encoding="utf-8"
        )

    builder.stage = stage
    return builder


# ------------------------------------------------------------ the committed page


def test_the_committed_page_is_what_the_guide_builds_to():
    done = subprocess.run(
        [sys.executable, str(REPO / "web" / "build_guide.py"), "--check"],
        capture_output=True, text=True,
    )
    assert done.returncode == 0, done.stderr


def test_the_page_carries_no_date_and_no_machine():
    # the page is a function of the guide alone, or the check above would
    # fail on the day after it was built or on somebody else's computer
    builder = _builder()
    assert builder.build() == builder.build()
    assert str(REPO) not in PAGE.read_text(encoding="utf-8")
    # all the template adds to the guide's words is the three things it is given
    assert set(re.findall(r"__[A-Z]+__", builder.PAGE)) == {"__TITLE__", "__CONTENTS__", "__BODY__"}
    assert not re.search(r"\b20\d\d\b", builder.PAGE)


def test_every_section_is_in_the_contents_once_and_in_order():
    page = PAGE.read_text(encoding="utf-8")
    listed = re.findall(r'<li><a href="#([^"]+)">', page.split("</nav>")[0])
    sections = re.findall(r'<h2 id="([^"]+)">', page)
    assert listed == sections
    assert len(sections) == len(set(sections)) >= 25
    assert "14-troubleshooting" in sections and "15-glossary" in sections


def test_no_two_sections_share_a_number():
    # sections 9c and 9d were each used twice, so "see section 9c" named two
    numbers = re.findall(r"^## (\d+[a-z]?)\. ", GUIDE.read_text(encoding="utf-8"), re.M)
    assert len(numbers) == len(set(numbers)), sorted(
        n for n in set(numbers) if numbers.count(n) > 1
    )


def test_a_section_the_guide_refers_to_exists():
    guide = GUIDE.read_text(encoding="utf-8")
    numbers = set(re.findall(r"^## (\d+[a-z]?)\. ", guide, re.M))
    cited = set(re.findall(r"\bsections? (\d+[a-z]?)\b", guide))
    cited |= set(re.findall(r"\bsections? \d+[a-z]? (?:and|to) (\d+[a-z]?)\b", guide))
    assert cited and cited <= numbers, sorted(cited - numbers)


def test_a_link_within_the_guide_lands_on_something():
    page = PAGE.read_text(encoding="utf-8")
    ids = set(re.findall(r'\bid="([^"]+)"', page))
    targets = set(re.findall(r'href="#([^"]+)"', page))
    assert targets and targets <= ids, sorted(targets - ids)


def test_an_address_of_the_app_in_the_guide_is_a_page_of_the_app():
    header = (REPO / "web" / "src" / "gwt-app" / "000-header.js").read_text(encoding="utf-8")
    groups = header.split("var NAV_GROUPS = [", 1)[1].split("\n  ];", 1)[0]
    pages = set(re.findall(r"\['([a-z]+)', '", groups))
    assert {"overview", "pumping", "templates"} <= pages
    named = set(re.findall(r"\(index\.html#/([a-z]+)", GUIDE.read_text(encoding="utf-8")))
    assert len(named) >= 10 and named <= pages, sorted(named - pages)


def test_the_guide_and_the_pictures_are_one_set():
    builder = _builder()
    guide = GUIDE.read_text(encoding="utf-8")
    builder.check_pictures(guide)
    shown = builder.pictures_shown(guide)
    assert len(shown) >= 15
    # and the script that takes them lists the same ones
    script = (REPO / "web" / "guide_shots.mjs").read_text(encoding="utf-8")
    taken = re.findall(r"\{ name: '([a-z-]+)', device:", script)
    assert sorted(f"guide/{name}.png" for name in taken) == sorted(shown)


def test_every_picture_says_what_it_shows_and_has_a_caption():
    guide = GUIDE.read_text(encoding="utf-8")
    pictures = re.findall(r'^!\[([^\]]*)\]\((guide/\S+)(?: "([^"]*)")?\)$', guide, re.M)
    assert len(pictures) == len(_builder().pictures_shown(guide))
    for alt, src, caption in pictures:
        # the words for a reader who cannot see it say what is on the page,
        # which the caption, written for one who can, need not
        assert len(alt) >= 40, src
        assert caption and caption != alt, src


def test_the_pictures_are_small_enough_to_put_on_a_phone_with_the_app():
    sizes = {p.name: p.stat().st_size for p in (REPO / "docs" / "guide").glob("*.png")}
    assert max(sizes.values()) < 120_000, max(sizes, key=sizes.get)
    assert sum(sizes.values()) < 1_200_000


def test_the_offline_release_carries_the_page_its_sheet_and_its_pictures():
    worker = (REPO / "docs" / "sw.js").read_text(encoding="utf-8")
    listed = set(re.findall(r"^  '([^']+)',$", worker, re.M))
    shown = _builder().pictures_shown(GUIDE.read_text(encoding="utf-8"))
    assert {"user_guide.html", "css/guide.css", *shown} <= listed
    # the Markdown it is built from is not what a reader is handed
    assert "user_guide.md" not in listed


# -------------------------------------------------------------------- the builder


def test_a_heading_gets_an_address_and_a_repeat_gets_its_own(staged):
    staged.stage([])
    title, body, contents = staged.render(
        "# The Guide\n\n## 2a. VES co-pilot (browser app)\n\ntext\n\n"
        "### Before you start\n\n## Notes\n\n## Notes\n"
    )
    assert title == "The Guide"
    assert contents == [
        ("2a-ves-co-pilot-browser-app", "2a. VES co-pilot (browser app)"),
        ("notes", "Notes"), ("notes-2", "Notes"),
    ]
    assert '<h2 id="2a-ves-co-pilot-browser-app">' in body
    assert '<h3 id="before-you-start">' in body


def test_a_picture_alone_in_a_paragraph_is_a_figure_with_its_size(staged):
    staged.stage(["tiles"])
    _png(staged.PICTURES / "phone.png", 20, 60)
    _, body, _ = staged.render(
        '# G\n\n![What the page shows](guide/tiles.png "The caption & more")\n\n'
        "![A phone](guide/phone.png)\n"
    )
    assert ('<figure class="shot wide"><img src="guide/tiles.png" alt="What the page shows" '
            'width="40" height="20" loading="lazy" decoding="async">'
            "<figcaption>The caption &amp; more</figcaption></figure>") in body
    # taller than wide is a phone's picture, shown at a phone's width
    assert '<figure class="shot tall"><img src="guide/phone.png"' in body
    assert "<p><img" not in body


def test_a_table_scrolls_in_its_own_box_and_markup_in_the_guide_is_text(staged):
    staged.stage([])
    _, body, _ = staged.render(
        "# G\n\n| a | b |\n|---|---|\n| 1 | `<project>` |\n\nSee <script>alert(1)</script>.\n"
    )
    assert body.count('<div class="table-wrap"><table>') == 1
    assert body.count("</table></div>") == 1
    assert "<code>&lt;project&gt;</code>" in body
    assert "<script>" not in body and "&lt;script&gt;" in body


def test_a_guide_with_no_title_is_refused(staged):
    staged.stage([])
    with pytest.raises(staged.GuideError, match="no heading of the first level"):
        staged.render("## Only a section\n")


@pytest.mark.parametrize("guide, staged_names, extra, said", [
    ("![a](guide/gone.png)", [], None, "pictures that do not exist: guide/gone.png"),
    ("no pictures", ["spare"], None, "pictures the guide does not show: spare.png"),
    ("![a](guide/one.png)\n\n![b](guide/one.png)", ["one"], None, "shows a picture twice"),
    ("![a](guide/one.png)", ["one"], "unlisted", "does not list the pictures"),
    ("![a](guide/one.png)", ["one"], "unrecorded", "no record of the words"),
])
def test_the_guide_and_the_pictures_coming_apart_is_said(staged, guide, staged_names, extra, said):
    staged.stage(staged_names)
    if extra == "unlisted":
        (staged.RECORD / "shots.json").write_text('{"app": "", "shots": []}', encoding="utf-8")
    if extra == "unrecorded":
        (staged.RECORD / "one.txt").unlink()
    with pytest.raises(staged.GuideError, match=said):
        staged.check_pictures(guide)


def test_check_fails_on_a_page_edited_by_hand_and_passes_on_a_fresh_build(staged, capsys):
    staged.stage(["one"])
    staged.SOURCE.write_text('# Guide\n\n## First\n\n![What it shows](guide/one.png "Caption")\n',
                             encoding="utf-8")
    assert staged.main(["--check"]) == 1          # not built yet
    assert staged.main([]) == 0
    assert staged.main(["--check"]) == 0
    staged.OUT.write_text(staged.OUT.read_text(encoding="utf-8").replace("Caption", "Edited"),
                          encoding="utf-8")
    capsys.readouterr()
    assert staged.main(["--check"]) == 1
    assert "python web/build_guide.py" in capsys.readouterr().err


def test_shrink_repacks_a_screenshot_smaller_and_keeps_its_size(staged, tmp_path):
    pytest.importorskip("PIL")
    from PIL import Image

    # a "screenshot": flat areas and a gradient, in true colour
    picture = Image.new("RGB", (300, 200), "#f6f7f5")
    for x in range(300):
        for y in range(60, 140):
            picture.putpixel((x, y), (27 + x % 7, 122 + y % 5, 46 + (x + y) % 3))
    path = tmp_path / "shot.png"
    picture.save(path, "PNG")
    before = path.stat().st_size
    staged.shrink([str(path)])
    with Image.open(path) as packed:
        assert packed.size == (300, 200)
        assert packed.mode == "P" and len(packed.getcolors(maxcolors=256)) <= staged.PALETTE
    assert path.stat().st_size < before
