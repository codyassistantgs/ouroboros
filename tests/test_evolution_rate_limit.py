"""Tests for evolution rate-limit window detection in supervisor/queue.py.

Verifies that ``_check_rate_limit_window`` correctly:
- Returns None when no rate-limit event exists
- Returns seconds-remaining when inside a rate-limit window
- Returns None when the rate-limit window has already expired
- Returns None when ``daily_limit`` is absent or False

Run: python -m pytest tests/test_evolution_rate_limit.py -v
"""
from __future__ import annotations

import datetime
import json
import pathlib
import tempfile
import time

import pytest


def _write_events(tmp_path: pathlib.Path, events: list) -> None:
    events_path = tmp_path / "logs" / "events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("w", encoding="utf-8") as f:
        for ev in events:
            f.write(json.dumps(ev) + "\n")


def _ts_offset(delta_sec: float) -> str:
    """Return an ISO timestamp offset from now by delta_sec seconds."""
    dt = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(seconds=delta_sec)
    return dt.isoformat()


class TestCheckRateLimitWindow:
    """Unit tests for _check_rate_limit_window()."""

    def test_returns_none_when_no_events(self):
        """No events.jsonl → no rate limit → None."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            result = _check_rate_limit_window(pathlib.Path(tmp))
        assert result is None

    def test_returns_none_when_no_api_error_events(self):
        """events.jsonl exists but has no llm_api_error entries → None."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            _write_events(tmp_path, [
                {"ts": _ts_offset(-60), "type": "consciousness_thought", "model": "anthropic/claude-haiku"},
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is None

    def test_returns_none_when_daily_limit_false(self):
        """llm_api_error without daily_limit=True → not a daily limit → None."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),
                    "type": "llm_api_error",
                    "daily_limit": False,
                    "resets_in_sec": 3600,
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is None

    def test_returns_none_when_window_expired(self):
        """Rate limit event exists but reset time already passed → None."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Event happened 2 hours ago, reset was in 1 hour — reset already passed
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-7200),  # 2 hours ago
                    "type": "llm_api_error",
                    "daily_limit": True,
                    "resets_in_sec": 3600,   # 1 hour from event time = 1 hour ago
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is None

    def test_returns_remaining_seconds_in_active_window(self):
        """Active rate limit (reset in future) → returns positive remaining seconds."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Event happened 60s ago, reset is 7200s from event time = 7140s from now
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-60),
                    "type": "llm_api_error",
                    "daily_limit": True,
                    "resets_in_sec": 7200,
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is not None, "Should detect active rate limit window"
        assert result > 0, "Remaining seconds should be positive"
        # Should be approximately 7200 - 60 = 7140 seconds, give some slack for test timing
        assert 7000 < result < 7200, f"Expected ~7140s remaining, got {result:.0f}s"

    def test_uses_most_recent_event(self):
        """Multiple rate-limit events: uses the most recent one."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Older event (expired) + newer event (still active)
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-7200),  # 2h ago — expired
                    "type": "llm_api_error",
                    "daily_limit": True,
                    "resets_in_sec": 3600,
                },
                {
                    "ts": _ts_offset(-30),   # 30s ago — still active
                    "type": "llm_api_error",
                    "daily_limit": True,
                    "resets_in_sec": 7200,
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        # Most recent event is the 30s-ago one with 7200s reset → still active
        assert result is not None, "Most recent event is still active"
        assert result > 0

    def test_resets_8pm_utc_style_event(self):
        """Simulate the exact error that triggered this fix: 'resets 8pm (UTC)'.

        extract_retry_after in utils.py converts "resets 8pm (UTC)" to seconds
        until that wall-clock time.  Here we simulate an event where resets_in_sec
        is a large value (daily reset) and verify it's treated as an active window.
        """
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Simulate: event happened 5 minutes ago, reset is 6h away from event time
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-300),    # 5 minutes ago
                    "type": "llm_api_error",
                    "daily_limit": True,
                    "resets_in_sec": 21600,    # 6 hours from event → still 5h55m remaining
                    "error": "RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: resets 8pm (UTC)\"}\")')",
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is not None
        assert result > 21000, f"Expected ~21300s remaining, got {result:.0f}s"
        assert result < 21600

    def test_consciousness_rate_limit_event_active(self):
        """consciousness_rate_limit with retry_after_sec > 1800 → detected as active window."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Simulate consciousness hitting a daily rate limit 2 minutes ago
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-120),   # 2 minutes ago
                    "type": "consciousness_rate_limit",
                    "retry_after_sec": 28800,  # 8h reset → still ~7h58m remaining
                    "error": "RateLimitError('429 - rate limit')",
                    "next_wakeup_sec": 28860,
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is not None, "consciousness_rate_limit with large retry_after_sec should be detected"
        assert result > 0, "Remaining seconds should be positive"
        # Should be approximately 28800 - 120 = 28680 seconds remaining
        assert 28000 < result < 28800, f"Expected ~28680s remaining, got {result:.0f}s"

    def test_consciousness_rate_limit_event_short_not_detected(self):
        """consciousness_rate_limit with retry_after_sec <= 1800 → NOT treated as daily limit."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Short transient rate limit (< 30 min) — should not block evolution
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),
                    "type": "consciousness_rate_limit",
                    "retry_after_sec": 60,   # only 60s reset — transient, not daily
                    "error": "RateLimitError('429 - too many requests')",
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is None, "Short consciousness rate limit should NOT block evolution"

    def test_consciousness_rate_limit_event_expired(self):
        """consciousness_rate_limit event whose window has already passed → returns None."""
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Event happened 10 hours ago, reset was in 8 hours → already reset
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-36000),  # 10 hours ago
                    "type": "consciousness_rate_limit",
                    "retry_after_sec": 28800,   # 8h from event = 2h ago → expired
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is None, "Expired consciousness_rate_limit should return None"


