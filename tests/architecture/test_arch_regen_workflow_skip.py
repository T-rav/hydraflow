"""Smoke-test the pure-regen-PR skip logic extracted as a pure function."""

# Mirrors the grep exclusions in .github/workflows/arch-regen.yml
# ("Skip drift check for pure-regen PRs"). The traceability ratchet
# baseline is auto-synced from the regenerated matrix on every regen
# (sync_traceability_baseline), so it legitimately rides along in
# DiagramLoop regen PRs.
_GENERATED_EXACT = {
    "docs/arch/.meta.json",
    "disturbance/baselines/traceability.yaml",
}


def _has_non_generated_changes(changed_files: list[str]) -> bool:
    """Return True if any changed file is outside the auto-regen set."""
    for raw in changed_files:
        f = raw.strip()
        if not f:
            continue
        if f.startswith("docs/arch/generated/") or f in _GENERATED_EXACT:
            continue
        return True
    return False


def test_pure_regen_pr_has_no_non_generated_changes():
    files = [
        "docs/arch/generated/loops.md",
        "docs/arch/generated/ports.md",
        "docs/arch/.meta.json",
    ]
    assert _has_non_generated_changes(files) is False


def test_synced_traceability_baseline_stays_pure_regen():
    files = [
        "docs/arch/generated/traceability_matrix.md",
        "docs/arch/.meta.json",
        "disturbance/baselines/traceability.yaml",
    ]
    assert _has_non_generated_changes(files) is False


def test_src_change_is_non_generated():
    files = ["src/diagram_loop.py", "docs/arch/generated/loops.md"]
    assert _has_non_generated_changes(files) is True


def test_empty_changeset_is_not_non_generated():
    assert _has_non_generated_changes([]) is False
