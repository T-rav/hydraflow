"""Unit tests for the complexity-tiered implement timeout (#11568)."""

from __future__ import annotations

import pytest

from implement_timeout import (
    IMPLEMENT_TIMEOUT_TIERS,
    MIN_IMPLEMENT_TIMEOUT_S,
    tiered_implement_timeout,
)

CEILING = 3600


class TestTierTable:
    @pytest.mark.parametrize("complexity", [None, 0])
    def test_unknown_complexity_gets_the_full_ceiling(self, complexity) -> None:
        assert tiered_implement_timeout(complexity, CEILING) == CEILING

    @pytest.mark.parametrize("complexity", [1, 2])
    def test_tier_one_and_two_get_half_the_ceiling(self, complexity: int) -> None:
        assert tiered_implement_timeout(complexity, CEILING) == 1800

    @pytest.mark.parametrize("complexity", [3, 4])
    def test_tier_three_and_four_get_three_quarters(self, complexity: int) -> None:
        assert tiered_implement_timeout(complexity, CEILING) == 2700

    @pytest.mark.parametrize("complexity", [5, 6, 7, 8, 9, 10])
    def test_tier_five_and_up_get_the_full_ceiling(self, complexity: int) -> None:
        assert tiered_implement_timeout(complexity, CEILING) == CEILING

    def test_table_is_sorted_by_upper_bound(self) -> None:
        uppers = [upper for upper, _ in IMPLEMENT_TIMEOUT_TIERS]
        assert uppers == sorted(uppers)

    def test_table_fractions_are_strictly_below_one(self) -> None:
        assert all(0 < fraction < 1 for _, fraction in IMPLEMENT_TIMEOUT_TIERS)


class TestBounds:
    @pytest.mark.parametrize("complexity", [None, 0, 1, 2, 3, 4, 5, 10])
    @pytest.mark.parametrize("ceiling", [60, 600, 3600, 14400])
    def test_never_exceeds_the_ceiling(self, complexity, ceiling: int) -> None:
        assert tiered_implement_timeout(complexity, ceiling) <= ceiling

    def test_never_drops_below_the_floor_when_ceiling_allows(self) -> None:
        # A 100s ceiling halved would be 50s — below the config floor of 60s.
        assert tiered_implement_timeout(1, 100) == MIN_IMPLEMENT_TIMEOUT_S

    def test_floor_never_pushes_above_a_tiny_ceiling(self) -> None:
        assert tiered_implement_timeout(1, 60) == 60

    def test_returns_an_int(self) -> None:
        assert isinstance(tiered_implement_timeout(3, 1000), int)

    def test_negative_complexity_reads_as_unknown(self) -> None:
        assert tiered_implement_timeout(-1, CEILING) == CEILING
