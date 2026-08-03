#!/usr/bin/env python3
"""Mutation Gauntlet — I/O shell (#10835).

Thin wrapper around the pure core (``src/mutation_gauntlet.py``): for each
selected mutant it materializes a scratch git worktree at HEAD, applies the
``(file, find, replace)`` patch, runs ONLY the mutant's ``target_gate`` via its
real entrypoint, captures the exit code, classifies it, and discards the
worktree. It emits ``<data_root>/mutation/gate_kill_rate.jsonl`` (append-only,
one row per campaign) and a human summary to stdout.

Run on demand — this is a diagnostic instrument, NOT a background loop, and it
is deliberately NOT wired into CI (one real gate per mutant is too slow for the
merge path). The load-bearing verdict/kill-rate logic lives in the pure core;
everything here is worktree + subprocess plumbing.

    python scripts/mutation_gauntlet.py --list
    python scripts/mutation_gauntlet.py --class logic --class safety
    python scripts/mutation_gauntlet.py --data-root ~/.hydraflow/data

Guard: a mutant whose patch does not apply, or whose gate could not be spawned,
is ``ERRORED`` — NEVER silently counted as ``KILLED``.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from tests.mutation.catalog import load_catalog  # noqa: E402

from mutation_gauntlet import (  # noqa: E402
    KillRateReport,
    Mutant,
    MutantClass,
    MutantResult,
    MutantSelector,
    Verdict,
    campaign_row,
    classify_result,
    plan_campaign,
    render_summary,
    summarize,
)


@dataclass(frozen=True)
class GateOutcome:
    """The result of trying to run one gate against a mutated worktree.

    ``ran`` is False only when the gate could not be spawned at all (e.g. the
    entrypoint is missing) — that path is ``ERRORED``, never a verdict.
    """

    exit_code: int
    ran: bool
    detail: str = ""


#: A gate runner: given a gate label and the mutated worktree, run the gate.
GateRunner = Callable[[str, Path], GateOutcome]

#: A worktree context manager: yields a scratch checkout of *repo_root* at HEAD.
WorktreeCtx = Callable[[Path], AbstractContextManager[Path]]

# Real entrypoint for each gate label (see catalog gate-label docstring). The
# shell runs ONLY the mutant's owning gate — that is what localizes a survivor.
GATE_COMMANDS: dict[str, list[str]] = {
    "unit-tests": ["make", "test"],
    "scenario": ["make", "scenario"],
    "lint-ul": ["make", "lint-ul"],
    "fake-coverage": [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/test_contracts_shapes.py",
        "tests/test_fake_conformance_runner.py",
    ],
    "adr-conformance": [
        "python",
        "-m",
        "pytest",
        "-q",
        "tests/test_adr_direction_declared.py",
        "tests/test_adr_conformance_coverage.py",
    ],
}


def apply_patch(worktree: Path, *, file: str, find: str, replace: str) -> bool:
    """Apply one first-occurrence ``(file, find, replace)`` patch in *worktree*.

    Returns True when the patch applied, False when the target file is missing
    or the ``find`` anchor is absent (a stale mutation point) — the caller maps
    False to ``ERRORED``, never a verdict.
    """
    target = worktree / file
    if not target.is_file():
        return False
    text = target.read_text(encoding="utf-8")
    if find not in text:
        return False
    target.write_text(text.replace(find, replace, 1), encoding="utf-8")
    return True


@contextmanager
def git_worktree(repo_root: Path) -> Iterator[Path]:
    """Create a detached scratch worktree of *repo_root* at HEAD; discard it.

    The worktree is always removed (even on failure) so a campaign leaves no
    stray checkouts behind.
    """
    scratch = Path(tempfile.mkdtemp(prefix="mutgaunt-"))
    worktree = scratch / "wt"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "--detach",
            str(worktree),
            "HEAD",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        yield worktree
    finally:
        subprocess.run(
            [
                "git",
                "-C",
                str(repo_root),
                "worktree",
                "remove",
                "--force",
                str(worktree),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        shutil.rmtree(scratch, ignore_errors=True)


def subprocess_gate_runner(gate: str, worktree: Path) -> GateOutcome:
    """Run the real entrypoint for *gate* inside *worktree*.

    An unknown gate or an un-spawnable command is ``ran=False`` (-> ERRORED).
    """
    command = GATE_COMMANDS.get(gate)
    if command is None:
        return GateOutcome(exit_code=-1, ran=False, detail=f"unknown gate {gate!r}")
    try:
        proc = subprocess.run(
            command,
            cwd=worktree,
            capture_output=True,
            text=True,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return GateOutcome(exit_code=-1, ran=False, detail=f"gate spawn failed: {exc}")
    tail = (proc.stdout or "")[-500:] + (proc.stderr or "")[-500:]
    return GateOutcome(exit_code=proc.returncode, ran=True, detail=tail.strip())


def run_mutant(
    mutant: Mutant,
    *,
    repo_root: Path,
    gate_runner: GateRunner,
    worktree_ctx: WorktreeCtx = git_worktree,
) -> MutantResult:
    """Run one *mutant*: worktree -> apply -> gate -> classify -> discard.

    Fail-closed: a patch that will not apply or a gate that never ran is
    ``ERRORED``. Only a gate that actually ran yields ``KILLED`` / ``SURVIVED``.
    """
    with worktree_ctx(repo_root) as worktree:
        applied = apply_patch(
            worktree,
            file=mutant.patch.file,
            find=mutant.patch.find,
            replace=mutant.patch.replace,
        )
        if not applied:
            return MutantResult(
                mutant=mutant,
                verdict=Verdict.ERRORED,
                gate_exit=None,
                detail=f"patch did not apply to {mutant.patch.file}",
            )
        outcome = gate_runner(mutant.target_gate, worktree)
        if not outcome.ran:
            return MutantResult(
                mutant=mutant,
                verdict=Verdict.ERRORED,
                gate_exit=outcome.exit_code,
                detail=outcome.detail or "gate could not run",
            )
        return MutantResult(
            mutant=mutant,
            verdict=classify_result(outcome.exit_code, outcome.ran),
            gate_exit=outcome.exit_code,
            detail=outcome.detail,
        )


def run_campaign(
    mutants: Sequence[Mutant],
    *,
    repo_root: Path,
    gate_runner: GateRunner,
    worktree_ctx: WorktreeCtx = git_worktree,
) -> list[MutantResult]:
    """Run every mutant in *mutants* and collect the per-mutant results."""
    return [
        run_mutant(
            mutant,
            repo_root=repo_root,
            gate_runner=gate_runner,
            worktree_ctx=worktree_ctx,
        )
        for mutant in mutants
    ]


def _head_sha(repo_root: Path) -> str:
    """Return the short HEAD SHA of *repo_root* (``unknown`` if git is absent)."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return proc.stdout.strip() or "unknown"


