/**
 * OperatorConsole — the pipeline-centric operator shell (epic #10556, Task 2).
 *
 * This is the layout container for the new operator console. It owns four
 * slots — header, pipeline (hero), detail, vitals — consumes the existing
 * WebSocket state via `useHydraFlowSocket` and turns it into the Task-1 view
 * models (`toPipeline` / `toTranscript` / `toVitals`), and threads the
 * URL-synced selection from `useOperatorSelection` down to its children. The
 * bottom Activity drawer was removed (#11) to reclaim vertical space; its
 * `ActivityDrawer` component still exists but is no longer mounted here.
 *
 * Task 2 ships the shell only: the real child components (PipelineRail,
 * ItemWorkspace, VitalsCard, ConsoleHeader) land in Tasks 3-9, so each slot
 * renders a small, prop-consuming placeholder for now. Nothing is wired into
 * the live dashboard yet — the behind-a-flag cutover is Task 10.
 *
 * `OperatorConsole` (default) binds the real socket hook. `OperatorConsoleView`
 * (named) is the presentational shell that takes an injected `socket` — the
 * seam that keeps the shell testable without a live provider/WebSocket.
 *
 * Phase-2 (Task 12): the shell wraps its subtree in a `ThemeProvider` whose
 * mode follows the document's `data-theme` (`useThemeMode`), so every token/
 * primitive descendant flips light ↔ dark off the same signal as the app's
 * CSS-variable theme; and every colour / space value here resolves from
 * `useTokens()` — no inline literals, no hardcoded hex.
 */

import React, { useMemo, useState } from 'react'
import { useHydraFlowSocket } from '../hooks/useHydraFlowSocket'
import { ThemeProvider, useTokens } from '../styles/primitives'
import { useThemeMode } from './useThemeMode'
import { useOperatorSelection } from './useOperatorSelection'
import { ConsoleHeader } from './ConsoleHeader'
import { PipelineRail } from './PipelineRail'
import { toPipeline } from './model/pipeline'
import { toTranscript } from './model/transcript'
import { toVitals, factoryUptimeLabel } from './model/vitals'
import { toLoops } from './model/loops'
import { toReleasePromotion } from './model/release'
import { toSettingsSummary } from './model/settingsSummary'
import { VitalsCard } from './VitalsCard'
import { LoopsPanel } from './LoopsPanel'
import { ReleasePromotionStrip } from './ReleasePromotionStrip'
import { SettingsSummary } from './SettingsSummary'
import { SettingsDrawer } from './SettingsDrawer'
import { RepoOverview, buildRepoSummaries } from './RepoOverview'
import { RepoSwitcher } from './RepoSwitcher'
import { ItemWorkspace } from './ItemWorkspace'
import { ActiveGrid } from './ActiveGrid'
import { IdleState } from './states/IdleState'
import { PausedState } from './states/PausedState'
import { DisconnectedBanner } from './states/DisconnectedBanner'
import { LoadingState } from './states/LoadingState'

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

