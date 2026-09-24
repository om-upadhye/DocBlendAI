"""Module 6 — Reliability Tier Classification.

Responsibility: threshold the retrieved combined_scores into one of four
tiers: Certain / Moderate / Uncertain / Unreadable.

Uses from schemas.py: RetrievalResult, ReliabilityLabel.
"""

from app.models.schemas import ReliabilityLabel, RetrievalResult


def classify_reliability(results: list[RetrievalResult]) -> ReliabilityLabel:
    """Return the reliability tier for an answer built from these results."""
    raise NotImplementedError("TODO (build step 5)")
