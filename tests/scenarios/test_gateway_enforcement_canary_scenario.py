"""MockWorld scenario: the canary routes one repository, and only that one.

Everything on the path is real — the lightweight spawn seam, the enforcement
predicate, the durable policy store and resolver, the gateway control plane, the
route-aware v2 mint, the virtual key store, the strict pre-upstream binding, the
streaming proxy and the ledger. Only the Claude subprocess and the external
Anthropic origin are deterministic fakes, and neither is an ``AsyncMock`` of a
port: the origin is an HTTP transport that records the bytes it was actually
sent, so "the upstream served z.ai's model" is a claim about the wire.

The scenario asks the two questions #11539's acceptance criteria turn on, at the
external boundary rather than in a unit:

* inside the canary, does the resolver's decision actually change what the
  upstream receives, and can a request that disagrees with its binding reach an
  upstream at all;
* outside it — a different repository, the same policy set, the same gateway —
  is the wire byte-identical to a run with no canary at all.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from hydraflow_gateway.routing_policy import (
    RequirementMapping,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
)
from hydraflow_gateway.routing_store import RoutingPolicyStore
from route_shadow import policy_snapshot_path, requirement_for_model
from tests.helpers import ConfigFactory
from tests.scenarios.helpers.gateway_turn import TURN_MODEL, run_gateway_turn

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "canary-scenario-control-token-0123456789"
_PROVIDER_KEY = "canary-scenario-real-provider-key"
_VIRTUAL_SECRET = "canary-scenario-virtual-secret"
_CANARY_REPO = "acme/project-x"
_OTHER_REPO = "acme/somewhere-else"
_POLICY_MODEL = "glm-5.3"


def _project_x_uses_zai() -> RoutingPolicy:
    """The operator's one rule, exactly as the P2 workspace would write it."""
    return RoutingPolicy(
        id="project-x-zai",
        match=RoutingMatch(repo_ids=(_CANARY_REPO,)),
        action=RoutingAction(
            provider_lock="zai-harness",
            requirement_map=(
                RequirementMapping(
                    requirement=requirement_for_model(TURN_MODEL),
                    effective_model=_POLICY_MODEL,
                ),
            ),
        ),
    )


async def _turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    repo: str,
    canary: str,
    policies: Sequence[RoutingPolicy] = (),
    governed_repo_slugs: frozenset[str] = frozenset(),
) -> Any:
    """Drive one real governed gateway spawn and report what the origin saw."""
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
    monkeypatch.setenv("ZAI_API_KEY", "canary-scenario-zai-key")

    config = ConfigFactory.create(repo_root=tmp_path / "repo", repo=repo)
    config.gateway_route_shadow_enabled = False
    config.gateway_enforcement_canary_repo = canary
    if policies:
        RoutingPolicyStore(policy_snapshot_path(config)).save(list(policies))

    return await run_gateway_turn(
        config=config,
        control_token=_CONTROL_TOKEN,
        provider_key=_PROVIDER_KEY,
        virtual_secret=_VIRTUAL_SECRET,
        key_id="canary-scenario-key",
        zai_upstream=True,
        governed_repo_slugs=governed_repo_slugs,
    )


def _served_model(turn: Any) -> str:
    """The model the external origin was actually asked for."""
    assert turn.exchanges, "the origin was never reached"
    return str(json.loads(turn.exchanges[-1][1])["model"])


def _served_origin(turn: Any) -> str:
    """The upstream host the request actually reached."""
    assert turn.exchanges, "the origin was never reached"
    return str(turn.exchanges[-1][0])


# --------------------------------------------------------------------------
# Inside the canary: the decision changes what the upstream receives
# --------------------------------------------------------------------------


async def test_a_governed_turn_reaches_the_upstream_the_policy_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """ "Project X always uses z.ai", observed on the wire rather than in a log."""
    turn = await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert _served_origin(turn).startswith("https://zai.test")


async def test_a_governed_turn_serves_the_model_the_policy_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC4 at the boundary: the child was rewritten and the rewrite reached upstream."""
    turn = await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert _served_model(turn) == _POLICY_MODEL


async def test_the_governed_turn_carries_the_decision_that_authorised_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC8: the mint decision names the policy revision the route came from."""
    turn = await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert turn.decisions[-1]["policy_id"] == "project-x-zai"


