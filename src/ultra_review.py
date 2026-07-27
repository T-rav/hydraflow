"""Opt-in "ultra" deep-review tier for the review phase (issue #10555).

RESEARCH FINDING (load-bearing — recorded in ADR-0109): the **cloud**
``/code-review ultra`` tier has **no programmatic entry point**. It is a
client-side, user-triggered, separately-billed Claude Code feature that
nothing in ``src/`` can launch. The reachable equivalent is the
locally-installed ``code-review`` plugin command, dispatched headlessly
through the same agent-CLI seam ``ReviewPhase._build_post_verify_runner``
already uses (``agent_cli.build_agent_command`` +
``ReviewRunner._execute``).

Load-bearing constraint: ``build_agent_command(..., isolate_user_settings=False)``
— passing ``True`` strips the ``--plugin-dir`` flags (``agent_cli.py``), so the
plugin slash-command would not resolve inside the spawn. This module always
builds the command with ``isolate_user_settings=False``.

Cost containment: the tier fans out to several reviewer agents per invocation,
so it is OFF by default (``config.review_ultra_enabled``) and, even when on,
only fires for a ``review:ultra``-labelled issue or a high-blast-radius diff
(``config.review_ultra_auto_high_blast``). See :func:`should_ultra_review`.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol

from pydantic import BaseModel, Field, field_validator

from review_advisor import compute_blast_radius, diff_stats_from_text

if TYPE_CHECKING:  # pragma: no cover - typing only
    from config import HydraFlowConfig

logger = logging.getLogger(__name__)


# Opt-in label an operator adds to an issue to request the ultra tier for its
# PR. Reads go through ``IssueStorePort.get_issue_labels`` (the ISSUE, not the
# PR — ``PRPort`` has no label-read method).
ULTRA_REVIEW_LABEL = "review:ultra"

# Findings below this confidence are advisory (posted, not blocking); findings
# at/above it are "material" and flip the verdict to REQUEST_CHANGES. Mirrors
# the ``code-review`` plugin's own <80 drop threshold.
ULTRA_CONFIDENCE_THRESHOLD = 80

# Compound role key MockWorld scenarios use to script an ultra payload via the
# existing ``FakeLLM.script_advisor`` / ``pop_advisor_result`` machinery — no
# new fake method required.
ULTRA_MOCKWORLD_ROLE = "ultra_review"


class _ExecuteFn(Protocol):
    """The ``ReviewRunner._execute`` seam the production dispatch threads into."""

    def __call__(
        self,
        cmd: list[str],
        prompt: str,
        cwd: Any,
        meta: dict[str, Any],
    ) -> Awaitable[str]:  # pragma: no cover - typing only
        ...


class UltraFinding(BaseModel):
    """A single deep-review finding with a 0-100 confidence score."""

    description: str
    confidence: int = Field(ge=0, le=100)
    severity: str | None = None
    location: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value: Any) -> int:
        """Coerce/clamp confidence to an int in [0, 100]; unparseable -> 0."""
        try:
            n = int(round(float(value)))
        except (TypeError, ValueError):
            return 0
        return max(0, min(100, n))


class UltraReviewResult(BaseModel):
    """Structured outcome of an ultra deep-review pass.

    ``degraded`` is True when the spawn produced no parseable findings block
    (unparseable output / infra hiccup). A degraded result is treated as
    "no signal" by the fold — it never flips a verdict — but is logged
    distinguishably so an "enabled but useless" tier is visible.
    """

    findings: list[UltraFinding] = Field(default_factory=list)
    degraded: bool = False

    @property
    def material_findings(self) -> list[UltraFinding]:
        """Findings scored at/above :data:`ULTRA_CONFIDENCE_THRESHOLD`."""
        return [f for f in self.findings if f.confidence >= ULTRA_CONFIDENCE_THRESHOLD]

    @property
    def has_material_findings(self) -> bool:
        return bool(self.material_findings)


def should_ultra_review(
    *,
    config: HydraFlowConfig,
    issue_labels: list[str],
    diff: str,
) -> bool:
    """Gate predicate for whether to run the ultra tier on a PR.

    All three of these must hold for the tier to fire (cost containment):

    1. ``config.review_ultra_enabled`` is on (default OFF), AND
    2. the issue carries the ``review:ultra`` label, OR
    3. ``config.review_ultra_auto_high_blast`` is on and the diff's blast
       radius classifies as ``"high"`` (critical paths / large src change).

    Pure — the only input is data already fetched by the caller. Returns
    ``False`` fast when the dial is off so the default path does zero work.
    """
    if not config.review_ultra_enabled:
        return False
    labels = {label.strip().lower() for label in issue_labels}
    if ULTRA_REVIEW_LABEL in labels:
        return True
    if config.review_ultra_auto_high_blast:
        stats = diff_stats_from_text(diff)
        if compute_blast_radius(stats) == "high":
            return True
    return False


def build_ultra_review_command(config: HydraFlowConfig) -> list[str]:
    """Build the headless command for the ultra deep-review spawn.

    ``isolate_user_settings=False`` is load-bearing: it keeps the
    ``--plugin-dir`` flags so the locally-installed ``code-review`` plugin
    slash-command resolves inside the spawn.
    """
    from agent_cli import build_agent_command  # noqa: PLC0415

    return build_agent_command(
        tool=config.review_tool,
        model=config.review_ultra_model,
        disallowed_tools="Write,Edit,NotebookEdit",
        isolate_user_settings=False,
    )


def build_ultra_review_prompt(*, pr_number: int, diff: str) -> str:
    """Build the prompt that drives the local ``code-review`` deep pass.

    Instructs the agent to run the multi-reviewer deep review over the diff and
    return a strict JSON object of findings with 0-100 confidence scores, so
    :func:`parse_ultra_findings` can fold high-confidence issues into the
    verdict. Truncates very large diffs to keep the prompt bounded.
    """
    diff_excerpt = (
        diff if len(diff) <= 20_000 else diff[:20_000] + "\n…[diff truncated]"
    )
    return (
        "Run a DEEP, adversarial multi-reviewer code review of the pull request "
        f"below (PR #{pr_number}). Use the `/code-review` deep-review workflow: "
        "multiple independent reviewers, then score each finding's confidence "
        "0-100 and drop anything you are not confident is a real defect.\n\n"
        "Return ONLY a JSON object of the form:\n"
        '{"findings": [{"description": "...", "confidence": 0-100, '
        '"severity": "low|medium|high", "location": "path:line"}]}\n'
        "Return an empty findings array if the diff is clean. Do not include "
        "prose outside the JSON object.\n\n"
        "=== DIFF ===\n"
        f"{diff_excerpt}\n"
    )


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"(\{.*\})", re.DOTALL)


def _extract_json_object(payload: str) -> str | None:
    """Extract the findings JSON object from an agent transcript, or None.

    Prefers a fenced ```json block; falls back to the widest ``{...}`` span.
    """
    fenced = _JSON_FENCE_RE.search(payload)
    if fenced:
        return fenced.group(1)
    block = _JSON_OBJECT_RE.search(payload)
    if block:
        return block.group(1)
    return None


def parse_ultra_findings(payload: str) -> UltraReviewResult:
    """Parse an ultra deep-review transcript into an :class:`UltraReviewResult`.

    Tolerant by design: unparseable / empty output returns a *degraded* result
    (no findings, ``degraded=True``) rather than raising, so a broken spawn
    fails soft (verdict untouched) instead of crashing the review. A payload
    that parses to an empty findings list is a *clean* result (not degraded).
    """
    if not payload or not payload.strip():
        return UltraReviewResult(degraded=True)

    raw = _extract_json_object(payload)
    if raw is None:
        logger.warning("ultra-review: no JSON object in transcript; degraded")
        return UltraReviewResult(degraded=True)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("ultra-review: JSON parse failed; degraded")
        return UltraReviewResult(degraded=True)

    items = data.get("findings") if isinstance(data, dict) else None
    if not isinstance(items, list):
        logger.warning("ultra-review: no findings list in payload; degraded")
        return UltraReviewResult(degraded=True)

    findings: list[UltraFinding] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        description = str(item.get("description", "")).strip()
        if not description:
            continue
        try:
            findings.append(
                UltraFinding(
                    description=description,
                    confidence=item.get("confidence", 0),
                    severity=item.get("severity"),
                    location=item.get("location"),
                )
            )
        except (TypeError, ValueError):
            continue
    return UltraReviewResult(findings=findings, degraded=False)


def summarize_ultra_findings(result: UltraReviewResult) -> str:
    """Render an ultra result as a markdown block for the summary / PR comment."""
    lines = ["## Ultra deep-review findings"]
    if result.has_material_findings:
        lines.append(
            "The ultra tier surfaced high-confidence issues "
            f"(confidence >= {ULTRA_CONFIDENCE_THRESHOLD}):"
        )
    else:
        lines.append("The ultra tier surfaced advisory (sub-threshold) notes:")
    for finding in result.findings:
        loc = f" (`{finding.location}`)" if finding.location else ""
        sev = f"[{finding.severity}] " if finding.severity else ""
        lines.append(
            f"- {sev}{finding.description}{loc} — confidence {finding.confidence}"
        )
    return "\n".join(lines)


async def run_ultra_review(
    *,
    execute: _ExecuteFn | Callable[..., Awaitable[str]],
    config: HydraFlowConfig,
    prompt: str,
    cwd: Any,
    meta: dict[str, Any] | None = None,
) -> UltraReviewResult:
    """Dispatch the ultra deep-review spawn and parse its findings.

    ``execute`` is the ``ReviewRunner._execute`` seam
    (``(cmd, prompt, cwd, meta) -> str``). Credit-exhaustion / authentication /
    likely-bug errors from the spawn PROPAGATE (per docs/wiki/dark-factory.md
    §2.2 — ``reraise_on_credit_or_bug``); any other runner failure fails soft to
    a *degraded* result so the tier never crashes the review it is advising.
    """
    from exception_classify import reraise_on_credit_or_bug  # noqa: PLC0415

    cmd = build_ultra_review_command(config)
    try:
        payload = await execute(cmd, prompt, cwd, meta or {"source": "ultra-review"})
    except Exception as exc:
        reraise_on_credit_or_bug(exc)
        logger.warning("ultra-review dispatch failed; degraded: %r", exc)
        return UltraReviewResult(degraded=True)
    return parse_ultra_findings(payload)
