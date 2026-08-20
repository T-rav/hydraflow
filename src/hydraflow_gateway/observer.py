"""Non-mutating observers for Anthropic request JSON and response SSE."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

_DEFAULT_MAX_OBSERVED_BYTES = 1_048_576
_JSON_OBSERVER_ERRORS = (UnicodeDecodeError, ValueError, RecursionError)


@dataclass(frozen=True)
class UsageSnapshot:
    """Usage and served-model metadata observed from an Anthropic SSE stream."""

    model_served: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    malformed_events: int = 0


class RequestMetadataObserver:
    """Bounded observer that extracts only ``model`` from a JSON request."""

    def __init__(self, *, max_bytes: int = _DEFAULT_MAX_OBSERVED_BYTES) -> None:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        self._max_bytes = max_bytes
        self._buffer = bytearray()
        self._overflowed = False

    def feed(self, chunk: bytes) -> None:
        """Observe a request chunk without changing the bytes being proxied."""
        if self._overflowed:
            return
        if len(self._buffer) + len(chunk) > self._max_bytes:
            self._buffer.clear()
            self._overflowed = True
            return
        self._buffer.extend(chunk)

    def model_requested(self) -> str | None:
        """Return the requested model when the bounded body is valid JSON."""
        if self._overflowed or not self._buffer:
            return None
        try:
            payload = json.loads(self._buffer)
        except _JSON_OBSERVER_ERRORS:
            return None
        if not isinstance(payload, dict):
            return None
        model = payload.get("model")
        return model if isinstance(model, str) and model else None


class SseUsageObserver:
    """Incrementally inspect SSE events while callers forward original bytes."""

    def __init__(self, *, max_event_bytes: int = _DEFAULT_MAX_OBSERVED_BYTES) -> None:
        if max_event_bytes <= 0:
            raise ValueError("max_event_bytes must be positive")
        self._max_event_bytes = max_event_bytes
        self._line_buffer = bytearray()
        self._discarding_line = False
        self._plain_buffer = bytearray()
        self._plain_overflowed = False
        self._data_lines: list[bytes] = []
        self._event_bytes = 0
        self._dropping_event = False
        self._model_served: str | None = None
        self._input_tokens = 0
        self._output_tokens = 0
        self._cache_read_tokens = 0
        self._cache_write_tokens = 0
        self._malformed_events = 0

    def feed(self, chunk: bytes) -> None:
        """Consume zero or more arbitrarily split SSE lines."""
        if not self._plain_overflowed:
            if len(self._plain_buffer) + len(chunk) <= self._max_event_bytes:
                self._plain_buffer.extend(chunk)
            else:
                self._plain_buffer.clear()
                self._plain_overflowed = True
        self._line_buffer.extend(chunk)
        while True:
            if self._discarding_line:
                newline = self._line_buffer.find(b"\n")
                if newline < 0:
                    self._line_buffer.clear()
                    return
                del self._line_buffer[: newline + 1]
                self._discarding_line = False
                continue
            newline = self._line_buffer.find(b"\n")
            if newline < 0:
                if len(self._line_buffer) > self._max_event_bytes:
                    self._line_buffer.clear()
                    self._discarding_line = True
                    self._drop_oversized_event()
                return
            if newline > self._max_event_bytes:
                del self._line_buffer[: newline + 1]
                self._drop_oversized_event()
                continue
            line = bytes(self._line_buffer[:newline])
            del self._line_buffer[: newline + 1]
            self._consume_line(line.removesuffix(b"\r"))

    def finish(self) -> UsageSnapshot:
        """Flush an EOF-terminated event and return the current snapshot."""
        if self._line_buffer:
            self._consume_line(bytes(self._line_buffer).removesuffix(b"\r"))
            self._line_buffer.clear()
        self._consume_event()
        self._consume_plain_json()
        return self.snapshot

    @property
    def snapshot(self) -> UsageSnapshot:
        """Return a stable copy of all metadata observed so far."""
        return UsageSnapshot(
            model_served=self._model_served,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            cache_read_tokens=self._cache_read_tokens,
            cache_write_tokens=self._cache_write_tokens,
            malformed_events=self._malformed_events,
        )

    def _consume_line(self, line: bytes) -> None:
        if not line:
            self._consume_event()
            return
        if self._dropping_event or not line.startswith(b"data:"):
            return
        data = line[5:]
        if data.startswith(b" "):
            data = data[1:]
        self._event_bytes += len(data)
        if self._event_bytes > self._max_event_bytes:
            self._data_lines.clear()
            self._dropping_event = True
            self._malformed_events += 1
            return
        self._data_lines.append(data)

    def _consume_event(self) -> None:
        if self._dropping_event:
            self._reset_event()
            return
        if not self._data_lines:
            self._reset_event()
            return
        raw = b"\n".join(self._data_lines)
        self._reset_event()
        if raw == b"[DONE]":
            return
        try:
            payload = json.loads(raw)
        except _JSON_OBSERVER_ERRORS:
            self._malformed_events += 1
            return
        if not isinstance(payload, dict):
            self._malformed_events += 1
            return
        self._observe_payload(payload)

    def _drop_oversized_event(self) -> None:
        if not self._dropping_event:
            self._malformed_events += 1
        self._data_lines.clear()
        self._event_bytes = 0
        self._dropping_event = True

    def _reset_event(self) -> None:
        self._data_lines.clear()
        self._event_bytes = 0
        self._dropping_event = False

    def _observe_payload(self, payload: dict[str, Any]) -> None:
        model = payload.get("model")
        if isinstance(model, str) and model:
            self._model_served = model
        message = payload.get("message")
        if isinstance(message, dict):
            model = message.get("model")
            if isinstance(model, str) and model:
                self._model_served = model
            self._observe_usage(message.get("usage"))
        self._observe_usage(payload.get("usage"))

    def _consume_plain_json(self) -> None:
        if self._plain_overflowed or not self._plain_buffer:
            return
        raw = bytes(self._plain_buffer).strip()
        self._plain_buffer.clear()
        if not raw.startswith(b"{") or not raw.endswith(b"}"):
            return
        try:
            payload = json.loads(raw)
        except _JSON_OBSERVER_ERRORS:
            self._malformed_events += 1
            return
        if isinstance(payload, dict):
            self._observe_payload(payload)

    def _observe_usage(self, raw: object) -> None:
        if not isinstance(raw, dict):
            return
        self._input_tokens = _latest_nonnegative(
            raw.get("input_tokens"), self._input_tokens
        )
        self._output_tokens = _latest_nonnegative(
            raw.get("output_tokens"), self._output_tokens
        )
        self._cache_read_tokens = _latest_nonnegative(
            raw.get("cache_read_input_tokens"), self._cache_read_tokens
        )
        self._cache_write_tokens = _latest_nonnegative(
            raw.get("cache_creation_input_tokens"), self._cache_write_tokens
        )


def _latest_nonnegative(value: object, current: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return current
