import React, { useMemo, useCallback } from 'react'
import { theme } from '../theme'
import { useHydraFlow, workerKey } from '../context/HydraFlowContext'
import { StreamCard } from './StreamCard'
import { PIPELINE_STAGES, PULSE_ANIMATION } from '../constants'
import { splitPipelineTracks } from '../utils/pipelineTracks'
import { countPipeline } from '../utils/pipelineCounts'
import { buildSyntheticStages, overallStatus as deriveOverallStatus } from '../utils/stageStatus'
import { TerminalFork } from './PipelineFork'
import {
  sectionHeaderStyles,
  sectionLabelStyles,
  sectionCountStyles,
  sectionLabelBase,
  WORKSTREAM_SIDE_INSET_PX,
} from '../styles/sectionStyles'

// ---------------------------------------------------------------------------
// Shared transcript-line row renderer (#10556 Task 4).
//
// Extracted here so the operator console's TranscriptStream reuses ONE formatted
// row implementation instead of forking its own. Presentational and pure: it
// takes a single view-model row from `toTranscript(...)`
// (`{ ts, kind, text, meta }`, kind ∈ read|edit|run|pass|fail|agent) and renders
// a timestamp + a colour-coded kind tag + the line text. Additive — StreamView's
// own render path is unchanged.
// ---------------------------------------------------------------------------

// Per-kind accent for the transcript kind tag. Unknown kinds fall back to the
// agent colour but keep their raw `data-kind` for downstream styling/tests.
export const TRANSCRIPT_KIND_COLORS = {
  read: theme.textMuted,
  edit: theme.cyan,
  run: theme.purple,
  pass: theme.green,
  fail: theme.red,
  agent: theme.accent,
}

/** Extract a stable HH:MM:SS from an ISO timestamp (timezone-agnostic — the
 * literal wall-clock in the string, so tests don't depend on the host TZ). */
export function formatTranscriptTs(ts) {
  if (!ts) return ''
  const match = /T(\d{2}:\d{2}:\d{2})/.exec(String(ts))
  return match ? match[1] : String(ts)
}

