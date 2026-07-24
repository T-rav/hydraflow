"""Unit tests for the shared read-only git timeout constant (#10402)."""

from __future__ import annotations

import git_timeouts


def test_git_readonly_timeout_s_value() -> None:
    assert git_timeouts.GIT_READONLY_TIMEOUT_S == 60


def test_git_readonly_timeout_s_is_int() -> None:
    assert isinstance(git_timeouts.GIT_READONLY_TIMEOUT_S, int)
