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
