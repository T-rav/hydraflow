"""Guard for the test-duration ratchet (CI-speedup Tier 4a).

The ratchet lives in ``tests/conftest.py``: a ``pytest_runtest_makereport``
hookwrapper that FAILS any test whose CALL phase exceeds ``_SLOW_TEST_BUDGET_S``
unless its node id is in the shrink-only ``_SLOW_TEST_GRANDFATHER`` set. These
static checks keep that machinery honest without running the slow tests
themselves:

  1. Every grandfather entry still resolves to a REAL, collectable test node —
     so the set cannot rot, hide a typo, or grandfather a test that no longer
     exists.
  2. The hook is actually defined and is a hookwrapper (a plain hook would not
     be able to mutate the report outcome).
  3. Anti-vacuity — the budget is a positive number and the grandfather set is
     non-empty, so the guard cannot pass by accident against an empty config.
"""

from __future__ import annotations

from pathlib import Path

from tests import conftest


def test_grandfather_entries_resolve_to_real_tests(real_repo_root: Path) -> None:
    """Each ``path::name`` entry points at a file that defines that test.

    Static only — we parse for ``def <name>``; we never execute the slow tests.
    Resolving the ids this way means a rename/deletion of a grandfathered test
    (or a typo in the set) fails here instead of silently un-grandfathering.
    """
    missing: list[str] = []
    for entry in conftest._SLOW_TEST_GRANDFATHER:
        assert "::" in entry, f"grandfather entry is not 'path::name': {entry!r}"
        rel_path, _, name = entry.partition("::")
        test_file = real_repo_root / rel_path
        if not test_file.is_file():
            missing.append(f"{entry} (no such file: {rel_path})")
            continue
        source = test_file.read_text(encoding="utf-8")
        if f"def {name}(" not in source:
            missing.append(f"{entry} (no `def {name}(` in {rel_path})")

    assert missing == [], (
        "Grandfathered slow tests no longer resolve (rename/delete/typo?). "
        "Fix or remove these entries in tests/conftest.py:\n  " + "\n  ".join(missing)
    )


def test_ratchet_hook_is_a_hookwrapper() -> None:
    """The ratchet hook exists and is registered as a hookwrapper.

    A non-wrapper hook cannot see/rewrite the report outcome, so the ratchet
    would silently no-op. Assert the pluggy impl opts mark it as a wrapper.
    """
    hook = getattr(conftest, "pytest_runtest_makereport", None)
    assert callable(hook), "tests.conftest.pytest_runtest_makereport must be defined"
    impl_opts = getattr(hook, "pytest_impl", None)
    assert impl_opts is not None, (
        "pytest_runtest_makereport must be decorated with @pytest.hookimpl(...)"
    )
    assert impl_opts.get("hookwrapper") is True, (
        "pytest_runtest_makereport must be a hookwrapper so it can rewrite the "
        "report outcome to 'failed' for over-budget tests."
    )


def test_ratchet_config_is_not_vacuous() -> None:
    """Budget is a positive number and the grandfather set is non-empty."""
    budget = conftest._SLOW_TEST_BUDGET_S
    assert isinstance(budget, int | float) and budget > 0, (
        f"_SLOW_TEST_BUDGET_S must be a positive number, got {budget!r}"
    )
    assert isinstance(conftest._SLOW_TEST_GRANDFATHER, frozenset)
    assert conftest._SLOW_TEST_GRANDFATHER, (
        "_SLOW_TEST_GRANDFATHER must list the known-slow tests (non-empty)."
    )
