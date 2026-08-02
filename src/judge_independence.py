"""Judge-independence budget + fail-visible dispatch policy (#10371).

Two publicly-confessed seams in the factory's evidence path get closed here:

1. **Correlated verdicts ("the jury is siblings").** Author and reviewers are
   the same model family; same-family lenses add variance-reduction, not
   independence. For four blast-radius classes we require *one independent
   verdict* — a verdict from a model family OUTSIDE the implementing agent's
   configured roster (or a deterministic gate where one exists).
2. **Silent fail-open.** Post-verification lens dispatch, when a judge is
   unavailable through infrastructure failure, passes the work with no verdict
   recorded and no alarm raised. Every such fail-open now becomes an append-only
   ledger row + a dashboard alert. The fail-open RATE gets a Shewhart control
   limit; above-limit files a ``hydraflow-find``.

Decided policy (spec ``docs/proposals/judge-independence-and-fail-visible.md``,
FINAL):

- Blast-radius classes: structural (ADR-touching / module-graph-altering),
  security-adjacent, data migrations, and **self-modification** — anything
  touching the gauntlet, gates, detectors, merge policy, or this policy itself
  (the highest class). The classifier that assigns classes is *itself* covered
  by the self-modification class (it is part of the policy machinery).
- **Fail-closed for self-modification:** a missing verdict on the machinery that
  produces verdicts is a STOP, not a degraded pass. All other classes remain
  fail-open but ledgered and alarmed.
- **Degraded mode is never silent:** when no independent family is configured or
  reachable, non-self-mod classes proceed with the same-family verdict plus a
  ledgered ``independence-unavailable`` record; the self-modification class
  escalates to HITL instead of merging.

This module is pure policy + append-only ledger IO. It never spawns subprocesses,
never calls ``gh``, and never imports orchestration or loop machinery — the
merge-outcome-changing behaviour is gated by feature flags at the call sites
(``review_advisor``), while the ledger/alarm is always live per the spec
("LEDGER/alarm can be live").
"""

from __future__ import annotations

import json
import logging
import math
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only
    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.judge_independence")


# ---------------------------------------------------------------------------
# Blast-radius classification
# ---------------------------------------------------------------------------


class BlastRadiusClass(StrEnum):
    """The four blast-radius classes that require an independent verdict.

    ``SELF_MODIFICATION`` is the highest class — a change touching the
    factory's own instruments (gauntlet/gates/detectors/merge policy/this
    policy). It is fail-CLOSED, unlike the other three which are fail-open
    but ledgered.
    """

    STRUCTURAL = "structural"
    SECURITY = "security"
    MIGRATION = "migration"
    SELF_MODIFICATION = "self_modification"


# Self-modification paths: the machinery that produces verdicts and gates
# merges. A change touching any of these is the highest class and fails CLOSED.
# The classifier module itself (``judge_independence.py``) is included per the
# spec's explicit acceptance criterion — the policy machinery watches itself.
_SELF_MOD_SUBSTRINGS: tuple[str, ...] = (
    "src/review_advisor.py",
    "src/review_phase.py",
    "src/review_phase/",
    "src/judge_independence.py",
    "src/fail_open_monitor_loop.py",
    # #10373: the green-while-dying monitor must not be quietly editable by the
    # machinery it monitors — its loop, its pure engine package, and its state
    # accessor are all self-modification class (independent verdict, fail-closed).
    "src/second_order_vitals_loop.py",
    "src/vitals/",
    "src/state/_second_order_vitals.py",
    "src/convergence_gate.py",
    "src/escalation_gate.py",
    "src/precondition_gate.py",
    "src/wiki_anchor_gate.py",
    "src/prompt_gate.py",
    "src/gate_activation_check.py",
    "src/gate_activator_loop.py",
    "src/gate_health_loop.py",
    "src/baseline_policy.py",
    "src/delta_verifier.py",
    "src/spec_judge.py",
    "src/verification_judge.py",
    "src/detector_calibration_loop.py",
    "src/reviewer.py",
    "src/pr_manager.py",  # merge policy lives here
    "src/staging_promotion_loop.py",  # merge/promotion policy
    "src/merge_state_watcher_loop.py",
    "docs/standards/",  # the written policy machinery
    # #10851: the class was under-inclusive — the 2026-07-30 precondition-gate
    # config flip wedged the machine (#10846/#10847) yet was not classified as
    # self-modification. Add the surface that is clearly self-mod AND rarely
    # touched: judge routing / provider dials — a failover re-dial changes verdict
    # *provenance* (#10844). Two surfaces are DELIBERATELY not path-matched here to
    # avoid the over-reach the #10851 counter-metric warns of (a class so broad
    # every config tweak needs an out-of-family verdict gets routed around):
    #   - gate *enablement* config (config.py) — caught by the ADR-0123
    #     `Binds: factory` backstop instead (only the ADR-cited files, not all of
    #     config.py);
    #   - instrument thresholds / finding-rate budgets — the specific weakens-a-gate
    #     files still need picking out from the routine ratchet baselines (e.g.
    #     suppressions.yaml is a mechanical noqa ledger, not a threshold), open in
    #     #10851.
    "src/credit_failover.py",  # #10844 provider re-dial → verdict provenance
)

