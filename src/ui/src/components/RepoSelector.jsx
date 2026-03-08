import React, { useState, useRef, useEffect } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'
import { normalizeRepoSlug } from '../context/HydraFlowContext'

export function RepoSelector() {
  const {
    supervisedRepos = [],
    runtimes = [],
    selectedRepoSlug,
    selectRepo,
  } = useHydraFlow()
  const [open, setOpen] = useState(false)
  const containerRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // Build repo list from supervisedRepos, augmented with runtime status
  const runtimeMap = new Map(
    (runtimes || []).map((rt) => [normalizeRepoSlug(rt.slug), rt]),
  )

  const repos = (supervisedRepos || []).map((repo) => {
    const slug = repo.slug || ''
    const normalized = normalizeRepoSlug(slug)
    const rt = runtimeMap.get(normalized)
    return {
      slug,
      displayName: slug || repo.path || 'unknown',
      running: rt?.running ?? repo.running ?? false,
    }
  })

  const selectedLabel = selectedRepoSlug
    ? (repos.find(r => normalizeRepoSlug(r.slug) === selectedRepoSlug)?.displayName || selectedRepoSlug)
    : 'All repos'

  return (
    <div ref={containerRef} style={styles.container} data-testid="repo-selector">
      <button
        style={styles.trigger}
        onClick={() => setOpen(!open)}
        data-testid="repo-selector-trigger"
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span style={styles.triggerLabel}>{selectedLabel}</span>
        <span style={styles.triggerArrow}>{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div style={styles.dropdown} role="listbox" data-testid="repo-selector-dropdown">
          <div
            style={!selectedRepoSlug ? optionSelected : styles.option}
            onClick={() => { selectRepo(null); setOpen(false) }}
            role="option"
            aria-selected={!selectedRepoSlug}
            data-testid="repo-option-all"
          >
            <span style={styles.optionLabel}>All repos</span>
          </div>
          {repos.map((repo) => {
            const normalized = normalizeRepoSlug(repo.slug)
            const isSelected = selectedRepoSlug === normalized
            return (
              <div
                key={repo.slug}
                style={isSelected ? optionSelected : styles.option}
                onClick={() => { selectRepo(repo.slug); setOpen(false) }}
                role="option"
                aria-selected={isSelected}
                data-testid={`repo-option-${normalized}`}
              >
                <span
                  style={repo.running ? dotRunning : dotStopped}
                  data-testid={`repo-status-${normalized}`}
                />
                <span style={styles.optionLabel}>{repo.displayName}</span>
              </div>
            )
          })}
          {repos.length === 0 && (
            <div style={styles.emptyOption}>No repos registered</div>
          )}
        </div>
      )}
    </div>
  )
}

const styles = {
  container: {
    position: 'relative',
    display: 'inline-flex',
  },
  trigger: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    padding: '4px 10px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.bg,
    color: theme.text,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
    whiteSpace: 'nowrap',
    maxWidth: 180,
    transition: 'border-color 0.15s',
  },
  triggerLabel: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  triggerArrow: {
    fontSize: 10,
    color: theme.textMuted,
    flexShrink: 0,
  },
  dropdown: {
    position: 'absolute',
    top: '100%',
    left: 0,
    marginTop: 4,
    minWidth: 200,
    maxHeight: 280,
    overflowY: 'auto',
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 8,
    padding: '4px 0',
    zIndex: 100,
    boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
  },
  option: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '6px 12px',
    cursor: 'pointer',
    fontSize: 12,
    color: theme.text,
    transition: 'background 0.1s',
  },
  optionLabel: {
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  dot: {
    width: 6,
    height: 6,
    borderRadius: '50%',
    flexShrink: 0,
  },
  emptyOption: {
    padding: '8px 12px',
    fontSize: 11,
    color: theme.textMuted,
    fontStyle: 'italic',
  },
}

// Pre-computed variants
const optionSelected = { ...styles.option, background: theme.accentSubtle }
const dotRunning = { ...styles.dot, background: theme.green }
const dotStopped = { ...styles.dot, background: theme.textMuted, opacity: 0.5 }
