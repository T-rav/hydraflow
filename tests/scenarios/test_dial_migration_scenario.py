"""MockWorld scenario: a repository's dials become policy, and no route moves.

#11991 AC5. The unit tests prove the generator's output resolves to what each
dial produces, and that the migration round-trips. Neither can see the property
this epic actually turns on, because it is a property of a **live turn**: while
the migration is installed, a real spawn must reach the same upstream with the
same bytes it reached before.

That is #11853's shape stated positively. A dial that stops steering does not
raise — it routes to a default that looks reasonable — so "nothing broke" is
not observable from the migration's own return value, from the store, or from
any assertion about the policies. It is observable at the external boundary,
which is what this drives: the real dashboard policy routes, the real
write-ahead journal, the real atomic snapshot replace, the real hash-linked
mutation chain, the real shadow resolver, the real gateway control plane, mint,
proxy and ledger. Only the Claude subprocess and the Anthropic origin are fakes.

The migration installs policies that nothing reads yet, so the route is
expected to be byte-identical — and asserting that BEFORE the switch is the
point. When the resolver does start reading policy, this scenario is the thing
that was already true and has to stay true.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import pytest

from hydraflow_gateway.routing_workspace import PolicyWorkspace
from route_shadow import routing_dir
from routing_migration import down_path_mutation, migrate_dials_to_policy
from tests.helpers import ConfigFactory
from tests.scenarios.helpers.gateway_turn import run_gateway_turn

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "dial-migration-scenario-control-token-0123"
_PROVIDER_KEY = "dial-migration-scenario-real-provider-key"
_VIRTUAL_SECRET = "dial-migration-scenario-virtual-secret"
_REPO = "acme/project-x"
_ACTOR = "migration-operator"
_NOW = datetime(2026, 9, 2, 12, 0, 0, tzinfo=UTC)
_GLM = "glm-5.2"


@dataclass(slots=True)
class _Repo:
    """One repository: its config, and the workspace its policies live in."""

    config: Any
    workspace: PolicyWorkspace


def _repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Repo:
    """A repo with one dial moved off its default, so migration has work."""
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("ZAI_API_KEY", "dial-migration-scenario-zai-key")
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)

    config = ConfigFactory.create(repo_root=tmp_path / "repo", repo=_REPO)
    config.planner_provider = "zai"
    config.planner_model = _GLM
    config.gateway_route_shadow_enabled = True
    return _Repo(
        config=config, workspace=PolicyWorkspace(routing_dir(config), repo=_REPO)
    )


async def _turn(config: Any) -> tuple[int, list[tuple[str, bytes]]]:
    turn = await run_gateway_turn(
        config=config,
        control_token=_CONTROL_TOKEN,
        provider_key=_PROVIDER_KEY,
        virtual_secret=_VIRTUAL_SECRET,
        key_id="dial-migration-scenario-key",
    )
    return turn.returncode, turn.exchanges


class TestMigratingDialsMovesNoRoute:
    """The migration is installed, and the live turn does not notice."""

    async def test_the_migration_installs_the_policies_its_dials_imply(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Anti-vacuity floor: the turns below prove nothing if nothing was written."""
        repo = _repo(tmp_path, monkeypatch)

        result = migrate_dials_to_policy(
            repo.config, repo.workspace, actor=_ACTOR, now=_NOW
        )

        assert result.changed is True
        assert [p.id for p in result.installed] == ["baseline-planner-provider"]

    async def test_the_live_turn_reaches_the_same_upstream_bytes_after_migrating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The property no unit test can make: the external boundary is unmoved."""
        repo = _repo(tmp_path, monkeypatch)
        _, before = await _turn(repo.config)

        migrate_dials_to_policy(repo.config, repo.workspace, actor=_ACTOR, now=_NOW)
        _, after = await _turn(repo.config)

        # Self-guarding: two turns that both failed would also compare equal,
        # and a sibling test asserting success does not protect THIS one.
        assert before, "the baseline turn reached the origin with nothing"
        assert after == before

    async def test_the_turn_still_succeeds_after_migrating(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Byte-identical traffic from two failed turns would also compare equal."""
        repo = _repo(tmp_path, monkeypatch)

        migrate_dials_to_policy(repo.config, repo.workspace, actor=_ACTOR, now=_NOW)
        returncode, exchanges = await _turn(repo.config)

        assert (returncode, bool(exchanges)) == (0, True)


class TestRollingBackMovesNoRouteEither:
    """The down-path is the half an operator reaches for when something is wrong."""

    async def test_the_live_turn_is_unmoved_after_the_down_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Migrate, roll back, and the boundary still has not moved."""
        repo = _repo(tmp_path, monkeypatch)
        _, before = await _turn(repo.config)

        result = migrate_dials_to_policy(
            repo.config, repo.workspace, actor=_ACTOR, now=_NOW
        )
        repo.workspace.apply(down_path_mutation(result), actor=_ACTOR, now=_NOW)
        _, after = await _turn(repo.config)

        assert before, "the baseline turn reached the origin with nothing"
        assert after == before

    async def test_the_down_path_leaves_a_verifiable_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rollback moves forward: the migration's own revision stays readable."""
        repo = _repo(tmp_path, monkeypatch)
        result = migrate_dials_to_policy(
            repo.config, repo.workspace, actor=_ACTOR, now=_NOW
        )

        rolled = repo.workspace.apply(
            down_path_mutation(result), actor=_ACTOR, now=_NOW
        )
        history = repo.workspace.history()

        assert rolled.revision > result.revision
        assert history.verification.ok is True
