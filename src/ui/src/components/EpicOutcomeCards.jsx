import React, { useMemo, useState } from 'react'
import { theme } from '../theme'

/**
 * Derive an epic's factory execution state for the card badge (#10299, #10306).
 *
 * The persisted `status` only distinguishes active|completed|stale|blocked
 * (plus the client-only ready|releasing|released), so an `active` epic renders
 * the same green badge whether or not the factory is actually working on it —
 * misleading when 0 children are running or queued. This refines the default
 * `active` status into a real execution state, derived from the worker/queue
 * occupancy already carried on the epic payload:
 *   - `running` — ≥1 child currently held by a worker (`active_children`)
 *   - `queued`  — no child running, but ≥1 awaiting dispatch (`queued_children`)
 *   - `paused`  — open children remain but none are running or queued (parked)
 *   - `idle`    — nothing open, running, or queued
 * Terminal / client-only statuses (completed, blocked, stale, ready,
 * releasing, released) pass through unchanged.
 */
export function deriveEpicExecutionState(epic) {
  const status = epic?.status
  if (status && status !== 'active') return status
  if ((epic?.active_children || 0) > 0) return 'running'
  if ((epic?.queued_children || 0) > 0) return 'queued'
  if ((epic?.in_progress || 0) > 0) return 'paused'
  return 'idle'
}

function EpicChildRow({ child }) {
  const dotColor = child.is_completed ? theme.green : child.is_failed ? theme.red : theme.textMuted
  return (
    <div style={styles.childRow}>
      <span style={{ ...styles.childDot, background: dotColor }} />
      <a
        href={child.url}
        target="_blank"
        rel="noopener noreferrer"
        style={styles.childLink}
        onClick={e => e.stopPropagation()}
      >
        #{child.issue_number}
      </a>
      <span style={styles.childTitle}>{child.title || `Issue #${child.issue_number}`}</span>
      {child.is_completed && <span style={styles.childBadgeDone}>done</span>}
      {child.is_failed && <span style={styles.childBadgeFailed}>failed</span>}
    </div>
  )
}

// A single stat pill (label + value). Hidden entirely when the value is 0 and
// `hideZero` is set, so a card only surfaces the buckets that actually apply.
function StatPill({ label, value, tone = 'muted', hideZero = false }) {
  if (hideZero && !value) return null
  return (
    <span style={statPillStyles[tone]} data-testid={`epic-stat-${label}`}>
      <span style={styles.statValue}>{value}</span>
      <span style={styles.statLabel}>{label}</span>
    </span>
  )
}

