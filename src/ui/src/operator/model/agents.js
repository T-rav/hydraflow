/**
 * Per-worker / per-agent state derivation for the operator console
 * (board redesign #10943 + #10944, epic #10556).
 *
 * ONE pure derivation module shared by both board views:
 *   - #10943 PipelineRail phase columns split each workflow column into
 *     ACTIVE (a worker is on it) vs QUEUED (waiting) sub-groups via
 *     `splitPhaseItems`, keyed off the same claim signal used here.
 *   - #10944 the agent grid renders one card per live/held worker, each with an
 *     explicit STATE — RUNNING / PAUSED / STALLED / WAITING-CI / BLOCKED — via
 *     `deriveAgentStates`.
 *
 * There is no React and no side effect here; given the same input it returns the
 * same output. The clock is always injected (`now`) — nothing reads the wall
 * clock — so stall detection is deterministic under test.
 *
 * Data sources (no backend change):
 *   - the pipeline view model (`toPipeline`) — per-stage items whose status
 *     collapses the #10168 `hydraflow-in-progress` build-claim marker to
 *     PipelineIssueStatus.ACTIVE/PROCESSING (both normalized to 'active'); this
 *     is the "is a worker on this?" signal for the ACTIVE/QUEUED split.
 *   - the reducer's `workers` slice — the granular per-worker registry carrying
 *     the WorkerStatus (incl. `ci_wait`, `escalated`), the worker id, the role,
 *     and `lastActivity.timestamp` (the heartbeat used for stall detection).
 *   - the derived factory run-state (`toVitals` → { factory, credits }) — the
 *     credit/auth pause that suspends the whole fleet.
 */

import { activeWorkflowItems, stageDurationLabel } from './pipeline'
import { toTranscript } from './transcript'

/**
 * The five explicit agent states an operator supervises from (#10944). String
 * values double as the `data-state` attribute + the filter-chip keys.
 */
export const WORKER_STATE = Object.freeze({
  RUNNING: 'running',
  PAUSED: 'paused',
  STALLED: 'stalled',
  WAITING_CI: 'waiting-ci',
  BLOCKED: 'blocked',
})

/** Filter-chip order (#10944): Running | Paused | Stalled | Waiting-CI | Blocked. */
export const AGENT_STATE_ORDER = Object.freeze([
  WORKER_STATE.RUNNING,
  WORKER_STATE.PAUSED,
  WORKER_STATE.STALLED,
  WORKER_STATE.WAITING_CI,
  WORKER_STATE.BLOCKED,
])

/**
 * Per-state presentation metadata. `tone` is a `Badge`/`Text` token tone (never a
 * hardcoded colour), so every state colour resolves through the theme layer.
 * `pulse` marks the state that carries the live pulse (RUNNING only).
 */
export const AGENT_STATE_META = Object.freeze({
  [WORKER_STATE.RUNNING]: { label: 'Running', tone: 'success', pulse: true },
  [WORKER_STATE.PAUSED]: { label: 'Paused', tone: 'warning', pulse: false },
  [WORKER_STATE.STALLED]: { label: 'Stalled', tone: 'danger', pulse: false },
  [WORKER_STATE.WAITING_CI]: { label: 'Waiting-CI', tone: 'info', pulse: false },
  [WORKER_STATE.BLOCKED]: { label: 'Blocked', tone: 'accent', pulse: false },
})

/** The #10168 build-claim marker a live/held worker carries on its issue. */
export const CLAIM_LABEL = 'hydraflow-in-progress'

/**
 * Silent-failure threshold: a live worker that has emitted no transcript output
 * for longer than this is STALLED (#10944 — the "two days unnoticed" catch,
 * cf. #10844). Callers may override per-render.
 */
export const DEFAULT_STALL_MS = 8 * 60 * 1000

// WorkerStatus (src/ui/src/types.js) → agent-state classification sets.
// `ci_wait` is a reviewer/merge worker parked on CI — it emits no transcript by
// design, so it must be classified BEFORE the stall check (it is not a stall).
const CI_WAIT_STATUSES = new Set(['ci_wait'])
// A worker that has escalated (needs a human) or errored out.
const BLOCKED_STATUSES = new Set(['escalated', 'escalating', 'blocked', 'failed'])
// Statuses that are NOT a live/held agent — excluded from the agent view so the
// old "No transcript yet" queued cards vanish (#10944).
const NON_LIVE_STATUSES = new Set(['queued', 'done', 'merged'])

