"""Assemble what the Pyodide spike serves, outside the shipped app.

    python spikes/pyodide-engine/build.py                     # downloads the tarball
    python spikes/pyodide-engine/build.py --tarball PATH      # one already on disk

Writes spikes/pyodide-engine/vendor/ (ignored by git), holding

  pyodide/        the Pyodide runtime and the wheels the VES computation
                  needs, taken from the release tarball: numpy, scipy and
                  the libopenblas scipy links against, and PyYAML, which
                  ``import groundwater`` reads its configuration with;
  groundwater-ves.zip
                  the package modules and data files the computation
                  actually touches, found by running it under an audit
                  hook rather than listed by hand;
  manifest.json   every file the worker fetches, with its size, which the
                  spike's service worker precaches and the driver sums.

Pyodide 0.29.3 is the runtime @stlite/browser 1.8.1 defaults to, which is
what web/build_demo.py pins for the Streamlit demo, so the spike measures the
same Python, numpy and scipy the demo already ships. The tarball is fetched
from GitHub releases because cdn.jsdelivr.net, Pyodide's usual host, is not
reachable from every machine this was run on; it is 392 MB and only about
31 MB of it is used, so nothing from it is committed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SRC = REPO / "src"

PYODIDE_VERSION = "0.29.3"
TARBALL_URL = (
    f"https://github.com/pyodide/pyodide/releases/download/{PYODIDE_VERSION}/"
    f"pyodide-{PYODIDE_VERSION}.tar.bz2"
)
# The tarball the numbers in docs/decisions/0001-engine.md were measured with.
TARBALL_SHA256 = "458e8ddbcbb6e21037d3237cd5c5146c451765bc738dfa2249ff34c5140331e4"

# What the worker asks loadPackage for. The plan says numpy and scipy only;
# PyYAML is here because groundwater/__init__.py imports project.py, which
# imports yaml, so no module of the package can be imported without it.
PACKAGES = ["numpy", "scipy", "pyyaml"]

# The runtime itself, besides the wheels: the loader, the Emscripten glue,
# the interpreter, the standard library and the lock file loadPackage reads.
CORE = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm",
        "python_stdlib.zip", "pyodide-lock.json"]

# A fixed date for every zip entry, so the archive is byte-reproducible.
ZIP_DATE = (2026, 1, 1, 0, 0, 0)

TRACER = r"""
import json, sys
seen = set()
def hook(event, args):
    if event == "open" and isinstance(args[0], str):
        seen.add(args[0])
sys.addaudithook(hook)
sys.path.insert(0, sys.argv[1])
import engine
ref = json.load(open(sys.argv[2], encoding="utf-8"))
for s in ref["ves"]:
    js = {"sounding_id": s["id"], "array_type": s["array"], "ab2": s["ab2"],
          "mn": s["mn"], "rho_app": s["rho"], "site": s["site"],
          "flags": [list(f) for f in s["flags"]]}
    engine.run(js)
mods = [m.__file__ for name, m in list(sys.modules.items())
        if name.startswith("groundwater") and getattr(m, "__file__", None)]
json.dump({"modules": mods, "opened": sorted(seen)}, sys.stdout)
"""


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch_tarball(dest: Path) -> Path:
    if dest.exists() and sha256(dest) == TARBALL_SHA256:
        return dest
    print(f"downloading {TARBALL_URL}")
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(TARBALL_URL) as resp, tmp.open("wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.replace(dest)
    return dest


def wheel_closure(lock: dict, names: list[str]) -> list[str]:
    """File names of ``names`` and everything they depend on, per the lock."""
    packages = lock["packages"]
    todo, done = list(names), []
    while todo:
        name = todo.pop()
        if name in done:
            continue
        done.append(name)
        todo.extend(packages[name]["depends"])
    return sorted(packages[n]["file_name"] for n in done)


def extract_runtime(tarball: Path, out: Path) -> list[str]:
    out.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tarball, "r:bz2") as tar:
        lock_member = tar.extractfile("pyodide/pyodide-lock.json")
        assert lock_member is not None
        lock = json.load(lock_member)
    wanted = CORE + wheel_closure(lock, PACKAGES)
    missing = [n for n in wanted if not (out / n).exists()]
    if missing:
        print(f"extracting {len(missing)} files from {tarball.name}")
        with tarfile.open(tarball, "r:bz2") as tar:
            for member in tar:
                name = member.name.removeprefix("pyodide/")
                if name in missing:
                    member.name = name
                    tar.extract(member, out, filter="data")
    return wanted


def trace_package() -> list[Path]:
    """The package files the computation reads: modules and data."""
    env = dict(os.environ, PYTHONPATH=str(SRC), OPENBLAS_NUM_THREADS="1")
    proc = subprocess.run(
        [sys.executable, "-c", TRACER, str(HERE),
         str(REPO / "tests" / "webapp" / "reference.json")],
        env=env, capture_output=True, text=True, check=True)
    found = json.loads(proc.stdout)
    root = (SRC / "groundwater").resolve()
    files = set()
    for name in found["modules"] + found["opened"]:
        path = Path(name).resolve()
        if path.is_file() and root in path.parents and path.suffix != ".pyc":
            files.add(path)
    # a package's __init__ is imported but a namespace module may not be
    # opened by name; every directory that holds a file needs its __init__
    for path in list(files):
        for parent in path.parents:
            if parent == root.parent:
                break
            init = parent / "__init__.py"
            if init.exists():
                files.add(init)
    return sorted(files)


def write_package_zip(files: list[Path], dest: Path) -> None:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for path in files:
            info = zipfile.ZipInfo(str(path.relative_to(SRC)), ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, path.read_bytes())
        engine = HERE / "engine.py"
        info = zipfile.ZipInfo("engine.py", ZIP_DATE)
        info.compress_type = zipfile.ZIP_DEFLATED
        zf.writestr(info, engine.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--tarball", type=Path,
                        help=f"pyodide-{PYODIDE_VERSION}.tar.bz2 already on disk")
    parser.add_argument("--out", type=Path, default=HERE / "vendor")
    args = parser.parse_args()

    out = args.out
    out.mkdir(parents=True, exist_ok=True)
    tarball = args.tarball or fetch_tarball(out / f"pyodide-{PYODIDE_VERSION}.tar.bz2")
    if sha256(tarball) != TARBALL_SHA256:
        raise SystemExit(f"{tarball} is not the tarball this spike was measured with")
    runtime = extract_runtime(tarball, out / "pyodide")

    files = trace_package()
    write_package_zip(files, out / "groundwater-ves.zip")
    print(f"groundwater-ves.zip: {len(files)} package files")
    for path in files:
        print("  ", path.relative_to(SRC))

    manifest = [{"url": f"pyodide/{n}", "bytes": (out / "pyodide" / n).stat().st_size}
                for n in runtime]
    manifest.append({"url": "groundwater-ves.zip",
                     "bytes": (out / "groundwater-ves.zip").stat().st_size})
    (out / "manifest.json").write_text(json.dumps(
        {"pyodide": PYODIDE_VERSION, "packages": PACKAGES, "files": manifest},
        indent=1) + "\n")
    total = sum(f["bytes"] for f in manifest)
    print(f"{len(manifest)} files, {total:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
