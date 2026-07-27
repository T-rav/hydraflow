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
 * Phase-2 (Task 12): the header surface uses the `Card` primitive and every
 * colour / space value resolves from `useTokens()`; the tinted status/control
 * accents are derived from token colours (subtle fills via `color-mix`), so
 * light + dark fall out of the console's ThemeProvider mode — no hardcoded hex.
 */

import React from 'react'
import { useTokens, Card } from '../styles/primitives'
import { Breadcrumb } from './Breadcrumb'

// Run-state → token colour keys. Anything unrecognised falls back to the
// neutral/idle look so an unexpected orchestrator status never renders as
// "healthy". `tinted` marks states whose pill carries a subtle coloured fill;
// neutral states sit on the plain surface.
const RUNSTATE_TONE = {
  running: { color: 'green', tinted: true },
  paused: { color: 'orange', tinted: true },
  stopping: { color: 'yellow', tinted: true },
  idle: { color: 'textMuted', tinted: false },
  done: { color: 'textMuted', tinted: false },
  unknown: { color: 'textMuted', tinted: false },
}

const RUNSTATE_LABEL = {
  running: 'Running',
  paused: 'Paused',
  stopping: 'Stopping…',
  idle: 'Idle',
  done: 'Idle',
  unknown: 'Unknown',
}

// A subtle fill derived from a token colour (mirrors the primitives' helper),
// so the tint flips with the mode alongside the colour it is derived from.
function subtle(color, pct = 15) {
  return `color-mix(in srgb, ${color} ${pct}%, transparent)`
}

function makeStyles(t) {
  const controlBase = {
    padding: `${t.space.xs}px ${t.space.md}px`,
    borderRadius: t.radius.md,
    fontSize: t.type.size.sm,
    fontWeight: t.type.weight.bold,
    cursor: 'pointer',
    transition: 'opacity 0.15s',
  }
  const control = (colorKey) => ({
    ...controlBase,
    border: `1px solid ${t.color[colorKey]}`,
    background: subtle(t.color[colorKey]),
    color: t.color[colorKey],
  })
  return {
    header: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.md,
      flexWrap: 'wrap',
      padding: `${t.space.sm}px ${t.space.md}px`,
      boxSizing: 'border-box',
      minWidth: 0,
    },
    breadcrumbSlot: { flex: '1 1 auto', minWidth: 0 },
    statusGroup: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      flexWrap: 'wrap',
    },
    pill: (toneKey, tinted) => ({
      display: 'inline-flex',
      alignItems: 'center',
      gap: t.space.xs,
      borderRadius: t.radius.pill,
      padding: `3px ${t.space.md}px`,
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.bold,
      textTransform: 'uppercase',
      letterSpacing: t.type.tracking.wide,
      whiteSpace: 'nowrap',
      color: t.color[toneKey],
      border: `1px solid ${tinted ? t.color[toneKey] : t.color.border}`,
      background: tinted ? subtle(t.color[toneKey]) : t.color.surface,
    }),
    dot: (toneKey) => ({
      width: 7,
      height: 7,
      borderRadius: t.radius.pill,
      flexShrink: 0,
      background: t.color[toneKey],
    }),
    creditReason: {
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
      color: t.color.orange,
      maxWidth: 280,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    },
    vitals: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      fontSize: t.type.size.xs,
      color: t.color.textMuted,
      fontVariantNumeric: 'tabular-nums',
      whiteSpace: 'nowrap',
    },
    vitalStrong: { color: t.color.textBright, fontWeight: t.type.weight.bold },
    vitalBad: { color: t.color.red, fontWeight: t.type.weight.bold },
    controls: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.xs,
      flexShrink: 0,
    },
    startBtn: control('green'),
    stopBtn: control('red'),
    clearBtn: control('orange'),
    disabledBtn: { opacity: 0.4, cursor: 'not-allowed' },
  }
}

function controlStyle(base, disabledStyle, disabled) {
  return disabled ? { ...base, ...disabledStyle } : base
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
  const t = useTokens()
  const styles = makeStyles(t)

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
    <Card as="header" data-testid="console-header" style={styles.header}>
      <div style={styles.breadcrumbSlot}>
        <Breadcrumb breadcrumb={breadcrumb} select={select} />
      </div>

      <div style={styles.statusGroup}>
        <span
          data-testid="console-header-runstate"
          data-state={state}
          role="status"
          aria-label={`Factory: ${label}`}
          style={styles.pill(tone.color, tone.tinted)}
        >
          <span style={styles.dot(tone.color)} />
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
          style={controlStyle(styles.startBtn, styles.disabledBtn, startDisabled)}
          disabled={startDisabled}
          onClick={() => onStart?.()}
        >
          Start
        </button>
        <button
          type="button"
          data-testid="console-header-stop"
          style={controlStyle(styles.stopBtn, styles.disabledBtn, stopDisabled)}
          disabled={stopDisabled}
          onClick={() => onStop?.()}
        >
          Stop
        </button>
        <button
          type="button"
          data-testid="console-header-clear"
          style={controlStyle(styles.clearBtn, styles.disabledBtn, clearDisabled)}
          disabled={clearDisabled}
          title="Clear credit pause"
          onClick={() => onClear?.()}
        >
          Clear
        </button>
      </div>
    </Card>
  )
}

export default ConsoleHeader
