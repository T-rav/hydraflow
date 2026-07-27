/**
 * ConsoleHeader — the operator console's header slot (epic #10556, Task 8).
 *
 * A presentational header that pulls together everything the operator needs at
 * a glance, top-of-screen:
 *   - a run-state pill driven by the Task-1 vitals VM (`toVitals`), colour-coded
 *     by orchestrator status, that surfaces the credit-pause reason (+ the
 *     provider that ran out) when the factory is paused on credits;
 *   - a compact aggregate-vitals readout (loop health, restarts, main↔staging);
 *   - Start / Stop / Clear controls wired to the *existing* orchestrator control
 *     calls (`startOrchestrator` / `stopOrchestrator` / `clearCreditPause`) — the
 *     same handlers the legacy Header.jsx uses — threaded in as
 *     `onStart` / `onStop` / `onClear`. No endpoint logic is reinvented here;
 *   - the clickable {@link Breadcrumb} trail from `useOperatorSelection` (Task 2).
 *
 * Everything is prop-driven so the header is testable without a live socket /
 * HydraFlowProvider. The default OperatorConsole sources the control handlers
 * and `connected` flag from the injected socket (which is the HydraFlow context
 * value — `useHydraFlowSocket` is an alias for `useHydraFlow`).
 *
 * Styling uses the shared `theme` CSS-variable references so the dark/light
 * paths and the Phase-2 token migration keep working.
 */

import React from 'react'
import { theme } from '../theme'
import { Breadcrumb } from './Breadcrumb'

// Run-state → pill tone. Anything unrecognised falls back to the neutral/idle
// look so an unexpected orchestrator status never renders as "healthy".
const RUNSTATE_TONE = {
  running: { color: theme.green, border: theme.green, bg: theme.greenSubtle },
  paused: { color: theme.orange, border: theme.orange, bg: theme.orangeSubtle },
  stopping: { color: theme.yellow, border: theme.yellow, bg: theme.yellowSubtle },
  idle: { color: theme.textMuted, border: theme.border, bg: theme.surface },
  done: { color: theme.textMuted, border: theme.border, bg: theme.surface },
  unknown: { color: theme.textMuted, border: theme.border, bg: theme.surface },
}

const RUNSTATE_LABEL = {
  running: 'Running',
  paused: 'Paused',
  stopping: 'Stopping…',
  idle: 'Idle',
  done: 'Idle',
  unknown: 'Unknown',
}

const styles = {
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    flexWrap: 'wrap',
    padding: '8px 12px',
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    background: theme.surface,
    boxSizing: 'border-box',
    minWidth: 0,
  },
  breadcrumbSlot: {
    flex: '1 1 auto',
    minWidth: 0,
  },
  statusGroup: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    flexWrap: 'wrap',
  },
  pill: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    borderRadius: 999,
    padding: '3px 10px',
    fontSize: 11,
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    whiteSpace: 'nowrap',
  },
  dot: {
    width: 7,
    height: 7,
    borderRadius: '50%',
    flexShrink: 0,
  },
  creditReason: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.orange,
    maxWidth: 280,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  vitals: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    fontSize: 11,
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
    whiteSpace: 'nowrap',
  },
  vitalStrong: {
    color: theme.textBright,
    fontWeight: 700,
  },
  vitalBad: {
    color: theme.red,
    fontWeight: 700,
  },
  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    flexShrink: 0,
  },
  btnBase: {
    padding: '5px 12px',
    borderRadius: 6,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  },
}

const startBtn = { ...styles.btnBase, border: `1px solid ${theme.green}`, background: theme.greenSubtle, color: theme.green }
const stopBtn = { ...styles.btnBase, border: `1px solid ${theme.red}`, background: theme.redSubtle, color: theme.red }
const clearBtn = { ...styles.btnBase, border: `1px solid ${theme.orange}`, background: theme.orangeSubtle, color: theme.orange }
const disabledBtn = { opacity: 0.4, cursor: 'not-allowed' }

function controlStyle(base, disabled) {
  return disabled ? { ...base, ...disabledBtn } : base
}

const EMPTY_VITALS = {
  factory: { state: 'unknown', reason: null },
  loopsHealthy: { ok: 0, total: 0 },
  restarts: [],
  credits: { paused: false, pausedUntil: null, provider: null },
  mainStagingSync: { state: 'unknown', openPrNumber: null },
}

