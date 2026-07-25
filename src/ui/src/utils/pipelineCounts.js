// countRegion / countPipeline turn StreamView's {stage, issues} groups into
// per-region and per-pipeline issue/PR counts for the pipeline flow region
// header numbers (#10488).

/**
 * Count issues and non-null PRs in a single stage group.
 *
 * @param {{stage: any, issues?: Array<{pr: any}>}} group
 * @returns {{issues: number, prs: number}}
 */
export function countRegion(group) {
  const issues = group?.issues || []
  return {
    issues: issues.length,
    prs: issues.filter(issue => issue.pr != null).length,
  }
}

/**
 * Sum per-stage counts (keyed by stage.key) and a grand total across all
 * stage groups.
 *
 * @param {Array<{stage: {key: string}, issues?: Array<{pr: any}>}>} stageGroups
 * @returns {{perStage: Record<string, {issues: number, prs: number}>, total: {issues: number, prs: number}}}
 */
export function countPipeline(stageGroups) {
  const perStage = {}
  const total = { issues: 0, prs: 0 }

  for (const group of stageGroups || []) {
    const counts = countRegion(group)
    perStage[group.stage.key] = counts
    total.issues += counts.issues
    total.prs += counts.prs
  }

  return { perStage, total }
}