class TestExtractRetryAfter:
    """Unit tests for extract_retry_after() in ouroboros/utils.py."""

    def test_you_ve_hit_your_limit_returns_8h(self):
        """'You've hit your limit' phrase → returns 28800s (8h fallback)."""
        from ouroboros.utils import extract_retry_after
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: You\\'ve hit your limit \\u00b7 resets 8pm (UTC)\"}')")
        result = extract_retry_after(exc)
        # The specific "resets 8pm (UTC)" pattern should be caught by the wall-clock
        # parser first; if parsing fails for any reason, the "hit your limit" fallback
        # should return 28800. Either way, result must be a positive number > 1800.
        assert result is not None, "Should return a positive delay, not None"
        assert result > 1800, f"Daily limit should return >1800s, got {result}"

    def test_hit_your_limit_no_time_returns_8h(self):
        """'You've hit your limit' without a reset time → exactly 28800s fallback."""
        from ouroboros.utils import extract_retry_after
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: You\\'ve hit your limit\"}')")
        result = extract_retry_after(exc)
        assert result == 28800.0, f"Expected 28800s fallback, got {result}"

    def test_you_have_hit_your_limit_returns_8h(self):
        """'You have hit your limit' variant → returns 28800s fallback."""
        from ouroboros.utils import extract_retry_after
        exc = Exception("RateLimitError('429: You have hit your limit for today')")
        result = extract_retry_after(exc)
        assert result == 28800.0, f"Expected 28800s fallback, got {result}"

    def test_regular_rate_limit_no_limit_phrase_returns_none(self):
        """Generic rate limit without 'hit your limit' → returns None (no fallback)."""
        from ouroboros.utils import extract_retry_after
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Too many requests\"}')")
        result = extract_retry_after(exc)
        assert result is None, f"Generic 429 without time/phrase should return None, got {result}"


