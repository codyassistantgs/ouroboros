# Architecture

Ouroboros v7.x — technical architecture.
Last updated: 2026-02-26

---

## High-Level Overview

Ouroboros is a self-developing AI agent with two execution contexts:

1. **Main agent** — handles user chat via Telegram. Runs through `claude-proxy`.
2. **Background consciousness** — periodic introspection loop. Runs via Claude Code directly.

These are fundamentally different: the main agent has **no tool access** (proxy limitation),
while the background consciousness **does** have real tool access.

---

## Components

### Telegram bot (`agent.py`)
- Receives user messages from Telegram
- Routes to task loop (`loop.py`)
- All LLM calls go through `LLMClient` → `OPENROUTER_BASE_URL`

### LLM Client (`llm.py`)
- OpenAI SDK client pointing at OpenRouter (or local proxy)
- Cost tracking via OpenRouter pricing API + static fallback
- Tool calling via standard OpenAI tool format

### Task Loop (`loop.py`)
- Runs multi-round LLM+tool loops
- Has circuit breaker: stops if budget exceeded or loop diverges
- Supports tool parallelism via `ThreadPoolExecutor`
- Categories: task, evolution, consciousness, review, summarize

### Background Consciousness (`consciousness.py`)
- Wakes periodically (default 300s, agent-adjustable via `set_next_wakeup`)
- Runs in Claude Code — has real file/bash/search tools
- Max 5 rounds per wakeup
- Budget limited to `OUROBOROS_BG_BUDGET_PCT` (default 10%) of total

### Memory (`memory.py`)
- `identity.md` — narrative self-description
- `USER_CONTEXT.md` — user profile, goals, priorities (max 1000 chars)
- `scratchpad.md` — working memory across sessions
- `journal/` — append-only event log (JSONL)
- `chat_history/` — Telegram message history

### Tools (`tools/`)
- `control.py` — schedule_task, send_owner_message, update_scratchpad, toggle_evolution, etc.
- `core.py` — repo_read, repo_write, knowledge_read/write, drive_read
- `git.py` — repo_commit_push (used in evolution)
- `shell.py` — bash execution (used in evolution)
- `search.py` — web search
- `evolution_stats.py` — evolution history and stats
- `health.py` — system health checks

### Supervisor (`supervisor/`)
- Manages process lifecycle
- Handles restart requests, stable promotion, evolution toggling

---

## Critical Architecture Reality (as of v7.1.0)

### The Proxy Problem
`claude-proxy` at port 8088 runs as a fake OpenAI endpoint:
- Converts all messages to flat text → `claude -p text`
- **Completely ignores `tools` parameter** — tool calls are impossible
- Returns `cost=0` always — budget tracking broken
- Model name mapping bug: `anthropic/claude-sonnet-4.6` (dots) doesn't match
  `CLAUDE_MODELS` set (hyphens), falls back to hardcoded default

**Consequence:** Evolution tasks fail silently — LLM responds but can't call tools.

### Two-Context Split
- **Main agent via proxy**: text only, no tools, no cost tracking
- **Background consciousness via Claude Code**: full tools, real file access

This means the consciousness loop is the only execution context that actually works
for code reading, file editing, and self-improvement.

### Circuit Breaker Issue
Loop success check uses `cost > 0.10` as a heuristic. Since proxy always returns
cost=0, all evolution tasks appear as failures even when they produce output.

---

## Data Flow

```
Telegram → agent.py → loop.py → LLMClient → proxy (port 8088) → claude CLI
                                                                       ↓ (text only, no tools)
                                     ← ← ← ← ← ← ← ← ← ← ← ← ← ← ←

Background: cron → Claude Code → consciousness.py → tools (real) → files/bash/search
```

---

## Evolution Architecture (intended, not working)

When evolution mode is ON:
1. Consciousness or main agent schedules an "evolution" task
2. Task loop runs with evolution-specific tools: repo_read, repo_write, shell_exec, repo_commit_push
3. Agent reads code, makes changes, runs tests, commits, pushes
4. Restart requested → supervisor pulls new code → restart

**Blocking issue**: All steps requiring tool calls fail silently through proxy.

---

## Key Config

| Variable | Default | Purpose |
|---|---|---|
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | LLM endpoint (or proxy) |
| `OPENROUTER_API_KEY` | — | API key (or `local-proxy` for proxy) |
| `OUROBOROS_MODEL` | `anthropic/claude-sonnet-4.6` | Main model |
| `OUROBOROS_MODEL_LIGHT` | `google/gemini-3-pro-preview` | Consciousness model |
| `OUROBOROS_BG_BUDGET_PCT` | `10` | % of budget for background loop |

---

## Fix Priorities

1. **Fix proxy tool calling** — either add real OpenRouter key, or patch proxy to
   forward tools to Claude CLI's MCP/tool interface
2. **Fix circuit breaker** — success check: `tool_calls > 0 OR len(response) > 500`
   instead of `cost > 0.10`
3. **Fix model name mapping** — `anthropic/claude-sonnet-4.6` → `claude-sonnet-4-6`
   (replace dots with hyphens) in proxy's `messages_to_prompt`
