"""Unit tests for the liveness-watchdog launchd installer (#10009).

Loads scripts/install_liveness_watchdog.py via importlib (same pattern as
tests/test_check_conflict_markers.py). No test ever calls real
``launchctl``: every path that would shell out monkeypatches
``subprocess.run`` first, and the dry-run tests assert it is never called at
all.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "install_liveness_watchdog.py"
_spec = importlib.util.spec_from_file_location("install_liveness_watchdog", _SCRIPT)
assert _spec and _spec.loader
installer = importlib.util.module_from_spec(_spec)
sys.modules["install_liveness_watchdog"] = installer
_spec.loader.exec_module(installer)


class TestRenderPlist:
    def test_contains_label_and_interval(self, tmp_path: Path) -> None:
        xml = installer.render_plist(
            label="com.hydraflow.liveness",
            python_executable="/usr/bin/python3",
            watchdog_script=tmp_path / "watchdog.py",
            extra_args=[],
            start_interval=300,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
        assert "<string>com.hydraflow.liveness</string>" in xml
        assert "<integer>300</integer>" in xml
        assert "<string>/usr/bin/python3</string>" in xml
        assert str(tmp_path / "watchdog.py") in xml
        assert "<true/>" in xml  # RunAtLoad

    def test_extra_args_appear_as_separate_strings(self, tmp_path: Path) -> None:
        xml = installer.render_plist(
            label="com.hydraflow.liveness",
            python_executable="/usr/bin/python3",
            watchdog_script=tmp_path / "watchdog.py",
            extra_args=["--healthz-url", "http://127.0.0.1:5555/healthz"],
            start_interval=300,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
        assert "<string>--healthz-url</string>" in xml
        assert "<string>http://127.0.0.1:5555/healthz</string>" in xml

    def test_escapes_special_xml_characters(self, tmp_path: Path) -> None:
        xml = installer.render_plist(
            label="com.hydraflow.liveness",
            python_executable="/usr/bin/python3",
            watchdog_script=tmp_path / "watchdog.py",
            extra_args=["--healthz-url", "http://host/a&b"],
            start_interval=300,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
        assert "a&amp;b" in xml
        assert "a&b" not in xml

    def test_is_valid_xml(self, tmp_path: Path) -> None:
        import xml.etree.ElementTree as ET

        xml_text = installer.render_plist(
            label="com.hydraflow.liveness",
            python_executable="/usr/bin/python3",
            watchdog_script=tmp_path / "watchdog.py",
            extra_args=["--stale-seconds", "900"],
            start_interval=300,
            stdout_path=tmp_path / "out.log",
            stderr_path=tmp_path / "err.log",
        )
        # DOCTYPE with an external DTD reference — strip it so ElementTree
        # (which has no network access here) doesn't try to resolve it.
        body = xml_text.split("<plist", 1)
        parseable = "<plist" + body[1]
        ET.fromstring(parseable)  # noqa: S314 — trusted, locally-rendered XML


class TestInstallDryRun:
    def test_dry_run_never_calls_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fake_run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fake_run)
        plist_path = tmp_path / "com.hydraflow.liveness.plist"
        installer.install(
            plist_path=plist_path,
            log_dir=tmp_path / "logs",
            extra_args=[],
            dry_run=True,
        )
        assert called is False
        assert not plist_path.exists()

    def test_uninstall_dry_run_never_calls_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        called = False

        def _fake_run(*a: object, **k: object) -> None:
            nonlocal called
            called = True

        monkeypatch.setattr(subprocess, "run", _fake_run)
        plist_path = tmp_path / "com.hydraflow.liveness.plist"
        plist_path.write_text("<plist/>", encoding="utf-8")
        installer.uninstall(plist_path=plist_path, dry_run=True)
        assert called is False
        assert plist_path.exists()  # dry-run never removes it


class TestInstallRealPathWithFakeSubprocess:
    """Exercise the non-dry-run branch, but subprocess.run is monkeypatched
    so no real launchctl call ever happens."""

    def test_install_writes_plist_and_bootstraps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls: list[list[str]] = []

        def _fake_run(argv: list[str], **k: object) -> object:
            calls.append(argv)

            class _R:
                returncode = 0
                stdout = ""
                stderr = ""

            return _R()

        monkeypatch.setattr(subprocess, "run", _fake_run)
        plist_path = tmp_path / "LaunchAgents" / "com.hydraflow.liveness.plist"
        installer.install(
            plist_path=plist_path,
            log_dir=tmp_path / "logs",
            extra_args=["--healthz-url", "http://127.0.0.1:5555/healthz"],
            dry_run=False,
        )
        assert plist_path.exists()
        assert "com.hydraflow.liveness" in plist_path.read_text()
        # bootout (idempotent unload) then bootstrap (load) — in that order.
        assert [c[1] for c in calls] == ["bootout", "bootstrap"]

    def test_install_is_idempotent_across_two_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        plist_path = tmp_path / "com.hydraflow.liveness.plist"
        installer.install(
            plist_path=plist_path,
            log_dir=tmp_path / "logs",
            extra_args=[],
            dry_run=False,
        )
        first_content = plist_path.read_text()
        installer.install(
            plist_path=plist_path,
            log_dir=tmp_path / "logs",
            extra_args=[],
            dry_run=False,
        )
        second_content = plist_path.read_text()
        assert first_content == second_content

    def test_uninstall_removes_plist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        plist_path = tmp_path / "com.hydraflow.liveness.plist"
        installer.install(
            plist_path=plist_path,
            log_dir=tmp_path / "logs",
            extra_args=[],
            dry_run=False,
        )
        assert plist_path.exists()
        installer.uninstall(plist_path=plist_path, dry_run=False)
        assert not plist_path.exists()

    def test_uninstall_missing_plist_is_safe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: None)
        installer.uninstall(
            plist_path=tmp_path / "does-not-exist.plist", dry_run=False
        )  # must not raise


class TestMainArgParsing:
    def test_main_dry_run_install_returns_zero(self, tmp_path: Path) -> None:
        # --dry-run bypasses the Darwin-only guard, so this passes on any OS.
        rc = installer.main(
            [
                "--dry-run",
                "--plist-path",
                str(tmp_path / "com.hydraflow.liveness.plist"),
            ]
        )
        assert rc == 0

    def test_main_dry_run_uninstall_returns_zero(self, tmp_path: Path) -> None:
        rc = installer.main(
            [
                "--dry-run",
                "--uninstall",
                "--plist-path",
                str(tmp_path / "com.hydraflow.liveness.plist"),
            ]
        )
        assert rc == 0
