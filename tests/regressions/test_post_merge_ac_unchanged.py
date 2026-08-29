"""Regression: post-merge AC + verification_judge stay isolated from the adversarial branch.

Spec contract for the earlier-adversarial pipeline: the new pre-impl
SpecACGenerator + SpecJudge are *siblings* of the existing post-merge
``acceptance_criteria`` + ``verification_judge`` pipeline, not a
replacement. This regression locks that contract:

  * Post-merge modules must not depend on the new adversarial agents.
  * Their public surface (the classes/functions the rest of the
    codebase imports) must stay intact.

A future refactor that conflates pre-impl Judge work with post-merge
verification will trip these checks.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

#: ``discovery_ensemble``, ``shape_ensemble`` and ``complexity_gate`` were removed
#: on 2026-07-21 (#9773 — Discover+Shape collapsed into Plan). They sat here
#: dead for 33 days: the five live entries kept working, so the gate was
#: DEGRADED rather than vacuous and nothing said so.
#: ``test_every_adversarial_module_still_exists`` is what makes the next
#: deletion loud (#11673).
_ADVERSARIAL_MODULE_NAMES = (
    "spec_ac_generator",
    "spec_judge",
    "plan_ensemble",
    "assumption_surfacer",
    "adversarial_retry_loop",
)
# Production code imports bare (``from spec_judge import ...``); the
# ``src.``-prefixed spelling is kept so a reintroduced alias import (it cannot
# resolve from an installed wheel, #11580) is caught here too.
_ADVERSARIAL_MODULES = {
    *_ADVERSARIAL_MODULE_NAMES,
    *(f"src.{name}" for name in _ADVERSARIAL_MODULE_NAMES),
}


def _is_adversarial_import(module: str) -> bool:
    """True when *module* is an adversarial module OR a member of its package.

    The set holds bare module names matched against AST import targets, so
    ``from spec_judge._core import X`` yields ``"spec_judge._core"`` — not
    ``in`` the set. The day one of these is decomposed, every import of its
    internals walks straight past this guard and it stays green (#11673).
    """
    return any(
        module == name or module.startswith(f"{name}.") for name in _ADVERSARIAL_MODULES
    )


def _leaked(imports: set[str]) -> set[str]:
    return {m for m in imports if _is_adversarial_import(m)}


def _module_imports(path: Path) -> set[str]:
    """Return all ``import X`` / ``from X import Y`` module targets in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                targets.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            targets.add(node.module)
    return targets


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def test_acceptance_criteria_does_not_import_adversarial() -> None:
    path = _repo_root() / "src" / "acceptance_criteria.py"
    imports = _module_imports(path)
    leaked = _leaked(imports)
    assert not leaked, (
        f"src/acceptance_criteria.py leaked adversarial-pipeline imports: "
        f"{sorted(leaked)}. Post-merge AC must stay independent of the "
        f"pre-impl SpecJudge pipeline (spec contract)."
    )


def test_verification_judge_does_not_import_adversarial() -> None:
    path = _repo_root() / "src" / "verification_judge.py"
    imports = _module_imports(path)
    leaked = _leaked(imports)
    assert not leaked, (
        f"src/verification_judge.py leaked adversarial-pipeline imports: "
        f"{sorted(leaked)}. Post-merge verification must stay independent "
        f"of the pre-impl SpecJudge pipeline (spec contract)."
    )


def test_acceptance_criteria_public_surface_intact() -> None:
    """Imports of the legacy public surface still resolve from the module."""
    import acceptance_criteria  # noqa: PLC0415

    # The post-merge AC pipeline's public entry point. Tracked here so
    # that an unintended rename (e.g. conflating with SpecACGenerator)
    # trips this regression before the rest of the codebase blows up.
    assert hasattr(acceptance_criteria, "AcceptanceCriteriaGenerator")


def test_verification_judge_public_surface_intact() -> None:
    import verification_judge  # noqa: PLC0415

    assert hasattr(verification_judge, "VerificationJudge")


def test_every_adversarial_module_still_exists() -> None:
    """A dead entry degrades this gate silently — make the next one loud."""
    src = Path(__file__).resolve().parents[2] / "src"
    missing = [
        name
        for name in _ADVERSARIAL_MODULE_NAMES
        if not (src / f"{name}.py").is_file() and not (src / name).is_dir()
    ]
    assert not missing, (
        f"adversarial modules no longer in src/: {missing}. Each dead entry "
        "silently narrows the leak check — remove it, or repoint it at the "
        "module that replaced it."
    )


def test_a_package_member_import_is_still_caught() -> None:
    """Negative control for the decomposition case this guard was blind to."""
    assert _is_adversarial_import("spec_judge._core")
    assert _is_adversarial_import("src.spec_judge._core")
    assert _is_adversarial_import("spec_judge")
    assert not _is_adversarial_import("spec_judgement")
    assert not _is_adversarial_import("acceptance_criteria")
