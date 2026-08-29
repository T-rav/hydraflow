"""Render the ports-and-loops standard's two registry tables from source.

``docs/standards/ports-and-loops/README.md`` states a structural contract and
then lists, by hand, every port and every loop that has to satisfy it. The
requirement tables are the contract and stay prose. The two *registry* tables
are an inventory, and an inventory maintained by hand is the most likely
silent-drift site in the repo — when this generator was written the hand
tables listed 9 ports against 10 live ones and 42 loops against 64, and named
``FakeSentry`` as ``ObservabilityPort``'s fake, which it has not been for some
time.

So the registry rows are generated here from the same extractors the coverage
matrix reads, written into delimited blocks in the README, and diffed by
``arch.runner --check``. Hand-editing a row now fails ``make arch-check``, and
``make arch-regen`` is the fix — the same loop the rest of
``docs/arch/generated/`` already runs on.

Every column is DERIVED, deliberately, because a hand-maintained column inside
a generated table would drift exactly the way the whole table used to:

- Module / Fake / Tick come straight off the extractors.
- ADR is a scan of ``docs/adr/*.md`` for the port or loop name, minus the
  roll-call ADRs that name every loop (``ADR_EXCLUDED_REFS``).
- Wiki term is resolved through the term files' own ``name:`` frontmatter
  rather than by transforming the class name into a filename — a name
  transform is a guess about a convention, and this is the convention's own
  declaration.

Known consequence: ``coverage_matrix.py``'s Standard column greps
``docs/standards/**/*.md`` for each loop and port name, so generating a
complete registry here turns that column ✅ for every row. That is not the
column going vacuous by accident — the requirement it tracked ("this item has
a row in the standard") is now satisfied by construction, which was the point.
Nothing gates on the column, and repointing or retiring it is a separate
decision about the coverage matrix.
"""

from __future__ import annotations

import re
from pathlib import Path

from arch._models import LoopInfo, PortInfo
from arch.generators.coverage_matrix import ADR_EXCLUDED_REFS

#: Delimiters of the generated blocks inside the standard's README.
PORT_REGISTRY_BLOCK = (
    "<!-- generated:port-registry -->",
    "<!-- /generated:port-registry -->",
)
LOOP_REGISTRY_BLOCK = (
    "<!-- generated:loop-registry -->",
    "<!-- /generated:loop-registry -->",
)

#: Rendered when a derived cell has nothing to report. One glyph, so a reader
#: scanning the column sees the gaps.
_ABSENT = "—"

_ADR_NUMBER_RE = re.compile(r"^(\d+)-")
_TERM_NAME_RE = re.compile(r'^name:\s*"?([^"\n]+?)"?\s*$', re.MULTILINE)

_PORT_HEADER = "| Port | Module | Fake | ADR | Wiki term |\n|---|---|---|---|---|"
_LOOP_HEADER = "| Loop | Module | Tick (s) | ADR | Wiki term |\n|---|---|---|---|---|"


def _adr_corpus(adr_dir: Path) -> list[tuple[str, str, str]]:
    """``(number, filename, text)`` for every ADR that may count as a ref.

    Read once and reused across every row: the per-name scan is 70-odd names
    against 150-odd files, and re-reading per name is the difference between
    a fast regen and one nobody runs.
    """
    corpus: list[tuple[str, str, str]] = []
    for path in sorted(adr_dir.glob("*.md")):
        if path.name in ADR_EXCLUDED_REFS:
            continue
        match = _ADR_NUMBER_RE.match(path.name)
        if not match:
            continue
        try:
            corpus.append((match.group(1), path.name, path.read_text()))
        except OSError:
            continue
    return corpus


def _term_index(terms_dir: Path) -> dict[str, str]:
    """``{declared term name: filename}`` from each term file's frontmatter."""
    index: dict[str, str] = {}
    if not terms_dir.is_dir():
        return index
    for path in sorted(terms_dir.glob("*.md")):
        try:
            head = path.read_text()[:2000]
        except OSError:
            continue
        match = _TERM_NAME_RE.search(head)
        if match:
            index.setdefault(match.group(1).strip(), path.name)
    return index


def _adr_cell(name: str, corpus: list[tuple[str, str, str]]) -> str:
    """Every ADR number whose text names this port or loop.

    Numbers rather than links on purpose: ``PRPort`` is named by ten ADRs, and
    ten markdown links is a cell nobody reads. The navigable cross-reference
    already exists at ``docs/arch/generated/adr_xref.md``.
    """
    pattern = re.compile(rf"\b{re.escape(name)}\b")
    hits = [number for number, _filename, text in corpus if pattern.search(text)]
    return ", ".join(hits) if hits else _ABSENT


def _term_cell(name: str, terms: dict[str, str]) -> str:
    filename = terms.get(name)
    if not filename:
        return _ABSENT
    return f"[{filename}](../../wiki/terms/{filename})"


def render_port_registry(ports: list[PortInfo], *, repo_root: Path) -> str:
    """The per-port registry table body, header included."""
    repo_root = Path(repo_root).resolve()
    corpus = _adr_corpus(repo_root / "docs" / "adr")
    terms = _term_index(repo_root / "docs" / "wiki" / "terms")
    rows: list[str] = []
    for port in sorted(ports, key=lambda p: p.name):
        fake = f"`{port.fake.name}`" if port.fake else _ABSENT
        rows.append(
            f"| `{port.name}` | `{port.source_path}` | {fake} "
            f"| {_adr_cell(port.name, corpus)} "
            f"| {_term_cell(port.name, terms)} |"
        )
    return "\n".join([_PORT_HEADER, *rows])


def render_loop_registry(loops: list[LoopInfo], *, repo_root: Path) -> str:
    """The per-loop registry table body, header included."""
    repo_root = Path(repo_root).resolve()
    corpus = _adr_corpus(repo_root / "docs" / "adr")
    terms = _term_index(repo_root / "docs" / "wiki" / "terms")
    rows: list[str] = []
    for loop in sorted(loops, key=lambda info: info.name):
        tick = loop.tick_interval_seconds or _ABSENT
        rows.append(
            f"| `{loop.name}` | `{loop.source_path}` | {tick} "
            f"| {_adr_cell(loop.name, corpus)} "
            f"| {_term_cell(loop.name, terms)} |"
        )
    return "\n".join([_LOOP_HEADER, *rows])


def render_blocks(
    loops: list[LoopInfo], ports: list[PortInfo], *, repo_root: Path
) -> dict[tuple[str, str], str]:
    """``{(begin marker, end marker): table}`` for the standard's README."""
    return {
        PORT_REGISTRY_BLOCK: render_port_registry(ports, repo_root=repo_root),
        LOOP_REGISTRY_BLOCK: render_loop_registry(loops, repo_root=repo_root),
    }
