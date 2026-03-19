"""Shared prompt text utilities for agent runners.

Provides text truncation and summarization helpers used by both
``AgentRunner`` and ``PlannerRunner`` when building prompts.
"""

from __future__ import annotations

import re
from collections.abc import Callable


def truncate_text(text: str, char_limit: int, line_limit: int) -> str:
    """Truncate *text* at a line boundary, also breaking long lines.

    Lines exceeding *line_limit* are hard-truncated to avoid producing
    unsplittable chunks that crash Claude CLI's text splitter.
    """
    lines: list[str] = []
    total = 0
    for raw_line in text.splitlines():
        capped = (
            raw_line[:line_limit] + "\u2026" if len(raw_line) > line_limit else raw_line
        )
        if total + len(capped) + 1 > char_limit:
            break
        lines.append(capped)
        total += len(capped) + 1  # +1 for newline
    result = "\n".join(lines)
    if len(result) < len(text):
        result += "\n\n\u2026(truncated)"
    return result


def summarize_for_prompt(text: str, max_chars: int, label: str) -> str:
    """Return *text* trimmed for prompt efficiency with a traceable note."""
    if len(text) <= max_chars:
        return text

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    cue_lines = [ln for ln in lines if re.match(r"^([-*]|\d+\.)\s+", ln) or "## " in ln]
    selected = cue_lines[:10] if cue_lines else lines[:10]
    compact = "\n".join(f"- {ln[:200]}" for ln in selected).strip()
    if not compact:
        compact = text[:max_chars]
    return (
        f"{compact}\n\n"
        f"[{label} summarized from {len(text):,} chars to reduce prompt size]"
    )


def truncate_comment(text: str, limit: int) -> str:
    """Return one discussion comment compacted for prompt efficiency."""
    raw = (text or "").strip()
    if len(raw) <= limit:
        return raw
    return raw[:limit] + f"\n[Comment truncated from {len(raw):,} chars]"


def build_comments_section(
    comments: list[str],
    *,
    max_comments: int = 6,
    truncate_fn: Callable[[str], str] | None = None,
) -> tuple[str, str, str]:
    """Build a discussion comments section from issue comments.

    Returns ``(section_text, raw_joined, formatted)`` where
    *section_text* is the ready-to-use prompt section (empty string if
    no comments), *raw_joined* is the concatenated raw comments, and
    *formatted* is the truncated/formatted text for stats recording.
    """
    if not comments:
        return "", "", ""

    selected = comments[:max_comments]
    if truncate_fn is not None:
        compact = [truncate_fn(c) for c in selected]
    else:
        compact = [c.strip() for c in selected]

    formatted = "\n".join(f"- {c}" for c in compact)
    section = f"\n\n## Discussion\n{formatted}"
    if len(comments) > max_comments:
        section += f"\n- ... ({len(comments) - max_comments} more comments omitted)"

    return section, "".join(comments), formatted
