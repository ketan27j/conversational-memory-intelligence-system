"""The write gate: decides whether an extracted candidate fact is worth
keeping. v1 is an AI judge (first_principles.md C3) — every decision is
logged so it can become training data for a future classifier.

The judge is a swappable interface so the demo test suite can inject a
deterministic fake (C14: repeatable testing) instead of depending on a live
LLM call for every test run.
"""
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Decision:
    keep: bool
    importance: int  # 1-10, per data_model.md
    confidence: float  # 0-1
    reason: str


class WriteGateJudge(Protocol):
    def judge(self, candidate: str) -> Decision: ...


class AnthropicWriteGateJudge:
    """Production judge. Requires ANTHROPIC_API_KEY. Not exercised by the
    offline demo test — see tests/test_write_gate.py's FakeJudge."""

    def __init__(self, model: str = "claude-haiku-4-5-20251001"):
        self.model = model

    def judge(self, candidate: str) -> Decision:
        import json

        import anthropic

        client = anthropic.Anthropic()
        prompt = (
            "Would remembering this fact help a future conversation with this "
            "user? Answer as JSON only: "
            '{"keep": bool, "importance": 1-10, "confidence": 0-1, "reason": str}.\n\n'
            f"Candidate: {candidate!r}"
        )
        resp = client.messages.create(
            model=self.model,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
        )
        data = json.loads(resp.content[0].text)
        return Decision(
            keep=bool(data["keep"]),
            importance=int(data["importance"]),
            confidence=float(data["confidence"]),
            reason=str(data["reason"]),
        )
