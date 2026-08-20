"""Per-adapter recording subroutines for the fake-contract test cassettes.

§4.2 Task 13 of
``docs/superpowers/plans/2026-04-22-fake-contract-tests.md``.

Each ``record_<adapter>`` function runs the *real* CLI for its adapter
(``gh`` / ``git`` / ``docker`` / ``claude``) and writes one or more
cassette fixtures to a caller-supplied temp directory. The shape of the
YAML payload matches :class:`contracts._schema.Cassette` so
later stages of the ``ContractRefreshLoop`` tick (Tasks 14–18) can diff
the fresh recordings against the committed cassettes and drive
refresh-PRs / drift-repair issues.

Design notes
------------

* **Recording, not replay.** These functions intentionally spawn real
  binaries and talk to real services. The *replay* harness
  (``tests/trust/contracts/_replay.py``) reads the cassettes these
  recorders produce and does not talk to any network.
* **Graceful failure.** A missing binary (``FileNotFoundError``), a
  non-zero CLI exit, a missing sandbox directory, or any
  ``OSError`` / ``subprocess.SubprocessError`` returns an empty
  ``list[Path]`` and emits a ``WARNING``. The caller (the background
  loop's ``_do_work``) decides whether that indicates drift or
  infrastructure trouble — the recorder itself never raises into the
  loop.
* **No side-effects outside the passed-in dir.** Every file written by
  a recorder lives under its ``tmp_cassette_dir`` / ``tmp_stream_dir``
  argument. The background loop is responsible for copying accepted
  cassettes to their committed path (Task 15).
* **Synchronous on purpose.** ``subprocess.run`` is used rather than
  ``asyncio.create_subprocess_exec`` because the refresh tick runs once
  a week and these calls are dominated by network/IO latency; the
  synchronous form is simpler to mock and simpler to reason about. The
  loop wraps these calls behind ``asyncio.to_thread`` so the event
  loop is not blocked while the recorder runs. As a defence-in-depth
  measure, every ``subprocess.run`` here passes
  ``timeout=_RECORDER_SUBPROCESS_TIMEOUT_S`` (120 s) so a hung
  subprocess (network-degraded host, expired auth, rate-limited
  ``api.anthropic.com``) cannot deadlock the event loop even if the
  ``to_thread`` wrapper is bypassed.

Ubiquitous language
-------------------

``cassette``, ``adapter``, ``fixture_repo``, ``interaction``,
``normalizers`` — see ``src/contracts/_schema.py``.
"""

from __future__ import annotations

import json
import logging
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agent_cli import claude_isolation_flags

logger = logging.getLogger("hydraflow.contract_recording")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Pinned alpine image — a floating ``:latest`` would cause cassette churn
# every time a new alpine layer lands on Docker Hub.
_ALPINE_IMAGE = "alpine:3.19"

# Stable prompt for the Claude stream recorder. "ping" is cheap,
# deterministic in shape (session → assistant → result) even when the
# exact wording of the assistant message varies — the normalizers in
# ``_schema.py`` collapse the volatile bits.
_CLAUDE_PROMPT = "ping"

# Hard wall-clock cap on every recorder subprocess. 120s is generous
# enough for a healthy ``gh``/``git``/``docker``/``claude`` round-trip
# while ensuring a hung subprocess (network-degraded host, expired auth,
# rate-limited ``api.anthropic.com``, frozen Docker daemon) cannot
# deadlock the asyncio event loop forever. Originally surfaced by
# sandbox-tier work (PR #8452 Task 2.5c) where the air-gapped network
# made ``claude -p ping`` hang indefinitely, freezing the orchestrator
# (and the dashboard server with it).
_RECORDER_SUBPROCESS_TIMEOUT_S = 120

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _recorder_sha() -> str:
    """Return the short SHA of ``HEAD`` for the recording context, or
    ``"unknown"`` if ``git`` is unavailable. Stamped into every cassette so
    ``git blame`` on a drifted fixture leads back to the recording run.

    A 120-second hard timeout prevents event-loop deadlock when the
    subprocess hangs (network failure, expired auth, frozen filesystem,
    etc.). On timeout we degrade gracefully to ``"unknown"`` rather than
    raise — the cassette payload is best-effort metadata.
    """
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_RECORDER_SUBPROCESS_TIMEOUT_S,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return "unknown"
    sha = proc.stdout.strip()
    return sha or "unknown"


def _now_iso() -> str:
    """UTC timestamp in the same format the existing cassettes use."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_cassette_payload(
    *,
    adapter: str,
    interaction: str,
    fixture_repo: str,
    command: str,
    args: list[str],
    exit_code: int,
    stdout: str,
    stderr: str,
    normalizers: list[str],
) -> dict[str, Any]:
    """Assemble the dict that matches :class:`Cassette`'s schema."""
    return {
        "adapter": adapter,
        "interaction": interaction,
        "recorded_at": _now_iso(),
        "recorder_sha": _recorder_sha(),
        "fixture_repo": fixture_repo,
        "input": {
            "command": command,
            "args": list(args),
            "stdin": None,
            "env": {},
        },
        "output": {
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
        },
        "normalizers": list(normalizers),
    }


