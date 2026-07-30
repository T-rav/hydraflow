"""Minimal fakes for builders that touch external deps during prompt rendering.

Each fake is the smallest object that satisfies the attribute/method surface the
builder actually calls. Do not add behavior here — if a builder reaches into
the fake in a way not covered, extend the fake with a named variant instead of
making the default smarter.

Some builders take a domain dataclass/model rather than plain scalars
(``SpecReviewInput``, ``RefinementIssue``, ``MergedChange``, ``list[Term]``).
``audit_prompts._coerce_task_dicts`` only knows Task/PRInfo/GitHubIssue/
EscalationContext, so those arguments are supplied here as named shapes instead.
All of them belong to one worked scenario — the "weekly escape digest" feature
(issue #9812, duplicate #9877, merged PR #9820) — so the fixtures that use them
read as a coherent trace through the factory rather than unrelated toy data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from adr_drift_triage_llm import TriageContext
from audit.models import AuditSample, MergedChange

# `_DirectionProposal` is module-private to decomposition_council, but it is the
# literal argument type of `_build_validation_prompt` — a structural stand-in
# would silently drift from the real council payload, so the fake uses it.
from decomposition_council import _DirectionProposal
from disturbance.burndown import BurndownUnit
from disturbance.registry import DIMENSIONS
from implement_spec_reviewer import SpecReviewInput
from issue_refinement import RefinementIssue
from models import (
    ConversationTurn,
    NewIssueSpec,
    ProductDirection,
    ShapeConversation,
    ShapeResult,
)
from review_advisor import FocusArea, PostVerifyInput, PreFlightInput, ReviewPlan
from term_proposer_llm import DraftContext
from ubiquitous_language import BoundedContext, Candidate, Term, TermKind


@dataclass
class _EmptyRepoWikiStore:
    def get_entries(self) -> list[Any]:
        return []

    def query(self, *_args: Any, **_kwargs: Any) -> list[Any]:
        return []


_MINIMAL_MANIFEST = [
    "src/agent.py",
    "src/reviewer.py",
    "src/triage.py",
]


# ---------------------------------------------------------------------------
# Worked scenario: the "weekly escape digest" feature
#
# Issue #9812 asks the factory to surface upheld sampled-audit disagreements as
# a weekly digest on the dashboard Insights tab. #9877 is a near-duplicate filed
# on top of it. PR #9820 is the merge that landed the aggregation helper.
# ---------------------------------------------------------------------------

# Fixed ids/timestamps: the audit writes rendered snapshots to
# tests/fixtures/prompts/rendered/ and cross-checks them against a canary trace
# by edit distance. Anything that changes per render (ULID defaults, now()) would
# show up as drift, so every field the prompt renders is pinned.
_UL_TERMS_ESCAPE_DIGEST: list[Term] = [
    Term(
        id="01JZ8Q4K7T3W9B2M5N6P8R0S1T",
        name="SampledAuditLoop",
        kind=TermKind.LOOP,
        bounded_context=BoundedContext.CARETAKER,
        definition=(
            "Caretaker loop that re-audits a governed sample of merged PRs with "
            "fresh context and no sight of the original gauntlet verdicts, so the "
            "disagreement rate is an independent bound on escaped defects rather "
            "than a self-confirming replay of the first review."
        ),
        code_anchor="src/sampled_audit_loop.py:SampledAuditLoop",
        invariants=[
            "Never edits code, opens a fix PR, or gates a merge (read-only sensor).",
            "The auditor prompt never contains an original-verdict token.",
        ],
        created_at="2026-06-02T09:14:00+00:00",
        updated_at="2026-07-19T11:02:00+00:00",
        confidence="accepted",
    ),
    Term(
        id="01JZ8Q5M2E4X7C1H6K9T3B5D8F",
        name="AuditSample",
        kind=TermKind.ENTITY,
        bounded_context=BoundedContext.CARETAKER,
        definition=(
            "One append-only audit_samples.jsonl row: the adversarial verdict on a "
            "single sampled merge plus the input_sources manifest that proves the "
            "auditor saw only the merged diff, the linked spec, and repo state."
        ),
        code_anchor="src/audit/models.py:AuditSample",
        invariants=[
            "input_sources is exactly AUDIT_INPUT_SOURCES — no verdict contamination.",
        ],
        created_at="2026-06-02T09:15:00+00:00",
        updated_at="2026-07-19T11:02:00+00:00",
        confidence="accepted",
    ),
    Term(
        id="01JZ8Q6P9R2V5Y8B1D4G7J0M3Q",
        name="EscapeLedger",
        kind=TermKind.AGGREGATE,
        bounded_context=BoundedContext.CARETAKER,
        definition=(
            "Append-only ledger of escaped defects — problems that reached a merged "
            "commit despite the gauntlet. Upheld sampled-audit disagreements are "
            "cross-linked into it with detection_source 'sampled-audit'."
        ),
        code_anchor="src/escape/ledger.py:EscapeLedger",
        aliases=["escape log"],
        created_at="2026-05-11T16:40:00+00:00",
        updated_at="2026-07-22T08:31:00+00:00",
        confidence="accepted",
    ),
    Term(
        id="01JZ8Q7S4T6W9Z2C5F8H1K4N7R",
        name="DisagreementObservation",
        kind=TermKind.VALUE_OBJECT,
        bounded_context=BoundedContext.CARETAKER,
        definition=(
            "One point in the Shewhart rate-control series: the per-tick "
            "disagreement count and sample size the governor uses to raise or lower "
            "the sampling rate around DEFAULT_BASE_RATE."
        ),
        code_anchor="src/audit/models.py:DisagreementObservation",
        created_at="2026-06-02T09:16:00+00:00",
        updated_at="2026-07-19T11:02:00+00:00",
    ),
    # Decoy: shares the word "review" with the entry below but is a Builder-side
    # runner the entry does not actually discuss. A fixture where every listed
    # term is a true match cannot exercise the "when in doubt, exclude" rule.
    Term(
        id="01JZ8Q8V7X9A2D5G8K1N4Q7T0W",
        name="PlanReviewer",
        kind=TermKind.RUNNER,
        bounded_context=BoundedContext.BUILDER,
        definition=(
            "Builder-side runner that reviews a generated implementation plan "
            "against the issue before the implement phase starts, returning "
            "approve/revise with findings."
        ),
        code_anchor="src/plan_reviewer.py:PlanReviewer",
        created_at="2026-03-08T12:00:00+00:00",
        updated_at="2026-07-01T10:20:00+00:00",
        confidence="accepted",
    ),
]


_ESCAPE_DIGEST_ISSUE_BODY = """\
## Problem

Upheld sampled-audit disagreements land in `escape_ledger.jsonl` and nowhere
else. Reading them today means SSHing to the host and `jq`-ing a JSONL file, so
nobody reads them, and the escape rate the loop exists to measure is invisible
to the people deciding whether the gauntlet is working.

## Requested

1. Aggregate `EscapeRecord` rows into ISO week buckets (Monday-start, UTC).
2. Per bucket, report: total escapes, count by `detection_source`, count by
   blast-radius stratum, and the three highest-stratum PR numbers.
3. Expose the aggregate at `GET /api/insights/escape-digest?weeks=N`
   (`weeks` defaults to 8, clamped to 1..26).
4. Render it on the Insights tab as a table, newest week first, with a sparkline
   of the weekly totals.
5. An empty ledger must render an explicit "no escapes recorded" state, not an
   empty table and not a 500.

## Out of scope

- Changing the sampling rate or the governor.
- Emailing or Slacking the digest (separate issue).

## Acceptance

- `weeks` outside 1..26 returns 422 with a message naming the bound.
- A record whose `detected_at` is unparseable is counted in an `unknown` bucket
  and logged once per digest build, not dropped silently.
"""

_ESCAPE_DIGEST_PLAN = """\
## Task 1 — Aggregation helper (pure)

Add `src/escape/digest.py`:

