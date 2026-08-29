"""Kernel document bodies as FILES, not Python string literals.

Why this module exists
----------------------
``kernel_writer`` (the ``make stamp`` CLI) and ``templating`` (the
``/api/onboarding`` wizard) each held their own Python ``f``-string copy of the
same stamped documents — eleven same-named builders across two modules. They
had already drifted: the kernel's ``CLAUDE.md`` carried ownership markers and
the full rule set, the wizard's carried neither. The only thing nominally
holding the split was a sentence in ``kernel_writer``'s module docstring
saying so. Prose, enforced by nothing — the same shape as the ownership
markers that turned out to be read by no parser at all.

Document text now lives under ``hydraflow_resources/kernel_templates/bodies``
as real ``.md`` / ``.toml`` / ``.py`` files, so a change to a stamped document
is a diff in that document rather than a diff in a string literal, and both
writers read one set.

Placeholders are ``{{name}}``. Substitution is literal and non-recursive: a
rendered value is never re-scanned, so content that happens to contain braces
cannot inject a placeholder.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path

_PLACEHOLDER = re.compile(r"\{\{([a-z_]+)\}\}")


class KernelTemplateError(RuntimeError):
    """A body file is missing, or a placeholder was left unresolved."""


def bodies_root() -> Path:
    """Directory holding the stamped-document bodies."""
    return Path(__file__).resolve().parent.parent / (
        "hydraflow_resources/kernel_templates/bodies"
    )


@cache
def _body(name: str) -> str:
    path = bodies_root() / name
    if not path.is_file():
        raise KernelTemplateError(f"kernel template body not found: {path}")
    return path.read_text(encoding="utf-8")


def render(name: str, /, **values: object) -> str:
    """Render body *name*, substituting ``{{key}}`` for each keyword.

    Raises rather than emitting a half-substituted document: an unresolved
    placeholder shipped into a child repo would be a silent defect in a file
    nobody re-reads, which is precisely the failure mode this area keeps
    producing. Fail loud, never partially.
    """
    text = _body(name)
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    if leftover := sorted({m.group(1) for m in _PLACEHOLDER.finditer(text)}):
        raise KernelTemplateError(
            f"{name}: unresolved placeholder(s) {leftover}; "
            f"caller supplied {sorted(values)}"
        )
    return text