const transcriptRowStyles = {
  row: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 8,
    padding: '1px 0',
    fontSize: 11,
    lineHeight: 1.5,
    minWidth: 0,
  },
  ts: {
    flexShrink: 0,
    fontFamily: 'monospace',
    fontSize: 10,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  kind: {
    flexShrink: 0,
    width: 40,
    fontSize: 9,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
  },
  text: {
    flex: '1 1 auto',
    minWidth: 0,
    color: theme.text,
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
}

/**
 * A single formatted transcript row.
 * @param {{ row: { ts?: string, kind?: string, text?: string } }} props
 */
export function TranscriptRow({ row }) {
  const kind = row?.kind || 'agent'
  const color = TRANSCRIPT_KIND_COLORS[kind] || TRANSCRIPT_KIND_COLORS.agent
  return (
    <div data-testid="transcript-row" data-kind={kind} style={transcriptRowStyles.row}>
      {row?.ts && (
        <span data-testid="transcript-ts" style={transcriptRowStyles.ts}>
          {formatTranscriptTs(row.ts)}
        </span>
      )}
      <span data-testid="transcript-kind" style={{ ...transcriptRowStyles.kind, color }}>
        {kind}
      </span>
      <span style={transcriptRowStyles.text}>{row?.text}</span>
    </div>
  )
}

// No-role stages (role: null) share the worker-less rendering branches, but each
// carries its own semantics. 'merged' is success (green, "{N} merged"); 'hitl' is
// an escalation bucket (red, "{N} needs human") and must NOT read as success.
// Keyed by stage.key so adding a no-role stage is one map entry, not a conditional.
const NO_ROLE_COUNT_LABELS = {
  merged: 'merged',
  hitl: 'needs human',
}
const NO_ROLE_DOT_COLORS = {
  merged: theme.green,
  hitl: theme.red,
}

// Human-readable labels for the work-queue strategy badge (#10067).
const QUEUE_STRATEGY_LABELS = {
  weighted_mix: 'weighted',
  priority: 'priority',
  fifo: 'fifo',
}

function PendingIntentCard({ intent }) {
  return (
    <div style={styles.pendingCard}>
      <span style={styles.pendingDot} />
      <span style={styles.pendingText}>{intent.text}</span>
      <span style={styles.pendingStatus}>
        {intent.status === 'pending' ? 'Creating issue...' : 'Failed'}
      </span>
    </div>
  )
}

function PipelineFlow({ stageGroups, queueStrategy, resyncing }) {
  // Per-region and pipeline-wide issue counts for the flow badges (#10488;
  // PR count dropped in #10593).
  const counts = useMemo(() => countPipeline(stageGroups), [stageGroups])

  const { mergedCount, failedCount } = useMemo(() => {
    const failed = stageGroups.reduce(
      (sum, g) => sum + g.issues.filter(i => i.overallStatus === 'failed').length, 0
    )
    return { mergedCount: counts.perStage.merged?.issues || 0, failedCount: failed }
  }, [stageGroups, counts])

  // #9863: a big backlog (67 queued in PLAN) rendered 67 dots in one
  // non-wrapping row and blew out the strip. Cap the dots and show the
  // remainder as a +N badge — the count survives, the layout does too.
  const FLOW_DOT_CAP = 10

  const renderFlowStage = (group) => (
    <div style={styles.flowStage} key={group.stage.key}>
      <span style={flowLabelStyles[group.stage.key]}>{group.stage.label}</span>
      <span
        style={styles.flowCount}
        data-testid={`flow-count-${group.stage.key}`}
        title={`${counts.perStage[group.stage.key].issues} issue(s) in ${group.stage.label}`}
      >
        {counts.perStage[group.stage.key].issues}
      </span>
      {group.issues.length > 0 && (
        <div style={styles.flowDots}>
          {group.issues.slice(0, FLOW_DOT_CAP).map(issue => {
            const isEpic = issue.isEpicChild || issue.epicNumber > 0
            const dotStyles = isEpic ? epicFlowDotStyleMap : regularFlowDotStyleMap
            const dotStyle =
              issue.overallStatus === 'active' ? dotStyles.active[group.stage.key]
              : issue.overallStatus === 'failed' ? dotStyles.failed[group.stage.key]
              : issue.overallStatus === 'hitl' ? dotStyles.hitl[group.stage.key]
              : issue.overallStatus === 'queued' ? dotStyles.queued[group.stage.key]
              : dotStyles.base[group.stage.key]
            return (
              <span
                key={`${issue.repo}#${issue.issueNumber}`}
                style={dotStyle}
                title={`#${issue.issueNumber}${isEpic ? ` (Epic #${issue.epicNumber})` : ''}`}
                data-testid={`flow-dot-${issue.issueNumber}`}
              >
                {isEpic ? 'e' : null}
              </span>
            )
          })}
          {group.issues.length > FLOW_DOT_CAP && (
            <span
              style={styles.flowDotOverflow}
              title={`${group.issues.length - FLOW_DOT_CAP} more in ${group.stage.label}`}
              data-testid={`flow-overflow-${group.stage.key}`}
            >
              +{group.issues.length - FLOW_DOT_CAP}
            </span>
          )}
        </div>
      )}
    </div>
  )

  const { triage: triageGroup, postTriage: postTriageGroups, terminal: terminalGroups } =
    splitPipelineTracks(stageGroups, g => g.stage.key)
  const groupKey = g => g.stage.key

  return (
    <div style={styles.flowContainer} data-testid="pipeline-flow">
      <span style={styles.flowTitle}>Pipeline Flow</span>
      <span
        style={styles.flowTotal}
        data-testid="flow-total"
        title={`${counts.total.issues} issue(s) across the whole pipeline`}
      >
        {counts.total.issues} issues
      </span>
      {queueStrategy && (
        <span
          style={styles.queueStrategyBadge}
          data-testid="queue-strategy-badge"
          title={`work-queue strategy: ${queueStrategy} — the algorithm choosing which issue the factory works next`}
        >
          ⚡ {QUEUE_STRATEGY_LABELS[queueStrategy] || queueStrategy}
        </span>
      )}
      {resyncing && (
        <span
          style={styles.resyncingBadge}
          data-testid="pipeline-resyncing-badge"
          title="Waiting for the backend to finish its post-restart refresh — the rail is holding its last known state rather than showing a possibly-stale empty view."
        >
          ⟳ resyncing
        </span>
      )}
      <div style={styles.flowConnector} />
      {triageGroup && renderFlowStage(triageGroup)}
      {postTriageGroups.map((group) => (
        <React.Fragment key={group.stage.key}>
          <div style={styles.flowConnector} />
          {renderFlowStage(group)}
        </React.Fragment>
      ))}
      <TerminalFork
        items={terminalGroups}
        keyOf={groupKey}
        renderItem={renderFlowStage}
        styles={forkStyles}
        testId="flow-terminal-fork"
      />
      {(mergedCount > 0 || failedCount > 0) && (
        <span style={styles.flowSummary} data-testid="flow-summary">
          {mergedCount > 0 && <span style={flowSummaryMergedStyle}>{mergedCount} merged</span>}
          {mergedCount > 0 && failedCount > 0 && <span style={flowSummaryDividerStyle}> · </span>}
          {failedCount > 0 && <span style={flowSummaryFailedStyle}>{failedCount} failed</span>}
        </span>
      )}
    </div>
  )
}

function StageSection({ stage, issues, workerCount, workerCap, queuedCount, intentMap, onRequestChanges, open, onToggle, enabled, dotColor, workers, prs }) {
  const safeIssues = issues || []
  const failedCount = safeIssues.filter(i => i.overallStatus === 'failed').length
  const hitlCount = safeIssues.filter(i => i.overallStatus === 'hitl').length
  // #9793: the header count and the expanded list previously came from two
  // sources (orchestrator live counters vs the label-derived /api/pipeline
  // snapshot) — "1 queued" could render zero queued rows. The count shown is
  // now derived from the SAME rows the expansion renders; when the
  // orchestrator is ahead of the snapshot the delta is shown honestly as
  // "syncing" instead of a phantom row count.
  const listQueuedCount = safeIssues.filter(i => i.overallStatus === 'queued').length
  const syncingCount = Math.max(0, (queuedCount || 0) - listQueuedCount)
  const hasRole = !!stage.role

  return (
    <div
      style={hasRole ? (enabled ? sectionEnabledStyle : sectionDisabledStyle) : styles.section}
      data-testid={`stage-section-${stage.key}`}
    >
      <div
        style={sectionHeaderStyles[stage.key]}
        onClick={onToggle}
        data-testid={`stage-header-${stage.key}`}
      >
        <span style={{ fontSize: 10 }}>{open ? '▾' : '▸'}</span>
        <span style={sectionLabelStyles[stage.key]}>{stage.label}</span>
        {hasRole && !enabled && (
          <span style={styles.disabledBadge} data-testid={`stage-disabled-${stage.key}`}>Disabled</span>
        )}
        <span style={sectionCountStyles[stage.key]}>
          {hasRole ? (
            <>
              <span data-testid={`stage-queued-${stage.key}`}>
                {listQueuedCount} queued
                {syncingCount > 0 && ` (+${syncingCount} syncing)`}
              </span>
              {failedCount > 0 && <span style={styles.failedBadge}> · {failedCount} failed</span>}
              {hitlCount > 0 && <span style={styles.hitlBadge}> · {hitlCount} hitl</span>}
              <span>
                {workerCap != null
                  ? ` · ${workerCount}/${workerCap} workers`
                  : ` · ${workerCount} ${workerCount === 1 ? 'worker' : 'workers'}`}
              </span>
            </>
          ) : (
            <span>{safeIssues.length} {NO_ROLE_COUNT_LABELS[stage.key] ?? 'merged'}</span>
          )}
        </span>
        <span
          style={{ ...styles.statusDot, background: dotColor }}
          data-testid={`stage-dot-${stage.key}`}
        />
      </div>
      {open && safeIssues.map(issue => (
        // Epic children render as flat cards (no EpicContainer grouping) —
        // the epic is shown inline on the card (the "Epic #N" chip), so the
        // pipeline flow stays a flat per-stage list. Epic roll-ups live on the
        // Outcomes screen.
        <StreamCard
          key={`${issue.repo}#${issue.issueNumber}`}
          issue={issue}
          intent={intentMap.get(issue.issueNumber)}
          defaultExpanded={issue.overallStatus === 'active'}
          onRequestChanges={onRequestChanges}
          transcript={findWorkerTranscript(workers, prs, stage.key, issue.issueNumber, issue.repo)}
        />
      ))}
    </div>
  )
}

/**
 * Convert a PipelineIssue from the server into a StreamCard-compatible shape.
 * Builds a synthetic `stages` object based on current pipeline position.
 */
export function toStreamIssue(pipeIssue, stageKey, prs) {
  const stages = buildSyntheticStages(pipeIssue, stageKey)

  // Match PR from prs array — repo-qualified so two repos' same issue number
  // don't resolve to the wrong repo's PR under repo=__all__.
  const matchedPr = (prs || []).find(
    p => p.issue === pipeIssue.issue_number && (p.repo ?? null) === (pipeIssue.repo ?? null),
  )
  const pr = matchedPr ? { number: matchedPr.pr, url: matchedPr.url || null } : null

  return {
    issueNumber: pipeIssue.issue_number,
    title: pipeIssue.title || `Issue #${pipeIssue.issue_number}`,
    issueUrl: pipeIssue.url || null,
    currentStage: stageKey,
    overallStatus: deriveOverallStatus(pipeIssue),
    startTime: null,
    endTime: null,
    pr,
    branch: `agent/issue-${pipeIssue.issue_number}`,
    stages,
    epicNumber: pipeIssue.epic_number || 0,
    isEpicChild: pipeIssue.is_epic_child || false,
    repo: pipeIssue.repo || '',
    // Work-queue visualisation (#10067): the P0/P1/P2 band and the position the
    // active strategy would dispatch this issue in. dispatch_rank is present
    // only on queued entries; default to a large sentinel so active/unranked
    // items sort after ranked ones.
    priority: pipeIssue.priority || 'none',
    dispatchRank: pipeIssue.dispatch_rank ?? Number.MAX_SAFE_INTEGER,
  }
}

/**
 * Find the transcript array for a given issue in a pipeline stage.
 * Worker keys vary by stage: triage-{issue}, plan-{issue}, {issue} (implement), review-{pr}.
 */
export function findWorkerTranscript(workers, prs, stageKey, issueNumber, repo = null) {
  if (!workers) return []
  let key
  switch (stageKey) {
    case 'triage':
      key = `triage-${workerKey(repo, issueNumber)}`
      break
    case 'plan':
      key = `plan-${workerKey(repo, issueNumber)}`
      break
    case 'implement':
      key = workerKey(repo, issueNumber)
      break
    case 'review': {
      const pr = (prs || []).find(
        p => p.issue === issueNumber && (p.repo ?? null) === (repo ?? null),
      )
      if (!pr) return []
      key = `review-${workerKey(repo, pr.pr)}`
      break
    }
    default:
      return []
  }
  return workers[key]?.transcript || []
}

export function StreamView({ intents, expandedStages, onToggleStage, onRequestChanges }) {
  const { pipelineIssues, prs, stageStatus, workers, config, pipelineSnapshotReady } = useHydraFlow()

  // Match intents to issues by issueNumber
  const intentMap = useMemo(() => {
    const map = new Map()
    for (const intent of (intents || [])) {
      if (intent.issueNumber != null) {
        map.set(intent.issueNumber, intent)
      }
    }
    return map
  }, [intents])

  // Pending intents (not yet matched to an issue)
  const pendingIntents = useMemo(
    () => (intents || []).filter(i => i.status === 'pending' || (i.status === 'failed' && i.issueNumber == null)),
    [intents]
  )

  // Build stage groups from pipelineIssues
  const stageGroups = useMemo(() => {
    return PIPELINE_STAGES.map(stage => {
      const stageIssues = (pipelineIssues[stage.key] || [])
        .map(pi => toStreamIssue(pi, stage.key, prs))
      // Active-first, then queued issues in DISPATCH order (#10067): the
      // backend stamps each queued entry with dispatch_rank — the position the
      // active queue strategy would pick it — so the top queued card is the one
      // the factory works next, instead of arrival order.
      stageIssues.sort((a, b) => {
        const aActive = a.overallStatus === 'active' ? 1 : 0
        const bActive = b.overallStatus === 'active' ? 1 : 0
        if (aActive !== bActive) return bActive - aActive
        return a.dispatchRank - b.dispatchRank
      })
      return { stage, issues: stageIssues }
    })
  }, [pipelineIssues, prs])

  const handleToggleStage = useCallback((key) => {
    onToggleStage(prev => ({ ...prev, [key]: !prev[key] }))
  }, [onToggleStage])

  const totalIssues = stageGroups.reduce((sum, g) => sum + g.issues.length, 0)
  const hasAnyIssues = totalIssues > 0 || pendingIntents.length > 0

  return (
    <div style={styles.container}>
      {pendingIntents.map((intent, i) => (
        <PendingIntentCard key={`pending-${i}`} intent={intent} />
      ))}

      <PipelineFlow stageGroups={stageGroups} queueStrategy={config?.queue_strategy} resyncing={pipelineSnapshotReady === false} />

      {stageGroups.map(({ stage, issues: stageIssues }) => {
        const status = stageStatus[stage.key] || {}
        const enabled = status.enabled !== false
        const workerCount = status.workerCount || 0
        const workerCap = stage.role ? (stageStatus.workerCaps?.[stage.key] ?? null) : null
        let dotColor
        if (!stage.role) {
          dotColor = NO_ROLE_DOT_COLORS[stage.key] ?? theme.green
        } else if (!enabled) {
          dotColor = theme.red
        } else if (workerCount > 0) {
          dotColor = theme.green
        } else {
          dotColor = theme.yellow
        }
        return (
          <StageSection
            key={stage.key}
            stage={stage}
            issues={stageIssues}
            workerCount={workerCount}
            workerCap={workerCap}
            queuedCount={status.queuedCount || 0}
            intentMap={intentMap}
            onRequestChanges={stage.role ? onRequestChanges : undefined}
            open={!!expandedStages[stage.key]}
            onToggle={() => handleToggleStage(stage.key)}
            enabled={enabled}
            dotColor={dotColor}
            workers={workers}
            prs={prs}
          />
        )
      })}

      {!hasAnyIssues && (
        <div style={styles.empty}>
          No active work.
        </div>
      )}
    </div>
  )
}

// Pre-computed per-stage flow label/dot styles (avoids object spread in .map())
const flowLabelBase = { ...sectionLabelBase, flexShrink: 0 }

const dotBase = {
  display: 'inline-block',
  width: 8,
  height: 8,
  borderRadius: '50%',
  flexShrink: 0,
}

const flowDotBase = { ...dotBase, transition: 'all 0.3s ease' }


const flowLabelStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowLabelBase, color: s.color }])
)

const flowDotStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: s.color }])
)

const flowDotQueuedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: s.subtleColor }])
)

const flowDotActiveStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...flowDotBase,
    background: s.color,
    animation: PULSE_ANIMATION,
  }])
)

const flowDotFailedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: theme.red }])
)

const flowDotHitlStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...flowDotBase, background: theme.red }])
)

// Epic dot styles — 12px circles with centered "e" text
const epicDotBase = {
  display: 'inline-flex',
  alignItems: 'center',
  justifyContent: 'center',
  width: 12,
  height: 12,
  borderRadius: '50%',
  flexShrink: 0,
  fontSize: 7,
  fontWeight: 700,
  color: theme.bg,
  transition: 'all 0.3s ease',
}

const epicFlowDotStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: s.color }])
)
const epicFlowDotQueuedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: s.subtleColor }])
)
const epicFlowDotActiveStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...epicDotBase,
    background: s.color,
    animation: PULSE_ANIMATION,
  }])
)
const epicFlowDotFailedStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: theme.red }])
)
const epicFlowDotHitlStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, { ...epicDotBase, background: theme.red }])
)

// Grouped style maps for quick lookup in render
const regularFlowDotStyleMap = {
  base: flowDotStyles,
  queued: flowDotQueuedStyles,
  active: flowDotActiveStyles,
  failed: flowDotFailedStyles,
  hitl: flowDotHitlStyles,
}
const epicFlowDotStyleMap = {
  base: epicFlowDotStyles,
  queued: epicFlowDotQueuedStyles,
  active: epicFlowDotActiveStyles,
  failed: epicFlowDotFailedStyles,
  hitl: epicFlowDotHitlStyles,
}

