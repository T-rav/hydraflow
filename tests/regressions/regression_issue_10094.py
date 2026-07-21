"""Regression guard for #10094 — committed sandbox seeds must not drift.

Root cause: ``scripts/sandbox_scenario.py::write_seed`` materializes a
scenario's ``seed().to_json()`` into the COMMITTED
``tests/sandbox_scenarios/seeds/<NAME>.json`` (the dir the docker container
mounts read-only). When a ``MockWorldSeed`` field is added but the committed
golden seed isn't regenerated, the next harness run
(``sandbox_scenario.py run`` / ``run-all`` / ``seed`` — which CI's sandbox
lane and the local bake execute) rewrites the file in place with the current
model. That surfaces as an unstaged `` M`` diff (``comments: {}``,
``auto_agent_attempts: {}``, ``sandbox_loop_interval: 60``,
``plan_hold_seconds: 0.0`` … — all schema defaults the stale JSON lacked) which
then leaks into unrelated commits. Observed on
``s05_hitl_after_review_exhaustion.json`` but every committed generated seed
was stale to some degree.

Two guards, so the drift can never silently recur:

1. **Freshness** — every committed *generated* seed must equal the current
   ``seed().to_json()`` for its scenario (exactly what ``write_seed`` would
   write). A ``MockWorldSeed``/scenario change that lands without regenerating
   the golden seed fails here — a hard error in the PR that introduced the
   drift, instead of a silent in-place rewrite on the next sandbox run.

2. **Tree-clean** — ``tests/sandbox_scenarios/seeds/`` must be git-clean after
   this test (mirrors the repo's tree-clean hygiene guards, e.g. #9539). Fails
   loudly if a test or the harness mutates a committed seed in place. Skips
   cleanly outside a git checkout.

``_smoke.json`` is a hand-authored minimal fixture (a single-line payload, not
``write_seed`` output — it is deliberately NOT idempotent under
``MockWorldSeed`` round-trip), so it is excluded from the freshness check.
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SEEDS_DIR = _REPO_ROOT / "tests" / "sandbox_scenarios" / "seeds"

# Hand-authored fixtures (not materialized by write_seed) — excluded from the
# generated-seed freshness check.
_FIXTURE_SEEDS = frozenset({"_smoke.json"})
# Transient per-run symlink the harness creates (already gitignored).
_TRANSIENT_SEEDS = frozenset({"scenario.json"})


def _generated_seed_files() -> list[Path]:
    """Committed seed JSONs that ARE materialized from a scenario ``seed()``."""
    return [
        p
        for p in sorted(_SEEDS_DIR.glob("*.json"))
        if p.name not in _FIXTURE_SEEDS and p.name not in _TRANSIENT_SEEDS
    ]


@pytest.mark.parametrize("seed_path", _generated_seed_files(), ids=lambda p: p.name)
def test_committed_seed_matches_scenario_definition(seed_path: Path) -> None:
    """A committed generated seed must equal its scenario's ``seed().to_json()``.

    Mirrors exactly what ``scripts/sandbox_scenario.py::write_seed`` writes, so
    a stale golden seed is caught here rather than by the harness rewriting it
    in place (#10094).
    """
    stem = seed_path.stem
    try:
        module = importlib.import_module(f"tests.sandbox_scenarios.scenarios.{stem}")
    except ModuleNotFoundError as exc:
        # raise (not pytest.fail) so the except branch provably ends control
        # flow — keeps `module` bound below for type checkers.
        raise AssertionError(
            f"{seed_path.name} has no scenario module "
            f"tests/sandbox_scenarios/scenarios/{stem}.py — orphaned generated "
            "seed. Delete the seed, restore the scenario, or (if it is a "
            "hand-authored fixture) add it to _FIXTURE_SEEDS."
        ) from exc

    expected = module.seed().to_json()  # identical to write_seed()'s payload
    actual = seed_path.read_text()
    assert actual == expected, (
        f"{seed_path.name} is STALE relative to {stem}.seed(). Regenerate it "
        f"with `python scripts/sandbox_scenario.py seed {stem}` and commit the "
        "result. Committed sandbox seeds are golden copies of the scenario's "
        "seed() and MUST be regenerated whenever MockWorldSeed or the scenario "
        "changes, or the next sandbox harness run rewrites them in place "
        "(#10094)."
    )


def test_seed_dir_is_git_clean() -> None:
    """``tests/sandbox_scenarios/seeds/`` must be git-clean (#10094).

    Turns silent in-place seed mutation into a hard failure. Skips cleanly when
    git is unavailable or this is not a checkout (early return, not a marker —
    the repo guard ``tests/test_no_ignored_active_tests.py`` forbids skip/xfail
    markers).
    """
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "tests/sandbox_scenarios/seeds/"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return  # git binary unavailable — nothing to assert
    if result.returncode != 0:
        return  # not a git checkout (e.g. exported tarball)

    dirty = [line for line in result.stdout.splitlines() if line.strip()]
    assert not dirty, (
        "Committed sandbox seeds are dirty:\n"
        + "\n".join(dirty)
        + "\n\nA test or the sandbox harness (write_seed) mutated a committed "
        "seed in place. Seeds are golden generated artifacts — regenerate and "
        "commit them (`python scripts/sandbox_scenario.py seed <name>`), or fix "
        "the writer so it never leaves the source tree dirty (#10094)."
    )
