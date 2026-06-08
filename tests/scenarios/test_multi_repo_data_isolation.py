"""Scenario: two seeded repos get isolated per-repo operational stores (D2).

ADR-0021 (amended) moves runs / insights / cost-telemetry / factory-metrics
from the flat ``data_root`` into ``repo_data_root`` so they no longer collide
when repos share a ``data_root``. This proves the repo-scoped accessors resolve
to distinct paths per runtime and that writing one repo's store does not bleed
into another's.
"""

from __future__ import annotations

import pytest

from mockworld.seed import MockWorldSeed

pytestmark = pytest.mark.scenario


@pytest.mark.asyncio
async def test_seeded_repos_have_isolated_operational_stores(
    mock_world, tmp_path
) -> None:
    seed = MockWorldSeed(
        repos=[
            ("owner/alpha", str(tmp_path / "alpha")),
            ("owner/beta", str(tmp_path / "beta")),
        ],
    )
    mock_world.apply_seed(seed)

    alpha = mock_world.registry.get("owner-alpha").config
    beta = mock_world.registry.get("owner-beta").config

    # Every in-scope D2 store resolves to a distinct path per repo.
    for accessor in (
        "repo_data_root",
        "repo_memory_dir",
        "retrospectives_path",
        "cost_inferences_path",
        "pr_stats_path",
        "factory_metrics_path",
    ):
        assert getattr(alpha, accessor) != getattr(beta, accessor)
    assert alpha.repo_data_path("runs") != beta.repo_data_path("runs")

    # Writing alpha's retrospective store must not appear under beta's.
    alpha.retrospectives_path.parent.mkdir(parents=True, exist_ok=True)
    alpha.retrospectives_path.write_text('{"repo": "alpha"}\n')
    assert not beta.retrospectives_path.exists()
