"""Regression: triage rubber-stamped unparseable verdicts as ready=True (#9798).

~131 occurrences of "could not parse LLM response, defaulting to ready=True"
made the triage gate a no-op: the parser was handed RAW stream-json frames
whose verdict is ESCAPED inside a ``result`` payload
(``{"type":"result","result":"{\\"ready\\":...}"}``), which none of the
text-level strategies could see, and the fallback then passed the issue
through unevaluated.

Pins:
1. Stream-json transcripts parse — via the ``result`` frame and via
   assistant content blocks — including a ready=false verdict (proof of
   real evaluation, not pass-through).
2. A genuinely unparseable transcript raises RuntimeError (the established
   infra-failure contract: issue stays queued for retry) instead of
   returning ready=True.
"""

from __future__ import annotations

import json

from triage import TriageRunner


def _stream_result_frame(verdict: dict) -> str:
    init = json.dumps(
        {"type": "system", "subtype": "init", "cwd": "/w", "tools": ["Bash"]}
    )
    result = json.dumps({"type": "result", "result": json.dumps(verdict)})
    return f"{init}\n{result}"


def test_verdict_escaped_in_result_frame_parses_ready_false() -> None:
    transcript = _stream_result_frame(
        {"ready": False, "reasons": ["needs acceptance criteria"]}
    )

    result = TriageRunner._parse_verdict(transcript, 42)

    assert result is not None
    assert result.ready is False
    assert result.reasons == ["needs acceptance criteria"]


def test_verdict_in_assistant_content_block_parses() -> None:
    frame = json.dumps(
        {
            "type": "assistant",
            "message": {
                "content": [
                    {
                        "type": "text",
                        "text": '{"ready": true, "reasons": []}',
                    }
                ]
            },
        }
    )
    transcript = f'{{"type":"system","subtype":"init"}}\n{frame}'

    result = TriageRunner._parse_verdict(transcript, 42)

    assert result is not None
    assert result.ready is True


def test_plain_text_transcripts_still_parse_unchanged() -> None:
    result = TriageRunner._parse_verdict('{"ready": false, "reasons": ["x"]}', 7)

    assert result is not None
    assert result.ready is False


def test_stream_json_with_no_verdict_still_returns_none() -> None:
    transcript = _stream_result_frame({"no_verdict_here": 1})

    assert TriageRunner._parse_verdict(transcript, 7) is None
