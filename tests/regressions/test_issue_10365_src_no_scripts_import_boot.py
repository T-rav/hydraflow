"""Regression: #10365 — src/ must not import scripts/ at boot.

Staging post-merge smoke (s82) went red because ``src/close_verification.py``
imported ``from scripts.hydraflow_audit.false_close import ...`` at module scope.
The factory container (``Dockerfile.agent``) copies ``src`` but not ``scripts``
and runs ``PYTHONPATH=/opt/hydraflow/src:/opt/hydraflow``, so importing
``post_merge_handler`` (which imports ``close_verification``) raised
``ModuleNotFoundError: No module named 'scripts'`` and the container exited 1.

Fix: the pure false-close classifier moved to ``src/false_close.py`` and every
importer now uses ``from false_close import ...``. These pins fail loudly if the
``scripts`` dependency ever creeps back into the #10365 boot chain.

The repo-wide AST guard lives at
``tests/architecture/test_src_does_not_import_scripts.py``; this file pins the
specific modules whose boot import broke staging.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"

# The exact import chain the container executes at boot for post-merge handling.
BOOT_CHAIN = ("post_merge_handler.py", "close_verification.py", "false_close.py")


def _module_level_import_sources(path: Path) -> list[str]:
    """Textual dump of every module-top-level import statement in *path*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        ast.unparse(node)
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
    ]


def test_false_close_lives_in_src() -> None:
    """The pure classifier ships in the image (src/), not in scripts/."""
    assert (SRC / "false_close.py").is_file()
    assert not (
        REPO_ROOT / "scripts" / "hydraflow_audit" / "false_close.py"
    ).exists(), "false_close must not remain under scripts/ — src/ can't import it there"


def test_boot_chain_has_no_module_level_scripts_import() -> None:
    """None of the #10365 boot-chain modules import scripts/ at module scope."""
    offenders: list[str] = []
    for name in BOOT_CHAIN:
        path = SRC / name
        assert path.is_file(), f"expected boot-chain module {name} under src/"
        for stmt in _module_level_import_sources(path):
            if "import scripts" in stmt or stmt.startswith("from scripts"):
                offenders.append(f"src/{name}: {stmt}")
    assert not offenders, (
        "The #10365 boot chain must not import scripts/ at module scope "
        "(container ships src/ only):\n  " + "\n  ".join(offenders)
    )


def test_close_verification_imports_false_close_from_src() -> None:
    """close_verification reuses the classifier via the top-level src module."""
    source = (SRC / "close_verification.py").read_text(encoding="utf-8")
    assert "from false_close import has_skip_regression, is_false_close" in source
    assert "from scripts" not in source


def test_false_close_importable_as_top_level_module() -> None:
    """The classifier resolves as a bare top-level import (PYTHONPATH=src)."""
    from false_close import (  # noqa: PLC0415 - import under test
        has_skip_regression,
        is_false_close,
    )

    # A close with no fix delta and no Skip-Regression trailer is a false close.
    assert is_false_close(paths=["docs/notes.md"], message="Closes #1") is True
    # A tests/regressions/ delta clears it.
    assert (
        is_false_close(paths=["tests/regressions/test_x.py"], message="Closes #1")
        is False
    )
    assert has_skip_regression("Skip-Regression: infra-only change") is True