# Security-adjacent paths: auth, secrets, prompt-assembly / trust-boundary.
_SECURITY_SUBSTRINGS: tuple[str, ...] = (
    "src/security_patch_loop.py",
    "src/branch_protection",
    "src/trust_fleet",
    "src/triage_honeypot.py",
    "src/human_steering.py",
    "src/prompt_",
    "/auth",
    "auth.py",
    "secret",
    "credential",
    "token",
)

# Data-migration paths.
_MIGRATION_SUBSTRINGS: tuple[str, ...] = (
    "src/data_migration.py",
    "migrations/",
    "/migration",
    "_migration.py",
    "schema_evolution",
)

# Structural: ADR-touching or module-graph-altering. Detected via ADR paths
# and the module-graph-critical roots (mirrors review_advisor.CRITICAL_PATHS).
_STRUCTURAL_SUBSTRINGS: tuple[str, ...] = (
    "docs/adr/",
    "src/orchestrator.py",
    "src/service_registry.py",
    "src/coordinator.py",
    "src/persistence/",
    "src/state/",
    "docs/arch/functional_areas.yml",
)

# ADR-numbered filename, e.g. ``0042-two-tier-....md`` under docs/adr/.
_ADR_FILE_RE = re.compile(r"docs/adr/\d{4}-")

# Unified-diff post-image path header, e.g. ``+++ b/src/foo.py``.
_DIFF_PATH_RE = re.compile(r"^\+\+\+ b/(.+?)\s*$", re.MULTILINE)
_DIFF_GIT_RE = re.compile(r"^diff --git a/(.+?) b/(.+?)\s*$", re.MULTILINE)


def paths_from_diff(diff: str) -> list[str]:
    """Extract changed paths from a unified-diff string.

    Reads both ``+++ b/<path>`` post-image headers and ``diff --git a/.. b/..``
    headers (the latter covers pure deletions/renames where no ``+++`` line is
    present). Tolerant of empty/malformed input.
    """
    paths: set[str] = set()
    for m in _DIFF_PATH_RE.finditer(diff):
        p = m.group(1).strip()
        if p and p != "/dev/null":
            paths.add(p)
    for m in _DIFF_GIT_RE.finditer(diff):
        for p in (m.group(1).strip(), m.group(2).strip()):
            if p and p != "/dev/null":
                paths.add(p)
    return sorted(paths)


def _path_matches(path: str, needles: tuple[str, ...]) -> bool:
    return any(n in path for n in needles)


