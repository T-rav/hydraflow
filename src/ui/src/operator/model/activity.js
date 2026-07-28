/**
 * Global activity-feed view-model adapter for the operator console
 * (epic #10556, Task 1).
 *
 * Pure, deterministic transform of the raw event stream into the demoted,
 * grouped activity feed that replaces today's raw firehose EventLog. No backend
 * change; no React; no side effects.
 *
 * Output shape (Task 1 interface):
 *   toActivityFeed(events) -> [{ ts, type, severity, summary, groupKey, count }]
 *
 * Grouping rules:
 *   - Collapses a *consecutive run* of identical heartbeats (pipeline_stats /
 *     queue_update / background_worker_status=ok) into one row with `count`.
 *   - Rolls up a consecutive run of `transcript_line` events for the same item
 *     into one row with `count`.
 *   - LOAD-BEARING (spec §11): error / hitl / alert rows are NEVER grouped —
 *     each keeps its own row so signal is never collapsed away.
 *
 * Input is expected newest-first (as the reducer stores events); output
 * preserves that order and a collapsed row carries the newest event's `ts`.
 */

const ERROR_TYPES = new Set(['error', 'hitl_escalation', 'hitl_update'])

function itemId(data) {
  if (data == null) return 'unknown'
  if (data.issue != null) return String(data.issue)
  if (data.pr != null) return String(data.pr)
  return 'unknown'
}

function severityOf(type, data) {
  if (ERROR_TYPES.has(type)) return 'error'
  if (type === 'background_worker_status') return data?.status === 'error' ? 'error' : 'info'
  if (type === 'system_alert') return data?.severity === 'warning' ? 'warn' : 'error'
  return 'info'
}

/** Whether this event may collapse into an adjacent identical row. */
function groupableKey(type, data) {
  if (type === 'transcript_line') return `transcript:${itemId(data)}`
  if (type === 'pipeline_stats' || type === 'PIPELINE_STATS') return 'heartbeat:pipeline_stats'
  if (type === 'queue_update') return 'heartbeat:queue_update'
  if (type === 'background_worker_status' && data?.status !== 'error') {
    return `heartbeat:bgworker:${data?.worker ?? 'unknown'}`
  }
  return null // not groupable
}

/**
 * Human-readable one-line summary for a single event, keyed by type. Exported so
 * other view-model adapters (e.g. `model/timeline.js`) reuse the SAME event→text
 * logic instead of re-deriving it — the activity feed and the phase timeline can
 * never drift on how an event reads.
 * @param {string} type
 * @param {object} [data]
 * @returns {string}
 */
export function summarizeEvent(type, data) {
  const d = data || {}
  switch (type) {
    case 'transcript_line': return String(d.line ?? '')
    case 'error': return d.message || 'Error'
    case 'system_alert': return d.message || 'System alert'
    case 'pr_created': return d.pr ? `PR #${d.pr} opened` : 'PR opened'
    case 'merge_update': return `PR #${d.pr} ${d.status || ''}`.trim()
    case 'review_update': return `PR #${d.pr} → ${d.verdict || d.status || ''}`.trim()
    case 'hitl_escalation': return d.pr ? `PR #${d.pr} escalated to HITL` : `Issue #${d.issue} escalated to HITL`
    case 'hitl_update': return `#${d.issue} ${d.action || d.status || ''}`.trim()
    case 'pipeline_stats':
    case 'PIPELINE_STATS': return 'pipeline stats'
    case 'queue_update': return 'queue update'
    case 'background_worker_status': return `${d.worker} → ${d.status}`
    default: return type
  }
}

/**
 * Build the activity-feed view model.
 * @param {Array} events - event array, newest-first
 * @returns {Array<{ts, type, severity, summary, groupKey, count}>}
 */
export function toActivityFeed(events) {
  const out = []
  let idx = 0

  for (const event of events || []) {
    const type = event?.type
    if (!type) { idx += 1; continue }
    const data = event.data || {}
    const gKey = groupableKey(type, data)
    const groupable = gKey !== null

    const last = out[out.length - 1]
    if (groupable && last && last._groupable && last.groupKey === gKey) {
      last.count += 1
      idx += 1
      continue
    }

    out.push({
      ts: event.timestamp,
      type,
      severity: severityOf(type, data),
      summary: summarizeEvent(type, data),
      // Non-groupable rows get a unique, deterministic key so they never
      // collapse and can serve as stable list keys downstream.
      groupKey: groupable ? gKey : `${type}#${event.id ?? event.timestamp ?? ''}#${idx}`,
      count: 1,
      _groupable: groupable,
    })
    idx += 1
  }

  // Drop the internal grouping flag before returning.
  return out.map(({ _groupable, ...row }) => row)
}
