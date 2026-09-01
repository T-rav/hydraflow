"""CharterLoopWorkerLoop — the driver that makes the runner a real loop (#11866).

#11861 shipped `CharterLoopRunner` as a dispatch component with no registration.
This owns only the periodic *when*, the per-repo iteration, and the dedup that
keeps one scheduled window from firing twice.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


from charter_loop_worker_loop import CharterLoopWorkerLoop, dedup_key
from tests.helpers import ConfigFactory

_NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


class _Dedup:
    def __init__(self, initial: set[str] | None = None) -> None:
        self._keys = set(initial or ())

    def get(self) -> set[str]:
        return set(self._keys)

    def set_all(self, keys: set[str]) -> None:
        self._keys = set(keys)


def _deps():
    from base_background_loop import LoopDeps
    from events import EventBus

    return LoopDeps(
        event_bus=EventBus(),
        stop_event=asyncio.Event(),
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _n: True,
    )


def _charter_yaml(tmp: Path, body: str) -> Path:
    root = tmp / "repo"
    (root / "agents").mkdir(parents=True, exist_ok=True)
    (root / "agents" / "a.md").write_text("you are a")
    (root / "charter.yaml").write_text(body)
    return root


_V2 = """schema_version: 2
actors: agents/
loops:
  a:
    actor: a
    enabled: true
    trigger:
      - cron: "0 9 * * *"
    goal: do the thing
