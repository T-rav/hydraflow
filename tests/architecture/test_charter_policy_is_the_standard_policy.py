"""The standard HydraFlow ships is the standard HydraFlow runs (#12116).

`charter.yaml`'s `policy:` section is what governs THIS repo's merges.
`src/assets/factory_autonomy_policy.yaml` is what the onboarding stamp copies
into a NEW repo's charter, and the fallback `config.merge_policy_path` resolves
to for a repo that declares none.

They are two files on purpose — a repo may tighten its own policy without
changing what HydraFlow ships — but while HydraFlow is its own reference
implementation they must agree. A divergence would first be observed as an
onboarded repo governing itself by different rules than the factory that
onboarded it, which is the failure this guard exists to make impossible.

It replaces the guard that held the charter to
`docs/standards/factory_autonomy/policy.yaml`. That file is gone: it was a
second normative-looking declaration of one thing, and `docs/` is absent from
the wheel, so the fallback that pointed at it had nothing to reach in an
installed HydraFlow.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT / "src"))

_CHARTER = _REPO_ROOT / "charter.yaml"
_SHIPPED = _REPO_ROOT / "src" / "assets" / "factory_autonomy_policy.yaml"


def _load(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name} is not a mapping"
    return loaded


def test_the_charter_declares_a_policy() -> None:
    """Fail closed on the premise. Every case below is vacuous without it: an
    absent `policy:` would make the comparison trivially true against a shipped
    default that had drifted arbitrarily far."""
    assert _load(_CHARTER).get("policy"), (
        "charter.yaml declares no `policy:` section, so this repo's merge gate "
        "has fallen back to the shipped default instead of its own declaration"
    )


def test_the_shipped_default_exists() -> None:
    """It is package data and the last-resort fallback, so its absence is not a
    missing test fixture — it is every repo without a declared policy losing
    the thing `merge_policy_path` resolves to."""
    assert _SHIPPED.exists(), f"{_SHIPPED} is missing from package data"


def test_the_shipped_default_matches_the_charter() -> None:
    """Compared as parsed documents, so comment and formatting differences
    between the two files mean nothing while a single reordered `roles:` entry
    — which changes who may approve a merge — reddens."""
    assert _load(_CHARTER)["policy"] == _load(_SHIPPED), (
        "charter.yaml's `policy:` section and src/assets/"
        "factory_autonomy_policy.yaml have drifted. The charter governs this "
        "repo; the asset is stamped into new ones and is the fallback for a "
        "repo declaring none. Update both."
    )
