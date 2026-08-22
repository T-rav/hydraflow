"""s91 — real Docker-network gateway transit reaches ledger and UI gauge.

This scenario exercises the production FastAPI/httpx gateway and the
HTTP-level fake upstream. MockWorld still owns GitHub/pipeline state; only the
external LLM boundary is real network I/O inside the air-gapped sandbox. The
production ``GatewayCoverageLoop`` consumes the resulting ledger row before
the dashboard assertion.
"""

from __future__ import annotations

import os

import httpx

from mockworld.seed import MockWorldSeed

NAME = "s91_gateway_session_tap"
DESCRIPTION = (
    "Mint a virtual key, stream one Anthropic response through the gateway, "
    "and observe the priced ledger row as 100% gateway coverage in the UI."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        cycles_to_run=1,
        prompt_telemetry_source_initialized=True,
    )


async def assert_outcome(api, page) -> None:
    gateway = os.environ.get("SANDBOX_GATEWAY_BASE", "http://gateway:8080")
    control_token = os.environ.get(
        "SANDBOX_GATEWAY_CONTROL_TOKEN",
        "hfgwctl_sandbox-control-token-0123456789abcdef",
    )
    initial_coverage = await api.get("/api/diagnostics/gateway-coverage?range=24h")
    repo_slug = initial_coverage.get("repo_slug")
    assert isinstance(repo_slug, str) and repo_slug

    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, read=None)) as client:
        minted = await client.post(
            f"{gateway}/control/v1/keys",
            headers={"authorization": f"Bearer {control_token}"},
            json={
                "principal_kind": "role",
                "principal_id": "sandbox-gateway-probe",
                "spawn_id": "s91-spawn",
                "session_id": "s91-session",
                "repo_slug": repo_slug,
                "repo_class": "hydraflow",
                "provider_binding": "anthropic",
                "capture_bodies": False,
                "ttl_seconds": 300,
            },
        )
        minted.raise_for_status()
        key = minted.json()["token"]

        chunks: list[bytes] = []
        async with client.stream(
            "POST",
            f"{gateway}/v1/messages?beta=s91",
            headers={
                "authorization": f"Bearer {key}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "sandbox-session-tap",
            },
            json={
                "model": "claude-sonnet-4-5",
                "max_tokens": 64,
                "stream": True,
                "messages": [{"role": "user", "content": "sandbox tap"}],
            },
        ) as response:
            assert response.status_code == 200
            async for chunk in response.aiter_raw():
                chunks.append(chunk)

    raw = b"".join(chunks)
    assert b"message_stop" in raw

    coverage = await api.wait_until(
        "/api/diagnostics/gateway-coverage?range=24h",
        lambda payload: (
            payload.get("gateway_requests", 0) >= 1
            and payload.get("coverage_percent") == 100.0
        ),
        timeout=30.0,
    )
    assert coverage["bypass_requests"] == 0
    assert coverage["bypassing_families"] == []

    await page.goto("/")
    await page.get_by_text("System", exact=True).first.click()
    await page.get_by_text("Diagnostics", exact=True).first.click()
    await page.get_by_text("Factory Cost", exact=True).first.click()
    gauge = page.locator('[data-testid="gateway-coverage-gauge"]')
    await gauge.wait_for(timeout=15_000)
    value = gauge.locator('[data-testid="gateway-coverage-value"]')
    await value.wait_for(timeout=15_000)
    assert "100" in await value.inner_text()
