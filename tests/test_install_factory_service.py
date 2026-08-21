"""Unit tests for the factory launchd-service installer (ADR-0135).

Loads scripts/install_factory_service.py via importlib (same pattern as
tests/test_install_liveness_watchdog.py). No test ever calls real
``launchctl`` or ``git clone``: every path that would shell out monkeypatches
``subprocess.run`` first, and the dry-run tests assert it is never called.
Nothing here writes under the real ``~/Library`` or ``~/.hydraflow``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).parent.parent / "scripts" / "install_factory_service.py"
_spec = importlib.util.spec_from_file_location("install_factory_service", _SCRIPT)
assert _spec and _spec.loader
installer = importlib.util.module_from_spec(_spec)
sys.modules["install_factory_service"] = installer
_spec.loader.exec_module(installer)


def _render(tmp_path: Path, **overrides):
    kwargs = {
        "label": "com.hydraflow.factory",
        "workspace": tmp_path / "ws",
        "factory_branch": "staging",
        "home": tmp_path / "home",
        "stdout_path": tmp_path / "out.log",
        "stderr_path": tmp_path / "err.log",
    }
    kwargs.update(overrides)
    return installer.render_plist(**kwargs)


def _parse(xml_text: str) -> ET.Element:
    # DOCTYPE references an external DTD — strip it so ElementTree (no network
    # here) doesn't try to resolve it.
    return ET.fromstring("<plist" + xml_text.split("<plist", 1)[1])  # noqa: S314


def _plist_dict(xml_text: str) -> dict[str, object]:
    """Flatten the top-level <dict> into {key: value} for assertions."""
    root = _parse(xml_text)
    top = root.find("dict")
    assert top is not None
    out: dict[str, object] = {}
    children = list(top)
    for i in range(0, len(children), 2):
        key = children[i].text or ""
        val = children[i + 1]
        if val.tag == "array":
            out[key] = [s.text for s in val]
        elif val.tag == "dict":
            kids = list(val)
            out[key] = {
                (kids[j].text or ""): kids[j + 1].text for j in range(0, len(kids), 2)
            }
        elif val.tag in {"true", "false"}:
            out[key] = val.tag == "true"
        else:
            out[key] = val.text
    return out


class TestRenderPlist:
    def test_label_program_args_and_working_directory(self, tmp_path: Path) -> None:
        d = _plist_dict(_render(tmp_path))
        ws = tmp_path / "ws"
        assert d["Label"] == "com.hydraflow.factory"
        # bash + the launcher INSIDE the workspace: the job runs in place.
        assert d["ProgramArguments"] == [
            "/bin/bash",
            str(ws / "scripts" / "run-factory-isolated.sh"),
        ]
        assert d["WorkingDirectory"] == str(ws)

    def test_environment_pins_service_mode_workspace_branch_home_and_path(
        self, tmp_path: Path
    ) -> None:
        env = _plist_dict(_render(tmp_path))["EnvironmentVariables"]
        assert isinstance(env, dict)
        assert env["HYDRAFLOW_FACTORY_SERVICE"] == "1"
        assert env["HYDRAFLOW_FACTORY_WORKSPACE"] == str(tmp_path / "ws")
        assert env["HYDRAFLOW_FACTORY_BRANCH"] == "staging"
        assert env["HOME"] == str(tmp_path / "home")
        # launchd's default PATH lacks uv/node/gh/docker — the pin must carry
        # Homebrew + the user-local bin, and only absolute entries.
        path = env["PATH"]
        assert isinstance(path, str)
        parts = path.split(":")
        assert parts[0] == "/opt/homebrew/bin"
        assert "/usr/local/bin" in parts
        assert "/usr/bin" in parts
        assert "/bin" in parts
        # launchd's own default PATH is /usr/bin:/bin:/usr/sbin:/sbin — the
        # pin must be a superset of it, never a regression.
        assert "/usr/sbin" in parts
        assert "/sbin" in parts
        assert parts[-1] == str(tmp_path / "home" / ".local" / "bin")
        assert all(p.startswith("/") for p in parts)

    def test_keepalive_runatload_throttle_and_log_paths(self, tmp_path: Path) -> None:
        d = _plist_dict(_render(tmp_path))
        assert d["KeepAlive"] is True
        assert d["RunAtLoad"] is True
        assert d["ThrottleInterval"] == "60"
        assert d["StandardOutPath"] == str(tmp_path / "out.log")
        assert d["StandardErrorPath"] == str(tmp_path / "err.log")

    def test_escapes_special_xml_characters(self, tmp_path: Path) -> None:
        xml_text = _render(tmp_path, workspace=tmp_path / "a&b<c>")
        assert "a&amp;b&lt;c&gt;" in xml_text
        assert "a&b<c>" not in xml_text
        _parse(xml_text)  # still well-formed

    def test_honours_branch_override(self, tmp_path: Path) -> None:
        env = _plist_dict(_render(tmp_path, factory_branch="main"))[
            "EnvironmentVariables"
        ]
        assert isinstance(env, dict)
        assert env["HYDRAFLOW_FACTORY_BRANCH"] == "main"


class TestEnsureRestartLabel:
    """The liveness knob gets a RESTART_LABEL so attempt_restart() has a target
    — but only when the operator has configured neither a command nor a
    label; existing keys are never overwritten (seed_restart_knob's contract)."""

    def test_creates_knob_with_enabled_and_label_when_absent(
        self, tmp_path: Path
    ) -> None:
        knob = tmp_path / "liveness" / "restart.knob"
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        text = knob.read_text()
        assert "RESTART_ENABLED=true" in text
        assert "RESTART_LABEL=com.hydraflow.factory" in text

    def test_appends_label_to_a_watchdog_seeded_knob(self, tmp_path: Path) -> None:
        # Exactly what install_liveness_watchdog.py seeds: enabled, no target —
        # the state that made attempt_restart() log "skipping restart".
        knob = tmp_path / "restart.knob"
        knob.write_text("# seeded\nRESTART_ENABLED=true\n", encoding="utf-8")
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        text = knob.read_text()
        assert text.startswith("# seeded\nRESTART_ENABLED=true\n")
        assert "RESTART_LABEL=com.hydraflow.factory" in text

    def test_never_overwrites_an_existing_label(self, tmp_path: Path) -> None:
        knob = tmp_path / "restart.knob"
        original = "RESTART_ENABLED=true\nRESTART_LABEL=com.example.custom\n"
        knob.write_text(original, encoding="utf-8")
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        assert knob.read_text() == original

    def test_never_touches_a_knob_with_a_restart_command(self, tmp_path: Path) -> None:
        knob = tmp_path / "restart.knob"
        original = "RESTART_ENABLED=false\nRESTART_COMMAND=my-custom --flag\n"
        knob.write_text(original, encoding="utf-8")
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        assert knob.read_text() == original

    def test_is_idempotent(self, tmp_path: Path) -> None:
        knob = tmp_path / "restart.knob"
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        first = knob.read_text()
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        assert knob.read_text() == first
        assert first.count("RESTART_LABEL=") == 1

    def test_dry_run_writes_nothing(self, tmp_path: Path) -> None:
        knob = tmp_path / "restart.knob"
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=True
        )
        assert not knob.exists()

    def test_parses_the_knob_the_way_the_watchdog_does(self, tmp_path: Path) -> None:
        # Comments, blank lines, and whitespace around '=' must not fool the
        # "already configured" detection (mirrors parse_knob_file).
        knob = tmp_path / "restart.knob"
        knob.write_text(
            "# c\n\n  RESTART_ENABLED = true \n# RESTART_LABEL=commented-out\n",
            encoding="utf-8",
        )
        installer.ensure_restart_label(
            knob, label="com.hydraflow.factory", dry_run=False
        )
        assert "RESTART_LABEL=com.hydraflow.factory" in knob.read_text()


