import React, { useEffect, useState } from 'react'
import { theme } from '../../theme'
import { useHydraFlow } from '../../context/HydraFlowContext'

/**
 * Inline SVG sparkline — renders a polyline from an array of numeric values.
 *
 * `hoverIndex`/`onHover` are optional: when provided, the sparkline reports
 * the nearest data-point index under the pointer and draws a cursor line at
 * `hoverIndex` — letting a caller drive several sparklines from one shared
 * hover position (see `CompanionGraphs`).
 */
function Sparkline({ values, width = 120, height = 32, color = theme.accent, hoverIndex = null, onHover }) {
  if (!values || values.length < 2) return null
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  const coords = values.map((v, i) => ({
    x: (i / (values.length - 1)) * width,
    y: height - ((v - min) / range) * (height - 4) - 2,
  }))
  const points = coords.map(({ x, y }) => `${x},${y}`).join(' ')

  const handleMouseMove = (e) => {
    if (!onHover) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = rect.width ? (e.clientX - rect.left) / rect.width : 0
    const idx = Math.round(ratio * (values.length - 1))
    onHover(Math.max(0, Math.min(values.length - 1, idx)))
  }
  const handleMouseLeave = () => onHover && onHover(null)

  return (
    <svg
      width={width}
      height={height}
      style={{ display: 'block' }}
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <polyline
        points={points}
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      {hoverIndex != null && coords[hoverIndex] && (
        <line
          x1={coords[hoverIndex].x}
          x2={coords[hoverIndex].x}
          y1={0}
          y2={height}
          stroke={theme.textMuted}
          strokeWidth="1"
          strokeDasharray="2,2"
        />
      )}
    </svg>
  )
}

/**
 * Info affordance for a metric tile — a small button that toggles a popover
 * stating exactly how the tile's number is computed. `numerator`/
 * `denominator`/`window_runs`/`data_source` come from `info`, the backend's
 * `metric_metadata` (see `factory_health.metric_metadata`) verbatim, never
 * hand-written here, so they cannot drift from the calculation (#11118
 * falsifiability convention). `deltaBaseline` is deliberately NOT part of
 * that backend payload: the delta it describes (`latest - first`) is
 * computed in `MetricCard` below, over `MetricCard`'s own `values` array —
 * so its description is generated right there, from that same array,
 * instead of being duplicated as backend prose that could go stale the
 * moment the delta formula changes without the description changing too.
 */
function MetricInfo({ info, deltaBaseline }) {
  const [open, setOpen] = useState(false)
  if (!info) return null
  return (
    <div style={styles.infoWrap}>
      <button
        type="button"
        aria-label={`How ${info.label} is calculated`}
        aria-expanded={open}
        style={styles.infoButton}
        onClick={(e) => {
          e.stopPropagation()
          setOpen((o) => !o)
        }}
      >
        i
      </button>
      {open && (
        <div role="tooltip" style={styles.infoPopover}>
          <div style={styles.infoRow}>
            {info.numerator} ÷ {info.denominator}
          </div>
          <div style={styles.infoRow}>Window: last {info.window_runs} runs</div>
          {deltaBaseline && <div style={styles.infoRow}>Δ compares to: {deltaBaseline}</div>}
          <div style={styles.infoRow}>Source: {info.data_source}</div>
        </div>
      )}
    </div>
  )
}

function MetricCard({ label, points, color, lowerIsBetter, info }) {
  if (!points || points.length === 0) {
    return (
      <div style={styles.card}>
        <div style={styles.cardHeader}>
          <div style={styles.cardLabel}>{label}</div>
          <MetricInfo info={info} />
        </div>
        <div style={styles.noData}>No data</div>
      </div>
    )
  }
  const values = points.map((p) => p.value)
  const latest = values[values.length - 1]
  const first = values[0]
  const delta = latest - first
  const improving = lowerIsBetter ? delta < 0 : delta > 0
  const trendColor = delta === 0 ? theme.textMuted : improving ? theme.green : theme.red
  // Describes the SAME `values` array `delta` is computed from two lines up
  // — not a second, independently-maintained claim about it.
  const deltaBaseline =
    values.length > 1 ? `earliest of the ${values.length} rolling-average points currently loaded` : null

  return (
    <div style={styles.card}>
      <div style={styles.cardHeader}>
        <div style={styles.cardLabel}>{label}</div>
        <MetricInfo info={info} deltaBaseline={deltaBaseline} />
      </div>
      <div style={styles.cardValue}>{formatValue(label, latest)}</div>
      <Sparkline values={values} color={color} />
      {values.length > 1 && (
        <div style={{ ...styles.delta, color: trendColor }}>
          {delta > 0 ? '+' : ''}
          {formatValue(label, delta)}
        </div>
      )}
    </div>
  )
}

