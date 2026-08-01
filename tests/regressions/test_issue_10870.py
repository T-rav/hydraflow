"""Regression for #10870: every auto_agent prompt template must render.

``prompts/auto_agent/`` templates are dispatched at escalation time. A template
that introduces an unknown ``{field}``, drops the ``{{> _envelope.md}}`` include,
or carries an unescaped literal brace raises at render time in production — with
no test failing beforehand. Two render families exist:

* ``render_prompt()`` — ``.format()``-based, lowercase fields — the sub-label
  "stuck" templates plus ``_default.md``.
* loop ``str.replace()`` — uppercase placeholders — ``pr_red_fix.md``
  (``pr_red_repair_loop._build_dispatch_prompt``) and ``sandbox_fix.md``
  (``sandbox_failure_fixer_loop._build_prompt``).

This renders/validates every template in both families so template↔code drift
fails here, not at escalation. Templates are discovered from the live prompt
directory, so a newly-added template is covered automatically.
"""

from __future__ import annotations

import re

import pytest

from preflight.runner import _PROMPT_DIR, render_prompt

# The envelope is a partial inlined into other templates, never rendered alone.
_ENVELOPE_PARTIAL = "_envelope"
# Rendered by their own loops via str.replace(), NOT render_prompt():
#   pr_red_fix.md  -> pr_red_repair_loop._build_dispatch_prompt
#   sandbox_fix.md -> sandbox_failure_fixer_loop._build_prompt
_REPLACE_FAMILY = {"pr_red_fix", "sandbox_fix"}
# The exact uppercase placeholders both loops substitute. Keep in sync with the
# .replace() chains in those two loops.
_REPLACE_KEYS = {
    "{PR_NUMBER}",
    "{PR_BRANCH}",
    "{CI_FAILURE_LOG}",
    "{RECENT_COMMIT_DIFFS}",
}

# Every keyword render_prompt() substitutes, with representative non-empty values.
_FULL_FIELDS = {
    "sub_label": "hydraflow-implement-stuck",
    "persona": "Test Persona",
    "issue_number": 123,
    "repo_slug": "owner/repo",
    "worktree_path": "/tmp/wt",
    "issue_body": "issue body text",
    "issue_comments_block": "[comments]",
    "escalation_context_block": "[escalation]",
    "wiki_excerpts_block": "[wiki]",
    "sentry_events_block": "[sentry]",
    "recent_commits_block": "[commits]",
    "prior_attempts_block": "[prior]",
}


def _render_prompt_stems() -> list[str]:
    return sorted(
        p.stem
        for p in _PROMPT_DIR.glob("*.md")
        if p.stem != _ENVELOPE_PARTIAL and p.stem not in _REPLACE_FAMILY
    )


@pytest.mark.parametrize("stem", _render_prompt_stems())
def test_render_prompt_template_renders(stem: str) -> None:
    """Every ``.format()``-family template renders with the full field set."""
    rendered = render_prompt(prompt_template=stem, **_FULL_FIELDS)
    assert rendered.strip(), f"{stem}.md rendered empty"
    # The envelope partial must be inlined, not left as the raw include token.
    assert "{{> _envelope.md}}" not in rendered, (
        f"{stem}.md left the envelope include unresolved"
    )


@pytest.mark.parametrize("stem", sorted(_REPLACE_FAMILY))
def test_replace_family_placeholders_are_provided(stem: str) -> None:
    """pr_red_fix/sandbox_fix use only placeholders their loops substitute."""
    text = (_PROMPT_DIR / f"{stem}.md").read_text(encoding="utf-8")
    used = set(re.findall(r"\{[A-Z][A-Z_]*\}", text))
    unknown = used - _REPLACE_KEYS
    assert not unknown, (
        f"{stem}.md uses placeholder(s) {sorted(unknown)} that neither loop "
        f"substitutes (provided: {sorted(_REPLACE_KEYS)}) — they would render "
        f"literally in the dispatched prompt"
    )
    # These are not render_prompt-based; they must not carry the include token.
    assert "{{> _envelope.md}}" not in text, (
        f"{stem}.md is replace-family but carries the render_prompt envelope include"
    )
