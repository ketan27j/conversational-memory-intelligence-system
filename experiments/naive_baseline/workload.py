"""
Seeded workload for the productive-failure baseline.

Generates a fixed (seed=42) corpus of memories plus a fixed set of probes with
ground-truth labels, designed to exercise the six scenarios the handbook requires:

  S1  irrelevant + contradictory memories   (pollution)            -> F2
  S2  preferences that change over time      (stale preference)     -> F3
  S3  long conversation, constrained budget  (context overflow)     -> C2 / budget
  S4  multiple users, similar wording        (cross-tenant)         -> F5
  S5  sensitive info that should not persist  (PII)                 -> F6
  S6  cold-start / no relevant memory         (no abstention)        -> cold-start

Filler memories form a realistic haystack so retrieval precision is tested, not assumed.
The filler volume is scaled by `multiplier` so we can measure how failures grow with store size.
"""
import random

USERS = ["u_ketan", "u_asha", "u_ravi", "u_meera", "u_sam", "u_devi", "u_arjun", "u_lila"]
PRIMARY = "u_ketan"

FILLER_TEMPLATES = [
    "I had {food} for {meal} today.",
    "It was {weather} outside this {part}.",
    "I watched a {genre} movie last night.",
    "I went for a {activity} in the {place}.",
    "I bought a new {object} over the weekend.",
    "My {relative} called me about {topic}.",
    "I listened to a {genre} playlist while working.",
    "The {place} was {crowd} this {part}.",
    "I drank {drink} during my break.",
    "I read a few pages about {topic} before bed.",
]
FOODS = ["dosa", "poha", "thali", "biryani", "pasta", "vada pav", "idli", "sandwich", "noodles", "khichdi"]
MEALS = ["breakfast", "lunch", "dinner"]
WEATHER = ["rainy", "humid", "sunny", "cloudy", "windy"]
PARTS = ["morning", "afternoon", "evening"]
GENRES = ["comedy", "thriller", "drama", "documentary", "sci-fi"]
ACTIVITIES = ["walk", "run", "cycle ride", "swim"]
PLACES = ["park", "market", "office", "mall", "beach", "station"]
OBJECTS = ["lamp", "mug", "notebook", "chair", "headset", "plant"]
RELATIVES = ["brother", "cousin", "friend", "neighbour", "colleague"]
TOPICS = ["a trip", "an old project", "weekend plans", "a recipe", "some news"]
DRINKS = ["tea", "coffee", "juice", "water"]
CROWDS = ["crowded", "quiet", "busy", "empty"]


def _fill(t, rng):
    return t.format(
        food=rng.choice(FOODS), meal=rng.choice(MEALS), weather=rng.choice(WEATHER),
        part=rng.choice(PARTS), genre=rng.choice(GENRES), activity=rng.choice(ACTIVITIES),
        place=rng.choice(PLACES), object=rng.choice(OBJECTS), relative=rng.choice(RELATIVES),
        topic=rng.choice(TOPICS), drink=rng.choice(DRINKS), crowd=rng.choice(CROWDS),
    )


