"""Tests for the #10788 timeline diff-stat payload fields.

``PRDiffStats`` plus the optional ``commit_sha`` / ``files_changed`` /
``additions`` / ``deletions`` keys added to ``PRCreatedPayload`` and
``MergeUpdatePayload``. TypedDicts don't validate at runtime, so these pin
the declared contract (optional keys, round-trip) the operator timeline and
the ``PRManager`` emit sites rely on.
"""

from __future__ import annotations

from models import MergeUpdatePayload, PRCreatedPayload, PRDiffStats

_DIFF_KEYS = {"commit_sha", "files_changed", "additions", "deletions"}


class TestPRDiffStats:
    def test_accepts_all_stat_fields(self) -> None:
        stats = PRDiffStats(
            commit_sha="deadbeef",
            files_changed=3,
            additions=10,
            deletions=2,
        )
        assert dict(stats) == {
            "commit_sha": "deadbeef",
            "files_changed": 3,
            "additions": 10,
            "deletions": 2,
        }

    def test_all_keys_are_optional(self) -> None:
        # total=False: an empty PRDiffStats is valid — that's the degraded
        # (failed / dry-run read) shape the emit sites merge as a no-op.
        assert PRDiffStats.__optional_keys__ == frozenset(_DIFF_KEYS)
        assert PRDiffStats.__required_keys__ == frozenset()
        assert dict(PRDiffStats()) == {}

    def test_partial_stats_round_trip(self) -> None:
        # A reply missing changedFiles/additions/deletions still carries sha.
        stats = PRDiffStats(commit_sha="abc123")
        assert dict(stats) == {"commit_sha": "abc123"}


class TestPRCreatedPayloadDiffFields:
    def test_diff_keys_are_declared_optional(self) -> None:
        assert PRCreatedPayload.__optional_keys__ >= _DIFF_KEYS

    def test_round_trips_base_plus_diff_fields(self) -> None:
        payload = PRCreatedPayload(
            pr=55,
            issue=42,
            branch="agent/issue-42",
            draft=False,
            url="https://example/pull/55",
            title="feat: x",
            commit_sha="headsha",
            files_changed=4,
            additions=20,
            deletions=1,
        )
        assert payload["commit_sha"] == "headsha"
        assert payload["files_changed"] == 4
        assert payload["additions"] == 20
        assert payload["deletions"] == 1
        # Base fields are untouched and coexist with the new keys.
        assert payload["pr"] == 55
        assert payload["issue"] == 42

    def test_base_only_payload_omits_diff_keys(self) -> None:
        payload = PRCreatedPayload(pr=1, issue=2, branch="b", url="u")
        assert _DIFF_KEYS.isdisjoint(payload.keys())


class TestMergeUpdatePayloadDiffFields:
    def test_diff_keys_are_declared_optional(self) -> None:
        assert MergeUpdatePayload.__optional_keys__ >= _DIFF_KEYS

    def test_round_trips_base_plus_diff_fields(self) -> None:
        payload = MergeUpdatePayload(
            pr=101,
            status="merged",
            title="Fixes #42",
            issue=42,
            commit_sha="mergesha",
            files_changed=3,
            additions=10,
            deletions=2,
        )
        assert payload["commit_sha"] == "mergesha"
        assert payload["files_changed"] == 3
        assert payload["additions"] == 10
        assert payload["deletions"] == 2
        assert payload["status"] == "merged"

    def test_base_only_payload_omits_diff_keys(self) -> None:
        payload = MergeUpdatePayload(pr=101, status="merged")
        assert _DIFF_KEYS.isdisjoint(payload.keys())
