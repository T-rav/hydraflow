"""Unit tests for the Tier-1 boot-correctness guard (#10734).

The pure :func:`decide_boot_action` truth table is the load-bearing piece: it is
the structural reason the kernel can never ``POST /api/control/start`` onto a
stale or wrong-branch boot (the 2026-07-27 incident). The thin I/O edge is
exercised with monkeypatched probes — no real network, no launchctl, no kills.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.liveness import boot_guard
from scripts.liveness.boot_guard import BootAction

_ORIGIN = "a" * 40  # a stand-in origin/<branch> HEAD sha


class TestDecideBootActionTruthTable:
    def test_matching_branch_matching_sha_zero_behind_idle_starts(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="idle",
        )
        assert d.action is BootAction.START

    def test_boot_sha_differs_reboots_and_never_starts(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha="b" * 40,
            commits_behind=0,
            status="idle",
        )
        assert d.action is BootAction.RESYNC_REBOOT
        assert d.action is not BootAction.START

    def test_commits_behind_reboots_even_when_boot_sha_unreadable(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=None,  # unreadable
            commits_behind=90,
            status="idle",
        )
        assert d.action is BootAction.RESYNC_REBOOT

    def test_workspace_on_main_while_factory_staging_reboots(self) -> None:
        # The literal 2026-07-27 shape: booted on main while staging is the branch.
        d = boot_guard.decide_boot_action(
            workspace_branch="main",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="idle",
        )
        assert d.action is BootAction.RESYNC_REBOOT

    def test_unavailable_origin_tip_is_no_action_with_notify_never_start(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=None,  # remote unreadable
            boot_sha=_ORIGIN,
            commits_behind=None,
            status="idle",
        )
        assert d.action is BootAction.NO_ACTION
        assert d.action is not BootAction.START
        assert d.notify is True

    def test_running_with_clean_boot_is_no_action(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="running",
        )
        assert d.action is BootAction.NO_ACTION

    def test_unreadable_status_is_no_action_never_reboot(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="main",  # even a wrong branch
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha="b" * 40,
            commits_behind=99,
            status=None,  # status API unreachable
        )
        assert d.action is BootAction.NO_ACTION

    def test_done_status_with_clean_boot_starts(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="done",
        )
        assert d.action is BootAction.START


class TestOperatorStoppedLatch:
    """An operator's Stop is a latch the kernel must honour (ADR-0135).

    ``/api/control/status`` reports ``idle`` after ``POST /api/control/stop``
    (the orchestrator is gone), so without the latch a verified-correct boot
    would be kicked straight back up with ``/api/control/start`` on the next
    5-minute tick — undoing the operator's deliberate stop.
    """

    def test_idle_verified_boot_under_latch_is_no_action_not_start(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="idle",
            operator_stopped=True,
        )
        assert d.action is BootAction.NO_ACTION
        # Latch reason, and no notification spam — a deliberate stop is not
        # an incident.
        assert ("operator stopped" in d.reason, d.notify) == (True, False)

    def test_done_status_under_latch_is_no_action(self) -> None:
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="done",
            operator_stopped=True,
        )
        assert d.action is BootAction.NO_ACTION

    def test_stale_boot_under_latch_still_resync_reboots(self) -> None:
        # The latch suppresses START only. A stale boot is still healed: the
        # relaunch boots INTO the latch (factory_autostart honours it too) and
        # stays stopped — that is the designed behaviour.
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha="b" * 40,
            commits_behind=0,
            status="idle",
            operator_stopped=True,
        )
        assert d.action is BootAction.RESYNC_REBOOT

    def test_running_under_latch_is_no_action_without_latch_reason(self) -> None:
        # A latch with a still-running orchestrator is a transient (stop in
        # flight) — the "already active" branch wins, never a START.
        d = boot_guard.decide_boot_action(
            workspace_branch="staging",
            factory_branch="staging",
            origin_head=_ORIGIN,
            boot_sha=_ORIGIN,
            commits_behind=0,
            status="running",
            operator_stopped=True,
        )
        assert d.action is BootAction.NO_ACTION


class TestExtractStatusFields:
    def test_pulls_nested_config_fields(self) -> None:
        body = {
            "status": "idle",
            "config": {"boot_sha": _ORIGIN, "commits_behind": 3},
        }
        assert boot_guard.extract_status_fields(body) == ("idle", _ORIGIN, 3, False)

    def test_missing_config_yields_none_facts(self) -> None:
        assert boot_guard.extract_status_fields({"status": "running"}) == (
            "running",
            None,
            None,
            False,
        )

    def test_bool_commits_behind_is_rejected(self) -> None:
        # bool is an int subclass — True must not read as "1 commit behind".
        body = {"status": "idle", "config": {"commits_behind": True}}
        assert boot_guard.extract_status_fields(body)[2] is None

    def test_wrong_typed_fields_become_none(self) -> None:
        body = {"status": 5, "config": {"boot_sha": 123, "commits_behind": "x"}}
        assert boot_guard.extract_status_fields(body) == (None, None, None, False)

    def test_operator_stopped_true_is_read(self) -> None:
        body = {"status": "idle", "operator_stopped": True}
        assert boot_guard.extract_status_fields(body)[3] is True

    def test_operator_stopped_missing_fails_open_to_false(self) -> None:
        # A pre-ADR-0135 factory (no field) keeps the existing START behaviour.
        assert boot_guard.extract_status_fields({"status": "idle"})[3] is False

    def test_operator_stopped_non_bool_fails_open_to_false(self) -> None:
        # Only a literal JSON true counts — "true"/1 must not latch the kernel.
        for junk in ("true", 1, None, {"x": 1}):
            body = {"status": "idle", "operator_stopped": junk}
            assert boot_guard.extract_status_fields(body)[3] is False, junk


class TestFetchControlStatus:
    def test_non_http_scheme_rejected(self) -> None:
        assert boot_guard.fetch_control_status("file:///etc/passwd") is None

    def test_unreachable_port_returns_none(self) -> None:
        # Port 1 refuses immediately — no real network needed.
        assert (
            boot_guard.fetch_control_status("http://127.0.0.1:1/x", timeout=1.0) is None
        )


class TestProbeBootCorrectnessComposition:
    """The stale-boot-prevention path, end to end over monkeypatched probes."""

    def test_stale_boot_yields_resync_reboot_not_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            boot_guard,
            "fetch_control_status",
            lambda *a, **k: {
                "status": "idle",
                "config": {"boot_sha": "b" * 40, "commits_behind": 90},
            },
        )
        monkeypatch.setattr(boot_guard, "git_current_branch", lambda ws: "main")
        monkeypatch.setattr(boot_guard, "git_origin_head", lambda ws, br: _ORIGIN)
        decision = boot_guard.probe_boot_correctness(
            workspace=Path("/tmp/ws"),
            factory_branch="staging",
            status_url="http://127.0.0.1:5555/api/control/status",
        )
        assert decision.action is BootAction.RESYNC_REBOOT
        assert decision.action is not BootAction.START

    def test_clean_boot_yields_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            boot_guard,
            "fetch_control_status",
            lambda *a, **k: {
                "status": "idle",
                "config": {"boot_sha": _ORIGIN, "commits_behind": 0},
            },
        )
        monkeypatch.setattr(boot_guard, "git_current_branch", lambda ws: "staging")
        monkeypatch.setattr(boot_guard, "git_origin_head", lambda ws, br: _ORIGIN)
        decision = boot_guard.probe_boot_correctness(
            workspace=Path("/tmp/ws"),
            factory_branch="staging",
            status_url="http://127.0.0.1:5555/api/control/status",
        )
        assert decision.action is BootAction.START

    def test_clean_idle_boot_under_operator_latch_yields_no_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The exact post-Stop shape: verified-correct boot, orchestrator gone
        # ("idle"), latch set. The kernel must not undo the operator's Stop.
        monkeypatch.setattr(
            boot_guard,
            "fetch_control_status",
            lambda *a, **k: {
                "status": "idle",
                "operator_stopped": True,
                "config": {"boot_sha": _ORIGIN, "commits_behind": 0},
            },
        )
        monkeypatch.setattr(boot_guard, "git_current_branch", lambda ws: "staging")
        monkeypatch.setattr(boot_guard, "git_origin_head", lambda ws, br: _ORIGIN)
        decision = boot_guard.probe_boot_correctness(
            workspace=Path("/tmp/ws"),
            factory_branch="staging",
            status_url="http://127.0.0.1:5555/api/control/status",
        )
        assert decision.action is BootAction.NO_ACTION
        assert decision.notify is False

    def test_unreadable_status_short_circuits_to_no_action(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(boot_guard, "fetch_control_status", lambda *a, **k: None)
        decision = boot_guard.probe_boot_correctness(
            workspace=Path("/tmp/ws"),
            factory_branch="staging",
            status_url="http://127.0.0.1:5555/api/control/status",
        )
        assert decision.action is BootAction.NO_ACTION


class TestGitProbesAgainstRealRepo:
    """Real throwaway git repos — cheap, and proves the probe shape is right."""

    def test_current_branch_and_origin_head(self, tmp_path: Path) -> None:
        origin = tmp_path / "origin"
        origin.mkdir()
        _git(origin, "init", "-q", "-b", "staging")
        (origin / "f").write_text("x", encoding="utf-8")
        _git(origin, "add", "-A")
        _git(origin, "commit", "-qm", "c0")

        workspace = tmp_path / "ws"
        _git(tmp_path, "clone", "-q", str(origin), str(workspace))
        _git(workspace, "checkout", "-q", "staging")

        assert boot_guard.git_current_branch(workspace) == "staging"
        head = boot_guard.git_origin_head(workspace, "staging")
        assert head == _git(origin, "rev-parse", "HEAD").stdout.strip()

    def test_detached_head_is_none(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        repo.mkdir()
        _git(repo, "init", "-q", "-b", "staging")
        (repo / "f").write_text("x", encoding="utf-8")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "c0")
        sha = _git(repo, "rev-parse", "HEAD").stdout.strip()
        _git(repo, "checkout", "-q", sha)  # detach
        assert boot_guard.git_current_branch(repo) is None

    def test_missing_workspace_returns_none(self, tmp_path: Path) -> None:
        assert boot_guard.git_current_branch(tmp_path / "nope") is None


# Isolate git from any global/system config (CI must not depend on it).
_GIT_ENV = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
}


def _git(repo: Path, *args: str):
    import os
    import subprocess

    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, **_GIT_ENV},
    )
