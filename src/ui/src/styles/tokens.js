/**
 * Design tokens for the operator console (epic 10556, Phase 2, Task 11).
 *
 * This is the JS source-of-truth for the visual system: colour / space / type /
 * radius / shadow, with BOTH a `dark` and a `light` palette. Dark is the primary
 * ("dark-first"), but every semantic name has a light counterpart so the light
 * path keeps working the moment a consumer resolves `light` — nothing is a
 * hard-coded dark value downstream.
 *
 * Two faces, one truth:
 *   - `resolveTokens(mode)` returns a fully-resolved token bundle (actual values)
 *     for JS-level consumers and the Phase-2 primitives in `primitives.jsx`.
 *     Flipping `mode` flips every colour/shadow value it returns.
 *   - `cssVars` mirrors the same tokens as `var(--x)` references, aligned 1:1
 *     with the `:root` custom properties in `index.html` and the map in
 *     `theme.js`. Runtime code that rides the browser-driven CSS variable flip
 *     uses these; the resolved palettes above are for code/tests that need the
 *     concrete value.
 *
 * The colour palettes intentionally match the existing dashboard `:root` (dark)
 * and add a Primer-aligned light set, so formalising them here does not change
 * how any current consumer renders.
 */

export const DEFAULT_MODE = 'dark' // dark-first

// ── Theme-independent scales ────────────────────────────────────────────────

// Spacing scale in px. Used for padding, gap, margins.
export const space = Object.freeze({
  none: 0,
  xxs: 2,
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 24,
  xxl: 32,
  xxxl: 48,
})

// Corner radius scale in px (`pill` is an effectively-infinite radius).
export const radius = Object.freeze({
  none: 0,
  sm: 4,
  md: 6,
  lg: 8,
  xl: 12,
  pill: 999,
})

// Typographic scale. `family.mono` matches the dashboard body font.
export const type = Object.freeze({
  family: Object.freeze({
    mono: "'SF Mono', 'Fira Code', 'JetBrains Mono', monospace",
    sans: "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
  }),
  size: Object.freeze({ xs: 11, sm: 12, md: 13, lg: 16, xl: 20, xxl: 28 }),
  weight: Object.freeze({ regular: 400, medium: 500, semibold: 600, bold: 700 }),
  leading: Object.freeze({ tight: 1.2, normal: 1.5 }),
  tracking: Object.freeze({ tight: '-0.01em', normal: '0', wide: '0.5px' }),
})

// ── Colour palettes (dark-first, light counterpart) ─────────────────────────

// Dark palette — identical to the values in `index.html` `:root` so this is a
// formalisation, not a behaviour change, for the current dashboard.
const darkColor = Object.freeze({
  bg: '#0d1117',
  surface: '#161b22',
  surfaceInset: '#21262d',
  border: '#30363d',
  text: '#c9d1d9',
  textBright: '#e6edf3',
  textMuted: '#8b949e',
  textInactive: '#484f58',
  accent: '#58a6ff',
  green: '#3fb950',
  red: '#f85149',
  yellow: '#f2cc60',
  orange: '#d18616',
  purple: '#a371f7',
  cyan: '#56d4dd',
  pink: '#f778ba',
  btnGreen: '#238636',
  btnRed: '#da3633',
  white: '#ffffff',
  codeText: '#79c0ff',
})

// Light palette — Primer-aligned counterparts for the same semantic names.
const lightColor = Object.freeze({
  bg: '#ffffff',
  surface: '#f6f8fa',
  surfaceInset: '#eaeef2',
  border: '#d0d7de',
  text: '#1f2328',
  textBright: '#0d1117',
  textMuted: '#59636e',
  textInactive: '#818b98',
  accent: '#0969da',
  green: '#1a7f37',
  red: '#cf222e',
  yellow: '#9a6700',
  orange: '#bc4c00',
  purple: '#8250df',
  cyan: '#1b7c83',
  pink: '#bf3989',
  btnGreen: '#1f883d',
  btnRed: '#cf222e',
  white: '#ffffff',
  codeText: '#0550ae',
})

export const palettes = Object.freeze({ dark: darkColor, light: lightColor })

// Elevation. Shadows differ per mode so raised surfaces read correctly on both
// backgrounds.
const darkShadow = Object.freeze({
  sm: '0 1px 2px rgba(0,0,0,0.3)',
  md: '0 4px 12px rgba(0,0,0,0.4)',
  lg: '0 8px 24px rgba(0,0,0,0.5)',
})
const lightShadow = Object.freeze({
  sm: '0 1px 2px rgba(31,35,40,0.08)',
  md: '0 4px 12px rgba(31,35,40,0.12)',
  lg: '0 8px 24px rgba(31,35,40,0.16)',
})
export const shadows = Object.freeze({ dark: darkShadow, light: lightShadow })

// ── Resolution ──────────────────────────────────────────────────────────────

/** Coerce an arbitrary mode to a known one, defaulting to dark-first. */
export function resolveMode(mode) {
  return palettes[mode] ? mode : DEFAULT_MODE
}

/**
 * Resolve the full token bundle for a mode. Colour + shadow flip with the mode;
 * space / radius / type are theme-independent and shared by reference.
 *
 * @param {'dark'|'light'} [mode]
 * @returns {{mode: string, color: object, shadow: object, space: object, radius: object, type: object}}
 */
export function resolveTokens(mode = DEFAULT_MODE) {
  const m = resolveMode(mode)
  return Object.freeze({
    mode: m,
    color: palettes[m],
    shadow: shadows[m],
    space,
    radius,
    type,
  })
}

// ── CSS-variable mirror (aligned with index.html :root + theme.js) ───────────

export const cssVars = Object.freeze({
  color: Object.freeze({
    bg: 'var(--bg)',
    surface: 'var(--surface)',
    surfaceInset: 'var(--surface-inset)',
    border: 'var(--border)',
    text: 'var(--text)',
    textBright: 'var(--text-bright)',
    textMuted: 'var(--text-muted)',
    textInactive: 'var(--text-inactive)',
    accent: 'var(--accent)',
    green: 'var(--green)',
    red: 'var(--red)',
    yellow: 'var(--yellow)',
    orange: 'var(--orange)',
    purple: 'var(--purple)',
    cyan: 'var(--cyan)',
    pink: 'var(--pink)',
    btnGreen: 'var(--btn-green)',
    btnRed: 'var(--btn-red)',
    white: 'var(--white)',
    codeText: 'var(--code-text)',
  }),
  space: Object.freeze({
    xs: 'var(--space-xs)',
    sm: 'var(--space-sm)',
    md: 'var(--space-md)',
    lg: 'var(--space-lg)',
    xl: 'var(--space-xl)',
  }),
  radius: Object.freeze({
    sm: 'var(--radius-sm)',
    md: 'var(--radius-md)',
    lg: 'var(--radius-lg)',
    xl: 'var(--radius-xl)',
    pill: 'var(--radius-pill)',
  }),
  shadow: Object.freeze({
    sm: 'var(--shadow-sm)',
    md: 'var(--shadow-md)',
    lg: 'var(--shadow-lg)',
  }),
})

// The default resolved bundle (dark-first). Importing `tokens` gives dark values.
export const tokens = resolveTokens(DEFAULT_MODE)

export default tokens
