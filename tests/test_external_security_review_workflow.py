"""Guards for the external Claude security-review anchor (#10986, ADR-0128).

The anchor's value is being an OUT-OF-BAND, ADVISORY-TO-HUMAN security reviewer
the factory cannot route around, degrade, or make pass itself. These tests pin
the load-bearing invariants of `.github/workflows/claude-security-review.yml` so
a future edit that quietly turns it into a hard gate, wires it into the factory's
auto-merge path, or reviews untrusted fork diffs fails CI.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "claude-security-review.yml"


def _load() -> dict:
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def _job(wf: dict) -> dict:
    jobs = wf["jobs"]
    assert len(jobs) == 1, "the anchor is a single-job workflow"
    return next(iter(jobs.values()))


def _steps(job: dict) -> list[dict]:
    return job["steps"]


def test_workflow_exists() -> None:
    assert _WORKFLOW.is_file(), "the external security-review workflow must exist"


def test_triggers_on_human_prs_into_protected_branches() -> None:
    wf = _load()
    # `on` parses to the truthy key `True` under yaml.safe_load, so read both.
    on = wf.get("on") or wf.get(True)
    assert on is not None, "workflow must declare triggers"
    pr = on["pull_request"]
    assert set(pr["branches"]) == {"staging", "main"}


def test_scoped_to_same_repo_non_automerge_non_dependabot() -> None:
    # The whole assurance value is being external + trusted-diff-only. The job
    # `if` must exclude forks (prompt-injection surface), the factory's governed
    # `auto-merge` PRs (inside the boundary), and dependabot.
    cond = _job(_load())["if"]
    assert "head.repo.full_name == github.repository" in cond, "fork PRs excluded"
    assert "auto-merge" in cond, "factory auto-merge PRs excluded (inside boundary)"
    assert "dependabot" in cond, "dependabot excluded"


def test_review_step_is_advisory_never_a_gate() -> None:
    # Advisory-to-human: the review step must not fail the job (and the workflow
    # must never be wired as a required check — pinned here at the YAML level).
    steps = _steps(_job(_load()))
    review = [
        s for s in steps if "claude-code-security-review" in str(s.get("uses", ""))
    ]
    assert len(review) == 1, "exactly one external-review step"
    assert review[0].get("continue-on-error") is True, (
        "the review step must be advisory (continue-on-error); a hard gate would "
        "let the factory be forced to make the external anchor pass itself"
    )


def test_inert_until_secret_provisioned() -> None:
    # No ANTHROPIC_API_KEY secret → the job is a green no-op: a guard step gates
    # every substantive step on the secret's presence.
    steps = _steps(_job(_load()))
    guard = [s for s in steps if s.get("id") == "guard"]
    assert len(guard) == 1, "a secret-presence guard step is required"
    gated = [
        s
        for s in steps
        if "steps.guard.outputs.enabled == 'true'" in str(s.get("if", ""))
    ]
    # Both the checkout and the review step gate on the guard output.
    assert len(gated) >= 2, "substantive steps must be gated on the secret guard"


def test_least_privilege_permissions() -> None:
    wf = _load()
    # Top-level permissions are empty (least privilege); the job widens only to
    # PR comments + read.
    assert wf.get("permissions") == {}, "top-level permissions must be empty"
    perms = _job(wf)["permissions"]
    assert perms.get("pull-requests") == "write"
    assert perms.get("contents") == "read"
    assert set(perms) == {"pull-requests", "contents"}, "no broader grants"
