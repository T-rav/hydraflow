"""One flag turned off three recorders, and the skip was indistinguishable
from a clean result (#11837).

`contract_refresh_external_enabled` gates the github, docker and claude
recorders together. #11830 flipped its default to False, and the entire stated
justification was the **github** recorder: `contracts_sandbox_repo` defaults to
`T-rav-Hydra-Ops/hydraflow-contracts-sandbox`, which 404s, so every install ran
a recorder that could never succeed. Nothing was ever alleged against the
docker or claude recorders — they were collateral, and the PR description,
config docstring and tests all discuss only the github failure mode.

Two distinct defects, both fixed here:

**Scope.** An operator who wants to silence the 404 recorder had no way to keep
docker and claude drift monitoring. The recorders are now selected by name, so
the broken one can be excluded on its own.

**Silence.** A skipped recorder returned a bare `[]`, and `_record_all`'s own
docstring defines `[]` as "tool missing / sandbox offline — the diff layer
already treats that as no-signal". So a *deliberate* skip was encoded
identically to a *broken* recorder, and it bypassed `_record_with_trace`
entirely — invisible even to the observability built to flag a silently-broken
recorder ("empty list + zero latency").

That is worse than a gap. With every external recorder skipped, `fleet.has_drift`
is false, so the tick lands in `_on_clean_tick()` — which resets the Task-18
attempt counters and auto-closes open fake-drift escalations. Permanent
silence was being reported as a positive all-clear.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock
from tests.helpers import config_mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest

from config import HydraFlowConfig
from contract_refresh_loop import ContractRefreshLoop
from tests.test_contract_refresh_loop import _deps, _FakeState


def _loop(tmp_path: Path, **overrides: object) -> ContractRefreshLoop:
    cfg = HydraFlowConfig(
        data_root=tmp_path / "data",
        repo_root=tmp_path / "repo",
        repo="hydra/hydraflow",
        **overrides,
    )
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)
    return ContractRefreshLoop(
        config=cfg,
        prs=AsyncMock(),
        state=_FakeState(),
        deps=_deps(asyncio.Event(), enabled=True),
    )


def test_the_broken_github_recorder_can_be_excluded_alone(tmp_path: Path) -> None:
    """The #11837 finding: silencing github must not silence docker and claude.

    Before this, `contract_refresh_external_enabled=False` was the only lever
    and it took all three down together.
    """
    loop = _loop(
        tmp_path,
        contract_refresh_external_enabled=True,
        contract_refresh_external_recorders=("docker", "claude"),
        contracts_sandbox_repo="real-org/real-contracts-sandbox",
    )
    skips = loop._external_recorder_skips()
    assert set(skips) == {"github"}, (
        f"excluding github alone must leave docker and claude running: {skips}"
    )
    assert "contract_refresh_external_recorders" in skips["github"]


def test_the_recorder_list_defaults_to_all_three(tmp_path: Path) -> None:
    """The operator lever is not where github's problem belongs.

    github's diagnosed defect is its TARGET (a 404 slug), so excluding it by
    name here would blame the recorder and would keep it off even for an
    operator who has pointed it at a real repo.
    """
    cfg = HydraFlowConfig(
        data_root=tmp_path / "d", repo_root=tmp_path / "r", repo="a/b"
    )
    assert set(cfg.contract_refresh_external_recorders) == {
        "github",
        "docker",
        "claude",
    }


def test_github_is_skipped_only_while_its_target_is_the_placeholder(
    tmp_path: Path,
) -> None:
    """The #11821 defect, stated as what it actually is.

    A stock install points at a slug that 404s, so the recorder could never
    succeed. Configuring a real repo is what re-enables it — the skip tracks
    the unreachable target, not the recorder.
    """
    stock = _loop(tmp_path, contract_refresh_external_enabled=True)
    assert set(stock._external_recorder_skips()) == {"github"}
    assert "placeholder" in stock._external_recorder_skips()["github"]

    configured = _loop(
        tmp_path,
        contract_refresh_external_enabled=True,
        contracts_sandbox_repo="real-org/real-contracts-sandbox",
    )
    assert configured._external_recorder_skips() == {}


def test_the_placeholder_is_read_from_the_field_not_respelled() -> None:
    """A second copy of the slug would drift and the skip would stop firing.

    Derived from the field default, so renaming the sandbox org keeps the
    guard pointing at whatever the placeholder currently is.
    """
    import inspect

    from contract_refresh_loop import ContractRefreshLoop as _C

    src = inspect.getsource(_C._external_recorder_skips)
    assert "T-rav-Hydra-Ops" not in src, "the placeholder slug is hardcoded"
    assert 'model_fields["contracts_sandbox_repo"].default' in src


def test_the_master_switch_still_takes_everything_down(tmp_path: Path) -> None:
    """The air-gapped sandbox depends on this and must keep working.

    `sandbox_main.py` sets the flag False so the loop completes promptly
    instead of blocking 120s per unreachable recorder (s30).
    """
    loop = _loop(tmp_path, contract_refresh_external_enabled=False)
    assert set(loop._external_recorder_skips()) == {"github", "docker", "claude"}


def test_a_skipped_recorder_is_not_reported_as_a_clean_tick(tmp_path: Path) -> None:
    """The silence half: a skip must be visible in the tick's own result.

    `[]` is already the recorder's "broken / offline" signal, so a skip that
    also returns `[]` is unreadable. With all three skipped the tick is
    drift-free by construction and lands in `_on_clean_tick()` — which resets
    attempt counters and auto-closes escalations. "Clean" must not be the last
    word an operator sees.
    """
    loop = _loop(tmp_path, contract_refresh_external_enabled=False)
    result = asyncio.run(loop._on_clean_tick())
    assert result is not None
    assert result.get("skipped_recorders"), (
        "a clean tick with three skipped recorders reported nothing about "
        f"them: {result}"
    )
    assert set(result["skipped_recorders"]) == {"github", "docker", "claude"}


def test_a_tick_with_every_recorder_running_reports_no_skips(tmp_path: Path) -> None:
    """Anti-vacuity: the key must not be present-and-truthy unconditionally.

    Without this, a bug that always reported skips would satisfy the test
    above while telling the operator nothing.
    """
    loop = _loop(
        tmp_path,
        contract_refresh_external_enabled=True,
        contract_refresh_external_recorders=("github", "docker", "claude"),
        contracts_sandbox_repo="real-org/real-contracts-sandbox",
    )
    assert loop._external_recorder_skips() == {}
    result = asyncio.run(loop._on_clean_tick())
    assert result is not None
    assert not result.get("skipped_recorders")


@pytest.mark.parametrize("recorder", ["github", "docker", "claude"])
def test_every_external_recorder_is_individually_selectable(
    tmp_path: Path, recorder: str
) -> None:
    """Parametrised over the recorder set rather than asserted once.

    The original defect was precisely that the three were not separable; a
    guard covering only github would re-admit it one recorder over.
    """
    loop = _loop(
        tmp_path,
        contract_refresh_external_enabled=True,
        contract_refresh_external_recorders=(recorder,),
        contracts_sandbox_repo="real-org/real-contracts-sandbox",
    )
    assert recorder not in loop._external_recorder_skips()
    assert len(loop._external_recorder_skips()) == 2


def test_boot_does_not_warn_about_a_recorder_that_is_not_running() -> None:
    """The boot check must not describe a skipped recorder as failing.

    `_check_contracts_sandbox` used to reach GitHub for the placeholder slug,
    get a 404, and advise `contract_refresh_external_enabled=false` — the
    over-broad remedy that is the whole subject of #11837. On a stock install
    the github recorder is now skipped for that exact reason, so there is
    nothing to warn about, and the docker/claude recorders keep working.
    """
    from unittest.mock import MagicMock

    from preflight import CheckStatus, _check_contracts_sandbox

    config = config_mock()
    config.contract_refresh_external_enabled = True
    config.contracts_sandbox_repo = HydraFlowConfig.model_fields[
        "contracts_sandbox_repo"
    ].default

    result = _check_contracts_sandbox(config)

    assert result.status == CheckStatus.PASS, result.message
    assert "skipped" in result.message
    assert "docker and claude still record" in result.message


def test_the_boot_remedy_names_the_narrow_lever_first() -> None:
    """A genuinely unreachable, operator-configured repo still warns.

    Anti-vacuity for the test above — the PASS branch must not swallow the
    real failure — and the remedy must now offer the per-recorder lever, not
    only the kill-switch that took all three down.
    """
    from unittest.mock import MagicMock, patch

    from preflight import CheckStatus, _check_contracts_sandbox

    config = config_mock()
    config.contract_refresh_external_enabled = True
    config.contracts_sandbox_repo = "acme/really-missing"

    gh = MagicMock()
    gh.returncode = 1
    with patch("preflight._run_fixed_argv", return_value=gh):
        result = _check_contracts_sandbox(config)

    assert result.status == CheckStatus.WARN
    assert "contract_refresh_external_recorders" in result.message
