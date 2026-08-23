"""Back-compat re-exports for the ``agent`` package.

The original ``src/agent.py`` (1715 lines / a 1388-LOC, 42-method
``AgentRunner``) was split into this package for mass discipline
(Refs #11547), the same shape ``review_phase/`` and ``implement_phase/``
already use. All existing imports keep working::

    from agent import AgentRunner   # still works
    import agent                    # still works

Layout:
  * ``_runner.py``     — the ``AgentRunner`` class: the self-check checklist,
    construction, the ``run`` entry point, the ``BaseRunner`` surface
    (``build_command`` / ``execute`` / ``verify_result``), and the thin
    ``skill_gate`` delegators.
  * ``_prompts.py``    — implement-prompt assembly.
  * ``_context.py``    — the untrusted-text inputs the prompt quotes.
  * ``_plan.py``       — plan-comment cleanup and the on-disk plan fallback.
  * ``_claude_md.py``  — the ``CLAUDE.md`` tamper guard.
  * ``_prequality.py`` — the pre-quality self-review loop.
  * ``_quality.py``    — the post-build quality gate and its fix loop.
  * ``_skills.py``     — skill execution and independent verification.
  * ``_commit.py``     — force-commit, commit counting, ``commit_pending``.

Each slice is a mixin ``AgentRunner`` inherits, so there is exactly ONE class
identity and every ``patch.object(AgentRunner, ...)`` target still resolves.
The mixins inherit ``BaseRunner`` themselves — they call ``self._execute`` and
one delegates to ``super()._verify_quality``, which only resolves when the base
is in the mixin's own MRO.

Two clusters are deliberately split by a name binding, not by concern: the
seven one-line ``skill_gate`` delegators and ``_extract_plan_comment`` name
``AgentRunner`` explicitly (the delegators pass ``self`` to functions annotated
``runner: AgentRunner``; ``_extract_plan_comment`` calls
``AgentRunner._strip_plan_noise``). They only work where the class is bound, so
they stay in ``_runner.py``. Moved verbatim — the class-name coupling is noted,
not fixed, in this structural PR.

**Patch targets follow their call site.** Module-level names the tests reach
through (``logger``, ``discover_plugin_skills``) are bound in the module that
CALLS them, so ``patch("agent.logger")`` would replace an attribute here and
leave the real binding untouched. Those are deliberately NOT re-exported —
patch ``agent._runner.logger`` / ``agent._prompts.discover_plugin_skills``
instead, and a stale target fails loudly rather than silently no-opping.
"""

from __future__ import annotations

from skill_registry import (
    AgentSkill,
    discover_tools,
    format_skills_for_prompt,
    format_tools_for_prompt,
    get_skills,
)

from ._runner import AgentRunner

__all__ = [
    "AgentRunner",
    "AgentSkill",
    "discover_tools",
    "format_skills_for_prompt",
    "format_tools_for_prompt",
    "get_skills",
]
