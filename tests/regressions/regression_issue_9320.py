"""Regression tests for issue #9320.

13 drift signatures survived LiveCorpusReplayLoop's 3-tick retry budget because
``gh_shape_validator`` generated false-positive validation errors for several
classes of shadow-corpus call patterns that all existed in main before this fix:

1. **Issue-list vs issue-view routing** — ``gh issue list`` was validated against
   ``GhIssueSummary`` which requires ``state``, but list calls omit it.
   Fix: route issue-list to ``_pick_shape_for_issue_list`` using ``GhIssueListItem``.

2. **--jq transforms** — ``gh pr list --json number --jq length`` produces scalar
   stdout; shape validation is meaningless.
   Fix: skip validation when ``--jq`` is present in args.

3. **Comments-only and narrow issue views** — ``gh issue view N --json comments``
   has no fields matching either issue shape.
   Fix: ``_pick_shape_for_issue`` returns ``None`` when neither ``state`` nor
   both ``number+title`` are present.

4. **Projection-only PR calls** — calls like ``gh pr view N --json commits``,
   ``--json reviews``, or ``--json headRefOid`` omit required fields.
   Fix: ``_pick_shape_for_pr`` guards on required fields before selecting a shape.

5. **Projection-only issue calls** — ``gh issue view N --json state,stateReason``
   omits ``number`` which ``GhIssueSummary`` requires.
   Fix: ``_pick_shape_for_issue`` guards on both ``number+state``.

6. **Narrow pr-checks and issue-list calls** — ``gh pr checks --json conclusion``
   omits ``name`` required by ``GhCheckRun``; ``gh issue list --json createdAt``
   omits ``number+title`` required by ``GhIssueListItem``.
   Fix: required-field guards in ``_pick_shape_for_checks`` and
   ``_pick_shape_for_issue_list``.

7. **Terminal check-run states** — ``gh pr checks --json state`` returns terminal
   conclusion values (``SUCCESS``, ``FAILURE``, ``SKIPPED``, etc.) for finished
   check runs; ``_GhCheckState`` only listed in-progress statuses.
   Fix: expand ``_GhCheckState`` to include all terminal values.

8. **Escalation re-fire** — ``LiveCorpusReplayLoop._file_escalation_issue`` had no
   dedup guard so it filed a new ``hitl-escalation`` issue on every tick past the
   threshold.
   Fix: ``_escalation_dedup_key`` + DedupStore guard in ``_do_work``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from contracts.shadow import ShadowCorpus
from contracts.shape_dispatchers import gh_shape_validator
from live_corpus_replay_loop import _escalation_dedup_key, _fleet_dedup_key


def _sample(
    tmp_path: Path,
    *,
    args: list[str],
    stdout: str,
    adapter: str = "github",
    command: str = "gh",
):
    corpus = ShadowCorpus(tmp_path)
    path = corpus.record(
        adapter=adapter,
        command=command,
        args=args,
        stdout=stdout,
        stderr="",
        exit_code=0,
    )
    assert path is not None
    return corpus.load(path)


# ── Pattern 1: issue-list vs issue-view routing ───────────────────────────────


@pytest.mark.asyncio
async def test_issue_list_without_state_uses_list_item_shape(tmp_path: Path) -> None:
    """``gh issue list --json number,title`` must not fail on missing ``state``."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number,title"],
        stdout=json.dumps([{"number": 1, "title": "fix: something"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_view_with_state_uses_summary_shape(tmp_path: Path) -> None:
    """``gh issue view N --json number,state`` validates against GhIssueSummary."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "1", "--json", "number,state"],
        stdout=json.dumps({"number": 1, "state": "OPEN"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_ignores_extra_fields(tmp_path: Path) -> None:
    """GhIssueListItem uses extra='ignore' so unexpected extra fields don't drift."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number,title,state"],
        stdout=json.dumps([{"number": 1, "title": "t", "state": "OPEN"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Pattern 2: --jq transforms ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_jq_transform_skipped(tmp_path: Path) -> None:
    """``gh pr list --json number --jq length`` produces non-JSON; skip."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number", "--jq", "length"],
        stdout="5\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_jq_transform_on_issue_list_skipped(tmp_path: Path) -> None:
    """``gh issue list --json number --jq '.[].number'`` produces scalar output."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "number", "--jq", ".[].number"],
        stdout="1\n2\n3\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Pattern 3: comments-only and narrow views ─────────────────────────────────


@pytest.mark.asyncio
async def test_issue_view_comments_only_skipped(tmp_path: Path) -> None:
    """``gh issue view N --json comments`` has no fields matching any shape."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "1", "--json", "comments"],
        stdout=json.dumps({"comments": []}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Pattern 4: projection-only PR calls ──────────────────────────────────────


@pytest.mark.asyncio
async def test_pr_view_commits_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json commits`` omits all required summary/detail fields."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "1", "--json", "commits"],
        stdout=json.dumps({"commits": []}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_reviews_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json reviews`` omits all required fields."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "1", "--json", "reviews"],
        stdout=json.dumps({"reviews": []}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_view_head_ref_oid_only_skipped(tmp_path: Path) -> None:
    """``gh pr view N --json headRefOid`` is a detail signal but omits ``number``."""
    sample = _sample(
        tmp_path,
        args=["pr", "view", "1", "--json", "headRefOid"],
        stdout=json.dumps({"headRefOid": "abc123"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_list_partial_fields_skipped(tmp_path: Path) -> None:
    """``gh pr list --json number,labels,body,commits`` omits title and state."""
    sample = _sample(
        tmp_path,
        args=["pr", "list", "--json", "number,labels,body,commits"],
        stdout=json.dumps([{"number": 1, "labels": [], "body": "", "commits": []}])
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Pattern 5: projection-only issue calls ────────────────────────────────────


@pytest.mark.asyncio
async def test_issue_view_state_reason_only_skipped(tmp_path: Path) -> None:
    """``gh issue view N --json state,stateReason`` omits ``number``."""
    sample = _sample(
        tmp_path,
        args=["issue", "view", "1", "--json", "state,stateReason"],
        stdout=json.dumps({"state": "CLOSED", "stateReason": "completed"}) + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Pattern 6: narrow pr-checks and issue-list ───────────────────────────────


@pytest.mark.asyncio
async def test_pr_checks_conclusion_only_skipped(tmp_path: Path) -> None:
    """``gh pr checks --json conclusion`` omits ``name`` required by GhCheckRun."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "conclusion"],
        stdout=json.dumps([{"conclusion": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_state_only_skipped(tmp_path: Path) -> None:
    """``gh pr checks --json state`` omits ``name``."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "state"],
        stdout=json.dumps([{"state": "COMPLETED"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_issue_list_date_only_skipped(tmp_path: Path) -> None:
    """``gh issue list --json createdAt,closedAt`` omits number+title."""
    sample = _sample(
        tmp_path,
        args=["issue", "list", "--json", "createdAt,closedAt"],
        stdout=json.dumps([{"createdAt": "2026-06-01T00:00:00Z", "closedAt": None}])
        + "\n",
    )
    assert await gh_shape_validator(sample) is None


# ── Pattern 7: terminal check-run states ─────────────────────────────────────


@pytest.mark.asyncio
async def test_pr_checks_success_state_validates(tmp_path: Path) -> None:
    """``gh pr checks --json name,state`` returning ``state=SUCCESS`` must pass."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci/test", "state": "SUCCESS"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_failure_state_validates(tmp_path: Path) -> None:
    """``state=FAILURE`` is a terminal value that must be accepted."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci/lint", "state": "FAILURE"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_skipped_state_validates(tmp_path: Path) -> None:
    """``state=SKIPPED`` is a terminal value that must be accepted."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci/deploy", "state": "SKIPPED"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_cancelled_state_validates(tmp_path: Path) -> None:
    """``state=CANCELLED`` is a terminal value that must be accepted."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci/build", "state": "CANCELLED"}]) + "\n",
    )
    assert await gh_shape_validator(sample) is None


@pytest.mark.asyncio
async def test_pr_checks_unknown_state_fails(tmp_path: Path) -> None:
    """An unrecognised check state still triggers drift detection."""
    sample = _sample(
        tmp_path,
        args=["pr", "checks", "1", "--json", "name,state"],
        stdout=json.dumps([{"name": "ci/test", "state": "BRAND_NEW_STATE"}]) + "\n",
    )
    result = await gh_shape_validator(sample)
    assert result is not None
    assert result["shape_validation_failed"] is True


# ── Pattern 8: escalation dedup ──────────────────────────────────────────────


def test_escalation_dedup_key_stable() -> None:
    """Same signature list always produces same escalation key."""
    sigs = ["abc123", "def456"]
    assert _escalation_dedup_key(sigs) == _escalation_dedup_key(sigs)


def test_escalation_dedup_key_order_independent() -> None:
    """Key is independent of signature list order."""
    assert _escalation_dedup_key(["a", "b"]) == _escalation_dedup_key(["b", "a"])


def test_escalation_dedup_key_prefixed() -> None:
    """Escalation key starts with 'esc:' to distinguish from drift keys."""
    key = _escalation_dedup_key(["sig1"])
    assert key.startswith("esc:")


def test_escalation_dedup_key_differs_from_fleet_key() -> None:
    """Escalation key must differ from fleet drift dedup key for same sigs."""
    from pathlib import Path as P

    sigs = ["abc123fullhex"]
    esc_key = _escalation_dedup_key(sigs)
    fleet_key = _fleet_dedup_key([(P("x.yaml"), s) for s in sigs])
    assert esc_key != fleet_key


def test_escalation_dedup_key_persists_in_store(tmp_path: Path) -> None:
    """Escalation dedup key written to DedupStore survives a get() round-trip."""
    from dedup_store import DedupStore

    dedup = DedupStore("live_corpus_replay", tmp_path / "dedup.json")
    sigs = ["deadbeef" * 8]
    esc_key = _escalation_dedup_key(sigs)

    seen = dedup.get()
    seen.add(esc_key)
    dedup.set_all(seen)

    assert esc_key in dedup.get()
