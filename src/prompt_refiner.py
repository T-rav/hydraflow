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
from pathlib import Path

SKILL_BUILDER_MODULES: dict[str, str] = {
    "diff-sanity": "src/diff_sanity.py",
    "scope-check": "src/scope_check.py",
    "plan-compliance": "src/plan_compliance.py",
    "test-adequacy": "src/test_adequacy.py",
    "discover-completeness": "src/discover_completeness.py",
    "shape-coherence": "src/shape_coherence.py",
}

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
    """
    func_name = _builder_func_name(skill_name)
    spec = importlib.util.spec_from_file_location(
        f"_refine_probe_{func_name}", builder_module_path
    )
    if spec is None or spec.loader is None:
        msg = f"cannot load builder module at {builder_module_path}"
        raise PromptRenderError(msg)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 — surface as a render error, uniform handling
        msg = f"failed to exec builder module at {builder_module_path}: {exc}"
        raise PromptRenderError(msg) from exc
    builder = getattr(module, func_name, None)
    if not callable(builder):
        msg = f"{builder_module_path} defines no callable {func_name}"
        raise PromptRenderError(msg)
    # ``builder`` is resolved dynamically (``getattr``), so its return type is
    # opaque to the type-checker; coerce to ``str`` for the length measurement.
    rendered = builder(
        issue_number=0,
        issue_title="refine-length-probe",
        diff=_LENGTH_PROBE_DIFF,
        plan_text="",
    )
    return str(rendered)


def length_drift_exceeds(before: str, after: str) -> bool:
    """True when rendered-prompt length changed by more than ``PROMPT_LENGTH_DRIFT_LIMIT``.

    An empty *before* is degenerate (builder produced nothing pre-patch): any
    non-empty *after* then counts as exceeding, two empties as within.
    """
    if not before:
        return bool(after)
    return abs(len(after) - len(before)) / len(before) > PROMPT_LENGTH_DRIFT_LIMIT
