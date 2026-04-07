"""Tests for the durable JSONL retrospective queue."""

from __future__ import annotations

from pathlib import Path

from retrospective_queue import QueueItem, QueueKind, RetrospectiveQueue


class TestAppend:
    def test_append_creates_file_and_persists(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl")
        q.append(QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=42))

        items = q.load()
        assert len(items) == 1
        assert items[0].kind == QueueKind.RETRO_PATTERNS
        assert items[0].issue_number == 42

    def test_append_multiple_items(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl")
        q.append(QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1))
        q.append(QueueItem(kind=QueueKind.REVIEW_PATTERNS, issue_number=2))

        items = q.load()
        assert len(items) == 2


class TestLoad:
    def test_load_empty_file(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl")
        assert q.load() == []

    def test_load_skips_corrupt_lines(self, tmp_path: Path) -> None:
        path = tmp_path / "queue.jsonl"
        path.write_text('not json\n{"kind":"retro_patterns","issue_number":1}\n')
        q = RetrospectiveQueue(path)

        items = q.load()
        assert len(items) == 1
        assert items[0].issue_number == 1


class TestAcknowledge:
    def test_acknowledge_removes_items(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl")
        q.append(QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1))
        q.append(QueueItem(kind=QueueKind.REVIEW_PATTERNS, issue_number=2))

        items = q.load()
        q.acknowledge([items[0].id])

        remaining = q.load()
        assert len(remaining) == 1
        assert remaining[0].issue_number == 2

    def test_acknowledge_all_empties_file(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl")
        q.append(QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1))

        items = q.load()
        q.acknowledge([items[0].id])

        assert q.load() == []

    def test_acknowledge_nonexistent_id_is_noop(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl")
        q.append(QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=1))

        q.acknowledge(["nonexistent"])

        assert len(q.load()) == 1


class TestTrim:
    def test_trim_caps_at_max_entries(self, tmp_path: Path) -> None:
        q = RetrospectiveQueue(tmp_path / "queue.jsonl", max_entries=3)
        for i in range(5):
            q.append(QueueItem(kind=QueueKind.RETRO_PATTERNS, issue_number=i))

        items = q.load()
        assert len(items) == 3
        # Oldest items dropped, newest kept
        assert items[0].issue_number == 2
