"""Ratchet: every Markdown prompt template is governed (#10858).

``prompt_fitness.discovered_builders()`` walks ``src/**/*.py`` only, so the
model-bound Markdown prompts under ``prompts/auto_agent/*.md`` (loaded by
``preflight.runner.render_prompt``) and the agent contracts under
``.claude/agents/*.md`` are prompts by every definition ADR-0116 uses, yet the
coverage series never sees them: it reads 100% while a whole artifact class sits
outside the denominator, and a 20th template can be added with no fixture, no
score, and nothing failing.

This guard closes the *silent-growth* half now: every Markdown prompt template
must be declared — ``MEASURED`` (a registered fixture renders and scores it) or
``GRANDFATHERED`` (known-unmeasured debt). A new template fails until it is
classified. Actually scoring the 20 grandfathered templates against the ADR-0087
rubric is the burn-down; this makes the inventory durable so the gap can't grow
unseen. Mirrors the module-state audit (#10889) and the Python-builder registry
ratchet (test_prompt_registry_completeness.py).
"""

from __future__ import annotations

import pathlib

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
_AUTO_AGENT = _REPO / "prompts" / "auto_agent"
_CLAUDE_AGENTS = _REPO / ".claude" / "agents"

#: Templates a registered fixture already renders + scores. ``_default.md`` and
#: ``_envelope.md`` are covered by the ``preflight_auto_agent`` builder
#: (``scripts/audit_prompts.py`` → ``tests/fixtures/prompts/preflight_auto_agent.json``,
#: registered in PR #10856).
_MEASURED = frozenset(
    {
        "prompts/auto_agent/_default.md",
        "prompts/auto_agent/_envelope.md",
    }
)

#: Known-unmeasured Markdown prompts (the #10858 debt). Each should eventually
#: gain a rendering fixture + rubric score and move to :data:`_MEASURED`; the
#: ratchet forbids this set from growing.
_GRANDFATHERED = frozenset(
    {
        # #11298 light-lane builder — declared at introduction; burn-down:
        # register a preflight_auto_agent-style fixture rendering the
        # auto-light template and move to _MEASURED.
        "prompts/auto_agent/auto-light.md",
        # prompts/auto_agent specialist sub-label templates
        "prompts/auto_agent/discover-stuck.md",
        "prompts/auto_agent/fake-coverage-stuck.md",
        "prompts/auto_agent/fake-drift-stuck.md",
        "prompts/auto_agent/flaky-test-stuck.md",
        "prompts/auto_agent/implement-cap-exhausted.md",
        "prompts/auto_agent/implement-stuck.md",
        "prompts/auto_agent/plan-stuck.md",
        "prompts/auto_agent/pr_red_fix.md",
        "prompts/auto_agent/rc-duration-stuck.md",
        "prompts/auto_agent/rc-red-bisect-exhausted.md",
        "prompts/auto_agent/revert-conflict.md",
        "prompts/auto_agent/review-stuck.md",
        "prompts/auto_agent/sandbox_fix.md",
        "prompts/auto_agent/skill-prompt-stuck.md",
        "prompts/auto_agent/triage-stuck.md",
        "prompts/auto_agent/trust-loop-anomaly.md",
        "prompts/auto_agent/wiki-rot-stuck.md",
        # .claude/agents contracts (the issue notes the same gap applies)
        ".claude/agents/hf.code-quality-enforcer.md",
        ".claude/agents/hf.test-audit.md",
        ".claude/agents/hydraflow-review-advisor.md",
    }
)

_GRANDFATHERED_MAX = len(_GRANDFATHERED)


def discover_markdown_prompt_templates() -> set[str]:
    """``<repo-relative-path>`` for every Markdown prompt template."""
    found: set[str] = set()
    for directory in (_AUTO_AGENT, _CLAUDE_AGENTS):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.md")):
            found.add(path.relative_to(_REPO).as_posix())
    return found


def test_every_markdown_prompt_template_is_governed() -> None:
    found = discover_markdown_prompt_templates()
    governed = _MEASURED | _GRANDFATHERED
    ungoverned = sorted(found - governed)
    assert not ungoverned, (
        "New Markdown prompt template(s) not declared in this governance ratchet "
        "(#10858). Add a rendering fixture + rubric score and list under "
        f"_MEASURED, or record as _GRANDFATHERED debt: {ungoverned}"
    )


def test_governance_registry_has_no_stale_entries() -> None:
    found = discover_markdown_prompt_templates()
    stale = sorted((_MEASURED | _GRANDFATHERED) - found)
    assert not stale, (
        "Governance registry lists a Markdown template that no longer exists — "
        f"the file was renamed or removed; drop the entry: {stale}"
    )


def test_grandfathered_debt_does_not_grow() -> None:
    # Burn-down, not just a ceiling: the unmeasured set may only shrink.
    present = discover_markdown_prompt_templates() & _GRANDFATHERED
    assert len(present) <= _GRANDFATHERED_MAX, (
        f"the unmeasured-template debt grew to {len(present)} (pinned at "
        f"{_GRANDFATHERED_MAX}). Score the new template and put it in _MEASURED, "
        "not _GRANDFATHERED."
    )


def test_measured_and_grandfathered_are_disjoint() -> None:
    overlap = _MEASURED & _GRANDFATHERED
    assert not overlap, (
        f"a template is both measured and grandfathered: {sorted(overlap)}"
    )
