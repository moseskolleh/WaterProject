"""Project folder management.

Every borehole project lives in one folder with a fixed layout::

    <project>/
        project.yaml     site metadata
        config.yaml      optional configuration overrides (house style,
                         VES, pumping and design rules)
        raw/             field data exactly as received (never modified)
        processed/       parsed and derived tables (CSV)
        figures/         all generated figures (PNG)
        reports/         generated .docx reports

Re-running the analysis on the same raw data regenerates processed/,
figures/ and reports/ deterministically.
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

import yaml

from .config import Config
from .models import SiteMetadata

SUBFOLDERS = ("raw", "processed", "figures", "reports")


class Project:
    """A borehole project folder with the standard layout."""

    def __init__(self, root: str | Path, site: SiteMetadata | None = None):
        self.root = Path(root)
        self.site = site or SiteMetadata()
        self.config = Config.load(self.root / "config.yaml")

    # -- folders ------------------------------------------------------------

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def processed(self) -> Path:
        return self.root / "processed"

    @property
    def figures(self) -> Path:
        return self.root / "figures"

    @property
    def reports(self) -> Path:
        return self.root / "reports"

    def ensure_folders(self) -> "Project":
        for sub in SUBFOLDERS:
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        return self

    # -- persistence ----------------------------------------------------------

    @classmethod
    def create(cls, root: str | Path, site: SiteMetadata | None = None) -> "Project":
        project = cls(root, site).ensure_folders()
        project.save_metadata()
        return project

    @classmethod
    def open(cls, root: str | Path) -> "Project":
        root = Path(root)
        meta_path = root / "project.yaml"
        site = SiteMetadata()
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}
            site_data = data.get("site", {}) or {}
            site = SiteMetadata(
                **{k: v for k, v in site_data.items() if k in SiteMetadata().__dict__}
            )
        return cls(root, site).ensure_folders()

    def clear_outputs(self) -> list[Path]:
        """Remove everything a previous run generated; return what went.

        ``raw/`` and the metadata are kept: they are inputs. Everything
        under ``processed/``, ``figures/`` and ``reports/`` is a product of
        the code that last ran, and a product left behind by an earlier
        version of the code is not a stale file but a wrong one - a map of
        what the project used to say, sitting beside the current map with
        nothing in its name to tell them apart. A run that starts by
        clearing the folders leaves exactly what it produced.
        """
        removed: list[Path] = []
        for sub in ("processed", "figures", "reports"):
            folder = self.root / sub
            if not folder.is_dir():
                continue
            for path in sorted(folder.iterdir()):
                if path.is_file():
                    path.unlink()
                    removed.append(path)
        return removed

    def save_metadata(self) -> None:
        data = {"site": {k: v for k, v in asdict(self.site).items() if v not in (None, "")}}
        with open(self.root / "project.yaml", "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False)

    def figure_path(self, name: str) -> Path:
        self.figures.mkdir(parents=True, exist_ok=True)
        return self.figures / name

    def report_path(self, name: str) -> Path:
        self.reports.mkdir(parents=True, exist_ok=True)
        return self.reports / name

    def processed_path(self, name: str) -> Path:
        self.processed.mkdir(parents=True, exist_ok=True)
        return self.processed / name
