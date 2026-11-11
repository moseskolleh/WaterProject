"""The changelog's index, the files it lists, and the release notes cut from it.

CHANGELOG.md was one file, and by November 2026 it was 433,445 bytes in 1,729
lines. The release workflow built a release's notes by cutting the version's
section out of it, GitHub refuses a release body over 125,000 characters, and
the section waiting to be released was 357,000: the next tag would have built
everything and been refused at the last step. The text now lives in
``changelog/<version>.md``, one file per version, and CHANGELOG.md is the
index: a section per version, each a link to its file and one bullet per entry
carrying the entry's heading.

Two files that must say the same thing drift, and an entry written into one
and not the other would be either a heading with no text or text no reader of
the index is told about. These tests hold the two together, and run the
workflow's own script, read out of ``.github/workflows/release.yml``, so that a
release that would be refused is refused here first. They read text files and
start a short Python process for each section and three more, so they need
nothing installed.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "CHANGELOG.md"
TEXTS = REPO / "changelog"
WORKFLOW = REPO / ".github" / "workflows" / "release.yml"

UNRELEASED = "Unreleased"
# GitHub's limit on a release body. The workflow's later step, "Record the
# release", appends the web app's release identifier and the install command
# to the notes, a few hundred characters, so the notes cut here have to leave
# room for them.
RELEASE_BODY_LIMIT = 125_000
ROOM_FOR_THE_RECORD = 2_000


def _stem(section: str) -> str:
    return "unreleased" if section == UNRELEASED else section


def _sections() -> list[tuple[str, list[str]]]:
    """Each "## " section of the index, in order: its name and its lines."""
    sections: list[tuple[str, list[str]]] = []
    for line in INDEX.read_text(encoding="utf-8").split("\n"):
        if line.startswith("## "):
            sections.append((line[3:], []))
        elif sections:
            sections[-1][1].append(line)
    return sections


def _headings(path: Path) -> list[str]:
    """The "### " headings of one version's file, outside any code fence."""
    headings, fenced = [], False
    for line in path.read_text(encoding="utf-8").split("\n"):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("### "):
            headings.append(line[4:])
    return headings


SECTIONS = _sections()
NAMES = [name for name, _ in SECTIONS]


def test_every_section_has_a_file_and_every_file_a_section():
    """A file under changelog/ that no section lists is text nobody is sent
    to, and a section with no file is a list of headings and nothing else."""
    assert NAMES, "CHANGELOG.md has no '## ' section"
    assert len(set(NAMES)) == len(NAMES), NAMES
    assert sorted(p.name for p in TEXTS.glob("*.md")) == sorted(
        f"{_stem(name)}.md" for name in NAMES
    )
    # nothing else belongs in the folder: the release workflow links to it
    assert [p.name for p in TEXTS.iterdir() if p.suffix != ".md"] == []


@pytest.mark.parametrize("name", NAMES)
def test_a_section_lists_the_headings_of_its_file(name):
    """In order, none missing, none extra, and not a character different: the
    headings are the only summary the index gives."""
    lines = [line for line in dict(SECTIONS)[name] if line.strip()]
    stem = _stem(name)
    # the form the release workflow requires of a section's first line, which
    # it then leaves out of the notes
    assert lines[:1] == [f"Full text: [changelog/{stem}.md](changelog/{stem}.md)"]
    listed = lines[1:]
    not_bullets = [line for line in listed if not line.startswith("- ")]
    assert not_bullets == [], "a section holds its link and its bullets only"

    text = TEXTS / f"{stem}.md"
    assert text.read_text(encoding="utf-8").startswith(f"# {name}\n\n")
    headings = _headings(text)
    assert [line[2:] for line in listed] == headings
    assert len(set(headings)) == len(headings), "two entries under one heading"
    if name != UNRELEASED:
        assert headings, f"{name} was released with no entries"


@pytest.mark.parametrize("name", NAMES)
def test_a_versions_file_holds_entries_and_nothing_else(name):
    """Under its title a version's file is "### " entries, with deeper headings
    inside them. Text under a "## " heading would belong to no entry: the
    index lists entries by their "### " headings, so nothing would tell a
    reader it was there."""
    fenced, strays = False, []
    for number, line in enumerate(
            (TEXTS / f"{_stem(name)}.md").read_text(encoding="utf-8").split("\n"), start=1):
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced and (line.startswith("## ") or (number > 1 and line.startswith("# "))):
            strays.append((number, line))
    assert not strays, f"changelog/{_stem(name)}.md has headings the index cannot list: {strays}"


def test_the_index_writes_no_angle_bracket_outside_code():
    """GitHub drops a tag it does not know, so ``changelog/<version>.md``
    written without backticks is shown as "changelog/.md", and the index is
    read on GitHub more than anywhere."""
    for number, line in enumerate(INDEX.read_text(encoding="utf-8").split("\n"), 1):
        outside_code = re.sub(r"`[^`]*`", "", line)
        assert not re.search(r"<[A-Za-z/!]", outside_code), f"CHANGELOG.md:{number}: {line}"


