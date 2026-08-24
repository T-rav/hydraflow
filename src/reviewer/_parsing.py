"""Reading a verdict out of agent output, and bounding what goes in.

Pure text in, text out. These are the methods a malformed reply reaches first,
which is why they are worth having in one place.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from base_runner import BaseRunner

if TYPE_CHECKING:
    pass

from models import (
    ReviewVerdict,
)

logger = logging.getLogger("hydraflow.reviewer")


# Compiled patterns that indicate a transcript line is internal tool output,
# not a human-readable review summary.
_JUNK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"[→←]"),  # Tool arrows (e.g. "→ TaskOutput: ...")
    re.compile(r"^\s*\{.*\}\s*$"),  # Raw JSON objects
    re.compile(r"<[a-zA-Z/][^>]*>"),  # HTML tags
    re.compile(r"^```"),  # Code fence markers
    re.compile(r"^Co-Authored-By:", re.IGNORECASE),  # Git trailers
    re.compile(r"^Signed-off-by:", re.IGNORECASE),  # Git trailers
    re.compile(r"^\s*\d+[\s,]+\d+"),  # Metric lines (e.g. "1234 5678")
    re.compile(r"^(tokens|cost|duration)\s*:", re.IGNORECASE),  # Metric labels
]


class ReviewParsingMixin(BaseRunner):
    """Reading a verdict out of agent output, and bounding what goes in."""

    # ------------------------------------------------------------------
    # Collaborator seams — provided by ``ReviewRunner.__init__`` or by a sibling
    # mixin. The method declarations are TYPE_CHECKING-only on purpose: a
    # runtime ``...`` body is a real class attribute and would win the MRO
    # over the sibling that really implements it (#11629).
    # ------------------------------------------------------------------

    def _parse_verdict(self, transcript: str) -> ReviewVerdict:
        """Extract the verdict from the reviewer transcript."""
        pattern = r"VERDICT:\s*(APPROVE|REQUEST_CHANGES|COMMENT)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            raw = match.group(1).upper().replace("_", "-")
            # Map the parsed string to the enum
            mapping = {
                "APPROVE": ReviewVerdict.APPROVE,
                "REQUEST-CHANGES": ReviewVerdict.REQUEST_CHANGES,
                "COMMENT": ReviewVerdict.COMMENT,
            }
            return mapping.get(raw, ReviewVerdict.COMMENT)
        return ReviewVerdict.COMMENT

    def _extract_summary(self, transcript: str) -> str:
        """Extract the summary line from the reviewer transcript."""
        pattern = r"SUMMARY:\s*(.+)"
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            sanitized = self._sanitize_summary(match.group(1).strip())
            if sanitized:
                return sanitized

        # Fallback: walk lines in reverse, skipping garbage
        for line in reversed(transcript.splitlines()):
            stripped = line.strip()
            if not stripped:
                continue
            sanitized = self._sanitize_summary(stripped)
            if sanitized:
                return sanitized

        return "No summary provided"

    @staticmethod
    def _sanitize_summary(candidate: str) -> str | None:
        """Return *candidate* if it looks like a real summary, else ``None``.

        Rejects strings that match any :data:`_JUNK_PATTERNS` or are
        shorter than 10 characters (likely not meaningful).  Valid
        summaries are truncated to 200 characters.
        """
        text = candidate.strip()
        if len(text) < 10:
            return None
        for pat in _JUNK_PATTERNS:
            if pat.search(text):
                return None
        return text[:200]

    def _summarize_issue_body(self, body: str) -> str:
        """Return compact issue context to reduce prompt size."""
        text = (body or "").strip()
        if not text:
            return "(No issue body provided)"

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        cue_lines = [
            ln
            for ln in lines
            if re.match(r"^([-*]|\d+\.)\s+", ln) or ln.lower().startswith("acceptance")
        ]
        selected = cue_lines[:8] if cue_lines else lines[:8]
        compact = "\n".join(f"- {ln[:200]}" for ln in selected)
        compacted = len(text) > self._config.max_issue_body_chars
        note = (
            f"[Body summarized from {len(text):,} chars to reduce prompt size]"
            if compacted
            else "[Body summarized for prompt efficiency]"
        )
        return f"Issue body summarized for token efficiency:\n{compact}\n\n{note}"

    def _summarize_diff(self, pr_number: int, diff: str) -> str:
        """Return compact diff context with file/change summary and excerpts."""
        max_diff = self._config.max_review_diff_chars
        source = diff
        truncated = False
        if len(source) > max_diff:
            logger.warning(
                "PR #%d diff truncated from %d to %d chars",
                pr_number,
                len(source),
                max_diff,
            )
            source = source[:max_diff]
            truncated = True

        files: list[str] = []
        file_stats: dict[str, dict[str, int]] = {}
        current_file = ""
        added = 0
        removed = 0
        excerpt_lines: list[str] = []
        excerpt_chars = 0
        hunk_changes = 0
        excerpt_limit = min(1600, max_diff)
        max_files_in_summary = 10

        for line in source.splitlines():
            if line.startswith("diff --git "):
                m = re.search(r" b/(.+)$", line)
                current_file = m.group(1) if m else ""
                if current_file and current_file not in files:
                    files.append(current_file)
                    file_stats[current_file] = {"added": 0, "removed": 0}
                hunk_changes = 0
                if excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                continue

            if line.startswith("@@"):
                hunk_changes = 0
                if excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                continue

            if line.startswith(("+++", "---")):
                continue

            if line.startswith("+"):
                added += 1
                if current_file:
                    file_stats.setdefault(current_file, {"added": 0, "removed": 0})[
                        "added"
                    ] += 1
                if hunk_changes < 4 and excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                hunk_changes += 1
                continue

            if line.startswith("-"):
                removed += 1
                if current_file:
                    file_stats.setdefault(current_file, {"added": 0, "removed": 0})[
                        "removed"
                    ] += 1
                if hunk_changes < 4 and excerpt_chars < excerpt_limit:
                    excerpt_lines.append(line)
                    excerpt_chars += len(line) + 1
                hunk_changes += 1

        top_files: list[tuple[str, dict[str, int]]] = sorted(
            file_stats.items(),
            key=lambda item: item[1]["added"] + item[1]["removed"],
            reverse=True,
        )[:max_files_in_summary]
        if top_files:
            file_lines = "\n".join(
                f"- {path}: +{stats['added']} / -{stats['removed']}"
                for path, stats in top_files
            )
        else:
            file_lines = "- (could not detect files)"
        truncated_note = ""
        if truncated:
            truncated_note = f"\n[Diff truncated at {max_diff:,} chars — review may be incomplete for large PRs]"
        else:
            truncated_note = "\n[Diff summarized to reduce prompt size]"

        excerpt_block = (
            "\n".join(excerpt_lines).strip() or "(No excerpt lines captured)"
        )
        return (
            "### Diff Summary\n"
            f"- Files changed (detected): {len(files)}\n"
            f"- Added lines (detected): {added}\n"
            f"- Removed lines (detected): {removed}\n"
            "- Top changed files:\n"
            f"{file_lines}\n\n"
            "### Diff Excerpts\n"
            f"```diff\n{excerpt_block}\n```"
            f"{truncated_note}"
        )
