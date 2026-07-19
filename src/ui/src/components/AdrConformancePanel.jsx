import React from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'

const OUTCOME_STYLES = {
  pass: 'badgePass',
  fail: 'badgeFail',
  unresolved: 'badgeUnresolved',
  manual: 'badgeManual',
  skipped: 'badgeSkipped',
}

function OutcomeBadge({ outcome }) {
  const styleKey = OUTCOME_STYLES[outcome] || 'badgeUnresolved'
  return (
    <span
      style={styles[styleKey]}
      data-testid={`adr-conformance-outcome-badge-${outcome}`}
    >
      {outcome}
    </span>
  )
}

function ChecksTable({ checks }) {
  if (!checks || checks.length === 0) return null
  return (
    <div style={styles.checksTable} data-testid="adr-conformance-checks">
      {checks.map((check, idx) => (
        <div key={`${check.check}-${idx}`} style={styles.checkRow}>
          <span style={styles.checkName}>{check.check}</span>
          <span style={styles.checkOutcome} data-testid={`adr-conformance-check-outcome-${check.outcome}`}>
            {check.outcome}
          </span>
        </div>
      ))}
    </div>
  )
}

function AdrRow({ adrId, row }) {
  return (
    <div style={styles.row} data-testid={`adr-conformance-row-${adrId}`}>
      <div style={styles.rowHeader}>
        <span style={styles.adrId} data-testid={`adr-conformance-id-${adrId}`}>
          {adrId}
        </span>
        <span style={styles.kindBadge}>{row.kind}</span>
      </div>
      <div style={styles.rowMeta}>
        <div style={styles.metaItem}>
          <span style={styles.metaLabel}>outcome</span>
          <OutcomeBadge outcome={row.outcome} />
        </div>
        <div style={styles.metaItem}>
          <span style={styles.metaLabel}>checks</span>
          <span style={styles.metaValue}>{row.checks?.length ?? 0}</span>
        </div>
      </div>
      <ChecksTable checks={row.checks} />
    </div>
  )
}

export function AdrConformancePanel() {
  const { adrConformance } = useHydraFlow()

  const entries = Object.entries(adrConformance || {})
    .sort(([a], [b]) => a.localeCompare(b))

  if (entries.length === 0) {
    return (
      <div style={styles.container} data-testid="adr-conformance-panel-root">
        <div style={styles.empty}>No ADR conformance data available yet.</div>
      </div>
    )
  }

  return (
    <div style={styles.container} data-testid="adr-conformance-panel-root">
      <div style={styles.header}>
        <h2 style={styles.title}>ADR Conformance</h2>
        <p style={styles.subtitle}>
          Per-ADR enforcement outcomes, sorted by ADR id. Reflects the latest conformance run.
        </p>
      </div>
      <div style={styles.rows} data-testid="adr-conformance-rows">
        {entries.map(([adrId, row]) => (
          <AdrRow key={adrId} adrId={adrId} row={row} />
        ))}
      </div>
    </div>
  )
}

const styles = {
  container: {
    flex: 1,
    overflowY: 'auto',
    padding: 20,
  },
  header: {
    marginBottom: 20,
  },
  title: {
    fontSize: 18,
    fontWeight: 700,
    color: theme.textBright,
    margin: 0,
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 12,
    color: theme.textMuted,
    margin: 0,
  },
  rows: {
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
  },
  row: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surface,
  },
  rowHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  adrId: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.textBright,
    fontFamily: 'monospace',
  },
  kindBadge: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    background: theme.accentSubtle,
    borderRadius: 4,
    padding: '2px 8px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  rowMeta: {
    display: 'flex',
    gap: 24,
    flexWrap: 'wrap',
    marginBottom: 8,
  },
  metaItem: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  metaLabel: {
    fontSize: 10,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  metaValue: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.textBright,
  },
  badgePass: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.green,
    background: theme.greenSubtle,
    borderRadius: 4,
    padding: '2px 8px',
  },
  badgeFail: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.red,
    background: theme.redSubtle,
    borderRadius: 4,
    padding: '2px 8px',
  },
  badgeUnresolved: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    background: theme.mutedSubtle,
    borderRadius: 4,
    padding: '2px 8px',
    border: `1px dashed ${theme.border}`,
  },
  badgeManual: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.yellow,
    background: theme.yellowSubtle,
    borderRadius: 4,
    padding: '2px 8px',
  },
  badgeSkipped: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    background: theme.mutedSubtle,
    borderRadius: 4,
    padding: '2px 8px',
  },
  checksTable: {
    marginTop: 8,
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
    background: theme.surfaceInset,
    borderRadius: 6,
    padding: '8px 12px',
  },
  checkRow: {
    display: 'flex',
    gap: 12,
    alignItems: 'baseline',
    justifyContent: 'space-between',
  },
  checkName: {
    fontSize: 11,
    color: theme.textMuted,
    fontFamily: 'monospace',
    flexShrink: 1,
    overflowWrap: 'anywhere',
  },
  checkOutcome: {
    fontSize: 11,
    color: theme.text,
    fontFamily: 'monospace',
    flexShrink: 0,
  },
  empty: {
    fontSize: 13,
    color: theme.textMuted,
    padding: 20,
  },
}
