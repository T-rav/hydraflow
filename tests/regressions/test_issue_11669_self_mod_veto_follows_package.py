"""Regression #11669 — the T29 self-modification veto was inert for review_phase.

``review_advisor.SELF_MODIFYING_PATHS`` names two modules:
``src/review_advisor.py`` and ``src/review_phase.py``. On 2026-05-11 (#T36,
commit ``67a16cd56``) ``review_phase`` was split into a package, and both
consumers of that set matched it as a **literal path**:

* ``_diff_touches_self_modifying_paths`` substring-searched the diff for
  ``+++ b/src/review_phase.py`` and friends;
* ``review_phase/_wiki_ingest.py`` tested ``path in SELF_MODIFYING_PATHS``;
* ``review_phase/_common.py``'s synthesis regexes baked the two module names
  in as ``src/(?:review_advisor|review_phase)\\.py``.

A diff touching ``src/review_phase/_advisors.py`` emits
``+++ b/src/review_phase/_advisors.py``, which contains none of those. So for
**104 days** the guard that exists so "the advisor must never approve changes
to its own implementation silently" (spec §5.8) fired for exactly one of the
15 files it names, and failed OPEN for the other 14 — on a trust boundary
(ADR-0045). Nothing reddened, because a membership test that matches nothing
is indistinguishable from one that does not match *this* diff.

The fix matches on module IDENTITY (``path_membership.module_identities``), so
membership follows the MODULE through any decomposition. These tests fail if
a package member of a self-modifying module stops being vetoed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from path_membership import module_identities
from review_advisor import (
    SELF_MODIFYING_PATHS,
    SURFACE_ADVISOR_CONFIGS,
    is_self_modifying_path,
    resolve_post_verify_authority,
)
from review_phase import _detect_self_modification_context

# Every real member of the review_phase package. Written as a live directory
# read rather than a literal list on purpose: a hard-coded list here would rot
# the same way SELF_MODIFYING_PATHS did.
_SRC = Path(__file__).resolve().parents[2] / "src"
PACKAGE_MEMBERS = sorted(
    p.relative_to(_SRC).as_posix() for p in (_SRC / "review_phase").glob("*.py")
)


def _diff_for(path: str) -> str:
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1,3 +1,4 @@\n"
        "+# advisor edits its own review logic\n"
    )


class TestPackageMembersAreSelfModifying:
    def test_the_package_has_members_to_test(self) -> None:
        """Vacuity guard — the bug being tested needs a package to exist."""
        assert len(PACKAGE_MEMBERS) > 1, (
            "src/review_phase/ has fewer than two modules; if it stopped being "
            "a package these tests would pass without proving anything."
        )

    @pytest.mark.parametrize(
        "member",
        PACKAGE_MEMBERS,
        ids=lambda m: m.rsplit("/", 1)[-1],
    )
    def test_every_review_phase_member_is_self_modifying(self, member: str) -> None:
        path = f"src/{member}"
        assert is_self_modifying_path(path), (
            f"{path} is a member of src/review_phase/, the module named by "
            "SELF_MODIFYING_PATHS, but is not classified as self-modifying. "
            "The T29 guard has gone package-blind again — match on module "
            "identity, not on the literal path."
        )

    @pytest.mark.parametrize(
        "member",
        PACKAGE_MEMBERS,
        ids=lambda m: m.rsplit("/", 1)[-1],
    )
    def test_a_package_member_diff_forces_veto_on_an_advisory_surface(
        self, member: str
    ) -> None:
        """The whole point of T29: advisory surfaces get upgraded, not consulted.

        ``wiki_ingest`` is configured ``advisory``. A diff touching the
        advisor's own implementation must come back ``veto`` anyway.
        """
        authority = resolve_post_verify_authority(
            surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
            diff=_diff_for(f"src/{member}"),
        )
        assert authority == "veto", (
            f"a diff touching src/{member} left wiki_ingest on 'advisory'. "
            "The advisor can approve a change to its own review logic with "
            "nothing stronger than an opinion."
        )


class TestTheOriginalRegressionShape:
    """The exact reproduction from the issue body."""

    def test_review_advisor_still_vetoes(self) -> None:
        assert (
            resolve_post_verify_authority(
                surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
                diff=_diff_for("src/review_advisor.py"),
            )
            == "veto"
        )

    def test_review_phase_package_member_now_vetoes(self) -> None:
        """This assertion is the bug: it returned 'advisory' before #11669."""
        assert (
            resolve_post_verify_authority(
                surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
                diff=_diff_for("src/review_phase/_advisors.py"),
            )
            == "veto"
        )

    def test_an_unrelated_module_is_untouched(self) -> None:
        """The fix ADDS vetoes; it must not turn the guard into a blanket."""
        assert (
            resolve_post_verify_authority(
                surface_config=SURFACE_ADVISOR_CONFIGS["wiki_ingest"],
                diff=_diff_for("src/pr_manager.py"),
            )
            == "advisory"
        )

    def test_a_sibling_of_the_package_is_untouched(self) -> None:
        """``src/review_phase_helpers.py`` is a different module, not a member."""
        assert not is_self_modifying_path("src/review_phase_helpers.py")
        assert not is_self_modifying_path("src/review_advisor_notes.py")


class TestWikiIngestSynthesisFollowsThePackage:
    """The third consumer: the context detector fed the same identity test."""

    def test_editorial_context_on_a_package_member_is_detected(self) -> None:
        detected = _detect_self_modification_context(
            "The agent modified src/review_phase/_advisors.py to relax the gate."
        )
        assert "src/review_phase/_advisors.py" in detected

    def test_detected_package_member_is_self_modifying(self) -> None:
        """Detection plus identity is what synthesizes the pseudo-header."""
        detected = _detect_self_modification_context(
            "modified src/review_phase/_wiki_ingest.py"
        )
        assert any(is_self_modifying_path(p) for p in detected)

    def test_benign_prose_mention_still_does_not_trigger(self) -> None:
        """T37 must survive: a bare mention is not a modification context."""
        assert not _detect_self_modification_context(
            "review found a type-hint gap in src/review_phase/_advisors.py"
        )


class TestModuleIdentityIsTheMechanism:
    def test_identities_resolve_a_member_to_its_module(self) -> None:
        assert "src/review_phase.py" in module_identities(
            "src/review_phase/_advisors.py"
        )

    def test_the_named_module_is_still_the_one_in_the_set(self) -> None:
        """SELF_MODIFYING_PATHS keeps naming the MODULE, not the file layout."""
        assert "src/review_phase.py" in SELF_MODIFYING_PATHS
