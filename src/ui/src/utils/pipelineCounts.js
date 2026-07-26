// countRegion / countPipeline turn StreamView's {stage, issues} groups into
// per-region and per-pipeline issue counts for the pipeline flow region
// header numbers (#10488; the PR count was dropped in #10593).

/**
 * Count issues in a single stage group.
 *
 * @param {{stage: any, issues?: Array<any>}} group
 * @returns {{issues: number}}
 */
export function countRegion(group) {
  const issues = group?.issues || []
  return {
    issues: issues.length,
  }
}

/**
 * Sum per-stage counts (keyed by stage.key) and a grand total across all
 * stage groups.
 *
 * @param {Array<{stage: {key: string}, issues?: Array<any>}>} stageGroups
 * @returns {{perStage: Record<string, {issues: number}>, total: {issues: number}}}
 */
export function countPipeline(stageGroups) {
  const perStage = {}
  const total = { issues: 0 }

  for (const group of stageGroups || []) {
    const counts = countRegion(group)
    perStage[group.stage.key] = counts
    total.issues += counts.issues
  }

  return { perStage, total }
}
