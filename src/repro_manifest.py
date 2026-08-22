"""Per-PR reproducibility manifest (CH-7, issue #9735).

When auditing a merged change months later, "which model versions, prompt
templates, and skill versions produced this?" must be answerable without
archaeology. This module builds a small JSON evidence block that the PR
authoring paths (``pr_manager.create_pr`` and the ``auto_pr`` entry points)
append to the PR body under a ``## Reproducibility Manifest`` heading.

The manifest records:

* ``hydraflow_sha`` — HEAD SHA of the factory checkout that authored the PR.
* ``models`` — resolved ``(tool, model)`` per role, read from the live
  :class:`~config.HydraFlowConfig` AFTER env-combo overrides and the
  SYSTEM/BACKGROUND group cascade have been applied (the #9717-fixed
  resolution — plain ``HydraFlowConfig()`` construction runs both stages).
* ``prompt_hashes`` — sha256 content hashes of the prompt/skill template
  set shipped in-repo. The set is stable and enumerable, documented by
  :data:`PROMPT_HASH_SPEC`: every ``*.md`` under ``prompts/`` plus every
  ``.codex/skills/*/SKILL.md``.
* ``config_snapshot`` — an explicit allowlist of non-secret config fields
  (:data:`CONFIG_SNAPSHOT_ALLOWLIST`): the tool/model role fields plus the
  flags that change authoring behavior. Credentials live on the separate
  ``Credentials`` class and are structurally unreachable here; the
  allowlist additionally never names tokens/keys/paths.

Manifests are EVIDENCE, not pins: nothing here freezes models per branch —
we record what WAS used. Attachment is fail-open: any error while building
the manifest logs a warning and leaves the PR body unchanged, because PR
creation is load-bearing and the manifest is not.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any

from config import HydraFlowConfig
from package_resources import RESOURCE_PACKAGE, checkout_root, package_root

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA = "hydraflow.repro-manifest/v1"
MANIFEST_HEADING = "## Reproducibility Manifest"

# The first fenced ```json block after the manifest heading — the exact shape
# :func:`render_manifest_block` writes. DOTALL because the payload is
# multi-line; non-greedy so a later unrelated fence can't be swallowed.
_MANIFEST_BLOCK_RE = re.compile(
    re.escape(MANIFEST_HEADING) + r"\s*```json\n(?P<payload>.*?)\n```",
    re.DOTALL,
)

# GitHub rejects PR bodies over 65_536 chars; leave headroom for the block.
_GITHUB_BODY_LIMIT = 65_536
_BODY_HEADROOM = 8_192

# The documented, stable, enumerable prompt/skill template set (recorded in
# the manifest itself so auditors know what the hash set covers).
PROMPT_HASH_SPEC = "prompts/**/*.md + .codex/skills/*/SKILL.md"

# Role → (tool_field | None, model_field) on HydraFlowConfig. Mirrors the
# per-role combo table (`config._ENV_COMBO_OVERRIDES`) plus the roles that
# have config fields but no combo env var (subskill, debug,
# verification_judge, corpus_learning_synthesis — the last has a model field
# only). ``system``/``background`` are the group-cascade sources; they are
# recorded too so an auditor can see what cascaded.
MODEL_ROLE_FIELDS: tuple[tuple[str, str | None, str], ...] = (
    ("system", "system_tool", "system_model"),
    ("background", "background_tool", "background_model"),
    ("implementation", "implementation_tool", "model"),
    ("review", "review_tool", "review_model"),
    ("planner", "planner_tool", "planner_model"),
    ("triage", "triage_tool", "triage_model"),
    ("subskill", "subskill_tool", "subskill_model"),
    ("debug", "debug_tool", "debug_model"),
    ("ac", "ac_tool", "ac_model"),
    ("verification_judge", "verification_judge_tool", "review_model"),
    ("wiki_compilation", "wiki_compilation_tool", "wiki_compilation_model"),
    ("transcript_summary", "transcript_summary_tool", "transcript_summary_model"),
    ("report_issue", "report_issue_tool", "report_issue_model"),
    ("adr_review", "adr_review_tool", "adr_review_model"),
    ("corpus_learning_synthesis", None, "corpus_learning_synthesis_model"),
)

# Non-secret config snapshot: ONLY scalar flags that change how PRs get
# authored. Model/tool fields are captured (post-cascade) in ``models``;
# they are intentionally not duplicated here. NEVER add tokens, keys, or
# path-like fields — ``test_allowlist_fields_exist_and_carry_no_secrets``
# ratchets this.
CONFIG_SNAPSHOT_ALLOWLIST: tuple[str, ...] = (
    "staging_enabled",
    "research_enabled",
    "implement_two_stage_review_enabled",
    "use_quality_gate_in_review",
    "epic_group_planning",
    "epic_gap_review_max_iterations",
    "max_review_fix_attempts",
    "tdd_max_remediation_loops",
    "agent_unrestricted_tools",
    "dry_run",
)


def _default_factory_root() -> Path:
    """The root the factory's own prompts and git metadata hang off.

    The checkout executing this code when there is one. From an installed
    wheel there is no checkout, so fall back to the packaged resource root:
    :func:`_prompts_dir` still finds ``prompts/`` beneath it (the trees ship
    as package data, #11589) and the hash keys are unchanged, while
    ``git rev-parse`` finds no repository and the SHA degrades to
    ``"unknown"`` — the honest answer for a build that came from no checkout.
    """
    root = checkout_root()
    return root if root is not None else package_root() / RESOURCE_PACKAGE


def _factory_sha(factory_root: Path) -> str:
    """HEAD SHA of the factory checkout, or ``"unknown"`` outside git."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=factory_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    sha = res.stdout.strip()
    return sha if res.returncode == 0 and sha else "unknown"


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _prompts_dir(factory_root: Path) -> Path | None:
    """Where *factory_root*'s auto-agent prompts live, or ``None``.

    Since #11589 the prompt tree is package data under
    ``src/hydraflow_resources/prompts`` — the one location that resolves both
    in a checkout and beside the installed modules. ``<root>/prompts`` stays
    a recognised layout so a root that predates the move (or a fixture that
    models one) is still hashed rather than silently reported empty.
    """
    for candidate in (
        factory_root / "src" / RESOURCE_PACKAGE / "prompts",
        factory_root / "prompts",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _prompt_hashes(factory_root: Path) -> dict[str, str]:
    """sha256 per template file in the :data:`PROMPT_HASH_SPEC` set.

    Keys stay ``prompts/...`` / ``.codex/skills/...`` regardless of where the
    prompt tree physically sits, so manifests remain comparable across the
    #11589 move.
    """
    keyed: dict[str, Path] = {}
    prompts_dir = _prompts_dir(factory_root)
    if prompts_dir is not None:
        keyed.update(
            {
                f"prompts/{p.relative_to(prompts_dir).as_posix()}": p
                for p in prompts_dir.rglob("*.md")
            }
        )
    skills_dir = factory_root / ".codex" / "skills"
    if skills_dir.is_dir():
        keyed.update(
            {
                p.relative_to(factory_root).as_posix(): p
                for p in skills_dir.glob("*/SKILL.md")
            }
        )
    return {key: _hash_file(keyed[key]) for key in sorted(keyed)}


def _resolved_models(config: HydraFlowConfig) -> dict[str, dict[str, str | None]]:
    return {
        role: {
            "tool": getattr(config, tool_field) if tool_field else None,
            "model": getattr(config, model_field),
        }
        for role, tool_field, model_field in MODEL_ROLE_FIELDS
    }


def _config_snapshot(config: HydraFlowConfig) -> dict[str, Any]:
    return {name: getattr(config, name) for name in CONFIG_SNAPSHOT_ALLOWLIST}


def build_manifest(
    config: HydraFlowConfig, *, factory_root: Path | None = None
) -> dict[str, Any]:
    """Build the reproducibility manifest dict from the live config.

    *config* must be the post-construction (env-applied, cascade-applied)
    :class:`HydraFlowConfig` — plain construction satisfies this.
    """
    root = factory_root if factory_root is not None else _default_factory_root()
    return {
        "schema": MANIFEST_SCHEMA,
        "hydraflow_sha": _factory_sha(root),
        "models": _resolved_models(config),
        "prompt_hash_spec": PROMPT_HASH_SPEC,
        "prompt_hashes": _prompt_hashes(root),
        "config_snapshot": _config_snapshot(config),
    }


def render_manifest_block(manifest: dict[str, Any]) -> str:
    """Render the manifest as the markdown comment block appended to PR bodies."""
    payload = json.dumps(manifest, indent=2, sort_keys=True)
    return f"{MANIFEST_HEADING}\n\n```json\n{payload}\n```\n"


def extract_manifest_block(body: str) -> dict[str, Any] | None:
    """Parse the manifest back out of a PR *body* — best-effort, never raises.

    Inverse of :func:`render_manifest_block` for the evidence-pack compiler
    (CH-4, #9732): it bundles the RC PR's own manifest into the release
    evidence pack. Returns ``None`` when the heading, the fenced JSON block,
    or a JSON object payload is absent — the caller records a named gap.
    """
    match = _MANIFEST_BLOCK_RE.search(body or "")
    if match is None:
        return None
    try:
        parsed = json.loads(match.group("payload"))
    except json.JSONDecodeError:
        logger.warning("Unparseable reproducibility-manifest block in PR body")
        return None
    if not isinstance(parsed, dict):
        return None
    return parsed


def append_manifest(
    body: str,
    *,
    config: HydraFlowConfig | None = None,
    factory_root: Path | None = None,
) -> str:
    """Append the reproducibility manifest block to a PR *body* — fail-open.

    Callers with a config in hand (``PRManager``) pass it; the ``auto_pr``
    paths pass ``None`` and a live config is constructed here, which applies
    the env-combo overrides and group cascade (#9717 resolution).

    Any failure — config construction, hashing, git — logs a warning and
    returns *body* unchanged: the manifest is evidence, not load-bearing.
    """
    try:
        cfg = config if config is not None else HydraFlowConfig()
        block = render_manifest_block(build_manifest(cfg, factory_root=factory_root))
        if len(body) + len(block) > _GITHUB_BODY_LIMIT - _BODY_HEADROOM:
            logger.warning(
                "repro manifest skipped: PR body (%d chars) too close to the "
                "GitHub body limit",
                len(body),
            )
            return body
        return f"{body}\n\n{block}"
    except Exception:  # evidence attachment must never block PR creation
        logger.warning("failed to attach reproducibility manifest", exc_info=True)
        return body
