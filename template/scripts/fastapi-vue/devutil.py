"""Utilities meant for devserver script, used only in source repository with dev deps."""

import asyncio
import subprocess
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

import httpx
from buildutil import find_dev_tool, find_install_tool, logger
from fastapi_vue.hostutil import parse_endpoint

DEFAULT_VITE_PORT = 5173
DEFAULT_BACKEND_PORT = 5180


class ProcessGroup:
    """Manage async subprocesses with automatic cleanup, like TaskGroup for processes."""

    def __init__(self):
        self._procs: list[asyncio.subprocess.Process] = []
        self._cmds: dict[int, str] = {}  # pid -> command name

    async def spawn(
        self, *cmd: str, cwd: str | None = None
    ) -> asyncio.subprocess.Process:
        """Spawn a subprocess and track it."""
        cmd_name = Path(cmd[0]).name
        logger.info(">>> %s", " ".join([cmd_name, *cmd[1:]]))
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd)
        self._procs.append(proc)
        self._cmds[proc.pid] = cmd_name
        return proc

    async def wait(
        self, *waitables: "asyncio.subprocess.Process | Coroutine[Any, Any, Any]"
    ) -> None:
        """Wait for processes/coroutines to complete, raise SystemExit on failure."""

        async def wait_proc(proc: asyncio.subprocess.Process) -> None:
            returncode = await proc.wait()
            if returncode != 0:
                cmd_name = self._cmds.get(proc.pid, "unknown")
                raise subprocess.CalledProcessError(returncode, cmd_name)

        tasks = [
            wait_proc(w) if isinstance(w, asyncio.subprocess.Process) else w
            for w in waitables
        ]
        try:
            await asyncio.gather(*tasks)
        except subprocess.CalledProcessError as e:
            logger.warning("%s failed with exit status %d", e.cmd, e.returncode)
            raise SystemExit(1) from None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, *_):
        """Wait for one process to exit, terminate others, then wait for all."""
        cleanup_task = asyncio.create_task(
            self._cleanup(immediate=exc_type is not None)
        )
        try:
            await asyncio.shield(cleanup_task)
        except asyncio.CancelledError:
            # Shield was cancelled but cleanup_task continues - wait for it
            await cleanup_task

    async def _cleanup(self, immediate: bool = False):
        running = [p for p in self._procs if p.returncode is None]
        if not running:
            return

        if not immediate:
            # Wait for any one process to exit
            await asyncio.wait(
                [asyncio.create_task(p.wait()) for p in running],
                return_when=asyncio.FIRST_COMPLETED,
            )

        # Terminate remaining processes
        for p in self._procs:
            if p.returncode is None:
                try:
                    p.terminate()
                except ProcessLookupError:
                    pass

        # Wait for all to finish (with overall timeout)
        still_running = [p for p in self._procs if p.returncode is None]
        if still_running:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*[p.wait() for p in still_running]),
                    timeout=10,
                )
            except TimeoutError:
                for p in self._procs:
                    if p.returncode is None:
                        try:
                            p.kill()
                        except ProcessLookupError:
                            pass
                        await p.wait()


async def check_ports_free(*urls: str) -> None:
    """Verify URLs are not responding (ports are free). Raise SystemExit if any respond."""
    async with httpx.AsyncClient() as client:
        for url in urls:
            try:
                res = await client.get(url, timeout=0.1)
                logger.warning(
                    "Conflicting %s already running at %s",
                    res.headers.get("server", "server"),
                    url,
                )
                raise SystemExit(1)
            except httpx.RequestError:
                pass  # Expected - port is free


async def ready(url: str, path: str = "") -> None:
    """Wait for the server to be ready by polling an endpoint.

    Raises SystemExit(1) if server doesn't start in time.
    """
    max_attempts = 50
    full_url = f"{url}{path}"

    async with httpx.AsyncClient() as client:
        for attempt in range(max_attempts):
            try:
                await client.get(full_url, timeout=1.0)
                logger.info("✓ Backend ready!")
                return
            except httpx.RequestError:
                if attempt == max_attempts - 1:
                    logger.warning("Backend didn't start in time")
                    raise SystemExit(1)
                await asyncio.sleep(0.1)


def setup_vite(endpoint: str) -> tuple[str, list[str], list[str]]:
    """Parse frontend endpoint and build commands.

    Returns (url, install_cmd, dev_cmd).
    Raises SystemExit(1) on invalid config.
    """
    endpoints = parse_endpoint(endpoint, DEFAULT_VITE_PORT)

    if "uds" in endpoints[0]:
        logger.warning("Unix sockets not supported with vite devserver")
        raise SystemExit(1)

    port = endpoints[0]["port"]
    host = endpoints[0]["host"]

    install_cmd = find_install_tool()
    dev_cmd = find_dev_tool()
    if host != "localhost":
        dev_cmd.append("--host" if len(endpoints) > 1 else f"--host={host}")
    if port != 5173:
        dev_cmd.append(f"--port={port}")

    return f"http://{host}:{port}", install_cmd, dev_cmd


def setup_fastapi(
    endpoint: str, module: str, default_port: int = DEFAULT_BACKEND_PORT
) -> tuple[str, list[str]]:
    """Parse backend endpoint and build fastapi dev command.

    Returns (url, cmd).
    Raises SystemExit(1) on invalid config.
    """
    endpoints = parse_endpoint(endpoint, default_port)

    if "uds" in endpoints[0]:
        logger.warning("Unix sockets not supported with vite devserver")
        raise SystemExit(1)

    host = endpoints[0]["host"]
    port = endpoints[0]["port"]

    cmd = [
        "fastapi",
        "dev",
        "--entrypoint",
        module,
        "--host",
        host,
        "--port",
        str(port),
    ]
    return f"http://{host}:{port}", cmd
