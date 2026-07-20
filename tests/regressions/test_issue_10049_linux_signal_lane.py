"""Workflow-lint guard for the Linux signal smoke lane (#10049).

The `linux-signal-smoke` job in `.github/workflows/ci.yml` reruns the
reap/signal-focused test subset inside a Linux container as root — the
process-tree/privilege context where a mocked `.pid` reaching the real
`os.killpg` killed the container's own PID 1 (#9983/#10002). This guard
pins the invariants that keep the lane honest:

1. The `subprocess_signal` paths-filter entry lives in the DEFAULT-quantifier
   filter step and contains positive globs only. A `!` negation there would
   resurrect #9908 (under the default `some` quantifier each `!glob`
   independently matches every file NOT under glob, so the filter fires on
   every PR). Negations belong exclusively in the `core_filter` step, which
   must keep `predicate-quantifier: every`.
2. The filter's file list and the job's pytest args stay in lock-step:
   src modules in the filter are exactly the signal blast-radius set, and
   every test file the filter watches is a test file the job runs (and vice
   versa). Drift in either direction silently un-gates or empties the lane.
3. Every file either side references exists on disk — a rename would
   otherwise leave the lane green-by-vacuity forever.
4. The lane stays ADVISORY: it must NOT appear in `ci-gate`'s `needs`.
   ci-gate is the umbrella that branch protection requires; per #9922 an
   advisory lane must never gate RC auto-merge.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

SIGNAL_SRC_MODULES = {
    "src/execution.py",
    "src/runner_utils.py",
    "src/subprocess_util.py",
    "src/process_group.py",
}


def _load_ci() -> dict[str, Any]:
    return yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))


def _changes_steps() -> list[dict[str, Any]]:
    return _load_ci()["jobs"]["changes"]["steps"]


def _step_by_id(step_id: str) -> dict[str, Any]:
    for step in _changes_steps():
        if step.get("id") == step_id:
            return step
    msg = f"changes job has no step with id={step_id!r}"
    raise AssertionError(msg)


def _filters_of(step: dict[str, Any]) -> dict[str, list[str]]:
    # dorny/paths-filter takes `filters` as a YAML string; parse the inner doc.
    return yaml.safe_load(step["with"]["filters"])


def _lane_pytest_files() -> set[str]:
    job = _load_ci()["jobs"]["linux-signal-smoke"]
    run_texts = [s.get("run", "") for s in job["steps"] if s.get("run")]
    assert run_texts, "linux-signal-smoke has no run step"
    files: set[str] = set()
    for text in run_texts:
        files.update(re.findall(r"tests/\S+\.py", text))
    return files


class TestSubprocessSignalFilter:
    def test_filter_entry_exists_in_default_quantifier_step(self) -> None:
        filters = _filters_of(_step_by_id("filter"))
        assert "subprocess_signal" in filters, (
            "the subprocess_signal paths-filter entry is gone — the "
            "linux-signal-smoke lane no longer triggers on signal-path PRs"
        )

    def test_default_step_has_no_negations(self) -> None:
        step = _step_by_id("filter")
        assert "predicate-quantifier" not in step.get("with", {}), (
            "the default filter step grew a predicate-quantifier — the "
            "#9908 split (negations only in core_filter) has been disturbed"
        )
        for name, globs in _filters_of(step).items():
            negated = [g for g in globs if str(g).startswith("!")]
            assert not negated, (
                f"filter {name!r} uses negation {negated} in the DEFAULT-"
                "quantifier step. Under `some`, each `!glob` independently "
                "matches every file NOT under glob (#9908). Move it to the "
                "core_filter step (predicate-quantifier: every)."
            )

    def test_core_filter_step_keeps_every_quantifier(self) -> None:
        step = _step_by_id("core_filter")
        assert step["with"].get("predicate-quantifier") == "every", (
            "core_filter lost `predicate-quantifier: every` — its `!` "
            "negations now each match every file NOT under the glob and "
            "core_python fires on every PR (#9908)"
        )

    def test_filter_src_set_is_the_signal_blast_radius(self) -> None:
        globs = set(_filters_of(_step_by_id("filter"))["subprocess_signal"])
        src_globs = {g for g in globs if g.startswith("src/")}
        assert src_globs == SIGNAL_SRC_MODULES, (
            f"subprocess_signal src set drifted from the #10010 blast-radius "
            f"modules.\n  missing: {sorted(SIGNAL_SRC_MODULES - src_globs)}\n"
            f"  extra: {sorted(src_globs - SIGNAL_SRC_MODULES)}"
        )

    def test_all_filter_paths_exist(self) -> None:
        globs = _filters_of(_step_by_id("filter"))["subprocess_signal"]
        missing = [g for g in globs if not (REPO_ROOT / g).is_file()]
        assert not missing, (
            f"subprocess_signal filter references nonexistent files "
            f"{missing} — a rename left the lane gated on nothing"
        )


class TestLinuxSignalSmokeJob:
    def test_job_gated_on_subprocess_signal_filter(self) -> None:
        job = _load_ci()["jobs"]["linux-signal-smoke"]
        condition = job.get("if", "")
        assert "needs.changes.outputs.subprocess_signal" in condition, (
            "linux-signal-smoke is no longer gated on the subprocess_signal "
            "filter — it would run on every PR (or never)"
        )
        assert "changes" in job.get("needs", []) or job.get("needs") == "changes", (
            "linux-signal-smoke must depend on the changes job for its gate"
        )

    def test_pytest_files_match_filter_test_set(self) -> None:
        filter_tests = {
            g
            for g in _filters_of(_step_by_id("filter"))["subprocess_signal"]
            if g.startswith("tests/")
        }
        lane_tests = _lane_pytest_files()
        assert filter_tests == lane_tests, (
            f"subprocess_signal filter and linux-signal-smoke pytest args "
            f"drifted.\n  filter-only (job no longer runs them): "
            f"{sorted(filter_tests - lane_tests)}\n  job-only (filter no "
            f"longer triggers on them): {sorted(lane_tests - filter_tests)}"
        )

    def test_all_lane_test_files_exist(self) -> None:
        missing = [f for f in _lane_pytest_files() if not (REPO_ROOT / f).is_file()]
        assert not missing, (
            f"linux-signal-smoke runs nonexistent test files {missing} — "
            "pytest would error (or a rename emptied the lane)"
        )

    def test_lane_runs_inside_a_container_as_docker_run(self) -> None:
        job = _load_ci()["jobs"]["linux-signal-smoke"]
        run_text = "\n".join(s.get("run", "") for s in job["steps"])
        assert "docker run" in run_text, (
            "the lane no longer runs inside a Linux container — plain "
            "runs-on: ubuntu-latest does NOT reproduce the container-as-root "
            "PID-tree that made #9983/#10002 hang (that context is the point)"
        )

    def test_lane_is_advisory_not_in_ci_gate_needs(self) -> None:
        ci = _load_ci()
        gate_needs = ci["jobs"]["ci-gate"]["needs"]
        assert "linux-signal-smoke" not in gate_needs, (
            "linux-signal-smoke was added to ci-gate's needs — that makes an "
            "advisory lane block the required umbrella check and stall RC "
            "auto-merge (#9922). It must stay out of ci-gate."
        )

    def test_lane_has_a_timeout(self) -> None:
        job = _load_ci()["jobs"]["linux-signal-smoke"]
        assert isinstance(job.get("timeout-minutes"), int), (
            "linux-signal-smoke has no timeout-minutes — a reproduced hang "
            "would burn the runner for the 6h default instead of minutes"
        )
