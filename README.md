# DocBlendAI

**Version 1.1.0** · Final-year B.Tech project (Group C4), Dept. of CSE, PRMIT&R Badnera

Confidence-aware multi-format document QA assistant: upload typed, scanned, or
handwritten academic documents and ask questions. Every answer carries a reliability
tier (Certain / Moderate / Uncertain / Unreadable).

**Supported uploads:** PDF, images (JPG, PNG, TIFF incl. multi-page, BMP, WEBP;
phone photos are turned upright automatically), Word (.docx, including tables),
PowerPoint (.pptx, one page per slide), and plain text (.txt). See `CLAUDE.md` for full
project context.

**Team members:** start with [CONTRIBUTING.md](CONTRIBUTING.md) for the Git workflow and troubleshooting.

## What you need

| Component | Version | How you get it |
|---|---|---|
| Python | **3.11** (tested 3.11.9) | https://www.python.org/downloads/release/python-3119/ (tick "Add python.exe to PATH") |
| Python packages | pinned in [`requirements.txt`](requirements.txt) | `pip install -r requirements.txt` (step 3 below) |
| Tesseract OCR | **5.4.0** (UB Mannheim build, includes `eng` + `osd` data) | `winget install UB-Mannheim.TesseractOCR` |
| Handwriting engine (default) | PaddleOCR **PP-OCRv6** models via RapidOCR 3.9.2 + ONNX Runtime 1.30.0 (~30 MB, bundled; no PaddlePaddle, no GPU) | installed with `requirements.txt` |
| TrOCR handwriting model (optional, `HTR_ENGINE=trocr`) | `microsoft/trocr-small-handwritten` (~250 MB) | downloaded by `scripts.setup_models` (step 5) into `%USERPROFILE%\.cache\huggingface` |
| Gemini API key | free tier works | https://aistudio.google.com/apikey |
| Gemini models (cloud) | `gemini-embedding-001` (embeddings), `gemini-3.5-flash-lite` (answers) | nothing to download; set in `.env` if you want others |

Main package versions: FastAPI 0.141.1 · ChromaDB 1.5.9 · SQLAlchemy 2.0.54 · google-genai 2.25.0 ·
PyTorch 2.14.0 (CPU) · transformers 5.17.0 · pytesseract 0.3.13 · pdfplumber 0.11.10 · jiwer 4.0.0.

## Installation (Windows)

1. **Get the code** (collaborators on the private repo):
   ```bash
   git clone https://github.com/om-upadhye/DocBlendAI.git
   cd DocBlendAI
   ```
2. **Create a Python 3.11 virtual environment:**
   ```bash
   py -3.11 -m venv venv
   ```
3. **Install the pinned packages** (PyTorch is large, so the first install takes a while):
   ```bash
   venv/Scripts/python -m pip install --upgrade pip
   venv/Scripts/python -m pip install -r requirements.txt
   ```
   With an NVIDIA GPU, first install `torch==2.14.0` and `torchvision==0.29.0` for your CUDA
   version from https://pytorch.org/get-started/locally/, then run the line above.
4. **Install Tesseract OCR:**
   ```bash
   winget install UB-Mannheim.TesseractOCR
   ```
   The default location (`C:\Program Files\Tesseract-OCR`) is found automatically; otherwise set
   `TESSERACT_CMD` in `.env` to the full path of `tesseract.exe`.
5. **Add your Gemini key and download the model:** copy `.env.example` to `.env`, put your key after
   `GEMINI_API_KEY=`, then run the setup check. It downloads the TrOCR model and reports anything missing:
   ```bash
   venv/Scripts/python -m scripts.setup_models
   ```
   > Never put a real key in `.env.example`: that file is committed; `.env` is not.

## Running

```bash
venv/Scripts/python -m uvicorn app.main:app --reload
```

- **App:** http://127.0.0.1:8000/ to upload documents, tick which ones to ask about, ask questions, and see reliability labels and sources.
  **View** on a document opens the page viewer: each page image with every recognised line boxed and
  coloured by confidence (green clear / amber partly legible / red poor), next to the recognised text.
