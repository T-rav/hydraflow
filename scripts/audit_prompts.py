"""Prompt audit script — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class AuditTarget:
    name: str
    builder_qualname: str
    fixture_path: str
    category: str
    call_site: str


PROMPT_REGISTRY: list[AuditTarget] = []

# ---------------------------------------------------------------------------
# Rubric #1 — leads with the request
# ---------------------------------------------------------------------------

IMPERATIVE_VERBS = frozenset(
    {
        "produce",
        "return",
        "generate",
        "classify",
        "review",
        "decide",
        "output",
        "propose",
        "write",
        "summarize",
    }
)


def _split_sentences(text: str) -> list[str]:
    """Split on `.`, `?`, `!`, `:` — any of which can end a directive sentence."""
    return [s.strip() for s in re.split(r"(?<=[.!?:])\s+", text) if s.strip()]


def score_leads_with_request(rendered: str) -> str:
    stripped = re.sub(r"<\w+>.*?</\w+>", "", rendered, flags=re.DOTALL).strip()
    sentences = _split_sentences(stripped)
    for idx, sentence in enumerate(sentences):
        words = set(re.findall(r"[A-Za-z]+", sentence.lower()))
        if words & IMPERATIVE_VERBS:
            if idx == 0:
                return "Pass"
            if idx <= 2:
                return "Partial"
            return "Fail"
    return "Fail"


def main() -> None:
    raise NotImplementedError("wired up in later tasks")


if __name__ == "__main__":
    main()
