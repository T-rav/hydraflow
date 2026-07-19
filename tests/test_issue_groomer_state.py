"""Config knobs + GroomState persistence for IssueGroomerLoop (spec #9957).

Covers: config defaults + bounds (env-table byte-equality is enforced by the
shared ``test_config_consistency.py`` guard), StateData round-trips, the
judged-pair cache's dedupe + newest-5000-cap prune, and the
naive-stored-timestamp -> tz-aware-UTC hardening on ``groom_last_full_sweep``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from config import HydraFlowConfig
from state import StateTracker


def _tracker(tmp_path: Path) -> StateTracker:
    return StateTracker(state_file=tmp_path / "state.json")


# ---------------------------------------------------------------------------
# Config defaults
# ---------------------------------------------------------------------------


class TestIssueGroomerConfigDefaults:
    def test_defaults(self) -> None:
        cfg = HydraFlowConfig()
        assert cfg.issue_groomer_enabled is True
        assert cfg.issue_groomer_interval == 86400
        assert cfg.issue_groomer_full_sweep_interval == 604800
        assert cfg.issue_groomer_pair_budget == 24
        assert cfg.issue_groomer_model == ""


class TestIssueGroomerConfigBounds:
    def test_pair_budget_accepts_lower_bound(self) -> None:
        cfg = HydraFlowConfig(repo="test/repo", issue_groomer_pair_budget=0)
        assert cfg.issue_groomer_pair_budget == 0

    def test_pair_budget_accepts_upper_bound(self) -> None:
        cfg = HydraFlowConfig(repo="test/repo", issue_groomer_pair_budget=200)
        assert cfg.issue_groomer_pair_budget == 200

    def test_pair_budget_rejects_below_minimum(self) -> None:
        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", issue_groomer_pair_budget=-1)

    def test_pair_budget_rejects_above_maximum(self) -> None:
        with pytest.raises(ValidationError):
            HydraFlowConfig(repo="test/repo", issue_groomer_pair_budget=201)


class TestIssueGroomerConfigEnvOverrides:
    def test_enabled_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HYDRAFLOW_ISSUE_GROOMER_ENABLED", "false")
        assert HydraFlowConfig().issue_groomer_enabled is False

    def test_interval_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HYDRAFLOW_ISSUE_GROOMER_INTERVAL", "43200")
        assert HydraFlowConfig().issue_groomer_interval == 43200

    def test_full_sweep_interval_env_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("HYDRAFLOW_ISSUE_GROOMER_FULL_SWEEP_INTERVAL", "259200")
        assert HydraFlowConfig().issue_groomer_full_sweep_interval == 259200

    def test_pair_budget_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HYDRAFLOW_ISSUE_GROOMER_PAIR_BUDGET", "10")
        assert HydraFlowConfig().issue_groomer_pair_budget == 10

    def test_model_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HYDRAFLOW_ISSUE_GROOMER_MODEL", "sonnet")
        assert HydraFlowConfig().issue_groomer_model == "sonnet"


# ---------------------------------------------------------------------------
# GroomState — change-detection index
# ---------------------------------------------------------------------------


class TestGroomIndex:
    def test_defaults_empty(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        assert st.get_groom_index() == {}

    def test_roundtrip(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        index = {
            "9957": {
                "title_hash": "abc123",
                "body_hash": "def456",
                "updated_at": "2026-07-19T00:00:00Z",
            }
        }
        st.set_groom_index(index)
        assert st.get_groom_index() == index

    def test_get_returns_a_copy(self, tmp_path: Path) -> None:
        """Mutating the returned dict must not leak back into state."""
        st = _tracker(tmp_path)
        st.set_groom_index(
            {"1": {"title_hash": "a", "body_hash": "b", "updated_at": "x"}}
        )
        snapshot = st.get_groom_index()
        snapshot["1"]["title_hash"] = "mutated"
        assert st.get_groom_index()["1"]["title_hash"] == "a"


# ---------------------------------------------------------------------------
# GroomState — judged-pair cache
# ---------------------------------------------------------------------------


class TestJudgedPairs:
    def test_defaults_empty(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        assert st.get_judged_pairs() == []

    def test_add_appends(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        st.add_judged_pairs(["1:2:aaa:bbb"])
        st.add_judged_pairs(["3:4:ccc:ddd"])
        assert st.get_judged_pairs() == ["1:2:aaa:bbb", "3:4:ccc:ddd"]

    def test_add_dedupes_existing_keys(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        st.add_judged_pairs(["1:2:aaa:bbb", "3:4:ccc:ddd"])
        st.add_judged_pairs(["1:2:aaa:bbb", "5:6:eee:fff"])
        assert st.get_judged_pairs() == [
            "1:2:aaa:bbb",
            "3:4:ccc:ddd",
            "5:6:eee:fff",
        ]

    def test_add_dedupes_within_a_single_call(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        st.add_judged_pairs(["1:2:aaa:bbb", "1:2:aaa:bbb"])
        assert st.get_judged_pairs() == ["1:2:aaa:bbb"]

    def test_prunes_to_newest_5000_keeping_insertion_order(
        self, tmp_path: Path
    ) -> None:
        st = _tracker(tmp_path)
        keys = [f"{n}:{n + 1}:h{n}:h{n + 1}" for n in range(5005)]
        st.add_judged_pairs(keys)
        kept = st.get_judged_pairs()
        assert len(kept) == 5000
        # The oldest 5 were dropped; the remainder keeps its original order.
        assert kept == keys[5:]

    def test_prune_applies_across_multiple_calls(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        first_batch = [f"a{n}:a{n + 1}:h{n}:h{n + 1}" for n in range(4998)]
        st.add_judged_pairs(first_batch)
        second_batch = [f"b{n}:b{n + 1}:h{n}:h{n + 1}" for n in range(10)]
        st.add_judged_pairs(second_batch)
        kept = st.get_judged_pairs()
        assert len(kept) == 5000
        # All 10 newest entries survive; the oldest 8 of the first batch don't.
        assert kept[-10:] == second_batch
        assert kept == (first_batch + second_batch)[-5000:]


# ---------------------------------------------------------------------------
# GroomState — weekly full-sweep marker
# ---------------------------------------------------------------------------


class TestLastFullSweep:
    def test_defaults_none(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        assert st.get_groom_last_full_sweep() is None

    def test_roundtrip_is_tz_aware(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        now = datetime.now(UTC)
        st.set_groom_last_full_sweep(now)
        result = st.get_groom_last_full_sweep()
        assert result is not None
        assert result.tzinfo is not None
        assert result == now

    def test_naive_stored_value_assumed_utc(self, tmp_path: Path) -> None:
        """A pre-hardening/legacy naive timestamp must not raise and must
        come back tz-aware (assumed UTC), comparable against an aware now."""
        st = _tracker(tmp_path)
        st._data.groom_last_full_sweep = "2026-07-12T00:00:00"
        result = st.get_groom_last_full_sweep()
        assert result is not None
        assert result.tzinfo is not None
        # Comparable against an aware "now" without raising TypeError.
        assert datetime.now(UTC) - result > timedelta(days=1)

    def test_unparseable_value_returns_none(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        st._data.groom_last_full_sweep = "not-a-timestamp"
        assert st.get_groom_last_full_sweep() is None


# ---------------------------------------------------------------------------
# GroomState — rolling digest issue
# ---------------------------------------------------------------------------


class TestDigestIssue:
    def test_default_is_zero(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        assert st.get_groom_digest_issue() == 0

    def test_roundtrip(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        st.set_groom_digest_issue(9958)
        assert st.get_groom_digest_issue() == 9958


# ---------------------------------------------------------------------------
# GroomState — open operator proposals (carried across ticks)
# ---------------------------------------------------------------------------


class TestOpenProposals:
    def test_defaults_empty(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        assert st.get_groom_open_proposals() == []

    def test_roundtrip(self, tmp_path: Path) -> None:
        st = _tracker(tmp_path)
        proposals = [
            {
                "kind": "dup",
                "a": 101,
                "b": 102,
                "canonical": 101,
                "verdict": "likely_dup",
                "confidence": "medium",
                "evidence": "same reap site",
                "first_seen": "2026-07-19T00:00:00+00:00",
            }
        ]
        st.set_groom_open_proposals(proposals)
        assert st.get_groom_open_proposals() == proposals

    def test_get_returns_a_copy(self, tmp_path: Path) -> None:
        """Mutating the returned list's entries must not leak back into state."""
        st = _tracker(tmp_path)
        st.set_groom_open_proposals([{"kind": "priority", "number": 7}])
        snapshot = st.get_groom_open_proposals()
        snapshot[0]["number"] = 999
        assert st.get_groom_open_proposals()[0]["number"] == 7
