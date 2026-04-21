<!-- docs/_prompt_audit_rubric.md — Section 2 of the generated report -->
## Rubric reference

| # | Criterion | Automated rule |
|---|---|---|
| 1 | Leads with the request | First non-whitespace sentence (pre-tag) contains an imperative from `{produce, return, generate, classify, review, decide, output, propose, write, summarize}`. |
| 2 | Specific | 3/3 of: output-artifact noun; named fields or schema; success criteria phrasing. |
| 3 | XML tags | ≥3 distinct `<content>...</content>` pairs (excluding `<thinking>` / `<scratchpad>`). |
| 4 | Examples where applicable | If structured output cues present, `<example>` or `Example:` required. |
| 5 | Output contract | ≥1 of: `respond with`, `do not`, `no prose`, `return only`, `output format`, `the output must`. |
| 6 | Placement of long context | ≥10K-char prompts: largest tagged block must end before the last imperative. |
| 7 | CoT scaffolded | Decision verbs present → require `<thinking>` / `<scratchpad>` / `think step by step`. |
| 8 | Edge cases named | ≥1 of: `if empty/missing/truncated/unclear/no …`, `when the … is not/cannot/fails`, `otherwise,`, `in case of`, `fallback`, `do not assume`. |

Severity: **High** when 2+ Fails, or any Fail on #1 or #6. **Medium** when 1 Fail or 3+ Partials. **Low** otherwise. **Unscored** for builders that can't render under the audit loader.