- `WeekBucket` frozen dataclass: `iso_week: str`, `total: int`,
  `by_source: dict[str, int]`, `by_stratum: dict[str, int]`,
  `top_prs: tuple[int, ...]`.
- `build_digest(records: Iterable[EscapeRecord], *, weeks: int) -> list[WeekBucket]`
  — bucket by ISO week from `detected_at` (parse with `datetime.fromisoformat`,
  normalize to UTC), newest first, at most `weeks` buckets.
- Unparseable `detected_at` → the literal `"unknown"` bucket, logged once.

Unit tests: empty input, single record, two records in the same week, records
spanning a year boundary (2025-W01 vs 2024-W52), unparseable timestamp.

## Task 2 — Read model + route

- `EscapeLedger.read_all()` already streams rows; add no I/O to `digest.py`.
- Register `GET /api/insights/escape-digest` in `src/server_routes_insights.py`.
- Validate `weeks` with `Query(default=8, ge=1, le=26)` so FastAPI returns 422.

## Task 3 — Insights tab UI

- Table + sparkline in the existing Insights partial; empty state copy
  "No escapes recorded in the last N weeks."

## Task 4 — Docs

- Wiki entry under `docs/wiki/patterns.md` describing the digest and how the
  disagreement bound relates to the escape rate.
"""

_ESCAPE_DIGEST_SPEC_REVIEW_DIFF = """\
diff --git a/src/escape/digest.py b/src/escape/digest.py
new file mode 100644
index 0000000..3b9a1c4
--- /dev/null
+++ b/src/escape/digest.py
@@ -0,0 +1,58 @@
+\"\"\"Weekly aggregation of escape-ledger records (#9812).\"\"\"
+
+from __future__ import annotations
+
+import logging
+from collections import Counter, defaultdict
+from dataclasses import dataclass
+from datetime import datetime
+from typing import Iterable
+
+from escape.models import EscapeRecord
+
+logger = logging.getLogger("hydraflow.escape.digest")
+
+
+@dataclass(frozen=True)
+class WeekBucket:
+    iso_week: str
+    total: int
+    by_source: dict[str, int]
+    top_prs: tuple[int, ...]
+
+
+def build_digest(records: Iterable[EscapeRecord], *, weeks: int = 8) -> list[WeekBucket]:
+    grouped: dict[str, list[EscapeRecord]] = defaultdict(list)
+    for rec in records:
+        stamp = datetime.fromisoformat(rec.detected_at)
+        year, week, _ = stamp.isocalendar()
+        grouped[f"{year}-W{week:02d}"].append(rec)
+
+    buckets: list[WeekBucket] = []
+    for iso_week in sorted(grouped, reverse=True)[:weeks]:
+        rows = grouped[iso_week]
+        sources = Counter(r.detection_source for r in rows)
+        buckets.append(
+            WeekBucket(
+                iso_week=iso_week,
+                total=len(rows),
+                by_source=dict(sources),
+                top_prs=tuple(r.pr_number for r in rows[:3]),
+            )
+        )
+    return buckets
diff --git a/src/server_routes_insights.py b/src/server_routes_insights.py
index 8a41f02..d17c9be 100644
--- a/src/server_routes_insights.py
+++ b/src/server_routes_insights.py
@@ -14,6 +14,7 @@ from fastapi import APIRouter, Query

 from config import HydraFlowConfig
+from escape.digest import build_digest
 from escape.ledger import EscapeLedger

 router = APIRouter(prefix="/api/insights", tags=["insights"])
@@ -61,3 +62,12 @@ async def gate_health() -> dict[str, object]:
     return {"gates": payload}
+
+
+@router.get("/escape-digest")
+async def escape_digest(weeks: int = 8) -> dict[str, object]:
+    config = HydraFlowConfig()
+    ledger = EscapeLedger(config.diagnostics_dir)
+    buckets = build_digest(ledger.read_all(), weeks=weeks)
+    return {"weeks": weeks, "buckets": [b.__dict__ for b in buckets]}
diff --git a/tests/test_escape_digest.py b/tests/test_escape_digest.py
new file mode 100644
index 0000000..9c2f7ab
--- /dev/null
+++ b/tests/test_escape_digest.py
@@ -0,0 +1,21 @@
+from escape.digest import build_digest
+from escape.models import EscapeRecord
+
+
+def _rec(pr: int, when: str, source: str = "sampled-audit") -> EscapeRecord:
+    return EscapeRecord(pr_number=pr, detected_at=when, detection_source=source)
+
+
+def test_build_digest_groups_two_records_in_one_week():
+    buckets = build_digest([_rec(1, "2026-07-20T10:00:00+00:00"),
+                            _rec(2, "2026-07-22T10:00:00+00:00")])
+    assert len(buckets) == 1
+    assert buckets[0].total == 2
+
+
+def test_build_digest_orders_weeks_newest_first():
+    buckets = build_digest([_rec(1, "2026-07-06T10:00:00+00:00"),
+                            _rec(2, "2026-07-20T10:00:00+00:00")])
+    assert [b.iso_week for b in buckets] == ["2026-W30", "2026-W28"]
"""

_SPEC_REVIEW_INPUT_ESCAPE_DIGEST = SpecReviewInput(
    issue_number=9812,
    issue_title=(
        "Surface sampled-audit escapes as a weekly digest on the Insights tab"
    ),
    issue_body=_ESCAPE_DIGEST_ISSUE_BODY,
    plan=_ESCAPE_DIGEST_PLAN,
    diff=_ESCAPE_DIGEST_SPEC_REVIEW_DIFF,
    commits=2,
    error=(
        "quality gate failed after 2 attempts: 1 failing test "
        "(tests/test_escape_digest.py::test_build_digest_orders_weeks_newest_first) "
        "and ruff F401 on src/server_routes_insights.py"
    ),
)


_REFINEMENT_ISSUE_9812 = RefinementIssue(
    number=9812,
    title="Surface sampled-audit escapes as a weekly digest on the Insights tab",
    body="""\
Upheld sampled-audit disagreements only exist in `escape_ledger.jsonl`. Nobody
reads a JSONL file on the host, so the escape rate the loop exists to measure
never reaches the humans deciding whether the gauntlet is working.

Asking for: ISO-week aggregation of `EscapeRecord` rows (counts by
`detection_source` and blast-radius stratum, top three PRs per week), a
`GET /api/insights/escape-digest?weeks=N` endpoint with `weeks` clamped to
1..26, and a table plus sparkline on the Insights tab.

Evidence: `escape_ledger.jsonl` on the 2026-07-19 host has 41 rows, 17 of them
`detection_source: sampled-audit`, and none of them appear anywhere in the UI.
Cross-refs ADR-0115 (adjudication) and the sampled-audit governance notes.
""",
    labels=("hydraflow-find", "area:observability", "P2"),
    updated_at="2026-07-19T11:02:00Z",
)

_REFINEMENT_ISSUE_9877 = RefinementIssue(
    number=9877,
    title="Weekly digest of adversarial-audit disagreements missing from Insights",
    body="""\
The Insights tab shows gate health and review-insight patterns but nothing about
the adversarial re-audit. `SampledAuditLoop` records a verdict per sampled merge
and cross-links upheld disagreements into the escape ledger, and none of that is
visible without reading `escape_ledger.jsonl` by hand on the host.

Want a weekly rollup on Insights: escapes per ISO week, split by detection
source, so a reviewer can see whether the escape rate is trending up after a
gauntlet change.

