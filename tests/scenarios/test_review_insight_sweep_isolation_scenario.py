"""One failing proposal must not cost the others their escalation.

#6580's unit pins assert on the list `verify_proposals` RETURNS. This drives
the real function through `RetrospectiveLoop` against FakeGitHub and asserts
on what the factory actually receives — the routed `[Review Insight]` issues.
That is the part a unit test cannot see: before the per-category isolation,
one store write raising mid-sweep meant every later stale category was never
classified, so its issue was silently never filed and the loop reported a
smaller `stale_proposals` count with no error anywhere.

`verify_proposals` is deliberately NOT patched here (the sibling scenario in
test_caretaker_loops.py stubs it, which is right for testing dedup and wrong
for testing the sweep itself). Only `update_proposal_verified` is patched, to
fail for exactly one category — #6580's own trigger.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.loop_port_seeding import seed_ports as _seed_ports

pytestmark = pytest.mark.scenario_loops

_STALE_DAYS = 30


def _seed_store(tmp_path):
    """A store with three proposals: stale, verify-and-fail, stale.

    ``bbb`` sits BETWEEN the two stale entries and takes the
    ``update_proposal_verified`` branch (its count more than halved). With
    that write raising and no isolation, the sweep dies on ``bbb`` and
    ``ccc`` — behind it in iteration order — is never reached.
    """
    from models import ReviewVerdict  # noqa: PLC0415
    from review_insights import ReviewInsightStore, ReviewRecord  # noqa: PLC0415

    store = ReviewInsightStore(tmp_path / "memory")
    store.record_proposal("aaa", pre_count=3)
    store.record_proposal("bbb", pre_count=10)
    store.record_proposal("ccc", pre_count=3)

    meta = store.load_proposal_metadata()
    assert list(meta) == ["aaa", "bbb", "ccc"], (
        f"iteration order is load-bearing for this scenario, got {list(meta)}"
    )
    old = (datetime.now(UTC) - timedelta(days=_STALE_DAYS + 10)).isoformat()
    for entry in meta.values():
        entry.proposed_at = old
    store.save_proposal_metadata(meta)

    def _rec(category: str) -> ReviewRecord:
        return ReviewRecord(
            pr_number=1,
            issue_number=1,
            timestamp="2026-02-20T10:30:00Z",
            verdict=ReviewVerdict.REQUEST_CHANGES,
            summary="s",
            fixes_made=False,
            categories=[category],
        )

    # aaa and ccc hold at 3 (stale); bbb drops 10 -> 1 (verifies).
    records = [_rec("aaa")] * 3 + [_rec("ccc")] * 3 + [_rec("bbb")]
    for r in records:
        store.append_review(r)
    return store, records


async def test_one_failing_proposal_does_not_cost_the_others_their_issue(
    tmp_path,
) -> None:
    """Both stale categories reach GitHub even though the middle one raises."""
    from retrospective_queue import QueueItem, QueueKind  # noqa: PLC0415

    store, records = _seed_store(tmp_path)

    world = MockWorld(tmp_path)
    fake_queue = MagicMock()
    fake_queue.load.return_value = [QueueItem(kind=QueueKind.VERIFY_PROPOSALS)]
    fake_queue.acknowledge = MagicMock()

    insights = MagicMock(wraps=store)
    insights.load_recent.return_value = records
    insights.load_proposal_metadata.side_effect = store.load_proposal_metadata
    insights.get_proposed_categories.return_value = set()

    def _explode(category: str, *, verified: bool) -> None:
        if category == "bbb":
            msg = "simulated store failure for one proposal"
            raise RuntimeError(msg)
        store.update_proposal_verified(category, verified=verified)

    insights.update_proposal_verified.side_effect = _explode

    _seed_ports(world, retrospective_queue=fake_queue, insights=insights)

    descriptions = {"aaa": "Category AAA", "bbb": "Category BBB", "ccc": "Category CCC"}
    with (
        patch("review_insights.CATEGORY_DESCRIPTIONS", descriptions),
        patch("review_insights._PROPOSAL_STALE_DAYS", _STALE_DAYS),
    ):
        await world.run_with_loops(["retrospective"], cycles=1)

    titles = [i.title for i in world._github._issues.values()]
    filed = sorted(t for t in titles if "Review Insight" in t)

    assert any("Category AAA" in t for t in filed), (
        f"the category BEFORE the failing one should have filed; got {filed}"
    )
    assert any("Category CCC" in t for t in filed), (
        "the category AFTER the failing one should have filed too — its "
        f"escalation is what the aborted sweep used to swallow. Got {filed}"
    )
    assert not any("Category BBB" in t for t in filed), (
        f"the failing category verifies rather than going stale; got {filed}"
    )
