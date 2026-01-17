"""Hatch build hook for building Vue frontend during package build."""

import subprocess
from pathlib import Path
from sys import stderr

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

exec(Path(__file__).with_name("util.py").read_text("UTF-8"))  # noqa: S102


def run(cmd, **kwargs):
    """Run a command and display it."""
    display_cmd = [Path(cmd[0]).name, *cmd[1:]]
    stderr.write(f"### {' '.join(display_cmd)}\n")
    subprocess.run(cmd, check=True, **kwargs)


class CustomBuildHook(BuildHookInterface):
    """Build hook that compiles Vue frontend before packaging."""

    def initialize(self, version, build_data):
        super().initialize(version, build_data)
        stderr.write(">>> Building the frontend\n")

        install_cmd, build_cmd = find_build_tool()

        try:
            run(install_cmd, cwd="frontend")
            stderr.write("\n")
            run(build_cmd, cwd="frontend")
        except Exception as e:
            stderr.write(f"Error occurred while building frontend: {e}\n")
            raise
