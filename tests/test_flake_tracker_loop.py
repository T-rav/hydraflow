"""Tests for FlakeTrackerLoop (spec §4.5)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from base_background_loop import LoopDeps
from config import HydraFlowConfig
from events import EventBus
from flake_tracker_loop import FlakeTrackerLoop, parse_junit_xml


def _deps(stop: asyncio.Event) -> LoopDeps:
    return LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda _name: True,
    )


@pytest.fixture
def loop_env(tmp_path: Path):
    cfg = HydraFlowConfig(data_root=tmp_path, repo="hydra/hydraflow")
    state = MagicMock()
    state.get_flake_counts.return_value = {}
    state.get_flake_attempts.return_value = 0
    state.inc_flake_attempts.return_value = 1
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    dedup = MagicMock()
    dedup.get.return_value = set()
    return cfg, state, pr_manager, dedup


def test_skeleton_worker_name_and_interval(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    assert loop._worker_name == "flake_tracker"
    assert loop._get_default_interval() == 14400


def test_parse_junit_xml_counts_failures_per_test() -> None:
    xml = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.scenarios" name="test_alpha" />
    <testcase classname="tests.scenarios" name="test_bravo">
      <failure message="AssertionError"/>
    </testcase>
    <testcase classname="tests.scenarios" name="test_charlie">
      <error message="Timeout"/>
    </testcase>
  </testsuite>
</testsuites>
"""
    results = parse_junit_xml(xml)
    assert results == {
        "tests.scenarios.test_alpha": "pass",
        "tests.scenarios.test_bravo": "fail",
        "tests.scenarios.test_charlie": "fail",
    }


async def test_tally_flakes_counts_mixed_results(loop_env) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )
    # Spec §4.5 step 2: only tests with a *mixed pass/fail record* count
    # as flaky. Always-pass = healthy; always-fail = broken, not flaky.
    runs = [
        {
            "tests.scenarios.test_alpha": "pass",
            "tests.scenarios.test_bravo": "fail",
            "tests.scenarios.test_delta": "fail",
        },
        {
            "tests.scenarios.test_alpha": "pass",
            "tests.scenarios.test_bravo": "fail",
            "tests.scenarios.test_delta": "fail",
        },
        {
            "tests.scenarios.test_alpha": "pass",
            "tests.scenarios.test_bravo": "pass",
            "tests.scenarios.test_charlie": "fail",
            "tests.scenarios.test_delta": "fail",
        },
        {
            "tests.scenarios.test_alpha": "pass",
            "tests.scenarios.test_charlie": "pass",
            "tests.scenarios.test_delta": "fail",
        },
    ]
    counts = loop._tally_flakes(runs)
    assert counts["tests.scenarios.test_bravo"] == 2
    assert counts["tests.scenarios.test_charlie"] == 1
    assert "tests.scenarios.test_alpha" not in counts  # no failures
    assert "tests.scenarios.test_delta" not in counts  # always-fail = broken


async def test_do_work_files_issue_when_threshold_hit(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    fake_runs = [
        {"tests.foo.test_flake": "fail"},
        {"tests.foo.test_flake": "pass"},
        {"tests.foo.test_flake": "fail"},
        {"tests.foo.test_flake": "fail"},
    ]

    async def fake_fetch():
        return [{"databaseId": i, "url": f"u{i}"} for i in range(len(fake_runs))]

    async def fake_download(run):
        return fake_runs[run["databaseId"]]

    async def fake_reconcile():
        return None

    monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch)
    monkeypatch.setattr(loop, "_download_junit", fake_download)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["filed"] == 1
    title = pr.create_issue.await_args.args[0]
    assert "test_flake" in title
    labels = pr.create_issue.await_args.args[2]
    assert "flaky-test" in labels


