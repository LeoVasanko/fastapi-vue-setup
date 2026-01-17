"""Entry point for the application."""

import sys


def main():
    """Run the FastAPI application using uvicorn."""
    import uvicorn

    if len(sys.argv) > 1:
        endpoint = sys.argv[1]
        if ":" in endpoint:
            host, port = endpoint.rsplit(":", 1)
            host = host or "localhost"
            port = int(port)
        else:
            host = "localhost"
            port = int(endpoint)
    else:
        host = "localhost"
        port = {{PROD_PORT}}

    uvicorn.run(
        "{{MODULE_NAME}}.app:app",
        host=host,
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
