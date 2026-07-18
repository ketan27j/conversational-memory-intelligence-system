"""P2 experiment (ADR-001, checkpoints/M6.md): seeds a batch of write-gate
decisions through the real write path (`write_gate.pipeline.process_turn`),
trains `NaiveBayesWriteGateClassifier` on a train split of the resulting
`write_gate_decision` rows, and measures how well it agrees with the judge
on a held-out split. A rule-based judge stands in for the live AI judge
(C14 — reproducible without ANTHROPIC_API_KEY), the same "swap the LLM call
for a deterministic stand-in" pattern every other experiment/test in this
codebase uses.

ADR-001 names no numeric adopt/reject bar ("once there is enough data") —
this experiment sets its own, `AGREEMENT_BAR`, flagged as this milestone's
starting guess in the same "not a law, tunable" spirit as C6's blend
weights / M2's RELEVANCE_FLOOR.

Run (from implementation/): python -m prototypes.classifier_experiment
"""
import random
import uuid

from db.connection import tenant_connection
from observability.metrics import estimate_llm_cost_usd
from prototypes.classifier import NaiveBayesWriteGateClassifier
from retrieval.embedder import EMBEDDING_DIM
from write_gate.judge import Decision
from write_gate.pipeline import process_turn

AGREEMENT_BAR = 0.90
N_CANDIDATES = 240
TRAIN_FRACTION = 0.7

_KEEP_TEMPLATES = [
    "I use {tool} for my {project} projects.",
    "My preferred {thing} is {value}.",
    "I live in {place}.",
    "I work as a {role} at {company}.",
    "I prefer {style} explanations.",
]
_DROP_TEMPLATES = [
    "It was {weather} outside today.",
    "I had {food} for lunch.",
    "That's an interesting question.",
    "Let me think about that for a moment.",
    "Thanks for the update.",
]
_FILL = {
    "tool": ["PostgreSQL", "Node.js", "Docker", "Redis", "Kafka"],
    "project": ["side", "work", "hobby", "backend", "client"],
    "thing": ["editor", "browser", "language", "framework", "shell"],
    "value": ["Vim", "Firefox", "Python", "FastAPI", "zsh"],
    "place": ["Thane", "Pune", "Bangalore", "Mumbai", "Delhi"],
    "role": ["engineer", "analyst", "manager", "designer", "researcher"],
    "company": ["Acme", "Globex", "Initech", "Umbrella", "Soylent"],
    "style": ["detailed", "concise", "step-by-step", "high-level", "technical"],
    "weather": ["rainy", "sunny", "humid", "cloudy", "windy"],
    "food": ["dosa", "pasta", "biryani", "a sandwich", "noodles"],
}


def _fill(template: str, rng: random.Random) -> str:
    return template.format(**{k: rng.choice(v) for k, v in _FILL.items() if "{" + k + "}" in template})


def generate_candidates(n: int, seed: int = 42) -> list[str]:
    rng = random.Random(seed)
    candidates = []
    for _ in range(n):
        if rng.random() < 0.5:
            candidates.append(_fill(rng.choice(_KEEP_TEMPLATES), rng))
        else:
            candidates.append(_fill(rng.choice(_DROP_TEMPLATES), rng))
    return candidates


class _RuleBasedJudge:
    """Stands in for AnthropicWriteGateJudge (C14) with a fixed, inspectable
    rule: keep_markers being present makes a candidate worth remembering.
    Deliberately simple (a live AI judge would draw a fuzzier line) — the
    experiment's job is to see whether a classifier can learn *a* judge's
    boundary from its logged decisions, not to model the real judge's exact
    prompt."""

    _KEEP_MARKERS = ("i use", "my preferred", "i live", "i work as", "i prefer")

    def judge(self, candidate: str) -> Decision:
        keep = any(marker in candidate.lower() for marker in self._KEEP_MARKERS)
        return Decision(keep=keep, importance=5, confidence=0.85, reason="rule-based judge (experiment)")


class _SingleFactExtractor:
    def __init__(self, fact: str):
        self.fact = fact

    def extract(self, text: str) -> list[str]:
        return [self.fact]


class _ZeroEmbedder:
    """Embedding quality is irrelevant to this experiment — process_turn's
    kept branch indexes the memory as a side effect, which needs *an*
    embedder, not a meaningful one."""

    def embed(self, text: str) -> list[float]:
        return [0.0] * EMBEDDING_DIM


def seed_decisions(tenant: str, candidates: list[str], judge: _RuleBasedJudge) -> None:
    embedder = _ZeroEmbedder()
    for candidate in candidates:
        process_turn(tenant, str(uuid.uuid4()), candidate, _SingleFactExtractor(candidate), judge, embedder)


def load_examples(tenant: str) -> list[tuple[str, bool]]:
    with tenant_connection(tenant) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT candidate_text, kept FROM write_gate_decision WHERE tenant_id = %s", (tenant,))
            return [(row[0], row[1]) for row in cur.fetchall()]


def main() -> int:
    tenant = str(uuid.uuid4())
    judge = _RuleBasedJudge()
    candidates = generate_candidates(N_CANDIDATES)
    seed_decisions(tenant, candidates, judge)

    examples = load_examples(tenant)
    rng = random.Random(7)
    rng.shuffle(examples)
    split = int(len(examples) * TRAIN_FRACTION)
    train, held_out = examples[:split], examples[split:]

    classifier = NaiveBayesWriteGateClassifier()
    classifier.train(train)

    correct = sum(1 for text, label in held_out if classifier.predict(text) == label)
    agreement = correct / len(held_out) if held_out else 0.0

    # Cost proxy: the classifier does no LLM call at inference time; the
    # judge it's being compared against would (a live AnthropicWriteGateJudge
    # call per candidate) -- same Haiku pricing observability/metrics.py
    # already uses for the write path's cost tracking (M5).
    judge_cost_per_call = estimate_llm_cost_usd(input_chars=60, output_chars=80)
    classifier_cost_per_call = 0.0

    print(f"labelled examples: {len(examples)} ({len(train)} train / {len(held_out)} held-out)")
    print(f"held-out agreement with judge: {agreement:.3f} (bar: {AGREEMENT_BAR})")
    print(f"est. cost per decision: judge ${judge_cost_per_call:.6f} vs classifier ${classifier_cost_per_call:.6f}")

    verdict = "ADOPT" if agreement >= AGREEMENT_BAR else "REJECT"
    print(f"\nADR-001 verdict: {verdict} — " + (
        f"held-out agreement {agreement:.3f} clears the {AGREEMENT_BAR} bar"
        if verdict == "ADOPT"
        else f"held-out agreement {agreement:.3f} is below the {AGREEMENT_BAR} bar"
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
