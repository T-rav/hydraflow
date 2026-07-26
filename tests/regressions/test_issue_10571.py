"""Regression test for issue #10571.

Bug: the ``{ ...baseStyleWithBorderShorthand, borderColor: X }`` pattern fixed
in ``Header.jsx`` for issue #10564 recurs in several other dashboard
components — a base style object sets the ``border`` CSS shorthand and a
variant/inline override then sets only the ``borderColor`` longhand. React
warns when a style update removes a longhand sub-property while the
shorthand remains set on the same DOM node across a rerender ("mixing
shorthand and non-shorthand properties for the same value").

Expected behaviour: any style object whose variants override a border
sub-property must define the base in longhand form (``borderWidth`` /
``borderStyle`` / ``borderColor``), so variants only ever change a value
rather than removing a key. ``borderRadius`` is not a ``border``
sub-property and must not be flagged.

Pure source-structure checks (see ``tests/ui_style_reader.py``) — the
frontend JS toolchain is not required to run them.
"""

from __future__ import annotations

import pytest

from tests.ui_style_reader import (
    REPO_ROOT,
    extract_nested_object,
    extract_object_literal,
    extract_spread_variants,
    find_border_shorthand_conflicts,
    read_source,
)

_STREAM_CARD = REPO_ROOT / "src" / "ui" / "src" / "components" / "StreamCard.jsx"
_PIPELINE_STATUS = REPO_ROOT / "src" / "ui" / "src" / "components" / "PipelineStatus.jsx"
_BUG_REPORT_PANEL = REPO_ROOT / "src" / "ui" / "src" / "components" / "BugReportPanel.jsx"
_ISSUE_HISTORY_PANEL = (
    REPO_ROOT / "src" / "ui" / "src" / "components" / "IssueHistoryPanel.jsx"
)


def test_stream_card_stage_node_base_has_no_border_shorthand_conflict() -> None:
    """`stageNodeBase` must not mix `border` shorthand with the six status variants' `borderColor`."""
    src = read_source(_STREAM_CARD)
    base = extract_object_literal(src, "stageNodeBase")
    variants = extract_spread_variants(src, "stageNodeBase")
    assert variants, "expected stageNodeBase to be spread by status variants in StageRow"

    conflicts = find_border_shorthand_conflicts(
        "StreamCard.stageNodeBase",
        base,
        {f"nodeStyle variant #{i}": v for i, v in enumerate(variants)},
    )

    assert conflicts == [], conflicts


def test_stream_card_stage_badge_has_no_border_shorthand_conflict() -> None:
    """`styles.stageBadge` must not mix `border` shorthand with the header meta badge's `borderColor` override."""
    src = read_source(_STREAM_CARD)
    styles_block = extract_object_literal(src, "styles")
    base = extract_nested_object(styles_block, "stageBadge")
    variants = extract_spread_variants(src, "styles.stageBadge")
    assert variants, "expected styles.stageBadge to be spread by the header meta badge"

    conflicts = find_border_shorthand_conflicts(
        "StreamCard.styles.stageBadge",
        base,
        {f"badge override #{i}": v for i, v in enumerate(variants)},
    )

    assert conflicts == [], conflicts


def test_pipeline_status_stage_has_no_border_shorthand_conflict() -> None:
    """`styles.stage` must not mix `border` shorthand with the active/inactive stage variants' `borderColor`."""
    src = read_source(_PIPELINE_STATUS)
    styles_block = extract_object_literal(src, "styles")
    base = extract_nested_object(styles_block, "stage")
    variants = extract_spread_variants(src, "styles.stage")
    assert variants, "expected styles.stage to be spread by active/inactive stageStyles variants"

    conflicts = find_border_shorthand_conflicts(
        "PipelineStatus.styles.stage",
        base,
        {f"stageStyles variant #{i}": v for i, v in enumerate(variants)},
    )

    assert conflicts == [], conflicts


