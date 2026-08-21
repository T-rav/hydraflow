"""Model-backed SpecReviewer (#10830 phase 2) — the injected contradiction seam.

Phase 1 shipped the deterministic half of the spec-intake gate (falsifiability
metric + max-severity aggregation + ledger) with :class:`spec_intake_gate.
SpecReviewer` as an empty Protocol seam. This module is the seam's production
implementation: one adversarial LLM read of a document performing the three
contradiction checks (internal / corpus / code) plus divergence classification
and unstated-assumption surfacing, returning a structured
:class:`spec_intake_gate.SpecReview`.

Design rulings honored (the phase-1 module's docstring is the authority):

- **Cause control, not error control** (Conant & Ashby, the #10830 warrant):
  this reads the *spec* before it becomes a setpoint — a crude check on inputs
  beats a sophisticated check on outputs.
- **Proposal-only:** the reviewer quotes offending spans verbatim; it never
  edits the document.
- **Two divergence classes, never one score:** contradicted-by-fact is a
  defect; diverges-from-practice is where the novel material lives.
- **Degrade to the deterministic floor:** a spawn or parse failure returns an
  EMPTY review with a warning — the falsifiability metric still lands, and a
  broken reviewer can never block intake (advisory instrument, per phase 1).

Invocation is ON-DEMAND (``make spec-intake``), not a loop — the #11055
right-sizing precedent: spec arrivals are rare human events, and a background
loop polling for them would cost the full new-loop ratchet set for no signal.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import Callable

from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from runner_utils import run_lightweight_agent
from spec_intake_gate import (
    Contradiction,
    ContradictionKind,
    Divergence,
    DivergenceKind,
    LoadBearingAssertion,
    Severity,
    SpecReview,
)

logger = logging.getLogger("hydraflow.spec_reviewer")

#: Hard bound on the one-shot review call (seconds) — matches the sampled-audit
#: adversarial-read tier.
SPEC_REVIEW_TIMEOUT_S = 300

#: How much of the document the reviewer is shown (chars) — bounded so a huge
#: spec cannot blow the prompt budget; the deterministic metric still sees all.
_DOC_CONTEXT_CHARS = 24_000

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_spec_review_prompt(document: str, *, subject_id: str) -> str:
    """The adversarial intake read: three contradiction checks + assumptions."""
    return (
        f"You are stress-testing a specification ({subject_id}) BEFORE it "
        "becomes a target anyone builds against. Read it adversarially "
        "against your knowledge of this repository.\n\n"
        "Reason first — work through the document's claims before concluding. "
        "Then report findings in FOUR separate categories:\n\n"
        "1. contradictions — three distinct kinds, reported separately:\n"
        '   - "internal": the document contradicts itself;\n'
        '   - "corpus": it conflicts with a live ADR or spec (semantic '
        "conflict, not wording drift);\n"
        '   - "code": it asserts behaviour the repository does not have.\n'
        "2. divergences — where it departs from established practice, in TWO "
        "classes that must never be merged:\n"
        '   - "contradicted_by_fact": a defect;\n'
        '   - "diverges_from_practice": NOT a defect — novel material lives '
        "here; report it so it feeds the lineage pass, never to punish it.\n"
        "3. load_bearing_assertions — claims the implementation would depend "
        "on, each with a severity reflecting the blast radius if wrong.\n"
        "4. unstated_assumptions — what the document silently presumes.\n\n"
        "Quote offending spans VERBATIM (never paraphrase — the quote is the "
        "proposal-only write surface). Severities: info|low|medium|high.\n\n"
        "Respond with STRICT JSON, nothing else:\n"
        '{"contradictions":[{"kind":"internal"|"corpus"|"code",'
        '"severity":"info"|"low"|"medium"|"high","quote":str,"explanation":str}],'
        '"divergences":[{"kind":"contradicted_by_fact"|"diverges_from_practice",'
        '"quote":str,"explanation":str}],'
        '"load_bearing_assertions":[{"claim":str,'
        '"severity":"info"|"low"|"medium"|"high"}],'
        '"unstated_assumptions":[str]}\n\n'
        "## Document\n" + document[:_DOC_CONTEXT_CHARS]
    )


def _severity(raw: object) -> Severity | None:
    try:
        return Severity(str(raw))
    except ValueError:
        return None


def parse_spec_review(payload: str) -> SpecReview:
    """Parse the reviewer's JSON into a SpecReview; malformed findings are
    dropped individually with a warning, and an unparseable payload degrades
    to the EMPTY review — the deterministic falsifiability floor still lands.
    """
    match = _JSON_BLOCK_RE.search(payload)
    if match is None:
        logger.warning("spec_reviewer: no JSON block in payload — empty review")
        return SpecReview()
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        logger.warning("spec_reviewer: malformed JSON payload — empty review")
        return SpecReview()
    if not isinstance(data, dict):
        return SpecReview()

    contradictions: list[Contradiction] = []
    for raw in data.get("contradictions") or []:
        if not isinstance(raw, dict):
            continue
        severity = _severity(raw.get("severity"))
        try:
            kind = ContradictionKind(str(raw.get("kind")))
        except ValueError:
            kind = None
        if kind is None or severity is None:
            logger.warning("spec_reviewer: dropped malformed contradiction %r", raw)
            continue
        contradictions.append(
            Contradiction(
                kind=kind,
                severity=severity,
                quote=str(raw.get("quote", "")),
                explanation=str(raw.get("explanation", "")),
            )
        )

    divergences: list[Divergence] = []
    for raw in data.get("divergences") or []:
        if not isinstance(raw, dict):
            continue
        try:
            dkind = DivergenceKind(str(raw.get("kind")))
        except ValueError:
            logger.warning("spec_reviewer: dropped malformed divergence %r", raw)
            continue
        divergences.append(
            Divergence(
                kind=dkind,
                quote=str(raw.get("quote", "")),
                explanation=str(raw.get("explanation", "")),
            )
        )

    assertions: list[LoadBearingAssertion] = []
    for raw in data.get("load_bearing_assertions") or []:
        if not isinstance(raw, dict):
            continue
        severity = _severity(raw.get("severity"))
        claim = str(raw.get("claim", "")).strip()
        if severity is None or not claim:
            logger.warning("spec_reviewer: dropped malformed assertion %r", raw)
            continue
        assertions.append(LoadBearingAssertion(claim=claim, severity=severity))

    assumptions = tuple(
        str(a).strip()
        for a in (data.get("unstated_assumptions") or [])
        if str(a).strip()
    )

    return SpecReview(
        contradictions=tuple(contradictions),
        divergences=tuple(divergences),
        load_bearing_assertions=tuple(assertions),
        unstated_assumptions=assumptions,
    )


class CLISpecReviewer:
    """Production reviewer: one-shot completion behind an injectable seam.

    ``complete`` maps prompt → raw payload; tests inject a fake, and
    :func:`cli_spec_reviewer` builds the production spawn. Any completion
    failure degrades to the empty review (never raises into intake).
    """

    def __init__(self, complete: Callable[[str], str]) -> None:
        self._complete = complete

    def review(self, document: str, *, subject_id: str) -> SpecReview:
        prompt = build_spec_review_prompt(document, subject_id=subject_id)
        try:
            payload = self._complete(prompt)
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning(
                "spec_reviewer: completion failed — empty review", exc_info=True
            )
            return SpecReview()
        return parse_spec_review(payload)


def cli_spec_reviewer(config, model: str) -> CLISpecReviewer:
    """The production seam: credit-aware, telemetried one-shot spawn (mirrors
    sampled_audit's ``_CLIAuditLLM``)."""

    def _complete(prompt: str) -> str:
        result = asyncio.run(
            run_lightweight_agent(
                runner=get_default_runner(),
                config=config,
                tool="claude",
                model=model,
                prompt=prompt,
                source="spec_intake_review",
                timeout=float(SPEC_REVIEW_TIMEOUT_S),
                issue_labels=(),
                provider="claude",
            )
        )
        if result.returncode != 0:
            msg = f"spec review LLM failed (rc={result.returncode}): {result.stderr[:200]}"
            raise RuntimeError(msg)
        return result.stdout

    return CLISpecReviewer(_complete)
