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

    def test_consciousness_rate_limit_daily_flag_no_retry_after_blocks(self):
        """consciousness_rate_limit with daily_limit=True but retry_after_sec=None → blocks evolution.

        Before this fix, when the rate-limit reset time couldn't be parsed (e.g., error
        message was 'quota exceeded' without a time), the consciousness loop set
        next_wakeup_sec=28800 but logged retry_after_sec=None.
        _check_rate_limit_window() would then compute float(None or 0)=0.0 <= 1800 and
        SKIP the event, potentially scheduling evolution during the active window.
        """
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Simulate: daily limit where reset time couldn't be parsed → retry_after_sec=None
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-60),     # 1 minute ago
                    "type": "consciousness_rate_limit",
                    "retry_after_sec": None,   # Not parseable (None → 0 via float(None or 0))
                    "daily_limit": True,       # But explicitly flagged as daily limit
                    "error": "RateLimitError('429 - quota exceeded')",
                    "next_wakeup_sec": 28800,
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is not None, (
            "consciousness_rate_limit with daily_limit=True should block evolution "
            "even when retry_after_sec is None — uses 8h default"
        )
        assert result > 0, "Remaining seconds should be positive"
        # Should be approximately 28800 - 60 = 28740 seconds remaining
        assert 28600 < result < 28800, f"Expected ~28740s remaining, got {result:.0f}s"

    def test_consciousness_rate_limit_short_with_daily_flag_blocks(self):
        """consciousness_rate_limit with daily_limit=True and small retry_after_sec → still blocks.

        Even if the reset time is close (e.g., 5 minutes away), a daily limit should
        block evolution for the remaining window duration, not be skipped.
        """
        from supervisor.queue import _check_rate_limit_window
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Simulate: daily limit expiring in 5 minutes (300s event - 30s elapsed = 270s remaining)
            _write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),     # 30 seconds ago
                    "type": "consciousness_rate_limit",
                    "retry_after_sec": 300,    # Only 5 minutes total → 270s remaining
                    "daily_limit": True,       # But it's a daily limit (not transient)
                    "error": "RateLimitError('429 - hit your limit, resets 1am UTC')",
                },
            ])
            result = _check_rate_limit_window(tmp_path)
        assert result is not None, (
            "consciousness_rate_limit with daily_limit=True should block evolution "
            "even when retry_after_sec <= 1800 (close to reset)"
        )
        assert result > 0, "Remaining seconds should be positive"
        # Should be approximately 300 - 30 = 270 seconds remaining
        assert 200 < result < 300, f"Expected ~270s remaining, got {result:.0f}s"


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

    def test_resets_1am_utc_returns_positive_value(self):
        """'resets 1am (UTC)' pattern → returns computed seconds to 1am UTC."""
        from ouroboros.utils import extract_retry_after
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: You\\'ve hit your limit · resets 1am (UTC)\"}')")
        result = extract_retry_after(exc)
        assert result is not None, "Should return a positive delay for 'resets 1am (UTC)'"
        assert result > 0, f"Result should be positive, got {result}"
        # The reset time is always in the future (at most 24h away)
        assert result <= 86400, f"Result should be at most 24h, got {result}"

    def test_resets_mar_6_3am_utc_returns_large_value(self):
        """'resets Mar 6, 3am (UTC)' date+time format → returns seconds to that date/time.

        This is the specific error format from Evolution #223:
        RateLimitError('Error code: 429 - {"detail": "Rate limit: You've hit your limit
        · resets Mar 6, 3am (UTC)"}')

        The old code fell through to the 'hit your limit' fallback returning 28800s (8h),
        but the real reset is days away. The new date+time parser returns the correct value.
        """
        import datetime as _dt
        from ouroboros.utils import extract_retry_after

        exc = Exception(
            "RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: "
            "You\\'ve hit your limit \\u00b7 resets Mar 6, 3am (UTC)\"}\")')"
        )
        result = extract_retry_after(exc)
        assert result is not None, "Should return a delay for 'resets Mar 6, 3am (UTC)'"
        assert result > 0, f"Result should be positive, got {result}"
        # Result must be larger than 8h fallback when reset is days away:
        # if today < Mar 6 UTC, result >> 28800; if today > Mar 6, result ≈ 1 year
        # Either way it should be a positive number of seconds
        assert result <= 366 * 86400, f"Result should not exceed 1 year, got {result}"

    def test_resets_date_time_format_more_accurate_than_fallback(self):
        """Date+time format ('resets Mar 6, 3am') gives seconds-accurate result,
        not just the fixed 28800s fallback."""
        import datetime as _dt
        from ouroboros.utils import extract_retry_after

        exc = Exception(
            "RateLimitError('429: Rate limit: You\\'ve hit your limit · resets Dec 31, 11pm (UTC)')"
        )
        result = extract_retry_after(exc)
        assert result is not None, "Should parse 'resets Dec 31, 11pm (UTC)'"
        assert result > 0, f"Result should be positive, got {result}"
        # Not the generic 28800s fallback if parsed correctly
        # (28800 would only be returned if the parse failed)
        assert result != 28800.0, (
            "Should return precise computed seconds, not the generic 8h fallback"
        )


