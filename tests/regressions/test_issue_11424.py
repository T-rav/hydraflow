"""Regression pin for #11424.

Three MockWorld catalog builders in
``tests/scenarios/catalog/loop_registrations.py`` accepted a ``ports`` dict
but never forwarded the loop's optional collaborator, leaving it permanently
``None``:

* ``_build_escape_ledger`` never forwarded ``auto_diagnoser`` — with it
  unset, ``EscapeLedgerLoop._get_auto_diagnoser`` (src/escape_ledger_loop.py)
  lazily builds a real ``EscapeAutoDiagnoser`` that does live git reads the
  moment auto-diagnose fires in a scenario.
* ``_build_skill_prompt_eval`` never forwarded ``refine_llm`` — with it
  unset, ``SkillPromptEvalLoop._refine_llm_complete``
  (src/skill_prompt_eval_loop.py) lazily builds a real ``_CLIRefineLLM``
  that spawns a real ``claude`` subprocess.
* ``_build_diagnostic`` never forwarded ``workspaces`` — with it unset,
  ``DiagnosticLoop``'s worktree create/destroy phase
  (src/diagnostic_loop.py) is silently no-opped, so no MockWorld scenario
  could ever exercise it.

This landed independently of, and was fixed by the same PR as, #11416's
identical ``wiki_compiler`` gap (see ``test_issue_11416.py``). Production
wiring for all three sites shipped via #11416/#11428, which settled on
namespaced port keys (``escape_ledger_auto_diagnoser``,
``skill_prompt_refine_llm``) rather than the bare ``auto_diagnoser``/
``refine_llm`` names to avoid colliding with similarly-named ports on other
builders; ``workspace`` (shared with ``_build_workspace_gc`` and other
worktree-consuming builders) was already namespaced. This file pins the
concrete symptom directly against the builder functions, independent of
``tests/scenarios/catalog/test_collaborator_wiring.py``'s more general
structural + behavioral guards, so this specific regression's contract
survives even if that file's coverage strategy changes.
"""

from __future__ import annotations

from pathlib import Path

from tests.scenarios.catalog.loop_registrations import (
    _build_diagnostic,
    _build_escape_ledger,
    _build_skill_prompt_eval,
)


def test_build_escape_ledger_wires_auto_diagnoser_from_ports(tmp_path: Path) -> None:
    """A sentinel seeded at ports['escape_ledger_auto_diagnoser'] must land
    on EscapeLedgerLoop._auto_diagnoser."""
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

    bg = make_bg_loop_deps(tmp_path)
    sentinel = object()
    ports: dict = {"github": None, "escape_ledger_auto_diagnoser": sentinel}

    loop = _build_escape_ledger(ports, bg.config, bg.loop_deps)

    assert loop._auto_diagnoser is sentinel, (
        "_build_escape_ledger did not forward "
        "ports['escape_ledger_auto_diagnoser'] onto "
        "EscapeLedgerLoop._auto_diagnoser — auto-diagnose would silently "
        "fall back to a real, live-git-reading EscapeAutoDiagnoser"
    )


def test_build_skill_prompt_eval_wires_refine_llm_from_ports(tmp_path: Path) -> None:
    """A sentinel seeded at ports['skill_prompt_refine_llm'] must land on
    SkillPromptEvalLoop._refine_llm."""
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

    bg = make_bg_loop_deps(tmp_path)
    sentinel = object()
    ports: dict = {"github": None, "skill_prompt_refine_llm": sentinel}

    loop = _build_skill_prompt_eval(ports, bg.config, bg.loop_deps)

    assert loop._refine_llm is sentinel, (
        "_build_skill_prompt_eval did not forward "
        "ports['skill_prompt_refine_llm'] onto "
        "SkillPromptEvalLoop._refine_llm — refinement would silently fall "
        "back to a real _CLIRefineLLM spawning a claude subprocess"
    )


def test_build_diagnostic_wires_workspaces_from_ports(tmp_path: Path) -> None:
    """A sentinel seeded at ports['workspace'] must land on
    DiagnosticLoop._workspaces."""
    from tests.helpers import make_bg_loop_deps  # noqa: PLC0415

    bg = make_bg_loop_deps(tmp_path)
    sentinel = object()
    ports: dict = {"github": None, "workspace": sentinel}

    loop = _build_diagnostic(ports, bg.config, bg.loop_deps)

    assert loop._workspaces is sentinel, (
        "_build_diagnostic did not forward ports['workspace'] onto "
        "DiagnosticLoop._workspaces — the worktree create/destroy phase "
        "stays unreachable in every MockWorld scenario"
    )
