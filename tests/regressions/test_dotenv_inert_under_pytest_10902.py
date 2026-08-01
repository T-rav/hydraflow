"""Regression (#10902): the ``.env`` fallback must be inert for a repo root the
test harness marks inert, so a default-constructed ``HydraFlowConfig()`` in a
test cannot read the operator's real ``.env``.

``_dotenv_lookup`` resolves ``repo_root/.env``; ``repo_root`` defaults to the
real checkout, whose ``.env`` carries a live ``HYDRAFLOW_GH_TOKEN`` no
``os.environ`` scrub can close. Roughly 145 tests default-construct the config,
so the real token was a live input to ``build_credentials`` masked only by
conftest seeding ``GH_TOKEN=test-token`` ahead of the fallback. The fix is an
explicit inert-root seam; conftest registers the real checkout root. Production
resolution is unchanged (pinned by
``tests/test_config_validation.py::test_gh_token_picks_up_dotenv_fallback`` — an
*explicit* ``repo_root=tmp_path`` is a different root and stays live).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from config import (
    HydraFlowConfig,
    build_credentials,
    register_dotenv_inert_root,
    unregister_dotenv_inert_root,
)


def test_inert_root_makes_dotenv_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / ".env").write_text("HYDRAFLOW_GH_TOKEN=ghp_should_not_leak\n")
    monkeypatch.delenv("HYDRAFLOW_GH_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    cfg = HydraFlowConfig(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
    )

    # Not (yet) inert → the .env fallback still works — the production behavior
    # the pinned dotenv-fallback test depends on.
    assert build_credentials(cfg).gh_token == "ghp_should_not_leak"

    # Marked inert → the .env is treated as absent; no real token leaks into a
    # test-constructed config (#10902). discard only this root so the session
    # fixture's real-checkout registration is untouched.
    register_dotenv_inert_root(tmp_path)
    try:
        assert build_credentials(cfg).gh_token == ""
    finally:
        unregister_dotenv_inert_root(tmp_path)
