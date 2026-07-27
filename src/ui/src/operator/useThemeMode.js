/**
 * useThemeMode — bridge the app's runtime theme flip into the token layer
 * (epic #10556, Phase 2, Task 12).
 *
 * The dashboard flips light/dark by toggling `data-theme` on the document root
 * (`:root[data-theme="light"]` in index.html), which re-points every `var(--x)`
 * CSS variable. The Task-11 primitives, however, resolve CONCRETE token values
 * from a mode (`ThemeProvider` / `useTokens`), not from CSS variables. This hook
 * reads the live `data-theme` (dark-first default) and observes changes, so the
 * operator console can drive a single `ThemeProvider` from it — keeping the
 * primitives and any `var(--x)`-backed style objects flipping together off the
 * same signal. That is what makes the light path keep working end-to-end.
 */

import React from 'react'

/** Read the current document theme mode, dark-first. */
export function readThemeMode() {
  if (typeof document === 'undefined' || !document.documentElement) return 'dark'
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
}

/** Subscribe to `data-theme` changes on the document root; returns the mode. */
export function useThemeMode() {
  const [mode, setMode] = React.useState(readThemeMode)

  React.useEffect(() => {
    if (typeof document === 'undefined' || typeof MutationObserver === 'undefined') {
      return undefined
    }
    const root = document.documentElement
    const sync = () => setMode(readThemeMode())
    sync() // catch any flip between initial render and effect
    const observer = new MutationObserver(sync)
    observer.observe(root, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  return mode
}

export default useThemeMode
