"""Regression for #11004: the agent image must not carry the `docs` extra.

The agent runtime runs the factory + `make quality` in worktrees — it needs the
`test`/`dev`/`docker` extras but NEVER builds the docs *site* (that is a CI Pages
step / `make arch-serve` for local dev). Installing the `docs` extra (mkdocs +
the heavy mkdocs-material) wasted image budget and chronically pinned the agent
image against its 2 GB cap, so a single legitimate dep addition (pytest-forked,
the #11004 fix) tipped it over and blocked RC promotion.

Guard: the agent Dockerfiles must select extras explicitly (never `--all-extras`,
which pulls `docs` back in) and must not name the `docs` extra. Static text
checks, mirroring the CI-command drift guards (#10904, #11004).
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENT_DOCKERFILES = ("Dockerfile.agent", "Dockerfile.agent-base")


def _sync_lines(dockerfile: str) -> list[str]:
    text = (_REPO_ROOT / dockerfile).read_text(encoding="utf-8")
    return [line for line in text.splitlines() if "uv sync" in line]


@pytest.mark.parametrize("dockerfile", _AGENT_DOCKERFILES)
def test_agent_image_does_not_use_all_extras(dockerfile: str) -> None:
    for line in _sync_lines(dockerfile):
        assert "--all-extras" not in line, (
            f"{dockerfile} uv sync must select extras explicitly, not "
            f"--all-extras (pulls the heavy `docs` extra into the agent image, "
            f"#11004): {line.strip()!r}"
        )


@pytest.mark.parametrize("dockerfile", _AGENT_DOCKERFILES)
def test_agent_image_excludes_docs_extra(dockerfile: str) -> None:
    lines = _sync_lines(dockerfile)
    assert lines, f"{dockerfile}: no `uv sync` line found — did the build move?"
    for line in lines:
        # `--extra docs` would reintroduce mkdocs/mkdocs-material at runtime.
        assert "docs" not in line.split("uv sync", 1)[1], (
            f"{dockerfile} must not install the `docs` extra in the agent "
            f"runtime image (#11004): {line.strip()!r}"
        )
