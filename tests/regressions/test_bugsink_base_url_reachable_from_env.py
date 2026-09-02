"""Regression: the sensor's Bugsink URL is settable from the environment.

`bugsink_base_url` shipped in #12020 as a config field with NO entry in
`_ENV_STR_OVERRIDES`. Nothing could set it. The intake reads it to fetch an
error group's stack trace from Bugsink's API, so unset it reads "" and
`_stacktrace_for` returns immediately — the enrichment would have been
permanently inert in any real deployment, and silently, because a missing trace
is indistinguishable from a backend that had none.

That is the same failure the exception sensor exists to prevent, shipped inside
the sensor's own feature: a thing that looks configured and does nothing.

Pinned as behaviour (set the var, read the field) rather than as the presence of
a table row, so it survives the override mechanism being refactored.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from config import HydraFlowConfig  # noqa: E402


def test_the_env_var_sets_the_field() -> None:
    with patch.dict(os.environ, {"HYDRAFLOW_BUGSINK_BASE_URL": "http://bs:8000"}):
        assert HydraFlowConfig().bugsink_base_url == "http://bs:8000"


def test_it_is_empty_when_unset() -> None:
    """The decoy: a field hardcoded to the probe value would pass above."""
    env = {k: v for k, v in os.environ.items() if k != "HYDRAFLOW_BUGSINK_BASE_URL"}
    with patch.dict(os.environ, env, clear=True):
        assert HydraFlowConfig().bugsink_base_url == ""
