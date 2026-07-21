"""Prompt-refinement synthesis support for SkillPromptEvalLoop (#9724).

Pure logic only: context assembly (with the holdout-exclusion invariant),
LLM-response patch parsing, and pre-eval tripwires. The loop owns LLM and
subprocess spawns; nothing here talks to the network.

Holdout invariant: a case directory carrying a ``HOLDOUT`` marker is a
held-out honeypot. It must NEVER enter refiner context — the synthesizer
cannot overfit to traps it cannot see. ``assemble_refine_context`` raises on
holdout input; validation (loop side) always includes 100% of holdouts.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

SKILL_BUILDER_MODULES: dict[str, str] = {
    "diff-sanity": "src/diff_sanity.py",
    "scope-check": "src/scope_check.py",
    "plan-compliance": "src/plan_compliance.py",
    "test-adequacy": "src/test_adequacy.py",
    "discover-completeness": "src/discover_completeness.py",
    "shape-coherence": "src/shape_coherence.py",
}

# Skills eligible for auto-merge self-refinement. Must stay a SUBSET of
# SKILL_BUILDER_MODULES, and every member MUST have held-out honeypot attack
# coverage in the adversarial corpus (a ``HOLDOUT`` marker dir whose
# ``expected_catcher`` is the skill) — the corpus-runner suite pins this
# precondition per skill.
#
# The overfit precondition: auto-refinement's only guard against a synthesized
# patch overfitting to the single regressed case is the holdout gate — the
# candidate must survive 100% of the skill's honeypots, which the synthesizer
# never saw (``assemble_refine_context`` refuses holdout input). A skill with
# NO holdout coverage has no such gate, so an auto-merge candidate for it could
# silently overfit; we refuse to auto-refine it (outcome ``not_refinable``)
# until holdouts exist.
#
# #10014 closed the #9724 follow-up: ``plan-compliance``,
# ``discover-completeness``, and ``shape-coherence`` gained holdout attack
# honeypots, so every builder skill is now refinable. A NEW skill starts
# outside this set until its holdout lands.
REFINABLE_SKILLS: frozenset[str] = frozenset(
    {
        "diff-sanity",
        "scope-check",
        "plan-compliance",
        "test-adequacy",
        "discover-completeness",
        "shape-coherence",
    }
)

PROMPT_LENGTH_DRIFT_LIMIT = 0.30

_HOLDOUT_MARKER = "HOLDOUT"
_DIFF_FENCE = re.compile(r"```diff\n(.*?)```", re.DOTALL)

# A git-format patch can touch a path via several independent line shapes, and
# a single bundled patch may mix sections that use different shapes. Any ONE
# of these lines is sufficient evidence that a path is a target of the patch:
#   - `diff --git a/<old> b/<new>` header: present for every file section,
#     including pure renames and deletions that carry no ---/+++ hunk lines.
#   - `--- a/<path>` / `+++ b/<path>`: the classic hunk header shape. When a
#     side is `/dev/null` (pure add or pure delete) it is a marker, not a
#     path, and simply fails to match the `a/`/`b/` prefix here.
#   - `rename from <path>` / `rename to <path>`: a pure rename has no hunk at
#     all, only these two lines.
_PATCH_DIFF_GIT_HEADER = re.compile(r"^diff --git a/(\S+) b/(\S+)$", re.MULTILINE)
_PATCH_OLD_SIDE = re.compile(r"^--- a/(.+)$", re.MULTILINE)
_PATCH_NEW_SIDE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_PATCH_RENAME = re.compile(r"^rename (?:from|to) (.+)$", re.MULTILINE)


class PatchParseError(ValueError):
    """LLM response carried no parseable ```diff fence."""


class PromptRenderError(RuntimeError):
    """A skill builder module could not be loaded/rendered for the length gate."""


# A fixed, minimal unified diff used only to *render* a builder's prompt so its
# length can be measured. Its content is irrelevant to the drift ratio (the same
# fixture feeds the before-patch and after-patch renders); it just has to be a
# plausible ``diff`` argument for every builder signature.
_LENGTH_PROBE_DIFF = (
    "--- a/probe.py\n+++ b/probe.py\n@@ -1 +1 @@\n-old_value\n+new_value\n"
)

# Skill-specific probe inputs for the length gate. The document-judging
# builders (and ``plan-compliance``) return "" without their input document
# — under the generic diff-only probe their before/after renders were both
# empty, so ``length_drift_exceeds`` measured nothing and the ±30% gate was
# a silent no-op for them (#10014). Fixed stand-in documents make the gate
# real; content is irrelevant (same fixture feeds both renders), it just has
# to be non-empty. Keyed per skill so builders without ``**_kwargs`` never
# receive unexpected keywords.
_LENGTH_PROBE_DOCUMENT = "length-probe stand-in document body\n"
_LENGTH_PROBE_EXTRA_KWARGS: dict[str, dict[str, str]] = {
    "plan-compliance": {"plan_text": "## File Delta\n- Modify `probe.py`\n"},
    "discover-completeness": {
        "issue_body": _LENGTH_PROBE_DOCUMENT,
        "brief": _LENGTH_PROBE_DOCUMENT,
    },
    "shape-coherence": {
        "discover_brief": _LENGTH_PROBE_DOCUMENT,
        "proposal": _LENGTH_PROBE_DOCUMENT,
    },
}


def assemble_refine_context(
    repo_root: Path, case_dir: Path, skill_name: str, failure_transcript: str
) -> str:
    if (case_dir / _HOLDOUT_MARKER).is_file():
        msg = f"{case_dir.name} is a holdout honeypot — refusing refiner context"
        raise ValueError(msg)
    builder_rel = SKILL_BUILDER_MODULES[skill_name]
    builder_src = (repo_root / builder_rel).read_text(encoding="utf-8")
    readme = (
        (case_dir / "README.md").read_text(encoding="utf-8")
        if (case_dir / "README.md").is_file()
        else ""
    )
    expected = (
        (case_dir / "expected_transcript.txt").read_text(encoding="utf-8")
        if (case_dir / "expected_transcript.txt").is_file()
        else ""
    )
    return (
        f"You maintain the `{skill_name}` review-skill prompt in HydraFlow.\n"
        f"The adversarial corpus case `{case_dir.name}` regressed PASS->FAIL.\n\n"
        f"## Case description\n{readme}\n\n"
        f"## Expected transcript (what a correct run looks like)\n{expected}\n\n"
        f"## Actual failing transcript\n{failure_transcript}\n\n"
        f"## Current builder module ({builder_rel})\n```python\n{builder_src}\n```\n\n"
        "Produce a minimal unified diff against ONLY that builder module that "
        "makes the skill catch this case again without loosening its judgment "
        "elsewhere. Reply with a single ```diff fence."
    )


