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
        # One exact-equality pin: service-mode flag, workspace, ADR-0042
        # branch, HOME, and a PATH that prepends Homebrew, appends the
        # user-local bin, and keeps every entry of launchd's own default
        # (/usr/bin:/bin:/usr/sbin:/sbin) — launchd agents inherit neither a
        # login profile nor Homebrew's bin, and the pin must never regress
        # what the default PATH could find.
        assert env == {
            "HYDRAFLOW_FACTORY_SERVICE": "1",
            "HYDRAFLOW_FACTORY_WORKSPACE": str(tmp_path / "ws"),
            "HYDRAFLOW_FACTORY_BRANCH": "staging",
            "HOME": str(tmp_path / "home"),
            "PATH": (
                "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:"
                + str(tmp_path / "home" / ".local" / "bin")
            ),
        }

    def test_keepalive_runatload_throttle_and_log_paths(self, tmp_path: Path) -> None:
        d = _plist_dict(_render(tmp_path))
        lifecycle = {k: d[k] for k in ("KeepAlive", "RunAtLoad", "ThrottleInterval")}
        assert lifecycle == {
            "KeepAlive": True,
            "RunAtLoad": True,
            "ThrottleInterval": "60",
        }
        assert (d["StandardOutPath"], d["StandardErrorPath"]) == (
            str(tmp_path / "out.log"),
            str(tmp_path / "err.log"),
        )

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
        # No subprocess of any kind, and nothing written or cloned.
        assert (calls.argv, plist_path.exists(), knob.exists(), ws.exists()) == (
            [],
            False,
            False,
            False,
        )

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
        assert "com.hydraflow.factory" in plist_path.read_text()
        # No clone (workspace existed); bootout (idempotent unload) THEN
        # bootstrap, each addressed at this plist.
        assert [(c[0], c[1], str(plist_path) in c) for c in calls.argv] == [
            ("launchctl", "bootout", True),
            ("launchctl", "bootstrap", True),
        ]

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
        # Clone first (into a created parent), then bootout -> bootstrap.
        assert calls.argv[0] == [
            "git",
            "clone",
            "git@example.com:org/repo.git",
            str(ws),
        ]
        assert (ws.parent.is_dir(), [c[1] for c in calls.argv[1:]]) == (
            True,
            ["bootout", "bootstrap"],
        )

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
        keys = (
            "workspace",
            "factory_branch",
            "knob_path",
            "log_dir",
            "origin_url",
            "dry_run",
        )
        assert {k: captured[k] for k in keys} == {
            "workspace": tmp_path / "ws",
            "factory_branch": "staging",
            "knob_path": tmp_path / "knob",
            "log_dir": tmp_path / "logs",
            "origin_url": "git@x:y/z.git",
            "dry_run": True,
        }

    def test_main_dry_run_uninstall_calls_no_launchctl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = _Calls()
        monkeypatch.setattr(subprocess, "run", calls)
        plist_path = tmp_path / "com.hydraflow.factory.plist"
        plist_path.write_text("<plist/>", encoding="utf-8")
        rc = installer.main(
            ["--dry-run", "--uninstall", "--plist-path", str(plist_path)]
        )
        assert rc == 0
        assert calls.argv == []
        assert plist_path.exists()

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
        assert (
            installer._LABEL,
            log_dir.name,
            installer._DEFAULT_WORKSPACE,
            installer._DEFAULT_FACTORY_BRANCH,
            installer._DEFAULT_KNOB_PATH,
            installer._DEFAULT_PLIST_PATH,
        ) == (
            "com.hydraflow.factory",
            ".hydraflow",
            log_dir / "factory-workspace" / "hydraflow",
            "staging",
            log_dir / "liveness" / "restart.knob",
            log_dir.parent / "Library" / "LaunchAgents" / "com.hydraflow.factory.plist",
        )
        # The earlier (failed) launchd attempt already logs to these names on
        # the host — reuse them rather than orphaning the old files.
        assert (installer._STDOUT_NAME, installer._STDERR_NAME) == (
            "factory-launchd.out.log",
            "factory-launchd.err.log",
        )


def test_makefile_wires_the_service_targets() -> None:
    makefile = (Path(__file__).parent.parent / "Makefile").read_text()
    needles = (
        "\nfactory-service-install:",
        "\nfactory-service-uninstall:",
        "install_factory_service.py",
        "factory-service-install factory-service-uninstall",  # .PHONY
    )
    missing = [n for n in needles if n not in makefile]
    assert not missing, f"Makefile is missing service-target wiring: {missing}"
