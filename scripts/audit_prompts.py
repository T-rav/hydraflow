"""Prompt audit script — see docs/superpowers/specs/2026-04-20-prompt-audit-design.md."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditTarget:
    name: str
    builder_qualname: str
    fixture_path: str
    category: str
    call_site: str


PROMPT_REGISTRY: list[AuditTarget] = []


def main() -> None:
    raise NotImplementedError("wired up in later tasks")


if __name__ == "__main__":
    main()
