"""Regression: a missing contracts sandbox is reported at boot, not per cycle.

`ContractRefreshLoop` re-records FakeGitHub cassettes against
`config.contracts_sandbox_repo`. When that repo does not exist the loop
degrades gracefully (`if main_sha is None: return None`), so it completes, the
factory reports healthy, and the only trace is one warning per cycle.

Measured 2026-08-30: `T-rav-Hydra-Ops/hydraflow-contracts-sandbox` returns 404,
and six `gh: Not Found` warnings in a single run read as background noise. The
external recorder was PERMANENTLY degraded and nothing said so — a permanent
condition wearing a transient failure's clothes, the same shape as the
wiki-compilation burn (#11819) that cost six hours before anyone looked.

A recurring mid-run warning is the one thing guaranteed to be tuned out. This
reports once, at boot, where an operator is already reading.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from preflight import CheckStatus, _check_contracts_sandbox


def _config(*, enabled: bool = True, slug: str = "acme/sandbox") -> MagicMock:
    config = MagicMock()
    config.contract_refresh_external_enabled = enabled
    config.contracts_sandbox_repo = slug
    return config


def _gh(returncode: int) -> MagicMock:
    result = MagicMock()
    result.returncode = returncode
    result.stdout = "acme/sandbox" if returncode == 0 else ""
    return result


def test_a_missing_sandbox_warns_and_names_the_remedies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("preflight._run_fixed_argv", lambda *a, **k: _gh(1))

    result = _check_contracts_sandbox(_config())

    assert result.status == CheckStatus.WARN
    assert "acme/sandbox" in result.message
    # The message must say what to DO. A warning that only states a fact is
    # the kind that gets read once and ignored thereafter.
    assert "contract_refresh_external_enabled=false" in result.message


def test_a_reachable_sandbox_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Anti-vacuity: a check that always warned would be muted within a day,
    and then it would be worse than not existing."""
    monkeypatch.setattr("preflight._run_fixed_argv", lambda *a, **k: _gh(0))

    assert _check_contracts_sandbox(_config()).status == CheckStatus.PASS


def test_disabled_external_recording_needs_no_sandbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Turning the recorder OFF is one of the two documented remedies, so it
    must not keep warning about a repo it no longer uses."""

    def _never_called(*_a: object, **_k: object) -> None:  # pragma: no cover
        msg = "GitHub must not be probed when external recording is disabled"
        raise AssertionError(msg)

    monkeypatch.setattr("preflight._run_fixed_argv", _never_called)

    assert _check_contracts_sandbox(_config(enabled=False)).status == CheckStatus.PASS


def test_an_empty_slug_warns_rather_than_probing_an_empty_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _never_called(*_a: object, **_k: object) -> None:  # pragma: no cover
        msg = "must not call gh with an empty repo slug"
        raise AssertionError(msg)

    monkeypatch.setattr("preflight._run_fixed_argv", _never_called)

    assert _check_contracts_sandbox(_config(slug="")).status == CheckStatus.WARN


def test_an_unreachable_github_warns_rather_than_crashing_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """This runs at boot; a diagnostic must never stop the factory starting."""
    monkeypatch.setattr("preflight._run_fixed_argv", lambda *a, **k: None)

    assert _check_contracts_sandbox(_config()).status == CheckStatus.WARN
