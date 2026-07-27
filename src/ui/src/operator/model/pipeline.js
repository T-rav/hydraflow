/**
 * Pipeline view-model adapter for the operator console (epic #10556, Task 1).
 *
 * Pure, deterministic transform of the existing WebSocket event stream into the
 * pipeline hero's view model. Consumes the same `pipeline_snapshot` (per-stage
 * PipelineIssue lists) and `pipeline_stats` (per-stage StageStats: worker
 * slots + queue/active depth) frames the current dashboard already receives —
 * no backend change.
 *
 * Output shape (Task 1 interface):
 *   { stages: [{ key, label, count, slots, items: [{id,title,status}],
 *                attention: { hitl, failed } }] }
 *
 * There is no React and no side effect here; given the same input it returns
 * the same output.
 */

import { PIPELINE_STAGES } from '../../constants'

/**
 * The six canonical operator-console stages, in lifecycle order.
 * Keys align with the backend pipeline-snapshot / pipeline-stats stage keys so
 * the raw frames map straight through; only the display label differs
 * ('implement' renders as 'Build'). `role` mirrors constants.PIPELINE_STAGES:
 * role-bearing stages have worker slots, no-role stages (hitl, merged) do not.
 */
export const OPERATOR_STAGES = [
  { key: 'triage', label: 'Triage', role: 'triage' },
  { key: 'plan', label: 'Plan', role: 'planner' },
  { key: 'implement', label: 'Build', role: 'implementer' },
  { key: 'review', label: 'Review', role: 'reviewer' },
  { key: 'hitl', label: 'HITL', role: null },
  { key: 'merged', label: 'Merged', role: null },
]

/**
 * Normalize a raw PipelineIssue status into the operator status vocabulary.
 * Mirrors utils/stageStatus.overallStatus so the operator console and the
 * legacy StreamView agree on what 'failed'/'hitl'/'done' mean.
 */
function normalizeStatus(status) {
  if (status === 'hitl') return 'hitl'
  if (status === 'failed' || status === 'error') return 'failed'
  if (status === 'merged') return 'done'
  if (status === 'active' || status === 'processing') return 'active'
  return 'queued'
}

/**
 * Resolve the raw snapshot stage map and stats stage map from either an event
 * array (newest-first, as the reducer stores) or a plain snapshot object.
 * @returns {{ snapshotStages: object|null, statsStages: object }}
 */
function resolveSources(input) {
  if (Array.isArray(input)) {
    let snapshotStages = null
    let statsStages = {}
    // events are newest-first; the first match is the freshest frame.
    for (const event of input) {
      const type = event?.type
      if (snapshotStages === null && (type === 'pipeline_snapshot' || type === 'PIPELINE_SNAPSHOT')) {
        // WS frame carries { seq, stages }; REST dispatch may pass stages bare.
        snapshotStages = event.data?.stages ?? event.data ?? {}
      } else if (Object.keys(statsStages).length === 0 && (type === 'pipeline_stats' || type === 'PIPELINE_STATS')) {
        statsStages = event.data?.stages ?? {}
      }
    }
    return { snapshotStages, statsStages }
  }
  if (input && typeof input === 'object') {
    return {
      snapshotStages: input.stages ?? null,
      statsStages: input.stats?.stages ?? input.stats ?? {},
    }
  }
  return { snapshotStages: null, statsStages: {} }
}

function mapItems(rawIssues) {
  return (rawIssues || [])
    .filter(i => i && i.issue_number != null)
    .map(i => ({
      id: i.issue_number,
      title: i.title || `Issue #${i.issue_number}`,
      status: normalizeStatus(i.status),
    }))
}

/**
 * Build the pipeline view model.
 * @param {Array|Object} input - event array (newest-first) or { stages, stats }
 * @returns {{ stages: Array }}
 */
export function toPipeline(input) {
  const { snapshotStages, statsStages } = resolveSources(input)

  const stages = OPERATOR_STAGES.map(({ key, label, role }) => {
    const hasSnapshot = !!snapshotStages && Object.prototype.hasOwnProperty.call(snapshotStages, key)
    const items = hasSnapshot ? mapItems(snapshotStages[key]) : []
    const stat = statsStages?.[key] ?? null

    // Worker slots only exist for role-bearing stages.
    const slots = role
      ? { used: stat?.worker_count ?? 0, cap: stat?.worker_cap ?? null }
      : null

    // Count: prefer the concrete chip count when a snapshot is present;
    // otherwise fall back to the stats depth for the stage.
    let count
    if (hasSnapshot) {
      count = items.length
    } else if (stat) {
      count = key === 'merged'
        ? (stat.completed_session ?? 0)
        : (stat.queued ?? 0) + (stat.active ?? 0)
    } else {
      count = 0
    }

    // Attention: failed items (any stage) + HITL depth. For the HITL stage the
    // badge is the whole queue depth; elsewhere it is the count of items that
    // have escalated to HITL while sitting in that stage.
    const failed = items.filter(i => i.status === 'failed').length
    let hitl
    if (key === 'hitl') {
      hitl = hasSnapshot
        ? items.length
        : (stat ? (stat.queued ?? 0) + (stat.active ?? 0) : 0)
    } else {
      hitl = items.filter(i => i.status === 'hitl').length
    }

    return { key, label, count, slots, items, attention: { hitl, failed } }
  })

  return { stages }
}

