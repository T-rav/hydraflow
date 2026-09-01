"""Every agent spawn goes through the governed resolver (#11544).

ADR-0141/ADR-0142 make the gateway resolver the routing authority for governed
workers. That claim is only worth something if nothing spawns a provider around
it — "project X always uses z.ai" is false the moment one code path reaches
Anthropic directly with an ambient credential.

**Anchored on the DISPATCH path, not on the string "claude".** A first attempt
keyed on agent-CLI literals and returned eight candidates, all of which were
noise or infrastructure: `claude -p ping` records a cassette, `claude plugin
install` manages the CLI, and the rest were provider names as data. A predicate
over literals cannot tell governed dispatch from a probe — the same
"a sweep is only as wide as its predicate" failure this repo keeps paying for.

This gauge caught that failure a second time, in my own hands: a manual
`grep 'src/*.py'` found two exec sites, and the AST walk over `rglob("*.py")`
found three — `src/runners/base_subprocess_runner.py` lives one directory down
and the glob never reached it. It is governed (resolves at 337, execs at 384),
so the count was right and the method was not. That is exactly why this is a
recursive AST scan and not a grep.

The dispatch path has exactly one shape: build a command, resolve a per-spawn
env, exec the agent. So the gauge pins the EXEC sites and requires each to be
preceded by the resolver. A new spawn site has to edit this file, and editing
it is where the question "should this be governed?" gets asked.

This is the architecture half of #11544's "gauges show zero governed
direct-provider bypass". The runtime half — counting spawns that reached a
provider with no resolved route — belongs with the ledger work.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"

#: The one function that execs a streaming agent process.
_AGENT_EXEC = "stream_claude_process"

#: The resolver every spawn must pass through. It returns the per-spawn env
#: that points the CLI at the routed backend, and for `gateway` it mints the
#: short-lived virtual key. A spawn that skips it inherits ambient credentials.
_RESOLVER = "resolve_harness_env"

#: Call sites permitted to exec an agent, each with why it is governed.
#: BY REFERENCE to the file, not a copied line number: line numbers drift and a
#: stale entry would silently stop pinning anything.
_GOVERNED_EXEC_SITES: dict[str, str] = {
    "src/base_runner.py": (
        "the main worker path — resolves env immediately before the exec and "
        "passes the enforced route into it"
    ),
    "src/runner_utils.py": (
        "the shared seam: the gate spawn and `run_lightweight_agent`, both of "
        "which resolve before spawning"
    ),
    "src/runners/base_subprocess_runner.py": (
        "the decomposed subprocess runner — resolves at 337, execs at 384, and "
        "holds the auth-retry loop around the spawn"
    ),
}


def _modules_calling(name: str) -> dict[str, list[int]]:
    """``{repo-relative path: [line numbers]}`` for every call to *name*."""
    found: dict[str, list[int]] = {}
    for path in sorted(_SRC.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text("utf-8"))
        except SyntaxError:  # pragma: no cover - unparseable source
            continue
        lines = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Name) and node.func.id == name)
                or (isinstance(node.func, ast.Attribute) and node.func.attr == name)
            )
        ]
        if lines:
            found[f"src/{path.relative_to(_SRC).as_posix()}"] = lines
    return found


def test_only_the_governed_seam_execs_an_agent() -> None:
    """A new exec site must be registered, and registering it asks the question.

    The registry is the point: it does not stop anyone adding a spawn, it makes
    them say in writing why that spawn is governed. An unregistered one is how
    "project X always uses z.ai" quietly stops being true.
    """
    callers = set(_modules_calling(_AGENT_EXEC))

    unregistered = callers - set(_GOVERNED_EXEC_SITES)
    assert not unregistered, (
        f"{sorted(unregistered)} exec an agent without being registered as a "
        "governed spawn site. Either route it through the resolver and add it "
        f"to _GOVERNED_EXEC_SITES with a reason, or do not spawn here."
    )


def test_the_registry_names_no_site_that_has_vanished() -> None:
    """A stale entry pins nothing while looking like it does.

    Same failure as an exemption for a check that no longer exists: the file
    still lists it, a reader still counts it, and it has stopped guarding.
    """
    callers = set(_modules_calling(_AGENT_EXEC))

    vanished = set(_GOVERNED_EXEC_SITES) - callers
    assert not vanished, (
        f"_GOVERNED_EXEC_SITES lists {sorted(vanished)}, which no longer exec "
        "an agent — prune them so the registry keeps meaning what it says"
    )


@pytest.mark.parametrize("module", sorted(_GOVERNED_EXEC_SITES))
def test_every_exec_site_resolves_before_it_spawns(module: str) -> None:
    """The registry says a site is governed; this checks that it is.

    Membership alone would be a spelling check — a module could be listed and
    still spawn without resolving. Parametrised per module so a regression
    names the offender rather than reporting one opaque failure.
    """
    exec_lines = _modules_calling(_AGENT_EXEC).get(module, [])
    resolver_lines = _modules_calling(_RESOLVER).get(module, [])

    assert exec_lines, f"{module} is registered but no longer execs an agent"
    assert resolver_lines, (
        f"{module} execs an agent at {exec_lines} but never calls "
        f"`{_RESOLVER}` — the spawn would inherit whatever credential the host "
        "environment happens to carry"
    )
    assert min(resolver_lines) < max(exec_lines), (
        f"{module} calls `{_RESOLVER}` only AFTER its last exec "
        f"(resolve at {resolver_lines}, exec at {exec_lines}) — an env "
        "resolved after the process starts governs nothing"
    )


def test_the_resolver_is_reached_from_somewhere() -> None:
    """Anti-vacuity for the whole file.

    If `resolve_harness_env` were renamed or deleted, every check above would
    pass by finding nothing on both sides. This fails loudly instead.
    """
    assert _modules_calling(_RESOLVER), (
        f"no module calls `{_RESOLVER}` — either it was renamed (update this "
        "gauge) or the governed seam has been removed entirely"
    )


def test_the_exec_helper_is_reached_from_somewhere() -> None:
    """The other half of the same anti-vacuity check."""
    assert _modules_calling(_AGENT_EXEC), (
        f"no module calls `{_AGENT_EXEC}` — this gauge is measuring nothing"
    )
