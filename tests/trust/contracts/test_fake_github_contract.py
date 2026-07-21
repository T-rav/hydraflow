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
from models import ReviewVerdict
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

    if method == "rerun_workflow_failed":
        run_id = int(args[0])
        ok = await fake.rerun_workflow_failed(run_id)
        assert ok, "FakeGitHub.rerun_workflow_failed unexpectedly returned False"
        assert run_id in fake._workflow_reruns, (
            f"rerun_workflow_failed did not record run {run_id}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

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

    # --- Issue-lifecycle / label cluster (#9768 slice 2) ---

    if method == "find_existing_issue":
        title = str(args[0])
        fake.add_issue(701, title, "body")
        number = await fake.find_existing_issue(title)
        return FakeOutput(exit_code=0, stdout=f"{number}\n", stderr="")

    if method == "get_issue_state":
        issue_number = int(args[0])
        # Closed with no explicit reason: covers the COMPLETED fallback
        # (#10025) rather than the trivial OPEN/UNKNOWN paths.
        fake.add_issue(issue_number, "Closed issue", "body", state="closed")
        state = await fake.get_issue_state(issue_number)
        return FakeOutput(exit_code=0, stdout=f"{state}\n", stderr="")

    if method == "get_issue_updated_at":
        issue_number = int(args[0])
        # Non-default value so the contract doesn't pass vacuously against
        # FakeIssue's hard-coded 2026-01-01T00:00:00Z default.
        fake.add_issue(
            issue_number,
            "Timestamped issue",
            "body",
            updated_at="2026-03-15T10:00:00Z",
        )
        updated_at = await fake.get_issue_updated_at(issue_number)
        return FakeOutput(exit_code=0, stdout=f"{updated_at}\n", stderr="")

    if method == "list_closed_issues_by_label":
        import json as _json

        label = str(args[0])
        fake.add_issue(
            901,
            "Closed with label",
            "body text",
            labels=[label],
            state="closed",
            updated_at="2026-01-15T00:00:00Z",
        )
        rows = await fake.list_closed_issues_by_label(label)
        return FakeOutput(exit_code=0, stdout=_json.dumps(rows) + "\n", stderr="")

    if method == "list_issue_comments":
        import json as _json

        issue_number = int(args[0])
        fake.add_issue(issue_number, "Commented issue", "body")
        fake.add_seeded_comment(
            issue_number,
            "First comment",
            login="reviewer-bot",
            created_at="2026-02-01T00:00:00Z",
        )
        comments = await fake.list_issue_comments(issue_number)
        return FakeOutput(exit_code=0, stdout=_json.dumps(comments) + "\n", stderr="")

    if method == "list_open_issue_numbers":
        import json as _json

        # Seeded out of ascending order to pin the sort; a closed issue
        # must be excluded from the result.
        fake.add_issue(120, "Open A", "body")
        fake.add_issue(110, "Open B", "body")
        fake.add_issue(130, "Closed C", "body", state="closed")
        numbers = await fake.list_open_issue_numbers()
        return FakeOutput(exit_code=0, stdout=_json.dumps(numbers) + "\n", stderr="")

    if method == "update_issue_body":
        issue_number = int(args[0])
        new_body = str(args[1])
        fake.add_issue(issue_number, "Body update target", "old body")
        await fake.update_issue_body(issue_number, new_body)
        assert fake._issues[issue_number].body == new_body, (
            f"update_issue_body did not record the new body on #{issue_number}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "remove_label":
        issue_number = int(args[0])
        label = str(args[1])
        fake.add_issue(
            issue_number, "Label removal target", "body", labels=[label, "keep-me"]
        )
        await fake.remove_label(issue_number, label)
        assert fake._issues[issue_number].labels == ["keep-me"], (
            f"remove_label left unexpected labels on #{issue_number}: "
            f"{fake._issues[issue_number].labels}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "transition":
        issue_number = int(args[0])
        new_stage = str(args[1])
        fake.add_issue(
            issue_number, "Transition target", "body", labels=["hydraflow-plan"]
        )
        await fake.transition(issue_number, new_stage)
        assert fake._issues[issue_number].labels == ["hydraflow-review"], (
            f"transition({new_stage!r}) produced unexpected labels: "
            f"{fake._issues[issue_number].labels}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "swap_pipeline_labels":
        issue_number = int(args[0])
        new_label = str(args[1])
        fake.add_issue(issue_number, "Swap target", "body", labels=["hydraflow-plan"])
        await fake.swap_pipeline_labels(issue_number, new_label)
        assert fake._issues[issue_number].labels == [new_label], (
            f"swap_pipeline_labels did not set literal label {new_label!r} "
            f"on #{issue_number}: {fake._issues[issue_number].labels}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "find_label_drift":
        import json as _json

        # ADR-0088 pr_ahead_of_issue case: issue at a pre-PR label, its PR
        # already at hydraflow-review with commits.
        fake.add_issue(501, "Drift issue", "body", labels=["hydraflow-ready"])
        fake.add_pr(number=601, issue_number=501, branch="b")
        fake.add_pr_label(601, "hydraflow-review")
        drifts = await fake.find_label_drift()
        assert [d.kind for d in drifts] == ["pr_ahead_of_issue"], (
            f"find_label_drift returned unexpected kinds: {[d.kind for d in drifts]}"
        )
        stdout = _json.dumps([d.model_dump(mode="json") for d in drifts]) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    # --- PR review / label-mutation cluster (#9768 slice 3) ---

    if method == "add_pr_labels":
        pr_number = int(args[0])
        labels = [str(a) for a in args[1:]]
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        await fake.add_pr_labels(pr_number, labels)
        assert fake._prs[pr_number].labels == labels, (
            f"add_pr_labels did not record labels on PR #{pr_number}: "
            f"{fake._prs[pr_number].labels}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "remove_pr_label":
        pr_number = int(args[0])
        label = str(args[1])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        fake.add_pr_label(pr_number, label)
        fake.add_pr_label(pr_number, "keep-me")
        await fake.remove_pr_label(pr_number, label)
        assert fake._prs[pr_number].labels == ["keep-me"], (
            f"remove_pr_label left unexpected labels on PR #{pr_number}: "
            f"{fake._prs[pr_number].labels}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "close_pr":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        closed = await fake.close_pr(pr_number)
        assert closed, "FakeGitHub.close_pr unexpectedly returned False"
        assert fake._prs[pr_number].closed, (
            f"close_pr did not mark PR #{pr_number} closed"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "expected_pr_title":
        issue_number = int(args[0])
        issue_title = str(args[1])
        title = FakeGitHub.expected_pr_title(issue_number, issue_title)
        return FakeOutput(exit_code=0, stdout=f"{title}\n", stderr="")

    if method == "update_pr_title":
        pr_number = int(args[0])
        title = str(args[1])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        ok = await fake.update_pr_title(pr_number, title)
        return FakeOutput(exit_code=0, stdout=f"{ok}\n", stderr="")

    if method == "get_pr_mergeable":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        mergeable = await fake.get_pr_mergeable(pr_number)
        return FakeOutput(exit_code=0, stdout=f"{mergeable}\n", stderr="")

    if method == "post_pr_comment":
        pr_number = int(args[0])
        body = str(args[1])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        await fake.post_pr_comment(pr_number, body)
        assert (pr_number, body) in fake._comments, (
            f"post_pr_comment did not record comment on PR #{pr_number}"
        )
        return FakeOutput(exit_code=0, stdout="", stderr="")

    if method == "submit_review":
        pr_number = int(args[0])
        flag = str(args[1])
        body = str(args[2])
        # Cassette shape mirrors close_issue.yaml's "--reason" convention —
        # a CLI-flag-shaped encoding of the ReviewVerdict enum kwarg the
        # real PRManager.submit_review takes.
        verdict_map = {
            "--approve": ReviewVerdict.APPROVE,
            "--request-changes": ReviewVerdict.REQUEST_CHANGES,
            "--comment": ReviewVerdict.COMMENT,
        }
        verdict = verdict_map[flag]
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        ok = await fake.submit_review(pr_number, verdict, body)
        return FakeOutput(exit_code=0, stdout=f"{ok}\n", stderr="")

    if method == "get_pr_approvers":
        import json as _json

        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        approvers = await fake.get_pr_approvers(pr_number)
        return FakeOutput(exit_code=0, stdout=_json.dumps(approvers) + "\n", stderr="")

    if method == "get_pr_checks":
        import json as _json

        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        checks = await fake.get_pr_checks(pr_number)
        return FakeOutput(exit_code=0, stdout=_json.dumps(checks) + "\n", stderr="")

    if method == "get_pr_reviews":
        import json as _json

        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        reviews = await fake.get_pr_reviews(pr_number)
        return FakeOutput(exit_code=0, stdout=_json.dumps(reviews) + "\n", stderr="")

    # --- PR/label read & query cluster (#9768 slice 4) ---

    if method == "find_open_pr_for_branch":
        import json as _json

        branch = str(args[0])
        # Seed an open PR on the branch so the lookup hits, not the
        # number=0 absence sentinel (which get_pr_diff etc. never see).
        fake.add_pr(number=777, issue_number=1, branch=branch)
        info = await fake.find_open_pr_for_branch(branch)
        assert info.number == 777, (
            f"find_open_pr_for_branch returned the wrong PR: {info.number}"
        )
        stdout = _json.dumps(info.model_dump(mode="json")) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_prs_by_label":
        import json as _json

        label = str(args[0])
        # One matching open PR + one merged PR carrying the same label the
        # method must exclude — pins the merged filter, not just the shape.
        fake.add_pr(number=778, issue_number=2, branch="feat/x")
        fake.add_pr_label(778, label)
        fake.add_pr(number=779, issue_number=3, branch="feat/y", merged=True)
        fake.add_pr_label(779, label)
        prs = await fake.list_prs_by_label(label)
        assert [p.number for p in prs] == [778], (
            f"list_prs_by_label leaked a merged PR: {[p.number for p in prs]}"
        )
        stdout = _json.dumps([p.model_dump(mode="json") for p in prs]) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_open_prs":
        import json as _json

        labels = [str(a) for a in args]
        fake.add_pr(number=780, issue_number=4, branch="feat/z")
        fake.add_pr_label(780, labels[0])
        prs = await fake.list_open_prs(labels)
        assert [p.pr for p in prs] == [780], (
            f"list_open_prs returned unexpected PRs: {[p.pr for p in prs]}"
        )
        stdout = _json.dumps([p.model_dump(mode="json") for p in prs]) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_all_open_prs":
        import json as _json

        # A bot PR carrying no HydraFlow label — invisible to the
        # label-filtered list_open_prs, visible here (DependabotMergeLoop).
        fake.add_pr(
            number=781,
            issue_number=0,
            branch="dependabot/pip/foo",
            author="dependabot[bot]",
            is_bot=True,
        )
        prs = await fake.list_all_open_prs()
        assert [p.pr for p in prs] == [781], (
            f"list_all_open_prs returned unexpected PRs: {[p.pr for p in prs]}"
        )
        stdout = _json.dumps([p.model_dump(mode="json") for p in prs]) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_conflicting_prs":
        import dataclasses as _dc
        import json as _json

        # mergeable=False seeds the CONFLICTING PR the method surfaces; a
        # mergeable PR must be excluded.
        fake.add_pr(number=782, issue_number=5, branch="feat/conf", mergeable=False)
        fake.add_pr(number=783, issue_number=6, branch="feat/ok")
        conflicts = await fake.list_conflicting_prs()
        assert [c.number for c in conflicts] == [782], (
            f"list_conflicting_prs returned unexpected PRs: "
            f"{[c.number for c in conflicts]}"
        )
        stdout = _json.dumps([_dc.asdict(c) for c in conflicts]) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "list_hitl_items":
        import json as _json

        hitl_labels = [str(a) for a in args]
        # One open issue at a HITL label + a closed one that must be
        # excluded (list_hitl_items only reports open issues).
        fake.add_issue(305, "Escalated issue", "body", labels=[hitl_labels[0]])
        fake.add_issue(
            306, "Closed HITL", "body", labels=[hitl_labels[0]], state="closed"
        )
        items = await fake.list_hitl_items(hitl_labels)
        assert [i.issue for i in items] == [305], (
            f"list_hitl_items returned unexpected issues: {[i.issue for i in items]}"
        )
        stdout = _json.dumps([i.model_dump(mode="json") for i in items]) + "\n"
        return FakeOutput(exit_code=0, stdout=stdout, stderr="")

    if method == "get_label_counts":
        import json as _json

        from config import HydraFlowConfig

        # Seed a non-trivial world: two open issues at distinct pipeline
        # labels, one closed-fixed issue, one merged PR — so every count in
        # the LabelCounts TypedDict is exercised, not a vacuous all-zero dict.
        fake.add_issue(210, "Open ready", "body", labels=["hydraflow-ready"])
        fake.add_issue(211, "Open review", "body", labels=["hydraflow-review"])
        fake.add_issue(
            212, "Closed fixed", "body", labels=["hydraflow-fixed"], state="closed"
        )
        fake.add_pr(number=790, issue_number=210, branch="b", merged=True)
        counts = await fake.get_label_counts(HydraFlowConfig())
        return FakeOutput(exit_code=0, stdout=_json.dumps(counts) + "\n", stderr="")

    if method == "get_pr_diff":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        diff = await fake.get_pr_diff(pr_number)
        return FakeOutput(exit_code=0, stdout=f"{diff}\n", stderr="")

    if method == "get_pr_diff_names":
        import json as _json

        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        names = await fake.get_pr_diff_names(pr_number)
        return FakeOutput(exit_code=0, stdout=_json.dumps(names) + "\n", stderr="")

    if method == "get_pr_head_sha":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        sha = await fake.get_pr_head_sha(pr_number)
        return FakeOutput(exit_code=0, stdout=f"{sha}\n", stderr="")

    if method == "get_pr_recent_commit_diffs":
        pr_number = int(args[0])
        fake.add_pr(number=pr_number, issue_number=1, branch="b")
        diffs = await fake.get_pr_recent_commit_diffs(pr_number)
        return FakeOutput(exit_code=0, stdout=f"{diffs}\n", stderr="")

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