function makeStyles(t) {
  return {
    root: {
      display: 'flex',
      flexDirection: 'column',
      minHeight: '100%',
      boxSizing: 'border-box',
    },
    pausedWrap: { padding: `${t.space.md}px ${t.space.md}px 0` },
    // The Activity drawer row was removed (#11), reclaiming its vertical space.
    // In focus mode the detail area spans BOTH columns full-width (#8) — the
    // vitals column then only rides the pipeline row; every other mode keeps
    // vitals spanning the pipeline + detail rows.
    grid: (focusFull) => ({
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) 280px',
      gridTemplateAreas: focusFull
        ? '"header header" "pipeline vitals" "detail detail"'
        : '"header header" "pipeline vitals" "detail vitals"',
      gap: t.space.md,
      padding: t.space.md,
      boxSizing: 'border-box',
      flex: 1,
      minHeight: 0,
    }),
    slot: (area) => ({ minWidth: 0, gridArea: area }),
    vitalsSlot: { minWidth: 0, gridArea: 'vitals', display: 'flex', flexDirection: 'column', gap: t.space.md },
    switcherWrap: { marginBottom: t.space.sm },
    toggleBar: { display: 'flex', gap: t.space.xs, marginBottom: t.space.sm },
    toggleBtn: (active) => ({
      border: `1px solid ${active ? t.color.accent : t.color.border}`,
      borderRadius: t.radius.md,
      background: active ? t.color.accent : t.color.surfaceInset,
      color: active ? t.color.bg : t.color.textMuted,
      cursor: 'pointer',
      padding: `3px ${t.space.sm}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
    }),
  }
}

/**
 * Focus <-> All-active mode toggle (Task 5). A two-button segmented control;
 * each button calls `select('mode', key)`, which the selection hook mirrors
 * into the URL query (`?mode=all-active`; focus is the clean default).
 * @param {{ mode: string, select: Function, styles: object }} props
 */
function ModeToggle({ mode, select, styles }) {
  return (
    <div data-testid="mode-toggle" role="group" aria-label="Detail mode" style={styles.toggleBar}>
      {MODES.map(m => (
        <button
          key={m.key}
          type="button"
          data-testid={`mode-toggle-${m.key}`}
          aria-pressed={mode === m.key}
          onClick={() => select('mode', m.key)}
          style={styles.toggleBtn(mode === m.key)}
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
export function OperatorConsoleView({ socket = {}, now = Date.now() }) {
  const themeMode = useThemeMode()
  const t = useTokens(themeMode)
  const styles = makeStyles(t)
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
    () => toVitals(events, {
      stagingPromotion: socket.stagingPromotion,
      // Loop-health count comes from the sticky worker slice (registry-stable),
      // not the moving events window — see toVitals / #10556.
      backgroundWorkers: socket.backgroundWorkers,
    }),
    [events, socket.stagingPromotion, socket.backgroundWorkers],
  )
  // Factory runtime (#12): a compact uptime label derived from the socket's best
  // start signal (active session's started_at, else a session id that encodes
  // its start), measured against the injected `now`. '' when no start signal
  // exists so the header renders nothing.
  const uptime = useMemo(() => factoryUptimeLabel(socket, now), [socket, now])
  // All-loops quick view: the reducer's deduped backgroundWorkers slice for the
  // per-loop snapshot, plus the raw events for restart/error correlation.
  const loops = useMemo(
    () => toLoops(socket.backgroundWorkers, { events }),
    [socket.backgroundWorkers, events],
  )
  // Release Promotion (staging<->main, ADR-0042) — a distinct concern from the
  // workflow pipeline and the background loops; its own strip near the pipeline.
  const release = useMemo(
    () => toReleasePromotion(socket.stagingPromotion, { backgroundWorkers: socket.backgroundWorkers }),
    [socket.stagingPromotion, socket.backgroundWorkers],
  )
  // Settings at-a-glance (key runtime config) + a drawer that reuses the classic
  // System tab for the full configuration surface.
  const settings = useMemo(() => toSettingsSummary(socket.config), [socket.config])
  const [settingsOpen, setSettingsOpen] = useState(false)

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
  // Focus mode (a single ItemWorkspace) claims the full detail width (#8): the
  // detail area spans both grid columns. All-active / overview / idle keep the
  // vitals column beside the detail row.
  const focusFull = !showOverview && !idle && mode !== 'all-active'
  const onResume = socket.clearCreditPause || socket.startOrchestrator

  return (
    <ThemeProvider mode={themeMode}>
      <div data-testid="operator-console" style={styles.root}>
        {disconnected && hasData && <DisconnectedBanner onRetry={socket.reconnect} />}
        {paused && (
          <div style={styles.pausedWrap}>
            <PausedState reason={vitals?.factory?.reason} provider={vitals?.credits?.provider} onResume={onResume} />
          </div>
        )}
        {loading ? (
          <LoadingState />
        ) : (
          <div style={styles.grid(focusFull)}>
            <div data-testid="operator-header-slot" style={styles.slot('header')}>
              <ConsoleHeader
                breadcrumb={breadcrumb}
                select={select}
                vitals={vitals}
                uptime={uptime}
                connected={socket.connected}
                onStart={socket.startOrchestrator}
                onStop={socket.stopOrchestrator}
                onClear={socket.clearCreditPause}
              />
            </div>
            <div data-testid="operator-pipeline-slot" style={styles.slot('pipeline')}>
              {multiRepo && (
                <div style={styles.switcherWrap}>
                  <RepoSwitcher repos={repos} current={repo} stage={stage} item={item} select={select} />
                </div>
              )}
              {showOverview ? (
                <RepoOverview repos={repos} select={select} />
              ) : (
                <PipelineRail pipeline={pipeline} select={select} stage={stage} />
              )}
              {!showOverview && <ReleasePromotionStrip release={release} />}
            </div>
            <div
              data-testid="operator-detail-slot"
              data-fullwidth={focusFull ? 'true' : 'false'}
              style={styles.slot('detail')}
            >
              <ModeToggle mode={mode} select={select} styles={styles} />
              {idle ? (
                <IdleState />
              ) : mode === 'all-active' ? (
                <ActiveGrid pipeline={pipeline} events={events} now={now} select={select} />
              ) : (
                <ItemWorkspace item={item} transcript={transcript} mode={mode} select={select} />
              )}
            </div>
            <div data-testid="operator-vitals-slot" style={styles.vitalsSlot}>
              <VitalsCard vitals={vitals} />
              <LoopsPanel loops={loops} />
              <SettingsSummary summary={settings} onOpenSettings={() => setSettingsOpen(true)} />
            </div>
          </div>
        )}
        <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
      </div>
    </ThemeProvider>
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
