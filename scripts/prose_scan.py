#!/usr/bin/env python3
"""Prose-hygiene scan for the authored docs corpus.

Ported from the book assembler's mechanical language advisories. Read-only.
Skips generated dirs and raw transcript dumps. Reports house-neutral defect
classes only. Tuned 2026-07-31 so hyphenated compounds (in in-memory),
relative links (../), range notation (PI-01..PI-07), and TODO-as-content do
not false-fire.
"""

from __future__ import annotations

import pathlib
import re

ROOTS = ["docs", "README.md", "CLAUDE.md"]
SKIP = (
    "docs/arch/generated/",
    "docs/prompt-audit",
    "docs/_prompt_audit",
    "docs/superpowers/plans/",
)
DBL = re.compile(r"\b(\w+)\s+\1(?!-)\b", re.IGNORECASE)
STOP = {"that", "had", "the", "a", "is", "of", "to", "no", "in"}
PUNCT = re.compile(r"\w +[,.;:](?= )|,,|(?<![\w./])\.\.(?![\w./])|\?\?")
FRAGMENT = re.compile(r"^(Now|Then|Here|Next) the \w+, (once|twice)\.$")
TODO = re.compile(r"^\s*(<!--\s*)?(TODO|FIXME|XXX)[:\s]")
LINK = re.compile(r"\]\(([^)]+\.md)[^)#]*\)")


def collect_files() -> list[pathlib.Path]:
    files: list[pathlib.Path] = []
    for root in ROOTS:
        path = pathlib.Path(root)
        if path.is_file():
            candidates = [path]
        elif path.is_dir():
            candidates = list(path.rglob("*.md"))
        else:
            candidates = []
        files.extend(f for f in candidates if not str(f).startswith(SKIP))
    return sorted(files)


def scan() -> dict[str, list[str]]:
    hits: dict[str, list[str]] = {
        "doubled word": [],
        "double/space punctuation": [],
        "telegraphic fragment": [],
        "dangling TODO marker": [],
        "broken relative link": [],
    }
    for path in collect_files():
        try:
            lines = path.read_text().splitlines()
        except OSError:
            continue
        in_code = False
        for lineno, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("```"):
                in_code = not in_code
                continue
            if in_code or stripped.startswith(("|", ">", "    ")) or "`" in line:
                continue
            loc = f"{path}:{lineno}"
            for match in DBL.finditer(line):
                if match.group(1).lower() not in STOP:
                    hits["doubled word"].append(f"{loc}: {match.group(0)!r}")
            if PUNCT.search(line):
                hits["double/space punctuation"].append(loc)
            if FRAGMENT.match(stripped):
                hits["telegraphic fragment"].append(f"{loc}: {stripped!r}")
            if TODO.match(line):
                hits["dangling TODO marker"].append(f"{loc}: {stripped[:60]}")
            for match in LINK.finditer(line):
                target = (path.parent / match.group(1)).resolve()
                if not target.exists() and not match.group(1).startswith(("http", "/")):
                    hits["broken relative link"].append(f"{loc}: {match.group(1)}")
    return hits


def main() -> None:
    hits = scan()
    files = collect_files()
    print(
        f"scanned {len(files)} authored markdown files (generated + transcripts excluded)\n"
    )
    total = 0
    for label, found in hits.items():
        total += len(found)
        print(f"== {label}: {len(found)} ==")
        for item in found[:12]:
            print(f"  {item}")
        if len(found) > 12:
            print(f"  ... +{len(found) - 12} more")
    print(f"\ntotal genuine hits: {total}")


if __name__ == "__main__":
    main()
