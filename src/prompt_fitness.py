"""Prompt fitness — the measured contract's scorecard (ADR-0116).

The completeness ratchet in ``tests/test_prompt_registry_completeness.py`` is a
**gate**: registered or not. ADR-0093 established that a contract also needs a
**measure**, so a decision can be made about whether the thing is getting
better. This module is that measure for the prompt layer.

Three series, deliberately kept together because each one alone is gameable:

* ``registry_coverage`` — registered modules / discovered modules. Rises as the
  ``GRANDFATHERED`` allowlist shrinks.
* ``severity_counts`` — High / Medium / Low over registered prompts, scored by
  the ADR-0087 rubric via ``scripts/audit_prompts.py``.
* ``criterion_fail_rates`` — per-criterion fail rate, so a broad structural
  problem (criterion 3, XML tags, currently near-universal) is visible as one
  number instead of hiding inside 25 individual scorecards.

**This scorecard measures FORM, not outcome.** Per ADR-0116 §6 it is not
admissible on its own: any claim that prompt quality improved must cite the
paired outcome series (verdict pass rate, retry/loop-back count, escape
attribution, cost per successful outcome). A rising score with a falling
outcome is a failure, not a win. :func:`fitness_summary` therefore carries an
explicit ``outcome_paired`` flag, false until that join lands, so a consumer
cannot mistake a form score for a quality claim.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SRC = _REPO / "src"
_AUDIT = _REPO / "scripts" / "audit_prompts.py"

# A prompt builder assembles model-bound text. Convention: build/compose/render
# + "prompt", or the bare ``_build_prompt`` / ``_build_prompt_with_stats`` used
# by the phase runners. Discovery is mechanical, never a curated list, because a
# hand-maintained list of what to check is what let the registry drift.
_BUILDER_NAME = re.compile(
    r"^_?(?:build|compose|render)_.*prompt.*$|^_?build_prompt(?:_with_stats)?$",
    re.IGNORECASE,
)

# Modules excluded by category, with the reason. An unexplained exclusion is how
# a real prompt hides, so every entry names why it is not model-bound text.
EXCLUDED_MODULES: dict[str, str] = {
    "_skill_prompt_eval": "get/set helpers for eval state",
    "prompt_gate_alerts": "operator alerting, not assembly",
    "prompt_stats": "measurement over a built prompt",
    "prompt_refiner": "renders builder source, not a prompt",
    "prompt_fitness": "this module measures prompts, it does not build them",
}

# Modules with builders but no registry entry, as of 2026-07-30. SHRINKS ONLY;
# ``GRANDFATHERED_MAX`` pins the size so a new builder cannot be waved through.
# Started at 30; the first backfill wave cleared the highest-blast-radius modules
# (verification_judge, shape_runner, review_advisor, decomposition_council and
# the acceptance-criteria/spec-review pair). What remains is mostly single-builder
# caretaker and adjacent loops, tracked to zero by GRANDFATHERED_DEADLINE.
GRANDFATHERED: frozenset[str] = frozenset(
    {
        "adversarial_agent_runner",
        "discover_runner",
        "onboarding.design_ai",
        "plan_touchpoint_expander",
        "preflight.runner",
        "research_runner",
    }
)

# Burn-down, not just a ceiling. A ratchet stops the gap growing; it does not
# make it close, so an untouched allowlist stays green forever. GRANDFATHERED_MAX
# is the ceiling *for today*; GRANDFATHERED_DEADLINE is the date by which it must
# have fallen to GRANDFATHERED_TARGET. Past that date the test fails until either
# the backfill lands or the schedule is renegotiated in a commit that says why —
# which makes coverage debt a dated commitment rather than a note.
GRANDFATHERED_DEADLINE = "2026-09-30"
GRANDFATHERED_TARGET = 0
GRANDFATHERED_BURNDOWN_ORIGIN = ("2026-07-30", 30)
GRANDFATHERED_MAX = 6

# Pins for the two other escape hatches. EXCLUDED_MODULES hides a module from
# discovery entirely, and ``unrenderable=True`` registers a prompt that is
# never rendered or scored. Both were unbounded and unguarded, which made
# either one a quieter route to "coverage went up" than the allowlist it sits
# beside. Currently zero unrenderable targets: keep it that way.
EXCLUDED_MODULES_MAX = 5
UNRENDERABLE_MAX = 0


def _module_name(path: Path) -> str:
    """Dotted module name relative to src/, e.g. ``audit.adjudicate``.

    Keyed on the dotted path rather than the bare stem: two files can share a
    stem (``arch/runner.py`` and ``preflight/runner.py`` both stem to
    ``runner``), which would collapse them into one key and hide one of them.
    The dotted name is also the importable name, so a registry entry can be
    constructed from it directly.
    """
    return ".".join(path.relative_to(_SRC).with_suffix("").parts)


def discovered_builders() -> dict[str, list[str]]:
    """Dotted module name -> prompt-builder function names, found by AST walk."""
    out: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        module = _module_name(path)
        if module in EXCLUDED_MODULES or path.stem in EXCLUDED_MODULES:
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except SyntaxError:  # pragma: no cover - src must parse
            continue
        for node in ast.walk(tree):
            if isinstance(
                node, ast.FunctionDef | ast.AsyncFunctionDef
            ) and _BUILDER_NAME.match(node.name):
                out.setdefault(module, []).append(node.name)
    return out


def registered_modules() -> set[str]:
    """Modules owning a builder named by a real ``AuditTarget``.

    Reads the registry structurally rather than grepping the file's text. The
    text search credited coverage for any quoted occurrence of the module name,
    so writing ``"research_runner."`` in a comment or docstring was enough to
    claim a module as covered and delete it from the allowlist — no fixture, no
    scoring, and the coverage number went up. An ``unrenderable`` target is not
    counted: it is registered but never rendered or scored, so crediting it
    would close the gap on paper while measuring nothing.
    """
    audit = _load_audit_module()
    modules = discovered_builders()  # hoisted: this walks every AST under src/
    owners: set[str] = set()
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        qualname = target.builder_qualname
        owners.update(m for m in modules if qualname.startswith(f"{m}."))
    return owners


# Criterion numbers from ADR-0087, for readable reporting.
CRITERIA: dict[int, str] = {
    1: "leads with the request",
    2: "specific over vague",
    3: "XML tag structure",
    4: "examples present",
    5: "output contract stated",
    6: "long-context placement",
    7: "chain-of-thought scaffold",
    8: "edge cases named",
}

SEVERITY_ORDER = ("High", "Medium", "Low")


@dataclass(frozen=True)
class PromptFitness:
    """Fitness scorecard for the prompt layer (ADR-0116)."""

    discovered_modules: int
    registered_modules: int
    grandfathered: int
    severity_counts: dict[str, int] = field(default_factory=dict)
    criterion_fail_rates: dict[int, float] = field(default_factory=dict)
    outcome_paired: bool = False

    @property
    def registry_coverage(self) -> float:
        """Registered / discovered. 1.0 when the allowlist reaches zero."""
        if self.discovered_modules == 0:
            return 1.0
        return self.registered_modules / self.discovered_modules

    @property
    def scored_prompts(self) -> int:
        return sum(self.severity_counts.values())

    @property
    def high_severity_share(self) -> float:
        if self.scored_prompts == 0:
            return 0.0
        return self.severity_counts.get("High", 0) / self.scored_prompts

    def as_dict(self) -> dict[str, object]:
        return {
            "registry_coverage": round(self.registry_coverage, 4),
            "discovered_modules": self.discovered_modules,
            "registered_modules": self.registered_modules,
            "grandfathered": self.grandfathered,
            "scored_prompts": self.scored_prompts,
            "severity_counts": dict(self.severity_counts),
            "high_severity_share": round(self.high_severity_share, 4),
            "criterion_fail_rates": {
                k: round(v, 4) for k, v in sorted(self.criterion_fail_rates.items())
            },
            "outcome_paired": self.outcome_paired,
        }


# Per-prompt setpoints: the exact criteria each prompt fails today (2026-07-30).
# This is the difference between "the fleet average held" and "this prompt did
# not get worse". Fleet aggregates mask per-prompt regression — one prompt can
# degrade while another improves and the mean never moves — so the binding
# check is per prompt, by name. A prompt may only shed failures; gaining one
# fails the build even if every aggregate improves.
PROMPT_BASELINE: dict[str, frozenset[int]] = {
    "acceptance_criteria_build": frozenset({3, 4, 5}),
    "acceptance_criteria_precheck": frozenset({2, 3, 5, 8}),
    "adr_drift_triage": frozenset({1, 3, 7, 8}),
    "adr_reviewer": frozenset({3, 7}),
    "agent_build_prompt_first_attempt": frozenset({1}),
    "agent_build_prompt_with_prior_failure": frozenset({1}),
    "agent_build_prompt_with_review_feedback": frozenset({1}),
    "agent_pre_quality_review": frozenset({3, 5, 8}),
    "agent_pre_quality_run_tool": frozenset({1, 2, 3, 5, 8}),
    "agent_quality_fix": frozenset({2, 3, 5, 8}),
    "audit_adjudicate": frozenset({3, 4, 7, 8}),
    "bug_reproducer": frozenset({3, 8}),
    "conflict_build": frozenset({1, 3, 8}),
    "conflict_rebuild": frozenset({1, 3, 8}),
    "decomposition_council_direction": frozenset({3, 8}),
    "decomposition_council_validation": frozenset({1, 3, 6}),
    "diagnostic_runner": frozenset({1, 3, 4, 7, 8}),
    "diff_sanity": frozenset({3, 5, 8}),
    "discover_completeness": frozenset({1, 3, 5, 7}),
    "discover_expander": frozenset({3, 5, 8}),
    "disturbance_dampener": frozenset({3, 4, 5}),
    "entry_evidence": frozenset({1, 3, 4, 8}),
    "hitl_build_prompt": frozenset({3, 8}),
    "implement_spec_review": frozenset({3, 4}),
    "intervention_classify": frozenset({3, 4, 7, 8}),
    "issue_refinement_dup": frozenset({8}),
    "issue_refinement_priority": frozenset({8}),
    "plan_compliance": frozenset({3, 5, 7}),
    "plan_reviewer": frozenset({3}),
    "planner_build_prompt_first_attempt": frozenset({1, 3}),
    "planner_retry": frozenset({1, 3, 4, 5}),
    "pr_red_repair_dispatch": frozenset({3, 4, 8}),
    "pr_unsticker_ci_fix": frozenset({1, 3, 4, 5, 8}),
    "pr_unsticker_ci_timeout": frozenset({1, 3, 5, 8}),
    "review_advisor_midflight": frozenset({3, 8}),
    "review_advisor_postverify": frozenset({3, 4, 7}),
    "review_advisor_preflight": frozenset({3, 4}),
    "reviewer_build_review": frozenset({1, 3, 7}),
    "reviewer_ci_fix": frozenset({1, 2, 3, 5, 7}),
    "reviewer_review_fix": frozenset({3, 4, 5, 7}),
    "sampled_audit": frozenset({1, 3, 4, 7, 8}),
    "sandbox_failure_fixer": frozenset({3, 4, 5, 8}),
    "scope_check": frozenset({2, 3, 5, 7, 8}),
    "shape_coherence": frozenset({1, 3, 4, 5, 7}),
    "shape_runner_advocate": frozenset({1, 3, 4, 5, 7, 8}),
    "shape_runner_critic": frozenset({1, 3, 4, 5, 8}),
    "shape_runner_turn": frozenset({1, 3, 4}),
    "spec_match_requirements_gap": frozenset({2, 3, 5, 8}),
    "term_proposer": frozenset({1, 3, 7}),
    "test_adequacy": frozenset({2, 3, 5}),
    "test_adequacy_verifier": frozenset({1, 3, 5, 7}),
    "triage_build_prompt": frozenset({1, 3}),
    "triage_decomposition": frozenset({1, 3, 4, 8}),
    "triage_honeypot": frozenset({1, 4, 8}),
    "ultra_review": frozenset({3, 4, 8}),
    "verification_judge_code_validation": frozenset({3, 4, 7}),
    "verification_judge_instructions_validation": frozenset({1, 3, 4}),
    "verification_judge_precheck": frozenset({3, 4}),
    "verification_judge_refinement": frozenset({1, 3}),
}


@dataclass(frozen=True)
class PromptRegression:
    """One prompt that gained a failing criterion, or stopped rendering."""

    prompt: str
    new_fails: frozenset[int]
    resolved: frozenset[int]
    unrenderable: bool = False


def per_prompt_scores() -> dict[str, frozenset[int]]:
    """Prompt name -> currently failing criterion numbers.

    A prompt whose fixture no longer renders is omitted, which
    :func:`prompt_regressions` reports as a regression rather than silently
    dropping from the scored set.
    """
    audit = _load_audit_module()
    out: dict[str, frozenset[int]] = {}
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        try:
            rendered = audit.render_target(target)
        except Exception:  # pragma: no cover - surfaced as unrenderable below
            continue
        card = audit.score(rendered)
        out[target.name] = frozenset(
            k for k, verdict in card.scores.items() if verdict == "Fail"
        )
    return out


# ---------------------------------------------------------------------------
# Unformatted-placeholder leak. Not an ADR-0087 rubric criterion — a
# correctness bug the rubric cannot see. Shared prompt fragments are written as
# ``str.format`` templates (see ``runner_constants.MEMORY_SUGGESTION_PROMPT``);
# a caller that interpolates the constant into an f-string without
# ``.format(context=...)`` ships a literal "{context}" to the model. Two callers
# had done exactly that (``shape_runner``, ``discover_runner``), found by the
# 2026-07-30 fixture backfill, invisible to all eight rubric criteria.
#
# Braces are legitimate inside code: fenced blocks, inline spans, and diff lines
# all carry f-strings and deliberate ``### P{N}`` templates. Those are stripped
# before scanning, so the check fires only on a placeholder left in prose.
# ---------------------------------------------------------------------------

_FENCED_CODE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`\n]*`")
_DIFF_LINE = re.compile(r"^[+-].*$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


def placeholder_leaks(rendered: str) -> frozenset[str]:
    """Names of ``str.format`` placeholders left unsubstituted in prose."""
    prose = _FENCED_CODE.sub(" ", rendered)
    prose = _INLINE_CODE.sub(" ", prose)
    prose = _DIFF_LINE.sub(" ", prose)
    return frozenset(m.group(1) for m in _PLACEHOLDER.finditer(prose))


def prompt_placeholder_leaks() -> dict[str, frozenset[str]]:
    """Prompt name -> leaked placeholder names, for prompts that leak any."""
    audit = _load_audit_module()
    out: dict[str, frozenset[str]] = {}
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        try:
            rendered = audit.render_target(target)
        except Exception:  # pragma: no cover - reported by prompt_regressions
            continue
        leaked = placeholder_leaks(rendered)
        if leaked:
            out[target.name] = leaked
    return out


def prompt_regressions() -> list[PromptRegression]:
    """Prompts that gained a failing criterion, or stopped rendering.

    Improvements are reported too (``resolved``) so the baseline can be tightened
    deliberately rather than drifting loose.
    """
    current = per_prompt_scores()
    out: list[PromptRegression] = []
    for name, baseline in sorted(PROMPT_BASELINE.items()):
        if name not in current:
            out.append(
                PromptRegression(name, frozenset(), frozenset(), unrenderable=True)
            )
            continue
        now = current[name]
        gained = now - baseline
        if gained:
            out.append(PromptRegression(name, gained, baseline - now))
    return out


def baseline_criterion_fail_rates() -> dict[int, float]:
    """Fail rates implied by ``PROMPT_BASELINE`` — the aggregates, derived.

    Hand-pinned fleet ceilings are not stable under coverage changes: adding a
    newly-measured bad prompt raises every average even though nothing
    regressed, so the only way to keep a pinned number green is to raise it,
    which is indistinguishable from covering up a real regression. Deriving the
    aggregates from the per-prompt baselines removes that ambiguity — the
    expectation updates only when a baseline entry is added or tightened, and
    there is no constant left to fudge.
    """
    total = len(PROMPT_BASELINE)
    if not total:
        return dict.fromkeys(CRITERIA, 0.0)
    return {
        c: sum(1 for fails in PROMPT_BASELINE.values() if c in fails) / total
        for c in CRITERIA
    }


def baseline_high_severity_share() -> float:
    """High-severity share implied by ``PROMPT_BASELINE``."""
    total = len(PROMPT_BASELINE)
    if not total:
        return 0.0
    highs = sum(
        1
        for fails in PROMPT_BASELINE.values()
        if len(fails) >= 2 or 1 in fails or 6 in fails
    )
    return highs / total


def _load_audit_module():
    """Import scripts/audit_prompts.py without requiring it on sys.path."""
    spec = importlib.util.spec_from_file_location("_audit_prompts", _AUDIT)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {_AUDIT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_audit_prompts", module)
    spec.loader.exec_module(module)
    return module


def fitness_summary(*, outcome_paired: bool = False) -> PromptFitness:
    """Compute the prompt-layer fitness scorecard.

    Scores every registered prompt by rendering its fixture and applying the
    ADR-0087 rubric. Discovery counts come from the same convention the
    completeness ratchet uses, so coverage and the gate cannot disagree.
    """
    audit = _load_audit_module()
    discovered = set(discovered_builders())
    registered = registered_modules()

    severity_counts: dict[str, int] = dict.fromkeys(SEVERITY_ORDER, 0)
    fail_counts: dict[int, int] = dict.fromkeys(CRITERIA, 0)
    scored = 0

    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        try:
            rendered = audit.render_target(target)
        except Exception:  # pragma: no cover - a broken fixture is its own finding
            continue
        card = audit.score(rendered)
        severity_counts[audit.severity_for(card)] += 1
        scored += 1
        for criterion, verdict in card.scores.items():
            if verdict == "Fail":
                fail_counts[criterion] = fail_counts.get(criterion, 0) + 1

    rates = {k: (v / scored if scored else 0.0) for k, v in fail_counts.items()}
    return PromptFitness(
        discovered_modules=len(discovered),
        registered_modules=len(registered),
        grandfathered=len(GRANDFATHERED),
        severity_counts=severity_counts,
        criterion_fail_rates=rates,
        outcome_paired=outcome_paired,
    )
