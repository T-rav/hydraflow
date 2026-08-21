"""Run the gateway with uvicorn via ``python -m hydraflow_gateway``."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    """Start one in-memory-key worker using the deployable env contract."""
    host = os.environ.get("GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("GATEWAY_PORT", "8080"))
    uvicorn.run(
        "hydraflow_gateway.app:create_app",
        factory=True,
        host=host,
        port=port,
        workers=1,
        access_log=False,
        date_header=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
