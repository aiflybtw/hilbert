from __future__ import annotations

import os

from openai import OpenAI

from src.config import config


def _client() -> OpenAI:
    return OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com",
    )


def call_deepseek(prompt: str, model: str = "deepseek-v4-flash") -> str | None:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        print("[deepseek] DEEPSEEK_API_KEY not set in .env")
        return None

    client = _client()
    print(f"[deepseek] sending prompt ({len(prompt)} chars)...")
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return resp.choices[0].message.content
