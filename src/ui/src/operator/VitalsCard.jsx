/**
 * VitalsCard — color-coded factory health readout (epic #10556, Task 6).
 *
 * Pure presentational component. Consumes the Task-1 `toVitals(...)` view model
 * and renders one color-coded row per vital: factory run-state, loop health
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
 * Phase 1 uses inline styles like the rest of the operator shell; the
 * token/primitive migration is Task 11/12. No backend change; no new deps.
 */

import React from 'react'

const SEVERITY_COLOR = {
  ok: '#3fb950', // green
  warn: '#d29922', // amber
  bad: '#f85149', // red
}

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

function VitalRow({ vitalKey, label, value, severity, detail }) {
  const color = SEVERITY_COLOR[severity]
  return (
    <div
      data-testid={`vital-${vitalKey}`}
      className={`vital-row ${severity}`}
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'baseline',
        gap: 8,
        padding: '6px 8px',
        borderLeft: `3px solid ${color}`,
        borderRadius: 4,
        background: 'rgba(127,127,127,0.06)',
      }}
    >
      <span style={{ fontSize: 12, opacity: 0.8 }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 600, color, textAlign: 'right', minWidth: 0 }}>
        {value}
        {detail ? (
          <span style={{ display: 'block', fontWeight: 400, opacity: 0.7, wordBreak: 'break-word' }}>
            {detail}
          </span>
        ) : null}
      </span>
    </div>
  )
}

export function VitalsCard({ vitals }) {
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
    <div
      data-testid="vitals-card"
      style={{ display: 'flex', flexDirection: 'column', gap: 6, padding: 8, boxSizing: 'border-box' }}
    >
      <div style={{ fontSize: 11, textTransform: 'uppercase', letterSpacing: 0.5, opacity: 0.6 }}>
        Vitals
      </div>
      <VitalRow
        vitalKey="factory"
        label="Factory"
        value={factory.state}
        severity={severityForFactory(factory.state)}
        detail={factory.reason}
      />
      <VitalRow
        vitalKey="loops"
        label="Loops healthy"
        value={`${loopsHealthy.ok}/${loopsHealthy.total}`}
        severity={severityForLoops(loopsHealthy)}
      />
      <VitalRow
        vitalKey="restarts"
        label="Restarts"
        value={restartSummary}
        severity={restarts.length ? 'bad' : 'ok'}
      />
      <VitalRow
        vitalKey="credits"
        label="Credits"
        value={credits.paused ? 'paused' : 'ok'}
        severity={credits.paused ? 'bad' : 'ok'}
        detail={creditsDetail}
      />
      <VitalRow
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
