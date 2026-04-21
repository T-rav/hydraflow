"""Tests for install_plugins_cli.run()."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from config import HydraFlowConfig
from install_plugins_cli import run


def test_installs_all_missing_tier1_plugins(tmp_path: Path):
    cfg = HydraFlowConfig(
        required_plugins=["superpowers", "code-review"],
        language_plugins={},
    )
    called_argvs: list[list[str]] = []

    def fake_run(argv, **kwargs):
        called_argvs.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with patch("preflight.subprocess.run", side_effect=fake_run):
        exit_code = run(cfg, cache_root=tmp_path)

    assert exit_code == 0
    assert called_argvs == [
        [
            "claude",
            "plugin",
            "install",
            "superpowers@claude-plugins-official",
            "--scope",
            "user",
        ],
        [
            "claude",
            "plugin",
            "install",
            "code-review@claude-plugins-official",
            "--scope",
            "user",
        ],
    ]


def test_skips_already_installed_plugins(tmp_path: Path):
    cfg = HydraFlowConfig(required_plugins=["superpowers"], language_plugins={})
    # Pre-populate cache so the plugin is "already installed"
    (tmp_path / "claude-plugins-official" / "superpowers" / "1.0.0" / "skills").mkdir(
        parents=True
    )

    with patch("preflight.subprocess.run") as mock_run:
        exit_code = run(cfg, cache_root=tmp_path)

    assert exit_code == 0
    assert mock_run.call_count == 0


def test_nonzero_exit_on_tier1_install_failure(tmp_path: Path):
    cfg = HydraFlowConfig(required_plugins=["superpowers"], language_plugins={})

    def fake_run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")

    with patch("preflight.subprocess.run", side_effect=fake_run):
        exit_code = run(cfg, cache_root=tmp_path)

    assert exit_code != 0


def test_zero_exit_when_only_tier2_install_fails(tmp_path: Path):
    """Tier-2 (language-conditional) failures are warnings, not errors."""
    cfg = HydraFlowConfig(
        required_plugins=[],
        language_plugins={"python": ["bogus-lsp"]},
    )

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="marketplace unknown"
        )

    with patch("preflight.subprocess.run", side_effect=fake_run):
        exit_code = run(cfg, cache_root=tmp_path)

    assert exit_code == 0


def test_nonzero_when_tier1_fails_even_if_tier2_succeeds(tmp_path: Path):
    """Tier-1 failure is still fatal regardless of Tier-2 outcome."""
    cfg = HydraFlowConfig(
        required_plugins=["superpowers"],
        language_plugins={"python": ["pyright-lsp"]},
    )

    def fake_run(argv, **_kwargs):
        # Fail tier-1 superpowers; succeed tier-2 pyright-lsp by populating cache
        if "superpowers" in argv[3]:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="boom")
        # pyright-lsp succeeds
        (
            tmp_path / "claude-plugins-official" / "pyright-lsp" / "1.0.0" / "skills"
        ).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with patch("preflight.subprocess.run", side_effect=fake_run):
        exit_code = run(cfg, cache_root=tmp_path)

    assert exit_code == 1


def test_tier2_entries_always_attempted_when_missing(tmp_path: Path):
    """Tier-2 entries are attempted even if Tier-1 is empty."""
    cfg = HydraFlowConfig(
        required_plugins=[],
        language_plugins={"python": ["pyright-lsp"]},
    )
    called_argvs: list[list[str]] = []

    def fake_run(argv, **_kwargs):
        called_argvs.append(argv)
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    with patch("preflight.subprocess.run", side_effect=fake_run):
        exit_code = run(cfg, cache_root=tmp_path)

    assert exit_code == 0
    assert called_argvs == [
        [
            "claude",
            "plugin",
            "install",
            "pyright-lsp@claude-plugins-official",
            "--scope",
            "user",
        ],
    ]
