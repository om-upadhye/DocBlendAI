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
    top_k: int = 8  # chunks retrieved per question (lists, tables and multi-part answers need several)
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
    ocr_max_side: int = 1600  # longest image side Paddle's detector uses (lower = less memory)
    # TrOCR (when htr_engine="trocr"): small runs on CPU; trocr-base-handwritten is more accurate but ~4x slower.
    htr_model: str = "microsoft/trocr-small-handwritten"
    calibration_file: Path = DATA_DIR / "calibration.json"

    # Reading hard pages with a Gemini vision model (vision_reader.py): "auto" = every handwritten
    # page + printed scans OCR found hard, "always" = every scanned/handwritten page, "off".
    vision_read: str = "auto"
    vision_model: str = "gemini-3.5-flash"  # best reading; the free tier allows ~20 pages a day
    vision_fallback_model: str = "gemini-3.5-flash-lite"  # used when the first is out of quota or fails
    vision_min_ocr_conf: float = 0.9  # auto mode: printed scans below this calibrated OCR confidence
    # When an answer from scanned / handwritten notes comes out Uncertain or "couldn't find", look
    # at the page images of the best passages once more before giving up.
    visual_recheck: bool = True

    # Layout analysis of scanned / handwritten pages (layout_analysis.py): regions, tables, reading order.
    layout_analysis: bool = True
    # rapid-layout model: pp_layout_cdla (bundled, ~7 MB) or pp_doc_layoutv2 / v3 (PP-StructureV3's
    # PP-DocLayout, more classes and more accurate, downloaded on first use, larger and slower).
    layout_model: str = "pp_layout_cdla"
    layout_min_score: float = 0.5
    # rapid-table structure model (slanet_plus, ~7 MB, downloaded once) for tables without drawn
    # lines; empty = word alignment only. Ruled tables are read from their grid (no model).
    table_model: str = "slanet_plus"
    # Read table areas again with the PaddleOCR engine (Tesseract often misses text in ruled cells).
    table_reread: bool = True
    # Load the OCR, layout, and table models at start-up (in the background) instead of on the
    # first upload, so the first user does not wait for them.
    preload_models: bool = True

    database_url: str = f"sqlite:///{(DATA_DIR / 'docblendai.db').as_posix()}"
    chroma_dir: Path = DATA_DIR / "chroma_db"
    upload_dir: Path = DATA_DIR / "uploads"

    # Public demo (hosted site, e.g. Render): each browser tab is a private session, sees only its
    # own uploads, and they are deleted soon after the tab closes. Off for local/team use.
    public_demo: bool = False
    # A session with no heartbeat for this long is ended and its documents deleted.
    session_ttl_seconds: int = 300
    # After the tab signals it is closing: grace period before deleting (a page reload comes back sooner).
    session_leave_grace_seconds: int = 20
    max_upload_mb: int = 0  # 0 = no limit
    max_pages: int = 0  # 0 = no limit; OCR/HTR of long scans is slow on small servers
    # Visitor/question counters reset at midnight in this UTC offset (5.5 = India).
    stats_utc_offset_hours: float = 5.5


settings = Settings()
