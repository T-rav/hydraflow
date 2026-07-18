"""Drift CI binding the factory-autonomy README table to policy.yaml (CH-3, #9731).

Two writers, one set (same pattern as the ADR/term drift tests): the prose
act-vs-ask table in ``docs/standards/factory_autonomy/README.md`` is
commentary; ``policy.yaml`` in the same directory is the normative encoding
enforced at the factory's merge seams (``src/merge_policy.py``). Every table
row must have exactly one policy entry (matched on ``readme_row``) and vice
versa, each row's Action-column direction must agree with the entry's
``autonomy``, and the README must carry the normative-policy marker section.
Editing one surface without the other reddens CI here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from merge_policy import AUTONOMY_ACT, AUTONOMY_ASK, MergePolicy, load_merge_policy

_STANDARD_DIR = Path("docs") / "standards" / "factory_autonomy"

# A table body row whose first cell opens with a bold row name:
# ``| **Tractable + reversible** — act, then report | ... | ... |``
_TABLE_ROW_RE = re.compile(r"^\|\s*\*\*(?P<row>[^*]+?)\*\*")

# The Action-column phrase that marks a row as requiring consent (ask).
_ASK_MARKER = "Confirm before acting"


@pytest.fixture
def readme_text(real_repo_root: Path) -> str:
    return (real_repo_root / _STANDARD_DIR / "README.md").read_text(encoding="utf-8")


@pytest.fixture
def policy(real_repo_root: Path) -> MergePolicy:
    return load_merge_policy(real_repo_root / _STANDARD_DIR / "policy.yaml")


def _table_rows(readme_text: str) -> dict[str, str]:
    """Return ``{bold row name: action cell}`` for every act-vs-ask table row."""
    rows: dict[str, str] = {}
    for line in readme_text.splitlines():
        match = _TABLE_ROW_RE.match(line.strip())
        if not match:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        rows[match.group("row").strip()] = cells[-1]
    return rows


class TestTableAndPolicyAreOneSet:
    def test_every_readme_row_has_a_policy_entry_and_vice_versa(
        self, readme_text: str, policy: MergePolicy
    ) -> None:
        readme_rows = set(_table_rows(readme_text))
        policy_rows = {entry.readme_row for entry in policy.entries}
        assert readme_rows, "act-vs-ask table not found in the README"
        missing_in_policy = readme_rows - policy_rows
        missing_in_readme = policy_rows - readme_rows
        assert not missing_in_policy, (
            f"README table row(s) with no policy.yaml entry: "
            f"{sorted(missing_in_policy)} — add an entry with a matching "
            "readme_row (policy.yaml is normative; the table is commentary)"
        )
        assert not missing_in_readme, (
            f"policy.yaml entr(y/ies) with no README table row: "
            f"{sorted(missing_in_readme)} — document the class in the "
            "README's act-vs-ask table"
        )

    def test_each_rows_action_direction_matches_the_entrys_autonomy(
        self, readme_text: str, policy: MergePolicy
    ) -> None:
        rows = _table_rows(readme_text)
        for entry in policy.entries:
            action_cell = rows[entry.readme_row]
            expected = AUTONOMY_ASK if _ASK_MARKER in action_cell else AUTONOMY_ACT
            assert entry.autonomy == expected, (
                f"policy entry {entry.id!r} declares autonomy="
                f"{entry.autonomy!r} but the README row "
                f"{entry.readme_row!r} action column reads as {expected!r}"
            )


class TestNormativeMarker:
    def test_readme_declares_policy_yaml_normative(self, readme_text: str) -> None:
        assert "## Machine-readable policy (normative)" in readme_text
        assert "policy.yaml" in readme_text

    def test_readme_documents_break_glass_and_kill_switch(
        self, readme_text: str, policy: MergePolicy
    ) -> None:
        assert policy.break_glass_label_prefix in readme_text
        assert "merge_policy_enabled" in readme_text


class TestPolicySchema:
    def test_packaged_policy_is_schema_valid(self, policy: MergePolicy) -> None:
        """Loading via load_merge_policy IS the schema validation — a schema
        change without a matching policy.yaml update fails here."""
        assert policy.entries
        assert policy.entry(policy.unapproved_merge_class).autonomy == AUTONOMY_ASK
