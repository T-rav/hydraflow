import React from 'react'
import { theme } from '../../theme'

/**
 * Top-line KPIs for the Factory Cost tab (§4.11p2 Task 11).
 *
 * Reads `/api/diagnostics/cost/rolling-24h` (fetched by the parent
 * FactoryCostTab) and surfaces the four headline metrics the operator
 * wants at a glance: cost in the last 24h, total input/output tokens,
 * and total LLM call count.
 *
 * `llm_calls` is not in the rolling-24h top-level totals; we derive it
 * from `rolling24h.by_loop[*].llm_calls` when present (from the per-loop
 * dashboard rollup schema) and fall back to 0 otherwise so this tile is
 * resilient to schema drift.
 */

function fmtUsd(n) {
  if (typeof n !== 'number' || !isFinite(n)) return '$0.00'
  return `$${n.toFixed(2)}`
}

function fmtInt(n) {
  if (typeof n !== 'number' || !isFinite(n)) return '0'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}K`
  return String(Math.round(n))
}

function totalLlmCalls(rolling24h) {
  const byLoop = rolling24h && Array.isArray(rolling24h.by_loop) ? rolling24h.by_loop : []
  let sum = 0
  for (const row of byLoop) {
    sum += Number(row && row.llm_calls) || 0
  }
  return sum
}

export function FactoryCostSummary({ rolling24h, error }) {
  if (error) {
    return <div style={styles.error}>Cost summary failed to load: {String(error)}</div>
  }
  if (!rolling24h) {
    return <div style={styles.loading}>Loading cost summary…</div>
  }

  const totals = rolling24h.total || {}
  const cost = Number(totals.cost_usd) || 0
  const tokensIn = Number(totals.tokens_in) || 0
  const tokensOut = Number(totals.tokens_out) || 0
  const llmCalls = totalLlmCalls(rolling24h)

  return (
    <div style={styles.row}>
      <Card label="Cost (24h)" value={fmtUsd(cost)} accent={theme.accent} />
      <Card label="Tokens In (24h)" value={fmtInt(tokensIn)} accent={theme.green} />
      <Card label="Tokens Out (24h)" value={fmtInt(tokensOut)} accent={theme.cyan} />
      <Card label="LLM Calls (24h)" value={fmtInt(llmCalls)} accent={theme.purple} />
    </div>
  )
}

function Card({ label, value, accent }) {
  return (
    <div style={{ ...styles.card, borderLeftColor: accent }}>
      <div style={styles.value}>{value}</div>
      <div style={styles.label}>{label}</div>
    </div>
  )
}

const styles = {
  row: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 16,
    marginBottom: 24,
  },
  card: {
    background: theme.surfaceInset,
    borderLeft: '4px solid',
    borderLeftColor: theme.accent,
    borderRadius: 8,
    padding: '16px 20px',
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
  },
  value: {
    fontSize: 28,
    fontWeight: 700,
    color: theme.textBright,
  },
  label: {
    fontSize: 11,
    color: theme.textMuted,
    textTransform: 'uppercase',
    letterSpacing: 1,
  },
  loading: {
    color: theme.textMuted,
    padding: 16,
  },
  error: {
    color: theme.red,
    padding: 16,
    fontSize: 12,
  },
}
