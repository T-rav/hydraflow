"""#11994: the policy route reads the live account set correctly.

The workspace tests pass `known_accounts` in directly, which proves the REFUSAL
but not that anything ever supplies a real set. The first version of this
wiring read a `.value` attribute that does not exist on `GatewayReadResult`, so
it returned None unconditionally and would have refused every rollback in
production while every workspace test stayed green. That is the shape these
tests exist to catch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes._gateway_policy_routes import _live_account_ids  # noqa: E402
from gateway_control_reader import GatewayReadResult, GatewaySourceState  # noqa: E402


def _result(state: GatewaySourceState, data: dict | None) -> GatewayReadResult:
    return GatewayReadResult(state, data)


async def _with(result: GatewayReadResult) -> frozenset[str] | None:
    reader = AsyncMock()
    reader.accounts = AsyncMock(return_value=result)
    with patch(
        "dashboard_routes._gateway_policy_routes.reader_from_config",
        return_value=reader,
    ):
        return await _live_account_ids(object())


class TestTheLiveAccountSetIsActuallyRead:
    async def test_account_ids_come_back_from_a_real_read(self) -> None:
        got = await _with(
            _result(
                GatewaySourceState.AVAILABLE,
                {"accounts": [{"account_id": "acct-a"}, {"account_id": "acct-b"}]},
            )
        )

        assert got == frozenset({"acct-a", "acct-b"}), (
            "a successful read produced no account ids — the wiring reads the "
            "wrong field, and every rollback would refuse"
        )

    async def test_an_empty_registry_is_an_empty_set_not_none(self) -> None:
        """Distinct facts: "no accounts" is verifiable, "unreadable" is not."""
        got = await _with(_result(GatewaySourceState.AVAILABLE, {"accounts": []}))

        assert got == frozenset()

    @pytest.mark.parametrize(
        "state",
        [
            GatewaySourceState.NOT_CONFIGURED,
            GatewaySourceState.UNREACHABLE,
        ],
    )
    async def test_an_unavailable_gateway_is_none(
        self, state: GatewaySourceState
    ) -> None:
        assert await _with(_result(state, None)) is None

    async def test_a_malformed_entry_is_skipped_not_fatal(self) -> None:
        got = await _with(
            _result(
                GatewaySourceState.AVAILABLE,
                {"accounts": [{"account_id": "acct-a"}, {}, "nonsense"]},
            )
        )

        assert got == frozenset({"acct-a"})
