# tests/test_ci_path_filter_completeness.py
"""Ratchet: every top-level path is either tested in CI or exempt with a reason.

CI decides whether to run the Python test job from a ``dorny/paths-filter``
allowlist in ``.github/workflows/ci.yml``. An allowlist maintained by memory
fails the same way a hand-maintained registry fails — silently, by omission —
and it did so three times:

* ``scripts/**`` was absent, so a PR editing ``PROMPT_REGISTRY`` skipped the
  tests that guard it (fixed 2026-07-30, ADR-0116).
* ``docs/wiki/**`` was absent, so ``TermProposerLoop`` merged an alias for the
  bare word "event" with its own PR green, and every subsequent unrelated
  build went red (fixed 2026-07-31, #10926).
* This ratchet itself watched the ``python`` filter, which gates only
  lint/typecheck/security — not the ``test`` job, which actually runs pytest
  and is gated by the separate ``core_python`` filter. ``agents/**`` was in
  ``python`` but not ``core_python``, so the ratchet reported it "covered"
  while the pytest suite (``tests/test_console_conformance.py``) never ran
  for an agents-only PR (fixed 2026-08-14, #11164).

Each was the same defect: an allowlist gap invisible until something merged
green that shouldn't have. A convention nobody can forget beats a convention
everybody agrees with.

So the allowlist is inverted here: a path is in scope for tests **by default**,
and staying out requires a written reason. The failure mode flips from
"forgot to add it, tests silently skipped" to "must say why it is exempt".
The ratchet watches ``core_python`` specifically — the filter whose ``if:``
actually gates the ``test`` job (see ci.yml:323) — rather than ``python``,
which only gates lint/typecheck/security and proves nothing about pytest
coverage.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_CI = _REPO / ".github" / "workflows" / "ci.yml"

# Top-level paths that legitimately do not gate the Python test suite, each
# with the reason. An unexplained exemption is how the next gap hides.
EXEMPT_PATHS: dict[str, str] = {
    "agents": (
        "console decision ledger + persona contracts (ARCH-0001); deliberately "
        "excluded from core_python so ledger-only PRs don't drag in the heavy "
        "smoke/scenario/regression/sandbox lanes. Guarded instead by the "
        "console_ledger paths-filter OR'd into the `audit` job's `if:`, which "
        "runs `make console-conformance` (shape, numbering, personas, chairs, "
        "staleness, git immutability) — see tests/regressions/test_issue_11164.py"
    ),
    "deploy": "deployment manifests; exercised by the sandbox e2e lane, not unit tests",
    "disturbance": "ratchet baselines, read by tests rather than imported by src",
    "repo_wiki": "per-repo knowledge written BY the factory; no code imports it",
    "static": "front-end assets; covered by the src/ui quality lane",
    "templates": "server-rendered HTML; covered by the src/ui quality lane",
}
EXEMPT_PATHS_MAX = 6

# Directories that hold no committed source of any kind.
_IGNORED = {".git", ".github", ".venv", "node_modules", "__pycache__"}


def _core_python_filter_globs() -> list[str]:
    """The expanded glob list under the ``core_python:`` filter in ci.yml.

    Unlike ``python:``, this filter's include list is a single brace-glob
    line (``predicate-quantifier: every`` requires it — see the comment
    above ``core_filter`` in ci.yml), so the braces must be expanded rather
    than read one glob per line.
    """
    text = _CI.read_text(encoding="utf-8")
    block = re.search(
        r"^            core_python:\n((?:              .*\n)+)", text, re.M
    )
    assert block, (
        "could not find the `core_python:` paths-filter block in ci.yml — "
        "this test guards it, so a rename must update this parser rather "
        "than silently matching nothing"
    )
    lines = re.findall(r"^              - '([^']+)'", block.group(1), re.M)
    globs: list[str] = []
    for line in lines:
        if line.startswith("!"):
            continue  # negations subtract from coverage; they never add it
        match = re.fullmatch(r"\{([^{}]*)\}", line)
        globs.extend(match.group(1).split(",") if match else [line])
    return globs


def _covered(top: str, globs: list[str]) -> bool:
    return any(g == top or g.startswith(f"{top}/") for g in globs)


def test_every_top_level_path_is_tested_or_exempt() -> None:
    globs = _core_python_filter_globs()
    tops = sorted(
        p.name
        for p in _REPO.iterdir()
        if p.is_dir() and p.name not in _IGNORED and not p.name.startswith(".")
    )
    uncovered = [t for t in tops if not _covered(t, globs) and t not in EXEMPT_PATHS]
    assert not uncovered, (
        f"Top-level paths in neither the CI `core_python` filter nor "
        f"EXEMPT_PATHS: {uncovered}. A change under these runs NO pytest "
        "tests, so anything guarding them is skipped and the PR goes green "
        "regardless. Add the path to the `core_python` filter in "
        ".github/workflows/ci.yml, or to EXEMPT_PATHS with a reason naming "
        "a real guard. Under-inclusive is merely expensive when a filter "
        "decides whether to TEST — and this is that filter."
    )


def test_exemptions_are_pinned_and_justified() -> None:
    assert len(EXEMPT_PATHS) <= EXEMPT_PATHS_MAX, (
        f"EXEMPT_PATHS grew to {len(EXEMPT_PATHS)} (pinned at "
        f"{EXEMPT_PATHS_MAX}). Exempting a path from the test filter is how "
        "past incidents happened; raise the pin deliberately."
    )
    unexplained = sorted(p for p, why in EXEMPT_PATHS.items() if not why.strip())
    assert not unexplained, f"EXEMPT_PATHS entries with no reason: {unexplained}"


def test_exemptions_are_not_stale() -> None:
    """A path that no longer exists leaves a hole for whatever takes its name."""
    stale = sorted(p for p in EXEMPT_PATHS if not (_REPO / p).exists())
    assert not stale, (
        f"EXEMPT_PATHS names paths that no longer exist: {stale}. Remove them "
        "so the list reflects real decisions."
    )


def test_the_two_paths_that_caused_incidents_stay_covered() -> None:
    """Regression pins for 2026-07-30 (#10856) and 2026-07-31 (#10926).

    Both were fixed by adding a glob; nothing stopped either being dropped
    again, and each removal would be invisible until a build went red for
    someone unrelated.
    """
    globs = _core_python_filter_globs()
    for path, incident in (
        ("scripts", "PROMPT_REGISTRY edits skipped the registry ratchet (ADR-0116)"),
        ("docs/wiki", "a term alias broke the paraphrase lint for everyone (#10926)"),
    ):
        assert any(g.startswith(path) for g in globs), (
            f"'{path}' is no longer in the CI `core_python` filter. It was "
            f"added because: {incident}. Removing it re-opens that exact hole."
        )
