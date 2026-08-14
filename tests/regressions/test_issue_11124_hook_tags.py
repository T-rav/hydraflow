"""Regression pins for the Claude-hook propagation gap (#11124/#11135).

`merge_assets.merge_settings_file` only propagates hook entries tagged
`"_hydraflow": true` into managed repos — but `.claude/settings.json`
carried ZERO tags, so every onboarded repo received the hook *scripts*
(via `copy_namespaced_files`) with nothing wiring them into settings:
dead destructive-git/secret-scan/lint enforcement everywhere (#11124).
`hf.validate-functional-areas.sh` was doubly dead — shipped but referenced
by no settings entry even in HydraFlow itself (#11135).

Pinned invariants:
1. every settings hook whose command references `.claude/hooks/hf.` is
   tagged `_hydraflow: true`;
2. bidirectional coverage — every `hf.*.sh` on disk is referenced by some
   settings entry, and every referenced script exists;
3. the merge actually lands the tagged hooks in a target repo's settings.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

_MODULE_PATH = REPO_ROOT / "scripts" / "merge_assets.py"
_spec = importlib.util.spec_from_file_location("merge_assets", _MODULE_PATH)
assert _spec is not None and _spec.loader is not None
merge_assets = importlib.util.module_from_spec(_spec)
sys.modules["merge_assets"] = merge_assets
_spec.loader.exec_module(merge_assets)


def _settings() -> dict:
    return json.loads((REPO_ROOT / ".claude" / "settings.json").read_text())


def _hf_hook_objects() -> list[dict]:
    out = []
    for entries in _settings().get("hooks", {}).values():
        for entry in entries:
            out.extend(
                h
                for h in entry.get("hooks", [])
                if ".claude/hooks/hf." in h.get("command", "")
            )
    return out


def test_every_hf_hook_entry_is_hydraflow_tagged() -> None:
    hooks = _hf_hook_objects()
    assert hooks, "expected hf. hook entries in .claude/settings.json"
    untagged = [h["command"] for h in hooks if not h.get("_hydraflow")]
    assert untagged == [], (
        f"untagged hf. hooks {untagged} — merge_settings_file only propagates "
        f"'_hydraflow: true' entries, so these are dead in every managed repo"
    )


def test_hook_scripts_and_settings_references_match_bidirectionally() -> None:
    referenced = {
        m.group(0)
        for h in _hf_hook_objects()
        if (m := re.search(r"hf\.[a-z-]+\.sh", h.get("command", "")))
    }
    on_disk = {f.name for f in (REPO_ROOT / ".claude" / "hooks").glob("hf.*.sh")}
    assert on_disk - referenced == set(), (
        f"orphan hook scripts shipped to managed repos but wired nowhere "
        f"(#11135): {sorted(on_disk - referenced)}"
    )
    assert referenced - on_disk == set(), (
        f"settings reference missing scripts: {sorted(referenced - on_disk)}"
    )


def test_merge_lands_tagged_hooks_in_target_settings(tmp_path: Path) -> None:
    target = tmp_path / ".claude" / "settings.json"
    target.parent.mkdir(parents=True)
    target.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Bash",
                            "hooks": [{"type": "command", "command": "their-own.sh"}],
                        }
                    ]
                }
            }
        )
    )
    merge_assets.merge_settings_file(REPO_ROOT / ".claude" / "settings.json", target)
    merged = json.loads(target.read_text())
    bash_cmds = [
        h["command"]
        for e in merged["hooks"]["PreToolUse"]
        if e.get("matcher") == "Bash"
        for h in e["hooks"]
    ]
    assert any("hf.block-destructive-git.sh" in c for c in bash_cmds)
    assert any("hf.validate-functional-areas.sh" in c for c in bash_cmds)
    # The target repo's own hook survives the merge.
    assert "their-own.sh" in bash_cmds
