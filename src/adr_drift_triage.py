"""Pure TRIAGE-step data model + text-shaping helpers for AdrDriftResolverLoop.

DETECT → **TRIAGE** → RESOLVE → FAIL-CLOSED (#9976). AdrTouchpointAuditorLoop
(ADR-0056) stays a pure detector — it files one ``hydraflow-adr-drift``
rollup per ADR and re-detects each tick, but never judges whether the
drift is REAL. This module supplies the pure pieces of the judgment step
so the resolver loop (``adr_drift_resolver_loop.py``) and its LLM wrapper
(``adr_drift_triage_llm.py``) can both depend on something with no I/O and
no side effects — trivially unit-testable, no fakes required.

No dependency on ``adr_drift.py`` or ``adr_touchpoint_auditor_loop.py``:
this module (and everything downstream of it) is deliberately a SEPARATE
subsystem from the auditor's detection machinery, per the issue's
"leave the auditor as a pure detector" constraint.
"""

from __future__ import annotations

import re
from enum import StrEnum

from pydantic import BaseModel, Field


class DriftClassification(StrEnum):
    """Outcome of triaging one ADR-drift rollup against its cited PR diff.

    Five values, closed set — the LLM's structured output MUST be one of
    these (an unparseable/off-list value fails Pydantic validation, which
    the caller treats as a triage error, never as an implicit CONSISTENT).
    """

    #: The cited module's change is consistent with the ADR's Decision/
    #: Context — a false-positive drift signal (the ~70% common case: a
    #: caller or co-tenant changed, not the decision itself).
    CONSISTENT = "consistent"
    #: The change genuinely contradicts or supersedes the ADR's Decision —
    #: the ADR text itself needs editing to match reality.
    REAL_DRIFT = "real_drift"
    #: The ADR's citation is broader than what it actually governs (e.g. a
    #: bare file-level citation on a module the ADR only owns one symbol
    #: of) — the FIX is narrowing the citation, not the code.
    OVER_CITATION = "over_citation"
    #: The cited file/symbol no longer exists or no longer relates to the
    #: ADR's decision (e.g. renamed, extracted elsewhere) — the citation
    #: itself is stale and should be removed or repointed.
    DEAD_CITATION = "dead_citation"
    #: The triage model could not confidently place the drift in any of
    #: the above buckets from the evidence given — always escalates to
    #: HITL, never auto-resolved either way (FAIL-CLOSED).
    LOW_CONFIDENCE = "low_confidence"


#: Classifications that hand off to the normal `hydraflow-find` discovery
#: pipeline for an ADR-text edit (RESOLVE step, non-CONSISTENT branch).
#: CONSISTENT resolves by closing; LOW_CONFIDENCE resolves by escalating —
#: neither belongs in this set.
RELABEL_CLASSIFICATIONS: frozenset[DriftClassification] = frozenset(
    {
        DriftClassification.REAL_DRIFT,
        DriftClassification.OVER_CITATION,
        DriftClassification.DEAD_CITATION,
    }
)


class TriageVerdict(BaseModel):
    """Structured TRIAGE output. FAIL-CLOSED: only ``CONSISTENT`` auto-closes.

    Every other classification (including a triage-call error, handled
    upstream of this model) leaves the rollup open for a human or the
    normal pipeline to act on — see the module docstring's DETECT → TRIAGE
    → RESOLVE → FAIL-CLOSED pipeline.
    """

    classification: DriftClassification
    rationale: str = Field(
        min_length=1,
        description=(
            "One-line, specific explanation. For CONSISTENT: the audit-close "
            "comment (why the cited change doesn't contradict the ADR). For "
            "REAL_DRIFT/OVER_CITATION/DEAD_CITATION: the concrete ADR-edit "
            "brief — what to change. For LOW_CONFIDENCE: what made the "
            "evidence ambiguous."
        ),
    )
    section: str = Field(
        default="",
        description=(
            "Which ADR section needs editing ('Decision', 'Context', "
            "'Related', ...). Required (non-empty) for REAL_DRIFT/"
            "OVER_CITATION/DEAD_CITATION; empty for CONSISTENT/LOW_CONFIDENCE."
        ),
    )


