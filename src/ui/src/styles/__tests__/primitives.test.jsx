import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import fs from 'node:fs'
import path from 'node:path'
import { resolveTokens, palettes, space, radius, type, DEFAULT_MODE } from '../tokens'
import {
  Surface,
  Card,
  Text,
  Stack,
  Badge,
  Button,
  ThemeProvider,
  useTokens,
} from '../primitives'
import { renderHook } from '@testing-library/react'

// Operator-console token + primitive layer (epic 10556, Phase 2, Task 11).
//
// The contract these tests pin: primitives resolve every colour/space/radius/
// shadow value from the token object, never from an inline literal, so that
// flipping the theme mode flips what the primitive renders. We prove this two
// ways: (1) a structural scan that primitives.jsx contains no hard-coded colour
// literal, and (2) render assertions that a primitive's rendered style equals
// the resolved token for its mode and differs between light and dark.

// jsdom (cssstyle) normalises colour values when they are assigned to a style
// property. Route both the token value and the rendered value through the same
// normaliser so an exact-match assertion is robust to that serialisation.
function cssColor(value) {
  const el = document.createElement('div')
  el.style.color = value
  return el.style.color
}

describe('tokens — light + dark palettes resolve to different values', () => {
  it('defaults to dark (dark-first) and exposes the dark palette', () => {
    const t = resolveTokens()
    expect(t.mode).toBe('dark')
    expect(DEFAULT_MODE).toBe('dark')
    expect(t.color).toBe(palettes.dark)
  })

  it('flips every load-bearing semantic colour between dark and light', () => {
    const dark = resolveTokens('dark')
    const light = resolveTokens('light')
    for (const key of ['bg', 'surface', 'surfaceInset', 'border', 'text', 'textMuted', 'accent', 'green', 'red']) {
      expect(dark.color[key]).toBeTruthy()
      expect(light.color[key]).toBeTruthy()
      expect(dark.color[key]).not.toBe(light.color[key])
    }
  })

  it('shares theme-independent scales (space / radius / type) across modes', () => {
    const dark = resolveTokens('dark')
    const light = resolveTokens('light')
    expect(dark.space).toBe(space)
    expect(dark.radius).toBe(radius)
    expect(dark.type).toBe(type)
    expect(light.space).toBe(space)
    expect(light.radius).toBe(radius)
    expect(light.type).toBe(type)
  })

  it('gives dark and light distinct shadow tokens', () => {
    expect(resolveTokens('dark').shadow.md).not.toBe(resolveTokens('light').shadow.md)
  })

  it('falls back to dark for an unknown mode', () => {
    expect(resolveTokens('carbon').mode).toBe('dark')
    expect(resolveTokens(undefined).mode).toBe('dark')
  })
})

