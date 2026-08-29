"""Every standard has a resolvable id and cites a gate that actually runs.

Three properties, and each one exists because the cheaper version of it is
satisfiable by something that is not true:

1. **Ids resolve.** ``charter.yaml``'s ``articles.standards`` entries (#11748)
   point at standards by id. An id that names no directory — or a directory
   that declares no id — is a declaration with no subject.
2. **The README and ``standard.yaml`` are one set.** The block in the README
   is commentary; the YAML is normative. Editing either alone reddens here,
   in both directions, which is the ``test_factory_autonomy_policy_drift``
   shape.
3. **A cited gate is collected by pytest.** "The file exists" is the weak
   version and this repo has a week of receipts on what it buys: a check that
   has stopped running goes on passing. So the citation is answered by asking
   pytest what it collects, and ``test_a_module_pytest_does_not_collect_is_not
   _reported_as_collected`` is the control that proves the answer comes from
   collection rather than from the path resolving.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from tests.architecture.standards_registry import (
    ENFORCED_BY_BEGIN,
    Standard,
    has_enforced_by_block,
    readme_enforced_by,
    registered_standards,
    repo_root,
    standard_directories,
)

#: ``pytest --collect-only -q`` prints one ``<path>: <count>`` line per file
#: that yielded collected (and not deselected) tests.
_COLLECTED_RE = re.compile(r"^(\S+\.py): (\d+)$")

#: A file that resolves but that pytest collects nothing from. Used as the
#: negative control: it is a real module in this very package, so "the path
#: exists" answers yes for it while "pytest collects it" answers no.
_UNCOLLECTED_CONTROL = "tests/architecture/standards_registry.py"


@dataclass(frozen=True, slots=True)
class Collection:
    """What pytest said it would collect, and the raw run for diagnostics."""

    counts: dict[str, int]
    returncode: int
    output: str

    def collects(self, path: str) -> bool:
        return self.counts.get(path, 0) > 0


@cache
def _collect(paths: tuple[str, ...]) -> Collection:
    """Ask the live pytest which of ``paths`` it collects.

    Deliberately the real collector rather than a model of it: ``python_files``
    globs, ``testpaths``, the ``addopts`` marker deselection and an import-time
    error are all things a re-implementation would have to mirror and would
    eventually mirror wrongly. Cached so the properties below share one spawn.
    """
    root = repo_root()
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
            *paths,
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(root / "src")},
        capture_output=True,
        text=True,
        check=False,
        timeout=600,
    )
    counts: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        match = _COLLECTED_RE.match(line.strip())
        if match:
            counts[match.group(1)] = int(match.group(2))
    return Collection(
        counts=counts,
        returncode=proc.returncode,
        output=(proc.stdout + proc.stderr)[-4000:],
    )


def _all_cited_paths(standards: Sequence[Standard]) -> tuple[str, ...]:
    seen: list[str] = []
    for standard in standards:
        for path in standard.enforced_by:
            if path not in seen:
                seen.append(path)
    return tuple(seen)


class TestIdsResolve:
    def test_every_standard_directory_declares_a_standard_yaml(self) -> None:
        # registered_standards() raises StandardsRegistryError on a directory
        # with no standard.yaml, so this is the load itself.
        declared = {standard.directory for standard in registered_standards()}
        assert declared == set(standard_directories())

    def test_every_declared_id_equals_its_directory_name(self) -> None:
        mismatched = {
            standard.directory: standard.id
            for standard in registered_standards()
            if standard.id != standard.directory
        }
        assert not mismatched, (
            f"standard.yaml `id` must equal its directory name: {mismatched} — "
            "charter.yaml resolves articles.standards entries against the "
            "directory, so an id that differs resolves to nothing"
        )


class TestReadmeAndYamlAreOneSet:
    def test_every_readme_carries_an_enforced_by_block(self) -> None:
        missing = [
            standard.directory
            for standard in registered_standards()
            if not has_enforced_by_block(standard)
        ]
        assert not missing, (
            f"README.md with no {ENFORCED_BY_BEGIN} block: {missing} — without "
            "it an empty citation list and an absent one look identical"
        )

    def test_the_readme_block_cites_exactly_what_standard_yaml_declares(
        self,
    ) -> None:
        disagreements: dict[str, tuple[list[str], list[str]]] = {}
        for standard in registered_standards():
            cited = list(readme_enforced_by(standard))
            declared = list(standard.enforced_by)
            if cited != declared:
                disagreements[standard.directory] = (cited, declared)
        assert not disagreements, (
            "README `Enforced by` block disagrees with standard.yaml "
            f"`enforced_by` (README, standard.yaml): {disagreements} — "
            "standard.yaml is normative; update the README to match, or the "
            "other way round if the YAML is what went stale"
        )


class TestCitedGatesActuallyRun:
    def test_every_cited_enforcer_path_exists(self) -> None:
        missing = {
            standard.directory: [
                path
                for path in standard.enforced_by
                if not (repo_root() / path).is_file()
            ]
            for standard in registered_standards()
        }
        missing = {k: v for k, v in missing.items() if v}
        assert not missing, f"standard.yaml cites paths that do not exist: {missing}"

    def test_every_cited_enforcer_is_collected_by_pytest(self) -> None:
        standards = registered_standards()
        cited = _all_cited_paths(standards)
        if not cited:  # pragma: no cover - only before the first binding lands
            return
        collection = _collect(cited)
        uncollected = {
            standard.directory: [
                path for path in standard.enforced_by if not collection.collects(path)
            ]
            for standard in standards
        }
        uncollected = {k: v for k, v in uncollected.items() if v}
        assert not uncollected, (
            f"standard.yaml cites gates pytest does not collect: {uncollected} "
            "— a gate that never runs is a citation to nothing. "
            f"pytest rc={collection.returncode}\n{collection.output}"
        )

    def test_a_module_pytest_does_not_collect_is_not_reported_as_collected(
        self,
    ) -> None:
        """The control: the check must read collection, not path resolution.

        ``standards_registry.py`` exists on disk and imports cleanly, so an
        existence check answers yes for it. pytest collects nothing from it,
        and this property is what proves the property above is asking pytest
        rather than asking the filesystem.
        """
        control = Path(_UNCOLLECTED_CONTROL)
        assert (repo_root() / control).is_file()
        collection = _collect((_UNCOLLECTED_CONTROL,))
        assert not collection.collects(_UNCOLLECTED_CONTROL)
