/**
 * RepoSwitcher — jump sideways between repos (epic #10556, Task 9).
 *
 * A compact dropdown that lets the operator switch which repo the console is
 * focused on WITHOUT losing their place: the current stage/item drill depth is
 * re-applied after the repo changes, so switching from `acme/app › Build › #55`
 * to `acme/lib` lands on `acme/lib › Build › #55` rather than dumping back to the
 * repo root. It also exposes the aggregate "All repos" entry (pop back to the
 * portfolio overview) and a "+ Add repo" action that opens the EXISTING
 * {@link RegisterRepoDialog} — repo registration is not reinvented here.
 *
 * The switcher is presentational and provider-free: it takes the repo list and
 * the Task-2 `select` callback as props. The only context consumer is
 * RegisterRepoDialog, which is mounted lazily (only once "+ Add repo" is clicked)
 * so the switcher itself renders fine inside the operator shell's tests without a
 * HydraFlowProvider. Styling uses the shared `theme` CSS-variable refs.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { theme } from '../theme'
import { canonicalRepoSlug } from '../constants'
import { borderSides } from '../styles/borders'
import { RegisterRepoDialog } from '../components/RegisterRepoDialog'

const styles = {
  wrapper: {
    position: 'relative',
    minWidth: 160,
    display: 'inline-block',
  },
  trigger: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 8,
    width: '100%',
    padding: '6px 10px',
    borderRadius: 8,
    border: `1px solid ${theme.border}`,
    background: theme.surface,
    color: theme.text,
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 700,
  },
  triggerLabel: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    minWidth: 0,
  },
  chevron: {
    fontSize: 10,
    color: theme.textMuted,
  },
  dropdown: {
    position: 'absolute',
    top: 'calc(100% + 4px)',
    left: 0,
    minWidth: 200,
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    boxShadow: '0 6px 18px rgba(0,0,0,0.35)',
    zIndex: 20,
    display: 'flex',
    flexDirection: 'column',
    maxHeight: 320,
    overflowY: 'auto',
  },
  optionBase: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    width: '100%',
    padding: '8px 10px',
    border: 'none',
    color: theme.text,
    cursor: 'pointer',
    textAlign: 'left',
    fontSize: 12,
    fontWeight: 600,
  },
  statusDot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    flexShrink: 0,
  },
  divider: {
    height: 1,
    background: theme.border,
    margin: '4px 0',
  },
  addBtn: {
    display: 'flex',
    alignItems: 'center',
    width: '100%',
    padding: '8px 10px',
    ...borderSides({ top: `1px solid ${theme.border}` }),
    background: theme.surfaceInset,
    color: theme.accent,
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 700,
  },
}

const optionStyle = { ...styles.optionBase, background: 'transparent' }
const optionActiveStyle = { ...styles.optionBase, background: theme.accentSubtle }

/**
 * @param {{
 *   repos?: Array<{ slug: string, name?: string, running?: boolean }>,
 *   current?: string|null,       // useOperatorSelection().repo
 *   stage?: string|null,         // useOperatorSelection().stage (re-applied on switch)
 *   item?: string|null,          // useOperatorSelection().item  (re-applied on switch)
 *   select?: (kind: string, value: unknown) => void,
 * }} props
 */
export function RepoSwitcher({ repos = [], current = null, stage = null, item = null, select = () => {} }) {
  const [open, setOpen] = useState(false)
  const [dialogOpen, setDialogOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!open) return undefined
    const handleClick = (event) => {
      if (containerRef.current && !containerRef.current.contains(event.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const canonicalCurrent = current ? canonicalRepoSlug(current) : null

  const currentLabel = useMemo(() => {
    if (!current) return 'All repos'
    const match = repos.find(r => canonicalRepoSlug(r.slug) === canonicalCurrent)
    return match?.name || current
  }, [repos, current, canonicalCurrent])

  // Switch repo while preserving the drill depth: applySelect('repo', ...) in the
  // selection hook resets stage+item, so we re-apply whatever depth was set. Each
  // select() is a functional state update, so the three compose in order to
  // { repo, stage, item } — a genuine sideways jump.
  const switchTo = (slug) => {
    select('repo', slug)
    if (stage) select('stage', stage)
    if (item) select('item', item)
    setOpen(false)
  }

  const goAllRepos = () => {
    // The overview is the repo root — clearing the repo already drops depth, so
    // do NOT re-apply stage/item here.
    select('repo', null)
    setOpen(false)
  }

  const openAddRepo = () => {
    setOpen(false)
    setDialogOpen(true)
  }

  return (
    <div ref={containerRef} style={styles.wrapper}>
      <button
        type="button"
        data-testid="repo-switcher-trigger"
        style={styles.trigger}
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => setOpen(prev => !prev)}
      >
        <span style={styles.triggerLabel}>{currentLabel}</span>
        <span style={styles.chevron}>{open ? '▴' : '▾'}</span>
      </button>

      {open && (
        <div style={styles.dropdown} role="listbox" data-testid="repo-switcher-dropdown">
          <button
            type="button"
            data-testid="repo-switcher-all"
            role="option"
            aria-selected={!current}
            style={!current ? optionActiveStyle : optionStyle}
            onClick={goAllRepos}
          >
            All repos
          </button>
          <div style={styles.divider} />
          {repos.map(repo => {
            const isCurrent = canonicalRepoSlug(repo.slug) === canonicalCurrent
            return (
              <button
                type="button"
                key={repo.slug}
                data-testid={`repo-switcher-option-${repo.slug}`}
                role="option"
                aria-selected={isCurrent}
                style={isCurrent ? optionActiveStyle : optionStyle}
                onClick={() => switchTo(repo.slug)}
              >
                <span
                  style={{ ...styles.statusDot, background: repo.running ? theme.green : theme.textMuted }}
                />
                {repo.name || repo.slug}
              </button>
            )
          })}
          <button
            type="button"
            data-testid="repo-switcher-add"
            style={styles.addBtn}
            onClick={openAddRepo}
          >
            + Add repo
          </button>
        </div>
      )}

      {dialogOpen && (
        <RegisterRepoDialog isOpen onClose={() => setDialogOpen(false)} />
      )}
    </div>
  )
}

export default RepoSwitcher
