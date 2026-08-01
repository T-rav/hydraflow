from arch.extractors.ports import extract_ports


def test_finds_protocol_port_with_adapter_and_fake(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/ports.py": """
            from typing import Protocol

            class WidgetPort(Protocol):
                def make(self) -> str: ...
                def break_(self) -> None: ...

            class HelperProtocol(Protocol):
                def thing(self) -> None: ...
        """,
            "src/widget_adapter.py": """
            class WidgetAdapter:
                def make(self) -> str: return ""
                def break_(self) -> None: pass
        """,
            "src/mockworld/__init__.py": "",
            "src/mockworld/fakes/__init__.py": "",
            "src/mockworld/fakes/fake_widget.py": """
            class FakeWidget:
                def make(self) -> str: return "fake"
                def break_(self) -> None: pass
        """,
        }
    )

    ports = extract_ports(src_dir=root / "src", fakes_dir=root / "src/mockworld/fakes")

    assert len(ports) == 1
    p = ports[0]
    assert p.name == "WidgetPort"
    assert sorted(p.methods) == ["break_", "make"]
    assert len(p.adapters) == 1
    assert p.adapters[0].name == "WidgetAdapter"
    assert p.fake is not None
    assert p.fake.name == "FakeWidget"


def test_adapter_split_across_mixin_module_still_detected(fixture_src_tree):
    """God-file decomposition: an adapter whose methods are split between its
    own body and a same-repo mixin base class (in another module) must still
    be detected as the port's adapter (PRManager / PRManagerPromotionMixin)."""
    root = fixture_src_tree(
        {
            "src/ports.py": """
            from typing import Protocol

            class WidgetPort(Protocol):
                def make(self) -> str: ...
                def promote(self) -> None: ...
        """,
            "src/widget_promotion.py": """
            class WidgetPromotionMixin:
                def promote(self) -> None: pass
        """,
            "src/widget_adapter.py": """
            from widget_promotion import WidgetPromotionMixin

            class WidgetAdapter(WidgetPromotionMixin):
                def make(self) -> str: return ""
        """,
        }
    )

    ports = extract_ports(src_dir=root / "src", fakes_dir=root / "nonexistent")

    assert len(ports) == 1
    p = ports[0]
    assert p.name == "WidgetPort"
    adapter_names = [a.name for a in p.adapters]
    assert "WidgetAdapter" in adapter_names


def test_port_without_fake_marks_fake_none(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/ports.py": """
            from typing import Protocol
            class LonelyPort(Protocol):
                def thing(self) -> None: ...
        """,
        }
    )
    ports = extract_ports(src_dir=root / "src", fakes_dir=root / "nonexistent")
    assert len(ports) == 1
    assert ports[0].fake is None


def test_skips_classes_not_ending_in_port(fixture_src_tree):
    root = fixture_src_tree(
        {
            "src/ports.py": """
            from typing import Protocol
            class Helper(Protocol):
                def thing(self) -> None: ...
            class WidgetPort(Protocol):
                def make(self) -> str: ...
        """,
        }
    )
    ports = extract_ports(src_dir=root / "src", fakes_dir=root / "nonexistent")
    assert len(ports) == 1
    assert ports[0].name == "WidgetPort"
