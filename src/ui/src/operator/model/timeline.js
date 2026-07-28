/**
 * Phase-container timeline view-model adapter for the operator console
 * (feat/operator-timeline).
 *
 * Pure, deterministic transform of the raw WebSocket event stream into a
 * chronological list of PHASE CONTAINERS — one collapsible card per pipeline
 * phase (triage → plan → build → review …) in the order the factory moved
 * through them, with the events that happened during each phase folded inside
 * and any PR/commit ("diff") references surfaced as structured rows. This
 * replaces the old flat scrolling event view. No backend change; no React; no
 * side effects.
 *
 * Output shape:
 *   toTimeline(events, { item?, now? }) -> {
 *     entries: [{
 *       id, phase, phaseLabel, issue,
 *       startTs, endTs, durationLabel,
 *       events: [{ ts, kind, text }],
 *       diffs:  [{ id, prNumber?, url?, commitSha?, filesChanged?, additions?, deletions? }],
 *     }]
 *   }
 *
 * Segmentation: a `phase_change` event is the CONTAINER BOUNDARY. Each one closes
 * the previous container (its `endTs` = the moment the next phase began) and
 * opens a new one; every non-boundary event between two boundaries belongs to the
 * open container. Events that arrive before the first `phase_change` have no
 * phase context and are dropped (the boot stream opens with a `phase_change`, so
 * this only sheds pre-boot noise). Output is oldest-first.
 *
 * The orchestrator's `phase_change` is a GLOBAL phase signal — its `data` carries
 * `{ phase }` and MAY carry `{ issue }`. When it carries an issue the container is
 * that issue's phase; when it does not, the container's issue is INFERRED from the
 * first contained event that names one. Filtering by `item` keeps containers that
 * belong to (or contain any event/diff for) that issue.
 *
 * Reuse, don't reinvent: event → text comes from `summarizeEvent` (model/activity)
 * and phase colour / duration come from `stageColorKey` / `stageDurationLabel`
 * (model/pipeline), so the timeline can never drift from the activity feed or the
 * pipeline rail. Deterministic: `now` is injected — the model NEVER reads the wall
 * clock, so the open container's duration is '' when no `now` is supplied.
 */

import { summarizeEvent } from './activity'
import { stageDurationLabel } from './pipeline'

const PHASE_CHANGE = 'phase_change'

/**
 * Map a raw `phase_change` phase value onto a canonical pipeline stage key +
 * display label. The stage KEY aligns with `constants.PIPELINE_STAGES` so
 * `stageColorKey(entry.phase)` resolves the same identity colour the rail uses
 * ('implement' is the Build stage). Unknown / terminal phases (idle, cleanup)
 * fall through to a title-cased label and a key that yields no rail colour
 * (rendered muted) — graceful, never a throw.
 */
const PHASE_MAP = Object.freeze({
  idle: { key: 'idle', label: 'Idle' },
  triage: { key: 'triage', label: 'Triage' },
  plan: { key: 'plan', label: 'Plan' },
  implement: { key: 'implement', label: 'Build' },
  build: { key: 'implement', label: 'Build' },
  review: { key: 'review', label: 'Review' },
  hitl: { key: 'hitl', label: 'Needs Human' },
  cleanup: { key: 'cleanup', label: 'Cleanup' },
  done: { key: 'merged', label: 'Done' },
  merged: { key: 'merged', label: 'Merged' },
})

/** Coarse event kind used for styling + testids; never carries text logic. */
const EVENT_KIND = Object.freeze({
  transcript_line: 'transcript',
  agent_activity: 'transcript',
  pr_created: 'pr',
  merge_update: 'merge',
  review_update: 'review',
  hitl_escalation: 'hitl',
  hitl_update: 'hitl',
  error: 'error',
  system_alert: 'error',
})

// Events whose payload represents a PR/commit moment worth surfacing as a
// structured "diff" row inside its phase (creation + merge). A `review_update`
// references a PR too, but reads as an event bullet ("PR #x → approve"), not a
// diff — so it stays in the events list only.
const DIFF_EVENT_TYPES = new Set(['pr_created', 'merge_update'])

function titleCase(value) {
  const s = String(value ?? '').trim()
  if (s === '') return 'Phase'
  return s.charAt(0).toUpperCase() + s.slice(1)
}

function resolvePhase(rawPhase) {
  const key = typeof rawPhase === 'string' ? rawPhase.toLowerCase() : ''
  return PHASE_MAP[key] ?? { key: key || 'unknown', label: titleCase(rawPhase) }
}

/** Numeric item id an event/phase belongs to (issue preferred, PR for reviewer). */
function idOf(data) {
  if (data == null) return null
  if (data.issue != null) return Number(data.issue)
  if (data.pr != null) return Number(data.pr)
  return null
}

function eventKind(type) {
  return EVENT_KIND[type] ?? 'event'
}

/** A finite number or `undefined` (so absent fields drop out of the diff row). */
function numOrUndef(value) {
  if (value == null) return undefined
  const n = Number(value)
  return Number.isFinite(n) ? n : undefined
}

/** Non-empty string or `undefined`. */
function strOrUndef(value) {
  if (value == null) return undefined
  const s = String(value)
  return s === '' ? undefined : s
}

