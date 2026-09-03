"""Regression: a compressed upstream stream made the gateway ledger cost-blind.

The usage observer is fed `aiter_raw()` — exactly the bytes the upstream sent.
Nothing ever constrained `accept-encoding`, so a client that negotiated gzip
(the default in every common HTTP client, httpx included) got a stream the
observer could not parse: no `data:` frame was legible, and the row landed with
`model_served=None`, zero tokens, `usage_complete=False`, `cost_unknown=True`.

ADR-0147 routed every LLM spawn through the gateway specifically so its ledger
would be the factory's cost record. This made that record empty for the traffic
it was built to measure.

Measured against api.anthropic.com before the fix — the same streaming request,
changing only the client's `accept-encoding`:

    gzip      -> model_served None, input 0,  output 0, cost_unknown True
    identity  -> model_served claude-haiku-4-5-20251001, input 14, output 6

Latent since the tap shipped (#11477): z.ai does not compress, so the only
upstream the ledger had ever recorded happened to be legible.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import SecretStr

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from hydraflow_gateway.proxy import replace_request_headers  # noqa: E402
from hydraflow_gateway.settings import (  # noqa: E402
    UpstreamAuthStyle,
    UpstreamSettings,
)


def _upstream() -> UpstreamSettings:
    return UpstreamSettings(
        base_url="https://upstream.test",
        api_key=SecretStr("k"),
        auth_style=UpstreamAuthStyle.X_API_KEY,
    )


def _encodings(headers: list[tuple[bytes, bytes]]) -> list[bytes]:
    return [value for name, value in headers if name.lower() == b"accept-encoding"]


@pytest.mark.parametrize(
    "client_sent",
    [
        pytest.param(b"gzip", id="gzip"),
        pytest.param(b"gzip, deflate, br", id="httpx-default"),
        pytest.param(b"br;q=1.0, gzip;q=0.8", id="weighted"),
        pytest.param(b"*", id="wildcard"),
    ],
)
def test_the_upstream_is_asked_for_an_uncompressed_stream(
    client_sent: bytes,
) -> None:
    """Whatever the client negotiated, the observer must get legible bytes."""
    headers = replace_request_headers([(b"accept-encoding", client_sent)], _upstream())

    assert _encodings(headers) == [b"identity"]


def test_a_client_that_sent_no_accept_encoding_still_pins_identity() -> None:
    """httpx adds one itself if we do not, so silence is not safety."""
    headers = replace_request_headers([], _upstream())

    assert _encodings(headers) == [b"identity"]


def test_a_capitalised_header_does_not_survive_alongside_it() -> None:
    """HTTP header names are case-insensitive; two values would be ambiguous."""
    headers = replace_request_headers([(b"Accept-Encoding", b"gzip")], _upstream())

    assert _encodings(headers) == [b"identity"]


def test_other_client_headers_are_still_forwarded() -> None:
    """Decoy: pinning one header must not become dropping the rest.

    Without this, blocking every header would satisfy the assertions above
    while breaking `anthropic-version`, `anthropic-beta` and content type.
    """
    headers = replace_request_headers(
        [
            (b"accept-encoding", b"gzip"),
            (b"anthropic-version", b"2023-06-01"),
            (b"content-type", b"application/json"),
        ],
        _upstream(),
    )

    assert (b"anthropic-version", b"2023-06-01") in headers
    assert (b"content-type", b"application/json") in headers


def test_the_observer_can_read_an_uncompressed_sse_frame() -> None:
    """The other half of the story: legible bytes actually yield usage.

    Pins WHY identity matters rather than only that it is set — the header
    assertion alone would pass against an observer that parsed nothing.
    """
    import gzip

    from hydraflow_gateway.observer import SseUsageObserver

    frame = (
        b'data: {"type":"message_start","message":{"model":"claude-haiku-4-5",'
        b'"usage":{"input_tokens":14,"output_tokens":0}}}\n\n'
        b'data: {"type":"message_delta","usage":{"output_tokens":6}}\n\n'
    )

    plain = SseUsageObserver()
    plain.feed(frame)
    legible = plain.finish()

    compressed = SseUsageObserver()
    compressed.feed(gzip.compress(frame))
    illegible = compressed.finish()

    assert legible.input_tokens == 14
    assert legible.output_tokens == 6
    assert legible.model_served == "claude-haiku-4-5"
    # The defect, stated as a fact about the observer: gzip in, nothing out.
    assert illegible.input_tokens == 0
    assert illegible.model_served is None
