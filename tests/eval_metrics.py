"""Evaluation metrics: Exact Match, Semantic Match, CER, WER.

Used to evaluate answers (EM, Semantic Match) and recognition quality
(CER, WER via jiwer) across typed, scanned, and handwritten documents.
Not a test module itself (no test_ prefix), so pytest does not collect it.
"""


def exact_match(prediction: str, reference: str) -> bool:
    """True if the normalized prediction equals the normalized reference."""
    raise NotImplementedError("TODO (build step 6)")


def semantic_match(prediction: str, reference: str, threshold: float = 0.8) -> bool:
    """True if the embedding cosine similarity is at least threshold."""
    raise NotImplementedError("TODO (build step 6)")


def cer(reference: str, hypothesis: str) -> float:
    """Character Error Rate (jiwer.cer)."""
    raise NotImplementedError("TODO (build step 6)")


def wer(reference: str, hypothesis: str) -> float:
    """Word Error Rate (jiwer.wer)."""
    raise NotImplementedError("TODO (build step 6)")