Noticed while triaging the 41-row ledger on 2026-07-19 — 17 rows have
`detection_source: sampled-audit` and none surface in the dashboard.
""",
    labels=("hydraflow-find", "area:observability"),
    updated_at="2026-07-24T07:48:00Z",
)


_MERGED_CHANGE_9820 = MergedChange(
    pr_number=9820,
    merge_sha="7c1f9ad3e5b84a02c6d9f1e7b3a5c8d0e2f4a6b8",
    subject="Add weekly escape-digest aggregation to EscapeLedger (#9812)",
    changed_paths=(
        "src/escape/digest.py",
        "src/escape/ledger.py",
        "src/server_routes_insights.py",
        "src/static/js/insights.js",
        "tests/test_escape_digest.py",
        "tests/test_server_routes_insights.py",
        "docs/wiki/patterns.md",
    ),
    merged_at="2026-07-24T14:22:09+00:00",
    body=(
        "Closes #9812. Adds `escape.digest.build_digest`, wires "
        "`GET /api/insights/escape-digest`, renders the weekly table on the "
        "Insights tab. Gauntlet: plan review approved, spec review compliant, "
        "quality green."
    ),
)


# ---------------------------------------------------------------------------
# Same scenario, earlier and later in the lifecycle: shape (#9812 before it was
# specified), the review advisor's two seams over the escape-digest diff, and
# the decomposition council splitting #9812 after the implement phase stalled.
#
# Multi-turn and council builders take a conversation/proposal object rather
# than scalars, so those arguments live here while the fixtures keep the plain
# args (task, stall_context, doc_context, depth, guidance) in JSON.
# ---------------------------------------------------------------------------

# Live operator steering on #9812, as it would arrive from a `/steer` comment.
# Threaded into every prompt that folds `fenced_steering_guidance`.
_STEERING_GUIDANCE_9812 = (
    "Keep this to a read-only view for now. I want the escape trend visible to "
    "the people arguing about gauntlet changes, not a new alerting surface that "
    "pages someone at 2am off a number we do not trust yet. If the aggregation "
    "and the UI cannot both land this cycle, land the aggregation and the API "
    "and leave the tab alone."
)


_SHAPE_CONVERSATION_ESCAPE_DIGEST = ShapeConversation(
    issue_number=9812,
    status="exploring",
    started_at="2026-07-19T11:20:00Z",
    last_activity_at="2026-07-21T15:06:00Z",
    turns=[
        ConversationTurn(
            role="agent",
            timestamp="2026-07-19T11:20:00Z",
            source="shape:turn-1",
            content="""\
Three directions, all reading the same source (`escape_ledger.jsonl`, 41 rows
on the 2026-07-19 host, 17 of them `detection_source: sampled-audit`). They
differ in who they are for and what decision they support.

**A. Weekly trend on the Insights tab.** Aggregate `EscapeRecord` rows into ISO
week buckets and render a table plus a sparkline next to the existing gate-health
panel. User Advocate: the person asking "did that gauntlet change help?" gets an
answer in one glance. Technical Realist: `EscapeLedger.read_all()` already
streams rows and `src/server_routes_insights.py` already has a router, so this
is one pure aggregation module plus a route plus a partial. Scope Hawk: the MVP
is the aggregation and the endpoint; the sparkline is optional.

**B. Per-PR escape badge in the merged-PR list.** Mark each merged PR that a
later audit found a defect in, linking to the `AuditSample` that found it.
User Advocate: makes an escape concrete and attributable instead of a statistic.
Technical Realist: needs a PR-number index over the ledger and a join in the
merged-PR view. Market Strategist: this is the one a reviewer would screenshot.
Scope Hawk: no aggregation needed at all, which makes it smaller than A.

**C. Control-limit alerting on the escape rate.** The governor already computes a
Shewhart series for the sampling rate; run the same limits over the weekly escape
count and notify when a week breaches. User Advocate: nobody has to remember to
look. Technical Realist: reuses `DisagreementObservation` machinery, but the
alert is only as good as the rate, and with 41 rows total the series is far too
short to set limits from.

My read: A and B answer different questions and are not really competitors — A is
"is the gauntlet working", B is "what escaped on my PR". C is downstream of both
and premature. Which question is actually blocking a decision right now?""",
        ),
        ConversationTurn(
            role="human",
            timestamp="2026-07-20T09:48:00Z",
            source="issue-comment",
            signal="scope_narrow",
            content="""\
"Is the gauntlet working" is the one blocking a decision. We have three open
proposals to add gates and no way to tell whether the two we already added did
anything. So A.

Drop C outright. You said it yourself — 41 rows will not support control limits,
and an alert we do not believe will get muted in a week and then it is noise
forever.

B I want, but later. Do not fold it in.

Two things I need from A that you did not mention. First: the split. A raw count
per week is not enough, I need it broken down by `detection_source`, because a
sampled-audit escape and a customer-reported escape mean completely different
things about the gauntlet. Second: what happens on a week with zero escapes, and
on an empty ledger? I do not want a blank panel that I cannot tell apart from a
broken endpoint.""",
        ),
        ConversationTurn(
            role="agent",
            timestamp="2026-07-20T13:31:00Z",
            source="shape:turn-3",
            content="""\
Both are real and the second one changes the shape more than it looks.

On the split: `EscapeRecord.detection_source` is already populated at write time,
so a per-bucket `Counter` over it is free. I would add the blast-radius stratum
alongside it for the same cost — `src/escape/ledger.py:88` already carries the
stratum on the record, and "the escapes are all LOW blast radius" is a
materially different story from "two of them were STRUCTURAL". Without the
stratum, a week with four cosmetic escapes and a week with one architectural one
look identical.

On the empty and zero cases: there are three distinguishable states and the API
has to keep them apart, which means the endpoint cannot just return a list.
1. The ledger has rows, this week has none — a real zero, which should render as
   a zero row so the sparkline has a point.
2. The ledger is empty — nothing has ever escaped, or nothing was ever recorded.
   Render explicit copy, not an empty table.
3. The endpoint failed. Must not look like either of the above.

That argues for the payload carrying the requested window and the buckets
separately, so an empty `buckets` with a valid `weeks` is unambiguous.

One more thing I found while reading the ledger: `detected_at` on
sampled-audit rows is the *audit* timestamp, not the merge timestamp. If we
bucket on it as-is, every escape lands in the week the auditor happened to run,
which is exactly the wrong axis for a trend. Fixing that is a change to
`src/sampled_audit_loop.py`, not to the digest.""",
        ),
        ConversationTurn(
            role="human",
            timestamp="2026-07-21T15:06:00Z",
            source="issue-comment",
            signal="positive",
            content="""\
Yes to all of it, including the stratum and the three-states point. The
`detected_at` finding is the most valuable thing in this conversation — bucketing
on audit time would have given us a chart that looked fine and meant nothing.
Fix it in the same change and say so in the PR body, because anyone reading the
ledger afterwards needs to know the column changed meaning.