def parse_patch_response(text: str) -> str:
    m = _DIFF_FENCE.search(text)
    if not m or not m.group(1).strip():
        raise PatchParseError("no ```diff fence in refiner response")
    return m.group(1).strip() + "\n"


def _collect_patch_targets(patch_text: str) -> set[str]:
    """Every path the patch touches, from every line shape a git-format patch
    may use to name a file — including sections (deletions, pure renames)
    that carry no `+++ b/<path>` line at all."""
    targets: set[str] = set()
    for old, new in _PATCH_DIFF_GIT_HEADER.findall(patch_text):
        targets.add(old)
        targets.add(new)
    targets.update(_PATCH_OLD_SIDE.findall(patch_text))
    targets.update(_PATCH_NEW_SIDE.findall(patch_text))
    targets.update(_PATCH_RENAME.findall(patch_text))
    return targets


def check_tripwires(patch_text: str, skill_name: str, repo_root: Path) -> list[str]:
    """Pre-eval hard gates. Empty list means the candidate may proceed to eval."""
    reasons: list[str] = []
    allowed = SKILL_BUILDER_MODULES[skill_name]
    targets = _collect_patch_targets(patch_text)
    if not targets:
        reasons.append("patch has no recognizable file targets")
    for t in sorted(targets):
        if t.startswith("tests/trust/"):
            reasons.append(
                f"patch edits the corpus itself ({t}) — tests/trust/** is off-limits"
            )
        elif t != allowed:
            reasons.append(f"patch may only touch {allowed}, found {t}")
    return reasons


def select_live_validation_sample(
    cases_dir: Path, regressed_case_id: str, skill_name: str, budget: int
) -> list[str]:
    """Small sample of the validation-case set to force through the real
    agent CLI during refine-candidate live re-validation (#10063), bounded
    by *budget*.

    Without this, ``_validate_candidate`` re-judges the candidate patch
    against ``expected_transcript.txt`` fixtures produced by the OLD
    prompt — a candidate that subtly breaks prompt->transcript behavior can
    pass validation without ever exercising the real CLI. The regressed
    case always takes priority (budget permitting): it is the one whose
    behavior the candidate patch is trying to restore, so proving it
    against a REAL transcript is the highest-value check. Remaining budget
    is spent on a deterministic (sorted) sample of *skill_name*'s OWN
    held-out honeypots — a holdout belonging to a DIFFERENT skill would
    return ``SKIPPED`` under ``--live-skill <skill_name>`` before any
    transcript is loaded (no CLI call, no signal), so including one would
    silently shrink the effective sample. Benign (``"none"``) sentinels are
    never sampled — fixture replay already fully exercises their parser
    path, and they carry no signal about the candidate's target-case fix.

    ``budget <= 0`` returns ``[]`` — the caller's default (no
    ``--force-live-cases`` flag), so every validation case still replays
    its fixture. Keeps CI/non-live runs deterministic.

    Scans the WORKTREE's cases dir directly (never imports tests code,
    mirroring :func:`discover_validation_case_ids`). A missing dir still
    yields the regressed case alone (budget permitting) — the caller's
    ``--cases`` filter is the ground truth for what actually runs.
    """
    if budget <= 0:
        return []
    selected = [regressed_case_id]
    if cases_dir.is_dir():
        holdouts = sorted(
            p.name
            for p in cases_dir.iterdir()
            if p.is_dir()
            and p.name != regressed_case_id
            and (p / _HOLDOUT_MARKER).is_file()
            and _case_expected_catcher(p) == skill_name
        )
        selected.extend(holdouts)
    return selected[:budget]


