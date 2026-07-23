"""Regression: ``record_github`` skipped ``create_pr``/``create_promotion_pr``
recording (issue #8699).

Before this fix, ``record_github_mutation`` only recorded ``close_issue``,
``create_issue``, and ``merge_pr`` (#8693/#9535). The ``pr_create.yaml`` and
``create_promotion_pr.yaml`` cassettes stayed hand-frozen (``baseline_only:
true``), so ``ContractRefreshLoop`` could never catch real ``gh pr create``
drift for either the regular PR-creation path or the ADR-0042 staging→main
promotion path (#10092 hand-added the promotion cassettes but explicitly
deferred the recorder side to this issue).

This mirrors the #9535 regression exactly (same two defect classes, same
fix shape):

1. **No-diff PR.** ``gh pr create`` rejects a scratch branch with no commits
   ahead of ``main`` — the recorder must provision a tree-identical synthetic
   commit first (``_provision_scratch_branch``) or the recording silently
   fails every tick.
2. **Volatile args.** ``contract_diff._canonical_payload`` does NOT normalize
   ``input.args`` — a live PR number/branch name would phantom-drift against
   the committed stable args and file a spurious ``contract-refresh`` PR
   every tick.

These tests drive ``record_github_mutation`` through a mocked ``gh`` that
returns live values DIFFERENT from every stable logical value baked into the
committed cassettes, and assert (a) drift-free recording vs the committed
baseline and (b) the synthetic-commit provisioning step for both new
recorders. Hermetic: no ``tests/architecture`` conftest fixtures, only
``tmp_path`` + the repo root resolved from ``__file__`` (same pattern as
``test_issue_9535_merge_pr_recorder.py``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from contract_diff import detect_adapter_drift
from contract_recording import record_github_mutation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMITTED = _REPO_ROOT / "tests/trust/contracts/cassettes/github"
_SANDBOX = "T-rav-Hydra-Ops/hydraflow-contracts-sandbox"


def _completed(
    argv: list[str], *, stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=argv, returncode=returncode, stdout=stdout, stderr=""
    )


def _fake_gh(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    """Simulate ``gh`` with live PR numbers/branches DIFFERENT from every
    stable logical value the committed cassettes carry (42, 10000,
    contract-branch, rc/2026-05-13-0000)."""
    # Git Data API: tree read + synthetic-commit POST → non-empty SHA.
    if "api" in argv and any("git/commits" in a for a in argv):
        return _completed(argv, stdout="d" * 40 + "\n")
    # Git Data API: ref get/create/delete/patch → main SHA (mostly unused).
    if "api" in argv and any("git/ref" in a for a in argv):
        return _completed(argv, stdout="e" * 40 + "\n")
    if "issue" in argv and "create" in argv:
        return _completed(argv, stdout=f"https://github.com/{_SANDBOX}/issues/321\n")
    if "pr" in argv and "create" in argv:  # live PR #8888, distinct from 42/10000
        return _completed(argv, stdout=f"https://github.com/{_SANDBOX}/pull/8888\n")
    # gh issue close / gh pr merge / gh pr close / git rev-parse → success.
    return _completed(argv, stdout="")


def test_pr_create_recording_is_drift_free_against_committed(tmp_path: Path) -> None:
    with patch("contract_recording.subprocess.run", side_effect=_fake_gh):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    recorded = tmp_path / "pr_create.yaml"
    assert recorded.exists(), (
        "pr_create cassette must be written — the no-diff-PR guard must hold "
        "for create_pr the same way it does for merge_pr"
    )
    report = detect_adapter_drift("github", [recorded], [_COMMITTED / "pr_create.yaml"])
    assert report is None, f"pr_create drifted despite live PR 8888: {report}"


def test_create_promotion_pr_recording_is_drift_free_against_committed(
    tmp_path: Path,
) -> None:
    with patch("contract_recording.subprocess.run", side_effect=_fake_gh):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    recorded = tmp_path / "create_promotion_pr.yaml"
    assert recorded.exists(), (
        "create_promotion_pr cassette must be written — the no-diff-PR guard "
        "must hold for the promotion scratch branch too"
    )
    report = detect_adapter_drift(
        "github", [recorded], [_COMMITTED / "create_promotion_pr.yaml"]
    )
    assert report is None, f"create_promotion_pr drifted despite live PR 8888: {report}"


def test_pr_create_recorder_posts_synthetic_commit_before_pr_create(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def capture(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _fake_gh(argv, **kw)

    with patch("contract_recording.subprocess.run", side_effect=capture):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    patch_ref = [
        i
        for i, c in enumerate(calls)
        if "--method" in c
        and "PATCH" in c
        and any("git/refs/heads/contract-recorder-create-pr-scratch" in a for a in c)
    ]
    pr_creates = [
        i
        for i, c in enumerate(calls)
        if "pr" in c
        and "create" in c
        and "--head" in c
        and c[c.index("--head") + 1] == "contract-recorder-create-pr-scratch"
    ]

    assert patch_ref, "recorder must PATCH the create_pr scratch ref — no-diff-PR guard"
    assert pr_creates, "recorder must call gh pr create for the create_pr scratch PR"
    assert patch_ref[0] < pr_creates[0], (
        "synthetic-commit ref PATCH must precede gh pr create"
    )


def test_create_promotion_pr_recorder_posts_synthetic_commit_before_pr_create(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def capture(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _fake_gh(argv, **kw)

    with patch("contract_recording.subprocess.run", side_effect=capture):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    patch_ref = [
        i
        for i, c in enumerate(calls)
        if "--method" in c
        and "PATCH" in c
        and any("git/refs/heads/contract-recorder-promotion-scratch" in a for a in c)
    ]
    pr_creates = [
        i
        for i, c in enumerate(calls)
        if "pr" in c
        and "create" in c
        and "--head" in c
        and c[c.index("--head") + 1] == "contract-recorder-promotion-scratch"
    ]

    assert patch_ref, "recorder must PATCH the promotion scratch ref — no-diff-PR guard"
    assert pr_creates, "recorder must call gh pr create for the promotion scratch PR"
    assert patch_ref[0] < pr_creates[0], (
        "synthetic-commit ref PATCH must precede gh pr create"
    )
