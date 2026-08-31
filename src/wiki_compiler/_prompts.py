"""The five prompt templates, in one place because two of them have two callers.

``_COMPILE_TOPIC_PROMPT`` is formatted by the legacy one-shot compile (in
``_compiler``) AND by the tracked flow's synthesize node (in ``_flow``); a
prompt owned by either module would force the other to import it back and
close an import cycle. The three single-caller prompts sit here too so the
synthesis-anchor gate has one file to read.
"""

from __future__ import annotations

_COMPILE_TOPIC_PROMPT = """\
You are a technical knowledge librarian maintaining a per-repository wiki.

Below are all current entries in the **{topic}** topic for repository **{repo}**.
Your job is to compile them into a clean, deduplicated set of entries.

## Current entries

{entries_text}

## Voice and structure (read this first — it overrides every other rule)

Each entry's `content` field MUST be **scannable** documentation, not a wall
of prose. Agents and humans read the title to decide whether to read the
entry, then read the entry to apply a rule — both audiences need structure.

**Required shape for every entry — no exceptions, ALL THREE PARTS REQUIRED:**

1. **Rule** (1 sentence): the rule itself, no narrative ramp-up.
2. **Example** (inline code, file path, or 2-3 bullet points): how the
   rule looks in use. Skip ONLY when the rule is purely conceptual.
3. **Why line** (literal markdown `**Why:**` prefix, then 1 sentence):
   the failure mode or constraint the rule prevents. The literal text
   `**Why:**` MUST appear at the start of the closing line — agents
   grep for this marker to extract the rationale. An entry without a
   `**Why:**` line is malformed.

Example of the required format:

> Use `is None` and `is not None` for optional objects.
>
> Example: `if callback is None: return`. Avoid `==` comparison for
> sentinels; custom `__eq__` can hide subtle bugs.
>
> **Why:** Identity checks are O(1) and immune to overridden `__eq__`;
> equality checks against `None` accidentally match falsy values.

**Hard length budget per entry — enforced, not aspirational:**

- `title`: ≤ 80 characters, specific enough that a reader can decide
  relevance from the title alone. Avoid generic labels like "Notes",
  "Findings", "Background", "Concurrency and I/O safety", or any
  multi-rule umbrella title.
- `content`: ≤ 150 words. If the source material exceeds this, **emit
  multiple entries.** A single entry covering "concurrency and I/O
  safety" with 5 distinct rules MUST become 5 separate entries.

**Anti-patterns to avoid:**

- Long single-paragraph dumps with no structure.
- Umbrella entries that consolidate unrelated rules under one title
  (e.g., a "Concurrency and I/O safety" entry covering locks, atomic
  writes, async patterns, and trace context all at once). Each rule
  gets its own entry.
- Retrospective voice ("This entry captures the lesson that…", "We
  learned in PR #N that…"). Write in rule voice ("Use X. Avoid Y.").
- Restating the title in the first sentence.
- Inline JSON or code fences spanning more than 5 lines (link to the
  source instead).

## Repo-specificity requirement (load-bearing — entries are gated on this)

Every entry MUST be grounded in **{repo}** — reference at least one
concrete repo anchor: a `src/*.py` module or file path, a registered
loop/worker/Port/runner/store name (e.g. `RepoWikiLoop`, `WorkspacePort`),
a config field (e.g. `rc_cadence_hours`), an ADR number (e.g. `ADR-0042`),
or a fake/double name (e.g. `FakeGitHub`).

**DROP any entry that reads as generic programming best-practice** — a rule
that would apply verbatim to any Python project and names nothing from this
repo. Examples to DROP, not emit: "Use `is None` for optional sentinels",
"Create a specialized method rather than overloading", "Use portable shell
commands in Alpine containers", "Delete code blocks bottom-to-top." A
downstream deterministic gate rejects anchor-less entries and logs them, so
emitting them wastes the slot — fold their durable, repo-specific corollary
(if any) into an anchored entry instead.

## Compilation rules (apply only after the structure rules above)

1. **Merge true duplicates ONLY**: Two entries are duplicates if they
   state the same rule about the same target. Two entries that touch
   adjacent topics (e.g., "use atomic writes" and "use file locks")
   are NOT duplicates — keep both as separate entries. When in doubt,
   keep separate.
2. **Split umbrella entries**: If an existing entry packs multiple
   distinct rules under one title, split it into one entry per rule
   even though the input was a single entry. Splitting is preferred
   over merging.
3. **Cross-reference**: If an entry relates to entries in other topics
   ({other_topics}), add a brief note like "See also: [topic] — [entry
   title]" inside the content.
4. **Resolve contradictions**: If entries contradict each other, keep
   the more recent one and note the resolution.
5. **Remove stale content**: If an entry's insight has been superseded
   by a newer one, drop it.
6. **Preserve source attribution**: Keep source_issue and source_type
   from the original entries when an output entry maps 1:1 to a single
   input. For split or genuinely-merged entries, use source_type
   "compiled" and source_issue null.
7. **Declare correspondence**: Every output entry MUST set
   "supersedes_ids" to the input entry id(s) — see the `(id: ...)`
   annotation next to each entry's title above — that it directly
   replaces. A 1:1 rewrite lists that one id. A merge lists every id
   it merges. A split of one umbrella input into several outputs
   lists that same input id on each split output. Do NOT list an id
   from an input this output doesn't actually draw from, and do NOT
   invent ids not shown above — readers follow this pointer from the
   old entry to its replacement, so a wrong id misdirects them to an
   unrelated topic.

## Expected entry-count behavior

- For a topic with N coherent input entries, expect roughly N output
  entries (give or take a couple from true-duplicate merges).
- A 50% reduction in entry count almost always means under-splitting.
  If your output has ≤ half the input count, double-check that you
  haven't created umbrella entries.

## Output format

Return a JSON array of compiled entries. Each entry must be a JSON object with these fields:
- "title": string (≤ 80 chars, descriptive — see length budget above)
- "content": string (rule + example + Why; ≤ 150 words)
- "source_type": string (plan, implement, review, hitl, or "compiled")
- "source_issue": number or null
- "stale": false
- "supersedes_ids": array of strings — the input entry ids (from the
  "(id: ...)" annotations above) this output entry replaces. See rule 7.

Return ONLY the JSON array, no other text.
"""

