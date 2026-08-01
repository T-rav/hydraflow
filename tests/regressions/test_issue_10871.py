"""Regression: ``prompt_fitness._load_audit_module`` was module-private but
imported across the module boundary by test/consumer code (#10871).

A leading underscore signals module-private intent (documented anti-pattern,
``docs/wiki/gotchas.md``), yet the loader's signature was effectively public
because outside code already depended on it. Fix: ``prompt_fitness`` now
exposes a public ``load_audit_module()``; ``_load_audit_module()`` becomes a
thin backward-compatible delegate, and every in-module call site was migrated
to the public name.

The guard below is deliberately broader than "no ``ImportFrom`` of the
private name": an earlier version of this guard only matched
``from prompt_fitness import _load_audit_module`` and would have missed a
consumer that does ``import prompt_fitness`` then calls
``prompt_fitness._load_audit_module()`` (attribute access, not an import
binding). Both forms couple a caller to the private symbol, so both are
detected.
"""

from __future__ import annotations

import ast
from pathlib import Path

import prompt_fitness
from prompt_fitness import _load_audit_module, load_audit_module

ROOT = Path(__file__).resolve().parents[2]
_OWNER_MODULE = "prompt_fitness"
_OWNER_PATH = ROOT / "src" / "prompt_fitness.py"
_THIS_FILE = Path(__file__).resolve()
_SCAN_DIRS = (ROOT / "src", ROOT / "tests", ROOT / "scripts")


def test_load_audit_module_is_public_and_returns_the_audit_module() -> None:
    audit = load_audit_module()
    assert hasattr(audit, "PROMPT_REGISTRY")
    assert hasattr(audit, "render_target")
    assert hasattr(audit, "score")


def test_load_audit_module_execs_fresh_on_every_call() -> None:
    """Pins the contract documented on load_audit_module() itself: it re-execs
    scripts/audit_prompts.py on every call rather than caching it, so two
    calls never return the same object. A future caching/memoizing "cleanup"
    of the now-public loader would silently break this."""
    assert load_audit_module() is not load_audit_module()


def test_private_delegate_returns_whatever_the_public_function_returns(
    monkeypatch,
) -> None:
    """Proves delegation, not a parallel implementation: patching the public
    function must change what the private alias returns."""
    sentinel = object()
    monkeypatch.setattr(prompt_fitness, "load_audit_module", lambda: sentinel)
    assert prompt_fitness._load_audit_module() is sentinel


def test_private_delegate_still_importable_for_backward_compat() -> None:
    """The private name stays importable (existing callers not yet migrated
    keep working) and still returns a usable audit module. Not an identity
    check: load_audit_module() deliberately re-execs scripts/audit_prompts.py
    fresh on every call, so two calls never return the same object."""
    audit = _load_audit_module()
    assert hasattr(audit, "PROMPT_REGISTRY")


# ---------------------------------------------------------------------------
# In-module callers migrated: no call site inside prompt_fitness.py itself
# (other than the delegate's own body) may still call the private name.
# ---------------------------------------------------------------------------


def test_in_module_callers_use_the_public_loader() -> None:
    source = _OWNER_PATH.read_text()
    tree = ast.parse(source, filename=str(_OWNER_PATH))

    # Walk excluding the delegate function body directly, since ast.walk has
    # no parent pointers: collect the delegate's own node range and drop any
    # call whose line falls inside it.
    delegate_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_load_audit_module":
            end = node.end_lineno or node.lineno
            delegate_lines = set(range(node.lineno, end + 1))

    offenders = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_load_audit_module"
        and node.lineno not in delegate_lines
    ]
    assert not offenders, (
        "prompt_fitness.py still calls the private _load_audit_module() "
        f"outside its own delegate body, at line(s): {offenders} — migrate "
        "these call sites to load_audit_module()."
    )


# ---------------------------------------------------------------------------
# Cross-module anti-pattern guard: nothing outside prompt_fitness.py may
# reference the private loader, whether by importing it or by attribute
# access on the imported module.
# ---------------------------------------------------------------------------


def _references_private_load_audit_module(
    tree: ast.AST,
) -> list[ast.ImportFrom | ast.Attribute]:
    """``ast`` nodes that reference ``prompt_fitness._load_audit_module``
    from outside the module — both binding forms:

    * ``from prompt_fitness import _load_audit_module`` (``ImportFrom``) —
      matched only when the module is ``prompt_fitness``.
    * ``<anything>._load_audit_module`` (``Attribute`` access, e.g. after
      ``import prompt_fitness`` or ``import prompt_fitness as pf``) —
      matched on attribute name alone, not scoped to a ``prompt_fitness``-
      derived base. Resolving an arbitrary alias back to its origin module
      would need name-binding analysis this walk doesn't do; matching by
      name is deliberately broader so an alias can't slip past, at the cost
      of also flagging an unrelated object that happens to expose an
      attribute of the same name. Fails safe: only false positives, no
      false negatives.
    """
    offenders: list[ast.ImportFrom | ast.Attribute] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            is_owner_module = module == _OWNER_MODULE or module.endswith(
                f".{_OWNER_MODULE}"
            )
            if is_owner_module and any(
                alias.name == "_load_audit_module" for alias in node.names
            ):
                offenders.append(node)
        elif isinstance(node, ast.Attribute) and node.attr == "_load_audit_module":
            offenders.append(node)
    return offenders


def test_detector_flags_import_from_of_the_private_symbol() -> None:
    tree = ast.parse("from prompt_fitness import _load_audit_module\n")
    assert len(_references_private_load_audit_module(tree)) == 1


def test_detector_flags_attribute_access_to_the_private_symbol() -> None:
    tree = ast.parse("import prompt_fitness\nprompt_fitness._load_audit_module()\n")
    assert len(_references_private_load_audit_module(tree)) == 1


def test_detector_ignores_the_public_loader() -> None:
    tree = ast.parse(
        "from prompt_fitness import load_audit_module\n"
        "import prompt_fitness\n"
        "prompt_fitness.load_audit_module()\n"
    )
    assert _references_private_load_audit_module(tree) == []


def test_no_cross_module_reference_to_the_private_loader_exists_in_the_repo() -> None:
    offenders: list[str] = []
    for scan_dir in _SCAN_DIRS:
        for path in sorted(scan_dir.rglob("*.py")):
            resolved = path.resolve()
            # This file itself deliberately imports and calls the private
            # delegate above to prove backward compat — that is the one
            # sanctioned exception, not a violation of the anti-pattern.
            if resolved in (_OWNER_PATH.resolve(), _THIS_FILE):
                continue
            try:
                tree = ast.parse(path.read_text(errors="replace"), filename=str(path))
            except SyntaxError:  # pragma: no cover - repo sources must parse
                continue
            for node in _references_private_load_audit_module(tree):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")

    assert not offenders, (
        "Cross-module reference(s) to the private prompt_fitness._load_audit_module "
        f"found outside src/prompt_fitness.py: {offenders} — use the public "
        "prompt_fitness.load_audit_module() instead."
    )