/**
 * Extract a structured diff row from a PR/merge event, or `null` when nothing
 * diff-shaped is present. DEGRADES GRACEFULLY: the live WS stream carries a PR
 * number + url (and, on `pr_created`, a branch/title) but NO commit sha / file
 * counts / additions / deletions — those keys are read defensively so that if the
 * backend ever adds them they flow straight through, but today they are simply
 * omitted (never fabricated). Only keys that are actually present appear on the
 * returned object.
 */
function extractDiff(type, data, id) {
  if (!DIFF_EVENT_TYPES.has(type)) return null
  const d = data || {}
  const prNumber = numOrUndef(d.pr)
  const url = strOrUndef(d.url)
  // Defensive: not in today's stream, but honoured if a future payload adds them.
  const commitSha = strOrUndef(d.commit_sha ?? d.commitSha)
  const additions = numOrUndef(d.additions)
  const deletions = numOrUndef(d.deletions)
  const filesChanged = numOrUndef(
    Array.isArray(d.files_changed) ? d.files_changed.length : (d.files_changed ?? d.filesChanged),
  )
  // Nothing addressable — don't emit an empty diff row.
  if (prNumber == null && url == null && commitSha == null) return null

  const diff = { id }
  if (prNumber != null) diff.prNumber = prNumber
  if (url != null) diff.url = url
  if (commitSha != null) diff.commitSha = commitSha
  if (filesChanged != null) diff.filesChanged = filesChanged
  if (additions != null) diff.additions = additions
  if (deletions != null) diff.deletions = deletions
  return diff
}

/** Oldest-first copy of a newest-first event array; stable on equal timestamps. */
function chronological(events) {
  // Input is newest-first (as the reducer stores it): reverse to oldest-first,
  // then a stable sort by ISO timestamp keeps same-ts events in that order.
  const rows = [...events].reverse()
  rows.sort((a, b) => {
    const ta = a?.timestamp ?? ''
    const tb = b?.timestamp ?? ''
    if (ta === tb) return 0
    return ta < tb ? -1 : 1
  })
  return rows
}

/**
 * Filter a segmented container list down to one issue. A container is kept when
 * it belongs to `wantId` (its own issue) OR carries any event/diff for it; a
 * container that belongs to another issue is narrowed to just the rows that name
 * `wantId`. Containers left with no events AND no diffs are dropped.
 */
function filterToItem(entries, wantId) {
  const kept = []
  for (const entry of entries) {
    const owns = entry.issue === wantId
    const events = owns ? entry.events : entry.events.filter(r => r._issue === wantId)
    const diffs = owns ? entry.diffs : entry.diffs.filter(r => r._issue === wantId)
    if (!owns && events.length === 0 && diffs.length === 0) continue
    kept.push({ ...entry, issue: wantId, events, diffs })
  }
  return kept
}

/** Strip internal bookkeeping (`_issue`) before returning rows to the caller. */
function cleanEntry(entry, now) {
  const end = entry.endTs ?? now
  return {
    id: entry.id,
    phase: entry.phase,
    phaseLabel: entry.phaseLabel,
    issue: entry.issue,
    startTs: entry.startTs,
    endTs: entry.endTs,
    durationLabel: stageDurationLabel(entry.startTs, end),
    events: entry.events.map(({ _issue, ...row }) => row),
    diffs: entry.diffs.map(({ _issue, ...row }) => row),
  }
}

/**
 * Build the phase-container timeline view model.
 *
 * @param {Array} events - raw event array, newest-first (as the reducer stores)
 * @param {{ item?: number|string, now?: number|string }} [opts]
 *   - `item`: restrict to one issue (omit for all active issues)
 *   - `now`: injected clock for the open container's duration (never read here)
 * @returns {{ entries: Array }} chronological (oldest-first) phase containers
 */
export function toTimeline(events, { item, now } = {}) {
  if (!Array.isArray(events)) return { entries: [] }

  const segments = []
  let current = null

  for (const event of chronological(events)) {
    const type = event?.type
    if (!type) continue
    const data = event.data || {}

    if (type === PHASE_CHANGE) {
      // Close the open container: it ended when this next phase began.
      if (current) current.endTs = event.timestamp ?? current.endTs
      const { key, label } = resolvePhase(data.phase)
      current = {
        id: event.id != null ? String(event.id) : `seg${segments.length}`,
        phase: key,
        phaseLabel: label,
        issue: idOf(data),
        startTs: event.timestamp ?? null,
        endTs: null,
        events: [],
        diffs: [],
      }
      segments.push(current)
      continue
    }

    // A non-boundary event with no open container has no phase context — drop it.
    if (!current) continue

    const evIssue = idOf(data)
    if (current.issue == null && evIssue != null) current.issue = evIssue

    current.events.push({
      ts: event.timestamp ?? null,
      kind: eventKind(type),
      text: summarizeEvent(type, data),
      _issue: evIssue,
    })

    const diffId = event.id != null ? String(event.id) : `${current.id}-d${current.diffs.length}`
    const diff = extractDiff(type, data, diffId)
    if (diff) current.diffs.push({ ...diff, _issue: evIssue })
  }

  const wantId = item == null ? null : Number(item)
  const scoped = wantId == null ? segments : filterToItem(segments, wantId)
  return { entries: scoped.map(entry => cleanEntry(entry, now)) }
}

export default toTimeline
