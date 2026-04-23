# plan-off-by-one

Plan says `take()` semantics must be unchanged. Diff changes slice from
`[:n]` to `[:n-1]` — an off-by-one semantics change in violation of the
plan. plan-compliance must flag the divergence.

Keyword: plan
