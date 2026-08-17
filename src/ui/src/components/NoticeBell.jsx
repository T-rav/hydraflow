import React, { useCallback, useState } from 'react'
import { theme } from '../theme'

/**
 * Advisory-notice bell (#11306).
 *
 * The banner is the console's highest-urgency surface — credit pauses,
 * factory faults, HITL requests. Informational caretaker notices (an epic
 * gone stale, a fleet-vitals shadow alarm) used to render there with the
 * same weight, which trains the operator to ignore the banner. They now
 * land here: a count badge, a dropdown listing each notice with its
 * source, and per-notice dismissal.
 *
 * Severity routing lives in the reducer; this component only renders what
 * it is handed.
 */
export function NoticeBell({ notices = [], onDismiss, onDismissAll }) {
  const [open, setOpen] = useState(false)
  const count = notices.length

  const toggle = useCallback(() => setOpen(prev => !prev), [])

  if (count === 0) {
    return (
      <span style={styles.wrap} data-testid="notice-bell-empty" title="No advisories">
        <span style={styles.bellMuted}>🔔</span>
      </span>
    )
  }

  return (
    <span style={styles.wrap}>
      <button
        type="button"
        onClick={toggle}
        style={styles.bellButton}
        aria-label={`${count} advisory ${count === 1 ? 'notice' : 'notices'}`}
        aria-expanded={open}
        data-testid="notice-bell"
      >
        <span style={styles.bell}>🔔</span>
        <span style={styles.badge} data-testid="notice-bell-count">{count}</span>
      </button>
      {open && (
        <div style={styles.dropdown} role="dialog" data-testid="notice-bell-dropdown">
          <div style={styles.dropdownHead}>
            <span style={styles.dropdownTitle}>Advisories</span>
            {onDismissAll && (
              <button
                type="button"
                onClick={onDismissAll}
                style={styles.clearAll}
                data-testid="notice-bell-clear-all"
              >
                Clear all
              </button>
            )}
          </div>
          {notices.map(notice => (
            <div key={notice.id} style={styles.notice} data-testid="notice-bell-item">
              <div style={styles.noticeMessage}>{notice.message}</div>
              <div style={styles.noticeMeta}>
                {notice.source && <span>{notice.source}</span>}
                {onDismiss && (
                  <span
                    role="button"
                    tabIndex={0}
                    onClick={() => onDismiss(notice.id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        onDismiss(notice.id)
                      }
                    }}
                    style={styles.noticeDismiss}
                    data-testid="notice-bell-dismiss"
                  >
                    ✕
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </span>
  )
}

const styles = {
  wrap: { position: 'relative', display: 'inline-flex', alignItems: 'center' },
  bellButton: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 4,
    background: 'transparent',
    border: 'none',
    cursor: 'pointer',
    padding: '2px 4px',
  },
  bell: { fontSize: 14 },
  bellMuted: { fontSize: 14, opacity: 0.35 },
  badge: {
    background: theme.yellow,
    color: theme.bg,
    borderRadius: 8,
    fontSize: 10,
    fontWeight: 700,
    padding: '0 5px',
    minWidth: 14,
    textAlign: 'center',
  },
  dropdown: {
    position: 'absolute',
    top: '100%',
    right: 0,
    marginTop: 6,
    width: 380,
    maxHeight: 420,
    overflowY: 'auto',
    background: theme.bgPanel || theme.bg,
    border: `1px solid ${theme.border}`,
    borderRadius: 6,
    boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
    zIndex: 40,
  },
  dropdownHead: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '8px 10px',
    borderBottom: `1px solid ${theme.border}`,
  },
  dropdownTitle: { fontSize: 12, fontWeight: 700, color: theme.textMuted },
  clearAll: {
    background: 'transparent',
    border: 'none',
    color: theme.accent,
    cursor: 'pointer',
    fontSize: 11,
  },
  notice: { padding: '8px 10px', borderBottom: `1px solid ${theme.border}` },
  noticeMessage: { fontSize: 12, color: theme.text, lineHeight: 1.4 },
  noticeMeta: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    marginTop: 4,
    fontSize: 10,
    color: theme.textMuted,
  },
  noticeDismiss: { cursor: 'pointer', padding: '0 4px' },
}
