"""DecompositionCouncil — LLM decision-maker for decompose-to-converge (ADR-0105).

Mirrors the shape of :class:`adr_reviewer.ADRCouncilReviewer`: a single
lightweight-agent call role-plays the council's own two internal phases
(direction, then validation) and returns one structured result block, which
is parsed into an :class:`~models.EpicDecompResult`. The call routes through
the shared :func:`runner_utils.run_lightweight_agent` seam (CH-6 gated +
telemetried) using the ADR-review provider dial (P1: reuse, no new knobs).

Confidence-gated retry (mirrors ``preflight/agent.py``'s ``_derive_status``
retry semantics, ADR-0084): a *decline* (``should_decompose=False``) at
anything less than ``high`` confidence — including a garbled/unparseable
reply — is treated the same way a garbled ``needs_human`` bail is treated
there: as not-yet-final, so the council is re-invoked once before the decline
is accepted. A *high*-confidence decline (genuinely atomic/not-splittable)
is final immediately, and any accept is always final (the retry rule only
guards against a premature "no" from a bad first pass).
"""

from __future__ import annotations

import json
import logging
import re
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

        Runs the council once; if it declines (``should_decompose=False``)
        at less than ``high`` confidence, re-runs the whole council one more
        time and returns that result regardless of its confidence (so a
        second weak decline is still accepted as final — no unbounded
        retries). An accept, or a high-confidence decline, returns
        immediately after the first run.
        """
        result = await self._run_council_once(
            task=task, stall_context=stall_context, doc_context=doc_context, depth=depth
        )
        if result.should_decompose or result.confidence == _HIGH_CONFIDENCE:
            return result

        logger.info(
            "Decomposition council: low-confidence decline for #%d "
            "(confidence=%r) — retrying once",
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
        """Run a single council pass: one seam call, direction then validation."""
        prompt = self._build_council_prompt(
            task, stall_context=stall_context, doc_context=doc_context, depth=depth
        )
        transcript = await self._execute_council(prompt)
        if transcript is None:
            logger.warning(
                "Decomposition council: seam call produced no output for #%d",
                task.id,
            )
            return EpicDecompResult(
                should_decompose=False,
                reasoning="Council call produced no output",
                confidence="low",
            )
        return self._parse_council_result(transcript)

    def _build_council_prompt(
        self,
        task: Task,
        *,
        stall_context: str,
        doc_context: str,
        depth: int,
    ) -> str:
        """Construct the single prompt driving both council phases.

        *stall_context* carries forward why the parent task stalled (from the
        auto-agent preflight loop); *doc_context* is an opaque string a later
        task fills with relevant repo docs/ADR excerpts — this council only
        needs to inject it, not interpret it.
        """
        body = (task.body or "")[:5000]
        max_depth = self._config.max_decomposition_depth
        return f"""You are the Decomposition Council for a stalled task. A prior \
autonomous implementation attempt on this task did not converge. Your job is \
to decide whether splitting it into an epic + independently implementable \
child issues would let it converge, and if so, produce the split.

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
{max_depth}). Weigh further splitting against that budget — prefer decline \
once close to the limit unless a split is clearly still warranted.

## Council Protocol

### Phase 1 -- Direction
Silently consider 2-3 candidate slicings of this work from DISTINCT lenses \
(e.g. by architectural layer, by user-facing capability, by risk/blast-radius). \
Weigh the tradeoffs of each candidate.

### Phase 2 -- Validation
Critically evaluate the strongest candidate from Phase 1. DECLINE the split \
(should_decompose=false) if:
- the candidates are near-duplicate/clone children with no independent value
- the task is an atomic, non-decomposable unit of work
- the children could not each land as an independent, reviewable PR

Otherwise ACCEPT the split (should_decompose=true) with at least 2 \
independently implementable children.

Rate your confidence in the FINAL decision as "high", "medium", or "low". \
Use "high" only when you are certain -- e.g. a task that is clearly atomic, \
or candidates that are clearly duplicative. Use "medium" or "low" when the \
call is genuinely close.

## Required Output

Return ONLY a JSON object in this exact format (no other text):

```json
{{
  "should_decompose": true,
  "confidence": "high",
  "epic_title": "Epic: ...",
  "epic_body": "## Sub-issues\\n\\n- [ ] Child title 1\\n- [ ] Child title 2",
  "children": [
    {{"title": "Child issue title", "body": "Detailed description..."}},
    {{"title": "Another child", "body": "More details..."}}
  ],
  "reasoning": "Why this decomposition makes sense"
}}
```

or

```json
{{
  "should_decompose": false,
  "confidence": "high",
  "reasoning": "Why this task should not be decomposed"
}}
```"""

    async def _execute_council(self, prompt: str) -> str | None:
        """Call the configured LLM backend for one council pass.

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

    def _parse_council_result(self, transcript: str) -> EpicDecompResult:
        """Parse the council's JSON result block into an ``EpicDecompResult``.

        Unparseable or malformed output (missing key, or an accept with
        fewer than 2 children) is treated as a garbled low-confidence
        decline so :meth:`decide` retries it once, mirroring how
        ``preflight/agent.py._derive_status`` treats a missing/garbled
        status as ``retry`` rather than a final answer.
        """
        data = _extract_json_object(transcript)
        if data is None:
            logger.warning(
                "Decomposition council: no parseable JSON result in transcript"
            )
            return EpicDecompResult(
                should_decompose=False,
                reasoning="Failed to parse council result",
                confidence="low",
            )

        confidence = str(data.get("confidence", "") or "").strip().lower() or "low"
        should = bool(data.get("should_decompose", False))

        if not should:
            return EpicDecompResult(
                should_decompose=False,
                reasoning=str(data.get("reasoning", "")),
                confidence=confidence,
            )

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
                "Decomposition council: accept with <2 parsed children -- "
                "treating as garbled"
            )
            return EpicDecompResult(
                should_decompose=False,
                reasoning=(
                    "Council accepted the split but produced fewer than 2 "
                    "children (treated as garbled)"
                ),
                confidence="low",
            )

        return EpicDecompResult(
            should_decompose=True,
            epic_title=str(data.get("epic_title", "")),
            epic_body=str(data.get("epic_body", "")),
            children=children,
            reasoning=str(data.get("reasoning", "")),
            confidence=confidence,
        )


def _extract_json_object(transcript: str) -> dict[str, object] | None:
    """Extract a JSON object from *transcript*: direct parse, then code fence.

    Mirrors ``triage.py._parse_decomposition``'s two-strategy approach.
    """
    try:
        parsed = json.loads(transcript.strip())
        if isinstance(parsed, dict) and "should_decompose" in parsed:
            return parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        pass

    fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", transcript, re.DOTALL)
    if fence_match:
        try:
            parsed = json.loads(fence_match.group(1).strip())
            if isinstance(parsed, dict) and "should_decompose" in parsed:
                return parsed
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    return None
