"""Guard: every `astral-sh/setup-uv` step across all CI workflows enables the
uv cache.

Without `enable-cache: true`, every job re-resolves and re-downloads the whole
dependency set on each run (`uv sync --all-extras`) — the Tier 1b slowdown this
ratchet exists to prevent regressing. Keying invalidation on `uv.lock` via
`cache-dependency-glob` keeps the cache correct when deps change. A new workflow
(or a new setup-uv step) that forgets caching fails here at PR time instead of
silently burning minutes on every future run.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOWS_DIR = _REPO_ROOT / ".github" / "workflows"


def _setup_uv_steps() -> list[tuple[str, str, dict]]:
    """Yield (workflow_file, job_name, step_dict) for every setup-uv step."""
    found: list[tuple[str, str, dict]] = []
    for wf in sorted(_WORKFLOWS_DIR.glob("*.yml")):
        data = yaml.safe_load(wf.read_text(encoding="utf-8"))
        for job_name, job in (data.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                uses = (step or {}).get("uses", "")
                if isinstance(uses, str) and uses.startswith("astral-sh/setup-uv"):
                    found.append((wf.name, job_name, step))
    return found


def test_at_least_one_setup_uv_step_discovered():
    # Sanity: the walker actually finds steps, so a green result below is not a
    # vacuous pass from a broken parse/traversal.
    assert _setup_uv_steps(), (
        "no astral-sh/setup-uv steps found under .github/workflows"
    )


def test_every_setup_uv_step_enables_cache():
    offenders: list[str] = []
    for wf_name, job_name, step in _setup_uv_steps():
        with_block = step.get("with") or {}
        if with_block.get("enable-cache") is not True:
            offenders.append(f"{wf_name}:{job_name} missing `enable-cache: true`")
        if not with_block.get("cache-dependency-glob"):
            offenders.append(f"{wf_name}:{job_name} missing `cache-dependency-glob`")
    assert not offenders, "setup-uv steps without uv caching:\n" + "\n".join(offenders)
