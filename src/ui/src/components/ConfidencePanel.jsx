import React from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'

const RANK_COLORS = {
  high: theme.green,
  medium: theme.yellow,
  low: theme.red,
}

const RISK_COLORS = {
  low: theme.green,
  medium: theme.yellow,
  high: theme.orange,
  critical: theme.red,
}

const ACTION_COLORS = {
  auto_merge: theme.green,
  stage: theme.accent,
  hold_for_review: theme.yellow,
  escalate_hitl: theme.orange,
  reject: theme.red,
}

function DORAGauges({ dora }) {
  if (!dora) return <div style={styles.emptyState}>No DORA data yet</div>

  const metrics = [
    { label: 'Deploy Freq', value: `${dora.deployment_frequency?.toFixed(1) ?? '—'}/day`, key: 'deployment_frequency' },
    { label: 'Lead Time', value: dora.lead_time_seconds ? `${(dora.lead_time_seconds / 3600).toFixed(1)}h` : '—', key: 'lead_time' },
    { label: 'Change Failure', value: `${((dora.change_failure_rate ?? 0) * 100).toFixed(1)}%`, key: 'cfr' },
    { label: 'Recovery Time', value: dora.recovery_time_seconds ? `${(dora.recovery_time_seconds / 3600).toFixed(1)}h` : '—', key: 'recovery' },
    { label: 'Rework Rate', value: `${((dora.rework_rate ?? 0) * 100).toFixed(1)}%`, key: 'rework' },
  ]

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <span>DORA Metrics</span>
        <span style={{ ...styles.healthBadge, color: dora.healthy ? theme.green : theme.red }}>
          {dora.healthy ? 'Healthy' : 'Degraded'}
        </span>
      </div>
      <div style={styles.gaugeGrid}>
        {metrics.map(m => (
          <div key={m.key} style={styles.gaugeCard}>
            <div style={styles.gaugeValue}>{m.value}</div>
            <div style={styles.gaugeLabel}>{m.label}</div>
          </div>
        ))}
      </div>
    </div>
  )
}

function ConfidenceBar({ name, value }) {
  const width = Math.max(0, Math.min(100, value * 100))
  const barColor = value >= 0.7 ? theme.green : value >= 0.4 ? theme.yellow : theme.red
  return (
    <div style={styles.barRow}>
      <div style={styles.barLabel}>{name}</div>
      <div style={styles.barTrack}>
        <div style={{ ...styles.barFill, width: `${width}%`, background: barColor }} />
      </div>
      <div style={styles.barValue}>{value.toFixed(2)}</div>
    </div>
  )
}