async def test_the_governed_turn_correlates_its_key_to_its_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lease this decision authorised is named on the decision itself."""
    turn = await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert turn.decisions[-1]["key_id"] == "canary-scenario-key"


async def test_the_governed_turn_succeeded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canary that broke the spawn would prove nothing about routing."""
    turn = await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert turn.returncode == 0


# --------------------------------------------------------------------------
# Outside the canary: byte-identical
# --------------------------------------------------------------------------


async def test_another_repository_reaches_the_same_upstream_as_with_no_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Same gateway, same policy set, different repository — nothing moves."""
    disarmed = await _turn(tmp_path / "a", monkeypatch, repo=_OTHER_REPO, canary="")
    armed = await _turn(
        tmp_path / "b",
        monkeypatch,
        repo=_OTHER_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert _served_origin(armed) == _served_origin(disarmed)


async def test_another_repository_sends_the_same_bytes_as_with_no_canary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The strongest available statement of "outside the bound is untouched"."""
    disarmed = await _turn(tmp_path / "a", monkeypatch, repo=_OTHER_REPO, canary="")
    armed = await _turn(
        tmp_path / "b",
        monkeypatch,
        repo=_OTHER_REPO,
        canary=_CANARY_REPO,
        policies=(_project_x_uses_zai(),),
    )

    assert [body for _, body in armed.exchanges] == [
        body for _, body in disarmed.exchanges
    ]


async def test_the_comparison_is_not_between_two_empty_wires(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two runs that both reached nothing would compare equal and prove nothing."""
    disarmed = await _turn(tmp_path, monkeypatch, repo=_OTHER_REPO, canary="")

    assert _served_model(disarmed) == TURN_MODEL


async def test_the_canary_repository_with_no_policy_is_also_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Arming the dial is not itself a routing change."""
    turn = await _turn(tmp_path, monkeypatch, repo=_CANARY_REPO, canary=_CANARY_REPO)

    assert _served_model(turn) == TURN_MODEL


# --------------------------------------------------------------------------
# The boundary refuses rather than serving
# --------------------------------------------------------------------------


async def _ungoverned_key_against_a_governed_repo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """The disarm ordering ADR-0141 §D5 documents, run backwards on purpose.

    The canary dial is off while the gateway's server-owned allow-list is on, so
    the spawn reaches for a v1 key the gateway will not issue for this
    repository.
    """
    return await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary="",
        governed_repo_slugs=frozenset({"acme-project-x"}),
    )


async def test_an_ungoverned_key_for_a_governed_repository_sends_no_upstream_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC6, measured at the origin rather than at the exception type."""
    turn = await _ungoverned_key_against_a_governed_repo(tmp_path, monkeypatch)

    assert turn.exchanges == []


async def test_an_ungoverned_key_for_a_governed_repository_fails_the_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """It fails closed: no lane the policy does not govern is used instead."""
    turn = await _ungoverned_key_against_a_governed_repo(tmp_path, monkeypatch)

    assert turn.returncode != 0


async def _literal_family_under_a_bare_provider_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Any:
    """A lock with no mapping meeting a Claude-model request (ADR-0139 §D4)."""
    policy = RoutingPolicy(
        id="project-x-zai",
        match=RoutingMatch(repo_ids=(_CANARY_REPO,)),
        action=RoutingAction(provider_lock="zai-harness"),
    )
    return await _turn(
        tmp_path,
        monkeypatch,
        repo=_CANARY_REPO,
        canary=_CANARY_REPO,
        policies=(policy,),
    )


async def test_an_unsatisfiable_route_sends_no_upstream_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC5: a held route never falls through to an ambient or direct credential."""
    turn = await _literal_family_under_a_bare_provider_lock(tmp_path, monkeypatch)

    assert turn.exchanges == []


async def test_an_unsatisfiable_route_fails_the_spawn_rather_than_substituting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The spawn does not quietly run on whatever lane happened to be open."""
    turn = await _literal_family_under_a_bare_provider_lock(tmp_path, monkeypatch)

    assert turn.returncode != 0