# Section headings are matched the same way ``adr_index._CONTEXT_RE`` does
# (## heading, blank-line-terminated body) but widened to capture the WHOLE
# section body (not just the first paragraph) and to also capture Decision —
# adr_index.ADR only carries a 300-char Context summary, which is too thin
# for the triage LLM to judge consistency against.
_CONTEXT_SECTION_RE = re.compile(r"##\s+Context\s*\n+(.+?)(?=\n##\s|\Z)", re.DOTALL)
_DECISION_SECTION_RE = re.compile(r"##\s+Decision\s*\n+(.+?)(?=\n##\s|\Z)", re.DOTALL)

#: Hard cap on how much ADR text rides in the triage prompt. Generous
#: enough for every real ADR's Context+Decision (the longest in this repo
#: is a few KB); a defensive ceiling against a pathological ADR file.
_MAX_ADR_TEXT_CHARS = 6_000

#: Hard cap on the (already module-filtered) PR diff text. Diffs can be
#: large; the triage question is "does this diff contradict the ADR", which
#: needs the actual hunks, not the whole PR — filtering by cited path
#: (:func:`filter_diff_to_paths`) already does most of the narrowing.
_MAX_DIFF_TEXT_CHARS = 8_000


def extract_decision_context(adr_markdown: str) -> str:
    """Return the ADR's Context + Decision sections, concatenated.

    Falls back to the raw text (bounded) when neither heading is found —
    a handful of ADRs don't follow the Context/Decision convention exactly
    (e.g. status-only stubs); better to over-supply than to hand the
    triage LLM nothing to judge against.
    """
    parts: list[str] = []
    ctx = _CONTEXT_SECTION_RE.search(adr_markdown)
    if ctx:
        parts.append("## Context\n" + ctx.group(1).strip())
    dec = _DECISION_SECTION_RE.search(adr_markdown)
    if dec:
        parts.append("## Decision\n" + dec.group(1).strip())
    text = "\n\n".join(parts) if parts else adr_markdown
    return text[:_MAX_ADR_TEXT_CHARS]


_DIFF_HEADER_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.MULTILINE)


def filter_diff_to_paths(diff_text: str, paths: frozenset[str] | set[str]) -> str:
    """Return only the per-file hunks of *diff_text* touching *paths*.

    ``diff_text`` is the standard ``git``/``gh pr diff`` unified-diff shape:
    zero or more ``diff --git a/X b/Y`` blocks concatenated. Splits on those
    headers and keeps a block when either its ``a/`` or ``b/`` path (a
    rename's old/new name can differ) is in *paths*.

    Scopes the triage prompt to the ADR's actually-cited module(s) instead
    of the whole PR — a PR that touches 20 files but only drifts one cited
    module shouldn't spend the triage LLM's context budget on the other 19.

    Falls back to the full (bounded) *diff_text* when no block matches any
    path — e.g. the cited path was deleted/renamed in a way this pass
    doesn't recognize, or *diff_text* is a test stub with no real headers.
    Better to over-supply than to hand the triage LLM an empty diff, which
    would make every judgment indistinguishable from "no evidence".
    """
    if not paths:
        return diff_text[:_MAX_DIFF_TEXT_CHARS]

    headers = list(_DIFF_HEADER_RE.finditer(diff_text))
    if not headers:
        return diff_text[:_MAX_DIFF_TEXT_CHARS]

    blocks: list[str] = []
    for i, match in enumerate(headers):
        start = match.start()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(diff_text)
        a_path, b_path = match.group(1), match.group(2)
        if a_path in paths or b_path in paths:
            blocks.append(diff_text[start:end])

    if not blocks:
        return diff_text[:_MAX_DIFF_TEXT_CHARS]
    return "".join(blocks)[:_MAX_DIFF_TEXT_CHARS]
