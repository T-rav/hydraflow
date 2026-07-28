"""Operator-facing escape resolution — the trigger surface for the ledger (#10574).

``EscapeLedger.append_resolution`` (``escape.ledger``) is the sanctioned way for
a human to close out a HITL escape by naming its encoding, but before this module
it had ZERO non-test callers: no CLI, no dashboard action, no loop path. Every
``escape-ledger`` HITL issue asked a human to "point at the encoding" with no
mechanism to record that answer, so ``encoded_as`` stayed ``none-yet`` forever
and the aging surface re-fired.

This is the thin, pure service the operator entry points invoke — the CLI
(``scripts/resolve_escape.py``) and any future dashboard action delegate here
rather than each re-deriving the ledger path, re-validating the encoding, and
re-wrapping ``append_resolution``. It is filesystem-only (append-only JSONL, no
git / gh / subprocess), so no Port abstraction is needed. Recording a resolution
row here is exactly the signal ``EscapeLedgerLoop._reconcile_surfaced_issues``
(#10577) reads to close the stranded HITL issue.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from escape.ledger import ESCAPE_LEDGER_FILENAME, EscapeLedger
from escape.models import EncodedAs, EscapeRecord

if TYPE_CHECKING:
    from config import HydraFlowConfig

#: Encodings a human may name to CLOSE OUT an escape. Deliberately EXCLUDES
#: ``none-yet`` — that is the "unresolved" sentinel the ledger starts a row at
#: and the aging surface fires on, never a resolution a human selects. Mirrors
#: ``escape.models.EncodedAs`` minus the sentinel; a resolution that named
#: ``none-yet`` would be a no-op that silently left the finding open.
VALID_ENCODINGS: tuple[EncodedAs, ...] = (
    "regression-test",
    "stored-lesson",
    "detector",
    "adr",
)

#: Confidence levels a human may confirm an attribution at (``escape.models``
#: ``AttributionConfidence``). Bumping off ``low`` is what answers a
#: ``low-confidence`` surfacing in the reconcile pass (#10577).
VALID_CONFIDENCES: tuple[str, ...] = ("high", "medium", "low")


class EscapeResolveError(RuntimeError):
    """Base for operator-input errors so a CLI can catch one type and exit 2."""


class InvalidEncodingError(EscapeResolveError):
    """*encoded_as* is not one of ``VALID_ENCODINGS`` (``none-yet`` included)."""


class InvalidConfidenceError(EscapeResolveError):
    """*attribution_confidence* is not one of ``VALID_CONFIDENCES``."""


class UnknownEscapeIdError(EscapeResolveError):
    """No ledger row exists for the given *escape_id* — nothing to resolve."""


class NoResolutionFieldsError(EscapeResolveError):
    """Neither *encoded_as* nor *attribution_confidence* was supplied.

    Both are optional individually (#10747 — a human may confirm confidence
    alone, or point at an encoding alone), but a resolution naming NEITHER
    would append a no-op row and silently leave the finding open.
    """


class UnanswerableLowConfidenceError(EscapeResolveError):
    """*attribution_confidence="low"* was supplied with no *encoded_as* (#10747).

    A low-confidence surfacing's answered predicate is
    ``attribution_confidence != "low"`` (``escape_ledger_loop._surfacing_answered``).
    Recording ``attribution_confidence="low"`` without also naming an encoding
    would append a row that can never satisfy that predicate — and because
    surfacing is a one-shot budget per (id, reason), the HITL issue would be
    silently stranded open forever with no way to re-fire. Name an encoding
    with ``encoded_as``, or bump confidence off ``"low"``.
    """


def default_ledger_path(config: HydraFlowConfig) -> Path:
    """The repo-scoped escape ledger path — the single source of truth (#10578).

    Resolves through ``config.diagnostics_dir`` + ``ESCAPE_LEDGER_FILENAME`` so
    the operator's default invocation targets the SAME file the loop writes,
    rather than re-hardcoding the literal (the concept-scatter smell #10104
    flags).
    """
    return config.diagnostics_dir / ESCAPE_LEDGER_FILENAME


def resolve_escape(
    escape_id: str,
    encoded_as: str | None = None,
    *,
    ledger_path: Path,
    attribution_confidence: str | None = None,
    notes: str | None = None,
) -> EscapeRecord:
    """Record a human resolution for *escape_id*, returning the new row.

    *encoded_as* and *attribution_confidence* are each independently optional
    (#10747) — a human may confirm attribution confidence alone (answering a
    low-confidence surfacing without yet knowing the encoding), or point at an
    encoding alone, but naming NEITHER would append a no-op row and silently
    leave the finding open, so that combination is rejected up front.

    Validates *encoded_as* (when given) against ``VALID_ENCODINGS`` (``none-yet``
    is rejected — it is the unresolved sentinel, not a selectable encoding) and
    *attribution_confidence* (when given) against ``VALID_CONFIDENCES`` BEFORE
    touching the ledger, so a bad value never appends a garbage row. Then
    delegates to the append-only ``EscapeLedger.append_resolution``: a NEW
    superseding row is appended sharing the original id, never a rewrite.

    Raises ``NoResolutionFieldsError`` when neither field is given,
    ``UnanswerableLowConfidenceError`` when *attribution_confidence* is
    ``"low"`` with no *encoded_as* (that combination can never answer a
    low-confidence surfacing and would silently strand it — #10747),
    ``InvalidEncodingError`` / ``InvalidConfidenceError`` on bad input, and
    ``UnknownEscapeIdError`` when no row exists for *escape_id*.
    """
    if encoded_as is None and attribution_confidence is None:
        raise NoResolutionFieldsError(
            "at least one of encoded_as or attribution_confidence must be "
            "given — naming neither would record nothing"
        )
    if encoded_as is not None and encoded_as not in VALID_ENCODINGS:
        raise InvalidEncodingError(
            f"encoded_as must be one of {', '.join(VALID_ENCODINGS)} "
            f"(got {encoded_as!r}); 'none-yet' is the unresolved sentinel, "
            "not a resolution"
        )
    if (
        attribution_confidence is not None
        and attribution_confidence not in VALID_CONFIDENCES
    ):
        raise InvalidConfidenceError(
            f"attribution_confidence must be one of {', '.join(VALID_CONFIDENCES)} "
            f"(got {attribution_confidence!r})"
        )
    if encoded_as is None and attribution_confidence == "low":
        raise UnanswerableLowConfidenceError(
            "attribution_confidence='low' alone can never answer a "
            "low-confidence surfacing and would silently strand the HITL "
            "issue — name an encoding with encoded_as, or bump confidence "
            "off 'low'"
        )
    ledger = EscapeLedger(Path(ledger_path))
    record = ledger.append_resolution(
        escape_id,
        encoded_as=encoded_as,
        attribution_confidence=attribution_confidence,
        notes=notes,
    )
    if record is None:
        raise UnknownEscapeIdError(
            f"no escape-ledger row found for id {escape_id!r} in {ledger_path}"
        )
    return record


def list_unresolved(ledger_path: Path) -> list[EscapeRecord]:
    """The current ``none-yet`` rows — the escapes still awaiting a resolution.

    Reads the collapsed one-row-per-id view (``read_latest``) so a row already
    resolved by an appended superseding line is excluded; the operator sees only
    what still needs a human encoding.
    """
    return [
        record
        for record in EscapeLedger(Path(ledger_path)).read_latest()
        if record.encoded_as == "none-yet"
    ]
