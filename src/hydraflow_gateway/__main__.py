"""Run the gateway with uvicorn via ``python -m hydraflow_gateway``."""

from __future__ import annotations

import os

import uvicorn

from observability import sentry_adapter


def main() -> None:
    """Start one in-memory-key worker using the deployable env contract."""
    # The gateway is a separate process, so the factory's sensor never covered
    # it -- and ADR-0147 made it the path every LLM spawn takes, which makes
    # gateway availability factory availability. An unreported crash here
    # stops the factory while the factory's own logs stay clean.
    sentry_adapter.install_process_sensor("gateway")

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
