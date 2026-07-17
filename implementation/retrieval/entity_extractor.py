"""Entity-matching search signal (first_principles.md C7, data_model.md's
`memory_entity` table): "a cleaned-up name, such as `postgresql` or
`acme_tools`". No ADR decided an NER model for this, and the examples in
data_model.md are ordinary lowercase technical nouns, not proper-noun-only
named entities — so this is a deterministic keyword-shape heuristic, not an
LLM call. Same extractor runs over both stored content (write time) and
incoming queries (read time), so a query naming an entity boosts memories
that mention it.
"""
import re

_STOPWORDS = frozenset(
    """
    a an the this that these those and or but if then so because as of to in
    on at for with without from into over under about above below between
    is are was were be been being am do does did have has had having will
    would shall should can could may might must not no nor
    i you he she it we they me him her us them my your his its our their
    what when where who whom which why how
    """.split()
)

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_\-.]*")


def extract_entities(text: str) -> list[str]:
    """Deterministic, order-preserving, de-duplicated. A token qualifies as
    an entity candidate if it's at least 3 characters, contains a letter,
    and isn't a stopword — this catches technical nouns ('postgresql'),
    identifiers ('acme_tools'), and version-like tokens ('python3.12') while
    filtering ordinary connective words."""
    seen: dict[str, None] = {}
    for match in _TOKEN_RE.finditer(text.lower()):
        token = match.group().strip(".-_")
        if len(token) < 3:
            continue
        if not any(c.isalpha() for c in token):
            continue
        if token in _STOPWORDS:
            continue
        seen.setdefault(token, None)
    return list(seen.keys())
