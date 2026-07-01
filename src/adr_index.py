"""ADR runtime indexer.

Parses docs/adr/*.md at runtime, renders compact summaries for prompt
injection. Load-bearing facts — we want agents to know what's been
decided before they plan.

File format (from docs/adr/0001-five-concurrent-async-loops.md):

    # ADR-0001: Five Concurrent Async Loops

    **Status:** Accepted
    **Date:** 2026-02-26

    ## Context

    HydraFlow must process GitHub issues through five distinct stages...

The separator after the ADR number is flexible: colon, em-dash, en-dash,
hyphen, or bare whitespace are all accepted (e.g.
``# ADR-0093 — Loop fitness as a measured contract``). Every
``# ADR-NNNN...`` heading in docs/adr/*.md MUST parse — see
``tests/test_adr_conformance_coverage.py::test_every_adr_file_parses``.

Status is normalized to one of: "Accepted", "Proposed", "Superseded",
"Deprecated". "Superseded by ADR-NNNN" populates ``superseded_by``.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

logger = logging.getLogger(__name__)

_TITLE_RE = re.compile(r"^#\s*ADR-(\d{4})\s*[:–—-]?\s*(.+?)\s*$", re.MULTILINE)
_STATUS_RE = re.compile(r"\*\*Status:\*\*\s*(.+?)\s*$", re.MULTILINE)
_CONTEXT_RE = re.compile(r"##\s+Context\s*\n\s*\n(.+?)(?=\n\s*\n|\n##\s|\Z)", re.DOTALL)
_SUPERSEDED_RE = re.compile(r"Superseded\s+by\s+(ADR-\d{4})", re.IGNORECASE)
_ENFORCEMENT_RE = re.compile(r"\*\*Enforcement:\*\*\s*(.+?)\s*$", re.MULTILINE)
# Capture the Enforced-by block: the field line plus any indented/continued
# lines until the next blank line, the next **Field:** / ## heading, or the
# next Markdown bullet (`- **Spec:**`, `- **Plan:**`, etc.). Without the
# bullet stop, a trailing sibling bullet on the *same* frontmatter list (no
# blank line between them) gets swallowed into the Enforced-by capture.
_ENFORCED_BY_RE = re.compile(
    r"\*\*Enforced by:\*\*[ \t]*(.*?)(?=\n\s*\n|\n\*\*[A-Z]|\n##\s|\n\s*[-*]\s|\Z)",
    re.DOTALL,
)
_KNOWN_ENFORCEMENT = frozenset({"enforced", "manual", "decision-of-record"})
# Matches `src/some/path.py` or `src/some/path.py:Symbol[.attr...]` citations.
# Shared with adr_pre_validator._SOURCE_SYMBOL_RE. Used for
# ADR↔source-file inverse indexing so the CI gate can flag PRs
# touching files cited in Accepted ADRs. The ``:Symbol`` tail is
# optional so umbrella ADRs that cite files in prose (without a
# specific symbol) also satisfy the gate. Dotted symbols like
# ``Class.method`` round-trip intact so the gate can match method-level
# citations against AST-extracted method names.
_SOURCE_FILE_CITATION_RE = re.compile(
    r"`(src/[^`:\s]+\.py)(?::([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*))?`"
)
# Matches a Markdown inline link `[text](url)`, used by Check.as_code_span
# to defuse links embedded in raw Enforced-by prose before they're wrapped
# in a code span for display in generated docs tables.
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")


@dataclass(frozen=True)
class Check:
    """One executable/resolvable check cited by an ADR's Enforced-by field."""

    kind: Literal["pytest", "make", "prose"]
    target: str
    raw: str

    def as_code_span(self) -> str:
        """Render ``raw`` as a Markdown inline code span, safe for embedding
        in generated docs tables.

        Manual/prose Enforced-by fields sometimes carry ADR-body Markdown
        verbatim (bullet lists, bold, and relative links into the
        gitignored ``docs/superpowers/`` tree). Naively wrapping ``raw`` in
        a single pair of backticks is unsafe on two counts: (1) if ``raw``
        itself contains a backtick, the code span closes early and any
        ``[text](url)`` after it renders as a *real* link; (2) even without
        an early close, some Markdown link syntax can still leak through.
        Stripping link syntax and backticks first makes the code span
        closure unconditionally safe, which keeps `mkdocs build --strict`
        from flagging a broken/excluded target for links that were only
        ever meant to be inert prose.
        """
        text = _MARKDOWN_LINK_RE.sub(r"\1 (\2)", self.raw)
        text = text.replace("`", "'")
        return f"`{text}`"


