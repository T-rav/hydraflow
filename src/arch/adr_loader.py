from __future__ import annotations

import re
from pathlib import Path

from arch.models import AdrSummary

STATUS_RX = re.compile(r"^Status:\s*Accepted\s*$", re.IGNORECASE | re.MULTILINE)
SUPERSEDED_BY_RX = re.compile(
    r"^Superseded-by:\s*\S+\s*$", re.IGNORECASE | re.MULTILINE
)
TITLE_RX = re.compile(r"^#\s*(?:ADR\s*\d+:?\s*)?(.+)$", re.MULTILINE)
SLUG_NUMBER_RX = re.compile(r"^(\d+)")


def load_accepted_adrs(repo_path: str) -> list[AdrSummary]:
    adr_dir = Path(repo_path) / "docs" / "adr"
    if not adr_dir.is_dir():
        return []

    summaries: list[AdrSummary] = []
    for path in sorted(adr_dir.glob("*.md")):
        slug = path.stem
        if slug.lower() == "readme":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        header = "\n".join(text.splitlines()[:30])
        if not STATUS_RX.search(header):
            continue
        if SUPERSEDED_BY_RX.search(header):
            continue
        title_match = TITLE_RX.search(text)
        title = title_match.group(1).strip() if title_match else slug
        number_match = SLUG_NUMBER_RX.match(slug)
        number = number_match.group(1) if number_match else ""
        one_line = _extract_one_line(text)
        summaries.append(
            AdrSummary(slug=slug, number=number, title=title, one_line=one_line)
        )

    return summaries


def _extract_one_line(text: str) -> str:
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.lower().startswith(("status:", "superseded-by:", "supersedes:")):
            continue
        return s[:160]
    return ""