def _notes_script() -> str:
    """The Python the release workflow runs to write the notes, as written.

    It is the one inline script in the workflow that reads CHANGELOG.md. The
    arguments it is given are checked too, because ``_cut_notes`` passes the
    same three.
    """
    workflow = WORKFLOW.read_text(encoding="utf-8")
    inline = re.findall(
        r"^ +python - ([^\n]+) <<'EOF'\n(.*?)^ +EOF$", workflow, re.S | re.M
    )
    reading = [(args, body) for args, body in inline if "CHANGELOG.md" in body]
    assert len(reading) == 1, "expected one script in release.yml to read CHANGELOG.md"
    args, body = reading[0]
    assert args == '"$VERSION" "$TAG" "$GITHUB_REPOSITORY"'
    return textwrap.dedent(body)


def _cut_notes(
    where: Path, section: str, version: str, *,
    rename_text: bool = True, rename_link: bool = True,
):
    """Run the workflow's script for ``version`` in a copy of the changelog.

    A released section is cut under its own name. "Unreleased" is cut the way
    the index's preamble says a release is: the section renamed, and its link
    and ``changelog/unreleased.md`` renamed with it unless ``rename_link`` or
    ``rename_text`` is off. The script writes release-notes.md beside the
    changelog it reads, which is why it is never run in the checkout.
    """
    where.mkdir()
    shutil.copytree(TEXTS, where / "changelog")
    index = INDEX.read_text(encoding="utf-8")
    if section != version:
        old, new = f"changelog/{_stem(section)}.md", f"changelog/{version}.md"
        index = index.replace(f"## {section}\n", f"## {version}\n")
        if rename_link:
            index = index.replace(old, new)
        if rename_text:
            (where / old).rename(where / new)
    (where / "CHANGELOG.md").write_text(index, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-", version, f"v{version}", "owner/repository"],
        input=_notes_script(), capture_output=True, text=True, cwd=where,
    )
    notes = where / "release-notes.md"
    return result, notes.read_text(encoding="utf-8") if notes.exists() else None


@pytest.mark.parametrize("name", NAMES)
def test_the_release_notes_fit_in_a_release_body(tmp_path, name):
    """Every released version, and Unreleased as if it were tagged today."""
    version = "99.0.0" if name == UNRELEASED else name
    result, notes = _cut_notes(tmp_path / "cut", name, version)
    headings = _headings(TEXTS / f"{_stem(name)}.md")
    if not headings:
        # only Unreleased may be empty, and an empty release is refused
        assert result.returncode != 0
        assert f"lists no entries under '## {version}'" in result.stderr
        return
    assert result.returncode == 0, result.stderr
    text = f"changelog/{version}.md"
    link = f"https://github.com/owner/repository/blob/v{version}/{text}"
    lines = notes.split("\n")
    assert lines[: len(headings)] == [f"- {heading}" for heading in headings]
    # the link to the tagged file is the only one: the index's own is relative
    assert lines[len(headings):] == [
        "", f"The full text of each entry: [{text}]({link})", "",
    ]
    assert len(notes) < RELEASE_BODY_LIMIT - ROOM_FOR_THE_RECORD


def test_a_release_is_refused_while_its_text_is_still_unreleased(tmp_path):
    """Renaming the section and forgetting the file would publish a link to
    a page that does not exist at the tag."""
    if UNRELEASED not in NAMES:
        pytest.skip("no Unreleased section to cut")
    result, notes = _cut_notes(tmp_path / "cut", UNRELEASED, "99.0.0", rename_text=False)
    assert result.returncode != 0
    assert "changelog/99.0.0.md does not exist" in result.stderr
    assert notes is None


def test_a_release_is_refused_while_its_link_still_names_unreleased(tmp_path):
    """Renaming the section and the file and forgetting the link would publish
    the stale link as the first line of the notes: the workflow knows the
    section's own link by the file it names. The release workflow does not run
    these tests, so the script has to refuse it by itself."""
    if UNRELEASED not in NAMES:
        pytest.skip("no Unreleased section to cut")
    result, notes = _cut_notes(tmp_path / "cut", UNRELEASED, "99.0.0", rename_link=False)
    assert result.returncode != 0
    assert "does not begin with" in result.stderr
    assert "'Full text: [changelog/99.0.0.md](changelog/99.0.0.md)'" in result.stderr
    assert notes is None


def test_a_version_with_no_section_is_refused(tmp_path):
    result, notes = _cut_notes(tmp_path / "cut", "99.0.0", "99.0.0")
    assert result.returncode != 0
    assert "CHANGELOG.md has no section headed '## 99.0.0'" in result.stderr
    assert notes is None
