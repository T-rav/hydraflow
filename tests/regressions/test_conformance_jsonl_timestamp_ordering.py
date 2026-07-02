"""Regression: latest-per-ADR selection must compare timestamps as datetimes.

Bead advisor-sqsv (shipped in #9698): the conformance dashboard route and the
jsonl compaction helper both pick "the newest row per adr_id". They originally
compared the serialized timestamp *strings* with ``>``. Pydantic serializes a
whole-second UTC datetime as ``...56Z`` but a sub-second one as
``...56.000001Z``, and lexically ``.`` (0x2E) sorts before ``Z`` (0x5A) — so
``...56.000001Z`` string-compared as *older* than ``...56Z`` even though it is
one microsecond *newer*. That silently served/kept the wrong (older) row
across the whole-second boundary.

The fix routes both consumers through ``file_util.is_newer_timestamp``, which
parses to ``datetime`` before comparing. These tests pin the specific
boundary that string comparison got wrong, at both the helper level and the
compaction level (the real consumer that rewrites the file).
"""

from __future__ import annotations

import json
from pathlib import Path

from file_util import compact_jsonl_latest_by_key, is_newer_timestamp

# The exact pair the string comparison inverted: same whole second, one with
# microseconds, one without. Chronologically the microsecond row is NEWER.
_NO_MICROS = "2026-07-02T12:00:56Z"
_WITH_MICROS = "2026-07-02T12:00:56.000001Z"


def test_microsecond_row_is_newer_than_whole_second_row():
    # Sanity: the naive string compare that shipped the bug gets this wrong.
    assert (_WITH_MICROS > _NO_MICROS) is False  # the bug: string-compare lies

    # The fix: parsed-datetime comparison ranks the microsecond row as newer.
    assert is_newer_timestamp(_WITH_MICROS, _NO_MICROS) is True
    assert is_newer_timestamp(_NO_MICROS, _WITH_MICROS) is False


def test_compaction_keeps_the_microsecond_row_across_the_second_boundary(
    tmp_path: Path,
):
    path = tmp_path / "adr_conformance.jsonl"
    # Same adr_id, whole-second row written first, microsecond (newer) row
    # second. String-compare compaction would have kept the whole-second row.
    path.write_text(
        json.dumps({"adr_id": "ADR-0100", "timestamp": _NO_MICROS, "outcome": "old"})
        + "\n"
        + json.dumps(
            {"adr_id": "ADR-0100", "timestamp": _WITH_MICROS, "outcome": "new"}
        )
        + "\n",
        encoding="utf-8",
    )

    compact_jsonl_latest_by_key(path, key="adr_id", ts_key="timestamp")

    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(rows) == 1
    assert rows[0]["outcome"] == "new"
    assert rows[0]["timestamp"] == _WITH_MICROS
