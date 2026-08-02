/**
 * CostPanel — the operator console's cost/tokens readout (#10785).
 *
 * Pure presentational component. Consumes the `toCostByRepo(...)` view model
 * (repo + per-repo cost-per-model over a rolling 24h window) and renders, in the
 * vitals column:
 *
 *   - a header: "Cost / model", the window label ("last 24h"), and the total
 *     spend across every model (rendered "unknown" when any model is unpriced);
 *   - the cross-repo aggregate — one row per model, spend-descending, each with
 *     its token count and cost;
 *   - on a multi-repo install, a per-repo breakdown beneath it (each repo's own
 *     cost-per-model list), so the operator sees BOTH the fleet total and where
 *     the spend lands.
 *
 * Load-bearing contracts the tests pin:
 *   - an unpriced model renders "unknown", never "$0.00" (#9821);
 *   - an empty / failed feed renders a calm empty state, never a crash;
 *   - every colour / space value resolves from the token layer via `useTokens()`
 *     — no inline `style={{…}}` literal, no hardcoded hex — so light + dark fall
 *     out of the console's ThemeProvider (inline-style + colour ratchets).
 */

import React from 'react'
import { useTokens, Text, Badge } from '../styles/primitives'
import { EMPTY_COST_VM } from './model/cost'
import { formatUsd, formatTokens } from '../utils/costFormat'

function makeStyles(t) {
  return {
    card: {
      display: 'flex',
      flexDirection: 'column',
      gap: t.space.xs,
      padding: t.space.sm,
      boxSizing: 'border-box',
    },
    header: { display: 'flex', alignItems: 'baseline', gap: t.space.sm },
    spacer: { flex: '1 1 auto' },
    total: { textAlign: 'right', minWidth: 0 },
    empty: { padding: `${t.space.xs}px 0` },
    row: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      padding: `${t.space.xxs}px ${t.space.xs}px`,
    },
    name: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: '1 1 auto' },
    tokens: { flexShrink: 0 },
    cost: { flexShrink: 0, textAlign: 'right' },
    reposWrap: { display: 'flex', flexDirection: 'column', gap: t.space.xs, marginTop: t.space.xs },
    repoHeader: {
      display: 'flex',
      alignItems: 'baseline',
      gap: t.space.sm,
      paddingTop: t.space.xs,
      borderTop: `1px solid ${t.color.border}`,
    },
    repoTotal: { flexShrink: 0, textAlign: 'right' },
  }
}

/** One model row: name · token count · cost (cost tone flips on "unknown"). */
function ModelRow({ row, styles, testid }) {
  return (
    <div data-testid={testid} style={styles.row}>
      <Text size="sm" style={styles.name}>{row.model}</Text>
      <Text as="span" size="xs" tone="muted" style={styles.tokens}>
        {formatTokens(row.tokensIn + row.tokensOut)}
      </Text>
      <Text
        as="span"
        size="sm"
        weight="semibold"
        tone={row.costUnknown ? 'warning' : 'default'}
        style={styles.cost}
      >
        {formatUsd(row.costUsd, { unknown: row.costUnknown })}
      </Text>
    </div>
  )
}

/** One repo's section: a slug + repo total header, then its cost-per-model rows. */
function RepoSection({ repo, styles }) {
  return (
    <div data-testid={`cost-repo-${repo.repo}`}>
      <div style={styles.repoHeader}>
        <Text size="xs" weight="semibold" tone="muted" style={styles.name}>{repo.repo}</Text>
        <Text as="span" size="xs" weight="semibold" style={styles.repoTotal}>
          {formatUsd(repo.totalCostUsd)}
        </Text>
      </div>
      {repo.byModel.map(row => (
        <ModelRow
          key={`${repo.repo}:${row.model}`}
          row={row}
          styles={styles}
          testid={`cost-repo-${repo.repo}-model-${row.model}`}
        />
      ))}
    </div>
  )
}

/**
 * @param {{ cost?: ReturnType<typeof import('./model/cost').toCostByRepo> }} props
 */
export function CostPanel({ cost = EMPTY_COST_VM }) {
  const t = useTokens()
  const styles = makeStyles(t)
  const { windowLabel, totalCostUsd, totalCostUnknown, all, repos } = cost

  return (
    <div data-testid="cost-panel" style={styles.card}>
      <div style={styles.header}>
        <Text size="xs" weight="semibold" tone="muted" uppercase>Cost / model</Text>
        <Badge tone="neutral">{windowLabel}</Badge>
        <span style={styles.spacer} />
        <Text
          as="span"
          size="sm"
          weight="semibold"
          tone={totalCostUnknown ? 'warning' : 'default'}
          style={styles.total}
          data-testid="cost-total"
        >
          {formatUsd(totalCostUsd, { unknown: totalCostUnknown })}
        </Text>
      </div>

      {all.length === 0 ? (
        <Text size="sm" tone="muted" style={styles.empty} data-testid="cost-empty">
          no spend recorded ({windowLabel})
        </Text>
      ) : (
        <>
          {all.map(row => (
            <ModelRow
              key={row.model}
              row={row}
              styles={styles}
              testid={`cost-model-${row.model}`}
            />
          ))}
          {repos.length > 1 && (
            <div style={styles.reposWrap} data-testid="cost-repos">
              {repos.map(repo => (
                <RepoSection key={repo.repo} repo={repo} styles={styles} />
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}

export default CostPanel
