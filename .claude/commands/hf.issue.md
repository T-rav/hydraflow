# Create a GitHub Issue

Take a rough description from the user, research the relevant codebase, and create a well-structured GitHub issue with full context, file references, and acceptance criteria.

## Usage

```
/gh-issue add a Stop hook that checks for Langfuse tracing in new LLM code
/gh-issue the tasks service Google Drive auth flow doesn't handle token refresh
```

`$ARGUMENTS` contains the rough issue description from the user.

If `$ARGUMENTS` is empty, ask the user to describe the issue.

## Instructions

### Phase 0: Resolve Configuration

Before doing anything else, resolve these three values. Use the EXACT fallback logic below — do NOT pass empty strings to `gh issue create`:

1. **REPO**: Run `echo "$HYDRAFLOW_GITHUB_REPO"`. If the output is empty, run `git remote get-url origin` and extract the `owner/repo` slug (strip `https://github.com/` prefix and `.git` suffix).
2. **ASSIGNEE**: Run `echo "$HYDRAFLOW_GITHUB_ASSIGNEE"`. If the output is empty, extract the owner from the repo slug (the part before `/`).
3. **LABEL**: Use `hydraflow-find` (the canonical label for discovery-stage issues).

### Phase 0.5: Check for Screenshot

If `$ARGUMENTS` mentions a screenshot file path (e.g. `/tmp/hydraflow-report-*.png`):
1. **Read the image** with the Read tool to understand what the user saw
2. Use what you see in the screenshot to inform your understanding of the bug

If `$ARGUMENTS` includes an uploaded screenshot URL (e.g. `https://gist.githubusercontent.com/...`):
- Use `![Screenshot](<URL>)` in the issue body with the **uploaded URL** (NOT the local file path)
- NEVER embed a local filesystem path like `/tmp/...` or `/var/folders/...` in the issue body — it will render as a broken image on GitHub

### Phase 1: Understand the Request

Parse `$ARGUMENTS` to understand what the user wants filed as an issue. Identify:
- What area of the codebase is involved
- What the problem or feature request is
- Any specific services, files, or patterns mentioned

**Epic detection:** If the user mentions "epic", "break into sub-issues", "multiple parts", or describes a large multi-component feature, treat this as an EPIC:
- Prefix the title with `[Epic]`
- Use the `hydraflow-epic` label (NOT `hydraflow-find` — the parent epic is a tracking issue, not implementable)
- Create sub-issues separately, each WITH the `hydraflow-find` label
- Link sub-issues in the epic body with checkboxes: `- [ ] #123 — title`

### Phase 2: Research the Codebase

Before writing the issue, explore the codebase to gather concrete context:
- Use Grep/Glob/Read to find the relevant files, services, and patterns
- Understand the current state of the code related to the issue
- Identify specific file paths, function names, and line numbers
- Check for existing related patterns or prior art in the codebase
- Look at how similar things are already done elsewhere
- **If the issue involves UI changes:**
  - Explore `ui/src/components/` for existing component patterns that overlap or could be reused
  - Check `ui/src/constants.js` for shared constants (e.g., `PIPELINE_STAGES`, `ACTIVE_STATUSES`)
  - Check `ui/src/types.js` for shared type definitions
  - Check `ui/src/theme.js` for the design system's color tokens and spacing values
  - Note the styling approach used in similar components (inline styles, CSS modules, etc.)

This research makes the issue actionable rather than vague.

### Phase 3: Check for Duplicates

Before creating, search for existing issues:
```bash
gh issue list --repo $REPO --label hydraflow-find --state open --search "<key terms>"
```

If a matching open issue already exists, tell the user and show the link instead of creating a duplicate.

