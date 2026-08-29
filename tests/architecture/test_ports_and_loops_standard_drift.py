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
from arch.runner import check_inline_blocks, substitute_blocks
from tests.architecture.standards_registry import repo_root

_README = Path("docs") / "standards" / "ports-and-loops" / "README.md"

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

    def test_a_missing_host_document_is_drift_not_a_skip(self, tmp_path: Path) -> None:
        """Fail-closed: deleting the README must not retire its own gate.

        ``emit`` skips a document that is not there (synthetic trees, partial
        stamps); ``check`` must not, or the staleness gate stops having a
        subject the moment somebody removes the file it watches.
        """
        assert check_inline_blocks(repo_root=tmp_path) == 1

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
