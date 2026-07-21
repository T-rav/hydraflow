"""Contract tests: FakeGitHub output must match recorded gh-CLI cassettes.

Spec: docs/superpowers/specs/2026-04-22-trust-architecture-hardening-design.md
§4.2 "fake contract tests — replay side". Each cassette in
`tests/trust/contracts/cassettes/github/` was recorded against a live gh
CLI against the sandbox repo; this test replays the cassette input through
`FakeGitHub` and asserts the normalized stdout/stderr/exit_code matches.

The refresh side (re-recording the cassettes against the live CLI) lives in
`src/contract_refresh_loop.py` — tracked separately from this replay gate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mockworld.fakes.fake_github import FakeGitHub
from tests.conftest import IssueFactory
from tests.trust.contracts._replay import FakeOutput, list_cassettes, replay_cassette
from tests.trust.contracts._schema import Cassette

_CASSETTE_DIR = Path(__file__).parent / "cassettes" / "github"


async def _invoke_fake_github(cassette: Cassette) -> FakeOutput:  # noqa: PLR0911
    """Dispatch the cassette input through FakeGitHub's matching method."""
    fake = FakeGitHub()
    method = cassette.input.command
    args = cassette.input.args

    if method == "create_pr":
        issue = IssueFactory.create(number=int(args[0]))
        pr_info = await fake.create_pr(issue, branch=str(args[1]))
        stdout = f"{pr_info.url}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "merge_pr":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        merged = await fake.merge_pr(pr_number)
        assert merged, "FakeGitHub.merge_pr unexpectedly returned False"
        stdout = f"merged pull request https://github.com/_/_/pull/{pr_number}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "close_issue":
        issue_number = int(args[0])
        # Cassette shape (#10025): ["<number>", "--reason", "<reason>"] —
        # thread the recorded reason through the fake's close, then assert
        # the state-reason side effect the reason exists to produce.
        reason = str(args[2]) if len(args) > 2 and args[1] == "--reason" else None
        fake.add_issue(issue_number, "Test Issue", "body")
        await fake.close_issue(issue_number, reason=reason)
        expected_reason = reason.upper().replace(" ", "_") if reason else "COMPLETED"
        state = await fake.get_issue_state(issue_number)
        assert state == expected_reason, (
            f"close_issue(reason={reason!r}) recorded state {state!r}; "
            f"expected {expected_reason!r}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "close_task":
        n = int(args[0])
        fake.add_issue(n, "Test issue", "")
        await fake.close_task(n)
        assert fake._issues[n].state == "closed"
        return FakeOutput(exit_code=0, stdout="", stderr=f"✓ Closed issue #{n}\n")

    if method == "create_task":
        title = str(args[0])
        body = str(args[1]) if len(args) > 1 else ""
        # FakeGitHub.create_task seeds an issue starting at 9001 when the
        # store is empty; the cassette hard-codes that initial value so the
        # contract is deterministic.
        new_number = await fake.create_task(title, body)
        return FakeOutput(
            exit_code=0,
            stdout=f"https://github.com/test-org/test-repo/issues/{new_number}\n",
            stderr="",
        )

    if method == "add_labels":
        issue_number = int(args[0])
        fake.add_issue(issue_number, "Seed issue", "")
        labels = [str(a) for a in args[1:]]
        await fake.add_labels(issue_number, labels)
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "ensure_labels_exist":
        await fake.ensure_labels_exist()
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "get_latest_ci_status":
        # Default FakeGitHub._ci_main_status is ("success", "").
        conclusion, url = await fake.get_latest_ci_status()
        stdout = f"{conclusion}\n{url}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_issues_by_label":
        import json as _json

        label = str(args[0])
        # Seed one issue carrying the label so the list is non-empty and
        # the contract covers the dict shape, not just the empty-list path.
        fake.add_issue(42, "CI failure detected", "main is red", labels=[label])
        issues = await fake.list_issues_by_label(label)
        stdout = _json.dumps(issues) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_open_issues":
        import json as _json

        # Seed two open issues (one labelled, one not) plus a closed issue
        # that must be excluded — covers the "no label filter" projection
        # and both the label-flattening and empty-labels paths.
        fake.add_issue(101, "Stale doc gap", "docs drifted", labels=["hydraflow-find"])
        fake.add_issue(102, "Needs triage", "no labels yet")
        fake.add_issue(103, "Already closed", "done")
        await fake.close_issue(103)
        issues = await fake.list_open_issues()
        stdout = _json.dumps(issues) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "get_issue_labels":
        issue_number = int(args[0])
        # Seed the issue with a deterministic label set so the contract
        # covers the non-empty path, mirroring the newline-separated output
        # of `gh issue view --json labels --jq '.labels[].name'`.
        fake.add_issue(
            issue_number,
            "Labelled issue",
            "body",
            labels=["hydraflow-ready", "hydraflow-review"],
        )
        names = await fake.get_issue_labels(issue_number)
        stdout = "".join(f"{name}\n" for name in names)
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "create_issue":
        title = str(args[0])
        body = str(args[1]) if len(args) > 1 else ""
        labels = [str(a) for a in args[2:]] if len(args) > 2 else None
        # Empty store: max(keys, default=9000)+1 = 9001; cassette hard-codes
        # that value so the contract is deterministic.
        new_number = await fake.create_issue(title, body, labels=labels)
        return FakeOutput(
            exit_code=0,
            stdout=f"https://github.com/test-org/test-repo/issues/{new_number}\n",
            stderr="",
        )

    if method == "post_comment":
        issue_number = int(args[0])
        body = str(args[1]) if len(args) > 1 else ""
        fake.add_issue(issue_number, "Seed issue", "")
        await fake.post_comment(issue_number, body)
        # Side-effect: comment must be recorded on the issue.
        assert body in fake._issues[issue_number].comments, (
            f"post_comment did not record comment on issue #{issue_number}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    # --- Staging / RC promotion cluster (#9768 slice; subsumes #9436) ---

    if method == "create_rc_branch":
        sha = await fake.create_rc_branch(str(args[0]))
        return FakeOutput(exit_code=0, stdout=f"{sha}\n", stderr="")

    if method == "push_synthetic_commit":
        sha = await fake.push_synthetic_commit(str(args[0]), str(args[1]))
        return FakeOutput(exit_code=0, stdout=f"{sha}\n", stderr="")

    if method == "create_promotion_pr":
        pr_number = await fake.create_promotion_pr(
            rc_branch=str(args[0]),
            title="Promote staging to main",
            body="Automated RC promotion (ADR-0042).",
        )
        # Read the stored URL rather than hard-coding it — the fake's URL
        # host (test/repo) is the single source of truth; any format change
        # must surface in this contract gate (#9436 plan).
        url = fake._prs[pr_number].url
        return FakeOutput(exit_code=0, stdout=f"{url}\n", stderr="")

    if method == "find_open_promotion_pr":
        found = await fake.find_open_promotion_pr()
        assert found is None, (
            f"fresh FakeGitHub must have no open promotion PR, got {found!r}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "merge_promotion_pr":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=0, branch="rc/2026-05-13-0000")
        merged = await fake.merge_promotion_pr(pr_number)
        assert merged, "FakeGitHub.merge_promotion_pr unexpectedly returned False"
        # The fake returns True even for an absent PR — the .merged
        # side-effect on the seeded PR is what actually pins fidelity.
        assert fake._prs[pr_number].merged, (
            f"merge_promotion_pr did not mark PR #{pr_number} merged"
        )
        stdout = f"merged pull request https://github.com/_/_/pull/{pr_number}\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "update_pr_branch":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        fake._prs[pr_number].mergeable = False
        ok = await fake.update_pr_branch(pr_number)
        assert fake._prs[pr_number].mergeable, (
            f"update_pr_branch did not clear the conflict flag on #{pr_number}"
        )
        return FakeOutput(exit_code=0, stdout=f"{ok}\n", stderr="")

    if method == "update_pr_base":
        pr_number = int(args[0])
        base = str(args[1])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        ok = await fake.update_pr_base(pr_number, base=base)
        assert fake._prs[pr_number].base == base, (
            f"update_pr_base did not record base {base!r} on #{pr_number}"
        )
        return FakeOutput(exit_code=0, stdout=f"{ok}\n", stderr="")

    if method == "list_rc_branches":
        import json as _json

        branches = await fake.list_rc_branches()
        return FakeOutput(exit_code=0, stdout=_json.dumps(branches) + "\n", stderr="")

    if method == "delete_branch":
        ok = await fake.delete_branch(str(args[0]))
        return FakeOutput(exit_code=0, stdout=f"{ok}\n", stderr="")

    if method == "list_recent_promotion_prs":
        import json as _json

        days = int(args[0]) if args else 7
        prs = await fake.list_recent_promotion_prs(days=days)
        return FakeOutput(exit_code=0, stdout=_json.dumps(prs) + "\n", stderr="")

    if method == "ensure_branch_exists":
        created = await fake.ensure_branch_exists(str(args[0]), base=str(args[1]))
        return FakeOutput(exit_code=0, stdout=f"{created}\n", stderr="")

    if method == "apply_staging_branch_protection":
        import json as _json

        result = await fake.apply_staging_branch_protection(str(args[0]))
        return FakeOutput(exit_code=0, stdout=_json.dumps(result) + "\n", stderr="")

    if method == "wait_for_ci":
        from ci_sentinels import is_ci_incomplete

        passed, summary = await fake.wait_for_ci(int(args[0]))
        # #9351 contract class: a success summary must never be classified
        # as an incomplete wait, or the caller retries a finished CI forever
        # (and the inverse drift once force-closed green RC PRs for 3 days).
        assert not is_ci_incomplete(summary), (
            f"success summary {summary!r} mis-classified as incomplete"
        )
        return FakeOutput(exit_code=0, stdout=f"{passed}\n{summary}\n", stderr="")

    msg = f"FakeGitHub has no contract-tested method {method!r}"
    raise NotImplementedError(msg)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "cassette_path",
    list_cassettes(_CASSETTE_DIR),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
async def test_fake_github_matches_cassette(cassette_path: Path) -> None:
    """Replay a GitHub cassette; assert FakeGitHub's output matches under normalizers."""
    await replay_cassette(cassette_path, _invoke_fake_github)


def test_cassette_directory_not_empty() -> None:
    """A trust gate with zero cassettes is a silent pass — guard against that."""
    assert list_cassettes(_CASSETTE_DIR), (
        f"{_CASSETTE_DIR} has no *.yaml cassettes; seed at least one."
    )
