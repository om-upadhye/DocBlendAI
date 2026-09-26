"""Application settings, loaded from .env via pydantic-settings.

Shared by all modules; not tied to a single module number. Import the
module-level `settings` object rather than reading os.environ directly.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", extra="ignore")

    # Empty default keeps the app bootable without a key; Gemini calls will fail until it is set.
    gemini_api_key: str = ""
    # gemini-embedding-001 (not -2): -2 merges a list of texts into ONE vector instead of one per text.
    embedding_model: str = "gemini-embedding-001"
    embedding_dim: int = 768
    # Lite by default: the free tier allows only 20 gemini-3.5-flash answers per day per project,
    # too few for a demo or one evaluation run. Set LLM_MODEL=gemini-3.5-flash in .env on a paid key.
    llm_model: str = "gemini-3.5-flash-lite"
    top_k: int = 5  # chunks retrieved per question
    # combined_score = w * similarity + (1 - w) * calibrated confidence. Relevance dominates:
    # a clearly-read but off-topic chunk should not outrank a relevant, less legible one.
    similarity_weight: float = 0.7
    # Re-ranking pool: fetch top_k * this many by similarity, then re-sort by combined_score.
    candidate_multiplier: int = 3

    # OCR / HTR (build step 4)
    tesseract_cmd: str = ""  # path to tesseract.exe if it is not on PATH
    ocr_dpi: int = 300
    # Mean Tesseract confidence (0-1) on a page with no text layer: at or above -> printed scan,
    # below -> treated as handwriting. First guess; tune on real samples.
    scanned_min_ocr_conf: float = 0.6
    # Handwriting engine. "paddle": PaddleOCR's PP-OCRv6 models run through RapidOCR/ONNX Runtime
    # (no PaddlePaddle framework): finds every line itself, ~3 s/page on CPU, and on real ruled-notebook
    # scans read far better than TrOCR. "trocr": the synopsis's TrOCR, kept for comparison.
    htr_engine: str = "paddle"
    ocr_threads: int = 2  # CPU threads for the Paddle engine; keeps a laptop or small server responsive
    # TrOCR (when htr_engine="trocr"): small runs on CPU; trocr-base-handwritten is more accurate but ~4x slower.
    htr_model: str = "microsoft/trocr-small-handwritten"
    calibration_file: Path = DATA_DIR / "calibration.json"

    database_url: str = f"sqlite:///{(DATA_DIR / 'docblendai.db').as_posix()}"
    chroma_dir: Path = DATA_DIR / "chroma_db"
    upload_dir: Path = DATA_DIR / "uploads"


settings = Settings()
