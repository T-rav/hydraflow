"""Tests for emit_loop_subprocess_trace (spec §4.11 point 3)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trace_collector import (
    _loop_trace_dir,
    _slug_for_loop,
    emit_loop_subprocess_trace,
)


@pytest.fixture
def data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "data"
    root.mkdir()
    cfg = MagicMock()
    cfg.data_root = root
    monkeypatch.setattr("trace_collector._current_config", lambda: cfg)
    return root


def test_slug_for_loop_lowercases_and_replaces_nonalnum() -> None:
    assert _slug_for_loop("RCBudgetLoop") == "rcbudgetloop"
    assert _slug_for_loop("Trust Fleet / Sanity") == "trust_fleet___sanity"
    assert _slug_for_loop("") == "unknown"


def test_loop_trace_dir_nested_under_data_root(data_root: Path) -> None:
    out = _loop_trace_dir("CorpusLearningLoop")
    assert out.is_relative_to(data_root / "traces" / "_loops")
    assert out.name == "corpuslearningloop"


def test_emit_writes_trace_entry_with_required_shape(data_root: Path) -> None:
    emit_loop_subprocess_trace(
        loop="CorpusLearningLoop",
        command=["gh", "api", "repos/o/r/issues"],
        exit_code=0,
        duration_ms=1234,
    )
    files = list(
        (data_root / "traces" / "_loops" / "corpuslearningloop").glob("run-*.json")
    )
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["kind"] == "loop"
    assert payload["loop"] == "CorpusLearningLoop"
    assert payload["command"] == ["gh", "api", "repos/o/r/issues"]
    assert payload["exit_code"] == 0
    assert payload["duration_ms"] == 1234
    assert payload["stderr"] is None
    assert "started_at" in payload  # ISO 8601


def test_emit_truncates_stderr_tail_preserving(data_root: Path) -> None:
    big = "A" * 4096 + "TAIL_MARKER"
    emit_loop_subprocess_trace(
        loop="X",
        command=["/bin/true"],
        exit_code=1,
        duration_ms=5,
        stderr_excerpt=big,
    )
    files = list((data_root / "traces" / "_loops" / "x").glob("run-*.json"))
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["stderr"] is not None
    assert len(payload["stderr"]) == 2048
    assert payload["stderr"].endswith("TAIL_MARKER")


def test_emit_never_raises_on_missing_config_or_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Case 1: no active config — must no-op silently.
    monkeypatch.setattr("trace_collector._current_config", lambda: None)
    emit_loop_subprocess_trace(loop="Z", command=["x"], exit_code=0, duration_ms=1)
    assert not any(tmp_path.rglob("run-*.json"))

    # Case 2: config present, filesystem broken — must log + swallow.
    cfg = MagicMock()
    cfg.data_root = tmp_path
    monkeypatch.setattr("trace_collector._current_config", lambda: cfg)
    monkeypatch.setattr(
        Path, "write_text", lambda *a, **kw: (_ for _ in ()).throw(OSError("full"))
    )
    emit_loop_subprocess_trace(loop="Q", command=["x"], exit_code=0, duration_ms=1)
    assert any("emit_loop_subprocess_trace failed" in r.message for r in caplog.records)
