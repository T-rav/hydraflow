"""Unit tests for the generic append-only JSONL ledger base (#10404).

``JsonlLedger[T]`` lifts the byte-identical read/append/dedup logic that had
independently accreted in ``audit.store.AuditSampleLedger``,
``escape.ledger.EscapeLedger``, and ``intervention.ledger.InterventionLedger``
(concept-scatter erosion finding). Exercised here against a synthetic
``_Widget`` record so the base behaviour is proven independent of any one
domain model.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonl_ledger import JsonlLedger

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


class _WidgetLedger(JsonlLedger[_Widget]):
    def __init__(self, path: Path) -> None:
        super().__init__(path, _Widget, logger=_logger)


class TestJsonlLedger:
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
