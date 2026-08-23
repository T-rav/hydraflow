"""Regression test for issue #6983.

Bug: ``EpicManager.refresh_cache`` and ``check_stale_epics`` wrap GitHub API
calls in broad ``except Exception`` without calling ``reraise_on_credit_or_bug``.
This means ``AuthenticationError`` and ``CreditExhaustedError`` are silently
consumed and logged as ordinary epic-level errors, rather than propagating to
stop the ``EpicMonitorLoop``.

Affected sites:
- ``src/epic.py`` — ``refresh_cache`` broad ``except Exception``
- ``src/epic.py`` — ``check_stale_epics`` ``post_comment`` handler
- ``src/epic.py`` — ``check_stale_epics`` ``bus.publish`` handler

Expected behaviour after fix:
  - ``AuthenticationError`` and ``CreditExhaustedError`` propagate out of
    ``refresh_cache`` and ``check_stale_epics`` so the orchestrator's
    credit-pause / auth-retry logic can handle them.

Anchored on the METHOD, not on a line number (#11664)
-----------------------------------------------------

The per-site assertion below used to filter whole-file handler line numbers to
a ±15-line window around ``epic.py:1061`` / ``:1163`` / ``:1180``. ``epic.py``
has grown since — ``refresh_cache`` now starts near 1142 and
``check_stale_epics`` near 1286 — so every window matched an EMPTY set and
``assert not []`` passed VACUOUSLY.

The anchors are now enclosing method names, resolved through
``tests.regressions._handler_anchors.unguarded_handlers``, which RAISES if the
method disappears — a rotted anchor fails loudly instead of passing for free.
See ``_handler_anchors`` for the full rationale.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from tests.regressions._handler_anchors import (
    RERAISE_GUARD,
    SRC,
    unguarded_handlers,
)

sys.path.insert(0, str(SRC))

REQUIRED_GUARD = RERAISE_GUARD

#: (file, enclosing method, short description) from the issue findings.
#:
#: The issue listed three line-anchored sites; the last two (``post_comment``
#: and ``bus.publish``) are both handlers inside ``check_stale_epics``. They are
#: kept as separate rows so each finding stays traceable, but note that the
#: method-scoped scan checks every broad handler in the method — so the two rows
#: assert the same (strictly stronger) property.
KNOWN_UNGUARDED_SITES: list[tuple[str, str, str]] = [
    (
        "epic.py",
        "refresh_cache",
        "refresh_cache broad except Exception swallows AuthenticationError",
    ),
    (
        "epic.py",
        "check_stale_epics",
        "check_stale_epics post_comment broad except Exception swallows fatal errors",
    ),
    (
        "epic.py",
        "check_stale_epics",
        "check_stale_epics bus.publish broad except Exception swallows fatal errors",
    ),
]


# ---------------------------------------------------------------------------
# AST-based: verify source has the guard
# ---------------------------------------------------------------------------


class TestEpicManagerExceptBlocksHaveReraise:
    """AST check -- the ``except Exception`` blocks in ``refresh_cache`` and
    ``check_stale_epics`` must call ``reraise_on_credit_or_bug``.
    """

    @pytest.mark.parametrize(
        ("filename", "method", "desc"),
        KNOWN_UNGUARDED_SITES,
        ids=[f"{f}:{m}:{i}" for i, (f, m, _) in enumerate(KNOWN_UNGUARDED_SITES)],
    )
    def test_known_site_has_reraise_guard(
        self, filename: str, method: str, desc: str
    ) -> None:
        """``unguarded_handlers`` raises if *method* is gone, so this can never
        pass by matching nothing.
        """
        filepath = SRC / filename
        assert filepath.exists(), f"Source file not found: {filepath}"

        unguarded = [ln for ln, _ in unguarded_handlers(filepath, method)]

        assert not unguarded, (
            f"{filename}:{method}() ({desc}) -- ``except Exception`` at line "
            f"{unguarded[0]} does not call reraise_on_credit_or_bug(). "
            f"Auth/credit failures are silently swallowed (issue #6983)."
        )


# ---------------------------------------------------------------------------
# Behavioural: AuthenticationError / CreditExhaustedError must propagate
# ---------------------------------------------------------------------------


def _make_manager(tmp_path: Path):
    """Build an EpicManager with standard mocks for behavioural tests."""
    from epic import EpicManager
    from events import EventBus
    from state import StateTracker
    from tests.helpers import ConfigFactory

    config = ConfigFactory.create(
        repo_root=tmp_path / "repo",
        state_file=tmp_path / "state.json",
    )
    state = StateTracker(config.state_file)
    bus = EventBus()
    prs = AsyncMock()
    fetcher = AsyncMock()
    manager = EpicManager(config, state, prs, fetcher, bus)
    return manager, state, bus, prs, fetcher


def _register_stale_epic(state, epic_number: int = 100) -> None:
    """Register an epic in state that will be detected as stale."""
    from models import EpicState

    stale_time = (datetime.now(UTC) - timedelta(days=30)).isoformat()
    epic = EpicState(
        epic_number=epic_number,
        title="Stale Epic",
        child_issues=[1, 2],
        last_activity=stale_time,
    )
    state.upsert_epic_state(epic)


def _register_open_epic(state, epic_number: int = 100) -> None:
    """Register an open (non-closed) epic in state for refresh_cache."""
    from models import EpicState

    epic = EpicState(
        epic_number=epic_number,
        title="Open Epic",
        child_issues=[1, 2],
    )
    state.upsert_epic_state(epic)


class TestRefreshCachePropagatesFatalErrors:
    """Behavioural tests -- when ``_build_detail`` raises
    ``AuthenticationError`` or ``CreditExhaustedError`` inside
    ``refresh_cache``, the exception must NOT be swallowed.
    """

    @pytest.mark.asyncio()
    async def test_authentication_error_propagates_from_refresh_cache(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import AuthenticationError

        mgr, state, _, _, _ = _make_manager(tmp_path)
        _register_open_epic(state)

        mgr._build_detail = AsyncMock(side_effect=AuthenticationError("token expired"))

        with pytest.raises(AuthenticationError):
            await mgr.refresh_cache()

    @pytest.mark.asyncio()
    async def test_credit_exhausted_error_propagates_from_refresh_cache(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        mgr, state, _, _, _ = _make_manager(tmp_path)
        _register_open_epic(state)

        mgr._build_detail = AsyncMock(side_effect=CreditExhaustedError("credits gone"))

        with pytest.raises(CreditExhaustedError):
            await mgr.refresh_cache()


class TestCheckStaleEpicsPostCommentPropagatesFatalErrors:
    """Behavioural tests -- when ``post_comment`` raises
    ``AuthenticationError`` or ``CreditExhaustedError`` inside
    ``check_stale_epics``, the exception must NOT be swallowed.
    """

    @pytest.mark.asyncio()
    async def test_authentication_error_propagates_from_post_comment(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import AuthenticationError

        mgr, state, _, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        prs.post_comment = AsyncMock(side_effect=AuthenticationError("token expired"))

        with pytest.raises(AuthenticationError):
            await mgr.check_stale_epics()

    @pytest.mark.asyncio()
    async def test_credit_exhausted_error_propagates_from_post_comment(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        mgr, state, _, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        prs.post_comment = AsyncMock(side_effect=CreditExhaustedError("credits gone"))

        with pytest.raises(CreditExhaustedError):
            await mgr.check_stale_epics()


class TestCheckStaleEpicsBusPublishPropagatesFatalErrors:
    """Behavioural tests -- when ``bus.publish`` raises
    ``AuthenticationError`` or ``CreditExhaustedError`` inside
    ``check_stale_epics`` (the SYSTEM_ALERT publish), the exception
    must NOT be swallowed.
    """

    @pytest.mark.asyncio()
    async def test_authentication_error_propagates_from_bus_publish(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import AuthenticationError

        mgr, state, bus, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        # post_comment succeeds, but bus.publish raises on the SYSTEM_ALERT
        prs.post_comment = AsyncMock()
        bus.publish = AsyncMock(side_effect=AuthenticationError("token expired"))

        with pytest.raises(AuthenticationError):
            await mgr.check_stale_epics()

    @pytest.mark.asyncio()
    async def test_credit_exhausted_error_propagates_from_bus_publish(
        self, tmp_path: Path
    ) -> None:
        from subprocess_util import CreditExhaustedError

        mgr, state, bus, prs, _ = _make_manager(tmp_path)
        _register_stale_epic(state)

        prs.post_comment = AsyncMock()
        bus.publish = AsyncMock(side_effect=CreditExhaustedError("credits gone"))

        with pytest.raises(CreditExhaustedError):
            await mgr.check_stale_epics()
