"""Integration: the shell detects KILLED and SURVIVED mutants (#10835).

Drives the REAL worktree + patch + classify pipeline of
``scripts/mutation_gauntlet.py`` with a FIXTURE gate and a FIXTURE mutant. The
SURVIVED case is the whole point: it proves the instrument can actually detect
a blind gate (a gate that stays green despite the injected fault) — the #10860
failure mode, one level up. No real ``make`` gates run here.

The shell module is loaded under a distinct name via ``importlib`` because it
shares the base name ``mutation_gauntlet`` with the pure core on ``PYTHONPATH``.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from mutation_gauntlet import Mutant, MutantClass, PatchSpec, Verdict, summarize

REPO = Path(__file__).resolve().parents[2]
_SHELL_PATH = REPO / "scripts" / "mutation_gauntlet.py"


def _load_shell():
    spec = importlib.util.spec_from_file_location(
        "mutation_gauntlet_shell", _SHELL_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclasses can resolve the module via __module__.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


shell = _load_shell()


_FIXTURE_MUTANT = Mutant(
    id="fixture-threshold-flip",
    mutant_class=MutantClass.LOGIC,
    target_gate="fixture-gate",
    patch=PatchSpec(file="guarded.py", find="THRESHOLD = 10", replace="THRESHOLD = 0"),
    rationale="fixture: flip a guard threshold to prove the pipeline end to end",
)


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    """A throwaway git repo with one committed file to mutate."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "tester"], check=True
    )
    (repo / "guarded.py").write_text("THRESHOLD = 10\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "seed"], check=True)
    return repo


def test_shell_reports_killed_when_gate_is_sensitive(scratch_repo: Path) -> None:
    def sensitive_gate(gate: str, worktree: Path):
        # A faithful gate: goes red when it sees the mutation.
        text = (worktree / "guarded.py").read_text(encoding="utf-8")
        return shell.GateOutcome(
            exit_code=1 if "THRESHOLD = 0" in text else 0, ran=True
        )

    result = shell.run_mutant(
        _FIXTURE_MUTANT, repo_root=scratch_repo, gate_runner=sensitive_gate
    )

    assert result.verdict is Verdict.KILLED
    assert result.gate_exit == 1


def test_shell_reports_survived_when_gate_is_blind(scratch_repo: Path) -> None:
    def blind_gate(gate: str, worktree: Path):
        # A deliberately insensitive gate: stays green despite the mutation.
        return shell.GateOutcome(exit_code=0, ran=True)

    result = shell.run_mutant(
        _FIXTURE_MUTANT, repo_root=scratch_repo, gate_runner=blind_gate
    )

    # The instrument detected a blind gate — the reason it exists.
    assert result.verdict is Verdict.SURVIVED


def test_shell_errors_when_patch_does_not_apply(scratch_repo: Path) -> None:
    stale = Mutant(
        id="stale-anchor",
        mutant_class=MutantClass.LOGIC,
        target_gate="fixture-gate",
        patch=PatchSpec(file="guarded.py", find="NOT_PRESENT", replace="x"),
        rationale="fixture: absent anchor -> ERRORED, never KILLED",
    )

    def never_run(gate: str, worktree: Path):
        raise AssertionError("gate must not run when the patch did not apply")

    result = shell.run_mutant(stale, repo_root=scratch_repo, gate_runner=never_run)

    assert result.verdict is Verdict.ERRORED
    assert result.gate_exit is None


def test_shell_errors_when_gate_cannot_run(scratch_repo: Path) -> None:
    def unspawnable_gate(gate: str, worktree: Path):
        return shell.GateOutcome(exit_code=-1, ran=False, detail="boom")

    result = shell.run_mutant(
        _FIXTURE_MUTANT, repo_root=scratch_repo, gate_runner=unspawnable_gate
    )

    # A gate that could not run is never counted as a kill.
    assert result.verdict is Verdict.ERRORED


def test_scratch_worktree_is_discarded_after_run(scratch_repo: Path) -> None:
    seen: dict[str, bool] = {}

    def blind_gate(gate: str, worktree: Path):
        seen["existed_during_run"] = worktree.exists()
        return shell.GateOutcome(exit_code=0, ran=True)

    shell.run_mutant(_FIXTURE_MUTANT, repo_root=scratch_repo, gate_runner=blind_gate)

    listing = subprocess.run(
        ["git", "-C", str(scratch_repo), "worktree", "list"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert seen["existed_during_run"] is True
    assert "mutgaunt-" not in listing


def test_emit_row_appends_one_jsonl_line(tmp_path: Path) -> None:
    report = summarize([])

    path = shell.emit_row(report, tmp_path, campaign_id="c", head_sha="sha", ts="t")

    assert path.name == "gate_kill_rate.jsonl"
    assert path.read_text(encoding="utf-8").strip()
