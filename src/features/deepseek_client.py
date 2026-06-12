from __future__ import annotations

import os

from openai import OpenAI

from src.config import config


def _client() -> OpenAI:
    return OpenAI(
        api_key=os.getenv("LLM_API_KEY"),
        base_url="https://api.deepseek.com",
    )


def call_deepseek(prompt: str, model: str = "deepseek-v4-flash", temperature: float = 0) -> str | None:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        print("[deepseek] LLM_API_KEY not set in .env")
        return None

    client = _client()
    print(f"[deepseek] sending prompt ({len(prompt)} chars, temp={temperature})...")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content
