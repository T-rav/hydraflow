"""Tests for repro_manifest.py — per-PR reproducibility manifest (CH-7, #9735).

The manifest is EVIDENCE, not a pin: it records the models, prompt/skill
template hashes, factory SHA, and allowlisted config flags that were in
effect at PR-authoring time. Nothing here freezes behavior.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from config import HydraFlowConfig
from repro_manifest import (
    CONFIG_SNAPSHOT_ALLOWLIST,
    MANIFEST_HEADING,
    MANIFEST_SCHEMA,
    MODEL_ROLE_FIELDS,
    PROMPT_HASH_SPEC,
    append_manifest,
    build_manifest,
    extract_manifest_block,
    render_manifest_block,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def factory_root(tmp_path: Path) -> Path:
    """A minimal synthetic factory checkout with prompts + skills + git."""
    root = tmp_path / "factory"
    (root / "prompts" / "auto_agent").mkdir(parents=True)
    (root / "prompts" / "auto_agent" / "_default.md").write_text("default prompt\n")
    (root / "prompts" / "auto_agent" / "triage-stuck.md").write_text("triage\n")
    (root / ".codex" / "skills" / "hf.adr").mkdir(parents=True)
    (root / ".codex" / "skills" / "hf.adr" / "SKILL.md").write_text("adr skill\n")
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null"}
    subprocess.run(
        ["git", "init"],
        cwd=root,
        check=True,
        capture_output=True,
        env={**os.environ, **env},
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "add", "."],
        cwd=root,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "init"],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return root


@pytest.fixture
def config() -> HydraFlowConfig:
    return HydraFlowConfig()


# ---------------------------------------------------------------------------
# build_manifest — structure
# ---------------------------------------------------------------------------


def test_manifest_has_schema_and_all_sections(config, factory_root):
    manifest = build_manifest(config, factory_root=factory_root)

    assert manifest["schema"] == MANIFEST_SCHEMA
    assert set(manifest) == {
        "schema",
        "hydraflow_sha",
        "models",
        "prompt_hash_spec",
        "prompt_hashes",
        "config_snapshot",
    }


def test_models_section_covers_every_declared_role(config, factory_root):
    manifest = build_manifest(config, factory_root=factory_root)

    assert set(manifest["models"]) == {role for role, _, _ in MODEL_ROLE_FIELDS}
    for role, tool_field, model_field in MODEL_ROLE_FIELDS:
        entry = manifest["models"][role]
        expected_tool = getattr(config, tool_field) if tool_field else None
        assert entry["tool"] == expected_tool
        assert entry["model"] == getattr(config, model_field)


def test_models_reflect_post_env_post_cascade_resolution(factory_root):
    """The manifest must record the #9717-fixed resolution: an explicit
    per-role combo survives the group cascade, while non-explicit roles
    still receive the cascaded value."""
    with patch.dict(
        os.environ,
        {
            "HYDRAFLOW_REPORT_ISSUE": "claude:opus",
            "HYDRAFLOW_BACKGROUND": "claude:sonnet",
        },
        clear=False,
    ):
        manifest = build_manifest(HydraFlowConfig(), factory_root=factory_root)

    assert manifest["models"]["report_issue"] == {"tool": "claude", "model": "opus"}
    assert manifest["models"]["adr_review"]["model"] == "sonnet"


# ---------------------------------------------------------------------------
# build_manifest — prompt/skill hashes
# ---------------------------------------------------------------------------


def test_prompt_hashes_cover_prompts_and_skill_files(config, factory_root):
    manifest = build_manifest(config, factory_root=factory_root)

    hashes = manifest["prompt_hashes"]
    assert set(hashes) == {
        "prompts/auto_agent/_default.md",
        "prompts/auto_agent/triage-stuck.md",
        ".codex/skills/hf.adr/SKILL.md",
    }
    expected = "sha256:" + hashlib.sha256(b"default prompt\n").hexdigest()
    assert hashes["prompts/auto_agent/_default.md"] == expected


def test_prompt_hashes_are_sorted_and_deterministic(config, factory_root):
    m1 = build_manifest(config, factory_root=factory_root)
    m2 = build_manifest(config, factory_root=factory_root)

    assert m1["prompt_hashes"] == m2["prompt_hashes"]
    keys = list(m1["prompt_hashes"])
    assert keys == sorted(keys)
    assert m1["prompt_hash_spec"] == PROMPT_HASH_SPEC


def test_prompt_hashes_empty_when_dirs_missing(config, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    manifest = build_manifest(config, factory_root=bare)
    assert manifest["prompt_hashes"] == {}


def test_live_factory_root_default_covers_shipped_templates(config):
    """factory_root=None resolves to the real checkout: the shipped prompt
    and skill sets must be enumerated."""
    manifest = build_manifest(config)

    hashes = manifest["prompt_hashes"]
    assert "prompts/auto_agent/_default.md" in hashes
    assert ".codex/skills/hf.adr/SKILL.md" in hashes
    assert all(v.startswith("sha256:") and len(v) == 71 for v in hashes.values())


# ---------------------------------------------------------------------------
# build_manifest — factory SHA
# ---------------------------------------------------------------------------


def test_hydraflow_sha_is_head_of_factory_repo(config, factory_root):
    manifest = build_manifest(config, factory_root=factory_root)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=factory_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert manifest["hydraflow_sha"] == head


def test_hydraflow_sha_unknown_outside_git(config, tmp_path):
    bare = tmp_path / "not-a-repo"
    bare.mkdir()
    manifest = build_manifest(config, factory_root=bare)
    assert manifest["hydraflow_sha"] == "unknown"


# ---------------------------------------------------------------------------
# build_manifest — config snapshot allowlist
# ---------------------------------------------------------------------------


def test_config_snapshot_matches_allowlist_exactly(config, factory_root):
    manifest = build_manifest(config, factory_root=factory_root)

    assert set(manifest["config_snapshot"]) == set(CONFIG_SNAPSHOT_ALLOWLIST)
    for field, value in manifest["config_snapshot"].items():
        assert value == getattr(config, field)
        assert isinstance(value, bool | int | str), field


def test_allowlist_fields_exist_and_carry_no_secrets():
    """Ratchet: every allowlist entry must be a real HydraFlowConfig field,
    and no entry may look like a credential or a user-data path."""
    fields = HydraFlowConfig.model_fields
    forbidden = ("token", "secret", "key", "password", "credential", "path", "dir")
    for name in CONFIG_SNAPSHOT_ALLOWLIST:
        assert name in fields, f"{name} is not a HydraFlowConfig field"
        assert not any(w in name.lower() for w in forbidden), name


def test_allowlist_has_no_duplicates():
    assert len(CONFIG_SNAPSHOT_ALLOWLIST) == len(set(CONFIG_SNAPSHOT_ALLOWLIST))


def test_role_fields_exist_on_config():
    fields = HydraFlowConfig.model_fields
    for role, tool_field, model_field in MODEL_ROLE_FIELDS:
        assert model_field in fields, f"{role}: {model_field}"
        if tool_field is not None:
            assert tool_field in fields, f"{role}: {tool_field}"


# ---------------------------------------------------------------------------
# render_manifest_block / append_manifest
# ---------------------------------------------------------------------------


def test_render_block_is_fenced_json_under_heading(config, factory_root):
    manifest = build_manifest(config, factory_root=factory_root)
    block = render_manifest_block(manifest)

    assert block.startswith(f"{MANIFEST_HEADING}\n")
    assert "```json\n" in block
    payload = block.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(payload) == manifest


def test_append_manifest_appends_block(config, factory_root):
    body = "## Summary\n\nCloses #1."
    out = append_manifest(body, config=config, factory_root=factory_root)

    assert out.startswith(body)
    assert MANIFEST_HEADING in out
    payload = out.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
    assert json.loads(payload)["schema"] == MANIFEST_SCHEMA


def test_append_manifest_builds_live_config_when_none(factory_root):
    out = append_manifest("body", factory_root=factory_root)
    assert MANIFEST_HEADING in out


def test_append_manifest_fails_open_on_error(factory_root):
    """Manifest attachment is evidence, not load-bearing: a failure must
    never block PR creation."""
    with patch("repro_manifest.build_manifest", side_effect=RuntimeError("boom")):
        out = append_manifest("body text", factory_root=factory_root)
    assert out == "body text"


def test_append_manifest_skips_when_body_near_github_limit(config, factory_root):
    body = "x" * 65_000
    out = append_manifest(body, config=config, factory_root=factory_root)
    assert out == body


# ---------------------------------------------------------------------------
# extract_manifest_block (CH-4 reads back what CH-7 wrote)
# ---------------------------------------------------------------------------


def test_extract_round_trips_render(config, factory_root):
    """The evidence-pack compiler must read back exactly what was attached."""
    manifest = build_manifest(config, factory_root=factory_root)
    body = append_manifest("## Summary\n\nCloses #1.", config=config)

    assert extract_manifest_block(body) is not None
    # Round-trip through the real attach path with the same factory root.
    body2 = f"prose\n\n{render_manifest_block(manifest)}"
    assert extract_manifest_block(body2) == manifest


def test_extract_returns_none_without_heading():
    assert extract_manifest_block("## Summary\n\n```json\n{}\n```") is None


def test_extract_returns_none_on_empty_or_none_body():
    assert extract_manifest_block("") is None


def test_extract_returns_none_on_malformed_json():
    body = f"{MANIFEST_HEADING}\n\n```json\nnot json at all\n```\n"
    assert extract_manifest_block(body) is None


def test_extract_returns_none_when_fence_missing():
    body = f"{MANIFEST_HEADING}\n\nno fenced block here\n"
    assert extract_manifest_block(body) is None


def test_extract_returns_none_on_non_dict_payload():
    body = f'{MANIFEST_HEADING}\n\n```json\n["a", "list"]\n```\n'
    assert extract_manifest_block(body) is None


def test_extract_finds_block_amid_other_fences():
    manifest = {"schema": MANIFEST_SCHEMA, "hydraflow_sha": "abc"}
    body = (
        '## Test Plan\n\n```json\n{"other": true}\n```\n\n'
        + render_manifest_block(manifest)
        + "\ntrailing prose\n"
    )
    assert extract_manifest_block(body) == manifest