def classify_paths(paths: Iterable[str]) -> frozenset[BlastRadiusClass]:
    """Classify a set of changed paths into blast-radius classes.

    A change may fall into multiple classes (e.g. an ADR that also touches a
    gate). Returns an empty set for unclassed (ordinary) changes — those keep
    the ordinary review path untouched (spec non-goal: no change to unclassed).
    """
    classes: set[BlastRadiusClass] = set()
    for path in paths:
        norm = path.strip()
        if not norm:
            continue
        if _path_matches(norm, _SELF_MOD_SUBSTRINGS):
            classes.add(BlastRadiusClass.SELF_MODIFICATION)
        if _path_matches(norm, _SECURITY_SUBSTRINGS):
            classes.add(BlastRadiusClass.SECURITY)
        if _path_matches(norm, _MIGRATION_SUBSTRINGS):
            classes.add(BlastRadiusClass.MIGRATION)
        if _ADR_FILE_RE.search(norm) or _path_matches(norm, _STRUCTURAL_SUBSTRINGS):
            classes.add(BlastRadiusClass.STRUCTURAL)
    return frozenset(classes)


def classify_diff(diff: str) -> frozenset[BlastRadiusClass]:
    """Classify a unified-diff string into blast-radius classes."""
    return classify_paths(paths_from_diff(diff))


def requires_independent_verdict(classes: frozenset[BlastRadiusClass]) -> bool:
    """Any blast-radius class present means one independent verdict is required."""
    return bool(classes)


def is_self_modification(classes: frozenset[BlastRadiusClass]) -> bool:
    """Whether the self-modification (highest, fail-closed) class is present."""
    return BlastRadiusClass.SELF_MODIFICATION in classes


def classes_label(classes: Iterable[BlastRadiusClass]) -> str:
    """Stable comma-joined label for logs/ledger (sorted for determinism)."""
    return ",".join(sorted(str(c) for c in classes))


# ---------------------------------------------------------------------------
# Model-family / roster resolution
# ---------------------------------------------------------------------------

# Prefix → family. Order matters only for readability; matching is longest
# meaningful token. Claude tiers (opus/sonnet/haiku) are the default roster.
_FAMILY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("claude", "claude"),
    ("opus", "claude"),
    ("sonnet", "claude"),
    ("haiku", "claude"),
    ("gpt", "openai"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("codex", "openai"),
    ("gemini", "google"),
    ("grok", "xai"),
    ("kimi", "moonshot"),
    ("moonshot", "moonshot"),
    ("glm", "zhipu"),
    ("zai", "zhipu"),
    ("deepseek", "deepseek"),
    ("qwen", "qwen"),
    ("llama", "meta"),
    ("mistral", "mistral"),
    ("pi", "inflection"),
)


def model_family(model: str) -> str:
    """Map a model name to its family identity.

    Deterministic and offline — no network. Unknown models map to their own
    lowercased leading token so an unrecognised second-vendor model is still
    treated as its own family (independence is granted, not silently denied).
    """
    if not model:
        return ""
    low = model.strip().lower()
    for prefix, family in _FAMILY_PREFIXES:
        if low.startswith(prefix) or f"/{prefix}" in low or f"-{prefix}" in low:
            return family
    # Provider-prefixed (``openrouter/anthropic/claude-..``) or bare unknown:
    # use the last path segment's leading alpha token as the family.
    tail = low.rsplit("/", 1)[-1]
    token = re.split(r"[^a-z]", tail, maxsplit=1)[0]
    return token or low


def roster_families(config: HydraFlowConfig) -> frozenset[str]:
    """Families of the implementing agent's configured roster.

    The implementing roster is the models that WRITE and same-family-review the
    change: the implementation model, the review model, and the background
    model. An independent verdict must come from a family OUTSIDE this set.
    """
    models = [
        getattr(config, "model", "") or "",
        getattr(config, "review_model", "") or "",
        getattr(config, "background_model", "") or "",
    ]
    return frozenset(model_family(m) for m in models if m)


def independent_judge_model(config: HydraFlowConfig) -> str:
    """The configured independent-family judge model, or empty string.

    v1: a single ``judge_independent_model`` config dial. Empty (default) means
    no second family is configured — the degraded path applies. A configured
    model whose family is inside the implementing roster does NOT count as
    independent (it would defeat the budget), so it is treated as unavailable.
    """
    model = (getattr(config, "judge_independent_model", "") or "").strip()
    if not model:
        return ""
    if model_family(model) in roster_families(config):
        return ""
    return model