Write it up. Cap the window so nobody can ask for 400 weeks and table-scan the
ledger, and make the bad-window case an obvious error rather than a clamp — I
would rather the UI show me a 422 than silently give me a different window than
the one I asked for.""",
        ),
    ],
)


_SHAPE_ADVOCATE_RESULT_ESCAPE_DIGEST = ShapeResult(
    issue_number=9812,
    directions=[
        ProductDirection(
            name="Weekly trend on the Insights tab",
            approach=(
                "Aggregate `EscapeRecord` rows into ISO week buckets (Monday-"
                "start, UTC), split each bucket by `detection_source` and by "
                "blast-radius stratum, and render the series as a table plus a "
                "sparkline beside the existing gate-health panel. Serve it from "
                "`GET /api/insights/escape-digest?weeks=N` with the window "
                "carried in the payload so an empty result is distinguishable "
                "from a failure."
            ),
            tradeoffs=(
                "Directly answers the question that is blocking three open gate "
                "proposals, and reuses `EscapeLedger.read_all()` plus the "
                "existing insights router, so the new surface is one pure module. "
                "Costs a full ledger read per request unless the window is "
                "capped, and a weekly bucket is a coarse instrument — a "
                "regression inside a week is invisible until the week closes."
            ),
            effort="medium",
            risk="low",
            differentiator=(
                "Modest. The value is that it makes an existing sensor legible "
                "rather than adding a new one."
            ),
        ),
        ProductDirection(
            name="Per-PR escape badge in the merged-PR list",
            approach=(
                "Index the ledger by PR number and mark every merged PR a later "
                "audit found a defect in, linking through to the `AuditSample` "
                "that found it."
            ),
            tradeoffs=(
                "Makes an escape concrete and attributable instead of a "
                "statistic, and needs no aggregation at all, so it is the "
                "smallest of the three. But it answers 'what escaped on my PR', "
                "not 'is the gauntlet working', and it puts a scarlet letter on "
                "individual PRs, which changes how people behave around the "
                "audit sensor."
            ),
            effort="low",
            risk="medium",
            differentiator=(
                "Strong on its own terms — this is the view a reviewer would "
                "screenshot — but it is orthogonal to the trend question."
            ),
        ),
        ProductDirection(
            name="Control-limit alerting on the escape rate",
            approach=(
                "Run the governor's existing Shewhart limits over the weekly "
                "escape count and notify when a week breaches, reusing the "
                "`DisagreementObservation` series machinery."
            ),
            tradeoffs=(
                "Nobody has to remember to look, which is the only option with "
                "that property. But the alert is only as trustworthy as the rate, "
                "and 41 total ledger rows is far too short a series to set limits "
                "from. An alert nobody believes gets muted once and stays muted."
            ),
            effort="medium",
            risk="high",
            differentiator="",
        ),
    ],
    recommendation=(
        "Ship the weekly trend on the Insights tab. It is the only direction that "
        "answers the question currently blocking a decision — whether the two "
        "gates already added changed the escape rate — and it does so by making "
        "an existing sensor legible rather than adding a new one. The per-PR badge "
        "is a genuinely good view and should be a follow-up: it answers a "
        "different question and is not a prerequisite. Control-limit alerting is "
        "downstream of both and premature at 41 ledger rows; setting limits from a "
        "series that short produces an alert that gets muted and never unmuted. "
        "One dependency the trend work must absorb: `detected_at` on sampled-audit "
        "rows is currently the audit timestamp, not the merge timestamp, so "
        "bucketing on it unchanged would chart when the auditor ran instead of "
        "when the defect shipped."
    ),
)


# The review advisor sees the escape-digest implementation plus the
# `sampled_audit_loop` change the shape conversation asked for. The loop path
# matches CRITICAL_PATH_GLOBS ("src/*_loop.py"), which is what makes the
# post-verify builder emit its second-order failure-check section.
_ESCAPE_DIGEST_LOOP_HUNK = """\
diff --git a/src/sampled_audit_loop.py b/src/sampled_audit_loop.py
index 2d8e4b1..a90c7f5 100644
--- a/src/sampled_audit_loop.py
+++ b/src/sampled_audit_loop.py
@@ -211,10 +211,18 @@ class SampledAuditLoop:
     async def _record_upheld(self, sample: AuditSample) -> None:
-        self._ledger.append(
-            EscapeRecord(
-                pr_number=sample.pr_number,
-                detected_at=sample.audited_at,
-                detection_source="sampled-audit",
-            )
-        )
+        # #9812: bucket on when the defect SHIPPED, not when the auditor ran.
+        # detected_at was the audit timestamp, so every escape landed in
+        # whatever week the sampler happened to pick it up and the weekly trend
+        # measured auditor scheduling instead of gauntlet quality.
+        self._ledger.append(
+            EscapeRecord(
+                pr_number=sample.pr_number,
+                detected_at=sample.merged_at,
+                detection_source="sampled-audit",
+                stratum=sample.blast_radius,
+            )
+        )
+        self._digest_cache.invalidate()
"""

_ESCAPE_DIGEST_REVIEW_DIFF = _ESCAPE_DIGEST_SPEC_REVIEW_DIFF + _ESCAPE_DIGEST_LOOP_HUNK

_ESCAPE_DIGEST_REVIEW_SPEC = (
    _ESCAPE_DIGEST_ISSUE_BODY
    + """
## Shaped direction (from the design conversation on #9812)

Weekly trend on the Insights tab, read-only. Each bucket splits by
`detection_source` AND by blast-radius stratum — a week of four cosmetic escapes
and a week with one structural escape must not look identical. The payload
carries the requested window alongside the buckets so three states stay
distinguishable: a real zero week, an empty ledger, and a failed endpoint. A
window outside 1..26 is a 422, deliberately not a clamp, so the UI never shows a
different window than the one it asked for.

Absorbed dependency: `detected_at` on sampled-audit rows was the audit
timestamp, not the merge timestamp. Bucketing on it unchanged would chart when
the auditor ran rather than when the defect shipped, so `SampledAuditLoop`
writes `merged_at` instead and the column changes meaning for every row written
from now on.
"""
)

_ESCAPE_DIGEST_EXECUTOR_VERDICT = """\
Reviewed the escape-digest change across 4 files (+96/-9), attempt 2.

Raised and fixed this attempt:
1. `build_digest` called `datetime.fromisoformat(rec.detected_at)` unguarded, so
   one malformed timestamp raised out of the whole digest instead of landing in
   the `unknown` bucket the acceptance criteria require. Now wrapped, logged once
   per build.
2. The route took `weeks: int = 8` with no bounds, so `weeks=400` table-scanned
   the ledger and `weeks=-3` silently returned the OLDEST buckets via a negative
   slice. Now `Query(default=8, ge=1, le=26)`, which FastAPI turns into a 422.

Raised and dismissed:
3. `WeekBucket` has `by_source` but no `by_stratum`, so requirement 2's
   blast-radius split is missing. Dismissed as a follow-up — the shaped
   direction called for it, but the field is additive and the table renders
   without it.
4. `top_prs=tuple(r.pr_number for r in rows[:3])` takes the first three rows in
   ledger order, not the three highest-stratum PRs. Dismissed as cosmetic; the
   ordering is stable so the panel is not misleading.
5. An empty ledger returns `buckets: []` with no explicit empty state.
   Dismissed — the Insights partial renders an empty table, which I judged close
   enough to requirement 5.
6. The `sampled_audit_loop` change writes `merged_at` into `detected_at`.
   Dismissed as intentional and specified.

Verdict: APPROVE. `make test` green (1841 passed), ruff clean, no happy-path
behaviour change for a well-formed ledger.
"""

_ESCAPE_DIGEST_EXECUTOR_FIX_DIFF = """\
diff --git a/src/escape/digest.py b/src/escape/digest.py
index 3b9a1c4..e70b52d 100644
--- a/src/escape/digest.py
+++ b/src/escape/digest.py
@@ -30,9 +30,17 @@ def build_digest(records, *, weeks: int = 8) -> list[WeekBucket]:
     grouped: dict[str, list[EscapeRecord]] = defaultdict(list)
+    unparseable = 0
     for rec in records:
-        stamp = datetime.fromisoformat(rec.detected_at)
-        year, week, _ = stamp.isocalendar()
-        grouped[f"{year}-W{week:02d}"].append(rec)
+        try:
+            stamp = datetime.fromisoformat(rec.detected_at)
+        except (TypeError, ValueError):
+            unparseable += 1
+            grouped["unknown"].append(rec)
+            continue
+        year, week, _ = stamp.isocalendar()
+        grouped[f"{year}-W{week:02d}"].append(rec)
+    if unparseable:
+        logger.warning("escape digest: %d record(s) with unparseable detected_at", unparseable)
diff --git a/src/server_routes_insights.py b/src/server_routes_insights.py
index d17c9be..4f2a1b8 100644
--- a/src/server_routes_insights.py
+++ b/src/server_routes_insights.py
@@ -66,7 +66,9 @@ async def gate_health() -> dict[str, object]:
 @router.get("/escape-digest")
-async def escape_digest(weeks: int = 8) -> dict[str, object]:
+async def escape_digest(
+    weeks: int = Query(default=8, ge=1, le=26),
+) -> dict[str, object]:
     config = HydraFlowConfig()
     ledger = EscapeLedger(config.diagnostics_dir)
     buckets = build_digest(ledger.read_all(), weeks=weeks)
