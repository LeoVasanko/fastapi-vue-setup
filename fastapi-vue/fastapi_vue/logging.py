"""Logging integration: tracerite loading and colored access log formatting.

The access log middleware supplies colored fields (``client``, ``status``,
``method``, ``host``, ``path``, ``extra``, ``timing``) via ``extra=``.  When
colors are disabled the ANSI escape codes are stripped from the assembled
output so the same formatting code path produces plain text.
"""

from __future__ import annotations

import io
import logging
import os
import re
import sys
from contextlib import suppress
from copy import deepcopy
from typing import TYPE_CHECKING, Literal

import tracerite
from starlette.middleware.errors import ServerErrorMiddleware
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from uvicorn.config import LOGGING_CONFIG, Config
from uvicorn.lifespan.on import LifespanOn

if TYPE_CHECKING:
    from typing import Any

    from starlette.requests import Request
    from uvicorn._types import LifespanScope
    from uvicorn.lifespan.on import LifespanSendMessage

from .accesslog import AccessLogMiddleware
from .environ import env

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")

RESET = "\033[0m"

ACCESS_LOG_FMT = "%(client)s %(status)s %(method)s %(host)s%(path)s %(extra)s%(timing)s"

ACCESS_LOGGER = "fastapi_vue.access"


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return ANSI_ESCAPE_RE.sub("", text)


def use_color(stream: io.TextIOBase = sys.stderr) -> bool:
    """Test if the stream supports color codes."""
    if os.environ.get("NO_COLOR"):  # Non empty means no (no-color.org)
        return False
    if os.environ.get("FORCE_COLOR", "") not in {"", "0"}:  # force-color.org, node
        return True
    if hasattr(stream, "isatty") and stream.isatty():
        return True
    with suppress(KeyError, ValueError, OSError):  # Journald does color (-ocat)
        dev, ino = map(int, os.environ["JOURNAL_STREAM"].split(":", 1))
        st = os.fstat(stream.fileno())
        return st.st_dev == dev and st.st_ino == ino
    return False


_LEVEL_EMOJI = {
    logging.DEBUG: "🐛",
    logging.INFO: "🔷",
    logging.WARNING: "❗",
    logging.ERROR: "🛑",
    logging.CRITICAL: "🚨",
}


def _level_prefix(record: logging.LogRecord) -> str:
    emoji = _LEVEL_EMOJI.get(record.levelno)
    return f"{emoji} " if emoji else f"{record.levelname}: "


class Formatter(logging.Formatter):
    """Formatter for both access records and ordinary log messages.

    Records with the middleware's access fields (``client`` etc.) are
    formatted from those; anything else gets an emoji level prefix
    (``LEVEL: `` fallback for unknown levels) in place of uvicorn's
    ``levelprefix``.

    Instantiation always loads tracerite, and with ``access=True`` also
    installs the access-log middleware: ``dictConfig`` builds formatters while
    uvicorn applies ``log_config``, which happens before the app is loaded —
    including in reload/worker subprocesses that re-import the config without
    calling ``fastapi_vue.server.run()`` again.  Patching the server error
    middleware here likewise propagates it to those subprocesses.
    """

    def __init__(
        self,
        fmt: str | None = None,
        datefmt: str | None = None,
        style: Literal["%", "{", "$"] = "%",
        use_colors: bool | None = None,  # noqa: FBT001  # mirrors logging.Formatter
        *,
        access: bool = False,
        install: bool = True,
    ) -> None:
        """Load tracerite, optionally install server patches and access log."""
        tracerite.load()
        tracerite.load_suppressions(
            extra={"starlette.routing": "until", "fastapi.routing": "until"}
        )
        if install:
            patch_lifespan_logging()
            patch_server_error_middleware()
        if access:
            install_access_log()
        if use_colors in (True, False):
            self.use_colors = use_colors
        else:
            self.use_colors = use_color(sys.stdout)
        super().__init__(fmt=fmt, datefmt=datefmt, style=style)

    def formatMessage(self, record: logging.LogRecord) -> str:  # noqa: N802
        """Format access records via middleware fields, others with an emoji prefix."""
        if "client" not in record.__dict__:
            return _level_prefix(record) + record.getMessage()
        formatted = super().formatMessage(record)
        if not self.use_colors:
            return strip_ansi(formatted)
        # Guard against app-supplied fields (``extra``) carrying raw color
        # codes without a reset: ensure the line begins and ends with a
        # reset, but only add one where it's missing to avoid duplicates.
        if not formatted.startswith(RESET):
            formatted = RESET + formatted
        if not formatted.endswith(RESET):
            formatted += RESET
        return formatted


