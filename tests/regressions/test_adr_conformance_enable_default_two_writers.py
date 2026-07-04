"""Regression: adr_conformance_loop_enabled has two writers of its default.

#9705 enabled AdrConformanceLoop by default by flipping the pydantic Field
default False->True, but the value is ALSO recorded in config._ENV_BOOL_OVERRIDES
(the env-var override table). Only the Field was updated, so the two drifted
and three tests in test_config_env.py failed — reddening staging's Tests job.

This pins the specific invariant for this flag: the env-override table's
recorded default must equal the pydantic field default, and both must be
True (enabled). The general drift guard lives in
``test_config_env.py::test_override_table_defaults_match_field_defaults``;
this is the incident-specific pin.
"""

from __future__ import annotations

from config import _ENV_BOOL_OVERRIDES, HydraFlowConfig


def test_adr_conformance_enable_default_is_true_and_consistent():
    field_default = HydraFlowConfig().adr_conformance_loop_enabled
    assert field_default is True

    table = {attr: default for attr, _env, default in _ENV_BOOL_OVERRIDES}
    assert "adr_conformance_loop_enabled" in table
    assert table["adr_conformance_loop_enabled"] == field_default
