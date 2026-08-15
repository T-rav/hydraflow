"""Scenario: two repos on different harness backends run side by side (#11211).

Direction item 3 (concurrency): both backend pools live simultaneously — each
registered repo owns an independent ``HydraFlowConfig`` and orchestrator, so a
GLM-native repo and a Claude-native repo coexist in one registry without one's
backend selection leaking into the other's. Direction item 3 also calls out
composing with credit-failover (ADR-0119, #10844): its process-wide engage
flag never overrides a repo already pinned to GLM (``repo_backend`` short-
circuits before ``credit_failover`` even sees a non-"claude" provider) — this
scenario proves both halves on two runtimes registered and running
concurrently: independent, correctly-isolated per-repo
``HydraFlowConfig.repo_provider`` values, AND (via the real
``apply_repo_provider``/``apply_credit_failover`` seam functions, not just a
config-field read) that a sibling's engaged Claude-cap failover never moves
the GLM-native repo's resolved spawn provider or model.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_two_repos_resolve_independent_backends_concurrently(
    mock_world, tmp_path
) -> None:
    mock_world.add_repo(
        "owner/claude-repo", str(tmp_path / "claude-repo"), repo_provider="claude"
    )
    mock_world.add_repo(
        "owner/glm-repo",
        str(tmp_path / "glm-repo"),
        repo_provider="zai",
        repo_model="glm-5.2",
    )

    claude_repo = mock_world.registry.get("owner-claude-repo")
    glm_repo = mock_world.registry.get("owner-glm-repo")

    # Both runtimes are registered and present simultaneously (no repo evicts
    # or overwrites the other's slot) — the "concurrently" half of Direction
    # item 3; each owns its own config/event-bus, not a shared singleton.
    assert claude_repo is not None
    assert glm_repo is not None
    assert claude_repo is not glm_repo
    assert claude_repo.config is not glm_repo.config

    # Each resolves its own backend — a GLM-native repo is not dragged onto
    # Claude by a sibling repo's default, and vice versa.
    assert claude_repo.config.repo_provider == "claude"
    assert glm_repo.config.repo_provider == "zai"
    assert glm_repo.config.repo_model == "glm-5.2"

    # A repo with no explicit dial keeps the factory-wide default ("claude"),
    # unaffected by a sibling repo's repo_provider override.
    assert claude_repo.config.repo_model == ""


@pytest.mark.asyncio
async def test_glm_native_repo_provider_unaffected_by_a_sibling_claude_cap(
    mock_world, tmp_path, monkeypatch
) -> None:
    """A repo pinned to GLM stays resolved to "zai" regardless of another
    repo's Claude-credit state — the composition ADR-0119's process-wide
    failover flag must respect (Direction item 3).

    Resolves through the real spawn-seam functions (``apply_repo_provider``
    then ``apply_credit_failover``, mirroring ``base_runner._execute``) rather
    than re-reading ``config.repo_provider`` — a bare config-field assertion
    would pass unchanged even with ``apply_repo_provider`` deleted, since
    nothing in this scenario mutates the config object itself. ``repo_model``
    is deliberately set to a value distinct from ``credit_failover_model``'s
    default ("glm-5.2") so the resolved ``--model`` also proves
    ``apply_repo_provider`` — not credit-failover's own independent reroute —
    is what routed this repo, even though failover is globally engaged.
    """
    import credit_failover
    from repo_backend import apply_repo_provider

    monkeypatch.setenv("ZAI_API_KEY", "k")
    mock_world.add_repo(
        "owner/claude-repo", str(tmp_path / "claude-repo"), repo_provider="claude"
    )
    mock_world.add_repo(
        "owner/glm-repo",
        str(tmp_path / "glm-repo"),
        repo_provider="zai",
        repo_model="glm-4.6",
    )

    from datetime import UTC, datetime

    credit_failover.reset_for_tests()
    try:
        # Simulate the claude-repo having hit an authoritative Anthropic cap
        # and engaged the (process-wide) failover flag.
        credit_failover.engage(
            now=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            resume_at=None,
            cooldown_minutes=15,
        )
        glm_repo = mock_world.registry.get("owner-glm-repo")
        cmd = ["claude", "--model", "claude-opus-4-8"]
        provider, cmd = apply_repo_provider("claude", cmd, glm_repo.config)
        provider, cmd = credit_failover.apply_credit_failover(
            provider, cmd, glm_repo.config
        )
        # The repo's spawn resolves to its OWN "zai"/"glm-4.6" dial, not the
        # sibling's Claude cap nor credit-failover's own "glm-5.2" default —
        # proof that apply_repo_provider (run before apply_credit_failover at
        # both spawn seams) is what routed it, regardless of the global
        # failover flag.
        assert provider == "zai"
        assert cmd.count("--model") == 1
        assert "glm-4.6" in cmd
        assert glm_repo.config.repo_provider == "zai"
    finally:
        credit_failover.reset_for_tests()
