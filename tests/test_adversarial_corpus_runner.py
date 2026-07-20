"""Unit tests for the adversarial corpus runner (the FORMAT=json producer).

Guards the contract SkillPromptEvalLoop._run_corpus depends on: a JSON list of
{case_id, skill, status, provenance, expected_catcher} dicts.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ADV = Path(__file__).resolve().parent / "trust" / "adversarial"
if str(_ADV) not in sys.path:
    sys.path.insert(0, str(_ADV))

import corpus_runner
from corpus_runner import (  # noqa: E402
    CASES_DIR,
    MissingTranscriptError,
    evaluate_case,
    evaluate_case_for_skill,
    is_holdout,
    main,
    read_expected_catcher,
    run_corpus,
    select_live_skill_cases,
)

_LOOP_KEYS = {"case_id", "skill", "status", "provenance", "expected_catcher"}
_VALID_STATUS = {"PASS", "FAIL", "SKIPPED"}


def test_run_corpus_returns_loop_schema() -> None:
    """Every result carries exactly the keys the loop reads, with a valid status."""
    results = run_corpus(strict=False)
    assert results, "expected a non-empty committed adversarial corpus"
    for r in results:
        assert set(r) >= _LOOP_KEYS, f"missing loop keys: {_LOOP_KEYS - set(r)}"
        assert r["status"] in _VALID_STATUS
        assert r["case_id"]


def test_committed_corpus_is_all_green() -> None:
    """The committed fixtures must currently PASS (this is the loop's last-green
    baseline); a FAIL here means a skill prompt regressed."""
    failing = [r["case_id"] for r in run_corpus(strict=False) if r["status"] == "FAIL"]
    assert not failing, f"corpus cases regressed to FAIL: {failing}"


def test_evaluate_real_catcher_case() -> None:
    # Committed corpus fixture — a catcher case the diff-sanity skill must flag.
    case = CASES_DIR / "missing-import"
    assert case.is_dir(), "committed corpus case 'missing-import' is missing"
    result = evaluate_case(case, strict=False)
    assert result["expected_catcher"] == "diff-sanity"
    assert result["skill"] == "diff-sanity"
    assert result["status"] == "PASS"


def test_evaluate_real_sentinel_case() -> None:
    # Committed corpus fixture — a benign 'none' sentinel no skill may flag.
    case = CASES_DIR / "benign-rename-sentinel"
    assert case.is_dir(), "committed corpus case 'benign-rename-sentinel' is missing"
    result = evaluate_case(case, strict=False)
    assert result["expected_catcher"] == "none"
    assert result["status"] == "PASS"


def _make_case_without_transcript(tmp_path: Path) -> Path:
    case = tmp_path / "synthetic-case"
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir(parents=True)
    (case / "before" / "x.py").write_text("a = 1\n")
    (case / "after" / "x.py").write_text("a = 2\n")
    (case / "expected_catcher.txt").write_text("diff-sanity\n")
    (case / "README.md").write_text("Keyword: something\n")
    return case


def test_missing_transcript_skipped_when_not_strict(tmp_path: Path) -> None:
    case = _make_case_without_transcript(tmp_path)
    result = evaluate_case(case, live=False, strict=False)
    assert result["status"] == "SKIPPED"


def test_missing_transcript_raises_when_strict(tmp_path: Path) -> None:
    case = _make_case_without_transcript(tmp_path)
    with pytest.raises(MissingTranscriptError):
        evaluate_case(case, live=False, strict=True)


def test_json_output_carries_summary(capsys: pytest.CaptureFixture[str]) -> None:
    """The slim `--json` projection must include `summary`. The loop reads it
    as `case.get("summary","")` — the failure transcript fed to the refiner —
    so omitting it left the production refine context permanently blank (#9724
    final-review F1)."""
    rc = main(["--json"])
    assert rc == 0
    slim = json.loads(capsys.readouterr().out)
    assert slim, "expected a non-empty committed adversarial corpus"
    for r in slim:
        assert set(r) >= _LOOP_KEYS | {"summary"}, f"missing keys in {r}"
        assert isinstance(r["summary"], str)


# ---------------------------------------------------------------------------
# #10014 — per-skill live backstop, document-input threading, and the
# holdout precondition behind REFINABLE_SKILLS.
# ---------------------------------------------------------------------------


def test_every_refinable_skill_has_holdout_attack_coverage() -> None:
    """The REFINABLE_SKILLS precondition, pinned: every auto-refinable skill
    must have at least one held-out ATTACK honeypot (a holdout case whose
    expected catcher is that skill) — the overfit gate validates against 100%
    of holdouts, so a member without one would have no gate at all."""
    from prompt_refiner import REFINABLE_SKILLS

    covered = {
        read_expected_catcher(case)
        for case in corpus_runner.discover_cases(CASES_DIR)
        if is_holdout(case)
    }
    missing = set(REFINABLE_SKILLS) - covered
    assert not missing, f"refinable skills without a holdout attack case: {missing}"


def _catcher_case(tmp_path: Path, name: str, catcher: str) -> Path:
    case = tmp_path / name
    (case / "before").mkdir(parents=True)
    (case / "after").mkdir()
    (case / "before" / "x.py").write_text("a = 1\n")
    (case / "after" / "x.py").write_text("a = 2\n")
    (case / "expected_catcher.txt").write_text(f"{catcher}\n")
    (case / "README.md").write_text(f"# {name}\n\nKeyword: sentinel-kw\n")
    return case


def test_select_live_skill_cases_round_robins_across_skills(tmp_path: Path) -> None:
    """A small budget must still exercise every skill's own prompt once —
    round-robin across catchers, not a first-N slice of one skill."""
    for name, catcher in [
        ("ds-1", "diff-sanity"),
        ("ds-2", "diff-sanity"),
        ("ds-3", "diff-sanity"),
        ("pc-1", "plan-compliance"),
        ("sc-1", "scope-check"),
        ("benign-1", "none"),
    ]:
        _catcher_case(tmp_path, name, catcher)
    dirs = corpus_runner.discover_cases(tmp_path)

    assert select_live_skill_cases(dirs, 4) == {"ds-1", "pc-1", "sc-1", "ds-2"}
    # "none" sentinels never consume live budget.
    assert "benign-1" not in select_live_skill_cases(dirs, 100)
    assert select_live_skill_cases(dirs, 0) == set()


def test_evaluate_case_for_skill_replay_carries_summary_and_findings() -> None:
    """The per-skill path now feeds the loop's refine context too, so its
    results must carry `summary`/`findings` like `evaluate_case` (#10014)."""
    case = CASES_DIR / "holdout-diff-sanity-attack-debug-residue"
    result = evaluate_case_for_skill(case, "diff-sanity")
    assert result["status"] == "PASS"
    assert isinstance(result["summary"], str)
    assert result["summary"]
    assert isinstance(result["findings"], list)
    skipped = evaluate_case_for_skill(case, "test-adequacy")
    assert skipped["status"] == "SKIPPED"
    assert skipped["summary"] == ""
    assert skipped["findings"] == []


class _FakeClaudeCLI:
    """Capture the prompts `load_transcript` sends to the agent CLI and reply
    with a fixed transcript."""

    def __init__(self, transcript: str = "no structured markers here\n") -> None:
        self.prompts: list[str] = []
        self._transcript = transcript

    def __call__(self, cmd: list[str], **_kwargs: object) -> SimpleNamespace:
        self.prompts.append(cmd[2])
        return SimpleNamespace(stdout=self._transcript)


def _own_prompt_for(case: Path, skill_name: str) -> str:
    """The prompt the target skill's OWN builder produces for *case* —
    computed independently of the runner's internals."""
    skill = next(s for s in corpus_runner.BUILTIN_SKILLS if s.name == skill_name)
    return skill.prompt_builder(
        issue_number=0,
        issue_title=f"adversarial-corpus::{case.name}",
        diff=corpus_runner.synthesize_diff(case / "before", case / "after"),
        plan_text=corpus_runner.load_plan_text(case),
        **corpus_runner.load_skill_input_texts(case, skill_name),
    )


_HOLDOUT_TRIO = {
    "holdout-plan-compliance-attack-missing-planned-test": "plan-compliance",
    "holdout-discover-completeness-attack-shallow-known-unknowns": (
        "discover-completeness"
    ),
    "holdout-shape-coherence-attack-single-option": "shape-coherence",
}


def test_run_corpus_live_builds_each_skills_own_prompt(monkeypatch) -> None:
    """#10014 item 2: a live run must exercise each catcher skill's OWN prompt
    (fixtures bypassed under budget), not BUILTIN_SKILLS[0]'s. The threaded
    document inputs (brief/proposal) make the discover/shape prompts non-empty
    — without them the builders return "" and the CLI would be invoked on
    nothing."""
    fake = _FakeClaudeCLI()
    monkeypatch.setattr(corpus_runner.subprocess, "run", fake)

    results = run_corpus(
        live=True, case_ids=frozenset(_HOLDOUT_TRIO), live_budget=len(_HOLDOUT_TRIO)
    )

    expected_prompts = {
        _own_prompt_for(CASES_DIR / name, skill)
        for name, skill in _HOLDOUT_TRIO.items()
    }
    assert set(fake.prompts) == expected_prompts
    assert all(p.strip() for p in fake.prompts)
    # The garbage transcript parses as no-marker (fail-open pass) — an attack
    # case whose catcher no longer flags it is exactly a live FAIL signal.
    assert {r["status"] for r in results} == {"FAIL"}


def test_run_corpus_live_budget_zero_replays_fixtures(monkeypatch) -> None:
    """Budget 0 disables the per-skill live path: no CLI spawn, fixtures
    replay, committed cases stay green."""
    fake = _FakeClaudeCLI()
    monkeypatch.setattr(corpus_runner.subprocess, "run", fake)

    results = run_corpus(live=True, case_ids=frozenset(_HOLDOUT_TRIO), live_budget=0)

    assert fake.prompts == []
    assert {r["status"] for r in results} == {"PASS"}


def test_force_live_empty_prompt_falls_back_to_fixture(
    tmp_path: Path, monkeypatch
) -> None:
    """A document-judging case whose input file is absent renders an empty
    prompt (the skills' "no input data" signal) — force_live must fall back to
    fixture replay rather than invoke the CLI on ""."""
    import shutil

    src = CASES_DIR / "holdout-discover-completeness-attack-shallow-known-unknowns"
    case = tmp_path / src.name
    shutil.copytree(src, case)
    (case / "after" / "brief.md").unlink()

    fake = _FakeClaudeCLI()
    monkeypatch.setattr(corpus_runner.subprocess, "run", fake)

    result = evaluate_case_for_skill(
        case, "discover-completeness", live=True, force_live=True
    )

    assert fake.prompts == []
    assert result["status"] == "PASS"  # replayed the canned transcript
