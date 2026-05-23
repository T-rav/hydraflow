import React from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
function TrendIndicator({ current, previous, label, format }) {
  if (previous == null || current == null) return null
  const diff = current - previous
  if (Math.abs(diff) < 0.001) return null

  const isUp = diff > 0
  const arrow = isUp ? '\u2191' : '\u2193'
  const color = isUp ? theme.green : theme.red
  const formatted = format ? format(Math.abs(diff)) : Math.abs(diff)

  return (
    <span style={{ ...styles.trend, color }} title={`Change from previous snapshot`}>
      {arrow} {formatted}
    </span>
  )
}

function StatCard({ label, value, subtle, trend }) {
  return (
    <div style={subtle ? styles.cardSubtle : styles.card}>
      <div style={styles.valueRow}>
        <div style={styles.value}>{value}</div>
        {trend}
      </div>
      <div style={styles.label}>{label}</div>
    </div>
  )
}

function RateCard({ label, value, previousValue }) {
  const pct = (value * 100).toFixed(1)
  return (
    <div style={styles.rateCard}>
      <div style={styles.rateValue}>{pct}%</div>
      <div style={styles.rateLabel}>{label}</div>
      <TrendIndicator
        current={value}
        previous={previousValue}
        format={v => `${(v * 100).toFixed(1)}%`}
      />
    </div>
  )
}

function ThresholdStatus({ thresholds }) {
  if (!thresholds || thresholds.length === 0) return null
  return (
    <div style={styles.thresholdSection}>
      {thresholds.map((t, i) => (
        <div key={i} style={styles.thresholdItem}>
          <span style={styles.thresholdDot} />
          <span style={styles.thresholdText}>
            {t.metric}: {(t.value * 100).toFixed(1)}% (threshold: {(t.threshold * 100).toFixed(1)}%)
          </span>
        </div>
      ))}
    </div>
  )
}

function TimeToMerge({ data, dataTestId }) {
  if (!data || Object.keys(data).length === 0) return null
  const fmt = (s) => {
    if (s < 60) return `${Math.round(s)}s`
    if (s < 3600) return `${Math.round(s / 60)}m`
    return `${(s / 3600).toFixed(1)}h`
  }
  return (
    <div className="metrics-grid" data-testid={dataTestId}>
      <StatCard label="Avg Time to Merge" value={fmt(data.avg)} subtle />
      <StatCard label="Median (p50)" value={fmt(data.p50)} subtle />
      <StatCard label="p90" value={fmt(data.p90)} subtle />
    </div>
  )
}

function formatTokens(n) {
  const value = Number.isFinite(n) ? n : 0
  return value.toLocaleString()
}

function formatRate(value) {
  return `${(Number(value || 0) * 100).toFixed(1)}%`
}

function formatStageName(stage) {
  return String(stage || '')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, char => char.toUpperCase())
}

