import React from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'

function ConfidenceBadge({ confidence }) {
  const isInsufficient = confidence === 'insufficient_data'
  return (
    <span
      style={isInsufficient ? styles.badgeInsufficient : styles.badgeOk}
      data-testid={isInsufficient ? 'confidence-insufficient' : 'confidence-ok'}
    >
      {isInsufficient ? 'insufficient data' : confidence}
    </span>
  )
}

function ComponentsTable({ components }) {
  if (!components || Object.keys(components).length === 0) return null
  return (
    <div style={styles.componentsTable} data-testid="loop-fitness-components">
      {Object.entries(components).map(([key, val]) => (
        <div key={key} style={styles.componentRow}>
          <span style={styles.componentKey}>{key}</span>
          <span style={styles.componentVal}>
            {val == null ? 'n/a' : typeof val === 'number' ? val.toFixed(3) : String(val)}
          </span>
        </div>
      ))}
    </div>
  )
}

function LoopRow({ workerName, row }) {
  const scoreDisplay = row.score == null ? 'n/a' : row.score.toFixed(3)
  const isInsufficient = row.confidence === 'insufficient_data'
  return (
    <div
      style={isInsufficient ? styles.rowInsufficient : styles.row}
      data-testid={`loop-fitness-row-${workerName}`}
    >
      <div style={styles.rowHeader}>
        <span style={styles.workerName} data-testid={`loop-fitness-name-${workerName}`}>
          {workerName}
        </span>
        <span style={styles.kindBadge}>{row.kind}</span>
      </div>
      <div style={styles.rowMeta}>
        <div style={styles.metaItem}>
          <span style={styles.metaLabel}>score</span>
          <span
            style={row.score == null ? styles.metaValueNa : styles.metaValue}
            data-testid={`loop-fitness-score-${workerName}`}
          >
            {scoreDisplay}
          </span>
        </div>
        <div style={styles.metaItem}>
          <span style={styles.metaLabel}>confidence</span>
          <ConfidenceBadge confidence={row.confidence} />
        </div>
        <div style={styles.metaItem}>
          <span style={styles.metaLabel}>samples</span>
          <span style={styles.metaValue}>{row.sample_count}</span>
        </div>
      </div>
      {row.notes && (
        <div style={styles.notes} data-testid={`loop-fitness-notes-${workerName}`}>
          {row.notes}
        </div>
      )}
      <ComponentsTable components={row.components} />
    </div>
  )
}

export function LoopFitnessPanel() {
  const { loopFitness } = useHydraFlow()

  const entries = Object.entries(loopFitness || {})
    .sort(([a], [b]) => a.localeCompare(b))

  if (entries.length === 0) {
    return (
      <div style={styles.container} data-testid="loop-fitness-panel-root">
        <div style={styles.empty}>No loop fitness data available yet.</div>
      </div>
    )
  }

  return (
    <div style={styles.container} data-testid="loop-fitness-panel-root">
      <div style={styles.header}>
        <h2 style={styles.title}>Loop Fitness</h2>
        <p style={styles.subtitle}>
          Per-loop quality scores, sorted by name. Scores reflect recent behavior — not a ranking.
        </p>
      </div>
      <div style={styles.rows} data-testid="loop-fitness-rows">
        {entries.map(([workerName, row]) => (
          <LoopRow key={workerName} workerName={workerName} row={row} />
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
  rowInsufficient: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surfaceInset,
    opacity: 0.75,
  },
  rowHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 10,
  },
  workerName: {
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
  metaValueNa: {
    fontSize: 14,
    fontWeight: 600,
    color: theme.textInactive,
    fontStyle: 'italic',
  },
  badgeOk: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.green,
    background: theme.greenSubtle,
    borderRadius: 4,
    padding: '2px 8px',
  },
  badgeInsufficient: {
    fontSize: 11,
    fontWeight: 600,
    color: theme.textMuted,
    background: theme.mutedSubtle,
    borderRadius: 4,
    padding: '2px 8px',
    border: `1px dashed ${theme.border}`,
  },
  notes: {
    fontSize: 12,
    color: theme.textMuted,
    fontStyle: 'italic',
    marginBottom: 8,
    paddingLeft: 4,
    borderLeft: `2px solid ${theme.border}`,
  },
  componentsTable: {
    marginTop: 8,
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
    background: theme.surfaceInset,
    borderRadius: 6,
    padding: '8px 12px',
  },
  componentRow: {
    display: 'flex',
    gap: 12,
    alignItems: 'baseline',
  },
  componentKey: {
    fontSize: 11,
    color: theme.textMuted,
    fontFamily: 'monospace',
    minWidth: 160,
    flexShrink: 0,
  },
  componentVal: {
    fontSize: 11,
    color: theme.text,
    fontFamily: 'monospace',
  },
  empty: {
    fontSize: 13,
    color: theme.textMuted,
    padding: 20,
  },
}
