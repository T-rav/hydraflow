"""Requirement-ID threading helpers (CH-5, issue #9733).

A requirement ID is declared on an issue in one of two ways:

- a ``req:<id>`` label, or
- a ``Req-ID: <id>`` line in the issue body.

The ID is optional everywhere except for issues that fall into the
*regulated* change class — a config-declared label set
(:attr:`config.HydraFlowConfig.regulated_labels`) that defaults to empty,
so nothing is regulated until an operator opts labels in.

Downstream carriers re-derive the ID from the issue itself (labels + body)
via :func:`extract_req_id` rather than persisting it in ``state.json``:
the label state machine only swaps ``hydraflow-*`` state labels and never
rewrites issue bodies, so both declaration forms survive every
plan → ready → review → fixed round trip, process restarts, and HITL
state resets — none of which is true for local state.

Enforcement is a ratchet, not a gate: the traceability matrix
(``docs/arch/generated/traceability_matrix.md``) reports untraced work and
the ``traceability`` disturbance dimension pins the untraced fraction so it
may only shrink.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REQ_LABEL_PREFIX = "req:"
REQ_TRAILER_KEY = "Req-ID"

# IDs: alphanumeric start, then a bounded run of word/dot/slash/dash chars.
# Bounded so a malformed label or body line can't smuggle prose into
# commit trailers or the generated matrix.
_REQ_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,63}$")

# `Req-ID: <id>` on its own line anywhere in the issue body.
_BODY_FIELD_RE = re.compile(
    r"^\s*Req-ID:[ \t]*(?P<req_id>\S+)[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def normalize_req_id(raw: str | None) -> str | None:
    """Return the stripped requirement ID, or ``None`` if invalid."""
    if raw is None:
        return None
    candidate = raw.strip()
    if not _REQ_ID_RE.match(candidate):
        return None
    return candidate


def extract_req_id(*, labels: Iterable[str], body: str = "") -> str | None:
    """Extract the requirement ID from issue labels and/or body.

    A ``req:<id>`` label wins over a ``Req-ID:`` body line so that
    label-driven tooling (the visible, queryable form) stays authoritative.
    Returns ``None`` when no valid ID is declared.
    """
    for label in labels:
        if label.lower().startswith(REQ_LABEL_PREFIX):
            req_id = normalize_req_id(label[len(REQ_LABEL_PREFIX) :])
            if req_id is not None:
                return req_id
    match = _BODY_FIELD_RE.search(body or "")
    if match:
        return normalize_req_id(match.group("req_id"))
    return None


def req_trailer(req_id: str) -> str:
    """Render the git-trailer form of a requirement ID."""
    return f"{REQ_TRAILER_KEY}: {req_id}"


def append_req_trailer(text: str, req_id: str | None) -> str:
    """Append a ``Req-ID:`` trailer to *text* (commit message or PR body).

    No-op when *req_id* is ``None`` or the trailer is already present, so
    callers can apply it unconditionally.
    """
    if not req_id:
        return text
    trailer = req_trailer(req_id)
    if trailer in text:
        return text
    base = text.rstrip("\n")
    if not base:
        return trailer
    return f"{base}\n\n{trailer}"


def is_regulated(labels: Iterable[str], regulated_labels: Iterable[str]) -> bool:
    """True when any issue label falls in the regulated change class.

    Matching is case-insensitive (GitHub label names are case-preserving
    but case-insensitive on lookup). An empty regulated class — the
    default — matches nothing.
    """
    regulated = {
        label.strip().lower() for label in regulated_labels if label and label.strip()
    }
    if not regulated:
        return False
    return any(label.lower() in regulated for label in labels)


def missing_required_req_id(
    *,
    labels: Iterable[str],
    body: str = "",
    regulated_labels: Iterable[str],
) -> bool:
    """True when the issue is regulated but declares no requirement ID."""
    labels = list(labels)
    if not is_regulated(labels, regulated_labels):
        return False
    return extract_req_id(labels=labels, body=body) is None
