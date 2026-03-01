"""Lazy singleton wrapper around mem0 Memory for Ouroboros.

Uses Gemini LLM + embeddings — no OpenAI key required.
Falls back gracefully if mem0 is not installed or GOOGLE_API_KEY is missing.
"""

from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)

_instance: Optional["Mem0Client"] = None


def get_mem0_client() -> Optional["Mem0Client"]:
    """Return singleton Mem0Client, or None if unavailable."""
    global _instance
    if _instance is None:
        try:
            _instance = Mem0Client()
        except Exception as e:
            log.warning(f"mem0 init failed (will run without long-term memory): {e}")
            return None
    return _instance


class Mem0Client:
    """Thin wrapper around mem0.Memory with Gemini backend."""

    def __init__(self) -> None:
        from mem0 import Memory
        from ouroboros.mem0_config import get_mem0_config
        self._mem = Memory.from_config(get_mem0_config())
        log.info("mem0 initialized with Gemini backend (LLM=gemini-2.5-flash, embed=text-embedding-004)")

    def remember(self, content: str, category: str = "general") -> bool:
        """Save a fact/lesson to long-term semantic memory."""
        try:
            self._mem.add(content, user_id="ouroboros", metadata={"category": category})
            return True
        except Exception as e:
            log.warning(f"mem0.remember failed: {e}")
            return False

    def recall(self, query: str, limit: int = 8) -> str:
        """Retrieve relevant memories for a given query. Returns formatted string."""
        try:
            results = self._mem.search(query, user_id="ouroboros", limit=limit)
            if not results or not results.get("results"):
                return ""
            memories = [r["memory"] for r in results["results"] if r.get("memory")]
            return "\n".join(f"- {m}" for m in memories)
        except Exception as e:
            log.warning(f"mem0.recall failed: {e}")
            return ""

    def recall_all(self, limit: int = 30) -> str:
        """Get all stored memories (for boot/orientation)."""
        try:
            results = self._mem.get_all(user_id="ouroboros")
            if not results or not results.get("results"):
                return ""
            memories = [r["memory"] for r in results["results"][:limit] if r.get("memory")]
            return "\n".join(f"- {m}" for m in memories)
        except Exception as e:
            log.warning(f"mem0.recall_all failed: {e}")
            return ""
