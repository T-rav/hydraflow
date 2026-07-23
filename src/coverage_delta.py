"""Pure functions for coverage-delta cross-checking.

Compares the set of lines changed in a branch diff against the lines
exercised by the test suite (from a Cobertura XML report) to produce a
deterministic list of changed lines that have no test coverage.
"""

from __future__ import annotations

import re
from pathlib import Path
from xml.etree import ElementTree


def parse_diff_changed_lines(diff: str) -> dict[str, set[int]]:
    """Parse added lines from a unified diff.

    Returns a mapping from repo-relative file path to the set of
    line numbers added/changed in that file.  Skips test files (paths
    starting with ``tests/``).
    """
    result: dict[str, set[int]] = {}
    current_file: str | None = None
    current_new_line: int = 0

    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:]
            if path.startswith("tests/"):
                current_file = None
            else:
                current_file = path
                result.setdefault(current_file, set())
        elif line.startswith("+++ "):
            # +++ /dev/null or other non-repo target — reset
            current_file = None
        elif line.startswith("diff --git "):
            current_file = None
        elif line.startswith("@@ "):
            match = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if match and current_file is not None:
                current_new_line = int(match.group(1))
        elif current_file is not None:
            if line.startswith("+"):
                result[current_file].add(current_new_line)
                current_new_line += 1
            elif line.startswith("-"):
                pass  # deleted line — no advance on new-file counter
            else:
                current_new_line += 1  # context line

    return {path: lines for path, lines in result.items() if lines}


def parse_cobertura_covered_lines(
    xml_path: Path,
    repo_root: Path,
) -> dict[str, set[int]]:
    """Parse a Cobertura coverage XML into a repo-relative covered-lines map.

    Normalises absolute source paths from ``<source>`` elements combined
    with ``filename`` attributes on ``<class>`` elements into paths relative
    to *repo_root*.  Lines with ``hits > 0`` are considered covered.
    """
    if not xml_path.is_file():
        return {}

    try:
        tree = ElementTree.parse(xml_path)  # noqa: S314  # nosec B314
    except ElementTree.ParseError:
        return {}

    root = tree.getroot()

    source_roots: list[Path] = []
    for source in root.findall(".//sources/source"):
        if source.text:
            source_roots.append(Path(source.text.strip()))

    result: dict[str, set[int]] = {}
    resolved_repo = repo_root.resolve()

    for cls in root.findall(".//class"):
        filename = cls.get("filename", "")
        if not filename:
            continue

        rel_path: str | None = None
        for src_root in source_roots:
            abs_path = (src_root / filename).resolve()
            try:
                rel_path = str(abs_path.relative_to(resolved_repo))
                break
            except ValueError:
                continue

        if rel_path is None:
            rel_path = filename

        covered: set[int] = set()
        for line_elem in cls.findall(".//line"):
            if int(line_elem.get("hits", "0")) > 0:
                number = int(line_elem.get("number", "0"))
                if number > 0:
                    covered.add(number)

        if covered:
            result.setdefault(rel_path, set()).update(covered)

    return result


def compute_uncovered_changed_lines(
    changed: dict[str, set[int]],
    covered: dict[str, set[int]],
) -> list[str]:
    """Return ``path:line`` strings for changed lines absent from the covered set.

    A changed line is "uncovered" only when its file appears in *covered*
    (meaning coverage data was collected for it) but the specific line number
    is missing from that file's covered set.  Files absent from *covered*
    are skipped — no data means we cannot make an assertion.
    """
    uncovered: list[str] = []
    for path, lines in sorted(changed.items()):
        if path not in covered:
            continue
        file_covered = covered[path]
        for line in sorted(lines):
            if line not in file_covered:
                uncovered.append(f"{path}:{line}")
    return uncovered
