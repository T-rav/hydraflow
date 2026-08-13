"""Tests for the greenfield kernel writer (issue #10935)."""

from __future__ import annotations

import pytest

from onboarding.kernel_lock import (
    BUILDING_CODE_VERSION,
    FileFreshness,
    compare,
    load_lock,
)
from onboarding.kernel_writer import (
    STANDARDS_DIRS,
    WIKI_TOPICS,
    KernelSpec,
    KernelWriterError,
    Ownership,
    prescription,
    spec_from_lock,
    stamp_kernel,
)


def _spec(**overrides: object) -> KernelSpec:
    payload: dict[str, object] = {
        "name": "game1",
        "package_name": "game1",
        "description": "A small deterministic game engine for HydraFlow onboarding.",
        "coverage_floor": 85,
        "safety_guards": ("decimal-purity",),
    }
    payload.update(overrides)
    return KernelSpec(**payload)  # type: ignore[arg-type]


def test_stamps_the_enumerated_invariant_kernel(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    paths = result.paths()
    # Code skeleton
    assert "src/game1/__init__.py" in paths
    assert "src/game1/cli.py" in paths
    assert "tests/unit/test_smoke.py" in paths
    # Config
    assert "pyproject.toml" in paths
    assert ".gitignore" in paths
    assert ".env.example" in paths
    assert "Makefile" in paths
    assert ".github/workflows/quality.yml" in paths
    # Docs
    assert "CLAUDE.md" in paths
    assert "AGENTS.md" in paths
    assert "README.md" in paths
    assert "docs/adr/README.md" in paths
    assert "docs/adr/0001-initial-architecture.md" in paths
    assert "docs/wiki/index.md" in paths
    # Issue/PR templates
    assert ".github/ISSUE_TEMPLATE/bug.md" in paths
    assert ".github/ISSUE_TEMPLATE/feature.md" in paths
    assert ".github/PULL_REQUEST_TEMPLATE.md" in paths
    # Scripts
    assert "scripts/__init__.py" in paths
    assert "scripts/prep.py" in paths
    assert "scripts/setup_branch_protection.py" in paths


def test_stamps_the_five_repowikiloop_topic_pages(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    assert WIKI_TOPICS == (
        "architecture",
        "patterns",
        "gotchas",
        "testing",
        "dependencies",
    )
    for topic in WIKI_TOPICS:
        rel = f"docs/wiki/{topic}.md"
        assert rel in result.paths()
        assert (result.root / rel).is_file()


def test_copies_all_six_standards_directories_from_hydraflow(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    for standard in STANDARDS_DIRS:
        readme = result.root / "docs" / "standards" / standard / "README.md"
        assert readme.is_file(), f"missing standards copy: {standard}"
    # Verified against HydraFlow's own six standards dirs.
    assert len(STANDARDS_DIRS) == 6


def test_pyproject_and_cli_carry_package_substitution(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    pyproject = (result.root / "pyproject.toml").read_text()
    assert 'name = "game1"' in pyproject
    assert 'game1 = "game1.cli:main"' in pyproject
    assert 'venvPath = "."' in pyproject
    assert 'pythonpath = ["src"]' in pyproject

    cli = (result.root / "src/game1/cli.py").read_text()
    assert 'print("game1 ready")' in cli

    smoke = (result.root / "tests/unit/test_smoke.py").read_text()
    assert "from game1.cli import main" in smoke


def test_makefile_reuses_scaffolder_and_applies_coverage_floor(tmp_path) -> None:
    result = stamp_kernel(_spec(coverage_floor=90), tmp_path / "game1")

    makefile = (result.root / "Makefile").read_text()
    # Reused scaffolder structure.
    assert "quality: quality-lite test coverage-check" in makefile
    assert ".DEFAULT_GOAL := help" in makefile
    # Coverage floor parameterized.
    assert "COVERAGE_TARGET ?= 90" in makefile
    assert "COVERAGE_MIN ?= 90" in makefile
    # Green-day-one: test emits a coverage artifact coverage-check can read.
    assert "--cov=src --cov-report=xml" in makefile
    # decimal-purity guard wired in.
    assert "decimal-purity:" in makefile


def test_cli_entry_override_is_honored(tmp_path) -> None:
    result = stamp_kernel(_spec(cli_entry="play-game"), tmp_path / "game1")
    pyproject = (result.root / "pyproject.toml").read_text()
    assert 'play-game = "game1.cli:main"' in pyproject


def test_claude_md_marks_template_owned_and_product_owned_sections(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    claude = (result.root / "CLAUDE.md").read_text()
    assert "TEMPLATE-OWNED" in claude
    assert "END TEMPLATE-OWNED" in claude
    assert "PRODUCT-OWNED" in claude
    # Domain guard surfaces in the product-owned block.
    assert "decimal-purity" in claude


def test_workflow_reuses_ci_scaffolder(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    workflow = (result.root / ".github/workflows/quality.yml").read_text()
    assert "prep-managed: quality-workflow" in workflow
    assert "make quality" in workflow


def test_residual_manual_steps_are_printed_not_automated(tmp_path) -> None:
    result = stamp_kernel(_spec(), tmp_path / "game1")

    joined = "\n".join(result.residual_steps)
    assert "gh repo create game1" in joined
    assert "setup_branch_protection.py --apply" in joined
    assert "make setup" in joined
    assert "make audit" in joined
    assert "staging" in joined


def test_restamp_is_idempotent_and_never_clobbers_product_files(tmp_path) -> None:
    target = tmp_path / "game1"
    first = stamp_kernel(_spec(), target)
    assert first.written
    assert not first.skipped

    # Operator edits a product-owned file.
    claude = target / "CLAUDE.md"
    claude.write_text("# my hand-edited product rules\n")

    second = stamp_kernel(_spec(), target)
    # Nothing re-written by default; product file preserved byte-for-byte.
    assert second.written == []
    assert claude.read_text() == "# my hand-edited product rules\n"
    # Every planned file reported as protected/skipped.
    assert {f.action for f in second.files} <= {"protected", "skipped"}


def test_force_restamps_template_files_but_protects_product_files(tmp_path) -> None:
    target = tmp_path / "game1"
    stamp_kernel(_spec(), target)

    gitignore = target / ".gitignore"  # TEMPLATE-owned
    claude = target / "CLAUDE.md"  # PRODUCT-owned
    gitignore.write_text("garbage\n")
    claude.write_text("# product\n")

    result = stamp_kernel(_spec(), target, force=True)

    # Template file rewritten back to the canonical kernel content.
    assert gitignore.read_text() != "garbage\n"
    assert ".venv/" in gitignore.read_text()
    # Product file still protected, even under force.
    assert claude.read_text() == "# product\n"
    actions = {f.path: f.action for f in result.files}
    assert actions[".gitignore"] == "rewritten"
    assert actions["CLAUDE.md"] == "protected"


def test_invalid_package_name_raises(tmp_path) -> None:
    with pytest.raises(KernelWriterError, match="valid Python identifier"):
        stamp_kernel(_spec(package_name="1bad-name!"), tmp_path / "game1")


def test_ownership_enum_tags_are_stable() -> None:
    assert Ownership.TEMPLATE.value == "template"
    assert Ownership.PRODUCT.value == "product"


def test_agents_console_layer_absent_by_default(tmp_path) -> None:
    # Chartering review chambers is a project choice, not kernel plumbing
    # (#10949): the default stamp writes no agents/ files.
    result = stamp_kernel(_spec(), tmp_path / "repo")
    assert not any(path.startswith("agents/") for path in result.paths())
    assert not (tmp_path / "repo" / "agents").exists()


def test_agents_console_layer_stamps_the_four_skeleton_readmes(tmp_path) -> None:
    result = stamp_kernel(_spec(agents_console=True), tmp_path / "repo")
    expected = {
        "agents/README.md",
        "agents/personas/README.md",
        "agents/console/README.md",
        "agents/console/decisions/README.md",
    }
    assert expected <= result.paths()
    personas = (tmp_path / "repo" / "agents" / "personas" / "README.md").read_text()
    # Vote-counting honesty is mandatory wherever panels are described.
    assert "1.x effective votes" in personas
    console = (tmp_path / "repo" / "agents" / "console" / "README.md").read_text()
    assert "never averaged" in console
    decisions = (
        tmp_path / "repo" / "agents" / "console" / "decisions" / "README.md"
    ).read_text()
    assert "no verdict" in decisions
    # The skeleton points at the methodology doc, not a copy of it.
    root_readme = (tmp_path / "repo" / "agents" / "README.md").read_text()
    assert "consoles-of-personas.md" in root_readme


def test_agents_console_skeleton_is_template_owned_and_restampable(tmp_path) -> None:
    target = tmp_path / "repo"
    stamp_kernel(_spec(agents_console=True), target)
    marker = target / "agents" / "personas" / "README.md"
    marker.write_text("locally edited\n")
    # Plain re-stamp never clobbers; force re-stamps TEMPLATE-owned skeletons.
    stamp_kernel(_spec(agents_console=True), target)
    assert marker.read_text() == "locally edited\n"
    stamp_kernel(_spec(agents_console=True), target, force=True)
    assert "Persona contracts" in marker.read_text()


def test_stamp_writes_committed_kernel_lock(tmp_path) -> None:
    # #11060 slice 1: the lock is the child's committed provenance record —
    # repo ROOT, not .hydraflow/ (which children gitignore).
    result = stamp_kernel(_spec(), tmp_path / "repo")
    lock_path = tmp_path / "repo" / "hydraflow-kernel.lock"
    assert lock_path.is_file()
    assert "hydraflow-kernel.lock" in result.paths()
    lock = load_lock(tmp_path / "repo")
    assert lock is not None
    assert lock["building_code_version"] == BUILDING_CODE_VERSION
    # The spec round-trips, so staleness can recompute the prescription.
    spec = spec_from_lock(lock)
    assert spec.pkg == _spec().pkg
    assert spec.coverage_floor == _spec().coverage_floor
    # Every planned file is hashed.
    files = lock["files"]
    assert "Makefile" in files and "sha256" in files["Makefile"]


def test_fresh_stamp_reports_fully_current(tmp_path) -> None:
    stamp_kernel(_spec(), tmp_path / "repo")
    lock = load_lock(tmp_path / "repo")
    assert lock is not None
    report = compare(
        lock,
        current_plan=prescription(spec_from_lock(lock)),
        child_root=tmp_path / "repo",
    )
    assert not report.version_stale
    assert report.stale_files == []
    assert report.modified_files == []
    assert all(state is FileFreshness.CURRENT for state in report.files.values())


def test_local_edit_reports_locally_modified(tmp_path) -> None:
    stamp_kernel(_spec(), tmp_path / "repo")
    (tmp_path / "repo" / "Makefile").write_text("# vandalized\n")
    lock = load_lock(tmp_path / "repo")
    assert lock is not None
    report = compare(
        lock,
        current_plan=prescription(spec_from_lock(lock)),
        child_root=tmp_path / "repo",
    )
    assert "Makefile" in report.modified_files


def test_deleted_file_reports_missing(tmp_path) -> None:
    stamp_kernel(_spec(), tmp_path / "repo")
    (tmp_path / "repo" / "Makefile").unlink()
    lock = load_lock(tmp_path / "repo")
    assert lock is not None
    report = compare(
        lock,
        current_plan=prescription(spec_from_lock(lock)),
        child_root=tmp_path / "repo",
    )
    assert report.files["Makefile"] is FileFreshness.MISSING


def test_kernel_update_beats_local_modification(tmp_path) -> None:
    # Simulate the building code moving on: the locked hash no longer matches
    # the CURRENT prescription. Even if the child also edited the file, the
    # verdict is KERNEL_UPDATED — the update path owns that merge conversation.
    stamp_kernel(_spec(), tmp_path / "repo")
    lock = load_lock(tmp_path / "repo")
    assert lock is not None
    lock["files"]["Makefile"]["sha256"] = "0" * 64  # pretend an old prescription
    (tmp_path / "repo" / "Makefile").write_text("# also locally edited\n")
    report = compare(
        lock,
        current_plan=prescription(spec_from_lock(lock)),
        child_root=tmp_path / "repo",
    )
    assert report.files["Makefile"] is FileFreshness.KERNEL_UPDATED
    assert "Makefile" in report.stale_files
    assert "Makefile" not in report.modified_files


def test_lock_restores_when_diverged_but_skips_when_identical(tmp_path) -> None:
    # A vandalized/diverged lock self-heals on re-stamp (no force needed);
    # a byte-identical re-stamp writes nothing (idempotency contract holds).
    stamp_kernel(_spec(), tmp_path / "repo")
    lock_path = tmp_path / "repo" / "hydraflow-kernel.lock"
    lock_path.write_text("{}\n")
    result = stamp_kernel(_spec(), tmp_path / "repo")  # no force
    actions = {f.path: f.action for f in result.files}
    assert actions["hydraflow-kernel.lock"] == "rewritten"
    third = stamp_kernel(_spec(), tmp_path / "repo")
    assert {f.action for f in third.files} <= {"protected", "skipped"}
    assert load_lock(tmp_path / "repo") is not None
    assert load_lock(tmp_path / "repo") != {}
