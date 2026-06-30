"""Pure rendering + persistence for loop fitness (no cross-loop ranking)."""

from __future__ import annotations

from pathlib import Path

from config import HydraFlowConfig
from loop_fitness import LoopFitness
from metrics_manager import get_metrics_cache_dir


def render_fitness_markdown(results: list[LoopFitness]) -> str:
    """Render per-loop fitness. Sorted by worker_name — never by score."""
    lines = [
        "# Loop Fitness",
        "",
        "_Per-loop trend only — scores are NOT comparable across loops._",
        "",
    ]
    for fit in sorted(results, key=lambda r: r.worker_name):
        score = "n/a" if fit.score is None else f"{fit.score:.2f}"
        lines.append(f"## {fit.worker_name}")
        lines.append("")
        lines.append(f"- kind: `{fit.kind.value}`")
        lines.append(f"- score: {score}")
        lines.append(f"- confidence: `{fit.confidence.value}`")
        lines.append(f"- samples: {fit.sample_count}")
        if fit.components:
            comp = ", ".join(f"{k}={v:g}" for k, v in sorted(fit.components.items()))
            lines.append(f"- components: {comp}")
        if fit.notes:
            lines.append(f"- notes: {fit.notes}")
        lines.append("")
    return "\n".join(lines)


def save_fitness_snapshots(
    config: HydraFlowConfig, results: list[LoopFitness]
) -> Path:
    """Append each fitness row to ``<metrics_cache_dir>/fitness.jsonl``."""
    from file_util import append_jsonl, file_lock  # noqa: PLC0415

    cache_dir = get_metrics_cache_dir(config)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / "fitness.jsonl"
    with file_lock(path):
        for fit in results:
            append_jsonl(path, fit.model_dump_json())
    return path
