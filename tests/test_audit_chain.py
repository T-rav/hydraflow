"""Unit tests for the hash-chained append-only audit stream helper (CH-1, #9729)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from audit_chain import (
    GENESIS_PREV_HASH,
    AuditChain,
    audit_streams,
    canonical_json,
    compute_record_hash,
    verify_file,
)
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stream(tmp_path: Path) -> AuditChain:
    return AuditChain(tmp_path / "stream.jsonl")


def _read_lines(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_lines(path: Path, rows: list[dict[str, object]]) -> None:
    path.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Canonicalization
# ---------------------------------------------------------------------------


class TestCanonicalization:
    def test_canonical_json_is_key_order_independent(self) -> None:
        a = canonical_json({"x": 1, "y": {"b": 2, "a": 3}})
        b = canonical_json({"y": {"a": 3, "b": 2}, "x": 1})
        assert a == b

    def test_canonical_json_golden_pin(self) -> None:
        """Pin the exact canonical form so serialization drift breaks loudly.

        Historical chains are only verifiable while canonicalization is
        byte-stable; any change to separators/sort/ascii handling must fail here.
        """
        payload = {
            "b": 1,
            "a": "ü",
            "nested": {"y": 2, "x": [1, 2.5, None, True]},
            "msg": "hello",
        }
        assert (
            canonical_json(payload)
            == '{"a":"ü","b":1,"msg":"hello","nested":{"x":[1,2.5,null,true],"y":2}}'
        )

    def test_compute_record_hash_golden_pin(self) -> None:
        payload = {
            "b": 1,
            "a": "ü",
            "nested": {"y": 2, "x": [1, 2.5, None, True]},
            "msg": "hello",
        }
        assert (
            compute_record_hash(payload, GENESIS_PREV_HASH)
            == "e1c9ec35107078f4280c3dda5230f5251fce80efb38cf8b6b9e9e6ec6156ff61"
        )

    def test_canonical_json_rejects_nan(self) -> None:
        with pytest.raises(ValueError):
            canonical_json({"x": float("nan")})


# ---------------------------------------------------------------------------
# Append
# ---------------------------------------------------------------------------


class TestAppend:
    def test_first_append_starts_at_genesis(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        written = chain.append({"event": "start", "n": 1})
        assert written["prev_hash"] == GENESIS_PREV_HASH
        assert written["record_hash"] == compute_record_hash(
            {"event": "start", "n": 1}, GENESIS_PREV_HASH
        )
        rows = _read_lines(chain.path)
        assert rows == [written]

    def test_appends_link_prev_hash_to_prior_record_hash(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        first = chain.append({"n": 1})
        second = chain.append({"n": 2})
        assert second["prev_hash"] == first["record_hash"]

    def test_append_preserves_payload_schema(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        payload = {"ts": "2026-07-08T00:00:00Z", "issue": 5, "cost_usd": 1.25}
        chain.append(payload)
        (row,) = _read_lines(chain.path)
        for key, value in payload.items():
            assert row[key] == value
        assert set(row) == set(payload) | {"prev_hash", "record_hash"}

    def test_append_rejects_reserved_hash_fields(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        with pytest.raises(ValueError, match="record_hash"):
            chain.append({"n": 1, "record_hash": "boom"})

    def test_append_after_unchained_prefix_starts_at_genesis(
        self, tmp_path: Path
    ) -> None:
        """Adoption baseline: pre-existing unchained rows are not retrofitted."""
        path = tmp_path / "stream.jsonl"
        _write_lines(path, [{"legacy": 1}, {"legacy": 2}])
        chain = AuditChain(path)
        written = chain.append({"n": 3})
        assert written["prev_hash"] == GENESIS_PREV_HASH
        assert chain.verify().ok

    def test_append_scrubs_secrets_before_hashing(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        token = "ghp_" + "a" * 40
        chain.append({"transcript": f"leaked {token} oops"})
        (row,) = _read_lines(chain.path)
        assert token not in json.dumps(row)
        assert "[REDACTED:" in str(row["transcript"])
        # The hash must cover the scrubbed content, so the chain still verifies.
        assert chain.verify().ok


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------


class TestVerify:
    def test_missing_file_is_ok_and_empty(self, tmp_path: Path) -> None:
        result = verify_file(tmp_path / "absent.jsonl")
        assert result.ok
        assert result.total_records == 0
        assert result.chained_records == 0

    def test_green_chain_verifies(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        for n in range(3):
            last = chain.append({"n": n})
        result = chain.verify()
        assert result.ok
        assert result.chained_records == 3
        assert result.head == last["record_hash"]

    def test_tampered_field_is_detected(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        chain.append({"n": 1, "cost_usd": 1.0})
        chain.append({"n": 2, "cost_usd": 2.0})
        rows = _read_lines(chain.path)
        rows[0]["cost_usd"] = 999.0
        _write_lines(chain.path, rows)
        result = chain.verify()
        assert not result.ok
        assert any("record_hash mismatch" in b.reason for b in result.breaks)

    def test_deleted_middle_record_is_detected(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        for n in range(3):
            chain.append({"n": n})
        rows = _read_lines(chain.path)
        del rows[1]
        _write_lines(chain.path, rows)
        result = chain.verify()
        assert not result.ok
        assert any("prev_hash" in b.reason for b in result.breaks)

    def test_tail_truncation_is_detected_via_chain_head(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        for n in range(3):
            chain.append({"n": n})
        rows = _read_lines(chain.path)
        _write_lines(chain.path, rows[:-1])
        result = chain.verify()
        assert not result.ok
        assert any("head" in b.reason for b in result.breaks)

    def test_unchained_row_after_chained_is_detected(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        chain.append({"n": 1})
        with chain.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"sneaky": True}) + "\n")
        result = chain.verify()
        assert not result.ok
        assert any("unchained" in b.reason for b in result.breaks)

    def test_corrupt_line_is_detected(self, tmp_path: Path) -> None:
        """The #9474 failure shape: a stash conflict marker in an audit file."""
        chain = _stream(tmp_path)
        chain.append({"n": 1})
        with chain.path.open("a", encoding="utf-8") as fh:
            fh.write("<<<<<<< Updated upstream\n")
        result = chain.verify()
        assert not result.ok
        assert any("invalid JSON" in b.reason for b in result.breaks)

    def test_unchained_prefix_is_tolerated(self, tmp_path: Path) -> None:
        path = tmp_path / "stream.jsonl"
        _write_lines(path, [{"legacy": 1}])
        chain = AuditChain(path)
        chain.append({"n": 2})
        result = chain.verify()
        assert result.ok
        assert result.total_records == 2
        assert result.chained_records == 1


