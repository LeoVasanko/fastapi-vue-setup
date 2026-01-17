#!/usr/bin/env -S uv run
"""Run Vite development server for frontend and FastAPI backend with auto-reload.

Usage:
    uv run scripts/devserver.py [host:port] [--backend host:port]

The optional host:port argument sets where the Vite frontend listens.
Supported forms: host[:port], :port (all interfaces), or just port.
The --backend option sets where the FastAPI backend listens (default: localhost:5180).

Environment:
    JS_RUNTIME          Path or name of JS runtime to use (deno, npm/node or bun).
    FASTAPI_VUE_FRONTEND_URL    Set by this script for the backend to know where Vite is.
"""

import argparse
import asyncio
import contextlib
import ipaddress
import os
from pathlib import Path
from sys import stderr
from urllib.parse import urlparse

import httpx

exec((Path(__file__).parent / "fastapi-vue/util.py").read_text("UTF-8"))  # noqa: S102

DEFAULT_HOST = "localhost"
DEFAULT_VITE_PORT = 5173
DEFAULT_BACKEND_PORT = 5180
FRONTEND_PATH = Path(__file__).parent.parent / "frontend"

EPILOG = """
  scripts/devserver.py                       # Default ports on localhost
  scripts/devserver.py 3000                  # Vite on localhost:3000
  scripts/devserver.py :3000 --backend 8000  # *:3000, localhost:8000
"""

BUN_BUG = """\
┃ ⚠️  Bun cannot correctly proxy API requests to the backend.
┃ Bug report: https://github.com/oven-sh/bun/issues/9882
┃
┃ Consider using deno or npm instead for development.
"""


def parse_endpoint(
    value: str | None, default_port: int = DEFAULT_VITE_PORT
) -> tuple[str | None, int, bool]:
    """Parse an endpoint for Vite or backend.

    Returns (host, port, all_ifaces).
    """
    if not value:
        return DEFAULT_HOST, default_port, False

    # Port only (numeric) -> localhost:port
    if value.isdigit():
        return DEFAULT_HOST, int(value), False

    # Leading colon :port -> bind all interfaces
    if value.startswith(":") and value != ":":
        port_part = value[1:]
        if not port_part.isdigit():
            raise SystemExit(f"Invalid port in '{value}'")
        return None, int(port_part), True

    # Unbracketed IPv6 (cannot safely contain a port)
    if value.count(":") > 1 and not value.startswith("["):
        try:
            ipaddress.IPv6Address(value)
        except ValueError as e:
            raise SystemExit(f"Invalid IPv6 address '{value}': {e}") from e
        return value, default_port, False

    # Use urllib.parse for everything else
    parsed = urlparse(f"//{value}")
    host = parsed.hostname or DEFAULT_HOST
    port = parsed.port or default_port

    return host, port, False


def resolve_frontend_tools(
    vite_host: str | None, vite_port: int, all_ifaces: bool
) -> tuple[list[str], list[str], str]:
    """Resolve frontend install and dev commands.

    Returns (install_cmd, dev_cmd, tool_name).
    Raises SystemExit if tools are not available.
    """
    if not (FRONTEND_PATH / "package.json").exists():
        stderr.write(f"┃ ⚠️  Frontend source not found at {FRONTEND_PATH}\n")
        raise SystemExit(1)

    result = find_js_runtime()  # noqa # type: ignore
    if result is None:
        if not os.environ.get("JS_RUNTIME"):
            stderr.write("┃ ⚠️  deno, npm or bun needed to run the frontend server.\n")
        raise SystemExit(1)

    tool, name = result

    install_args = {
        "deno": ("install", "--quiet", "--allow-scripts=npm:vue-demi"),
        "npm": ("install", "--silent"),
        "bun": ("install", "--silent"),
    }
    dev_args = {
        "deno": ("run", "dev", "--"),
        "npm": ("--silent", "run", "dev", "--"),
        "bun": ("run", "dev", "--"),
    }

    install_cmd = [tool, *install_args[name]]
    dev_cmd = [tool, *dev_args[name], "--port", str(vite_port)]

    if all_ifaces:
        dev_cmd.append("--host")
    elif vite_host:
        dev_cmd.extend(["--host", vite_host])

    if name == "bun":
        stderr.write(BUN_BUG)

    return install_cmd, dev_cmd, name


async def wait_for_backend(backend_host: str, backend_port: int):
    """Wait for the backend to be ready by polling the health endpoint."""
    max_attempts = 50
    async with httpx.AsyncClient() as client:
        for attempt in range(max_attempts):
            try:
                await client.get(f"http://{backend_host}:{backend_port}", timeout=1.0)
                stderr.write("✓ Backend ready!\n")
                return True
            except httpx.RequestError:
                if attempt == max_attempts - 1:
                    stderr.write("┃ ⚠️  Backend didn't start in time\n")
                    return False
                await asyncio.sleep(0.1)
    return False


