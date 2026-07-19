"""Regression: SecurityPatchLoop severity threshold defaults to "medium".

Previously the default was "high", so medium-severity Dependabot/security alerts
(e.g. the open `idna` and `pymdown-extensions` advisories) fell below the
threshold and the SecurityPatchLoop never filed a rollup issue for them — they
sat unactioned. Lowered the default to "medium" (in BOTH the `_ENV_STR_OVERRIDES`
env tuple and the Pydantic `Field`, so base and per-repo runtime configs agree)
so medium alerts are surfaced by default.
"""

from __future__ import annotations

from config import HydraFlowConfig


def test_security_patch_threshold_defaults_to_medium() -> None:
    """A fresh config (no override) files security rollups down to medium."""
    assert HydraFlowConfig().security_patch_severity_threshold == "medium"
