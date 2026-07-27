/**
 * VitalsCard — color-coded factory health readout (epic #10556, Task 6).
 *
 * Pure presentational component. Consumes the Task-1 `toVitals(...)` view model
 * and renders one color-coded row per vital: the factory run-state (labelled
 * "Workflow" — it monitors the workflow / assembly line, #15), loop health
 * (ok/total), recently-restarted loops, credit state, and main↔staging sync.
 * Each row carries an `ok` | `warn` | `bad` severity class (and a matching
 * accent color) so an operator can read factory health at a glance — the class
 * *is* the color-coding contract the tests pin.
 *
 * Severity rules:
 *   factory  — running → ok · error/crashed → bad · else (paused/idle/…) → warn
 *   loops    — ok === total → ok · none reported → warn · otherwise → bad
 *   restarts — any restart → bad · none → ok
 *   credits  — paused → bad · otherwise → ok
 *   sync     — in_sync → ok · behind/unknown → warn
 *
 * Phase-2 token migration (Task 12): every colour / space / radius value now
 * resolves from the token layer via `useTokens()` and the shared primitives
 * (`Stack` / `Text`) — no hardcoded hex, so light + dark both fall out of the
 * token mode supplied by the console's ThemeProvider.
 */

import React from 'react'
import { useTokens, Text } from '../styles/primitives'

// Severity → token colour key + the `Text` tone that renders it.
const SEVERITY_COLOR_KEY = { ok: 'green', warn: 'yellow', bad: 'red' }
const SEVERITY_TEXT_TONE = { ok: 'success', warn: 'warning', bad: 'danger' }

const SYNC_LABEL = {
  in_sync: 'in sync',
  behind: 'behind',
  unknown: 'unknown',
}

function severityForFactory(state) {
  if (state === 'running') return 'ok'
  if (state === 'error' || state === 'crashed') return 'bad'
  return 'warn' // paused / idle / stopped / unknown
}

function severityForLoops({ ok, total }) {
  if (!total) return 'warn'
  return ok === total ? 'ok' : 'bad'
}

function makeStyles(t) {
  return {
    card: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.sm,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    row: (severity) => ({
      display: 'flex',
      justifyContent: 'space-between',
      alignItems: 'baseline',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px`,
      borderLeft: `3px solid ${t.color[SEVERITY_COLOR_KEY[severity]]}`,
      borderRadius: t.radius.sm,
      backgroundColor: `color-mix(in srgb, ${t.color.textMuted} 8%, transparent)`,
    }),
    value: { textAlign: 'right', minWidth: 0 },
    detail: { display: 'block', fontWeight: t.type.weight.regular, opacity: 0.7, wordBreak: 'break-word' },
  }
}

function VitalRow({ styles, vitalKey, label, value, severity, detail }) {
  return (
    <div
      data-testid={`vital-${vitalKey}`}
      className={`vital-row ${severity}`}
      style={styles.row(severity)}
    >
      <Text size="sm" tone="muted">{label}</Text>
      <Text as="span" size="sm" weight="semibold" tone={SEVERITY_TEXT_TONE[severity]} style={styles.value}>
        {value}
        {detail ? (
          <Text as="span" size="sm" tone="muted" style={styles.detail}>
            {detail}
          </Text>
        ) : null}
      </Text>
    </div>
  )
}

export function VitalsCard({ vitals }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const { factory, loopsHealthy, restarts, credits, mainStagingSync } = vitals

  const restartSummary = restarts.length
    ? restarts.map(r => `${r.loop} ×${r.count}`).join(', ')
    : 'none'

  const creditsDetail = credits.paused
    ? [credits.provider, credits.pausedUntil ? `until ${credits.pausedUntil}` : null]
        .filter(Boolean)
        .join(' · ') || null
    : null

  const syncDetail = mainStagingSync.openPrNumber ? `RC PR #${mainStagingSync.openPrNumber}` : null

  return (
    <div data-testid="vitals-card" style={styles.card}>
      <Text size="xs" weight="semibold" tone="muted" uppercase>
        Vitals
      </Text>
      <VitalRow
        styles={styles}
        vitalKey="factory"
        label="Workflow"
        value={factory.state}
        severity={severityForFactory(factory.state)}
        detail={factory.reason}
      />
      <VitalRow
        styles={styles}
        vitalKey="loops"
        label="Loops healthy"
        value={`${loopsHealthy.ok}/${loopsHealthy.total}`}
        severity={severityForLoops(loopsHealthy)}
      />
      <VitalRow
        styles={styles}
        vitalKey="restarts"
        label="Restarts"
        value={restartSummary}
        severity={restarts.length ? 'bad' : 'ok'}
      />
      <VitalRow
        styles={styles}
        vitalKey="credits"
        label="Credits"
        value={credits.paused ? 'paused' : 'ok'}
        severity={credits.paused ? 'bad' : 'ok'}
        detail={creditsDetail}
      />
      <VitalRow
        styles={styles}
        vitalKey="sync"
        label="main ↔ staging"
        value={SYNC_LABEL[mainStagingSync.state] ?? mainStagingSync.state}
        severity={mainStagingSync.state === 'in_sync' ? 'ok' : 'warn'}
        detail={syncDetail}
      />
    </div>
  )
}

export default VitalsCard
