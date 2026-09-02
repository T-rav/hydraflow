"""#11991 AC2: the migration is reversible, proven by round-tripping it.

"An explicit reversible migration" is the kind of claim that is usually a
paragraph in a runbook. This asserts it: migrate, observe the resolver's answer
change, take the documented down-path, and observe the answer return to exactly
what it was — with the history still intact, because the store's rollback
creates a new revision rather than rewriting one.

The observation is made through `explain`, not through the store. A store that
holds the right rows and a resolver that answers differently are both true at
once, and only the second is what a spawn experiences.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from hydraflow_gateway.routing_policy import (  # noqa: E402
    PolicySource,
    RequestFace,
    explain,
)
from hydraflow_gateway.routing_workspace import PolicyWorkspace  # noqa: E402
from route_shadow import (  # noqa: E402
    LegacyRouteMechanism,
    RouteStage,
    build_route_context,
)
from routing_migration import (  # noqa: E402
    down_path_mutation,
    migrate_dials_to_policy,
)

_REPO = "acme/hydraflow"
_ACTOR = "migration-operator"
_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
_GLM = "glm-5.2"


@pytest.fixture(autouse=True)
def _zai_account_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a credential the resolver HOLDS, for reasons unrelated to this."""
    monkeypatch.setenv("ZAI_API_KEY", "migration-roundtrip-key")


@pytest.fixture
def config() -> HydraFlowConfig:
    """One moved dial — the smallest config the migration has work to do on."""
    return HydraFlowConfig(repo=_REPO, planner_provider="zai", planner_model=_GLM)


@pytest.fixture
def workspace(tmp_path: Path) -> PolicyWorkspace:
    return PolicyWorkspace(tmp_path / "routing", repo=_REPO)


def _source(workspace: PolicyWorkspace) -> PolicySource:
    """Who the resolver says decided a planner spawn, right now."""
    context = build_route_context(
        config=HydraFlowConfig(repo=_REPO, planner_provider="zai", planner_model=_GLM),
        principal_id="planner",
        final_provider="zai",
        final_model=_GLM,
        request_face=RequestFace.AGENTIC,
        stages=(
            RouteStage(
                mechanism=LegacyRouteMechanism.ROLE_DIAL,
                provider="zai",
                detail="planner_provider=zai",
            ),
        ),
    )
    return explain(context, workspace.read().snapshot).policy_source


def test_before_the_migration_the_route_is_legacy(
    workspace: PolicyWorkspace,
) -> None:
    """The starting point, asserted rather than assumed.

    Without this the round-trip below could 'return to legacy' from a state
    that was never anything else.
    """
    assert _source(workspace) is PolicySource.LEGACY_COMPATIBILITY


def test_the_migration_puts_a_managed_policy_in_charge(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """The up-path did something observable at the resolver."""
    migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    assert _source(workspace) is not PolicySource.LEGACY_COMPATIBILITY


def test_the_down_path_returns_the_route_to_legacy(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """AC2 itself: the reverse is one call, and the resolver agrees it worked."""
    result = migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    workspace.apply(down_path_mutation(result), actor=_ACTOR, now=_NOW)

    assert _source(workspace) is PolicySource.LEGACY_COMPATIBILITY


def test_the_down_path_restores_the_exact_policy_set(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """Not merely 'legacy again' — the same set, byte for byte.

    `policy_source` returning to legacy would also hold if the rollback had
    disabled the policies rather than removed them, or removed one of two.
    """
    before = workspace.read().snapshot.policies
    result = migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    workspace.apply(down_path_mutation(result), actor=_ACTOR, now=_NOW)

    assert workspace.read().snapshot.policies == before


def test_the_down_path_moves_forward_and_never_rewrites_history(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """Rollback creates a NEW revision; the migration's own stays readable."""
    result = migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    rolled = workspace.apply(down_path_mutation(result), actor=_ACTOR, now=_NOW)

    history = workspace.history()

    assert rolled.revision > result.revision
    assert history.verification.ok is True
    assert history.verification.records >= rolled.revision


def test_a_repository_with_no_moved_dial_migrates_nothing(
    workspace: PolicyWorkspace,
) -> None:
    """A no-op migration reports it, so nobody rolls back what never happened."""
    result = migrate_dials_to_policy(
        HydraFlowConfig(repo=_REPO), workspace, actor=_ACTOR, now=_NOW
    )

    assert (result.changed, result.installed) == (False, ())
    assert result.revision == result.prior_revision


def test_the_migration_reports_the_revision_the_down_path_needs(
    config: HydraFlowConfig, workspace: PolicyWorkspace
) -> None:
    """`prior_revision` is the whole reason the reverse is a call, not a hunt."""
    result = migrate_dials_to_policy(config, workspace, actor=_ACTOR, now=_NOW)

    assert result.changed is True
    assert down_path_mutation(result).target_revision == result.prior_revision
