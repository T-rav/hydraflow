---
id: 1036
topic: gotchas
source_issue: 10575
source_phase: plan
created_at: 2026-07-26T00:41:55.611443+00:00
status: superseded
corroborations: 1
superseded_by: 1039
---

# repo_wiki frontmatter is naive f'{k}: {v}' — avoid colons/multiline values

repo_wiki entry frontmatter is rebuilt via plain `f"{k}: {v}"` string joins, not real YAML serialization. A frontmatter value containing a colon, a newline, or a stray `---` line in the body silently corrupts or drops the entry (no error raised). When hand-editing `repo_wiki/**/*.md`, keep frontmatter values single-line and colon-free, and never place `---` inside the body text. **Why:** corruption from this pattern fails silently, so it goes unnoticed until the next drift audit.
