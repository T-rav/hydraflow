"""Regression pins for the stamped repo's never-reported required check (#11715).

The kernel stamped ``REQUIRED_CHECKS = ["quality"]`` into every child's
``scripts/setup_branch_protection.py`` while stamping a ``quality.yml`` whose
``quality`` job is matrix-expanded from a matrix *discovered at runtime*
(``${{ fromJSON(needs.discover-projects.outputs.matrix) }}``). GitHub names
those check runs ``quality (<project_dir>)``, so a bare ``quality`` context is
never reported: it sits at "Expected -- waiting for status" and hard-blocks
every PR on a freshly stamped repo.

Enumerating the legs is NOT the fix -- that is what HydraFlow's own ``main
protect`` does, and it cannot generalise, because a stamped child's leg set is
unknowable at stamp time. The fix is the shape ``ci.yml``'s ``CI Gate`` already
uses: one aggregator job that fans in the matrix and reports a single stable
context.

Two invariants are pinned here:

1. **Structural** -- every stamped required context resolves to a NON-matrix job
   in the stamped workflow, and the aggregator ``needs`` every matrix job (so no
   leg escapes the gate). This is computed from the artifacts, not asserted
   against a hardcoded name, so it keeps holding if the names change.
2. **Behavioral** -- the aggregator's shell body is EXECUTED against synthetic
   upstream results: a failed leg, a cancelled leg, a skipped leg and an empty
   result set must each fail the gate. Text-pinning ``if: always()`` alone would
   not catch a gate that reports green over red.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from ci_scaffold import QUALITY_GATE_CONTEXT, QUALITY_GATE_JOB  # noqa: E402
from onboarding.kernel_writer import KernelSpec, prescription  # noqa: E402

_WORKFLOW_REL = ".github/workflows/quality.yml"
_PROTECTION_REL = "scripts/setup_branch_protection.py"


def _stamped() -> dict[str, str]:
    """The kernel's PRESCRIBED file contents (no disk writes needed)."""
    return {
        rel: content
        for rel, content, _ownership in prescription(KernelSpec(name="demo-repo"))
    }


def _stamped_jobs() -> dict[str, dict]:
    data = yaml.safe_load(_stamped()[_WORKFLOW_REL])
    jobs = data["jobs"]
    assert isinstance(jobs, dict) and jobs, "stamped quality.yml has no jobs"
    return jobs


def _list_constant(source: str, name: str) -> list[str]:
    """A module-level ``name = [...]`` list literal, read out of ``source``."""
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            assert isinstance(value, list) and value, f"{name} parsed empty"
            return value
    raise AssertionError(f"no {name} assignment in stamped {_PROTECTION_REL}")


def _protected_branches() -> list[str]:
    return _list_constant(_stamped()[_PROTECTION_REL], "PROTECTED_BRANCHES")


def _trigger_branches() -> list[str]:
    """Base branches the stamped workflow's `pull_request` trigger accepts.

    ``on`` is YAML's boolean ``True`` after safe_load, hence the two-key lookup.
    """
    data = yaml.safe_load(_stamped()[_WORKFLOW_REL])
    triggers = data.get("on", data.get(True))
    assert isinstance(triggers, dict), "stamped quality.yml has no `on:` block"
    return list(triggers["pull_request"]["branches"])


def _required_checks() -> list[str]:
    """``REQUIRED_CHECKS`` as parsed out of the stamped protection script."""
    return _list_constant(_stamped()[_PROTECTION_REL], "REQUIRED_CHECKS")


def _context_of(job_key: str, spec: dict) -> str:
    """The GitHub check-run context a non-matrix job reports under."""
    return str(spec.get("name") or job_key)


def _matrix_job_keys(jobs: dict[str, dict]) -> set[str]:
    return {
        key
        for key, spec in jobs.items()
        if isinstance(spec, dict)
        and (spec.get("strategy") or {}).get("matrix") is not None
    }


def _gate_script() -> str:
    """The aggregator step's shell body, lifted from the stamped workflow."""
    steps = _stamped_jobs()[QUALITY_GATE_JOB]["steps"]
    runs = [s["run"] for s in steps if "run" in s]
    assert len(runs) == 1, (
        f"expected exactly one run: step in the aggregator, got {len(runs)}"
    )
    return runs[0]


