"""A governed spawn locked to Moonshot reaches Moonshot, and nothing else does.

The unit tests around this lane assert what the tables say. This asserts what
a real spawn does: a routing policy naming ``kimi-harness`` sends the request
to Moonshot's origin, presenting Moonshot's credential rather than the virtual
key the worker held.

That gap is the whole reason this layer exists here. Every table could be
wired correctly and the lane still be unreachable — a provider lock the
resolver refuses, an upstream the settings loader never registers, a
credential swap that hands the origin the wrong token. None of those are
visible from the config object; all of them are visible from the origin.

The z.ai case rides alongside as the decoy. The two lanes share their auth
style, their harness shape and most of their code path, so "kimi works" is
only worth stating next to "and z.ai still goes where it always did" — the
defect this change corrected was precisely kimi traffic arriving on z.ai's
account.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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

_CONTROL_TOKEN = "kimi-scenario-control-token-0123456789"
_PROVIDER_KEY = "kimi-scenario-real-provider-key"
_VIRTUAL_SECRET = "kimi-scenario-virtual-secret"
_REPO = "acme/moonshot-project"
_KIMI_MODEL = "kimi-k3"
_GLM_MODEL = "glm-5.3"


def _locked_to(lock: str, model: str) -> RoutingPolicy:
    """One operator rule: this repo's traffic serves *model* from *lock*'s lane."""
    return RoutingPolicy(
        id=f"moonshot-project-{lock}",
        match=RoutingMatch(repo_ids=(_REPO,)),
        action=RoutingAction(
            provider_lock=lock,
            requirement_map=(
                RequirementMapping(
                    requirement=requirement_for_model(TURN_MODEL),
                    effective_model=model,
                ),
            ),
        ),
    )


async def _turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, lock: str, model: str
) -> Any:
    """Drive one real governed gateway spawn and report what the origin saw."""
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
    monkeypatch.setenv("ZAI_API_KEY", "kimi-scenario-zai-key")
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi-scenario-moonshot-key")

    config = ConfigFactory.create(repo_root=tmp_path / "repo", repo=_REPO)
    config.gateway_route_shadow_enabled = False
    config.gateway_enforcement_canary_repo = _REPO
    RoutingPolicyStore(policy_snapshot_path(config)).save([_locked_to(lock, model)])

    return await run_gateway_turn(
        config=config,
        control_token=_CONTROL_TOKEN,
        provider_key=_PROVIDER_KEY,
        virtual_secret=_VIRTUAL_SECRET,
        key_id="kimi-scenario-key",
        zai_upstream=True,
        kimi_upstream=True,
        governed_repo_slugs=frozenset({_REPO}),
    )


def _served_host(turn: Any) -> str:
    """The upstream host the request actually reached.

    Parsed and compared whole rather than prefix-matched: ``kimi.test`` is a
    substring of nothing here today, but a host assertion that passes on a
    substring is one rename away from passing on the wrong origin.
    """
    assert turn.exchanges, "the origin was never reached"
    return urlparse(turn.exchanges[-1][0]).netloc


def _served_model(turn: Any) -> str:
    assert turn.exchanges, "the origin was never reached"
    return str(json.loads(turn.exchanges[-1][1])["model"])


async def test_a_spawn_locked_to_kimi_reaches_moonshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lane is reachable end to end, not merely declared."""
    turn = await _turn(tmp_path, monkeypatch, lock="kimi-harness", model=_KIMI_MODEL)

    assert _served_host(turn) == "kimi.test"
    assert _served_model(turn) == _KIMI_MODEL


async def test_a_spawn_locked_to_zai_still_reaches_zai(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decoy. Both upstreams are registered on every turn in this file, so
    a build that routed every locked spawn to the last-registered lane would
    pass the case above and fail here."""
    turn = await _turn(tmp_path, monkeypatch, lock="zai-harness", model=_GLM_MODEL)

    assert _served_host(turn) == "zai.test"
    assert _served_model(turn) == _GLM_MODEL


async def test_moonshot_is_handed_its_own_credential_not_the_virtual_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The credential swap is only observable at the origin.

    A worker presents the virtual key; the gateway must exchange it for the
    upstream's real credential. If that swap does not happen for a newly added
    lane, the request still leaves the process and still looks routed — it
    just arrives holding a secret the origin has never seen, and fails as
    someone else's 401.
    """
    turn = await _turn(tmp_path, monkeypatch, lock="kimi-harness", model=_KIMI_MODEL)
    sent = " ".join(
        f"{name}: {value}"
        for headers in turn.headers
        for name, value in headers.items()
    )

    assert f"{_PROVIDER_KEY}-kimi" in sent, (
        "Moonshot was not handed its own upstream credential"
    )
    assert _VIRTUAL_SECRET not in sent, "the worker's virtual key reached the origin"