async def test_escalation_fires_after_three_attempts(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    state.get_flake_attempts.return_value = 2  # next inc → 3
    state.inc_flake_attempts.return_value = 3
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    async def fake_fetch():
        # Two runs so test_bad has a mixed pass/fail record (spec §4.5).
        return [{"databaseId": 0, "url": "u"}, {"databaseId": 1, "url": "v"}]

    call = {"n": 0}

    async def fake_dl(_):
        call["n"] += 1
        # First run: test_bad fails. Second run: test_bad passes. Mixed
        # record → counts as flaky per spec.
        return {
            "tests.scenarios.test_bad": "fail" if call["n"] == 1 else "pass",
            "tests.scenarios.test_other": "pass",
        }

    async def fake_reconcile():
        return None

    # Threshold=1 so a single fail-in-mixed-set triggers.
    cfg.flake_threshold = 1
    monkeypatch.setattr(loop, "_fetch_recent_runs", fake_fetch)
    monkeypatch.setattr(loop, "_download_junit", fake_dl)
    monkeypatch.setattr(loop, "_reconcile_closed_escalations", fake_reconcile)

    stats = await loop._do_work()
    assert stats["escalated"] == 1
    labels = pr.create_issue.await_args.args[2]
    assert "hitl-escalation" in labels
    assert "flaky-test-stuck" in labels


async def test_reconcile_closed_escalations_clears_dedup(loop_env, monkeypatch) -> None:
    cfg, state, pr, dedup = loop_env
    dedup.get.return_value = {"flake_tracker:tests.foo.test_bar"}
    stop = asyncio.Event()
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )

    class FakeProc:
        returncode = 0

        async def communicate(self):
            return (
                b'[{"title": "HITL: flaky test tests.foo.test_bar unresolved after 3 attempts"}]',
                b"",
            )

    async def fake_subproc(*args, **kwargs):
        return FakeProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subproc)

    await loop._reconcile_closed_escalations()
    dedup.set_all.assert_called_once()
    remaining = dedup.set_all.call_args.args[0]
    assert "flake_tracker:tests.foo.test_bar" not in remaining
    state.clear_flake_attempts.assert_called_once_with("tests.foo.test_bar")


@pytest.mark.asyncio
async def test_kill_switch_short_circuits_do_work(loop_env) -> None:
    """Disabled kill-switch → _do_work returns `disabled` and skips reconcile (ADR-0049)."""
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    deps = LoopDeps(
        event_bus=EventBus(),
        stop_event=stop,
        status_cb=lambda *a, **k: None,
        enabled_cb=lambda name: name != "flake_tracker",
    )
    loop = FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=deps
    )
    loop._reconcile_closed_escalations = AsyncMock(return_value=None)
    loop._fetch_recent_runs = AsyncMock(
        side_effect=AssertionError("must not run when disabled")
    )
    stats = await loop._do_work()
    assert stats == {"status": "disabled"}
    loop._reconcile_closed_escalations.assert_not_awaited()
    pr.create_issue.assert_not_awaited()


# ---------------------------------------------------------------------------
# _download_junit — unit tests
# ---------------------------------------------------------------------------


def _make_loop(loop_env) -> FlakeTrackerLoop:
    cfg, state, pr, dedup = loop_env
    stop = asyncio.Event()
    return FlakeTrackerLoop(
        config=cfg, state=state, pr_manager=pr, dedup=dedup, deps=_deps(stop)
    )


_GOOD_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.a" name="test_one" />
    <testcase classname="tests.a" name="test_two">
      <failure message="boom"/>
    </testcase>
  </testsuite>
