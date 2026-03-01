"""Unit tests for consciousness.py retry-on-GOOGLE_API_KEY-error behaviour.

These tests focus on the resilience logic introduced in v7.1.20:
- _safe_fallback_model() always returns a non-Google model
- _is_google_model() correctly classifies model names
- BackgroundConsciousness._think() retries with fallback model when the
  primary call fails with a GOOGLE_API_KEY error, so that
  ``consciousness_llm_error`` is never emitted when the retry succeeds.

Run: python -m pytest tests/test_consciousness_retry.py -v
"""
from __future__ import annotations

import pathlib
import tempfile
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# Helper-function unit tests (no I/O required)
# ---------------------------------------------------------------------------

from ouroboros.consciousness import _is_google_model, _safe_fallback_model


class TestIsGoogleModel:
    """_is_google_model() classification."""

    def test_google_prefix(self):
        assert _is_google_model("google/gemini-2.5-flash")

    def test_gemini_prefix(self):
        assert _is_google_model("gemini-1.5-pro")
        assert _is_google_model("gemini-2.0-flash")

    def test_anthropic_not_google(self):
        assert not _is_google_model("anthropic/claude-haiku-4-5")
        assert not _is_google_model("anthropic/claude-sonnet-4.6")

    def test_openai_not_google(self):
        assert not _is_google_model("openai/gpt-4o-mini")

    def test_empty_string(self):
        assert not _is_google_model("")


class TestSafeFallbackModel:
    """_safe_fallback_model() never returns a Google model."""

    def test_returns_non_google_when_ouroboros_model_not_set(self):
        import os
        old = os.environ.pop("OUROBOROS_MODEL", None)
        try:
            result = _safe_fallback_model()
            assert not _is_google_model(result), (
                f"_safe_fallback_model() returned a Google model: {result!r}"
            )
        finally:
            if old is not None:
                os.environ["OUROBOROS_MODEL"] = old

    def test_returns_non_google_when_ouroboros_model_is_google(self):
        import os
        old = os.environ.get("OUROBOROS_MODEL")
        try:
            os.environ["OUROBOROS_MODEL"] = "google/gemini-2.5-flash"
            result = _safe_fallback_model()
            assert not _is_google_model(result), (
                f"_safe_fallback_model() returned a Google model: {result!r}"
            )
        finally:
            if old is None:
                os.environ.pop("OUROBOROS_MODEL", None)
            else:
                os.environ["OUROBOROS_MODEL"] = old

    def test_returns_ouroboros_model_when_non_google(self):
        import os
        old = os.environ.get("OUROBOROS_MODEL")
        try:
            os.environ["OUROBOROS_MODEL"] = "anthropic/claude-haiku-4-5"
            result = _safe_fallback_model()
            assert result == "anthropic/claude-haiku-4-5"
        finally:
            if old is None:
                os.environ.pop("OUROBOROS_MODEL", None)
            else:
                os.environ["OUROBOROS_MODEL"] = old


# ---------------------------------------------------------------------------
# Retry behaviour: _think() retries immediately on GOOGLE_API_KEY error
# ---------------------------------------------------------------------------

def _make_consciousness(tmp_path: pathlib.Path):
    """Build a BackgroundConsciousness with a mocked LLM client."""
    from ouroboros.consciousness import BackgroundConsciousness

    bc = BackgroundConsciousness(
        drive_root=tmp_path,
        repo_dir=tmp_path,
        event_queue=None,
        owner_chat_id_fn=lambda: None,
    )
    # Ensure logs/ directory exists so append_jsonl works
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)
    return bc


class TestThinkRetryOnGoogleError:
    """_think() retries with a fallback model on GOOGLE_API_KEY error."""

    def test_retry_succeeds_no_error_logged(self):
        """When primary call fails with GOOGLE_API_KEY error but retry succeeds,
        consciousness_llm_error must NOT be logged to events.jsonl."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            bc = _make_consciousness(tmp_path)

            # Patch the LLM client:
            # - First call raises GOOGLE_API_KEY error
            # - Subsequent calls return a valid empty response
            google_err = Exception(
                "InternalServerError(\"Error code: 500 - {'detail': 'GOOGLE_API_KEY not configured'}\")"
            )
            ok_response = (
                {"content": "All good.", "tool_calls": []},
                {"cost": 0.0, "prompt_tokens": 10, "completion_tokens": 5},
            )
            bc._llm.chat = MagicMock(side_effect=[google_err, ok_response])

            # Patch _build_context to avoid file-system reads beyond tmp_path
            bc._build_context = MagicMock(return_value="system context")
            bc._tool_schemas = MagicMock(return_value=[])
            bc._maybe_schedule_arch_review = MagicMock()

            # Run _think() — should retry once and complete successfully
            bc._think()

            # The LLM was called twice (primary + retry)
            assert bc._llm.chat.call_count == 2

            # No consciousness_llm_error should have been logged
            events_path = tmp_path / "logs" / "events.jsonl"
            if events_path.exists():
                import json
                events = [
                    json.loads(line)
                    for line in events_path.read_text().splitlines()
                    if line.strip()
                ]
                error_events = [e for e in events if e.get("type") == "consciousness_llm_error"]
                assert len(error_events) == 0, (
                    f"consciousness_llm_error was logged even though retry succeeded: {error_events}"
                )

            # The model_override should have been set to a non-Google model
            assert bc._model_override is not None
            assert not _is_google_model(bc._model_override), (
                f"model_override is still a Google model: {bc._model_override!r}"
            )

    def test_retry_fails_error_is_logged(self):
        """When both primary and retry calls fail, consciousness_llm_error IS logged."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = pathlib.Path(tmp)
            bc = _make_consciousness(tmp_path)

            google_err = Exception(
                "InternalServerError(\"Error code: 500 - {'detail': 'GOOGLE_API_KEY not configured'}\")"
            )
            bc._llm.chat = MagicMock(side_effect=[google_err, google_err])
            bc._build_context = MagicMock(return_value="context")
            bc._tool_schemas = MagicMock(return_value=[])
            bc._maybe_schedule_arch_review = MagicMock()

            bc._think()

            # Both calls should have been made
            assert bc._llm.chat.call_count == 2

            events_path = tmp_path / "logs" / "events.jsonl"
            assert events_path.exists(), "events.jsonl should have been created"
            import json
            events = [
                json.loads(line)
                for line in events_path.read_text().splitlines()
                if line.strip()
            ]
            error_events = [e for e in events if e.get("type") == "consciousness_llm_error"]
            assert len(error_events) >= 1, (
                "consciousness_llm_error should be logged when retry also fails"
            )
