import React from 'react'
import { Badge, Card, Text, useTokens } from '../../styles/primitives'
import { EMPTY_GATEWAY_COVERAGE } from './gatewayCoverageModel'

function usd(value) {
  return `$${Number(value || 0).toFixed(4)}`
}

export function GatewayCoverageGauge({
  coverage = EMPTY_GATEWAY_COVERAGE,
  loading = false,
  error = null,
}) {
  const tokens = useTokens()
  const percent = coverage.displayPercent
  const hasMeter = percent != null
  const bypassNames = coverage.bypassingFamilies.map((row) => row.family)

  return (
    <Card
      as="section"
      data-testid="gateway-coverage-gauge"
      aria-label="Gateway spend coverage"
      style={styles.card(tokens)}
    >
      <div style={styles.header}>
        <div>
          <Text as="h3" size="md" weight="semibold" uppercase>
            Gateway coverage
          </Text>
          <Text as="div" size="xs" tone="muted">
            {coverage.scopeLabel} · {coverage.windowLabel}
          </Text>
        </div>
        <Badge tone={error ? 'danger' : coverage.tone}>
          {error ? 'Unavailable' : loading ? 'Loading' : coverage.statusLabel}
        </Badge>
      </div>

      {error ? (
        <Text role="alert" tone="danger">Coverage data could not be loaded.</Text>
      ) : loading ? (
        <Text role="status" tone="muted">Loading gateway coverage…</Text>
      ) : (
        <>
          <div
            role={hasMeter ? 'meter' : 'status'}
            aria-label="LLM spend through gateway"
            aria-valuemin={hasMeter ? 0 : undefined}
            aria-valuemax={hasMeter ? 100 : undefined}
            aria-valuenow={hasMeter ? percent : undefined}
            aria-valuetext={coverage.meterLabel}
            style={styles.meterWrap}
          >
            <Text size="xxl" weight="bold" data-testid="gateway-coverage-value">
              {coverage.valueLabel}
            </Text>
            <div aria-hidden="true" style={styles.track(tokens)}>
              <div style={styles.fill(tokens, percent || 0)} />
            </div>
          </div>

          <Text size="xs" tone="muted">
            {usd(coverage.gatewaySpendUsd)} gateway / {usd(coverage.knownTotalSpendUsd)} known spend
            {' · '}{coverage.gatewayRequests} gateway requests
            {' · '}{coverage.bypassRequests} direct provider requests
          </Text>

          {coverage.regressionDetected ? (
            <Text role="alert" tone="danger">
              {coverage.bypassRequests > 0
                ? 'Direct-provider traffic reappeared after gateway coverage reached 100%.'
                : 'Gateway coverage evidence became incomplete after coverage reached 100%.'}
            </Text>
          ) : null}

          {coverage.unknownRequests > 0 ? (
            <Text size="xs" tone="warning">
              {coverage.unknownRequests} request{coverage.unknownRequests === 1 ? '' : 's'} unpriced; no total coverage claim.
            </Text>
          ) : null}

          <div data-testid="gateway-bypass-families" style={styles.bypassRow}>
            <Text size="xs" tone="muted">Bypassing families:</Text>
            {bypassNames.length === 0 ? (
              <Text size="xs" tone="success">none observed</Text>
            ) : bypassNames.map((name) => (
              <Badge key={name} tone="warning">{name}</Badge>
            ))}
          </div>
        </>
      )}
    </Card>
  )
}

const styles = {
  card: (tokens) => ({
    display: 'flex',
    flexDirection: 'column',
    gap: tokens.space.sm,
  }),
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 12,
  },
  meterWrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  track: (tokens) => ({
    height: 10,
    borderRadius: tokens.radius.pill,
    backgroundColor: tokens.color.surfaceInset,
    overflow: 'hidden',
  }),
  fill: (tokens, percent) => ({
    width: `${Math.max(0, Math.min(100, percent))}%`,
    height: '100%',
    borderRadius: tokens.radius.pill,
    backgroundColor: tokens.color.cyan,
  }),
  bypassRow: {
    display: 'flex',
    flexWrap: 'wrap',
    alignItems: 'center',
    gap: 6,
  },
}
