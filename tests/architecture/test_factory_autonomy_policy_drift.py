"""Drift CI binding the factory-autonomy README table to the charter (CH-3, #9731).

Two writers, one set (same pattern as the ADR/term drift tests): the prose
act-vs-ask table in ``docs/standards/factory_autonomy/README.md`` is
commentary; ``charter.yaml``'s ``policy:`` section is the normative encoding
enforced at the factory's merge seams (``src/merge_policy.py``) since #12116. Every table
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
    # This repo's GOVERNING copy, not the shipped default (#12116): the README
    # describes how HydraFlow governs itself, so the binding has to be against
    # the file that actually decides. `test_shipped_default_matches_the_charter`
    # holds the packaged seed to this same section, so the standard HydraFlow
    # ships and the standard HydraFlow runs stay one table.
    return load_merge_policy(real_repo_root / "charter.yaml")


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
            f"README table row(s) with no charter policy entry: "
            f"{sorted(missing_in_policy)} — add an entry with a matching "
            "readme_row (the charter is normative; the table is commentary)"
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
    def test_readme_points_at_the_file_that_actually_decides(
        self, readme_text: str, real_repo_root: Path
    ) -> None:
        """The README must name the charter, and every path it cites must exist.

        This asserted the bare substring `"policy.yaml"` — which #12116 left
        passing on a dead relative link to a deleted file, since the string
        still appeared in the prose describing it. A marker test that survives
        the thing it marks going away is not marking anything.

        So it checks the pointer, and then resolves every repo path the section
        mentions. A broken link in the one document `CLAUDE.md` sends an
        operator to for autonomy policy is worse than no document.
        """
        assert "## Machine-readable policy (normative)" in readme_text
        assert "charter.yaml" in readme_text, (
            "the README does not name charter.yaml, which is what "
            "config.merge_policy_path resolves to for this repo"
        )

        cited = set(re.findall(r"`([a-z0-9_./]+\.(?:yaml|py))`", readme_text))
        missing = sorted(
            path
            for path in cited
            if "/" in path and not (real_repo_root / path).exists()
        )

        assert not missing, f"README cites paths that do not exist: {missing}"

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
