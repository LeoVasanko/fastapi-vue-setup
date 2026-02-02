import contextlib
import ipaddress
from urllib.parse import urlparse


def parse_endpoint(value: str | None, default_port: int = 0) -> list[dict]:
    """Parse an endpoint string into uvicorn bind configurations.

    Args:
        value: Endpoint string to parse
        default_port: Port to use when not specified

    Returns:
        List of dicts with uvicorn bind kwargs (host/port or uds).

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

    # Leading colon :port -> bind all interfaces (0.0.0.0 + ::)
    if value.startswith(":") and value != ":":
        port_part = value[1:]
        if not port_part.isdigit():
            raise SystemExit(f"Invalid port in '{value}'")
        port = int(port_part)
        return [{"host": "0.0.0.0", "port": port}, {"host": "::", "port": port}]  # noqa: S104

    # UNIX domain socket (unix:/path or just /path)
    if value.startswith("/"):
        return [{"uds": value}]
    if value.startswith("unix:"):
        uds_path = value[5:] or None
        if uds_path is None:
            raise SystemExit("unix: path must not be empty")
        return [{"uds": uds_path}]

    # Unbracketed IPv6 (cannot safely contain a port) -> detect by multiple colons
    if value.count(":") > 1 and not value.startswith("["):
        try:
            ipaddress.IPv6Address(value)
        except ValueError as e:
            raise SystemExit(f"Invalid IPv6 address '{value}': {e}") from e
        return [{"host": value, "port": default_port}]

    # Use urllib.parse for everything else (host[:port], [ipv6][:port])
    parsed = urlparse(f"//{value}")  # // prefix lets urlparse treat it as netloc
    host = parsed.hostname or "localhost"
    port = parsed.port or default_port

    # Validate IP literals (optional; hostname passes through)
    with contextlib.suppress(ValueError):
        ipaddress.ip_address(host)

    return [{"host": host, "port": port}]
