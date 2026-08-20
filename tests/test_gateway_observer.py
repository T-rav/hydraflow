"""Tests for bounded, byte-transparent request and SSE observers."""

from __future__ import annotations

import pytest

from hydraflow_gateway.observer import RequestMetadataObserver, SseUsageObserver

_DEEPLY_NESTED_VALUE = b"[" * 2_000 + b"0" + b"]" * 2_000
_HUGE_INTEGER = b"9" * 5_000


def _forward_through_observer(
    observer: RequestMetadataObserver | SseUsageObserver,
    raw: bytes,
) -> bytes:
    forwarded = bytearray()
    for offset in range(0, len(raw), 37):
        chunk = raw[offset : offset + 37]
        observer.feed(chunk)
        forwarded.extend(chunk)
    return bytes(forwarded)


class TestRequestMetadataObserver:
    def test_model_requested_handles_arbitrary_chunking(self) -> None:
        observer = RequestMetadataObserver()
        observer.feed(b'{"model":"claude-')
        observer.feed(b'sonnet","messages":[]}')
        assert observer.model_requested() == "claude-sonnet"

    def test_model_requested_returns_none_for_invalid_or_oversized_json(self) -> None:
        invalid = RequestMetadataObserver()
        invalid.feed(b"not-json")
        oversized = RequestMetadataObserver(max_bytes=3)
        oversized.feed(b"four")

        assert invalid.model_requested() is None
        assert oversized.model_requested() is None

    @pytest.mark.parametrize(
        "body",
        [
            b'{"model":"must-not-surface","nested":' + _DEEPLY_NESTED_VALUE + b"}",
            b'{"model":"must-not-surface","number":' + _HUGE_INTEGER + b"}",
        ],
        ids=["recursive-json", "oversized-integer"],
    )
    def test_model_requested_treats_json_parser_limits_as_unknown(
        self, body: bytes
    ) -> None:
        observer = RequestMetadataObserver()

        forwarded = _forward_through_observer(observer, body)

        assert forwarded == body
        assert observer.model_requested() is None


class TestSseUsageObserver:
    def test_finish_extracts_model_and_latest_usage_across_split_lines(self) -> None:
        raw = (
            b'event: message_start\r\ndata: {"type":"message_start","message":'
            b'{"model":"claude-test","usage":{"input_tokens":11,'
            b'"cache_creation_input_tokens":3,"cache_read_input_tokens":4}}}\r\n\r\n'
            b'event: message_delta\ndata: {"type":"message_delta","usage":'
            b'{"output_tokens":17}}\n\n'
        )
        observer = SseUsageObserver()
        for offset in range(0, len(raw), 7):
            observer.feed(raw[offset : offset + 7])

        usage = observer.finish()

        assert usage.model_served == "claude-test"
        assert usage.input_tokens == 11
        assert usage.output_tokens == 17
        assert usage.cache_read_tokens == 4
        assert usage.cache_write_tokens == 3
        assert usage.malformed_events == 0

    def test_finish_supports_multiline_data_and_eof_terminated_event(self) -> None:
        observer = SseUsageObserver()
        observer.feed(
            b'data: {"type":"message_delta",\ndata: "usage":{"output_tokens":9}}'
        )

        assert observer.finish().output_tokens == 9

    def test_malformed_and_oversized_events_do_not_interrupt_later_usage(self) -> None:
        observer = SseUsageObserver(max_event_bytes=64)
        observer.feed(b"data: {invalid}\n\n")
        observer.feed(b"data: " + (b"x" * 65) + b"\n\n")
        observer.feed(b'data: {"usage":{"output_tokens":5}}\n\n')

        usage = observer.finish()

        assert usage.output_tokens == 5
        assert usage.malformed_events == 2

    def test_no_newline_input_is_bounded_and_recovers_after_line_end(self) -> None:
        observer = SseUsageObserver(max_event_bytes=64)
        for _ in range(16):
            observer.feed(b"x" * 16)
        observer.feed(b"\n\n")
        observer.feed(b'data: {"usage":{"output_tokens":5}}\n\n')

        usage = observer.finish()

        assert usage.output_tokens == 5
        assert usage.malformed_events == 1

    def test_negative_boolean_and_noninteger_usage_values_are_ignored(self) -> None:
        observer = SseUsageObserver()
        observer.feed(
            b'data: {"usage":{"input_tokens":true,"output_tokens":-1,'
            b'"cache_read_input_tokens":"7"}}\n\n'
        )

        usage = observer.finish()

        assert usage.input_tokens == 0
        assert usage.output_tokens == 0
        assert usage.cache_read_tokens == 0

    def test_finish_extracts_nonstream_anthropic_json_usage(self) -> None:
        raw = (
            b'{"id":"msg_json","type":"message","model":"claude-sonnet-4-6",'
            b'"usage":{"input_tokens":13,"output_tokens":21,'
            b'"cache_creation_input_tokens":2,"cache_read_input_tokens":8}}'
        )
        observer = SseUsageObserver()
        for offset in range(0, len(raw), 11):
            observer.feed(raw[offset : offset + 11])

        usage = observer.finish()

        assert usage.model_served == "claude-sonnet-4-6"
        assert usage.input_tokens == 13
        assert usage.output_tokens == 21
        assert usage.cache_write_tokens == 2
        assert usage.cache_read_tokens == 8

    @pytest.mark.parametrize(
        "malformed_payload",
        [
            b'{"model":"must-not-surface","nested":' + _DEEPLY_NESTED_VALUE + b"}",
            b'{"model":"must-not-surface","usage":{"output_tokens":'
            + _HUGE_INTEGER
            + b"}}",
        ],
        ids=["recursive-json", "oversized-integer"],
    )
    def test_feed_marks_json_parser_limits_malformed_and_forwards_later_events(
        self, malformed_payload: bytes
    ) -> None:
        valid_event = b'data: {"model":"claude-valid","usage":{"output_tokens":7}}\n\n'
        raw = b"data: " + malformed_payload + b"\n\n" + valid_event
        observer = SseUsageObserver()

        forwarded = _forward_through_observer(observer, raw)
        usage = observer.finish()

        assert forwarded == raw
        assert usage.model_served == "claude-valid"
        assert usage.output_tokens == 7
        assert usage.malformed_events == 1

    @pytest.mark.parametrize(
        "body",
        [
            b'{"model":"must-not-surface","nested":' + _DEEPLY_NESTED_VALUE + b"}",
            b'{"model":"must-not-surface","usage":{"output_tokens":'
            + _HUGE_INTEGER
            + b"}}",
        ],
        ids=["recursive-json", "oversized-integer"],
    )
    def test_finish_marks_nonstream_json_parser_limits_malformed(
        self, body: bytes
    ) -> None:
        observer = SseUsageObserver()

        forwarded = _forward_through_observer(observer, body)
        usage = observer.finish()

        assert forwarded == body
        assert usage.model_served is None
        assert usage.output_tokens == 0
        assert usage.malformed_events == 1
