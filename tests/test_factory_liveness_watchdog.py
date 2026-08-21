"""Unit tests for the external liveness watchdog (#10009).

Loads scripts/factory_liveness_watchdog.py via importlib — same pattern as
tests/test_check_conflict_markers.py — since it's a standalone script, not
part of the ``src`` package (deliberately: it must not import the thing it
watches). No real network or launchctl/osascript calls are made anywhere in
this file: ``check_healthz`` is exercised against a real closed local port
(offline-safe, no external network needed) and ``subprocess.run`` is
monkeypatched wherever a restart/notification path is exercised.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "factory_liveness_watchdog.py"
_spec = importlib.util.spec_from_file_location("factory_liveness_watchdog", _SCRIPT)
assert _spec and _spec.loader
watchdog = importlib.util.module_from_spec(_spec)
sys.modules["factory_liveness_watchdog"] = watchdog
_spec.loader.exec_module(watchdog)


def _write_events(tmp_path: Path, lines: list[str]) -> Path:
    path = tmp_path / "events.jsonl"
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return path


class TestParseKnobFile:
    def test_parses_key_value_lines(self) -> None:
        text = "RESTART_ENABLED=true\nRESTART_LABEL=com.hydraflow.factory\n"
        assert watchdog.parse_knob_file(text) == {
            "RESTART_ENABLED": "true",
            "RESTART_LABEL": "com.hydraflow.factory",
        }

    def test_skips_blank_lines_and_comments(self) -> None:
        text = "\n# a comment\nRESTART_ENABLED=false\n   \n"
        assert watchdog.parse_knob_file(text) == {"RESTART_ENABLED": "false"}

    def test_empty_file_returns_empty_dict(self) -> None:
        assert watchdog.parse_knob_file("") == {}

    def test_lines_without_equals_are_ignored(self) -> None:
        assert watchdog.parse_knob_file("not-a-key-value-line\n") == {}


class TestIsRestartEnabled:
    @pytest.mark.parametrize("value", ["true", "True", "1", "yes"])
    def test_truthy_values(self, value: str) -> None:
        assert watchdog.is_restart_enabled({"RESTART_ENABLED": value}) is True

    @pytest.mark.parametrize("value", ["false", "0", "no", ""])
    def test_falsy_values(self, value: str) -> None:
        assert watchdog.is_restart_enabled({"RESTART_ENABLED": value}) is False

    def test_missing_key_is_falsy(self) -> None:
        assert watchdog.is_restart_enabled({}) is False


class TestReadLastJsonlTimestamp:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        assert watchdog.read_last_jsonl_timestamp(tmp_path / "nope.jsonl") is None

    def test_reads_last_line_timestamp(self, tmp_path: Path) -> None:
        path = _write_events(
            tmp_path,
            [
                '{"timestamp": "2026-07-01T00:00:00+00:00"}',
                '{"timestamp": "2026-07-02T00:00:00+00:00"}',
            ],
        )
        assert watchdog.read_last_jsonl_timestamp(path) == datetime(
            2026, 7, 2, tzinfo=UTC
        )

    def test_falls_back_past_corrupt_trailing_line(self, tmp_path: Path) -> None:
        path = _write_events(
            tmp_path,
            ['{"timestamp": "2026-07-01T00:00:00+00:00"}', "corrupt {{{"],
        )
        assert watchdog.read_last_jsonl_timestamp(path) == datetime(
            2026, 7, 1, tzinfo=UTC
        )

    def test_all_corrupt_returns_none(self, tmp_path: Path) -> None:
        path = _write_events(tmp_path, ["{{{", "nope"])
        assert watchdog.read_last_jsonl_timestamp(path) is None


class TestCheckHealthz:
    def test_unreachable_port_is_down(self) -> None:
        # Port 1 is a privileged/reserved port almost never bound locally;
        # connection is refused immediately — no real network access needed.
        assert watchdog.check_healthz("http://127.0.0.1:1/healthz", 1.0) is False

    def test_invalid_url_is_down(self) -> None:
        assert watchdog.check_healthz("not-a-url", 1.0) is False

    def test_non_http_scheme_rejected_without_calling_urlopen(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """bandit B310: urlopen() also honours file:// and other unexpected
        schemes — the scheme check must reject those BEFORE urlopen is ever
        called, not merely happen to fail inside it."""
        called = False

        def _fake_urlopen(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(watchdog.urllib.request, "urlopen", _fake_urlopen)
        assert watchdog.check_healthz("file:///etc/passwd", 1.0) is False
        assert called is False

    def test_success_response_is_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _FakeResp:
            status = 200

            def __enter__(self) -> _FakeResp:
                return self

            def __exit__(self, *exc: object) -> None:
                return None

        monkeypatch.setattr(
            watchdog.urllib.request, "urlopen", lambda *a, **k: _FakeResp()
        )
        assert watchdog.check_healthz("http://127.0.0.1:5555/healthz", 1.0) is True


class TestMarkerRoundTrip:
    def test_read_missing_marker_returns_none(self, tmp_path: Path) -> None:
        assert watchdog.read_marker(tmp_path / "state.json") is None

    def test_write_then_read_round_trips(self, tmp_path: Path) -> None:
        path = tmp_path / "liveness" / "state.json"
        data = {"down_since": "2026-07-01T00:00:00+00:00", "restarted": False}
        watchdog.write_marker(path, data)
        assert watchdog.read_marker(path) == data

    def test_clear_marker_removes_file(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        watchdog.write_marker(path, {"down_since": "x"})
        watchdog.clear_marker(path)
        assert not path.exists()

    def test_clear_marker_missing_file_is_noop(self, tmp_path: Path) -> None:
        watchdog.clear_marker(tmp_path / "does-not-exist.json")  # must not raise

    def test_corrupt_marker_file_treated_as_absent(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        path.write_text("not json", encoding="utf-8")
        assert watchdog.read_marker(path) is None


class TestDecide:
    """Pure decision logic — the heart of the watchdog."""

    def test_healthy_no_marker_is_noop(self) -> None:
        d = watchdog.decide(
            healthz_ok=True,
            events_age_seconds=10.0,
            stale_threshold_seconds=900,
            marker=None,
            restart_enabled=False,
            now=datetime.now(UTC),
        )
        assert d.is_down is False
        assert d.should_notify is False
        assert d.should_restart is False
        assert d.new_marker is None

    def test_healthz_down_triggers_down(self) -> None:
        d = watchdog.decide(
            healthz_ok=False,
            events_age_seconds=None,
            stale_threshold_seconds=900,
            marker=None,
            restart_enabled=False,
            now=datetime.now(UTC),
        )
        assert d.is_down is True
        assert d.should_notify is True
        assert d.new_marker is not None
        assert "down_since" in d.new_marker

    def test_stale_events_triggers_down_even_if_healthz_ok(self) -> None:
        d = watchdog.decide(
            healthz_ok=True,
            events_age_seconds=1000.0,
            stale_threshold_seconds=900,
            marker=None,
            restart_enabled=False,
            now=datetime.now(UTC),
        )
        assert d.is_down is True

    def test_events_age_under_threshold_is_healthy(self) -> None:
        d = watchdog.decide(
            healthz_ok=True,
            events_age_seconds=100.0,
            stale_threshold_seconds=900,
            marker=None,
            restart_enabled=False,
            now=datetime.now(UTC),
        )
        assert d.is_down is False

    def test_down_and_restart_disabled_never_restarts(self) -> None:
        d = watchdog.decide(
            healthz_ok=False,
            events_age_seconds=None,
            stale_threshold_seconds=900,
            marker=None,
            restart_enabled=False,
            now=datetime.now(UTC),
        )
        assert d.should_restart is False

    def test_down_and_restart_enabled_restarts_once(self) -> None:
        d = watchdog.decide(
            healthz_ok=False,
            events_age_seconds=None,
            stale_threshold_seconds=900,
            marker=None,
            restart_enabled=True,
            now=datetime.now(UTC),
        )
        assert d.should_restart is True
        assert d.new_marker is not None
        assert d.new_marker["restarted"] is True

    def test_down_already_restarted_does_not_restart_again(self) -> None:
        now = datetime.now(UTC)
        marker = {
            "down_since": (now - timedelta(minutes=10)).isoformat(),
            "restarted": True,
        }
        d = watchdog.decide(
            healthz_ok=False,
            events_age_seconds=None,
            stale_threshold_seconds=900,
            marker=marker,
            restart_enabled=True,
            now=now,
        )
        assert d.should_restart is False
        assert d.is_down is True
        assert d.new_marker is not None
        assert d.new_marker["restarted"] is True  # stays True, not reset

    def test_down_since_persists_across_ticks(self) -> None:
        now = datetime.now(UTC)
        original_since = (now - timedelta(hours=2)).isoformat()
        marker = {"down_since": original_since, "restarted": True}
        d = watchdog.decide(
            healthz_ok=False,
            events_age_seconds=None,
            stale_threshold_seconds=900,
            marker=marker,
            restart_enabled=True,
            now=now,
        )
        assert d.new_marker is not None
        assert d.new_marker["down_since"] == original_since

    def test_recovery_clears_marker_and_notifies(self) -> None:
        now = datetime.now(UTC)
        marker = {"down_since": "2026-07-01T00:00:00+00:00", "restarted": True}
        d = watchdog.decide(
            healthz_ok=True,
            events_age_seconds=5.0,
            stale_threshold_seconds=900,
            marker=marker,
            restart_enabled=True,
            now=now,
        )
        assert d.is_down is False
        assert d.should_notify is True
        assert d.should_restart is False
        assert d.new_marker is None
        assert "recovered" in d.notify_message.lower()


class TestSendNotificationAndRestartDryRun:
    """Never touch the real system: dry_run=True must not call subprocess."""

    def test_send_notification_dry_run_skips_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fake_run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fake_run)
        watchdog.send_notification("hello", dry_run=True)
        assert called is False

    def test_attempt_restart_dry_run_skips_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fake_run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fake_run)
        watchdog.attempt_restart({"RESTART_ENABLED": "true"}, dry_run=True)
        assert called is False

    def test_attempt_restart_no_target_configured_skips_subprocess(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fake_run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fake_run)
        watchdog.attempt_restart({"RESTART_ENABLED": "true"}, dry_run=False)
        assert called is False

    def test_attempt_restart_with_label_calls_launchctl_kickstart(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def _fake_run(argv: list[str], **k: object) -> object:
            calls.append(argv)

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        watchdog.attempt_restart(
            {"RESTART_ENABLED": "true", "RESTART_LABEL": "com.hydraflow.factory"},
            dry_run=False,
        )
        assert len(calls) == 1
        assert calls[0][:3] == ["launchctl", "kickstart", "-k"]
        assert calls[0][3].endswith("com.hydraflow.factory")

    def test_attempt_restart_with_command_prefers_command_over_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[object] = []

        def _fake_run(argv: object, **k: object) -> object:
            calls.append(argv)

            class _R:
                returncode = 0

            return _R()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        watchdog.attempt_restart(
            {
                "RESTART_ENABLED": "true",
                "RESTART_LABEL": "com.hydraflow.factory",
                "RESTART_COMMAND": "echo restart",
            },
            dry_run=False,
        )
        # RESTART_COMMAND is shlex-split into an argv list — never shell=True
        # (bandit B602) — even though this string is operator-authored.
        assert calls == [["echo", "restart"]]

    def test_attempt_restart_command_with_unbalanced_quotes_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fake_run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fake_run)
        watchdog.attempt_restart(
            {"RESTART_ENABLED": "true", "RESTART_COMMAND": 'unterminated "quote'},
            dry_run=False,
        )
        assert called is False


class TestMainEndToEnd:
    """main() orchestration, always with --dry-run so no marker file is
    written and no subprocess call ever fires for real."""

    def test_healthy_dry_run_is_quiet(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setattr(watchdog, "check_healthz", lambda *a, **k: True)
        events = _write_events(
            tmp_path,
            [json.dumps({"timestamp": datetime.now(UTC).isoformat()})],
        )
        rc = watchdog.main(
            [
                "--dry-run",
                "--events-path",
                str(events),
                "--marker-path",
                str(tmp_path / "state.json"),
                "--knob-path",
                str(tmp_path / "restart.knob"),
            ]
        )
        assert rc == 0
        assert not (tmp_path / "state.json").exists()

    def test_down_dry_run_never_writes_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(watchdog, "check_healthz", lambda *a, **k: False)
        rc = watchdog.main(
            [
                "--dry-run",
                "--events-path",
                str(tmp_path / "events.jsonl"),
                "--marker-path",
                str(tmp_path / "state.json"),
                "--knob-path",
                str(tmp_path / "restart.knob"),
            ]
        )
        assert rc == 0
        # --dry-run must never persist the marker file, even when down.
        assert not (tmp_path / "state.json").exists()

    def test_down_non_dry_run_writes_marker_without_real_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(watchdog, "check_healthz", lambda *a, **k: False)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        marker_path = tmp_path / "state.json"
        rc = watchdog.main(
            [
                "--events-path",
                str(tmp_path / "events.jsonl"),
                "--marker-path",
                str(marker_path),
                "--knob-path",
                str(tmp_path / "restart.knob"),
            ]
        )
        assert rc == 0
        assert marker_path.exists()
        data = json.loads(marker_path.read_text())
        assert "down_since" in data

    def test_recovery_non_dry_run_clears_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        marker_path = tmp_path / "state.json"
        watchdog.write_marker(
            marker_path,
            {"down_since": "2026-07-01T00:00:00+00:00", "restarted": False},
        )
        monkeypatch.setattr(watchdog, "check_healthz", lambda *a, **k: True)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        rc = watchdog.main(
            [
                "--events-path",
                str(tmp_path / "events.jsonl"),
                "--marker-path",
                str(marker_path),
                "--knob-path",
                str(tmp_path / "restart.knob"),
            ]
        )
        assert rc == 0
        assert not marker_path.exists()


# --------------------------------------------------------------------------
# Tier-1 boot-correctness kernel (#10734).
# --------------------------------------------------------------------------

_BootAction = watchdog.boot_guard.BootAction


def _reboot_decision(reason: str = "stale boot") -> object:
    return watchdog.boot_guard.BootDecision(
        _BootAction.RESYNC_REBOOT, reason, notify=True
    )


def _start_decision() -> object:
    return watchdog.boot_guard.BootDecision(_BootAction.START, "clean boot")


class TestBranchPinDefault:
    """Deliverable 2: relaunch always pinned to staging, never the shell 'main'."""

    def test_factory_branch_defaults_to_staging_with_env_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_FACTORY_BRANCH", raising=False)
        args = watchdog.build_arg_parser().parse_args([])
        assert args.factory_branch == "staging"


class TestRebootFactory:
    """The reboot actuator: kill the port group, then detached-relaunch."""

    def _fake_launcher(self, tmp_path: Path) -> Path:
        launcher = tmp_path / "run-factory-isolated.sh"
        launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        return launcher

    def test_kills_port_group_then_spawns_detached_pinned_to_staging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        terminated: list[int] = []
        monkeypatch.setattr(
            watchdog, "find_port_listener_pids", lambda port, **k: [4242]
        )
        monkeypatch.setattr(watchdog, "_terminate_pid_group", terminated.append)
        popen_calls: list[tuple[object, dict[str, object]]] = []

        class _FakePopen:
            def __init__(self, argv: object, **kwargs: object) -> None:
                popen_calls.append((argv, kwargs))

        monkeypatch.setattr(watchdog.subprocess, "Popen", _FakePopen)

        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            launcher=self._fake_launcher(tmp_path),
            dry_run=False,
        )
        assert ok is True
        # Port group killed BEFORE the relaunch spawn.
        assert terminated == [4242]
        assert len(popen_calls) == 1
        argv, kwargs = popen_calls[0]
        assert argv[0] == "bash"
        # Detached so the kernel's own exit can't kill the launcher.
        assert kwargs["start_new_session"] is True
        # Branch pin — never the shell default 'main'.
        assert kwargs["env"]["HYDRAFLOW_FACTORY_BRANCH"] == "staging"

    def test_missing_launcher_returns_false_without_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(watchdog, "find_port_listener_pids", lambda port, **k: [])
        called = False

        def _popen(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(watchdog.subprocess, "Popen", _popen)
        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            launcher=tmp_path / "does-not-exist.sh",
            dry_run=False,
        )
        assert ok is False
        assert called is False

    def test_dry_run_performs_no_kill_and_no_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        killed = False
        spawned = False

        def _term(pid: int) -> None:
            nonlocal killed
            killed = True

        def _popen(*a: object, **k: object) -> None:
            nonlocal spawned
            spawned = True

        monkeypatch.setattr(watchdog, "_terminate_pid_group", _term)
        monkeypatch.setattr(watchdog.subprocess, "Popen", _popen)
        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            launcher=self._fake_launcher(tmp_path),
            dry_run=True,
        )
        assert ok is True
        assert killed is False
        assert spawned is False


class TestRebootFactoryViaLaunchdLabel:
    """ADR-0135: when the factory is a KeepAlive launchd service, a reboot is a
    ``launchctl kickstart -k`` of that label — launchd re-runs the service-mode
    launcher (which re-syncs). Killing the port group and spawning the
    dev-checkout launcher as well would race launchd's own restart: two
    factories contending for the dashboard port."""

    def test_label_kickstarts_instead_of_kill_and_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        terminated: list[int] = []
        monkeypatch.setattr(
            watchdog, "find_port_listener_pids", lambda port, **k: [4242]
        )
        monkeypatch.setattr(watchdog, "_terminate_pid_group", terminated.append)
        spawned = False

        def _popen(*a: object, **k: object) -> None:
            nonlocal spawned
            spawned = True

        monkeypatch.setattr(watchdog.subprocess, "Popen", _popen)
        runs: list[list[str]] = []

        def _run(argv: list[str], **k: object) -> object:
            runs.append(list(argv))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

        monkeypatch.setattr(watchdog.subprocess, "run", _run)
        monkeypatch.setattr(watchdog.os, "getuid", lambda: 501)

        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            launcher=tmp_path / "does-not-exist.sh",  # irrelevant under a label
            restart_label="com.hydraflow.factory",
            dry_run=False,
        )
        assert ok is True
        # One kickstart; launchd owns both the kill and the relaunch.
        assert (runs, terminated, spawned) == (
            [["launchctl", "kickstart", "-k", "gui/501/com.hydraflow.factory"]],
            [],
            False,
        )

    def test_label_kickstart_failure_returns_false(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            watchdog.subprocess,
            "run",
            lambda *a, **k: SimpleNamespace(returncode=113, stdout="", stderr="x"),
        )
        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            restart_label="com.hydraflow.factory",
            dry_run=False,
        )
        assert ok is False

    def test_dry_run_with_label_calls_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(watchdog.subprocess, "run", _run)
        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            restart_label="com.hydraflow.factory",
            dry_run=True,
        )
        assert ok is True
        assert called is False

    def test_blank_label_falls_back_to_kill_and_spawn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # An empty/whitespace RESTART_LABEL is "not configured" — exactly the
        # knob state install_liveness_watchdog.py seeds — so the legacy path
        # (kill port group + detached launcher spawn) stays in force.
        monkeypatch.setattr(watchdog, "find_port_listener_pids", lambda port, **k: [])
        popen_calls: list[object] = []

        class _FakePopen:
            def __init__(self, argv: object, **kwargs: object) -> None:
                popen_calls.append(argv)

        monkeypatch.setattr(watchdog.subprocess, "Popen", _FakePopen)
        launcher = tmp_path / "run-factory-isolated.sh"
        launcher.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        ok = watchdog.reboot_factory(
            workspace=tmp_path / "ws",
            factory_branch="staging",
            dashboard_port=5555,
            launcher=launcher,
            restart_label="   ",
            dry_run=False,
        )
        assert ok is True
        assert len(popen_calls) == 1


def _wire_kernel(
    monkeypatch: pytest.MonkeyPatch, *, decision: object, status: str = "idle"
) -> None:
    """Stub every live probe so main() with --workspace makes no real I/O."""
    monkeypatch.setattr(watchdog, "check_healthz", lambda *a, **k: True)
    monkeypatch.setattr(
        watchdog.boot_guard, "probe_boot_correctness", lambda **k: decision
    )
    monkeypatch.setattr(
        watchdog.boot_guard,
        "fetch_control_status",
        lambda *a, **k: {"status": status, "config": {}},
    )
    # Orphan reaper: header-only ps snapshot -> selects nothing -> never kills.
    monkeypatch.setattr(
        watchdog.orphan_reaper,
        "enumerate_processes",
        lambda **k: "  PID  PPID     ELAPSED COMMAND\n",
    )


class TestBootGuardMainWiring:
    """Deliverable 1: a stale boot is prevented at launch, not detected after."""

    def _args(self, tmp_path: Path, *, dry_run: bool = False) -> list[str]:
        argv = [
            "--workspace",
            str(tmp_path / "ws"),
            "--factory-branch",
            "staging",
            "--events-path",
            str(tmp_path / "events.jsonl"),
            "--marker-path",
            str(tmp_path / "state.json"),
            "--knob-path",
            str(tmp_path / "restart.knob"),
        ]
        if dry_run:
            argv.insert(0, "--dry-run")
        return argv

    def test_stale_boot_reboots_and_records_incident(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(monkeypatch, decision=_reboot_decision())
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            watchdog, "reboot_factory", lambda **k: calls.append(k) or True
        )
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)

        rc = watchdog.main(self._args(tmp_path))
        assert rc == 0
        # Rebooted once, pinned to staging.
        assert len(calls) == 1
        assert calls[0]["factory_branch"] == "staging"
        # Incident recorded so the next tick does not re-spawn.
        marker = json.loads((tmp_path / "state.json").read_text())
        assert "stale_reboot_at" in marker

    def test_stale_boot_reboot_carries_the_knob_restart_label(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The knob the two installers leave behind (ADR-0135): enabled + label.
        (tmp_path / "restart.knob").write_text(
            "RESTART_ENABLED=true\nRESTART_LABEL=com.hydraflow.factory\n",
            encoding="utf-8",
        )
        _wire_kernel(monkeypatch, decision=_reboot_decision())
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            watchdog, "reboot_factory", lambda **k: calls.append(k) or True
        )
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)
        monkeypatch.setattr(watchdog, "attempt_restart", lambda *a, **k: None)

        watchdog.main(self._args(tmp_path))

        assert len(calls) == 1
        assert calls[0]["restart_label"] == "com.hydraflow.factory"

    def test_stale_boot_without_label_passes_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(monkeypatch, decision=_reboot_decision())
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            watchdog, "reboot_factory", lambda **k: calls.append(k) or True
        )
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)

        watchdog.main(self._args(tmp_path))

        assert calls[0]["restart_label"] is None

    def test_stale_boot_reboots_at_most_once_per_incident(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(monkeypatch, decision=_reboot_decision())
        calls: list[dict[str, object]] = []
        monkeypatch.setattr(
            watchdog, "reboot_factory", lambda **k: calls.append(k) or True
        )
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)

        watchdog.main(self._args(tmp_path))  # tick 1 -> reboot
        watchdog.main(self._args(tmp_path))  # tick 2 -> still stale, no re-spawn
        assert len(calls) == 1

    def test_stale_boot_never_calls_control_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(monkeypatch, decision=_reboot_decision())
        monkeypatch.setattr(watchdog, "reboot_factory", lambda **k: True)
        posts: list[str] = []
        monkeypatch.setattr(
            watchdog, "http_post_status", lambda url, **k: posts.append(url)
        )
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)
        watchdog.main(self._args(tmp_path))
        assert not any("/api/control/start" in u for u in posts)

    def test_clean_boot_issues_control_start(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(monkeypatch, decision=_start_decision())
        posts: list[str] = []
        monkeypatch.setattr(
            watchdog,
            "http_post_status",
            lambda url, **k: posts.append(url) or "started",
        )
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)
        watchdog.main(self._args(tmp_path))
        assert any("/api/control/start" in u for u in posts)

    def test_dry_run_stale_boot_writes_no_marker(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(monkeypatch, decision=_reboot_decision())
        monkeypatch.setattr(watchdog, "reboot_factory", lambda **k: True)
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)
        rc = watchdog.main(self._args(tmp_path, dry_run=True))
        assert rc == 0
        assert not (tmp_path / "state.json").exists()

    def test_no_workspace_skips_boot_guard_entirely(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Legacy notify-only mode: without --workspace the guard never runs.
        called = False

        def _probe(**k: object) -> object:
            nonlocal called
            called = True
            return _reboot_decision()

        monkeypatch.setattr(watchdog, "check_healthz", lambda *a, **k: True)
        monkeypatch.setattr(watchdog.boot_guard, "probe_boot_correctness", _probe)
        rc = watchdog.main(
            [
                "--dry-run",
                "--events-path",
                str(tmp_path / "events.jsonl"),
                "--marker-path",
                str(tmp_path / "state.json"),
                "--knob-path",
                str(tmp_path / "restart.knob"),
            ]
        )
        assert rc == 0
        assert called is False


class TestOrphanReaperMainWiring:
    def test_reaper_kills_selected_orphans_non_dry_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _wire_kernel(
            monkeypatch,
            decision=watchdog.boot_guard.BootDecision(
                _BootAction.NO_ACTION, "already running"
            ),
        )
        # A ps snapshot with one genuine orphan; reap is monkeypatched (no kills).
        monkeypatch.setattr(
            watchdog.orphan_reaper,
            "enumerate_processes",
            lambda **k: (
                "  PID  PPID     ELAPSED COMMAND\n"
                "9999     1    50:00 python -m pytest -n auto tests/\n"
            ),
        )
        reaped: list[int] = []
        monkeypatch.setattr(
            watchdog.orphan_reaper,
            "reap_orphans",
            lambda pids: reaped.extend(pids) or pids,
        )
        monkeypatch.setattr(watchdog, "reboot_factory", lambda **k: True)
        monkeypatch.setattr(watchdog, "send_notification", lambda *a, **k: None)
        watchdog.main(
            [
                "--workspace",
                str(tmp_path / "ws"),
                "--events-path",
                str(tmp_path / "events.jsonl"),
                "--marker-path",
                str(tmp_path / "state.json"),
                "--knob-path",
                str(tmp_path / "restart.knob"),
            ]
        )
        assert reaped == [9999]