def parse_enforced_by(block: str) -> tuple[Check, ...]:
    """Parse an Enforced-by block into typed checks. One check per line.

    Commas are NOT separators (so `manual` prose with commas stays intact).
    A line beginning `pytest:` or `make:` is typed; anything else is `prose`
    (legal only under Enforcement: manual — the coverage ratchet enforces that).
    """
    checks: list[Check] = []
    for raw_line in block.splitlines():
        line = raw_line.strip().rstrip(",").strip()
        if not line:
            continue
        if line.startswith("pytest:"):
            checks.append(
                Check(kind="pytest", target=line[len("pytest:") :].strip(), raw=line)
            )
        elif line.startswith("make:"):
            checks.append(
                Check(kind="make", target=line[len("make:") :].strip(), raw=line)
            )
        else:
            checks.append(Check(kind="prose", target=line, raw=line))
    return tuple(checks)


def _normalize_enforcement(raw: str) -> str:
    low = raw.strip().lower()
    return low if low in _KNOWN_ENFORCEMENT else "unknown"


@dataclass(frozen=True)
class ADR:
    number: int
    title: str
    status: str  # normalized: Accepted | Proposed | Superseded | Deprecated | Unknown
    summary: str  # first paragraph of ## Context, flattened
    superseded_by: str | None = None
    source_files: frozenset[str] = frozenset()
    """Set of `src/...` paths cited anywhere in the ADR body — used by
    the P2 CI gate to flag PRs touching files under Accepted ADRs."""
    source_symbols: dict[str, frozenset[str]] = field(default_factory=dict)
    """Per-cited-file set of qualified symbols (``Class``, ``func``, or
    ``Class.method``).  An *empty* frozenset for a file means at least
    one bare ``src/foo.py`` citation exists — the gate then fires on any
    change to that file (backwards-compatible with pre-symbol citations).
    A non-empty frozenset means *only* changes to those symbols fire the
    gate."""
    enforcement: str = "unknown"
    """enforced | manual | decision-of-record | unknown (ADR-0098)."""
    enforced_by: tuple[Check, ...] = ()
    """Typed checks parsed from **Enforced by:**; () for decision-of-record."""


def parse_adr_file(path: Path) -> ADR:
    """Parse a single ADR markdown file. Never raises on malformed input."""
    text = path.read_text()

    title_match = _TITLE_RE.search(text)
    if title_match is None:
        # Fallback: use filename stem
        number = _extract_number_from_filename(path)
        title = path.stem
    else:
        number = int(title_match.group(1))
        title = title_match.group(2)

    status_raw = ""
    status_match = _STATUS_RE.search(text)
    if status_match:
        status_raw = status_match.group(1).strip()

    superseded_by = None
    sup_match = _SUPERSEDED_RE.search(status_raw)
    if sup_match:
        superseded_by = sup_match.group(1)
        status_norm = "Superseded"
    else:
        status_norm = _normalize_status(status_raw)

    summary = ""
    ctx_match = _CONTEXT_RE.search(text)
    if ctx_match:
        summary = " ".join(ctx_match.group(1).split())[:300]

    source_symbols: dict[str, set[str]] = {}
    bare_files: set[str] = set()
    for file_path, symbol in _SOURCE_FILE_CITATION_RE.findall(text):
        if symbol:
            source_symbols.setdefault(file_path, set()).add(symbol)
        else:
            bare_files.add(file_path)
            source_symbols.setdefault(file_path, set())
    # A bare citation collapses any symbol-qualified citations for the
    # same file: the gate fires on any change.
    for f in bare_files:
        source_symbols[f] = set()
    source_files = frozenset(source_symbols.keys())
    source_symbols_frozen = {f: frozenset(s) for f, s in source_symbols.items()}

    enf_match = _ENFORCEMENT_RE.search(text)
    enforcement = _normalize_enforcement(enf_match.group(1)) if enf_match else "unknown"
    eb_match = _ENFORCED_BY_RE.search(text)
    enforced_by = parse_enforced_by(eb_match.group(1)) if eb_match else ()

    return ADR(
        number=number,
        title=title,
        status=status_norm,
        summary=summary,
        superseded_by=superseded_by,
        source_files=source_files,
        source_symbols=source_symbols_frozen,
        enforcement=enforcement,
        enforced_by=enforced_by,
    )


