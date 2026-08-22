"""Regression: the agent/sandbox image must ship ``prompts/`` (#11590).

``src/preflight/runner.py`` resolves ``prompts/auto_agent/`` relative to
``src/``; the sandbox container runs HydraFlow from ``/opt/hydraflow/src``,
so ``Dockerfile.agent`` must copy ``prompts`` alongside ``src``. Before this
pin every in-container auto-agent spawn died with ``FileNotFoundError`` on
``_default.md`` — invisible while the light lane defaulted off because no
sandbox scenario reached a spawn.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOCKERFILE = _REPO_ROOT / "Dockerfile.agent"
_COPY_RE = re.compile(r"^COPY\s+(?:--chown=\S+\s+)?(\S+)\s+(\S+)\s*$", re.MULTILINE)


def _copied_into_opt_hydraflow() -> dict[str, str]:
    return {
        src: dst
        for src, dst in _COPY_RE.findall(_DOCKERFILE.read_text(encoding="utf-8"))
        if dst.startswith("/opt/hydraflow/")
    }


def test_agent_image_copies_prompts_next_to_src() -> None:
    copied = _copied_into_opt_hydraflow()
    assert copied.get("src") == "/opt/hydraflow/src"
    assert copied.get("prompts") == "/opt/hydraflow/prompts"


def test_every_auto_agent_playbook_is_a_tracked_file() -> None:
    prompt_dir = _REPO_ROOT / "prompts" / "auto_agent"
    assert (prompt_dir / "_default.md").is_file()
    assert (prompt_dir / "_envelope.md").is_file()
    assert (prompt_dir / "auto-light.md").is_file()
