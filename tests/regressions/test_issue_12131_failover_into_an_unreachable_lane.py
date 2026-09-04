"""#12131 — failing over to a lane the gateway cannot serve.

Credit exhaustion is supposed to have two outcomes and only two: fail over to
GLM and keep working, or pause the factory and surface the cap. This produced a
third. `_maybe_engage_failover` treated "the loop is gateway-routed" as proof
that failover was possible:

    gateway_route = self._loop_uses_gateway_transport(loop_name)
    if not credit_failover.zai_key_present() and not gateway_route:
        return False

The direct lane checks its credential; the gateway lane checked its transport.
`apply_credit_failover`'s docstring says why — "a `gateway` spawn does NOT
[need a local key], because the proxy mints a z.ai-bound virtual key" — which
is true exactly while the proxy has a z.ai upstream to mint against.

Where it does not, the sequence observed in the RC dry-run was:

    Claude credit cap (provider=anthropic) — engaging GLM failover
    mint 422: {"detail":"provider is unavailable"} requested='zai-harness'

`_maybe_engage_failover` returned True, so the caller skipped
`_pause_for_credits`; every rerouted spawn then died on the mint. The factory
got neither failover nor the pause, and the operator saw mint errors instead of
the credit cap that caused them. Sandbox scenario `s89_credit_pause_auto_resume`
timed out waiting for a pause that could no longer fire.

The guard is a NECESSARY condition, not a sufficient one — the env pair being
set does not prove the upstream is healthy. That is deliberate: this closes the
case where the lane is provably absent, and a mint that fails for some other
reason is a different failure with a different fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import credit_failover  # noqa: E402
from credit_failover import (  # noqa: E402
    apply_credit_failover,
    gateway_zai_lane_present,
)

_GATEWAY_PAIR = ("GATEWAY_ZAI_HARNESS_BASE_URL", "GATEWAY_ZAI_HARNESS_API_KEY")


@pytest.fixture(autouse=True)
def _armed(monkeypatch: pytest.MonkeyPatch):
    """Failover engaged and no LOCAL z.ai credential anywhere."""
    from datetime import UTC, datetime

    for name in (
        "ZAI_API_KEY",
        "ZAI_CODING_PLAN_KEY",
        "HYDRAFLOW_ZAI_API_KEY",
        "HYDRAFLOW_ZAI_CODING_PLAN_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    credit_failover.reset_for_tests()
    credit_failover.engage(
        now=datetime.now(UTC), resume_at=None, cooldown_minutes=15
    )
    yield
    credit_failover.reset_for_tests()


def _config(tmp_path: Path):
    from config import HydraFlowConfig

    return HydraFlowConfig(repo_root=tmp_path)


def test_a_gateway_spawn_is_not_rerouted_into_a_lane_with_no_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The defect, at the spawn rewrite.

    Rerouting here produced a command asking for a glm model on a binding the
    gateway would refuse, so the spawn failed on the mint rather than running
    anywhere. Leaving it alone is what lets the credit signal reach the pause.
    """
    for name in _GATEWAY_PAIR:
        monkeypatch.delenv(name, raising=False)
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "x"]

    assert apply_credit_failover("gateway", cmd, _config(tmp_path)) == ("gateway", cmd)


def test_a_gateway_spawn_is_rerouted_when_the_upstream_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The decoy. Without it, a guard that simply disabled gateway failover
    would satisfy the case above while removing the feature entirely.

    Note there is still no local z.ai credential here — the worker holds none,
    which is the property the gateway lane was built for and which this change
    does not touch.
    """
    for name in _GATEWAY_PAIR:
        monkeypatch.setenv(name, "not-a-real-credential")
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "x"]

    provider, rewritten = apply_credit_failover("gateway", cmd, _config(tmp_path))

    assert provider == "gateway"
    assert "glm-5.2" in rewritten


def test_a_half_configured_pair_is_not_a_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    """`_add_upstream` refuses a half-set pair and registers nothing, so one
    variable set is not a reachable lane. Reading it as one would put the
    deployment back in the state this issue describes."""
    monkeypatch.setenv("GATEWAY_ZAI_HARNESS_BASE_URL", "https://zai.invalid")
    monkeypatch.delenv("GATEWAY_ZAI_HARNESS_API_KEY", raising=False)

    assert gateway_zai_lane_present() is False


def test_the_direct_lane_rule_is_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A direct `claude` spawn still turns on the LOCAL key and nothing else.

    The gateway's upstream being configured must not stand in for a credential
    the direct lane has to hold itself — that would be the same conflation in
    the other direction.
    """
    for name in _GATEWAY_PAIR:
        monkeypatch.setenv(name, "not-a-real-credential")
    cmd = ["claude", "--model", "claude-opus-4-8", "-p", "x"]

    assert apply_credit_failover("claude", cmd, _config(tmp_path)) == ("claude", cmd)
