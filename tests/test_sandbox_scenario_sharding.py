"""Sharding for `sandbox_scenario.py run-all --shard I/N`.

The RC sandbox suite (71 scenarios) ran sequentially in one job. Sharding fans
it across N parallel matrix jobs. The load-bearing invariant: the shards must
PARTITION the suite — every scenario runs in exactly one shard, none dropped,
none double-run — or the RC gate would silently skip coverage.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.sandbox_scenario import _parse_shard, _select_shard


class TestParseShard:
    def test_none_and_empty_are_unsharded(self) -> None:
        assert _parse_shard(None) is None
        assert _parse_shard("") is None

    def test_valid_spec_is_zero_indexed(self) -> None:
        assert _parse_shard("1/6") == (0, 6)
        assert _parse_shard("6/6") == (5, 6)

    @pytest.mark.parametrize("bad", ["0/6", "7/6", "3", "1/0", "-1/6"])
    def test_invalid_specs_raise(self, bad: str) -> None:
        with pytest.raises(ValueError):
            _parse_shard(bad)


class TestSelectShard:
    def test_unsharded_returns_everything(self) -> None:
        items = list(range(71))
        assert _select_shard(items, None) == items

    def test_single_shard_returns_everything(self) -> None:
        items = list(range(71))
        assert _select_shard(items, "1/1") == items

    @pytest.mark.parametrize("count", [2, 3, 4, 6, 8])
    def test_shards_partition_the_suite(self, count: int) -> None:
        items = [f"s{n:02d}" for n in range(71)]
        seen: list[str] = []
        for shard in range(1, count + 1):
            seen.extend(_select_shard(items, f"{shard}/{count}"))
        # Every scenario exactly once, none dropped, none duplicated.
        assert sorted(seen) == sorted(items)
        assert len(seen) == len(items)

    def test_shards_are_balanced(self) -> None:
        items = list(range(71))
        sizes = [len(_select_shard(items, f"{i}/6")) for i in range(1, 7)]
        # 71 / 6 -> sizes differ by at most 1 (round-robin stripe).
        assert max(sizes) - min(sizes) <= 1

    def test_deterministic(self) -> None:
        items = [f"s{n:02d}" for n in range(71)]
        assert _select_shard(items, "3/6") == _select_shard(items, "3/6")
