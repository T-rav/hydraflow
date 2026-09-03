"""A ``ProviderBinding`` member is wired everywhere, or it is not a lane.

Adding an upstream provider means adding one enum member and then finding
every hand-maintained table keyed by it. Nothing checked that the finding
happened, and the tables are spread over four modules plus two hand-copied
``Literal``s in a script and a runner contract. A member present in the enum
and absent from a table does not raise at import: it raises on the first
request that routes to it, or — worse — resolves to a default and bills the
wrong lane, which is the blindness ADR-0147 exists to end.

Moonshot's own Claude Code guide warns about the same shape from the outside:
omit one of the model-tier variables and "corresponding scenarios fail
silently". A provider lane is exactly as usable as its least-wired table.

Every case here parametrises over ``ProviderBinding`` itself, by reference. A
third binding is held to all of it the day the member lands, which is the
point — this file is written to redden for the NEXT provider, not to describe
the two that exist today.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import get_args, get_type_hints

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT / "scripts") not in sys.path:  # pragma: no cover - path setup
    sys.path.insert(0, str(_REPO_ROOT / "scripts"))

from gateway_mint_client import GatewayMintRequest  # noqa: E402
from hydraflow_gateway import accounts, routing_accounts  # noqa: E402
from hydraflow_gateway.models import (  # noqa: E402
    LEGACY_ACCOUNT_IDS,
    ProviderBinding,
    legacy_account_id,
)
from route_shadow import local_account_availability  # noqa: E402

# Iterated inline at each decorator rather than aliased here: a module-level
# sequence fed to `parametrize` is itself a guard enumeration owing the registry
# a drop-detector, and an alias for `sorted(ProviderBinding)` has none to give —
# it cannot shrink unless the enum does, and the enum shrinking is caught loudly
# by every `ProviderBinding.X` reference in the maps this file checks.


def test_there_are_bindings_to_guard() -> None:
    """Fail closed: an empty enum makes every parametrised case below vanish.

    Without this the whole file reports green by collecting nothing, which is
    the failure mode a parametrised guard is most likely to reach and least
    likely to show.
    """
    bindings = sorted(ProviderBinding, key=str)

    assert len(bindings) >= 2, (
        f"expected at least the two legacy upstream lanes, found {bindings}"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_a_binding_has_a_stable_account_id(binding: ProviderBinding) -> None:
    """ADR-0138's compiled identity. Without it the lane has no ledger name."""
    assert binding in LEGACY_ACCOUNT_IDS, (
        f"{binding.value} has no entry in LEGACY_ACCOUNT_IDS, so "
        "legacy_account_id() raises KeyError the first time anything asks "
        "which account its spend belongs to"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_a_binding_names_its_credential_variable(binding: ProviderBinding) -> None:
    """Both modules that map a binding to its credential env name must know it.

    The *name* only — never the value. A binding missing here cannot be
    configured at all, and the operator sees an unconfigured lane rather than
    an error naming the variable they forgot.
    """
    assert binding in accounts.CREDENTIAL_ENV_NAMES, (
        f"{binding.value} is absent from accounts.CREDENTIAL_ENV_NAMES"
    )
    assert binding in routing_accounts.LEGACY_CREDENTIAL_ENV, (
        f"{binding.value} is absent from routing_accounts.LEGACY_CREDENTIAL_ENV"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_a_binding_has_a_display_name(binding: ProviderBinding) -> None:
    """The operator console renders lanes by these names."""
    assert binding in accounts.ACCOUNT_DISPLAY_NAMES, (
        f"{binding.value} is absent from accounts.ACCOUNT_DISPLAY_NAMES"
    )
    assert binding in routing_accounts.LEGACY_DISPLAY_NAMES, (
        f"{binding.value} is absent from routing_accounts.LEGACY_DISPLAY_NAMES"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_a_binding_declares_how_it_authenticates(binding: ProviderBinding) -> None:
    """Auth style is per-vendor and cannot be defaulted.

    Anthropic takes ``x-api-key``; z.ai and Moonshot take a bearer token. A
    binding with no declared style would be sent the wrong header shape and
    fail as an opaque 401 from someone else's server.
    """
    assert binding in routing_accounts._LEGACY_AUTH_STYLE, (  # noqa: SLF001
        f"{binding.value} declares no upstream auth style"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_the_two_credential_maps_agree(binding: ProviderBinding) -> None:
    """``accounts`` and ``routing_accounts`` carry the same map twice.

    They are byte-identical today and nothing holds them that way. Two copies
    of one mapping is what ADR-0139 §D8 calls a guaranteed future
    disagreement; until they are one table, this is the thing that notices.
    """
    assert (
        accounts.CREDENTIAL_ENV_NAMES[binding]
        == routing_accounts.LEGACY_CREDENTIAL_ENV[binding]
    ), (
        f"{binding.value} names two different credential variables depending "
        "on which module you ask"
    )
    assert (
        accounts.ACCOUNT_DISPLAY_NAMES[binding]
        == routing_accounts.LEGACY_DISPLAY_NAMES[binding]
    ), f"{binding.value} renders under two different names"


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_the_mint_contract_accepts_the_binding(binding: ProviderBinding) -> None:
    """``GatewayMintRequest`` re-types the enum as a hand-copied ``Literal``.

    A binding the mint contract does not list cannot have a key minted for it,
    so the lane exists everywhere except at the one seam that hands a worker
    its credential.
    """
    allowed = get_args(get_type_hints(GatewayMintRequest)["provider_binding"])

    assert binding.value in allowed, (
        f"{binding.value} is a ProviderBinding but GatewayMintRequest's "
        f"provider_binding Literal only accepts {sorted(allowed)} — the "
        "hand-copied Literal drifted from the enum it copies"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_the_probe_covers_the_binding(binding: ProviderBinding) -> None:
    """``scripts/gateway_probe.py`` keeps its own copy of the binding list.

    The probe is how an operator answers "is this lane actually reachable".
    A binding it does not enumerate is the one lane nobody can check.
    """
    import gateway_probe  # noqa: PLC0415

    assert binding.value in gateway_probe._PROVIDER_BINDINGS, (  # noqa: SLF001
        f"{binding.value} is missing from gateway_probe._PROVIDER_BINDINGS, "
        "so the probe silently never tests that lane"
    )


@pytest.mark.parametrize("binding", sorted(ProviderBinding, key=str))
def test_this_host_can_see_the_binding(binding: ProviderBinding) -> None:
    """``route_shadow.local_account_availability`` must name every lane.

    This is the case this file was missing when it was written, and the miss
    cost a working provider: every gateway table was wired, the policy locked
    correctly, the pool listed a configured Moonshot account — and the routed
    spawn was still refused, because the client-side availability list was a
    hand-written pair that had never heard of it. The refusal surfaced as
    ``no-eligible-account``, which reads as "the operator's policy excluded
    everything" rather than "a table nobody updated", so the message pointed
    away from the cause.

    A lane the resolver cannot see is not a degraded lane. It is a lane whose
    every spawn is held, with a reason that blames the policy.
    """
    visible = {account.account_id for account in local_account_availability()}

    assert legacy_account_id(binding) in visible, (
        f"{binding.value} is invisible to local_account_availability(), so "
        "every spawn routed to it is held as no-eligible-account"
    )
