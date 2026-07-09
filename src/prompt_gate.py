"""PromptGate — the CH-6 assembly-time data-governance gate for LLM prompts.

Issue #9734. Prompts carry issue text, source excerpts, and diffs to the model
vendor; for ``regulated-*`` data classes that content is a subprocessor
disclosure. This module is the ONE choke point every prompt-assembly →
agent-spawn path consults before content leaves the process:

* **Classification** — a repo declares a data class (``public-code`` |
  ``internal`` | ``regulated-<name>``) via ``HydraFlowConfig.repo_data_class``
  (populated from the runtime repo registry, ``repos.json``). Issues can carry
  a ``data-class:<class>`` label that overrides UPWARD in restriction only.
  Any classification uncertainty (unknown class string, conflicting regulated
  labels) collapses to :data:`FAIL_CLOSED_DATA_CLASS` — never downward.
* **Redaction** — ``regulated-*`` prompts pass through a small named pattern
  set (:data:`BUILTIN_REDACTION_PATTERNS` merged with
  ``config.data_class_redaction_patterns``). v1 is deliberately NOT DLP-grade
  content scanning; the backend allowlist is the hard gate, redaction is
  defense in depth.
* **Backend policy** — ``config.data_class_allowed_backends`` maps a data
  class to the CLI backends (``claude``/``codex``/``gemini``/``pi``) allowed
  to receive its prompts. A regulated class with no entry allows NOTHING
  (fail closed): :func:`gate_prompt` raises :class:`PromptGateBlockedError`
  and the spawn seams surface it as a hard failure that the existing
  escalation machinery routes to HITL.
* **Evidence** — every gate decision for a regulated class appends one JSONL
  audit record (``config.prompt_gate_audit_path``) carrying pattern NAMES and
  counts — never prompt content.

Zero-regression contract: for ``public-code``/``internal`` classes the gate
is a structured no-op — prompt returned unchanged, no blocking, no filesystem
writes. ``tests/test_prompt_gate.py::TestZeroRegressionNoOp`` pins this.

Enforcement: ``tests/test_prompt_gate_completeness.py`` extends the ADR-0055
spawn-containment ratchet (``tests/_spawn_audit.py``) so every LLM spawn seam
must call :func:`gate_prompt` / :func:`gate_context_fields`.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from json import dumps
from typing import TYPE_CHECKING

from file_util import append_jsonl

if TYPE_CHECKING:
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.prompt_gate")

#: The two unregulated data classes (in ascending restriction order).
DATA_CLASS_PUBLIC_CODE = "public-code"
DATA_CLASS_INTERNAL = "internal"

#: Every class more restrictive than ``internal`` carries this prefix.
REGULATED_PREFIX = "regulated-"

#: Fail-closed class assigned on ANY classification uncertainty (unknown or
#: malformed class string, conflicting regulated issue labels). It is
#: regulated and — absent an explicit allowlist entry — blocks every backend.
FAIL_CLOSED_DATA_CLASS = "regulated-unclassified"

#: Issue labels of the form ``data-class:<class>`` override the repo's
#: declared class upward (never downward, never sideways).
DATA_CLASS_LABEL_PREFIX = "data-class:"

_VALID_CLASS_RE = re.compile(r"^(?:public-code|internal|regulated-[a-z0-9][a-z0-9-]*)$")

#: v1 built-in redaction pattern set (spec #9734: SSN-like, credit-card-like,
#: generic ``key=value`` secrets). Merged with — and overridable by —
#: ``config.data_class_redaction_patterns``. Names are audit-record keys.
BUILTIN_REDACTION_PATTERNS: dict[str, str] = {
    "ssn_like": r"\b\d{3}-\d{2}-\d{4}\b",
    "credit_card_like": r"\b(?:\d{4}[ -]){3}\d{1,4}\b|\b\d{13,16}\b",
    "key_value_secret": (
        r"(?i)\b(?:api[_-]?key|secret|token|password|passwd|credential)\b"
        r"\s*[:=]\s*[^\s'\"]+"
    ),
}


def is_valid_data_class(raw: str) -> bool:
    """True when *raw* is a well-formed data class string."""
    return bool(_VALID_CLASS_RE.fullmatch(raw.strip()))


def normalize_data_class(raw: str) -> str:
    """Return *raw* when valid; otherwise fail closed.

    Unknown/malformed class strings are classification uncertainty and
    collapse to :data:`FAIL_CLOSED_DATA_CLASS` (spec #9734 constraint).
    """
    cleaned = raw.strip()
    if is_valid_data_class(cleaned):
        return cleaned
    logger.warning(
        "prompt gate: unknown data class %r — failing closed to %r",
        raw,
        FAIL_CLOSED_DATA_CLASS,
    )
    return FAIL_CLOSED_DATA_CLASS


def restriction_rank(data_class: str) -> int:
    """Ordering key: ``public-code`` (0) < ``internal`` (1) < ``regulated-*`` (2)."""
    if data_class == DATA_CLASS_PUBLIC_CODE:
        return 0
    if data_class == DATA_CLASS_INTERNAL:
        return 1
    return 2


def is_regulated(data_class: str) -> bool:
    """True for ``regulated-*`` classes (including the fail-closed class)."""
    return data_class.startswith(REGULATED_PREFIX)


def effective_data_class(repo_class: str, issue_labels: Sequence[str] = ()) -> str:
    """Resolve the effective class: repo declaration + upward-only label override.

    A ``data-class:<class>`` label elevates the class when strictly MORE
    restrictive than the repo's declaration; it can never lower it or move it
    sideways between regulated classes. Multiple distinct elevating labels are
    classification uncertainty → :data:`FAIL_CLOSED_DATA_CLASS`.
    """
    repo_c = normalize_data_class(repo_class)
    elevating = {
        label_c
        for label in issue_labels
        if label.startswith(DATA_CLASS_LABEL_PREFIX)
        for label_c in (normalize_data_class(label[len(DATA_CLASS_LABEL_PREFIX) :]),)
        if restriction_rank(label_c) > restriction_rank(repo_c)
    }
    if not elevating:
        return repo_c
    if len(elevating) == 1:
        return next(iter(elevating))
    logger.warning(
        "prompt gate: conflicting data-class labels %s — failing closed",
        sorted(elevating),
    )
    return FAIL_CLOSED_DATA_CLASS


@dataclass(frozen=True)
class GateDecision:
    """One gate decision — audit-record shape (pattern names/counts, no content)."""

    data_class: str
    action: str  # "allow" | "redact" | "block"
    patterns_hit: dict[str, int] = field(default_factory=dict)
    source: str = ""
    tool: str = ""
    issue_number: int | None = None
    reason: str = ""


@dataclass(frozen=True)
class GateResult:
    """Gated prompt (possibly redacted) plus the decision that produced it."""

    prompt: str
    decision: GateDecision


class PromptGateBlockedError(RuntimeError):
    """The effective data class forbids sending this prompt to the backend.

    Raised BEFORE any subprocess spawns, so a block never costs LLM spend.
    Spawn seams either propagate it (``BaseRunner._execute`` — the phase
    escalation machinery converts repeated hard failures into HITL routing)
    or collapse it to their soft-failure result (``run_lightweight_agent``,
    ``BaseSubprocessRunner.run`` — fail closed, audit record already written).
    """

    def __init__(self, message: str, *, decision: GateDecision) -> None:
        super().__init__(message)
        self.decision = decision


def _compiled_patterns(config: HydraFlowConfig) -> dict[str, re.Pattern[str]]:
    """Merge built-ins with configured extras; skip (loudly) invalid regexes."""
    merged: dict[str, str] = {
        **BUILTIN_REDACTION_PATTERNS,
        **(config.data_class_redaction_patterns or {}),
    }
    compiled: dict[str, re.Pattern[str]] = {}
    for name, pattern in merged.items():
        try:
            compiled[name] = re.compile(pattern)
        except re.error:
            logger.warning(
                "prompt gate: invalid redaction pattern %r — skipped "
                "(built-ins still apply; the backend allowlist is the hard gate)",
                name,
                exc_info=True,
            )
    return compiled


def _redact(
    text: str, patterns: dict[str, re.Pattern[str]]
) -> tuple[str, dict[str, int]]:
    """Replace matches with ``[REDACTED:<name>]``; return (text, name→count)."""
    hits: dict[str, int] = {}
    for name, rx in patterns.items():
        text, count = rx.subn(f"[REDACTED:{name}]", text)
        if count:
            hits[name] = count
    return text, hits


def _emit_audit(config: HydraFlowConfig, decision: GateDecision) -> None:
    """Append one JSONL audit record. Best-effort: never raises.

    Records carry counts and pattern NAMES only — never prompt content.
    """
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "repo": config.repo,
        "source": decision.source,
        "data_class": decision.data_class,
        "action": decision.action,
        "patterns_hit": dict(decision.patterns_hit),
        "tool": decision.tool,
        "issue_number": decision.issue_number,
        "reason": decision.reason,
    }
    try:
        append_jsonl(config.prompt_gate_audit_path, dumps(record))
    except Exception:
        logger.warning("prompt gate audit write failed", exc_info=True)


def gate_prompt(
    prompt: str,
    *,
    config: HydraFlowConfig,
    source: str,
    tool: str = "",
    issue_number: int | None = None,
    issue_labels: Sequence[str] = (),
) -> GateResult:
    """Gate one assembled prompt before it is sent to an LLM backend.

    For ``public-code``/``internal`` classes this is a structured no-op.
    For regulated classes: redact via the merged pattern set, then require
    *tool* to be in ``config.data_class_allowed_backends[<class>]`` — a
    missing entry or unknown tool blocks (fail closed) by raising
    :class:`PromptGateBlockedError`. Every regulated decision emits an audit
    record.
    """
    data_class = effective_data_class(config.repo_data_class, issue_labels)
    if not is_regulated(data_class):
        return GateResult(
            prompt,
            GateDecision(
                data_class=data_class,
                action="allow",
                source=source,
                tool=tool,
                issue_number=issue_number,
            ),
        )

    redacted, hits = _redact(prompt, _compiled_patterns(config))
    allowed = (config.data_class_allowed_backends or {}).get(data_class) or []
    if not tool or tool not in allowed:
        reason = (
            f"data class {data_class!r} does not allow backend {tool!r} "
            f"(allowed: {sorted(allowed) if allowed else 'none configured — fail closed'})"
        )
        decision = GateDecision(
            data_class=data_class,
            action="block",
            patterns_hit=hits,
            source=source,
            tool=tool,
            issue_number=issue_number,
            reason=reason,
        )
        _emit_audit(config, decision)
        raise PromptGateBlockedError(
            f"prompt gate blocked: {reason}", decision=decision
        )

    decision = GateDecision(
        data_class=data_class,
        action="redact" if hits else "allow",
        patterns_hit=hits,
        source=source,
        tool=tool,
        issue_number=issue_number,
    )
    _emit_audit(config, decision)
    return GateResult(redacted, decision)


def gate_context_fields(
    fields: dict[str, str],
    *,
    config: HydraFlowConfig,
    source: str,
    issue_number: int | None = None,
    issue_labels: Sequence[str] = (),
) -> tuple[dict[str, str], GateDecision]:
    """Redaction-only gate for assembly seams with no backend in scope.

    Used by ``preflight.context.gather_context``: gathered free-text fields
    (issue body, comments, wiki excerpts) are redacted for regulated classes
    before entering any prompt. Blocking stays with the spawn seams, which
    all call :func:`gate_prompt`. Emits ONE audit record per regulated call.
    """
    data_class = effective_data_class(config.repo_data_class, issue_labels)
    if not is_regulated(data_class):
        return dict(fields), GateDecision(
            data_class=data_class,
            action="allow",
            source=source,
            issue_number=issue_number,
        )

    patterns = _compiled_patterns(config)
    redacted: dict[str, str] = {}
    total_hits: dict[str, int] = {}
    for key, value in fields.items():
        redacted[key], hits = _redact(value, patterns)
        for name, count in hits.items():
            total_hits[name] = total_hits.get(name, 0) + count

    decision = GateDecision(
        data_class=data_class,
        action="redact" if total_hits else "allow",
        patterns_hit=total_hits,
        source=source,
        issue_number=issue_number,
    )
    _emit_audit(config, decision)
    return redacted, decision


__all__ = [
    "BUILTIN_REDACTION_PATTERNS",
    "DATA_CLASS_INTERNAL",
    "DATA_CLASS_LABEL_PREFIX",
    "DATA_CLASS_PUBLIC_CODE",
    "FAIL_CLOSED_DATA_CLASS",
    "REGULATED_PREFIX",
    "GateDecision",
    "GateResult",
    "PromptGateBlockedError",
    "effective_data_class",
    "gate_context_fields",
    "gate_prompt",
    "is_regulated",
    "is_valid_data_class",
    "normalize_data_class",
    "restriction_rank",
]
