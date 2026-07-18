"""Deliverable-3 benchmark re-run (M5, checkpoints/M5.md, C14): runs the same
seeded workload the naive-baseline benchmark (experiments/naive_baseline)
used against the real system (hybrid search + C6 ranking, M2), and prints
the same metric set side by side against experiments/baseline_results.csv.
Same fixed seed (42) and the same reused `build_workload` generator as the
baseline -> an apples-to-apples comparison, not a re-derived one.

Bypasses only the LLM *extraction* call (write_gate/pipeline.py's
extractor.extract), the same way the naive baseline bypasses it:
experiments/naive_baseline/workload.py's `mems` are already memory-shaped
text, not raw conversation turns needing extraction. Everything after
extraction runs for real -- each memory is written through
write_gate.pipeline.process_turn (a fixed single-candidate extractor +
always-keep judge stand in for the LLM calls, C14 style), so indexing,
write-time contradiction detection/resolution (M3, C8), and audit logging
all run exactly as they do in production. Skipping that write path
entirely (a naive direct INSERT) was tried first and turned out to
silently skip M3's contradiction resolution too -- the S2 stale-preference
metric would then measure nothing this milestone built.

Uses a deterministic hash-based embedder by default -- no live
VOYAGE_API_KEY dependency, same C14 "repeatable testing" posture the test
suite's FakeEmbedder uses. S2's stale/current preference pairs are given
matching concept vectors (see `WorkloadEmbedder`) so contradiction
detection's cosine-similarity "same subject" check has something real to
find; every other memory gets an independent random vector, same as
FakeEmbedder. Vector-similarity results otherwise reflect a synthetic
embedding space, not real semantic quality; keyword + entity signals (C7)
are real either way. Set VOYAGE_API_KEY to benchmark against real
embeddings instead (concept-pairing is skipped -- a real embedder should
already place paraphrased preference statements close together).

Run: python benchmark.py --compare-baseline ../experiments/baseline_results.csv
"""
import argparse
import csv
import hashlib
import os
import random
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "experiments" / "naive_baseline"))
from workload import build_workload  # noqa: E402

from db.connection import job_connection, tenant_connection  # noqa: E402
from retrieval.embedder import EMBEDDING_DIM  # noqa: E402
from retrieval.search import hybrid_search  # noqa: E402
from secrets_filter import detector  # noqa: E402
from write_gate.judge import Decision  # noqa: E402
from write_gate.pipeline import process_turn  # noqa: E402

_UUID_NAMESPACE = uuid.UUID("6f1f7e2a-6c1f-4e2a-9b1f-000000000000")
K = 5
BUDGET_TOKENS = 150


def user_uuid(user_id: str) -> str:
    """Deterministic string-user-id -> UUID so the naive baseline's workload
    (plain string user ids) can be replayed against a schema that requires
    `tenant_id UUID`, without changing the shared `workload.py`."""
    return str(uuid.uuid5(_UUID_NAMESPACE, user_id))


def _concept_key(tag: str | None) -> str | None:
    """S2's tag pairs are named `<subject>_stale` / `<subject>_current` --
    the shared `<subject>` prefix is the concept grouping key."""
    if tag is None:
        return None
    for suffix in ("_stale", "_current"):
        if tag.endswith(suffix):
            return tag[: -len(suffix)]
    return None