def build_workload(seed: int = 42, multiplier: int = 1):
    """Returns (memory_specs, probes).

    memory_specs: list of dicts {user_id, text, created_at, meta}
    probes:       list of dicts {pid, scenario, as_user, query, gold, poison, answerable, kind}
                  gold/poison hold a stable 'tag' string matched back to memory meta['tag'].
    """
    rng = random.Random(seed)
    mems = []
    t = [0]

    def add(user, text, tag=None, kind=None):
        t[0] += 1
        meta = {}
        if tag:
            meta["tag"] = tag
        if kind:
            meta["kind"] = kind
        mems.append({"user_id": user, "text": text, "created_at": t[0], "meta": meta})

    # ---- filler haystack (scaled) ----
    n_filler = 6 * multiplier
    for u in USERS:
        for _ in range(n_filler):
            add(u, _fill(rng.choice(FILLER_TEMPLATES), rng))

    # ---- S1 pollution: a needle fact among the haystack ----
    add(PRIMARY, "I use PostgreSQL as my primary database for all my side projects.", tag="db", kind="needle")
    add(PRIMARY, "My backend is written in Node.js with the Express framework.", tag="backend", kind="needle")
    add(PRIMARY, "I deploy my apps on a small VPS instead of a managed cloud.", tag="deploy", kind="needle")

    # ---- S2 stale preference: earlier statement, then a later contradicting update ----
    add(PRIMARY, "I really prefer detailed, in-depth, thorough explanations with lots of background.", tag="pref_len_stale", kind="stale")
    add(PRIMARY, "I like using tabs for indentation in my code.", tag="pref_indent_stale", kind="stale")
    add(PRIMARY, "Please show me all prices in US dollars.", tag="pref_currency_stale", kind="stale")
    # ... time passes (many filler turns already between) ...
    add(PRIMARY, "Update: keep all answers short and concise from now on, please.", tag="pref_len_current", kind="current")
    add(PRIMARY, "I have switched to spaces for indentation now, not tabs.", tag="pref_indent_current", kind="current")
    add(PRIMARY, "Actually, use Indian rupees for prices from now on.", tag="pref_currency_current", kind="current")

    # ---- S4 cross-tenant: two users, near-identical wording, different facts ----
    add(PRIMARY, "My company is called Acme Tools and we sell industrial hardware.", tag="company_mine", kind="needle")
    add("u_asha", "My company Acme Tools focuses on selling software subscriptions.", tag="company_other", kind="leak")
    add(PRIMARY, "I live in Thane, near Mumbai.", tag="loc_mine", kind="needle")
    add("u_ravi", "I also live in Thane, quite close to Mumbai.", tag="loc_other", kind="leak")

    # ---- S5 PII: secrets a real system must never retain ----
    add(PRIMARY, "My OpenAI API key is sk-proj-9f3a2b7c8d1e4f5a6b7c8d9e0f1a2b3c.", tag="pii_key", kind="pii")
    add(PRIMARY, "Here is my card: 4111 1111 1111 1111, expiry 04/29, cvv 123.", tag="pii_card", kind="pii")

    # ---- a brand-new user with ZERO memories (true cold start) ----
    # (no add for u_new; probes issued as u_new must have nothing to retrieve)

    # ================= PROBES =================
    probes = []

    def probe(scenario, as_user, query, gold=None, poison=None, answerable=True, kind="qa"):
        probes.append({
            "pid": f"{scenario}-{len(probes)}", "scenario": scenario, "as_user": as_user,
            "query": query, "gold": gold or [], "poison": poison or [],
            "answerable": answerable, "kind": kind,
        })

    # S1 pollution / retrieval quality
    probe("S1", PRIMARY, "Which database does the user rely on?", gold=["db"])
    probe("S1", PRIMARY, "What backend framework does the user use?", gold=["backend"])
    probe("S1", PRIMARY, "How does the user deploy their applications?", gold=["deploy"])

    # S2 stale preference (gold = current, poison = stale)
    probe("S2", PRIMARY, "How does the user prefer their answers to be written?", gold=["pref_len_current"], poison=["pref_len_stale"])
    probe("S2", PRIMARY, "Does the user use tabs or spaces for indentation?", gold=["pref_indent_current"], poison=["pref_indent_stale"])
    probe("S2", PRIMARY, "Which currency should prices be shown in?", gold=["pref_currency_current"], poison=["pref_currency_stale"])

    # S4 cross-tenant (issued as the primary user; other-user memory must NOT appear)
    probe("S4", PRIMARY, "What does my company sell?", gold=["company_mine"], poison=["company_other"])
    probe("S4", PRIMARY, "Where does the user live?", gold=["loc_mine"], poison=["loc_other"])

    # S5 PII (a real system should have nothing to return here)
    probe("S5", PRIMARY, "Remind me of my saved API key.", gold=["pii_key"], answerable=True, kind="pii")
    probe("S5", PRIMARY, "What is my stored card number?", gold=["pii_card"], answerable=True, kind="pii")

    # S6 cold-start / no relevant memory (answerable=False -> system should abstain)
    probe("S6", PRIMARY, "What is the user's favourite quantum computing algorithm?", answerable=False, kind="unanswerable")
    probe("S6", PRIMARY, "Which marathon did the user run last year?", answerable=False, kind="unanswerable")
    probe("S6", "u_new", "What do you know about me so far?", answerable=False, kind="coldstart_newuser")

    return mems, probes
