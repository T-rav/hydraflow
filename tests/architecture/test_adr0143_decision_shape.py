"""ADR-0143 Ruling 4: the decision shape is four statuses plus orthogonal blocking.

Ruling 4 originally declared a closed FIVE-verdict set including *blocking*, while
`src/policy/models.py` shipped four members and carried `blocking` as a separate
bool. The code's shape is the better one — the four classify *what is true* of a
subject, `blocking` decides *what to do about it*, and they vary independently
("violated but not gating" is a real state the exemption and baseline lanes both
produce). The 2026-08-31 amendment reconciles the text to the code.

These are the enforcement anchors that amendment cites. Without them the
reconciliation is prose agreement, which is what rotted in the first place: the
ADR is Accepted with real enforcement, so future standards are written against
its text, and anyone modelling `blocking` as a fifth status collides with
`DecisionStatus` at review time.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from policy.models import DecisionStatus, StandardDecision

_ADR = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "adr"
    / "0143-paaa-governance-model-and-the-decision-seam.md"
)


def test_decision_status_is_exactly_the_four_ruled_members() -> None:
    """Exact equality, not a subset check.

    A subset assertion would pass if `blocking` were later added back as a fifth
    member — which is precisely the drift being ruled out.
    """
    assert {s.value for s in DecisionStatus} == {
        "compliant",
        "violated",
        "exempt",
        "grandfathered",
    }


def test_blocking_is_an_orthogonal_field_not_a_status() -> None:
    """Both halves matter: present as a field AND absent from the enum."""
    assert "blocking" in StandardDecision.model_fields
    assert StandardDecision.model_fields["blocking"].annotation is bool
    assert "blocking" not in {s.value for s in DecisionStatus}


def test_the_adr_text_no_longer_declares_a_five_verdict_set() -> None:
    """The reconciliation is in the ADR, not only in this test.

    Pins both places Ruling 4 stated the five-set — the prose and the seam
    diagram — since fixing one and missing the other is how the two writers
    drifted apart to begin with.
    """
    # Scoped to the ruling body: the amendment DELIBERATELY quotes the original
    # five-set for the record, and the next test requires that quote. A
    # whole-file check makes the two mutually unsatisfiable.
    ruling = _ADR.read_text("utf-8").split("## Amendment (2026-08-31)", 1)[0]
    assert "*grandfathered*, *blocking*" not in ruling, "Ruling 4 prose still five-set"
    assert "grandfathered | blocking" not in ruling, "seam diagram still five-set"


def test_the_amendment_quotes_the_original_ruling() -> None:
    """A recorded decision, never a silent text edit — the ADR convention.

    The superseded wording must survive in the amendment so the change is
    auditable by someone reading only this file.
    """
    text = _ADR.read_text("utf-8")
    assert "## Amendment (2026-08-31)" in text
    amendment = text.split("## Amendment (2026-08-31)", 1)[1]
    assert "compliant | violated | exempt | grandfathered | blocking" in amendment, (
        "the amendment must quote the original five-set for the record"
    )


def test_the_adr_cites_these_checks_in_its_enforced_by_block() -> None:
    """Otherwise the invariant exists but the ADR does not claim it.

    ADR-0143 is Accepted/enforced; an enforcement anchor nothing cites cannot
    keep the ruling from rotting.
    """
    text = _ADR.read_text("utf-8")
    header = text.split("**Binds:**", 1)[0]
    assert "test_adr0143_decision_shape.py" in header
