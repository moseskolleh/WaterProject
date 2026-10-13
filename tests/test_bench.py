"""What the bench's scripts promise beyond their numbers.

``bench/web.mjs`` has ``bench/terrain_memory.py --write-tile`` write the
synthetic elevation tile it times the browser app's terrain card on, before
it times anything, so that option runs wherever the bench does. The memory
measure in the same script reads ``/proc`` and runs on Linux only.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_the_terrain_tile_is_written_without_the_resource_module(tmp_path):
    """Prevents ``node bench/web.mjs`` failing on Windows before it times
    the cold load, which needs no Python: Windows has no ``resource``
    module, and only the memory measure reads it. The script is run as
    web.mjs runs it, from the repository root, with ``resource`` made
    impossible to import."""
    tile = tmp_path / "tile.tif"
    code = (
        "import runpy, sys\n"
        "sys.modules['resource'] = None\n"
        f"sys.argv = ['bench/terrain_memory.py', '--write-tile', {str(tile)!r}]\n"
        "runpy.run_path('bench/terrain_memory.py', run_name='__main__')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["tool"] == "bench/run.py"
    assert tile.read_bytes()[:4] == b"II*\x00"
