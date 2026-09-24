"""Module 6 — Reliability Tier Classification.

Responsibility: label an answer Certain / Moderate / Uncertain / Unreadable by
jointly weighing retrieval relevance (similarity) and recognition confidence
(calibrated) of the evidence it rests on: the top-ranked retrieval result.

    Unreadable  confidence < UNREADABLE_MAX_CONF (the relevant text could not
                be read reliably, whatever its similarity)
    Certain     similarity >= CERTAIN_MIN_SIM and confidence >= CERTAIN_MIN_CONF
    Moderate    similarity >= MODERATE_MIN_SIM and confidence >= MODERATE_MIN_CONF
    Uncertain   everything else, including no evidence at all

Using two thresholds instead of one on combined_score keeps each label
explainable: "Moderate because the handwriting was only partly legible" vs
"Moderate because the match was loose".

Uses from schemas.py: RetrievalResult, ReliabilityLabel.
"""

from app.models.schemas import ReliabilityLabel, RetrievalResult

# Similarity cut-offs for gemini-embedding-001 at 768 dims. First guesses
# from a small live sample (relevant ~0.72-0.77, off-topic ~0.59-0.64).
CERTAIN_MIN_SIM = 0.75
MODERATE_MIN_SIM = 0.65
# Calibrated confidence ~ expected character accuracy (see confidence_capture).
CERTAIN_MIN_CONF = 0.85
MODERATE_MIN_CONF = 0.60
UNREADABLE_MAX_CONF = 0.35
# All of the above are to be tuned against the evaluation set (build step 6).

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
    top = max(results, key=lambda r: r.combined_score)

    if top.confidence < UNREADABLE_MAX_CONF:
        return ReliabilityLabel.UNREADABLE
    if top.similarity >= CERTAIN_MIN_SIM and top.confidence >= CERTAIN_MIN_CONF:
        return ReliabilityLabel.CERTAIN
    if top.similarity >= MODERATE_MIN_SIM and top.confidence >= MODERATE_MIN_CONF:
        return ReliabilityLabel.MODERATE
    return ReliabilityLabel.UNCERTAIN


def worse_of(a: ReliabilityLabel, b: ReliabilityLabel) -> ReliabilityLabel:
    return max(a, b, key=TIER_ORDER.index)
