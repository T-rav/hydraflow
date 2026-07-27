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

const slotStyle = { minWidth: 0 }
const placeholderStyle = {
  padding: '8px 12px',
  borderRadius: 6,
  fontSize: 12,
  opacity: 0.7,
  background: 'rgba(127,127,127,0.08)',
}

// ---------------------------------------------------------------------------
// Placeholder children — replaced by the real components in Tasks 3-9. They
// consume the same props the real components will, so the wiring proven here
// stays valid as they land.
// ---------------------------------------------------------------------------

function ItemWorkspacePlaceholder({ item, transcript, mode }) {
  return (
    <div data-testid="item-workspace-placeholder" style={placeholderStyle}>
      ItemWorkspace — item: {item ?? 'none'} · {transcript.length} rows · mode: {mode}
    </div>
  )
}

function ActivityDrawerPlaceholder({ activity }) {
  return (
    <div data-testid="activity-drawer-placeholder" style={placeholderStyle}>
      ActivityDrawer — {activity.length} rows
    </div>
  )
}

/**
 * Presentational shell. Takes the socket state as a prop so it can be rendered
 * with a fixture in tests without a live HydraFlowProvider.
 * @param {{ socket: object }} props
 */
export function OperatorConsoleView({ socket = {} }) {
  const { stage, item, mode, select, breadcrumb } = useOperatorSelection()
  const events = socket.events ?? []

  const pipeline = useMemo(
    () => toPipeline({ stages: socket.pipelineIssues, stats: socket.pipelineStats }),
    [socket.pipelineIssues, socket.pipelineStats],
  )
  const transcript = useMemo(() => toTranscript(events, item), [events, item])
  const vitals = useMemo(
    () => toVitals(events, { stagingPromotion: socket.stagingPromotion }),
    [events, socket.stagingPromotion],
  )
  const activity = useMemo(() => toActivityFeed(events), [events])

  return (
    <div
      data-testid="operator-console"
      style={{
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1fr) 280px',
        gridTemplateAreas: '"header header" "pipeline vitals" "detail vitals" "drawer drawer"',
        gap: 12,
        padding: 12,
        boxSizing: 'border-box',
        minHeight: '100%',
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
        <PipelineRail pipeline={pipeline} select={select} stage={stage} />
      </div>
      <div data-testid="operator-detail-slot" style={{ ...slotStyle, gridArea: 'detail' }}>
        <ItemWorkspacePlaceholder item={item} transcript={transcript} mode={mode} select={select} />
      </div>
      <div data-testid="operator-vitals-slot" style={{ ...slotStyle, gridArea: 'vitals' }}>
        <VitalsCard vitals={vitals} />
      </div>
      <div data-testid="operator-drawer-slot" style={{ ...slotStyle, gridArea: 'drawer' }}>
        <ActivityDrawerPlaceholder activity={activity} select={select} />
      </div>
    </div>
  )
}

/**
 * Default export: binds the live WebSocket/REST state and renders the shell.
 * Not mounted anywhere yet — the flagged cutover is Task 10.
 */
export function OperatorConsole() {
  const socket = useHydraFlowSocket()
  return <OperatorConsoleView socket={socket} />
}

export default OperatorConsole