/**
 * Companion graph row — one aligned sparkline per tile, truncated to the
 * shortest series among tiles that actually have a trend to show, so the
 * same index means "the same window offset" across metrics. A tile with
 * fewer than 2 points (e.g. a metric just wired up, with only one
 * retrospective entry recording it) sits out of the alignment computation
 * and renders "No data" instead of dragging every other tile — a full tile
 * with 16 points of history must not go blank because one other tile has 1.
 * Shares one hover cursor across every rendered sparkline. Reuses
 * `Sparkline`; no new charting dep.
 */
function CompanionGraphs({ metricConfigs, ra }) {
  const [hoverIndex, setHoverIndex] = useState(null)
  const seriesByKey = metricConfigs.map(({ key }) => (ra[key] || []).map((p) => p.value))
  const qualifyingLengths = seriesByKey.map((s) => s.length).filter((n) => n >= 2)
  if (qualifyingLengths.length === 0) return null
  const minLen = Math.min(...qualifyingLengths)
  const aligned = seriesByKey.map((s) => (s.length >= 2 ? s.slice(s.length - minLen) : null))

  return (
    <div style={styles.companionSection}>
      <h4 style={styles.sectionSubtitle}>Aligned Trend (last {minLen} windows)</h4>
      <div style={styles.companionGrid}>
        {metricConfigs.map(({ key, label, color }, i) => (
          <div key={key} style={styles.companionCell}>
            <div style={styles.companionLabel}>{label}</div>
            {aligned[i] ? (
              <>
                <Sparkline
                  values={aligned[i]}
                  color={color}
                  width={140}
                  height={36}
                  hoverIndex={hoverIndex}
                  onHover={setHoverIndex}
                />
                <div style={styles.companionHoverValue}>
                  {hoverIndex != null && aligned[i][hoverIndex] != null
                    ? formatValue(label, aligned[i][hoverIndex])
                    : ' '}
                </div>
              </>
            ) : (
              <div style={styles.noData}>No data</div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

function formatValue(label, value) {
  // 'Rate' metrics are stored as 0–1 fractions; multiply by 100 to display.
  if (label.includes('Rate')) {
    return `${(value * 100).toFixed(1)}%`
  }
  // '%' labels (e.g. 'Plan Accuracy %') are already on a 0–100 scale.
  if (label.includes('%')) {
    return `${value.toFixed(1)}%`
  }
  if (label.includes('Duration')) {
    return `${value.toFixed(0)}s`
  }
  return value.toFixed(1)
}

function CohortComparison({ cohorts }) {
  if (!cohorts) return null
  const { memory_available: avail, memory_unavailable: unavail } = cohorts
  if (avail.count === 0 && unavail.count === 0) return null

  const metrics = [
    { key: 'plan_accuracy_pct', label: 'Plan Accuracy' },
    { key: 'quality_fix_rounds', label: 'Fix Rounds' },
    { key: 'first_pass_rate', label: 'First-Pass Rate' },
  ]

  return (
    <div style={styles.cohortSection}>
      <h4 style={styles.sectionSubtitle}>Memory Impact Attribution</h4>
      <div style={styles.cohortGrid}>
        <div style={styles.cohortHeader} />
        <div style={styles.cohortHeader}>With Memory ({avail.count})</div>
        <div style={styles.cohortHeader}>Without Memory ({unavail.count})</div>
        {metrics.map(({ key, label }) => (
          <React.Fragment key={key}>
            <div style={styles.cohortLabel}>{label}</div>
            <div style={styles.cohortValue}>
              {avail[key] != null ? formatCohortValue(key, avail[key]) : '-'}
            </div>
            <div style={styles.cohortValue}>
              {unavail[key] != null ? formatCohortValue(key, unavail[key]) : '-'}
            </div>
          </React.Fragment>
        ))}
      </div>
    </div>
  )
}

function formatCohortValue(key, value) {
  if (key === 'plan_accuracy_pct') return `${value.toFixed(1)}%`
  if (key === 'first_pass_rate') return `${(value * 100).toFixed(1)}%`
  return value.toFixed(1)
}

function RegressionAlerts({ regressions }) {
  if (!regressions || regressions.length === 0) return null
  return (
    <div style={styles.regressionSection}>
      <h4 style={styles.sectionSubtitle}>Regression Alerts</h4>
      {regressions.map((r, i) => (
        <div key={i} style={styles.regressionItem}>
          <span style={styles.regressionMetric}>{r.metric}</span>
          <span style={styles.regressionDetail}>
            baseline {r.baseline_mean} → recent {r.recent_mean} ({r.deviation_sigma}σ)
          </span>
        </div>
      ))}
    </div>
  )
}

export function FactoryHealthSection() {
  const { fetchWithRepo, selectedRepoSlug } = useHydraFlow()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    fetchWithRepo('/api/factory-health/summary')
      .then((r) => r.json())
      .then((d) => {
        if (!cancelled) setData(d)
      })
      .catch((err) => console.error('factory health fetch failed', err))
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [selectedRepoSlug, fetchWithRepo])

  if (loading && !data) {
    return <div style={styles.loading}>Loading factory health…</div>
  }

  if (!data || !data.rolling_averages) return null

  const { rolling_averages: ra, cohorts, regressions, metric_metadata: metricMeta } = data

  const metricConfigs = [
    { key: 'plan_accuracy_pct', label: 'Plan Accuracy %', color: theme.accent, lowerIsBetter: false },
    { key: 'first_pass_rate', label: 'First-Pass Rate', color: theme.green, lowerIsBetter: false },
    { key: 'quality_fix_rounds', label: 'Fix Rounds', color: theme.orange, lowerIsBetter: true },
    { key: 'ci_fix_rounds', label: 'CI Fix Rounds', color: theme.yellow, lowerIsBetter: true },
    { key: 'duration_seconds', label: 'Duration (s)', color: theme.purple, lowerIsBetter: true },
  ]

  return (
    <div style={styles.section}>
      <h3 style={styles.sectionTitle}>Factory Health Trends</h3>

      <div style={styles.metricsGrid}>
        {metricConfigs.map(({ key, label, color, lowerIsBetter }) => (
          <MetricCard
            key={key}
            label={label}
            points={ra[key] || []}
            color={color}
            lowerIsBetter={lowerIsBetter}
            info={metricMeta && metricMeta[key]}
          />
        ))}
      </div>

      <CompanionGraphs metricConfigs={metricConfigs} ra={ra} />

      <CohortComparison cohorts={cohorts} />
      <RegressionAlerts regressions={regressions} />
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
  sectionSubtitle: {
    color: theme.textBright,
    fontSize: 13,
    fontWeight: 600,
    margin: '0 0 8px 0',
  },
  metricsGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))',
    gap: 12,
    marginBottom: 16,
  },
  card: {
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
    position: 'relative',
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 4,
  },
  cardLabel: {
    color: theme.textMuted,
    fontSize: 11,
  },
  infoWrap: {
    position: 'relative',
  },
  infoButton: {
    width: 14,
    height: 14,
    lineHeight: '13px',
    borderRadius: '50%',
    border: `1px solid ${theme.textMuted}`,
    background: 'transparent',
    color: theme.textMuted,
    fontSize: 9,
    fontStyle: 'italic',
    fontWeight: 700,
    padding: 0,
    cursor: 'pointer',
  },
  infoPopover: {
    position: 'absolute',
    top: 18,
    right: 0,
    zIndex: 10,
    width: 220,
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    boxShadow: theme.shadowMd,
    padding: 10,
  },
  infoRow: {
    color: theme.text,
    fontSize: 11,
    marginBottom: 4,
  },
  cardValue: {
    color: theme.textBright,
    fontSize: 18,
    fontWeight: 700,
    marginBottom: 4,
  },
  delta: {
    fontSize: 11,
    marginTop: 4,
  },
  noData: {
    color: theme.textInactive,
    fontSize: 12,
  },
  loading: {
    color: theme.textMuted,
    fontSize: 12,
    padding: 16,
  },
  cohortSection: {
    marginTop: 16,
  },
  cohortGrid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr 1fr',
    gap: 8,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  cohortHeader: {
    color: theme.textMuted,
    fontSize: 11,
    fontWeight: 600,
  },
  cohortLabel: {
    color: theme.text,
    fontSize: 12,
  },
  cohortValue: {
    color: theme.textBright,
    fontSize: 12,
    fontWeight: 600,
  },
  regressionSection: {
    marginTop: 16,
  },
  regressionItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 12px',
    background: theme.redSubtle,
    border: `1px solid ${theme.red}`,
    borderRadius: 6,
    marginBottom: 4,
  },
  regressionMetric: {
    color: theme.red,
    fontSize: 12,
    fontWeight: 600,
  },
  regressionDetail: {
    color: theme.text,
    fontSize: 11,
  },
  companionSection: {
    marginTop: 4,
    marginBottom: 16,
  },
  companionGrid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))',
    gap: 12,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 12,
  },
  companionCell: {
    display: 'flex',
    flexDirection: 'column',
  },
  companionLabel: {
    color: theme.textMuted,
    fontSize: 10,
    marginBottom: 2,
  },
  companionHoverValue: {
    color: theme.textBright,
    fontSize: 10,
    marginTop: 2,
    minHeight: 12,
  },
}
