"""Contract tests: StreamParser must consume recorded Claude streams cleanly.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 — FakeLLM is unlike the other adapters: the real dialect we guard is
the `claude ... --output-format stream-json` wire format consumed by
`src/stream_parser.py:StreamParser`. Each sample in `claude_streams/` is a
raw `.jsonl` of real (or real-shape) Claude stream events; this test feeds
them line-by-line into `StreamParser.parse()` and asserts no crash plus at
least one non-empty display line and a final `result` event.

If a sample fails, fix `StreamParser` — not the sample — a failing sample
is the signal that the stream-json protocol drifted.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stream_parser import StreamParser

_STREAM_DIR = Path(__file__).parent / "claude_streams"


def _list_streams() -> list[Path]:
    return sorted(_STREAM_DIR.glob("*.jsonl"))


@pytest.mark.parametrize(
    "stream_path",
    _list_streams(),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
def test_stream_parser_consumes_sample(stream_path: Path) -> None:
    """StreamParser.parse must not raise and must emit >=1 non-empty display + a result."""
    parser = StreamParser()
    non_empty_displays = 0
    had_result = False
    for raw_line in stream_path.read_text().splitlines():
        if not raw_line.strip():
            continue
        display, result = parser.parse(raw_line)
        if display:
            non_empty_displays += 1
        if result is not None:
            had_result = True
    assert non_empty_displays > 0, (
        f"{stream_path.name}: parser produced no display text — sample is empty or "
        f"parser stopped recognizing assistant/user/result event types."
    )
    assert had_result, (
        f"{stream_path.name}: no final result event — sample is truncated or the "
        f"Claude stream-json schema dropped the result event type."
    )


def test_stream_samples_directory_not_empty() -> None:
    """A trust gate with zero samples is a silent pass — guard against that."""
    assert _list_streams(), f"{_STREAM_DIR} has no *.jsonl samples; seed at least one."
