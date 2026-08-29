"""The test-pyramid README's two tables agree with ``testing/standard.yaml``.

``docs/standards/testing/README.md`` is mostly how-to prose, which stays
prose. Two things in it are factual claims a machine can check: the three-layer
table (which layer lives where) and the "When each layer is required" matrix
(which layers a given change must ship). ``standard.yaml`` is the normative
encoding of both; the tables are commentary.

The matrix is where drift hurts. It is the thing CLAUDE.md's quick rule points
at when it says a load-bearing feature ships all three layers, and a row that
quietly relaxes — or a column that gets reordered under unchanged headers —
changes the merge bar with nothing going red.

So the assertions are agreements, not presence checks: the row set must match
in both directions, the column order must match the declared layer order, and
every cell must open with the symbol its declared status renders. Editing a
cell's ✅ to ⚠️ reddens; changing the YAML status without the cell reddens.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.architecture.standards_registry import repo_root

_STANDARD_DIR = Path("docs") / "standards" / "testing"

_LAYERS_BLOCK = ("<!-- standard:layers -->", "<!-- /standard:layers -->")
_REQUIREMENTS_BLOCK = (
    "<!-- standard:requirements -->",
    "<!-- /standard:requirements -->",
)

#: How a declared status renders in a matrix cell. The cell may say more after
#: the symbol ("✅ required (sNN scenario)"); it may not open with another one.
_STATUS_SYMBOL: dict[str, str] = {
    "required": "✅",
    "conditional": "⚠️",
    "not_required": "❌",
}

_FEATURE_SHAPE_HEADER = "Feature shape"


@pytest.fixture
def readme_text() -> str:
    return (repo_root() / _STANDARD_DIR / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def standard() -> dict[str, Any]:
    raw = yaml.safe_load(
        (repo_root() / _STANDARD_DIR / "standard.yaml").read_text(encoding="utf-8")
    )
    assert isinstance(raw, dict)
    return raw


def _block_rows(readme_text: str, block: tuple[str, str]) -> list[list[str]]:
    """Cells of every body row inside ``block``, header and rule excluded."""
    begin, end = block
    assert begin in readme_text and end in readme_text, (
        f"README is missing the {begin} block — the table it delimits is what "
        "standard.yaml is bound to"
    )
    body = readme_text.split(begin, 1)[1].split(end, 1)[0]
    rows: list[list[str]] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or set(stripped) <= set("|- "):
            continue
        rows.append([cell.strip() for cell in stripped.strip("|").split("|")])
    return rows


class TestLayerTable:
    def test_the_table_lists_exactly_the_declared_layers_in_order(
        self, readme_text: str, standard: dict[str, Any]
    ) -> None:
        rows = _block_rows(readme_text, _LAYERS_BLOCK)[1:]
        listed = [row[0] for row in rows]
        declared = [f"**{layer['label']}**" for layer in standard["layers"]]
        assert listed == declared

    def test_each_row_opens_with_the_declared_where_glob(
        self, readme_text: str, standard: dict[str, Any]
    ) -> None:
        rows = _block_rows(readme_text, _LAYERS_BLOCK)[1:]
        mismatched = {
            layer["id"]: row[1]
            for layer, row in zip(standard["layers"], rows, strict=True)
            if not row[1].startswith(f"`{layer['where']}`")
        }
        assert not mismatched, (
            "Where cell must open with the glob standard.yaml declares; "
            f"mismatched: {mismatched}"
        )


class TestRequirementsMatrix:
    def test_the_header_matches_the_declared_column_order(
        self, readme_text: str, standard: dict[str, Any]
    ) -> None:
        header = _block_rows(readme_text, _REQUIREMENTS_BLOCK)[0]
        expected = [_FEATURE_SHAPE_HEADER] + [
            layer["column"] for layer in standard["layers"]
        ]
        assert header == expected, (
            "matrix columns must read in the order standard.yaml declares its "
            "layers — reordering one side alone silently re-reads every cell"
        )

    def test_every_row_has_exactly_one_requirements_entry_and_vice_versa(
        self, readme_text: str, standard: dict[str, Any]
    ) -> None:
        listed = [row[0] for row in _block_rows(readme_text, _REQUIREMENTS_BLOCK)[1:]]
        declared = [entry["shape"] for entry in standard["requirements"]]
        assert listed == declared, (
            f"matrix rows {listed} vs standard.yaml shapes {declared} — only "
            f"in the README: {sorted(set(listed) - set(declared))}; only in "
            f"the YAML: {sorted(set(declared) - set(listed))}"
        )

    def test_each_cell_opens_with_the_symbol_its_declared_status_renders(
        self, readme_text: str, standard: dict[str, Any]
    ) -> None:
        rows = _block_rows(readme_text, _REQUIREMENTS_BLOCK)[1:]
        layer_ids = [layer["id"] for layer in standard["layers"]]
        disagreements: dict[tuple[str, str], tuple[str, str]] = {}
        for entry, row in zip(standard["requirements"], rows, strict=True):
            for index, layer_id in enumerate(layer_ids, start=1):
                status = entry[layer_id]
                symbol = _STATUS_SYMBOL[status]
                if not row[index].startswith(symbol):
                    disagreements[entry["shape"], layer_id] = (row[index], status)
        assert not disagreements, (
            "matrix cell does not render its declared status "
            f"(cell, declared): {disagreements} — "
            f"{_STATUS_SYMBOL}"
        )
