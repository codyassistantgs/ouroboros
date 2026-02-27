# Evolution #17: Fix Budget Tracking (v7.1.3)

**Date:** 2026-02-27
**Commit:** b53e2ca

## Problem Identified

Budget tracking was completely broken. `state.json` showed `spent_usd: 0.0` despite:
- 144 API calls
- 15,065,957 prompt tokens
- 248,606 completion tokens

Estimated real cost: ~$45-50 (at claude-sonnet-4.6 pricing).

## Root Cause (Two Bugs)

### Bug 1: events.py `_handle_llm_usage`
The event emitted by loop.py has this structure:
```json
{
  "type": "llm_usage",
  "cost": 0.045,          // ← estimated cost at TOP LEVEL
  "usage": {
    "prompt_tokens": 10000,
    "completion_tokens": 500
    // NO "cost" field here — proxy returns 0
  }
}
```
`_handle_llm_usage` was calling `ctx.update_budget_from_usage(evt["usage"])` — passing the
sub-dict WITHOUT the cost. So `update_budget_from_usage` always saw cost=None → 0.

### Bug 2: loop.py `_estimate_cost` alias mismatch
The proxy returns short model names (`claude-sonnet-4-6`) but the pricing table uses
canonical OpenRouter IDs (`anthropic/claude-sonnet-4.6`). Prefix match failed.
Cost estimate = 0 for all proxy-routed calls.

## Fixes

1. **events.py**: Copy `evt["cost"]` into usage dict when `usage.cost` is missing/zero.
2. **loop.py**: Add `_PROXY_MODEL_ALIASES` dict mapping short names → canonical IDs.

## Impact

- Budget tracking now works: `spent_usd` accumulates correctly
- Budget enforcement and reporting to user becomes accurate
- Directly addresses Gosha's goal: "earn myself tokens = be economically self-aware"

## Lessons

The bug was invisible because `spent_usd` is shown as $0.0 but nobody panics (unlimited budget).
Always verify budget tracking in system tests — mock the cost flow end-to-end.
