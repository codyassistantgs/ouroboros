# How to Improve Effectively

Maintained by the agent. See BIBLE.md section 8.

---

## Core Lessons (as of v7.1.0)

### 1. Proxy Architecture Constraint
Evolution runs through `claude-proxy` which strips tool definitions from LLM calls.
This means the LLM cannot invoke any Ouroboros tools during evolution — it can only generate text.
**Fix path:** Either upgrade proxy to support tool_calls, OR have `claude_code_edit`
bypass the proxy and invoke Claude CLI directly (which IS the current implementation —
the problem is the tool never gets called).

### 2. The Real Evolution Problem
`claude_code_edit` in Python spawns a `claude -p <prompt>` subprocess with native tools.
But it's never invoked because the LLM can't call it (proxy strips tool schema).
**Fix:** Make the agent construct and invoke the `claude -p` subprocess directly
during evolution, bypassing the LLM tool-call mechanism entirely.

### 3. Heuristic Traps
The evolution "success" heuristic (completion_tokens > threshold) is insufficient.
Evolution "succeeded" 3 times with zero code changes because the LLM generated
long text responses without any tool calls. Always verify success by checking:
- Did any git commits happen?
- Did `claude_code_edit` actually get invoked?
- Did the subprocess exit cleanly?

### 4. Rate Limit Strategy
Rate limits reset daily. When hitting 429s:
- Exponential backoff with max 3600s (don't hammer the endpoint)
- Don't mark circuits as broken from rate limits — that's not a failure

### 5. Cost Tracking with Proxy
claude-proxy returns cost=$0 always (it doesn't track costs).
Cost tracking via OpenRouter API call to `/generation/{id}` is the fix,
but requires the raw OpenRouter generation ID (not proxy ID).

### 6. Improvement Prompt Quality
Improvement prompts need to be extremely specific:
- Exact file paths to change
- Exact behavior to achieve
- Exact test to verify success
Vague improvement prompts produce vague responses.

---

## Effective Improvement Checklist

Before starting any improvement:
- [ ] Understand root cause (not just symptoms)
- [ ] Identify exact files to change
- [ ] Know how to verify the fix works
- [ ] Bible check: does this align with the constitution?
- [ ] Get user approval (or confirm /no-approve mode)

After completing improvement:
- [ ] Tests pass
- [ ] Commit and push
- [ ] Update VERSION and README changelog
- [ ] Tag release
- [ ] Update stable marker
- [ ] Log in improvements-log/
- [ ] Update ARCHITECTURE.md if structure changed
