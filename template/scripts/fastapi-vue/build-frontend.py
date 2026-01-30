"""Hatch build hook for building Vue frontend during package build."""

import sys
from pathlib import Path

from hatchling.builders.hooks.plugin.interface import BuildHookInterface  # type: ignore

sys.path.insert(0, str(Path(__file__).parent))
from buildutil import build


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        super().initialize(version, build_data)
        build("frontend")
