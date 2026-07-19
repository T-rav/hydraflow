"""Regression (#9754): the sandbox must disable CH-3 merge policy.

`enforce_merge_policy` fetches PR labels via a RAW `gh pr view --json labels`
subprocess (`merge_policy._fetch_pr_labels`, deliberately not routed through
PRPort). On the air-gapped sandbox network that runs against an empty
`config.repo`, falls back to git, and fails with "not a git repository" — so
EVERY approved PR's merge raised and no issue reached the "merged" outcome
(s01_happy_single_issue timed out with 0 merged issues).

`sandbox_main._apply_sandbox_config_overrides` must turn merge_policy off,
alongside the other external-reaching features it already disables. The e2e
guard is the s01 sandbox scenario, but that job is path-filtered and often
skipped; this fast unit guard runs in every `make quality`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from mockworld.sandbox_main import _apply_sandbox_config_overrides
from tests.helpers import ConfigFactory


def test_sandbox_disables_merge_policy_and_other_external_reachers() -> None:
    config = ConfigFactory.create()
    # Sanity: these default ON in production, so the overrides are meaningful.
    assert config.merge_policy_enabled is True
    assert config.research_enabled is True

    _apply_sandbox_config_overrides(config)

    # The #9754 fix: merge policy off so the raw gh label read never fires.
    assert config.merge_policy_enabled is False
    # The siblings it sits beside — all external reachers, all off.
    assert config.transcript_summarization_enabled is False
    assert config.research_enabled is False
    assert config.contract_refresh_external_enabled is False