def test_bug_report_panel_status_badge_has_no_border_shorthand_conflict() -> None:
    """`styles.statusBadge` must not mix `border` shorthand with the inline `borderColor` override."""
    src = read_source(_BUG_REPORT_PANEL)
    styles_block = extract_object_literal(src, "styles")
    base = extract_nested_object(styles_block, "statusBadge")
    variants = extract_spread_variants(src, "styles.statusBadge")
    assert variants, "expected styles.statusBadge to be spread by the inline status badge"

    conflicts = find_border_shorthand_conflicts(
        "BugReportPanel.styles.statusBadge",
        base,
        {f"status badge override #{i}": v for i, v in enumerate(variants)},
    )

    assert conflicts == [], conflicts


def test_bug_report_panel_pill_has_no_border_shorthand_conflict() -> None:
    """`styles.pill` must not mix `border` shorthand with `styles.pillActive`'s `borderColor` override."""
    src = read_source(_BUG_REPORT_PANEL)
    styles_block = extract_object_literal(src, "styles")
    base = extract_nested_object(styles_block, "pill")
    pill_active = extract_nested_object(styles_block, "pillActive")

    conflicts = find_border_shorthand_conflicts(
        "BugReportPanel.styles.pill",
        base,
        {"pillActive": pill_active},
    )

    assert conflicts == [], conflicts


def test_issue_history_panel_linked_pill_has_no_border_shorthand_conflict() -> None:
    """`styles.linkedPill` must not mix `border` shorthand with `renderLinkedIssue`'s `borderColor` override."""
    src = read_source(_ISSUE_HISTORY_PANEL)
    styles_block = extract_object_literal(src, "styles")
    base = extract_nested_object(styles_block, "linkedPill")
    variants = extract_spread_variants(src, "styles.linkedPill")
    assert variants, "expected styles.linkedPill to be spread by renderLinkedIssue's pillStyle"

    conflicts = find_border_shorthand_conflicts(
        "IssueHistoryPanel.styles.linkedPill",
        base,
        {f"pillStyle override #{i}": v for i, v in enumerate(variants)},
    )

    assert conflicts == [], conflicts


def test_issue_history_panel_button_has_no_border_shorthand_conflict() -> None:
    """`styles.button` must not mix `border` shorthand with `buttonActiveStyle`'s `borderColor` override."""
    src = read_source(_ISSUE_HISTORY_PANEL)
    styles_block = extract_object_literal(src, "styles")
    base = extract_nested_object(styles_block, "button")
    variants = extract_spread_variants(src, "styles.button")
    assert variants, "expected styles.button to be spread by buttonActiveStyle"

    conflicts = find_border_shorthand_conflicts(
        "IssueHistoryPanel.styles.button",
        base,
        {f"buttonActiveStyle override #{i}": v for i, v in enumerate(variants)},
    )

    assert conflicts == [], conflicts


def test_border_shorthand_with_variant_longhand_override_is_flagged() -> None:
    """Sanity-check the checker itself: a real shorthand/longhand mix must be flagged."""
    base = "{ border: '1px solid red' }"
    variant = "{ ...base, borderColor: 'blue' }"

    conflicts = find_border_shorthand_conflicts("decoy", base, {"variant": variant})

    assert conflicts != []


def test_border_radius_override_is_not_flagged_as_a_border_subproperty() -> None:
    """`borderRadius` is not a `border` sub-property and must never be flagged."""
    base = "{ border: '1px solid red', borderRadius: 8 }"
    variant = "{ ...base, borderRadius: 12 }"

    conflicts = find_border_shorthand_conflicts("decoy", base, {"variant": variant})

    assert conflicts == []


def test_style_object_with_no_border_keys_has_no_conflicts() -> None:
    """A style object family untouched by `border` entirely must report zero conflicts."""
    base = "{ display: 'flex', gap: 8 }"
    variant = "{ ...base, gap: 12 }"

    conflicts = find_border_shorthand_conflicts("decoy", base, {"variant": variant})

    assert conflicts == []


def test_extract_object_literal_raises_for_missing_name() -> None:
    """A missing object-literal name must fail loudly, not silently return nothing."""
    with pytest.raises(AssertionError):
        extract_object_literal("const foo = {}", "bar")
