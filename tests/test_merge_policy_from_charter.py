"""The merge policy is read out of `charter.yaml` (#12116).

Operator ruling, 2026-09-03: *"should just be charter, policy roles under it."*
`charter.yaml` becomes the single governing declaration, and the act-vs-ask
classes move under it from `docs/standards/factory_autonomy/policy.yaml`.

The move is not a preferences edit. `policy.yaml` is normative — it is what
`merge_policy.enforce_merge_policy` gates the factory's own merges on — so the
one property that must survive it is the fail-closed one: a policy that cannot
be read is a deny, never a default-allow. Every case here is written so that a
loader which quietly returned an empty policy would fail it.

The legacy shape stays loadable on purpose. A repo mid-migration still carries
`policy.yaml`, and a consolidation that made those repos fail closed on their
next merge would be an outage dressed as a cleanup.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from merge_policy import (  # noqa: E402
    MERGE_POLICY_SCHEMA_VERSION,
    MergePolicyError,
    load_merge_policy,
)

_LEGACY = {
    "schema_version": MERGE_POLICY_SCHEMA_VERSION,
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
            "description": "Confirm before acting.",
            # The gate class must actually list the action it gates — the
            # schema refuses a `unapproved_merge_class` that names a class
            # which does not cover `merge-unapproved-pr`, so the binding
            # cannot be nominal.
            "actions": ["merge-unapproved-pr"],
            # An `ask` entry must declare who may approve it — the schema
            # refuses one that does not, which is the rule that stops a class
            # being nominally gated and actually unapprovable.
            "required_approvals": {"count": 1, "roles": ["operator"]},
            # …and where it goes when nobody approves it. Both are required
            # together: a gated class with no escalation route stalls silently.
            "escalation": "hitl",
        },
    ],
}


def _write(path: Path, document: object) -> Path:
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def test_a_charter_carries_the_policy_under_its_own_key(tmp_path: Path) -> None:
    """The end state: one file, the policy nested under `policy:`."""
    charter = _write(
        tmp_path / "charter.yaml",
        {
            "schema_version": 2,
            "purpose": {"product": "x", "goals": ["g"]},
            "policy": _LEGACY,
        },
    )

    policy = load_merge_policy(charter)

    assert policy.unapproved_merge_class == "high-blast-radius"
    assert {entry.id for entry in policy.entries} == {
        "tractable-reversible",
        "high-blast-radius",
    }


def test_a_legacy_policy_document_still_loads(tmp_path: Path) -> None:
    """A repo mid-migration must not fail closed on its next merge.

    Without this the consolidation is an outage for every repo that has not
    yet moved its file — and fail-closed means their merges stop, not that
    they degrade politely.
    """
    legacy = _write(tmp_path / "policy.yaml", _LEGACY)

    assert load_merge_policy(legacy).unapproved_merge_class == "high-blast-radius"


def test_a_charter_with_no_policy_section_is_refused(tmp_path: Path) -> None:
    """Fail closed. An unmigrated charter must not read as "no restrictions".

    This is the case that makes the whole change safe or not. A loader that
    treated a missing `policy:` as an empty policy would hand back something
    with no classes and no gate — and the merge seam would then approve
    everything, silently, on every repo whose charter had not been migrated.
    """
    charter = _write(
        tmp_path / "charter.yaml",
        {"schema_version": 2, "purpose": {"product": "x", "goals": ["g"]}},
    )

    with pytest.raises(MergePolicyError):
        load_merge_policy(charter)


def test_a_policy_section_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    """The decoy for the case above: `policy:` present but useless."""
    charter = _write(
        tmp_path / "charter.yaml", {"schema_version": 2, "policy": ["not", "a", "map"]}
    )

    with pytest.raises(MergePolicyError):
        load_merge_policy(charter)


def test_the_nested_policy_is_validated_as_strictly_as_a_bare_one(
    tmp_path: Path,
) -> None:
    """Nesting must not become a way to smuggle a malformed policy past the
    schema check — the validation applies to the subtree, not to the file."""
    broken = {**_LEGACY, "merge_gate": {"unapproved_merge_class": "high-blast-radius"}}
    charter = _write(tmp_path / "charter.yaml", {"schema_version": 2, "policy": broken})

    with pytest.raises(MergePolicyError):
        load_merge_policy(charter)


def test_an_unknown_key_inside_the_policy_section_is_refused(tmp_path: Path) -> None:
    """`_TOP_LEVEL_KEYS` still applies one level down."""
    charter = _write(
        tmp_path / "charter.yaml",
        {"schema_version": 2, "policy": {**_LEGACY, "surprise": 1}},
    )

    with pytest.raises(MergePolicyError):
        load_merge_policy(charter)


def test_a_charter_key_beside_the_policy_is_not_an_unknown_policy_key(
    tmp_path: Path,
) -> None:
    """The charter's own sections must not be judged by the policy schema.

    `_TOP_LEVEL_KEYS` is `{schema_version, merge_gate, classes}`. Applied to
    the charter root — which carries `purpose`, `articles`, `rails`, `loops`
    — every one of those reads as an unknown key, so a loader that forgot to
    descend would refuse every charter it was handed and fail the factory
    closed on a file that is entirely correct.
    """
    charter = _write(
        tmp_path / "charter.yaml",
        {
            "schema_version": 2,
            "purpose": {"product": "x", "goals": ["g"]},
            "articles": {"standards": ["testing"]},
            "rails": {},
            "loops": {},
            "policy": _LEGACY,
        },
    )

    assert load_merge_policy(charter).unapproved_merge_class == "high-blast-radius"


def test_a_missing_file_is_still_a_refusal(tmp_path: Path) -> None:
    """Unchanged, and restated here because it is the property the whole
    consolidation risks: no readable declaration means deny, not allow."""
    with pytest.raises(MergePolicyError):
        load_merge_policy(tmp_path / "nothing-here.yaml")
