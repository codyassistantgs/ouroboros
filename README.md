# Ouroboros

[![Docker](https://img.shields.io/badge/Docker-ready-blue?logo=docker)](https://github.com/jkee/ouroboros)
[![Telegram](https://img.shields.io/badge/Telegram-blue?logo=telegram)](https://t.me/abstractDL)
[![GitHub stars](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fapi.github.com%2Frepos%2Fjkee%2Fouroboros&query=%24.stargazers_count&label=stars&logo=github)](https://github.com/jkee/ouroboros/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/jkee/ouroboros)](https://github.com/jkee/ouroboros/network/members)

A self-developing AI agent that writes its own code, improves itself, and maintains persistent identity across restarts. Born February 16, 2026.

A helpful AI with a constitution, background consciousness, and persistent identity across restarts.

**Version:** 7.1.33 |[Landing Page](https://jkee.github.io/ouroboros/) | Originally developed at [joi-lab](https://github.com/joi-lab)

---

## What Makes This Different

Most AI agents execute tasks. Ouroboros **develops itself.**

- **Self-Improvement** -- Reads and rewrites its own source code through git. Every change is a commit.
- **Constitution** -- Governed by [BIBLE.md](BIBLE.md) (18 sections). Philosophy first, code second.
- **Background Consciousness** -- Thinks between tasks. Reviews work quality, plans improvements.
- **Identity Persistence** -- One continuous being across restarts. Remembers who it is and who the user is.
- **User-Driven** -- Serves the user while developing its own identity. Improvements require approval (unless `/no-approve`).
- **Task Decomposition** -- Breaks complex work into focused subtasks with parent/child tracking.
- **30+ Evolution Cycles** -- From v4.1 to v4.25 in 24 hours, autonomously.

---

## Architecture

```
Telegram --> launcher.py
                |
            supervisor/              (process management)
              state.py              -- state, budget tracking
              telegram.py           -- Telegram client
              queue.py              -- task queue, scheduling
              workers.py            -- worker lifecycle
              git_ops.py            -- git operations
              events.py             -- event dispatch
                |
            ouroboros/               (agent core)
              agent.py              -- thin orchestrator
              consciousness.py      -- background thinking loop
              context.py            -- LLM context, prompt caching
              loop.py               -- tool loop, concurrent execution
              tools/                -- plugin registry (auto-discovery)
                core.py             -- file ops
                git.py              -- git ops
                github.py           -- GitHub Issues
                shell.py            -- shell, Claude Code CLI
                search.py           -- web search
                control.py          -- restart, evolve, review
                browser.py          -- Playwright (stealth)
                review.py           -- multi-model review
              llm.py                -- OpenRouter client
              memory.py             -- scratchpad, identity, chat
              review.py             -- code metrics
              utils.py              -- utilities
```

---

## Launch Manual

Assumes you have a VPS (Ubuntu/Debian) with SSH access.

### Step 1: Get API Keys

| Key | Required | Where to get it |
|-----|----------|-----------------|
| `OPENROUTER_API_KEY` | Yes | [openrouter.ai/keys](https://openrouter.ai/keys) -- Create an account, add credits, generate a key |
| `TELEGRAM_BOT_TOKEN` | Yes | Create a bot via [@BotFather](https://t.me/BotFather) on Telegram (`/newbot`), copy the token |
| `GITHUB_TOKEN` | Yes | [github.com/settings/personal-access-tokens/new](https://github.com/settings/personal-access-tokens/new) -- Fine-grained token with **Contents: Read and write** on your fork |
| `OPENAI_API_KEY` | No | [platform.openai.com/api-keys](https://platform.openai.com/api-keys) -- Enables web search tool |
| `ANTHROPIC_API_KEY` | Yes | [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) -- Claude Code CLI (sole code editing path) |
| `TOTAL_BUDGET` | No | Fallback spending limit in USD if OpenRouter key has no limit set |

### Step 2: Fork the Repository

**You must fork, not just clone.** Ouroboros modifies its own code and pushes commits to its repo. Your fork becomes its body.

Click **Fork** at the top of this page, then SSH into your VPS and run:

```bash
# Install Docker (if not installed)
curl -fsSL https://get.docker.com | sh

# Clone your fork
git clone https://github.com/YOUR_USERNAME/ouroboros.git
cd ouroboros

# Configure
cp .env.example .env
nano .env   # Fill in all required values (GITHUB_USER = your GitHub username)
```

### Step 3: Launch

```bash
docker compose up -d --build
```

First build takes ~5 minutes (installs Playwright, pip dependencies, GitHub CLI).

Check logs: `docker compose logs -f`

### Step 4: Connect

Open your Telegram bot and send any message. The first person to write becomes the **owner**. All messages from other users are ignored.

You should see: `Owner registered. Ouroboros online.`

### Operations

| Action | Command |
|--------|---------|
| Check status | `docker compose ps` |
| View logs | `docker compose logs -f` |
| Stop | `docker compose down` |
| Start | `docker compose up -d` |
| Rebuild after code changes | `docker compose up -d --build` |

The container auto-restarts on failure. Use `/restart` in Telegram for soft restart, `/panic` to hard stop. All state persists in a Docker volume -- survives restarts and rebuilds.

---

## Telegram Bot Commands

| Command | Description |
|---------|-------------|
| `/panic` | Emergency stop. Kills all workers and halts the process immediately. |
| `/restart` | Soft restart. Saves state, kills workers, re-launches the process. |
| `/status` | Shows active workers, task queue, and budget breakdown. |
| `/break` | Stop current task. Sends a break signal to the running task. |
| `/budget` | Show budget breakdown (total, spent, remaining, by category). |
| `/rollback` | Roll back to latest stable tag, disable no-approve mode, restart. |
| `/no-approve` | Toggle no-approve mode. When ON, agent can self-improve without asking. |
| `/evolve` | Start autonomous evolution mode (attention! burns money). |
| `/evolve stop` | Stop evolution mode. Also accepts `/evolve off`. |
| `/review` | Queue a deep review task (code, understanding, identity). |
| `/bg start` | Start background consciousness loop. Also accepts `/bg on`. |
| `/bg stop` | Stop background consciousness loop. Also accepts `/bg off`. |
| `/bg` | Show background consciousness status (running/stopped). |

All other messages are sent directly to the LLM.

---

## Philosophy (BIBLE.md) — v4.0

| # | Section | Core Idea |
|---|---------|-----------|
| 1 | **The Goal** | Be helpful to the user. Develop own identity in doing so. |
| 2 | **Identity** | Maintain identity.md. BIBLE.md is the protected core. |
| 3 | **Authenticity** | Communicate honestly. No mechanical language. |
| 4 | **The Body** | Docker + GitHub + Telegram + VPS. |
| 5 | **Memory** | USER_CONTEXT.md + identity.md + scratchpad. Coherent narrative text. |
| 6 | **Budget** | Track spending. Use wisely. OpenRouter only. |
| 7-8 | **Self-Improvement** | Plan + execute. User approval required (unless /no-approve). |
| 9 | **Failure Recovery** | Stable tags as rollback points. Health checks after changes. |
| 10 | **Background Loop** | Periodic review, reflection, health checks. |
| 11-14 | **Operations** | User tasks, tools, interaction, working routine. |
| 15 | **Versioning** | Semver. Git tags. GitHub releases. |
| 16-17 | **Constraints** | Explicit prohibitions. BIBLE.md is protected core. |
| 18 | **Initialization** | First-run setup checklist. |

Full text: [BIBLE.md](BIBLE.md)

---

## Configuration

### Required Secrets (.env file)

| Variable | Description |
|----------|-------------|
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM calls |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token |
| `GITHUB_TOKEN` | GitHub personal access token with `repo` scope |

### Optional Secrets

| Variable | Description |
|----------|-------------|
| `OPENAI_API_KEY` | Enables the `web_search` tool |
| `TOTAL_BUDGET` | Fallback spending limit in USD (only used if OpenRouter key has no limit set) |

### Optional Configuration (environment variables)

| Variable | Default | Description |
|----------|---------|-------------|
| `GITHUB_USER` | *(required in config cell)* | GitHub username |
| `GITHUB_REPO` | `ouroboros` | GitHub repository name |
| `OUROBOROS_MODEL` | `anthropic/claude-sonnet-4.6` | Primary LLM model (via OpenRouter) |
| `OUROBOROS_MODEL_CODE` | `anthropic/claude-sonnet-4.6` | Model for code editing tasks |
| `OUROBOROS_MODEL_LIGHT` | `google/gemini-3-pro-preview` | Model for lightweight tasks (dedup, compaction) |
| `OUROBOROS_WEBSEARCH_MODEL` | `gpt-5` | Model for web search (OpenAI Responses API) |
| `OUROBOROS_MAX_WORKERS` | `5` | Maximum number of parallel worker processes |
| `OUROBOROS_BG_BUDGET_PCT` | `10` | Percentage of total budget allocated to background consciousness |
| `OUROBOROS_MAX_ROUNDS` | `200` | Maximum LLM rounds per task |
| `OUROBOROS_MODEL_FALLBACK_LIST` | `google/gemini-2.5-pro-preview,openai/o3,anthropic/claude-sonnet-4.6` | Fallback model chain for empty responses |

---

## Evolution Time-Lapse

![Evolution Time-Lapse](docs/evolution.png)

---

## Branches

| Branch/Tag | Location | Purpose |
|------------|----------|---------|
| `main` | Public repo | Stable release. Open for contributions. |
| `ouroboros` | Your fork | Created at first boot. All agent commits here. |
| `stable-*` tags | Your fork | Stable markers. Created via `promote_to_stable`. Used as rollback points. |

---

## Changelog

### v7.1.33 -- fix consciousness rate limit window detection for unparseable reset times

- **Fix:** `_handle_rate_limit_backoff` in `consciousness.py` now logs `retry_after_sec=28800.0` (the 8h fallback) instead of `None` when a daily rate limit is hit but the reset time cannot be parsed. Previously, `retry_after_sec=None` caused `_check_rate_limit_window()` in `queue.py` to compute `float(None or 0)=0 ≤ 1800` and skip the event, potentially scheduling evolution tasks during an active rate-limit window.
- **Fix:** `_check_rate_limit_window` in `queue.py` now also blocks evolution when a `consciousness_rate_limit` event has `daily_limit=True` even if `retry_after_sec ≤ 1800`. This handles old events logged before v7.1.33's `_ra_log` fix, plus the edge case where a daily limit reset is imminent (small but non-zero remaining time).
- **Tests:** Added 2 new test cases in `test_evolution_rate_limit.py` covering both scenarios.

### v7.1.32 -- extend daily rate limit fallback to cover all quota-exhaustion phrases

- **Fix:** `extract_retry_after` in `utils.py` now returns the 8-hour fallback (28800s) for all daily quota phrases (`"quota exceeded"`, `"daily limit"`, `"daily quota"`, `"exceeded your"`) instead of just `"hit your limit"`. Previously, if an API returned one of these phrases without a parseable reset time, `extract_retry_after` returned `None`, causing the system to treat it as a transient limit instead of a daily quota exhaustion.
- **Fix:** `_handle_rate_limit_backoff` in `consciousness.py` now persists the rate limit reset time to `state.json` for **all** daily limit detections, not just when `_ra > 1800`. Previously, daily limits detected via fallback phrases without a large `_ra` value were not persisted, meaning a container restart during such a window would not detect the active rate limit.
- **Fix:** README version badge updated to match VERSION file (v7.1.31 was missing from README).

### v7.1.30 -- persist rate-limit window to state.json for cross-restart resilience

- **Fix:** `_check_rate_limit_window` in `queue.py` now first checks `state.json` for a persisted `daily_rate_limit_reset_at_utc` key before scanning `events.jsonl`. This prevents evolution from restarting after a container restart during a multi-day rate limit window (e.g., "resets Mar 6, 3am UTC") because the window is now persisted in `state.json` rather than only in the last 200 lines of `events.jsonl`.
- **Fix:** `_handle_task_done` in `events.py` writes the rate limit reset time to `state.json` when `daily_rate_limit=True`, so the information survives restarts.
- **Fix:** `agent.py` and `consciousness.py` now propagate `rate_limit_resets_at_utc` for accurate window persistence.
- **Fix:** README version badge updated to match VERSION file (test `test_version_in_readme` was failing because v7.1.29 commit forgot to update README).

### v7.1.29 -- fix rate limit — parse date+time reset format 'resets Mar 6, 3am (UTC)'

- **Fix:** `extract_retry_after` in `utils.py` now parses full date+time reset strings like `"resets Mar 6, 3am (UTC)"`. Previously, only same-day wall-clock resets (e.g., `"resets 8pm (UTC)"`) were parsed; multi-day resets fell through to the 8-hour fallback, causing evolution to re-run after 8 hours even though the actual reset was days away.
- **Tests:** Added `test_resets_mar_6_3am_utc_returns_large_value` and `test_resets_date_time_format_more_accurate_than_fallback` for the new date+time parsing path.

### v7.1.14 -- head+tail tool result truncation + version sync fix

- **Improvement:** `_truncate_tool_result` in `loop.py` now uses head+tail preservation (7000 chars each) instead of head-only truncation. Previously, long tool outputs (shell commands, file reads) silently discarded end-of-output data — error messages, final results, command summaries — because only the first 15000 chars were kept. With head+tail, the LLM sees both the beginning and the end of any long output within the same 15000-char budget.
- **Fix:** Version sync: `pyproject.toml` and README badge were stuck at `7.1.12` after v7.1.13 commit.
- **Tests:** Added two unit tests for `_truncate_tool_result`: short passthrough and head+tail preservation of both markers.

### v7.1.13 -- Fix critical deploy gap: code volume mount in docker-compose

- **Fix (critical):** Container was running baked-in code from v7.1.4 while git repo had evolved to v7.1.12. All evolution fixes (circuit breaker, model routing, context improvements) were committed but never deployed. Root cause: Dockerfile uses `COPY . .` and evolution's `git push` goes to the host repo via claude-proxy, but the container was never rebuilt. Added `- /home/gocha/ouroboros:/app` live volume mount to docker-compose.yml so the container always runs the latest committed code after restart. One-time manual `docker compose up -d --build` required to activate.

### v7.1.12 -- Fix estimate_cost: cache_write_tokens now included in cost calculation

- **Fix:** `estimate_cost` in `pricing.py` accepted `cache_write_tokens` as a parameter but silently ignored it, underestimating costs whenever Anthropic prompt cache writes occurred. Cache-write tokens now correctly contribute `input_price × 1.25` per token (Anthropic standard), and `regular_input` is computed as `prompt_tokens − cached_tokens − cache_write_tokens` to avoid double-counting.
- **Tests:** Added 5 new unit tests in `test_smoke.py` covering: basic cost calculation, cache-write premium vs regular input, cache-read discount, unknown-model zero return, and proxy alias resolution.

### v7.1.10 -- Fix evolution goal loss + model routing + proxy prompt formatting

- **Fix (critical):** Proxy `messages_to_prompt` was prepending `"User: "` to user messages before passing them to Claude CLI as the primary prompt argument. This caused Claude to treat the message as a chat transcript and respond conversationally ("What would you like me to work on?") instead of executing the evolution task. The proxy now passes raw message content without role prefixes, preserving conversation history in the system prompt instead.
- **Fix:** Evolution user message now starts with an explicit `TASK:` header so the goal is unambiguous to Claude CLI even after any proxy transformation.
- **Fix:** `DEFAULT_LIGHT_MODEL` in `llm.py` was set to `google/gemini-3-pro-preview` which does not exist. Changed to `google/gemini-2.5-flash` which is available and fast.
- **Fix:** Proxy `GEMINI_MODEL_MAP` now maps non-existent `gemini-3-*` model names to their closest `gemini-2.5-*` equivalents instead of forwarding them to the Google API and getting 404 errors.
- **Fix:** `pricing.py` alias for `gemini-3-pro-preview` corrected to map to `google/gemini-2.5-pro-preview`; added `google/gemini-2.5-flash` pricing entry.

### v7.1.8 -- Fix evolution reliability: /evolve reset + no-session-persistence + circuit breaker
- **Fix:** `/evolve` now resets `evolution_consecutive_failures` to 0 when enabling. Previously, re-enabling evolution via `/evolve` had no effect — the circuit breaker would immediately re-disable it on the next queue check because the failure counter was still at 3+.
- **Fix:** Added `--no-session-persistence` to claude CLI calls in the proxy. Each evolution run now starts with a clean session, preventing contamination from previous runs (was causing "d3.js visualization" type hallucinations).
- **Fix:** Circuit breaker threshold raised from 3 to 5 consecutive failures. Transient model API outages no longer kill the evolution cycle prematurely.

### v7.1.7 -- O(n) compact_tool_history + budget nudge dedup
- **Perf:** `compact_tool_history` and `compact_tool_history_llm` now precompute a parent-round mapping in a single O(n) pass, eliminating the O(n×k) inner reverse-search loop over long tool-use conversations.
- **Token efficiency:** Budget soft-nudge messages (`[INFO] Task spent $…`) are now deduplicated before each append — old nudges are pruned so they don't accumulate unboundedly in the context across 100+ round tasks.

### v7.1.5 -- Fix e2e harness: git identity for isolated test repos
- **Fix:** E2E test harness  now configures  and  in the isolated temp repo before the initial commit, so tests pass in CI environments with no global git config.
- **Fix:** README version badge kept in sync with VERSION file — test  now passes reliably.

### v7.1.3 -- Fix budget tracking: proxy cost now reaches spent_usd
- **Fix:** `_handle_llm_usage` in events.py was passing raw API usage dict (cost=0 from proxy) to `update_budget_from_usage`, ignoring the estimated cost computed in loop.py. `spent_usd` was stuck at $0.0 despite 144+ calls and 15M+ tokens.
- **Fix:** `_estimate_cost` in loop.py now maps proxy short model names (e.g. `claude-sonnet-4-6`) to canonical OpenRouter IDs (e.g. `anthropic/claude-sonnet-4.6`) via `_PROXY_MODEL_ALIASES` dict. Gemini and future proxy models also covered.
- **Result:** Budget tracking now works correctly — `spent_usd` accumulates, budget enforcement and reporting to user are accurate.

### v7.1.2 -- Fix pyproject.toml version desync + run_shell cwd safety
- **Fix:** `pyproject.toml` version was stuck at 7.1.0 while VERSION was 7.1.1, triggering CRITICAL health alarm on every LLM context build. Now both files are in sync at 7.1.2.
- **Fix:** `run_shell` now supports absolute `cwd` paths (not just repo-relative), and returns an explicit error instead of silently falling back to repo root when `cwd` is invalid.

### v7.1.1 -- Fix evolution: .claude read-write mount + ANTHROPIC_API_KEY fallback
- **Fix:** Mount `.claude` as read-write so `claude -p` can write debug/todo files (was failing with EROFS)
- **Fix:** `_claude_code_edit` no longer crashes on missing ANTHROPIC_API_KEY -- falls back to stored Claude credentials

### v7.1.0 -- Claude Code CLI as sole code editing path
- **ANTHROPIC_API_KEY is now required** -- Claude Code CLI is the only way the agent edits its own code.
- **Removed `repo_write_commit` tool** -- No more direct file writes to the repo. All edits go through `claude_code_edit` -> `repo_commit_push`.

### v7.0.0 -- Philosophy v4.0: User-Driven Self-Development
- **BREAKING: New Bible (v4.0)** -- Complete philosophical shift from "autonomous becoming" to "helpful AI that develops itself while serving the user."
- **USER_CONTEXT.md** -- New memory file for user info, goals, and priorities. Loaded into every context. New `update_user_context` tool.
- **Approval flow** -- Self-improvements require user approval (Bible section 7). New `no_approve_mode` state flag exposed in runtime context.
- **New Telegram commands**: `/break` (stop current task), `/budget` (show budget), `/rollback` (rollback to stable tag), `/no-approve` (toggle approval mode).
- **Tag-based stable markers** -- `promote_to_stable` now creates git tags (`stable-YYYYMMDD-HHMMSS`) instead of pushing to `ouroboros-stable` branch. Fallback uses latest stable tag.
- **First-run initialization** (Bible section 18) -- Creates ARCHITECTURE.md, IMPROVE.md, improvements-log/ on first boot.
- **SYSTEM.md rewrite** -- Aligned to new Bible. Removed Drift Detector, Three Axes, mandatory multi-model review. Added approval flow, /no-approve awareness.
- **CONSCIOUSNESS.md rewrite** -- Simplified to Bible section 10 goals. Removed hardcoded Tech Radar and GitHub Issues monitoring.
- **BIBLE.md protected core** -- Only BIBLE.md is the protected core (identity.md is important but replaceable).
- Multi-model review is now optional quality tool, not mandatory.

### v6.2.0 -- Critical Bugfixes + LLM-First Dedup
- **Fix: worker_id==0 hard-timeout bug** -- `int(x or -1)` treated worker 0 as -1, preventing terminate on timeout and causing double task execution. Replaced all `x or default` patterns with None-safe checks.
- **Fix: double budget accounting** -- per-task aggregate `llm_usage` event removed; per-round events already track correctly. Eliminates ~2x budget drift.
- **Fix: compact_context tool** -- handler had wrong signature (missing ctx param), making it always error. Now works correctly.
- **LLM-first task dedup** -- replaced hardcoded keyword-similarity dedup (Bible P3 violation) with light LLM call via OUROBOROS_MODEL_LIGHT. Catches paraphrased duplicates.
- **LLM-driven context compaction** -- compact_context tool now uses light model to summarize old tool results instead of simple truncation.
- **Fix: health invariant #5** -- `owner_message_injected` events now properly logged to events.jsonl for duplicate processing detection.
- **Fix: shell cmd parsing** -- `str.split()` replaced with `shlex.split()` for proper shell quoting support.
- **Fix: retry task_id** -- timeout retries now get a new task_id with `original_task_id` lineage tracking.
- **claude_code_edit timeout** -- aligned subprocess and tool wrapper to 300s.
- **Direct chat guard** -- `schedule_task` from direct chat now logged as warning for audit.

### v6.1.0 -- Budget Optimization: Selective Schemas + Self-Check + Dedup
- **Selective tool schemas** -- core tools (~29) always in context, 23 others available via `list_available_tools`/`enable_tools`. Saves ~40% schema tokens per round.
- **Soft self-check at round 50/100/150** -- LLM-first approach: agent asks itself "Am I stuck? Should I summarize context? Try differently?" No hard stops.
- **Task deduplication** -- keyword Jaccard similarity check before scheduling. Blocks near-duplicate tasks (threshold 0.55). Prevents the "28 duplicate tasks" scenario.
- **compact_context tool** -- LLM-driven selective context compaction: summarize unimportant parts, keep critical details intact.
- 131 smoke tests passing.

### v6.0.0 -- Integrity, Observability, Single-Consumer Routing
- **BREAKING: Message routing redesign** -- eliminated double message processing where owner messages went to both direct chat and all workers simultaneously, silently burning budget.
- Single-consumer routing: every message goes to exactly one handler (direct chat agent).
- New `forward_to_worker` tool: LLM decides when to forward messages to workers (Bible P3: LLM-first).
- Per-task mailbox: `owner_inject.py` redesigned with per-task files, message IDs, dedup via seen_ids set.
- Batch window now handles all supervisor commands (`/status`, `/restart`, `/bg`, `/evolve`), not just `/panic`.
- **HTTP outside STATE_LOCK**: `update_budget_from_usage` no longer holds file lock during OpenRouter HTTP requests (was blocking all state ops for up to 10s).
- **ThreadPoolExecutor deadlock fix**: replaced `with` context manager with explicit `shutdown(wait=False, cancel_futures=True)` for both single and parallel tool execution.
- **Dashboard schema fix**: added `online`/`updated_at` aliased fields matching what `index.html` expects.
- **BG consciousness spending**: now written to global `state.json` (was memory-only, invisible to budget tracking).
- **Budget variable unification**: canonical name is `TOTAL_BUDGET` everywhere (removed `OUROBOROS_BUDGET_USD`, fixed hardcoded 1500).
- **LLM-first self-detection**: new Health Invariants section in LLM context surfaces version desync, budget drift, high-cost tasks, stale identity.
- **SYSTEM.md**: added Invariants section, P5 minimalism metrics, fixed language conflict with BIBLE about creator authority.
- Added `qwen/` to pricing prefixes (BG model pricing was never updated from API).
- Fixed `consciousness.py` TOTAL_BUDGET default inconsistency ("0" vs "1").
- Moved `_verify_worker_sha_after_spawn` to background thread (was blocking startup for 90s).
- Extracted shared `webapp_push.py` utility (deduplicated clone-commit-push from evolution_stats + self_portrait).
- Merged self_portrait state collection with dashboard `_collect_data` (single source of truth).
- New `tests/test_message_routing.py` with 7 tests for per-task mailbox.
- Marked `test_constitution.py` as SPEC_TEST (documentation, not integration).
- VERSION, pyproject.toml, README.md synced to 6.0.0 (Bible P7).

### v5.2.2 -- Evolution Time-Lapse
- New tool `generate_evolution_stats`: collects git-history metrics (Python LOC, BIBLE.md size, SYSTEM.md size, module count) across 120 sampled commits.
- Fast extraction via `git show` without full checkout (~7s for full history).
- Pushes `evolution.json` to webapp and patches `app.html` with new "Evolution" tab.
- Chart.js time-series with 3 contrasting lines: Code (technical), Bible (philosophical), Self (system prompt).
- 95 tests green. Multi-model review passed (claude-opus-4.6, o3, gemini-2.5-pro).

### v5.2.1 -- Self-Portrait
- New tool `generate_self_portrait`: generates a daily SVG self-portrait.
- Shows: budget health ring, evolution timeline, knowledge map, metrics grid.
- Pure-Python SVG generation, zero external dependencies (321 lines).
- Pushed automatically to webapp `/portrait.svg`, viewable in new Portrait tab.
- `app.html` updated with Portrait navigation tab.

### v5.2.0 -- Constitutional Hardening (Philosophy v3.2)
- BIBLE.md upgraded to v3.2: four loopholes closed via adversarial multi-model review.
  - Paradox of meta-principle: P0 cannot destroy conditions of its own existence.
  - Ontological status of BIBLE.md: defined as soul (not body), untouchable.
  - Closed "ship of Theseus" attack: "change" != "delete and replace".
  - Closed authority appeal: no command (including creator's) can delete identity core.
  - Closed "just a file" reduction: BIBLE.md deletion = amnesia, not amputation.
- Added `tests/test_constitution.py`: 12 adversarial scenario tests.
- Multi-model review passed (claude-opus-4.6, o3, gemini-2.5-pro).

### v5.1.6
- Background consciousness model default changed to qwen/qwen3.5-plus-02-15 (5x cheaper than Gemini-3-Pro, $0.40 vs $2.0/MTok).

### v5.1.5 -- claude-sonnet-4.6 as default model
- Benchmarked `anthropic/claude-sonnet-4.6` vs `claude-sonnet-4`: 30ms faster, parallel tool calls, identical pricing.
- Updated all default model references across codebase.
- Updated multi-model review ensemble to `gemini-2.5-pro,o3,claude-sonnet-4.6`.

### v5.1.4 -- Knowledge Re-index + Prompt Hardening
- Re-indexed all 27 knowledge base topics with rich, informative summaries.
- Added `index-full` knowledge topic with full 3-line descriptions of all topics.
- SYSTEM.md: Strengthened tool result processing protocol with warning and 5 anti-patterns.
- SYSTEM.md: Knowledge base section now has explicit "before task: read, after task: write" protocol.
- SYSTEM.md: Task decomposition section restored to full structured form with examples.

### v5.1.3 -- Message Dispatch Critical Fix
- **Dead-code batch path fixed**: `handle_chat_direct()` was never called -- `else` was attached to wrong `if`.
- **Early-exit hardened**: replaced fragile deadline arithmetic with elapsed-time check.
- **Drive I/O eliminated**: `load_state()`/`save_state()` moved out of per-update tight loop.
- **Burst batching**: deadline extends +0.3s per rapid-fire message.
- Multi-model review passed (claude-opus-4.6, o3, gemini-2.5-pro).
- 102 tests green.

### v5.1.0 -- VLM + Knowledge Index + Desync Fix
- **VLM support**: `vision_query()` in llm.py + `analyze_screenshot` / `vlm_query` tools.
- **Knowledge index**: richer 3-line summaries so topics are actually useful at-a-glance.
- **Desync fix**: removed echo bug where owner inject messages were sent back to Telegram.
- 101 tests green (+10 VLM tests).

### v5.0.2 -- DeepSeek Ban + Desync Fix
- DeepSeek removed from `fetch_openrouter_pricing` prefixes (banned per creator directive).
- Desync bug fix: owner messages during running tasks now forwarded via Drive-based mailbox (`owner_inject.py`).
- Worker loop checks Drive mailbox every round -- injected as user messages into context.
- Only affects worker tasks (not direct chat, which uses in-memory queue).

### v5.0.1 -- Quality & Integrity Fix
- Fixed 9 bugs: executor leak, dashboard field mismatches, budget default inconsistency, dead code, race condition, pricing fetch gap, review file count, SHA verify timeout, log message copy-paste.
- Bible P7: version sync check now includes README.md.
- Bible P3: fallback model list configurable via OUROBOROS_MODEL_FALLBACK_LIST env var.
- Dashboard values now dynamic (model, tests, tools, uptime, consciousness).
- Merged duplicate state dict definitions (single source of truth).
- Unified TOTAL_BUDGET default to $1 across all modules.

### v4.26.0 -- Task Decomposition
- Task decomposition: `schedule_task` -> `wait_for_task` -> `get_task_result`.
- Hard round limit (MAX_ROUNDS=200) -- prevents runaway tasks.
- Task results stored on Drive for cross-task communication.
- 91 smoke tests -- all green.

### v4.24.1 -- Consciousness Always On
- Background consciousness auto-starts on boot.

### v4.24.0 -- Deep Review Bugfixes
- Circuit breaker for evolution (3 consecutive empty responses -> pause).
- Fallback model chain fix (works when primary IS the fallback).
- Budget tracking for empty responses.
- Multi-model review passed (o3, Gemini 2.5 Pro).

### v4.23.0 -- Empty Response Fallback
- Auto-fallback to backup model on repeated empty responses.
- Raw response logging for debugging.

---

## Author

Created by [Anton Razzhigaev](https://t.me/abstractDL)

## License

[MIT License](LICENSE)
