"""Which file the merge gate reads, while both shapes exist (#12116).

`charter.yaml` is becoming the single governing declaration, but a repo that
has not migrated still keeps its policy in
`docs/standards/factory_autonomy/policy.yaml` — and the kernel writer still
stamps that file into every newly onboarded repo. Both must keep working, and
the order between them has to be decided somewhere rather than discovered.

The rule: a charter that DECLARES a policy wins; otherwise the legacy file.
Declaring is the test, not existing — every HydraFlow repo has a `charter.yaml`
already, so "a charter is present" would silently take precedence over the
legacy policy the repo is actually governed by, and fail its merges closed.

Fail-closed is the property under test throughout. `enforce_merge_policy`
treats an unreadable policy as a deny, so resolving to the wrong path does not
degrade politely — it stops the factory merging.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from config import HydraFlowConfig  # noqa: E402

_POLICY_BODY = {
    "schema_version": 1,
    "merge_gate": {
        "unapproved_merge_class": "high-blast-radius",
        "break_glass_label_prefix": "policy-override:",
        "escalation": "hitl",
    },
    "classes": [
        {
            "id": "tractable-reversible",
            "readme_row": "Tractable + reversible",
            "autonomy": "act",
            "default": True,
            "description": "Act, then report.",
            "actions": [],
        },
        {
            "id": "high-blast-radius",
            "readme_row": "High blast radius",
            "autonomy": "ask",
            "description": "Confirm first.",
            "actions": ["merge-unapproved-pr"],
            "required_approvals": {"count": 1, "roles": ["operator"]},
            "escalation": "hitl",
        },
    ],
}


def _legacy(repo: Path) -> Path:
    target = repo / "docs" / "standards" / "factory_autonomy" / "policy.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(_POLICY_BODY), encoding="utf-8")
    return target


def _charter(repo: Path, *, with_policy: bool) -> Path:
    doc: dict[str, object] = {
        "schema_version": 2,
        "purpose": {"product": "x", "goals": ["g"]},
    }
    if with_policy:
        doc["policy"] = _POLICY_BODY
    target = repo / "charter.yaml"
    target.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return target


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    return root


def test_a_charter_that_declares_a_policy_is_the_source(repo: Path) -> None:
    """The end state this issue is moving toward."""
    charter = _charter(repo, with_policy=True)

    assert HydraFlowConfig(repo_root=repo).merge_policy_path == charter


def test_a_charter_that_declares_a_policy_beats_a_legacy_file(repo: Path) -> None:
    """During migration both exist. The charter is the governing declaration,
    so it wins — otherwise moving the content in would change nothing and the
    two copies would drift apart unnoticed."""
    charter = _charter(repo, with_policy=True)
    _legacy(repo)

    assert HydraFlowConfig(repo_root=repo).merge_policy_path == charter


def test_a_charter_without_a_policy_yields_to_the_legacy_file(repo: Path) -> None:
    """The case that makes "declares" the right test rather than "exists".

    Every HydraFlow repo already has a `charter.yaml`; almost none of them
    declare a policy yet. Keying on presence would point the merge gate at a
    file with no policy in it and deny every merge in every unmigrated repo.
    """
    _charter(repo, with_policy=False)
    legacy = _legacy(repo)

    assert HydraFlowConfig(repo_root=repo).merge_policy_path == legacy


def test_a_repo_with_only_a_legacy_file_is_unchanged(repo: Path) -> None:
    """No charter at all — the pre-#12116 behaviour, pinned so the migration
    cannot quietly drop the repos that have not started it."""
    legacy = _legacy(repo)

    assert HydraFlowConfig(repo_root=repo).merge_policy_path == legacy


def test_an_unparseable_charter_does_not_swallow_the_legacy_file(repo: Path) -> None:
    """A broken charter must not be read as "declares no policy" *and* also not
    strand the repo: the legacy file is still there and still governs.

    The alternative — treating a YAML error as "charter wins" — points the gate
    at a file that cannot be parsed, which denies every merge on a syntax error
    in a section the repo may not even use yet.
    """
    (repo / "charter.yaml").write_text("{{ not: valid", encoding="utf-8")
    legacy = _legacy(repo)

    assert HydraFlowConfig(repo_root=repo).merge_policy_path == legacy
