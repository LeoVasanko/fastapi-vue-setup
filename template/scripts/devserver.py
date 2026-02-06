#!/usr/bin/env -S uv run
# auto-upgrade@fastapi-vue-setup - remove this if you modify this file
"""Run Vite development server for frontend and FastAPI backend with auto-reload."""

import argparse
import asyncio
import os
import sys
from contextlib import suppress
from pathlib import Path

# Import util.py from scripts/fastapi-vue (not a package, so we adjust sys.path)
sys.path.insert(0, str(Path(__file__).with_name("fastapi-vue")))
from devutil import (  # type: ignore
    ProcessGroup,
    check_ports_free,
    logger,
    ready,
    setup_vite,
)

DEFAULT_VITE_PORT = TEMPLATE_VITE_PORT
DEFAULT_DEV_PORT = TEMPLATE_DEV_PORT


async def run_devserver(
    frontend: str, backend: str, extra_args: list[str] | None = None
) -> None:
    reporoot = Path(__file__).parent.parent
    front = reporoot / "frontend"
    if not (front / "package.json").exists():
        logger.warning("Frontend source not found at %s", front)
        raise SystemExit(1)

    viteurl, npm_install, vite = setup_vite(frontend, DEFAULT_VITE_PORT)
    backurl, MODULE_NAME = setup_cli("PROJECT_CLI", backend, DEFAULT_DEV_PORT)

    # Tell the everyone where the frontend and backend are (vite proxy, etc)
    os.environ["ENVPREFIX_FRONTEND_URL"] = viteurl
    os.environ["ENVPREFIX_BACKEND_URL"] = backurl

    async with ProcessGroup() as pg:
        npm_i = await pg.spawn(*npm_install, cwd=front)
        await check_ports_free(viteurl, backurl)
        await pg.spawn(*MODULE_NAME, *(extra_args or []))
        await pg.wait(npm_i, ready(backurl, path="/api/health?from=devserver.py"))
        await pg.spawn(*vite, cwd=front)


def main():
    parser = argparse.ArgumentParser(
        description="Run Vite and FastAPI development servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=HELP_EPILOG,
    )
    parser.add_argument(
        "frontend",
        nargs="?",
        metavar="host:port",
        help=f"Vite frontend endpoint (default: localhost:{DEFAULT_VITE_PORT})",
    )
    parser.add_argument(
        "--backend",
        metavar="host:port",
        help=f"FastAPI backend endpoint (default: localhost:{DEFAULT_DEV_PORT})",
    )
    args, extra_args = parser.parse_known_args()
    with suppress(KeyboardInterrupt):
        asyncio.run(run_devserver(args.frontend, args.backend, extra_args))


HELP_EPILOG = """
  scripts/devserver.py [args to PROJECT_CLI]

  JS_RUNTIME environment variable can be used to select the JS runtime:
  npm, deno, bun, or full path to the runtime executable (node maps to npm).
"""


if __name__ == "__main__":
    main()