function RecentDecisions({ decisions }) {
  if (!decisions || decisions.length === 0) {
    return <div style={styles.emptyState}>No release decisions yet</div>
  }

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>Recent Decisions</div>
      <div style={styles.tableWrapper}>
        <table style={styles.table}>
          <thead>
            <tr>
              <th style={styles.th}>PR</th>
              <th style={styles.th}>Confidence</th>
              <th style={styles.th}>Risk</th>
              <th style={styles.th}>Action</th>
              <th style={styles.th}>Mode</th>
            </tr>
          </thead>
          <tbody>
            {decisions.slice(0, 15).map((d, i) => (
              <tr key={i} style={i % 2 === 0 ? styles.trEven : styles.trOdd}>
                <td style={styles.td}>#{d.pr}</td>
                <td style={styles.td}>
                  <span style={{ color: RANK_COLORS[d.confidence_rank] || theme.text }}>
                    {(d.confidence_score ?? 0).toFixed(2)} ({d.confidence_rank})
                  </span>
                </td>
                <td style={styles.td}>
                  <span style={{ color: RISK_COLORS[d.risk_level] || theme.text }}>
                    {(d.risk_score ?? 0).toFixed(2)} ({d.risk_level})
                  </span>
                </td>
                <td style={styles.td}>
                  <span style={{ ...styles.actionBadge, color: ACTION_COLORS[d.action] || theme.text }}>
                    {d.action?.replace(/_/g, ' ')}
                  </span>
                </td>
                <td style={styles.td}>
                  <span style={styles.modeBadge}>{d.mode}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function LatestScore({ scores }) {
  const latest = scores?.[0]
  if (!latest) return null

  const components = latest.components || {}
  const sortedComponents = Object.entries(components).sort((a, b) => b[1] - a[1])

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <span>Latest Score — PR #{latest.pr}</span>
        <span style={{ ...styles.rankBadge, color: RANK_COLORS[latest.rank] || theme.text }}>
          {(latest.score ?? 0).toFixed(2)} ({latest.rank})
        </span>
      </div>
      <div style={styles.barsContainer}>
        {sortedComponents.map(([name, value]) => (
          <ConfidenceBar key={name} name={name} value={value} />
        ))}
      </div>
      {latest.summary && <div style={styles.summary}>{latest.summary}</div>}
    </div>
  )
}

function StabilityStatus({ assessment }) {
  if (!assessment) return null

  const postureColors = {
    aggressive: theme.green,
    balanced: theme.yellow,
    conservative: theme.red,
  }

  return (
    <div style={styles.section}>
      <div style={styles.sectionHeader}>
        <span>System Stability</span>
        <span style={{ ...styles.postureBadge, color: postureColors[assessment.risk_posture] || theme.text }}>
          {assessment.risk_posture}
        </span>
      </div>
      <div style={styles.stabilityGrid}>
        <div style={styles.stabilityItem}>
          <div style={styles.stabilityLabel}>DORA Trend</div>
          <div style={styles.stabilityValue}>{assessment.dora_trend}</div>
        </div>
        <div style={styles.stabilityItem}>
          <div style={styles.stabilityLabel}>Decision Accuracy</div>
          <div style={styles.stabilityValue}>
            {((assessment.confidence_accuracy ?? 0) * 100).toFixed(1)}%
          </div>
        </div>
        <div style={styles.stabilityItem}>
          <div style={styles.stabilityLabel}>Suggested Mode</div>
          <div style={styles.stabilityValue}>{assessment.suggested_mode}</div>
        </div>
        <div style={styles.stabilityItem}>
          <div style={styles.stabilityLabel}>Weight Drift</div>
          <div style={styles.stabilityValue}>
            {(assessment.calibration_drift ?? 0).toFixed(3)}
          </div>
        </div>
      </div>
      {assessment.reasoning && assessment.reasoning.length > 0 && (
        <div style={styles.reasoningList}>
          {assessment.reasoning.map((r, i) => (
            <div key={i} style={styles.reasoningItem}>{r}</div>
          ))}
        </div>
      )}
    </div>
  )
}

export function ConfidencePanel() {
  const { state } = useHydraFlow()
  const { confidenceScores, releaseDecisions, doraHealth, stabilityAssessment } = state

  return (
    <div style={styles.container}>
      <DORAGauges dora={doraHealth} />
      <LatestScore scores={confidenceScores} />
      <RecentDecisions decisions={releaseDecisions} />
      <StabilityStatus assessment={stabilityAssessment} />
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    padding: 16,
  },
  section: {
    background: theme.surface,
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
    padding: 16,
  },
  sectionHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    fontSize: 14,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 12,
  },
  emptyState: {
    color: theme.textMuted,
    fontSize: 12,
    textAlign: 'center',
    padding: 24,
  },
  // DORA gauges
  gaugeGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(5, 1fr)',
    gap: 8,
  },
  gaugeCard: {
    background: theme.surfaceInset,
    borderRadius: 6,
    padding: 12,
    textAlign: 'center',
  },
  gaugeValue: {
    fontSize: 16,
    fontWeight: 700,
    color: theme.textBright,
  },
  gaugeLabel: {
    fontSize: 10,
    color: theme.textMuted,
    marginTop: 4,
  },
  healthBadge: {
    fontSize: 11,
    fontWeight: 600,
  },
  // Signal bars
  barsContainer: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
  },
  barRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  barLabel: {
    fontSize: 11,
    color: theme.textMuted,
    width: 100,
    textAlign: 'right',
    flexShrink: 0,
  },
  barTrack: {
    flex: 1,
    height: 8,
    background: theme.surfaceInset,
    borderRadius: 4,
    overflow: 'hidden',
  },
  barFill: {
    height: '100%',
    borderRadius: 4,
    transition: 'width 0.3s ease',
  },
  barValue: {
    fontSize: 11,
    color: theme.text,
    width: 36,
    textAlign: 'right',
    flexShrink: 0,
  },
  rankBadge: {
    fontSize: 13,
    fontWeight: 700,
  },
  summary: {
    fontSize: 11,
    color: theme.textMuted,
    marginTop: 8,
    fontStyle: 'italic',
  },
  // Decision table
  tableWrapper: {
    overflowX: 'auto',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontSize: 12,
  },
  th: {
    textAlign: 'left',
    padding: '6px 8px',
    color: theme.textMuted,
    borderBottom: `1px solid ${theme.border}`,
    fontSize: 11,
    fontWeight: 600,
  },
  td: {
    padding: '6px 8px',
    color: theme.text,
  },
  trEven: {
    background: 'transparent',
  },
  trOdd: {
    background: theme.surfaceInset,
  },
  actionBadge: {
    fontWeight: 600,
    fontSize: 11,
    textTransform: 'capitalize',
  },
  modeBadge: {
    fontSize: 10,
    color: theme.textMuted,
    background: theme.surfaceInset,
    padding: '2px 6px',
    borderRadius: 4,
  },
  // Stability
  postureBadge: {
    fontSize: 12,
    fontWeight: 600,
    textTransform: 'capitalize',
  },
  stabilityGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8,
  },
  stabilityItem: {
    background: theme.surfaceInset,
    borderRadius: 6,
    padding: 8,
    textAlign: 'center',
  },
  stabilityLabel: {
    fontSize: 10,
    color: theme.textMuted,
  },
  stabilityValue: {
    fontSize: 13,
    fontWeight: 600,
    color: theme.textBright,
    marginTop: 2,
    textTransform: 'capitalize',
  },
  reasoningList: {
    marginTop: 8,
  },
  reasoningItem: {
    fontSize: 11,
    color: theme.textMuted,
    padding: '2px 0',
  },
}
