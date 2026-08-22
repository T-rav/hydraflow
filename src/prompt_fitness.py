"""Prompt fitness — the measured contract's scorecard (ADR-0116).

The completeness ratchet in ``tests/test_prompt_registry_completeness.py`` is a
**gate**: registered or not. ADR-0093 established that a contract also needs a
**measure**, so a decision can be made about whether the thing is getting
better. This module is that measure for the prompt layer.

Three series, deliberately kept together because each one alone is gameable:

* ``registry_coverage`` — registered **builders** / discovered builders. Counted
  per builder, not per module: a module with five builders and one fixture used
  to read as fully covered, which reported 100% while five builders had no
  fixture and no score at all.
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
from types import ModuleType

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
#
# ``prompt_refiner`` used to sit here on the grounds that it "renders builder
# source, not a prompt". That is true of ``render_builder_prompt`` and false of
# the module: ``build_refine_prompt`` in the same file returns text ending
# "Reply with a single ```diff fence." A module-level exclusion hid a real
# prompt behind a reason that only covered one of its functions, so exclusions
# that apply to a single function now live in EXCLUDED_BUILDERS instead.
EXCLUDED_MODULES: dict[str, str] = {
    "_skill_prompt_eval": "get/set helpers for eval state",
    "prompt_gate_alerts": "operator alerting, not assembly",
    "prompt_stats": "measurement over a built prompt",
    "prompt_fitness": "this module measures prompts, it does not build them",
}

# Function-level exclusions, keyed ``module.function``. Narrower than excluding
# a whole module, which is the point: the reason has to be true of the one
# thing it exempts.
EXCLUDED_BUILDERS: dict[str, str] = {
    "prompt_refiner.render_builder_prompt": (
        "executes another module's builder in isolation and returns ITS output; "
        "assembles no prompt text of its own"
    ),
}

# Modules with builders but no registry entry. EMPTY as of 2026-07-30: the
# backfill went 30 -> 0 in one PR, so every prompt builder in src/ is now
# registered, rendered to a fixture and scored.
#
# The machinery stays. GRANDFATHERED_MAX = 0 means a new builder cannot be
# waved through at all -- it must be registered, not exempted. If a future
# subsystem genuinely needs to carry debt, raising the ceiling is a deliberate
# edit that also has to move GRANDFATHERED_DEADLINE, because a stale deadline
# with a non-empty allowlist fails the build. That is the point: the debt
# cannot come back quietly.
GRANDFATHERED: frozenset[str] = frozenset({})

# Burn-down, not just a ceiling. A ratchet stops the gap growing; it does not
# make it close, so an untouched allowlist stays green forever. GRANDFATHERED_MAX
# is the ceiling *for today*; GRANDFATHERED_DEADLINE is the date by which it must
# have fallen to GRANDFATHERED_TARGET. Past that date the test fails until either
# the backfill lands or the schedule is renegotiated in a commit that says why —
# which makes coverage debt a dated commitment rather than a note.
#
# "A commit that says why" now has a gate behind it (#10861). The deadline is
# not a bare string that can move for free: every value it has taken is logged
# here paired with the issue/PR that authorized the move, mirroring ADR-0113's
# Precedent/Divergence receipt. Moving the deadline means appending a row with a
# fresh `#<n>` receipt; a bare edit that carries no receipt, or reuses an earlier
# one, fails test_deadline_moves_carry_a_receipt. GRANDFATHERED_DEADLINE is
# derived from the last row so every existing importer is untouched. (The window
# cap in test_burndown_schedule_is_coherent already bounds how *far* a single
# window may reach; the receipt is the orthogonal "who authorized this" gate.)
GRANDFATHERED_SCHEDULE_LOG: tuple[tuple[str, str], ...] = (("2026-09-30", "#10856"),)
GRANDFATHERED_DEADLINE = GRANDFATHERED_SCHEDULE_LOG[-1][0]
GRANDFATHERED_TARGET = 0
GRANDFATHERED_BURNDOWN_ORIGIN = ("2026-07-30", 30)
GRANDFATHERED_MAX = 0

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
                if f"{module}.{node.name}" in EXCLUDED_BUILDERS:
                    continue
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
    audit = load_audit_module()
    modules = discovered_builders()  # hoisted: this walks every AST under src/
    owners: set[str] = set()
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        qualname = target.builder_qualname
        owners.update(m for m in modules if qualname.startswith(f"{m}."))
    return owners


def all_builders() -> set[str]:
    """Every discovered builder as ``module.function``."""
    return {
        f"{m}.{b}" for m, builders in discovered_builders().items() for b in builders
    }


def registered_builders() -> set[str]:
    """Builders with at least one renderable ``AuditTarget``.

    Coverage is counted per *builder*, not per module. Module granularity
    overstated it badly: a module with five builders and one fixture read as
    fully covered, which reported 100% while five builders across four
    already-"covered" modules had no fixture and no score at all. Two of them
    (``reviewer._build_precheck_prompt``, ``spec_match.build_self_review_prompt``)
    had been invisible that way since the registry was built.
    """
    audit = load_audit_module()
    modules = discovered_builders()
    out: set[str] = set()
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        qualname = target.builder_qualname
        leaf = qualname.rsplit(".", 1)[-1]
        for module in modules:
            if qualname.startswith(f"{module}.") and leaf in modules[module]:
                out.add(f"{module}.{leaf}")
    return out


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

    # Counted per BUILDER, not per module: a module with five builders and one
    # fixture used to read as fully covered. Field names kept for compatibility
    # with the existing scorecard consumers.
    discovered_modules: int
    registered_modules: int
    grandfathered: int
    severity_counts: dict[str, int] = field(default_factory=dict)
    criterion_fail_rates: dict[int, float] = field(default_factory=dict)
    outcome_paired: bool = False

    @property
    def registry_coverage(self) -> float:
        """Registered builders / discovered builders."""
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
    "adversarial_agent_compose": frozenset({1, 3, 4}),
    "agent_build_prompt_first_attempt": frozenset({1}),
    "agent_build_prompt_with_prior_failure": frozenset({1}),
    "agent_build_prompt_with_review_feedback": frozenset({1}),
    "agent_pre_quality_review": frozenset({3, 5, 8}),
    "agent_pre_quality_run_tool": frozenset({1, 2, 3, 5, 8}),
    "agent_quality_fix": frozenset({2, 3, 5, 8}),
    # The JSONL lifecycle boundary names the concrete task artifact and its
    # owner, while the supported lifecycle example preserves example coverage.
    "agent_tdd_subagent": frozenset({3, 5}),
    "audit_adjudicate": frozenset({3, 4, 7, 8}),
    "bug_reproducer": frozenset({3, 8}),
    "conflict_build": frozenset({1, 3, 8}),
    "conflict_rebuild": frozenset({1, 3, 8}),
    "decomposition_council_direction": frozenset({3, 8}),
    "decomposition_council_validation": frozenset({3, 6}),
    "diagnostic_runner": frozenset({1, 3, 4, 7, 8}),
    "diff_sanity": frozenset({3, 5, 8}),
    "discover_completeness": frozenset({1, 3, 5, 7}),
    "discover_expander": frozenset({3, 5, 8}),
    "discover_runner": frozenset({1, 3, 4, 7}),
    "disturbance_dampener": frozenset({3, 4, 5}),
    "entry_evidence": frozenset({1, 3, 4, 8}),
    "goal_supervisor_prompt": frozenset({1, 3, 4, 8}),
    "hitl_build_prompt": frozenset({3, 8}),
    "implement_spec_review": frozenset({3, 4}),
    "intervention_classify": frozenset({3, 4, 7, 8}),
    "issue_refinement_dup": frozenset({8}),
    "issue_refinement_priority": frozenset({8}),
    "onboarding_design_ai": frozenset({3, 4, 8}),
    "plan_compliance": frozenset({3, 5, 7}),
    "plan_reviewer": frozenset({3}),
    # RE-REVIEW branch (#11301): inherits the base prompt's criterion-3
    # pin; the added block carries its own reason-first cue so 7 passes.
    "plan_reviewer_rereview": frozenset({3}),
    "plan_touchpoint_expander": frozenset({3, 4, 5, 8}),
    "planner_build_prompt_first_attempt": frozenset({1, 3}),
    "planner_retry": frozenset({1, 3, 4, 5}),
    "pr_red_repair_dispatch": frozenset({3, 4, 8}),
    "pr_unsticker_ci_fix": frozenset({1, 3, 4, 5, 8}),
    "pr_unsticker_ci_timeout": frozenset({1, 3, 5, 8}),
    "preflight_auto_agent": frozenset({1, 4}),
    "prompt_refiner_refine": frozenset({3, 4, 5, 7, 8}),
    "research_runner": frozenset({1, 3, 4, 7, 8}),
    "review_advisor_midflight": frozenset({3, 8}),
    "review_advisor_midflight_section": frozenset({3, 4, 7, 8}),
    "review_advisor_postverify": frozenset({3, 4, 7}),
    "review_advisor_preflight": frozenset({3, 4}),
    "reviewer_build_review": frozenset({1, 3, 7}),
    "reviewer_build_review_quality_gate": frozenset({1, 3, 7}),
    "reviewer_ci_fix": frozenset({1, 2, 3, 5, 7}),
    "reviewer_precheck": frozenset({2, 3, 5, 8}),
    "reviewer_review_fix": frozenset({3, 4, 5, 7}),
    "sampled_audit": frozenset({1, 3, 4, 7, 8}),
    "sandbox_failure_fixer": frozenset({3, 4, 5, 8}),
    "scope_check": frozenset({2, 3, 5, 7, 8}),
    "shape_coherence": frozenset({1, 3, 4, 5, 7}),
    "shape_runner_advocate": frozenset({1, 3, 4, 5, 7, 8}),
    "shape_runner_critic": frozenset({1, 3, 4, 5, 8}),
    "shape_runner_turn": frozenset({1, 3, 4}),
    "spec_match_requirements_gap": frozenset({2, 3, 5, 8}),
    # #10830 phase 2 (2026-08-13): the adversarial intake read. Fails 1/3/4/8
    # at birth — pinned so it can only shed failures from here.
    "spec_review": frozenset({1, 3, 4, 8}),
    "spec_match_self_review": frozenset({1, 3, 5, 7, 8}),
    "term_proposer": frozenset({1, 3}),
    "test_adequacy": frozenset({2, 3, 5}),
    # Repair-in-run prompt (#11593): pinned at its introduction score, in line
    # with its finder/verifier siblings.
    "test_adequacy_repair": frozenset({1, 3, 5, 7, 8}),
    "test_adequacy_verifier": frozenset({1, 3, 5, 7}),
    "triage_build_prompt": frozenset({1, 3}),
    # triage_decomposition removed: its builder went away with the #11298
    # intake auto-decomposition path (flag-rot cleanup), so there is no
    # prompt left to pin.
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
    audit = load_audit_module()
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
# Braces are legitimate inside code: fenced blocks, inline spans, unified-diff
# hunks, and f-string literals all carry braces (``### P{N}`` templates,
# ``f"{year}-W{week:02d}"``) that are content rather than leaks. Each is stripped
# before scanning — crucially, diff stripping is scoped to real hunks, not every
# ``+``/``-`` line, so a ``{placeholder}`` left on a Markdown bullet still fires
# (issue #10865).
# ---------------------------------------------------------------------------

_FENCE_LINE = re.compile(r"^\s*```")
_INLINE_CODE = re.compile(r"`[^`\n]*`")
# Enter diff mode only on a real unified-diff header. A Markdown bullet
# (``- ...`` / ``+ ...``) is NOT a header, so bulleted prose is never mistaken
# for diff content — that conflation (issue #10865) blanked bulleted lines and
# let a ``{placeholder}`` hidden inside a bullet escape the leak scan.
_DIFF_HEADER = re.compile(r"^(?:diff --git |index [0-9a-f]{4,}\.\.|--- |\+\+\+ |@@ )")
# Body lines of a hunk: context (`` ``), added (``+``), removed (``-``), or the
# ``\ No newline at end of file`` marker. Only stripped while inside a hunk.
_DIFF_BODY = re.compile(r"^[ +\-\\]")
# f-string literals carry braces that are content, not placeholders
# (``f"{year}-W{week:02d}"`` quoted inside a review-finding bullet). Triple-
# quoted forms are matched first so ``f"""x{y}"""`` is not read as an empty
# ``f""`` that leaves ``x{y}`` exposed.
_FSTRING = re.compile(
    r"""
    (?<![A-Za-z0-9_])
    (?:[fF][rR]?|[rR][fF])
    (?:
        \"\"\".*?\"\"\"
      | '''.*?'''
      | \"(?:\\.|[^\"\\\n])*\"
      | '(?:\\.|[^'\\\n])*'
    )
    """,
    re.VERBOSE | re.DOTALL,
)
_PLACEHOLDER = re.compile(r"(?<!\{)\{([A-Za-z_][A-Za-z0-9_]*)\}(?!\})")


def _strip_fenced_code(text: str) -> str:
    """Drop fenced code blocks, pairing fences by line rather than by regex.

    A non-greedy ``r"```.*?```"`` breaks on *nested* fences: a prompt that
    embeds a source file inside ```` ```python ```` where that file itself
    contains a ```` ```diff ```` block matches only as far as the inner
    opening fence, leaving the rest of the embedded source exposed as prose.
    That produced a false leak report for ``prompt_refiner_refine``, whose
    whole purpose is to hand a builder's source to the model.

    Toggling on every fence line treats the entire embedded region as code,
    which is the correct reading: everything between the outer fences is
    payload, nesting included.
    """
    out: list[str] = []
    in_code = False
    for line in text.splitlines():
        if _FENCE_LINE.match(line):
            in_code = not in_code
            continue
        if not in_code:
            out.append(line)
    return "\n".join(out)


def _strip_diff_hunks(text: str) -> str:
    """Blank the body of unified-diff hunks, leaving ordinary prose intact.

    The previous rule (``_DIFF_LINE = r"^[+-].*$"``) blanked *every* line
    starting with ``+`` or ``-`` before the placeholder scan, which also erased
    Markdown bullets (``- Use the {context}...``) — so a ``{placeholder}`` left
    inside a bulleted list escaped the leak gate (issue #10865). Diff content is
    only stripped when it is genuinely inside a hunk: entered on a real
    unified-diff header (``diff --git`` / ``index`` / ``--- `` / ``+++ `` /
    ``@@ ``) and left on the first line that is not diff body.

    Known narrowing: prose that resumes immediately after a hunk with no
    intervening non-diff line (e.g. a bullet separated only by blank lines)
    stays in diff mode. Honouring the ``@@`` line counts is out of scope — a
    sampled-audit diff is rendered truncated, so those counts do not hold.
    """
    out: list[str] = []
    in_hunk = False
    for line in text.splitlines():
        if _DIFF_HEADER.match(line):
            in_hunk = True
            continue
        if in_hunk and (not line.strip() or _DIFF_BODY.match(line)):
            continue
        in_hunk = False
        out.append(line)
    return "\n".join(out)


def placeholder_leaks(rendered: str) -> frozenset[str]:
    """Names of ``str.format`` placeholders left unsubstituted in prose."""
    prose = _strip_fenced_code(rendered)
    prose = _INLINE_CODE.sub(" ", prose)
    prose = _strip_diff_hunks(prose)
    prose = _FSTRING.sub(" ", prose)
    return frozenset(m.group(1) for m in _PLACEHOLDER.finditer(prose))


# Prompts whose payload is arbitrary source code, where a brace-wrapped
# identifier is content rather than an unsubstituted placeholder.
#
# This is an exemption, not a detector improvement, because no content-based
# heuristic can win here. ``prompt_refiner_refine`` embeds a builder module
# verbatim inside a ```python fence, and that module contains its own ```diff
# fence — so the fences nest with the same delimiter, which is ambiguous
# markdown that neither a non-greedy regex nor line-level toggling can resolve.
# The prompt's entire purpose is to hand source to the model, so the payload
# will always contain whatever that source contains.
#
# Pinned by size: an exemption with a reason is a decision, one without is rot.
PLACEHOLDER_LEAK_EXEMPT: dict[str, str] = {
    "prompt_refiner_refine": (
        "embeds a builder module's source verbatim for the model to patch; the "
        "module's own f-string templates are payload, not leaked placeholders"
    ),
}
PLACEHOLDER_LEAK_EXEMPT_MAX = 1


def prompt_placeholder_leaks() -> dict[str, frozenset[str]]:
    """Prompt name -> leaked placeholder names, for prompts that leak any."""
    audit = load_audit_module()
    out: dict[str, frozenset[str]] = {}
    for target in audit.PROMPT_REGISTRY:
        if target.unrenderable:
            continue
        try:
            rendered = audit.render_target(target)
        except Exception:  # pragma: no cover - reported by prompt_regressions
            continue
        if target.name in PLACEHOLDER_LEAK_EXEMPT:
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


def load_audit_module() -> ModuleType:
    """Import scripts/audit_prompts.py without requiring it on sys.path.

    Executes the module fresh on every call rather than caching it: two
    calls never return the same object, so callers must not rely on
    identity across calls.
    """
    spec = importlib.util.spec_from_file_location("_audit_prompts", _AUDIT)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load {_AUDIT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("_audit_prompts", module)
    spec.loader.exec_module(module)
    return module


def _load_audit_module() -> ModuleType:
    """Deprecated alias for :func:`load_audit_module`; kept for callers not yet migrated."""
    return load_audit_module()


def fitness_summary(*, outcome_paired: bool = False) -> PromptFitness:
    """Compute the prompt-layer fitness scorecard.

    Scores every registered prompt by rendering its fixture and applying the
    ADR-0087 rubric. Discovery counts come from the same convention the
    completeness ratchet uses, so coverage and the gate cannot disagree.
    """
    audit = load_audit_module()
    # Builder granularity, not module. See registered_builders().
    discovered = all_builders()
    registered = registered_builders()

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
