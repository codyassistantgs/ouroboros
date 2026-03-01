"""mem0 configuration for Ouroboros — uses Gemini backend (no OpenAI required)."""

from __future__ import annotations
import os


def get_mem0_config() -> dict:
    api_key = os.environ.get("GOOGLE_API_KEY", "")
    return {
        "llm": {
            "provider": "gemini",
            "config": {
                "model": "gemini-2.5-flash",
                "api_key": api_key,
                "temperature": 0.1,
            }
        },
        "embedder": {
            "provider": "gemini",
            "config": {
                "model": "models/text-embedding-004",
                "api_key": api_key,
            }
        },
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "ouroboros_memory",
                "path": "/data/memory/chroma",
            }
        },
        "history_db_path": "/data/memory/mem0_history.db",
        "version": "v1.1",
    }