export function EpicOutcomeCard({ epic }) {
  const [expanded, setExpanded] = useState(false)

  const total = epic.total_children || 0
  const completed = epic.completed || 0
  const failed = epic.failed || 0
  const pct = total > 0 ? Math.round((completed / total) * 100) : Math.round(epic.percent_complete || 0)
  const execState = deriveEpicExecutionState(epic)
  const badgeStyle = epicStatusStyles[execState] || epicStatusStyles.paused
  const children = Array.isArray(epic.children) ? epic.children : []

  const completedWidth = total > 0 ? (completed / total) * 100 : 0
  const failedWidth = total > 0 ? (failed / total) * 100 : 0

  return (
    <div style={styles.card} data-testid={`epic-outcome-card-${epic.epic_number}`}>
      <div
        style={styles.cardHeader}
        onClick={() => setExpanded(p => !p)}
        role="button"
        tabIndex={0}
        onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setExpanded(p => !p) } }}
      >
        <span style={styles.chevron}>{expanded ? '▾' : '▸'}</span>
        {epic.url ? (
          <a
            href={epic.url}
            target="_blank"
            rel="noopener noreferrer"
            style={styles.epicLink}
            onClick={e => e.stopPropagation()}
          >
            #{epic.epic_number}
          </a>
        ) : (
          <span style={styles.epicLabel}>#{epic.epic_number}</span>
        )}
        <span style={styles.epicTitle}>{epic.title || `Epic #${epic.epic_number}`}</span>
        {epic.auto_decomposed && <span style={styles.autoBadge}>auto</span>}
        <span style={badgeStyle} data-testid={`epic-badge-${epic.epic_number}`}>{execState}</span>
      </div>

      <div style={styles.barTrack}>
        {completed > 0 && (
          <div style={{ ...styles.barGreen, width: `${completedWidth}%` }} />
        )}
        {failed > 0 && (
          <div style={{ ...styles.barRed, width: `${failedWidth}%` }} />
        )}
      </div>

      <div style={styles.progressLine} data-testid={`epic-progress-${epic.epic_number}`}>
        <span style={styles.progressStrong}>{completed}/{total} done</span>
        <span style={styles.progressPct}>{pct}%</span>
      </div>

      <div style={styles.statRow}>
        <StatPill label="children" value={total} tone="muted" />
        <StatPill label="merged" value={epic.merged_children || 0} tone="green" hideZero />
        <StatPill label="failed" value={failed} tone="red" hideZero />
        <StatPill label="in progress" value={epic.in_progress || 0} tone="accent" hideZero />
        <StatPill label="queued" value={epic.queued_children || 0} tone="yellow" hideZero />
      </div>

      {expanded && (
        <div style={styles.childList}>
          {children.length > 0 ? (
            children.map(child => (
              <EpicChildRow key={child.issue_number} child={child} />
            ))
          ) : (
            <span style={styles.childEmpty}>No child issues found</span>
          )}
        </div>
      )}
    </div>
  )
}

/**
 * Grid of epic outcome cards for the Outcomes tab (#10306).
 *
 * Epics were removed from the pipeline/stream view and now render here as
 * outcome cards (progress + counts + stats), expandable to their child issues.
 * Renders nothing when there are no epics so the tab stays clean.
 */
export function EpicOutcomeCards({ epics }) {
  const ordered = useMemo(() => {
    const list = Array.isArray(epics) ? epics : []
    // Non-completed epics first so in-flight work leads; stable within a group.
    return [...list].sort((a, b) => {
      const ac = a.status === 'completed' ? 1 : 0
      const bc = b.status === 'completed' ? 1 : 0
      return ac - bc
    })
  }, [epics])

  if (ordered.length === 0) return null

  const activeCount = ordered.filter(e => e.status !== 'completed').length

  return (
    <div style={styles.section} data-testid="epic-outcome-cards">
      <div style={styles.sectionHeader}>
        <span style={styles.sectionTitle}>Epics</span>
        <span style={styles.sectionCount}>{ordered.length}</span>
        {activeCount > 0 && activeCount !== ordered.length && (
          <span style={styles.sectionActive}>{activeCount} active</span>
        )}
      </div>
      <div style={styles.grid}>
        {ordered.map(epic => (
          <EpicOutcomeCard key={epic.epic_number} epic={epic} />
        ))}
      </div>
    </div>
  )
}

