"""FakeGitHub `gh issue view` — selector-honoring projection (#11246)."""

from __future__ import annotations

import json

import pytest

from mockworld.fakes import FakeGitHub


@pytest.mark.asyncio
async def test_issue_view_projects_requested_labels_and_body() -> None:
    """`--json labels,body` returns exactly those fields from FakeIssue state.

    Regression for the matched-but-wrong shape: the branch used to return a
    hardcoded ``{"comments": []}`` for every selector, so a consumer reading
    labels/body through the passthrough always saw empty data under
    MockWorld.
    """
    gh = FakeGitHub()
    gh.add_issue(
        42,
        "Button broken",
        "Steps to reproduce…",
        labels=["hydraflow-plan", "bug"],
    )

    output = await gh._run_gh(
        "gh", "issue", "view", "42", "--repo", gh._repo, "--json", "labels,body"
    )

    data = json.loads(output)
    assert data == {
        "labels": [{"name": "hydraflow-plan"}, {"name": "bug"}],
        "body": "Steps to reproduce…",
    }


@pytest.mark.asyncio
async def test_issue_view_projects_title_and_state() -> None:
    """State and its reason use the gh wire vocabulary."""
    gh = FakeGitHub()
    gh.add_issue(7, "Open issue", "body")
    gh.add_issue(8, "Closed issue", "body", state="closed")

    open_out = await gh._run_gh(
        "gh",
        "issue",
        "view",
        "7",
        "--repo",
        gh._repo,
        "--json",
        "title,state,stateReason",
    )
    closed_out = await gh._run_gh(
        "gh",
        "issue",
        "view",
        "8",
        "--repo",
        gh._repo,
        "--json",
        "title,state,stateReason",
    )

    assert json.loads(open_out) == {
        "title": "Open issue",
        "state": "OPEN",
        "stateReason": "",
    }
    assert json.loads(closed_out) == {
        "title": "Closed issue",
        "state": "CLOSED",
        "stateReason": "COMPLETED",
    }


@pytest.mark.asyncio
async def test_issue_view_unions_repeated_json_selectors() -> None:
    """Repeated `--json` flags are unioned, matching the real gh CLI."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "B")

    output = await gh._run_gh(
        "gh", "issue", "view", "42", "--json", "title", "--json", "body"
    )

    assert json.loads(output) == {"title": "T", "body": "B"}


@pytest.mark.asyncio
async def test_issue_view_projects_extended_issue_fields() -> None:
    """All fields modelled by FakeIssue use gh-compatible wire shapes."""
    gh = FakeGitHub()
    gh.add_issue(
        42,
        "T",
        "B",
        state="closed",
        updated_at="2026-08-20T12:34:56Z",
    )
    gh._issues[42].state_reason = "NOT_PLANNED"
    gh.add_seeded_comment(
        42,
        "reviewed",
        login="alice",
        created_at="2026-08-20T12:30:00Z",
    )

    output = await gh._run_gh(
        "gh",
        "issue",
        "view",
        "42",
        "--json",
        "number,updatedAt,stateReason,comments",
    )

    assert json.loads(output) == {
        "number": 42,
        "updatedAt": "2026-08-20T12:34:56Z",
        "stateReason": "NOT_PLANNED",
        "comments": [
            {
                "author": {"login": "alice"},
                "body": "reviewed",
                "createdAt": "2026-08-20T12:30:00Z",
            }
        ],
    }


@pytest.mark.asyncio
async def test_issue_view_omits_and_records_unmodelled_fields() -> None:
    """Unmodelled fields are omitted from the payload and recorded, not faked."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "B", labels=["bug"])

    output = await gh._run_gh(
        "gh", "issue", "view", "42", "--repo", gh._repo, "--json", "labels,assignees"
    )

    data = json.loads(output)
    assert data == {"labels": [{"name": "bug"}]}
    assert gh.issue_view_unmodelled_fields == {"assignees"}


@pytest.mark.asyncio
async def test_issue_view_unknown_issue_raises() -> None:
    """Unknown issues fail like gh instead of masquerading as empty state."""
    gh = FakeGitHub()

    with pytest.raises(RuntimeError, match="issue 9999 not found"):
        await gh._run_gh(
            "gh",
            "issue",
            "view",
            "9999",
            "--repo",
            gh._repo,
            "--json",
            "labels,body",
        )


@pytest.mark.asyncio
async def test_issue_view_without_json_selector_returns_empty_object() -> None:
    """No `--json` selector means nothing is projected — the fake stops
    returning the fabricated ``{"comments": []}`` payload."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "B")

    output = await gh._run_gh("gh", "issue", "view", "42")

    assert json.loads(output) == {}
    assert gh.issue_view_unmodelled_fields == {"--json"}


@pytest.mark.asyncio
async def test_issue_view_trailing_json_flag_without_value_returns_empty_object() -> (
    None
):
    """A trailing `--json` with no selector value projects nothing."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "B")

    output = await gh._run_gh("gh", "issue", "view", "42", "--json")

    assert json.loads(output) == {}
    assert gh.issue_view_unmodelled_fields == {"--json"}


@pytest.mark.asyncio
async def test_issue_view_records_unapplied_jq_filter() -> None:
    """The fake reports that it returned JSON without applying a jq filter."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "B", labels=["bug"])

    output = await gh._run_gh(
        "gh",
        "issue",
        "view",
        "42",
        "--json",
        "labels",
        "--jq",
        ".labels[].name",
    )

    assert json.loads(output) == {"labels": [{"name": "bug"}]}
    assert gh.issue_view_unmodelled_fields == {"--jq"}


# ---------------------------------------------------------------------------
# `gh issue edit <n> --body` mutation (#11246)
#
# ReportIssueLoop._verify_issue appends the screenshot URL by re-writing the
# body through ``update_issue_body``; an inline ``--body`` edit through the
# passthrough must land in the same fake state instead of being swallowed.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_issue_edit_body_updates_fake_issue_body() -> None:
    gh = FakeGitHub()
    gh.add_issue(42, "T", "original body")

    output = await gh._run_gh(
        "gh",
        "issue",
        "edit",
        "42",
        "--repo",
        gh._repo,
        "--body",
        "original body\n\n## Screenshot\n\n![Screenshot](url)\n",
    )

    assert (
        gh._issues[42].body == "original body\n\n## Screenshot\n\n![Screenshot](url)\n"
    )
    assert output == ""


@pytest.mark.asyncio
async def test_issue_edit_body_unknown_issue_is_a_noop() -> None:
    gh = FakeGitHub()

    output = await gh._run_gh(
        "gh", "issue", "edit", "9999", "--repo", gh._repo, "--body", "x"
    )

    assert output == ""
    assert gh._issues == {}


@pytest.mark.asyncio
async def test_issue_edit_body_without_value_is_a_noop() -> None:
    """A trailing `--body` with no value must not corrupt the stored body."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "original")

    output = await gh._run_gh("gh", "issue", "edit", "42", "--repo", gh._repo, "--body")

    assert output == ""
    assert gh._issues[42].body == "original"


@pytest.mark.asyncio
async def test_issue_close_still_closes_through_run_gh() -> None:
    """Pin `gh issue close <n>`: the close/edit branch restructure (#11246)
    must preserve the pre-existing close behaviour."""
    gh = FakeGitHub()
    gh.add_issue(42, "T", "B")

    output = await gh._run_gh("gh", "issue", "close", "42")

    assert output == ""
    assert gh._issues[42].state == "closed"
