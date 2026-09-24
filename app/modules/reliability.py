"""Module 6 — Reliability Tier Classification.

Responsibility: threshold the retrieved combined_scores into one of four
tiers: Certain / Moderate / Uncertain / Unreadable.

Build step 3 (interim): every Answer needs a label, so this thresholds the
best similarity only. Step 5 replaces it with combined_score + calibrated
confidence and adds Unreadable (low recognition confidence), which typed
text never triggers.

Uses from schemas.py: RetrievalResult, ReliabilityLabel.
"""

from app.models.schemas import ReliabilityLabel, RetrievalResult

# Cosine similarity cut-offs for gemini-embedding-001 at 768 dims. First
# guesses from a small live sample (relevant ~0.72-0.77, off-topic ~0.59-0.64);
# tune against the evaluation set.
CERTAIN_MIN = 0.75
MODERATE_MIN = 0.65

# Best to worst; used to combine labels ("the worse of two").
TIER_ORDER = [
    ReliabilityLabel.CERTAIN,
    ReliabilityLabel.MODERATE,
    ReliabilityLabel.UNCERTAIN,
    ReliabilityLabel.UNREADABLE,
]


def classify_reliability(results: list[RetrievalResult]) -> ReliabilityLabel:
    """Return the reliability tier for an answer built from these results."""
    if not results:
        return ReliabilityLabel.UNCERTAIN
    best = max(r.combined_score for r in results)
    if best >= CERTAIN_MIN:
        return ReliabilityLabel.CERTAIN
    if best >= MODERATE_MIN:
        return ReliabilityLabel.MODERATE
    return ReliabilityLabel.UNCERTAIN


def worse_of(a: ReliabilityLabel, b: ReliabilityLabel) -> ReliabilityLabel:
    return max(a, b, key=TIER_ORDER.index)