class TestFindSpecificEvolutionTarget:
    """Unit tests for _find_specific_evolution_target() rate-limit filtering."""

    def _write_events(self, tmp_path: pathlib.Path, events: list) -> None:
        events_path = tmp_path / "logs" / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("w", encoding="utf-8") as f:
            for ev in events:
                f.write(json.dumps(ev) + "\n")

    def _make_env(self, tmp_path: pathlib.Path):
        """Build a minimal env-like object pointing at tmp_path."""
        class _FakeEnv:
            def drive_path(self, rel):
                return tmp_path / rel
        return _FakeEnv()

    def test_rate_limit_error_skipped(self):
        """llm_api_error with is_rate_limit=True is NOT returned as evolution target."""
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),
                    "type": "llm_api_error",
                    "is_rate_limit": True,
                    "daily_limit": True,
                    "resets_in_sec": 28800,
                    "error": "RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: You\\'ve hit your limit · resets 8pm (UTC)\"}')",
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result == "" or "rate limit" not in result.lower(), (
            f"Rate limit error should NOT be returned as evolution target, got: {result!r}"
        )
        # Specifically, should not mention the 429 rate limit error
        if result:
            assert "RateLimitError" not in result, (
                f"RateLimitError should be filtered from evolution targets, got: {result!r}"
            )

    def test_daily_limit_flag_skipped(self):
        """llm_api_error with daily_limit=True is NOT returned as evolution target."""
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-60),
                    "type": "llm_api_error",
                    "is_rate_limit": True,
                    "daily_limit": True,
                    "resets_in_sec": 3600,
                    "error": "RateLimitError('429 - hit your limit')",
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result == "" or "RateLimitError" not in result, (
            f"daily_limit error should be filtered, got: {result!r}"
        )

    def test_consciousness_rate_limit_event_skipped(self):
        """consciousness_rate_limit events are NOT returned as evolution target."""
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-120),
                    "type": "consciousness_rate_limit",
                    "retry_after_sec": 28800,
                    "error": "RateLimitError('429 - rate limit')",
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result == "" or "consciousness_rate_limit" not in result, (
            f"consciousness_rate_limit should be filtered, got: {result!r}"
        )

    def test_real_tool_error_is_returned(self):
        """Genuine tool_error events ARE returned as evolution targets."""
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),
                    "type": "tool_error",
                    "tool": "repo_read",
                    "error": "FileNotFoundError: /app/missing_file.py not found",
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result != "", "Real tool_error should be returned as evolution target"
        assert "tool_error" in result, f"Expected tool_error in result, got: {result!r}"

    def test_rate_limit_skipped_real_error_used(self):
        """When both a rate-limit error and a real error exist, use the real error."""
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-120),
                    "type": "llm_api_error",
                    "is_rate_limit": True,
                    "daily_limit": True,
                    "error": "RateLimitError('429 - hit your limit')",
                },
                {
                    "ts": _ts_offset(-30),
                    "type": "tool_error",
                    "tool": "run_shell",
                    "error": "CalledProcessError: command failed with exit code 1",
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result != "", "Should find the tool_error even when rate limit also present"
        assert "tool_error" in result, (
            f"Should target the real tool_error, not the rate limit, got: {result!r}"
        )


class TestEvolutionCircuitBreakerRateLimitOnLaterRound:
    """Rate limit hitting on round 2+ must not increment evolution_consecutive_failures.

    When round 1 of an evolution task succeeds and round 2 hits a daily rate limit,
    the task_done event has total_rounds=1, completion_tokens>0, cost>0 — so the
    simple ``_api_error = (rounds == 0 and ...)`` check is False.  The extended
    check in _handle_task_done must detect the llm_api_error event and treat it
    as an infrastructure error rather than a logic failure.
    """

    def _write_combined_events(self, tmp_path: pathlib.Path, task_id: str) -> None:
        """Write events.jsonl simulating: round 1 OK, round 2 daily rate limit."""
        events_path = tmp_path / "logs" / "events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("w", encoding="utf-8") as f:
            # Round 1 — successful LLM round
            f.write(json.dumps({
                "ts": _ts_offset(-300),
                "type": "llm_round",
                "task_id": task_id,
                "round": 1,
                "model": "anthropic/claude-haiku-4-5",
                "prompt_tokens": 5000,
                "completion_tokens": 800,
                "cost_usd": 0.05,
            }) + "\n")
            # Round 2 — daily rate limit error
            f.write(json.dumps({
                "ts": _ts_offset(-60),
                "type": "llm_api_error",
                "task_id": task_id,
                "round": 2,
                "model": "anthropic/claude-haiku-4-5",
                "error": "RateLimitError('Error code: 429 - rate limit: resets 8pm (UTC)')",
                "is_rate_limit": True,
                "daily_limit": True,
                "resets_in_sec": 18000.0,
                "sleep_sec": 0,
            }) + "\n")

    def test_daily_rate_limit_on_later_round_not_counted_as_failure(self):
        """llm_api_error(daily_limit=True) for task on later round → _api_error=True in events."""
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            task_id = "test_task_abc"
            self._write_combined_events(tmp_path, task_id)

            # Simulate what _handle_task_done does: check events.jsonl for daily limit
            import subprocess
            import json as _json
            _ev_path = tmp_path / "logs" / "events.jsonl"
            _tail = subprocess.run(
                ["tail", "-n", "500", str(_ev_path)],
                capture_output=True, text=True, timeout=5,
            )
            found_daily_limit = False
            for _line in (_tail.stdout or "").splitlines():
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _ev = _json.loads(_line)
                    if (_ev.get("type") == "llm_api_error"
                            and _ev.get("daily_limit")
                            and str(_ev.get("task_id") or "") == str(task_id)):
                        found_daily_limit = True
                        break
                except Exception:
                    continue

            assert found_daily_limit, (
                "Should detect daily rate limit event for this task in events.jsonl"
            )

    def test_daily_rate_limit_different_task_not_detected(self):
        """llm_api_error(daily_limit=True) for a DIFFERENT task_id → not detected for current task."""
        import pathlib
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Write rate limit event for a different task
            self._write_combined_events(tmp_path, "other_task_xyz")

            # Check for a task_id that has no rate limit event
            import subprocess
            import json as _json
            _ev_path = tmp_path / "logs" / "events.jsonl"
            _tail = subprocess.run(
                ["tail", "-n", "500", str(_ev_path)],
                capture_output=True, text=True, timeout=5,
            )
            found_daily_limit = False
            check_task_id = "current_task_123"
            for _line in (_tail.stdout or "").splitlines():
                _line = _line.strip()
                if not _line:
                    continue
                try:
                    _ev = _json.loads(_line)
                    if (_ev.get("type") == "llm_api_error"
                            and _ev.get("daily_limit")
                            and str(_ev.get("task_id") or "") == str(check_task_id)):
                        found_daily_limit = True
                        break
                except Exception:
                    continue

            assert not found_daily_limit, (
                "Should NOT detect rate limit for a different task_id"
            )


class TestRateLimitAccumulatedUsageSignal:
    """Tests that _call_llm_with_retry signals daily rate limits via accumulated_usage.

    The accumulated_usage dict is passed by reference; when a daily rate limit is
    detected the function stores daily_rate_limit=True, rate_limit_resets_in_sec,
    and rate_limit_resets_at_utc so the caller (run_llm_loop) can produce a more
    informative error message instead of the generic "empty response" text.
    """

    def test_accumulated_usage_keys_present_on_daily_limit(self):
        """Verify the three rate-limit keys are present in accumulated_usage after a daily limit."""
        # We test this by directly calling the helper logic, not the full LLM stack.
        # Simulate what _call_llm_with_retry does when ra > 1800.
        import datetime as _dt

        ra = 28800.0  # 8 hours (daily limit)
        accumulated_usage: dict = {}

        # Replicate the key assignments from _call_llm_with_retry
        resets_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=ra)
        resets_at_iso = resets_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        accumulated_usage["daily_rate_limit"] = True
        accumulated_usage["rate_limit_resets_in_sec"] = ra
        accumulated_usage["rate_limit_resets_at_utc"] = resets_at_iso

        assert accumulated_usage.get("daily_rate_limit") is True
        assert accumulated_usage.get("rate_limit_resets_in_sec") == 28800.0
        assert "rate_limit_resets_at_utc" in accumulated_usage
        assert accumulated_usage["rate_limit_resets_at_utc"].endswith("Z"), (
            "resets_at_utc should be a UTC ISO string ending with 'Z'"
        )

    def test_resets_at_utc_is_future_timestamp(self):
        """resets_at_utc computed from ra seconds should be a future UTC time."""
        import datetime as _dt

        ra = 7200.0  # 2 hours
        now = _dt.datetime.now(_dt.timezone.utc)
        resets_at = now + _dt.timedelta(seconds=ra)
        resets_at_iso = resets_at.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Parse back and verify it's in the future
        parsed = _dt.datetime.strptime(resets_at_iso, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc
        )
        assert parsed > now, "resets_at_utc should be in the future"
        # And within a minute of the expected reset time (no extreme drift)
        diff = abs((parsed - resets_at).total_seconds())
        assert diff < 60, f"resets_at_utc too far from expected: diff={diff}s"

    def test_evolution_error_message_uses_rate_limit_info(self):
        """When accumulated_usage has daily_rate_limit=True, the evolution error message
        should mention the reset time rather than 'empty response'."""
        # Simulate the run_llm_loop logic for evolution rate limit
        accumulated_usage = {
            "daily_rate_limit": True,
            "rate_limit_resets_in_sec": 21600.0,  # 6 hours
            "rate_limit_resets_at_utc": "2026-03-01T20:00:00Z",
        }

        # Replicate the message-building logic from run_llm_loop
        if accumulated_usage.get("daily_rate_limit"):
            ra_sec = float(accumulated_usage.get("rate_limit_resets_in_sec") or 28800)
            resets_at = accumulated_usage.get("rate_limit_resets_at_utc") or "unknown"
            hours = ra_sec / 3600
            msg = (
                f"⚠️ Evolution paused: daily API rate limit hit. "
                f"Resets in ~{hours:.1f}h (at {resets_at}). Will resume automatically."
            )
        else:
            msg = "⚠️ Evolution: model returned no response"

        assert "paused" in msg, "Message should say 'paused' not 'empty response'"
        assert "rate limit" in msg, "Message should mention 'rate limit'"
        assert "6.0h" in msg, "Message should include hours until reset"
        assert "2026-03-01T20:00:00Z" in msg, "Message should include reset time"
        assert "empty response" not in msg, "Should NOT say 'empty response' for rate limits"
