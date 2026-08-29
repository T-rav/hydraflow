"""Doc-informed context retrieval for decompose-to-converge (ADR-0105).

Gathers a small, bounded slice of the repo's own documentation -- ADR
excerpts and wiki entries -- relevant to the files a stalled task has
touched, so the decomposition ensemble (``decomposition_ensemble.py``)
can weigh a split against the architectural decisions and gotchas that
already govern that area of the codebase. The ensemble treats the
result as an opaque string; it does not interpret its structure.

Two independent, best-effort lookups feed the result:

* ADRs -- via the ``## Module -> ADRs`` table in the generated
  cross-reference (``docs/arch/generated/adr_xref.md``). Touched files
  are mapped to their dotted module name (``src/config.py`` ->
  ``src.config``), matched against the table, and the hit ADRs are
  ranked by how many touched files cite them before the top
  ``max_adrs`` are expanded into a title + short Decision excerpt from
  ``docs/adr/NNNN-*.md``.
* Wiki -- a simple keyword match against the topic pages under
  ``docs/wiki/*.md`` (the ``index.md`` table of contents is skipped;
  it has no entry content of its own). Keywords are derived from the
  touched files' module-name parts and matched against each entry's
  title + prose, bounded to the top ``max_wiki`` matches.

Both lookups -- and the module as a whole -- are graceful: a missing
generated file, an absent ADR markdown file, an unmapped touched file,
or no matches at all simply yields a smaller (possibly empty) result
rather than raising. Callers pass this string on into an LLM prompt, so
it also stays deliberately tight rather than dumping full documents.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

from adr_utils import extract_adr_section

logger = logging.getLogger("hydraflow.decomposition_docs")

_ADR_XREF_RELPATH = Path("docs/arch/generated/adr_xref.md")
_WIKI_RELDIR = Path("docs/wiki")
_ADR_RELDIR = Path("docs/adr")

_MODULE_SECTION_MARKER = "## Module"
_MODULE_ROW_RE = re.compile(r"^\|\s*`([^`]+)`\s*\|\s*(.+?)\s*\|\s*$")
_ADR_ID_RE = re.compile(r"ADR-(\d+)")
_TITLE_HEADING_RE = re.compile(r"^#\s+(.+)$")

_WIKI_SKIP_FILES = {"index.md"}
_STOPWORDS = {"src", "test", "tests", "the", "and"}

_ADR_EXCERPT_CHARS = 400
_WIKI_EXCERPT_CHARS = 220


def gather_decomposition_docs(
    touched_files: list[str],
    *,
    repo_root: Path,
    max_adrs: int = 3,
    max_wiki: int = 5,
) -> str:
    """Return a bounded doc-context string for *touched_files*.

    Best-effort and never raises. An empty string means nothing
    relevant was found (or ``touched_files`` was empty / all files were
    unmapped) -- callers should treat that as "no doc context
    available", not a failure signal.
    """
    if not touched_files:
        return ""

    try:
        adr_section = _gather_adr_section(
            touched_files, repo_root=repo_root, max_adrs=max_adrs
        )
        wiki_section = _gather_wiki_section(
            touched_files, repo_root=repo_root, max_wiki=max_wiki
        )
    except Exception:
        logger.warning("gather_decomposition_docs failed", exc_info=True)
        return ""

    sections = [s for s in (adr_section, wiki_section) if s]
    return "\n\n".join(sections)


# ---------------------------------------------------------------------------
# ADRs: touched files -> module -> "## Module -> ADRs" table -> excerpts
# ---------------------------------------------------------------------------


def _module_for_file(path: str) -> str | None:
    """Map a repo-relative file path to its dotted module name.

    Only files under ``src/`` are mappable -- that is the only tree the
    generated cross-reference indexes. ``src/foo/bar.py`` ->
    ``src.foo.bar``; ``src/foo/__init__.py`` -> ``src.foo``. Anything
    else (tests, docs, non-Python files) returns ``None``.
    """
    normalized = path.replace("\\", "/").lstrip("/")
    if not normalized.endswith(".py"):
        return None
    parts = normalized.split("/")
    if len(parts) < 2 or parts[0] != "src":
        return None
    package_parts, filename = parts[1:-1], parts[-1]
    stem = filename[: -len(".py")]
    module_parts = package_parts if stem == "__init__" else [*package_parts, stem]
    if not module_parts:
        return None
    return "src." + ".".join(module_parts)


def _parse_module_to_adrs(text: str) -> dict[str, list[str]]:
    """Parse the ``## Module -> ADRs`` table into ``{module: [adr_id, ...]}``."""
    marker_index = text.find(_MODULE_SECTION_MARKER)
    if marker_index == -1:
        return {}
    mapping: dict[str, list[str]] = {}
    for line in text[marker_index:].splitlines():
        match = _MODULE_ROW_RE.match(line.strip())
        if not match:
            continue
        module, adrs_raw = match.groups()
        adrs = [a.strip() for a in adrs_raw.split(",") if a.strip().startswith("ADR-")]
        if adrs:
            mapping[module] = adrs
    return mapping


