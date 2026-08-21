"""Regression for #11518 / #11565: no job checks out a job-output ref.

Class: ``actions/cache-poisoning/poisonable-step`` (CodeQL alert #108) — a
privileged job checking out ``ref: ${{ needs.<job>.outputs.<key> }}``. Four
sites carried the shape; each is pinned here to the literal ref it now uses.

* ``staging-rc-dryrun.yml:dryrun-shard`` — literal ``staging`` plus the in-job
  pin (PR #11560). The gate *composition* is executed for real in
  ``test_issue_11518_dryrun_shard_pin_gate.py``; only the ref is pinned here.
* ``staging-rc-dryrun.yml:report`` — literal ``staging``. The SHA the report
  names travels through the job output into the reporter's ``--sha`` via
  ``env:``, so a staging tip that advanced since ``resolve`` cannot make the
  report name the wrong commit; the checkout only supplies the script.
* ``rc-promotion-scenario.yml:{scenario,scenario-browser,trust}`` — no
  ``ref:`` at all. The workflow runs on ``pull_request`` only, so the default
  checkout is the event's own merge ref with a PR-scoped cache; ``gate``
  admits only same-repo ``rc/*`` heads. The cron that resolved "the open
  rc/* PR" through ``gh api`` under default-branch privilege is gone.

Fleet-wide prevention lives in
``tests/architecture/test_workflow_checkout_refs.py``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
DRYRUN = WORKFLOW_DIR / "staging-rc-dryrun.yml"
RC_PROMOTION = WORKFLOW_DIR / "rc-promotion-scenario.yml"

PROTECTED_REF = "staging"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(workflow: dict) -> dict:
    # YAML 1.1 coerces the bare key ``on`` to boolean ``True``.
    raw = workflow.get("on", workflow.get(True))
    return raw if isinstance(raw, dict) else {}


def _steps(workflow: dict, job: str) -> list[dict]:
    return [s for s in workflow["jobs"][job].get("steps") or [] if isinstance(s, dict)]


def _checkouts(workflow: dict, job: str) -> list[dict]:
    return [
        s
        for s in _steps(workflow, job)
        if str(s.get("uses", "")).startswith("actions/checkout@")
    ]


def _ref(step: dict) -> str:
    return str((step.get("with") or {}).get("ref", ""))


def test_dryrun_shard_checks_out_the_literal_protected_branch() -> None:
    checkouts = _checkouts(_load(DRYRUN), "dryrun-shard")
    assert [_ref(s) for s in checkouts] == [PROTECTED_REF]


def test_dryrun_report_checks_out_the_literal_protected_branch() -> None:
    checkouts = _checkouts(_load(DRYRUN), "report")
    assert [_ref(s) for s in checkouts] == [PROTECTED_REF]


def test_dryrun_report_names_the_resolved_sha_not_the_checked_out_tip() -> None:
    # The "one SHA per report" property no longer rides on the checkout: the
    # resolved SHA must reach `--sha` through the environment, and no `run:`
    # in the job may interpolate the job output inline (script-injection sink).
    steps = _steps(_load(DRYRUN), "report")
    aggregate = next(s for s in steps if s.get("id") == "aggregate")
    env = aggregate.get("env") or {}
    carriers = [k for k, v in env.items() if "needs.resolve.outputs.sha" in str(v)]
    assert len(carriers) == 1, env
    assert f'--sha "${carriers[0]}"' in str(aggregate["run"])
    for step in steps:
        assert "${{ needs." not in str(step.get("run", "")), step


def test_rc_promotion_runs_only_in_pull_request_context() -> None:
    # No schedule / workflow_dispatch: nothing here ever runs with
    # default-branch privilege, so there is no privileged cache to poison.
    assert set(_triggers(_load(RC_PROMOTION))) == {"pull_request"}


def test_rc_promotion_jobs_check_out_the_events_own_merge_ref() -> None:
    workflow = _load(RC_PROMOTION)
    suite_jobs = [job for job in workflow["jobs"] if job != "gate"]
    assert len(suite_jobs) >= 3, suite_jobs
    for job in suite_jobs:
        checkouts = _checkouts(workflow, job)
        assert len(checkouts) == 1, (job, checkouts)
        # Absent, not merely literal: the default in a pull_request job IS the
        # event merge ref. Any `ref:` here is a regression to re-litigate.
        assert "ref" not in (checkouts[0].get("with") or {}), (job, checkouts[0])


def test_rc_promotion_gate_no_longer_resolves_a_ref_for_the_suite() -> None:
    gate = _load(RC_PROMOTION)["jobs"]["gate"]
    outputs = gate.get("outputs") or {}
    assert "pr_ref" not in outputs, outputs
    for step in gate.get("steps") or []:
        assert "gh api" not in str(step.get("run", "")), step


def _gate_resolve_step() -> dict:
    gate = _load(RC_PROMOTION)["jobs"]["gate"]
    return next(s for s in gate["steps"] if s.get("id") == "resolve")


def _gate_env_names(resolve: dict) -> tuple[str, str, str]:
    """``(head_ref, head_repo, this_repo)`` env var names, derived from the YAML.

    Derived rather than restated so renaming a variable in the workflow cannot
    leave these tests exercising stale names.
    """
    env = resolve.get("env") or {}
    head_ref = [k for k, v in env.items() if "pull_request.head.ref" in str(v)]
    head_repo = [
        k for k, v in env.items() if "pull_request.head.repo.full_name" in str(v)
    ]
    this_repo = [
        k for k, v in env.items() if str(v).strip() == "${{ github.repository }}"
    ]
    assert len(head_ref) == len(head_repo) == len(this_repo) == 1, env
    return head_ref[0], head_repo[0], this_repo[0]


def test_rc_promotion_gate_admits_only_same_repo_rc_heads() -> None:
    # A fork PR whose head branch is merely *named* rc/* is not a promotion
    # PR. Both sides of the comparison reach the shell through env, never by
    # interpolating attacker-chosen text into `run:`.
    resolve = _gate_resolve_step()
    run = str(resolve["run"])
    for name in _gate_env_names(resolve):
        assert f"${name}" in run, name
    assert "${{" not in run, run


@pytest.mark.parametrize(
    ("head_repo", "head_ref", "want"),
    [
        ("T-rav/hydraflow", "rc/2026-08-21-1259", "true"),
        ("T-rav/hydraflow", "feature/x", "false"),
        ("evil/hydraflow", "rc/2026-08-21-1259", "false"),  # fork named rc/*
        ("", "rc/whatever", "false"),  # head repo deleted -> expression is empty
        ("T-rav/hydraflow", "rc/$(echo injected)", "true"),  # text stays inert
    ],
)
def test_rc_promotion_gate_script_executes_the_same_repo_rc_rule(
    tmp_path: Path, head_repo: str, head_ref: str, want: str
) -> None:
    # The gate is shell, and shell is only trusted by running it: execute the
    # real `run:` block with the real env-var names against each input class.
    resolve = _gate_resolve_step()
    ref_name, repo_name, this_name = _gate_env_names(resolve)
    output = tmp_path / "github_output"
    output.touch()
    env = {
        **os.environ,
        ref_name: head_ref,
        repo_name: head_repo,
        this_name: "T-rav/hydraflow",
        "GITHUB_OUTPUT": str(output),
    }
    proc = subprocess.run(
        ["bash", "-c", str(resolve["run"])],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    values = dict(
        line.split("=", 1) for line in output.read_text().splitlines() if "=" in line
    )
    assert values.get("should_run") == want, (values, proc.stdout)
