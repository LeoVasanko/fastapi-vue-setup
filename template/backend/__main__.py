# auto-upgrade@fastapi-vue-setup - remove this if you modify this file
"""Command-line entry point for running the backend server."""

import argparse
import os
from pathlib import Path

from fastapi_vue import server

DEFAULT_PORT = TEMPLATE_DEFAULT_PORT
DEVMODE = os.getenv("ENVPREFIX_DEV") == "1"


def main() -> None:
    """Run the backend server with optional arguments."""
    parser = argparse.ArgumentParser(description="Run the MODULE_NAME server.")
    parser.add_argument(
        "-l",
        "--listen",
        action="append",
        help=(f"Endpoint (default: localhost:{DEFAULT_PORT})."),
    )
    args = parser.parse_args()
    server.run(
        "APP_MODULE:APP_VAR",
        listen=args.listen,
        default_port=DEFAULT_PORT,
        reload=Path(__file__).parent if DEVMODE else False,
    )


if __name__ == "__main__":
    main()