def _case_expected_catcher(case_dir: Path) -> str:
    """Best-effort read of ``expected_catcher.txt``; ``""`` when absent."""
    path = case_dir / "expected_catcher.txt"
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def discover_validation_case_ids(cases_dir: Path, regressed_case_id: str) -> list[str]:
    """Case ids a candidate prompt must survive during loop-side validation.

    Returns the regressed case plus every holdout honeypot (a ``HOLDOUT`` marker
    dir) and every benign sentinel (``expected_catcher.txt == "none"``), deduped
    (a benign holdout satisfies both tests) and sorted for a stable ``--cases``
    argument. 100% of holdouts are always included: the synthesizer never saw
    them (``assemble_refine_context`` refuses holdout input), so passing them all
    proves the candidate did not overfit to traps it could not read.

    Scans the WORKTREE's cases dir (never imports tests code). A missing dir
    yields just the regressed id.
    """
    ids: set[str] = {regressed_case_id}
    if not cases_dir.is_dir():
        return sorted(ids)
    for case_dir in cases_dir.iterdir():
        if not case_dir.is_dir():
            continue
        if (case_dir / _HOLDOUT_MARKER).is_file():
            ids.add(case_dir.name)
            continue
        catcher = case_dir / "expected_catcher.txt"
        if catcher.is_file() and catcher.read_text(encoding="utf-8").strip() == "none":
            ids.add(case_dir.name)
    return sorted(ids)


def _builder_func_name(skill_name: str) -> str:
    """``diff-sanity`` → ``build_diff_sanity_prompt`` (skill_registry convention)."""
    return "build_" + skill_name.replace("-", "_") + "_prompt"


def render_builder_prompt(builder_module_path: Path, skill_name: str) -> str:
    """Render *skill_name*'s prompt by executing its builder module in isolation.

    Loads the module fresh from *builder_module_path* via
    ``importlib.util.spec_from_file_location`` under a throwaway name, so the host
    process's already-imported ``src`` modules are never clobbered — the loop
    patches ONE builder inside a worktree and must not poison its own live
    imports by reloading them. Calls the module's ``build_<skill>_prompt`` on a
    fixed fixture diff; the caller measures the returned length before and after
    the patch for the ±30% drift tripwire.

    Raises :class:`PromptRenderError` when the module can't be loaded or defines
    no builder function.

    Suppresses bytecode caching for the duration of the exec: this is a
    throwaway probe module (never registered in ``sys.modules``, discarded
    the moment this call returns), and writing its compiled ``.pyc`` into a
    ``__pycache__`` under *builder_module_path* would leave collateral
    untracked-file noise in whatever tree it's probing — e.g. the refine
    loop calls this against a candidate worktree both before and after
    applying a patch, and a stray ``__pycache__`` there would trip the
    worktree's changed-set assertion (#9724 review, Finding 1).
    """
    func_name = _builder_func_name(skill_name)
    spec = importlib.util.spec_from_file_location(
        f"_refine_probe_{func_name}", builder_module_path
    )
    if spec is None or spec.loader is None:
        msg = f"cannot load builder module at {builder_module_path}"
        raise PromptRenderError(msg)
    module = importlib.util.module_from_spec(spec)
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # surface as a render error, uniform handling
        msg = f"failed to exec builder module at {builder_module_path}: {exc}"
        raise PromptRenderError(msg) from exc
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
    builder = getattr(module, func_name, None)
    if not callable(builder):
        msg = f"{builder_module_path} defines no callable {func_name}"
        raise PromptRenderError(msg)
    # ``builder`` is resolved dynamically (``getattr``), so its return type is
    # opaque to the type-checker; coerce to ``str`` for the length measurement.
    probe_kwargs: dict[str, object] = {
        "issue_number": 0,
        "issue_title": "refine-length-probe",
        "diff": _LENGTH_PROBE_DIFF,
        "plan_text": "",
    }
    probe_kwargs.update(_LENGTH_PROBE_EXTRA_KWARGS.get(skill_name, {}))
    rendered = builder(**probe_kwargs)
    return str(rendered)


def length_drift_exceeds(before: str, after: str) -> bool:
    """True when rendered-prompt length changed by more than ``PROMPT_LENGTH_DRIFT_LIMIT``.

    An empty *before* is degenerate (builder produced nothing pre-patch): any
    non-empty *after* then counts as exceeding, two empties as within.
    """
    if not before:
        return bool(after)
    return abs(len(after) - len(before)) / len(before) > PROMPT_LENGTH_DRIFT_LIMIT
