# ruff: noqa: INP001
"""Utilities used at build time and in devserver script. No dependencies."""

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

MIN_NODE_VERSION = 20


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
        result = subprocess.run(  # noqa: S603
            [node_path, "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        version_str = result.stdout.strip()
        # Parse version like "v20.10.0" or "v18.17.1"
        match = re.match(r"v(\d+)", version_str)
        if match:
            major_version = int(match.group(1))
            if major_version >= MIN_NODE_VERSION:
                return
            msg = f"Node.js {version_str} found, but v{MIN_NODE_VERSION}+ required"
            raise RuntimeError(msg)
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError):
        pass
    msg = "Could not determine Node.js version"
    raise RuntimeError(msg)


def _validate_npm_runtime(tool: str) -> bool:
    """Validate npm runtime by checking Node.js version. Returns True if valid."""
    node_path = shutil.which("node", path=str(Path(tool).parent))
    if node_path is None:
        return False
    try:
        _check_node_version(node_path)
    except RuntimeError:
        return False
    return True


def _find_runtime_from_env(options: list[str]) -> tuple[str, str] | None:
    """Find runtime specified by JS_RUNTIME environment variable."""
    js_runtime_env = os.environ.get("JS_RUNTIME")
    if not js_runtime_env:
        return None

    js_runtime = js_runtime_env
    js_path = Path(js_runtime)
    runtime_name = js_path.name

    # Map node to npm
    if runtime_name == "node":
        runtime_name = "npm"
        js_runtime = str(js_path.parent / "npm") if js_path.parent.name else "npm"

    for option in options:
        if option != runtime_name and not runtime_name.startswith(option):
            continue

        tool = shutil.which(js_runtime)
        if tool is None:
            msg = f"JS_RUNTIME={js_runtime_env}: {option} not found"
            raise RuntimeError(msg)

        if option == "npm":
            node_path = shutil.which("node", path=str(Path(tool).parent))
            if node_path is None:
                msg = f"JS_RUNTIME={js_runtime_env}: node not found"
                raise RuntimeError(msg)
            _check_node_version(node_path)

        return tool, option

    msg = f"JS_RUNTIME={js_runtime_env} not recognized"
    raise RuntimeError(msg)


def _auto_detect_runtime(options: list[str]) -> tuple[str, str]:
    """Auto-detect JavaScript runtime from available options."""
    node_version_error: RuntimeError | None = None

    for option in options:
        tool = shutil.which(option)
        if not tool:
            continue

        if option == "npm" and not _validate_npm_runtime(tool):
            try:
                node_path = shutil.which("node", path=str(Path(tool).parent))
                if node_path:
                    _check_node_version(node_path)
            except RuntimeError as e:
                node_version_error = e
            continue

        return tool, option

    if node_version_error:
        raise node_version_error
    msg = "Node.js (v20+), Deno or Bun is required but none was found"
    raise RuntimeError(msg)


def find_js_runtime() -> tuple[str, str]:
    """Find a JavaScript runtime from JS_RUNTIME env or auto-detect.

    Returns (tool_path, tool_name) where tool_name is "deno", "npm", or "bun".
    Raises RuntimeError if no suitable runtime is found.
    """
    options = ["npm", "deno", "bun"]

    # Check for JS_RUNTIME environment variable
    if result := _find_runtime_from_env(options):
        return result

    # Auto-detect
    return _auto_detect_runtime(options)


def find_build_tool() -> tuple[list[str], list[str]]:
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
            "Bun has a WS proxy bug (github.com/oven-sh/bun/issues/9882). Consider npm.",
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
        raise SystemExit(1) from None

    def run(cmd: list[str]) -> None:
        display_cmd = [Path(cmd[0]).stem, *cmd[1:]]
        logger.info("### %s", " ".join(display_cmd))
        subprocess.run(cmd, check=True, cwd=folder)  # noqa: S603

    try:
        run(install_cmd)
        logger.info("")
        run(build_cmd)
    except subprocess.CalledProcessError:
        raise SystemExit(1) from None
