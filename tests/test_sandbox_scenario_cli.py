"""sandbox_scenario CLI — invocation surface tests.

Doesn't actually boot docker — patches subprocess.run. Verifies the
correct compose commands are issued for each subcommand.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from scripts import sandbox_scenario


def test_seed_subcommand_writes_json(tmp_path) -> None:
    seeds_dir = tmp_path / "seeds"
    with (
        patch.object(sandbox_scenario, "SEEDS_DIR", seeds_dir),
        patch.object(sandbox_scenario, "load_scenario") as load,
    ):
        load.return_value.NAME = "s00_smoke"
        load.return_value.seed.return_value.to_json.return_value = '{"x": 1}'
        sandbox_scenario.cmd_seed("s00_smoke")
    assert (seeds_dir / "s00_smoke.json").read_text() == '{"x": 1}'


def test_down_subcommand_calls_compose_down() -> None:
    with patch("subprocess.run") as run:
        sandbox_scenario.cmd_down()
    args = run.call_args[0][0]
    assert "docker" in args[0] and "compose" in args
    assert "down" in args


def test_run_subcommand_cleans_up_untracked_seed_in_committed_dir(
    monkeypatch, tmp_path
) -> None:
    """``cmd_run`` writes into the committed ``SEEDS_DIR`` (so the docker mount
    is unchanged) but removes the untracked seed + ``scenario.json`` symlink it
    materialized once the run finishes (#10980).

    Fakes docker via ``subprocess.run`` but lets real ``git`` run so the
    committed-golden detection (``git ls-files --error-unmatch``) sees the
    scenario's seed as untracked and cleans it up. Proves: (1) the run returns
    the scenario rc; (2) no ``<name>.json`` / ``scenario.json`` is left in the
    committed dir afterward.
    """
    real_run = subprocess.run  # captured before patching — for real git calls
    real_seeds = sandbox_scenario.SEEDS_DIR
    stem = "s99_fake_cleanup"
    seed_file = real_seeds / f"{stem}.json"
    scenario_link = real_seeds / "scenario.json"

    def fake_run(cmd, **kwargs):
        # Golden-detection must see real git so the untracked stray is deletable.
        if cmd and cmd[0] == "git":
            return real_run(cmd, **kwargs)
        # stdout keeps ``_wait_for_healthy`` from polling/sleeping.
        return subprocess.CompletedProcess(
            cmd, 0, stdout='[{"Health":"healthy"}]', stderr=""
        )

    monkeypatch.setattr(sandbox_scenario.subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox_scenario, "RESULTS_DIR", tmp_path / "results")
    fake_mod = SimpleNamespace(
        NAME=stem,
        seed=lambda: SimpleNamespace(to_json=lambda: '{"x": 1}'),
    )
    monkeypatch.setattr(sandbox_scenario, "load_scenario", lambda name: fake_mod)

    assert not seed_file.exists()
    try:
        rc = sandbox_scenario.cmd_run(stem)
        assert rc == 0
        assert not seed_file.exists(), (
            "cmd_run left an untracked seed in the committed SEEDS_DIR (#10980)"
        )
        assert not scenario_link.exists() and not scenario_link.is_symlink()
    finally:
        # Defensive: never let a failed run leave the committed dir dirty.
        seed_file.unlink(missing_ok=True)
        scenario_link.unlink(missing_ok=True)
