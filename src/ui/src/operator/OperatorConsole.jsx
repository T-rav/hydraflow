/**
 * OperatorConsole — the pipeline-centric operator shell (epic #10556, Task 2).
 *
 * This is the layout container for the new operator console. It owns five
 * slots — header, pipeline (hero), detail, vitals, drawer — consumes the
 * existing WebSocket state via `useHydraFlowSocket` and turns it into the four
 * Task-1 view models (`toPipeline` / `toTranscript` / `toVitals` /
 * `toActivityFeed`), and threads the URL-synced selection from
 * `useOperatorSelection` down to its children.
 *
 * Task 2 ships the shell only: the real child components (PipelineRail,
 * ItemWorkspace, VitalsCard, ActivityDrawer, ConsoleHeader) land in Tasks 3-9,
 * so each slot renders a small, prop-consuming placeholder for now. Nothing is
 * wired into the live dashboard yet — the behind-a-flag cutover is Task 10.
 *
 * `OperatorConsole` (default) binds the real socket hook. `OperatorConsoleView`
 * (named) is the presentational shell that takes an injected `socket` — the
 * seam that keeps the shell testable without a live provider/WebSocket.
 */

import React, { useMemo } from 'react'
import { useHydraFlowSocket } from '../hooks/useHydraFlowSocket'
import { useOperatorSelection } from './useOperatorSelection'
import { ConsoleHeader } from './ConsoleHeader'
import { PipelineRail } from './PipelineRail'
import { toPipeline } from './model/pipeline'
import { toTranscript } from './model/transcript'
import { toVitals } from './model/vitals'
import { toActivityFeed } from './model/activity'
import { VitalsCard } from './VitalsCard'
import { ActivityDrawer } from './ActivityDrawer'
import { RepoOverview, buildRepoSummaries } from './RepoOverview'
import { RepoSwitcher } from './RepoSwitcher'
import { ItemWorkspace } from './ItemWorkspace'
import { ActiveGrid } from './ActiveGrid'
import { IdleState } from './states/IdleState'
import { PausedState } from './states/PausedState'
import { DisconnectedBanner } from './states/DisconnectedBanner'
import { LoadingState } from './states/LoadingState'

const slotStyle = { minWidth: 0 }

// Active work sits in every stage except 'merged' (which is historical). An
// idle repo has none of it — the calm IdleState replaces the detail workspace.
function pipelineActiveCount(pipeline) {
  return (pipeline?.stages || [])
    .filter(s => s.key !== 'merged')
    .reduce((sum, s) => sum + (s.count || 0), 0)
}

const MODES = [
  { key: 'focus', label: 'Focus' },
  { key: 'all-active', label: 'All active' },
]

const modeToggleStyles = {
  bar: {
    display: 'flex',
    gap: 4,
    marginBottom: 8,
  },
  btn: {
    border: '1px solid var(--border)',
    borderRadius: 6,
    background: 'var(--surface-inset)',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    padding: '3px 10px',
    font: 'inherit',
    fontSize: 11,
    fontWeight: 600,
  },
  btnActive: {
    background: 'var(--accent)',
    color: 'var(--bg)',
    borderColor: 'var(--accent)',
  },
}

/**
 * Focus <-> All-active mode toggle (Task 5). A two-button segmented control;
 * each button calls `select('mode', key)`, which the selection hook mirrors
 * into the URL query (`?mode=all-active`; focus is the clean default).
 * @param {{ mode: string, select: Function }} props
 */
function ModeToggle({ mode, select }) {
  return (
    <div data-testid="mode-toggle" role="group" aria-label="Detail mode" style={modeToggleStyles.bar}>
      {MODES.map(m => (
        <button
          key={m.key}
          type="button"
          data-testid={`mode-toggle-${m.key}`}
          aria-pressed={mode === m.key}
          onClick={() => select('mode', m.key)}
          style={{ ...modeToggleStyles.btn, ...(mode === m.key ? modeToggleStyles.btnActive : null) }}
        >
          {m.label}
        </button>
      ))}
    </div>
  )
}

/**
 * Presentational shell. Takes the socket state as a prop so it can be rendered
 * with a fixture in tests without a live HydraFlowProvider.
 * @param {{ socket: object }} props
 */
