import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def populated_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "src").mkdir()
    (repo / "src/widget_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class WidgetLoop(BaseBackgroundLoop):\n"
        "    pass\n"
    )
    (repo / "src/mockworld/fakes").mkdir(parents=True)
    (repo / "tests/scenarios").mkdir(parents=True)
    (repo / "docs/adr").mkdir(parents=True)
    (repo / "docs/adr/0001-thing.md").write_text("# ADR-0001\n")
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "add",
            ".",
        ],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    return repo


def test_emit_writes_all_artifacts(populated_repo: Path):
    fa_path = populated_repo / "docs/arch/functional_areas.yml"
    fa_path.parent.mkdir(parents=True, exist_ok=True)
    fa_path.write_text(
        "areas:\n  orchestration:\n    label: Orchestration\n    description: x\n"
    )
    from arch.runner import emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    expected = {
        "loops.md",
        "ports.md",
        "labels.md",
        "modules.md",
        "events.md",
        "adr_xref.md",
        "mockworld.md",
        "changelog.md",
        "functional_areas.md",
        "coverage_matrix.md",
        "ubiquitous-language.md",
        "ubiquitous-language-context-map.md",
        "adr-conformance.md",
        "ai_system_inventory.md",
        "traceability_matrix.md",
    }
    assert {p.name for p in out.iterdir() if p.suffix == ".md"} == expected
    assert (out.parent / ".meta.json").exists()


def test_check_returns_zero_when_in_sync(populated_repo: Path):
    from arch.runner import check, emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    rc = check(repo_root=populated_repo, generated_dir=out)
    assert rc == 0


def test_check_returns_one_when_drifted(populated_repo: Path):
    from arch.runner import check, emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    # Add a new loop AFTER baseline emit
    (populated_repo / "src/widget2_loop.py").write_text(
        "from base_background_loop import BaseBackgroundLoop\n"
        "class Widget2Loop(BaseBackgroundLoop):\n    pass\n"
    )
    rc = check(repo_root=populated_repo, generated_dir=out)
    assert rc == 1


def test_emitted_artifact_body_has_no_sha_footer(populated_repo: Path):
    from arch.runner import emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    loops_text = (out / "loops.md").read_text()
    assert "_Regenerated from commit" not in loops_text
    assert "<!-- arch:generated -->" in loops_text


def test_strip_footer_handles_html_comment_placeholder():
    from arch.runner import _strip_footer

    body = "# Title\n\ncontent\n\n<!-- arch:generated -->\n"
    assert "<!-- arch:generated -->" not in _strip_footer(body)


def test_check_no_conflict_after_two_emits_same_repo(populated_repo: Path):
    from arch.runner import check, emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    # Second emit simulates a different branch's commit being forced in
    emit(repo_root=populated_repo, out_dir=out)
    assert check(repo_root=populated_repo, generated_dir=out) == 0


def test_drift_exempt_pins_git_log_window_artifacts():
    # Both artifacts derive from a moving `git log` window: in CI the check
    # runs from the PR *merge commit*, so any squash-merge landing on the
    # base between author regen and CI shifts the window and would fail
    # unrelated PRs. Their staleness is governed elsewhere (changelog: none
    # needed; traceability_matrix: the disturbance ratchet baseline).
    from arch.runner import _DRIFT_EXEMPT

    assert {"changelog.md", "traceability_matrix.md"} == _DRIFT_EXEMPT


def test_check_ignores_traceability_matrix_drift(populated_repo: Path):
    from arch.runner import check, emit

    out = populated_repo / "docs/arch/generated"
    emit(repo_root=populated_repo, out_dir=out)
    # Simulate the merge-commit window shift: committed matrix differs from
    # what a fresh emit at HEAD would produce.
    (out / "traceability_matrix.md").write_text(
        "# Requirements Traceability Matrix\n\n<!-- untraced-pct: 73 -->\n"
    )
    assert check(repo_root=populated_repo, generated_dir=out) == 0


def _write_traceability_baseline(repo: Path) -> Path:
    baseline = repo / "disturbance/baselines/traceability.yaml"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_text(
        "comment: c\nentries:\n"
        "  docs/arch/generated/traceability_matrix.md::untraced-pct: 100\n"
    )
    return baseline


def test_main_emit_syncs_traceability_baseline(populated_repo: Path, monkeypatch):
    # `make arch-regen` / `arch-regen-stage` route through `_main --emit`;
    # the emitted matrix and the ratchet baseline must move together or the
    # gate's `resolved` assertion fails on the next unrelated PR.
    import sys

    from arch.runner import _main
    from disturbance.baseline import load_baseline

    baseline = _write_traceability_baseline(populated_repo)
    # A real PR-squash-merge population, fully traced → recomputed pct 0.
    subprocess.run(
        [
            "git",
            "-c",
            "user.email=t@t",
            "-c",
            "user.name=t",
            "commit",
            "--allow-empty",
            "-m",
            "feat: traced work (#1)\n\nReq-ID: REQ-1",
        ],
        cwd=populated_repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(
        sys, "argv", ["arch.runner", "--emit", "--repo-root", str(populated_repo)]
    )

    assert _main() == 0
    # Fully traced population → fresh matrix reports pct 0, so the
    # grandfathered entry is pruned (from the RECOMPUTED value).
    assert load_baseline(baseline) == {}


def test_main_emit_never_prunes_baseline_from_an_empty_parse(
    populated_repo: Path, monkeypatch
):
    # populated_repo's history has NO PR-merge commits: the matrix renders
    # pct 0 from an empty population, which is the generation-regression
    # shape, not 0%-untraced success — the sync must leave the baseline
    # alone (CH-5 convergence review finding 3).
    import sys

    from arch.runner import _main
    from disturbance.baseline import load_baseline

    baseline = _write_traceability_baseline(populated_repo)
    monkeypatch.setattr(
        sys, "argv", ["arch.runner", "--emit", "--repo-root", str(populated_repo)]
    )

    assert _main() == 0
    assert load_baseline(baseline) == {
        "docs/arch/generated/traceability_matrix.md::untraced-pct": 100
    }


def test_artifact_files_covers_ubiquitous_language():
    from arch.runner import _ARTIFACT_FILES

    assert "ubiquitous-language.md" in _ARTIFACT_FILES
    assert "ubiquitous-language-context-map.md" in _ARTIFACT_FILES


def test_artifact_files_matches_compute_artifacts_keys(populated_repo: Path):
    from arch.runner import _ARTIFACT_FILES, _compute_artifacts

    fa_path = populated_repo / "docs/arch/functional_areas.yml"
    fa_path.parent.mkdir(parents=True, exist_ok=True)
    fa_path.write_text(
        "areas:\n  orchestration:\n    label: Orchestration\n    description: x\n"
    )
    computed_keys = set(_compute_artifacts(populated_repo).keys())
    assert (
        set(_ARTIFACT_FILES) == computed_keys
    )  # all emitted files must be drift-checked
