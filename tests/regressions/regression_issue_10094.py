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

Three guards, so the drift can never silently recur:

1. **Freshness** — every committed *generated* seed must equal the current
   ``seed().to_json()`` for its scenario (exactly what ``write_seed`` would
   write). A ``MockWorldSeed``/scenario change that lands without regenerating
   the golden seed fails here — a hard error in the PR that introduced the
   drift, instead of a silent in-place rewrite on the next sandbox run.

2. **Tree-clean** — ``tests/sandbox_scenarios/seeds/`` must be git-clean after
   this test (mirrors the repo's tree-clean hygiene guards, e.g. #9539). Fails
   loudly if a test or the harness mutates a committed seed in place. Skips
   cleanly outside a git checkout.

3. **Round-trip isolation** — ``write_seed()`` run against the REAL scenario
   module (not a mock — exercises the real ``MockWorldSeed.to_json()`` schema
   round-trip that produces the default-valued-field drift) with ``SEEDS_DIR``
   redirected to ``tmp_path`` must land ONLY in ``tmp_path`` and must leave the
   real committed source file byte-for-byte and mtime untouched. Pins the fix
   direction the issue asked for directly: a materialize round-trip writes to
   a temp copy, never back to source. ``tests/test_sandbox_scenario_cli.py``
   covers the CLI wiring but mocks ``load_scenario``/``to_json`` entirely, so
   it never actually exercises the schema round-trip that causes the drift;
   this guard closes that gap.

``_smoke.json`` is a hand-authored minimal fixture (a single-line payload, not
``write_seed`` output — it is deliberately NOT idempotent under
``MockWorldSeed`` round-trip), so it is excluded from the freshness check.
"""

from __future__ import annotations

import importlib
import shutil
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


def test_write_seed_materialize_round_trip_never_touches_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``write_seed()`` must land ONLY in the injected ``SEEDS_DIR`` (#10094).

    Exercises the REAL scenario module + REAL ``MockWorldSeed.to_json()`` —
    not a mock — the same code path ``cmd_run``/``cmd_run-all``/``cmd_seed``
    use, with ``SEEDS_DIR`` redirected to ``tmp_path``. Snapshots the real
    committed seed's mtime and content before and after to prove the write
    never lands on source, even if ``write_seed``'s target ever silently
    drifted back to the real dir. This is the literal fix direction #10094
    asked for: a materialize round-trip writes to a temp copy, never source.
    """
    from scripts import sandbox_scenario

    stem = "s05_hitl_after_review_exhaustion"
    real_seed_path = _SEEDS_DIR / f"{stem}.json"
    content_before = real_seed_path.read_text()
    mtime_before = real_seed_path.stat().st_mtime_ns

    monkeypatch.setattr(sandbox_scenario, "SEEDS_DIR", tmp_path)
    out = sandbox_scenario.write_seed(stem)

    assert out == tmp_path / f"{stem}.json"
    # Real round-trip through the current scenario/model — must match the
    # freshness guard's expectation (both compute module.seed().to_json()).
    module = importlib.import_module(f"tests.sandbox_scenarios.scenarios.{stem}")
    assert out.read_text() == module.seed().to_json()

    assert real_seed_path.read_text() == content_before, (
        "write_seed() rewrote the COMMITTED source seed's content even "
        "though SEEDS_DIR was redirected to tmp_path — the exact #10094 leak."
    )
    assert real_seed_path.stat().st_mtime_ns == mtime_before, (
        "write_seed() touched the COMMITTED source seed's mtime even though "
        "SEEDS_DIR was redirected to tmp_path — the exact #10094 leak."
    )


def test_cmd_run_materialize_never_pollutes_committed_seeds_dir() -> None:
    """``cmd_run`` must materialize into a throwaway temp dir, never ``SEEDS_DIR``.

    Sibling of #10094: same root cause (``write_seed`` writing into the
    committed golden dir), different trigger. 72 of 78 scenarios have no
    committed golden seed, so a manual ``sandbox_scenario.py run <seedless>``
    used to drop an untracked ``<name>.json`` (plus a ``scenario.json`` symlink)
    into ``tests/sandbox_scenarios/seeds/``, tripping
    ``test_seed_dir_is_git_clean`` on the next full-suite run in that workspace
    (#10980). Exercises the REAL seed-materialization seam ``cmd_run`` uses
    against a REAL *seedless* scenario module — the exact class that polluted —
    then proves the committed dir is entry-for-entry, byte-for-byte, and
    mtime-for-mtime unchanged. ``cmd_seed`` stays the only writer of the goldens.
    """
    from scripts import sandbox_scenario

    # A real scenario with NO committed golden (one of the 72) — the exact case
    # reported in #10980. If a golden ever gets added for it, pick another.
    stem = "s75_worker_stall_escalation"
    assert not (_SEEDS_DIR / f"{stem}.json").exists(), (
        f"{stem} unexpectedly has a committed golden seed — pick a seedless "
        "scenario so this guard actually proves the no-pollution property."
    )

    names_before = {p.name for p in _SEEDS_DIR.iterdir()}
    files_before = {
        p.name: (p.read_text(), p.stat().st_mtime_ns)
        for p in _SEEDS_DIR.iterdir()
        if p.is_file()
    }

    seed_dir = sandbox_scenario._materialize_run_seed(stem)
    try:
        # Materialization landed in a throwaway temp dir OUTSIDE the golden dir.
        assert seed_dir != _SEEDS_DIR
        assert _SEEDS_DIR not in seed_dir.parents
        seed_file = seed_dir / f"{stem}.json"
        module = importlib.import_module(
            f"tests.sandbox_scenarios.scenarios.{stem}"
        )
        assert seed_file.read_text() == module.seed().to_json()
        # The per-run scenario.json symlink lives in the temp dir too, not source.
        assert (seed_dir / "scenario.json").is_symlink()

        # The committed golden dir is entirely untouched — no stray file added,
        # no in-place mutation, no mtime bump.
        assert {p.name for p in _SEEDS_DIR.iterdir()} == names_before, (
            "_materialize_run_seed added or removed an entry in the committed "
            "seeds dir — the exact #10980 pollution."
        )
        assert {
            p.name: (p.read_text(), p.stat().st_mtime_ns)
            for p in _SEEDS_DIR.iterdir()
            if p.is_file()
        } == files_before, (
            "_materialize_run_seed mutated a committed seed in place (#10980)."
        )
    finally:
        shutil.rmtree(seed_dir, ignore_errors=True)


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
