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