def scan_adr_directory(adr_dir: Path) -> list[ADR]:
    """Parse every ADR file in the directory, sorted by number.

    Emits a ``logger.warning`` for each ADR number claimed by more than one
    file. Two ADRs sharing a number silently collapse in every dict-keyed
    downstream caller (``adrs_touching``, ``compute_drift``, the ``adr_xref``
    generator), so the colliding citations merge non-deterministically. The
    #9406 collisions went unnoticed for weeks because nothing on the runtime
    path signalled the duplicate; this warning surfaces it in logs / Sentry
    immediately while still returning a usable (collision-included) list.
    """
    if not adr_dir.exists() or not adr_dir.is_dir():
        return []
    adrs: list[ADR] = []
    files_by_number: dict[int, list[str]] = defaultdict(list)
    for p in adr_dir.iterdir():
        if p.is_file() and p.suffix == ".md" and _TITLE_RE.search(p.read_text()):
            adr = parse_adr_file(p)
            adrs.append(adr)
            files_by_number[adr.number].append(p.name)
    for number, names in files_by_number.items():
        if len(names) > 1:
            logger.warning(
                "Duplicate ADR number %04d claimed by %d files: %s. "
                "Dict-keyed callers will non-deterministically keep/merge one; "
                "renumber the later-authored file (issue #9406 / #9457).",
                number,
                len(names),
                ", ".join(sorted(names)),
            )
    return sorted(adrs, key=lambda a: a.number)


def _normalize_status(raw: str) -> str:
    low = raw.lower()
    if "accepted" in low:
        return "Accepted"
    if "proposed" in low or "draft" in low:
        return "Proposed"
    if "superseded" in low:
        return "Superseded"
    if "deprecated" in low:
        return "Deprecated"
    return "Unknown"


def _extract_number_from_filename(path: Path) -> int:
    m = re.match(r"(\d{4})-", path.name)
    return int(m.group(1)) if m else 0


def render_full(adrs: list[ADR]) -> str:
    """Render the full ADR index for injection into plan-phase prompts."""
    if not adrs:
        return ""

    accepted = [a for a in adrs if a.status == "Accepted"]
    proposed = [a for a in adrs if a.status == "Proposed"]
    superseded = [a for a in adrs if a.status == "Superseded"]

    parts: list[str] = ["# Architecture Decisions (ADRs)"]

    if accepted:
        parts.append("\n## Accepted (load-bearing)")
        for a in accepted:
            parts.append(f"- ADR-{a.number:04d} {a.title} — {a.summary}")

    if proposed:
        parts.append("\n## Proposed (drafted, not yet accepted)")
        for a in proposed:
            parts.append(f"- ADR-{a.number:04d} {a.title} — {a.summary}")

    if superseded:
        parts.append("\n## Superseded")
        for a in superseded:
            ref = f" (superseded by {a.superseded_by})" if a.superseded_by else ""
            parts.append(f"- ADR-{a.number:04d} {a.title}{ref}")

    return "\n".join(parts)


def render_titles_only(adrs: list[ADR]) -> str:
    """Titles-only view for implement/review prompts (prompt-size conscious).

    Excludes Superseded entries to reduce noise. Agents working in
    implement/review shouldn't be reminded of rules that have been replaced.
    """
    accepted = [a for a in adrs if a.status == "Accepted"]
    proposed = [a for a in adrs if a.status == "Proposed"]
    visible = accepted + proposed
    if not visible:
        return ""
    lines = ["# Architecture Decisions (titles only)"]
    for a in visible:
        lines.append(f"- ADR-{a.number:04d} {a.title}")
    return "\n".join(lines)


class ADRIndex:
    """Mtime-based cache over the ADR directory.

    Scans lazily on first ``adrs()`` call. Re-scans only when the directory
    or any ADR file's mtime has changed. Cheap for hot callers.
    """

    def __init__(self, adr_dir: Path) -> None:
        self._adr_dir = adr_dir
        self._cached: list[ADR] | None = None
        self._fingerprint: tuple[float, ...] = ()

    def adrs(self) -> list[ADR]:
        fingerprint = self._compute_fingerprint()
        if self._cached is None or fingerprint != self._fingerprint:
            self._cached = scan_adr_directory(self._adr_dir)
            self._fingerprint = fingerprint
        return self._cached

    def adrs_touching(self, paths: list[str] | tuple[str, ...]) -> dict[str, list[ADR]]:
        """Return a mapping of input paths → ADRs that cite each.

        Includes Accepted and Proposed ADRs — Superseded / Deprecated
        don't trigger the P2 gate. Proposed ADRs count because a PR
        that adds a Proposed ADR citing the touched file IS the author's
        statement of responsibility for the change; the ADR's status
        will be bumped to Accepted when the PR merges and the decision
        takes effect.

        Paths with no hits are omitted from the result.
        """
        if not paths:
            return {}
        live = [a for a in self.adrs() if a.status in ("Accepted", "Proposed")]
        result: dict[str, list[ADR]] = {}
        for path in paths:
            hits = [a for a in live if path in a.source_files]
            if hits:
                result[path] = hits
        return result

    def _compute_fingerprint(self) -> tuple[float, ...]:
        if not self._adr_dir.exists():
            return ()
        mtimes: list[float] = [self._adr_dir.stat().st_mtime]
        for p in self._adr_dir.iterdir():
            if p.is_file() and p.suffix == ".md":
                mtimes.append(p.stat().st_mtime)
        return tuple(sorted(mtimes))
