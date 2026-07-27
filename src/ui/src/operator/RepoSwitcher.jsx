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
 * HydraFlowProvider. Phase-2 (Task 12): every colour / space / radius / shadow
 * value resolves from `useTokens()`, so light + dark fall out of the console's
 * ThemeProvider mode — the dropdown shadow is a token, not a hardcoded rgba.
 */

import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useTokens } from '../styles/primitives'
import { canonicalRepoSlug } from '../constants'
import { borderSides } from '../styles/borders'
import { RegisterRepoDialog } from '../components/RegisterRepoDialog'

function makeStyles(t) {
  const optionBase = {
    display: 'flex',
    alignItems: 'center',
    gap: t.space.sm,
    width: '100%',
    padding: `${t.space.sm}px ${t.space.md}px`,
    border: 'none',
    color: t.color.text,
    cursor: 'pointer',
    textAlign: 'left',
    fontSize: t.type.size.sm,
    fontWeight: t.type.weight.semibold,
  }
  return {
    wrapper: { position: 'relative', minWidth: 160, display: 'inline-block' },
    trigger: {
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'space-between',
      gap: t.space.sm,
      width: '100%',
      padding: `${t.space.xs}px ${t.space.md}px`,
      borderRadius: t.radius.lg,
      border: `1px solid ${t.color.border}`,
      background: t.color.surface,
      color: t.color.text,
      cursor: 'pointer',
      fontSize: t.type.size.sm,
      fontWeight: t.type.weight.bold,
    },
    triggerLabel: {
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
      minWidth: 0,
    },
    chevron: { fontSize: 10, color: t.color.textMuted },
    dropdown: {
      position: 'absolute',
      top: 'calc(100% + 4px)',
      left: 0,
      minWidth: 200,
      background: t.color.surface,
      border: `1px solid ${t.color.border}`,
      borderRadius: t.radius.lg,
      boxShadow: t.shadow.lg,
      zIndex: 20,
      display: 'flex',
      flexDirection: 'column',
      maxHeight: 320,
      overflowY: 'auto',
    },
    option: { ...optionBase, background: 'transparent' },
    optionActive: { ...optionBase, background: `color-mix(in srgb, ${t.color.accent} 18%, transparent)` },
    statusDot: (running) => ({
      width: 8,
      height: 8,
      borderRadius: t.radius.pill,
      flexShrink: 0,
      background: running ? t.color.green : t.color.textMuted,
    }),
    divider: { height: 1, background: t.color.border, margin: `${t.space.xs}px 0` },
    addBtn: {
      display: 'flex',
      alignItems: 'center',
      width: '100%',
      padding: `${t.space.sm}px ${t.space.md}px`,
      ...borderSides({ top: `1px solid ${t.color.border}` }),
      background: t.color.surfaceInset,
      color: t.color.accent,
      cursor: 'pointer',
      fontSize: t.type.size.sm,
      fontWeight: t.type.weight.bold,
    },
  }
}

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
  const t = useTokens()
  const styles = makeStyles(t)
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
            style={!current ? styles.optionActive : styles.option}
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
                style={isCurrent ? styles.optionActive : styles.option}
                onClick={() => switchTo(repo.slug)}
              >
                <span style={styles.statusDot(repo.running)} />
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