function RepoMetrics({ data }) {
  if (!data || Object.keys(data).length === 0) return null
  const throughput = data.throughput || {}
  const friction = data.friction || {}
  const retriesByStage = data.retries_by_stage || {}
  const throughputEntries = Object.entries(throughput)
    .filter(([, value]) => Number(value || 0) > 0)
    .sort(([a], [b]) => a.localeCompare(b))
  const retryEntries = Object.entries(retriesByStage)
    .filter(([, value]) => Number(value || 0) > 0)
    .sort(([a], [b]) => a.localeCompare(b))

  return (
    <div data-testid="metrics-grid-repo">
      <div style={styles.repoHeader}>
        <span style={styles.repoName}>{data.repo || data.repo_slug}</span>
        <span style={styles.repoSlug}>{data.repo_slug}</span>
      </div>
      {throughputEntries.length > 0 && (
        <>
          <div style={styles.subheading}>Throughput</div>
          <div className="metrics-grid">
            {throughputEntries.map(([stage, value]) => (
              <StatCard
                key={stage}
                label={`${formatStageName(stage)} / hr`}
                value={Number(value || 0).toFixed(2)}
                subtle
              />
            ))}
          </div>
        </>
      )}
      <div style={styles.subheading}>Friction</div>
      <div className="metrics-grid">
        <StatCard label="Quality Fix Rounds" value={Number(friction.quality_fix_rounds || 0)} subtle />
        <StatCard label="CI Fix Rounds" value={Number(friction.ci_fix_rounds || 0)} subtle />
        <StatCard label="HITL Escalations" value={Number(friction.hitl_escalations || 0)} subtle />
        <StatCard label="Stage Retries" value={Number(friction.stage_retries || 0)} subtle />
        <StatCard label="Quality Fix Rate" value={formatRate(friction.quality_fix_rate)} subtle />
        <StatCard label="HITL Escalation Rate" value={formatRate(friction.hitl_escalation_rate)} subtle />
      </div>
      {retryEntries.length > 0 && (
        <div style={styles.retryList}>
          {retryEntries.map(([stage, value]) => (
            <span key={stage} style={styles.retryBadge}>
              {formatStageName(stage)}: {value}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function SectionCard({ title, children, fullWidth = false }) {
  const className = fullWidth ? 'metrics-section-card metrics-section-card--full' : 'metrics-section-card'
  return (
    <section className={className}>
      <h3 style={styles.heading}>{title}</h3>
      {children}
    </section>
  )
}

export function MetricsPanel() {
  const {
    metrics, lifetimeStats, githubMetrics, metricsHistory, stageStatus,
  } = useHydraFlow()
  const sessionTriaged = stageStatus?.triage?.sessionCount || 0
  const sessionPlanned = stageStatus?.plan?.sessionCount || 0
  const sessionImplemented = stageStatus?.implement?.sessionCount || 0
  const sessionReviewed = stageStatus?.review?.sessionCount || 0
  const mergedCount = stageStatus?.merged?.sessionCount || 0
  const github = githubMetrics || {}
  const openByLabel = github.open_by_label || {}
  const lifetime = metrics?.lifetime || lifetimeStats || {}
  const lifetimeIssuesCompleted = Number(lifetime.issues_completed ?? 0)
  const lifetimePrsMerged = Number(lifetime.prs_merged ?? 0)
  const githubTotalClosed = Number(github.total_closed ?? 0)
  const githubTotalMerged = Number(github.total_merged ?? 0)
  const githubOpenIssueTotal = Object.values(openByLabel).reduce((a, b) => a + Number(b || 0), 0)

  const timeToMerge = metrics?.time_to_merge || {}
  const repoMetrics = metrics?.repo_metrics || {}
  const thresholds = metrics?.thresholds || []
  const inferenceLifetime = metrics?.inference_lifetime || {}
  const inferenceSession = metrics?.inference_session || {}

  const outcomeEntries = [
    { key: 'merged', label: 'Merged', value: Number(lifetime.total_outcomes_merged ?? 0), color: theme.green },
    { key: 'already_satisfied', label: 'Already Satisfied', value: Number(lifetime.total_outcomes_already_satisfied ?? 0), color: theme.accent },
    { key: 'hitl_closed', label: 'HITL Closed', value: Number(lifetime.total_outcomes_hitl_closed ?? 0), color: theme.orange },
    { key: 'hitl_skipped', label: 'HITL Skipped', value: Number(lifetime.total_outcomes_hitl_skipped ?? 0), color: theme.yellow },
    { key: 'failed', label: 'Failed', value: Number(lifetime.total_outcomes_failed ?? 0), color: theme.red },
    { key: 'manual_close', label: 'Manual Close', value: Number(lifetime.total_outcomes_manual_close ?? 0), color: theme.textMuted },
  ]
  const totalOutcomes = outcomeEntries.reduce((s, e) => s + e.value, 0)
  const maxOutcome = Math.max(...outcomeEntries.map(e => e.value), 1)

  const hasGithub = githubMetrics !== null && githubMetrics !== undefined
  const githubLooksUnavailable = hasGithub
    && githubOpenIssueTotal === 0
    && githubTotalClosed === 0
    && githubTotalMerged === 0
    && (lifetimeIssuesCompleted > 0 || lifetimePrsMerged > 0)
  const useGithubTotals = hasGithub && !githubLooksUnavailable
  const hasSession = sessionTriaged > 0 || sessionPlanned > 0 ||
    sessionImplemented > 0 || sessionReviewed > 0 || mergedCount > 0
  const hasLifetime = useGithubTotals || lifetimeIssuesCompleted > 0 ||
    lifetimePrsMerged > 0
  const hasRepoMetrics = Object.keys(repoMetrics).length > 0 && (
    Object.values(repoMetrics.throughput || {}).some(value => Number(value || 0) > 0) ||
    Object.values(repoMetrics.friction || {}).some(value => Number(value || 0) > 0) ||
    Object.keys(repoMetrics.time_to_merge || {}).length > 0
  )

  // Extract history data
  const historyData = metricsHistory || {}
  const snapshots = historyData.snapshots || []
  const current = historyData.current
  const prev = snapshots.length > 0 ? snapshots[snapshots.length - 1] : null

  if (!hasGithub && !hasSession && !hasLifetime && !current && !hasRepoMetrics) {
    return (
      <div style={styles.container} data-testid="metrics-panel-root">
        <div style={styles.empty}>No metrics data available yet.</div>
      </div>
    )
  }

  const sections = [
    {
      key: 'lifetime',
      title: 'Lifetime',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-lifetime">
          <StatCard
            label="Issues Completed"
            value={useGithubTotals ? githubTotalClosed : lifetimeIssuesCompleted}
            trend={<TrendIndicator
              current={current?.issues_completed}
              previous={prev?.issues_completed}
            />}
          />
          <StatCard
            label="PRs Merged"
            value={useGithubTotals ? githubTotalMerged : lifetimePrsMerged}
            trend={<TrendIndicator
              current={current?.prs_merged}
              previous={prev?.prs_merged}
            />}
          />
          {useGithubTotals && (
            <StatCard
              label="Open Issues"
              value={githubOpenIssueTotal}
            />
          )}
        </div>
      ),
      shouldRender: true,
    },
    {
      key: 'rates',
      title: 'Rates',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-rates">
          <RateCard
            label="Merge Rate"
            value={current?.merge_rate ?? 0}
            previousValue={prev?.merge_rate}
          />
          <RateCard
            label="First-Pass Approval"
            value={current?.first_pass_approval_rate ?? 0}
            previousValue={prev?.first_pass_approval_rate}
          />
          <RateCard
            label="Quality Fix Rate"
            value={current?.quality_fix_rate ?? 0}
            previousValue={prev?.quality_fix_rate}
          />
          <RateCard
            label="HITL Escalation"
            value={current?.hitl_escalation_rate ?? 0}
            previousValue={prev?.hitl_escalation_rate}
          />
        </div>
      ),
      shouldRender: Boolean(current || prev),
    },
    {
      key: 'outcomes',
      title: 'Outcomes',
      content: (
        <div data-testid="metrics-grid-outcomes">
          <div style={styles.outcomeSummary}>
            <span style={styles.outcomeBadge}>{totalOutcomes}</span>
            <span style={styles.outcomeLabel}>total outcomes</span>
          </div>
          {outcomeEntries
            .filter(e => e.value > 0)
            .map(e => (
              <div key={e.key} style={styles.outcomeBarRow}>
                <div style={styles.outcomeBarLabel}>{e.label}</div>
                <div style={styles.outcomeBarTrack}>
                  <div style={{ ...styles.outcomeBarFill, width: `${(e.value / maxOutcome) * 100}%`, background: e.color }} />
                </div>
                <div style={styles.outcomeBarCount}>{e.value}</div>
              </div>
            ))}
        </div>
      ),
      shouldRender: totalOutcomes > 0,
    },
    {
      key: 'thresholds',
      title: 'Threshold Alerts',
      content: <ThresholdStatus thresholds={thresholds} />,
      shouldRender: thresholds.length > 0,
    },
    {
      key: 'time-to-merge',
      title: 'Time to Merge',
      content: <TimeToMerge data={timeToMerge} dataTestId="metrics-grid-time-to-merge" />,
      shouldRender: Object.keys(timeToMerge).length > 0,
    },
    {
      key: 'repo',
      title: 'Repo Metrics',
      content: <RepoMetrics data={repoMetrics} />,
      shouldRender: hasRepoMetrics,
    },
    {
      key: 'session',
      title: 'Session',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-session">
          <StatCard label="Triaged" value={sessionTriaged || 0} subtle />
          <StatCard label="Planned" value={sessionPlanned || 0} subtle />
          <StatCard label="Implemented" value={sessionImplemented || 0} subtle />
          <StatCard label="Reviewed" value={sessionReviewed || 0} subtle />
          <StatCard label="Merged" value={mergedCount || 0} subtle />
        </div>
      ),
      shouldRender: hasSession,
    },
    {
      key: 'inference',
      title: 'Inference',
      content: (
        <div className="metrics-grid" data-testid="metrics-grid-inference">
          <StatCard
            label="Session Tokens"
            value={formatTokens(inferenceSession.total_tokens || 0)}
            subtle
          />
          <StatCard
            label="Session Calls"
            value={formatTokens(inferenceSession.inference_calls || 0)}
            subtle
          />
          <StatCard
            label="Lifetime Tokens"
            value={formatTokens(inferenceLifetime.total_tokens || 0)}
            subtle
          />
          <StatCard
            label="Lifetime Calls"
            value={formatTokens(inferenceLifetime.inference_calls || 0)}
            subtle
          />
          <StatCard
            label="Session Pruned Chars"
            value={formatTokens(inferenceSession.pruned_chars_total || 0)}
            subtle
          />
          <StatCard
            label="Lifetime Pruned Chars"
            value={formatTokens(inferenceLifetime.pruned_chars_total || 0)}
            subtle
          />
        </div>
      ),
      shouldRender: true,
    },
  ]

  const sectionCards = sections
    .filter(section => section.shouldRender)
    .map(section => (
      <SectionCard key={section.key} title={section.title}>
        {section.content}
      </SectionCard>
    ))

  return (
    <div style={styles.container} data-testid="metrics-panel-root">
      <div className="metrics-sections" data-testid="metrics-sections">
        {sectionCards}
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
  heading: {
    fontSize: 16,
    fontWeight: 600,
    color: theme.textBright,
    marginBottom: 16,
    marginTop: 0,
  },
  card: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 20,
    background: theme.surface,
    textAlign: 'center',
  },
  cardSubtle: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surfaceInset,
    textAlign: 'center',
  },
  valueRow: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 6,
  },
  value: {
    fontSize: 32,
    fontWeight: 700,
    color: theme.textBright,
    marginBottom: 4,
  },
  label: {
    fontSize: 12,
    color: theme.textMuted,
    textTransform: 'capitalize',
  },
  trend: {
    fontSize: 12,
    fontWeight: 600,
  },
  empty: {
    fontSize: 13,
    color: theme.textMuted,
    padding: 20,
  },
  rateCard: {
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: 16,
    background: theme.surface,
    textAlign: 'center',
  },
  rateValue: {
    fontSize: 24,
    fontWeight: 700,
    color: theme.textBright,
    marginBottom: 4,
  },
  rateLabel: {
    fontSize: 11,
    color: theme.textMuted,
    marginBottom: 4,
  },
  thresholdSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    marginBottom: 24,
    padding: 16,
    background: theme.surfaceInset,
    borderRadius: 8,
    border: `1px solid ${theme.red}`,
  },
  thresholdItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  thresholdDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: theme.red,
    flexShrink: 0,
  },
  thresholdText: {
    fontSize: 12,
    color: theme.textBright,
  },
  repoHeader: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 10,
    marginBottom: 12,
    flexWrap: 'wrap',
  },
  repoName: {
    fontSize: 14,
    fontWeight: 700,
    color: theme.textBright,
  },
  repoSlug: {
    fontSize: 12,
    color: theme.textMuted,
  },
  subheading: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.text,
    marginTop: 12,
    marginBottom: 8,
    textTransform: 'uppercase',
  },
  retryList: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    marginTop: 12,
  },
  retryBadge: {
    fontSize: 12,
    color: theme.text,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '4px 8px',
  },
  outcomeSummary: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 12,
  },
  outcomeBadge: {
    fontSize: 18,
    fontWeight: 700,
    color: theme.textBright,
    background: theme.surfaceInset,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '4px 12px',
  },
  outcomeLabel: {
    fontSize: 13,
    color: theme.textMuted,
  },
  outcomeBarRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginBottom: 4,
  },
  outcomeBarLabel: {
    fontSize: 12,
    color: theme.text,
    width: 140,
    flexShrink: 0,
  },
  outcomeBarTrack: {
    flex: 1,
    height: 8,
    background: theme.surfaceInset,
    borderRadius: 4,
    overflow: 'hidden',
  },
  outcomeBarFill: {
    height: '100%',
    borderRadius: 4,
    transition: 'width 0.3s',
  },
  outcomeBarCount: {
    fontSize: 12,
    fontWeight: 600,
    color: theme.textBright,
    width: 32,
    textAlign: 'right',
    flexShrink: 0,
  },
}
