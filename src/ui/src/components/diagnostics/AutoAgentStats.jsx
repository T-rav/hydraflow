import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'

export function AutoAgentStats() {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let cancelled = false
    const fetchStats = async () => {
      try {
        const res = await fetch('/api/diagnostics/auto-agent')
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        const json = await res.json()
        if (!cancelled) setData(json)
      } catch (e) {
        if (!cancelled) setError(String(e))
      }
    }
    fetchStats()
    const t = setInterval(fetchStats, 30_000)
    return () => {
      cancelled = true
      clearInterval(t)
    }
  }, [])

  if (error) {
    return (
      <div style={styles.section} data-testid="auto-agent-stats-error">
        <h3 style={styles.sectionTitle}>Auto-Agent</h3>
        <div style={{ color: theme.red, fontSize: 12 }}>
          Auto-Agent stats unavailable: {error}
        </div>
      </div>
    )
  }
  if (!data) {
    return (
      <div style={styles.section} data-testid="auto-agent-stats-loading">
        <h3 style={styles.sectionTitle}>Auto-Agent</h3>
        <div style={styles.loading}>Loading…</div>
      </div>
    )
  }

  // Guard against malformed response shapes (e.g. test stubs that return [])
  if (!data.today || !data.last_7d) {
    return (
      <div style={styles.section} data-testid="auto-agent-stats-loading">
        <h3 style={styles.sectionTitle}>Auto-Agent</h3>
        <div style={styles.loading}>Loading…</div>
      </div>
    )
  }

  return (
    <div style={styles.section} data-testid="auto-agent-stats">
      <h3 style={styles.sectionTitle}>Auto-Agent</h3>
      <div style={styles.windowGrid}>
        <Window title="Today (24h)" stats={data.today} />
        <Window title="Last 7 days" stats={data.last_7d} />
      </div>
      <TopSpend rows={data.top_spend} />
    </div>
  )
}

function Window({ title, stats }) {
  return (
    <div style={styles.card}>
      <div style={styles.cardLabel}>{title}</div>
      <div style={styles.statGrid}>
        <span style={styles.statKey}>Spend</span>
        <span style={styles.statValue}>${stats.spend_usd.toFixed(2)}</span>
        <span style={styles.statKey}>Attempts</span>
        <span style={styles.statValue}>{stats.attempts}</span>
        <span style={styles.statKey}>Resolved</span>
        <span style={styles.statValue}>
          {stats.resolved}{' '}
          <span style={styles.statMuted}>({(stats.resolution_rate * 100).toFixed(0)}%)</span>
        </span>
        <span style={styles.statKey}>p50 cost</span>
        <span style={styles.statValue}>${stats.p50_cost_usd.toFixed(2)}</span>
        <span style={styles.statKey}>p95 cost</span>
        <span style={styles.statValue}>${stats.p95_cost_usd.toFixed(2)}</span>
        <span style={styles.statKey}>p50 wall</span>
        <span style={styles.statValue}>{stats.p50_wall_clock_s.toFixed(0)}s</span>
        <span style={styles.statKey}>p95 wall</span>
        <span style={styles.statValue}>{stats.p95_wall_clock_s.toFixed(0)}s</span>
      </div>
    </div>
  )
}

function TopSpend({ rows }) {
  if (!rows?.length) return null
  return (
    <div style={styles.topSpend} data-testid="auto-agent-top-spend">
      <div style={styles.cardLabel}>Top spend (24h)</div>
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Issue</th>
            <th style={styles.th}>Sub-label</th>
            <th style={styles.th}>$</th>
            <th style={styles.th}>s</th>
            <th style={styles.th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.issue}-${r.ts}`} style={styles.tr}>
              <td style={styles.td}>#{r.issue}</td>
              <td style={styles.td}>{r.sub_label}</td>
              <td style={styles.td}>${r.cost_usd.toFixed(2)}</td>
              <td style={styles.td}>{r.wall_clock_s.toFixed(0)}</td>
              <td style={styles.td}>{r.status}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const styles = {
  section: {
    marginTop: 24,
    marginBottom: 24,
  },
  sectionTitle: {
    color: theme.textBright,
    fontSize: 16,
    fontWeight: 700,
    margin: '0 0 16px 0',
  },
  windowGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(2, 1fr)',
    gap: 16,
    marginBottom: 16,
  },
  card: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  cardLabel: {
    color: theme.textMuted,
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 8,
  },
  statGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    rowGap: 4,
    columnGap: 8,
  },
  statKey: {
    color: theme.textMuted,
    fontSize: 12,
  },
  statValue: {
    color: theme.textBright,
    fontSize: 12,
    fontWeight: 600,
    fontVariantNumeric: 'tabular-nums',
  },
  statMuted: {
    color: theme.textMuted,
    fontWeight: 400,
  },
  topSpend: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  table: {
    width: '100%',
    fontSize: 12,
    borderCollapse: 'collapse',
  },
  th: {
    color: theme.textMuted,
    fontWeight: 600,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: '0.3px',
    textAlign: 'left',
    padding: '4px 0',
    borderBottom: `1px solid ${theme.border}`,
  },
  td: {
    color: theme.text,
    padding: '4px 0',
    fontVariantNumeric: 'tabular-nums',
  },
  tr: {},
  loading: {
    color: theme.textMuted,
    fontSize: 12,
    padding: 16,
  },
}
