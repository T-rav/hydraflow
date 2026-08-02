"""Regression test for issue #10865 — placeholder leak hidden in a Markdown bullet.

``prompt_fitness.placeholder_leaks`` strips diff content before scanning rendered
prompts for un-substituted ``{placeholder}`` tokens. The original rule,
``_DIFF_LINE = re.compile(r"^[+-].*$")``, blanked *every* line beginning with a
bare ``-`` or ``+`` — which also matches an ordinary Markdown bullet
(``- Use the {context}...``). A real placeholder leak sitting inside a bulleted
list line was therefore erased before the scan and escaped the leak gate, in
exactly the defect class the detector was written to close.

The fix makes diff stripping hunk-scoped: ``+``/``-`` lines are only treated as
diff body when they sit inside an actual unified-diff hunk (after a
``diff --git`` / ``index`` / ``---`` / ``+++`` / ``@@`` header). Bulleted prose
is scanned like any other prose, so a placeholder inside it is caught, while
genuine diff hunk lines are still stripped.
"""

from __future__ import annotations

from prompt_fitness import placeholder_leaks


def test_placeholder_in_flush_markdown_bullet_is_a_leak() -> None:
    # The core escape: a bullet marker must not blank the line before the scan.
    assert placeholder_leaks(
        "- Use the {context} to decide what to do next."
    ) == frozenset({"context"})


def test_placeholder_in_indented_markdown_bullet_is_a_leak() -> None:
    # Two leading spaces before the bullet must not change the verdict.
    assert "context" in placeholder_leaks("  - Use the {context} to decide.")


def test_placeholder_in_plus_prefixed_bullet_is_a_leak() -> None:
    # ``+`` is also a valid Markdown bullet marker; outside a hunk it is prose.
    assert "foo" in placeholder_leaks("+ consider the {foo} value")


def test_placeholder_in_bullet_after_a_diff_hunk_is_a_leak() -> None:
    # A finding bullet that follows a real diff hunk (separated by a plain prose
    # line that closes the hunk) is still scanned as prose.
    text = (
        "@@ -1,2 +1,2 @@\n"
        "-old line\n"
        "+new line\n"
        "Findings below:\n"
        "- Use the {context} to decide what to do next.\n"
    )
    assert "context" in placeholder_leaks(text)


def test_genuine_diff_hunk_lines_are_still_stripped() -> None:
    # A full unified diff with real headers: every ``+``/``-`` body line, braces
    # included, is diff content and must not be reported as a leak.
    text = (
        "diff --git a/x.py b/x.py\n"
        "index 1234567..89abcde 100644\n"
        "--- a/x.py\n"
        "+++ b/x.py\n"
        "@@ -1,3 +1,4 @@\n"
        " context line\n"
        "-removed {gone}\n"
        "+added {alsogone}\n"
    )
    assert placeholder_leaks(text) == frozenset()


def test_lone_fstring_diff_line_is_not_a_leak() -> None:
    # Pin the existing brace-in-code case: an f-string literal on a ``+``-prefixed
    # line is content, not a leak, even with no preceding diff header.
    assert (
        placeholder_leaks('+        grouped[f"{year}-W{week:02d}"].append(r)')
        == frozenset()
    )


def test_bulleted_fstring_literal_is_not_a_leak() -> None:
    # A review-finding bullet that quotes an f-string is prose, but the braces are
    # content — the f-string strip keeps it quiet without blanking the bullet.
    assert (
        placeholder_leaks('- the code writes f"{year}-W{week:02d}" here') == frozenset()
    )


def test_triple_quoted_fstring_is_fully_stripped() -> None:
    # Guards the f-string strip against the empty-``f""`` trap on triple quotes.
    assert placeholder_leaks('- see f"""a{b}c""" in the snippet') == frozenset()
