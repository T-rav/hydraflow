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
# Backfill order by blast radius: verification_judge (4 builders), shape_runner
# (3), review_advisor (3), then the two-builder modules, then the singles.
GRANDFATHERED: frozenset[str] = frozenset(
    {
        "acceptance_criteria",
        "adjudicate",
        "adr_drift_triage_llm",
        "adversarial_agent_runner",
        "bug_reproducer",
        "classify",
        "decomposition_council",
        "design_ai",
        "discover_completeness",
        "discover_expander",
        "discover_runner",
        "disturbance_dampener_loop",
        "entry_evidence_loop",
        "implement_spec_reviewer",
        "issue_refinement",
        "plan_compliance",
        "plan_touchpoint_expander",
        "pr_red_repair_loop",
        "research_runner",
        "review_advisor",
        "runner",
        "sampled_audit_loop",
        "sandbox_failure_fixer_loop",
        "scope_check",
        "shape_coherence",
        "shape_runner",
        "term_proposer_llm",
        "triage_honeypot",
        "ultra_review",
        "verification_judge",
    }
)
GRANDFATHERED_MAX = 30


def discovered_builders() -> dict[str, list[str]]:
    """Module stem -> prompt-builder function names, found by AST walk."""
    out: dict[str, list[str]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        module = path.stem
        if module in EXCLUDED_MODULES:
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
    """Modules named in a PROMPT_REGISTRY AuditTarget builder path."""
    text = _AUDIT.read_text()
    return {
        m for m in discovered_builders() if re.search(rf"[\"\']{re.escape(m)}\.", text)
    }


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
