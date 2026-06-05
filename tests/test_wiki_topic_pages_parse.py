"""Guard: every committed ``docs/wiki/*.md`` topic page parses with zero skips.

The ``RepoWikiLoop`` re-reads these pages on every tick and, during ingest,
does a read-modify-write of each topic file. An entry that fails
``WikiEntry`` validation is dropped with a ``Skipping malformed entry``
warning — and because the dropped entry is absent from the rewrite, the next
ingest write can *permanently delete* it from disk. So a malformed committed
entry is not merely log noise; it is a latent data-loss bug.

This regression locks the fix for the gotchas.md (h3-section folding +
missing ``source_type``) and testing.md (string ``source_issue``) defects by
asserting the live topic pages all round-trip through ``_load_topic_entries``
without a single skip.
"""

from __future__ import annotations

import logging
from pathlib import Path

from repo_wiki import RepoWikiStore

WIKI_DIR = Path(__file__).resolve().parents[1] / "docs" / "wiki"
_SKIP_MARKER = "Skipping malformed entry"


def _skip_warnings(records: list[logging.LogRecord]) -> list[str]:
    return [r.getMessage() for r in records if _SKIP_MARKER in r.getMessage()]


def test_all_wiki_topic_pages_parse_without_skips(tmp_path, caplog) -> None:
    store = RepoWikiStore(tmp_path)
    pages = sorted(WIKI_DIR.glob("*.md"))
    assert pages, f"no wiki topic pages found under {WIKI_DIR}"

    offenders: dict[str, list[str]] = {}
    for page in pages:
        with caplog.at_level(logging.WARNING, logger="hydraflow.repo_wiki"):
            caplog.clear()
            store._load_topic_entries(page)
            skips = _skip_warnings(caplog.records)
        if skips:
            offenders[page.name] = skips

    assert not offenders, f"malformed wiki entries skipped during parse: {offenders}"


def test_malformed_entry_warning_names_entry_id_and_reason(tmp_path, caplog) -> None:
    page = tmp_path / "broken.md"
    page.write_text(
        "# Broken\n\n"
        "## A rule with an incomplete entry\n\n"
        "Some prose.\n\n"
        '```json:entry\n{"id": "broken-entry-xyz", "topic": "testing"}\n```\n'
    )
    store = RepoWikiStore(tmp_path)

    with caplog.at_level(logging.WARNING, logger="hydraflow.repo_wiki"):
        entries = store._load_topic_entries(page)

    assert entries == []
    skips = _skip_warnings(caplog.records)
    assert len(skips) == 1
    message = skips[0]
    assert "broken-entry-xyz" in message
    assert "source_type" in message