- **API docs:** http://127.0.0.1:8000/docs

If the server refuses to start with "database is out of date", delete `data/docblendai.db`
and the contents of `data/chroma_db/` (local dev data), restart, and re-upload.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/upload` | Upload a PDF, image, .docx, .pptx, or .txt (optional `format_hint`: typed / scanned / handwritten) |
| GET | `/documents` | List uploaded documents (oldest first) |
| DELETE | `/documents/{id}` | Remove a document (database, vector store, file, and page view) |
| GET | `/documents/{id}/pages` | Page viewer data: recognised text, lines with boxes and confidence, image link |
| GET | `/documents/{id}/pages/{n}/image` | The page image recognition read |
| POST | `/ask` | Ask a question → answer + reliability label. Optional `doc_ids` limits it to those documents; omit to search all |
| GET | `/answer/{id}` | Fetch a stored answer |
| GET | `/answer/{id}/sources` | Chunks behind an answer, with similarity, confidence, content type |

## Testing and evaluation

```bash
venv/Scripts/python -m pytest
venv/Scripts/python -m evaluation.make_dataset
venv/Scripts/python -m evaluation.run_eval --fit-calibration
```

Tests fake Tesseract, TrOCR, and Gemini, so they run offline. The evaluation uses the
real engines: it generates a synthetic dataset (typed, degraded scans, handwriting-style
fonts), measures CER/WER, fits confidence calibration into `data/calibration.json`,
and scores question answering (Exact Match, Semantic Match, retrieval hits, accuracy per
reliability tier). The latest report is in [evaluation/results/report.md](evaluation/results/report.md).

## Folder structure

```
app/
├── main.py                  FastAPI app, router registration, /health, serves the UI
├── config.py                Settings from .env (pydantic-settings)
├── static/index.html        Demo UI
├── routers/
│   ├── upload.py            Module 1: POST /upload, GET/DELETE /documents
│   └── query.py             POST /ask, GET /answer/{id}[/sources] (Modules 5-7)
├── modules/
│   ├── format_detection.py  Module 2: detect format, route to an extractor
│   ├── text_parser.py       Module 2: direct parsing of PDF / Word / PowerPoint / text
│   ├── file_types.py        Modules 1-2: supported upload formats
│   ├── pdf_render.py        Module 2: PDF pages / image files -> page images, denoise
│   ├── ocr_extractor.py     Module 2: pytesseract OCR, page-orientation correction
│   ├── paddle_extractor.py  Module 2: handwriting via PaddleOCR PP-OCRv6 (default engine)
│   ├── htr_extractor.py     Module 2: TrOCR HTR (optional engine), ruled-notebook segmentation
│   ├── page_store.py        Modules 1-2: page images + line boxes for the viewer
│   ├── confidence_capture.py Module 3: raw -> calibrated confidence
│   ├── content_type.py      Module 4: table / paragraph / image labeling
│   ├── chunker.py           Modules 4/5: split text into chunks
│   ├── embedder.py          Module 5: Gemini embeddings
│   ├── vector_store.py      Module 5: ChromaDB wrapper
│   ├── retrieval.py         Module 5: combined_score ranking
│   ├── reliability.py       Module 6: four-tier reliability labels
│   └── llm_answer.py        Module 7: Gemini answer generation
├── db/
│   ├── database.py          SQLAlchemy engine/session (SQLite), schema check
│   └── models.py            ORM: Document, Query, Answer, RetrievalResult
└── models/
    └── schemas.py           Pydantic entities shared by all modules
scripts/
└── setup_models.py          One-time setup check + TrOCR model download
data/
├── uploads/                 Uploaded documents (git-ignored)
├── chroma_db/               ChromaDB persistence (git-ignored)
└── calibration.json         Fitted confidence calibration (committed, shared)
evaluation/
├── make_dataset.py          Synthetic typed / scanned / handwritten dataset
├── run_eval.py              Recognition, calibration, and QA evaluation
└── results/report.md        Latest evaluation report
tests/
├── test_*.py                Unit and API tests (offline)
└── eval_metrics.py          Exact Match, Semantic Match, CER, WER
```
