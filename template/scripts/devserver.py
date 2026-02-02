#!/usr/bin/env -S uv run
# auto-upgrade@fastapi-vue-setup - remove this if you modify this file
"""Run Vite development server for frontend and FastAPI backend with auto-reload."""

import argparse
import asyncio
import contextlib
import os
import sys
from pathlib import Path

from fastapi_vue import server

# Import util.py from scripts/fastapi-vue (not a package, so we adjust sys.path)
sys.path.insert(0, str(Path(__file__).with_name("fastapi-vue")))
from devutil import (  # type: ignore
    ProcessGroup,
    check_ports_free,
    logger,
    ready,
    setup_fastapi,
    setup_vite,
)

DEFAULT_VITE_PORT = TEMPLATE_VITE_PORT
DEFAULT_DEV_PORT = TEMPLATE_DEV_PORT


async def run_devserver(frontend: str, backend: str) -> None:
    reporoot = Path(__file__).parent.parent
    front = reporoot / "frontend"
    if not (front / "package.json").exists():
        logger.warning("Frontend source not found at %s", front)
        raise SystemExit(1)

    viteurl, npm_install, vite = setup_vite(frontend, DEFAULT_VITE_PORT)
    backurl, module, backend_config = setup_fastapi(
        backend, "MODULE_NAME.APP_MODULE:APP_VAR", DEFAULT_DEV_PORT
    )

    # Tell the everyone where the frontend and backend are (vite proxy, etc)
    os.environ["FASTAPI_VUE_FRONTEND_URL"] = viteurl
    os.environ["FASTAPI_VUE_BACKEND_URL"] = backurl

    async with ProcessGroup() as pg:
        npm_i = await pg.spawn(*npm_install, cwd=front)
        await check_ports_free(viteurl, backurl)

        # Run backend in a thread (server.run is blocking)
        loop = asyncio.get_event_loop()
        loop.run_in_executor(None, lambda: server.run(module, **backend_config))

        # Wait for both install and backend to be ready
        await pg.wait(npm_i, ready(backurl, path="/api/health?from=devserver.py"))

        # Start Vite dev server (ProcessGroup waits for any exit, then terminates others)
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
    args = parser.parse_args()
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(run_devserver(args.frontend, args.backend))


HELP_EPILOG = """
  scripts/devserver.py                       # Default ports on localhost
  scripts/devserver.py 3000                  # Vite on localhost:3000
  scripts/devserver.py :3000 --backend 8000  # *:3000, localhost:8000

  JS_RUNTIME environment variable can be used to select the JS runtime
"""


if __name__ == "__main__":
    main()
