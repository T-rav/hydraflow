/**
 * SettingsSummary — the operator console's "settings at-a-glance" strip
 * (epic #10556 follow-up).
 *
 * Pure presentational component. Consumes the `toSettingsSummary(...)` view
 * model and renders the KEY runtime settings (model, worker/planner/reviewer
 * pools, batch size, queue strategy, merge policy) as compact labelled chips,
 * plus a gear/"Settings" affordance that opens the FULL classic System-tab
 * configuration in a drawer (SettingsDrawer) via `onOpenSettings`.
 *
 * Presentation only: no socket, no side effects. Every colour / space value
 * resolves from `useTokens()` (no hardcoded literals), so light + dark fall out
 * of the console's ThemeProvider mode. The `data-testid`s the tests pin are
 * `settings-summary`, `settings-open` (the gear button) and
 * `settings-item-<key>` (one per chip).
 */

import React from 'react'
import { useTokens, Card, Text } from '../styles/primitives'

function makeStyles(t) {
  return {
    panel: { display: 'flex', flexDirection: 'column', minWidth: 0, padding: 0, overflow: 'hidden' },
    header: {
      display: 'flex',
      alignItems: 'center',
      gap: t.space.sm,
      padding: `${t.space.xs}px ${t.space.sm}px`,
      borderBottom: `1px solid ${t.color.border}`,
    },
    spacer: { flex: '1 1 auto' },
    gear: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: t.space.xs,
      flexShrink: 0,
      border: `1px solid ${t.color.border}`,
      borderRadius: t.radius.md,
      background: t.color.surfaceInset,
      color: t.color.text,
      cursor: 'pointer',
      padding: `${t.space.xxs}px ${t.space.sm}px`,
      font: 'inherit',
      fontSize: t.type.size.xs,
      fontWeight: t.type.weight.semibold,
    },
    gearIcon: { fontSize: t.type.size.sm, lineHeight: 1 },
    items: {
      display: 'flex',
      flexWrap: 'wrap',
      gap: t.space.xs,
      padding: `${t.space.sm}px`,
    },
    item: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xxs,
      minWidth: 0,
      maxWidth: '100%',
      border: `1px solid ${t.color.border}`,
      borderRadius: t.radius.md,
      background: t.color.surfaceInset,
      padding: `${t.space.xxs}px ${t.space.sm}px`,
    },
    itemLabel: { whiteSpace: 'nowrap' },
    itemValue: {
      minWidth: 0,
      maxWidth: 220,
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap',
    },
  }
}

/**
 * @param {{
 *   summary?: { items?: Array<{ key: string, label: string, value: string }> },
 *   onOpenSettings?: () => void,
 * }} props
 */
export function SettingsSummary({ summary, onOpenSettings }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const items = summary?.items ?? []

  return (
    <Card as="section" data-testid="settings-summary" style={styles.panel} aria-label="Runtime settings">
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Settings</Text>
        <span style={styles.spacer} />
        <button
          type="button"
          data-testid="settings-open"
          onClick={() => onOpenSettings?.()}
          style={styles.gear}
          aria-label="Open system settings"
          title="Open the full system configuration"
        >
          <span style={styles.gearIcon} aria-hidden="true">⚙</span>
          <span>Settings</span>
        </button>
      </div>
      <div style={styles.items}>
        {items.map(item => (
          <div key={item.key} data-testid={`settings-item-${item.key}`} style={styles.item}>
            <Text as="span" size="xs" tone="muted" style={styles.itemLabel}>{item.label}</Text>
            <Text as="span" size="sm" style={styles.itemValue} title={String(item.value)}>
              {item.value}
            </Text>
          </div>
        ))}
      </div>
    </Card>
  )
}

export default SettingsSummary