def _write_yaml_cassette(path: Path, payload: dict[str, Any]) -> None:
    """Serialize *payload* to *path* as YAML (mirrors ``_schema.dump_cassette``).

    Refuses to overwrite an existing cassette whose ``output.stdout`` was
    non-empty with a new payload whose ``output.stdout`` is empty — that
    almost always means the recorder ran in a degenerate context
    (suppressed output, broken pipe, locale weirdness) and the existing
    cassette is the better contract. Logs a WARN so the skip is visible
    in operator logs instead of going silent.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    new_stdout = (payload.get("output") or {}).get("stdout") or ""
    if not new_stdout and path.exists():
        try:
            existing = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            existing = {}
        existing_stdout = (existing.get("output") or {}).get("stdout") or ""
        if existing_stdout:
            logger.warning(
                "contract_recording: refusing to overwrite %s — new stdout is "
                "empty but existing cassette has non-empty stdout (likely "
                "degenerate recording context)",
                path,
            )
            return
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh, sort_keys=False, default_flow_style=False)


def _run(argv: list[str]) -> subprocess.CompletedProcess[str] | None:
    """Run *argv* with captured text output. Return None on
    ``FileNotFoundError`` / ``OSError`` / ``SubprocessError`` /
    ``TimeoutExpired`` and warn-log the failure — the caller propagates
    that as an empty recording list.

    A 120-second hard timeout prevents event-loop deadlock when the
    subprocess hangs (network failure, expired auth, rate-limited
    ``api.anthropic.com``, frozen Docker daemon, etc.). On timeout we
    log a warning and return None so the recorder degrades to "no
    cassette written" rather than freezing the orchestrator's asyncio
    event loop. ``subprocess.TimeoutExpired`` is a subclass of
    ``SubprocessError`` but caught explicitly here for clearer logs.
    """
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=_RECORDER_SUBPROCESS_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        logger.warning("contract_recording: binary missing for %s: %s", argv[0], exc)
    except subprocess.TimeoutExpired as exc:
        logger.warning(
            "contract_recording: subprocess timed out after %ss for %s: %s",
            _RECORDER_SUBPROCESS_TIMEOUT_S,
            argv[0],
            exc,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("contract_recording: subprocess failed for %s: %s", argv[0], exc)
    return None


def _require_success(
    proc: subprocess.CompletedProcess[str] | None, *, label: str
) -> bool:
    """Log a warning + return False if *proc* is None or exited non-zero."""
    if proc is None:
        return False
    if proc.returncode != 0:
        logger.warning(
            "contract_recording: %s exited %s: %s",
            label,
            proc.returncode,
            (proc.stderr or "").strip(),
        )
        return False
    return True


def _gh_api_scalar(argv: list[str], *, label: str) -> str | None:
    """Run a scalar-returning ``gh api`` call and return its stripped, non-empty
    stdout — or ``None`` (warn-logged) on a missing binary, non-zero exit, or
    empty output. Collapses the run → require-success → strip → non-empty guard
    that every Git-Data-API read/write in ``_provision_scratch_branch`` repeats.
    """
    proc = _run(argv)
    if not _require_success(proc, label=label):
        return None
    assert proc is not None
    value = proc.stdout.strip().strip('"')
    if not value:
        logger.warning("contract_recording: %s returned empty output", label)
        return None
    return value


# ---------------------------------------------------------------------------
# Public recorders
# ---------------------------------------------------------------------------


# Stable fake-shaped stdout for create_issue — mirrors FakeGitHub.create_issue
# which always returns "https://github.com/test-org/test-repo/issues/{n}\n".
# The recorder captures the real CLI exit code but stores this constant so the
# replay test compares apples-to-apples (same pattern as record_docker).
_FAKE_CREATE_ISSUE_STDOUT = "https://github.com/test-org/test-repo/issues/9001\n"

# Fixed scratch branch + synthetic-commit message used by
# ``_provision_scratch_branch``. The branch name is intentionally constant (not
# per-run) for determinism: the happy-path ``gh pr merge --delete-branch``
# removes it, and the best-effort pre-delete in ``_provision_scratch_branch``
# makes the fixed name idempotent across a prior interrupted tick.
_SCRATCH_BRANCH = "contract-recorder-scratch"
_SCRATCH_COMMIT_MESSAGE = "contract recorder scratch commit"

# Stable logical PR/issue numbers written into the merge_pr / close_issue
# cassettes. The live sandbox numbers are volatile, and
# ``contract_diff._canonical_payload`` does NOT normalize ``input.args`` (it
# drops only ``recorded_at``/``recorder_sha`` and runs normalizers on
# ``stdin``/``stdout``/``stderr`` only). Recording the live number would diff
# against the committed cassettes' ``args: ["42"]`` and file a phantom
# ``contract-refresh`` PR on every weekly tick. We store these constants (which
# match the committed cassettes byte-for-byte) in the cassette and use the live
# numbers only for the side-effecting CLI calls — mirroring the stable-shape
# ``_FAKE_CREATE_ISSUE_STDOUT`` pattern.
_FAKE_MERGE_PR_NUMBER = "42"
_FAKE_CLOSE_ISSUE_NUMBER = "42"

# Fixed scratch branches for the create_pr / create_promotion_pr recorders —
# distinct names from _SCRATCH_BRANCH (merge_pr's) so all mutations can run in
# the same tick without one recorder's provisioning/cleanup stepping on
# another's branch ref.
_CREATE_PR_SCRATCH_BRANCH = "contract-recorder-create-pr-scratch"
_PROMOTION_SCRATCH_BRANCH = "contract-recorder-promotion-scratch"

# Stable logical args + fake-shaped stdout for the create_pr cassette.
# Filename/interaction stay "pr_create" (not "create_pr") to match the
# pre-existing hand-authored baseline (tests/trust/contracts/cassettes/github/
# pr_create.yaml) this recorder promotes to machine-recorded —
# contract_diff.detect_adapter_drift matches recorded vs committed cassettes
# by filename, so keeping the name lands the diff on the SAME committed
# fixture instead of creating an orphaned duplicate (mirrors #8693's in-place
# close_issue/create_issue/merge_pr conversion). ["42", "contract-branch"] and
# the test-org/test-repo URL mirror the committed baseline exactly so a
# correctly-recorded cassette is drift-free against it on day one (#9535
# pattern) regardless of the sandbox's live PR number.
_FAKE_CREATE_PR_ARGS = ["42", "contract-branch"]
_FAKE_CREATE_PR_STDOUT = "https://github.com/test-org/test-repo/pull/101\n"

# Stable logical rc-branch arg + fake-shaped stdout for create_promotion_pr —
# matches the hand-authored baseline from #10092
# (create_promotion_pr.yaml). FakeGitHub.create_promotion_pr stores the PR
# under the "test/repo" host (NOT test-org/test-repo — see that cassette's
# comment) at _pr_counter's starting value (10_000) for a fresh FakeGitHub
# instance.
_FAKE_PROMOTION_RC_BRANCH = "rc/2026-05-13-0000"
_FAKE_CREATE_PROMOTION_PR_STDOUT = "https://github.com/test/repo/pull/10000\n"


def _parse_trailing_int(url: str) -> int | None:
    """Return the trailing integer segment of a GitHub resource URL, or None."""
    stripped = url.strip().rstrip("/")
    try:
        return int(stripped.split("/")[-1])
    except (ValueError, IndexError):
        return None


def _record_close_issue(sandbox_repo: str, tmp_dir: Path) -> Path | None:
    """Provision a fresh sandbox issue then close it; write close_issue cassette."""
    create = _run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            sandbox_repo,
            "--title",
            "contract-recorder-scratch",
            "--body",
            "",
        ]
    )
    if not _require_success(create, label="gh issue create (close_issue setup)"):
        return None
    assert create is not None
    issue_number = _parse_trailing_int(create.stdout)
    if issue_number is None:
        logger.warning(
            "contract_recording: could not parse issue number from %r", create.stdout
        )
        return None

    # `--reason "not planned"` exercises the reason-threading path (#10025):
    # PRManager.close_issue(reason=...) is how automated dedup closes record
    # stateReason=NOT_PLANNED instead of gh's default COMPLETED.
    close = _run(
        [
            "gh",
            "issue",
            "close",
            str(issue_number),
            "--repo",
            sandbox_repo,
            "--reason",
            "not planned",
        ]
    )
    if not _require_success(close, label="gh issue close"):
        return None
    assert close is not None

    payload = _build_cassette_payload(
        adapter="github",
        interaction="close_issue",
        fixture_repo=sandbox_repo,
        command="close_issue",
        # STABLE logical arg (#9535) composed with the #10025 reason flags —
        # the live ``issue_number`` still drives the side-effecting
        # ``gh issue close`` above, but ``input.args`` is compared verbatim by
        # the drift layer, so it must equal the committed cassette's
        # ["42", "--reason", "not planned"] to avoid a phantom refresh PR
        # every tick.
        args=[_FAKE_CLOSE_ISSUE_NUMBER, "--reason", "not planned"],
        exit_code=close.returncode,
        # Fake-shaped: FakeGitHub.close_issue returns empty stdout/stderr.
        # Real gh CLI may print a confirmation line; we discard it so the
        # cassette matches what FakeGitHub emits and replay tests pass.
        stdout="",
        stderr="",
        normalizers=[],
    )
    payload["baseline_only"] = False
    path = tmp_dir / "close_issue.yaml"
    _write_yaml_cassette(path, payload)
    return path


def _record_create_issue(sandbox_repo: str, tmp_dir: Path) -> Path | None:
    """Create a sandbox issue; write create_issue cassette; close the issue."""
    create = _run(
        [
            "gh",
            "issue",
            "create",
            "--repo",
            sandbox_repo,
            "--title",
            "contract-recorder-scratch",
            "--body",
            "",
        ]
    )
    if not _require_success(create, label="gh issue create (create_issue)"):
        return None
    assert create is not None

    issue_number = _parse_trailing_int(create.stdout)

    payload = _build_cassette_payload(
        adapter="github",
        interaction="create_issue",
        fixture_repo=sandbox_repo,
        command="create_issue",
        args=["contract-recorder-scratch", ""],
        exit_code=0,
        # Fake-shaped: FakeGitHub.create_issue always returns a test-org URL
        # at issue 9001. Real sandbox URL differs; store the stable fake shape
        # so replay compares apples-to-apples.
        stdout=_FAKE_CREATE_ISSUE_STDOUT,
        stderr="",
        normalizers=[],
    )
    payload["baseline_only"] = False
    path = tmp_dir / "create_issue.yaml"
    _write_yaml_cassette(path, payload)

    # Clean up: close the scratch issue so no durable open issues accumulate
    # in the sandbox repo across ContractRefreshLoop ticks.
    if issue_number is not None:
        close = _run(
            ["gh", "issue", "close", str(issue_number), "--repo", sandbox_repo]
        )
        if not _require_success(close, label="gh issue close (create_issue cleanup)"):
            logger.warning(
                "contract_recording: cleanup close of issue #%s failed — cassette "
                "was written successfully but the sandbox issue remains open",
                issue_number,
            )
    else:
        logger.warning(
            "contract_recording: could not parse issue number from %r — "
            "sandbox issue was not closed",
            create.stdout,
        )

    return path


def _provision_scratch_branch(sandbox_repo: str, *, branch: str) -> str | None:
    """Create *branch* in *sandbox_repo* carrying a single tree-identical commit.

    GitHub rejects ``gh pr create`` when the head branch has no commits between
    it and its base ("No commits between main and <branch>"). The old recorder
    created the branch ref at ``main``'s SHA with no further commit, so it never
    produced a mergeable PR. We POST a commit whose tree equals ``main``'s tree
    (an empty-diff commit) parented on ``main`` and fast-forward the branch ref
    to it — the PR carries one commit (zero file changes) which GitHub accepts,
    and the eventual merge leaves ``main``'s tree unchanged, so every refresh
    tick is idempotent. Mirrors the proven ``PRManager.push_synthetic_commit``.

    Best-effort deletes any stale ref left by a prior interrupted recording so
    the fixed branch name is re-runnable. Returns the new commit SHA on success,
    or ``None`` (warn-logged) on any failed step — the recorder degrades to "no
    cassette written" rather than raising into the background loop.

    This helper deliberately shells out to the real ``gh`` CLI via ``_run``
    (not ``PRPort``): the whole point of the recorder is to capture the *live*
    contract, so routing through the fake would defeat it.
    """
    # Best-effort cleanup of a stale scratch ref (a prior tick interrupted
    # before ``gh pr merge --delete-branch``). A 404/422 here is expected and
    # deliberately NOT gated on ``_require_success``.
    _run(
        [
            "gh",
            "api",
            f"repos/{sandbox_repo}/git/refs/heads/{branch}",
            "--method",
            "DELETE",
        ]
    )

    main_sha = _gh_api_scalar(
        [
            "gh",
            "api",
            f"repos/{sandbox_repo}/git/ref/heads/main",
            "--jq",
            ".object.sha",
        ],
        label="gh api get main sha",
    )
    if main_sha is None:
        return None

    create_branch = _run(
        [
            "gh",
            "api",
            f"repos/{sandbox_repo}/git/refs",
            "--raw-field",
            f"ref=refs/heads/{branch}",
            "--raw-field",
            f"sha={main_sha}",
        ]
    )
    if not _require_success(create_branch, label="gh api create branch"):
        return None

    tree_sha = _gh_api_scalar(
        [
            "gh",
            "api",
            f"repos/{sandbox_repo}/git/commits/{main_sha}",
            "--jq",
            ".tree.sha",
        ],
        label="gh api get main tree",
    )
    if tree_sha is None:
        return None

    # Tree-identical (empty-diff) commit parented on main: the branch gains one
    # commit (so ``gh pr create`` is accepted) without changing main's tree.
    commit_sha = _gh_api_scalar(
        [
            "gh",
            "api",
            f"repos/{sandbox_repo}/git/commits",
            "--method",
            "POST",
            "--raw-field",
            f"message={_SCRATCH_COMMIT_MESSAGE}",
            "--raw-field",
            f"tree={tree_sha}",
            "--raw-field",
            f"parents[]={main_sha}",
            "--jq",
            ".sha",
        ],
        label="gh api create commit",
    )
    if commit_sha is None:
        return None

    patch_ref = _run(
        [
            "gh",
            "api",
            f"repos/{sandbox_repo}/git/refs/heads/{branch}",
            "--method",
            "PATCH",
            "--raw-field",
            f"sha={commit_sha}",
        ]
    )
    if not _require_success(patch_ref, label="gh api patch branch ref"):
        return None

    return commit_sha


def _record_merge_pr(sandbox_repo: str, tmp_dir: Path) -> Path | None:
    """Provision a scratch branch with a synthetic commit, open + merge a PR;
    write the merge_pr cassette with STABLE logical args.

    ``_provision_scratch_branch`` puts one tree-identical (empty-diff) commit on
    the scratch branch so ``gh pr create`` is accepted while the sandbox
    ``main`` tree never grows. The cassette records the stable logical PR number
    (``"42"``), never the volatile live sandbox number — ``input.args`` is
    compared verbatim by the drift layer, so a live number would phantom-drift
    every tick.
    """
    if not _provision_scratch_branch(sandbox_repo, branch=_SCRATCH_BRANCH):
        return None

    create_pr = _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            sandbox_repo,
            "--head",
            _SCRATCH_BRANCH,
            "--base",
            "main",
            "--title",
            "contract recorder scratch",
            "--body",
            "",
        ]
    )
    if not _require_success(create_pr, label="gh pr create (merge_pr setup)"):
        return None
    assert create_pr is not None
    pr_number = _parse_trailing_int(create_pr.stdout)
    if pr_number is None:
        logger.warning(
            "contract_recording: could not parse PR number from %r", create_pr.stdout
        )
        return None

    # The side-effecting merge targets the LIVE PR number; the cassette does not.
    merge = _run(
        [
            "gh",
            "pr",
            "merge",
            str(pr_number),
            "--repo",
            sandbox_repo,
            "--merge",
            "--delete-branch",
        ]
    )
    if not _require_success(merge, label="gh pr merge"):
        return None
    assert merge is not None

    # Fake-shaped stdout mirrors FakeGitHub.merge_pr; the pr_number normalizer
    # collapses the number so replay is deterministic. Both stdout and args use
    # the STABLE _FAKE_MERGE_PR_NUMBER — args are compared verbatim by the drift
    # layer, so they must equal the committed cassette's ["42"].
    fake_stdout = (
        f"merged pull request https://github.com/_/_/pull/{_FAKE_MERGE_PR_NUMBER}\n"
    )
    payload = _build_cassette_payload(
        adapter="github",
        interaction="merge_pr",
        fixture_repo=sandbox_repo,
        command="merge_pr",
        args=[_FAKE_MERGE_PR_NUMBER],
        exit_code=merge.returncode,
        stdout=fake_stdout,
        stderr="",
        normalizers=["pr_number"],
    )
    payload["baseline_only"] = False
    path = tmp_dir / "merge_pr.yaml"
    _write_yaml_cassette(path, payload)
    return path


def _record_create_pr(sandbox_repo: str, tmp_dir: Path) -> Path | None:
    """Provision a scratch branch with a synthetic commit, open a PR against
    main (without merging), write the pr_create cassette with STABLE logical
    args, then best-effort close+delete-branch so the sandbox doesn't
    accumulate open scratch PRs across ContractRefreshLoop ticks.

    Uses ``_provision_scratch_branch`` (the same no-diff-PR guard #9535 added
    for merge_pr) so ``gh pr create`` is accepted on a tree-identical commit.
    """
    if not _provision_scratch_branch(sandbox_repo, branch=_CREATE_PR_SCRATCH_BRANCH):
        return None

    create_pr = _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            sandbox_repo,
            "--head",
            _CREATE_PR_SCRATCH_BRANCH,
            "--base",
            "main",
            "--title",
            "contract recorder scratch",
            "--body",
            "",
        ]
    )
    if not _require_success(create_pr, label="gh pr create (pr_create)"):
        return None
    assert create_pr is not None
    pr_number = _parse_trailing_int(create_pr.stdout)
    if pr_number is None:
        logger.warning(
            "contract_recording: could not parse PR number from %r", create_pr.stdout
        )
        return None

    # Fake-shaped stdout mirrors FakeGitHub.create_pr (via PRInfoFactory's
    # default URL); both stdout and args use the STABLE logical values that
    # match the committed pr_create.yaml baseline byte-for-byte —
    # input.args is compared verbatim by the drift layer, so the live PR
    # number/branch would phantom-drift every tick (#9535 pattern).
    payload = _build_cassette_payload(
        adapter="github",
        interaction="pr_create",
        fixture_repo=sandbox_repo,
        command="create_pr",
        args=list(_FAKE_CREATE_PR_ARGS),
        exit_code=create_pr.returncode,
        stdout=_FAKE_CREATE_PR_STDOUT,
        stderr="",
        normalizers=["pr_number"],
    )
    payload["baseline_only"] = False
    path = tmp_dir / "pr_create.yaml"
    _write_yaml_cassette(path, payload)

    # Best-effort cleanup: close (never merge — nothing exercises the merge
    # path here) the scratch PR and delete its branch so the sandbox doesn't
    # accumulate open PRs across weekly ticks. A failure here does not
    # invalidate the cassette that was already written.
    close = _run(
        [
            "gh",
            "pr",
            "close",
            str(pr_number),
            "--repo",
            sandbox_repo,
            "--delete-branch",
        ]
    )
    if not _require_success(close, label="gh pr close (pr_create cleanup)"):
        logger.warning(
            "contract_recording: cleanup close of PR #%s failed — cassette "
            "was written successfully but the sandbox PR/branch remains open",
            pr_number,
        )

    return path


def _record_create_promotion_pr(sandbox_repo: str, tmp_dir: Path) -> Path | None:
    """Provision a scratch branch with a synthetic commit, open a promotion
    PR against main, write the create_promotion_pr cassette with STABLE
    logical args, then best-effort close+delete-branch.

    Mirrors PRManager.create_promotion_pr's real shape (``gh pr create
    --base main``) closely enough for contract purposes; the recorded
    cassette never carries the live rc-branch name or PR number — both are
    volatile per real StagingPromotionLoop tick — only the fixed logical
    values already committed by #10092's hand-authored baseline.
    """
    if not _provision_scratch_branch(sandbox_repo, branch=_PROMOTION_SCRATCH_BRANCH):
        return None

    create_pr = _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            sandbox_repo,
            "--head",
            _PROMOTION_SCRATCH_BRANCH,
            "--base",
            "main",
            "--title",
            "Promote staging to main",
            "--body",
            "Automated RC promotion (ADR-0042).",
        ]
    )
    if not _require_success(create_pr, label="gh pr create (create_promotion_pr)"):
        return None
    assert create_pr is not None
    pr_number = _parse_trailing_int(create_pr.stdout)
    if pr_number is None:
        logger.warning(
            "contract_recording: could not parse PR number from %r", create_pr.stdout
        )
        return None

    payload = _build_cassette_payload(
        adapter="github",
        interaction="create_promotion_pr",
        fixture_repo=sandbox_repo,
        command="create_promotion_pr",
        args=[_FAKE_PROMOTION_RC_BRANCH],
        exit_code=create_pr.returncode,
        stdout=_FAKE_CREATE_PROMOTION_PR_STDOUT,
        stderr="",
        normalizers=["pr_number"],
    )
    payload["baseline_only"] = False
    path = tmp_dir / "create_promotion_pr.yaml"
    _write_yaml_cassette(path, payload)

    close = _run(
        [
            "gh",
            "pr",
            "close",
            str(pr_number),
            "--repo",
            sandbox_repo,
            "--delete-branch",
        ]
    )
    if not _require_success(close, label="gh pr close (create_promotion_pr cleanup)"):
        logger.warning(
            "contract_recording: cleanup close of promotion PR #%s failed — "
            "cassette was written successfully but the sandbox PR/branch "
            "remains open",
            pr_number,
        )

    return path


def record_github_mutation(sandbox_repo: str, tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for mutating GitHub operations against the sandbox repo.

    Follows the record_git/record_docker safety contract:
    - Each mutation provisions the required resource first (fresh issue or
      scratch branch+PR), runs the mutation, and captures the CLI exit code.
    - Cassette stdout/stderr use FakeGitHub's return shape, not raw gh CLI
      verbatim — so the replay test compares apples-to-apples.
    - ``baseline_only: false`` on every written cassette so
      ``ContractRefreshLoop`` can auto-regenerate on its weekly tick.
    - Standard guards apply: ``_RECORDER_SUBPROCESS_TIMEOUT_S`` cap via
      ``_run()``, skip-if-no-binary, refuse-to-overwrite-with-degenerate-output
      via ``_write_yaml_cassette()``.

    Command allow-list: close_issue, create_issue, merge_pr, create_pr
    (pr_create.yaml), create_promotion_pr.
    """
    tmp_cassette_dir = Path(tmp_cassette_dir)
    tmp_cassette_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []

    close_path = _record_close_issue(sandbox_repo, tmp_cassette_dir)
    if close_path:
        paths.append(close_path)

    create_path = _record_create_issue(sandbox_repo, tmp_cassette_dir)
    if create_path:
        paths.append(create_path)

    merge_path = _record_merge_pr(sandbox_repo, tmp_cassette_dir)
    if merge_path:
        paths.append(merge_path)

    pr_create_path = _record_create_pr(sandbox_repo, tmp_cassette_dir)
    if pr_create_path:
        paths.append(pr_create_path)

    create_promotion_path = _record_create_promotion_pr(sandbox_repo, tmp_cassette_dir)
    if create_promotion_path:
        paths.append(create_promotion_path)

    return paths


