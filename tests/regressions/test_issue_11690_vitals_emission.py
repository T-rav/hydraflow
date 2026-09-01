"""Vitals reach a spool, on an RC cut and on a floor (#11690 decision D2).

Layer 1 (#11689) built a self-identifying vitals document and wired it to
**nothing**: `scripts/emit_vitals.py` had no caller anywhere in `src/`,
`scripts/`, the Makefile or CI. A document nobody emits is not a data plane.

This covers Layer 2 — transport with no opinion about sinks. Decisions D1 (push
vs pull) and D3 (which sink) are deliberately NOT taken: an adapter outside
HydraFlow reads the spool and can push or be scraped, to anywhere, without
touching this code.

**Why the factory host, not CI.** The document's value is identity — `repo`,
`head_sha`, `host`. Two hosts reporting `parametrize_copies: 451` are the same
fact or two different facts depending entirely on which factory produced it,
and no consumer recovers that afterwards. Emitting from a CI runner would stamp
the runner's hostname and answer a question nobody asked.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from vitals_spool import floor_elapsed

_NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


class TestTheFloor:
    """The floor is what makes a quiet factory distinguishable from a dead one."""

    def test_a_factory_that_never_reported_is_due_immediately(self) -> None:
        """Never-emitted is the case the floor exists to surface.

        Waiting a further day before the first reading would leave a brand-new
        or just-recovered factory invisible for exactly as long as it is most
        worth watching.
        """
        assert floor_elapsed(None, _NOW, 24.0) is True

    def test_a_recent_reading_does_not_re_emit(self) -> None:
        assert floor_elapsed(_NOW - timedelta(hours=1), _NOW, 24.0) is False

    def test_an_old_reading_is_due(self) -> None:
        assert floor_elapsed(_NOW - timedelta(hours=25), _NOW, 24.0) is True

    def test_a_zero_floor_disables_the_heartbeat(self) -> None:
        """A real configuration, not an accident of arithmetic.

        A factory cutting RCs often needs no separate heartbeat. Without the
        explicit guard, `0` would make every tick "due" and emit continuously —
        the opposite of what setting it to zero reads like.
        """
        assert floor_elapsed(None, _NOW, 0.0) is False
        assert floor_elapsed(_NOW - timedelta(days=99), _NOW, 0.0) is False

    def test_a_naive_timestamp_is_not_a_crash(self) -> None:
        """Stamps are written by us, but read back from disk after upgrades."""
        assert floor_elapsed(_NOW - timedelta(hours=25), _NOW, 24.0) is True


class TestTheEmitterIsActuallyWired:
    """Layer 1 shipped a correct emitter that nothing called. That is the defect.

    These read the promotion loop's SOURCE rather than mocking it: the failure
    being guarded is "no caller exists", and a test that mocks the caller
    cannot observe its absence.
    """

    def test_the_rc_cut_emits(self) -> None:
        import inspect

        from staging_promotion_loop import StagingPromotionLoop

        src = inspect.getsource(StagingPromotionLoop._cut_new_rc)
        assert 'await emit_to_spool(self._config, now=now, reason="rc_cut")' in src, (
            "the RC cut does not emit vitals — D2's primary trigger is unwired"
        )

    def test_the_floor_is_checked_every_tick(self) -> None:
        import inspect

        from staging_promotion_loop import StagingPromotionLoop

        src = inspect.getsource(StagingPromotionLoop._do_work)
        assert "await self._maybe_emit_vitals_floor()" in src, (
            "the floor is never checked, so a factory that stops cutting RCs "
            "goes silent and reads as dead"
        )

    def test_the_floor_is_checked_before_the_promotion_work(self) -> None:
        """Ordering is the point, not presence.

        The reading matters most when cuts are FAILING. A floor checked after
        the promotion work would be skipped by every early return above it —
        and the promotion path has several.
        """
        import inspect

        from staging_promotion_loop import StagingPromotionLoop

        src = inspect.getsource(StagingPromotionLoop._do_work)
        assert src.index("_maybe_emit_vitals_floor()") < src.index("_sweep_if_due()"), (
            "the floor check sits after promotion work and can be skipped"
        )


class TestEmissionNeverBreaksTheCut:
    """Observation that can fail a promotion tick is worse than no observation."""

    async def test_a_missing_emitter_script_is_silent(self, tmp_path: Path) -> None:
        from unittest.mock import patch

        from package_resources import ResourceNotFoundError
        from vitals_spool import emit_to_spool

        config = _config(tmp_path)
        with patch(
            "vitals_spool.checkout_path", side_effect=ResourceNotFoundError("absent")
        ):
            assert await emit_to_spool(config, now=_NOW, reason="rc_cut") is None

    async def test_a_failing_emitter_is_silent(self, tmp_path: Path) -> None:
        from unittest.mock import AsyncMock, MagicMock, patch

        from vitals_spool import emit_to_spool

        config = _config(tmp_path)
        failed = MagicMock()
        failed.returncode = 1
        failed.stdout = ""
        with (
            patch("vitals_spool.checkout_path", return_value=Path("emit.py")),
            patch("vitals_spool.run_subprocess_result", AsyncMock(return_value=failed)),
        ):
            assert await emit_to_spool(config, now=_NOW, reason="rc_cut") is None

    async def test_the_kill_switch_short_circuits(self, tmp_path: Path) -> None:
        from vitals_spool import emit_to_spool

        config = _config(tmp_path)
        config.vitals_emit_enabled = False
        assert await emit_to_spool(config, now=_NOW, reason="rc_cut") is None


class TestATruthyNonBoolFlagNeverSpawnsASubprocess:
    """A MagicMock config must not opt a test into emitting.

    `getattr(config, "vitals_emit_enabled", False)` returns a truthy Mock for
    ANY attribute on a MagicMock, which is the config shape most loop tests
    hand their subject. The first draft used a plain truthiness check and 79
    promotion-loop tests began spawning a real emitter subprocess — they failed
    loudly here, but the same shape has shipped silently before (a Mock in
    arithmetic does not raise).
    """

    async def test_a_truthy_non_true_flag_is_treated_as_disabled(
        self, tmp_path: Path
    ) -> None:
        from types import SimpleNamespace
        from unittest.mock import patch

        from vitals_spool import emit_to_spool

        # A SimpleNamespace carrying a truthy NON-bool, rather than a bare
        # MagicMock: it expresses the property under test exactly — "truthy but
        # not True" — and `tests/architecture/test_config_mock_numeric_fields.py`
        # rightly forbids standing in for HydraFlowConfig with a bare Mock,
        # since every numeric field it does not set then answers with a Mock.
        config = SimpleNamespace(
            vitals_emit_enabled=object(),
            data_root=tmp_path,
            repo_root=tmp_path,
        )

        with patch("vitals_spool.run_subprocess_result") as spawn:
            assert await emit_to_spool(config, now=_NOW, reason="rc_cut") is None
        assert not spawn.called, (
            "a truthy non-bool opted a caller into spawning the emitter — a "
            "MagicMock config answers ANY attribute that way, which is the "
            "config shape most loop tests use. Check with `is not True`."
        )

    async def test_a_real_config_with_the_flag_on_does_emit(
        self, tmp_path: Path
    ) -> None:
        """Anti-vacuity: the guard must not disable emission for real configs."""
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from vitals_spool import emit_to_spool

        ok = MagicMock()
        ok.returncode = 0
        ok.stdout = json.dumps({"schema_version": 1})
        with (
            patch("vitals_spool.checkout_path", return_value=Path("emit.py")),
            patch(
                "vitals_spool.run_subprocess_result", AsyncMock(return_value=ok)
            ) as spawn,
        ):
            written = await emit_to_spool(_config(tmp_path), now=_NOW, reason="floor")
        assert spawn.called
        assert written is not None


class TestTheSpooledDocument:
    async def test_a_good_run_appends_and_stamps(self, tmp_path: Path) -> None:
        """The happy path, end to end, with the emitter's real output shape."""
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from vitals_spool import emit_to_spool, read_last_emit, spool_path

        config = _config(tmp_path)
        ok = MagicMock()
        ok.returncode = 0
        ok.stdout = json.dumps(
            {"schema_version": 1, "kind": "hydraflow.vitals", "identity": {}}
        )
        with (
            patch("vitals_spool.checkout_path", return_value=Path("emit.py")),
            patch("vitals_spool.run_subprocess_result", AsyncMock(return_value=ok)),
        ):
            written = await emit_to_spool(config, now=_NOW, reason="rc_cut")

        assert written == spool_path(config)
        lines = written.read_text("utf-8").strip().splitlines()
        assert len(lines) == 1
        doc = json.loads(lines[0])
        assert doc["trigger"] == "rc_cut", (
            "the trigger must ride ON the document — an aggregate that cannot "
            "tell a cut-triggered reading from a floor heartbeat cannot tell a "
            "busy factory from a quiet one"
        )
        assert read_last_emit(config) == _NOW

    async def test_a_second_emission_appends_rather_than_replaces(
        self, tmp_path: Path
    ) -> None:
        """Append-only: the spool is a history, not a latest-value cell."""
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from vitals_spool import emit_to_spool, spool_path

        config = _config(tmp_path)
        ok = MagicMock()
        ok.returncode = 0
        ok.stdout = json.dumps({"schema_version": 1})
        with (
            patch("vitals_spool.checkout_path", return_value=Path("emit.py")),
            patch("vitals_spool.run_subprocess_result", AsyncMock(return_value=ok)),
        ):
            await emit_to_spool(config, now=_NOW, reason="rc_cut")
            await emit_to_spool(config, now=_NOW, reason="floor")

        lines = spool_path(config).read_text("utf-8").strip().splitlines()
        assert [json.loads(x)["trigger"] for x in lines] == ["rc_cut", "floor"]


def _config(tmp_path: Path):
    from config import HydraFlowConfig

    return HydraFlowConfig(repo="owner/repo", data_root=tmp_path, repo_root=tmp_path)


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch: pytest.MonkeyPatch):
    """Nothing here may spawn a real emitter."""
    yield
