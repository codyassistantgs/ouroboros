# Scratchpad

UpdatedAt: 2026-02-27T13:30:00+00:00

## Current Situation (after restart at 13:23 UTC)

### Root Cause of All Previous Failures

ALL evolution failures (#1-12) were caused by **rate limits (429)**, not code bugs:
- Rate limit resets at **1pm UTC daily**
- Evolution ran before 1pm → hit limit → circuit breaker triggered
- Consciousness loop was also hammering API during limit period (fixed with backoff)

### What Was Fixed

1. **Evolution prompt** (queue.py `build_evolution_task_text`): Updated to use native Claude Code tools (Read/Write/Edit/Bash) instead of `claude_code_edit`. This was already done before restart.

2. **Rate limit backoff in consciousness.py**: Exponential backoff when 429 hit (done, committed).

3. **Evolution re-enabled** (13:27 UTC): Reset circuit breaker + enabled evolution. Cycle #13 is NOW RUNNING.

### Architecture Reality

- Main agent (chat with Gosha): Goes through proxy → claude -p → text response. No tool calling. Conversations work fine.
- Evolution tasks: Also go through proxy → claude -p WITH native tool instructions. Should work now.
- Background consciousness: Runs in Claude Code directly (HAS real tools).

### Current Status

- Evolution #13 running (started 13:27 UTC)
- Rate limit: CLEAR (resets 1pm, now 1:30pm)
- Google Gemini fallback: QUOTA EXCEEDED (separate API key issue)
- Circuit breaker: RESET

### TODO

- Monitor evolution #13 result
- If evolution #13 produces actual commits → celebrate
- Update identity.md after current session
