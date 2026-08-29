"""Every prompt-audit anchor names a symbol that is actually there.

``scripts/audit_prompts.py`` publishes an anchor per registered prompt
builder. It used to be a hand-written ``src/<path>.py:<lineno>`` string
stored beside ``builder_qualname``, and it rotted the way every line-number
anchor in this repo has rotted:

* 26 of the 59 line anchors pointed OUTSIDE the span of the function they
  named -- ``triage_build_prompt`` said line 194 for a function living at
  315-412, the three ``agent_build_prompt_*`` targets said 135 for one at
  219-463;
* ``reviewer_precheck`` said ``src/reviewer.py``, which had become the
  PACKAGE ``src/reviewer/`` -- the module-to-package rot that has already
  blinded ten path-membership sites here (#11669).

No mutation was needed to demonstrate it. History applied it 26 times with
CI green throughout, because the only test touching the field asserted a
dataclass round-trip: it constructed a target with ``"src/triage.py:194"``
and asserted the field equalled ``"src/triage.py:194"``. That is true of any
string. Nothing else read the field except the report writer.

The anchor is now DERIVED from ``builder_qualname`` (``derive_call_site``),
which is load-bearing -- ``render_target`` resolves the builder through it --
so it cannot name one thing and point at another. This guard closes the
other half: that the file the derivation picked really does define the
symbol chain the qualname claims. The derivation asks the FILESYSTEM; this
asks the module's AST. Two objects that must agree, which is the only
arrangement in which a drift reddens.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Below this the sweep is not measuring the registry any more. The registry
#: has held 77 targets since the decomposition PRs; a floor rather than an
#: equality so adding a builder is not a test edit, and a floor rather than
#: ``> 0`` so a truncated import cannot pass as a clean sweep.
_MIN_REGISTERED_TARGETS = 70


def _registry() -> list:
    from scripts.audit_prompts import PROMPT_REGISTRY  # noqa: PLC0415

    return list(PROMPT_REGISTRY)


def _unresolved_reason(anchor: str) -> str | None:
    """Why *anchor* does not resolve, or ``None`` when it does.

    Resolution is structural: the file must exist, and each name in the
    ``::``-suffixed chain must be a class or function defined directly inside
    the previous one. A chain that runs out mid-way is a failure, never a
    skip -- an anchor nobody can follow is the defect this file is about.
    """
    file_part, separator, chain = anchor.partition("::")
    if not separator or not chain:
        return f"{anchor!r} carries no `file::symbol` chain"
    path = REPO_ROOT / file_part
    if not path.is_file():
        return f"{file_part} is not a file"
    try:
        scope: ast.AST = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:  # pragma: no cover - a broken src/ file
        return f"{file_part} does not parse: {exc}"
    for name in chain.split("."):
        for node in ast.iter_child_nodes(scope):
            if (
                isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
                and node.name == name
            ):
                scope = node
                break
        else:
            return f"{file_part} defines no {name!r} at that level"
    return None


def test_the_sweep_is_looking_at_the_real_registry() -> None:
    """Anti-vacuity: an empty or truncated registry would sweep clean."""
    targets = _registry()

    assert len(targets) >= _MIN_REGISTERED_TARGETS, (
        f"only {len(targets)} prompt targets imported; the registry is the "
        "subject of this sweep and a short one proves nothing"
    )
    nested = [t for t in targets if t.call_site.partition("::")[2].count(".") >= 1]
    assert nested, (
        "no target resolves through a class.method chain, so the deepest "
        "branch of the resolver went unexercised"
    )


def test_every_registered_call_site_resolves() -> None:
    unresolved = {
        target.name: reason
        for target in _registry()
        if (reason := _unresolved_reason(target.call_site)) is not None
    }

    assert not unresolved, (
        "prompt-audit anchors that point at nothing -- the class this "
        "registry carried on 27 of 77 entries with CI green throughout:\n"
        + "\n".join(f"  {name}: {why}" for name, why in sorted(unresolved.items()))
    )


@pytest.mark.parametrize(
    ("anchor", "fragment"),
    [
        ("src/triage.py::TriageRunner._no_such_method", "no '_no_such_method'"),
        ("src/triage.py::NoSuchClass._build_prompt_with_stats", "no 'NoSuchClass'"),
        ("src/reviewer.py::ReviewPromptMixin", "is not a file"),
        ("src/triage.py", "carries no `file::symbol` chain"),
    ],
)
def test_the_resolver_rejects_an_anchor_that_points_at_nothing(
    anchor: str, fragment: str
) -> None:
    """The known-negatives. A resolver that never refuses sweeps clean forever.

    ``src/reviewer.py`` is the real historical anchor, kept as a case because
    it is the one that survived the module-to-package rename in silence.
    """
    reason = _unresolved_reason(anchor)

    assert reason is not None and fragment in reason, reason


def test_the_resolver_accepts_the_anchor_it_is_meant_to_accept() -> None:
    """The known-positive, so the negatives above are not passing trivially."""
    assert (
        _unresolved_reason("src/triage.py::TriageRunner._build_prompt_with_stats")
        is None
    )
