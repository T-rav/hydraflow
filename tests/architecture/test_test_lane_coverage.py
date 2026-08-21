"""Guard: every test file a pytest lane ``--ignore``s is run by some other lane.

``make quality``'s main pytest lane excludes files that are xdist-unsafe
(``PYTEST_SERIAL_PATHS``), host-exclusive (``PYTEST_HOST_EXCLUSIVE_PATHS``) or
owned by the gateway coverage lane (``GATEWAY_PACKAGE_TEST_PATHS``), and CI
repeats the split by hand ("keep in sync with the Makefile"). An exclusion
that nobody re-runs is a test that silently stopped counting — the same
failure shape as ``tests/test_ci_path_filter_completeness.py``, one level
down. This guard expands every pytest invocation in the Makefile and the CI
workflows (resolving ``$(VAR)``, ``$(addprefix …)``, ``$(filter-out …)`` and
``$(wildcard …)``) and asserts each ignored file appears positionally in at
least one lane that does not ignore it.
"""

from __future__ import annotations

import re
from pathlib import Path

_MAKE_ASSIGN = re.compile(r"^([A-Z][A-Z0-9_]*)\s*[:?]?=\s*(.*)$")
_MAKE_FUNC = re.compile(r"\$\((addprefix|filter-out|wildcard)\s+([^()$]*)\)")
_MAKE_VAR = re.compile(r"\$\(([A-Za-z_][A-Za-z0-9_]*)\)")
_IGNORE_FLAG = "--ignore="


def _joined_lines(text: str) -> list[str]:
    """Makefile/YAML text with backslash continuations folded into one line."""
    out: list[str] = []
    buffer = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            buffer += line[:-1] + " "
            continue
        out.append(buffer + line)
        buffer = ""
    if buffer:
        out.append(buffer)
    return out


def _make_variables(lines: list[str]) -> dict[str, str]:
    variables: dict[str, str] = {}
    for line in lines:
        if line.startswith("\t") or line.lstrip().startswith("#"):
            continue
        match = _MAKE_ASSIGN.match(line)
        if match:
            variables[match.group(1)] = match.group(2).split(" #")[0].strip()
    return variables


def _expand(text: str, variables: dict[str, str], repo_root: Path) -> str:
    """Expand make variables and the three list functions the lanes use."""
    for _ in range(20):
        before = text

        def _func(match: re.Match[str]) -> str:
            name, args = match.group(1), match.group(2)
            if name == "wildcard":
                return " ".join(
                    sorted(
                        p.relative_to(repo_root).as_posix()
                        for p in repo_root.glob(args.strip())
                    )
                )
            prefix, _, rest = args.partition(",")
            if name == "addprefix":
                return " ".join(prefix + tok for tok in rest.split())
            drop = set(prefix.split())
            return " ".join(tok for tok in rest.split() if tok not in drop)

        text = _MAKE_FUNC.sub(_func, text)
        text = _MAKE_VAR.sub(lambda m: variables.get(m.group(1), ""), text)
        if text == before:
            break
    return text


def _pytest_lanes(repo_root: Path) -> list[tuple[str, list[str]]]:
    """Every ``pytest`` invocation as (origin, tokens), fully expanded."""
    lanes: list[tuple[str, list[str]]] = []
    make_lines = _joined_lines((repo_root / "Makefile").read_text(encoding="utf-8"))
    variables = _make_variables(make_lines)
    sources = [("Makefile", make_lines)]
    for workflow in sorted((repo_root / ".github" / "workflows").glob("*.yml")):
        sources.append(
            (workflow.name, _joined_lines(workflow.read_text(encoding="utf-8")))
        )
    for origin, lines in sources:
        for line in lines:
            if "pytest" not in line or line.lstrip().startswith("#"):
                continue
            expanded = _expand(line, variables, repo_root)
            for segment in re.split(r"&&|\|\||;|\s&\s", expanded):
                tokens = segment.split()
                if "pytest" in tokens:
                    lanes.append((origin, tokens[tokens.index("pytest") + 1 :]))
    return lanes


def _ignored_files(lanes: list[tuple[str, list[str]]], repo_root: Path) -> set[str]:
    ignored: set[str] = set()
    for _origin, tokens in lanes:
        for tok in tokens:
            if tok.startswith(_IGNORE_FLAG):
                pattern = tok[len(_IGNORE_FLAG) :]
                matches = list(repo_root.glob(pattern))
                if not matches:
                    continue
                for path in matches:
                    if path.is_file():
                        ignored.add(path.relative_to(repo_root).as_posix())
    return ignored


def _lane_runs(tokens: list[str], file: str) -> bool:
    """True when *tokens* names *file* (or an ancestor dir) positionally and does not ignore it.

    A lane that deselects by marker or keyword (``-m`` / ``-k``) never counts:
    pytest would collect the file and then select zero tests from it unless
    the file happens to carry the marker, which this guard cannot see.
    """
    if any(t in {"-m", "-k"} or t.startswith(("-m=", "-k=")) for t in tokens):
        return False
    positional = [t for t in tokens if not t.startswith("-") and t.startswith("tests")]
    ignores = [
        t[len(_IGNORE_FLAG) :].rstrip("/") for t in tokens if t.startswith(_IGNORE_FLAG)
    ]
    if any(file == ig or file.startswith(ig + "/") for ig in ignores):
        return False
    for tok in positional:
        base = tok.rstrip("/")
        if file == base or file.startswith(base + "/"):
            return True
    return False


def test_marker_filtered_lane_is_not_credited_as_coverage() -> None:
    assert _lane_runs(["tests/", "-q"], "tests/test_x.py")
    assert not _lane_runs(
        ["tests/scenarios/", "-m", "scenario_loops"], "tests/scenarios/test_x.py"
    )
    assert not _lane_runs(["tests/", "-k", "smoke"], "tests/test_x.py")
    assert not _lane_runs(["tests/", "--ignore=tests/test_x.py"], "tests/test_x.py")


def test_every_ignored_test_file_runs_in_some_lane(real_repo_root: Path) -> None:
    lanes = _pytest_lanes(real_repo_root)
    assert lanes, "no pytest invocations found — the parser is broken, not the Makefile"
    ignored = _ignored_files(lanes, real_repo_root)
    assert ignored, (
        "no --ignore'd test files found — the parser is broken, not the Makefile"
    )

    uncovered = sorted(
        file
        for file in ignored
        if not any(_lane_runs(tokens, file) for _, tokens in lanes)
    )
    assert not uncovered, (
        "Test file(s) are --ignore'd by a pytest lane and never run positionally by any "
        "other lane in the Makefile or .github/workflows — they silently stopped counting:\n  "
        + "\n  ".join(uncovered)
        + "\n\nEither add the file to the lane that owns it (PYTEST_SERIAL_PATHS / "
        "PYTEST_HOST_EXCLUSIVE_PATHS / GATEWAY_PACKAGE_TEST_PATHS) or drop the --ignore."
    )
