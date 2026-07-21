"""Model pricing loader — reads per-model token costs from a managed JSON asset."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("hydraflow.model_pricing")

_ASSET_PATH = Path(__file__).parent / "assets" / "model_pricing.json"

_REQUIRED_COST_FIELDS = frozenset({"input_cost_per_million", "output_cost_per_million"})

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _next_token(text: str) -> str | None:
    """Return the first alphanumeric token in *text*, or None if there is none."""
    match = _TOKEN_RE.search(text)
    return match.group(0) if match else None


def _token_aligned_match(candidate: str, model: str) -> bool:
    """True if *candidate* occurs in *model* aligned on token boundaries.

    A match is rejected when the token immediately following it is purely
    numeric: for pricing ids that means *model* is a newer/different version
    of the candidate's family (``claude-opus-4`` vs ``claude-opus-4-9``), and
    it must not inherit the candidate's — potentially stale — price (#9466).
    Non-numeric residual tokens (variant tags like ``-extended``) are allowed.
    """
    start = model.find(candidate)
    while start != -1:
        end = start + len(candidate)
        starts_on_boundary = start == 0 or not model[start - 1].isalnum()
        ends_on_boundary = end == len(model) or not model[end].isalnum()
        if starts_on_boundary and ends_on_boundary:
            trailing = _next_token(model[end:])
            if trailing is None or not trailing.isdigit():
                return True
        start = model.find(candidate, start + 1)
    return False


@dataclass(frozen=True, slots=True)
class ModelRate:
    """Per-model token pricing rates (USD per million tokens)."""

    input_cost_per_million: float
    output_cost_per_million: float
    cache_write_cost_per_million: float
    cache_read_cost_per_million: float

    def estimate_cost(
        self,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float:
        """Return estimated cost in USD for the given token counts."""
        return (
            self.input_cost_per_million * input_tokens
            + self.output_cost_per_million * output_tokens
            + self.cache_write_cost_per_million * cache_write_tokens
            + self.cache_read_cost_per_million * cache_read_tokens
        ) / 1_000_000


class ModelPricingTable:
    """Loads and resolves model pricing from the managed JSON asset."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or _ASSET_PATH
        self._rates: dict[str, ModelRate] = {}
        self._aliases: dict[str, str] = {}
        # (candidate, canonical id) pairs eligible for the gated fuzzy
        # fallback, longest candidate first (#9466).
        self._fuzzy_candidates: list[tuple[str, str]] = []
        self._fuzzy_logged: set[str] = set()
        self._unknown_warned: set[str] = set()
        self._loaded = False

    def _load(self) -> None:
        """Parse the pricing JSON and build lookup tables."""
        if self._loaded:
            return
        self._loaded = True
        if not self._path.is_file():
            logger.warning("Model pricing asset not found: %s", self._path)
            return
        try:
            raw = json.loads(self._path.read_text())
        except (json.JSONDecodeError, OSError):
            logger.warning(
                "Failed to load model pricing from %s", self._path, exc_info=True
            )
            return
        if not isinstance(raw, dict):
            return
        models = raw.get("models", {})
        if not isinstance(models, dict):
            return
        for model_id, entry in models.items():
            if not isinstance(entry, dict):
                continue
            if not _REQUIRED_COST_FIELDS.issubset(entry):
                logger.warning(
                    "Skipping model %r — missing required cost fields", model_id
                )
                continue
            rate = ModelRate(
                input_cost_per_million=float(entry["input_cost_per_million"]),
                output_cost_per_million=float(entry["output_cost_per_million"]),
                cache_write_cost_per_million=float(
                    entry.get("cache_write_cost_per_million", 0.0)
                ),
                cache_read_cost_per_million=float(
                    entry.get("cache_read_cost_per_million", 0.0)
                ),
            )
            self._rates[model_id] = rate
            for alias in entry.get("aliases", []):
                if isinstance(alias, str):
                    self._aliases[alias.lower()] = model_id
        self._build_fuzzy_candidates()

    def _build_fuzzy_candidates(self) -> None:
        """Precompute fuzzy-eligible (candidate, canonical id) pairs (#9466).

        Only multi-token candidates (containing a delimiter) are eligible:
        bare tier aliases like ``opus``/``sonnet``/``haiku`` are substrings of
        essentially every Claude id and must never fuzzy-match. Longest
        candidate first, so the most specific entry wins.
        """
        pairs = [(model_id.lower(), model_id) for model_id in self._rates]
        pairs.extend(self._aliases.items())
        self._fuzzy_candidates = sorted(
            (
                (candidate, canonical)
                for candidate, canonical in pairs
                if any(not ch.isalnum() for ch in candidate)
            ),
            key=lambda pair: len(pair[0]),
            reverse=True,
        )

    def get_rate(self, model: str) -> ModelRate | None:
        """Look up pricing for *model*: exact ID, then alias, then a gated
        token-aligned fuzzy fallback.

        Unknown models return ``None`` (surfacing as cost-unknown per #9821,
        never $0) and log a one-time warning rather than silently inheriting
        a stale same-tier price (#9466).
        """
        self._load()
        model_l = model.lower().strip()
        if model_l in self._rates:
            return self._rates[model_l]
        canonical = self._aliases.get(model_l)
        if canonical:
            return self._rates.get(canonical)
        rate = self._fuzzy_rate(model_l)
        if rate is None and model_l not in self._unknown_warned:
            self._unknown_warned.add(model_l)
            logger.warning(
                "No pricing entry for model %r — cost will surface as unknown; "
                "add it to %s (#9466)",
                model_l,
                self._path,
            )
        return rate

    def _fuzzy_rate(self, model_l: str) -> ModelRate | None:
        """Gated fuzzy fallback (#9466): resolve *model_l* via the most
        specific multi-token candidate that matches on token boundaries with
        no numeric version residual. Logs a one-time signal per model when it
        fires, so silent fuzzy resolutions are observable."""
        for candidate, canonical in self._fuzzy_candidates:
            if not _token_aligned_match(candidate, model_l):
                continue
            rate = self._rates.get(canonical)
            if rate is None:
                continue
            if model_l not in self._fuzzy_logged:
                self._fuzzy_logged.add(model_l)
                logger.info(
                    "Pricing fuzzy fallback: resolved %r via token-aligned "
                    "match on %r -> %r (#9466)",
                    model_l,
                    candidate,
                    canonical,
                )
            return rate
        return None

    def estimate_cost(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        cache_write_tokens: int = 0,
        cache_read_tokens: int = 0,
    ) -> float | None:
        """Return estimated cost in USD, or None if model is unknown."""
        rate = self.get_rate(model)
        if rate is None:
            return None
        return rate.estimate_cost(
            input_tokens, output_tokens, cache_write_tokens, cache_read_tokens
        )


def load_pricing(path: Path | None = None) -> ModelPricingTable:
    """Load the model pricing table from the default or given path."""
    return ModelPricingTable(path)
