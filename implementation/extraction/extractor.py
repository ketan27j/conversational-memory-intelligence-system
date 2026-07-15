"""Single-pass fact extraction (design_backlog.md P2): pull clean, short
facts out of a raw conversation turn — not a transcript replay (C2).

Swappable interface, same rationale as write_gate/judge.py: tests inject a
deterministic fake instead of depending on a live LLM call.
"""
from typing import Protocol


class FactExtractor(Protocol):
    def extract(self, text: str) -> list[str]: ...


class AnthropicFactExtractor:
    """Production extractor. Requires ANTHROPIC_API_KEY. Not exercised by
    the offline demo test — see tests/test_write_gate.py's FakeExtractor."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def extract(self, text: str) -> list[str]:
        import json

        import anthropic

        client = anthropic.Anthropic()
        prompt = (
            "Extract 0 or more short, standalone facts worth remembering "
            "long-term from this message (skip small talk, skip anything "
            "already obvious). Answer as a JSON array of strings only.\n\n"
            f"Message: {text!r}"
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        facts = json.loads(resp.content[0].text)
        return [str(f) for f in facts]