/**
 * @param {{
 *   vitals?: object,          // toVitals(...) view model
 *   breadcrumb?: Array,       // useOperatorSelection().breadcrumb
 *   select?: (kind: string, value: unknown) => void,
 *   connected?: boolean,      // socket.connected — controls disabled when false
 *   onStart?: () => void,     // socket.startOrchestrator
 *   onStop?: () => void,      // socket.stopOrchestrator
 *   onClear?: () => void,     // socket.clearCreditPause
 * }} props
 */
export function ConsoleHeader({
  vitals = EMPTY_VITALS,
  breadcrumb = [],
  select = () => {},
  connected = false,
  onStart = () => {},
  onStop = () => {},
  onClear = () => {},
}) {
  const factory = vitals?.factory ?? EMPTY_VITALS.factory
  const loops = vitals?.loopsHealthy ?? EMPTY_VITALS.loopsHealthy
  const credits = vitals?.credits ?? EMPTY_VITALS.credits
  const restarts = vitals?.restarts ?? EMPTY_VITALS.restarts
  const sync = vitals?.mainStagingSync ?? EMPTY_VITALS.mainStagingSync

  const state = factory.state || 'unknown'
  const tone = RUNSTATE_TONE[state] ?? RUNSTATE_TONE.unknown
  const label = RUNSTATE_LABEL[state] ?? state
  const paused = !!credits.paused

  // The factory is "up" when running or credit-paused (a credit pause blocks
  // work but leaves the orchestrator running) — Stop is available in both.
  const runningLike = state === 'running' || state === 'paused'
  const stopping = state === 'stopping'

  const startDisabled = !connected || runningLike || stopping
  const stopDisabled = !connected || !runningLike
  const clearDisabled = !connected || !paused

  const restartTotal = restarts.reduce((sum, r) => sum + (r?.count ?? 0), 0)
  const loopsBad = loops.total > 0 && loops.ok < loops.total
  const syncBehind = sync.state === 'behind'

  return (
    <header data-testid="console-header" style={styles.header}>
      <div style={styles.breadcrumbSlot}>
        <Breadcrumb breadcrumb={breadcrumb} select={select} />
      </div>

      <div style={styles.statusGroup}>
        <span
          data-testid="console-header-runstate"
          data-state={state}
          role="status"
          aria-label={`Factory: ${label}`}
          style={{ ...styles.pill, color: tone.color, border: `1px solid ${tone.border}`, background: tone.bg }}
        >
          <span style={{ ...styles.dot, background: tone.color }} />
          {label}
        </span>

        {paused && (factory.reason || credits.provider) && (
          <span
            data-testid="console-header-credit-reason"
            style={styles.creditReason}
            title={factory.reason || undefined}
          >
            {factory.reason || 'credits paused'}
            {credits.provider ? ` (${credits.provider})` : ''}
          </span>
        )}

        <span style={styles.vitals}>
          <span data-testid="console-header-loops">
            loops <span style={loopsBad ? styles.vitalBad : styles.vitalStrong}>{loops.ok}/{loops.total}</span>
          </span>
          {restartTotal > 0 && (
            <span data-testid="console-header-restarts">
              restarts <span style={styles.vitalBad}>{restartTotal}</span>
            </span>
          )}
          {syncBehind && (
            <span data-testid="console-header-sync" style={styles.vitalStrong}>
              main↔staging behind{sync.openPrNumber ? ` #${sync.openPrNumber}` : ''}
            </span>
          )}
        </span>
      </div>

      <div style={styles.controls} data-testid="console-header-controls">
        <button
          type="button"
          data-testid="console-header-start"
          style={controlStyle(startBtn, startDisabled)}
          disabled={startDisabled}
          onClick={() => onStart?.()}
        >
          Start
        </button>
        <button
          type="button"
          data-testid="console-header-stop"
          style={controlStyle(stopBtn, stopDisabled)}
          disabled={stopDisabled}
          onClick={() => onStop?.()}
        >
          Stop
        </button>
        <button
          type="button"
          data-testid="console-header-clear"
          style={controlStyle(clearBtn, clearDisabled)}
          disabled={clearDisabled}
          title="Clear credit pause"
          onClick={() => onClear?.()}
        >
          Clear
        </button>
      </div>
    </header>
  )
}

export default ConsoleHeader
