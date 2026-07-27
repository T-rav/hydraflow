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
 * only — no socket, no side effects. Phase-2 (Task 12): the strip surface uses
 * the `Surface` primitive, counts use `Badge`, and every colour / space value
 * resolves from `useTokens()`, so light + dark fall out of the console's
 * ThemeProvider mode.
 */

import React from 'react'
import { useTokens, Surface, Badge } from '../styles/primitives'
import { useActivityFeed } from './useActivityFeed'

function severityColor(t, severity) {
  if (severity === 'error') return t.color.red
  if (severity === 'warn') return t.color.yellow
  return t.color.textMuted
}

function makeStyles(t) {
  return {
    drawer: {
      display: 'flex',
      flexDirection: 'column',
      minWidth: 0,
      borderTop: `1px solid ${t.color.border}`,
    },
    strip: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.md}px`,
      minWidth: 0,
    },
    toggle: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: t.space.xs,
      flexShrink: 0,
      background: 'transparent',
      color: t.color.text,
      cursor: 'pointer',
      padding: `${t.space.xxs}px ${t.space.xs}px`,
      font: 'inherit',
      fontWeight: t.type.weight.bold,
      fontSize: t.type.size.xs,
      textTransform: 'uppercase',
      letterSpacing: t.type.tracking.wide,
      borderRadius: t.radius.sm,
      borderWidth: 0,
      borderStyle: 'none',
    },
    caret: { fontSize: 10, color: t.color.textMuted },
    latest: (severity) => ({
      flex: '1 1 auto',
      minWidth: 0,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      fontSize: t.type.size.sm,
      fontVariantNumeric: 'tabular-nums',
      color: severityColor(t, severity),
    }),
    inlineCount: { color: t.color.textMuted, fontVariantNumeric: 'tabular-nums' },
    chips: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: t.space.xs,
      flexShrink: 0,
    },
    chip: (active) => ({
      border: `1px solid ${active ? t.color.accent : t.color.border}`,
      borderRadius: t.radius.lg,
      background: active ? t.color.accent : t.color.surfaceInset,
      color: active ? t.color.bg : t.color.textMuted,
      cursor: 'pointer',
      padding: `1px ${t.space.sm}px`,
      font: 'inherit',
      fontSize: 10,
      fontWeight: t.type.weight.semibold,
      lineHeight: 1.6,
    }),
    list: (height) => ({
      overflowY: 'auto',
      overflowX: 'hidden',
      borderTop: `1px solid ${t.color.border}`,
      height,
    }),
    spacer: (height) => ({ position: 'relative', width: '100%', height }),
    window: (offsetTop) => ({
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      transform: `translateY(${offsetTop}px)`,
    }),
    row: (rowHeight) => ({
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      padding: `0 ${t.space.md}px`,
      boxSizing: 'border-box',
      fontSize: t.type.size.sm,
      minWidth: 0,
      height: rowHeight,
    }),
    dot: (severity) => ({
      display: 'inline-block',
      width: 6,
      height: 6,
      borderRadius: t.radius.pill,
      flexShrink: 0,
      background: severityColor(t, severity),
    }),
    rowSummary: {
      flex: '1 1 auto',
      minWidth: 0,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      color: t.color.text,
    },
    empty: { padding: t.space.md, fontSize: t.type.size.sm, color: t.color.textMuted },
  }
}

function ActivityRow({ styles, row, rowHeight }) {
  return (
    <div
      data-testid="activity-row"
      data-type={row.type}
      data-severity={row.severity}
      style={styles.row(rowHeight)}
    >
      <span style={styles.dot(row.severity)} />
      <span style={styles.rowSummary} title={row.summary}>
        {row.summary}
      </span>
      {row.count > 1 && (
        <Badge tone="neutral" data-testid="activity-count">
          ×{row.count}
        </Badge>
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
  const t = useTokens()
  const styles = makeStyles(t)
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
    <Surface tone="raised" as="div" data-testid="activity-drawer" data-expanded={expanded} style={styles.drawer}>
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
          style={styles.latest(latest?.severity)}
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
              style={styles.chip(filter === f.key)}
            >
              {f.label}
            </button>
          ))}
        </span>

        {newCount > 0 && (
          <Badge tone="warning" data-testid="activity-new-count">
            {newCount} new
          </Badge>
        )}
      </div>

      {expanded && (
        <div
          data-testid="activity-list"
          onScroll={onScroll}
          style={styles.list(viewportHeight)}
        >
          {visible.length === 0 ? (
            <div style={styles.empty}>No matching activity.</div>
          ) : (
            <div style={styles.spacer(totalHeight)}>
              <div style={styles.window(offsetTop)}>
                {visible.map(({ row, index }) => (
                  <ActivityRow key={row.groupKey ?? `${row.type}-${index}`} styles={styles} row={row} rowHeight={rowHeight} />
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Surface>
  )
}

export default ActivityDrawer
