"""Unit tests for coverage_delta pure functions."""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

sys.path.insert(0, str(Path(__file__).parent.parent))


from coverage_delta import (
    compute_uncovered_changed_lines,
    parse_cobertura_covered_lines,
    parse_diff_changed_lines,
)

# ---------------------------------------------------------------------------
# parse_diff_changed_lines
# ---------------------------------------------------------------------------


class TestParseDiffChangedLines:
    def test_empty_diff_returns_empty_dict(self) -> None:
        assert parse_diff_changed_lines("") == {}

    def test_single_added_line_returns_correct_mapping(self) -> None:
        diff = dedent("""\
            diff --git a/src/foo.py b/src/foo.py
            --- a/src/foo.py
            +++ b/src/foo.py
            @@ -1,1 +1,2 @@
             existing
            +added_line
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {"src/foo.py": {2}}

    def test_multiple_added_lines_in_one_hunk(self) -> None:
        diff = dedent("""\
            diff --git a/src/bar.py b/src/bar.py
            --- a/src/bar.py
            +++ b/src/bar.py
            @@ -5,2 +5,4 @@
             ctx5
            +added6
            +added7
             ctx8
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {"src/bar.py": {6, 7}}

    def test_test_files_are_excluded(self) -> None:
        diff = dedent("""\
            diff --git a/tests/test_foo.py b/tests/test_foo.py
            --- a/tests/test_foo.py
            +++ b/tests/test_foo.py
            @@ -1,1 +1,2 @@
             existing
            +new_test_line
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {}

    def test_deleted_lines_are_not_counted(self) -> None:
        diff = dedent("""\
            diff --git a/src/baz.py b/src/baz.py
            --- a/src/baz.py
            +++ b/src/baz.py
            @@ -1,2 +1,1 @@
            -removed
             kept
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {}

    def test_mixed_production_and_test_files(self) -> None:
        diff = dedent("""\
            diff --git a/src/util.py b/src/util.py
            --- a/src/util.py
            +++ b/src/util.py
            @@ -1,1 +1,2 @@
             existing
            +new_util
            diff --git a/tests/test_util.py b/tests/test_util.py
            --- a/tests/test_util.py
            +++ b/tests/test_util.py
            @@ -1,1 +1,2 @@
             existing_test
            +new_test
        """)
        result = parse_diff_changed_lines(diff)
        assert "src/util.py" in result
        assert "tests/test_util.py" not in result

    def test_multiple_hunks_in_same_file(self) -> None:
        diff = dedent("""\
            diff --git a/src/multi.py b/src/multi.py
            --- a/src/multi.py
            +++ b/src/multi.py
            @@ -1,1 +1,2 @@
             line1
            +line2
            @@ -10,1 +11,2 @@
             line10
            +line12
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {"src/multi.py": {2, 12}}

    def test_file_at_repo_root_not_in_src(self) -> None:
        diff = dedent("""\
            diff --git a/setup.py b/setup.py
            --- a/setup.py
            +++ b/setup.py
            @@ -1,1 +1,2 @@
             existing
            +new_line
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {"setup.py": {2}}

    def test_dev_null_deleted_file_not_included(self) -> None:
        diff = dedent("""\
            diff --git a/src/old.py b/src/old.py
            --- a/src/old.py
            +++ /dev/null
            @@ -1,2 +0,0 @@
            -line1
            -line2
        """)
        result = parse_diff_changed_lines(diff)
        assert result == {}


# ---------------------------------------------------------------------------
# parse_cobertura_covered_lines
# ---------------------------------------------------------------------------


class TestParseCoberturaCoveredLines:
    def _write_xml(self, tmp_path: Path, source: str, classes: list[dict]) -> Path:
        """Write a minimal Cobertura XML fixture and return its path."""
        class_els = ""
        for cls in classes:
            lines_xml = "".join(
                f'<line number="{ln}" hits="{hits}"/>'
                for ln, hits in cls["lines"].items()
            )
            class_els += (
                f'<class name="{cls["name"]}" filename="{cls["filename"]}">'
                f"<lines>{lines_xml}</lines></class>"
            )
        xml = (
            '<?xml version="1.0" ?>'
            "<coverage>"
            f"<sources><source>{source}</source></sources>"
            f"<packages><package name='.'><classes>{class_els}</classes></package></packages>"
            "</coverage>"
        )
        xml_path = tmp_path / "coverage.xml"
        xml_path.write_text(xml)
        return xml_path

    def test_nonexistent_file_returns_empty(self, tmp_path: Path) -> None:
        result = parse_cobertura_covered_lines(tmp_path / "missing.xml", tmp_path)
        assert result == {}

    def test_simple_xml_returns_covered_lines(self, tmp_path: Path) -> None:
        xml_path = self._write_xml(
            tmp_path,
            source=str(tmp_path),
            classes=[
                {
                    "name": "foo.py",
                    "filename": "src/foo.py",
                    "lines": {1: 1, 2: 1, 3: 0},
                }
            ],
        )
        result = parse_cobertura_covered_lines(xml_path, tmp_path)
        assert "src/foo.py" in result
        assert result["src/foo.py"] == {1, 2}

    def test_uncovered_lines_not_included(self, tmp_path: Path) -> None:
        xml_path = self._write_xml(
            tmp_path,
            source=str(tmp_path),
            classes=[
                {
                    "name": "bar.py",
                    "filename": "src/bar.py",
                    "lines": {5: 0, 6: 0},
                }
            ],
        )
        result = parse_cobertura_covered_lines(xml_path, tmp_path)
        # File with only uncovered lines has no covered lines to map
        assert result.get("src/bar.py", set()) == set()

    def test_multiple_files_in_xml(self, tmp_path: Path) -> None:
        xml_path = self._write_xml(
            tmp_path,
            source=str(tmp_path),
            classes=[
                {
                    "name": "a.py",
                    "filename": "src/a.py",
                    "lines": {1: 1, 2: 0},
                },
                {
                    "name": "b.py",
                    "filename": "src/b.py",
                    "lines": {10: 1, 11: 1},
                },
            ],
        )
        result = parse_cobertura_covered_lines(xml_path, tmp_path)
        assert result["src/a.py"] == {1}
        assert result["src/b.py"] == {10, 11}

    def test_malformed_xml_returns_empty(self, tmp_path: Path) -> None:
        xml_path = tmp_path / "bad.xml"
        xml_path.write_text("<not valid xml")
        result = parse_cobertura_covered_lines(xml_path, tmp_path)
        assert result == {}


# ---------------------------------------------------------------------------
# compute_uncovered_changed_lines
# ---------------------------------------------------------------------------


class TestComputeUncoveredChangedLines:
    def test_empty_changed_returns_empty(self) -> None:
        result = compute_uncovered_changed_lines({}, {"src/foo.py": {1, 2}})
        assert result == []

    def test_all_changed_lines_covered_returns_empty(self) -> None:
        changed = {"src/foo.py": {1, 2}}
        covered = {"src/foo.py": {1, 2, 3}}
        assert compute_uncovered_changed_lines(changed, covered) == []

    def test_uncovered_changed_lines_returned_as_path_colon_line(self) -> None:
        changed = {"src/foo.py": {1, 2, 3}}
        covered = {"src/foo.py": {1}}
        result = compute_uncovered_changed_lines(changed, covered)
        assert "src/foo.py:2" in result
        assert "src/foo.py:3" in result
        assert "src/foo.py:1" not in result

    def test_file_with_no_coverage_data_is_skipped(self) -> None:
        # If covered has no data for a file, we can't assert anything
        changed = {"src/new_module.py": {1, 2}}
        covered = {}  # no data for new_module.py
        result = compute_uncovered_changed_lines(changed, covered)
        assert result == []

    def test_results_are_sorted_by_path_then_line(self) -> None:
        changed = {"src/b.py": {3, 1}, "src/a.py": {2}}
        covered = {"src/a.py": set(), "src/b.py": set()}
        result = compute_uncovered_changed_lines(changed, covered)
        assert result == ["src/a.py:2", "src/b.py:1", "src/b.py:3"]