// Worker role → operator phase (key + display label). Keys align with the
// pipeline stage keys ('implement' renders as 'Build').
const ROLE_TO_PHASE = Object.freeze({
  triage: { key: 'triage', label: 'Triage' },
  planner: { key: 'plan', label: 'Plan' },
  implementer: { key: 'implement', label: 'Build' },
  reviewer: { key: 'review', label: 'Review' },
})

// ── #10943: ACTIVE / QUEUED phase-column bucketing ──────────────────────────

/**
 * The "is a worker on this?" claim signal for a phase-column item. The pipeline
 * snapshot collapses the `hydraflow-in-progress` build-claim marker (#10168) to
 * PipelineIssueStatus.ACTIVE/PROCESSING, both normalized to 'active' by
 * `toPipeline`. Everything else (queued) is waiting.
 * @param {string} status
 * @returns {boolean}
 */
export function isActiveClaim(status) {
  return status === 'active'
}

/**
 * Split a phase column's items into the #10943 sub-groups: ACTIVE (a worker is
 * running that item) vs QUEUED (waiting for a slot). QUEUED preserves the input
 * order, which the backend snapshot already emits in queue/priority order (the
 * queued list is iterated straight off the stage's priority queue). Pure —
 * tolerant of a missing / non-array `items`.
 * @param {Array<{status?: string}>} [items]
 * @returns {{ active: Array, queued: Array }}
 */
export function splitPhaseItems(items) {
  const active = []
  const queued = []
  for (const item of Array.isArray(items) ? items : []) {
    if (isActiveClaim(item?.status)) active.push(item)
    else queued.push(item)
  }
  return { active, queued }
}

// ── #10944: 5-state agent derivation ────────────────────────────────────────

/** Coerce an ISO string or epoch-ms to epoch-ms, or NaN when unparseable. */
function toMs(ts) {
  if (ts == null) return Number.NaN
  return typeof ts === 'number' ? ts : Date.parse(ts)
}

/**
 * Whether a live worker has gone silent past the stall threshold. A missing /
 * unparseable heartbeat is treated as NOT stalled — absence of a signal never
 * fabricates a silent-failure alarm.
 */
function isStalled(lastActivityTs, now, stallThresholdMs) {
  const last = toMs(lastActivityTs)
  const nowMs = toMs(now)
  if (Number.isNaN(last) || Number.isNaN(nowMs)) return false
  return nowMs - last > stallThresholdMs
}

/**
 * Classify a single worker into one of the five agent states.
 *
 * Precedence — PAUSED > BLOCKED > WAITING-CI > STALLED > RUNNING:
 *   - PAUSED first: a credit/auth pause is a fleet-wide halt (the operator's
 *     first question, "why is nothing moving?"), and it suppresses the false
 *     STALLED that would otherwise fire while output is legitimately absent.
 *   - BLOCKED / WAITING-CI outrank STALLED so an escalated or CI-parked worker
 *     (which produces no transcript by design) is never mislabeled a stall.
 *
 * @param {{status?: string, factoryPaused?: boolean, lastActivityTs?: string|number|null, now: number|string, stallThresholdMs?: number}} args
 * @returns {string} one of WORKER_STATE
 */
export function classifyAgentState({
  status,
  factoryPaused = false,
  lastActivityTs = null,
  now,
  stallThresholdMs = DEFAULT_STALL_MS,
}) {
  if (factoryPaused) return WORKER_STATE.PAUSED
  if (BLOCKED_STATUSES.has(status)) return WORKER_STATE.BLOCKED
  if (CI_WAIT_STATUSES.has(status)) return WORKER_STATE.WAITING_CI
  if (isStalled(lastActivityTs, now, stallThresholdMs)) return WORKER_STATE.STALLED
  return WORKER_STATE.RUNNING
}

/**
 * The numeric id a `workers`-map key refers to. Keys are
 * `${rolePrefix}${workerKey}` where the implementer has no prefix and
 * `workerKey = ${repo}#${id} | ${id}` (see HydraFlowContext.workerKey). Triage /
 * plan / implement keys carry the issue number; reviewer keys carry the PR.
 */
function idFromWorkerKey(key) {
  const tail = String(key).replace(/^(triage|plan|review)-/, '')
  const idStr = tail.includes('#') ? tail.slice(tail.lastIndexOf('#') + 1) : tail
  const n = Number(idStr)
  return Number.isFinite(n) ? n : null
}

