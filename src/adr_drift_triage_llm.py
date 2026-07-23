"""LLM wrapper for AdrDriftResolverLoop's TRIAGE step (#9976).

Sends a structured request: (ADR Context+Decision text) x (the cited PR's
diff, scoped to the cited module) → :class:`TriageVerdict`. Mirrors
``term_proposer_llm.py``'s shape deliberately (a ``LLMClient`` Protocol +
one wrapper class with a single async classify/draft method + strict
Pydantic validation of the raw dict) — that's the established pattern the
other structured-output loops in this codebase use.

A distinct ``LLMClient`` Protocol from ``term_proposer_llm.LLMClient``
(not reused) because this call site has a GitHub issue in scope (the
rollup being triaged) and MUST thread its number + labels through to the
CH-6 prompt-gate's upward-only ``data-class:`` label elevation — see
``runner_utils.run_lightweight_agent``'s docstring. term_proposer's
Protocol has no issue in scope, so widening its signature there would be
the wrong fix; a purpose-built Protocol here is more honest than forcing a
shared shape to fit two different call contexts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError

from adr_drift_triage import TriageVerdict, extract_decision_context


class LLMClient(Protocol):
    """Structured-output LLM client with issue context in scope.

    Implementations: production uses ``adr_drift_resolver_runtime.
    AdrDriftResolverLLMClient`` (routes through
    ``runner_utils.run_lightweight_agent``); tests use a stub with a
    pre-canned response — see ``tests/test_adr_drift_triage_llm.py``.
    """

    async def complete_structured(
        self,
        *,
        prompt: str,
        schema: dict[str, Any],
        issue_number: int,
        issue_labels: list[str],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class TriageContext:
    """All inputs the TRIAGE LLM needs to classify one drift rollup."""

    adr_number: int
    adr_title: str
    adr_markdown: str  # full raw ADR file text; Context/Decision extracted internally
    pr_number: int
    pr_diff: str  # already scoped to the ADR's cited module(s)
    issue_number: int  # the rollup issue being triaged (CH-6 context)
    issue_labels: tuple[str, ...] = ()


_PROMPT_TEMPLATE = """You are triaging one ADR-drift finding for HydraFlow's automated ADR-conformance fleet.

## Background

`AdrTouchpointAuditorLoop` (ADR-0056) is a pure DETECTOR: it flags any PR whose diff touches a `src/` module an Accepted ADR cites, when the ADR's own markdown file was NOT part of the same diff. It cannot judge whether the change actually contradicts the ADR's decision — it only knows the module changed. In practice, roughly 70% of these findings are false positives: a caller or co-tenant of the cited module changed, not the decision itself.

Your job is to make that judgment call the detector cannot: does this specific code change actually drift from what the ADR decided?

## ADR-{adr_number:04d}: {adr_title}

{adr_decision_context}

## The cited PR's diff (scoped to the module(s) this ADR cites)

PR #{pr_number}:

```diff
{pr_diff}
```

## Classify

Choose exactly ONE of these five outcomes:

- **consistent** — the diff is compatible with the ADR's Decision/Context as written. Nothing about the ADR's text needs to change; the module changed for reasons the ADR already allows for (a caller changed, an implementation detail moved, a co-tenant of the same file changed). This is the common case (~70% of findings).
- **real_drift** — the diff genuinely contradicts or supersedes something the ADR's Decision section states as true. The ADR text is now WRONG and needs a real edit to match reality.
- **over_citation** — the ADR's citation of this module is broader than what it actually governs (e.g. it bare-cites a whole file when it really only owns one symbol/behavior in it). The fix is narrowing the ADR's citation, not touching the ADR's decision.
- **dead_citation** — the cited file/symbol no longer exists, was renamed, or was extracted elsewhere, so the citation itself is stale. The fix is removing or repointing the citation.
- **low_confidence** — the evidence given (ADR text + diff) does not let you confidently pick one of the above. Use this whenever you are genuinely unsure — a wrong low_confidence costs a human 30 seconds of review; a wrong consistent silently loses real drift forever.

## FAIL-CLOSED — read before answering

Only `consistent` ever closes this finding automatically, with no human review. Every other classification (`real_drift`, `over_citation`, `dead_citation`, `low_confidence`) leaves it open for a human or the standard editing pipeline. This means:

- If you are not CONFIDENT the change is consistent, do NOT choose `consistent`. Prefer `low_confidence` over a guessed `consistent`.
- Do not invent facts not present in the ADR text or diff above. If the diff shown to you looks unrelated to the ADR's actual decision (e.g. the module was only touched for formatting/typing), that IS legitimate evidence for `consistent` — say so in your rationale.

## Output

Output a strict JSON object matching this shape:

```json
{{
  "classification": "consistent" | "real_drift" | "over_citation" | "dead_citation" | "low_confidence",
  "rationale": "<one line, specific>",
  "section": "<ADR section to edit, e.g. 'Decision' or 'Context'; empty string for consistent/low_confidence>"
}}
```

`rationale` requirements by classification:
- consistent: the audit-close comment — why this diff doesn't contradict the ADR (this is posted verbatim as the closing comment).
- real_drift / over_citation / dead_citation: a concrete brief — WHAT in the ADR text needs to change and WHY, specific enough that another engineer could make the edit without re-reading the diff themselves.
- low_confidence: what specifically made the evidence ambiguous.
"""


class AdrDriftTriageLLM:
    """Classifies one drift rollup via structured LLM call."""

    def __init__(self, client: LLMClient) -> None:
        self._client = client

    async def classify(self, ctx: TriageContext) -> TriageVerdict:
        prompt = self._build_prompt(ctx)
        raw = await self._client.complete_structured(
            prompt=prompt,
            schema=TriageVerdict.model_json_schema(),
            issue_number=ctx.issue_number,
            issue_labels=list(ctx.issue_labels),
        )
        try:
            return TriageVerdict.model_validate(raw)
        except ValidationError as e:
            raise ValueError(f"LLM returned invalid TriageVerdict: {e}") from e

    def _build_prompt(self, ctx: TriageContext) -> str:
        return _PROMPT_TEMPLATE.format(
            adr_number=ctx.adr_number,
            adr_title=ctx.adr_title,
            adr_decision_context=extract_decision_context(ctx.adr_markdown),
            pr_number=ctx.pr_number,
            pr_diff=ctx.pr_diff or "(no diff text available)",
        )
