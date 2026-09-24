"""Pipeline test stubs — one per module (1-7).

Each test is skipped until its module is implemented; un-skip and fill in as
the build order in CLAUDE.md progresses.
"""

import pytest

pytestmark = pytest.mark.skip(reason="module not implemented yet")


def test_module1_upload_saves_document() -> None:
    """Module 1: POST /upload stores the file and returns a Document."""


def test_module2_format_detection_and_extraction() -> None:
    """Module 2: typed/scanned/handwritten PDFs route to the right extractor."""


def test_module3_confidence_calibration() -> None:
    """Module 3: calibrated_conf is in [0, 1] and monotonic in raw_conf."""


def test_module4_content_type_identification() -> None:
    """Module 4: table/paragraph/image chunks are labeled correctly."""


def test_module5_confidence_aware_retrieval() -> None:
    """Module 5: results are ranked by combined_score."""


def test_module6_reliability_tiers() -> None:
    """Module 6: scores map to Certain/Moderate/Uncertain/Unreadable."""


def test_module7_llm_answer_generation() -> None:
    """Module 7: POST /ask returns an Answer with a reliability_label."""