/**
 * Normalize the reducer's `workers` map into a flat list of live/held agents,
 * dropping non-live records (queued / done / merged) so the agent view shows
 * only running or held workers.
 */
function normalizeWorkers(workers) {
  const out = []
  for (const [key, rec] of Object.entries(workers || {})) {
    if (!rec) continue
    if (NON_LIVE_STATUSES.has(rec.status)) continue
    const phase = ROLE_TO_PHASE[rec.role || 'implementer']
    if (!phase) continue
    const isReviewer = (rec.role || 'implementer') === 'reviewer'
    const keyId = idFromWorkerKey(key)
    const pr = isReviewer ? (rec.pr ?? keyId) : (rec.pr ?? null)
    const id = isReviewer ? (rec.pr ?? keyId) : keyId
    out.push({
      key,
      id,
      pr,
      phase: phase.key,
      phaseLabel: phase.label,
      role: rec.role || 'implementer',
      workerId: rec.worker ?? null,
      status: rec.status ?? null,
      title: rec.title ?? '',
      lastActivityTs: rec.lastActivity?.timestamp ?? null,
    })
  }
  return out
}

/** First / last transcript-row timestamp for an item id (start-of-work / heartbeat). */
function transcriptBounds(events, id) {
  if (id == null) return { first: null, last: null }
  const rows = toTranscript(events, id)
  if (rows.length === 0) return { first: null, last: null }
  return { first: rows[0].ts, last: rows[rows.length - 1].ts }
}

/**
 * Derive the operator's agent view: one entry per live/held worker, each with an
 * explicit state (#10944). Queued items are excluded entirely — they belong in
 * the phase columns' QUEUED section (#10943).
 *
 * Agents come from the `workers` slice (the granular registry). A pipeline item
 * whose claim status is 'active' but has NO worker record still surfaces as a
 * RUNNING agent: the REST snapshot's claim signal is authoritative even when the
 * granular worker_update WS frames were missed/coalesced.
 *
 * @param {{
 *   workers?: Object,
 *   pipeline?: {stages?: Array},
 *   events?: Array,
 *   factory?: {state?: string, reason?: string|null},
 *   credits?: {pausedUntil?: string|null, provider?: string|null},
 *   now?: number|string,
 *   stallThresholdMs?: number,
 * }} [args]
 * @returns {Array<{key,id,pr,phase,phaseLabel,role,workerId,status,title,state,claimLabel,elapsed,lastActivityTs,reason,resumeEta,provider}>}
 */
export function deriveAgentStates({
  workers,
  pipeline,
  events = [],
  factory,
  credits,
  now = Date.now(),
  stallThresholdMs = DEFAULT_STALL_MS,
} = {}) {
  const factoryPaused = factory?.state === 'paused'
  const reason = factory?.reason ?? null
  const resumeEta = credits?.pausedUntil ?? null
  const provider = credits?.provider ?? null

  const agents = normalizeWorkers(workers)
  const seen = new Set(agents.map(a => `${a.phase}:${a.id}`))

  // Pipeline-active fallback: claimed items with no worker record still show.
  for (const item of activeWorkflowItems(pipeline).filter(it => isActiveClaim(it.status))) {
    const dedup = `${item.stage}:${item.id}`
    if (seen.has(dedup)) continue
    seen.add(dedup)
    agents.push({
      key: `pipeline-${item.stage}-${item.id}`,
      id: item.id,
      pr: null,
      phase: item.stage,
      phaseLabel: item.stageLabel,
      role: null,
      workerId: null,
      status: 'active',
      title: item.title ?? '',
      lastActivityTs: null,
    })
  }

  return agents.map(agent => {
    const bounds = transcriptBounds(events, agent.id)
    const lastActivityTs = agent.lastActivityTs ?? bounds.last
    const state = classifyAgentState({
      status: agent.status,
      factoryPaused,
      lastActivityTs,
      now,
      stallThresholdMs,
    })
    const paused = state === WORKER_STATE.PAUSED
    return {
      ...agent,
      lastActivityTs,
      state,
      claimLabel: CLAIM_LABEL,
      elapsed: stageDurationLabel(bounds.first, now),
      reason: paused ? reason : null,
      resumeEta: paused ? resumeEta : null,
      provider: paused ? provider : null,
    }
  })
}
