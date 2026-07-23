"""Verify the sandbox-seed tree-clean guard in tests/conftest.py fires (#10094).

Mirrors tests/test_mock_path_pollution_guard.py's pattern: uses pytest's
``pytester`` fixture to spin up an in-process pytest run against a
self-contained conftest that reproduces the mtime-snapshot hook shape (not
the real ``tests/conftest.py`` — that keeps this pinned to the guard's
*mechanics*, independent of fragile path coupling to the repo root), then
points it at synthetic tests that do/don't mutate a seed file. Must see the
guard fire only when a seed is actually rewritten.
"""

from __future__ import annotations

import pytest

pytest_plugins = ["pytester"]

_HOOK_CONFTEST = """
    from pathlib import Path
    import pytest

    _SEEDS_DIR = Path(__file__).resolve().parent / "seeds"


    def _mtimes():
        if not _SEEDS_DIR.is_dir():
            return {}
        return {p.name: p.stat().st_mtime_ns for p in _SEEDS_DIR.glob("*.json")}


    _baseline = _mtimes()


    def pytest_runtest_teardown(item, nextitem):
        current = _mtimes()
        mutated = sorted(
            name for name, mtime in current.items() if _baseline.get(name) != mtime
        )
        if mutated:
            _baseline.update({name: current[name] for name in mutated})
            pytest.fail(
                f"Sandbox-seed tree-clean violation: test {item.nodeid} "
                f"mutated committed seed(s) {mutated}."
            )
    """


def test_guard_fires_when_a_test_rewrites_a_committed_seed(
    pytester: pytest.Pytester,
) -> None:
    pytester.makeconftest(_HOOK_CONFTEST)
    seeds_dir = pytester.path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "s05_hitl_after_review_exhaustion.json").write_text('{"a": 1}')

    pytester.makepyfile(
        test_mutator="""
        from pathlib import Path

        def test_rewrites_committed_seed():
            seed_path = (
                Path(__file__).resolve().parent
                / "seeds"
                / "s05_hitl_after_review_exhaustion.json"
            )
            seed_path.write_text('{"a": 1, "comments": {}}')
        """
    )
    result = pytester.runpytest("-q")
    result.stdout.fnmatch_lines(["*Sandbox-seed tree-clean violation*"])
    assert result.ret != 0


def test_guard_quiet_when_no_seed_is_touched(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_HOOK_CONFTEST)
    seeds_dir = pytester.path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "s05_hitl_after_review_exhaustion.json").write_text('{"a": 1}')

    pytester.makepyfile(
        test_reader="""
        from pathlib import Path

        def test_only_reads_the_seed():
            seed_path = (
                Path(__file__).resolve().parent
                / "seeds"
                / "s05_hitl_after_review_exhaustion.json"
            )
            assert seed_path.read_text() == '{"a": 1}'
        """
    )
    result = pytester.runpytest("-q")
    assert result.ret == 0


def test_guard_quiet_when_test_writes_to_tmp_path_instead(
    pytester: pytest.Pytester,
) -> None:
    """The prescribed #10094 fix shape: redirect the write to tmp_path."""
    pytester.makeconftest(_HOOK_CONFTEST)
    seeds_dir = pytester.path / "seeds"
    seeds_dir.mkdir()
    (seeds_dir / "s05_hitl_after_review_exhaustion.json").write_text('{"a": 1}')

    pytester.makepyfile(
        test_isolated_writer="""
        def test_materializes_into_tmp_path_not_source(tmp_path):
            (tmp_path / "s05_hitl_after_review_exhaustion.json").write_text(
                '{"a": 1, "comments": {}}'
            )
        """
    )
    result = pytester.runpytest("-q")
    assert result.ret == 0
