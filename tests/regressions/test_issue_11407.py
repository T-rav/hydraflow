"""Regression pin for #11407: sampled adversarial re-audit of PR #11341.

``_append_site``'s ``title in existing_sites`` fallback (added in #11341 to
make a site-aware rediscovery of a pre-#11328 legacy, untagged roster line a
no-op) cannot distinguish "this is the same site whose legacy line has no
site tag" from "this is a completely different, newly-discovered site whose
finder-generated title happens to collide with an unrelated legacy entry."
Templated/generic finder titles (e.g. "Missing null check") are exactly the
case #11328 was designed around: titles are not guaranteed unique per site.

Before the fix, a title collision with a legacy line silently dropped the
new site: no roster change, no comment, ``file_or_fold`` returned the
matched issue number as though idempotency had succeeded, and the new site
was never tracked again. The fix binds the legacy bare line to the
current call's site identifier instead of leaving it untouched -- the site
is recorded (no longer silently lost), while a genuine same-site rediscovery
still produces no duplicate "new site" notification.
"""

from __future__ import annotations

import pytest

from find_class_key import (
    compute_class_key,
    extract_folded_sites,
    file_or_fold,
    render_marker,
)


class _RecordingPRPort:
    """Scripted PRPort double recording file_or_fold's calls."""

    def __init__(self) -> None:
        self._issues: dict[int, dict] = {}
        self._next_number = 50000
        self.comment_calls: list[tuple[int, str]] = []
        self.update_calls: list[tuple[int, str]] = []

    async def list_issues_by_label(self, label: str) -> list[dict]:
        return [dict(issue) for issue in self._issues.values()]

    async def update_issue_body(self, issue_number: int, body: str) -> None:
        self.update_calls.append((issue_number, body))
        self._issues[issue_number]["body"] = body

    async def post_comment(self, issue_number: int, body: str) -> None:
        self.comment_calls.append((issue_number, body))

    async def create_issue(
        self, title: str, body: str, labels: list[str] | None = None
    ) -> int:
        number = self._next_number
        self._next_number += 1
        self._issues[number] = {"number": number, "title": title, "body": body}
        return number


_SOURCE = "generic-null-check-finder"
_NEEDLE = "missing null check before dereference"
_COLLIDING_TITLE = "Missing null check"


def _legacy_issue_with_bare_title_line() -> tuple[_RecordingPRPort, str]:
    """An issue filed before #11328: one site, rostered by title text alone."""
    prs = _RecordingPRPort()
    class_key = compute_class_key(_SOURCE, _NEEDLE)
    legacy_body = (
        "## Finding\n\nsrc/original_site.py:5 missing null check\n\n"
        "## Folded sites\n"
        f"- {_COLLIDING_TITLE}\n\n"
        f"{render_marker(class_key)}\n"
    )
    prs._issues[50000] = {
        "number": 50000,
        "title": _COLLIDING_TITLE,
        "body": legacy_body,
    }
    prs._next_number = 50001
    return prs, legacy_body


@pytest.mark.asyncio
async def test_distinct_site_colliding_with_legacy_title_is_not_silently_dropped() -> (
    None
):
    """A genuinely new site whose title collides with a legacy line must
    still end up tracked in the roster -- not silently discarded.
    """
    prs, legacy_body = _legacy_issue_with_bare_title_line()

    result_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        _COLLIDING_TITLE,
        "## Finding\n\nsrc/foo.py:12 missing null check",
        ["hydraflow-find"],
        site="src/foo.py:12",
    )

    assert result_number == 50000
    assert len(prs._issues) == 1
    final_body = prs._issues[50000]["body"]
    # The body must change -- a silent no-op would mean the new site was
    # never recorded anywhere.
    assert final_body != legacy_body
    # The new site's identifier now appears in the roster.
    assert "src/foo.py:12" in extract_folded_sites(final_body)
    # The body change was actually persisted.
    assert len(prs.update_calls) == 1


@pytest.mark.asyncio
async def test_genuine_rediscovery_of_the_legacy_site_still_posts_no_comment() -> None:
    """The #11328 intent -- a true same-site rediscovery is quiet -- must
    survive the fix: binding a legacy bare line to the calling site does
    not spam a "new site folded" comment.
    """
    prs, _legacy_body = _legacy_issue_with_bare_title_line()

    await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        _COLLIDING_TITLE,
        "## Finding\n\nsrc/original_site.py:5 missing null check",
        ["hydraflow-find"],
        site="src/original_site.py:5",
    )

    assert len(prs.comment_calls) == 0


@pytest.mark.asyncio
async def test_bound_site_is_recognized_on_a_later_rediscovery() -> None:
    """Once bound to a site identifier, a later tick rediscovering that
    exact site (even with a reworded title) is a true no-op.
    """
    prs, _legacy_body = _legacy_issue_with_bare_title_line()

    await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        _COLLIDING_TITLE,
        "## Finding\n\nsrc/foo.py:12 missing null check",
        ["hydraflow-find"],
        site="src/foo.py:12",
    )
    body_after_bind = prs._issues[50000]["body"]

    result_number = await file_or_fold(
        prs,
        _SOURCE,
        _NEEDLE,
        "Missing null check (re-swept)",
        "## Finding\n\nsrc/foo.py:12 missing null check",
        ["hydraflow-find"],
        site="src/foo.py:12",
    )

    assert result_number == 50000
    assert prs._issues[50000]["body"] == body_after_bind
    assert len(prs.comment_calls) == 0
