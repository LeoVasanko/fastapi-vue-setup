# auto-upgrade@fastapi-vue-setup - remove this if you modify this file
import argparse
import asyncio
import os

from fastapi_vue.hostutil import parse_endpoint
from uvicorn import Config, Server

DEFAULT_PORT = 5080


def run_server(endpoints: list[dict], *, proxy=""):
    conf: dict[str, object] = {"app": "MODULE_NAME.APP_MODULE:APP_VAR"}
    if proxy:
        conf["proxy_headers"] = True
        conf["forwarded_allow_ips"] = proxy

    async def serve_all():
        async with asyncio.TaskGroup() as tg:
            for ep in endpoints:
                tg.create_task(Server(Config(**conf, **ep)).serve())

    asyncio.run(serve_all())


def main():
    parser = argparse.ArgumentParser(description="Run the MODULE_NAME server.")
    parser.add_argument(
        "endpoint",
        nargs="?",
        help=(
            f"Endpoint (default: localhost:{DEFAULT_PORT}). "
            "Forms: host:port | :port | [ipv6]:port | ip | host | unix:/path.sock"
        ),
    )
    args = parser.parse_args()
    proxy = os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
    try:
        run_server(parse_endpoint(args.endpoint, DEFAULT_PORT), proxy=proxy)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
