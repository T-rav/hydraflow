import { PIPELINE_STAGES } from '../constants'
import { borderSides } from './borders'

export const WORKSTREAM_SIDE_INSET_PX = 8

const sectionHeaderBase = {
  display: 'flex',
  alignItems: 'center',
  gap: 8,
  padding: '8px 12px',
  margin: `8px ${WORKSTREAM_SIDE_INSET_PX}px 4px`,
  cursor: 'pointer',
  userSelect: 'none',
  borderRadius: 6,
  transition: 'background 0.15s',
}

export const sectionLabelBase = {
  fontSize: 11,
  fontWeight: 600,
  textTransform: 'uppercase',
  letterSpacing: '0.5px',
}

const sectionCountBase = {
  fontSize: 11,
  fontWeight: 600,
  marginLeft: 'auto',
}

const subtleBorder = (color) => `color-mix(in srgb, ${color} 20%, transparent)`

export const sectionHeaderStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...sectionHeaderBase,
    background: s.subtleColor,
    // Box border with a thicker left accent, expressed per-side so the object
    // never mixes the `border` shorthand with a longhand (#10583).
    ...borderSides({ fallback: `1px solid ${subtleBorder(s.color)}`, left: `3px solid ${s.color}` }),
  }])
)

export const sectionLabelStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...sectionLabelBase,
    color: s.color,
  }])
)

export const sectionCountStyles = Object.fromEntries(
  PIPELINE_STAGES.map(s => [s.key, {
    ...sectionCountBase,
    color: s.color,
  }])
)
