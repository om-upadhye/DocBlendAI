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
    llm_model: str = "gemini-3.5-flash"
    top_k: int = 5  # chunks retrieved per question

    database_url: str = f"sqlite:///{(DATA_DIR / 'docblendai.db').as_posix()}"
    chroma_dir: Path = DATA_DIR / "chroma_db"
    upload_dir: Path = DATA_DIR / "uploads"


settings = Settings()
