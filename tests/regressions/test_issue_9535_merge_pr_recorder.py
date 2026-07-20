"""Regression: ``_record_merge_pr`` no-diff PR + volatile args (issue #9535).

Two independent defects meant the ``merge_pr`` GitHub cassette was never
live-recorded drift-free:

1. **No-diff PR.** The recorder created the scratch branch at ``main``'s SHA
   with no commit, then called ``gh pr create``. GitHub rejects a PR with no
   commits between head and base ("No commits between main and
   contract-recorder-scratch"), so the recorder returned ``None`` every weekly
   tick and the cassette was never refreshed.
2. **Volatile args.** Even if recording succeeded it wrote
   ``args=[str(pr_number)]`` using the live sandbox PR number.
   ``contract_diff._canonical_payload`` does NOT normalize ``input.args`` (it
   drops only ``recorded_at``/``recorder_sha`` and normalizes
   ``stdin``/``stdout``/``stderr``), so a real number would phantom-drift
   against the committed ``args: ["42"]`` and file a spurious
   ``contract-refresh`` PR every tick.

The fix provisions a tree-identical synthetic commit before ``gh pr create``
(mirroring ``PRManager.push_synthetic_commit``) and records stable logical
``args`` (``["42"]``). ``_record_close_issue`` carried the identical
volatile-args bug and is fixed the same way.

These tests drive the recorder through a mocked ``gh`` returning live numbers
DIFFERENT from 42 (PR 9999, issue 537) and pin (a) drift-free recording vs the
committed baseline and (b) the synthetic-commit provisioning step. They are
hermetic: no ``tests/architecture`` conftest fixtures, only ``tmp_path`` + the
repo root resolved from ``__file__``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from contract_diff import detect_adapter_drift
from contract_recording import record_github_mutation

_REPO_ROOT = Path(__file__).resolve().parents[2]
_COMMITTED = _REPO_ROOT / "tests/trust/contracts/cassettes/github"
# Must equal the committed cassettes' ``fixture_repo`` so a correctly-recorded
# cassette canonically matches the baseline (config.contracts_sandbox_repo
# default).
_SANDBOX = "T-rav-Hydra-Ops/hydraflow-contracts-sandbox"


def _completed(
    argv: list[str], *, stdout: str = "", returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=argv, returncode=returncode, stdout=stdout, stderr=""
    )


def _fake_gh(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
    """Simulate ``gh`` with live numbers deliberately DIFFERENT from 42."""
    # Git Data API: tree read + synthetic-commit POST → non-empty SHA.
    if "api" in argv and any("git/commits" in a for a in argv):
        return _completed(argv, stdout="c" * 40 + "\n")
    # Git Data API: ref get/create/delete/patch → main SHA (output mostly unused).
    if "api" in argv and any("git/ref" in a for a in argv):
        return _completed(argv, stdout="a" * 40 + "\n")
    if "issue" in argv and "create" in argv:  # live issue #537 (≠ 42)
        return _completed(argv, stdout=f"https://github.com/{_SANDBOX}/issues/537\n")
    if "pr" in argv and "create" in argv:  # live PR #9999 (≠ 42)
        return _completed(argv, stdout=f"https://github.com/{_SANDBOX}/pull/9999\n")
    # gh issue close / gh pr merge / git rev-parse → success, no output.
    return _completed(argv, stdout="")


def test_merge_pr_recording_is_drift_free_against_committed(tmp_path: Path) -> None:
    with patch("contract_recording.subprocess.run", side_effect=_fake_gh):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    recorded = tmp_path / "merge_pr.yaml"
    assert recorded.exists(), (
        "merge_pr cassette must be written — the no-diff-PR regression is fixed"
    )
    report = detect_adapter_drift("github", [recorded], [_COMMITTED / "merge_pr.yaml"])
    assert report is None, f"merge_pr drifted despite live PR 9999: {report}"


def test_close_issue_recording_is_drift_free_against_committed(tmp_path: Path) -> None:
    with patch("contract_recording.subprocess.run", side_effect=_fake_gh):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    recorded = tmp_path / "close_issue.yaml"
    assert recorded.exists()
    report = detect_adapter_drift(
        "github", [recorded], [_COMMITTED / "close_issue.yaml"]
    )
    assert report is None, f"close_issue drifted despite live issue 537: {report}"


def test_merge_pr_recorder_posts_synthetic_commit_before_pr_create(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def capture(argv: list[str], **kw: object) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        return _fake_gh(argv, **kw)

    with patch("contract_recording.subprocess.run", side_effect=capture):
        record_github_mutation(sandbox_repo=_SANDBOX, tmp_cassette_dir=tmp_path)

    commit_post = [
        i
        for i, c in enumerate(calls)
        if any(str(a).startswith("parents[]=") for a in c)
    ]
    pr_create = [i for i, c in enumerate(calls) if "pr" in c and "create" in c]

    assert commit_post, (
        "recorder must POST a synthetic commit (parents[]= field) — no-diff-PR guard"
    )
    assert pr_create, "recorder must call gh pr create"
    assert commit_post[0] < pr_create[0], (
        "synthetic commit POST must precede gh pr create"
    )
