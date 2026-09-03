"""#11970 — the unsticker merged anything that went green.

`_wait_and_merge` waits for CI and then presents the operator-enabled
`unstick_auto_merge` config grant to `enforce_merge_policy` as an
operator-role approval. That grant is a statement about the LANE — "the
factory may unstick itself" — while the PR is somebody else's work.

Nothing caught it because the packaged `policy.yaml` declares `paths: []` and
`labels: []` on every class. `MergePolicy.has_change_matchers` is therefore
False, the gate never fetches the diff, and `classify_change` returns the
`default: true` class: `tractable-reversible`, `autonomy: act`, no approvals
required. `high-blast-radius`, the only class carrying `required_approvals`,
cannot match anything and never fires. Green CI was the entire test.

These pin the LANE's own scope. Giving `high-blast-radius` real matchers would
change what every merge lane in the factory requires, which is a throughput
decision for the operator rather than a side effect of repairing one loop —
recorded on #11970 and deliberately not done here.
"""

from __future__ import annotations

import pytest

from pr_unsticker._scope import OUT_OF_SCOPE_PREFIXES, out_of_scope


class TestWhatAStandingGrantCannotSpeakFor:
    @pytest.mark.parametrize(
        "path",
        [
            pytest.param("docs/adr/0143-paaa.md", id="adr"),
            pytest.param("docs/standards/testing/README.md", id="standard"),
            pytest.param("control/principles.yaml", id="control-plane"),
            pytest.param(".github/workflows/ci.yml", id="ci-gate"),
            # #12116 moved the act-vs-ask policy into `charter.yaml`. Before
            # that it lived under `docs/standards/`, which this list already
            # covered — so the rules the standing grant must not speak for
            # walked out from behind the guard when they were relocated, and a
            # bare top-level filename matches none of the directory prefixes.
            pytest.param("charter.yaml", id="governing-declaration"),
        ],
    )
    def test_a_change_to_the_rules_is_out_of_scope(self, path: str) -> None:
        assert out_of_scope([path]) == [path]

    @pytest.mark.parametrize("prefix", OUT_OF_SCOPE_PREFIXES)
    def test_every_declared_prefix_actually_excludes_something(
        self, prefix: str
    ) -> None:
        """Swept over the live tuple, not over the four cases above.

        The named cases are a hand-kept copy of `OUT_OF_SCOPE_PREFIXES`, and a
        fifth prefix added without a case beside it would be covered by
        nothing. Directory prefixes need a file under them; a bare filename is
        already a path.
        """
        path = f"{prefix}x.md" if prefix.endswith("/") else prefix

        assert out_of_scope([path]) == [path]

    def test_ordinary_source_and_tests_stay_in_scope(self) -> None:
        # The decoy that matters. A scope this lane cannot merge ANYTHING under
        # would satisfy every test above while disabling the unsticker — the
        # loop exists to unwedge mechanical failures.
        assert out_of_scope(["src/foo.py", "tests/test_foo.py", "README.md"]) == []

    def test_a_mixed_pr_is_named_by_its_governance_paths(self) -> None:
        # The message has to name what blocked it; "out of scope" alone makes a
        # human re-derive what the check already knows.
        assert out_of_scope(["src/foo.py", "docs/adr/0001-x.md"]) == [
            "docs/adr/0001-x.md"
        ]

    def test_a_prefix_lookalike_is_not_in_scope(self) -> None:
        # `docs/adrs-notes/` is not `docs/adr/`. A substring match here would
        # quietly widen the lane's refusal set.
        assert out_of_scope(["docs/adrs-notes/x.md", "controllers/y.py"]) == []

    def test_the_prefix_set_is_not_empty(self) -> None:
        """Anti-vacuity: an empty prefix set makes every assertion above pass.

        That is precisely the shape of the defect being fixed — `paths: []` in
        the packaged policy is why `high-blast-radius` never fires.
        """
        assert OUT_OF_SCOPE_PREFIXES


class TestTheLaneFailsClosed:
    @pytest.mark.asyncio
    async def test_an_unreadable_diff_blocks_the_merge(self, tmp_path) -> None:
        """Not seeing the change is not evidence that it is mechanical."""
        from unittest.mock import AsyncMock, MagicMock

        from pr_unsticker._merge import PRUnstickerMergeMixin

        mixin = MagicMock(spec=PRUnstickerMergeMixin)
        mixin._prs = MagicMock()
        mixin._prs.get_pr_diff_names = AsyncMock(side_effect=RuntimeError("gh down"))

        reason = await PRUnstickerMergeMixin._outside_standing_grant(mixin, 42)

        assert reason is not None
        assert "diff" in reason

    @pytest.mark.asyncio
    async def test_a_mechanical_pr_is_not_blocked(self, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from pr_unsticker._merge import PRUnstickerMergeMixin

        mixin = MagicMock(spec=PRUnstickerMergeMixin)
        mixin._prs = MagicMock()
        mixin._prs.get_pr_diff_names = AsyncMock(return_value=["src/foo.py"])

        assert await PRUnstickerMergeMixin._outside_standing_grant(mixin, 42) is None

    @pytest.mark.asyncio
    async def test_a_governance_pr_is_blocked_and_named(self, tmp_path) -> None:
        from unittest.mock import AsyncMock, MagicMock

        from pr_unsticker._merge import PRUnstickerMergeMixin

        mixin = MagicMock(spec=PRUnstickerMergeMixin)
        mixin._prs = MagicMock()
        mixin._prs.get_pr_diff_names = AsyncMock(
            return_value=["src/foo.py", "docs/standards/testing/README.md"]
        )

        reason = await PRUnstickerMergeMixin._outside_standing_grant(mixin, 42)

        assert reason is not None
        assert "docs/standards/testing/README.md" in reason


class TestTheMergePathActuallyConsultsIt:
    """The call site, not just the predicate.

    A first pass pinned `_outside_standing_grant` alone, and deleting its call
    from `_wait_and_merge` kept every test green — the helper was correct and
    unreached. The defect is a PR getting MERGED, so that is what these assert.
    """

    @staticmethod
    async def _merge(tmp_path, *, changed: list[str]):
        from unittest.mock import AsyncMock

        from tests.test_pr_unsticker import _make_hitl_item, _make_unsticker

        harness = _make_unsticker(tmp_path)
        harness.prs.wait_for_ci = AsyncMock(return_value=(True, "green"))
        harness.prs.get_pr_diff_names = AsyncMock(return_value=changed)
        harness.prs.merge_pr = AsyncMock(return_value=True)
        harness.prs.get_pr_diff_stats = AsyncMock(return_value={})
        item = _make_hitl_item(issue=42, pr=99)

        merged = await harness.unsticker._wait_and_merge(item)
        return merged, harness

    @pytest.mark.asyncio
    async def test_a_governance_pr_is_not_merged(self, tmp_path) -> None:
        merged, harness = await self._merge(
            tmp_path, changed=["docs/adr/0143-paaa.md"]
        )

        assert merged is False
        harness.prs.merge_pr.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_mechanical_pr_still_merges(self, tmp_path) -> None:
        # The decoy. A lane that merged nothing would pass the test above and
        # silently disable the unsticker.
        merged, harness = await self._merge(tmp_path, changed=["src/foo.py"])

        assert merged is True
        harness.prs.merge_pr.assert_awaited_once()
