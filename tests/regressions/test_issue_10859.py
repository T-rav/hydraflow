"""Regression: HydraFlowConfig reads .env / os.environ at audit time (#10859).

ADR-0087 requires the prompt audit's mechanical scoring to be reproducible —
"same input -> same score, always." PR #10856 fixed a real fidelity bug by
making the harness defer to the real HydraFlowConfig defaults instead of
hand-invented placeholder numbers, but ``_real_config_defaults()`` built that
"real" config with a bare ``HydraFlowConfig()``, which runs
``resolve_defaults`` unconditionally: ``_apply_env_overrides`` reads
``HYDRAFLOW_*``/``HYDRA_*`` (and other declared) env vars, and the
git-identity step reads ``repo_root/.env`` directly via ``_dotenv_lookup``.
Verified while investigating this issue: ``HYDRAFLOW_MIN_REVIEW_FINDINGS=9``
reached the rendered corpus. A developer's stray ``.env`` entry, or a CI
runner with a different environment, would see baseline failures that
reproduce nowhere else — indistinguishable from a real prompt regression.

Fix: ``_real_config_defaults()`` now builds its config via
``config.declared_default_config()``, which scrubs every env-override key
(``config.env_override_keys()``) plus any live ``HYDRAFLOW_*``/``HYDRA_*``
key, and defaults ``repo_root`` to a fresh empty temp dir so
``_dotenv_lookup`` never finds a ``.env`` to read.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from scripts.audit_prompts import _real_config_defaults


@pytest.fixture(autouse=True)
def _clear_real_config_defaults_cache():
    _real_config_defaults.cache_clear()
    yield
    _real_config_defaults.cache_clear()


def test_min_review_findings_ignores_env_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact reproduction from the issue: HYDRAFLOW_MIN_REVIEW_FINDINGS=9
    must not reach the captured corpus the audit renders prompts from."""
    monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "9")
    captured = _real_config_defaults()
    assert captured["min_review_findings"] == 3


def test_rendered_corpus_is_byte_identical_with_and_without_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issue's acceptance criterion: the captured field dict every
    rendered prompt is built from must be identical whether or not a
    representative HYDRAFLOW_* override set is exported in the audit's
    environment — spanning a table-driven field, a non-prefixed table-driven
    field, an inline list-typed field, and the git-identity fallback."""
    baseline = _real_config_defaults()

    monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "9")
    monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", "50000")
    monkeypatch.setenv("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "leaked-user")
    monkeypatch.setenv("LOG_INGEST_INTERVAL", "99999")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Leaked Committer")
    _real_config_defaults.cache_clear()
    overridden = _real_config_defaults()

    assert overridden == baseline


def test_full_rendered_prompt_corpus_is_byte_identical_with_and_without_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The issue's acceptance criterion literally, not just the intermediate
    captured-field dict: actual rendered prompt text for every registry
    target must be byte-identical whether or not a representative
    HYDRAFLOW_* override set is exported in the audit's environment. The
    dict-level test above is a good proxy since ``_MinimalConfig.__getattr__``
    reads straight from that dict, but only rendering the real corpus proves
    no builder bypasses that layer."""
    from scripts.audit_prompts import PROMPT_REGISTRY, render_target

    targets = [t for t in PROMPT_REGISTRY if not t.unrenderable]
    assert len(targets) >= 60  # sanity: registry isn't accidentally empty/gutted

    baseline = {t.name: render_target(t) for t in targets}

    monkeypatch.setenv("HYDRAFLOW_MIN_REVIEW_FINDINGS", "9")
    monkeypatch.setenv("HYDRAFLOW_MAX_REVIEW_DIFF_CHARS", "50000")
    monkeypatch.setenv("HYDRAFLOW_HUMAN_STEERING_AUTHORIZED_USERS", "leaked-user")
    monkeypatch.setenv("LOG_INGEST_INTERVAL", "99999")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Leaked Committer")
    _real_config_defaults.cache_clear()
    overridden = {t.name: render_target(t) for t in targets}

    assert overridden == baseline


def test_git_identity_leak_from_dotenv_does_not_reach_the_corpus(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """os.environ scrubbing alone cannot close this hole: ``_dotenv_lookup``
    reads ``repo_root/.env`` directly, bypassing ``os.environ`` entirely.
    Regression coverage for a caller — like this audit script — that never
    passes an explicit ``repo_root``: ``declared_default_config()`` must
    default to a fresh temp dir rather than trust the auto-detected checkout
    root, or a real ``.env`` sitting next to ``cwd`` would leak in."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("HYDRAFLOW_GIT_USER_NAME=leaked-from-dotenv\n")
    captured = _real_config_defaults()
    assert captured["git_user_name"] == ""


def test_uses_declared_default_config_not_a_bare_hydraflowconfig() -> None:
    """Pin the fix to declared_default_config() specifically, not merely
    'some env scrubbing somewhere' — a future refactor that reintroduces a
    bare HydraFlowConfig() call here would silently reopen this issue."""
    source = inspect.getsource(_real_config_defaults)
    assert "cfg = declared_default_config()" in source
    assert "cfg = HydraFlowConfig()" not in source
