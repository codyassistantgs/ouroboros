# Evolution #29: O(n) compact_tool_history + budget nudge dedup (v7.1.7)

**Date:** 2026-02-28
**Commit:** pending

## Problems Identified

### 1. O(n²) inner loop in compact_tool_history / compact_tool_history_llm

`compact_tool_history` (and its LLM variant) contained an O(n×k) inner search:

```python
for i, msg in enumerate(messages):
    ...
    if msg.get("role") == "tool" and i > 0:
        parent_round = None
        for rs in reversed(tool_round_starts):   # O(k) per message
            if rs < i:
                parent_round = rs
                break
```

For a 200-round task (~600 messages, ~200 tool-round starts), this yields up to
600 × 200 = 120,000 iterations per compaction call. `compact_tool_history` is
called every loop iteration after round 8, so the total redundant work grows
quadratically with task length.

### 2. Budget nudge messages accumulate indefinitely

`_check_budget_limits` in loop.py appended a new `[INFO] Task spent $…` system
message every 10 rounds when spending exceeded 30% of budget:

```python
elif budget_pct > 0.3 and round_idx % 10 == 0:
    messages.append({"role": "system", "content": f"[INFO] Task spent $..."})
```

These system messages are neither compacted by `compact_tool_history` (which only
touches tool/assistant messages) nor pruned by `apply_message_token_soft_cap`
(which only trims named sections). Over a 100-round high-spend task, 7+ copies of
"Wrap up if possible" accumulate, wasting ~50 tokens each (~350 tokens total).

## Fixes

### context.py — precomputed parent-round mapping

Before the main compaction loop, a single O(n) pre-pass builds a dict mapping
each tool-result message index → its parent assistant-with-tool_calls index:

```python
msg_to_parent_round: Dict[int, int] = {}
_last_round_start: Optional[int] = None
for i, msg in enumerate(messages):
    if msg.get("role") == "assistant" and msg.get("tool_calls"):
        _last_round_start = i
    elif msg.get("role") == "tool" and _last_round_start is not None:
        msg_to_parent_round[i] = _last_round_start
```

The main loop then uses `msg_to_parent_round.get(i)` — O(1) — instead of the
reverse-search inner loop. Applied to both `compact_tool_history` and
`compact_tool_history_llm` (two search loops fixed in the latter).

### loop.py — budget nudge dedup

Before appending a new budget nudge, remove all previous nudge messages with
a one-pass list comprehension:

```python
messages[:] = [
    m for m in messages
    if not (m.get("role") == "system" and
            str(m.get("content", "")).startswith("[INFO] Task spent $"))
]
messages.append({"role": "system", "content": f"[INFO] Task spent $..."})
```

This ensures at most one budget nudge exists in the messages list at any time.

## Impact

- Compaction of long tool-use histories is now strictly O(n) instead of O(n²)
- Budget nudge no longer bloats context over multi-hundred-round tasks
- 130/130 tests pass (3 e2e skipped as expected)

## Lessons

- Nested reverse-search loops are easy to overlook but become significant in
  hot paths called every LLM round
- Inline system messages appended during a task need an explicit cleanup strategy;
  otherwise they silently accumulate in the context window
