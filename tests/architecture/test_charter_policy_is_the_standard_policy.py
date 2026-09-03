"""While both policy files exist, they say the same thing (#12116).

`charter.yaml`'s `policy:` section is now the normative copy for this repo —
`config.merge_policy_path` prefers a charter that declares one. But
`docs/standards/factory_autonomy/policy.yaml` has not gone away: the kernel
writer (`onboarding/kernel_writer.py:STANDARDS_DIRS`) stamps the whole
`factory_autonomy/` directory into every newly onboarded repo, and those repos
have no policy in their charter yet. Deleting it would leave them with no
governing policy at all, which fails their merges closed on day one.

So the migration leaves two files in place for a while, and that is precisely
the shape this issue exists to remove: two normative-looking declarations of
one thing. The difference between a migration and a regression is whether the
duplication is *checked*. This is the check.

It is deliberately an equality, not a floor. A subset relation would let the
charter grow a class the stamped file never gets, and the divergence would
first be observed as a newly onboarded repo governing itself by different
rules than the factory that onboarded it.

Delete this file together with `policy.yaml`, not before — while the second
file ships, something has to hold it to the first.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CHARTER = _REPO_ROOT / "charter.yaml"
_STANDARD = _REPO_ROOT / "docs" / "standards" / "factory_autonomy" / "policy.yaml"


def _load(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name} is not a mapping"
    return loaded


def test_the_charter_declares_a_policy() -> None:
    """Fail closed on the premise. Every case below is vacuous without it —
    an empty `policy:` would make the comparison trivially true against a
    standard file that had drifted arbitrarily far."""
    charter = _load(_CHARTER)

    assert charter.get("policy"), (
        "charter.yaml declares no `policy:` section, so the merge gate has "
        "silently fallen back to docs/standards/factory_autonomy/policy.yaml"
    )


@pytest.mark.skipif(
    not _STANDARD.exists(),
    reason="policy.yaml has been retired; this guard retires with it",
)
def test_the_two_declarations_are_identical() -> None:
    """The stamped copy and the governing copy must not diverge.

    Compared as parsed documents rather than as text: comment and formatting
    differences between the two files are expected and mean nothing, while a
    single reordered `roles:` entry means the onboarded repo approves merges a
    different set of actors can approve.
    """
    assert _load(_CHARTER)["policy"] == _load(_STANDARD), (
        "charter.yaml's `policy:` section and "
        "docs/standards/factory_autonomy/policy.yaml have drifted. The charter "
        "is what governs this repo; the standard file is what the kernel writer "
        "stamps into new ones. Update both, or retire policy.yaml and delete "
        "this guard with it."
    )
