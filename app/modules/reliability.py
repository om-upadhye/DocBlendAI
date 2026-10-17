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

# Similarity cut-offs for gemini-embedding-001 at 768 dims. The step 6 evaluation
# (evaluation/results/report.md, 18 synthetic questions) put correct answers at
# 0.66-0.77 and unanswerable ones at 0.50-0.52, but questions asked on the live
# site showed real questions scoring 0.65-0.77 whether or not the documents held
# the answer, so 0.65 made almost every answer Certain. Certain now needs a
# clearly strong match; the model's own support check (llm_answer) does the rest.
# Retune with `run_eval --rescore` as the dataset grows.
CERTAIN_MIN_SIM = 0.70
MODERATE_MIN_SIM = 0.60
# Calibrated confidence ~ expected character accuracy (see confidence_capture):
# Certain allows at most ~1 misread character in 10.
CERTAIN_MIN_CONF = 0.90
MODERATE_MIN_CONF = 0.60
UNREADABLE_MAX_CONF = 0.35

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