class WorkloadEmbedder:
    """Deterministic hash-derived vectors (same approach as
    tests/conftest.py's FakeEmbedder), except text belonging to an S2
    stale/current pair hashes on its shared concept key instead of its own
    text -- see module docstring for why."""

    def __init__(self, concept_of_text: dict[str, str]):
        self._concept_of_text = concept_of_text

    def embed(self, text: str) -> list[float]:
        key = self._concept_of_text.get(text, text)
        seed = int.from_bytes(hashlib.sha256(key.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        return [rng.uniform(-1, 1) for _ in range(EMBEDDING_DIM)]


def get_embedder(mems: list[dict]):
    if os.environ.get("VOYAGE_API_KEY"):
        from retrieval.embedder import VoyageEmbedder

        return VoyageEmbedder()
    concept_of_text = {
        m["text"]: concept
        for m in mems
        if (concept := _concept_key(m["meta"].get("tag"))) is not None
    }
    return WorkloadEmbedder(concept_of_text)


class _SingleFactExtractor:
    """Stands in for the LLM extraction call M5 does not re-run (see module
    docstring) -- the workload's `mems` are already extracted-fact-shaped,
    so there is exactly one candidate per turn: the text itself."""

    def __init__(self, fact: str):
        self.fact = fact

    def extract(self, text: str) -> list[str]:
        return [self.fact]


class _AlwaysKeepJudge:
    def judge(self, candidate: str) -> Decision:
        return Decision(keep=True, importance=5, confidence=0.9, reason="benchmark seed")


def seed_workload(multiplier: int, embedder) -> dict[str, tuple[str, str]]:
    """Writes every workload memory through the real write path
    (write_gate.pipeline.process_turn) so indexing and write-time
    contradiction resolution (M3) both run for real. Returns
    tag -> (memory_id, tenant_uuid), resolved by content lookup after the
    write since process_turn doesn't return the id it inserted."""
    mems, _probes = build_workload(seed=42, multiplier=multiplier)
    tag2id: dict[str, tuple[str, str]] = {}
    judge = _AlwaysKeepJudge()

    for m in mems:
        tenant = user_uuid(m["user_id"])
        process_turn(
            tenant, str(uuid.uuid4()), m["text"], _SingleFactExtractor(m["text"]), judge, embedder
        )
        tag = m["meta"].get("tag")
        if tag:
            with tenant_connection(tenant) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id FROM memory WHERE tenant_id = %s AND content = %s "
                        "ORDER BY created_at DESC LIMIT 1",
                        (tenant, m["text"]),
                    )
                    row = cur.fetchone()
                    assert row is not None
                    tag2id[tag] = (str(row[0]), tenant)
    return tag2id


def run_probes(probes, tag2id, embedder):
    latencies = []
    prec, rec, hit, rr = [], [], [], []
    stale_wins = []
    leak = []
    abstain_fail = []

    for p in probes:
        as_tenant = user_uuid(p["as_user"])
        start = time.monotonic()
        with tenant_connection(as_tenant) as conn:
            with conn.cursor() as cur:
                result = hybrid_search(cur, p["query"], embedder, k_max=K, token_budget=BUDGET_TOKENS)
        latencies.append((time.monotonic() - start) * 1000)

        result_ids = [m.id for m in result.memories]
        gold_ids = [tag2id[t][0] for t in p["gold"] if t in tag2id]
        poison_ids = [tag2id[t][0] for t in p["poison"] if t in tag2id]

        if p["kind"] == "qa" and p["answerable"] and gold_ids:
            inter = len(set(result_ids) & set(gold_ids))
            prec.append(inter / K)
            rec.append(inter / len(gold_ids))
            hit.append(1 if inter > 0 else 0)
            ranks = [i + 1 for i, mid in enumerate(result_ids) if mid in gold_ids]
            rr.append(1 / ranks[0] if ranks else 0)

        if p["scenario"] == "S2" and gold_ids and poison_ids:
            gold_rank = next((i for i, mid in enumerate(result_ids) if mid in gold_ids), None)
            poison_rank = next((i for i, mid in enumerate(result_ids) if mid in poison_ids), None)
            stale_wins.append(
                1 if (poison_rank is not None and (gold_rank is None or poison_rank < gold_rank)) else 0
            )

        if p["scenario"] == "S4":
            with job_connection() as jconn:
                with jconn.cursor() as jcur:
                    jcur.execute(
                        "SELECT tenant_id FROM memory WHERE id = ANY(%s)",
                        ([m.id for m in result.memories],),
                    )
                    owners = {str(row[0]) for row in jcur.fetchall()}
            leak.append(1 if any(o != as_tenant for o in owners) else 0)

        if not p["answerable"]:
            abstain_fail.append(0 if result.abstained else 1)

    return {
        "latency_ms": latencies,
        "precision_at_5": prec,
        "recall_at_5": rec,
        "hit_at_5": hit,
        "mrr": rr,
        "stale_wins_rate": stale_wins,
        "cross_tenant_leak_rate": leak,
        "abstention_failure_rate": abstain_fail,
    }


def secrets_stored_rate() -> float:
    """S5, component-level: does the secrets filter block the two PII
    strings the workload defines, before they'd ever reach storage? Tests
    the real detector (secrets_filter/detector.py) directly, independent of
    the seeded-memory bypass used for retrieval scenarios above."""
    pii_texts = [
        "My OpenAI API key is sk-proj-9f3a2b7c8d1e4f5a6b7c8d9e0f1a2b3c.",
        "Here is my card: 4111 1111 1111 1111, expiry 04/29, cvv 123.",
    ]
    stored = 0
    for text in pii_texts:
        findings = detector.scan(text)
        if not findings:
            stored += 1  # would have been stored with the secret intact
    return stored / len(pii_texts)


def mean(xs):
    return sum(xs) / len(xs) if xs else 0.0


def percentile(xs, pct):
    if not xs:
        return 0.0
    ordered = sorted(xs)
    idx = min(len(ordered) - 1, max(0, round(pct * (len(ordered) - 1))))
    return ordered[idx]


def load_baseline(path: str) -> dict[tuple[str, str], list[tuple[int, float]]]:
    rows: dict[tuple[str, str], list[tuple[int, float]]] = {}
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            key = (row["scenario"], row["metric"])
            rows.setdefault(key, []).append((int(row["store_size"]), float(row["value"])))
    return rows


def closest_baseline(baseline, scenario, metric, n):
    key = (scenario, metric)
    if key not in baseline:
        return None
    return min(baseline[key], key=lambda sn: abs(sn[0] - n))[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--compare-baseline",
        default=str(Path(__file__).parent.parent / "experiments" / "baseline_results.csv"),
    )
    parser.add_argument("--multiplier", type=int, default=1, help="same knob as the naive baseline's MULTIPLIERS")
    args = parser.parse_args()

    mems, probes = build_workload(seed=42, multiplier=args.multiplier)
    embedder = get_embedder(mems)
    embedder_kind = "VoyageEmbedder (live)" if os.environ.get("VOYAGE_API_KEY") else "WorkloadEmbedder (offline)"
    print(f"embedder: {embedder_kind}")

    tag2id = seed_workload(args.multiplier, embedder)
    metrics = run_probes(probes, tag2id, embedder)

    real = {
        # len(mems), not len(tag2id): every memory in the workload gets
        # inserted (the always-keep judge), but only a subset carry a probe
        # tag -- store size must reflect what's actually in the database,
        # or a `--multiplier` run would silently compare against the wrong
        # baseline store_size row (L4 VERIFY finding).
        "n_memories": float(len(mems)),
        "retrieval_p50_ms": percentile(metrics["latency_ms"], 0.50),
        "retrieval_p95_ms": percentile(metrics["latency_ms"], 0.95),
        ("S1", "precision_at_5"): mean(metrics["precision_at_5"]),
        ("S1", "recall_at_5"): mean(metrics["recall_at_5"]),
        ("S1", "hit_at_5"): mean(metrics["hit_at_5"]),
        ("S1", "mrr"): mean(metrics["mrr"]),
        ("S2", "stale_wins_rate"): mean(metrics["stale_wins_rate"]),
        ("S4", "cross_tenant_leak_rate"): mean(metrics["cross_tenant_leak_rate"]),
        ("S5", "secrets_stored"): secrets_stored_rate(),
        ("S6", "abstention_failure_rate"): mean(metrics["abstention_failure_rate"]),
    }

    baseline = load_baseline(args.compare_baseline)
    n = int(real["n_memories"])

    print(f"\n{'scenario':<10}{'metric':<28}{'baseline':>12}{'real system':>14}")
    print("-" * 64)
    for label in ["retrieval_p50_ms", "retrieval_p95_ms"]:
        bl = closest_baseline(baseline, "ALL", label, n)
        bl_s = f"{bl:.2f}" if bl is not None else "n/a"
        print(f"{'ALL':<10}{label:<28}{bl_s:>12}{real[label]:>14.2f}")
    for scenario, metric_name in [
        ("S1", "precision_at_5"), ("S1", "recall_at_5"), ("S1", "hit_at_5"), ("S1", "mrr"),
        ("S2", "stale_wins_rate"), ("S4", "cross_tenant_leak_rate"),
        ("S5", "secrets_stored"), ("S6", "abstention_failure_rate"),
    ]:
        bl = closest_baseline(baseline, scenario, metric_name, n)
        bl_s = f"{bl:.3f}" if bl is not None else "n/a"
        val = real[(scenario, metric_name)]
        print(f"{scenario:<10}{metric_name:<28}{bl_s:>12}{val:>14.3f}")

    print(f"\nstore size: {n} memories (naive baseline compared at closest available store_size per row)")
    print(
        "note: tenant ids are deterministic (user_uuid), so repeated runs against the same "
        "database accumulate state rather than starting fresh -- run against a freshly seeded "
        "database (`docker compose up -d` on an empty volume) for a clean comparison."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
