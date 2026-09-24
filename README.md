# DocBlendAI

Confidence-aware multi-format document QA assistant: upload typed, scanned, or
handwritten academic PDFs and ask questions. Every answer carries a reliability
tier (Certain / Moderate / Uncertain / Unreadable). See `CLAUDE.md` for full
project context.

## Running

```bash
venv/Scripts/python -m pip install -r requirements.txt
venv/Scripts/python -m uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000/docs.

## Folder structure

```
app/
├── main.py                  FastAPI app, router registration, /health
├── config.py                Settings from .env (pydantic-settings)
├── routers/
│   ├── upload.py            Module 1: POST /upload
│   └── query.py             POST /ask, GET /answer/{id} (Modules 5-7)
├── modules/
│   ├── format_detection.py  Module 2: detect format, route to an extractor
│   ├── text_parser.py       Module 2: direct parsing of typed PDFs
│   ├── ocr_extractor.py     Module 2: pytesseract OCR for scanned PDFs
│   ├── htr_extractor.py     Module 2: TrOCR HTR for handwritten PDFs
│   ├── confidence_capture.py Module 3: raw -> calibrated confidence
│   ├── content_type.py      Module 4: table / paragraph / image labeling
│   ├── chunker.py           Modules 4/5: split text into chunks
│   ├── embedder.py          Module 5: Gemini embeddings
│   ├── vector_store.py      Module 5: ChromaDB wrapper
│   ├── retrieval.py         Module 5: combined_score ranking
│   ├── reliability.py       Module 6: four-tier reliability labels
│   └── llm_answer.py        Module 7: Gemini answer generation
├── db/
│   ├── database.py          SQLAlchemy engine/session (SQLite)
│   └── models.py            ORM: Document, Query, Answer, RetrievalResult
└── models/
    └── schemas.py           Pydantic entities shared by all modules
data/
├── uploads/                 Uploaded PDFs (git-ignored)
└── chroma_db/               ChromaDB persistence (git-ignored)
tests/
├── test_pipeline.py         One test stub per module
└── eval_metrics.py          Exact Match, Semantic Match, CER, WER
```
