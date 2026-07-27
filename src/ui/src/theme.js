/**
 * Theme constants — CSS variable references for inline styles.
 * Actual color values are defined as :root custom properties in index.html.
 *
 * The scale references at the bottom (radius/shadow/space) and the light-mode
 * color overrides are formalised in src/styles/tokens.js (epic 10556, Task 11).
 * These entries are ADDITIVE — every existing color key above them is unchanged,
 * so current consumers keep resolving the same `var(--…)` values.
 */
export const theme = {
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
  triageGreen: 'var(--triage-green)',
  cyan: 'var(--cyan)',
  pink: 'var(--pink)',

  btnGreen: 'var(--btn-green)',
  btnRed: 'var(--btn-red)',
  white: 'var(--white)',

  codeText: 'var(--code-text)',

  accentHover: 'var(--accent-hover)',
  accentSubtle: 'var(--accent-subtle)',
  mutedSubtle: 'var(--muted-subtle)',
  purpleSubtle: 'var(--purple-subtle)',
  yellowSubtle: 'var(--yellow-subtle)',
  orangeSubtle: 'var(--orange-subtle)',
  greenSubtle: 'var(--green-subtle)',
  redSubtle: 'var(--red-subtle)',
  cyanSubtle: 'var(--cyan-subtle)',
  pinkSubtle: 'var(--pink-subtle)',
  overlay: 'var(--overlay)',
  intentBg: 'var(--intent-bg)',

  // Scale tokens — mirror the scales in src/styles/tokens.js and the CSS vars
  // added to :root in index.html (epic 10556, Task 11). Additive references so
  // inline-style consumers can pull spacing/radius/shadow from the same source
  // of truth as the token object.
  radiusSm: 'var(--radius-sm)',
  radiusMd: 'var(--radius-md)',
  radiusLg: 'var(--radius-lg)',
  radiusXl: 'var(--radius-xl)',
  radiusPill: 'var(--radius-pill)',
  shadowSm: 'var(--shadow-sm)',
  shadowMd: 'var(--shadow-md)',
  shadowLg: 'var(--shadow-lg)',
  spaceXs: 'var(--space-xs)',
  spaceSm: 'var(--space-sm)',
  spaceMd: 'var(--space-md)',
  spaceLg: 'var(--space-lg)',
  spaceXl: 'var(--space-xl)',
}
