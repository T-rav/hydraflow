"""Regression test for #10566.

``WikiCompiler.compile_topic_tracked`` (src/wiki_compiler.py) computed one
global ``superseded_ids`` list from *all* active entries and handed that
same list to every synthesized entry's ``supersedes`` frontmatter, then
pointed every input entry's ``superseded_by`` at only the *first* synthesis
id. A sampled adversarial re-audit (SampledAuditLoop) caught this in a real
``dependencies/`` topic refresh: five unrelated old entries (cross-dependency
mapping, DependabotMergeLoop, TrustFleetSanityLoop, ADR-drift citations,
JsonlLedger split) were all marked ``superseded_by: 0017`` even though 0017
is topically only about cross-dependency mapping — and every new entry
(0017-0021) claimed ``supersedes`` all five old ids regardless of which one
it actually replaced. Anyone following ``superseded_by`` from the old
DependabotMergeLoop entry landed on an unrelated cross-dependency-mapping
document instead of its real replacement.

The fix (``WikiCompiler._resolve_supersession_ids``) honors the LLM's own
per-entry ``supersedes_ids`` declaration (now surfaced via an ``(id: ...)``
annotation in the compiler prompt) instead of blanket-linking every
synthesized entry to every input entry.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repo_wiki import WikiEntry
from wiki_compiler import WikiCompiler

REPO = "acme/widget"

_OLD_TOPICS = [
    ("0011", "Cross-dependency mapping"),
    ("0012", "DependabotMergeLoop guidance"),
    ("0013", "TrustFleetSanityLoop guidance"),
    ("0014", "ADR-drift citations"),
    ("0015", "JsonlLedger split"),
]


def _write_entry_file(path: Path, *, entry_id: str, topic: str, title: str) -> None:
    from datetime import UTC, datetime

    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).isoformat()
    path.write_text(
        "---\n"
        f"id: {entry_id}\n"
        f"topic: {topic}\n"
        "source_issue: 1\n"
        "source_phase: plan\n"
        f"created_at: {now}\n"
        "status: active\n"
        "---\n"
        "\n"
        f"# {title}\n\nContent body.\n",
        encoding="utf-8",
    )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestSupersessionMappingIsTopical:
    """End-to-end: replays the exact five-entry shape the auditor flagged."""

    @pytest.fixture
    def topic_dir(self, tmp_path: Path) -> Path:
        tracked_root = tmp_path / "repo_wiki"
        topic_dir = tracked_root / REPO / "dependencies"
        for entry_id, title in _OLD_TOPICS:
            _write_entry_file(
                topic_dir / f"{entry_id}-issue-1-x.md",
                entry_id=entry_id,
                topic="dependencies",
                title=title,
            )
        return tracked_root

    @pytest.mark.asyncio
    async def test_each_new_entry_supersedes_only_its_own_topical_match(
        self, topic_dir: Path
    ) -> None:
        compiler = WikiCompiler.__new__(WikiCompiler)
        compiler._config = MagicMock()
        compiler._credentials = MagicMock()
        compiler._credentials.gh_token = ""
        compiler._runner = MagicMock()

        # Each new entry declares correspondence to exactly the one old
        # entry it topically replaces — a 1:1 rewrite, not a merge.
        import json

        response = [
            {
                "title": f"{title} (updated)",
                "content": f"See `src/repo_wiki.py`. Replaces old entry {old_id}.",
                "source_type": "compiled",
                "source_issue": None,
                "supersedes_ids": [old_id],
            }
            for old_id, title in _OLD_TOPICS
        ]
        compiler._call_model = AsyncMock(return_value=json.dumps(response))

        count = await compiler.compile_topic_tracked(topic_dir, REPO, "dependencies")
        assert count == 5

        dep_dir = topic_dir / REPO / "dependencies"
        synthesis_files = sorted(dep_dir.glob("*-issue-synthesis-*.md"))
        assert len(synthesis_files) == 5

        # Map each synthesis file's declared supersedes id -> its own new id,
        # and pin that each file declares exactly one old id — not all five.
        known_old_ids = {old_id for old_id, _title in _OLD_TOPICS}
        new_id_for_old: dict[str, str] = {}
        for path in synthesis_files:
            text = _read(path)
            new_id = path.name.split("-", 1)[0]
            supersedes_line = next(
                line for line in text.splitlines() if line.startswith("supersedes:")
            )
            declared_ids = supersedes_line.split(":", 1)[1].strip().split(",")
            assert len(declared_ids) == 1
            assert declared_ids[0] in known_old_ids
            new_id_for_old[declared_ids[0]] = new_id

        assert set(new_id_for_old) == {oid for oid, _ in _OLD_TOPICS}
        # Every old id maps to a *distinct* new entry — the bug collapsed
        # all five onto the single first synthesis id.
        assert len(set(new_id_for_old.values())) == 5

        # Each old entry's superseded_by must point at its own topical
        # replacement, not uniformly at the first synthesis id.
        for old_id, _title in _OLD_TOPICS:
            old_path = dep_dir / f"{old_id}-issue-1-x.md"
            text = _read(old_path)
            assert "status: superseded" in text
            expected_new_id = new_id_for_old[old_id]
            assert f"superseded_by: {expected_new_id}" in text


class TestResolveSupersessionIdsEdgeCases:
    """Direct unit coverage of the pure mapping function.

    A prior implementation attempt on this issue shipped a mapping
    function but was rejected by test-adequacy review for missing the
    non-exclusive/duplicate supersedes-id case below — cover it
    explicitly so a future refactor can't silently reintroduce it.
    """

    @staticmethod
    def _active(*ids: str) -> list[dict]:
        return [{"id": i, "path": f"/tmp/{i}.md"} for i in ids]

    @staticmethod
    def _entry(supersedes_ids: list[str]) -> WikiEntry:
        return WikiEntry(
            title="t",
            content="c",
            source_type="compiled",
            supersedes_ids=supersedes_ids,
        )

    def test_duplicate_id_within_single_entry_is_deduped(self) -> None:
        active = self._active("0001", "0002")
        compiled = [self._entry(["0001", "0001", "0002"])]

        result = WikiCompiler._resolve_supersession_ids(active, compiled)

        assert result == [["0001", "0002"]]

    def test_non_exclusive_duplicate_across_entries_both_keep_it(self) -> None:
        # An umbrella old entry split into two new entries: both
        # legitimately declare the same old id.
        active = self._active("0001")
        compiled = [self._entry(["0001"]), self._entry(["0001"])]

        result = WikiCompiler._resolve_supersession_ids(active, compiled)

        assert result == [["0001"], ["0001"]]

    def test_hallucinated_id_not_in_active_entries_is_dropped(self) -> None:
        active = self._active("0001")
        compiled = [self._entry(["0001", "9999"])]

        result = WikiCompiler._resolve_supersession_ids(active, compiled)

        assert result == [["0001"]]

    def test_unclaimed_old_id_falls_back_to_first_entry(self) -> None:
        active = self._active("0001", "0002", "0003")
        compiled = [self._entry(["0001"]), self._entry(["0002"])]

        result = WikiCompiler._resolve_supersession_ids(active, compiled)

        # 0003 was never declared by any entry — folded onto entry 0.
        assert result[0] == ["0001", "0003"]
        assert result[1] == ["0002"]

    def test_no_declarations_at_all_folds_everything_onto_first_entry(self) -> None:
        active = self._active("0001", "0002", "0003")
        compiled = [self._entry([])]

        result = WikiCompiler._resolve_supersession_ids(active, compiled)

        assert result == [["0001", "0002", "0003"]]
