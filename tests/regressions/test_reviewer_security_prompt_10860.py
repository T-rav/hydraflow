"""Regression: the reviewer prompt must always carry a security-audit
instruction (#10860).

PR #10981 pruned the long production prompts to save tokens and dropped the
always-on security-review guidance from
``reviewer._build_review_prompt_with_stats`` entirely — both the
"... security risks ..." review dimension and the
"Check for security issues (injection, crypto, auth)" audit bullet. The
ADR-0087 form rubric scores prompt *structure*, not *content*, so it could not
see the loss; the semantic prune judge missed it too. Only fresh-eyes code
review caught it. The ``review_advisor`` security lens is conditional (gated
behind separate kill-switches) and is not a substitute for the unconditional
instruction in the base review prompt.

This pins the security dimension across both rendered variants so a future
prune cannot silently drop it again.
"""

from __future__ import annotations

import pytest
from scripts.audit_prompts import PROMPT_REGISTRY, render_target


def _target(name: str):
    matches = [t for t in PROMPT_REGISTRY if t.name == name]
    assert len(matches) == 1, f"expected exactly one registry entry named {name!r}"
    return matches[0]


@pytest.mark.parametrize(
    "name", ["reviewer_build_review", "reviewer_build_review_quality_gate"]
)
def test_reviewer_prompt_always_includes_security_audit(name: str) -> None:
    rendered = render_target(_target(name))
    assert "Security" in rendered, (
        f"{name} lost its always-on security-audit instruction (#10860)"
    )
    lower = rendered.lower()
    # Spot-check the specific risk classes the instruction must name.
    assert "injection" in lower
    assert "auth" in lower
