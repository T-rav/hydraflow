---
id: 0850
topic: gotchas
source_issue: 10509
source_phase: plan
created_at: 2026-07-25T05:02:36.104103+00:00
status: active
corroborations: 1
---

# FakeIssueStore's HITL/merged fidelity gap makes scenario tests vacuous

`src/mockworld/fakes/fake_issue_store.py:436-441` stamps hitl and merged snapshot entries with `PipelineIssueStatus.PROCESSING` regardless of actual state, so a MockWorld scenario written against the fake cannot reproduce status-mapping bugs around HITL/merged rendering — it always looks like `processing`. Fix the fake's status fidelity before writing a scenario test that depends on distinguishing `hitl`/`merged`/`processing`, or the scenario will pass without exercising the real defect.

**Why:** a scenario test that can't fail against the un-fixed code isn't testing anything — check fake fidelity before trusting scenario coverage.
