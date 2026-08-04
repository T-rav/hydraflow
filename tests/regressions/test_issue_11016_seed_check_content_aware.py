"""Regression for #11016: the sandbox-seed tree-clean check is content-aware.

The #11004 `--forked` fix broke the old check: it baselined committed-seed
mtimes once at conftest IMPORT, so under `--forked` every test forks with that
stale baseline and a single harmless re-serialization (identical bytes, new
mtime — git stays clean) made EVERY later forked test blame itself, blocking
innocent PRs. The check now (a) snapshots per-test (setup -> teardown) and
(b) fails only on real CONTENT drift, confirmed via git — a bare mtime bump is
not a #10094 violation. This pins that behavior via the `_content_dirty_seeds`
helper (a bad-parse or a reverted content-based check would regress it).
"""

from __future__ import annotations

from types import SimpleNamespace

from tests import conftest as root_conftest


def test_git_porcelain_parse_flags_only_content_dirty_seeds(monkeypatch) -> None:
    porcelain = (
        " M tests/sandbox_scenarios/seeds/s05_hitl.json\n"
        "?? tests/sandbox_scenarios/seeds/s99_untracked.json\n"
    )
    monkeypatch.setattr(
        root_conftest.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(stdout=porcelain),
    )
    # s05 is content-modified; s07 was only mtime-bumped (not in git output) → clean.
    result = root_conftest._content_dirty_seeds(["s05_hitl.json", "s07_clean.json"])
    assert result == ["s05_hitl.json"]


def test_empty_input_and_git_failure_are_fail_open() -> None:
    assert root_conftest._content_dirty_seeds([]) == []


def test_git_failure_returns_empty_not_blame(monkeypatch) -> None:
    def boom(*_a, **_k):
        raise OSError("git unavailable")

    monkeypatch.setattr(root_conftest.subprocess, "run", boom)
    # Fail-open: the dedicated regression_issue_10094::test_seed_dir_is_git_clean
    # is the authoritative content backstop; this hook must not blame on a git hiccup.
    assert root_conftest._content_dirty_seeds(["s05_hitl.json"]) == []