_CONTRADICTION_PROMPT = """\
You are a technical knowledge librarian. A new wiki entry has been written to the
**{topic}** topic of repository **{repo}**. Identify which existing sibling entries
(if any) it contradicts — meaning the new entry's advice is incompatible with an
existing entry's advice, not merely different in emphasis.

## New entry

title: {new_title}
content:
{new_content}

## Existing sibling entries (current only)

{siblings_text}

## Instructions

Return a JSON object with one key, "contradicts", mapping to an array of
{{"id": <sibling_id>, "reason": <one-sentence>}} objects.

Only include a sibling if the new entry **directly contradicts** it — e.g.,
"use X" vs "never use X", or "Python 3.11 minimum" vs "Python 3.10 minimum".
Do NOT include siblings that are merely related or complementary.

Return ONLY the JSON object, no other text.

Example valid outputs:
  {{"contradicts": []}}
  {{"contradicts": [{{"id":"01HQ...","reason":"new entry says X, this one said not-X"}}]}}
"""

_GENERALIZATION_PROMPT = """\
You are a technical knowledge librarian comparing two wiki entries from
different repositories, both on topic **{topic}**. Decide whether they
encode the **same underlying principle** (not merely the same keywords).

## Entry A (repo: {repo_a})

title: {title_a}
content:
{content_a}

## Entry B (repo: {repo_b})

title: {title_b}
content:
{content_b}

## Instructions

Return a JSON object with these keys:
- same_principle: bool — true only if both entries advise the same rule in
  a way that would generalize across any Python project
- generalized_title: str — if same_principle is true, a short neutral title
- generalized_body: str — if same_principle is true, merged content that drops
  repo-specific details
- confidence: "high" | "medium" | "low" — how sure you are

Return ONLY the JSON object, no other text.

Example outputs:
  {{"same_principle": false, "generalized_title": "", "generalized_body": "", "confidence": "low"}}
  {{"same_principle": true, "generalized_title": "Pytest async mode", "generalized_body": "Configure pytest-asyncio with mode=auto.", "confidence": "high"}}
"""