**Pattern-shaped findings (#11292):** If the finding's needle is a PATTERN — a
regex/AST shape that could recur at more than one site (e.g. "this branch
parser is missing a namespace", "this test hard-codes an ADR filename") —
do NOT file one issue per site. Sweep ALL sites in one pass first, then run
the mechanical class-key check instead of a keyword search:

```bash
python scripts/find_class_check.py --check \
  --source "<short finder/pattern id, e.g. branch-namespace-parser>" \
  --needle "<one stable description of the pattern — same text every time \
this pattern is swept, do NOT reword it per site>" \
  --title "<the issue title you're about to create>"
```

Give every discovered site a stable identifier `<file>:<line>` — this is
what idempotency is tracked against across ticks, so it must stay identical
even if you reword a site's description later.

- Exit `0` → stdout prints `FOLD <number>`. Do not create a new issue. For
  EACH swept site, re-run the same command with `--site "<file:line>"`
  added:
  - Exit `3` (`ALREADY-LISTED <number>`) → this exact site is already on
    the issue. Make no changes for it.
  - Exit `0` (`FOLD <number>`) → this site is new.
  If every site came back `ALREADY-LISTED`, stop here — no body edit, no
  comment (this is the expected outcome when a sweep rediscovers only
  already-known sites; posting a comment anyway is the duplicate-comment
  bug #11328 exists to prevent). Otherwise fetch the current body
  (`gh issue view <number> --json body -q .body`) and, immediately above
  the `<!-- hydraflow-class: ... -->` marker line, insert one line per new
  site directly below the LAST existing `- ` line under the `## Folded
  sites` heading (create that heading, right above the marker, if the
  issue predates it) in the exact form:
  `- <short site description> (site: \`<file:line>\`)`
  Write it back with `gh issue edit <number> --body-file <tmpfile>`, THEN
  post ONE comment listing only the newly added site(s).
- Exit `1` → stdout prints `FILE-NEW`. Create ONE issue whose body lists
  every site the sweep found under a `## Folded sites` heading, one line
  per site in the same `- <description> (site: \`<file:line>\`)` form, and
  append the marker line immediately after that section from:
  `python scripts/find_class_check.py --emit-marker --source "<source>" --needle "<needle>"`
  Skipping the `## Folded sites` section on the seeding issue, or using any
  other line shape, makes every site on it permanently unrecognizable to
  `--site` on later ticks — silently defeating idempotency from creation.
- Exit `2` → the check itself failed (gh auth/network/rate-limit). Do NOT
  treat this as `FILE-NEW` — a transient failure misread as "no matches"
  files an avoidable duplicate. Retry, or stop and report the failure.

This is a mechanical decision, not a judgment call — never skip the check
because the sites "seem different enough" to you, and never skip `--site`
because there's only one site this time. A finding that is a single
concrete bug at a single site (not a recurring pattern) is unaffected and
follows the normal duplicate-search flow above.

### Phase 4: Create the Issue

**CRITICAL RULES:**
- The issue body MUST be detailed (at least 200 characters). NEVER create an issue with an empty or one-line body.
- ALL of the user's input from `$ARGUMENTS` goes into the BODY, not the title. The title is a short summary YOU write.
- The `--label` flag MUST have a non-empty value. Use `hydraflow-find` as default.
- Use `--body-file` with a temp file for long bodies to avoid shell escaping issues.

Create the issue using `gh issue create` with:
- **Label**: `$LABEL` (MUST be non-empty — default `hydraflow-find`)
- **Assignee**: `$ASSIGNEE`
- **Title**: Concise, descriptive (under 70 chars) — this is a SHORT summary, NOT the user's full input
- **Body**: Well-structured with the sections below. MUST be at least 200 characters.

#### Issue Body Structure

```markdown
## Problem

Clear description of what's missing, broken, or needed. Include WHY this matters.

## Current State

What exists today — reference specific files, services, and patterns found during research.
Use full file paths so the implementer can navigate directly.

## Proposed Solution

Concrete description of what should be built or changed.
Reference existing patterns in the codebase that should be followed.

## Scope

### Files/Services involved:
- List specific files and directories

### Key integration points:
- List functions, classes, or patterns to hook into

## UI/UX Considerations (if applicable)

_Include this section only when the issue involves frontend/UI changes. Skip entirely for backend-only issues._

### Existing components to reuse or extend:
- List any components in `ui/src/components/` that overlap with the proposed change

### Responsive requirements:
- Min-width constraints needed
- Viewport or container-size considerations

### Shared code:
- Constants, types, or styles to import from centralized modules (`constants.js`, `types.js`, `theme.js`)

## Screenshot (if provided)

![Screenshot](<path from $ARGUMENTS>)

## Acceptance Criteria

- [ ] Checklist of concrete, verifiable outcomes
- [ ] Each item should be testable
- [ ] Include test requirements
```

#### gh issue create command

For long bodies, use a temp file to avoid shell escaping issues:

```bash
BODY_FILE=$(mktemp)
cat > "$BODY_FILE" <<'ISSUE_EOF'
<body content here>
ISSUE_EOF

gh issue create --repo $REPO \
  --assignee $ASSIGNEE \
  --label $LABEL \
  --title "<title>" \
  --body-file "$BODY_FILE"

rm -f "$BODY_FILE"
```

For shorter bodies, the HEREDOC approach also works:

```bash
gh issue create --repo $REPO \
  --assignee $ASSIGNEE \
  --label $LABEL \
  --title "<title>" \
  --body "$(cat <<'EOF'
<body content>
EOF
)"
```

### Phase 5: Report Back

Show the user:
- The issue URL
- A brief summary of what was filed
