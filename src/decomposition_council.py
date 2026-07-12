"""DecompositionCouncil — LLM decision-maker for decompose-to-converge (ADR-0105).

Genuinely two-pass, per ADR-0105 §Decision(2): two SEPARATE
:func:`runner_utils.run_lightweight_agent` calls, not one completion
role-playing both phases. A single completion that both proposes a split and
"validates" it just rationalizes its own proposal -- that defeats the point
of a council, which is an *independent* second look:

1. **Direction** (:meth:`_run_direction`) -- proposes ONE candidate split
   (epic + children) from distinct lenses (architectural/layer boundaries;
   isolate-the-failing-part; vertical independently-shippable slices), given
   ``task``, ``stall_context``, ``doc_context``, ``depth``. Direction does
   not decide ``should_decompose`` -- it only authors a candidate.
2. **Validation** (:meth:`_run_validation`) -- a SEPARATE seam call, seeded
   with the direction pass's proposed split (and no memory of how it was
   produced), that adversarially critiques it: are the children
   independently-shippable, non-overlapping, genuinely more tractable than
   the parent (not clones), and architecture-consistent? It returns
   APPROVE (-> ``should_decompose=True``, using the direction's children)
   or REVISE/REJECT (-> ``should_decompose=False``), plus a self-reported
   ``confidence``. Validation is the sole owner of ``should_decompose`` and
   ``confidence`` -- it can overturn a direction pass that proposed a split.

Both calls route through the shared :func:`runner_utils.run_lightweight_agent`
seam (CH-6 gated + telemetried) using the same ADR-review provider dial and
``source="decomposition_council"`` (P1: reuse, no new knobs).

Confidence-gated retry (mirrors ``preflight/agent.py``'s ``_derive_status``
retry semantics, ADR-0084): a *decline* (``should_decompose=False``) at
anything less than ``high`` confidence -- including a garbled/unparseable
reply from either pass -- is treated as not-yet-final, so the ENTIRE PAIR
(direction + validation) is re-run once before the decline is accepted.
Re-running the pair (rather than validation alone) gives direction a chance
to propose a better candidate on retry, instead of asking validation to
re-judge the same flawed proposal. A *high*-confidence decline is final
immediately, and any accept is always final (the retry rule only guards
against a premature "no" from a bad first pass).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from exception_classify import reraise_on_credit_or_bug
from models import EpicDecompResult, NewIssueSpec

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from execution import SubprocessRunner
    from models import Task

logger = logging.getLogger("hydraflow.decomposition_council")

# Only an exact "high" self-report short-circuits the retry-on-decline rule;
# "medium"/"low"/garbled/missing all count as not-yet-confident.
_HIGH_CONFIDENCE = "high"

# Validation's decision maps 1:1 onto should_decompose: only an explicit
# "approve" counts as an accept. "revise"/"reject"/anything else declines.
_APPROVE = "approve"


@dataclass(frozen=True)
class _DirectionProposal:
    """The direction pass's candidate split, handed to validation to judge."""

    epic_title: str
    epic_body: str
    children: list[NewIssueSpec]
    rationale: str


