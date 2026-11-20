"""Optional Claude provider (AI_PROVIDER=claude). Needs `pip install anthropic` and ANTHROPIC_API_KEY."""
from __future__ import annotations

import anthropic


def complete_claude(model: str, system: str, prompt: str) -> str:
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        output_config={"effort": "low"},  # short, factual write-ups don't need deep thinking
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined this article")
    return "".join(b.text for b in response.content if b.type == "text")
