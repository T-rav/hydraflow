/**
 * ActivityDrawer — the operator console's demoted, grouped, virtualized global
 * activity feed (epic #10556, Task 7). Replaces today's raw firehose EventLog:
 * activity is no longer the star of the layout, it is a strip that expands.
 *
 *   - Collapsed (default): a single strip = latest line + filter chips
 *     (`all · errors · merges · hitl`) + an "N new" pill when unseen rows have
 *     arrived.
 *   - Expanded: a virtualized, grouped list. Grouped rows (a collapsed run of
 *     heartbeats / identical transcript lines) show an "×N" count. Error / HITL
 *     / alert rows are NEVER grouped — that guarantee is enforced upstream by
 *     `toActivityFeed(...)` (Task 1), so here each simply renders as its own
 *     row with count === 1 (no badge).
 *
 * Windowing is lightweight and dependency-free (slice-by-scroll via
 * `useActivityFeed`): a spacer div holds the full scroll height while only a
 * bounded window of rows is mounted and translated into view. Presentation
 * only — no socket, no side effects; styling uses the shared `theme`
 * CSS-variable references so the dark/light paths keep working.
 */

import React from 'react'
import { theme } from '../theme'
import { useActivityFeed } from './useActivityFeed'

function severityColor(severity) {
  if (severity === 'error') return theme.red
  if (severity === 'warn') return theme.yellow
  return theme.textMuted
}

const styles = {
  drawer: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
    borderTop: `1px solid ${theme.border}`,
    background: theme.surface,
  },
  strip: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 10px',
    minWidth: 0,
  },
  toggle: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    flexShrink: 0,
    background: 'transparent',
    color: theme.text,
    cursor: 'pointer',
    padding: '2px 4px',
    font: 'inherit',
    fontWeight: 700,
    fontSize: 11,
    textTransform: 'uppercase',
    letterSpacing: 0.4,
    borderRadius: 4,
    borderWidth: 0,
    borderStyle: 'none',
  },
  caret: {
    fontSize: 10,
    color: theme.textMuted,
  },
  latest: {
    flex: '1 1 auto',
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    fontSize: 12,
    fontVariantNumeric: 'tabular-nums',
  },
  inlineCount: {
    color: theme.textMuted,
    fontVariantNumeric: 'tabular-nums',
  },
  chips: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    flexShrink: 0,
  },
  chip: {
    border: `1px solid ${theme.border}`,
    borderRadius: 10,
    background: theme.surfaceInset,
    color: theme.textMuted,
    cursor: 'pointer',
    padding: '1px 8px',
    font: 'inherit',
    fontSize: 10,
    fontWeight: 600,
    lineHeight: 1.6,
  },
  chipActive: {
    background: theme.accent,
    color: theme.bg,
    borderColor: theme.accent,
  },
  newBadge: {
    flexShrink: 0,
    borderRadius: 10,
    background: theme.orange,
    color: theme.bg,
    padding: '1px 8px',
    fontSize: 10,
    fontWeight: 700,
    lineHeight: 1.6,
    whiteSpace: 'nowrap',
  },
  list: {
    overflowY: 'auto',
    overflowX: 'hidden',
    borderTop: `1px solid ${theme.border}`,
  },
  spacer: {
    position: 'relative',
    width: '100%',
  },
  window: {
    position: 'absolute',
    top: 0,
    left: 0,
    right: 0,
  },
  row: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '0 10px',
    boxSizing: 'border-box',
    fontSize: 12,
    minWidth: 0,
  },
  dot: {
    display: 'inline-block',
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  rowSummary: {
    flex: '1 1 auto',
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    color: theme.text,
  },
  count: {
    flexShrink: 0,
    borderRadius: 8,
    background: theme.surfaceInset,
    color: theme.textMuted,
    padding: '0 6px',
    fontSize: 10,
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
  },
  empty: {
    padding: '10px',
    fontSize: 12,
    color: theme.textMuted,
  },
}

function ActivityRow({ row, rowHeight }) {
  return (
    <div
      data-testid="activity-row"
      data-type={row.type}
      data-severity={row.severity}
      style={{ ...styles.row, height: rowHeight }}
    >
      <span style={{ ...styles.dot, background: severityColor(row.severity) }} />
      <span style={styles.rowSummary} title={row.summary}>
        {row.summary}
      </span>
      {row.count > 1 && (
        <span data-testid="activity-count" style={styles.count}>
          ×{row.count}
        </span>
      )}
    </div>
  )
}

/**
 * @param {{ activity?: Array<{ts,type,severity,summary,groupKey,count}> }} props
 *   `activity` is the grouped feed from `toActivityFeed(...)`. Any extra props
 *   passed by the shell (e.g. `select`) are intentionally ignored — the drawer
 *   is a read-only view.
 */
export function ActivityDrawer({ activity = [] }) {
  const {
    filter,
    setFilter,
    filters,
    expanded,
    toggle,
    latest,
    newCount,
    visible,
    onScroll,
    totalHeight,
    offsetTop,
    rowHeight,
    viewportHeight,
  } = useActivityFeed(activity)

  return (
    <div data-testid="activity-drawer" data-expanded={expanded} style={styles.drawer}>
      <div data-testid="activity-strip" style={styles.strip}>
        <button
          type="button"
          data-testid="activity-toggle"
          aria-expanded={expanded}
          onClick={toggle}
          style={styles.toggle}
        >
          <span style={styles.caret}>{expanded ? '▾' : '▸'}</span>
          <span>Activity</span>
        </button>

        <span
          data-testid="activity-latest"
          style={{ ...styles.latest, color: severityColor(latest?.severity) }}
          title={latest?.summary || ''}
        >
          {latest ? latest.summary : 'No activity yet'}
          {latest && latest.count > 1 && <span style={styles.inlineCount}> ×{latest.count}</span>}
        </span>

        <span style={styles.chips}>
          {filters.map(f => (
            <button
              key={f.key}
              type="button"
              data-testid={`activity-filter-${f.key}`}
              aria-pressed={filter === f.key}
              onClick={() => setFilter(f.key)}
              style={{ ...styles.chip, ...(filter === f.key ? styles.chipActive : null) }}
            >
              {f.label}
            </button>
          ))}
        </span>

        {newCount > 0 && (
          <span data-testid="activity-new-count" style={styles.newBadge}>
            {newCount} new
          </span>
        )}
      </div>

      {expanded && (
        <div
          data-testid="activity-list"
          onScroll={onScroll}
          style={{ ...styles.list, height: viewportHeight }}
        >
          {visible.length === 0 ? (
            <div style={styles.empty}>No matching activity.</div>
          ) : (
            <div style={{ ...styles.spacer, height: totalHeight }}>
              <div style={{ ...styles.window, transform: `translateY(${offsetTop}px)` }}>
                {visible.map(({ row, index }) => (
                  <ActivityRow key={row.groupKey ?? `${row.type}-${index}`} row={row} rowHeight={rowHeight} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default ActivityDrawer
