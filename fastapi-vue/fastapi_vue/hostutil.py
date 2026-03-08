"""Parse endpoint strings for uvicorn server configuration."""

import contextlib
import ipaddress
from urllib.parse import urlparse


def _parse_all_interfaces(value: str) -> list[dict] | None:
    """Parse ':port' format to bind all interfaces."""
    if not (value.startswith(":") and value != ":"):
        return None
    port_part = value[1:]
    if not port_part.isdigit():
        msg = f"Invalid port in '{value}'"
        raise SystemExit(msg)
    port = int(port_part)
    return [{"host": "0.0.0.0", "port": port}, {"host": "::", "port": port}]  # noqa: S104


def _parse_unix_socket(value: str) -> list[dict] | None:
    """Parse UNIX domain socket paths."""
    if value.startswith("/"):
        return [{"uds": value}]
    if value.startswith("unix:"):
        uds_path = value[5:] or None
        if uds_path is None:
            msg = "unix: path must not be empty"
            raise SystemExit(msg)
        return [{"uds": uds_path}]
    return None


def _parse_unbracketed_ipv6(value: str, default_port: int) -> list[dict] | None:
    """Parse unbracketed IPv6 addresses."""
    if value.count(":") <= 1 or value.startswith("["):
        return None
    try:
        ipaddress.IPv6Address(value)
    except ValueError as e:
        msg = f"Invalid IPv6 address '{value}': {e}"
        raise SystemExit(msg) from e
    return [{"host": value, "port": default_port}]


def _parse_host_port(value: str, default_port: int) -> list[dict]:
    """Parse host[:port] or [ipv6][:port] using urlparse."""
    parsed = urlparse(f"//{value}")  # // prefix lets urlparse treat it as netloc
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port

    # Validate IP literals (optional; hostname passes through)
    with contextlib.suppress(ValueError):
        ipaddress.ip_address(host)

    return [{"host": host, "port": port}]


def parse_endpoint(value: str | None, default_port: int = 0) -> list[dict]:
    """Parse an endpoint string into uvicorn bind configurations.

    Args:
        value: Endpoint string to parse
        default_port: Port to use when not specified

    Returns:
        List of dicts with uvicorn bind kwargs (host/port or uds).
        Two entries may be returned for IPv4 and IPv6 (all interaces).

    Supported forms:
    - None or empty -> [{host: "localhost", port: default_port}]
    - port (numeric) -> [{host: "localhost", port: port}]
    - :port -> [{host: "0.0.0.0", port}, {host: "::", port}] (all interfaces)
    - host:port -> [{host, port}]
    - host -> [{host, port: default_port}]
    - [ipv6]:port -> [{host: ipv6, port}]
    - ipv6 (unbracketed) -> [{host: ipv6, port: default_port}]
    - /path or unix:/path -> [{uds: path}]

    """
    if not value:
        return [{"host": "localhost", "port": default_port}]

    # Port only (numeric) -> localhost:port
    if value.isdigit():
        return [{"host": "localhost", "port": int(value)}]

    # Try specialized parsers in order
    result = _parse_all_interfaces(value)
    if result is not None:
        return result

    result = _parse_unix_socket(value)
    if result is not None:
        return result

    result = _parse_unbracketed_ipv6(value, default_port)
    if result is not None:
        return result

    # Fallback: host[:port], [ipv6][:port]
    return _parse_host_port(value, default_port)


def parse_endpoints(
    listen: str | list[str] | None = None,
    default_port: int = 8000,
) -> list[dict]:
    """Parse listen strings into a list of endpoint dicts.

    Args:
        listen: Endpoint string(s) (see parse_endpoint for formats).
        default_port: Port to use when not specified in listen args.

    """
    if listen is None:
        listen = [f"localhost:{default_port}"]
    elif isinstance(listen, str):
        listen = [listen]
    return [ep for s in listen for ep in parse_endpoint(s, default_port)]
