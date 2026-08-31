"""The model stage that turns retrospective signals into candidate findings.

The finder proposes; `retro_findings.validate` disposes. Nothing here is
trusted: output is parsed defensively, unknown kinds and unanchored findings
are skipped, and every failure mode degrades to zero findings so a retro tick
can never block the merge path.

The one exception is a billing signal. `CreditExhaustedError` propagates —
burying it leaves the loop spawning against a dead account
(docs/wiki/dark-factory.md §2.2).
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

from pydantic import TypeAdapter, ValidationError

import runner_utils
from config import Credentials
from exception_classify import reraise_on_credit_or_bug
from execution import get_default_runner
from retro_findings import RetroFinding

if TYPE_CHECKING:
    from collections.abc import Sequence

    from config import HydraFlowConfig
    from retro_signals import RetroSignal

logger = logging.getLogger("hydraflow.retro_finder")

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

_finding_adapter: TypeAdapter[RetroFinding] = TypeAdapter(RetroFinding)

_PROMPT = """\
You are analysing failure signals from a software factory's own pipeline.

Each signal below was measured, not inferred: it carries a count, the issues it
spans, and verbatim evidence. Propose concrete findings grounded ONLY in these
signals.

Return a JSON array. Nothing else — no preamble, no commentary. Each element:

  {{"kind": "gate",   "signal_id": ..., "title": ..., "rationale": ...,
    "guard_path": "<tests/architecture/... | .claude/hooks/... | .github/workflows/...>",
    "observed": "<must restate the signal's count>"}}

  {{"kind": "bugfix", "signal_id": ..., "title": ..., "rationale": ...,
    "repro_command": "<command that reproduces it>",
    "repro_file": "<an existing repo-relative file>",
    "error_excerpt": "<copied VERBATIM from the signal's evidence>"}}

  {{"kind": "policy", "signal_id": ..., "title": ..., "rationale": ...,
    "doc_path": "<an existing doc: CLAUDE.md, docs/standards/..., docs/wiki/...>",
    "rule_text": "<the rule to add>"}}

Rules:
- Every finding MUST cite one of the signal_ids given below.
- error_excerpt must be copied character-for-character from that signal's
  evidence. Anything invented is discarded.
- A signal with no evidence text cannot support a "bugfix".
- Propose nothing you cannot anchor. Returning [] is a valid answer.

--- SIGNALS ---
{signals}
"""


class RetroFinder:
    """Proposes typed findings from measured signals."""

    def __init__(
        self,
        config: HydraFlowConfig,
        runner: Any = None,
        credentials: Any = None,
    ) -> None:
        self._config = config
        self._runner = runner or get_default_runner()
        self._credentials = credentials or Credentials()

    async def find(
        self,
        signals: Sequence[RetroSignal],
        *,
        issue_labels: Sequence[str] = (),
    ) -> list[RetroFinding]:
        """Return candidate findings. Never raises except on billing signals.

        *issue_labels* is the union of labels across the issues whose evidence
        produced *signals*; the CH-6 gate uses it for upward-only
        ``data-class:`` elevation on this spawn. The finder reads evidence from
        many issues at once, so the union — not any single issue — is correct.
        """
        if not self._config.retro_finder_enabled or not signals:
            return []

        prompt = _PROMPT.format(signals=self._render(signals))
        raw = await self._call_model(prompt, issue_labels=issue_labels)
        if not raw:
            return []
        return _parse(raw)

    def _render(self, signals: Sequence[RetroSignal]) -> str:
        budget = self._config.retro_evidence_max_chars
        per_signal = max(200, budget // max(1, len(signals)))
        blocks: list[str] = []
        for signal in signals:
            excerpts = "\n".join(
                f"    evidence: {ref.excerpt[:per_signal]}" for ref in signal.evidence
            )
            blocks.append(
                f"- id: {signal.id}\n"
                f"  family: {signal.family}\n"
                f"  signature: {signal.signature}\n"
                f"  count: {signal.count}\n"
                f"  issues: {signal.issues}\n"
                f"{excerpts}"
            )
        return "\n".join(blocks)[:budget]

    async def _call_model(
        self, prompt: str, *, issue_labels: Sequence[str] = ()
    ) -> str:
        try:
            result = await runner_utils.run_lightweight_agent(
                runner=self._runner,
                config=self._config,
                tool=self._config.retro_finder_tool,
                model=self._config.retro_finder_model,
                provider=self._config.retro_finder_provider,
                prompt=prompt,
                source="retro_finder",
                timeout=self._config.retro_finder_timeout,
                gh_token=self._credentials.gh_token,
                issue_labels=issue_labels,
            )
        except TimeoutError:
            logger.warning("Retro finder timed out")
            return ""
        except Exception as exc:
            reraise_on_credit_or_bug(exc)
            logger.warning("Retro finder unavailable: %s", exc)
            return ""

        if result.returncode != 0:
            logger.warning(
                "Retro finder failed (rc=%d): %s",
                result.returncode,
                result.stderr[:200],
            )
            return ""
        return result.stdout or ""


def _parse(raw: str) -> list[RetroFinding]:
    """Extract findings from model output, skipping anything malformed."""
    payload = _extract_array(raw)
    if payload is None:
        logger.warning("Retro finder returned no parseable JSON array")
        return []

    findings: list[RetroFinding] = []
    for item in payload:
        try:
            findings.append(_finding_adapter.validate_python(item))
        except ValidationError:
            logger.debug("Skipping unusable finding: %s", str(item)[:160])
    return findings


def _extract_array(raw: str) -> list[Any] | None:
    for candidate in (
        raw,
        *(_FENCE_RE.findall(raw) or []),
        *(_ARRAY_RE.findall(raw) or []),
    ):
        try:
            parsed = json.loads(candidate.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(parsed, list):
            return parsed
    return None