</testsuites>
"""


async def test_download_junit_missing_database_id_returns_empty(loop_env) -> None:
    """Run dict without databaseId → {} without calling subprocess."""
    loop = _make_loop(loop_env)
    result = await loop._download_junit({})
    assert result == {}


async def test_download_junit_missing_database_id_explicit_none(loop_env) -> None:
    """Run dict with databaseId=None → {} without calling subprocess."""
    loop = _make_loop(loop_env)
    result = await loop._download_junit({"databaseId": None})
    assert result == {}


async def test_download_junit_gh_failure_returns_empty(loop_env, monkeypatch) -> None:
    """Non-zero returncode from gh run download → {} (artifact not present)."""
    loop = _make_loop(loop_env)

    class _FailProc:
        returncode = 1

        async def communicate(self):
            return b"", b"no artifact named junit-scenario"

    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=_FailProc())
    )
    result = await loop._download_junit({"databaseId": 99})
    assert result == {}


async def test_download_junit_no_xml_files_returns_empty(loop_env, monkeypatch) -> None:
    """gh succeeds but writes no *.xml files → {}."""
    loop = _make_loop(loop_env)

    class _OkProc:
        returncode = 0

        async def communicate(self):
            return b"", b""

    # The subprocess writes nothing; the temp dir remains empty.
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(return_value=_OkProc())
    )
    result = await loop._download_junit({"databaseId": 7})
    assert result == {}


async def test_download_junit_valid_xml_returns_parsed_results(
    loop_env, monkeypatch
) -> None:
    """gh succeeds and writes a valid JUnit XML → parsed pass/fail dict."""
    loop = _make_loop(loop_env)
    captured_dir: list[str] = []

    class _OkProc:
        returncode = 0

        async def communicate(self):
            # Plant the XML in the directory that the loop passed via --dir.
            (Path(captured_dir[0]) / "results.xml").write_bytes(_GOOD_XML)
            return b"", b""

    async def _fake_exec(*args, **kwargs):
        # args[0] is the full command list; --dir <path> is the last two elements.
        cmd = list(args)
        dir_idx = cmd.index("--dir")
        captured_dir.append(cmd[dir_idx + 1])
        return _OkProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    result = await loop._download_junit({"databaseId": 42})
    assert result == {
        "tests.a.test_one": "pass",
        "tests.a.test_two": "fail",
    }


async def test_download_junit_malformed_xml_skipped(loop_env, monkeypatch) -> None:
    """ET.ParseError on a single file → that file is skipped; valid files still parsed."""
    loop = _make_loop(loop_env)
    captured_dir: list[str] = []

    class _OkProc:
        returncode = 0

        async def communicate(self):
            d = Path(captured_dir[0])
            (d / "bad.xml").write_bytes(b"<<< not xml >>>")
            (d / "good.xml").write_bytes(_GOOD_XML)
            return b"", b""

    async def _fake_exec(*args, **kwargs):
        cmd = list(args)
        dir_idx = cmd.index("--dir")
        captured_dir.append(cmd[dir_idx + 1])
        return _OkProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    result = await loop._download_junit({"databaseId": 5})
    # bad.xml triggers ET.ParseError → skipped; good.xml is parsed normally.
    assert "tests.a.test_one" in result
    assert "tests.a.test_two" in result


async def test_download_junit_multiple_xml_files_merged(loop_env, monkeypatch) -> None:
    """Multiple *.xml files in the artifact dir → results merged into one dict."""
    loop = _make_loop(loop_env)
    captured_dir: list[str] = []

    second_xml = b"""<?xml version="1.0" encoding="utf-8"?>
<testsuites>
  <testsuite name="pytest">
    <testcase classname="tests.b" name="test_three">
      <failure message="oops"/>
    </testcase>
  </testsuite>
</testsuites>
"""

    class _OkProc:
        returncode = 0

        async def communicate(self):
            d = Path(captured_dir[0])
            (d / "first.xml").write_bytes(_GOOD_XML)
            (d / "second.xml").write_bytes(second_xml)
            return b"", b""

    async def _fake_exec(*args, **kwargs):
        cmd = list(args)
        dir_idx = cmd.index("--dir")
        captured_dir.append(cmd[dir_idx + 1])
        return _OkProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    result = await loop._download_junit({"databaseId": 13})
    assert result["tests.a.test_one"] == "pass"
    assert result["tests.a.test_two"] == "fail"
    assert result["tests.b.test_three"] == "fail"


async def test_download_junit_only_malformed_xml_returns_empty(
    loop_env, monkeypatch
) -> None:
    """All XML files malformed → {} (every file triggers ET.ParseError and is skipped)."""
    loop = _make_loop(loop_env)
    captured_dir: list[str] = []

    class _OkProc:
        returncode = 0

        async def communicate(self):
            d = Path(captured_dir[0])
            (d / "broken.xml").write_bytes(b"<not><valid xml")
            return b"", b""

    async def _fake_exec(*args, **kwargs):
        cmd = list(args)
        dir_idx = cmd.index("--dir")
        captured_dir.append(cmd[dir_idx + 1])
        return _OkProc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", _fake_exec)
    result = await loop._download_junit({"databaseId": 3})
    assert result == {}
