/**
 * OperatorConsole — the pipeline-centric operator shell (epic #10556, Task 2).
 *
 * This is the layout container for the new operator console. It owns five
 * slots — header, pipeline (hero), detail, vitals, and a full-width bottom
 * timeline — consumes the existing WebSocket state via `useHydraFlowSocket` and
 * turns it into the Task-1 view models (`toPipeline` / `toTranscript` /
 * `toVitals` / `toTimeline`), and threads the URL-synced selection from
 * `useOperatorSelection` down to its children. The old bottom Activity drawer was
 * removed (#11); its reclaimed space now hosts the phase-container timeline
 * (`TimelinePanel`, feat/operator-timeline), a vertical timeline of pipeline
 * phases with events + PR/commit diffs folded inside each phase. The
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

import React, { useEffect, useMemo, useState } from 'react'
import { useHydraFlowSocket } from '../hooks/useHydraFlowSocket'
import { ThemeProvider, useTokens } from '../styles/primitives'
import { useThemeMode } from './useThemeMode'
import { useOperatorSelection } from './useOperatorSelection'
import { ConsoleHeader } from './ConsoleHeader'
import { PipelineRail } from './PipelineRail'
import { toPipeline } from './model/pipeline'
import { toTranscript } from './model/transcript'
import { toTimeline } from './model/timeline'
import { toVitals, factoryUptimeLabel } from './model/vitals'
import { toLoops } from './model/loops'
import { toReleasePromotion } from './model/release'
import { toSettingsSummary } from './model/settingsSummary'
import { VitalsCard } from './VitalsCard'
import { LoopsPanel } from './LoopsPanel'
import { CostPanel } from './CostPanel'
import { useCostByRepo } from './useCostByRepo'
import { EMPTY_COST_VM } from './model/cost'
import { SupervisorPanel } from './SupervisorPanel'
import { useSupervisorThread } from './useSupervisorThread'
import { EMPTY_SUPERVISOR_VM } from './model/supervisorThread'
import { FinderFaceplatePanel } from './FinderFaceplatePanel'
import { useFinderFaceplates } from './useFinderFaceplates'
import { EMPTY_FINDER_FACEPLATES_VM } from './model/finderFaceplates'
import { LoopFaceplatePanel } from './LoopFaceplatePanel'
import { useLoopFaceplates } from './useLoopFaceplates'
import { toLoopFaceplates } from './model/loopFaceplates'
import { JudgeCalibrationPanel } from './JudgeCalibrationPanel'
import { useJudgeCalibration } from './useJudgeCalibration'
import { EMPTY_JUDGE_CALIBRATION_VM } from './model/judgeCalibration'
import { ReleasePromotionStrip } from './ReleasePromotionStrip'
import { SettingsSummary } from './SettingsSummary'
import { SettingsDrawer } from './SettingsDrawer'
import { RepoOverview, buildRepoSummaries } from './RepoOverview'
import { RepoSwitcher } from './RepoSwitcher'
import { ItemWorkspace } from './ItemWorkspace'
import { ActiveGrid } from './ActiveGrid'
import { TimelinePanel } from './TimelinePanel'
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
  // The 'all-active' mode is the redesigned AGENT view (#10944): live/held
  // workers with an explicit state. The URL key stays 'all-active' (selection
  // contract); only the operator-facing label reads 'Agents'.
  { key: 'all-active', label: 'Agents' },
  // Instruments: the finder/loop faceplates + judge calibration promoted out
  // of the vitals rail into a full-width grid (the #10942 primary-surface
  // direction) — eight stacked rail panels had turned the 280px column into
  // an endless scroll.
  { key: 'instruments', label: 'Instruments' },
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
    // The Activity drawer row was removed (#11); its reclaimed bottom space now
    // hosts the full-width phase-container timeline (feat/operator-timeline),
    // spanning BOTH columns beneath the detail/vitals rows. In focus mode the
    // detail area spans both columns full-width (#8) — the vitals column then only
    // rides the pipeline row; every other mode keeps vitals spanning the pipeline
    // + detail rows. The timeline row is always full-width at the bottom.
    grid: (focusFull) => ({
      display: 'grid',
      gridTemplateColumns: 'minmax(0, 1fr) 280px',
      gridTemplateAreas: focusFull
        ? '"header header" "pipeline vitals" "detail detail" "timeline timeline"'
        : '"header header" "pipeline vitals" "detail vitals" "timeline timeline"',
      gap: t.space.md,
      padding: t.space.md,
      boxSizing: 'border-box',
      flex: 1,
      minHeight: 0,
    }),
    slot: (area) => ({ minWidth: 0, gridArea: area }),
    vitalsSlot: { minWidth: 0, gridArea: 'vitals', display: 'flex', flexDirection: 'column', gap: t.space.md },
    // Instruments mode: full-width responsive card grid in the detail slot.
    instrumentsGrid: {
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))',
      gap: t.space.md,
      alignItems: 'start',
    },
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
 * Focus / Agents / Instruments mode toggle (Task 5, #10942). A segmented control;
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
export function OperatorConsoleView({ socket = {}, now = Date.now(), cost = EMPTY_COST_VM, supervisor = EMPTY_SUPERVISOR_VM, faceplates = EMPTY_FINDER_FACEPLATES_VM, calibration = EMPTY_JUDGE_CALIBRATION_VM, loopFaceplatesRaw = null }) {
  const themeMode = useThemeMode()
  const t = useTokens(themeMode)
  const styles = makeStyles(t)
  const { repo, stage, item, mode, select, breadcrumb } = useOperatorSelection()
  const events = socket.events ?? []

  const pipeline = useMemo(
    () => toPipeline({ stages: socket.pipelineIssues, stats: socket.pipelineStats }),
    [socket.pipelineIssues, socket.pipelineStats],
  )
  // Loop faceplates (#10826): the static register half arrives via the poll
  // hook; the live half (PV/quiescence) is the WS backgroundWorkers slice, so
  // the join recomputes on every WS frame without refetching.
  const loopFaceplates = useMemo(
    () => toLoopFaceplates(loopFaceplatesRaw, socket.backgroundWorkers),
    [loopFaceplatesRaw, socket.backgroundWorkers],
  )
  // Task 9: per-repo portfolio summaries. Only a multi-repo install shows the
  // overview / switcher; a single-repo install drills straight to the pipeline.
  const repos = useMemo(() => buildRepoSummaries(socket), [socket])
  const multiRepo = repos.length > 1
  const showOverview = multiRepo && repo == null
  const transcript = useMemo(() => toTranscript(events, item), [events, item])
  // Phase-container timeline (feat/operator-timeline): the event stream folded
  // into chronological phase cards. `now` is injected so the open phase's
  // duration is deterministic; `item` scopes it to the drilled issue (all active
  // issues when nothing is drilled in).
  const timeline = useMemo(() => toTimeline(events, { item, now }), [events, item, now])
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
  // Instruments mode is exempt (#11203 review): it shows GLOBAL diagnostics
  // (noise floors, loop control register, judge calibration) that matter
  // precisely when the pipeline is quiet — pre-promotion these panels were
  // always visible in the rail, so gating them behind idle would regress.
  const idle =
    activeCount === 0 && item == null && !showOverview && mode !== 'instruments'
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
                <ActiveGrid
                  pipeline={pipeline}
                  workers={socket.workers}
                  events={events}
                  factory={vitals?.factory}
                  credits={vitals?.credits}
                  now={now}
                  select={select}
                />
              ) : mode === 'instruments' ? (
                <div data-testid="instruments-grid" style={styles.instrumentsGrid}>
                  <FinderFaceplatePanel faceplates={faceplates} />
                  <LoopFaceplatePanel faceplates={loopFaceplates} />
                  <JudgeCalibrationPanel calibration={calibration} />
                </div>
              ) : (
                <ItemWorkspace item={item} transcript={transcript} mode={mode} select={select} />
              )}
            </div>
            <div data-testid="operator-vitals-slot" style={styles.vitalsSlot}>
              <VitalsCard vitals={vitals} />
              <CostPanel cost={cost} />
              <SupervisorPanel
                supervisor={supervisor}
                onResume={socket.startOrchestrator}
                onPause={socket.stopOrchestrator}
                onRestartLoop={socket.restartLoop}
                onAckEscalations={socket.ackEscalations}
              />
              {/* Finder/Loop faceplates + judge calibration moved to the
                  full-width Instruments mode (the #10942 primary-surface
                  promotion) — the rail keeps only glanceable panels. */}
              <LoopsPanel loops={loops} />
              <SettingsSummary summary={settings} onOpenSettings={() => setSettingsOpen(true)} />
            </div>
            <div data-testid="operator-timeline-slot" style={styles.slot('timeline')}>
              <TimelinePanel timeline={timeline} />
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
// One-second wall-clock tick. The view previously defaulted `now` to a bare
// `Date.now()` PARAMETER DEFAULT, so every render — and the WS context
// re-renders this tree on every event — produced a fresh `now`, invalidating
// the `toTimeline`/`uptime` useMemos and re-deriving the O(MAX_EVENTS)
// timeline transform per render (#100 slowness investigation). A 1s state
// tick keeps `now` referentially stable between ticks.
function useNowTick(intervalMs = 1000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
  return now
}

