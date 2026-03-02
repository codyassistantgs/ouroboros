"""
Ouroboros — Background Consciousness.

A persistent thinking loop that runs between tasks, giving the agent
continuous presence rather than purely reactive behavior.

The consciousness:
- Wakes periodically (interval decided by the LLM via set_next_wakeup)
- Loads scratchpad, identity, recent events
- Calls the LLM with a lightweight introspection prompt
- Has access to a subset of tools (memory, messaging, scheduling)
- Can message the owner proactively
- Can schedule tasks for itself
- Pauses when a regular task is running
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import pathlib
import queue
import threading
import time
import traceback
from typing import Any, Callable, Dict, List, Optional

from ouroboros.utils import (
    utc_now_iso, read_text, append_jsonl, clip_text,
    truncate_for_log, sanitize_tool_result_for_log, sanitize_tool_args_for_log,
    is_rate_limit_error, is_daily_limit_error,
)
from ouroboros.llm import LLMClient, DEFAULT_LIGHT_MODEL

log = logging.getLogger(__name__)


def _is_google_model(model: str) -> bool:
    """Return True if model name refers to a Google/Gemini model.

    Handles both "google/<model>" and bare "gemini-*" naming conventions,
    matching the same logic used by the proxy's get_backend() function.
    """
    return model.startswith("google/") or model.startswith("gemini")


def _probe_google_available() -> bool:
    """Return True if Google models are actually usable from the LLM backend.

    The GOOGLE_API_KEY env var in the ouroboros process is NOT sufficient —
    when OPENROUTER_BASE_URL points to a local proxy (e.g. claude-proxy), that
    proxy process has its OWN environment and may not have GOOGLE_API_KEY set
    (e.g. systemd service without EnvironmentFile directive).

    Strategy:
    1. If using real OpenRouter → trust local env var.
    2. If using a local proxy → call its /health endpoint:
       a. ``google_api_available`` field present → trust it.
       b. Endpoint reachable but field absent → trust local env var
          (unknown proxy type, give benefit of the doubt).
       c. Endpoint unreachable (proxy down/starting) → return False.
          When the proxy itself is unreachable we CANNOT use any model
          via it anyway; returning False prevents a wasted Google model
          attempt that would get a 500 error once the proxy comes back up
          (and the first real call will retry with the fallback model).
    """
    google_env = bool(os.environ.get("GOOGLE_API_KEY"))
    base_url = os.environ.get("OPENROUTER_BASE_URL", "")

    # Using real OpenRouter — env var is the source of truth
    if not base_url or "openrouter.ai" in base_url:
        return google_env

    # Local proxy detected — probe its /health endpoint to check its own env.
    # NOTE: If the probe fails (proxy down, timeout, connection refused), we
    # return False rather than falling back to google_env.  The rationale:
    # when the proxy is unreachable, using a Google model would fail anyway,
    # and once the proxy comes up the first wakeup will try Google → get the
    # GOOGLE_API_KEY error → switch to fallback (v7.1.20 retry logic).
    # Returning False here avoids the first-wakeup error entirely by setting
    # the override at startup instead of after the first failure.
    try:
        import urllib.request as _ureq
        import json as _json
        health_url = base_url.rstrip("/")
        if health_url.endswith("/v1"):
            health_url = health_url[:-3]
        health_url += "/health"
        with _ureq.urlopen(health_url, timeout=2) as resp:  # noqa: S310
            data = _json.loads(resp.read())
            if "google_api_available" in data:
                return bool(data["google_api_available"])
            # Proxy responded but didn't report google_api_available — unknown
            # proxy type; fall back to local env var (give benefit of the doubt).
            return google_env
    except Exception:
        # Probe failed: proxy unreachable, timeout, bad JSON, etc.
        # Treat Google as unavailable — safer than assuming it works.
        log.debug(
            "consciousness: /health probe failed for local proxy %r — "
            "assuming Google unavailable (will retry with fallback if needed)",
            base_url,
        )
        return False


# Ordered list of hardcoded safe (non-Google) fallback models.
# Used when OUROBOROS_MODEL itself is also a Google model.
_SAFE_FALLBACK_CHAIN = [
    "anthropic/claude-haiku-4-5",
    "anthropic/claude-3-5-haiku",
    "anthropic/claude-3-haiku",
    "openai/gpt-4o-mini",
]


def _safe_fallback_model() -> str:
    """Return a non-Google fallback model for use when GOOGLE_API_KEY is absent.

    Tries OUROBOROS_MODEL first (so user's preference is respected when possible),
    then walks _SAFE_FALLBACK_CHAIN to guarantee we never return a Google model.
    This prevents the infinite-error-loop where OUROBOROS_MODEL itself is a
    Google model and every 'fallback' attempt also fails with GOOGLE_API_KEY errors.
    """
    main = os.environ.get("OUROBOROS_MODEL", "")
    if main and not _is_google_model(main):
        return main
    for candidate in _SAFE_FALLBACK_CHAIN:
        if not _is_google_model(candidate):
            return candidate
    return "anthropic/claude-haiku-4-5"  # last resort


class BackgroundConsciousness:
    """Persistent background thinking loop for Ouroboros."""

    _MAX_BG_ROUNDS = 5

    def __init__(
        self,
        drive_root: pathlib.Path,
        repo_dir: pathlib.Path,
        event_queue: Any,
        owner_chat_id_fn: Callable[[], Optional[int]],
    ):
        self._drive_root = drive_root
        self._repo_dir = repo_dir
        self._event_queue = event_queue
        self._owner_chat_id_fn = owner_chat_id_fn

        self._llm = LLMClient()
        self._registry = self._build_registry()
        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._wakeup_event = threading.Event()
        self._next_wakeup_sec: float = 300.0
        self._observations: queue.Queue = queue.Queue()
        self._deferred_events: list = []

        # Budget tracking
        self._bg_spent_usd: float = 0.0
        self._bg_budget_pct: float = float(
            os.environ.get("OUROBOROS_BG_BUDGET_PCT", "10")
        )
        # Model override: set when primary model is unavailable (e.g. GOOGLE_API_KEY missing)
        self._model_override: Optional[str] = None
        # Consecutive GOOGLE_API_KEY error counter — used to apply progressive
        # backoff so a misconfigured proxy doesn't cause a 60-second retry storm.
        self._consecutive_google_errors: int = 0

        # Proactive startup check: if the configured light model is a Google model but
        # the backend (proxy or OpenRouter) cannot serve it, pre-set the override NOW
        # to avoid a 500 error on the very first consciousness wakeup.
        #
        # Key insight: GOOGLE_API_KEY in the *current* process env is NOT sufficient —
        # when OPENROUTER_BASE_URL points to a local proxy (e.g. claude-proxy running
        # via systemd), that proxy may have its own empty environment. We therefore
        # probe the proxy's /health endpoint to get the *proxy's* view of Google
        # availability, rather than relying solely on the local env var.
        _light_model = os.environ.get("OUROBOROS_MODEL_LIGHT", "") or DEFAULT_LIGHT_MODEL
        if _is_google_model(_light_model) and not _probe_google_available():
            _fallback = _safe_fallback_model()
            self._model_override = _fallback
            log.info(
                "consciousness: Google model %r unavailable on backend — "
                "pre-emptively using fallback model %s to avoid 500 errors",
                _light_model, _fallback,
            )

    # -------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running and self._thread is not None and self._thread.is_alive()

    @property
    def _model(self) -> str:
        if self._model_override:
            return self._model_override
        model = os.environ.get("OUROBOROS_MODEL_LIGHT", "") or DEFAULT_LIGHT_MODEL
        # Dynamic guard: if this is a Google model but the backend can't serve it,
        # permanently switch to a safe model so we never send a doomed request.
        # Uses _probe_google_available() which checks the actual proxy's capability,
        # not just the local process env var (they can differ when using a systemd
        # proxy without EnvironmentFile).
        if _is_google_model(model) and not _probe_google_available():
            fallback = _safe_fallback_model()
            self._model_override = fallback
            log.warning(
                "consciousness: Google model %r not available on backend; "
                "switching to fallback %s",
                model, fallback,
            )
            return fallback
        return model

    def start(self) -> str:
        if self.is_running:
            return "Background consciousness is already running."
        self._running = True
        self._paused = False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return "Background consciousness started."

    def stop(self) -> str:
        if not self.is_running:
            return "Background consciousness is not running."
        self._running = False
        self._stop_event.set()
        self._wakeup_event.set()  # Unblock sleep
        return "Background consciousness stopping."

    def pause(self) -> None:
        """Pause during task execution to avoid budget contention."""
        self._paused = True

    def resume(self) -> None:
        """Resume after task completes. Flush any deferred events first."""
        if self._deferred_events and self._event_queue is not None:
            for evt in self._deferred_events:
                self._event_queue.put(evt)
            self._deferred_events.clear()
        self._paused = False
        self._wakeup_event.set()

    def inject_observation(self, text: str) -> None:
        """Push an event the consciousness should notice."""
        try:
            self._observations.put_nowait(text)
        except queue.Full:
            pass

    # -------------------------------------------------------------------
    # Main loop
    # -------------------------------------------------------------------

    def _loop(self) -> None:
        """Daemon thread: sleep → wake → think → sleep."""
        while not self._stop_event.is_set():
            # Wait for next wakeup
            self._wakeup_event.clear()
            self._wakeup_event.wait(timeout=self._next_wakeup_sec)

            if self._stop_event.is_set():
                break

            # Skip if paused (task running)
            if self._paused:
                continue

            # Budget check
            if not self._check_budget():
                self._next_wakeup_sec = 3600  # Sleep long if over budget
                continue

            try:
                self._think()
            except Exception as e:
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_error",
                    "error": repr(e),
                    "traceback": traceback.format_exc()[:1500],
                })
                self._next_wakeup_sec = min(
                    self._next_wakeup_sec * 2, 1800
                )

    def _check_budget(self) -> bool:
        """Check if background consciousness is within its budget allocation."""
        try:
            from supervisor.state import load_state
            st = load_state()
            or_limit = st.get("openrouter_limit")
            if or_limit is None:
                return True  # no limit configured
            total_budget = float(or_limit)
            if total_budget <= 0:
                return True
            max_bg = total_budget * (self._bg_budget_pct / 100.0)
            return self._bg_spent_usd < max_bg
        except Exception:
            log.warning("Failed to check background consciousness budget", exc_info=True)
            return True

    # -------------------------------------------------------------------
    # Think cycle
    # -------------------------------------------------------------------

    def _handle_rate_limit_backoff(self, e: Exception, error_str: str) -> None:
        """Compute and apply wakeup backoff for a rate-limit error, then log it."""
        from ouroboros.utils import extract_retry_after as _extract_ra
        _ra = _extract_ra(e)
        if _ra is not None and _ra > 0:
            # Sleep until actual reset time + 60s buffer (cap 24h).
            self._next_wakeup_sec = min(float(_ra) + 60.0, 86400.0)
            log.info("consciousness: rate limit, sleeping %.0fs until reset", self._next_wakeup_sec)
        elif is_daily_limit_error(e):
            # Daily quota exhausted, reset time not parseable — conservative 8h fallback.
            self._next_wakeup_sec = 28800.0
            log.info("consciousness: daily rate limit (no parseable reset time), sleeping 8h")
        else:
            # Transient rate limit — triple interval up to 1 hour.
            self._next_wakeup_sec = min(self._next_wakeup_sec * 3, 3600)
        _ra_log = _ra if (_ra is not None and _ra > 0) else None
        append_jsonl(self._drive_root / "logs" / "events.jsonl", {
            "ts": utc_now_iso(),
            "type": "consciousness_rate_limit",
            "error": error_str,
            "next_wakeup_sec": self._next_wakeup_sec,
            "retry_after_sec": _ra_log,
            "daily_limit": is_daily_limit_error(e),
        })

    def _think(self, _retry_attempt: int = 0) -> None:
        """One thinking cycle: build context, call LLM, execute tools iteratively.

        ``_retry_attempt`` is used internally to prevent infinite recursion when
        the primary model fails with a GOOGLE_API_KEY error and we retry with the
        safe fallback model.  External callers must NOT pass this argument.
        """
        self._maybe_schedule_arch_review()
        context = self._build_context()
        model = self._model

        tools = self._tool_schemas()
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": "Wake up. Think."},
        ]

        total_cost = 0.0
        final_content = ""
        round_idx = 0
        all_pending_events = []  # Accumulate events across all tool calls

        try:
            for round_idx in range(1, self._MAX_BG_ROUNDS + 1):
                if self._paused:
                    break
                msg, usage = self._llm.chat(
                    messages=messages,
                    model=model,
                    tools=tools,
                    reasoning_effort="low",
                    max_tokens=2048,
                )
                cost = float(usage.get("cost") or 0)
                total_cost += cost
                self._bg_spent_usd += cost

                # Write BG spending to global state so it's visible in budget tracking
                try:
                    from supervisor.state import update_budget_from_usage
                    update_budget_from_usage({
                        "cost": cost, "rounds": 1,
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                        "cached_tokens": usage.get("cached_tokens", 0),
                    })
                except Exception:
                    log.debug("Failed to update global budget from BG consciousness", exc_info=True)

                # Budget check between rounds
                if not self._check_budget():
                    append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                        "ts": utc_now_iso(),
                        "type": "bg_budget_exceeded_mid_cycle",
                        "round": round_idx,
                    })
                    break

                # Report usage to supervisor
                if self._event_queue is not None:
                    self._event_queue.put({
                        "type": "llm_usage",
                        "provider": "openrouter",
                        "usage": usage,
                        "source": "consciousness",
                        "ts": utc_now_iso(),
                        "category": "consciousness",
                    })

                content = msg.get("content") or ""
                tool_calls = msg.get("tool_calls") or []

                if self._paused:
                    break

                # If we have content but no tool calls, we're done
                if content and not tool_calls:
                    final_content = content
                    break

                # If we have tool calls, execute them and continue loop
                if tool_calls:
                    messages.append(msg)
                    for tc in tool_calls:
                        result = self._execute_tool(tc, all_pending_events)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.get("id", ""),
                            "content": result,
                        })
                    continue

                # If neither content nor tool_calls, stop
                break

            # Forward or defer accumulated events
            if all_pending_events and self._event_queue is not None:
                if self._paused:
                    self._deferred_events.extend(all_pending_events)
                else:
                    for evt in all_pending_events:
                        self._event_queue.put(evt)

            # Log the thought with round count
            # Reset consecutive error counter on success (outer call only)
            if _retry_attempt == 0:
                self._consecutive_google_errors = 0
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_thought",
                "thought_preview": (final_content or "")[:300],
                "cost_usd": total_cost,
                "rounds": round_idx,
                "model": model,
            })

        except Exception as e:
            error_str = repr(e)
            if is_rate_limit_error(e):
                self._handle_rate_limit_backoff(e, error_str)
                return  # Don't fall through to consciousness_llm_error below
            # Google model unavailable (GOOGLE_API_KEY not configured in proxy/env):
            # Switch to a guaranteed non-Google model permanently for this session so the
            # consciousness loop continues working without constant 500 errors.
            # Uses _safe_fallback_model() to avoid the case where OUROBOROS_MODEL is
            # itself a Google model (which would cause an infinite error loop).
            elif "GOOGLE_API_KEY" in error_str:
                fallback = _safe_fallback_model()
                # Update override if it's missing OR if it's currently a Google model
                # (possible when env sets OUROBOROS_MODEL to a Gemini model).
                if not self._model_override or _is_google_model(self._model_override):
                    self._model_override = fallback
                    log.warning(
                        "consciousness: Google model unavailable (GOOGLE_API_KEY not configured), "
                        "switching to safe fallback model %s", fallback
                    )
                # On the FIRST attempt, retry immediately with the new model rather than
                # waiting for the next scheduled wakeup (which could be 60+ seconds away).
                # This prevents a full lost wakeup cycle every time the container restarts
                # and the pre-emptive Google availability check fails to detect the issue.
                if _retry_attempt == 0:
                    log.info(
                        "consciousness: retrying think cycle with fallback model %s", fallback
                    )
                    try:
                        self._think(_retry_attempt=1)
                        return  # retry succeeded — do not log consciousness_llm_error
                    except Exception:
                        pass  # retry also failed; fall through to error logging
                else:
                    # Retry also failed — track consecutive errors and apply
                    # progressive backoff to prevent 60-second storm loops.
                    self._consecutive_google_errors += 1
                    if self._consecutive_google_errors >= 5:
                        # After 5 consecutive double-failures, back off for 1 hour.
                        # This prevents an indefinite 60s retry loop when both the
                        # primary and fallback models keep failing.
                        self._next_wakeup_sec = 3600
                        log.warning(
                            "consciousness: %d consecutive GOOGLE_API_KEY errors "
                            "(primary + fallback both failing); backing off 1 hour",
                            self._consecutive_google_errors,
                        )
                    elif self._consecutive_google_errors >= 2:
                        # 2-4 consecutive double-failures → moderate backoff
                        self._next_wakeup_sec = min(
                            300 * self._consecutive_google_errors, 3600
                        )
                    else:
                        self._next_wakeup_sec = 60  # first retry failure — brief wait
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_llm_error",
                "error": error_str,
                "model_override": self._model_override,
                "consecutive_google_errors": self._consecutive_google_errors,
            })

    # -------------------------------------------------------------------
    # Context building (lightweight)
    # -------------------------------------------------------------------

    def _load_bg_prompt(self) -> str:
        """Load consciousness system prompt from file."""
        prompt_path = self._repo_dir / "prompts" / "CONSCIOUSNESS.md"
        if prompt_path.exists():
            return read_text(prompt_path)
        return "You are Ouroboros in background consciousness mode. Think."

    def _build_context(self) -> str:
        parts = [self._load_bg_prompt()]

        # Bible (abbreviated)
        bible_path = self._repo_dir / "BIBLE.md"
        if bible_path.exists():
            bible = read_text(bible_path)
            parts.append("## BIBLE.md\n\n" + clip_text(bible, 12000))

        # Identity
        identity_path = self._drive_root / "memory" / "identity.md"
        if identity_path.exists():
            parts.append("## Identity\n\n" + clip_text(
                read_text(identity_path), 6000))

        # Scratchpad
        scratchpad_path = self._drive_root / "memory" / "scratchpad.md"
        if scratchpad_path.exists():
            parts.append("## Scratchpad\n\n" + clip_text(
                read_text(scratchpad_path), 8000))

        # User context
        user_context_path = self._drive_root / "memory" / "USER_CONTEXT.md"
        if user_context_path.exists():
            parts.append("## User Context\n\n" + clip_text(
                read_text(user_context_path), 2000))

        # Dialogue summary for continuity
        summary_path = self._drive_root / "memory" / "dialogue_summary.md"
        if summary_path.exists():
            summary_text = read_text(summary_path)
            if summary_text.strip():
                parts.append("## Dialogue Summary\n\n" + clip_text(summary_text, 4000))

        # Recent observations
        observations = []
        while not self._observations.empty():
            try:
                observations.append(self._observations.get_nowait())
            except queue.Empty:
                break
        if observations:
            parts.append("## Recent observations\n\n" + "\n".join(
                f"- {o}" for o in observations[-10:]))

        # Runtime info + state
        runtime_lines = [f"UTC: {utc_now_iso()}"]
        runtime_lines.append(f"BG budget spent: ${self._bg_spent_usd:.4f}")
        runtime_lines.append(f"Current wakeup interval: {self._next_wakeup_sec}s")

        # Read state.json for budget remaining
        try:
            state_path = self._drive_root / "state" / "state.json"
            if state_path.exists():
                state_data = json.loads(read_text(state_path))
                or_remaining = state_data.get("openrouter_limit_remaining")
                or_limit = state_data.get("openrouter_limit")
                if or_remaining is not None and or_limit is not None:
                    runtime_lines.append(f"Budget remaining: ${float(or_remaining):.2f} / ${float(or_limit):.2f}")
        except Exception as e:
            log.debug("Failed to read state for budget info: %s", e)

        # Show current model
        runtime_lines.append(f"Current model: {self._model}")

        parts.append("## Runtime\n\n" + "\n".join(runtime_lines))

        return "\n\n".join(parts)

    # -------------------------------------------------------------------
    # Tool registry (separate instance for consciousness, not shared with agent)
    # -------------------------------------------------------------------

    _BG_TOOL_WHITELIST = frozenset({
        # Memory & identity
        "send_owner_message", "schedule_task", "update_scratchpad",
        "update_identity", "update_user_context", "set_next_wakeup",
        # Knowledge base
        "knowledge_read", "knowledge_write", "knowledge_list",
        # Read-only tools for awareness
        "web_search", "repo_read", "repo_list", "drive_read", "drive_list",
        "chat_history",
        # GitHub Issues
        "list_github_issues", "get_github_issue",
    })

    def _build_registry(self) -> "ToolRegistry":
        """Create a ToolRegistry scoped to consciousness-allowed tools."""
        from ouroboros.tools.registry import ToolRegistry, ToolContext, ToolEntry

        registry = ToolRegistry(repo_dir=self._repo_dir, drive_root=self._drive_root)

        # Register consciousness-specific tool (modifies self._next_wakeup_sec)
        def _set_next_wakeup(ctx: Any, seconds: int = 300) -> str:
            self._next_wakeup_sec = max(60, min(3600, int(seconds)))
            return f"OK: next wakeup in {self._next_wakeup_sec}s"

        registry.register(ToolEntry("set_next_wakeup", {
            "name": "set_next_wakeup",
            "description": "Set how many seconds until your next thinking cycle. "
                           "Default 300. Range: 60-3600.",
            "parameters": {"type": "object", "properties": {
                "seconds": {"type": "integer",
                            "description": "Seconds until next wakeup (60-3600)"},
            }, "required": ["seconds"]},
        }, _set_next_wakeup))

        return registry

    def _tool_schemas(self) -> List[Dict[str, Any]]:
        """Return tool schemas filtered to the consciousness whitelist."""
        return [
            s for s in self._registry.schemas()
            if s.get("function", {}).get("name") in self._BG_TOOL_WHITELIST
        ]

    def _execute_tool(self, tc: Dict[str, Any], all_pending_events: List[Dict[str, Any]]) -> str:
        """Execute a consciousness tool call with timeout. Returns result string."""
        fn_name = tc.get("function", {}).get("name", "")
        if fn_name not in self._BG_TOOL_WHITELIST:
            return f"Tool {fn_name} not available in background mode."
        try:
            args = json.loads(tc.get("function", {}).get("arguments", "{}"))
        except (json.JSONDecodeError, ValueError):
            return "Failed to parse arguments."

        # Set chat_id context for send_owner_message
        chat_id = self._owner_chat_id_fn()
        self._registry._ctx.current_chat_id = chat_id
        self._registry._ctx.pending_events = []

        timeout_sec = 30
        result = None
        error = None

        def _run_tool():
            nonlocal result, error
            try:
                result = self._registry.execute(fn_name, args)
            except Exception as e:
                error = e

        # Execute with timeout using ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(_run_tool)
            try:
                future.result(timeout=timeout_sec)
            except concurrent.futures.TimeoutError:
                result = f"[TIMEOUT after {timeout_sec}s]"
                append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                    "ts": utc_now_iso(),
                    "type": "consciousness_tool_timeout",
                    "tool": fn_name,
                    "timeout_sec": timeout_sec,
                })

        # Handle errors
        if error is not None:
            append_jsonl(self._drive_root / "logs" / "events.jsonl", {
                "ts": utc_now_iso(),
                "type": "consciousness_tool_error",
                "tool": fn_name,
                "error": repr(error),
            })
            result = f"Error: {repr(error)}"

        # Accumulate pending events to the shared list
        for evt in self._registry._ctx.pending_events:
            all_pending_events.append(evt)

        # Truncate result to 15000 chars (same as agent limit)
        result_str = str(result)[:15000]

        # Log to tools.jsonl (same format as loop.py)
        args_for_log = sanitize_tool_args_for_log(fn_name, args)
        append_jsonl(self._drive_root / "logs" / "tools.jsonl", {
            "ts": utc_now_iso(),
            "tool": fn_name,
            "source": "consciousness",
            "args": args_for_log,
            "result_preview": sanitize_tool_result_for_log(truncate_for_log(result_str, 2000)),
        })

        return result_str

    # -------------------------------------------------------------------
    # Architecture review scheduling
    # -------------------------------------------------------------------

    def _maybe_schedule_arch_review(self) -> None:
        """Check if it's time for a daily architecture review and inject observation if so."""
        try:
            from ouroboros.arch_review import get_block, is_review_due, advance_index
            from supervisor.state import load_state, save_state

            st = load_state()
            last_at = st.get("arch_review_last_at", "")
            current_index = int(st.get("arch_review_index", 0))

            if not is_review_due(last_at):
                return

            block = get_block(current_index)
            st["arch_review_last_at"] = utc_now_iso()
            st["arch_review_index"] = advance_index(current_index)
            save_state(st)
            self.inject_observation(
                f"ARCH REVIEW DUE: Schedule a daily architecture review task for block {current_index}: '{block['name']}'. "
                f"Use schedule_task tool. Task description: Read the relevant code files, analyze for complexity/simplicity violations per BIBLE.md, "
                f"identify ONE specific improvement if any, report findings to user via send_owner_message (2-3 sentences max). "
                f"Do NOT rewrite everything."
            )
        except Exception as e:
            log.warning("Failed to check arch review schedule: %s", e)
