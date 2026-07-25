import { STAGE_KEYS, STAGE_META } from '../hooks/useTimeline'

// Backs StreamView.toStreamIssue — the single chokepoint that fabricates a
// StreamCard-shaped stages map from a raw PipelineIssue snapshot entry.
// Extracted so stage/status derivation is unit-testable in isolation from
// React rendering, mirroring pipelineTracks.js's precedent of deriving
// behaviour from PIPELINE_STAGES properties instead of hardcoding stage
// keys (#10509).

const STAGE_INDEX = Object.fromEntries(STAGE_KEYS.map((k, i) => [k, i]))

function freshStage(status) {
  return { status, startTime: null, endTime: null, transcript: [] }
}

/** Map a raw PipelineIssue status to the node status of its current stage. */
export function currentStageStatus(pipeIssue) {
  if (pipeIssue.status === 'merged') return 'done'
  // 'processing' means a worker has already dequeued the issue and is about
  // to claim it (IssueStore._in_flight) — closer to "in progress" than to
  // "waiting", so it renders as active rather than collapsing into queued.
  if (pipeIssue.status === 'active' || pipeIssue.status === 'processing') return 'active'
  if (pipeIssue.status === 'failed') return 'failed'
  if (pipeIssue.status === 'hitl') return 'hitl'
  return 'queued'
}

/** Map a raw PipelineIssue status to the card-level overallStatus. */
export function overallStatus(pipeIssue) {
  if (pipeIssue.status === 'hitl') return 'hitl'
  if (pipeIssue.status === 'failed' || pipeIssue.status === 'error') return 'failed'
  if (pipeIssue.status === 'merged') return 'done'
  if (pipeIssue.status === 'active' || pipeIssue.status === 'processing') return 'active'
  return 'queued'
}

/**
 * Build the synthetic per-stage map StreamCard renders, based purely on the
 * issue's position (`stageKey`) in the pipeline.
 *
 * Conditional stages (e.g. hitl — see PIPELINE_STAGES) are escalation
 * branches, not linear stops every issue passes through: a stage before the
 * current index only gets stamped 'done' when there's positive evidence the
 * issue actually visited it (`pipeIssue.hitl_visited`), never just because
 * it's behind the current position.
 */
export function buildSyntheticStages(pipeIssue, stageKey) {
  const currentIdx = STAGE_INDEX[stageKey] ?? 0
  const stages = {}
  for (let i = 0; i < STAGE_KEYS.length; i++) {
    const k = STAGE_KEYS[i]
    if (i < currentIdx) {
      const isSkippedConditional = STAGE_META[k]?.conditional && !pipeIssue.hitl_visited
      stages[k] = freshStage(isSkippedConditional ? 'pending' : 'done')
    } else if (i === currentIdx) {
      stages[k] = freshStage(currentStageStatus(pipeIssue))
    } else {
      stages[k] = freshStage('pending')
    }
  }
  return stages
}
