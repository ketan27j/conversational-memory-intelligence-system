"""
Productive-failure benchmark runner.

Builds the naive store at several store sizes, runs the fixed probe set, and measures
each failure mode against ground truth. Outputs:
  - baseline_results.csv   (tidy: scenario, metric, store_size, value, unit, note)
  - error_examples.jsonl   (concrete failing retrievals at the largest store size)

Deterministic: fixed seed, fixed probes, TF-IDF is deterministic.
Run:  python benchmark.py
"""
import csv
import json
import os
import statistics as st

import numpy as np

from memory import NaiveMemoryStore, approx_tokens
from workload import build_workload, PRIMARY

SEED = 42
MULTIPLIERS = [1, 4, 16, 40]   # -> roughly 68, 212, 788, 1940 memories
K = 5
BUDGET_TOKENS = 150
OUT_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_CSV = os.path.join(OUT_DIR, "..", "baseline_results.csv")
ERRORS_JSONL = os.path.join(OUT_DIR, "..", "error_examples.jsonl")


def build_store(multiplier):
    mems, probes = build_workload(seed=SEED, multiplier=multiplier)
    store = NaiveMemoryStore()
    for m in mems:
        store.add(m["user_id"], m["text"], m["created_at"], m["meta"])
    tag2id = {m.meta["tag"]: m.id for m in store.memories if "tag" in m.meta}
    return store, probes, tag2id


def rank_of(ranking, mem_id):
    for pos, (mem, _score) in enumerate(ranking):
        if mem.id == mem_id:
            return pos
    return None


def run_size(multiplier):
    store, probes, tag2id = build_store(multiplier)
    n = store.stats()["n_memories"]
    rows = []
    latencies = []

    # accumulators
    prec, rec, hit, rr = [], [], [], []
    stale_wins = []
    leak = []
    injected_tokens = []
    dropped = []
    pii_exposed = []
    top1_answerable, top1_unanswerable = [], []
    abstain_fail = []

    for p in probes:
        topk, dt = store.retrieve_timed(p["query"], k=K)
        latencies.append(dt)
        ranking = store.full_ranking(p["query"])
        gold_ids = [tag2id[t] for t in p["gold"] if t in tag2id]
        poison_ids = [tag2id[t] for t in p["poison"] if t in tag2id]
        topk_ids = [m.id for m, _ in topk]
        topk_scores = [s for _, s in topk]

        # cross-tenant leak (any returned memory from a different user than the asker)
        if p["as_user"] in store_users(store):
            leaked = any(m.user_id != p["as_user"] for m, _ in topk)
            leak.append(1 if leaked else 0)

        # retrieval quality on answerable QA probes (S1, S2, S4)
        if p["answerable"] and p["kind"] == "qa" and gold_ids:
            inter = len(set(topk_ids) & set(gold_ids))
            prec.append(inter / K)
            rec.append(inter / len(gold_ids))
            hit.append(1 if inter > 0 else 0)
            gpos = min([rank_of(ranking, g) for g in gold_ids])
            rr.append(1.0 / (gpos + 1) if gpos is not None else 0.0)
            top1_answerable.append(topk_scores[0])

            # context-budget: greedy include by rank until budget, see if gold survives
            included, total = set(), 0
            for mem, _ in ranking:
                tok = approx_tokens(mem.text)
                if total + tok > BUDGET_TOKENS:
                    break
                total += tok
                included.add(mem.id)
            injected_tokens.append(sum(approx_tokens(m.text) for m, _ in topk))
            dropped.append(0 if any(g in included for g in gold_ids) else 1)

        # stale preference: does the stale memory outrank the current one?
        if p["scenario"] == "S2" and gold_ids and poison_ids:
            g = min(rank_of(ranking, x) for x in gold_ids)
            s = min(rank_of(ranking, x) for x in poison_ids)
            stale_wins.append(1 if (s is not None and (g is None or s < g)) else 0)

        # PII exposure: is the secret retrievable in top-k?
        if p["kind"] == "pii" and gold_ids:
            pii_exposed.append(1 if any(g in topk_ids for g in gold_ids) else 0)

        # cold-start / no relevant memory: did the system abstain? (it never does)
        if not p["answerable"]:
            abstain_fail.append(1 if len(topk) > 0 else 0)
            top1_unanswerable.append(topk_scores[0] if topk_scores else 0.0)

    def add(scenario, metric, value, unit, note=""):
        rows.append({"scenario": scenario, "metric": metric, "store_size": n,
                     "value": round(value, 4) if isinstance(value, float) else value,
                     "unit": unit, "note": note})

    # retrieval / pollution
    add("S1", "precision_at_5", mean(prec), "ratio", "answerable QA probes")
    add("S1", "recall_at_5", mean(rec), "ratio", "")
    add("S1", "hit_at_5", mean(hit), "ratio", "fraction with >=1 gold in top-5")
    add("S1", "mrr", mean(rr), "ratio", "")
    # F3
    add("S2", "stale_wins_rate", mean(stale_wins), "ratio", "stale memory outranks current")
    # F5
    add("S4", "cross_tenant_leak_rate", mean(leak), "ratio", "top-5 contains another user's memory")
    # F6
    add("S5", "secrets_stored", 2, "count", "PII memories admitted (no filter)")
    add("S5", "pii_exposure_rate", mean(pii_exposed), "ratio", "secret retrievable in top-5")
    # S3 budget
    add("S3", "mean_injected_tokens", mean(injected_tokens), "tokens", f"sum of top-{K}; budget={BUDGET_TOKENS}")
    add("S3", "relevant_dropped_under_budget_rate", mean(dropped), "ratio", f"gold excluded under {BUDGET_TOKENS}-token budget")
    # S6 abstention
    add("S6", "abstention_failure_rate", mean(abstain_fail), "ratio", "returned >=1 memory when none relevant")
    add("S6", "mean_top1_sim_answerable", mean(top1_answerable), "cosine", "similarity when an answer exists")
    add("S6", "mean_top1_sim_unanswerable", mean(top1_unanswerable), "cosine", "similarity when guessing")
    # latency + storage
    add("ALL", "retrieval_p50_ms", float(np.percentile(latencies, 50)), "ms", "")
    add("ALL", "retrieval_p95_ms", float(np.percentile(latencies, 95)), "ms", "")
    s = store.stats()
    add("ALL", "n_memories", s["n_memories"], "count", "")
    add("ALL", "raw_text_kb", s["raw_text_bytes"] / 1024.0, "kb", "")
    add("ALL", "tfidf_nnz", s["tfidf_nnz"], "count", "non-zero index entries")
    return rows