def _run_gate(results: str) -> int:
    """Execute the aggregator's shell body with a synthetic ``RESULTS``."""
    proc = subprocess.run(
        ["bash", "-c", _gate_script()],
        env={"RESULTS": results, "PATH": "/usr/bin:/bin:/usr/local/bin"},
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode


# --------------------------------------------------------------------------
# 1. Structural: the required context is reportable, and gates every leg.
# --------------------------------------------------------------------------


def test_no_required_context_is_a_matrix_job_key() -> None:
    """The #11715 bug itself: requiring a matrix-expanded job by its bare key."""
    jobs = _stamped_jobs()
    matrix_keys = _matrix_job_keys(jobs)
    assert matrix_keys, (
        "the stamped quality.yml no longer has a matrix job — this guard has "
        "gone vacuous; re-point it at whatever produces the dynamic legs"
    )
    offenders = sorted(set(_required_checks()) & matrix_keys)
    assert not offenders, (
        f"branch protection would require {offenders}, but those jobs are "
        "matrix-expanded: GitHub only ever reports '<job> (<value>)' check runs, "
        "so the bare context is never reported and every PR on the stamped repo "
        "blocks forever (#11715). Require the aggregator instead."
    )


def test_required_contexts_are_produced_by_non_matrix_jobs() -> None:
    """Every stamped required context maps to a job that actually reports it."""
    jobs = _stamped_jobs()
    matrix_keys = _matrix_job_keys(jobs)
    producible = {
        _context_of(key, spec) for key, spec in jobs.items() if key not in matrix_keys
    }
    unproducible = sorted(set(_required_checks()) - producible)
    assert not unproducible, (
        f"stamped REQUIRED_CHECKS {unproducible} are produced by no fixed-name job "
        f"in {_WORKFLOW_REL} (fixed-name contexts: {sorted(producible)})"
    )


def test_aggregator_gates_every_matrix_job() -> None:
    """No matrix leg escapes the gate: the aggregator ``needs`` every matrix job."""
    jobs = _stamped_jobs()
    gate = jobs[QUALITY_GATE_JOB]
    assert _context_of(QUALITY_GATE_JOB, gate) == QUALITY_GATE_CONTEXT
    assert QUALITY_GATE_CONTEXT in _required_checks(), (
        "the aggregator exists but branch protection does not require it — "
        "the stamped repo would be gated by nothing"
    )
    needs = set(gate["needs"])
    ungated = sorted(_matrix_job_keys(jobs) - needs)
    assert not ungated, (
        f"matrix job(s) {ungated} are not in the aggregator's `needs`, so their "
        "legs can go red without failing the one required context"
    )


def test_aggregator_runs_even_when_upstream_fails() -> None:
    """``if: always()`` is load-bearing: a skipped gate reports no verdict."""
    gate = _stamped_jobs()[QUALITY_GATE_JOB]
    assert gate.get("if") == "always()", (
        "the aggregator lost `if: always()`. Without it a failed or cancelled "
        "`quality` SKIPS the gate, so the one required context never reports a "
        "verdict of its own — and GitHub resolves that inconsistently (a "
        "job-level skip reads as Success, i.e. green over a red matrix; a "
        "never-expanded matrix stays 'expected', i.e. blocked forever). "
        "`always()` removes the question (#11715)."
    )


# --------------------------------------------------------------------------
# 2. Behavioral: the gate's own shell body, executed.
# --------------------------------------------------------------------------


def test_gate_passes_when_every_upstream_job_succeeded() -> None:
    assert _run_gate("success success") == 0


@pytest.mark.parametrize(
    ("results", "why"),
    [
        ("success failure", "a failed leg must fail the gate"),
        ("success cancelled", "a cancelled leg must fail the gate"),
        ("success skipped", "a skipped leg must fail the gate"),
        ("skipped skipped", "an entirely skipped matrix must fail the gate"),
        ("", "no upstream results at all must fail the gate"),
        ("   ", "whitespace-only results must fail the gate"),
    ],
)
def test_gate_fails_on_any_non_success_upstream(results: str, why: str) -> None:
    assert _run_gate(results) != 0, why


def test_required_context_can_report_on_every_protected_branch() -> None:
    """The workflow must trigger on every branch whose protection requires it.

    ``on.pull_request.branches`` filters by BASE branch. The stamped protection
    script protects `main` AND `staging` with the same required context, and the
    stamped CLAUDE.md tells agents to target `staging` — so a workflow triggering
    only on `main` leaves that context unreported on every feature PR. Different
    mechanism, identical outcome to the bare-`quality` bug: "expected — waiting
    for status", forever (#11715).
    """
    triggers = set(_trigger_branches())
    unreachable = sorted(set(_protected_branches()) - triggers)
    assert not unreachable, (
        f"branch(es) {unreachable} have protection requiring {_required_checks()}, "
        f"but the stamped quality.yml only triggers on {sorted(triggers)} — a PR "
        "into them would never see that check reported and could never merge"
    )