def independent_family_available(config: HydraFlowConfig) -> bool:
    """Whether an independent-family judge is configured and reachable-by-config."""
    return bool(independent_judge_model(config))


# ---------------------------------------------------------------------------
# Dispositions
# ---------------------------------------------------------------------------


class FailOpenDisposition(StrEnum):
    """What to do when post-verify dispatch fails open (judge unavailable)."""

    #: Non-self-mod class (or unclassed): proceed (APPROVE) but ledger + alarm.
    FAIL_OPEN_LEDGERED = "fail_open_ledgered"
    #: Self-mod class with the fail-closed flag on: STOP the merge + escalate.
    FAIL_CLOSED_STOP = "fail_closed_stop"


class IndependenceDisposition(StrEnum):
    """Independence-availability decision for a classed change."""

    #: An independent family is configured — route the verdict to it.
    INDEPENDENT_AVAILABLE = "independent_available"
    #: No independent family, non-self-mod: proceed same-family + ledger.
    DEGRADED_SAME_FAMILY = "degraded_same_family"
    #: No independent family, self-mod: escalate to HITL (never merge silently).
    DEGRADED_SELF_MOD_HITL = "degraded_self_mod_hitl"


def disposition_for_fail_open(
    classes: frozenset[BlastRadiusClass],
    *,
    self_mod_fail_closed_enabled: bool,
) -> FailOpenDisposition:
    """Decide fail-open handling for a dispatch failure on a (possibly) classed change.

    Self-modification + the fail-closed flag → STOP. Everything else remains
    fail-open but the caller MUST ledger + alarm it.
    """
    if is_self_modification(classes) and self_mod_fail_closed_enabled:
        return FailOpenDisposition.FAIL_CLOSED_STOP
    return FailOpenDisposition.FAIL_OPEN_LEDGERED


def disposition_for_independence(
    classes: frozenset[BlastRadiusClass],
    *,
    independent_available: bool,
) -> IndependenceDisposition:
    """Decide independence routing for a classed change.

    Precondition: ``requires_independent_verdict(classes)`` is True (unclassed
    changes never reach here — the ordinary path is untouched).
    """
    if independent_available:
        return IndependenceDisposition.INDEPENDENT_AVAILABLE
    if is_self_modification(classes):
        return IndependenceDisposition.DEGRADED_SELF_MOD_HITL
    return IndependenceDisposition.DEGRADED_SAME_FAMILY


# ---------------------------------------------------------------------------
# Append-only ledger IO
# ---------------------------------------------------------------------------

FAIL_OPEN_LEDGER_NAME = "fail_open_ledger.jsonl"


def ledger_path_for(config: HydraFlowConfig) -> Path:
    """Resolve ``<data_root>/diagnostics/fail_open_ledger.jsonl``."""
    return config.diagnostics_dir / FAIL_OPEN_LEDGER_NAME


# Ledger record ``kind`` values.
KIND_FAIL_OPEN = "fail_open"
KIND_INDEPENDENCE_UNAVAILABLE = "independence_unavailable"
KIND_CLASSED_VERDICT = "classed_verdict"


