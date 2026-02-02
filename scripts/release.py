#!/usr/bin/env -S uv run
"""Build and release both fastapi-vue and fastapi-vue-setup packages."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
FASTAPI_VUE = ROOT / "fastapi-vue"


def main():
    # Clear the dist directory
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()

    # Build fastapi-vue (subdirectory) to root dist
    subprocess.run(
        ["uv", "build", "--out-dir", str(DIST)],
        cwd=FASTAPI_VUE,
        check=True,
    )

    # Build fastapi-vue-setup (root)
    subprocess.run(
        ["uv", "build", "--out-dir", str(DIST)],
        cwd=ROOT,
        check=True,
    )


if __name__ == "__main__":
    main()
