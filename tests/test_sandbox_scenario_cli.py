"""sandbox_scenario CLI — invocation surface tests.

Doesn't actually boot docker — patches subprocess.run. Verifies the
correct compose commands are issued for each subcommand.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
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


def test_run_subcommand_mounts_temp_seed_dir_not_committed(
    monkeypatch, tmp_path
) -> None:
    """``cmd_run`` threads a throwaway ``SANDBOX_SEED_DIR`` to compose and never
    writes into the committed golden ``SEEDS_DIR`` (#10980).

    Fully patches ``subprocess.run`` (so no docker boots) and captures the env
    the harness hands compose. Proves: (1) the seed dir passed to compose is a
    temp dir, not the committed one; (2) no seed / ``scenario.json`` lands in the
    committed dir for this scenario; (3) the temp dir is cleaned up afterward.
    """
    real_seeds = sandbox_scenario.SEEDS_DIR
    captured: dict[str, str] = {}

    def fake_run(cmd, **kwargs):
        env = kwargs.get("env")
        if env and "SANDBOX_SEED_DIR" in env:
            captured["seed_dir"] = env["SANDBOX_SEED_DIR"]
        # stdout keeps ``_wait_for_healthy`` from polling/sleeping.
        return subprocess.CompletedProcess(
            cmd, 0, stdout='[{"Health":"healthy"}]', stderr=""
        )

    monkeypatch.setattr(sandbox_scenario.subprocess, "run", fake_run)
    monkeypatch.setattr(sandbox_scenario, "RESULTS_DIR", tmp_path / "results")
    fake_mod = SimpleNamespace(
        NAME="s99_fake",
        seed=lambda: SimpleNamespace(to_json=lambda: '{"x": 1}'),
    )
    monkeypatch.setattr(sandbox_scenario, "load_scenario", lambda name: fake_mod)

    rc = sandbox_scenario.cmd_run("s99_fake")

    assert rc == 0
    assert "seed_dir" in captured, "cmd_run never passed SANDBOX_SEED_DIR to compose"
    assert captured["seed_dir"] != str(real_seeds)
    assert not (real_seeds / "s99_fake.json").exists()
    assert not (real_seeds / "scenario.json").exists()
    # The single-use temp seed dir is removed once the run finishes.
    assert not Path(captured["seed_dir"]).exists()