export function OperatorConsoleView({ socket = {} }) {
  const { repo, stage, item, mode, select, breadcrumb } = useOperatorSelection()
  const events = socket.events ?? []

  const pipeline = useMemo(
    () => toPipeline({ stages: socket.pipelineIssues, stats: socket.pipelineStats }),
    [socket.pipelineIssues, socket.pipelineStats],
  )
  // Task 9: per-repo portfolio summaries. Only a multi-repo install shows the
  // overview / switcher; a single-repo install drills straight to the pipeline.
  const repos = useMemo(() => buildRepoSummaries(socket), [socket])
  const multiRepo = repos.length > 1
  const showOverview = multiRepo && repo == null
  const transcript = useMemo(() => toTranscript(events, item), [events, item])
  const vitals = useMemo(
    () => toVitals(events, { stagingPromotion: socket.stagingPromotion }),
    [events, socket.stagingPromotion],
  )
  const activity = useMemo(() => toActivityFeed(events), [events])

  // --- State-screen signals (Task 10) --------------------------------------
  // `disconnected` is surfaced additively by useHydraFlowSocket (connected===false).
  const disconnected = socket.disconnected === true
  // "Has data" gates loading vs. disconnected: once anything has arrived we keep
  // the last-known board instead of falling back to skeletons.
  const activeCount = pipelineActiveCount(pipeline)
  const hasData = events.length > 0 || socket.pipelineStats != null || activeCount > 0
  // Loading only when the *real* context reports not-yet-connected AND nothing
  // has landed. A bare `{}` test socket has connected===undefined (not false),
  // so it keeps rendering the full shell — preserving the empty-socket contract.
  const loading = socket.connected === false && !hasData && !disconnected
  const paused = vitals?.factory?.state === 'paused'
  // An idle repo has no active work and nothing drilled into — show the calm
  // idle screen in the detail area (the hero/vitals stay visible).
  const idle = activeCount === 0 && item == null && !showOverview
  const onResume = socket.clearCreditPause || socket.startOrchestrator

  return (
    <div
      data-testid="operator-console"
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100%',
        boxSizing: 'border-box',
      }}
    >
      {disconnected && hasData && <DisconnectedBanner onRetry={socket.reconnect} />}
      {paused && (
        <div style={{ padding: '12px 12px 0' }}>
          <PausedState reason={vitals?.factory?.reason} provider={vitals?.credits?.provider} onResume={onResume} />
        </div>
      )}
      {loading ? (
        <LoadingState />
      ) : (
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'minmax(0, 1fr) 280px',
            gridTemplateAreas: '"header header" "pipeline vitals" "detail vitals" "drawer drawer"',
            gap: 12,
            padding: 12,
            boxSizing: 'border-box',
            flex: 1,
            minHeight: 0,
          }}
        >
      <div data-testid="operator-header-slot" style={{ ...slotStyle, gridArea: 'header' }}>
        <ConsoleHeader
          breadcrumb={breadcrumb}
          select={select}
          vitals={vitals}
          connected={socket.connected}
          onStart={socket.startOrchestrator}
          onStop={socket.stopOrchestrator}
          onClear={socket.clearCreditPause}
        />
      </div>
      <div data-testid="operator-pipeline-slot" style={{ ...slotStyle, gridArea: 'pipeline' }}>
        {multiRepo && (
          <div style={{ marginBottom: 8 }}>
            <RepoSwitcher repos={repos} current={repo} stage={stage} item={item} select={select} />
          </div>
        )}
        {showOverview ? (
          <RepoOverview repos={repos} select={select} />
        ) : (
          <PipelineRail pipeline={pipeline} select={select} stage={stage} />
        )}
      </div>
      <div data-testid="operator-detail-slot" style={{ ...slotStyle, gridArea: 'detail' }}>
        <ModeToggle mode={mode} select={select} />
        {idle ? (
          <IdleState />
        ) : mode === 'all-active' ? (
          <ActiveGrid pipeline={pipeline} events={events} select={select} />
        ) : (
          <ItemWorkspace item={item} transcript={transcript} mode={mode} select={select} />
        )}
      </div>
      <div data-testid="operator-vitals-slot" style={{ ...slotStyle, gridArea: 'vitals' }}>
        <VitalsCard vitals={vitals} />
      </div>
      <div data-testid="operator-drawer-slot" style={{ ...slotStyle, gridArea: 'drawer' }}>
        <ActivityDrawer activity={activity} select={select} />
      </div>
        </div>
      )}
    </div>
  )
}

/**
 * Default export: binds the live WebSocket/REST state (including the additive
 * `disconnected` signal) and renders the shell. Mounted opt-in from App.jsx
 * behind the `?console=operator` / toggle cutover flag (Task 10); the classic
 * dashboard remains the default until parity is human-verified.
 */
export function OperatorConsole() {
  const socket = useHydraFlowSocket()
  return <OperatorConsoleView socket={socket} />
}

export default OperatorConsole
