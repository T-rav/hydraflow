"""Regression pin for #9936.

WikiRotDetectorLoop used to walk ``rglob("*.md")`` and regex each file as one
raw blob, ignoring the structured ``WikiEntry`` parse — so it misattributed a
multi-entry topic page's findings to the file heading and couldn't key on
provenance. The fix has the loop import the module-level ``parse_topic_page``
so PR-claim and cite verification share the authoritative parse. This pins that
the module-level function matches the store's own read and carries the
structured ``source_type`` / ``source_issue`` the loop now keys on.
"""

from pathlib import Path

from repo_wiki import RepoWikiStore, WikiEntry, parse_topic_page

_REPO = "acme/widget"


def test_parse_topic_page_matches_store_read_with_provenance(tmp_path: Path) -> None:
    store = RepoWikiStore(tmp_path)
    entry = WikiEntry(title="X", content="Y", source_type="plan", source_issue=1)
    store.ingest(_REPO, [entry])
    topic_path = store._repo_dir(_REPO) / f"{store._classify_topic(entry)}.md"

    via_function = parse_topic_page(topic_path)
    via_store = store._load_topic_entries(topic_path)

    # Same authoritative parse via the module-level function and the store.
    assert [e.model_dump() for e in via_function] == [e.model_dump() for e in via_store]
    # Structured provenance survives the round-trip (what the loop keys on).
    assert via_function[0].source_issue == 1
    assert via_function[0].source_type == "plan"
