/**
 * Primitive components for the operator console (epic 10556, Phase 2, Task 11).
 *
 * Every colour / space / radius / shadow value these primitives render is
 * pulled from the resolved token bundle (see `tokens.js`) — there is NO
 * hard-coded colour literal in this file. That is the load-bearing contract:
 * because everything routes through tokens, switching the theme mode flips what
 * the primitive renders, and the light path works without touching this file.
 *
 * Mode resolution is dark-first. A primitive reads its mode from (in priority
 * order) an explicit `mode` prop, then the surrounding `ThemeProvider`, then the
 * default (`dark`). This lets Task-12 migrations opt individual subtrees into a
 * mode without prop-drilling, while tests can pin an exact mode per render.
 *
 * These are the building blocks migrated components consume in Task 12; nothing
 * in the current app imports them yet.
 */

import React from 'react'
import { resolveTokens, DEFAULT_MODE } from './tokens'

const ThemeContext = React.createContext(DEFAULT_MODE)

/** Supplies a theme mode to descendant primitives (dark-first by default). */
export function ThemeProvider({ mode = DEFAULT_MODE, children }) {
  return <ThemeContext.Provider value={mode}>{children}</ThemeContext.Provider>
}

/**
 * Resolve the token bundle a primitive should use: an explicit `mode` wins,
 * otherwise the provider mode, otherwise the dark-first default.
 */
export function useTokens(mode) {
  const contextMode = React.useContext(ThemeContext)
  return resolveTokens(mode ?? contextMode)
}

// A subtle fill derived from a token colour — no literal colour involved, so the
// fill flips with the mode alongside the colour it is derived from.
function subtleFill(color, pct = 15) {
  return `color-mix(in srgb, ${color} ${pct}%, transparent)`
}

// ── Surface ──────────────────────────────────────────────────────────────────

const SURFACE_TONE = {
  base: (c) => c.bg,
  raised: (c) => c.surface,
  inset: (c) => c.surfaceInset,
}

/**
 * A themed background region. `tone` selects which background token to use.
 */
export function Surface({ tone = 'raised', mode, as: As = 'div', style, children, ...rest }) {
  const t = useTokens(mode)
  const pick = SURFACE_TONE[tone] ?? SURFACE_TONE.raised
  return (
    <As
      data-primitive="surface"
      style={{ backgroundColor: pick(t.color), color: t.color.text, ...style }}
      {...rest}
    >
      {children}
    </As>
  )
}

// ── Card ───────────────────────────────────────────────────────────────────

/** A raised surface with a token border, radius, shadow and padding. */
export function Card({ mode, as: As = 'div', padded = true, style, children, ...rest }) {
  const t = useTokens(mode)
  return (
    <As
      data-primitive="card"
      style={{
        backgroundColor: t.color.surface,
        color: t.color.text,
        border: `1px solid ${t.color.border}`,
        borderRadius: t.radius.lg,
        boxShadow: t.shadow.sm,
        padding: padded ? t.space.lg : 0,
        ...style,
      }}
      {...rest}
    >
      {children}
    </As>
  )
}

// ── Text ─────────────────────────────────────────────────────────────────────

const TEXT_TONE = {
  default: (c) => c.text,
  bright: (c) => c.textBright,
  muted: (c) => c.textMuted,
  inactive: (c) => c.textInactive,
  accent: (c) => c.accent,
  success: (c) => c.green,
  danger: (c) => c.red,
  warning: (c) => c.yellow,
  code: (c) => c.codeText,
}

/** A typographic primitive driven by the `type` scale and a colour tone. */
export function Text({
  mode,
  as: As = 'span',
  size = 'sm',
  weight = 'regular',
  tone = 'default',
  uppercase = false,
  mono = true,
  style,
  children,
  ...rest
}) {
  const t = useTokens(mode)
  const tonePick = TEXT_TONE[tone] ?? TEXT_TONE.default
  return (
    <As
      data-primitive="text"
      style={{
        color: tonePick(t.color),
        fontSize: t.type.size[size] ?? t.type.size.sm,
        fontWeight: t.type.weight[weight] ?? t.type.weight.regular,
        fontFamily: mono ? t.type.family.mono : t.type.family.sans,
        lineHeight: t.type.leading.normal,
        textTransform: uppercase ? 'uppercase' : 'none',
        letterSpacing: uppercase ? t.type.tracking.wide : t.type.tracking.normal,
        ...style,
      }}
      {...rest}
    >
      {children}
    </As>
  )
}

// ── Stack ────────────────────────────────────────────────────────────────────

/** Flex layout with token-driven spacing. */
export function Stack({
  mode,
  as: As = 'div',
  direction = 'column',
  gap = 'md',
  align,
  justify,
  wrap = false,
  style,
  children,
  ...rest
}) {
  const t = useTokens(mode)
  return (
    <As
      data-primitive="stack"
      style={{
        display: 'flex',
        flexDirection: direction,
        gap: t.space[gap] ?? t.space.md,
        alignItems: align,
        justifyContent: justify,
        flexWrap: wrap ? 'wrap' : 'nowrap',
        ...style,
      }}
      {...rest}
    >
      {children}
    </As>
  )
}

// ── Badge ────────────────────────────────────────────────────────────────────

const BADGE_TONE = {
  neutral: (c) => c.textMuted,
  accent: (c) => c.accent,
  info: (c) => c.cyan,
  success: (c) => c.green,
  warning: (c) => c.yellow,
  danger: (c) => c.red,
}

/** A pill label whose text colour and subtle fill both come from one token. */
export function Badge({ mode, tone = 'neutral', style, children, ...rest }) {
  const t = useTokens(mode)
  const tonePick = BADGE_TONE[tone] ?? BADGE_TONE.neutral
  const color = tonePick(t.color)
  return (
    <span
      data-primitive="badge"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: t.space.xs,
        color,
        backgroundColor: subtleFill(color),
        borderRadius: t.radius.pill,
        padding: `${t.space.xxs}px ${t.space.sm}px`,
        fontSize: t.type.size.xs,
        fontWeight: t.type.weight.semibold,
        fontFamily: t.type.family.mono,
        lineHeight: t.type.leading.tight,
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  )
}

// ── Button ───────────────────────────────────────────────────────────────────

const BUTTON_VARIANT = {
  primary: (c) => ({ bg: c.accent, fg: c.white, border: c.accent }),
  success: (c) => ({ bg: c.btnGreen, fg: c.white, border: c.btnGreen }),
  danger: (c) => ({ bg: c.btnRed, fg: c.white, border: c.btnRed }),
  ghost: (c) => ({ bg: 'transparent', fg: c.text, border: c.border }),
}

/** A button whose colours come entirely from a token-backed variant. */
export function Button({
  mode,
  variant = 'primary',
  size = 'md',
  type = 'button',
  disabled = false,
  style,
  children,
  ...rest
}) {
  const t = useTokens(mode)
  const variantPick = BUTTON_VARIANT[variant] ?? BUTTON_VARIANT.primary
  const v = variantPick(t.color)
  const pad =
    size === 'sm'
      ? `${t.space.xs}px ${t.space.sm}px`
      : `${t.space.sm}px ${t.space.md}px`
  return (
    <button
      type={type}
      data-primitive="button"
      disabled={disabled}
      style={{
        backgroundColor: v.bg,
        color: v.fg,
        border: `1px solid ${v.border}`,
        borderRadius: t.radius.md,
        padding: pad,
        fontSize: t.type.size.sm,
        fontWeight: t.type.weight.semibold,
        fontFamily: t.type.family.mono,
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        ...style,
      }}
      {...rest}
    >
      {children}
    </button>
  )
}