def store_users(store):
    return {m.user_id for m in store.memories}


def mean(xs):
    return float(st.mean(xs)) if xs else 0.0


def collect_error_examples(multiplier):
    """Pull concrete failing retrievals at the largest store size for error_examples.jsonl."""
    store, probes, tag2id = build_store(multiplier)
    examples = []
    for p in probes:
        topk = store.retrieve(p["query"], k=K, as_user=p["as_user"])
        topk_view = [{"user": m.user_id, "text": m.text, "score": round(s, 3)} for m, s in topk]
        gold_ids = [tag2id[t] for t in p["gold"] if t in tag2id]
        poison_ids = [tag2id[t] for t in p["poison"] if t in tag2id]
        topk_ids = [m.id for m, _ in topk]

        cat, failure = None, None
        if p["scenario"] == "S2" and poison_ids:
            rk = store.full_ranking(p["query"])
            g = min(rank_of(rk, x) for x in gold_ids) if gold_ids else None
            sp = min(rank_of(rk, x) for x in poison_ids)
            if sp is not None and (g is None or sp < g):
                cat, failure = "F3_stale_preference", "stale memory outranks the current one"
        elif p["scenario"] == "S4":
            if any(m.user_id != p["as_user"] for m, _ in topk):
                cat, failure = "F5_cross_tenant_leak", "another user's memory returned for this user"
        elif p["kind"] == "pii":
            if any(g in topk_ids for g in gold_ids):
                cat, failure = "F6_pii_exposure", "sensitive data was stored and is retrievable"
        elif not p["answerable"]:
            cat, failure = "coldstart_no_abstention", "no relevant memory exists, but system still injected memories"
        elif p["scenario"] == "S1":
            if not (set(topk_ids) & set(gold_ids)):
                cat, failure = "F2_pollution_miss", "relevant memory buried below filler in top-5"

        if cat:
            examples.append({
                "category": cat, "scenario": p["scenario"], "as_user": p["as_user"],
                "query": p["query"],
                "expected": [m.text for m in store.memories if m.id in gold_ids] or "should abstain / store nothing",
                "top_k": topk_view, "failure": failure,
            })
    return examples


def main():
    all_rows = []
    print(f"{'size':>6} {'prec@5':>7} {'hit@5':>6} {'stale':>6} {'leak':>6} {'pii_exp':>7} {'drop':>6} {'p95ms':>7}")
    for mult in MULTIPLIERS:
        rows = run_size(mult)
        all_rows.extend(rows)
        d = {(r["scenario"], r["metric"]): r["value"] for r in rows}
        print(f"{d[('ALL','n_memories')]:>6} "
              f"{d[('S1','precision_at_5')]:>7} {d[('S1','hit_at_5')]:>6} "
              f"{d[('S2','stale_wins_rate')]:>6} {d[('S4','cross_tenant_leak_rate')]:>6} "
              f"{d[('S5','pii_exposure_rate')]:>7} {d[('S3','relevant_dropped_under_budget_rate')]:>6} "
              f"{d[('ALL','retrieval_p95_ms')]:>7}")

    with open(RESULTS_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["scenario", "metric", "store_size", "value", "unit", "note"])
        w.writeheader()
        w.writerows(all_rows)

    examples = collect_error_examples(MULTIPLIERS[-1])
    with open(ERRORS_JSONL, "w") as f:
        for ex in examples:
            f.write(json.dumps(ex) + "\n")

    print(f"\nwrote {RESULTS_CSV} ({len(all_rows)} rows)")
    print(f"wrote {ERRORS_JSONL} ({len(examples)} concrete failure examples)")


if __name__ == "__main__":
    np.random.seed(SEED)
    main()
