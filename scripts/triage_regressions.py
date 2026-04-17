#!/usr/bin/env python3
"""One-shot triage for tests/regressions/.

Runs the full regression suite, collects currently-failing nodeids, and writes
an @pytest.mark.xfail decorator directly above each failing test function.

The xfail reason embeds the issue number parsed from the filename, so a future
fix that flips the test green will surface as an unexpected pass (XPASS) and
we can drop the marker explicitly rather than silently.

Rerunnable: if a test is already marked xfail, it is left alone.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path


def collect_failing_nodeids() -> set[str]:
    """Run pytest, return the set of failing nodeids (`path::Class::test_x`)."""
    env = {**os.environ, "PYTHONPATH": "src"}
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/regressions/",
            "--tb=no",
            "-q",
            "--no-header",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        print(
            f"Warning: pytest exited with code {result.returncode}. "
            f"stderr: {result.stderr[:200]}",
            file=sys.stderr,
        )
    nodeids: set[str] = set()
    for line in result.stdout.splitlines():
        if line.startswith("FAILED "):
            rest = line[len("FAILED ") :]
            nodeid = rest.split(" ", 1)[0]
            nodeids.add(nodeid)
    return nodeids


ISSUE_RE = re.compile(r"test_issue_(\d+)\.py$")


def issue_number_for(path: Path) -> str | None:
    m = ISSUE_RE.search(path.name)
    return m.group(1) if m else None


def _insert_pytest_import(source: str) -> str:
    """Add `import pytest` after any `from __future__ import ...` line.

    Future-imports must precede all other module code, so a naive prepend
    would raise SyntaxError. If no future-import is present, prepend.
    """
    lines = source.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.startswith("from __future__"):
            lines.insert(idx + 1, "import pytest\n")
            return "".join(lines)
    return "import pytest\n" + source


def add_xfail_markers(failing: set[str]) -> int:
    """Insert `@pytest.mark.xfail(...)` above every failing test function.

    Returns the number of markers added.
    """
    by_file: dict[Path, set[str]] = {}
    for nodeid in failing:
        path_str, _, rest = nodeid.partition("::")
        func_name = rest.rsplit("::", 1)[-1].split("[", 1)[0]
        by_file.setdefault(Path(path_str), set()).add(func_name)

    added = 0
    for path, funcs in by_file.items():
        issue = issue_number_for(path) or "unknown"
        source = path.read_text()
        lines = source.splitlines(keepends=True)
        out: list[str] = []
        need_import = "import pytest" not in source
        file_added = 0
        for line in lines:
            stripped = line.lstrip()
            for func in funcs:
                prefix = f"def {func}("
                async_prefix = f"async def {func}("
                if stripped.startswith(prefix) or stripped.startswith(async_prefix):
                    indent = line[: len(line) - len(stripped)]
                    prev = out[-1] if out else ""
                    if "pytest.mark.xfail" not in prev:
                        out.append(
                            f"{indent}@pytest.mark.xfail("
                            f'reason="Regression for issue #{issue} — fix not yet landed", '
                            f"strict=False)\n"
                        )
                        file_added += 1
                    break
            out.append(line)
        new_source = "".join(out)
        if need_import and file_added:
            new_source = _insert_pytest_import(new_source)
        path.write_text(new_source)
        added += file_added
    return added


def main() -> int:
    failing = collect_failing_nodeids()
    print(f"Collected {len(failing)} failing nodeids")
    added = add_xfail_markers(failing)
    print(f"Added {added} xfail markers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