"""

_V1 = "schema_version: 1\n"


def _loop(tmp: Path, *, root: Path | None, dedup: _Dedup, **overrides):
    config = ConfigFactory.create()
    config.data_root = tmp / "data"
    config.charter_loop_worker_loop_enabled = overrides.pop("enabled", True)
    config.dry_run = False
    receipts: list[str] = []

    def _runner_for(repo: str, repo_root: Path):
        from charter_loop_runner import CharterLoopRunner

        return CharterLoopRunner(
            repo=repo,
            repo_root=repo_root,
            receipts_path=tmp / "r.jsonl",
            receipt_writer=lambda _p, line: receipts.append(line),
            dispatch=AsyncMock(return_value={}),
        )

    loop = CharterLoopWorkerLoop(
        config=config,
        dedup=dedup,
        deps=_deps(),
        runner_for=_runner_for,
        repos=lambda: [("o/r", root)] if root is not None else [],
    )
    return loop, receipts


class TestTheKillSwitch:
    """ADR-0049: enabled_cb first, static config flag second."""

    async def test_the_static_flag_stops_it(self, tmp_path: Path) -> None:
        loop, _ = _loop(
            tmp_path, root=_charter_yaml(tmp_path, _V2), dedup=_Dedup(), enabled=False
        )
        assert (await loop._do_work())["status"] == "config_disabled"

    async def test_it_ships_disabled(self) -> None:
        """The default is the RULING, not caution.

        This loop dispatches agent work from a target repo's declaration, so
        arming it enlarges what the factory will run on someone else's say-so —
        an ENACT belonging to a human (ADR-0143 Ruling 6 guard 4).
        """
        from config import HydraFlowConfig

        assert HydraFlowConfig(repo="o/r").charter_loop_worker_loop_enabled is False


class TestMigrationIsSkippedNotFailed:
    async def test_a_v1_repo_is_skipped(self, tmp_path: Path) -> None:
        """Every repo today is unmigrated; failing them would make the loop
        permanently red on arrival."""
        loop, receipts = _loop(
            tmp_path, root=_charter_yaml(tmp_path, _V1), dedup=_Dedup()
        )
        result = await loop._do_work()

        assert result["skipped_unmigrated"] == 1
        assert result["dispatched"] == 0
        assert receipts == []

    async def test_a_repo_with_no_charter_is_skipped(self, tmp_path: Path) -> None:
        empty = tmp_path / "bare"
        empty.mkdir()
        loop, _ = _loop(tmp_path, root=empty, dedup=_Dedup())
        assert (await loop._do_work())["skipped_unmigrated"] == 1


class TestDedup:
    """The window is part of the identity, and that is the whole design."""

    def test_the_key_carries_the_window(self) -> None:
        """Keying on `repo:loop` alone would fire a daily loop once, ever."""
        first = dedup_key("o/r", "a", "2026-09-01T09:00:00+00:00")
        second = dedup_key("o/r", "a", "2026-09-02T09:00:00+00:00")
        assert first != second
        assert first.startswith("charter_loop:o/r:a:")

    async def test_a_second_tick_in_the_same_window_is_suppressed(
        self, tmp_path: Path
    ) -> None:
        root = _charter_yaml(tmp_path, _V2)
        dedup = _Dedup()

        loop, _ = _loop(tmp_path, root=root, dedup=dedup)
        first = await loop._do_work()

        loop2, _ = _loop(tmp_path, root=root, dedup=dedup)
        second = await loop2._do_work()

        assert first["dispatched"] == 1
        assert second["dispatched"] == 0, (
            "the same scheduled window dispatched twice — dedup is not durable"
        )
        # Suppression happens one layer EARLIER than the dedup set: the ledger
        # is read back into `last_fired`, so the runner reports "not due" and
        # never builds a receipt for the window at all. `deduped` therefore
        # stays 0, and that is the better outcome — the dedup set is the
        # durable RECORD that makes the reconstruction possible, not the
        # mechanism that does the suppressing. The counter is belt-and-braces
        # for a window that somehow reaches the receipt stage twice in one tick.
        assert second["deduped"] == 0
        assert second["status"] == "idle"

    async def test_the_dedup_ledger_is_the_last_fired_record(
        self, tmp_path: Path
    ) -> None:
        """Reconstructing `last_fired` from dedup is what makes the catch-up
        policy survive a restart. A second store would be a second place the
        same fact lives, and the two would drift the first time one was written
        and the other was not.
        """
        from charter_loop_worker_loop import _last_fired_from_dedup

        class _C:
            class loops:  # noqa: N801 - test stub
                @staticmethod
                def by_name():
                    return {"a": None, "b": None}

        window = "2026-09-01T09:00:00+00:00"
        latest = _last_fired_from_dedup(_C(), "o/r", {dedup_key("o/r", "a", window)})
        assert latest["a"] == datetime.fromisoformat(window)
        assert latest["b"] is None, "a loop that never fired must read as None"

    async def test_a_foreign_repos_keys_are_ignored(self, tmp_path: Path) -> None:
        """Anti-vacuity: a prefix match that ignored the repo would let one
        repo's window suppress another's."""
        from charter_loop_worker_loop import _last_fired_from_dedup

        class _C:
            class loops:  # noqa: N801 - test stub
                @staticmethod
                def by_name():
                    return {"a": None}

        latest = _last_fired_from_dedup(
            _C(), "o/r", {dedup_key("other/repo", "a", "2026-09-01T09:00:00+00:00")}
        )
        assert latest["a"] is None


class TestABrokenCharterRunsNothing:
    async def test_an_unreadable_charter_does_not_stop_the_tick(
        self, tmp_path: Path
    ) -> None:
        """A broken charter is the drift caretaker's to report. This loop
        refuses to run anything for that repo and moves on — it never guesses
        at a partial declaration."""
        root = tmp_path / "broken"
        root.mkdir()
        (root / "charter.yaml").write_text("loops:\n  a:\n  a:\n")

        loop, receipts = _loop(tmp_path, root=root, dedup=_Dedup())
        result = await loop._do_work()

        assert result is not None
        assert result["dispatched"] == 0
        assert receipts == []


class TestTheLoopHasTheRequiredWiring:
    def test_it_reraises_credit_and_bug_exceptions(self) -> None:
        """CLAUDE.md hard rule: without it a CreditExhaustedError is eaten and
        the loop burns attempt budget against an exhausted billing signal."""
        import inspect

        import charter_loop_worker_loop

        source = inspect.getsource(charter_loop_worker_loop)
        assert source.count("reraise_on_credit_or_bug(exc)") >= 2, (
            "every broad except in a subprocess-spawning path needs it"
        )

    def test_it_is_registered_in_the_orchestrator(self) -> None:
        import inspect

        import orchestrator

        source = inspect.getsource(orchestrator)
        assert '"charter_loop_worker"' in source
