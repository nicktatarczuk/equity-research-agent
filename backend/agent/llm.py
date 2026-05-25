"""
Thin wrapper around langchain-google-genai so every node uses the same
configured model and we can swap models in one place.
"""
from __future__ import annotations

import os

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI


def get_llm(temperature: float = 0.3) -> ChatGoogleGenerativeAI:
    """Return a configured Gemini chat model."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Get one free at https://aistudio.google.com/apikey"
        )
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=temperature,
        max_output_tokens=2048,
    )


def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.3) -> str:
    """One-shot call: system + user prompt → string response."""
    llm = get_llm(temperature=temperature)
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ]
    response = llm.invoke(messages)
    return response.content if hasattr(response, "content") else str(response)
