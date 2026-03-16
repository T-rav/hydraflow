"""Tests for route_types — canonical parameter type aliases."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, get_args, get_origin

from src.route_types import RepoSlugParam


class TestRepoSlugParam:
    """Verify the canonical RepoSlugParam definition."""

    def test_is_annotated_type(self) -> None:
        assert get_origin(RepoSlugParam) is Annotated

    def test_base_type_is_optional_str(self) -> None:
        args = get_args(RepoSlugParam)
        # First arg is the base type (str | None)
        assert args[0] == str | None

    def test_query_description(self) -> None:
        args = get_args(RepoSlugParam)
        query = args[1]
        assert query.description == "Repo slug to scope the request"


class TestNoDuplicateAnnotatedAliases:
    """Guard against copy-pasting Annotated type aliases across modules.

    When a large module is split into a package, type aliases like
    ``RepoSlugParam = Annotated[...]`` tend to be duplicated instead of
    imported from the canonical location (``route_types.py``).

    This test scans all Python files under ``src/`` and flags any file
    (other than ``route_types.py``) that re-defines an alias already
    exported by ``route_types.py``.
    """

    # Pattern: ``SomeName = Annotated[`` or ``SomeName: TypeAlias = Annotated[``
    _ALIAS_RE = re.compile(
        r"^([A-Z]\w*)\s*(?::\s*TypeAlias\s*)?=\s*Annotated\s*\[",
        re.MULTILINE,
    )

    def _canonical_names(self) -> set[str]:
        """Return alias names defined in route_types.py."""
        source = Path("src/route_types.py").read_text()
        return {m.group(1) for m in self._ALIAS_RE.finditer(source)}

    def test_no_duplicate_route_param_aliases(self) -> None:
        canonical = self._canonical_names()
        assert canonical, "route_types.py should define at least one alias"

        src = Path("src")
        duplicates: list[str] = []
        for py_file in sorted(src.rglob("*.py")):
            if py_file.name == "route_types.py":
                continue
            content = py_file.read_text()
            for match in self._ALIAS_RE.finditer(content):
                name = match.group(1)
                if name in canonical:
                    duplicates.append(f"{py_file}:{name}")

        assert duplicates == [], (
            "Found duplicate Annotated aliases that should be imported "
            f"from route_types.py: {duplicates}"
        )
