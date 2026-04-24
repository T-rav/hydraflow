"""Wiki-vs-code drift detection — P4 of the wiki-evolution audit.

First-cut detector is deterministic and cheap: for every *active*
tracked-layout entry under ``{tracked_root}/{repo_slug}/{topic}/``,
extract ``src/...`` citations from its body and verify each cited
file still exists under ``repo_root``.  Missing files = drift.

Symbol-level drift (cited class/function removed while file remains)
is intentionally out of scope for this pass — adding an LLM
validator on top of this skeleton is the Phase 2 extension.

The RepoWikiLoop calls ``detect_drift`` on a weekly cadence and can
use the returned findings to mark entries stale with a
``stale_reason: drift_detected <files>`` note.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("hydraflow.wiki_drift_detector")

# Matches `src/some/path.py:Symbol` citations inside backticks and
# captures (file, symbol). Shares shape with
# src/adr_index.py:_SOURCE_FILE_CITATION_RE.
_SOURCE_PAIR_CITATION_RE = re.compile(r"`(src/[^`:\s]+\.py):([A-Za-z_]\w*)`")


@dataclass(frozen=True)
class DriftFinding:
    """One drifted wiki entry.

    ``missing_files`` lists cited ``src/...py`` files that no longer
    exist under ``repo_root``.  ``missing_symbols`` lists
    ``src/path.py:Symbol`` citations where the file exists but the
    symbol (``class Symbol`` / ``def Symbol`` / ``async def Symbol``)
    is not defined in it.
    """

    entry_path: Path
    entry_id: str
    topic: str
    missing_files: frozenset[str]
    missing_symbols: frozenset[str] = frozenset()


@dataclass
class DriftResult:
    findings: list[DriftFinding] = field(default_factory=list)


def _parse_frontmatter(text: str) -> dict[str, str]:
    """Minimal parser of the leading ``---`` YAML-ish block.

    Mirrors ``src/repo_wiki.py:_split_tracked_entry`` — kept separate
    to avoid importing a heavy module.
    """
    if not text.startswith("---\n"):
        return {}
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return {}
    block = text[4:end]
    out: dict[str, str] = {}
    for line in block.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def _entry_body(text: str) -> str:
    """Return the body after the leading frontmatter (or the whole
    text when no frontmatter is present)."""
    if not text.startswith("---\n"):
        return text
    try:
        end = text.index("\n---\n", 4)
    except ValueError:
        return text
    return text[end + len("\n---\n") :]


def _file_defines_symbol(file_path: Path, symbol: str) -> bool:
    """Grep *file_path* for a top-level or indented definition of *symbol*.

    Matches ``class Symbol`` / ``def Symbol`` / ``async def Symbol``
    with optional leading whitespace (so methods inside classes count)
    followed by ``(``, ``:``, ``[``, or whitespace — whatever Python
    syntax permits. Module-level assignments (constants / aliases) are
    caught by the trailing ``=`` / ``:`` alternative.

    False positives on comments/strings would be rare and one-directional
    (under-flagging drift rather than over-flagging), so we keep it
    regex-simple rather than AST-parsing.
    """
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    pattern = re.compile(
        rf"^\s*(?:class|def|async\s+def)\s+{re.escape(symbol)}\b",
        re.MULTILINE,
    )
    if pattern.search(text):
        return True
    # Module-level constants/aliases: `FOO = ...` or `FOO: Type = ...`.
    assign_pattern = re.compile(
        rf"^{re.escape(symbol)}\s*(?::\s*[^=\n]+)?\s*=",
        re.MULTILINE,
    )
    return bool(assign_pattern.search(text))


def detect_drift(
    *,
    tracked_root: Path,
    repo_root: Path,
    repo_slug: str,
) -> DriftResult:
    """Scan tracked-layout active entries and flag those citing missing files.

    Parameters
    ----------
    tracked_root:
        Root where the per-entry layout lives (typically
        ``{repo_root}/repo_wiki``).
    repo_root:
        Working tree root used to resolve ``src/...`` citations.
    repo_slug:
        ``owner/repo`` slug scoping the lookup.
    """
    result = DriftResult()
    repo_dir = tracked_root / repo_slug
    if not repo_dir.is_dir():
        return result

    for topic_dir in sorted(p for p in repo_dir.iterdir() if p.is_dir()):
        for entry_path in sorted(topic_dir.glob("*.md")):
            try:
                text = entry_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            fields = _parse_frontmatter(text)
            if fields.get("status", "active") != "active":
                continue

            body = _entry_body(text)
            pairs = set(_SOURCE_PAIR_CITATION_RE.findall(body))
            if not pairs:
                continue

            missing_files: set[str] = set()
            missing_symbols: set[str] = set()
            for file_ref, symbol in pairs:
                file_path = repo_root / file_ref
                if not file_path.is_file():
                    missing_files.add(file_ref)
                    continue
                if not _file_defines_symbol(file_path, symbol):
                    missing_symbols.add(f"{file_ref}:{symbol}")

            if not missing_files and not missing_symbols:
                continue

            result.findings.append(
                DriftFinding(
                    entry_path=entry_path,
                    entry_id=fields.get("id", ""),
                    topic=topic_dir.name,
                    missing_files=frozenset(missing_files),
                    missing_symbols=frozenset(missing_symbols),
                )
            )

    return result


def apply_drift_markers(findings: list[DriftFinding]) -> int:
    """Flip each flagged entry's ``status: active`` → ``stale`` with a
    ``stale_reason: drift_detected: <files>`` annotation.

    Only mutates files whose frontmatter still says ``status: active`` —
    idempotent on second call, safe against entries that a prior lint
    pass already marked stale.

    Returns the count of entries actually updated. Never raises on
    per-file read / write failures; logs and continues.
    """
    updated = 0
    for finding in findings:
        try:
            text = finding.entry_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            logger.warning(
                "drift automark: cannot read %s; skipping", finding.entry_path
            )
            continue
        fields = _parse_frontmatter(text)
        if not fields or fields.get("status", "active") != "active":
            continue
        body = _entry_body(text)
        parts = sorted(finding.missing_files) + sorted(finding.missing_symbols)
        reason = "drift_detected: " + ",".join(parts)
        fields["status"] = "stale"
        fields["stale_reason"] = reason
        rebuilt = (
            "---\n"
            + "\n".join(f"{k}: {v}" for k, v in fields.items())
            + "\n---\n"
            + body
        )
        try:
            finding.entry_path.write_text(rebuilt, encoding="utf-8")
        except OSError:
            logger.warning(
                "drift automark: cannot write %s; skipping", finding.entry_path
            )
            continue
        updated += 1
    return updated
