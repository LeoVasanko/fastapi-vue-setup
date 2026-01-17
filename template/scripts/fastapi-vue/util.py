"""Shared utilities for build and dev scripts."""

import os
import shutil
from pathlib import Path
from sys import stderr


def find_js_runtime() -> tuple[str, str] | None:
    """Find a JavaScript runtime from JS_RUNTIME env or auto-detect.

    Returns (tool_path, tool_name) where tool_name is "deno", "npm", or "bun".
    Returns None if no runtime is found.
    """
    options = ["deno", "npm", "bun"]

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
                    stderr.write(f"┃ ⚠️  JS_RUNTIME={js_runtime_env} not found\n")
                    return None
                return tool, option
        stderr.write(f"┃ ⚠️  JS_RUNTIME={js_runtime_env} not recognized\n")
        return None

    # Auto-detect
    for option in options:
        if tool := shutil.which(option):
            return tool, option
    return None


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
    build = {
        "deno": ("task", "build"),
        "npm": ("run", "build"),
        "bun": ("--bun", "run", "build"),
    }

    result = find_js_runtime()
    if result is None:
        raise RuntimeError(
            "Deno, npm or Bun is required for building but none was found"
        )

    tool, name = result
    return [tool, *install[name]], [tool, *build[name]]


def find_dev_tool():
    """Find JavaScript runtime and construct dev command.

    Returns (dev_cmd, tool_name) or (None, None) if not found.
    """
    dev_args = {
        "deno": ("run", "dev", "--"),
        "npm": ("--silent", "run", "dev", "--"),
        "bun": ("run", "dev", "--"),
    }

    result = find_js_runtime()
    if result is None:
        return None, None

    tool, name = result
    return [tool, *dev_args[name]], name
