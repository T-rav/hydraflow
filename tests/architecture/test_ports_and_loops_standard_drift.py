"""The ports-and-loops registry tables are an extract, not a hand list.

``docs/standards/ports-and-loops/README.md`` used to carry both registries by
hand. They had drifted: 9 ports listed against 10 live, 42 loops against 64,
and ``ObservabilityPort``'s fake recorded as ``FakeSentry``. Nothing went red,
because nothing was reading the tables.

The rows now come from the same extractors the coverage matrix reads, land
inside generated blocks, and are diffed by ``arch.runner --check`` — so
``make arch-check`` reddens on a hand edit and ``make arch-regen`` is the fix.

Four properties. The first runs the exact code path CI runs. The middle two
are the ones that would have caught the original drift — they compare the
committed table's membership against the live extractors rather than against
itself. The last is the vacuity guard: delete the block markers and the
generator must raise, because a generator with nowhere to write that returns
quietly is a staleness gate with no subject.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

from arch.extractors.loops import extract_loops
from arch.extractors.ports import extract_ports
from arch.generators.ports_and_loops_standard import (
    LOOP_REGISTRY_BLOCK,
    PORT_REGISTRY_BLOCK,
)
from arch.runner import (
    check_inline_blocks,
    emit_inline_blocks,
    substitute_blocks,
)
from tests.architecture.standards_registry import repo_root

_README = Path("docs") / "standards" / "ports-and-loops" / "README.md"
_DECLARATION = Path("docs") / "standards" / "ports-and-loops" / "standard.yaml"

#: Every registry row opens with the class name in backticks.
_ROW_NAME_RE = re.compile(r"^\|\s*`([A-Za-z0-9_]+)`\s*\|")


@pytest.fixture
def readme_text() -> str:
    return (repo_root() / _README).read_text(encoding="utf-8")


def _names_in_block(readme_text: str, block: tuple[str, str]) -> set[str]:
    begin, end = block
    assert begin in readme_text and end in readme_text, (
        f"{_README} is missing the {begin} block — the generator has nowhere "
        "to write and the table reverts to a hand list"
    )
    body = readme_text.split(begin, 1)[1].split(end, 1)[0]
    return {
        match.group(1)
        for match in (_ROW_NAME_RE.match(line) for line in body.splitlines())
        if match
    }


class TestTheStalenessGate:
    def test_the_committed_blocks_match_what_the_generator_renders(self) -> None:
        """The live ``make arch-check`` path, in process."""
        assert check_inline_blocks(repo_root=repo_root()) == 0, (
            "generated blocks in a standard are stale — run `make arch-regen`"
        )


class TestTheTablesCoverTheLiveTree:
    def test_the_port_registry_lists_exactly_the_live_ports(
        self, readme_text: str
    ) -> None:
        listed = _names_in_block(readme_text, PORT_REGISTRY_BLOCK)
        live = {
            port.name
            for port in extract_ports(
                src_dir=repo_root() / "src",
                fakes_dir=repo_root() / "src/mockworld/fakes",
            )
        }
        assert listed == live, (
            f"registry lists {sorted(listed - live)} that no longer exist and "
            f"omits {sorted(live - listed)}"
        )

    def test_the_loop_registry_lists_exactly_the_live_loops(
        self, readme_text: str
    ) -> None:
        listed = _names_in_block(readme_text, LOOP_REGISTRY_BLOCK)
        live = {loop.name for loop in extract_loops(repo_root() / "src")}
        assert listed == live, (
            f"registry lists {sorted(listed - live)} that no longer exist and "
            f"omits {sorted(live - listed)}"
        )


class TestTheGeneratorRefusesToWriteNowhere:
    def test_a_document_without_the_block_markers_raises(self) -> None:
        with pytest.raises(ValueError, match="missing"):
            substitute_blocks(
                "somewhere.md",
                "prose with no markers in it\n",
                {PORT_REGISTRY_BLOCK: "| Port |\n|---|\n"},
            )

    def test_a_declared_standard_with_no_block_is_drift_not_a_skip(
        self, tmp_path: Path
    ) -> None:
        """Fail-closed where the standard IS declared.

        Deleting the README, or just its markers, must not retire its own gate.
        The declaration is what makes this the enforced case; without it the
        check cannot tell a broken tree from one that never shipped the
        standard.
        """
        declaration = tmp_path / _DECLARATION
        declaration.parent.mkdir(parents=True)
        declaration.write_text("id: ports-and-loops\n", encoding="utf-8")

        assert check_inline_blocks(repo_root=tmp_path) == 1, (
            "a tree that declares the standard but has no host document is stale"
        )

        (tmp_path / _README).write_text("prose, no markers\n", encoding="utf-8")
        assert check_inline_blocks(repo_root=tmp_path) == 1, (
            "a declared standard whose markers were deleted is stale too — "
            "otherwise deleting the markers silently retires the generator"
        )

    def test_an_undeclared_standard_with_no_block_is_skipped(
        self, tmp_path: Path
    ) -> None:
        """A tree that never shipped the standard has nothing to be stale about.

        This is the s34 condition: ``DiagramLoop`` regenerates inside an
        ephemeral worktree branched off the BASE commit, which predates the
        block. Same shape for a child repo stamped before the block existed.
        Writing a block there would invent a standard the tree has not adopted;
        erroring would fail every such regen.
        """
        readme = tmp_path / _README
        readme.parent.mkdir(parents=True)
        readme.write_text("prose, no markers\n", encoding="utf-8")

        assert check_inline_blocks(repo_root=tmp_path) == 0
        assert emit_inline_blocks(repo_root=tmp_path) == []
        assert readme.read_text(encoding="utf-8") == "prose, no markers\n", (
            "an undeclared standard must be left alone, not written into"
        )

    def test_emit_raises_when_a_declared_standard_lost_its_markers(
        self, tmp_path: Path
    ) -> None:
        declaration = tmp_path / _DECLARATION
        declaration.parent.mkdir(parents=True)
        declaration.write_text("id: ports-and-loops\n", encoding="utf-8")
        (tmp_path / _README).write_text("prose, no markers\n", encoding="utf-8")

        with pytest.raises(ValueError, match="missing"):
            emit_inline_blocks(repo_root=tmp_path)

    def test_this_repo_declares_the_standard_so_the_guard_is_live_here(
        self,
    ) -> None:
        """The skip path must not be silently covering this repo.

        Without this, deleting ``standard.yaml`` would leave every property
        above passing while the generator quietly stopped enforcing anything —
        the defect class this branch exists to close.
        """
        assert (repo_root() / _DECLARATION).is_file()

    def test_a_document_with_the_markers_receives_the_body(self) -> None:
        begin, end = PORT_REGISTRY_BLOCK
        result = substitute_blocks(
            "somewhere.md",
            f"before\n{begin}\nstale\n{end}\nafter\n",
            {PORT_REGISTRY_BLOCK: "fresh"},
        )
        assert result == f"before\n{begin}\nfresh\n{end}\nafter\n"


class TestRegenConvergesInOnePass:
    """`make arch-regen` must settle the tree, not leave it half-stale.

    `coverage_matrix.py` greps `docs/standards/**` for every loop and port
    name, and the ports-and-loops registry is a generated block inside that
    tree. So the blocks have to be written BEFORE the artifacts that read
    them. With the order reversed the matrix is computed against the previous
    registry, one regen leaves the tree stale, `arch-check` stays red, and the
    bot heals that run regen once and commit would ship the staleness they
    exist to remove. Found for real merging #11759's
    `RailsDriftCaretakerLoop` -> `CharterDriftCaretakerLoop` rename.
    """

    def test_inline_blocks_are_emitted_before_the_artifacts_that_read_them(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from arch import runner

        order: list[str] = []
        monkeypatch.setattr(
            runner, "emit_inline_blocks", lambda **_: (order.append("blocks"), [])[1]
        )
        monkeypatch.setattr(runner, "emit", lambda **_: order.append("artifacts"))
        monkeypatch.setattr(runner, "sync_traceability_baseline", lambda _: False)
        monkeypatch.setattr(
            sys, "argv", ["arch.runner", "--emit", "--repo-root", str(tmp_path)]
        )

        assert runner._main() == 0
        assert order == ["blocks", "artifacts"], (
            "docs/standards blocks must be written before docs/arch/generated "
            "is computed — the matrix reads the registry, so the reverse order "
            "needs two regens to converge and leaves arch-check red after one"
        )

    def test_transposed_markers_raise_instead_of_duplicating_the_document(
        self,
    ) -> None:
        """END before BEGIN passes both `in` checks and used to corrupt.

        The slice arithmetic ran with ``stop < start`` and DUPLICATED the
        document rather than replacing a region, so `--emit` wrote the
        corruption, each later regen grew it, and `--check` could never
        converge. The absent-marker guard cannot see this shape — both markers
        are present.
        """
        begin, end = PORT_REGISTRY_BLOCK
        transposed = f"{end}\nmiddle\n{begin}\ntail"

        with pytest.raises(ValueError, match="transposed"):
            substitute_blocks("x.md", transposed, {PORT_REGISTRY_BLOCK: "body"})
