# Console decision records

One file per adjudication, numbered per chamber (`<chamber>/NNNN-<slug>.md`) — the ADR pattern applied to chamber rulings. The directory listing IS the index (no hand-maintained table — this repo knows why). Records capture the adjudication — seats, verdict, dissent-by-name, evidence links; the judged artifact stays canonical where it lives.

**The chair's closing duty: no committed record, no verdict.** Records are immutable once merged; corrections are new records referencing the old (enforced: `make console-conformance`).

## Template

```markdown
# <CHAMBER>-NNNN: <subject>

**Date:** YYYY-MM-DD · **Seats:** <who sat> · **Verdict:** <chamber vocabulary>
**Dissent:** <named, or none>
**Enforcement:** enforced | process-gated | decision-of-record
**Enforced by:** <make target / script — required when enforced> · **Gate:** <named gate — required when process-gated>
**Evidence:** <links: issues, PRs, ADRs, queries run>

<One paragraph: what was judged and why the verdict.>
```
