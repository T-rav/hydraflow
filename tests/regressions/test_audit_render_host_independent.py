"""Regression: the prompt audit render must not depend on the host machine.

``render_target`` builders call ``discover_plugin_skills``, which scans
``~/.claude/plugins/cache`` — the operator's real machine. That broke
ADR-0087's "same input → same score" contract three ways at once:

- CI runners have no plugin cache → agent prompts rendered WITHOUT the
  ``## Available Skills`` section (criterion-6 pin test passed).
- A local *isolated* run imported ``plugin_skill_registry`` lazily, after
  conftest's session fixture patched ``HOME=/tmp/hydraflow-test`` → empty
  cache root → section absent → passed.
- A local *full-suite* run imported ``agent`` at collection time, before the
  HOME patch, so the module-level ``DEFAULT_CACHE_ROOT`` constant captured the
  real home → the operator's installed skill descriptions (+~1.4k chars)
  rendered into the prompt → ``test_criterion6_fixture_set_is_pinned`` failed
  on a fixture CI said was under threshold.

Two-layer fix pinned here:

1. ``default_cache_root()`` resolves ``Path.home()`` at call time, so the
   conftest HOME redirect applies regardless of import order.
2. ``render_target`` patches the builder module's ``discover_plugin_skills``
   with the checked-in ``_AUDIT_PLUGIN_SKILLS`` set, so the audit scores the
   section production always injects — identically on every host.
"""

from __future__ import annotations

from pathlib import Path

import plugin_skill_registry
from scripts import audit_prompts as audit
from scripts.audit_prompts import PROMPT_REGISTRY

_SENTINEL_DESCRIPTION = "HOST-LEAK-SENTINEL do not render this text"


def _fake_home_with_cache(tmp_path: Path) -> Path:
    """A fake HOME whose plugin cache contains an allowlisted, phase-eligible
    skill with a sentinel description — visible iff the audit reads the host."""
    skill_dir = (
        tmp_path
        / ".claude"
        / "plugins"
        / "cache"
        / "claude-plugins-official"
        / "superpowers"
        / "skills"
        / "test-driven-development"
    )
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        "name: test-driven-development\n"
        f"description: {_SENTINEL_DESCRIPTION}\n"
        "---\n"
        "body\n"
    )
    return tmp_path


def _render_agent_fixture() -> str:
    target = next(
        t for t in PROMPT_REGISTRY if t.name == "agent_build_prompt_with_prior_failure"
    )
    return audit.render_target(target)


def test_default_cache_root_resolves_home_at_call_time(
    tmp_path: Path, monkeypatch
) -> None:
    home = _fake_home_with_cache(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    assert plugin_skill_registry.default_cache_root() == (
        home / ".claude" / "plugins" / "cache"
    )


def test_render_ignores_host_plugin_cache(tmp_path: Path, monkeypatch) -> None:
    home = _fake_home_with_cache(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    plugin_skill_registry.clear_plugin_skill_cache()
    try:
        rendered = _render_agent_fixture()
    finally:
        plugin_skill_registry.clear_plugin_skill_cache()

    # The host's cache never leaks in...
    assert _SENTINEL_DESCRIPTION not in rendered
    # ...and the deterministic section production injects is always present.
    assert "## Available Skills" in rendered
    assert "superpowers:test-driven-development" in rendered


def test_render_length_is_host_invariant(tmp_path: Path, monkeypatch) -> None:
    """Same fixture, with and without a populated host cache → identical render."""
    plugin_skill_registry.clear_plugin_skill_cache()
    baseline = _render_agent_fixture()

    home = _fake_home_with_cache(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    plugin_skill_registry.clear_plugin_skill_cache()
    try:
        with_cache = _render_agent_fixture()
    finally:
        plugin_skill_registry.clear_plugin_skill_cache()

    assert with_cache == baseline
