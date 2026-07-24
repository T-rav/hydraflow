---
id: 0193
topic: architecture
source_issue: 10451
source_phase: plan
created_at: 2026-07-24T12:15:48.605899+00:00
status: active
corroborations: 1
---

# LikeC4: declare `relationship extends` in specification before using it as an edge kind

In `.likec4` files, subclass relationships between klass nodes (e.g. `IdentifiedJsonlLedger` extends `AppendOnlyJsonlLedger`, or `TrendStore` extends `AppendOnlyJsonlLedger`) require an explicit `relationship extends` declaration in the `specification` block — it isn't implicit. Applies to any `docs/architecture/*.likec4` diagram modeling a class hierarchy.
**Why:** an undeclared relationship kind breaks parsing/rendering or silently falls back to a generic edge, misrepresenting the hierarchy the diagram exists to document.
