"""Wire-level contract tests for the deterministic sandbox provider fake."""

from __future__ import annotations

import httpx

from hydraflow_gateway.observer import SseUsageObserver
from hydraflow_gateway.sandbox_upstream import create_sandbox_app


class TestSandboxUpstream:
    async def test_stream_is_valid_deterministic_anthropic_sse(self) -> None:
        app = create_sandbox_app(api_key="provider-secret")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://upstream.test",
        ) as client:
            response = await client.post(
                "/v1/messages",
                headers={
                    "x-api-key": "provider-secret",
                    "anthropic-beta": "tools-2025-04-20",
                    "anthropic-version": "2023-06-01",
                },
                json={"model": "claude-sonnet-4-6", "stream": True},
            )
            observation = await client.get("/observations/latest")

        assert response.status_code == 200
        assert response.content.count(b"event:") >= 5
        assert b'"type":"tool_use"' in response.content
        assert b'"type":"thinking_delta"' in response.content
        assert b'"type":"message_stop"' in response.content
        observer = SseUsageObserver()
        observer.feed(response.content)
        usage = observer.finish()
        assert usage.model_served == "claude-sonnet-4-6"
        assert usage.input_tokens == 17
        assert usage.output_tokens == 23
        assert usage.cache_read_tokens == 5
        assert usage.cache_write_tokens == 3
        assert observation.json()["anthropic_beta"] == "tools-2025-04-20"
        assert observation.json()["provider_auth_valid"] is True
        assert "provider-secret" not in observation.text

    async def test_provider_auth_fails_closed(self) -> None:
        app = create_sandbox_app(api_key="provider-secret")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://upstream.test",
        ) as client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": "wrong"},
                json={"model": "claude-sonnet-4-6"},
            )

        assert response.status_code == 401
        assert "provider-secret" not in response.text

    async def test_tool_result_turn_finishes_the_agentic_session(self) -> None:
        app = create_sandbox_app(api_key="provider-secret")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://upstream.test",
        ) as client:
            response = await client.post(
                "/v1/messages",
                headers={"x-api-key": "provider-secret"},
                json={
                    "messages": [
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_sandbox",
                                    "content": "README contents",
                                }
                            ],
                        }
                    ]
                },
            )
            observation = await client.get("/observations/latest")

        assert response.status_code == 200
        assert b'"stop_reason":"end_turn"' in response.content
        assert b"sandbox tool round trip complete" in response.content
        assert observation.json()["tool_result_observed"] is True

    async def test_rate_limit_and_overload_are_deterministic(self) -> None:
        app = create_sandbox_app(api_key="provider-secret")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://upstream.test",
        ) as client:
            rate_limit = await client.post(
                "/v1/messages",
                headers={"x-api-key": "provider-secret"},
                json={"sandbox_scenario": "rate-limit"},
            )
            overloaded = await client.post(
                "/v1/messages",
                headers={"x-api-key": "provider-secret"},
                json={"sandbox_scenario": "overloaded"},
            )

        assert rate_limit.status_code == 429
        assert rate_limit.json()["error"]["type"] == "rate_limit_error"
        assert overloaded.status_code == 529
        assert overloaded.json()["error"]["type"] == "overloaded_error"
