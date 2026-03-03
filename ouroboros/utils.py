"""
Ouroboros — Shared utilities.

Single source for helper functions used across all modules.
Does not import anything from ouroboros.* (zero dependency level).
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import logging
import os
import pathlib
import subprocess
import time
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Time
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def sha256_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# File I/O
# ---------------------------------------------------------------------------

def read_text(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def write_text(path: pathlib.Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def append_jsonl(path: pathlib.Path, obj: Dict[str, Any]) -> None:
    """Append a JSON object as a line to a JSONL file (concurrent-safe)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(obj, ensure_ascii=False)
    data = (line + "\n").encode("utf-8")

    lock_timeout_sec = 2.0
    lock_stale_sec = 10.0
    lock_sleep_sec = 0.01
    write_retries = 3
    retry_sleep_base_sec = 0.01

    path_hash = hashlib.sha256(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
    lock_path = path.parent / f".append_jsonl_{path_hash}.lock"
    lock_fd = None
    lock_acquired = False

    try:
        start = time.time()
        while time.time() - start < lock_timeout_sec:
            try:
                lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
                lock_acquired = True
                break
            except FileExistsError:
                try:
                    stat = lock_path.stat()
                    if time.time() - stat.st_mtime > lock_stale_sec:
                        lock_path.unlink()
                        continue
                except Exception:
                    log.debug("Failed to read lock stat during lock acquisition retry", exc_info=True)
                    pass
                time.sleep(lock_sleep_sec)
            except Exception:
                log.debug("Failed to acquire file lock for jsonl append", exc_info=True)
                break

        for attempt in range(write_retries):
            try:
                fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
                try:
                    os.write(fd, data)
                finally:
                    os.close(fd)
                return
            except Exception:
                if attempt < write_retries - 1:
                    time.sleep(retry_sleep_base_sec * (2 ** attempt))

        for attempt in range(write_retries):
            try:
                with path.open("a", encoding="utf-8") as f:
                    f.write(line + "\n")
                return
            except Exception:
                if attempt < write_retries - 1:
                    time.sleep(retry_sleep_base_sec * (2 ** attempt))
    except Exception:
        log.warning("append_jsonl: all write attempts failed for %s", path, exc_info=True)
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except Exception:
                log.debug("Failed to close lock fd after jsonl append", exc_info=True)
                pass
        if lock_acquired:
            try:
                lock_path.unlink()
            except Exception:
                log.debug("Failed to unlink lock file after jsonl append", exc_info=True)
                pass


# ---------------------------------------------------------------------------
# Path safety
# ---------------------------------------------------------------------------

def safe_relpath(p: str) -> str:
    p = p.replace("\\", "/").lstrip("/")
    if ".." in pathlib.PurePosixPath(p).parts:
        raise ValueError("Path traversal is not allowed.")
    return p


# ---------------------------------------------------------------------------
# Text helpers
# ---------------------------------------------------------------------------

def truncate_for_log(s: str, max_chars: int = 4000) -> str:
    if len(s) <= max_chars:
        return s
    return s[: max_chars // 2] + "\n...\n" + s[-max_chars // 2:]


def clip_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    half = max(200, max_chars // 2)
    return text[:half] + "\n...(truncated)...\n" + text[-half:]


def short(s: Any, n: int = 120) -> str:
    t = str(s or "")
    return t[:n] + "..." if len(t) > n else t


def estimate_tokens(text: str) -> int:
    """Rough token estimate (chars/4 heuristic)."""
    return max(1, (len(str(text or "")) + 3) // 4)


# ---------------------------------------------------------------------------
# Subprocess
# ---------------------------------------------------------------------------

def run_cmd(cmd: List[str], cwd: Optional[pathlib.Path] = None) -> str:
    res = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\n\nSTDOUT:\n{res.stdout}\n\nSTDERR:\n{res.stderr}"
        )
    return res.stdout.strip()


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

def get_git_info(repo_dir: pathlib.Path) -> tuple[str, str]:
    """Best-effort retrieval of (git_branch, git_sha)."""
    branch = ""
    sha = ""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            branch = r.stdout.strip()
    except Exception:
        log.debug("Failed to get git branch", exc_info=True)
        pass
    try:
        r = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir), capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0:
            sha = r.stdout.strip()
    except Exception:
        log.debug("Failed to get git SHA", exc_info=True)
        pass
    return branch, sha


# ---------------------------------------------------------------------------
# Sanitization helpers (for logging)
# ---------------------------------------------------------------------------

def sanitize_task_for_event(
    task: Dict[str, Any], drive_logs: pathlib.Path, threshold: int = 4000,
) -> Dict[str, Any]:
    """Sanitize task dict for event logging: truncate large text, strip base64 images, persist full text."""
    try:
        sanitized = task.copy()

        # Strip all keys ending with _base64 (images, etc.)
        keys_to_strip = [k for k in sanitized.keys() if k.endswith("_base64")]
        for key in keys_to_strip:
            value = sanitized.pop(key)
            # Record that it was present and its size
            sanitized[f"{key}_present"] = True
            if isinstance(value, str):
                sanitized[f"{key}_len"] = len(value)

        text = task.get("text")
        if not isinstance(text, str):
            return sanitized

        text_len = len(text)
        text_hash = sha256_text(text)
        sanitized["text_len"] = text_len
        sanitized["text_sha256"] = text_hash

        if text_len > threshold:
            sanitized["text"] = truncate_for_log(text, threshold)
            sanitized["text_truncated"] = True
            try:
                task_id = task.get("id")
                filename = f"task_{task_id}.txt" if task_id else f"task_{text_hash[:12]}.txt"
                full_path = drive_logs / "tasks" / filename
                write_text(full_path, text)
                sanitized["text_full_path"] = f"tasks/{filename}"
            except Exception:
                log.debug("Failed to persist full task text to Drive during sanitization", exc_info=True)
                pass
        else:
            sanitized["text_truncated"] = False

        return sanitized
    except Exception:
        return task


_SECRET_KEYS = frozenset([
    "token", "api_key", "apikey", "authorization", "secret", "password", "passwd", "passphrase",
])

# Patterns that indicate leaked secrets in tool output
import re as _re
_SECRET_PATTERNS = _re.compile(
    r'ghp_[A-Za-z0-9]{30,}'       # GitHub personal access token
    r'|sk-ant-[A-Za-z0-9\-]{30,}' # Anthropic API key
    r'|sk-or-[A-Za-z0-9\-]{30,}'  # OpenRouter API key
    r'|gsk_[A-Za-z0-9]{30,}'      # Groq API key
    r'|sk-[A-Za-z0-9]{40,}'       # OpenAI API key
    r'|\b[0-9]{8,}:[A-Za-z0-9_\-]{30,}\b'  # Telegram bot token (digits:alphanum)
)


def sanitize_tool_result_for_log(result: str) -> str:
    """Redact potential secrets from tool result before logging."""
    if not isinstance(result, str) or len(result) < 20:
        return result
    return _SECRET_PATTERNS.sub("***REDACTED***", result)


def sanitize_tool_args_for_log(
    fn_name: str, args: Dict[str, Any], threshold: int = 3000,
) -> Dict[str, Any]:
    """Sanitize tool arguments for logging: redact secrets, truncate large fields."""

    def _sanitize_value(key: str, value: Any, depth: int) -> Any:
        if depth > 3:
            return {"_depth_limit": True}
        if key.lower() in _SECRET_KEYS:
            return "*** REDACTED ***"
        if isinstance(value, str) and len(value) > threshold:
            return {
                key: truncate_for_log(value, threshold),
                f"{key}_len": len(value),
                f"{key}_sha256": sha256_text(value),
                f"{key}_truncated": True,
            }
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return {k: _sanitize_value(k, v, depth + 1) for k, v in value.items()}
        if isinstance(value, list):
            sanitized = [_sanitize_value(key, item, depth + 1) for item in value[:50]]
            if len(value) > 50:
                sanitized.append({"_truncated": f"... {len(value) - 50} more items"})
            return sanitized
        try:
            json.dumps(value, ensure_ascii=False)
            return value
        except (TypeError, ValueError):
            log.debug("Failed to JSON serialize value in sanitize_tool_args", exc_info=True)
            return {"_repr": repr(value)}

    try:
        return {k: _sanitize_value(k, v, 0) for k, v in args.items()}
    except Exception:
        log.debug("Failed to sanitize tool arguments for logging", exc_info=True)
        try:
            return json.loads(json.dumps(args, ensure_ascii=False, default=str))
        except Exception:
            log.debug("Tool argument sanitization failed completely", exc_info=True)
            return {"_error": "sanitization_failed"}


def get_budget_remaining(state_data: Dict[str, Any]) -> Optional[float]:
    """Get budget remaining from state data (OpenRouter API is the single source of truth).

    Returns remaining USD or None if OpenRouter limit not yet fetched.
    """
    or_remaining = state_data.get("openrouter_limit_remaining")
    if or_remaining is not None:
        return float(or_remaining)
    return None


# ---------------------------------------------------------------------------
# Rate limit helpers
# ---------------------------------------------------------------------------

def extract_retry_after(exc: Exception) -> Optional[float]:
    """Extract Retry-After delay (seconds) from a rate-limit exception.

    Checks (in order):
    1. .response.headers["retry-after"] (openai SDK httpx response)
    2. Regex patterns in repr(exc) for common Retry-After formats
    3. Wall-clock reset times like "resets 8pm (UTC)" or "resets 20:00 UTC"
    Returns None if no delay hint found (caller should use default backoff).
    """
    import re as _re

    response = getattr(exc, "response", None)
    if response is not None:
        headers = getattr(response, "headers", {}) or {}
        raw = (headers.get("retry-after")
               or headers.get("Retry-After")
               or headers.get("x-ratelimit-reset-requests"))
        if raw:
            try:
                return float(raw)
            except (ValueError, TypeError):
                pass

    error_str = repr(exc)
    for pattern in (
        r"retry.?after['\s:]+(\d+(?:\.\d+)?)",
        r"reset.?in['\s:]+(\d+(?:\.\d+)?)\s*s",
        r"x-ratelimit-reset-requests['\s:]+(\d+(?:\.\d+)?)",
    ):
        m = _re.search(pattern, error_str, _re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                pass

    # Parse wall-clock reset times: "resets 8pm (UTC)", "resets 11pm (UTC)"
    m = _re.search(r"resets\s+(\d{1,2})\s*(am|pm)\s*\(?UTC\)?", error_str, _re.IGNORECASE)
    if m:
        try:
            hour = int(m.group(1))
            period = m.group(2).lower()
            if period == "pm" and hour != 12:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            now_utc = _dt.datetime.now(_dt.timezone.utc)
            reset_time = now_utc.replace(hour=hour, minute=0, second=0, microsecond=0)
            if reset_time <= now_utc:
                reset_time += _dt.timedelta(days=1)
            return (reset_time - now_utc).total_seconds()
        except (ValueError, TypeError):
            pass

    # Parse 24h wall-clock reset times: "resets 20:00 UTC", "resets 23:00 (UTC)"
    m = _re.search(r"resets\s+(\d{1,2}):(\d{2})\s*\(?UTC\)?", error_str, _re.IGNORECASE)
    if m:
        try:
            hour = int(m.group(1))
            minute = int(m.group(2))
            now_utc = _dt.datetime.now(_dt.timezone.utc)
            reset_time = now_utc.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if reset_time <= now_utc:
                reset_time += _dt.timedelta(days=1)
            return (reset_time - now_utc).total_seconds()
        except (ValueError, TypeError):
            pass

    # Parse date+time reset: "resets Mar 6, 3am (UTC)", "resets Dec 31, 11pm (UTC)"
    # This format appears when the reset is days away (e.g. weekly/monthly quota resets).
    # Without this parser, the "hit your limit" fallback only returns 8 hours, causing
    # repeated retries when the actual reset is multiple days in the future.
    m = _re.search(
        r"resets\s+([A-Za-z]{3,9})\s+(\d{1,2}),\s*(\d{1,2})\s*(am|pm)\s*\(?UTC\)?",
        error_str, _re.IGNORECASE,
    )
    if m:
        try:
            import calendar as _cal
            month_str = m.group(1)[:3].lower()
            _month_abbrs = {mn.lower(): i for i, mn in enumerate(_cal.month_abbr) if mn}
            month_num = _month_abbrs.get(month_str)
            if month_num:
                day = int(m.group(2))
                hour = int(m.group(3))
                period = m.group(4).lower()
                if period == "pm" and hour != 12:
                    hour += 12
                elif period == "am" and hour == 12:
                    hour = 0
                now_utc = _dt.datetime.now(_dt.timezone.utc)
                reset_time = now_utc.replace(
                    month=month_num, day=day, hour=hour, minute=0, second=0, microsecond=0
                )
                if reset_time <= now_utc:
                    reset_time = reset_time.replace(year=now_utc.year + 1)
                return (reset_time - now_utc).total_seconds()
        except (ValueError, TypeError):
            pass

    # Final fallback: daily quota exhaustion phrases.
    # These appear in OpenRouter/Anthropic/Groq rate limit errors when a specific
    # reset time is absent or the above patterns failed to match (e.g. the error
    # was deeply nested in quotes/repr).  All phrases here are also matched by
    # is_daily_limit_error(), so we keep them in sync: every phrase that signals
    # a daily limit should return a non-None delay so callers always get a
    # meaningful backoff value rather than falling through to None.
    # Return 8 hours as a conservative default — better than returning None and
    # treating it as a transient error that should be retried in seconds.
    error_lower = error_str.lower()
    if any(phrase in error_lower for phrase in (
        "hit your limit",
        "you have hit your limit",
        "quota exceeded",
        "daily limit",
        "daily quota",
        "exceeded your",
    )):
        return 28800.0  # 8 hours

    return None


def is_rate_limit_error(exc: Exception) -> bool:
    """Return True if the exception looks like an HTTP 429 rate-limit error."""
    error_str = repr(exc)
    return (
        "429" in error_str
        or "RateLimitError" in type(exc).__name__
        or "rate limit" in error_str.lower()
        or "too many requests" in error_str.lower()
    )


# Phrases that indicate a DAILY quota exhaustion (not just a transient rate window).
# These appear when the API has exhausted the user's daily token/request limit,
# as opposed to per-minute/per-hour windows that resolve quickly.
_DAILY_LIMIT_PHRASES = (
    "hit your limit",
    "you have hit your limit",
    "quota exceeded",
    "daily limit",
    "daily quota",
    "exceeded your",
)


def persist_daily_rate_limit_reset(
    drive_root: pathlib.Path,
    task_id: str,
    resets_in_sec: float,
) -> str:
    """Persist daily rate-limit reset time to state.json; returns ISO reset timestamp.

    Writes ``daily_rate_limit_reset_at_utc`` so container restarts during a
    multi-day window don't lose the rate-limit knowledge and re-queue evolution.
    """
    resets_at = _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(seconds=resets_in_sec)
    resets_at_iso = resets_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        state_path = drive_root / "state" / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        st: dict = {}
        if state_path.exists():
            try:
                st = json.loads(state_path.read_text(encoding="utf-8"))
            except Exception:
                st = {}
        st["daily_rate_limit_reset_at_utc"] = resets_at_iso
        tmp = state_path.with_name(f".state.json.rl.{task_id}.tmp")
        tmp.write_text(json.dumps(st, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(state_path))
        log.info("Persisted daily rate limit reset %s to state.json (task %s)", resets_at_iso, task_id)
    except Exception:
        log.debug("Failed to persist daily rate limit reset to state.json", exc_info=True)
    return resets_at_iso


def is_transient_server_error(exc: Exception) -> bool:
    """Return True if the exception is a transient 5xx server/gateway error.

    Detects proxy and upstream timeout errors (504), bad gateway (502), and
    service unavailable (503) responses.  These are temporary infrastructure
    problems that warrant retry with longer delays, but should NOT be treated
    as rate limits or returned as evolution targets.

    Examples:
    - InternalServerError("Error code: 504 - {'detail': 'Claude CLI timeout'}")
    - InternalServerError("Error code: 502 - {'detail': 'Bad Gateway'}")
    - InternalServerError("Error code: 503 - {'detail': 'Service Unavailable'}")
    """
    error_str = repr(exc)
    error_lower = error_str.lower()
    return (
        "504" in error_str
        or "502" in error_str
        or "503" in error_str
        or "claude cli timeout" in error_lower
        or "gateway timeout" in error_lower
        or "bad gateway" in error_lower
        or "service unavailable" in error_lower
        or "upstream connect error" in error_lower
    )


def is_daily_limit_error(exc: Exception) -> bool:
    """Return True if the exception indicates a daily API quota exhaustion.

    Distinguishes *daily* limits (full quota for the day used up) from transient
    *rate-window* limits (too many requests per minute/hour).  Daily limits should
    trigger an immediate fail-fast even when the reset time is close (e.g.,
    "resets 1am (UTC)" with only 2 minutes remaining), because:

    - The worker should not block for 2+ minutes waiting to retry.
    - The next evolution cycle will naturally retry after the reset.
    - Spinning retries wastes budget and log space.

    Examples of daily limit messages:
    - "Rate limit: You've hit your limit · resets 1am (UTC)"
    - "You have hit your limit for today"
    - "Quota exceeded for the day"
    """
    error_lower = repr(exc).lower()
    return any(phrase in error_lower for phrase in _DAILY_LIMIT_PHRASES)
