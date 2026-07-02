from adr_conformance import MUTATING_MAKE_TARGETS, is_mutating, resolve_check
from adr_index import Check


def test_pytest_check_resolves_by_ast(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_alpha():\n    assert True\n")
    assert resolve_check(
        Check("pytest", "tests/t.py::test_alpha", "pytest:tests/t.py::test_alpha"),
        tmp_path,
    )
    assert not resolve_check(Check("pytest", "tests/t.py::test_missing", "x"), tmp_path)


def test_pytest_parametrized_matches_base_name(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_p():\n    assert True\n")
    assert resolve_check(Check("pytest", "tests/t.py::test_p[case1]", "x"), tmp_path)


def test_make_check_resolves_by_makefile_grep(tmp_path):
    (tmp_path / "Makefile").write_text("arch-check:\n\techo hi\n")
    assert resolve_check(Check("make", "arch-check", "make:arch-check"), tmp_path)
    assert not resolve_check(Check("make", "nope", "make:nope"), tmp_path)


def test_prose_never_resolves(tmp_path):
    assert not resolve_check(Check("prose", "human review", "human review"), tmp_path)


def test_mutating_targets_flagged():
    assert is_mutating(Check("make", "lint-ul", "make:lint-ul"))
    assert is_mutating(Check("make", "arch-regen", "make:arch-regen"))
    assert not is_mutating(Check("make", "arch-check", "make:arch-check"))
    assert not is_mutating(Check("pytest", "tests/t.py::t", "x"))
    assert "lint-ul" in MUTATING_MAKE_TARGETS


def test_pytest_class_method_resolves_when_direct_child(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(
        "class TestFoo:\n    def test_bar(self):\n        assert True\n"
    )
    assert resolve_check(
        Check("pytest", "tests/t.py::TestFoo::test_bar", "x"), tmp_path
    )


def test_pytest_class_method_false_when_method_defined_in_different_class(tmp_path):
    # The exact false-positive the reviewer flagged: test_bar exists, but not
    # as a member of TestFoo. A flat ast.walk() name match would wrongly
    # resolve this True.
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(
        "class TestFoo:\n"
        "    def test_other(self):\n"
        "        assert True\n"
        "\n"
        "class TestBaz:\n"
        "    def test_bar(self):\n"
        "        assert True\n"
    )
    assert not resolve_check(
        Check("pytest", "tests/t.py::TestFoo::test_bar", "x"), tmp_path
    )


def test_pytest_class_method_false_when_class_missing(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_bar():\n    assert True\n")
    assert not resolve_check(
        Check("pytest", "tests/t.py::TestFoo::test_bar", "x"), tmp_path
    )


def test_pytest_class_method_parametrized_strips_suffix(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text(
        "class TestFoo:\n    def test_bar(self):\n        assert True\n"
    )
    assert resolve_check(
        Check("pytest", "tests/t.py::TestFoo::test_bar[case1]", "x"), tmp_path
    )


def test_pytest_module_level_function_still_resolves(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_bar():\n    assert True\n")
    assert resolve_check(Check("pytest", "tests/t.py::test_bar", "x"), tmp_path)
    assert not resolve_check(
        Check("pytest", "tests/t.py::test_missing_entirely", "x"), tmp_path
    )


def test_pytest_module_only_citation_resolves_when_file_exists(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_bar():\n    assert True\n")
    assert resolve_check(Check("pytest", "tests/t.py", "x"), tmp_path)
    assert not resolve_check(Check("pytest", "tests/missing.py", "x"), tmp_path)


def test_pytest_dangling_double_colon_treated_as_module_only(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "t.py").write_text("def test_bar():\n    assert True\n")
    assert resolve_check(Check("pytest", "tests/t.py::", "x"), tmp_path)
