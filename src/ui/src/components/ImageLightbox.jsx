import React, { useCallback, useEffect } from 'react'
import { theme } from '../theme'

/**
 * Full-screen click-to-zoom overlay for a captured screenshot (#10626).
 *
 * Inline dashboard thumbnails are too small to read; this renders `src`
 * centered at up to the viewport size while preserving aspect ratio
 * (`objectFit: contain`, `width/height: auto`) so a screenshot is legible
 * without leaving the dashboard. The backdrop, the close button, and the
 * Escape key all dismiss it; an "Open original" link opens the
 * full-resolution image in a new tab.
 *
 * Props:
 *   src      — image URL to display (renders nothing when falsy)
 *   alt      — accessible alt text for the image
 *   caption  — optional label shown in the toolbar
 *   onClose  — called when the viewer should be dismissed
 */
export function ImageLightbox({ src, alt = '', caption = '', onClose }) {
  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === 'Escape') onClose?.()
    },
    [onClose]
  )

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const handleBackdropClick = useCallback(
    (e) => {
      if (e.target === e.currentTarget) onClose?.()
    },
    [onClose]
  )

  if (!src) return null

  return (
    <div
      style={styles.overlay}
      onClick={handleBackdropClick}
      role="dialog"
      aria-modal="true"
      aria-label={alt || caption || 'Screenshot preview'}
      data-testid="image-lightbox-overlay"
    >
      <div style={styles.toolbar}>
        {caption && (
          <span style={styles.caption} data-testid="image-lightbox-caption">
            {caption}
          </span>
        )}
        <div style={styles.toolbarActions}>
          <a
            href={src}
            target="_blank"
            rel="noreferrer"
            style={styles.openOriginal}
            onClick={(e) => e.stopPropagation()}
            data-testid="image-lightbox-open-original"
          >
            Open original ↗
          </a>
          <button
            type="button"
            style={styles.closeBtn}
            onClick={onClose}
            aria-label="Close"
            data-testid="image-lightbox-close"
          >
            ✕
          </button>
        </div>
      </div>
      <img
        src={src}
        alt={alt}
        style={styles.image}
        onClick={(e) => e.stopPropagation()}
        data-testid="image-lightbox-img"
      />
    </div>
  )
}

const styles = {
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.85)',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    padding: 24,
    boxSizing: 'border-box',
    zIndex: 1100,
  },
  toolbar: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'flex-end',
    gap: 16,
    width: '100%',
    maxWidth: '95vw',
  },
  caption: {
    marginRight: 'auto',
    fontSize: 13,
    fontWeight: 600,
    color: theme.white,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  toolbarActions: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  openOriginal: {
    color: theme.accent,
    fontSize: 12,
    fontWeight: 600,
    textDecoration: 'none',
    whiteSpace: 'nowrap',
  },
  closeBtn: {
    borderTop: `1px solid ${theme.border}`,
    borderRight: `1px solid ${theme.border}`,
    borderBottom: `1px solid ${theme.border}`,
    borderLeft: `1px solid ${theme.border}`,
    borderRadius: 6,
    background: 'transparent',
    color: theme.white,
    fontSize: 14,
    fontWeight: 700,
    lineHeight: 1,
    padding: '4px 10px',
    cursor: 'pointer',
  },
  image: {
    maxWidth: '95vw',
    maxHeight: '85vh',
    width: 'auto',
    height: 'auto',
    objectFit: 'contain',
    borderRadius: 8,
    boxShadow: '0 8px 40px rgba(0,0,0,0.5)',
  },
}
