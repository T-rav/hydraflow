"""Regression: a new LLM/subprocess spawn path without a sandbox seam is red.

The s51/s56/s57 wedge class (#10012): runners=fake_llm covers only the four
original phase runners, so each NEW loop path that shelled out to a real
``claude``/``make`` wedged the air-gapped sandbox at scenario time — s51
(#9919 DiscoverRunner/ShapeRunner), s56 (SkillPromptEvalLoop refine path,
seams hand-added in #10006), s57 (IssueRefinementLoop). This pins the guard
mechanics on a synthetic tree: the scanner must SEE a new spawn call site in
loop/runner scope, the ratchet must flag it when neither SANDBOX_SEAMS nor
the grandfathered baseline covers it, and a stale baseline entry must demand
pruning. If any of these regress, the completeness guard in
tests/architecture/test_sandbox_seam_completeness.py goes vacuously green
and the next wedge ships silently again.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from tests.architecture.sandbox_seam_scan import (
    ratchet_diff,
    scan_runner_constructions,
    scan_spawn_signatures,
    subprocess_runner_subclasses,
    undeclared_signatures,
)

_NEW_LOOP = """
    class SkillEvalV2Loop:
        async def _refine(self, prompt: str) -> str:
            return await run_lightweight_agent(prompt)

        async def _run_corpus(self) -> None:
            await asyncio.create_subprocess_exec("make", "trust-adversarial")
    """

_NEW_RUNNER = """
    class ProbeRunner:
        async def run(self, prompt: str) -> str:
            return await stream_claude_process(cmd=["claude", "-p"], prompt=prompt)
    """

_OUT_OF_SCOPE = """
    def helper() -> None:
        run_subprocess(["gh", "pr", "view"])
    """


def _write_tree(root: Path) -> None:
    spec = {
        "src/skill_eval_v2_loop.py": _NEW_LOOP,
        "src/runners/probe_runner.py": _NEW_RUNNER,
        # Not *_loop.py / *_runner.py / runners/** — must stay out of scope.
        "src/helpers.py": _OUT_OF_SCOPE,
    }
    for rel, body in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(body).lstrip("\n"))


def test_scanner_sees_new_spawn_paths_in_loop_and_runner_scope(
    tmp_path: Path,
) -> None:
    _write_tree(tmp_path)
    current = scan_spawn_signatures(tmp_path)
    assert current == {
        "src/skill_eval_v2_loop.py::SkillEvalV2Loop._refine::run_lightweight_agent": 1,
        (
            "src/skill_eval_v2_loop.py::SkillEvalV2Loop._run_corpus"
            "::create_subprocess_exec"
        ): 1,
        "src/runners/probe_runner.py::ProbeRunner.run::stream_claude_process": 1,
    }


def test_new_undeclared_spawn_path_reddens_the_ratchet(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    current = scan_spawn_signatures(tmp_path)
    # The runner module declares a seam; the new loop declares nothing and is
    # not grandfathered — exactly the next-s51 shape the guard must catch.
    undeclared = undeclared_signatures(current, {"probe_runner": "seed_seam"})
    new, resolved = ratchet_diff(undeclared, {})
    assert set(new) == {
        "src/skill_eval_v2_loop.py::SkillEvalV2Loop._refine::run_lightweight_agent",
        (
            "src/skill_eval_v2_loop.py::SkillEvalV2Loop._run_corpus"
            "::create_subprocess_exec"
        ),
    }
    assert not resolved


def test_declared_and_grandfathered_paths_stay_green(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    current = scan_spawn_signatures(tmp_path)
    undeclared = undeclared_signatures(current, {"probe_runner": "seed_seam"})
    baseline = {
        "src/skill_eval_v2_loop.py::SkillEvalV2Loop._refine::run_lightweight_agent": 1,
        (
            "src/skill_eval_v2_loop.py::SkillEvalV2Loop._run_corpus"
            "::create_subprocess_exec"
        ): 1,
    }
    new, resolved = ratchet_diff(undeclared, baseline)
    assert not new
    assert not resolved


def test_covered_spawn_path_demands_baseline_prune(tmp_path: Path) -> None:
    """The ratchet only shrinks.

    Once a grandfathered path gains a seam declaration (or the spawn is
    removed), its baseline entry becomes stale; leaving it would let the
    module silently re-grow a spawn later. The diff must demand the prune.
    """
    _write_tree(tmp_path)
    current = scan_spawn_signatures(tmp_path)
    undeclared = undeclared_signatures(
        current,
        {"probe_runner": "seed_seam", "skill_eval_v2_loop": "seed_seam"},
    )
    stale_baseline = {
        "src/skill_eval_v2_loop.py::SkillEvalV2Loop._refine::run_lightweight_agent": 1,
    }
    new, resolved = ratchet_diff(undeclared, stale_baseline)
    assert not new
    assert resolved == {
        "src/skill_eval_v2_loop.py::SkillEvalV2Loop._refine::run_lightweight_agent": 1,
    }


def test_second_spawn_call_in_grandfathered_function_reddens(
    tmp_path: Path,
) -> None:
    """Counts are load-bearing: baselines pin call-site multiplicity.

    A grandfathered module adding ANOTHER spawn call to the same function
    would be invisible to a set-based baseline; the count comparison must
    flag the excess.
    """
    _write_tree(tmp_path)
    loop_path = tmp_path / "src/skill_eval_v2_loop.py"
    body = loop_path.read_text() + (
        "\n"
        "    async def _refine_twice(self, prompt: str) -> str:\n"
        "        await run_lightweight_agent(prompt)\n"
        "        return await run_lightweight_agent(prompt)\n"
    )
    loop_path.write_text(body)
    current = scan_spawn_signatures(tmp_path)
    signature = (
        "src/skill_eval_v2_loop.py::SkillEvalV2Loop._refine_twice"
        "::run_lightweight_agent"
    )
    assert current[signature] == 2
    new, _resolved = ratchet_diff({signature: current[signature]}, {signature: 1})
    assert new == {signature: 1}


# ---------------------------------------------------------------------------
# BaseSubprocessRunner construction sites (#11602) — the spawn-primitive scan
# above structurally cannot see these: the only lexical spawn is inside
# ``runners/base_subprocess_runner.py``, so the CONSTRUCTING module produces no
# spawn signature at all. Three composition-root runners rode that blind spot.
# ---------------------------------------------------------------------------

_RUNNER_DEFS = """
    class FixerRunner(BaseSubprocessRunner[Spawn]):
        def _telemetry_source(self) -> str:
            return "fixer"


    class SpecialFixerRunner(FixerRunner):
        def _telemetry_source(self) -> str:
            return "special_fixer"
    """

_COMPOSITION_ROOT = """
    from runners.fixer_runner import FixerRunner
    from runners.fixer_runner import SpecialFixerRunner as SFR


    def build_services(config, bus):
        return (
            FixerRunner(config=config, event_bus=bus),
            FixerRunner(config=config, event_bus=bus),
            SFR(config=config, event_bus=bus),
        )
    """


def _write_runner_tree(root: Path) -> None:
    spec = {
        "src/runners/base_subprocess_runner.py": (
            "\n    class BaseSubprocessRunner:\n        pass\n"
        ),
        "src/runners/fixer_runner.py": _RUNNER_DEFS,
        "src/service_registry.py": _COMPOSITION_ROOT,
    }
    for rel, body in spec.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(body).lstrip("\n"))


def test_construction_scan_counts_composition_root_sites(tmp_path: Path) -> None:
    """Two runners built in one function are one signature with count 2."""
    _write_runner_tree(tmp_path)

    current = scan_runner_constructions(tmp_path)

    assert current["src/service_registry.py::build_services::FixerRunner"] == 2


def test_construction_scan_follows_subclass_of_subclass(tmp_path: Path) -> None:
    """A second-generation subclass spawns through the same base ``run``."""
    _write_runner_tree(tmp_path)

    assert "SpecialFixerRunner" in subprocess_runner_subclasses(tmp_path)


def test_construction_scan_resolves_import_aliases(tmp_path: Path) -> None:
    """Renaming at the import site must not dodge the ratchet."""
    _write_runner_tree(tmp_path)

    current = scan_runner_constructions(tmp_path)

    assert "src/service_registry.py::build_services::SpecialFixerRunner" in current