describe('primitives consume ONLY tokens — no hard-coded colour literals', () => {
  it('primitives.jsx source has no hex / rgb / hsl colour literal', () => {
    // vitest runs with cwd = src/ui (see scripts/run-vitest.cjs).
    const src = fs.readFileSync(path.resolve(process.cwd(), 'src/styles/primitives.jsx'), 'utf8')
    expect(src).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
    expect(src).not.toMatch(/\b(?:rgba?|hsla?)\s*\(/)
  })
})

describe('primitives render token-driven styles that flip with the theme mode', () => {
  it('Surface background reads from the token and flips dark ↔ light', () => {
    const { container: dark } = render(<Surface mode="dark">x</Surface>)
    const { container: light } = render(<Surface mode="light">x</Surface>)
    const darkBg = dark.firstChild.style.backgroundColor
    const lightBg = light.firstChild.style.backgroundColor
    expect(darkBg).toBe(cssColor(resolveTokens('dark').color.surface))
    expect(lightBg).toBe(cssColor(resolveTokens('light').color.surface))
    expect(darkBg).not.toBe(lightBg)
  })

  it('Surface tone selects the right token (base / raised / inset)', () => {
    const { container: base } = render(<Surface tone="base" mode="dark">x</Surface>)
    const { container: inset } = render(<Surface tone="inset" mode="dark">x</Surface>)
    const t = resolveTokens('dark')
    expect(base.firstChild.style.backgroundColor).toBe(cssColor(t.color.bg))
    expect(inset.firstChild.style.backgroundColor).toBe(cssColor(t.color.surfaceInset))
  })

  it('Text colour reads from the token and flips with the mode', () => {
    const { container: dark } = render(<Text mode="dark">hi</Text>)
    const { container: light } = render(<Text mode="light">hi</Text>)
    expect(dark.firstChild.style.color).toBe(cssColor(resolveTokens('dark').color.text))
    expect(light.firstChild.style.color).toBe(cssColor(resolveTokens('light').color.text))
    expect(dark.firstChild.style.color).not.toBe(light.firstChild.style.color)
  })

  it('Text pulls size + weight from the type scale', () => {
    const { container } = render(<Text mode="dark" size="lg" weight="semibold">hi</Text>)
    const t = resolveTokens('dark')
    expect(container.firstChild.style.fontSize).toBe(`${t.type.size.lg}px`)
    expect(container.firstChild.style.fontWeight).toBe(String(t.type.weight.semibold))
  })

  it('Card uses token radius + shadow + surface, not literals', () => {
    const { container } = render(<Card mode="dark">c</Card>)
    const el = container.firstChild
    const t = resolveTokens('dark')
    expect(el.style.backgroundColor).toBe(cssColor(t.color.surface))
    expect(el.style.borderRadius).toBe(`${t.radius.lg}px`)
    expect(el.style.boxShadow).not.toBe('')
    expect(el.style.padding).toBe(`${t.space.lg}px`)
  })

  it('Stack lays out flex with token spacing for its gap', () => {
    const { container } = render(<Stack mode="dark" gap="lg" direction="row">a</Stack>)
    const el = container.firstChild
    expect(el.style.display).toBe('flex')
    expect(el.style.flexDirection).toBe('row')
    expect(el.style.gap).toBe(`${resolveTokens('dark').space.lg}px`)
  })

  it('Badge tone maps to a token colour and flips with the mode', () => {
    const { container: dark } = render(<Badge tone="success" mode="dark">ok</Badge>)
    const { container: light } = render(<Badge tone="success" mode="light">ok</Badge>)
    expect(dark.firstChild.style.color).toBe(cssColor(resolveTokens('dark').color.green))
    expect(light.firstChild.style.color).toBe(cssColor(resolveTokens('light').color.green))
    expect(dark.firstChild.style.color).not.toBe(light.firstChild.style.color)
  })

  it('Button variant pulls its background from a token and fires onClick', () => {
    let clicks = 0
    const { container } = render(
      <Button mode="dark" variant="primary" onClick={() => { clicks += 1 }}>go</Button>,
    )
    const btn = container.firstChild
    expect(btn.tagName).toBe('BUTTON')
    expect(btn.style.backgroundColor).toBe(cssColor(resolveTokens('dark').color.accent))
    btn.click()
    expect(clicks).toBe(1)
  })
})

describe('ThemeProvider / useTokens supply the mode without prop-drilling', () => {
  it('a per-primitive mode prop overrides the provider mode', () => {
    const { container } = render(
      <ThemeProvider mode="light">
        <Card>c</Card>
        <Card mode="dark">d</Card>
      </ThemeProvider>,
    )
    const [lightCard, darkCard] = container.querySelectorAll('[data-primitive="card"]')
    expect(lightCard.style.backgroundColor).toBe(cssColor(resolveTokens('light').color.surface))
    expect(darkCard.style.backgroundColor).toBe(cssColor(resolveTokens('dark').color.surface))
  })

  it('useTokens defaults to dark and follows the provider mode', () => {
    const bare = renderHook(() => useTokens())
    expect(bare.result.current.mode).toBe('dark')

    const wrapped = renderHook(() => useTokens(), {
      wrapper: ({ children }) => <ThemeProvider mode="light">{children}</ThemeProvider>,
    })
    expect(wrapped.result.current.mode).toBe('light')
  })
})
