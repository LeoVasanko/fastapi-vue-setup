"""FastAPI static file serving with zstd compression and SPA support."""

from __future__ import annotations

import fnmatch
import logging
import mimetypes
import time
from base64 import urlsafe_b64encode
from functools import partial
from pathlib import Path, PurePath, PurePosixPath
from wsgiref.handlers import format_date_time

from blake3 import blake3
from fastapi import FastAPI, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException
from starlette.routing import Route
from zstandard import ZstdCompressor

logger = logging.getLogger("uvicorn.error")  # Use FastAPI logging style

__all__ = ["Frontend"]


class Assets:
    """Default cached value to /assets/"""

    @staticmethod
    def parse(cached: str | list[str] | Assets) -> list[str]:
        match cached:
            case Assets():
                return ["/assets/"]
            case str():
                return [cached]
            case list():
                return cached
            case _:
                raise ValueError(f"Invalid cached value: {cached!r}")


class Frontend:
    """Static file server with automatic zstd compression and caching.

    Features:
    - Automatic zstd compression for compressible files
    - ETag-based caching of immutable assets
    - SPA (Single Page Application) support
    - /favicon.ico with correct MIME type (image/png etc)
    - Dev mode: indexes files but returns error directing to Vite server

    Args:
        directory: Path to the directory containing static files
        index: Name of the index file (default: "index.html")
        spa: Enable SPA mode - serve index.html for unknown routes (default: False)
        cached: Path prefixes that are immutable (default: "/assets/")
        favicon: May use wildcards of full path. E.g. /assets/logo*.png matches logo.hash.png created by Vite
        zstdlevel: Zstd compression level (default: 18)
    """

    def __init__(
        self,
        directory: Path | str,
        *,
        index: str = "index.html",
        spa: bool = False,
        catch_all: bool | None = None,
        cached: str | list[str] | Assets = Assets(),
        favicon: str | None = None,
        zstdlevel: int = 18,
    ) -> None:
        self.www: dict[str, tuple[bytes, bytes | None, dict]] = {}
        self.base: Path = Path(directory)
        self.index = index
        self.spa = spa
        self._catch_all = spa if catch_all is None else catch_all
        self.cached_paths = Assets.parse(cached)
        self.zstdlevel = zstdlevel
        self.favicon = favicon
        self._app: FastAPI | None = None
        self._mount_path: str = ""
        self._ridx: int = 0
        self._routes: list[Route] = []

    def _index_only(self) -> set[str]:
        """Index file paths without loading content (for dev mode)."""
        paths: set[str] = set()
        if not self.base.exists():
            return paths
        queue = [PurePath()]
        while queue:
            current = self.base / queue.pop(0)
            for p in current.iterdir():
                rel = p.relative_to(self.base)
                if p.is_dir():
                    queue.append(rel)
                    continue
                name = "/" + rel.as_posix()
                name = name.removesuffix(self.index)
                paths.add(name)
        if self.favicon:
            p = PurePosixPath(self.favicon)
            base = str(p.with_suffix(""))
            ext = p.suffix
            if any(path.startswith(base) and path.endswith(ext) for path in paths):
                paths.add("/favicon.ico")
        return paths

    def _load(self):
        """Load static files from disk with compression."""
        www: dict[str, tuple[bytes, bytes | None, dict]] = {}
        if not self.base.exists():
            raise ValueError(f"Frontend folder {self.base} not found (try uv build)")
        paths = [PurePath()]
        while paths:
            current = self.base / paths.pop(0)
            for p in current.iterdir():
                rel = p.relative_to(self.base)
                if p.is_dir():
                    paths.append(rel)
                    continue
                # Read file
                name = "/" + rel.as_posix()
                mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
                name = name.removesuffix(self.index)
                data = p.read_bytes()
                etag = urlsafe_b64encode(blake3(data).digest(9)).decode()
                if mime.startswith("text/"):
                    mime += "; charset=UTF-8"
                mtime = p.stat().st_mtime
                cached = any(name.startswith(prefix) for prefix in self.cached_paths)
                headers = {
                    "etag": f'"{etag}"',
                    "last-modified": format_date_time(mtime),
                    "cache-control": (
                        "max-age=31536000, immutable" if cached else "no-cache"
                    ),
                    "content-type": mime,
                }
                zstd = ZstdCompressor(self.zstdlevel).compress(data)
                if len(zstd) >= len(data):
                    zstd = None
                www[name] = data, zstd, headers
        if self.favicon:
            if m := fnmatch.filter(www, self.favicon):
                data, zstd, headers = www[m[0]]
                if "immutable" in headers.get("cache-control", ""):
                    headers = {**headers, "cache-control": "max-age=86400"}
                www["/favicon.ico"] = data, zstd, headers
        if not www:
            msg = "Frontend files missing, check your installation.\n"
            www["/"] = (
                msg.encode(),
                None,
                {
                    "etag": "error",
                    "content-type": "text/plain",
                    "cache-control": "no-store",
                },
            )
        return www

    async def load(self, *, debug: bool | None = None, log: bool = True):
        """Load or reload static files from disk.

        In debug mode, returns 409 instead of files (avoid accidental use of stale builds)
        If debug is None, uses app.debug (app passed to frontend.route)
        """
        if debug is None:
            debug = getattr(self._app, "debug", False)
        if debug:
            # Dev mode: just index paths, no content loading
            self._devmode_paths = await run_in_threadpool(self._index_only)
            self._register_routes()
            return

        start = time.perf_counter()
        self.www = await run_in_threadpool(self._load)
        self._register_routes()
        duration = time.perf_counter() - start
        if not log:
            return
        compfiles = [(len(d), len(z)) for d, z, _ in self.www.values() if z]
        raw = sum(v[0] for v in compfiles)
        comp = sum(v[1] for v in compfiles)
        ratio = comp / raw * 100 if raw else 100.0
        if log and self.www:
            logger.info(
                f"{self.base.name}: {len(self.www)} files in {1000 * duration:.1f} ms | "
                f"zstd {len(compfiles)} files {1e-6 * raw:.2f}->{1e-6 * comp:.2f} MB ({ratio:.0f} %)"
            )
        if self.favicon and "/favicon.ico" not in self.www:
            logger.warning("Favicon not found: %s", self.favicon)

    def route(self, app: FastAPI, mount_path="/"):
        """Register frontend routes with a FastAPI app.

        In SPA/catch-all mode, this must only be called only after all other routes.

        The calling position determines routing priority, although in regular mode the
        routes are actually added only after load() is called.

        Args:
            app: FastAPI application instance
            mount_path: Path where the frontend should be mounted (default: "/")
        """
        self._app = app
        self._mount_path = mount_path.rstrip("/")
        self._ridx = len(app.routes)

        if self._catch_all:
            # Register catch-all immediately (works without load)
            path = self._mount_path + "{path:path}"
            app.api_route(path, methods=["GET", "HEAD"], name="frontend")(self.handle)

    def _register_routes(self):
        """Register individual routes for each loaded file (non-catch_all mode)."""
        if self._app is None or self._catch_all:
            return

        # Remove previously registered routes (for reload support)
        for route in list(self._routes):
            if route in self._app.routes:
                self._app.routes.remove(route)
        self._routes.clear()

        # Get paths and select handler based on mode (checked once, not per request)
        debug = getattr(self._app, "debug", False)
        paths = self._devmode_paths if debug else self.www.keys()
        handler = _devmode_respond if debug else self._respond
        # Insert at the position where route() was called
        self._app.routes[self._ridx : self._ridx] = self._routes = [
            Route(
                self._mount_path + p,
                endpoint=handler if debug else partial(handler, name=p),
                methods=["GET", "HEAD"],
                name=f"frontend{p.replace('/', '_')}",
            )
            for p in paths
        ]

    def _respond(self, request: Request, name: str):
        """Serve a static file with ETag and compression support."""
        data, zstd, headers = self.www[name]
        if request.headers.get("if-none-match") == headers["etag"]:
            return Response(status_code=304, headers=headers)
        if zstd and "zstd" in request.headers.get("accept-encoding", ""):
            return Response(
                content=zstd, headers={**headers, "content-encoding": "zstd"}
            )
        return Response(content=data, headers=headers)

    def handle(self, request: Request, path: str):
        """SPA catch-all handler with directory redirects and fallback to index."""
        name = path.removesuffix(self.index)
        debug = getattr(self._app, "debug", False)
        files = self._devmode_paths if debug else self.www

        if name not in files:
            # Friendly redirect for directories missing trailing slash
            if name and f"{name}/" in files:
                return RedirectResponse(request.url.path + "/")
            # SPA support: serve / for unknown paths if the browser wants HTML
            if self.spa and "text/html" in request.headers.get("accept", ""):
                name = "/"
            # 404 for everything else
            if name not in files:
                raise HTTPException(status_code=404)

        return (_devmode_respond if debug else self._respond)(request, name)


def _devmode_respond(request: Request, name=""):
    """Return error response directing to Vite server."""
    return JSONResponse(
        status_code=409,
        content={
            "detail": "Frontend assets served by Vite in debug mode. You are on backend, connect to frontend instead."
        },
    )