"""

_ESCAPE_DIGEST_REVIEW_PLAN = ReviewPlan(
    risk_summary=(
        "Two changes of very different blast radius in one diff. The digest "
        "module and its route are additive and read-only — worst case an "
        "Insights panel is wrong. The `sampled_audit_loop` hunk redefines what "
        "`detected_at` means on every sampled-audit ledger row written from now "
        "on, and it edits the one loop the factory relies on to measure its own "
        "escape rate. A defect there is silent and corrupts the sensor rather "
        "than the view."
    ),
    focus_areas=[
        FocusArea(
            description=(
                "`detected_at` changes meaning mid-ledger, with no migration "
                "and no marker on existing rows"
            ),
            files=["src/sampled_audit_loop.py", "src/escape/digest.py"],
            rationale=(
                "Rows written before this change carry audit time; rows after "
                "carry merge time. `build_digest` buckets both without "
                "distinguishing them, so the trend it charts is a mixture of two "
                "different axes. Decide whether that is acceptable or whether "
                "old rows need a flag."
            ),
        ),
        FocusArea(
            description="Acceptance criteria that the diff does not implement",
            files=["src/escape/digest.py", "src/server_routes_insights.py"],
            rationale=(
                "The issue asks for a per-stratum split, top-three by stratum, "
                "and an explicit empty state. Check each against `WeekBucket` "
                "and the route payload rather than trusting the summary."
            ),
        ),
        FocusArea(
            description="Unbounded ledger read behind a request-scoped handler",
            files=["src/server_routes_insights.py"],
            rationale=(
                "The handler constructs `HydraFlowConfig()` and streams the "
                "entire ledger per request, then slices to `weeks` after "
                "grouping. Confirm the bound is enforced before the read, not "
                "after."
            ),
        ),
        FocusArea(
            description="New `_digest_cache.invalidate()` call inside the loop",
            files=["src/sampled_audit_loop.py"],
            rationale=(
                "A cache handle appears in the loop with no construction shown "
                "in the diff. Confirm it exists, is not None on the sandbox "
                "path, and that a failure to invalidate cannot raise out of "
                "`_record_upheld` and abort the audit tick."
            ),
        ),
    ],
    rubric=[
        "Does every acceptance criterion in the issue map to a line in the diff?",
        "Can a malformed ledger row abort the whole digest?",
        "Is the `weeks` bound enforced, and is an out-of-range value an error "
        "rather than a silent clamp?",
        "Can anything in the loop hunk raise and stop the audit tick recording?",
        "Do the tests assert the failure paths, or only the two happy-path "
        "grouping cases?",
    ],
    escalation_signals=[
        "a shaped requirement dismissed as a follow-up without being recorded "
        "as out of scope",
        "a persisted field changing meaning without a migration or a marker on "
        "existing rows",
        "new code in a caretaker loop that can raise inside the tick body",
        "an empty result that is indistinguishable from a failed request",
    ],
)

_PREFLIGHT_INPUT_ESCAPE_DIGEST = PreFlightInput(
    surface="review",
    diff=_ESCAPE_DIGEST_REVIEW_DIFF,
    spec=_ESCAPE_DIGEST_REVIEW_SPEC,
    related_paths=[
        "src/escape/digest.py",
        "src/escape/ledger.py",
        "src/escape/models.py",
        "src/sampled_audit_loop.py",
        "src/server_routes_insights.py",
        "src/static/js/insights.js",
        "tests/test_escape_digest.py",
        "tests/test_sampled_audit_loop.py",
    ],
    prior_attempts=1,
    issue_number=9812,
    human_guidance=_STEERING_GUIDANCE_9812,
)

_POSTVERIFY_INPUT_ESCAPE_DIGEST = PostVerifyInput(
    surface="review",
    diff=_ESCAPE_DIGEST_REVIEW_DIFF,
    spec=_ESCAPE_DIGEST_REVIEW_SPEC,
    executor_verdict_summary=_ESCAPE_DIGEST_EXECUTOR_VERDICT,
    executor_fix_diff=_ESCAPE_DIGEST_EXECUTOR_FIX_DIFF,
    pre_flight_plan=_ESCAPE_DIGEST_REVIEW_PLAN,
    attempt_number=2,
    issue_number=9812,
    lens="correctness",
    human_guidance=_STEERING_GUIDANCE_9812,
)


# The direction pass's candidate split of #9812 after the implement phase
# stalled twice on the quality gate. Child 1 is the salvage slice.
_DIRECTION_PROPOSAL_ESCAPE_DIGEST = _DirectionProposal(
    epic_title=(
        "Epic: Surface sampled-audit escapes as a weekly digest on the Insights tab"
    ),
    epic_body="""\
## Sub-issues

- [ ] Land the escape-digest aggregation helper and its passing tests
- [ ] Bucket on merge time, not audit time, in SampledAuditLoop
- [ ] Serve the digest with a bounded window and a distinguishable empty state
- [ ] Render the weekly table and sparkline on the Insights tab

The parent attempted the pure aggregation, the loop semantics change, the route
and the UI in one branch, and stalled on the quality gate twice — a failing
year-boundary bucketing test plus a ruff F401 in the route module. The
aggregation helper's own tests were green both times; everything that failed
sits in the three children after it.
""",
    rationale=(
        "Considered three lenses. Layer boundaries (aggregation / persistence / "
        "transport / UI) is close to the right answer but would put the loop "
        "semantics change in the same child as the ledger read, and those have "
        "very different blast radius — one is additive, the other redefines a "
        "persisted field. Vertical independently-shippable slices does not work "
        "here: there is exactly one user-visible slice, so slicing vertically "
        "yields one child and defeats the split. Isolate-the-failing-part wins. "
        "The aggregation helper passed its tests on both stalled attempts and is "
        "reviewable on its own, so it becomes a salvage child; the year-boundary "
        "bucketing failure, the unbounded window, and the untouched UI each fail "
        "for unrelated reasons and can be attacked independently once the helper "
        "is merged."
    ),
    children=[
        NewIssueSpec(
            title="Land the escape-digest aggregation helper (salvage)",
            body="""\
Extract the slice of the stalled branch that was already green and merge it
alone, with no new work folded in.

In scope: `src/escape/digest.py` with `WeekBucket` and `build_digest`, including
the per-stratum split the shaped direction asked for, plus the two grouping
tests that passed on both stalled attempts
(`test_build_digest_groups_two_records_in_one_week`,
`test_build_digest_orders_weeks_newest_first`).

Out of scope: the year-boundary case, the route, the loop change, the UI. The
helper stays pure — no I/O, no config, no FastAPI import.

Done when: `build_digest` is importable and unit-tested in isolation, `make
quality` is green, and nothing outside `src/escape/digest.py` and
`tests/test_escape_digest.py` is touched.""",
            labels=["salvage", "area:observability"],
        ),
        NewIssueSpec(
            title="Bucket escapes on merge time, not audit time",
            body="""\
`SampledAuditLoop._record_upheld` writes `sample.audited_at` into
`EscapeRecord.detected_at`, so an escape is attributed to the week the sampler
happened to pick the PR up rather than the week the defect shipped. Bucketing on
it unchanged produces a weekly trend that measures auditor scheduling.

This is the part of the stalled attempt with real blast radius: it redefines what
a persisted field means for every row written afterwards, in the one loop the
factory uses to measure its own escape rate.

In scope: write `merged_at`, carry the blast-radius stratum onto the record, and
decide explicitly what happens to rows already written under the old meaning —
either a marker on new rows or a documented cut-over date. Any failure in the new
code must not be able to raise out of the tick body and stop the sensor
recording.

Done when: a sampled audit of a PR merged in week N records an escape in week N,
pre-existing rows are still readable with their meaning documented, and a raising
cache invalidation cannot abort `_record_upheld`.""",
            labels=["area:observability", "caretaker"],
        ),
        NewIssueSpec(
            title="Serve the digest with a bounded window and a real empty state",
            body="""\
`GET /api/insights/escape-digest` on the stalled branch takes `weeks: int = 8`
with no bounds and returns a bare bucket list. `weeks=400` table-scans the
ledger; `weeks=-3` returns the oldest buckets through a negative slice; an empty
ledger is indistinguishable from a failed request. The ruff F401 that failed the
gate was in this module.