def emit_row(
    report: KillRateReport,
    data_root: Path,
    *,
    campaign_id: str,
    head_sha: str,
    ts: str,
) -> Path:
    """Append one campaign row to ``<data_root>/mutation/gate_kill_rate.jsonl``."""
    out_dir = data_root / "mutation"
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "gate_kill_rate.jsonl"
    row = campaign_row(report, campaign_id=campaign_id, head_sha=head_sha, ts=ts)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, sort_keys=True) + "\n")
    return path


def _build_selector(args: argparse.Namespace) -> MutantSelector | None:
    """Translate CLI filters into a :class:`MutantSelector` (``None`` = all)."""
    ids = frozenset(args.id) if args.id else None
    classes = frozenset(MutantClass(c) for c in args.mclass) if args.mclass else None
    gates = frozenset(args.gate) if args.gate else None
    if ids is None and classes is None and gates is None:
        return None
    return MutantSelector(ids=ids, classes=classes, gates=gates)


def _default_data_root() -> Path:
    """Resolve the data root from config, falling back to a repo-local dir."""
    try:
        from config import HydraFlowConfig

        return HydraFlowConfig().data_root
    except Exception:  # the instrument must run without full config present
        return REPO / "data"


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint: plan, optionally run, report, and emit the jsonl row."""
    parser = argparse.ArgumentParser(description="Mutation gauntlet (#10835)")
    parser.add_argument("--class", dest="mclass", action="append", default=[])
    parser.add_argument("--gate", dest="gate", action="append", default=[])
    parser.add_argument("--id", dest="id", action="append", default=[])
    parser.add_argument("--data-root", dest="data_root", default=None)
    parser.add_argument(
        "--list",
        action="store_true",
        help="list the planned mutants and exit without running any gate",
    )
    args = parser.parse_args(argv)

    catalog = load_catalog()
    selected = plan_campaign(catalog, _build_selector(args))

    if args.list:
        for mutant in selected:
            print(
                f"{mutant.id}  [{mutant.mutant_class.value}]  "
                f"gate={mutant.target_gate}  file={mutant.patch.file}"
            )
        return 0

    results = run_campaign(selected, repo_root=REPO, gate_runner=subprocess_gate_runner)
    report = summarize(results)
    print(render_summary(report))

    data_root = Path(args.data_root) if args.data_root else _default_data_root()
    path = emit_row(
        report,
        data_root,
        campaign_id=uuid.uuid4().hex[:12],
        head_sha=_head_sha(REPO),
        ts=datetime.now(UTC).isoformat(),
    )
    print(f"\nappended campaign row -> {path}")
    # A survivor is a finding, not a runner failure: exit nonzero so an
    # on-demand invocation surfaces a blind gate to the caller.
    return 1 if report.has_survivors else 0


if __name__ == "__main__":
    raise SystemExit(main())
