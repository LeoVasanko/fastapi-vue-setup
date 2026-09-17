"""Access to the project's fastapi-vue environment variables.

The project entry point (generated __main__.py) sets FASTAPI_VUE to the
project-specific prefix (e.g. "MY_APP"). Project settings are then passed
as "<PREFIX>_*" environment variables; this module is the single place
that resolves those names.

Call env with a dataclass or msgspec.Struct type to bind an object of
that type, e.g. env(Config). It is decoded from "<PREFIX>_<CLASS NAME>"
when set (in spawned server processes) and default-constructed otherwise
(in the CLI entry point, which mutates it before server.run() calls
teleport()).
"""

import dataclasses
import json
import os
import re
from typing import Any, TypeVar

PREFIX_VARIABLE = "FASTAPI_VUE"

# Names already used by fastapi-vue itself; bindings may not take them
RESERVED_NAMES = frozenset({"DEV", "VITE_URL", "BACKEND_URL"})

T = TypeVar("T")


def _mangle(name: str) -> str:
    """Class name to env name: underscores normalized, uppercased."""
    return re.sub(r"_+", "_", name).strip("_").upper()


def _encode(obj: Any) -> str:  # noqa: ANN401
    if hasattr(type(obj), "__struct_fields__"):
        import msgspec  # noqa: PLC0415

        return msgspec.json.encode(obj).decode()
    return json.dumps(dataclasses.asdict(obj))


def _decode(raw: str, type_: type[T]) -> T:
    if hasattr(type_, "__struct_fields__"):
        import msgspec  # noqa: PLC0415

        return msgspec.json.decode(raw, type=type_)
    return type_(**json.loads(raw))


class _Env:
    """Lazy accessors for the project's "<PREFIX>_*" environment variables.

    Evaluated on each access. Value accessors return None when FASTAPI_VUE
    or the variable itself is not set.
    """

    def __init__(self) -> None:
        self._bindings: dict[str, tuple[type, Any]] = {}

    def __call__(self, type_: type[T], *, name: str | None = None) -> T:
        """Bind and return an object of the given type.

        The type must be a dataclass or msgspec.Struct with defaults for
        all fields. Decoded from the "<PREFIX>_<NAME>" variable when set,
        default-constructed otherwise. The variable name is derived from
        the class name unless overridden with name=. Repeated calls with
        the same type return the same object; conflicting names raise
        KeyError.
        """
        var = name if name is not None else _mangle(type_.__name__)
        if var in RESERVED_NAMES:
            msg = f"{var} is reserved for fastapi-vue itself"
            raise KeyError(msg)
        if bound := self._bindings.get(var):
            bound_type, obj = bound
            if bound_type is not type_:
                msg = f"{var} is already bound to {bound_type}"
                raise KeyError(msg)
            return obj
        if not (hasattr(type_, "__struct_fields__") or dataclasses.is_dataclass(type_)):
            msg = f"{type_} must be a dataclass or msgspec.Struct"
            raise TypeError(msg)
        raw = self._get(var)
        obj = _decode(raw, type_) if raw else type_()
        self._bindings[var] = (type_, obj)
        return obj

    @property
    def prefix(self) -> str | None:
        """Return the project prefix from the FASTAPI_VUE environment variable."""
        return os.environ.get(PREFIX_VARIABLE) or None

    def _get(self, name: str) -> str | None:
        prefix = self.prefix
        return os.environ.get(f"{prefix}_{name}") if prefix else None

    @property
    def dev(self) -> bool:
        """Check whether running under the devserver (<PREFIX>_DEV=1)."""
        return self._get("DEV") == "1"

    @property
    def vite_url(self) -> str | None:
        """Return the vite devserver URL (<PREFIX>_VITE_URL), if set."""
        return self._get("VITE_URL")

    @property
    def backend_url(self) -> str | None:
        """Return the backend URL (<PREFIX>_BACKEND_URL), if set."""
        return self._get("BACKEND_URL")


env = _Env()


def teleport() -> None:
    """Serialize objects bound via env() into environment variables.

    Called by server.run() before spawning workers, so mutations made in
    the CLI entry point propagate to them. Call directly only when spawning
    server processes by other means.
    """
    if not env._bindings:  # noqa: SLF001
        return
    if not (prefix := env.prefix):
        msg = f"{PREFIX_VARIABLE} is not set; cannot teleport bound objects"
        raise RuntimeError(msg)
    for var, (_, obj) in env._bindings.items():  # noqa: SLF001
        os.environ[f"{prefix}_{var}"] = _encode(obj)