class _Calls:
    def __init__(self) -> None:
        self.argv: list[list[str]] = []

    def __call__(self, argv: list[str], **k: object) -> object:
        self.argv.append(list(argv))

        class _R:
            returncode = 0
            stdout = ""
            stderr = ""

        return _R()


class TestInstallDryRun:
    def test_dry_run_never_calls_subprocess_or_writes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        plist_path = tmp_path / "LaunchAgents" / "com.hydraflow.factory.plist"
        knob = tmp_path / "restart.knob"
        ws = tmp_path / "ws"  # absent on purpose: dry-run must not clone either
        installer.install(
            plist_path=plist_path,
            workspace=ws,
            factory_branch="staging",
            home=tmp_path / "home",
            log_dir=tmp_path / "logs",
            knob_path=knob,
            origin_url="git@example.com:org/repo.git",
            dry_run=True,
        )
        assert calls.argv == []
        assert not plist_path.exists()
        assert not knob.exists()
        assert not ws.exists()

    def test_uninstall_dry_run_never_calls_subprocess(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        plist_path = tmp_path / "com.hydraflow.factory.plist"
        plist_path.write_text("<plist/>", encoding="utf-8")
        installer.uninstall(plist_path=plist_path, dry_run=True)
        assert calls.argv == []
        assert plist_path.exists()


class TestInstallRealPathWithFakeSubprocess:
    def _existing_workspace(self, tmp_path: Path) -> Path:
        ws = tmp_path / "home" / ".hydraflow" / "factory-workspace" / "hydraflow"
        (ws / ".git").mkdir(parents=True)
        return ws

    def test_install_writes_plist_bootouts_then_bootstraps(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        ws = self._existing_workspace(tmp_path)
        plist_path = tmp_path / "LaunchAgents" / "com.hydraflow.factory.plist"
        installer.install(
            plist_path=plist_path,
            workspace=ws,
            factory_branch="staging",
            home=tmp_path / "home",
            log_dir=tmp_path / "home" / ".hydraflow",
            knob_path=tmp_path / "home" / ".hydraflow" / "liveness" / "restart.knob",
            origin_url="git@example.com:org/repo.git",
            dry_run=False,
        )
        assert plist_path.exists()
        assert "com.hydraflow.factory" in plist_path.read_text()
        # No clone (workspace existed); bootout (idempotent unload) THEN bootstrap.
        assert [c[0] for c in calls.argv] == ["launchctl", "launchctl"]
        assert [c[1] for c in calls.argv] == ["bootout", "bootstrap"]
        assert all(str(plist_path) in c for c in calls.argv)

    def test_install_clones_missing_workspace_before_rendering(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        ws = tmp_path / "home" / ".hydraflow" / "factory-workspace" / "hydraflow"
        installer.install(
            plist_path=tmp_path / "com.hydraflow.factory.plist",
            workspace=ws,
            factory_branch="staging",
            home=tmp_path / "home",
            log_dir=tmp_path / "home" / ".hydraflow",
            knob_path=tmp_path / "knob",
            origin_url="git@example.com:org/repo.git",
            dry_run=False,
        )
        assert calls.argv[0][:2] == ["git", "clone"]
        assert calls.argv[0][-2:] == ["git@example.com:org/repo.git", str(ws)]
        assert ws.parent.is_dir()  # parent created so clone can land
        assert [c[1] for c in calls.argv[1:]] == ["bootout", "bootstrap"]

    def test_install_wires_restart_label_into_knob(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess, "run", _Calls())
        ws = self._existing_workspace(tmp_path)
        knob = tmp_path / "home" / ".hydraflow" / "liveness" / "restart.knob"
        knob.parent.mkdir(parents=True)
        knob.write_text("RESTART_ENABLED=true\n", encoding="utf-8")
        installer.install(
            plist_path=tmp_path / "com.hydraflow.factory.plist",
            workspace=ws,
            factory_branch="staging",
            home=tmp_path / "home",
            log_dir=tmp_path / "home" / ".hydraflow",
            knob_path=knob,
            origin_url="git@example.com:org/repo.git",
            dry_run=False,
        )
        assert "RESTART_LABEL=com.hydraflow.factory" in knob.read_text()

    def test_install_is_idempotent_across_two_runs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess, "run", _Calls())
        ws = self._existing_workspace(tmp_path)
        plist_path = tmp_path / "com.hydraflow.factory.plist"
        knob = tmp_path / "knob"
        kwargs = {
            "plist_path": plist_path,
            "workspace": ws,
            "factory_branch": "staging",
            "home": tmp_path / "home",
            "log_dir": tmp_path / "home" / ".hydraflow",
            "knob_path": knob,
            "origin_url": "git@example.com:org/repo.git",
            "dry_run": False,
        }
        installer.install(**kwargs)
        first_plist, first_knob = plist_path.read_text(), knob.read_text()
        installer.install(**kwargs)
        assert plist_path.read_text() == first_plist
        assert knob.read_text() == first_knob

    def test_uninstall_removes_plist_and_leaves_knob_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        plist_path = tmp_path / "com.hydraflow.factory.plist"
        plist_path.write_text("<plist/>", encoding="utf-8")
        knob = tmp_path / "knob"
        knob.write_text("RESTART_LABEL=com.hydraflow.factory\n", encoding="utf-8")
        installer.uninstall(plist_path=plist_path, dry_run=False)
        assert not plist_path.exists()
        assert knob.read_text() == "RESTART_LABEL=com.hydraflow.factory\n"
        assert [c[1] for c in calls.argv] == ["bootout"]

    def test_uninstall_missing_plist_is_safe(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(subprocess, "run", _Calls())
        installer.uninstall(plist_path=tmp_path / "nope.plist", dry_run=False)


class TestMainArgParsing:
    def test_main_dry_run_install_returns_zero_and_calls_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        rc = installer.main(
            [
                "--dry-run",
                "--plist-path",
                str(tmp_path / "com.hydraflow.factory.plist"),
                "--workspace",
                str(tmp_path / "ws"),
                "--log-dir",
                str(tmp_path / "logs"),
                "--knob-path",
                str(tmp_path / "knob"),
            ]
        )
        assert rc == 0
        # The only subprocess a dry-run may make is the read-only origin
        # lookup; never launchctl, never a clone.
        assert all(
            c[0] != "launchctl" and c[:2] != ["git", "clone"] for c in calls.argv
        )
        assert all(
            c[:4] == ["git", "-C", str(installer._REPO_ROOT), "remote"]
            for c in calls.argv
        )

    def test_main_passes_parsed_args_to_install(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}
        monkeypatch.setattr(installer, "install", lambda **kw: captured.update(kw))
        monkeypatch.setattr(installer, "_dev_origin_url", lambda: "git@x:y/z.git")
        rc = installer.main(
            [
                "--dry-run",
                "--workspace",
                str(tmp_path / "ws"),
                "--factory-branch",
                "staging",
                "--knob-path",
                str(tmp_path / "knob"),
                "--log-dir",
                str(tmp_path / "logs"),
            ]
        )
        assert rc == 0
        assert captured["workspace"] == tmp_path / "ws"
        assert captured["factory_branch"] == "staging"
        assert captured["knob_path"] == tmp_path / "knob"
        assert captured["log_dir"] == tmp_path / "logs"
        assert captured["origin_url"] == "git@x:y/z.git"
        assert captured["dry_run"] is True

    def test_main_dry_run_uninstall_returns_zero(self, tmp_path: Path) -> None:
        rc = installer.main(
            [
                "--dry-run",
                "--uninstall",
                "--plist-path",
                str(tmp_path / "com.hydraflow.factory.plist"),
            ]
        )
        assert rc == 0

    def test_non_darwin_without_dry_run_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(installer.platform, "system", lambda: "Linux")
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        rc = installer.main(["--plist-path", str(tmp_path / "x.plist")])
        assert rc == 1
        assert calls.argv == []

    def test_defaults_point_at_the_hydraflow_home_layout(self) -> None:
        # Defaults are computed at import against the real HOME; the test
        # conftest swaps HOME afterwards, so assert the LAYOUT, not Path.home().
        log_dir = installer._DEFAULT_LOG_DIR
        assert installer._LABEL == "com.hydraflow.factory"
        assert log_dir.name == ".hydraflow"
        assert (
            log_dir / "factory-workspace" / "hydraflow" == installer._DEFAULT_WORKSPACE
        )
        assert installer._DEFAULT_FACTORY_BRANCH == "staging"
        assert log_dir / "liveness" / "restart.knob" == installer._DEFAULT_KNOB_PATH
        assert installer._DEFAULT_PLIST_PATH.parts[-3:] == (
            "Library",
            "LaunchAgents",
            "com.hydraflow.factory.plist",
        )
        assert installer._DEFAULT_PLIST_PATH.parent.parent.parent == log_dir.parent
        # The earlier (failed) launchd attempt already logs to these names on
        # the host — reuse them rather than orphaning the old files.
        assert installer._STDOUT_NAME == "factory-launchd.out.log"
        assert installer._STDERR_NAME == "factory-launchd.err.log"


def test_makefile_wires_the_service_targets() -> None:
    makefile = (Path(__file__).parent.parent / "Makefile").read_text()
    assert "\nfactory-service-install:" in makefile
    assert "\nfactory-service-uninstall:" in makefile
    assert "install_factory_service.py" in makefile
    assert "factory-service-install factory-service-uninstall" in makefile  # .PHONY
