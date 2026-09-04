"""#11993 — a provider lock survives retries and brokered children.

The epic's promise is one sentence: *"project X always uses z.ai"*. The canary
scenario already proves it for one clean turn. This covers the two clauses the
issue singles out as where a lock would actually leak, and neither would
announce itself — a leaked retry looks like a successful spawn, on the wrong
lane, with a ledger row nobody reads until the bill arrives.

Both properties turn out to hold **by construction**, and that is what these
pin. A test asserting only the outcome would pass today and keep passing
through the refactor that breaks it; a test pinning the construction reddens
when the construction changes, which is the moment the property is actually at
risk.

**Retries.** `BaseRunner._execute` resolves `harness_env` once (base_runner.py,
before the loop) and the retry loop reuses it. Every attempt therefore addresses
the lane the first resolution chose. Move that resolution inside the loop — an
entirely reasonable-looking refactor, since a stale key is exactly what the
retry is recovering from — and each attempt becomes a fresh chance to resolve
differently.

**Brokered children.** `implement_worker_runner` pins `provider="gateway"` with
the comment *"Pinned, not dialled: the key, the route decision and the ledger
row are all gateway properties"*, and passes the child's own catalogued role as
`source`. So a child routes through the governed resolver under its own
principal rather than inheriting or defaulting. Change that pin to a dial and a
child resolves on config, which is precisely the "inherits nothing" case the
issue names.
"""

from __future__ import annotations

import inspect
import logging
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import base_runner  # noqa: E402
import implement_worker_runner  # noqa: E402
from base_runner import BaseRunner  # noqa: E402
from events import EventBus  # noqa: E402
from runner_utils import AuthenticationRetryError  # noqa: E402
from tests.helpers import ConfigFactory  # noqa: E402


class _Runner(BaseRunner):
    _log = logging.getLogger("hydraflow.test_lock_proof")


# ---------------------------------------------------------------------------
# Clause 1 — retries stay on the lane the first resolution chose
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_every_retry_attempt_reuses_one_resolved_route(tmp_path: Path) -> None:
    """The route is resolved ONCE for a spawn, however many attempts it takes.

    Asserted as a call count on `resolve_harness_env`, which is the thing that
    decides the lane. Three attempts and one resolution is the property; three
    resolutions would mean each attempt got its own chance to answer
    differently, and a lock would hold only for as long as nothing failed.
    """
    config = ConfigFactory.create(repo_root=tmp_path)
    runner = _Runner(config, EventBus())
    locked_env = {"ANTHROPIC_BASE_URL": "https://zai.test/api/anthropic"}

    with (
        patch.object(
            base_runner,
            "resolve_harness_env",
            new_callable=AsyncMock,
            return_value=locked_env,
        ) as resolve,
        patch.object(
            base_runner,
            "stream_claude_process",
            new_callable=AsyncMock,
            side_effect=AuthenticationRetryError("auth failed"),
        ) as spawn,
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            base_runner, "renew_gateway_key_if_needed", new_callable=AsyncMock
        ),
        pytest.raises(AuthenticationRetryError),
    ):
        await runner._execute(["claude", "-p"], "prompt", tmp_path, {"issue": 42})

    assert spawn.await_count == 3, "the retry loop did not run all three attempts"
    assert resolve.await_count == 1, (
        f"the route was resolved {resolve.await_count} times for one spawn — "
        "each attempt now gets its own chance to pick a lane, so a provider "
        "lock holds only until something fails (#11993)"
    )


@pytest.mark.asyncio
async def test_every_attempt_is_handed_the_same_env_object(tmp_path: Path) -> None:
    """Resolving once is not enough if the loop rebuilds the env per attempt.

    The decoy for the case above: a build that resolved once and then derived a
    fresh env for each attempt would keep `await_count == 1` and still be able
    to send attempt two somewhere else. Identity, not equality — two equal
    dicts built separately are still two decisions.
    """
    config = ConfigFactory.create(repo_root=tmp_path)
    runner = _Runner(config, EventBus())
    locked_env = {"ANTHROPIC_BASE_URL": "https://zai.test/api/anthropic"}

    with (
        patch.object(
            base_runner,
            "resolve_harness_env",
            new_callable=AsyncMock,
            return_value=locked_env,
        ),
        patch.object(
            base_runner,
            "stream_claude_process",
            new_callable=AsyncMock,
            side_effect=AuthenticationRetryError("auth failed"),
        ) as spawn,
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(
            base_runner, "renew_gateway_key_if_needed", new_callable=AsyncMock
        ),
        pytest.raises(AuthenticationRetryError),
    ):
        await runner._execute(["claude", "-p"], "prompt", tmp_path, {"issue": 42})

    # The env rides on the StreamConfig, not on the call — reading it off the
    # call kwargs finds None and would have made this assertion fail for a
    # reason that has nothing to do with the property.
    handed = [call.kwargs["config"].harness_env for call in spawn.await_args_list]

    assert len(handed) == 3
    assert all(env is locked_env for env in handed), (
        "an attempt was handed a different env object than the one resolved "
        "for the spawn — the lane can move between attempts"
    )


# ---------------------------------------------------------------------------
# Clause 2 — a brokered child routes through the governed resolver
# ---------------------------------------------------------------------------


def test_a_brokered_child_pins_the_gateway_rather_than_reading_a_dial() -> None:
    """A child must not resolve on config, or it resolves on ITS defaults.

    This is the "inherits nothing" case: a Fable driver spawns a child, and a
    child that reads a dial reads the dial as configured, not the lock the
    parent's repository declared. Pinning the gateway sends it through the
    governed resolver instead, where the policy applies.

    Read off the source rather than mocked, because the property is that the
    literal is there — a behavioural assertion would pass against a build that
    happened to have `gateway` in the dial it read.
    """
    source = inspect.getsource(implement_worker_runner)

    assert 'provider="gateway"' in source, (
        "the brokered-child spawn no longer pins the gateway; if it now reads "
        "a dial, a child resolves on its own config and a repository's "
        "provider lock stops covering its children (#11993)"
    )


def test_a_brokered_child_carries_its_own_catalogued_role_as_principal() -> None:
    """The lock is matched per principal, so the principal must be the child's.

    `run_lightweight_agent` resolves with `principal_id=source`, and
    `canonical_worker_role` matches a `WorkerRole` value exactly. A child
    passing a loop-shaped source would mint unbound — the seam's own docstring
    says so — and an unbound key is one a provider lock cannot be enforced
    against.
    """
    source = inspect.getsource(implement_worker_runner)

    assert "source=request.worker_role.value" in source, (
        "the brokered child no longer passes its catalogued worker role as the "
        "principal; a loop-shaped source mints unbound and escapes the lock"
    )


def test_the_child_seam_still_threads_lineage() -> None:
    """The decoy, and the thing that makes a violation visible.

    P6a's lineage is what lets an operator SEE that a child went somewhere its
    parent did not. Without `driver_id` and `parent_spawn_id` reaching the mint,
    a child's ledger rows are unattributable and the two assertions above could
    hold while nobody could tell which parent a stray child belonged to.
    """
    source = inspect.getsource(implement_worker_runner)

    assert "driver_id=driver_id" in source
    assert "parent_spawn_id=parent_spawn_id" in source
