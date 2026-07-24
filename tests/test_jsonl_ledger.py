"""Unit tests for the generic append-only JSONL ledger base (#10404, #10403).

``AppendOnlyJsonlLedger[S]`` lifts the byte-identical read/append logic that
had independently accreted in ``audit.store.AuditSampleLedger``,
``escape.ledger.EscapeLedger``, ``intervention.ledger.InterventionLedger``,
and ``erosion.trends.TrendStore`` (concept-scatter erosion finding).
``IdentifiedJsonlLedger[T]`` extends it with ``existing_ids()`` dedup for the
three domains that have a stable row id — ``TrendStore`` does not, and stays
on the plain base (see ``tests/regressions/test_issue_10403.py``).

Exercised here against synthetic ``_Widget`` (has an id) and ``_Note`` (no
id) records so the base behaviour is proven independent of any one domain
model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonl_ledger import AppendOnlyJsonlLedger, IdentifiedJsonlLedger

_logger = logging.getLogger("test.jsonl_ledger")


@dataclass(frozen=True)
class _Widget:
    id: str
    label: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {"id": self.id, "label": self.label}

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> _Widget:
        return cls(id=str(raw.get("id", "")), label=str(raw.get("label", "")))


class _WidgetLedger(IdentifiedJsonlLedger[_Widget]):
    def __init__(self, path: Path) -> None:
        super().__init__(path, _Widget, logger=_logger)


@dataclass(frozen=True)
class _Note:
    """A row with no stable id — mirrors ``ChangeDatapoint``."""

    text: str

    def to_json_dict(self) -> dict[str, Any]:
        return {"text": self.text}

    @classmethod
    def from_json_dict(cls, raw: dict[str, Any]) -> _Note:
        return cls(text=str(raw.get("text", "")))


class _NoteLog(AppendOnlyJsonlLedger[_Note]):
    def __init__(self, path: Path) -> None:
        super().__init__(path, _Note, logger=_logger)


class TestIdentifiedJsonlLedger:
    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        ledger = _WidgetLedger(tmp_path / "nope.jsonl")
        assert ledger.read_all() == []
        assert ledger.existing_ids() == set()

    def test_append_and_read_roundtrip(self, tmp_path: Path) -> None:
        ledger = _WidgetLedger(tmp_path / "widgets.jsonl")
        widget = _Widget(id="a", label="first")
        ledger.append(widget)
        assert ledger.read_all() == [widget]
        assert ledger.existing_ids() == {"a"}

    def test_append_multiple_preserves_order(self, tmp_path: Path) -> None:
        ledger = _WidgetLedger(tmp_path / "widgets.jsonl")
        ledger.append(_Widget(id="a"))
        ledger.append(_Widget(id="b"))
        assert [w.id for w in ledger.read_all()] == ["a", "b"]
        assert ledger.existing_ids() == {"a", "b"}

    def test_malformed_line_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "widgets.jsonl"
        path.write_text('{"id": "a"}\nnot json\n{"id": "b"}\n', encoding="utf-8")
        ledger = _WidgetLedger(path)
        assert {w.id for w in ledger.read_all()} == {"a", "b"}

    def test_non_dict_json_line_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "widgets.jsonl"
        path.write_text('[1, 2, 3]\n{"id": "a"}\n', encoding="utf-8")
        ledger = _WidgetLedger(path)
        assert [w.id for w in ledger.read_all()] == ["a"]

    def test_blank_lines_are_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "widgets.jsonl"
        path.write_text('{"id": "a"}\n\n   \n{"id": "b"}\n', encoding="utf-8")
        ledger = _WidgetLedger(path)
        assert [w.id for w in ledger.read_all()] == ["a", "b"]

    def test_append_creates_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "dir" / "widgets.jsonl"
        ledger = _WidgetLedger(nested)
        ledger.append(_Widget(id="a"))
        assert nested.exists()
        assert ledger.read_all() == [_Widget(id="a")]

    def test_path_property_returns_constructed_path(self, tmp_path: Path) -> None:
        target = tmp_path / "widgets.jsonl"
        assert _WidgetLedger(target).path == target


class TestAppendOnlyJsonlLedger:
    """The plain, id-less base — no ``existing_ids`` method at all."""

    def test_read_missing_file_returns_empty(self, tmp_path: Path) -> None:
        assert _NoteLog(tmp_path / "nope.jsonl").read_all() == []

    def test_append_and_read_roundtrip(self, tmp_path: Path) -> None:
        log = _NoteLog(tmp_path / "notes.jsonl")
        note = _Note(text="first")
        log.append(note)
        assert log.read_all() == [note]

    def test_append_multiple_preserves_order(self, tmp_path: Path) -> None:
        log = _NoteLog(tmp_path / "notes.jsonl")
        log.append(_Note(text="a"))
        log.append(_Note(text="b"))
        assert [n.text for n in log.read_all()] == ["a", "b"]

    def test_malformed_line_is_skipped(self, tmp_path: Path) -> None:
        path = tmp_path / "notes.jsonl"
        path.write_text('{"text": "a"}\nnot json\n{"text": "b"}\n', encoding="utf-8")
        log = _NoteLog(path)
        assert [n.text for n in log.read_all()] == ["a", "b"]

    def test_append_creates_parent_directory(self, tmp_path: Path) -> None:
        nested = tmp_path / "nested" / "dir" / "notes.jsonl"
        log = _NoteLog(nested)
        log.append(_Note(text="a"))
        assert nested.exists()

    def test_has_no_existing_ids_method(self) -> None:
        assert not hasattr(_NoteLog, "existing_ids")
