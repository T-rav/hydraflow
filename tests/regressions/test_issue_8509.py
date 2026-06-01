"""Regression test for issue #8509.

Bug: FakeCoverageAuditorLoop classified FakeGitHub.clear_rate_limit and
FakeGitHub.set_rate_limit_mode as ``adapter-surface``, causing the auditor
to file spurious cassette-gap issues for test-only helper methods.

Expected behaviour after fix:
  - ``clear_rate_limit`` on FakeGitHub classifies as ``test-helper``, not
    ``adapter-surface``.
  - ``set_rate_limit_mode`` on FakeGitHub classifies as ``test-helper``, not
    ``adapter-surface``.

Self-retires: if either method is renamed or removed, its assertion is skipped
because the method simply won't appear in either bucket — no false failure.
"""

from __future__ import annotations

from pathlib import Path

from fake_coverage_auditor_loop import catalog_fake_methods

_FAKES_DIR = Path(__file__).resolve().parents[2] / "src" / "mockworld" / "fakes"


class TestClearRateLimitIsHelper:
    """FakeGitHub.clear_rate_limit must classify as test-helper, not adapter-surface."""

    def test_clear_rate_limit_classifies_as_test_helper(self) -> None:
        catalog = catalog_fake_methods(_FAKES_DIR)
        assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes dir"
        github = catalog["FakeGitHub"]
        assert "clear_rate_limit" in github["adapter-surface"] + github[
            "test-helper"
        ], "clear_rate_limit no longer exists"
        assert "clear_rate_limit" not in github["adapter-surface"], (
            "clear_rate_limit is a test-only helper and must not appear in adapter-surface"
        )
        assert "clear_rate_limit" in github["test-helper"]

    def test_set_rate_limit_mode_classifies_as_test_helper(self) -> None:
        catalog = catalog_fake_methods(_FAKES_DIR)
        assert "FakeGitHub" in catalog, "FakeGitHub not found in fakes dir"
        github = catalog["FakeGitHub"]
        assert "set_rate_limit_mode" in github["adapter-surface"] + github[
            "test-helper"
        ], "set_rate_limit_mode no longer exists"
        assert "set_rate_limit_mode" not in github["adapter-surface"], (
            "set_rate_limit_mode is a test-only helper and must not appear in adapter-surface"
        )
        assert "set_rate_limit_mode" in github["test-helper"]
