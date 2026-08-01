"""Regression: prompt-audit fixtures can override config to score config-gated
branches (#10872).

``scripts/audit_prompts.py`` built one ``_MinimalConfig`` per render, resolving
every field from the real ``HydraFlowConfig`` defaults. A prompt builder with a
config-gated alternative branch — ``reviewer._build_review_prompt_with_stats``'s
``elif self._config.use_quality_gate_in_review`` chain, which is dead whenever
``max_ci_fix_attempts > 0`` (the production default is 2) — could therefore never
be rendered or scored under any fixture, so that branch drifted unmeasured.

Fix: a fixture may declare an optional ``config_overrides`` map. It is threaded
into ``_MinimalConfig`` so the named fields take the override value instead of
the production default, letting a fixture flip ``max_ci_fix_attempts=0`` +
``use_quality_gate_in_review=True`` and exercise the otherwise-dead branch. With
no overrides the config resolves exactly as before.
"""

from __future__ import annotations

from scripts.audit_prompts import (
    PROMPT_REGISTRY,
    _MinimalConfig,
    load_fixture,
    render_target,
)

from config import declared_default_config

# Strings that only ONE branch of the verify_step / fix_verify chain emits.
_QUALITY_GATE_MARKER = "Run `make quality` to verify everything passes"
_QUALITY_GATE_FIX_MARKER = "architecture tests only run under the full suite"
_CI_MARKER = "CI will verify these automatically after review."


def _target(name: str):
    matches = [t for t in PROMPT_REGISTRY if t.name == name]
    assert len(matches) == 1, f"expected exactly one registry entry named {name!r}"
    return matches[0]


def test_minimal_config_honors_fixture_overrides() -> None:
    cfg = _MinimalConfig(
        config_overrides={
            "use_quality_gate_in_review": True,
            "max_ci_fix_attempts": 0,
        }
    )
    assert cfg.use_quality_gate_in_review is True
    assert cfg.max_ci_fix_attempts == 0


def test_minimal_config_without_overrides_resolves_production_defaults() -> None:
    # The default (no-override) path is unchanged: fields still fall through to
    # the real HydraFlowConfig default. max_ci_fix_attempts stays > 0, so the
    # ci-enabled branch wins and the quality-gate branch stays dead — exactly
    # the condition that made it unscorable before this fix.
    cfg = _MinimalConfig()
    real = declared_default_config()
    assert cfg.max_ci_fix_attempts == real.max_ci_fix_attempts
    assert cfg.max_ci_fix_attempts > 0


def test_override_fixture_declares_config_overrides() -> None:
    fixture = load_fixture(_target("reviewer_build_review_quality_gate").fixture_path)
    assert fixture.config_overrides == {
        "use_quality_gate_in_review": True,
        "max_ci_fix_attempts": 0,
    }


def test_override_fixture_renders_the_quality_gate_branch() -> None:
    rendered = render_target(_target("reviewer_build_review_quality_gate"))
    assert _QUALITY_GATE_MARKER in rendered
    assert _QUALITY_GATE_FIX_MARKER in rendered
    assert _CI_MARKER not in rendered


def test_default_fixture_renders_the_ci_branch() -> None:
    rendered = render_target(_target("reviewer_build_review"))
    assert _CI_MARKER in rendered
    assert _QUALITY_GATE_MARKER not in rendered
