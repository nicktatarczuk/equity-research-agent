"""
Gemini LLM client wrapper with retry logic.

Why retry: Gemini's free tier limits us to 5 calls per minute. Even with
prompt consolidation, transient rate limits, network blips, or burst traffic
can still trigger a 429. We retry up to 3 times with exponential backoff.
"""
from __future__ import annotations

import logging
import os
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)


def get_llm(temperature: float = 0.3, model_override: str | None = None) -> ChatGoogleGenerativeAI:
    """Return a configured Gemini chat model. Pass model_override to use a different model for one call."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Get one free at https://aistudio.google.com/apikey"
        )
    model = model_override or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=4096,  # Bumped up - the combined research call needs more room
    )


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect Gemini rate-limit (429) errors across the various ways they manifest."""
    s = str(exc).lower()
    return any(k in s for k in ["429", "rate", "quota", "resource_exhausted", "exhausted"])


def call_llm(
    system_prompt: str,
    user_prompt: str,
    temperature: float = 0.3,
    model_override: str | None = None,
    max_retries: int = 3,
) -> str:
    """
    One-shot call: system + user prompt -> string response.
    Retries on rate limit errors with exponential backoff (15s, 30s, 60s).
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            llm = get_llm(temperature=temperature, model_override=model_override)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            response = llm.invoke(messages)
            return response.content if hasattr(response, "content") else str(response)
        except Exception as e:
            last_exc = e
            if _is_rate_limit_error(e) and attempt < max_retries - 1:
                wait = 15 * (2 ** attempt)  # 15s, 30s, 60s
                logger.warning(f"Gemini rate limited (attempt {attempt + 1}/{max_retries}). Waiting {wait}s...")
                time.sleep(wait)
                continue
            raise
    # Unreachable, but appeases linters
    raise last_exc if last_exc else RuntimeError("LLM call failed without exception")
