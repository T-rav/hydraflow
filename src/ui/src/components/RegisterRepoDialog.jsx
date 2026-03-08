import React, { useState, useCallback, useRef, useEffect } from 'react'
import { theme } from '../theme'
import { useHydraFlow } from '../context/HydraFlowContext'

export function RegisterRepoDialog({ isOpen, onClose }) {
  const { addRepoByPath, startRuntime } = useHydraFlow()
  const [input, setInput] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)
  const inputRef = useRef(null)

  useEffect(() => {
    if (isOpen && inputRef.current) {
      inputRef.current.focus()
    }
    if (isOpen) {
      setInput('')
      setError(null)
    }
  }, [isOpen])

  const handleSubmit = useCallback(async (e) => {
    e.preventDefault()
    const value = input.trim()
    if (!value) return

    setLoading(true)
    setError(null)

    try {
      // Detect if it's a slug (owner/repo) or a filesystem path
      const isSlug = /^[a-zA-Z0-9_.-]+\/[a-zA-Z0-9_.-]+$/.test(value)
      if (isSlug) {
        // Use startRuntime with slug to register via /api/repos
        const result = await startRuntime(value)
        if (result?.ok) {
          onClose()
        } else {
          setError(result?.error || 'Failed to register repo')
        }
      } else {
        // Treat as filesystem path
        const result = await addRepoByPath(value)
        if (result?.ok) {
          onClose()
        } else {
          setError(result?.error || 'Failed to add repo')
        }
      }
    } catch (err) {
      setError(err?.message || 'Unexpected error')
    } finally {
      setLoading(false)
    }
  }, [input, addRepoByPath, startRuntime, onClose])

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Escape') onClose()
  }, [onClose])

  if (!isOpen) return null

  return (
    <div
      style={styles.overlay}
      onClick={onClose}
      onKeyDown={handleKeyDown}
      data-testid="register-repo-overlay"
    >
      <div
        style={styles.dialog}
        onClick={(e) => e.stopPropagation()}
        data-testid="register-repo-dialog"
      >
        <div style={styles.header}>
          <span style={styles.title}>Register Repository</span>
          <button
            style={styles.closeBtn}
            onClick={onClose}
            aria-label="Close"
            data-testid="register-repo-close"
          >
            ×
          </button>
        </div>
        <form onSubmit={handleSubmit}>
          <label style={styles.label} htmlFor="repo-input">
            GitHub slug or filesystem path
          </label>
          <input
            ref={inputRef}
            id="repo-input"
            type="text"
            style={styles.input}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="owner/repo or /path/to/repo"
            disabled={loading}
            data-testid="register-repo-input"
          />
          {error && (
            <div style={styles.error} data-testid="register-repo-error">
              {error}
            </div>
          )}
          <div style={styles.actions}>
            <button
              type="button"
              style={styles.cancelBtn}
              onClick={onClose}
              disabled={loading}
            >
              Cancel
            </button>
            <button
              type="submit"
              style={loading || !input.trim() ? submitBtnDisabled : styles.submitBtn}
              disabled={loading || !input.trim()}
              data-testid="register-repo-submit"
            >
              {loading ? 'Adding…' : 'Add'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    bottom: 0,
    background: theme.overlay,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 1000,
  },
  dialog: {
    background: theme.surface,
    border: `1px solid ${theme.border}`,
    borderRadius: 12,
    padding: 24,
    width: 420,
    maxWidth: '90vw',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 16,
  },
  title: {
    fontSize: 16,
    fontWeight: 700,
    color: theme.textBright,
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    color: theme.textMuted,
    fontSize: 20,
    cursor: 'pointer',
    padding: '0 4px',
    lineHeight: 1,
  },
  label: {
    display: 'block',
    fontSize: 12,
    fontWeight: 600,
    color: theme.textMuted,
    marginBottom: 8,
  },
  input: {
    width: '100%',
    padding: '8px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: theme.bg,
    color: theme.text,
    fontSize: 13,
    outline: 'none',
    boxSizing: 'border-box',
  },
  error: {
    fontSize: 11,
    color: theme.red,
    marginTop: 8,
  },
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 8,
    marginTop: 16,
  },
  cancelBtn: {
    padding: '6px 12px',
    borderRadius: 6,
    border: `1px solid ${theme.border}`,
    background: 'none',
    color: theme.textMuted,
    fontSize: 12,
    fontWeight: 600,
    cursor: 'pointer',
  },
  submitBtn: {
    padding: '6px 16px',
    borderRadius: 6,
    border: `1px solid ${theme.accent}`,
    background: theme.accentSubtle,
    color: theme.accent,
    fontSize: 12,
    fontWeight: 700,
    cursor: 'pointer',
  },
}

// Pre-computed variant
const submitBtnDisabled = { ...styles.submitBtn, opacity: 0.4, cursor: 'not-allowed' }
