# ruff: noqa: INP001
"""Utilities meant for devserver script, used only in source repository with dev deps."""

from __future__ import annotations

import asyncio
import sys
from asyncio.subprocess import Process
from contextlib import suppress
from pathlib import Path
from subprocess import CalledProcessError
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from buildutil import find_dev_tool, find_install_tool, logger
from fastapi_vue.hostutil import parse_endpoint

if TYPE_CHECKING:
    from collections.abc import Awaitable


class ProcessGroup(asyncio.TaskGroup):
    """TaskGroup with structured ownership of async subprocesses."""

    def __init__(self, *, terminate_timeout: float = 10) -> None:
        """Set the grace period before terminate() escalates to kill()."""
        super().__init__()
        self._terminate_timeout = terminate_timeout
        self._cmds: dict[Process, tuple[str, ...]] = {}

    async def spawn(self, *cmd: str, cwd: str | None = None, vital: bool = False) -> Process:
        """Spawn and own a subprocess. If a vital process exits, the group cancels."""

        async def run() -> None:
            name = Path(cmd[0]).stem
            logger.info(">>> %s", " ".join([name, *cmd[1:]]))
            try:
                proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd)
                self._cmds[proc] = cmd
                started.set_result(proc)
            except Exception as e:  # noqa: BLE001
                started.set_exception(e)
                return

            try:
                returncode = await proc.wait()
            finally:
                with suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), self._terminate_timeout)
                except TimeoutError:
                    with suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()

            if vital:
                logger.warning("Vital process %s exited", name)
                raise CalledProcessError(returncode, cmd)

        started = asyncio.get_running_loop().create_future()
        self.create_task(run())
        return await asyncio.shield(started)

    async def wait(self, *waitables: Process | Awaitable) -> tuple[Any, ...]:
        """Wait concurrently and return results in argument order."""

        async def task(w: Process | Awaitable) -> Any:  # noqa: ANN401
            if not isinstance(w, Process):
                return await w
            if retcode := await w.wait():
                cmd = self._cmds[w]
                logger.warning("Process %s exited with status %d", Path(cmd[0]).stem, retcode)
                raise CalledProcessError(retcode, cmd)
            return retcode

        async with asyncio.TaskGroup() as group:
            tasks = [group.create_task(task(w)) for w in waitables]

        return tuple(task.result() for task in tasks)


async def http_get_server(url: str, timeout: float) -> str | None:  # noqa: ASYNC109
    """GET url with plain asyncio streams, return the response Server header.

    Returns an empty string when the server responds without a Server header,
    and None when the server is unreachable or doesn't answer in time.
    """
    parts = urlsplit(url)
    host = parts.hostname or "localhost"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    path = parts.path or "/"
    if parts.query:
        path += f"?{parts.query}"
    try:
        async with asyncio.timeout(timeout):
            reader, writer = await asyncio.open_connection(host, port)
            try:
                writer.write(f"GET {path} HTTP/1.0\r\nHost: {host}\r\n\r\n".encode())
                await writer.drain()
                data = await reader.readuntil(b"\r\n\r\n")
            finally:
                writer.close()
    except (OSError, EOFError, ValueError, TimeoutError):
        return None
    for line in data.decode(errors="replace").split("\r\n"):
        if line.lower().startswith("server:"):
            return line[7:].strip()
    return ""


async def check_ports_free(*urls: str) -> None:
    """Verify URLs are not responding (ports are free).

    Meant to run as a task inside a TaskGroup. Logs the conflict and raises
    RuntimeError (handled like a failed process) if any URL responds.
    """
    servers = await asyncio.gather(*(http_get_server(url, timeout=0.1) for url in urls))
    for url, server in zip(urls, servers, strict=True):
        if server is not None:
            logger.error("Conflicting %s already running at %s", server or "server", url)
            raise RuntimeError(url)


async def ready(url: str, path: str = "", max_attempts: int = 50) -> None:
    """Wait for the server to be ready by polling an endpoint.

    Use empty path to disable the check and make this return immediately.
    Logs, then raises RuntimeError if the server doesn't start in time.
    """
    if not path:
        return

    for attempt in range(max_attempts):
        if await http_get_server(f"{url}{path}", timeout=1.0) is not None:
            logger.info("🟢 Backend ready!")
            return
        if attempt == max_attempts - 1:
            logger.error("Backend at %s didn't start in time", url)
            raise RuntimeError(url)
        await asyncio.sleep(0.1)


def setup_vite(
    endpoint: str,
    default_port: int = 5173,
) -> tuple[str, list[str], list[str]]:
    """Parse frontend endpoint and build commands.

    Returns (url, install_cmd, dev_cmd).
    Raises SystemExit(1) on invalid config.
    """
    endpoints = parse_endpoint(endpoint, default_port)

    if "uds" in endpoints[0]:
        logger.warning("Unix sockets not supported with vite devserver")
        raise SystemExit(1)

    port = endpoints[0]["port"]
    host = endpoints[0]["host"]

    install_cmd = find_install_tool()
    dev_cmd = find_dev_tool()
    if host != "localhost":
        dev_cmd.append("--host" if len(endpoints) > 1 else f"--host={host}")
    dev_cmd.append(f"--port={port}")

    return f"http://{host}:{port}", install_cmd, dev_cmd


def setup_fastapi(
    endpoint: str,
    module: str,
    default_port: int = 8000,
) -> tuple[str, list[str]]:
    """Parse backend endpoint and build uvicorn command.

    Returns (url, uvicorn_cmd).
    Raises SystemExit(1) on invalid config.
    """
    endpoints = parse_endpoint(endpoint, default_port)

    if "uds" in endpoints[0]:
        logger.warning("Unix sockets not supported with vite devserver")
        raise SystemExit(1)

    host = endpoints[0]["host"]
    port = endpoints[0]["port"]
    reload_dir = module.split(".", maxsplit=1)[0]  # Don't reload on frontend changes

    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        module,
        f"--host={host}",
        f"--port={port}",
        "--reload",
        f"--reload-dir={reload_dir}",
        "--forwarded-allow-ips=*",
    ]
    return f"http://{host}:{port}", cmd


def setup_cli(
    cli: str,
    endpoint: str,
    default_port: int = 8000,
) -> tuple[str, list[str]]:
    """Parse backend endpoint and build CLI command.

    Returns (url, cli_cmd).
    Raises SystemExit(1) on invalid config.
    """
    endpoints = parse_endpoint(endpoint, default_port)

    if "uds" in endpoints[0]:
        logger.warning("Unix sockets not supported with vite devserver")
        raise SystemExit(1)

    host = endpoints[0]["host"]
    port = endpoints[0]["port"]

    # Run the package as a module with the current interpreter, instead of
    # relying on a PATH-installed CLI entry point.
    cmd = [sys.executable, "-m", cli, f"--listen={host}:{port}"]
    return f"http://{host}:{port}", cmd