export function OperatorConsole() {
  const socket = useHydraFlowSocket()
  const now = useNowTick()
  // Cost feed (#10785): polls the repo + per-repo cost-per-model rollup on its
  // own pinned cadence (aborted in-flight on unmount), independent of the WS
  // slice the shell otherwise renders from.
  const cost = useCostByRepo()
  // Supervisor thread (#10733, ADR-0124): polls the Tier-2 goal-supervisor's
  // append-only observation thread on its own pinned cadence (aborted in-flight
  // on unmount), independent of the WS slice the shell otherwise renders from.
  const supervisor = useSupervisorThread()
  // Finder faceplates (#10826): polls the read-only join of each generative
  // finder's measured noise floor against its live finding-rate on its own pinned
  // cadence (aborted in-flight on unmount), independent of the WS slice.
  const faceplates = useFinderFaceplates()
  // Loop faceplates (#10826): polls the STATIC control-register half (fleet
  // class + setpoint + floor sigma) on its own pinned cadence; the view joins
  // it against the live backgroundWorkers WS slice client-side.
  const loopFaceplatesRaw = useLoopFaceplates()
  // Judge calibration (#10836): polls the read-only proper-scoring report for
  // each review judge (calibration ECE + discrimination AUC, resolved against
  // the escape ledger) on its own pinned cadence (aborted in-flight on unmount),
  // independent of the WS slice.
  const calibration = useJudgeCalibration()
  return <OperatorConsoleView socket={socket} now={now} cost={cost} supervisor={supervisor} faceplates={faceplates} calibration={calibration} loopFaceplatesRaw={loopFaceplatesRaw} />
}

export default OperatorConsole
