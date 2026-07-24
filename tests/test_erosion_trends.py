"""Unit tests for the erosion trend surfaces (#10367, v2 of epic #10104).

Covers the pure duplication-density sensor (synthetic file contents, no git)
and the pure month-over-month trend rollup (all four trend metrics) + its
Markdown render and the append-only datapoint store.
"""

from __future__ import annotations

from pathlib import Path

from erosion.duplication import compute as dup_compute
from erosion.duplication import duplication_for_range
from erosion.trends import (
    ChangeDatapoint,
    TrendStore,
    compute_monthly_trends,
    render_erosion_trends_markdown,
)

_BLOCK = "alpha\nbeta\ngamma\ndelta\nepsilon\n"


class TestDuplication:
    def test_identical_block_across_two_files_is_duplicated(self) -> None:
        finding = dup_compute({"a.py": _BLOCK, "b.py": _BLOCK}, block_lines=5)
        assert finding.duplicated_blocks == 1
        assert finding.total_lines == 10
        assert finding.duplicate_groups == (("a.py", "b.py"),)
        # 1 dup block / (10 lines / 1000) = 100 per KLOC
        assert finding.density == 100.0

    def test_distinct_files_have_no_duplication(self) -> None:
        finding = dup_compute(
            {"a.py": "one\ntwo\nthree\nfour\nfive\n", "b.py": _BLOCK},
            block_lines=5,
        )
        assert finding.duplicated_blocks == 0
        assert finding.density == 0.0

    def test_file_shorter_than_block_yields_no_windows(self) -> None:
        finding = dup_compute({"a.py": "one\ntwo\n"}, block_lines=5)
        assert finding.duplicated_blocks == 0
        assert finding.total_lines == 2

    def test_whitespace_is_normalized_before_hashing(self) -> None:
        finding = dup_compute(
            {"a.py": _BLOCK, "b.py": "alpha  \n  beta\ngamma\ndelta\nepsilon"},
            block_lines=5,
        )
        assert finding.duplicated_blocks == 1

    def test_duplication_for_range_reads_only_py_files(self, tmp_path: Path) -> None:
        (tmp_path / "a.py").write_text(_BLOCK, encoding="utf-8")
        (tmp_path / "b.py").write_text(_BLOCK, encoding="utf-8")
        (tmp_path / "c.txt").write_text(_BLOCK, encoding="utf-8")
        finding = duplication_for_range(
            tmp_path, ["a.py", "b.py", "c.txt", "missing.py"], block_lines=5
        )
        assert finding is not None
        assert finding.duplicated_blocks == 1


class TestMonthlyTrends:
    def test_all_four_metrics_per_month(self) -> None:
        datapoints = [
            ChangeDatapoint(
                "2026-01",
                files_touched=4,
                modules_crossed=3,
                scatter_findings=1,
                duplication_density=10.0,
            ),
            ChangeDatapoint(
                "2026-01",
                files_touched=2,
                modules_crossed=1,
                scatter_findings=0,
                duplication_density=20.0,
            ),
            ChangeDatapoint(
                "2026-02",
                files_touched=6,
                modules_crossed=5,
                scatter_findings=2,
                duplication_density=30.0,
            ),
        ]
        rows = compute_monthly_trends(datapoints)
        assert [r.month for r in rows] == ["2026-01", "2026-02"]
        jan = rows[0]
        assert jan.change_count == 2
        assert jan.pct_crossing_3_modules == 50.0  # 1 of 2 crossed >=3
        assert jan.mean_files_touched == 3.0
        assert jan.duplication_density == 15.0  # mean of 10 and 20
        assert jan.scatter_findings == 1

    def test_empty_datapoints_yields_no_rows(self) -> None:
        assert compute_monthly_trends([]) == []

    def test_render_contains_all_columns(self) -> None:
        rows = compute_monthly_trends([ChangeDatapoint("2026-01", 4, 3, 1, 10.0)])
        md = render_erosion_trends_markdown(rows)
        assert "# Erosion trends" in md
        assert "% crossing ≥3 modules" in md
        assert "duplication /KLOC" in md
        assert "2026-01" in md

    def test_render_empty_has_placeholder_row(self) -> None:
        md = render_erosion_trends_markdown([])
        assert "no changes recorded yet" in md


class TestTrendStore:
    def test_append_and_read_roundtrip(self, tmp_path: Path) -> None:
        store = TrendStore(tmp_path / "erosion_trends.jsonl")
        dp = ChangeDatapoint("2026-01", 4, 3, 1, 10.0)
        store.append(dp)
        assert store.read_all() == [dp]

    def test_missing_file_is_empty(self, tmp_path: Path) -> None:
        assert TrendStore(tmp_path / "nope.jsonl").read_all() == []