const styles = {
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
    flexShrink: 0,
    maxHeight: '42%',
    overflowY: 'auto',
  },
  sectionHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  sectionTitle: {
    fontSize: 12,
    fontWeight: 700,
    color: theme.textBright,
    textTransform: 'uppercase',
    letterSpacing: '0.4px',
  },
  sectionCount: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.purple,
    background: theme.purpleSubtle,
    borderRadius: 8,
    padding: '1px 6px',
  },
  sectionActive: {
    fontSize: 10,
    color: theme.textMuted,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 8,
  },
  card: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    padding: '10px 12px',
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderLeft: `3px solid ${theme.purple}`,
    borderRadius: 8,
  },
  cardHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    cursor: 'pointer',
  },
  chevron: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
    width: 10,
  },
  epicLabel: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.purple,
    flexShrink: 0,
  },
  epicLink: {
    fontSize: 11,
    fontWeight: 700,
    color: theme.purple,
    flexShrink: 0,
    textDecoration: 'none',
    cursor: 'pointer',
  },
  epicTitle: {
    fontSize: 12,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
    minWidth: 0,
  },
  autoBadge: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.accent,
    background: theme.accentSubtle,
    borderRadius: 4,
    padding: '1px 4px',
    flexShrink: 0,
  },
  barTrack: {
    display: 'flex',
    height: 5,
    background: theme.border,
    borderRadius: 3,
    overflow: 'hidden',
  },
  barGreen: {
    height: '100%',
    background: theme.green,
    transition: 'width 0.3s ease',
  },
  barRed: {
    height: '100%',
    background: theme.red,
    transition: 'width 0.3s ease',
  },
  progressLine: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    fontSize: 11,
    color: theme.textMuted,
  },
  progressStrong: {
    fontWeight: 600,
    color: theme.text,
  },
  progressPct: {
    fontVariantNumeric: 'tabular-nums',
  },
  statRow: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
  },
  statValue: {
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
  },
  statLabel: {
    opacity: 0.85,
  },
  childList: {
    marginTop: 2,
    paddingTop: 6,
    borderTop: `1px dashed ${theme.border}`,
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
  },
  childRow: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '2px 0',
  },
  childDot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  childLink: {
    fontSize: 10,
    fontWeight: 600,
    color: theme.accent,
    textDecoration: 'none',
    flexShrink: 0,
  },
  childTitle: {
    fontSize: 10,
    color: theme.text,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    flex: 1,
    minWidth: 0,
  },
  childBadgeDone: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.green,
    background: theme.greenSubtle,
    borderRadius: 4,
    padding: '0 4px',
    flexShrink: 0,
  },
  childBadgeFailed: {
    fontSize: 9,
    fontWeight: 600,
    color: theme.red,
    background: theme.redSubtle,
    borderRadius: 4,
    padding: '0 4px',
    flexShrink: 0,
  },
  childEmpty: {
    fontSize: 10,
    color: theme.textMuted,
    fontStyle: 'italic',
  },
}

const statPillBase = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 4,
  fontSize: 10,
  borderRadius: 999,
  padding: '2px 8px',
  whiteSpace: 'nowrap',
}

const statPillStyles = {
  muted: { ...statPillBase, color: theme.textMuted, background: theme.surfaceInset },
  green: { ...statPillBase, color: theme.green, background: theme.greenSubtle },
  red: { ...statPillBase, color: theme.red, background: theme.redSubtle },
  accent: { ...statPillBase, color: theme.accent, background: theme.accentSubtle },
  yellow: { ...statPillBase, color: theme.yellow, background: theme.yellowSubtle },
}

const epicStatusBase = {
  fontSize: 9,
  fontWeight: 600,
  padding: '1px 6px',
  borderRadius: 4,
  flexShrink: 0,
}

const epicStatusStyles = {
  // Execution states derived from worker/queue occupancy (deriveEpicExecutionState, #10299)
  active: { ...epicStatusBase, color: theme.green, background: theme.greenSubtle },
  running: { ...epicStatusBase, color: theme.green, background: theme.greenSubtle },
  queued: { ...epicStatusBase, color: theme.yellow, background: theme.yellowSubtle },
  paused: { ...epicStatusBase, color: theme.textMuted, background: theme.mutedSubtle },
  idle: { ...epicStatusBase, color: theme.textMuted, background: theme.mutedSubtle },
  // Terminal statuses
  completed: { ...epicStatusBase, color: theme.textMuted, background: theme.mutedSubtle },
  stale: { ...epicStatusBase, color: theme.yellow, background: theme.yellowSubtle },
  blocked: { ...epicStatusBase, color: theme.red, background: theme.redSubtle },
  // Client-only release lifecycle statuses
  ready: { ...epicStatusBase, color: theme.cyan, background: theme.cyanSubtle },
  releasing: { ...epicStatusBase, color: theme.purple, background: theme.purpleSubtle },
  released: { ...epicStatusBase, color: theme.green, background: theme.greenSubtle },
}