const flowSummaryMergedStyle = { color: theme.green }
const flowSummaryDividerStyle = { color: theme.textMuted }
const flowSummaryFailedStyle = { color: theme.red }

const styles = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: 8,
  },
  flowContainer: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '8px 12px',
    margin: `0 ${WORKSTREAM_SIDE_INSET_PX}px 8px`,
    background: theme.surfaceInset,
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
    overflowX: 'auto',
    flexWrap: 'nowrap',
  },
  flowStage: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    flexShrink: 0,
  },
  flowDots: {
    display: 'flex',
    gap: 4,
    alignItems: 'center',
  },
  flowDotOverflow: {
    fontSize: 9,
    fontWeight: 700,
    color: theme.textMuted,
    marginLeft: 2,
    whiteSpace: 'nowrap',
  },
  flowCount: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.textMuted,
    whiteSpace: 'nowrap',
  },
  flowConnector: {
    width: 16,
    height: 1,
    background: theme.border,
    flexShrink: 0,
  },
  flowFork: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    gap: 1,
    margin: '0 4px',
  },
  flowForkTop: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
  },
  flowForkArrow: {
    color: theme.cyan,
    fontSize: 10,
    fontWeight: 600,
  },
  flowTitle: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.5px',
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  flowTotal: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.textMuted,
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  queueStrategyBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent,
    background: theme.accentSubtle,
    padding: '1px 6px',
    borderRadius: 8,
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  resyncingBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.yellow,
    background: theme.yellowSubtle,
    padding: '1px 6px',
    borderRadius: 8,
    flexShrink: 0,
    whiteSpace: 'nowrap',
  },
  flowSummary: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
    marginLeft: 4,
    display: 'flex',
    alignItems: 'center',
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 200,
    color: theme.textMuted,
    fontSize: 13,
  },
  section: {
    marginBottom: 4,
  },
  failedBadge: {
    fontWeight: 700,
    color: theme.red,
  },
  hitlBadge: {
    fontWeight: 700,
    color: theme.yellow,
  },
  statusDot: dotBase,
  disabledBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.red,
    background: theme.redSubtle,
    border: `1px solid ${theme.red}`,
    borderRadius: 10,
    padding: '1px 6px',
    textTransform: 'uppercase',
  },
  pendingCard: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '10px 12px',
    background: theme.intentBg,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    margin: `0 ${WORKSTREAM_SIDE_INSET_PX}px 8px`,
  },
  pendingDot: {
    ...dotBase,
    background: theme.accent,
    animation: PULSE_ANIMATION,
  },
  pendingText: {
    flex: 1,
    fontSize: 12,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  pendingStatus: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
  },
}

// Canonical fork-slot → PipelineFlow-style map fed to the shared TerminalFork so
// the large flow diagram shares the Header pipeline row's fork topology while
// keeping its own larger styling (#9564).
const forkStyles = {
  fork: styles.flowFork,
  forkTop: styles.flowForkTop,
  forkArrow: styles.flowForkArrow,
}

// Pre-computed section opacity variants (avoids object spread in StageSection render)
const sectionEnabledStyle = { ...styles.section, opacity: 1, transition: 'opacity 0.2s' }
const sectionDisabledStyle = { ...styles.section, opacity: 0.5, transition: 'opacity 0.2s' }
