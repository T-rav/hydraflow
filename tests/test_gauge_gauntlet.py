"""Unit tests for the gauge gauntlet (#11060 slice 2) — the pure parts.

Execution (npm/uv) is exercised by the advisory CI lane and `make
gauge-gauntlet`, not here: these tests pin the registry, the fixtures, the
command plans, the fake-runner path, and the no-silent-caps reporting.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from gauge_gauntlet import (  # noqa: E402
    EXECUTABLE_GAUGES,
    KNOWN_GAUGES,
    GaugeResult,
    js_fixture_files,
    plan_commands,
    run_gauge,
    summarize,
)


def test_registry_covers_all_nine_scaffold_gauges() -> None:
    assert len(KNOWN_GAUGES) == 9
    assert {"python", "javascript"} == EXECUTABLE_GAUGES
    assert set(KNOWN_GAUGES) >= EXECUTABLE_GAUGES


def test_js_fixture_is_real_not_a_stub() -> None:
    files = js_fixture_files()
    # Flat-config eslint with the TS parser, strict tsconfig, a real test, and
    # the ACTUAL generated Makefile for the javascript gauge.
    assert "typescript-eslint" in files["eslint.config.mjs"]
    assert '"strict": true' in files["tsconfig.json"]
    assert "expect(add(2, 3)).toBe(5)" in files["tests/index.test.ts"]
    assert "npx eslint" in files["Makefile"]
    assert "npx tsc --noEmit" in files["Makefile"]
    assert "vitest" in files["Makefile"]


def test_command_plans_execute_the_real_rails() -> None:
    python_plan = plan_commands("python")
    assert ["uv", "run", "make", "lint-check"] in python_plan
    assert ["uv", "run", "make", "test"] in python_plan
    js_plan = plan_commands("javascript")
    assert ["make", "typecheck"] in js_plan
    assert js_plan[0][0] == "npm"  # install precedes execution
    assert plan_commands("rust") == []  # no fixture yet → no fake plan


def test_unexercised_and_unknown_gauges_are_reported_not_skipped(
    tmp_path: Path,
) -> None:
    assert run_gauge("rust", tmp_path).status == "UNEXERCISED"
    assert run_gauge("cobol", tmp_path).status == "UNKNOWN"


def test_run_gauge_fails_on_first_failing_command(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        code = 1 if command[-1] == "typecheck" else 0
        return subprocess.CompletedProcess(command, code, stdout="", stderr="boom")

    result = run_gauge("javascript", tmp_path, runner=fake_runner)
    assert result.status == "FAIL"
    assert "typecheck" in result.detail and "boom" in result.detail
    # Stopped at the failure — test never ran.
    assert ["make", "test"] not in calls


def test_run_gauge_passes_when_all_commands_pass(tmp_path: Path) -> None:
    def fake_runner(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    assert run_gauge("javascript", tmp_path, runner=fake_runner).status == "PASS"
    # The fixture really landed on disk before execution.
    assert (tmp_path / "child-javascript" / "eslint.config.mjs").is_file()


def test_summarize_exit_code_and_no_silent_caps_note() -> None:
    output, code = summarize(
        [
            GaugeResult("python", "PASS"),
            GaugeResult("rust", "UNEXERCISED", "not requested"),
        ]
    )
    assert code == 0
    assert "PASS" in output and "UNEXERCISED" in output
    assert "unproven strings" in output  # the honesty note

    output, code = summarize([GaugeResult("javascript", "FAIL", "exit 1: boom")])
    assert code == 1
    assert "boom" in output
