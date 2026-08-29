"""The kernel index and the stamper ship the same set of standards.

``docs/standards/factory_operation/README.md`` is the index doc: its job is to
say which standards a HydraFlow-format repo gets. ``STANDARDS_DIRS`` in
``src/onboarding/kernel_writer.py`` is what the stamper actually copies. Those
are two writers of one set, and until now nothing made them agree — the table
listed ``ports-and-loops`` twice, omitted ``adr_enforcement`` and
``factory_operation``, and called itself "the four kernel standards" while
holding six rows.

Three properties, and the third is what stops the first two from being
satisfiable by deletion:

1. The kernel table names exactly ``STANDARDS_DIRS``.
2. The "stays here" table names exactly the complement — every standard
   directory that is not stamped.
3. Together they partition ``docs/standards/``, so a new standard directory
   cannot appear in neither table.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from onboarding.kernel_writer import STANDARDS_DIRS
from tests.architecture.standards_registry import (
    repo_root,
    standard_directories,
)

_README = Path("docs") / "standards" / "factory_operation" / "README.md"

_KERNEL_BLOCK = ("<!-- standards:kernel -->", "<!-- /standards:kernel -->")
_LOCAL_BLOCK = ("<!-- standards:local -->", "<!-- /standards:local -->")

#: Every row links its standard as ``../<id>/README.md``. The id is the link
#: target, not the bolded display name, so a row cannot claim a standard it
#: does not actually point at.
_LINKED_ID_RE = re.compile(r"\.\./([A-Za-z0-9_-]+)/README\.md")


@pytest.fixture
def readme_text() -> str:
    return (repo_root() / _README).read_text(encoding="utf-8")


def _linked_ids(readme_text: str, block: tuple[str, str]) -> set[str]:
    begin, end = block
    assert begin in readme_text and end in readme_text, (
        f"{_README} is missing the {begin} block — the table it delimits is "
        "what binds this index to the stamper"
    )
    body = readme_text.split(begin, 1)[1].split(end, 1)[0]
    return set(_LINKED_ID_RE.findall(body))


class TestKernelTableMatchesTheStamper:
    def test_the_kernel_table_names_exactly_what_the_stamper_ships(
        self, readme_text: str
    ) -> None:
        listed = _linked_ids(readme_text, _KERNEL_BLOCK)
        shipped = set(STANDARDS_DIRS)
        assert listed == shipped, (
            f"kernel table lists {sorted(listed)} but STANDARDS_DIRS ships "
            f"{sorted(shipped)} — only in the table: "
            f"{sorted(listed - shipped)}; only in STANDARDS_DIRS: "
            f"{sorted(shipped - listed)}"
        )

    def test_the_local_table_names_exactly_the_unstamped_standards(
        self, readme_text: str
    ) -> None:
        listed = _linked_ids(readme_text, _LOCAL_BLOCK)
        unstamped = set(standard_directories()) - set(STANDARDS_DIRS)
        assert listed == unstamped, (
            f"'stays here' table lists {sorted(listed)} but the unstamped "
            f"standards are {sorted(unstamped)} — only in the table: "
            f"{sorted(listed - unstamped)}; unlisted: "
            f"{sorted(unstamped - listed)}"
        )

    def test_the_two_tables_partition_every_standard_directory(
        self, readme_text: str
    ) -> None:
        kernel = _linked_ids(readme_text, _KERNEL_BLOCK)
        local = _linked_ids(readme_text, _LOCAL_BLOCK)
        assert not kernel & local, (
            f"standard(s) in both tables: {sorted(kernel & local)} — a "
            "standard is either stamped into child repos or it is not"
        )
        assert kernel | local == set(standard_directories()), (
            "the two tables must cover docs/standards/ exactly; unlisted: "
            f"{sorted(set(standard_directories()) - (kernel | local))}; "
            f"listed but absent from disk: "
            f"{sorted((kernel | local) - set(standard_directories()))}"
        )