In scope: `Query(default=8, ge=1, le=26)` so an out-of-range window is a 422 and
not a silent clamp, the requested window echoed in the payload alongside the
buckets, and the bound applied before the ledger read rather than after grouping.

Out of scope: caching, and any change to `build_digest` itself.

Done when: `weeks` outside 1..26 returns 422 naming the bound, an empty ledger
returns a 200 whose payload states the window and an empty bucket list, and ruff
is clean.""",
            labels=["area:observability", "api"],
        ),
        NewIssueSpec(
            title="Render the weekly escape table and sparkline on Insights",
            body="""\
The stalled branch never reached the UI. This child consumes the endpoint from
the child above and is the only user-visible slice.

In scope: a table newest-week-first beside the existing gate-health panel, a
sparkline of the weekly totals, the per-source and per-stratum split visible per
row, and explicit copy for the empty-ledger state ("No escapes recorded in the
last N weeks") that cannot be confused with a failed fetch.

Out of scope: the per-PR escape badge in the merged-PR list, which the design
conversation deferred to a follow-up.

Done when: the Insights tab renders the digest against a seeded ledger, a real
zero week appears as a zero row rather than a gap, and an empty ledger shows the
empty-state copy.""",
            labels=["area:observability", "ui"],
        ),
    ],
)


# ---------------------------------------------------------------------------
# Same scenario, downstream: what the caretaker fleet did with PR #9820
# ---------------------------------------------------------------------------
# The loop-owned and subpackage builders below each read one after-effect of the
# merge above. AdrTouchpointAuditorLoop flagged PR #9820 for touching
# `src/escape/ledger.py`, which ADR-0114 cites, and rolled the finding up as
# issue #9903. SampledAuditLoop sampled the same merge, re-audited it, and
# disagreed. A human filed the bucketing defect the auditor named as bug #9861,
# and the fix PR #9871 (branch `agent/issue-9861`) then went red in CI and in
# the sandbox tier. Same pinning rule as the block above: no ULID defaults, no
# now() — every rendered field is fixed so snapshots don't drift.

_ADR_0114_MARKDOWN = """# ADR-0114: The escape ledger is append-only

## Status

Accepted

## Context

The first escape store (#10231) was a mutable JSON object keyed by escape id.
Every human re-attribution overwrote the row it corrected, so by the time we
wanted to ask "how often does a first attribution turn out to be wrong?" the
evidence had been erased in place. The ledger is the factory's audit trail of
defects that got past the gauntlet; a trail that can be edited is not evidence.

Two forces pull the other way and are why this needs to be written down:

1. Derived views want a compact table. A digest, a metrics rollup, and the
   dashboard all want "current state per escape", not the full event stream.
2. Long-running hosts want the file bounded. The 2026-07 host is at 41 rows and
   180KB; a naive reader that parses the whole file per request is wasteful.

## Decision

The on-disk ledger is append-only. One JSONL row per event, appended, never
rewritten.

- A correction is a NEW row sharing the original's id (supersession), never an
  edit of the original line. `append_resolution` is the only sanctioned writer
  for human decisions and it appends.
- `EscapeLedger` never opens the ledger file for writing in a mode other than
  append. No compaction, pruning, or in-place disposition update without an ADR
  that supersedes this one.
- Readers collapse the stream to a current view on read (`latest_by_escape`,
  two-stage: by id, then by `detection_ref`). Collapsing is a read concern.
- Derived views (digests, metrics, dashboard panels) are computed from a read.
  Caching a derived view IN MEMORY is explicitly allowed and expected; what is
  forbidden is a cache that becomes a second source of truth on disk.

## Consequences

- The ledger grows monotonically. That is accepted: it is an audit trail, and
  the growth rate is bounded by the escape rate, not by traffic.
- Any consumer that wants "one row per escape" pays the collapse cost on read.
- A reviewer can always reconstruct what was believed at any point in time.

## Citations

- `src/escape/ledger.py`
- `src/escape/models.py`
- `src/jsonl_ledger.py`
"""

# PR #9820's diff, already scoped by the loop to the module ADR-0114 cites.
# The touchpoint detector cannot tell whether the added `append` override and
# the new `_digest_cache` violate the append-only decision or are the in-memory
# derived-view caching the ADR explicitly allows — which is exactly the
# judgment the TRIAGE prompt exists to make.
_LEDGER_SCOPED_DIFF_9820 = """diff --git a/src/escape/ledger.py b/src/escape/ledger.py
index 4f21a90..b8c7d13 100644
--- a/src/escape/ledger.py
+++ b/src/escape/ledger.py
@@ -18,10 +18,13 @@
 from __future__ import annotations

 import logging
+from collections.abc import Iterator
 from dataclasses import replace
 from pathlib import Path

+from escape.digest import WeekBucket, build_digest
 from escape.metrics import escape_by_id, latest_by_escape, latest_by_id
 from escape.models import EncodedAs, EscapeRecord
 from jsonl_ledger import IdentifiedJsonlLedger

@@ -40,6 +43,10 @@ class EscapeLedger(IdentifiedJsonlLedger[EscapeRecord]):

     def __init__(self, path: Path) -> None:
         super().__init__(path, EscapeRecord, logger=logger)
+        # Derived-view cache for the weekly digest route (#9812), keyed by the
+        # `weeks` window. Rebuilt from a read; never persisted. Cleared on
+        # append so a freshly recorded escape can never be served stale.
+        self._digest_cache: dict[int, list[WeekBucket]] = {}

     def read_latest(self) -> list[EscapeRecord]:
         return latest_by_escape(self.read_all())
@@ -57,6 +64,27 @@ class EscapeLedger(IdentifiedJsonlLedger[EscapeRecord]):
     def read_latest_index(self) -> dict[str, EscapeRecord]:
         return escape_by_id(self.read_all())

+    def iter_records(self) -> Iterator[EscapeRecord]:
+        # Single-pass read for the digest: build_digest only needs one pass,
+        # and the route was re-parsing the whole file per request.
+        yield from self.read_all()
+
+    def weekly_digest(self, *, weeks: int = 8) -> list[WeekBucket]:
+        cached = self._digest_cache.get(weeks)
+        if cached is not None:
+            return cached
+        buckets = build_digest(self.iter_records(), weeks=weeks)
+        self._digest_cache[weeks] = buckets
+        return buckets
+
+    def append(self, record: EscapeRecord) -> None:
+        # Invalidate the derived digest cache, then delegate. This override
+        # adds no write path of its own: the base class append is still the
+        # only thing that touches the file, still in append mode.
+        self._digest_cache.clear()
+        super().append(record)
+
     def append_resolution(
         self,
         escape_id: str,
"""

_TRIAGE_CONTEXT_PR_9820 = TriageContext(
    adr_number=114,
    adr_title="The escape ledger is append-only",
    adr_markdown=_ADR_0114_MARKDOWN,
    pr_number=9820,
    pr_diff=_LEDGER_SCOPED_DIFF_9820,
    issue_number=9903,
    issue_labels=("hydraflow-find", "adr-drift", "adr:0114"),
)


# The re-auditor's disagreement on the merged PR #9820 — three named claims of
# descending strength, so the adjudicator has something real to sort rather
# than a single obviously-right or obviously-wrong assertion.
_AUDIT_FINDING_9820 = """\
Correctness (ISO year boundary): `build_digest` keys buckets with
`f"{year}-W{week:02d}"` taken from `datetime.isocalendar()`, but sorts the keys
as strings (`sorted(grouped, reverse=True)[:weeks]`). ISO week-numbering years
do not align with calendar years: 2025-12-29 is 2026-W01. A record from
2025-12-29 therefore sorts under "2026-W01" ahead of "2025-W52", which is
correct, but a record from 2027-01-02 (2026-W53) sorts BELOW "2027-W01" and is
dropped from an 8-week window that should contain it. The merged tests cover
2026-W28 vs 2026-W30 only, so nothing exercises a year boundary.

Spec fidelity: the issue's acceptance list requires that an unparseable
`detected_at` be counted in an `unknown` bucket and logged once per digest
build. `build_digest` calls `datetime.fromisoformat(rec.detected_at)`
unguarded, so one malformed row raises ValueError out of the route handler and
returns 500 for the whole digest — the precise failure the acceptance criterion
was written to prevent. The plan's Task 1 also names `by_stratum` per bucket;
`WeekBucket` ships without that field and the route returns `b.__dict__`, so
the documented response shape is not what is served.

Style (not a defect): the route constructs `HydraFlowConfig()` per request
instead of taking the injected config. Wasteful, consistent with several
existing routes, and not what I am claiming as the escape."""

_AUDIT_SAMPLE_9820 = AuditSample(
    id="01JZ9M4T7K2B5N8Q1D4G7J0M3R",
    audited_at="2026-07-25T02:14:09+00:00",
    pr_number=9820,
    merge_sha="7c1f9ad3e5b84a02c6d9f1e7b3a5c8d0e2f4a6b8",
    blast_radius_class="core-runtime",
    verdict="disagree",
    findings=_AUDIT_FINDING_9820,
    input_sources=(
        "merged-diff:7c1f9ad",
        "issue-body:9812",
        "accepted-plan:9812",
        "repo-state:staging@7c1f9ad",
    ),
    auditor_model="claude-opus-4-6",
    sample_rate=0.12,
)


# Last three commits on `agent/issue-9861` — the in-flight fix for the
# bucketing defect the auditor named. Both the sandbox fixer and the PR-red
# repair dispatch read this through the PR port, not through their fixture.
_DIGEST_FIX_COMMIT_DIFFS = """commit 3f8a1c92  fix(digest): sort week buckets by real date, not key string
diff --git a/src/escape/digest.py b/src/escape/digest.py
index 3b9a1c4..7d2e5f8 100644
--- a/src/escape/digest.py
+++ b/src/escape/digest.py
@@ -21,6 +21,7 @@ class WeekBucket:
     iso_week: str
     total: int
     by_source: dict[str, int]
+    week_start: date
     top_prs: tuple[int, ...]

@@ -30,18 +31,20 @@ def build_digest(records, *, weeks: int = 8) -> list[WeekBucket]:
     grouped: dict[str, list[EscapeRecord]] = defaultdict(list)
     for rec in records:
-        stamp = datetime.fromisoformat(rec.detected_at)
-        year, week, _ = stamp.isocalendar()
-        grouped[f"{year}-W{week:02d}"].append(rec)
+        stamp = _parse_stamp(rec.detected_at)
+        if stamp is None:
+            grouped["unknown"].append(rec)
+            continue
+        year, week, _ = stamp.isocalendar()
+        grouped[f"{year}-W{week:02d}"].append(rec)

-    for iso_week in sorted(grouped, reverse=True)[:weeks]:
+    for iso_week in _newest_first(grouped)[:weeks]:
         rows = grouped[iso_week]

commit b71e0d45  fix(digest): unparseable detected_at goes to the unknown bucket
diff --git a/src/escape/digest.py b/src/escape/digest.py
index 7d2e5f8..a04c6b1 100644
--- a/src/escape/digest.py
+++ b/src/escape/digest.py
@@ -48,3 +48,22 @@ def build_digest(records, *, weeks: int = 8) -> list[WeekBucket]:
     return buckets
+
+
+def _parse_stamp(raw: str) -> datetime | None:
+    try:
+        return datetime.fromisoformat(raw).astimezone(UTC)
+    except Exception:  # noqa: BLE001
+        _warn_once(raw)
+        return None
+
+
+def _newest_first(grouped: dict) -> list[str]:  # type: ignore[type-arg]
+    def key(iso_week: str) -> date:
+        if iso_week == "unknown":
+            return date.min
+        year, week = iso_week.split("-W")
+        return date.fromisocalendar(int(year), int(week), 1)
+
+    return sorted(grouped, key=key, reverse=True)

commit c02d5e17  test(digest): cover the 2026-W53 boundary and the unknown bucket
diff --git a/tests/test_escape_digest.py b/tests/test_escape_digest.py
index 9c2f7ab..1e5b8d3 100644
--- a/tests/test_escape_digest.py
+++ b/tests/test_escape_digest.py
@@ -19,3 +19,18 @@ def test_build_digest_orders_weeks_newest_first():
     assert [b.iso_week for b in buckets] == ["2026-W30", "2026-W28"]
+
+
+def test_iso_year_boundary_keeps_both_weeks():
+    buckets = build_digest([_rec(1, "2027-01-02T10:00:00+00:00"),
+                            _rec(2, "2027-01-05T10:00:00+00:00")], weeks=8)
+    assert [b.iso_week for b in buckets] == ["2027-W01", "2026-W53"]
+
+
+def test_unparseable_timestamp_lands_in_unknown_bucket():
+    buckets = build_digest([_rec(1, "not-a-timestamp")], weeks=8)
+    assert [b.iso_week for b in buckets] == ["unknown"]
"""

# Sandbox-tier transcript for the same fix PR: the scenario asserts the
# pipeline's own terminal labels, so its failure reads as a pipeline
# regression rather than a unit-test failure.
_SANDBOX_SCENARIO_LOG_9871 = """\
sandbox\tscenario issue-to-merge\t2026-07-29T05:02:11Z [seed] issue #9861 opened with label hydraflow-find
sandbox\tscenario issue-to-merge\t2026-07-29T05:02:44Z [triage] classified bug (confidence 0.86) -> hydraflow-plan
sandbox\tscenario issue-to-merge\t2026-07-29T05:03:19Z [plan] 3-step plan approved by PlanReviewer (round 1)
sandbox\tscenario issue-to-merge\t2026-07-29T05:05:02Z [implement] worktree agent/issue-9861 committed 2 files
sandbox\tscenario issue-to-merge\t2026-07-29T05:05:37Z [review] ReviewRunner: 3 findings, 3 resolved
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:02Z [quality] pytest: 1 failed, 3184 passed
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:10Z [assert] expected pr labels {'hydraflow-fixed'}, got {'hydraflow-review', 'hydraflow-hitl'}
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:10Z E   AssertionError: PR #9871 never left review
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:10Z     scenarios/issue_to_merge.py:214: in assert_terminal_labels
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:11Z [hydraflow.log] pr_red_repair: PR #9871 settled red, real red, dispatching (attempt 1/3)
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:11Z [hydraflow.log] label_drift_watcher: pr_ahead_of_issue on #9871 (issue at hydraflow-plan)
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:12Z 1 scenario failed (issue-to-merge), 6 passed in 241s
sandbox\tscenario issue-to-merge\t2026-07-29T05:06:12Z ##[error]Process completed with exit code 1"""


@dataclass(frozen=True)
class _FakePRListItem:
    """The ``models.PRListItem`` attribute surface PR-keyed builders read.

    ``PrRedRepairLoop`` keys on ``.pr`` (not ``.number``), which is a shape
    ``_coerce_task_dicts`` has no rule for — a fixture dict would coerce to
    ``PRInfo`` and then ``AttributeError`` on ``pr.pr``.
    """

    pr: int
    branch: str
    issue: int = 0
    title: str = ""
    is_bot: bool = True


class _SettledRedPRPort:
    """Read-only ``PRPort`` slice for the two CI-log-expanding loop builders.

    ``SandboxFailureFixerLoop._build_prompt`` and
    ``PrRedRepairLoop._build_dispatch_prompt`` read ``self._prs``, an instance
    attribute that no fixture ``args`` entry can reach. Both then await
    ``fetch_ci_failure_logs`` / ``get_pr_recent_commit_diffs`` and fall back to
    placeholder text on failure, so an unset ``_prs`` renders a prompt with the
    context stripped out. This is the object ``render_target`` needs to set on
    the instance for those two prompts to render with their real payload.
    """

    async def fetch_ci_failure_logs(self, _pr_number: int) -> str:
        return _SANDBOX_SCENARIO_LOG_9871

    async def get_pr_recent_commit_diffs(self, _pr_number: int, n: int = 3) -> str:
        return _DIGEST_FIX_COMMIT_DIFFS


_PR_LIST_ITEM_9871 = _FakePRListItem(
    pr=9871,
    branch="agent/issue-9861",
    issue=9861,
    title="fix(digest): week bucketing drops the ISO-53 week and 500s on a bad stamp",
)


# The suppressions backlog in the route module the digest work landed in. The
# last two signatures are the ones PR #9820 and the #9861 fix added (a BLE001
# suppression around the ledger read and an arg-type ignore on the Query
# default); the rest are the file's standing debt. `fix_prompt` is read from the
# real registry so the fixture cannot drift from the dimension's actual guidance.
_BURNDOWN_UNIT_DIGEST = BurndownUnit(
    dimension="suppressions",
    path="src/server_routes_insights.py",
    signatures=(
        "src/server_routes_insights.py::noqa:C901",
        "src/server_routes_insights.py::noqa:PLR0912",
        "src/server_routes_insights.py::noqa:S110",
        "src/server_routes_insights.py::type-ignore[no-untyped-def]",
        "src/server_routes_insights.py::type-ignore[no-any-return]",
        "src/server_routes_insights.py::type-ignore[union-attr]",
        "src/server_routes_insights.py::noqa:BLE001",
        "src/server_routes_insights.py::type-ignore[arg-type]",
    ),
    fix_prompt=next(d.fix_prompt for d in DIMENSIONS if d.name == "suppressions"),
    dedup_key="disturbance:suppressions:src/server_routes_insights.py",
)


# TermProposerLoop's next candidate out of the same corpus: the audit-sample
# ledger the sampled-audit loop writes. Deliberately a hard call — it is a
# sibling of the already-covered EscapeLedger term, so the model has to decide
# whether it is a distinct domain concept or scaffolding around one.
_AUDIT_SAMPLE_LEDGER_SOURCE = """\
class AuditSampleLedger(IdentifiedJsonlLedger[AuditSample]):
    # Append-only reader/writer over one audit_samples.jsonl file.
    #
    # <data_root>/diagnostics/audit_samples.jsonl - one AuditSample per line,
    # following escape_ledger.jsonl's append-only-JSONL convention. Appends,
    # reads all, exposes already-recorded ids for dedup, and supports an
    # in-place disposition update (the ONE mutation: an adjudicated
    # disagreement's disposition is reconciled from `pending` - the audit
    # trail is otherwise immutable).

    def __init__(self, path: Path) -> None:
        super().__init__(path, AuditSample, logger=logger)

    def update_dispositions(self, updated: dict[str, AuditSample]) -> None:
        # Rewrite the file, replacing rows in *updated* by id. Used only by the
        # adjudication reconcile - every other write is a pure append. A no-op
        # when *updated* is empty or the file is absent.
        if not updated or not self.path.exists():
            return
        rows = self.read_all()
        with self.path.open("w", encoding="utf-8") as fh:
            for row in rows:
                out = updated.get(row.id, row)
                fh.write(json.dumps(out.to_json_dict(), sort_keys=False) + "\\n")

    def pending_disagreements(self) -> list[AuditSample]:
        # The adjudication work queue: sampled rows that disagreed with the
        # gauntlet and have not yet been upheld, refuted, or handed to a human.
        return [
            row
            for row in self.read_all()
            if row.verdict == "disagree" and row.disposition == "pending"
        ]
"""

_DRAFT_CONTEXT_AUDIT_SAMPLE_LEDGER = DraftContext(
    candidate=Candidate(
        name="AuditSampleLedger",
        code_anchor="src/audit/store.py:AuditSampleLedger",
        signals=("S1", "S2"),
        imports_seen=3,
        importing_term_anchors=(
            "src/sampled_audit_loop.py:SampledAuditLoop",
            "src/audit/models.py:AuditSample",
        ),
    ),
    candidate_source=_AUDIT_SAMPLE_LEDGER_SOURCE,
    caller_snippets={
        "src/sampled_audit_loop.py:SampledAuditLoop": """\
    def _ledger(self) -> AuditSampleLedger:
        return AuditSampleLedger(
            self._config.data_root / "diagnostics" / AUDIT_SAMPLES_FILENAME
        )

    async def _record(self, sample: AuditSample) -> None:
        ledger = self._ledger()
        if sample.id in ledger.recorded_ids():
            return
        ledger.append(sample)
        self._obs.gauge("sampled_audit.rows", len(ledger.read_all()))

    async def _adjudicate_pending(self) -> int:
        ledger = self._ledger()
        pending = ledger.pending_disagreements()
        resolved: dict[str, AuditSample] = {}
        for sample in pending[: self._config.sampled_audit_max_adjudications]:
            verdict, rationale = parse_adjudication(
                await self._llm.adjudicate(
                    prompt=build_adjudication_prompt(sample, await self._diff(sample))
                )
            )
            resolved[sample.id] = reconcile(sample, verdict, rationale)
        ledger.update_dispositions(resolved)
        return len(resolved)""",
        "src/audit/metrics.py:disagreement_rate": """\
def disagreement_rate(rows: list[AuditSample]) -> tuple[float, float, float]:
    # Wilson interval over the sampled rows - the headline statistical bound.
    # Reads the ledger's rows; never writes, never re-samples.
    disagreed = sum(1 for r in rows if r.verdict == "disagree")
    return wilson(disagreed, len(rows))""",
    },
    existing_terms=_UL_TERMS_ESCAPE_DIGEST,
)


_REGISTRY: dict[tuple[str, str], Any] = {
    ("repo_wiki_store", "empty"): _EmptyRepoWikiStore(),
    ("manifest", "minimal"): _MINIMAL_MANIFEST,
    # Worked scenario: weekly escape digest (#9812 / #9877 / PR #9820).
    ("terms", "ul_escape_digest"): _UL_TERMS_ESCAPE_DIGEST,
    ("inp", "escape_digest_spec_review"): _SPEC_REVIEW_INPUT_ESCAPE_DIGEST,
    # Same scenario: shape conversation, review-advisor seams, council split.
    ("conversation", "escape_digest_shape"): _SHAPE_CONVERSATION_ESCAPE_DIGEST,
    ("advocate_result", "escape_digest_directions"): (
        _SHAPE_ADVOCATE_RESULT_ESCAPE_DIGEST
    ),
    ("inp", "escape_digest_preflight"): _PREFLIGHT_INPUT_ESCAPE_DIGEST,
    ("inp", "escape_digest_postverify"): _POSTVERIFY_INPUT_ESCAPE_DIGEST,
    ("proposal", "escape_digest_split"): _DIRECTION_PROPOSAL_ESCAPE_DIGEST,
    ("a", "refinement_issue_9812"): _REFINEMENT_ISSUE_9812,
    ("b", "refinement_issue_9877"): _REFINEMENT_ISSUE_9877,
    ("issue", "refinement_issue_9877"): _REFINEMENT_ISSUE_9877,
    ("change", "merged_change_9820"): _MERGED_CHANGE_9820,
    # Same scenario, downstream: ADR-drift triage of PR #9820 (rollup #9903),
    # adjudication of the re-audit disagreement, the fix PR #9871 going red,
    # the suppressions it left behind, and the next UL candidate.
    ("ctx", "adr_drift_pr_9820"): _TRIAGE_CONTEXT_PR_9820,
    ("ctx", "term_proposer_audit_sample_ledger"): _DRAFT_CONTEXT_AUDIT_SAMPLE_LEDGER,
    ("sample", "audit_disagreement_9820"): _AUDIT_SAMPLE_9820,
    ("unit", "disturbance_suppressions_digest"): _BURNDOWN_UNIT_DIGEST,
    ("pr", "settled_red_9871"): _PR_LIST_ITEM_9871,
    ("prs_port", "settled_red_9871"): _SettledRedPRPort(),
}


def get_fake(kind: str, shape: str) -> Any:
    key = (kind, shape)
    if key not in _REGISTRY:
        raise KeyError(f"no fake registered for ({kind!r}, {shape!r}); extend fakes.py")
    return _REGISTRY[key]