async def _terminate_process(proc: asyncio.subprocess.Process, name: str) -> None:
    """Gracefully terminate a subprocess."""
    if proc.returncode is not None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=2)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            return
        await proc.wait()


async def run_devserver(
    vite_host: str | None,
    vite_port: int,
    all_ifaces: bool,
    backend_host: str,
    backend_port: int,
) -> None:
    """Run the development server with install, backend, and frontend."""
    install_cmd, dev_cmd, tool_name = resolve_frontend_tools(
        vite_host, vite_port, all_ifaces
    )

    # Tell the backend where the Vite dev server is
    os.environ["FASTAPI_VUE_FRONTEND_URL"] = (
        f"http://{vite_host or 'localhost'}:{vite_port}"
    )
    # Tell Vite where the backend is (for proxying /api requests)
    os.environ["FASTAPI_VUE_BACKEND_URL"] = f"http://{backend_host}:{backend_port}"
    cwd = str(Path(__file__).parent.parent)
    frontend_cwd = str(FRONTEND_PATH)

    backend_proc: asyncio.subprocess.Process | None = None
    install_proc: asyncio.subprocess.Process | None = None
    frontend_proc: asyncio.subprocess.Process | None = None

    try:
        # Start install (concurrent with backend)
        stderr.write(f">>> {tool_name} {' '.join(install_cmd[1:])}\n")
        install_proc = await asyncio.create_subprocess_exec(
            *install_cmd, cwd=frontend_cwd
        )

        await asyncio.sleep(0.1)

        # Start backend (concurrent with install)
        backend_cmd = [
            "uvicorn",
            "MODULE_NAME.app:app",
            "--host",
            backend_host,
            "--port",
            str(backend_port),
            "--reload",
        ]
        stderr.write(f">>> {' '.join(backend_cmd)}\n")
        backend_proc = await asyncio.create_subprocess_exec(*backend_cmd, cwd=cwd)

        # Wait for install to complete and backend to be ready
        install_task = asyncio.create_task(install_proc.wait(), name="install")
        backend_ready_task = asyncio.create_task(
            wait_for_backend(backend_host, backend_port), name="backend_ready"
        )

        done, pending = await asyncio.wait(
            {install_task, backend_ready_task},
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            if task.get_name() == "install":
                if task.result() != 0:
                    stderr.write("┃ ⚠️  Install failed\n")
                    raise SystemExit(1)
            elif task.get_name() == "backend_ready" and not task.result():
                raise SystemExit(1)

        if pending:
            done2, _ = await asyncio.wait(pending)
            for task in done2:
                if task.get_name() == "install":
                    if task.result() != 0:
                        stderr.write("┃ ⚠️  Install failed\n")
                        raise SystemExit(1)
                elif task.get_name() == "backend_ready" and not task.result():
                    raise SystemExit(1)

        install_proc = None

        # Start Vite dev server
        stderr.write(f">>> {tool_name} {' '.join(dev_cmd[1:])}\n")
        frontend_proc = await asyncio.create_subprocess_exec(*dev_cmd, cwd=frontend_cwd)

        # Wait for either process to exit
        done, pending = await asyncio.wait(
            {
                asyncio.create_task(backend_proc.wait(), name="backend"),
                asyncio.create_task(frontend_proc.wait(), name="frontend"),
            },
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in done:
            t.result()
        for t in pending:
            t.cancel()

    except asyncio.CancelledError:
        stderr.write("\n✓ Shutting down...\n")
    finally:
        if frontend_proc is not None:
            await _terminate_process(frontend_proc, "frontend")
        if install_proc is not None:
            await _terminate_process(install_proc, "install")
        if backend_proc is not None:
            await _terminate_process(backend_proc, "backend")


def main():
    parser = argparse.ArgumentParser(
        description="Run Vite and FastAPI development servers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=EPILOG,
    )
    parser.add_argument(
        "frontend",
        nargs="?",
        metavar="host:port",
        help="Vite frontend endpoint (default: localhost:5173)",
    )
    parser.add_argument(
        "--backend",
        metavar="host:port",
        help="FastAPI backend endpoint (default: localhost:5180)",
    )
    args = parser.parse_args()

    vite_host, vite_port, all_ifaces = parse_endpoint(args.frontend, DEFAULT_VITE_PORT)
    backend_host, backend_port, _ = parse_endpoint(args.backend, DEFAULT_BACKEND_PORT)
    # Backend host defaults to localhost (never None)
    backend_host = backend_host or DEFAULT_HOST

    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(
            run_devserver(vite_host, vite_port, all_ifaces, backend_host, backend_port)
        )


if __name__ == "__main__":
    main()