def _gather_adr_section(
    touched_files: list[str], *, repo_root: Path, max_adrs: int
) -> str:
    xref_path = repo_root / _ADR_XREF_RELPATH
    if not xref_path.is_file():
        return ""
    try:
        text = xref_path.read_text()
    except OSError:
        return ""

    module_to_adrs = _parse_module_to_adrs(text)
    if not module_to_adrs:
        return ""

    counts: Counter[str] = Counter()
    for touched in touched_files:
        module = _module_for_file(touched)
        if module is None:
            continue
        for adr_id in module_to_adrs.get(module, []):
            counts[adr_id] += 1
    if not counts:
        return ""

    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    selected_ids = [adr_id for adr_id, _ in ranked[:max_adrs]]

    blocks = [
        block
        for adr_id in selected_ids
        if (block := _load_adr_excerpt(repo_root, adr_id)) is not None
    ]
    if not blocks:
        return ""
    return "## Related ADRs\n\n" + "\n\n".join(blocks)


def _load_adr_excerpt(repo_root: Path, adr_id: str) -> str | None:
    """Load *adr_id*'s title + a short Decision excerpt, or ``None`` gracefully."""
    id_match = _ADR_ID_RE.search(adr_id)
    if not id_match:
        return None
    number = int(id_match.group(1))
    adr_dir = repo_root / _ADR_RELDIR
    if not adr_dir.is_dir():
        return None
    candidates = sorted(adr_dir.glob(f"{number:04d}-*.md"))
    if not candidates:
        return None
    try:
        text = candidates[0].read_text()
    except OSError:
        return None

    title = _extract_title(text) or adr_id
    decision = extract_adr_section(text, "Decision")
    excerpt = _truncate(decision, _ADR_EXCERPT_CHARS) if decision else ""
    body = excerpt or "(no Decision section found)"
    return f"### {adr_id}: {title}\n\n{body}"


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        match = _TITLE_HEADING_RE.match(line.strip())
        if match:
            return re.sub(r"^ADR-\d+:\s*", "", match.group(1).strip())
    return ""


# ---------------------------------------------------------------------------
# Wiki: touched files -> keywords -> topic-page entry match -> excerpts
# ---------------------------------------------------------------------------


def _keywords_for_files(touched_files: list[str]) -> set[str]:
    keywords: set[str] = set()
    for touched in touched_files:
        stem = Path(touched.replace("\\", "/")).stem
        for raw_token in re.split(r"[_\-.]+", stem):
            token = raw_token.lower()
            if len(token) >= 3 and token not in _STOPWORDS:
                keywords.add(token)
    return keywords


def _parse_wiki_entries(text: str) -> list[tuple[str, str]]:
    """Split a wiki topic page into ``(title, prose)`` pairs.

    Mirrors the schema ``RepoWikiStore`` writes: each entry is a
    ``## Title`` heading, prose, then an optional ``json:entry``
    metadata fence. Only the prose above the fence is kept; free-form
    sections with no title are skipped.
    """
    sections = re.split(r"(?:^|\n)## ", text)
    entries: list[tuple[str, str]] = []
    for section in sections[1:]:
        title, _, body = section.partition("\n")
        title = title.strip()
        if not title:
            continue
        fence_match = re.search(r"```json:entry", body)
        prose = body[: fence_match.start()] if fence_match else body
        entries.append((title, prose.strip()))
    return entries


def _gather_wiki_section(
    touched_files: list[str], *, repo_root: Path, max_wiki: int
) -> str:
    keywords = _keywords_for_files(touched_files)
    if not keywords:
        return ""
    wiki_dir = repo_root / _WIKI_RELDIR
    if not wiki_dir.is_dir():
        return ""

    scored: list[tuple[int, int, str, str]] = []
    order = 0
    for topic_path in sorted(wiki_dir.glob("*.md")):
        if topic_path.name in _WIKI_SKIP_FILES:
            continue
        try:
            text = topic_path.read_text()
        except OSError:
            continue
        for title, prose in _parse_wiki_entries(text):
            haystack = f"{title}\n{prose}".lower()
            score = sum(1 for kw in keywords if kw in haystack)
            if score <= 0:
                continue
            scored.append((-score, order, title, prose))
            order += 1
    if not scored:
        return ""

    scored.sort(key=lambda item: (item[0], item[1]))
    blocks = [
        f"### {title}\n\n{_truncate(prose, _WIKI_EXCERPT_CHARS)}"
        for _, _, title, prose in scored[:max_wiki]
    ]
    return "## Related Wiki Entries\n\n" + "\n\n".join(blocks)


def _truncate(text: str, limit: int) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "…"
