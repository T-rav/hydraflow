"""Architecture guard: the reap-test serial list stays in sync (#10904).

The subprocess-group reap tests are xdist-unsafe and must run SERIALLY. That
list is declared in two places, kept "in sync" only by comment discipline:

* Makefile ``REAP_TESTS`` (folded into ``PYTEST_SERIAL_PATHS``).
* ``.github/workflows/ci.yml`` — the regression job's inline ``REAP="..."``,
  which is parallel-ignored and then run serially.

If the two drift — e.g. a new reap test added to one but not the other — that
test can land in the parallel lane in one runner and race, masked only by
``--reruns``. This guard fails when they disagree, or when either lists a path
that no longer exists on disk (a stale entry silently no-ops). Static text scan;
it never imports or runs the reap tests.
"""

from __future__ import annotations

import re
from pathlib import Path


def _extract_paths(text: str) -> set[str]:
    return set(re.findall(r"tests/\S+\.py", text))


def _makefile_reap(repo_root: Path) -> set[str]:
    mk = (repo_root / "Makefile").read_text(encoding="utf-8")
    # The assignment spans backslash-continued lines; end at the first newline
    # not preceded by a backslash.
    m = re.search(r"REAP_TESTS\s*:=\s*(.*?)(?<!\\)\n", mk, re.S)
    assert m, "Could not locate `REAP_TESTS :=` in the Makefile"
    return _extract_paths(m.group(1))


def _ci_reap(repo_root: Path) -> set[str]:
    ci = (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    m = re.search(r'REAP="(.*?)"', ci, re.S)
    assert m, 'Could not locate `REAP="..."` in ci.yml'
    return _extract_paths(m.group(1))


def test_reap_serial_list_in_sync(real_repo_root: Path) -> None:
    """Makefile REAP_TESTS and the ci.yml regression-job REAP list match (#10904)."""
    mk = _makefile_reap(real_repo_root)
    ci = _ci_reap(real_repo_root)
    assert mk == ci, (
        "The reap-test serial list drifted between the Makefile and ci.yml — a "
        "reap test could run in the parallel lane and race. Reconcile them:\n"
        f"  only in Makefile REAP_TESTS: {sorted(mk - ci)}\n"
        f"  only in ci.yml REAP:         {sorted(ci - mk)}"
    )


def test_reap_serial_paths_exist(real_repo_root: Path) -> None:
    """Every reap path is a real file — a stale entry silently no-ops (#10904)."""
    missing = sorted(
        p for p in _makefile_reap(real_repo_root) if not (real_repo_root / p).is_file()
    )
    assert not missing, (
        f"Makefile REAP_TESTS lists nonexistent path(s) (stale after a rename or "
        f"delete — the serial lane silently skips them): {missing}"
    )