class WebSocketChatterFilter(logging.Filter):
    """Drop stock uvicorn WebSocket handshake/chatter records.

    Stock uvicorn logs WS handshakes (``'%s - "WebSocket %s" ...'``) and the
    websockets library's "connection open/closed" chatter to ``uvicorn.error``,
    ungated by ``access_log``.  Our middleware logs WebSockets itself.
    """

    _PREFIXES = ('%s - "WebSocket ', "connection open", "connection closed", "connection rejected")

    def filter(self, record: logging.LogRecord) -> bool:
        """Keep records not matching stock WebSocket chatter prefixes."""
        msg = record.msg
        if not isinstance(msg, str):
            return True
        return not msg.startswith(self._PREFIXES)


class UvicornQuietFilter(logging.Filter):
    """Silence uvicorn's routine chatter (startup/shutdown lines, etc.).

    Handler-side, not a logger level: uvicorn's ``configure_logging``
    re-applies ``log_level`` to its loggers after ``dictConfig``, which would
    override a level lifted in the config dict.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """Drop uvicorn records below WARNING."""
        return not (record.name.startswith("uvicorn") and record.levelno < logging.WARNING)


_installed = False


def install_access_log() -> None:
    """Wrap apps loaded by uvicorn with AccessLogMiddleware, once per process.

    The guard is deliberately module-level: reload/worker subprocesses
    re-import this module, resetting it so the patch is re-applied there.
    """
    global _installed  # noqa: PLW0603  # deliberately module-level, see docstring
    if _installed:
        return
    _installed = True

    original_load = Config.load

    def load(self):  # noqa: ANN001, ANN202
        original_load(self)
        if not isinstance(self.loaded_app, AccessLogMiddleware):
            self.loaded_app = AccessLogMiddleware(self.loaded_app)

    Config.load = load  # type: ignore[method-assign]


_lifespan_patched = False


def patch_lifespan_logging() -> None:
    """Patch uvicorn's LifespanOn to log lifespan failures with exc_info.

    Starlette formats lifespan exceptions into a plain-text ASGI message,
    which uvicorn logs as-is without exc_info, while the exc_info-carrying
    log in ``LifespanOn.main()`` is skipped when a failure message was sent.
    This suppresses the text message and always logs the exception with
    exc_info, so tracerite (or any exc_info-aware handler) renders the
    traceback. Monkeypatches uvicorn internals; written against uvicorn 0.52.
    """
    global _lifespan_patched  # noqa: PLW0603  # once-per-process, resets in subprocesses
    if _lifespan_patched:
        return
    _lifespan_patched = True

    original_send = LifespanOn.send

    async def send(self: LifespanOn, message: LifespanSendMessage) -> None:
        # Drop the pre-formatted traceback text; main() logs the exception itself.
        if message["type"] in ("lifespan.startup.failed", "lifespan.shutdown.failed"):
            message = dict(message)  # type: ignore[assignment]
            message.pop("message", None)
        await original_send(self, message)

    async def main(self: LifespanOn) -> None:
        """Mirror upstream LifespanOn.main, but always log failures with exc_info."""
        try:
            app = self.config.loaded_app
            scope: LifespanScope = {
                "type": "lifespan",
                "asgi": {"version": self.config.asgi_version, "spec_version": "2.0"},
                "state": self.state,
            }
            await app(scope, self.receive, self.send)
        except BaseException:
            self.asgi = None
            self.error_occurred = True
            if self.startup_failed or self.shutdown_failed or self.config.lifespan != "auto":
                phase = "shutdown" if self.shutdown_failed else "startup"
                self.logger.exception("Uncaught exception during application %s", phase)
            else:
                self.logger.info("ASGI 'lifespan' protocol appears unsupported.")
        finally:
            self.startup_event.set()
            self.shutdown_event.set()

    LifespanOn.send = send  # type: ignore[method-assign]
    LifespanOn.main = main  # type: ignore[method-assign]


_server_error_patched = False

DEBUG_INGRESS = """This page is shown for your guidance because the application is \
running in debug mode and has crashed handling this request."""


def _generate_html(exc: Exception) -> str:
    return tracerite.html_page(
        exc,
        title="FastAPI debugger",
        heading="500 Server Error",
        ingress=DEBUG_INGRESS,
    )


def _generate_plain_text(exc: Exception) -> str:
    buffer = io.StringIO()
    tracerite.tty_traceback(exc, file=buffer)
    return buffer.getvalue()


def _generate_json(exc: Exception) -> dict[str, Any]:
    chain = tracerite.extract_chain(exc)
    return {"detail": "Internal Server Error", "traceback": chain}


def patch_server_error_middleware() -> None:
    """Patch Starlette's ServerErrorMiddleware to format debug errors with tracerite.

    Starlette's debug responses use its own static HTML traceback template.
    This replaces ``debug_response`` with tracerite renderers (source
    context, locals, chained exceptions), adds ``accept: application/json``
    handling, and returns a JSON body also for non-debug errors when
    requested. Only apps running with ``debug=True`` produce traceback
    responses. Monkeypatches Starlette internals; written against
    starlette 1.6.
    """
    global _server_error_patched  # noqa: PLW0603  # once-per-process, resets in subprocesses
    if _server_error_patched:
        return
    _server_error_patched = True

    def debug_response(
        self: ServerErrorMiddleware,  # noqa: ARG001
        request: Request,
        exc: Exception,
    ) -> Response:
        accept = request.headers.get("accept", "")
        if "text/html" in accept:
            return HTMLResponse(_generate_html(exc), status_code=500)
        if "application/json" in accept:
            return JSONResponse(_generate_json(exc), status_code=500)
        return PlainTextResponse(_generate_plain_text(exc), status_code=500)

    def error_response(
        self: ServerErrorMiddleware,  # noqa: ARG001
        request: Request,
        exc: Exception,  # noqa: ARG001  # signature mirrors Starlette's
    ) -> Response:
        if "application/json" in request.headers.get("accept", ""):
            return JSONResponse({"detail": "Internal Server Error"}, status_code=500)
        return PlainTextResponse("Internal Server Error", status_code=500)

    ServerErrorMiddleware.debug_response = debug_response  # type: ignore[method-assign]
    ServerErrorMiddleware.error_response = error_response  # type: ignore[method-assign]


def _merge_log_config(base: dict, overlay: dict) -> dict:
    """Deep-merge *overlay* onto *base*; dicts merge recursively, others replace."""
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge_log_config(base[key], value)
        else:
            base[key] = value
    return base


def setup_logging(*, log_config: dict | None = None, dev: bool | None = None) -> None:
    """Set up pretty logging standalone, outside of ``server.run()``.

    Optional helper for CLI mains, devservers and scripts that log before
    (or without) starting the server.  Loads tracerite directly and applies
    the same patching as the server path (see ``patch_log_config``, a
    private helper) with ``logging.config.dictConfig``: partial dicts merge
    over uvicorn's default config, so only customizations are needed.  The
    server-side patches (error middleware, access log) are not installed —
    there is no server here.  The root logger level is INFO with *dev*
    true, WARNING otherwise; *dev* of None follows ``env.dev``.  An
    explicit level in *log_config* always wins::

        import fastapi_vue
        fastapi_vue.setup_logging(log_config={"loggers": {"myapp": {"level": "DEBUG"}}})
    """
    if log_config is not None and not isinstance(log_config, dict):
        msg = f"setup_logging requires a dict log_config, got {type(log_config).__name__}"
        raise TypeError(msg)
    import logging.config

    tracerite.load()
    config = patch_log_config(log_config or {}, access_log=False, install=False, dev=dev)
    # Standalone setup must not disable loggers created before this call.
    config.setdefault("disable_existing_loggers", False)
    logging.config.dictConfig(config)


def patch_log_config(log_config, *, access_log: bool = True, install: bool = True, dev: bool | None = None):  # noqa: ANN001, ANN201
    """Patch a uvicorn log_config dict for our logging, best-effort.

    A dict without a ``version`` key is treated as a partial config: it is
    merged over uvicorn's default dict, so only the customizations are
    needed (e.g. ``{"loggers": {"kanta": {"level": "DEBUG"}}}``).  A dict
    with ``version`` is a complete config used as-is; pieces that do not
    fit its structure are silently skipped.  Non-dict configs (e.g. an ini
    file path) pass through untouched.

    Always adds an unreferenced NullHandler whose Formatter instantiation
    loads tracerite in every process uvicorn applies the config in, filters
    on the default handler dropping stock uvicorn's WebSocket chatter and
    routine INFO lines, an emoji-level-prefix Formatter in place of
    uvicorn's stock ``default`` formatter (a user-supplied one wins), a root
    logger entry so ``logging.info()`` et al. print through the default
    handler when one exists, at INFO in dev and WARNING in production
    (matching Python's default).  The
    ``watchfiles.main`` logger is lifted to WARNING so its INFO "N changes
    detected" line is dropped while the WARNING "Reloading..." line (logged
    to ``uvicorn.error``) still shows; a user-supplied level wins.
    With ``install=False`` (standalone use via ``setup_logging``) the
    NullHandler backdoor and the server-side patches in Formatter are
    skipped.  With ``access_log``, additionally rewires the ``access``
    formatter to our Formatter and attaches its handler to our
    ``fastapi_vue.access`` logger.  We must not
    attach handlers to ``uvicorn.access``: uvicorn gates its own
    protocol-level access logging on ``uvicorn.access.hasHandlers()``.
    """
    if not isinstance(log_config, dict):
        return log_config
    config = deepcopy(log_config)
    if "version" not in config:
        config = _merge_log_config(deepcopy(LOGGING_CONFIG), config)

    if install:
        with suppress(Exception):
            config["formatters"]["fastapi_vue"] = {"()": "fastapi_vue.logging.Formatter"}
            config["handlers"]["fastapi_vue"] = {
                "class": "logging.NullHandler",
                "formatter": "fastapi_vue",
            }

    with suppress(Exception):
        filters = config.setdefault("filters", {})
        filters["ws_chatter"] = {"()": "fastapi_vue.logging.WebSocketChatterFilter"}
        filters["uvicorn_quiet"] = {"()": "fastapi_vue.logging.UvicornQuietFilter"}
        handler_filters = config["handlers"]["default"].setdefault("filters", [])
        for name in ("ws_chatter", "uvicorn_quiet"):
            if name not in handler_filters:
                handler_filters.append(name)

    # Emoji level prefixes for ordinary logs, replacing uvicorn's stock
    # default formatter; a user-supplied default formatter is left alone.
    with suppress(Exception):
        default = config["formatters"]["default"]
        if default == LOGGING_CONFIG["formatters"]["default"]:
            config["formatters"]["default"] = {
                "()": "fastapi_vue.logging.Formatter",
                "fmt": "%(message)s",
                "use_colors": None,
                "install": install,
            }

    # uvicorn's default config leaves the root logger handlerless, eating
    # logging.info() et al.; route root through uvicorn's default handler.
    # Level is WARNING in production so third-party loggers stay quiet, as
    # with Python's default; dev keeps INFO.  Subloggers can override.
    with suppress(Exception):
        root = config.setdefault("root", {})
        root.setdefault("level", "INFO" if (env.dev if dev is None else dev) else "WARNING")
        if "default" in config.get("handlers", {}):
            root_handlers = root.setdefault("handlers", [])
            if "default" not in root_handlers:
                root_handlers.append("default")

    # watchfiles logs "N changes detected" to its own logger at INFO; only the
    # WARNING "Reloading..." line (uvicorn.error) should show.
    with suppress(Exception):
        config.setdefault("loggers", {}).setdefault("watchfiles.main", {}).setdefault(
            "level", "WARNING"
        )

    if access_log:
        with suppress(Exception):
            config["formatters"]["access"] = {
                "()": "fastapi_vue.logging.Formatter",
                "fmt": ACCESS_LOG_FMT,
                "use_colors": None,
                "access": True,
            }
        with suppress(Exception):
            if "access" in config["handlers"]:
                config.setdefault("loggers", {})[ACCESS_LOGGER] = {
                    "handlers": ["access"],
                    "level": "INFO",
                    "propagate": False,
                }

    return config
