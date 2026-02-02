# auto-upgrade@fastapi-vue-setup - remove this if you modify this file
import argparse

from fastapi_vue import server

DEFAULT_PORT = TEMPLATE_DEFAULT_PORT


def main():
    parser = argparse.ArgumentParser(description="Run the MODULE_NAME server.")
    parser.add_argument(
        "-l",
        "--listen",
        action="append",
        help=(f"Endpoint (default: localhost:{DEFAULT_PORT})."),
    )
    args = parser.parse_args()
    server.run(
        "MODULE_NAME.APP_MODULE:APP_VAR",
        listen=args.listen,
        default_port=DEFAULT_PORT,
    )


if __name__ == "__main__":
    main()
