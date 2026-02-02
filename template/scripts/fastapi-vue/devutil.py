"""Utilities meant for devserver script, used only in source repository with dev deps."""

import asyncio
import subprocess
from collections.abc import Coroutine
from contextlib import suppress
from pathlib import Path
from typing import Any

import httpx
from buildutil import find_dev_tool, find_install_tool, logger
from fastapi_vue.hostutil import parse_endpoint


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
        await self._cleanup(immediate=exc_type is not None)

    async def _cleanup(self, immediate: bool = False):
        running = [p for p in self._procs if p.returncode is None]
        if not running:
            return

        if not immediate:
            # Wait for any one process to exit
            with suppress(asyncio.CancelledError):
                await asyncio.wait(
                    [asyncio.create_task(p.wait()) for p in running],
                    return_when=asyncio.FIRST_COMPLETED,
                )

        # Terminate remaining processes
        for p in self._procs:
            if p.returncode is None:
                with suppress(ProcessLookupError):
                    p.terminate()

        # Wait for all to finish (with overall timeout), shielded from cancellation
        still_running = [p for p in self._procs if p.returncode is None]
        if still_running:
            with suppress(asyncio.CancelledError):
                try:
                    await asyncio.shield(
                        asyncio.wait_for(
                            asyncio.gather(*[p.wait() for p in still_running]),
                            timeout=10,
                        )
                    )
                except TimeoutError:
                    for p in self._procs:
                        if p.returncode is None:
                            with suppress(ProcessLookupError):
                                p.kill()
                            await p.wait()


async def check_ports_free(*urls: str) -> None:
    """Verify URLs are not responding (ports are free). Raise SystemExit if any respond."""

    async def check(client: httpx.AsyncClient, url: str) -> None:
        with suppress(httpx.RequestError):
            res = await client.get(url, timeout=0.1)
            server = res.headers.get("server", "server")
            logger.warning("Conflicting %s already running at %s", server, url)
            raise SystemExit(1)

    async with httpx.AsyncClient() as client:
        await asyncio.gather(*[check(client, url) for url in urls])


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


def setup_vite(
    endpoint: str, default_port: int = 5173
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
    endpoint: str, module: str, default_port: int = 8000
) -> tuple[str, str, dict]:
    """Parse backend endpoint and build server.run() config.

    Returns (url, module, config_dict).
    Raises SystemExit(1) on invalid config.
    """
    endpoints = parse_endpoint(endpoint, default_port)

    if "uds" in endpoints[0]:
        logger.warning("Unix sockets not supported with vite devserver")
        raise SystemExit(1)

    host = endpoints[0]["host"]
    port = endpoints[0]["port"]

    config = {
        "listen": f"{host}:{port}",
        "reload": True,
        "reload_dirs": [module.split(".")[0]],  # Don't reload on frontend changes
        "forwarded_allow_ips": "*",
    }
    return f"http://{host}:{port}", module, config