def _append(path: Path, record: dict[str, object]) -> bool:
    """Append one JSON record to the ledger. Best-effort; never raises.

    Returns True on success, False on any IO error (the ledger is fail-visible
    telemetry, and a telemetry write must never break the review pipeline).
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
        return True
    except OSError:
        logger.debug("fail-open ledger append failed path=%s", path, exc_info=True)
        return False


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def record_fail_open(
    path: Path,
    *,
    lens: str | None,
    pr: int | None,
    surface: str,
    classes: frozenset[BlastRadiusClass],
    disposition: FailOpenDisposition,
    reason: str,
    ts: str | None = None,
) -> bool:
    """Ledger a fail-open (judge-unavailable → work passed) event."""
    return _append(
        path,
        {
            "ts": ts or _now_iso(),
            "kind": KIND_FAIL_OPEN,
            "lens": lens,
            "pr": pr,
            "surface": surface,
            "failure_class": sorted(str(c) for c in classes),
            "self_modification": is_self_modification(classes),
            "disposition": str(disposition),
            "reason": reason,
        },
    )


def record_independence_unavailable(
    path: Path,
    *,
    lens: str | None,
    pr: int | None,
    surface: str,
    classes: frozenset[BlastRadiusClass],
    disposition: IndependenceDisposition,
    ts: str | None = None,
) -> bool:
    """Ledger a degraded-mode ``independence-unavailable`` event.

    Never silent: a classed change proceeded with a same-family verdict (or a
    self-mod change escalated to HITL) because no independent family was
    configured/reachable.
    """
    return _append(
        path,
        {
            "ts": ts or _now_iso(),
            "kind": KIND_INDEPENDENCE_UNAVAILABLE,
            "lens": lens,
            "pr": pr,
            "surface": surface,
            "failure_class": sorted(str(c) for c in classes),
            "self_modification": is_self_modification(classes),
            "disposition": str(disposition),
        },
    )


def record_classed_verdict(
    path: Path,
    *,
    lens: str | None,
    pr: int | None,
    surface: str,
    classes: frozenset[BlastRadiusClass],
    independent: bool,
    judge_family: str,
    verdict: str,
    dissent: bool,
    ts: str | None = None,
) -> bool:
    """Ledger a verdict on a classed change (coverage + disagreement-by-family).

    ``independent`` marks whether the verdict came from an independent family;
    ``dissent`` marks whether that judge dissented (VETO or a blocking
    disagreement) — the empirical measure of correlated blindness the budget is
    catching, partitioned by ``judge_family`` for the disagreement-by-family
    metric.
    """
    return _append(
        path,
        {
            "ts": ts or _now_iso(),
            "kind": KIND_CLASSED_VERDICT,
            "lens": lens,
            "pr": pr,
            "surface": surface,
            "failure_class": sorted(str(c) for c in classes),
            "independent": independent,
            "judge_family": judge_family,
            "verdict": verdict,
            "dissent": dissent,
        },
    )


def read_records(path: Path) -> list[dict[str, object]]:
    """Read all ledger records. Tolerant of missing file / malformed lines."""
    if not path.exists():
        return []
    records: list[dict[str, object]] = []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            records.append(obj)
    return records


# ---------------------------------------------------------------------------
# Shewhart control limit on the fail-open rate
# ---------------------------------------------------------------------------


def _day_bucket(ts: object) -> str | None:
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).astimezone(UTC).date().isoformat()
    except ValueError:
        return None


def daily_fail_open_counts(records: Sequence[dict[str, object]]) -> dict[str, int]:
    """Fail-open events bucketed by UTC day (the c-chart observation series)."""
    counts: dict[str, int] = defaultdict(int)
    for r in records:
        if r.get("kind") != KIND_FAIL_OPEN:
            continue
        day = _day_bucket(r.get("ts"))
        if day is not None:
            counts[day] += 1
    return dict(counts)


def rolling_kind_count(
    records: Sequence[dict[str, object]],
    now: datetime,
    *,
    days: int,
    kind: str,
) -> int:
    """Count independence-ledger records of *kind* in the trailing *days* window.

    The rolling-window counterpart of :func:`daily_fail_open_counts` (which
    buckets per UTC day for the c-chart). The second-order vitals capstone reads
    ONE per-window observation per series, so it needs the count of a single
    ``kind`` (``fail_open`` / ``independence_unavailable``) whose ``ts`` falls in
    ``[now - days, now]``. Owning this windowed count HERE — beside the ledger it
    reads — lets the capstone obtain the independence reading by import (one
    source of truth), rather than re-deriving the window/kind filter itself, the
    same way it reads escapes/interventions/audit from their owners' metrics.
    Records with a missing/unparseable or out-of-window ``ts`` are skipped; a
    naive timestamp is interpreted in *now*'s timezone.
    """
    cutoff = now - timedelta(days=days)
    count = 0
    for r in records:
        if r.get("kind") != kind:
            continue
        raw = r.get("ts")
        if not isinstance(raw, str):
            continue
        try:
            ts = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=now.tzinfo)
        if cutoff <= ts <= now:
            count += 1
    return count


def shewhart_c_chart_ucl(counts: Sequence[float]) -> float:
    """Shewhart c-chart upper control limit: ``cbar + 3*sqrt(cbar)``.

    A c-chart models counts of defects per constant-size sample (here: fail-open
    events per day). ``cbar`` is the mean count; the 3-sigma UCL is the classic
    Shewhart rule ("sampling effort follows observed variation"). Returns 0.0
    for an empty series.
    """
    if not counts:
        return 0.0
    cbar = sum(counts) / len(counts)
    return cbar + 3.0 * math.sqrt(cbar)


def fail_open_rate_breach(
    records: Sequence[dict[str, object]],
    *,
    min_days: int = 3,
) -> tuple[bool, float, int]:
    """Whether today's fail-open count breaches the c-chart UCL.

    Returns ``(breached, ucl, latest_count)``. Requires at least ``min_days``
    of history before it can fire — a control limit computed from one or two
    points is noise, not signal. The latest day is compared against the UCL
    computed over the PRIOR days (so a spike day cannot inflate its own limit).
    """
    counts_by_day = daily_fail_open_counts(records)
    if len(counts_by_day) < min_days:
        return (False, 0.0, 0)
    ordered_days = sorted(counts_by_day)
    latest_day = ordered_days[-1]
    latest_count = counts_by_day[latest_day]
    prior = [float(counts_by_day[d]) for d in ordered_days[:-1]]
    ucl = shewhart_c_chart_ucl(prior)
    return (latest_count > ucl, ucl, latest_count)


# ---------------------------------------------------------------------------
# Aggregate metrics for the calibration report / dashboard panel
# ---------------------------------------------------------------------------


def calibration_metrics(records: Sequence[dict[str, object]]) -> dict[str, object]:
    """Compute the judge-independence slice of the gauntlet-calibration picture.

    Returns a plain dict (JSON-serialisable) used by both the generated report
    and the dashboard panel:

    - ``classed_verdicts`` / ``independent_verdicts`` / ``pct_independent``
    - ``fail_open_total`` and the daily counts + c-chart UCL / breach
    - ``independence_unavailable_total``
    - ``disagreement_by_family`` — {family: {"verdicts": n, "dissents": n}}
    """
    classed = [r for r in records if r.get("kind") == KIND_CLASSED_VERDICT]
    independent = [r for r in classed if r.get("independent") is True]
    fail_open = [r for r in records if r.get("kind") == KIND_FAIL_OPEN]
    unavailable = [r for r in records if r.get("kind") == KIND_INDEPENDENCE_UNAVAILABLE]

    by_family: dict[str, dict[str, int]] = defaultdict(
        lambda: {"verdicts": 0, "dissents": 0}
    )
    for r in independent:
        fam = str(r.get("judge_family") or "unknown")
        by_family[fam]["verdicts"] += 1
        if r.get("dissent") is True:
            by_family[fam]["dissents"] += 1

    pct_independent = (
        round(100.0 * len(independent) / len(classed), 1) if classed else 0.0
    )
    breached, ucl, latest = fail_open_rate_breach(records)
    return {
        "classed_verdicts": len(classed),
        "independent_verdicts": len(independent),
        "pct_independent": pct_independent,
        "fail_open_total": len(fail_open),
        "fail_open_daily": daily_fail_open_counts(records),
        "fail_open_ucl": round(ucl, 2),
        "fail_open_latest_day_count": latest,
        "fail_open_rate_breached": breached,
        "independence_unavailable_total": len(unavailable),
        "disagreement_by_family": {k: dict(v) for k, v in by_family.items()},
    }
