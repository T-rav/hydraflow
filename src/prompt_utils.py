"""Shared prompt-building utilities for agent runners."""

from __future__ import annotations


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
    """Return *text* trimmed for prompt efficiency with a traceable note.

    Extracts bullet/heading cue lines when available, otherwise takes the
    first 10 lines.
    """
    import re  # noqa: PLC0415

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


def truncate_comment(text: str, max_chars: int) -> str:
    """Return one discussion comment compacted for prompt efficiency."""
    raw = (text or "").strip()
    if len(raw) <= max_chars:
        return raw
    return raw[:max_chars] + f"\n[Comment truncated from {len(raw):,} chars]"


def build_comments_section(
    comments: list[str],
    max_comments: int,
    max_comment_chars: int,
    *,
    truncate_fn: callable | None = None,  # type: ignore[type-arg]
) -> tuple[str, int, int]:
    """Build a discussion comments section from *comments*.

    Returns ``(section_text, chars_before, chars_after)``.
    *truncate_fn* defaults to :func:`truncate_comment` with *max_comment_chars*.
    """
    if not comments:
        return "", 0, 0

    chars_before = sum(len(c) for c in comments)
    if truncate_fn is None:

        def truncate_fn(c: str) -> str:
            return truncate_comment(c, max_comment_chars)

    selected = comments[:max_comments]
    compact = [truncate_fn(c) for c in selected]
    formatted = "\n".join(f"- {c}" for c in compact)
    chars_after = len(formatted)
    section = f"\n\n## Discussion\n{formatted}"
    if len(comments) > max_comments:
        section += f"\n- ... ({len(comments) - max_comments} more comments omitted)"
    return section, chars_before, chars_after
