import React, { useEffect, useRef, useState } from 'react'
import { theme } from '../theme'
import { PIPELINE_STAGES } from '../constants'
import { useHITLCorrection } from '../hooks/useHITLCorrection'

// Composite row identity — colliding issue numbers across repos must not share
// per-row state (corrections/summaries/expand) in aggregate mode. Falls back to
// the bare issue number when no repo is present (single-repo payloads).
const rowKey = (item) =>
  item.repo ? `${item.repo}#${item.issue}` : String(item.issue)

export function HITLTable({ items, onRefresh }) {
  // Only one row is expanded at a time (expandedIssue is a single composite
  // key, not a set). Per-row data-testids stay keyed by the bare issue number,
  // so in aggregate mode colliding issue numbers share a testid — selecting the
  // detail/action testids is unambiguous precisely because at most one of them
  // is expanded (and thus rendered) at once.
  const [expandedIssue, setExpandedIssue] = useState(null)
  const [summaryExpandedIssue, setSummaryExpandedIssue] = useState(null)
  const [summaries, setSummaries] = useState(() =>
    Object.fromEntries(
      (items || []).map(item => [
        rowKey(item),
        {
          text: item.llmSummary || '',
          updatedAt: item.llmSummaryUpdatedAt || null,
          loading: false,
          error: '',
        },
      ])
    )
  )
  const [corrections, setCorrections] = useState({})
  const [actionLoading, setActionLoading] = useState(null)
  const [actionError, setActionError] = useState({})
  const [closedIssues, setClosedIssues] = useState(() => new Set())
  const [refreshing, setRefreshing] = useState(false)
  const [countdown, setCountdown] = useState(30)
  const onRefreshRef = useRef(onRefresh)
  const { submitCorrection, skipIssue, closeIssue, approveProcess } = useHITLCorrection()

  useEffect(() => { onRefreshRef.current = onRefresh }, [onRefresh])

  useEffect(() => {
    const timer = setInterval(() => {
      setCountdown(prev => {
        if (prev <= 1) {
          onRefreshRef.current()
          return 30
        }
        return prev - 1
      })
    }, 1000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setRefreshing(false)
    setCountdown(30)
  }, [items])

  useEffect(() => {
    setSummaries(prev => {
      const next = { ...prev }
      for (const item of items || []) {
        const key = rowKey(item)
        if (item.llmSummary) {
          next[key] = {
            text: item.llmSummary,
            updatedAt: item.llmSummaryUpdatedAt || null,
            loading: false,
            error: '',
          }
        } else if (!next[key]) {
          next[key] = {
            text: '',
            updatedAt: null,
            loading: false,
            error: '',
          }
        }
      }
      return next
    })
  }, [items])

  const visibleItems = items.filter(item => !closedIssues.has(rowKey(item)))

  const toggleExpand = (key) => {
    setExpandedIssue(prev => prev === key ? null : key)
  }

  const toggleSummaryExpand = (key) => {
    setSummaryExpandedIssue(prev => prev === key ? null : key)
  }

  const ensureSummary = async (item) => {
    const key = rowKey(item)
    const existing = summaries[key]
    if (existing?.text || existing?.loading) return
    setSummaries(prev => ({
      ...prev,
      [key]: { ...(prev[key] || {}), loading: true, error: '' },
    }))
    try {
      const url = item.repo
        ? `/api/hitl/${item.issue}/summary?repo=${encodeURIComponent(item.repo)}`
        : `/api/hitl/${item.issue}/summary`
      const resp = await fetch(url)
      if (!resp.ok) throw new Error(`status ${resp.status}`)
      const payload = await resp.json()
      setSummaries(prev => ({
        ...prev,
        [key]: {
          text: payload.summary || '',
          updatedAt: payload.updated_at || null,
          loading: false,
          error: '',
        },
      }))
    } catch {
      setSummaries(prev => ({
        ...prev,
        [key]: {
          ...(prev[key] || {}),
          loading: false,
          error: 'Could not generate context summary yet.',
        },
      }))
    }
  }

  const toggleExpandAndLoadSummary = (item) => {
    toggleExpand(rowKey(item))
    setSummaryExpandedIssue(null)
    void ensureSummary(item)
  }

  const handleCorrectionChange = (key, value) => {
    setCorrections(prev => ({ ...prev, [key]: value }))
  }

  const handleRetry = async (item) => {
    const key = rowKey(item)
    const text = (corrections[key] || '').trim()
    if (!text) return
    setActionLoading({ key, action: 'retry' })
    await submitCorrection(item.issue, text, item.repo)
    setCorrections(prev => ({ ...prev, [key]: '' }))
    setActionLoading(null)
    onRefresh()
  }

  const handleSkip = async (item) => {
    const key = rowKey(item)
    setActionLoading({ key, action: 'skip' })
    setActionError(prev => ({ ...prev, [key]: null }))
    const reason = corrections[key] || ''
    const ok = await skipIssue(item.issue, reason, item.repo)
    if (!ok) {
      setActionError(prev => ({ ...prev, [key]: 'Skip failed. Try again.' }))
    }
    setActionLoading(null)
    if (ok) setExpandedIssue(null)
    onRefresh()
  }

  const handleClose = async (item) => {
    const key = rowKey(item)
    setActionLoading({ key, action: 'close' })
    setActionError(prev => ({ ...prev, [key]: null }))
    const reason = corrections[key] || ''
    const ok = await closeIssue(item.issue, reason, item.repo)
    if (ok) {
      setClosedIssues(prev => {
        const next = new Set(prev)
        next.add(key)
        return next
      })
      setExpandedIssue(null)
    } else {
      setActionError(prev => ({ ...prev, [key]: 'Close failed. Try again.' }))
    }
    setActionLoading(null)
    onRefresh()
  }

  const handleApproveProcess = async (item) => {
    const key = rowKey(item)
    setActionLoading({ key, action: 'approve-process' })
    await approveProcess(item.issue, item.repo)
    setActionLoading(null)
    setExpandedIssue(null)
    onRefresh()
  }

  const isActionLoading = (key, action) =>
    actionLoading && actionLoading.key === key && actionLoading.action === action

  const isAnyActionLoading = (key) =>
    actionLoading && actionLoading.key === key

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={visibleItems.length === 0
          ? { ...styles.headerText, color: theme.textMuted }
          : styles.headerText}>
          {visibleItems.length === 0
            ? 'HITL'
            : `${visibleItems.length} item${visibleItems.length !== 1 ? 's' : ''} awaiting action`}
        </span>
        <div style={styles.refreshGroup}>
          <button
            onClick={() => { setRefreshing(true); setCountdown(30); onRefresh() }}
            style={styles.refresh}
            disabled={refreshing}
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
          <span style={styles.countdownHint}>
            {refreshing ? '' : `auto in ${countdown}s`}
          </span>
        </div>
      </div>
      {visibleItems.length === 0 ? (
        <div style={styles.empty}>No stuck issues</div>
      ) : (
      <table style={styles.table}>
        <thead>
          <tr>
            <th style={styles.th}>Issue</th>
            <th style={styles.th}>Title</th>
            <th style={styles.th}>Cause</th>
            <th style={styles.th}>PR</th>
            <th style={styles.th}>Branch</th>
            <th style={styles.th}>Status</th>
          </tr>
        </thead>
        <tbody>
          {visibleItems.map((item) => {
            const key = rowKey(item)
            const isExpanded = expandedIssue === key
            const status = item.status || 'pending'
            return (
              <React.Fragment key={key}>
                <tr
                  onClick={() => toggleExpandAndLoadSummary(item)}
                  style={isExpanded ? styles.rowActive : styles.row}
                  data-testid={`hitl-row-${item.issue}`}
                >
                  <td style={styles.td}>
                    {item.repo && (
                      <span style={styles.repoBadge} data-testid={`hitl-repo-${item.issue}`}>
                        {item.repo}
                      </span>
                    )}
                    <a href={item.issueUrl || item.prUrl || '#'} target="_blank" rel="noreferrer" style={styles.link}
                       onClick={e => e.stopPropagation()}>
                      {item.type === 'pr' ? `PR #${item.pr || item.number}` : `#${item.issue}`}
                    </a>
                  </td>
                  <td style={styles.td}>
                    <span style={typeBadgeStyle(item.type)} data-testid={`hitl-type-${item.issue}`}>
                      {item.type === 'pr' ? 'pr' : 'issue'}
                    </span>
                    <span style={{ marginLeft: 8 }}>{item.title}</span>
                  </td>
                  <td style={styles.td}>
                    {item.cause
                      ? <span style={{ ...styles.causeText, color: causeColors(item.cause).fg }}>{item.cause}</span>
                      : <span style={styles.causePlaceholder}>—</span>}
                  </td>
                  <td style={styles.td}>
                    {item.pr > 0 ? (
                      <a href={item.prUrl || '#'} target="_blank" rel="noreferrer" style={styles.link}
                         onClick={e => e.stopPropagation()}>
                        #{item.pr}
                      </a>
                    ) : (
                      <span style={styles.causePlaceholder}>—</span>
                    )}
                  </td>
                  <td style={styles.td}>{item.branch}</td>
                  <td style={styles.td}>
                    <span style={statusBadgeStyle(status)}>{status}</span>
                  </td>
                </tr>
                {isExpanded && (
                  <tr data-testid={`hitl-detail-${item.issue}`}>
                    <td colSpan={6} style={styles.detailCell}>
                      <div style={styles.detailPanel}>
                        <div style={styles.summarySection}>
                          <div style={styles.summaryHeader}>
                            <span style={styles.summaryTitle}>LLM Context Summary</span>
                            <button
                              style={styles.summaryToggle}
                              onClick={e => { e.stopPropagation(); toggleSummaryExpand(key) }}
                              disabled={!summaries[key]?.text}
                              data-testid={`hitl-summary-toggle-${item.issue}`}
                            >
                              {summaryExpandedIssue === key ? 'Show less' : 'Show more'}
                            </button>
                          </div>
                          <div
                            style={
                              summaryExpandedIssue === key
                                ? styles.summaryExpanded
                                : styles.summaryCollapsed
                            }
                            data-testid={`hitl-summary-${item.issue}`}
                          >
                            {summaries[key]?.loading
                              ? 'Generating summary...'
                              : summaries[key]?.text || summaries[key]?.error || 'Summary pending. Refresh in a few seconds.'}
                          </div>
                        </div>
                        {item.visualEvidence && item.visualEvidence.items && item.visualEvidence.items.length > 0 && (
                          <div style={styles.visualSection} data-testid={`hitl-visual-${item.issue}`}>
                            <div style={styles.visualHeader}>
                              <span style={styles.visualTitle}>Visual Evidence</span>
                              {item.visualEvidence.run_url && (
                                <a
                                  href={item.visualEvidence.run_url}
                                  target="_blank"
                                  rel="noreferrer"
                                  style={styles.link}
                                  onClick={e => e.stopPropagation()}
                                >
                                  Run #{item.visualEvidence.attempt || 1}
                                </a>
                              )}
                            </div>
                            {item.visualEvidence.summary && (
                              <div style={styles.visualSummary}>{item.visualEvidence.summary}</div>
                            )}
                            <div style={styles.visualGrid}>
                              {item.visualEvidence.items.map((ev, idx) => (
                                <div key={`${ev.screen_name}-${idx}`} style={styles.visualCard} data-testid={`hitl-visual-item-${item.issue}-${idx}`}>
                                  <div style={styles.visualCardHeader}>
                                    <span style={styles.visualScreenName}>{ev.screen_name}</span>
                                    <span style={visualStatusStyle(ev.status)}>
                                      {ev.status === 'fail' ? 'FAIL' : ev.status === 'warn' ? 'WARN' : 'PASS'}
                                    </span>
                                  </div>
                                  <div style={styles.visualDiffBar}>
                                    <div style={diffFillStyle(ev.status, ev.diff_percent)} />
                                  </div>
                                  <span style={styles.visualDiffLabel}>{ev.diff_percent.toFixed(1)}% diff</span>
                                  <div style={styles.visualLinks}>
                                    {ev.baseline_url && <a href={ev.baseline_url} target="_blank" rel="noreferrer" style={styles.link} onClick={e => e.stopPropagation()}>Baseline</a>}
                                    {ev.actual_url && <a href={ev.actual_url} target="_blank" rel="noreferrer" style={styles.link} onClick={e => e.stopPropagation()}>Actual</a>}
                                    {ev.diff_url && <a href={ev.diff_url} target="_blank" rel="noreferrer" style={styles.link} onClick={e => e.stopPropagation()}>Diff</a>}
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                        {item.cause && (
                          <div style={causeBadgeStyle(item)} data-testid={`hitl-cause-${item.issue}`}>
                            Cause: {item.cause}
                          </div>
                        )}
                        <textarea
                          style={styles.textarea}
                          placeholder="Provide correction guidance..."
                          value={corrections[key] || ''}
                          onChange={e => handleCorrectionChange(key, e.target.value)}
                          onClick={e => e.stopPropagation()}
                          data-testid={`hitl-textarea-${item.issue}`}
                        />
                        <div style={styles.actions}>
                          <button
                            style={styles.retryBtn}
                            disabled={!(corrections[key] || '').trim() || isAnyActionLoading(key)}
                            onClick={e => { e.stopPropagation(); handleRetry(item) }}
                            data-testid={`hitl-retry-${item.issue}`}
                          >
                            {isActionLoading(key, 'retry') ? 'Processing...' : 'Retry with guidance'}
                          </button>
                          <button
                            style={styles.skipBtn}
                            disabled={isAnyActionLoading(key)}
                            onClick={e => { e.stopPropagation(); handleSkip(item) }}
                            data-testid={`hitl-skip-${item.issue}`}
                          >
                            {isActionLoading(key, 'skip') ? 'Skipping...' : 'Skip'}
                          </button>
                          <button
                            style={styles.closeBtn}
                            disabled={isAnyActionLoading(key)}
                            onClick={e => { e.stopPropagation(); handleClose(item) }}
                            data-testid={`hitl-close-${item.issue}`}
                          >
                            {isActionLoading(key, 'close') ? 'Closing...' : 'Close issue'}
                          </button>
                          {item.issueTypeReview && (
                            <button
                              style={styles.approveProcessBtn}
                              disabled={isAnyActionLoading(key)}
                              onClick={e => { e.stopPropagation(); handleApproveProcess(item) }}
                              data-testid={`hitl-approve-process-${item.issue}`}
                            >
                              {isActionLoading(key, 'approve-process') ? 'Approving...' : 'Approve'}
                            </button>
                          )}
                        </div>
                        {actionError[key] && (
                          <div style={styles.actionError}>{actionError[key]}</div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
      )}
    </div>
  )
}

const originColors = Object.fromEntries(
  PIPELINE_STAGES
    .filter(s => s.key !== 'merged')
    .map(s => [`from ${s.key}`, { bg: s.subtleColor, fg: s.color }])
)

function typeBadgeStyle(type) {
  const colors = type === 'pr'
    ? { bg: theme.purpleSubtle, fg: theme.purple }
    : { bg: theme.accentSubtle, fg: theme.accent }
  return {
    fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 700,
    background: colors.bg, color: colors.fg, textTransform: 'uppercase',
    letterSpacing: 0.5,
  }
}

function statusBadgeStyle(status) {
  const colors = {
    pending: { bg: theme.yellowSubtle, fg: theme.yellow },
    processing: { bg: theme.accentSubtle, fg: theme.accent },
    resolved: { bg: theme.greenSubtle, fg: theme.green },
    approval: { bg: theme.purpleSubtle, fg: theme.purple },
    ...originColors,
  }
  const { bg, fg } = colors[status] || colors.pending
  return {
    fontSize: 11, padding: '2px 8px', borderRadius: 8, fontWeight: 600,
    background: bg, color: fg,
  }
}

function causeColors(cause) {
  if (!cause) return { bg: theme.orangeSubtle, fg: theme.orange }
  const lower = cause.toLowerCase()
  if (lower.includes('proposal') || lower.includes('improve')) {
    return { bg: theme.purpleSubtle, fg: theme.purple }
  }
  if (lower.includes('triage') || lower.includes('insufficient')) {
    return { bg: theme.yellowSubtle, fg: theme.yellow }
  }
  if (lower.includes('visual') || lower.includes('screenshot')) {
    return { bg: theme.redSubtle, fg: theme.red }
  }
  return { bg: theme.orangeSubtle, fg: theme.orange }
}

function visualStatusStyle(status) {
  const colors = {
    fail: { bg: theme.redSubtle, fg: theme.red },
    warn: { bg: theme.yellowSubtle, fg: theme.yellow },
    pass: { bg: theme.greenSubtle, fg: theme.green },
  }
  const { bg, fg } = colors[status] || colors.fail
  return {
    fontSize: 10, padding: '1px 6px', borderRadius: 4, fontWeight: 700,
    background: bg, color: fg,
  }
}

const diffFillBg = { fail: theme.red, warn: theme.yellow, pass: theme.green }

function diffFillStyle(status, diffPercent) {
  return {
    height: '100%', borderRadius: 2, transition: 'width 0.3s',
    width: `${Math.min(diffPercent, 100)}%`,
    background: diffFillBg[status] || theme.red,
  }
}

function causeBadgeStyle(item) {
  if (item.isMemorySuggestion) return styles.memoryCauseBadge
  const colors = causeColors(item.cause)
  return { ...badgeBase, background: colors.bg, color: colors.fg }
}

const badgeBase = {
  display: 'inline-block', marginBottom: 8,
  padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 600,
}

const btnBase = {
  padding: '6px 14px', border: 'none', borderRadius: 6,
  fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit', fontSize: 12,
}

const styles = {
  container: { padding: 12, overflowX: 'auto' },
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 12,
  },
  headerText: { color: theme.red, fontWeight: 600, fontSize: 13 },
  refreshGroup: {
    display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2,
  },
  refresh: {
    background: theme.surfaceInset, border: `1px solid ${theme.border}`, color: theme.text,
    padding: '4px 12px', borderRadius: 6, cursor: 'pointer', fontSize: 11,
  },
  countdownHint: {
    fontSize: 10, color: theme.textMuted, lineHeight: 1,
  },
  empty: {
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    height: 200, color: theme.textMuted, fontSize: 13,
  },
  table: { width: '100%', minWidth: 600, borderCollapse: 'collapse', fontSize: 12 },
  th: {
    textAlign: 'left', padding: 8, borderBottom: `1px solid ${theme.border}`,
    color: theme.textMuted, fontSize: 11,
  },
  td: { padding: 8, borderBottom: `1px solid ${theme.border}` },
  row: { cursor: 'pointer' },
  rowActive: { cursor: 'pointer', background: theme.surfaceInset },
  link: { color: theme.accent, textDecoration: 'none' },
  repoBadge: {
    display: 'inline-block', marginRight: 6, fontSize: 9, padding: '1px 6px',
    borderRadius: 8, background: theme.surfaceInset, color: theme.textMuted,
    verticalAlign: 'middle',
  },
  causeText: { fontSize: 11, color: theme.orange, fontWeight: 500 },
  causePlaceholder: { color: theme.textMuted, fontStyle: 'italic' },
  detailCell: { padding: 0, borderBottom: `1px solid ${theme.border}` },
  detailPanel: {
    padding: '12px 16px', background: theme.surface,
    borderTop: `1px solid ${theme.border}`,
  },
  summarySection: {
    marginBottom: 10,
    padding: '8px 10px',
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: theme.surfaceInset,
  },
  summaryHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginBottom: 6,
  },
  summaryTitle: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.textMuted,
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
  },
  summaryToggle: {
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.accent,
    borderRadius: 6,
    padding: '2px 8px',
    fontSize: 11,
    cursor: 'pointer',
  },
  summaryCollapsed: {
    whiteSpace: 'pre-wrap',
    lineHeight: '18px',
    maxHeight: '36px',
    overflow: 'hidden',
    color: theme.text,
    fontSize: 12,
  },
  summaryExpanded: {
    whiteSpace: 'pre-wrap',
    lineHeight: '18px',
    maxHeight: '90px',
    overflowY: 'auto',
    color: theme.text,
    fontSize: 12,
    paddingRight: 4,
  },
  causeBadge: { ...badgeBase, background: theme.orangeSubtle, color: theme.orange },
  textarea: {
    width: '100%', minHeight: 60, padding: 8,
    background: theme.bg, border: `1px solid ${theme.border}`,
    borderRadius: 6, color: theme.text, fontFamily: 'inherit', fontSize: 12,
    resize: 'vertical', boxSizing: 'border-box',
  },
  actions: { display: 'flex', gap: 8, marginTop: 8 },
  retryBtn: { ...btnBase, background: theme.btnGreen, color: theme.white },
  skipBtn: { ...btnBase, background: theme.surfaceInset, color: theme.text, border: `1px solid ${theme.border}` },
  closeBtn: { ...btnBase, background: theme.btnRed, color: theme.white },
  actionError: { marginTop: 6, fontSize: 12, color: theme.red || '#c0392b' },
  approveMemoryBtn: { ...btnBase, background: theme.purple, color: theme.white },
  approveProcessBtn: { ...btnBase, background: theme.btnGreen, color: theme.white },
  memoryCauseBadge: { ...badgeBase, background: theme.purpleSubtle, color: theme.purple },
  visualSection: {
    marginBottom: 10, padding: '8px 10px',
    border: `1px solid ${theme.border}`, borderRadius: 6,
    background: theme.surfaceInset,
  },
  visualHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 6,
  },
  visualTitle: {
    fontSize: 11, fontWeight: 700, color: theme.textMuted,
    letterSpacing: '0.04em', textTransform: 'uppercase',
  },
  visualSummary: {
    fontSize: 12, color: theme.text, marginBottom: 8,
    lineHeight: '18px',
  },
  visualGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
    gap: 8,
  },
  visualCard: {
    padding: 8, border: `1px solid ${theme.border}`, borderRadius: 6,
    background: theme.surface,
  },
  visualCardHeader: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    marginBottom: 4,
  },
  visualScreenName: { fontSize: 11, fontWeight: 600, color: theme.text },
  visualDiffBar: {
    height: 4, borderRadius: 2, background: theme.surfaceInset,
    marginBottom: 4, overflow: 'hidden',
  },
  visualDiffLabel: { fontSize: 10, color: theme.textMuted },
  visualLinks: { display: 'flex', gap: 8, marginTop: 4, fontSize: 11 },
}
