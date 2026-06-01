"""Smoke-test the pure-regen-PR skip logic extracted as a pure function."""


def _has_non_generated_changes(changed_files: list[str]) -> bool:
    """Return True if any changed file is outside docs/arch/generated/ and .meta.json."""
    for raw in changed_files:
        f = raw.strip()
        if not f:
            continue
        if f.startswith("docs/arch/generated/") or f == "docs/arch/.meta.json":
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


def test_src_change_is_non_generated():
    files = ["src/diagram_loop.py", "docs/arch/generated/loops.md"]
    assert _has_non_generated_changes(files) is True


def test_empty_changeset_is_not_non_generated():
    assert _has_non_generated_changes([]) is False
