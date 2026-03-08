# ruff: noqa: INP001
"""Hatch build hook for building Vue frontend during package build."""

import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

sys.path.insert(0, str(Path(__file__).parent))
from buildutil import build


class CustomBuildHook(BuildHookInterface):  # type: ignore[misc]
    """Hatch build hook that builds Vue frontend during package build."""

    def initialize(self, version: str, build_data: dict) -> None:  # type: ignore[override]
        """Build frontend before package is built."""
        super().initialize(version, build_data)
        build("frontend")
