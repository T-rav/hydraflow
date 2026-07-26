/**
 * Per-item transcript view-model adapter for the operator console
 * (epic #10556, Task 1).
 *
 * Pure, deterministic transform of the existing `transcript_line` and
 * `agent_activity` WebSocket events into the formatted, per-item live
 * transcript that replaces today's raw `transcript line#…` wall. No backend
 * change; no React; no side effects.
 *
 * Output shape (Task 1 interface):
 *   toTranscript(events, issueId) -> [{ ts, kind, text, meta }]
 *   kind ∈ 'read' | 'edit' | 'run' | 'pass' | 'fail' | 'agent'
 *
 * Regression contract: the legacy `transcript line#undefined` bug
 * (EventLog.eventSummary rendered `#${data.issue || data.pr}` = `#undefined`
 * when a line carried neither id) is repaired here — id-less lines are dropped
 * rather than attributed to a phantom `#undefined` item, and any literal
 * `#undefined` token leaking into a line's text is stripped.
 */

// Tool → kind classification for structured agent_activity events.
const READ_TOOLS = new Set(['Read', 'Glob', 'Grep', 'LS', 'NotebookRead'])
const EDIT_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit'])
const RUN_TOOLS = new Set(['Bash', 'Task'])

/** Strip a leading/embedded literal `#undefined` id token (the known bug). */
function repairText(text) {
  if (typeof text !== 'string') return text == null ? '' : String(text)
  return text.replace(/#undefined\s*/g, '').trim()
}

/** Numeric item id an event belongs to (issue preferred, PR for reviewer). */
function itemIdOf(data) {
  if (data == null) return null
  if (data.issue != null) return Number(data.issue)
  if (data.pr != null) return Number(data.pr)
  return null
}

/** Classify a structured agent_activity event into a transcript kind. */
function kindFromActivity(data) {
  const tool = data.tool_name
  if (READ_TOOLS.has(tool)) return 'read'
  if (EDIT_TOOLS.has(tool)) return 'edit'
  if (RUN_TOOLS.has(tool)) return 'run'
  if (data.activity_type === 'error') return 'fail'
  return 'agent'
}

/** Classify a raw transcript_line's text into a transcript kind. */
function kindFromLine(text) {
  const t = String(text || '')
  if (/(^|\s)(✗|✘|fail(ed|ure)?|error)\b/i.test(t)) return 'fail'
  if (/(✓|\bpass(ed|ing)?\b|\ball tests pass|\bsuccess\b)/i.test(t)) return 'pass'
  if (/^\s*(read(ing)?|cat |viewing)\b/i.test(t)) return 'read'
  if (/^\s*(edit(ing)?|writing|wrote|modified|created|patch)\b/i.test(t)) return 'edit'
  if (/^\s*(\$|run(ning)?|executing|bash)\b/i.test(t)) return 'run'
  return 'agent'
}

/**
 * Build the per-item transcript view model.
 *
 * @param {Array} events   - event array (any order; sorted chronologically here)
 * @param {number|string} [issueId] - restrict to one item; omit for all items
 * @returns {Array<{ts, kind, text, meta}>} rows, oldest-first
 */
export function toTranscript(events, issueId) {
  const wantId = issueId == null ? null : Number(issueId)
  const rows = []

  for (const event of events || []) {
    const type = event?.type
    if (type !== 'transcript_line' && type !== 'agent_activity') continue
    const data = event.data || {}

    const id = itemIdOf(data)
    // Repair: an id-less line can never be attributed to an item — drop it so
    // it never renders as a `#undefined` header.
    if (id == null) continue
    if (wantId != null && id !== wantId) continue

    let kind
    let text
    if (type === 'agent_activity') {
      kind = kindFromActivity(data)
      text = repairText(data.summary || data.detail || data.tool_name || '')
    } else {
      text = repairText(data.line)
      kind = kindFromLine(text)
    }

    rows.push({
      ts: event.timestamp,
      kind,
      text,
      meta: {
        source: data.source ?? null,
        tool: data.tool_name ?? null,
        activityType: data.activity_type ?? null,
        issue: data.issue != null ? Number(data.issue) : (data.pr != null ? null : id),
        pr: data.pr != null ? Number(data.pr) : null,
        raw: type === 'transcript_line',
      },
    })
  }

  // Chronological (oldest-first) for display; ts primary, id tiebreak.
  rows.sort((a, b) => {
    const ta = a.ts || ''
    const tb = b.ts || ''
    if (ta !== tb) return ta < tb ? -1 : 1
    return 0
  })

  return rows
}