def record_github(sandbox_repo: str, tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for the GitHub adapter against the sandbox repo.

    Delegates to :func:`record_github_mutation` which provisions fresh sandbox
    resources (issues, scratch PRs) and records the mutating operations
    (close_issue, create_issue, merge_pr, create_pr, create_promotion_pr)
    following the record_git/record_docker safety contract — real CLI exit
    codes, fake-shaped output.
    """
    return record_github_mutation(
        sandbox_repo=sandbox_repo,
        tmp_cassette_dir=tmp_cassette_dir,
    )


def record_git(sandbox_dir: Path, tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for the git adapter against a fixture sandbox.

    ``sandbox_dir`` is expected to contain at least one file. The committed
    ``tests/trust/contracts/fixtures/git_sandbox`` fixture is seeded with three
    tracked files (``.gitkeep``, ``README.md``, ``file.txt``), so ``git commit``
    produces the full root-commit summary — the ``(root-commit)`` header, a
    ``N files changed, M insertions(+)`` shortstat, and one ``create mode`` line
    per file. The recorder runs ``git init`` / ``git add -A`` / ``git commit``
    in that directory and captures the commit output verbatim; the replay-side
    fake (``_invoke_fake_git``) reproduces the same summary from a live scan of
    the fixture, so both stay in lockstep as the fixture changes.

    Returns ``[]`` if the sandbox does not exist, ``git`` is missing, or
    any step exits non-zero.
    """
    sandbox_dir = Path(sandbox_dir)
    tmp_cassette_dir = Path(tmp_cassette_dir)
    if not sandbox_dir.is_dir():
        logger.warning("contract_recording: git sandbox dir missing: %s", sandbox_dir)
        return []
    tmp_cassette_dir.mkdir(parents=True, exist_ok=True)

    sandbox_str = str(sandbox_dir)

    # ``-b main`` forces the initial branch regardless of the host's
    # ``init.defaultBranch`` (some systems still ship ``master``) so the
    # recording matches the ``[main <sha>] initial`` line the fake emits.
    init = _run(["git", "-C", sandbox_str, "init", "-q", "-b", "main"])
    if not _require_success(init, label="git init"):
        return []

    add = _run(["git", "-C", sandbox_str, "add", "-A"])
    if not _require_success(add, label="git add"):
        return []

    # NOTE: no ``-q`` — the cassette must capture the ``[main <sha>] initial``
    # confirmation line that ``FakeGit.commit`` emulates. ``-q`` suppresses
    # that line and produced empty-stdout cassettes that broke replay.
    commit = _run(
        [
            "git",
            "-C",
            sandbox_str,
            "-c",
            "user.email=contract@refresh.local",
            "-c",
            "user.name=contract-refresh",
            "commit",
            "-m",
            "initial",
        ]
    )
    if not _require_success(commit, label="git commit"):
        return []
    assert commit is not None

    payload = _build_cassette_payload(
        adapter="git",
        interaction="commit",
        fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
        command="commit",
        args=["initial"],
        exit_code=commit.returncode,
        stdout=commit.stdout,
        stderr=commit.stderr,
        normalizers=["sha:short"],
    )
    commit_path = tmp_cassette_dir / "commit.yaml"
    _write_yaml_cassette(commit_path, payload)

    rev_parse = _run(["git", "-C", sandbox_str, "rev-parse", "HEAD"])
    if not _require_success(rev_parse, label="git rev-parse"):
        return [commit_path]
    assert rev_parse is not None

    rev_parse_payload = _build_cassette_payload(
        adapter="git",
        interaction="rev_parse",
        fixture_repo="tests/trust/contracts/fixtures/git_sandbox",
        command="rev_parse",
        args=["HEAD"],
        exit_code=rev_parse.returncode,
        stdout=rev_parse.stdout,
        stderr=rev_parse.stderr,
        normalizers=["sha:long"],
    )
    rev_parse_path = tmp_cassette_dir / "rev_parse.yaml"
    _write_yaml_cassette(rev_parse_path, rev_parse_payload)
    return [commit_path, rev_parse_path]


def record_docker(tmp_cassette_dir: Path) -> list[Path]:
    """Record cassettes for the docker adapter.

    Runs ``docker run --rm alpine:3.19 echo hello`` — cheap, pinned,
    deterministic. Returns ``[]`` on any docker failure (missing binary,
    daemon offline, pull failure).
    """
    tmp_cassette_dir = Path(tmp_cassette_dir)
    tmp_cassette_dir.mkdir(parents=True, exist_ok=True)

    argv = ["docker", "run", "--rm", _ALPINE_IMAGE, "echo", "hello"]
    proc = _run(argv)
    if not _require_success(proc, label="docker run alpine echo"):
        return []
    assert proc is not None

    # The fake's observable output is the JSON "result" event, not the
    # raw container stdout — store the shape the fake emits so replay
    # compares apples-to-apples. This mirrors the existing committed
    # cassette at tests/trust/contracts/cassettes/docker/run_alpine_echo.yaml.
    fake_shape_stdout = '{"exit_code": 0, "success": true, "type": "result"}\n'

    payload = _build_cassette_payload(
        adapter="docker",
        interaction="run_alpine_echo",
        fixture_repo=_ALPINE_IMAGE,
        command="run_agent",
        args=[_ALPINE_IMAGE, "echo", "hello"],
        exit_code=proc.returncode,
        stdout=fake_shape_stdout,
        stderr="",
        normalizers=[],
    )
    path = tmp_cassette_dir / "run_alpine_echo.yaml"
    _write_yaml_cassette(path, payload)
    return [path]


CLAUDE_STREAM_FILENAME = "stream_001_ping.jsonl"

# This recorder guards the native Claude CLI's raw stream-json protocol.  Its
# model is deliberately owned by the recorder instead of borrowed from an
# unrelated runtime role: maintenance/ADR routing may validly select a GLM,
# OpenRouter, or Kimi model that the native Anthropic endpoint cannot execute.
CLAUDE_STREAM_MODEL = "sonnet"

# Placeholder substituted for live assistant/result text (see
# ``_redact_claude_text``). Deliberately unambiguous so anyone reading a
# committed cassette can tell at a glance that the wording was redacted,
# not really said by the model.
_CLAUDE_TEXT_PLACEHOLDER = "<redacted: non-deterministic assistant text>"


def _redact_claude_text(raw_stdout: str) -> str:
    """Replace free-form assistant/result text with a stable placeholder.

    ``claude -p`` text is live LLM output — it varies on every call even
    for the identical "ping" prompt (issue #10220: the claude adapter's
    ContractRefreshLoop attempt counter never reset because a fresh
    recording essentially never matched the previously committed one, so
    the adapter could never reach a clean tick and kept re-escalating).
    The StreamParser contract only requires a non-empty display/result —
    see ``tests/trust/contracts/test_fake_llm_contract.py`` — not any
    particular wording, so pinning the wording to a fixed placeholder
    keeps the recording deterministic without weakening the structural
    (event-shape) contract. Only the ``assistant`` message's ``text``
    content blocks and the terminal ``result`` event's ``result`` string
    are touched; empty strings are left empty so "no text produced" is
    still distinguishable from "text produced".
    """
    out_lines: list[str] = []
    for raw_line in raw_stdout.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            out_lines.append(raw_line)
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            out_lines.append(raw_line)
            continue
        if not isinstance(event, dict):
            out_lines.append(raw_line)
            continue
        _redact_event_text(event)
        out_lines.append(json.dumps(event))
    trailing_newline = "\n" if raw_stdout.endswith("\n") else ""
    return "\n".join(out_lines) + trailing_newline


def _redact_event_text(event: dict[str, Any]) -> None:
    """Mutate *event* in place, redacting its free-form text fields."""
    if event.get("type") == "assistant":
        message = event.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if isinstance(content, list):
            for block in content:
                if (
                    isinstance(block, dict)
                    and block.get("type") == "text"
                    and block.get("text")
                ):
                    block["text"] = _CLAUDE_TEXT_PLACEHOLDER
    elif event.get("type") == "result":
        if isinstance(event.get("result"), str) and event["result"]:
            event["result"] = _CLAUDE_TEXT_PLACEHOLDER


def record_claude_stream(tmp_stream_dir: Path) -> list[Path]:
    """Record a minimal ``claude`` stream JSONL.

    Runs ``claude -p "ping" --output-format stream-json --verbose --model
    sonnet`` and writes the redacted stdout (see ``_redact_claude_text``) to
    ``<tmp_stream_dir>/stream_001_ping.jsonl``. The Claude adapter
    cassette is *not* YAML — it is a raw JSONL file because the fake
    replays lines verbatim.

    ``claude_isolation_flags()`` restricts the spawn to project-scope
    settings so a host/user-level plugin's ``SessionStart`` hook (e.g.
    superpowers) can't inject its skill-invocation guidance into the
    recording — that guidance is large, changes whenever the plugin's
    skill content changes, and has nothing to do with the stream-json
    protocol shape this cassette exists to guard (issue #10220).

    The recorder always selects :data:`CLAUDE_STREAM_MODEL`; it does not reuse
    an ADR/maintenance role's provider or model because those roles may be
    routed to a non-Anthropic model. The terminal gateway profile skips this
    legacy host subprocess at the composition root because a process running
    on the host cannot be isolated from host OAuth/keychain state. Returns
    ``[]`` if ``claude`` is missing, exits non-zero, or produces empty stdout
    (a zero-byte stream is useless as a fixture and would only corrupt later
    diffs).
    """
    tmp_stream_dir = Path(tmp_stream_dir)
    tmp_stream_dir.mkdir(parents=True, exist_ok=True)

    argv = [
        "claude",
        "-p",
        _CLAUDE_PROMPT,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        CLAUDE_STREAM_MODEL,
        *claude_isolation_flags(),
    ]
    proc = _run(argv)
    if not _require_success(proc, label="claude -p ping"):
        return []
    assert proc is not None

    if not proc.stdout.strip():
        logger.warning(
            "contract_recording: claude produced empty stream; skipping write"
        )
        return []

    path = tmp_stream_dir / CLAUDE_STREAM_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_redact_claude_text(proc.stdout), encoding="utf-8")
    return [path]