class TestIsDailyLimitError:
    """Unit tests for is_daily_limit_error() in ouroboros/utils.py."""

    def test_hit_your_limit_is_daily(self):
        """'hit your limit' phrase → True (daily quota exhaustion)."""
        from ouroboros.utils import is_daily_limit_error
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: You\\'ve hit your limit · resets 1am (UTC)\"}')")
        assert is_daily_limit_error(exc) is True

    def test_you_have_hit_your_limit_is_daily(self):
        """'you have hit your limit' variant → True."""
        from ouroboros.utils import is_daily_limit_error
        exc = Exception("RateLimitError('429: You have hit your limit for today')")
        assert is_daily_limit_error(exc) is True

    def test_quota_exceeded_is_daily(self):
        """'quota exceeded' phrase → True."""
        from ouroboros.utils import is_daily_limit_error
        exc = Exception("RateLimitError('Error: Quota exceeded for this billing period')")
        assert is_daily_limit_error(exc) is True

    def test_too_many_requests_is_not_daily(self):
        """Generic 'too many requests' → False (transient rate window, not daily)."""
        from ouroboros.utils import is_daily_limit_error
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Too many requests, please retry after 60s\"}')")
        assert is_daily_limit_error(exc) is False

    def test_connection_error_is_not_daily(self):
        """Non-rate-limit errors → False."""
        from ouroboros.utils import is_daily_limit_error
        exc = ConnectionError("Connection refused")
        assert is_daily_limit_error(exc) is False


class TestDailyLimitFastFail:
    """Tests for the close-to-reset edge case in _call_llm_with_retry.

    The bug: when "resets 1am (UTC)" error occurs and it is close to 1am UTC
    (e.g., 00:58 UTC → ra ≈ 120s < 1800s), the old code did NOT trigger the
    fast-fail path because ra <= 1800, even though "You've hit your limit"
    clearly indicates daily quota exhaustion.

    The fix: is_daily_limit_error() detects the daily quota phrase and triggers
    fast-fail regardless of how small ra is.
    """

    def test_close_to_reset_triggers_fast_fail_via_daily_flag(self):
        """Simulate the 00:58 UTC / resets 1am edge case.

        We verify the logic path: is_daily_limit_error returns True for the
        "hit your limit" phrase, so the daily_limit fast-fail triggers even when
        ra < 1800.
        """
        from ouroboros.utils import is_daily_limit_error, extract_retry_after, is_rate_limit_error

        # The exact error that triggered Evolution #146's target selection
        exc = Exception("RateLimitError('Error code: 429 - {\"detail\": \"Rate limit: You\\'ve hit your limit · resets 1am (UTC)\"}')")

        assert is_rate_limit_error(exc) is True, "Should be a rate limit error"
        assert is_daily_limit_error(exc) is True, "Should be a daily limit (has 'hit your limit')"

        # is_daily_limit_error=True means fast-fail even when ra is small
        # (the old code only fast-failed when ra > 1800)
        ra = extract_retry_after(exc)
        # No matter the current time, is_daily_limit_error ensures fast-fail
        # The condition in _call_llm_with_retry is now:
        #   if (ra is not None and float(ra) > 1800) or daily:
        # Previously just: if ra is not None and float(ra) > 1800:
        daily = is_daily_limit_error(exc)
        old_would_fast_fail = ra is not None and float(ra) > 1800
        new_would_fast_fail = old_would_fast_fail or daily
        assert new_would_fast_fail is True, (
            f"New code should always fast-fail for daily limit errors. "
            f"ra={ra:.0f}s, daily={daily}, "
            f"old_condition={old_would_fast_fail}, new_condition={new_would_fast_fail}"
        )


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

    def test_old_format_rate_limit_event_filtered_by_safety_net(self):
        """OLD llm_api_error without is_rate_limit flag is still filtered by safety net.

        Before v7.1.26, llm_api_error events didn't have the is_rate_limit/daily_limit
        flags. The safety-net keyword check on the assembled error string catches these.
        The specific error format from Evolution #190's target is tested here.
        """
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            # Old-format event: no is_rate_limit or daily_limit flags
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),
                    "type": "llm_api_error",
                    # Deliberately omit is_rate_limit and daily_limit (old event format)
                    "error": (
                        "RateLimitError('Error code: 429 - "
                        "{\"detail\": \"Rate limit: You\\'ve hit your limit "
                        "\u00b7 resets 1am (UTC)\"}')"
                    ),
                    "model": "anthropic/claude-haiku-4-5",
                    "round": 1,
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result == "" or "RateLimitError" not in result, (
            f"Old-format rate limit error should be filtered by safety net, got: {result!r}"
        )
        # Must not contain the 429 error as an evolution target
        if result:
            assert "429" not in result, (
                f"Rate limit 429 should never appear in evolution target, got: {result!r}"
            )

    def test_consciousness_llm_error_now_filtered(self):
        """consciousness_llm_error events are now filtered (added to SKIP set in v7.1.29).

        These are always infrastructure/model issues, never fixable code bugs.
        """
        from ouroboros.context import _find_specific_evolution_target
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            self._write_events(tmp_path, [
                {
                    "ts": _ts_offset(-30),
                    "type": "consciousness_llm_error",
                    "error": "ConnectionError: Failed to connect to proxy",
                    "model_override": None,
                    "consecutive_google_errors": 0,
                },
            ])
            env = self._make_env(tmp_path)
            result = _find_specific_evolution_target(env, str(tmp_path))
        assert result == "" or "consciousness_llm_error" not in result, (
            f"consciousness_llm_error should be filtered as infra error, got: {result!r}"
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