class DecompositionCouncil:
    """Two-pass (direction -> validation) council deciding whether to split a stalled task."""

    def __init__(self, runner: SubprocessRunner, config: HydraFlowConfig) -> None:
        self._runner = runner
        self._config = config

    async def decide(
        self,
        *,
        task: Task,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> EpicDecompResult:
        """Decide whether/how to decompose *task*, retrying once on a weak decline.

        Runs the direction+validation pair once; if it declines
        (``should_decompose=False``) at less than ``high`` confidence,
        re-runs the whole pair one more time and returns that result
        regardless of its confidence (so a second weak decline is still
        accepted as final -- no unbounded retries). An accept, or a
        high-confidence decline, returns immediately after the first pass.
        """
        result = await self._run_council_once(
            task=task, stall_context=stall_context, doc_context=doc_context, depth=depth
        )
        if result.should_decompose or result.confidence == _HIGH_CONFIDENCE:
            return result

        logger.info(
            "Decomposition council: low-confidence decline for #%d "
            "(confidence=%r) -- retrying once",
            task.id,
            result.confidence,
        )
        return await self._run_council_once(
            task=task, stall_context=stall_context, doc_context=doc_context, depth=depth
        )

    async def _run_council_once(
        self,
        *,
        task: Task,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> EpicDecompResult:
        """Run one direction pass then, if it yields a usable candidate, one
        independent validation pass. Two separate seam calls when direction
        succeeds; one call (direction only) when it doesn't -- there is
        nothing sound to validate.
        """
        proposal = await self._run_direction(
            task, stall_context=stall_context, doc_context=doc_context, depth=depth
        )
        if proposal is None:
            return EpicDecompResult(
                should_decompose=False,
                reasoning="Direction phase produced no usable candidate split",
                confidence="low",
            )
        return await self._run_validation(
            task,
            proposal,
            stall_context=stall_context,
            doc_context=doc_context,
            depth=depth,
        )

    async def _run_direction(
        self,
        task: Task,
        *,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> _DirectionProposal | None:
        """Direction pass: propose ONE candidate split. Returns ``None`` if
        the seam produced no output or an unparseable/too-small candidate
        (treated as garbled -- see :meth:`_parse_direction_result`).
        """
        prompt = self._build_direction_prompt(
            task, stall_context=stall_context, doc_context=doc_context, depth=depth
        )
        transcript = await self._execute_council(prompt)
        if transcript is None:
            logger.warning(
                "Decomposition council: direction pass produced no output for #%d",
                task.id,
            )
            return None
        return self._parse_direction_result(transcript)

    async def _run_validation(
        self,
        task: Task,
        proposal: _DirectionProposal,
        *,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> EpicDecompResult:
        """Validation pass: independently critique *proposal* and decide."""
        prompt = self._build_validation_prompt(
            task,
            proposal,
            stall_context=stall_context,
            doc_context=doc_context,
            depth=depth,
        )
        transcript = await self._execute_council(prompt)
        if transcript is None:
            logger.warning(
                "Decomposition council: validation pass produced no output for #%d",
                task.id,
            )
            return EpicDecompResult(
                should_decompose=False,
                reasoning="Validation phase produced no output",
                confidence="low",
            )
        return self._parse_validation_result(transcript, proposal)

    def _build_direction_prompt(
        self,
        task: Task,
        *,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> str:
        """Construct the direction-pass prompt: propose ONE candidate split.

        *stall_context* carries forward why the parent task stalled (from the
        auto-agent preflight loop); *doc_context* is an opaque string a later
        task fills with relevant repo docs/ADR excerpts -- this council only
        needs to inject it, not interpret it.
        """
        body = (task.body or "")[:5000]
        max_depth = self._config.max_decomposition_depth
        return f"""You are the Direction phase of the Decomposition Council for a \
stalled task. A prior autonomous implementation attempt on this task did not \
converge. Your job is ONLY to propose a candidate split into an epic + \
independently implementable child issues -- a separate, independent \
Validation phase will critique your proposal, so do not pre-judge whether it \
will be accepted; just produce your strongest candidate.

## Task #{task.id}

**Title:** {task.title}

**Body:**
{body}

## Why the task stalled

{stall_context}

## Supporting documentation context

{doc_context}

## Decomposition depth

This lineage has already been decomposed {depth} time(s) (max allowed: \
{max_depth}).

## Direction Protocol

Silently consider 2-3 candidate slicings of this work from DISTINCT lenses:
- architectural / layer boundaries
- isolate-the-failing-part (the piece that actually stalled)
- vertical, independently-shippable slices

Weigh the tradeoffs of each candidate, then commit to the single strongest \
one. Propose at least 2 independently implementable children -- each must be \
able to land as its own reviewable PR, and must NOT be a near-duplicate of \
another child.

## Required Output

Return ONLY a JSON object in this exact format (no other text):

```json
{{
  "epic_title": "Epic: ...",
  "epic_body": "## Sub-issues\\n\\n- [ ] Child title 1\\n- [ ] Child title 2",
  "children": [
    {{"title": "Child issue title", "body": "Detailed description..."}},
    {{"title": "Another child", "body": "More details..."}}
  ],
  "rationale": "Which lens(es) you considered and why this candidate is strongest"
}}
```"""

    def _build_validation_prompt(
        self,
        task: Task,
        proposal: _DirectionProposal,
        *,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> str:
        """Construct the validation-pass prompt: adversarially critique
        *proposal*. This is a SEPARATE seam call from direction -- validation
        receives only the proposal's content, not any reasoning trace from
        how direction produced it, so its critique is independent.
        """
        max_depth = self._config.max_decomposition_depth
        children_block = "\n".join(
            f"{i}. **{child.title}**\n   {child.body}"
            for i, child in enumerate(proposal.children, start=1)
        )
        return f"""You are the Validation phase of the Decomposition Council for a \
stalled task. A separate Direction phase (which you do not have access to \
the reasoning of) proposed the candidate split below. Your job is to \
ADVERSARIALLY critique it, independently of whatever reasoning produced it -- \
do not assume it is sound just because it was proposed.

## Task #{task.id}

**Title:** {task.title}

## Why the task stalled

{stall_context}

## Supporting documentation context

{doc_context}

## Decomposition depth

This lineage has already been decomposed {depth} time(s) (max allowed: \
{max_depth}). Weigh further splitting against that budget -- prefer \
REVISE/REJECT once close to the limit unless the split is clearly still \
warranted.

## Proposed split to critique

**Epic:** {proposal.epic_title}

**Rationale given:** {proposal.rationale}

**Children:**
{children_block}

## Validation Protocol

REJECT or REVISE (should_decompose=false) the split if:
- the children are near-duplicate/clone children with no independent value
- the children overlap (not clearly separable work)
- a child is not genuinely more tractable than the parent
- the children could not each land as an independent, reviewable PR
- the split is inconsistent with the repo's architecture (per the docs above)
- the task is actually an atomic, non-decomposable unit of work

Otherwise APPROVE (should_decompose=true).

Rate your confidence in the FINAL decision as "high", "medium", or "low". \
Use "high" only when you are certain -- e.g. clearly duplicative children, \
or a clearly sound and well-separated split. Use "medium" or "low" when the \
call is genuinely close.

## Required Output

Return ONLY a JSON object in this exact format (no other text):

```json
{{
  "decision": "approve",
  "confidence": "high",
  "reasoning": "Why this decomposition makes sense"
}}
```

or

```json
{{
  "decision": "reject",
  "confidence": "high",
  "reasoning": "Why this split is unsound"
}}
```"""

    async def _execute_council(self, prompt: str) -> str | None:
        """Call the configured LLM backend for one council pass (direction
        or validation).

        Reuses the ADR-review provider dial (P1: avoid a new config knob).
        Any failure to reach the seam is a soft failure here (``None`` ->
        treated as a garbled, retryable decline by the caller) EXCEPT a
        credit-exhaustion/auth signal or a likely-bug exception, which
        ``reraise_on_credit_or_bug`` re-raises so it reaches the loop's
        dedicated handler instead of silently burning attempt budget.
        """
        from runner_utils import run_lightweight_agent  # noqa: PLC0415

        try:
            result = await run_lightweight_agent(
                runner=self._runner,
                config=self._config,
                tool=self._config.adr_review_tool,
                model=self._config.adr_review_model,
                provider=self._config.adr_review_provider,
                prompt=prompt,
                source="decomposition_council",
                timeout=self._config.agent_timeout,
            )
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Decomposition council seam call failed: %s", exc)
            return None
        if result.returncode != 0:
            logger.warning(
                "Decomposition council seam call failed (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            return None
        return result.stdout if result.stdout else None

    def _parse_direction_result(self, transcript: str) -> _DirectionProposal | None:
        """Parse the direction pass's JSON candidate into a proposal.

        Unparseable output, or a candidate with fewer than 2 children, is
        treated as garbled and returns ``None`` -- there is nothing sound to
        hand to validation, so the caller declines this pass without
        spending a second seam call on it.
        """
        data = _extract_json_object(transcript, required_key="children")
        if data is None:
            logger.warning(
                "Decomposition council: no parseable JSON candidate in direction transcript"
            )
            return None

        children_raw = data.get("children", [])
        children: list[NewIssueSpec] = []
        if isinstance(children_raw, list):
            for item in children_raw:
                if isinstance(item, dict) and "title" in item:
                    children.append(
                        NewIssueSpec(
                            title=str(item["title"]),
                            body=str(item.get("body", "")),
                        )
                    )

        if len(children) < 2:
            logger.warning(
                "Decomposition council: direction candidate has <2 parsed children -- "
                "treating as garbled"
            )
            return None

        return _DirectionProposal(
            epic_title=str(data.get("epic_title", "")),
            epic_body=str(data.get("epic_body", "")),
            children=children,
            rationale=str(data.get("rationale", "")),
        )

    def _parse_validation_result(
        self, transcript: str, proposal: _DirectionProposal
    ) -> EpicDecompResult:
        """Parse the validation pass's JSON verdict into an ``EpicDecompResult``.

        Validation is the sole owner of ``should_decompose`` and
        ``confidence`` -- an APPROVE carries the direction pass's
        epic/children through; a REVISE/REJECT (or unparseable verdict)
        declines regardless of what was proposed. Unparseable output is
        treated as a garbled low-confidence decline so :meth:`decide`
        retries it once, mirroring how ``preflight/agent.py._derive_status``
        treats a missing/garbled status as ``retry`` rather than a final
        answer.
        """
        data = _extract_json_object(transcript, required_key="decision")
        if data is None:
            logger.warning(
                "Decomposition council: no parseable JSON verdict in validation transcript"
            )
            return EpicDecompResult(
                should_decompose=False,
                reasoning="Failed to parse validation result",
                confidence="low",
            )

        confidence = str(data.get("confidence", "") or "").strip().lower() or "low"
        decision = str(data.get("decision", "") or "").strip().lower()
        reasoning = str(data.get("reasoning", ""))

        if decision != _APPROVE:
            return EpicDecompResult(
                should_decompose=False,
                reasoning=reasoning,
                confidence=confidence,
            )

        return EpicDecompResult(
            should_decompose=True,
            epic_title=proposal.epic_title,
            epic_body=proposal.epic_body,
            children=proposal.children,
            reasoning=reasoning,
            confidence=confidence,
        )


def _extract_json_object(
    transcript: str, *, required_key: str
) -> dict[str, object] | None:
    """Extract a JSON object from *transcript*: direct parse, then code fence.

    Mirrors ``triage.py._parse_decomposition``'s two-strategy approach.
    *required_key* disambiguates which pass's shape is being parsed (e.g.
    direction's ``children`` vs. validation's ``decision``).
    """
    try:
        parsed = json.loads(transcript.strip())
        if isinstance(parsed, dict) and required_key in parsed:
            return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", transcript, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict) and required_key in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None
