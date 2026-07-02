import markdown

from adr_index import ADR, Check
from arch._models import ADRRef, ADRRefIndex
from arch.generators.adr_cross_reference import render_adr_cross_reference


def test_raw_check_text_with_markdown_link_and_backticks_does_not_render_as_link():
    """Regression: an Enforced-by `raw` citation with an embedded markdown
    link plus a literal backtick used to break the single-backtick wrapper,
    letting mkdocs render a real `<a href>` into the excluded superpowers/
    tree and fail `mkdocs build --strict`.
    """
    idx = ADRRefIndex(adr_to_modules=[ADRRef(adr_id="ADR-0050", cited_modules=[])])
    adrs = [
        ADR(
            number=50,
            title="Auto-Agent HITL pre-flight",
            status="Accepted",
            summary="",
            enforcement="manual",
            enforced_by=(
                Check(
                    "prose",
                    "tests/test_x.py`.",
                    "`tests/test_x.py`.",
                ),
                Check(
                    "prose",
                    "spec link",
                    "- **Spec:** [docs/superpowers/specs/x.md](../superpowers/specs/x.md)",
                ),
            ),
        ),
    ]
    md = render_adr_cross_reference(idx, adrs)
    html = markdown.markdown(md, extensions=["tables"])
    assert "<a href" not in html, (
        f"raw check text leaked a real markdown link into rendered HTML:\n{html}"
    )


def test_emits_forward_and_reverse_tables():
    idx = ADRRefIndex(
        adr_to_modules=[
            ADRRef(adr_id="ADR-0001", cited_modules=["src.foo", "src.bar"]),
            ADRRef(adr_id="ADR-0002", cited_modules=["src.foo"]),
        ]
    )
    md = render_adr_cross_reference(idx)
    assert "## ADR → Modules" in md
    assert "## Module → ADRs" in md
    assert "src.foo" in md
    assert "ADR-0001" in md
    # src.foo is cited by both ADRs — assert both appear in the reverse section
    reverse_section = md.split("## Module → ADRs", 1)[1]
    assert "ADR-0001" in reverse_section
    assert "ADR-0002" in reverse_section
