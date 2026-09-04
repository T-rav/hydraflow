"""The config surface follows the config when it is decomposed (#11547).

Three arch readers derive published artifacts from ``HydraFlowConfig``. Each
one used to parse ``src/config.py`` as a file and answer **empty** — never
raise — once the config was split across modules, which is the standing remedy
for the largest god class on the board. A blank "Model roles" table and
unresolvable loop intervals, with nothing red anywhere.

These tests are written from the decomposed side: every case moves the subject
out of ``config.py`` first and then asks the reader for it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from arch.config_surface import (
    annotated_field_names,
    config_surface_paths,
    int_field_defaults,
    resolve_local_module,
    role_table,
)

if TYPE_CHECKING:
    from pathlib import Path

_MONOLITHIC = {
    "src/config.py": """
        _ENV_COMBO_OVERRIDES: list[tuple[str, str, str]] = [
            ("HYDRAFLOW_WIDGET", "widget_tool", "widget_model"),
        ]

        class HydraFlowConfig(BaseModel):
            widget_model: str = Field(default="opus")
            widget_interval_seconds: int = Field(default=300)
    """,
}

#: The same config after the #11547 recipe: dials onto a mixin, tables to a
#: sibling. ``config.py`` keeps only the class statement and its imports.
_DECOMPOSED = {
    "src/config.py": """
        from config_dials import WidgetDials
        from config_env_tables import _ENV_COMBO_OVERRIDES

        class HydraFlowConfig(WidgetDials):
            pass
    """,
    "src/config_dials.py": """
        class WidgetDials(BaseModel):
            widget_model: str = Field(default="opus")
            widget_interval_seconds: int = Field(default=300)
    """,
    "src/config_env_tables.py": """
        _ENV_COMBO_OVERRIDES: list[tuple[str, str, str]] = [
            ("HYDRAFLOW_WIDGET", "widget_tool", "widget_model"),
        ]
    """,
}


@pytest.fixture
def monolithic(fixture_src_tree) -> Path:
    return fixture_src_tree(_MONOLITHIC) / "src"


@pytest.fixture
def decomposed(fixture_src_tree) -> Path:
    return fixture_src_tree(_DECOMPOSED) / "src"


class TestTheReadersSurviveDecomposition:
    """Each reader, asked for a subject that is no longer in ``config.py``."""

    def test_fields_on_a_mixin_are_still_the_configs_fields(
        self, decomposed: Path
    ) -> None:
        assert annotated_field_names(decomposed, "HydraFlowConfig") == [
            "widget_interval_seconds",
            "widget_model",
        ]

    def test_a_role_table_in_a_sibling_module_is_still_found(
        self, decomposed: Path
    ) -> None:
        assert role_table(decomposed) == [
            ("HYDRAFLOW_WIDGET", "widget_tool", "widget_model")
        ]

    def test_int_defaults_on_a_mixin_are_still_found(self, decomposed: Path) -> None:
        assert int_field_defaults(decomposed)["widget_interval_seconds"] == 300

    def test_decomposing_changes_no_answer(self, monolithic: Path, decomposed: Path):
        """The point of the exercise: the readers cannot tell the two apart.

        Stated as one assertion because "same answer before and after" is the
        actual contract — the three above would all still hold if decomposition
        quietly returned a *different* non-empty answer.
        """
        before = (
            annotated_field_names(monolithic, "HydraFlowConfig"),
            role_table(monolithic),
            int_field_defaults(monolithic),
        )
        after = (
            annotated_field_names(decomposed, "HydraFlowConfig"),
            role_table(decomposed),
            int_field_defaults(decomposed),
        )

        assert before == after


class TestTheSurfaceIsBoundedByImports:
    """The control. Without it "follows the config" would mean "reads all of src"."""

    def test_a_module_the_config_does_not_import_contributes_nothing(
        self, fixture_src_tree
    ) -> None:
        """A mixin nobody imports is not part of the config.

        If the surface were the whole tree, every assertion above would pass
        for a reason that has nothing to do with following the config.
        """
        src = (
            fixture_src_tree(
                {
                    **_DECOMPOSED,
                    "src/config_orphan.py": """
                        class OrphanDials(BaseModel):
                            orphan_model: str = Field(default="nope")
                    """,
                }
            )
            / "src"
        )

        assert "orphan_model" not in annotated_field_names(src, "HydraFlowConfig")
        assert "orphan_model" not in int_field_defaults(src)

    def test_a_base_the_surface_cannot_resolve_is_not_an_error(
        self, decomposed: Path
    ) -> None:
        """``BaseModel`` resolves nowhere in src and holds no HydraFlow dials."""
        assert annotated_field_names(decomposed, "WidgetDials") == [
            "widget_interval_seconds",
            "widget_model",
        ]

    def test_a_package_resolves_to_every_module_not_just_its_facade(
        self, fixture_src_tree
    ) -> None:
        """A decomposed module's ``__init__`` is a re-export facade (#11673)."""
        root = fixture_src_tree(
            {
                "src/pkg/__init__.py": "from ._impl import thing\n",
                "src/pkg/_impl.py": "thing = 1\n",
            }
        )

        resolved = {p.name for p in resolve_local_module("pkg", root / "src")}

        assert resolved == {"__init__.py", "_impl.py"}


class TestTheReadersFailClosed:
    """Answering "nothing" is how this stayed invisible for so long."""

    def test_a_missing_role_table_raises_rather_than_rendering_an_empty_section(
        self, fixture_src_tree
    ) -> None:
        """It used to return ``[]`` — a "Model roles" header with no rows."""
        src = fixture_src_tree({"src/config.py": "class HydraFlowConfig: pass\n"})

        with pytest.raises(RuntimeError, match="_ENV_COMBO_OVERRIDES"):
            role_table(src / "src")

    def test_a_missing_config_class_raises(self, fixture_src_tree) -> None:
        src = fixture_src_tree({"src/config.py": "x = 1\n"})

        with pytest.raises(RuntimeError, match="HydraFlowConfig"):
            annotated_field_names(src / "src", "HydraFlowConfig")

    def test_the_surface_is_empty_without_a_config_module(
        self, fixture_src_tree
    ) -> None:
        src = fixture_src_tree({"src/other.py": "x = 1\n"})

        assert config_surface_paths(src / "src") == []


class TestTheSurfaceSpansConfigAndItsImports:
    def test_it_lists_config_and_the_modules_it_imports(self, decomposed: Path) -> None:
        assert [p.name for p in config_surface_paths(decomposed)] == [
            "config.py",
            "config_dials.py",
            "config_env_tables.py",
        ]
