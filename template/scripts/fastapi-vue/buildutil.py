"""Utilities used at build time and in devserver script. No dependencies."""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path


class _PrefixFormatter(logging.Formatter):
    """Formatter that adds prefix based on log level."""

    def format(self, record: logging.LogRecord) -> str:
        if record.levelno >= logging.WARNING:
            return f"⚠️  {record.getMessage()}"
        return record.getMessage()


_handler = logging.StreamHandler()
_handler.setFormatter(_PrefixFormatter())
logger = logging.getLogger("fastapi-vue")
logger.addHandler(_handler)
logger.setLevel(logging.INFO)


def _check_node_version(node_path: str) -> None:
    """Check if Node.js version is >= 20.

    Raises RuntimeError if version is too old or cannot be determined.
    """
    try:
        result = subprocess.run(
            [node_path, "--version"], capture_output=True, text=True, check=True
        )
        version_str = result.stdout.strip()
        # Parse version like "v20.10.0" or "v18.17.1"
        match = re.match(r"v(\d+)", version_str)
        if match:
            major_version = int(match.group(1))
            if major_version >= 20:
                return
            raise RuntimeError(
                f"Node.js {version_str} found, but v20+ required (install with nvm)"
            )
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    raise RuntimeError("Could not determine Node.js version")


def find_js_runtime() -> tuple[str, str]:
    """Find a JavaScript runtime from JS_RUNTIME env or auto-detect.

    Returns (tool_path, tool_name) where tool_name is "deno", "npm", or "bun".
    Raises JSRuntimeError if no suitable runtime is found.
    """
    options = ["npm", "deno", "bun"]
    node_version_error: RuntimeError | None = None

    # Check for JS_RUNTIME environment variable
    if js_runtime_env := os.environ.get("JS_RUNTIME"):
        js_runtime = js_runtime_env
        js_path = Path(js_runtime)
        runtime_name = js_path.name
        # Map node to npm
        if runtime_name == "node":
            runtime_name = "npm"
            js_runtime = str(js_path.parent / "npm") if js_path.parent.name else "npm"
        for option in options:
            if option == runtime_name or runtime_name.startswith(option):
                tool = shutil.which(js_runtime)
                if tool is None:
                    raise RuntimeError(
                        f"JS_RUNTIME={js_runtime_env}: {option} not found"
                    )
                # Check Node.js version if using npm
                if option == "npm":
                    node_path = shutil.which("node", path=str(Path(tool).parent))
                    if node_path is None:
                        raise RuntimeError(
                            f"JS_RUNTIME={js_runtime_env}: node not found"
                        )
                    _check_node_version(node_path)  # Raises on failure
                return tool, option
        raise RuntimeError(f"JS_RUNTIME={js_runtime_env} not recognized")

    # Auto-detect
    for option in options:
        if tool := shutil.which(option):
            # Check Node.js version if using npm
            if option == "npm":
                node_path = shutil.which("node", path=str(Path(tool).parent))
                if node_path is None:
                    continue
                try:
                    _check_node_version(node_path)
                except RuntimeError as e:
                    node_version_error = e
                    continue  # Try next runtime
            return tool, option

    # No runtime found - provide helpful error
    if node_version_error:
        raise node_version_error
    raise RuntimeError("Node.js (v20+), Deno or Bun is required but none was found")


def find_build_tool():
    """Find JavaScript runtime and construct install/build commands.

    Returns (install_cmd, build_cmd) tuples of command lists.
    Raises RuntimeError if no runtime is found.
    """
    install = {
        "deno": ("install", "--allow-scripts=npm:vue-demi"),
        "npm": ("install",),
        "bun": ("--bun", "install"),
    }
    # Run vite directly for deno to avoid npm-run-all2/run-p issues
    build = {
        "deno": ("run", "-A", "npm:vite", "build"),
        "npm": ("run", "build"),
        "bun": ("--bun", "run", "build"),
    }

    tool, name = find_js_runtime()
    return [tool, *install[name]], [tool, *build[name]]


def find_dev_tool() -> list[str]:
    """Find JavaScript runtime and construct dev command.

    Returns dev_cmd (without vite-specific args).
    Raises RuntimeError if no runtime is found.
    """
    dev_args = {
        "deno": ("run", "-A", "npm:vite"),
        "npm": ("--silent", "run", "dev", "--"),
        "bun": ("run", "dev", "--"),
    }

    tool, name = find_js_runtime()

    if name == "bun":
        logger.warning(
            "Bun has a bug in WS proxying (https://github.com/oven-sh/bun/issues/9882). Consider using npm instead."
        )

    return [tool, *dev_args[name]]


def find_install_tool() -> list[str]:
    """Find JavaScript runtime and construct install command.

    Returns install_cmd.
    Raises RuntimeError if no runtime is found.
    """
    install_args = {
        "deno": ("install", "--quiet", "--allow-scripts=npm:vue-demi"),
        "npm": ("install", "--silent"),
        "bun": ("install", "--silent"),
    }

    tool, name = find_js_runtime()
    return [tool, *install_args[name]]


def build(folder: str = "frontend") -> None:
    """Build the frontend in the specified folder.

    Raises SystemExit(1) on failure.
    """
    logger.info(">>> Building %s", folder)

    try:
        install_cmd, build_cmd = find_build_tool()
    except RuntimeError as e:
        logger.warning(e)
        raise SystemExit(1)

    def run(cmd):
        display_cmd = [Path(cmd[0]).stem, *cmd[1:]]
        logger.info("### %s", " ".join(display_cmd))
        subprocess.run(cmd, check=True, cwd=folder)

    try:
        run(install_cmd)
        logger.info("")
        run(build_cmd)
    except subprocess.CalledProcessError:
        raise SystemExit(1)