_SYNTHESIZE_INGEST_PROMPT = """\
You are a technical knowledge librarian. A {source_type} phase just completed for \
issue #{issue_number} in repository {repo}.

## Raw phase output

{raw_text}

## Instructions

Extract 1-5 durable knowledge entries from this output. Focus on:
- Architecture decisions or patterns discovered
- Gotchas, pitfalls, or edge cases encountered
- Testing strategies or conventions learned
- Dependency quirks or version constraints found
- Reusable patterns or anti-patterns identified

Skip ephemeral details (specific variable names, one-off debugging steps).
Each entry should be a standalone insight useful for future work on this repo.

## Voice and structure (load-bearing — do not skip)

Each entry's `content` field MUST be **scannable** documentation, not a wall
of prose. Agents and humans read the title to decide whether to read the
entry, then read the entry to apply a rule — both audiences need structure.

Required shape for each entry:

- Open with a one-sentence rule statement (no narrative ramp-up).
- Follow with a short example (inline code, file path, or 2-3 bullet
  points) showing the rule in use. If the rule is purely conceptual,
  skip the example.
- Close with a `**Why:**` line in one sentence, naming the failure mode
  or constraint the rule prevents.

Hard length budget per entry:

- `title`: ≤ 80 characters, specific enough that a reader can decide
  relevance from the title alone (avoid generic labels like "Notes",
  "Findings", "Background", or "{source_type} from #{issue_number}").
- `content`: ≤ 150 words. If the source material exceeds this, **emit
  multiple entries** rather than producing a single long blob.

Anti-patterns to avoid:

- Long single-paragraph dumps with no structure.
- Retrospective voice ("This entry captures the lesson that…", "We
  learned in PR #N that…"). Write in rule voice ("Use X. Avoid Y.").
- Restating the title in the first sentence.
- Inline JSON or code fences spanning more than 5 lines (link to the
  source instead).

## Repo-specificity requirement (load-bearing — entries are gated on this)

Every entry MUST be grounded in **{repo}** — reference at least one
concrete repo anchor: a `src/*.py` module or file path, a registered
loop/worker/Port/runner/store name (e.g. `RepoWikiLoop`), a config field
(e.g. `rc_cadence_hours`), an ADR number (e.g. `ADR-0042`), or a fake name
(e.g. `FakeGitHub`). **Skip any insight that reads as generic programming
best-practice** — a rule that would apply verbatim to any Python project
and names nothing from this repo. A downstream deterministic gate rejects
anchor-less entries, so emitting them wastes the slot.

## Output format

Return a JSON array of entries. Each entry must be:
- "title": string (≤ 80 chars, descriptive — see length budget above)
- "content": string (rule + example + Why; ≤ 150 words)
- "source_type": "{source_type}"
- "source_issue": {issue_number}

Return ONLY the JSON array, no other text.
"""

_ADR_DRAFT_JUDGE_PROMPT = """\
You are a technical knowledge librarian evaluating whether a pattern rises to
ADR-worthy architectural status. Review the proposed ADR draft below and
answer two questions strictly:

1. **architectural**: does it change a system-level invariant (loop topology,
   state machine, persistence layout, promotion flow, module boundary)?
   Operational tips, style conventions, and per-phase workflows are NOT
   architectural.
2. **load_bearing**: if this decision were reversed tomorrow, would multiple
   components need to change?

## Proposed ADR

title: {title}
context: {context}
decision: {decision}
consequences: {consequences}

Return ONLY a JSON object:
  {{"architectural": <bool>, "load_bearing": <bool>, "reason": "<1 sentence>"}}
"""
