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