# ---------------------------------------------------------------------------
# Rotation
# ---------------------------------------------------------------------------


class TestRotation:
    def test_chain_head_carries_forward_across_rotation(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        chain.append({"n": 1})
        old_head = chain.append({"n": 2})["record_hash"]

        rotated = tmp_path / "stream.jsonl.1"
        chain.path.rename(rotated)

        written = chain.append({"n": 3})
        assert written["prev_hash"] == old_head
        assert chain.verify().ok
        assert verify_file(rotated).ok

    def test_verify_accepts_carried_forward_first_prev_hash(
        self, tmp_path: Path
    ) -> None:
        chain = _stream(tmp_path)
        chain.append({"n": 1})
        chain.path.rename(tmp_path / "stream.jsonl.1")
        chain.append({"n": 2})
        result = verify_file(chain.path)
        assert result.ok
        assert result.chained_records == 1


# ---------------------------------------------------------------------------
# Rewrite (sanctioned amendment path)
# ---------------------------------------------------------------------------


class TestRewrite:
    def test_rewrite_rechains_amended_records(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        for n in range(3):
            chain.append({"n": n, "outcome": None})
        records = _read_lines(chain.path)
        records[1]["outcome"] = "improved"
        chain.rewrite(records)

        rows = _read_lines(chain.path)
        assert rows[1]["outcome"] == "improved"
        assert chain.verify().ok

    def test_rewrite_preserves_unchained_prefix(self, tmp_path: Path) -> None:
        path = tmp_path / "stream.jsonl"
        _write_lines(path, [{"legacy": 1}])
        chain = AuditChain(path)
        chain.append({"n": 2})
        records = _read_lines(path)
        records[1]["n"] = 99
        chain.rewrite(records)

        rows = _read_lines(path)
        assert rows[0] == {"legacy": 1}
        assert rows[1]["n"] == 99
        assert chain.verify().ok

    def test_out_of_band_edit_without_rewrite_is_detected(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        chain.append({"n": 1})
        chain.append({"n": 2})
        rows = _read_lines(chain.path)
        rows[0]["n"] = 42  # editor-style tamper: no re-chaining
        _write_lines(chain.path, rows)
        assert not chain.verify().ok


# ---------------------------------------------------------------------------
# Retention pruning
# ---------------------------------------------------------------------------


class TestPruneBefore:
    def _seed(self, chain: AuditChain, timestamps: list[str]) -> None:
        for ts in timestamps:
            chain.append({"ts": ts, "n": ts})

    def test_prunes_only_records_older_than_cutoff(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        self._seed(
            chain,
            [
                "2026-01-01T00:00:00Z",
                "2026-02-01T00:00:00Z",
                "2026-06-01T00:00:00Z",
                "2026-07-01T00:00:00Z",
            ],
        )
        cutoff = datetime(2026, 5, 1, tzinfo=UTC)
        removed = chain.prune_before(cutoff, "ts")
        assert removed == 2
        rows = _read_lines(chain.path)
        assert [r["ts"] for r in rows] == [
            "2026-06-01T00:00:00Z",
            "2026-07-01T00:00:00Z",
        ]
        assert chain.verify().ok

    def test_prune_never_deletes_inside_the_floor(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        self._seed(chain, ["2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z"])
        removed = chain.prune_before(datetime(2026, 1, 1, tzinfo=UTC), "ts")
        assert removed == 0
        assert len(_read_lines(chain.path)) == 2

    def test_prune_all_keeps_head_for_carry_forward(self, tmp_path: Path) -> None:
        chain = _stream(tmp_path)
        self._seed(chain, ["2026-01-01T00:00:00Z"])
        old_head = _read_lines(chain.path)[-1]["record_hash"]
        removed = chain.prune_before(datetime(2027, 1, 1, tzinfo=UTC), "ts")
        assert removed == 1
        assert chain.path.read_text(encoding="utf-8") == ""
        written = chain.append({"ts": "2027-06-01T00:00:00Z"})
        assert written["prev_hash"] == old_head
        assert chain.verify().ok

    def test_unparseable_timestamp_stops_the_prefix_cut(self, tmp_path: Path) -> None:
        """Fail-safe: never delete a record whose age cannot be established."""
        chain = _stream(tmp_path)
        chain.append({"ts": "not-a-date"})
        chain.append({"ts": "2026-01-01T00:00:00Z"})
        removed = chain.prune_before(datetime(2027, 1, 1, tzinfo=UTC), "ts")
        assert removed == 0
        assert len(_read_lines(chain.path)) == 2


# ---------------------------------------------------------------------------
# Stream registry
# ---------------------------------------------------------------------------


class TestAuditStreams:
    def test_registry_lists_the_four_chained_streams(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        specs = {s.name: s for s in audit_streams(config)}
        assert set(specs) == {
            "preflight",
            "health_decisions",
            "inference_telemetry",
            "approval_records",
        }
        assert (
            specs["preflight"].path == config.data_root / "auto_agent" / "audit.jsonl"
        )
        assert specs["preflight"].timestamp_key == "ts"
        assert specs["health_decisions"].path == config.memory_dir / "decisions.jsonl"
        assert specs["health_decisions"].timestamp_key == "timestamp"
        assert specs["inference_telemetry"].path == config.cost_inferences_path
        assert specs["inference_telemetry"].timestamp_key == "timestamp"
        assert specs["approval_records"].path == config.approval_records_path
        assert specs["approval_records"].timestamp_key == "timestamp"

    def test_retention_defaults_to_none_meaning_keep_forever(
        self, tmp_path: Path
    ) -> None:
        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        for spec in audit_streams(config):
            assert spec.retention_days is None

    def test_retention_reads_config_fields(self, tmp_path: Path) -> None:
        config = ConfigFactory.create(
            repo_root=tmp_path / "repo",
            audit_retention_days_preflight=2555,
            audit_retention_days_health_decisions=90,
            audit_retention_days_inference_telemetry=30,
            audit_retention_days_approval_records=2555,
        )
        specs = {s.name: s for s in audit_streams(config)}
        assert specs["preflight"].retention_days == 2555
        assert specs["health_decisions"].retention_days == 90
        assert specs["inference_telemetry"].retention_days == 30
        assert specs["approval_records"].retention_days == 2555
