# tests/test_ci_path_filter_completeness.py
"""Ratchet: every top-level path is either tested in CI or exempt with a reason.

CI decides whether to run the Python test job from a ``dorny/paths-filter``
allowlist in ``.github/workflows/ci.yml``. An allowlist maintained by memory
fails the same way a hand-maintained registry fails — silently, by omission —
and it did so twice in two days:

* ``scripts/**`` was absent, so a PR editing ``PROMPT_REGISTRY`` skipped the
  tests that guard it (fixed 2026-07-30, ADR-0116).
* ``docs/wiki/**`` was absent, so ``TermProposerLoop`` merged an alias for the
  bare word "event" with its own PR green, and every subsequent unrelated
  build went red (fixed 2026-07-31, #10926).

Both were the same defect and the second landed a day after the first, with
the rule already written in a comment directly above the gap. A convention
nobody can forget beats a convention everybody agrees with.

So the allowlist is inverted here: a path is in scope for tests **by default**,
and staying out requires a written reason. The failure mode flips from
"forgot to add it, tests silently skipped" to "must say why it is exempt".
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_CI = _REPO / ".github" / "workflows" / "ci.yml"

# Top-level paths that legitimately do not gate the Python test suite, each
# with the reason. An unexplained exemption is how the next gap hides.
EXEMPT_PATHS: dict[str, str] = {
    "deploy": "deployment manifests; exercised by the sandbox e2e lane, not unit tests",
    "disturbance": "ratchet baselines, read by tests rather than imported by src",
    "repo_wiki": "per-repo knowledge written BY the factory; no code imports it",
    "static": "front-end assets; covered by the src/ui quality lane",
    "templates": "server-rendered HTML; covered by the src/ui quality lane",
}
EXEMPT_PATHS_MAX = 5

# Directories that hold no committed source of any kind.
_IGNORED = {".git", ".github", ".venv", "node_modules", "__pycache__"}


def _python_filter_globs() -> list[str]:
    """The glob list under the ``python:`` filter in ci.yml."""
    text = _CI.read_text(encoding="utf-8")
    block = re.search(r"^            python:\n((?:              .*\n)+)", text, re.M)
    assert block, (
        "could not find the `python:` paths-filter block in ci.yml — this test "
        "guards it, so a rename must update this parser rather than silently "
        "matching nothing"
    )
    return re.findall(r"^              - '([^']+)'", block.group(1), re.M)


def _covered(top: str, globs: list[str]) -> bool:
    return any(g == top or g.startswith(f"{top}/") for g in globs)


def test_every_top_level_path_is_tested_or_exempt() -> None:
    globs = _python_filter_globs()
    tops = sorted(
        p.name
        for p in _REPO.iterdir()
        if p.is_dir() and p.name not in _IGNORED and not p.name.startswith(".")
    )
    uncovered = [t for t in tops if not _covered(t, globs) and t not in EXEMPT_PATHS]
    assert not uncovered, (
        f"Top-level paths in neither the CI `python` filter nor EXEMPT_PATHS: "
        f"{uncovered}. A change under these runs NO Python tests, so anything "
        "guarding them is skipped and the PR goes green regardless. Add the "
        "path to the filter in .github/workflows/ci.yml, or to EXEMPT_PATHS "
        "with a reason. Under-inclusive is merely expensive when a filter "
        "decides whether to TEST — and this is that filter."
    )


def test_exemptions_are_pinned_and_justified() -> None:
    assert len(EXEMPT_PATHS) <= EXEMPT_PATHS_MAX, (
        f"EXEMPT_PATHS grew to {len(EXEMPT_PATHS)} (pinned at "
        f"{EXEMPT_PATHS_MAX}). Exempting a path from the test filter is how "
        "the last two incidents happened; raise the pin deliberately."
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
    globs = _python_filter_globs()
    for path, incident in (
        ("scripts", "PROMPT_REGISTRY edits skipped the registry ratchet (ADR-0116)"),
        ("docs/wiki", "a term alias broke the paraphrase lint for everyone (#10926)"),
    ):
        top = path.split("/")[0] if "/" not in path else path
        assert any(g.startswith(path) for g in globs), (
            f"'{path}' is no longer in the CI `python` filter. It was added "
            f"because: {incident}. Removing it re-opens that exact hole."
        )
        del top
