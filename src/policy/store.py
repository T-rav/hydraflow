"""The fact ledger: ``.hydraflow/{repo_slug}/metrics/facts.jsonl``.

Sits next to ``adr_conformance.jsonl`` and follows the same ADR-0021 layout and
the same **snapshot** retention: one row per ``(standard, subject, key)``,
compacted after every append, so the file is bounded at "one row per fact"
rather than growing by a whole fact set every tick. It is the recorded evidence
that makes a ``StandardDecision`` reproducible offline — read the rows back,
hand them to a ``DecisionEngine``, get the same decision without the repo, the
network, or any service being up (#11687).

Writes go through ``file_util.append_jsonl`` (crash-safe fsync + ADR-0085
secret scrubbing) and ``file_util.compact_jsonl_latest_by_key`` (atomic
``os.replace``), exactly like ``AdrConformanceLoop._persist_jsonl``.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from file_util import append_jsonl, compact_jsonl_latest_by_key
from policy.models import Fact

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence
    from pathlib import Path

logger = logging.getLogger("hydraflow.policy.store")

#: Filename of the ledger inside a repo's metrics directory.
FACTS_FILENAME = "facts.jsonl"


def facts_path(repo_data_root: Path) -> Path:
    """The ledger path for a repo: ``{repo_data_root}/metrics/facts.jsonl``."""
    return repo_data_root / "metrics" / FACTS_FILENAME


def append_facts(path: Path, facts: Sequence[Fact]) -> None:
    """Append *facts*, then compact to the newest row per ``fact_key``.

    A hard no-op for an empty sequence, and not merely as an optimization:
    compaction is *lossy* by contract — ``compact_jsonl_latest_by_key`` drops
    any row missing its key — so letting an empty append fall through to the
    rewrite would silently truncate rows an older writer left behind. Appending
    nothing must leave the ledger byte-identical.
    """
    if not facts:
        return
    for fact in facts:
        append_jsonl(path, fact.model_dump_json())
    compact_jsonl_latest_by_key(path, key="fact_key", ts_key="observed_at")


def read_facts(path: Path) -> list[Fact]:
    """Read the ledger back into ``Fact`` records.

    Tolerates blank and corrupt lines the same way the dashboard read path and
    ``compact_jsonl_latest_by_key`` do — a torn tail must not make an otherwise
    replayable ledger unreadable — but a row that parses as JSON and then fails
    ``Fact`` validation is *not* tolerated: that is a schema break, and
    silently dropping it would let a decision be replayed over a quietly
    smaller fact set than the one that was recorded.
    """
    if not path.exists():
        return []
    facts: list[Fact] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Dropping corrupt jsonl line while reading %s", path)
            continue
        if not isinstance(row, dict):
            continue
        facts.append(Fact.model_validate(row))
    return facts


def facts_to_jsonl(facts: Iterable[Fact]) -> str:
    """Serialize *facts* to JSONL text (one JSON object per line, trailing \\n)."""
    return "".join(f"{fact.model_dump_json()}\n" for fact in facts)


def facts_from_jsonl(text: str) -> list[Fact]:
    """Parse JSONL *text* back into ``Fact`` records (inverse of the above)."""
    return [
        Fact.model_validate_json(line) for line in text.splitlines() if line.strip()
    ]
