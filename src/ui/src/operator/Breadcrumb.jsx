/**
 * Breadcrumb — the operator console's depth trail (epic #10556, Task 8).
 *
 * Renders the root-first crumb array from `useOperatorSelection` (Task 2) as a
 * clickable trail: `‹ All repos › repo ▾ › stage › item`. Each crumb carries the
 * exact `select(kind, value)` args needed to "pop" the selection back to that
 * depth — clicking a shallower crumb drops everything beneath it (picking the
 * repo crumb drops stage + item; the root "All repos" crumb clears the repo).
 *
 * The terminal crumb is the current location, so it is rendered as a static
 * `aria-current="page"` marker rather than a navigable button. The concrete
 * repo crumb carries a ▾ switcher caret — the visual affordance for the
 * RepoSwitcher dropdown that lands in Task 9; here it is presentation only.
 *
 * Presentation only — no socket, no side effects. Styling uses the shared
 * `theme` CSS-variable references so the dark/light paths keep working.
 */

import React from 'react'
import { theme } from '../theme'

const styles = {
  nav: {
    display: 'flex',
    alignItems: 'center',
    flexWrap: 'wrap',
    gap: 4,
    minWidth: 0,
    fontSize: 12,
  },
  lead: {
    color: theme.textMuted,
    fontWeight: 700,
    marginRight: 2,
  },
  crumbBtn: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 2,
    border: 'none',
    background: 'transparent',
    color: theme.textMuted,
    cursor: 'pointer',
    padding: '2px 4px',
    borderRadius: 4,
    font: 'inherit',
    fontWeight: 600,
    maxWidth: 220,
  },
  crumbCurrent: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 2,
    padding: '2px 4px',
    color: theme.textBright,
    fontWeight: 700,
    maxWidth: 220,
  },
  label: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  caret: {
    color: theme.textMuted,
    fontSize: 10,
  },
  sep: {
    color: theme.textMuted,
    userSelect: 'none',
  },
}

/** A repo crumb with a concrete value carries the ▾ switcher affordance. */
function hasSwitcherCaret(crumb) {
  return crumb.kind === 'repo' && crumb.value != null
}

/**
 * @param {{
 *   breadcrumb?: Array<{ kind: string, label: string, value: unknown }>,
 *   select?: (kind: string, value: unknown) => void,
 * }} props
 */
export function Breadcrumb({ breadcrumb = [], select = () => {} }) {
  const crumbs = breadcrumb ?? []
  const lastIndex = crumbs.length - 1

  return (
    <nav data-testid="operator-breadcrumb" aria-label="Breadcrumb" style={styles.nav}>
      <span aria-hidden="true" style={styles.lead}>‹</span>
      {crumbs.map((crumb, i) => {
        const isCurrent = i === lastIndex
        const caret = hasSwitcherCaret(crumb)
        return (
          <React.Fragment key={`${crumb.kind}:${crumb.value ?? 'root'}:${i}`}>
            {i > 0 && <span aria-hidden="true" style={styles.sep}>›</span>}
            {isCurrent ? (
              <span
                data-testid={`breadcrumb-crumb-${i}`}
                data-kind={crumb.kind}
                aria-current="page"
                style={styles.crumbCurrent}
              >
                <span style={styles.label}>{crumb.label}</span>
                {caret && <span aria-hidden="true" style={styles.caret}>▾</span>}
              </span>
            ) : (
              <button
                type="button"
                data-testid={`breadcrumb-crumb-${i}`}
                data-kind={crumb.kind}
                style={styles.crumbBtn}
                onClick={() => select(crumb.kind, crumb.value)}
              >
                <span style={styles.label}>{crumb.label}</span>
                {caret && <span aria-hidden="true" style={styles.caret}>▾</span>}
              </button>
            )}
          </React.Fragment>
        )
      })}
    </nav>
  )
}

export default Breadcrumb