/**
 * The workflow stages the factory is actively working — triage → plan → build
 * → review, in lifecycle order. These are the role-bearing stages
 * (`OPERATOR_STAGES` with a non-null `role`); the terminal stages `hitl`
 * (waiting on a human) and `merged` (historical) are deliberately excluded
 * because nothing is "running" there.
 */
export const WORKFLOW_STAGE_KEYS = ['triage', 'plan', 'implement', 'review']

/**
 * Flatten the active-work items across every workflow stage of a pipeline view
 * model, in lifecycle order, tagging each with the stage it sits in. This is
 * what the all-active grid renders: a running triage/plan/build/review item all
 * surface, not just Build-stage items. Tolerant of a missing / empty pipeline.
 *
 * @param {{ stages?: Array }} [pipeline]
 * @returns {Array<{id, title, status, stage, stageLabel}>}
 */
export function activeWorkflowItems(pipeline) {
  const stages = pipeline?.stages ?? []
  const items = []
  for (const key of WORKFLOW_STAGE_KEYS) {
    const stage = stages.find(s => s.key === key)
    if (!stage) continue
    for (const item of stage.items ?? []) {
      items.push({ ...item, stage: stage.key, stageLabel: stage.label })
    }
  }
  return items
}

/**
 * Format how long an item has been running as a compact, human relative
 * duration: `45s`, `12m`, `1h04m` (hours pad minutes to two digits).
 *
 * Pure and deterministic — `now` is passed in explicitly (never read from
 * `Date.now()` here) so callers/tests control the clock. `startTs` may be an ISO
 * string (an event timestamp) or epoch-ms; `now` is epoch-ms (or ISO). Returns
 * '' for a missing / unparseable / future start so the caller can omit the chip.
 *
 * @param {string|number|null|undefined} startTs
 * @param {number|string} now
 * @returns {string}
 */
export function stageDurationLabel(startTs, now) {
  if (startTs == null) return ''
  const startMs = typeof startTs === 'number' ? startTs : Date.parse(startTs)
  if (Number.isNaN(startMs)) return ''
  const nowMs = typeof now === 'number' ? now : Date.parse(now)
  if (Number.isNaN(nowMs)) return ''

  const diffSec = Math.floor((nowMs - startMs) / 1000)
  if (diffSec < 0) return ''
  if (diffSec < 60) return `${diffSec}s`
  const totalMin = Math.floor(diffSec / 60)
  if (totalMin < 60) return `${totalMin}m`
  const hours = Math.floor(totalMin / 60)
  const mins = totalMin % 60
  return `${hours}h${String(mins).padStart(2, '0')}m`
}

/**
 * Each operator stage's identity colour, as a TOKEN colour key, derived from the
 * classic dashboard's `PIPELINE_STAGES` (constants.js) so the operator rail and
 * the legacy board can never drift: triage=yellow, plan=purple,
 * build/implement=accent, review=orange, hitl=red, merged=green. `PIPELINE_STAGES`
 * stores `var(--x)` references; the token colour key is that `x` (camel-cased),
 * so consumers resolve the value through `useTokens()` — theme-mode aware, no
 * hardcoded literal.
 */
const STAGE_COLOR_KEY = Object.freeze(
  Object.fromEntries(
    PIPELINE_STAGES.map(s => {
      const match = /var\(--([a-z0-9-]+)\)/.exec(s.color || '')
      const key = match
        ? match[1].replace(/-([a-z])/g, (_, c) => c.toUpperCase())
        : null
      return [s.key, key]
    }),
  ),
)

/**
 * Token colour key for a stage's classic-palette identity colour, or `null` for
 * an unknown stage key. Callers resolve it via `useTokens()` (`t.color[key]`).
 * @param {string} stageKey
 * @returns {string|null}
 */
export function stageColorKey(stageKey) {
  return STAGE_COLOR_KEY[stageKey] ?? null
}

/**
 * The timestamp at which an item ENTERED its current stage, inferred from its
 * transcript rows' `meta.source` (triage/planner/reviewer, or null for the
 * implement stage). Rows are oldest-first, as `toTranscript(...)` returns them;
 * the current stage began at the first row of the trailing run that shares the
 * latest row's source. Returns `null` when the source never changes (a single
 * observed stage — the caller falls back to the total running duration) or there
 * are no rows. Pure — never reads the wall clock.
 *
 * @param {Array<{ts, meta?}>} rows - oldest-first transcript rows
 * @returns {string|number|null}
 */
export function stageTransitionTs(rows) {
  if (!Array.isArray(rows) || rows.length === 0) return null
  const sourceOf = (r) => r?.meta?.source ?? null
  const current = sourceOf(rows[rows.length - 1])
  let transitionTs = null
  for (let i = rows.length - 1; i >= 0; i--) {
    if (sourceOf(rows[i]) === current) {
      transitionTs = rows[i].ts
    } else {
      // rows[i] is the last row of the PREVIOUS stage; the current stage began
      // at the row after it, whose ts we already captured.
      return transitionTs
    }
  }
  // Every row shares one source: no transition observed within the window.
  return null
}
