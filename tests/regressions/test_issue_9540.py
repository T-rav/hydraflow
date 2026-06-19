"""Regression for #9540: spawn-contract ratchets cite a stale, wrong ADR.

The module docstrings of the telemetry/credit spawn-contract ratchets cite
``ADR-0086`` for the "non-central spawn paths must stay telemetried / detect
credit" contract. But ``docs/adr/0086-live-corpus-replay-loop.md`` is actually
about the ``LiveCorpusReplayLoop`` shadow-corpus drift detector — an unrelated
decision (a casualty of the known ADR-number renumbering churn). A reader
following the citation lands on the wrong ADR.

This guards provenance: any ``ADR-NNNN`` cited by a spawn-contract file must
resolve to an ADR whose subject matter is NOT the LiveCorpusReplayLoop.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]

# The spawn-contract ratchet files (+ shared helper) that carry the citation.
_SPAWN_CONTRACT_FILES = (
    "tests/test_telemetry_source_completeness.py",
    "tests/test_subprocess_runner_contract_completeness.py",
    "tests/_spawn_audit.py",
)

_ADR_REF = re.compile(r"ADR-(\d{4})")
# Markers that identify the unrelated LiveCorpusReplayLoop ADR by its title.
_LIVE_CORPUS_MARKERS = (
    "LiveCorpusReplayLoop",
    "live-corpus-replay-loop",
    "Shadow-Corpus",
)


def _adr_path(number: str) -> Path | None:
    matches = list((_REPO_ROOT / "docs" / "adr").glob(f"{number}-*.md"))
    return matches[0] if matches else None


@pytest.mark.parametrize("rel_path", _SPAWN_CONTRACT_FILES)
def test_spawn_contract_adr_citation_is_not_the_live_corpus_loop(rel_path: str) -> None:
    source = (_REPO_ROOT / rel_path).read_text()

    mismatches: list[str] = []
    for number in _ADR_REF.findall(source):
        adr = _adr_path(number)
        if adr is None:
            continue
        title = adr.read_text().splitlines()[0]
        if any(marker in title for marker in _LIVE_CORPUS_MARKERS) or any(
            marker in adr.name for marker in _LIVE_CORPUS_MARKERS
        ):
            mismatches.append(
                f"{rel_path} cites ADR-{number} -> {adr.name!r} ({title.strip()!r})"
            )

    assert not mismatches, (
        "spawn-contract docstring cites the unrelated LiveCorpusReplayLoop ADR "
        "instead of the telemetry/credit contract reference:\n" + "\n".join(mismatches)
    )
