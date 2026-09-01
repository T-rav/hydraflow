"""Did a backend's tool call fail? Read every dialect we can enumerate.

`TraceCollector` captured tool errors for the **Claude** backend only (#11887).
Pi and Codex spans carried none: `_handle_pi_tool_end` flipped a span to
``succeeded=True`` on any completion event and read the body for nothing but
``invocationId``, and `_handle_codex_item` had no completion branch at all, so
a Codex span stayed ``succeeded=False, duration_ms=0`` forever — "never
closed", not "failed". `ToolCallSpan.succeeded` therefore meant a different
thing per backend, and nothing downstream could read it.

**Why this is not the sentinel #11889 warned about.** That issue is right that
there is no authoritative Pi/Codex error shape in-repo — `_parse_pi_tool_end`
reads only ``result``, `_parse_codex_item` reads only ``type``/``text``, and
`tests/fixtures/stream_json/` holds Claude samples and nothing else — and that
guessing ONE field name would ship a marker that silently never matches.

The answer is not to guess one. It is to read the whole enumerable space and
to make a miss *observable*: a payload carrying none of these markers is
reported as **unknown**, not as success. A single guessed field fails silently;
a set that returns "I did not recognise this" fails loudly, and the loudness is
what a captured fixture then resolves.

If a real fixture reveals a marker missing here, add it — this table is the
guess, and it is deliberately the only one.
"""

from __future__ import annotations

from typing import Any

#: Truthy in these means failure.
_TRUTHY_FAILURE_KEYS = ("isError", "is_error")
#: Falsey in these means failure (present-and-false, never merely absent).
_FALSEY_FAILURE_KEYS = ("success", "ok")
#: A string status in this set means failure.
_FAILURE_STATUSES = frozenset({"error", "failed", "failure"})
#: Keys whose string value is compared against `_FAILURE_STATUSES`.
_STATUS_KEYS = ("status", "state", "outcome")
#: A non-zero integer in these means failure.
_EXIT_CODE_KEYS = ("exitCode", "exit_code")
#: Carries the error text directly.
_ERROR_TEXT_KEYS = ("error",)
#: Where a nested payload hides.
_NESTED_KEYS = ("result", "output", "item")

_MAX_ERROR_CHARS = 2000
_UNKNOWN = "(no error text)"


def _text(value: Any) -> str:
    """Best-effort error text, never empty."""
    if isinstance(value, dict):
        for key in ("message", "error", "content", "output", "text"):
            if value.get(key):
                return _text(value[key])
        return _UNKNOWN
    rendered = str(value).strip()
    return rendered[:_MAX_ERROR_CHARS] or _UNKNOWN


def _failure_in(payload: dict[str, Any]) -> tuple[bool, str] | None:
    """``(True, text)`` if this level carries a failure marker, else None."""
    for key in _TRUTHY_FAILURE_KEYS:
        if payload.get(key):
            return True, _text(payload.get("error") or payload.get("result") or payload)
    for key in _FALSEY_FAILURE_KEYS:
        # `is False` and not falsiness: an ABSENT key must never read as
        # failure, and `0`/`""` are not the signal either.
        if payload.get(key) is False:
            return True, _text(payload.get("error") or payload.get("result") or payload)
    for key in _STATUS_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.lower() in _FAILURE_STATUSES:
            return True, _text(
                payload.get("error")
                or payload.get("result")
                or payload.get("output")
                or payload
            )
    for key in _EXIT_CODE_KEYS:
        value = payload.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value != 0:
            return True, _text(
                payload.get("result") or payload.get("aggregated_output") or payload
            )
    for key in _ERROR_TEXT_KEYS:
        if payload.get(key):
            return True, _text(payload[key])
    return None


def read_failure(payload: dict[str, Any]) -> str | None:
    """Error text if *payload* signals a failed tool call, else None.

    Checks this level then one nesting down (`result`, `output`, `item`),
    because every dialect observed in the wild puts the marker in one of those
    two places. Deeper nesting is not searched: an unbounded walk would start
    matching unrelated fields, and a false "failed" is worse than an unknown.
    """
    if not isinstance(payload, dict):
        return None
    found = _failure_in(payload)
    if found is not None:
        return found[1]
    for key in _NESTED_KEYS:
        nested = payload.get(key)
        if isinstance(nested, dict):
            found = _failure_in(nested)
            if found is not None:
                return found[1]
    return None


def looks_like_success(payload: dict[str, Any]) -> bool:
    """True when *payload* positively says the call succeeded.

    Distinct from "not a failure": absence of a marker is UNKNOWN, and the
    caller decides what to do with that. Keeping the third state is the whole
    reason this module is not a boolean.
    """
    if not isinstance(payload, dict):
        return False
    for level in (payload, *(payload.get(k) for k in _NESTED_KEYS)):
        if not isinstance(level, dict):
            continue
        for key in _FALSEY_FAILURE_KEYS:
            if level.get(key) is True:
                return True
        for key in _STATUS_KEYS:
            value = level.get(key)
            if isinstance(value, str) and value.lower() in {
                "completed",
                "success",
                "ok",
            }:
                return True
        for key in _EXIT_CODE_KEYS:
            if level.get(key) == 0:
                return True
    return False
