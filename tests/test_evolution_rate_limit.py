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
