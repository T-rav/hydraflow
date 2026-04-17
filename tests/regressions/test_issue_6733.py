"""Regression test for issue #6733.

The ``workspace_gc_interval`` config field is overridden by the env var
``HYDRAFLOW_WORKTREE_GC_INTERVAL`` (legacy name), but the canonical env
var should be ``HYDRAFLOW_WORKSPACE_GC_INTERVAL`` to match the field name
— consistent with every other entry in ``_ENV_INT_OVERRIDES``.

These tests are RED until the env var key is updated to
``HYDRAFLOW_WORKSPACE_GC_INTERVAL`` (with the old key moved to
``_DEPRECATED_ENV_ALIASES``).
"""

from __future__ import annotations

import pytest

from config import _ENV_INT_OVERRIDES

# ---------------------------------------------------------------------------
# Test 1: The env-var naming convention is consistent
# ---------------------------------------------------------------------------


class TestEnvVarNamingConvention:
    """Every entry in _ENV_INT_OVERRIDES must follow the pattern
    field_name -> HYDRAFLOW_<FIELD_NAME_UPPER>.
    """

    @pytest.mark.xfail(reason="Regression for issue #6733 — fix not yet landed", strict=False)
    def test_workspace_gc_interval_env_key_matches_field_name(self) -> None:
        """The canonical env var for workspace_gc_interval should be
        HYDRAFLOW_WORKSPACE_GC_INTERVAL, not HYDRAFLOW_WORKTREE_GC_INTERVAL.
        """
        env_key_for_field: str | None = None
        for field_name, env_key, _default in _ENV_INT_OVERRIDES:
            if field_name == "workspace_gc_interval":
                env_key_for_field = env_key
                break

        assert env_key_for_field is not None, (
            "workspace_gc_interval not found in _ENV_INT_OVERRIDES"
        )
        expected = "HYDRAFLOW_WORKSPACE_GC_INTERVAL"
        assert env_key_for_field == expected, (
            f"Env var for workspace_gc_interval is {env_key_for_field!r}, "
            f"expected {expected!r} (field name and env var are mismatched)"
        )


# ---------------------------------------------------------------------------
# Test 2: Setting the canonical env var actually works at runtime
# ---------------------------------------------------------------------------


class TestCanonicalEnvVarApplied:
    """HYDRAFLOW_WORKSPACE_GC_INTERVAL should control workspace_gc_interval."""

    @pytest.mark.xfail(reason="Regression for issue #6733 — fix not yet landed", strict=False)
    def test_canonical_env_var_overrides_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting HYDRAFLOW_WORKSPACE_GC_INTERVAL should change the field."""
        monkeypatch.setenv("HYDRAFLOW_WORKSPACE_GC_INTERVAL", "900")

        # Re-import to pick up the patched env
        from config import HydraFlowConfig, _apply_env_overrides

        cfg = HydraFlowConfig()
        _apply_env_overrides(cfg)

        assert cfg.workspace_gc_interval == 900, (
            f"Expected workspace_gc_interval=900 from env var "
            f"HYDRAFLOW_WORKSPACE_GC_INTERVAL, got {cfg.workspace_gc_interval}"
        )
