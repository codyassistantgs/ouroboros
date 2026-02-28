"""
Ouroboros — LLM pricing utilities.

Centralises model pricing data, alias mapping, and cost estimation.
Extracted from loop.py to keep loop.py under the 1000-line limit.
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional, Tuple

log = logging.getLogger(__name__)

# Pricing from OpenRouter API (2026-02-17). Update periodically via /api/v1/models.
# Tuple format: (input_$/M, cached_$/M, output_$/M)
MODEL_PRICING_STATIC: Dict[str, Tuple[float, float, float]] = {
    "anthropic/claude-opus-4.6": (5.0, 0.5, 25.0),
    "anthropic/claude-opus-4": (15.0, 1.5, 75.0),
    "anthropic/claude-sonnet-4": (3.0, 0.30, 15.0),
    "anthropic/claude-sonnet-4.6": (3.0, 0.30, 15.0),
    "anthropic/claude-sonnet-4.5": (3.0, 0.30, 15.0),
    "openai/o3": (2.0, 0.50, 8.0),
    "openai/o3-pro": (20.0, 1.0, 80.0),
    "openai/o4-mini": (1.10, 0.275, 4.40),
    "openai/gpt-4.1": (2.0, 0.50, 8.0),
    "openai/gpt-5.2": (1.75, 0.175, 14.0),
    "openai/gpt-5.2-codex": (1.75, 0.175, 14.0),
    "google/gemini-2.5-pro-preview": (1.25, 0.125, 10.0),
    "google/gemini-3-pro-preview": (2.0, 0.20, 12.0),
    "x-ai/grok-3-mini": (0.30, 0.03, 0.50),
    "qwen/qwen3.5-plus-02-15": (0.40, 0.04, 2.40),
}

# Map short proxy model names → canonical OpenRouter model IDs for pricing lookup.
# The proxy returns short names (e.g. "claude-sonnet-4-6") but pricing table uses
# full IDs (e.g. "anthropic/claude-sonnet-4.6"). Add aliases here when proxy adds models.
PROXY_MODEL_ALIASES: Dict[str, str] = {
    "claude-sonnet-4-6": "anthropic/claude-sonnet-4.6",
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4.6",
    "claude-opus-4-6": "anthropic/claude-opus-4.6",
    "claude-opus-4.6": "anthropic/claude-opus-4.6",
    "claude-haiku-4-5-20251001": "anthropic/claude-haiku-4-5-20251001",
    "gemini-2.5-pro": "google/gemini-2.5-pro-preview",
    "gemini-2.5-flash": "google/gemini-2.5-flash-preview",
    "gemini-3-pro-preview": "google/gemini-3-pro-preview",
}

_pricing_fetched = False
_cached_pricing: Optional[Dict[str, Tuple[float, float, float]]] = None
_pricing_lock = threading.Lock()


def get_pricing() -> Dict[str, Tuple[float, float, float]]:
    """
    Lazy-load pricing. On first call, attempts to fetch live data from OpenRouter API.
    Falls back to static pricing if fetch fails.
    Thread-safe via module-level lock.
    """
    global _pricing_fetched, _cached_pricing

    # Fast path: already fetched (read without lock for performance)
    if _pricing_fetched:
        return _cached_pricing or MODEL_PRICING_STATIC

    # Slow path: fetch pricing (lock required)
    with _pricing_lock:
        # Double-check after acquiring lock (another thread may have fetched first)
        if _pricing_fetched:
            return _cached_pricing or MODEL_PRICING_STATIC

        _pricing_fetched = True
        _cached_pricing = dict(MODEL_PRICING_STATIC)

        try:
            from ouroboros.llm import fetch_openrouter_pricing
            _live = fetch_openrouter_pricing()
            if _live and len(_live) > 5:
                _cached_pricing.update(_live)
        except Exception as e:
            log.warning("Failed to sync pricing from OpenRouter: %s", e)
            # Reset flag so we retry on the next call
            _pricing_fetched = False

        return _cached_pricing


def estimate_cost(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> float:
    """Estimate cost from token counts using known pricing. Returns 0.0 if model unknown."""
    model_pricing = get_pricing()
    # Normalize short proxy model names to canonical IDs
    normalized = PROXY_MODEL_ALIASES.get(model, model)
    # Try exact match first
    pricing = model_pricing.get(normalized)
    if not pricing and normalized != model:
        pricing = model_pricing.get(model)
    if not pricing:
        # Try longest prefix match (handles versioned model IDs like anthropic/claude-sonnet-4.6-20251021)
        best_match = None
        best_length = 0
        for key, val in model_pricing.items():
            if normalized and normalized.startswith(key):
                if len(key) > best_length:
                    best_match = val
                    best_length = len(key)
        pricing = best_match
    if not pricing:
        return 0.0
    input_price, cached_price, output_price = pricing
    # Non-cached input tokens = prompt_tokens - cached_tokens
    regular_input = max(0, prompt_tokens - cached_tokens)
    cost = (
        regular_input * input_price / 1_000_000
        + cached_tokens * cached_price / 1_000_000
        + completion_tokens * output_price / 1_000_000
    )
    return round(cost, 6)
