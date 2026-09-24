# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# DocBlendAI

Final-year B.Tech project (Group C4) — a confidence-aware multi-format document
QA assistant. Guide: Prof. R. A. Tiwari, Dept. of CSE, PRMIT&R Badnera.

## What it does

Students, researchers, and faculty work with academic material in mixed formats
(typed, scanned/printed, handwritten). DocBlendAI detects the format of an
uploaded document, extracts text with the right method for that format, and
answers user questions through a confidence-aware Retrieval-Augmented
Generation (RAG) pipeline — always labeling how trustworthy each answer is.

Reliability tiers: **Certain / Moderate / Uncertain / Unreadable**, derived from
jointly weighing recognition confidence and retrieval relevance.

## Scope

**In scope:** typed, scanned/printed, and handwritten academic PDFs; automatic
format detection; content-type identification (table/paragraph/image);
confidence-aware retrieval; four-tier reliability labeling.

**Out of scope:** live classroom transcription, multilingual scripts,
real-time video content.

## 7 core modules (per approved synopsis — keep names/boundaries in sync with this)

1. **Document Upload**
2. **Format Detection & Text Extraction** — routes to direct parsing / OCR / HTR
3. **Confidence Capture & Calibration**
4. **Content-Type Identification** — table / paragraph / image
5. **Confidence-Aware Retrieval (RAG)** — combined_score = similarity + calibrated confidence
6. **Reliability Tier Classification**
7. **LLM Answer Generation**

## Architecture decisions (locked — see reasoning before changing)

- **Pattern: single FastAPI monolith**, not microservices. Modules are separated
  by Python file/folder boundaries, not network boundaries — keeps deployment
  and demo simple while still letting 4 people work on separate modules in
  parallel.
- **Storage: ChromaDB + SQLite**, not ChromaDB alone.
  - ChromaDB: `RecognizedChunk.vector` + similarity search only
  - SQLite (via SQLAlchemy): `Document`, `Query`, `Answer`, `RetrievalResult` —
    anything relational/filterable (format_type, reliability_label, user_id, etc.)
  - SQLite chosen over MySQL/Postgres: zero server setup across 4 laptops,
    single file, plenty for this scale.

## Entities (from synopsis Problem Analysis table — schemas.py must match exactly)

- `Document`: doc_id, file_path, format_type, page_count
- `RecognizedChunk`: chunk_id, text, content_type, raw_conf, calibrated_conf, vector
- `Query`: query_id, question_text, user_id
- `RetrievalResult`: chunk_id, similarity, confidence, combined_score
- `Answer`: answer_id, answer_text, reliability_label

## Stack

FastAPI, ChromaDB, SQLite + SQLAlchemy, Gemini API (LLM + embeddings),
pytesseract (OCR), TrOCR/transformers (HTR), jiwer (CER/WER eval)

`requirements.txt` currently lists only python-dotenv, google-generativeai,
torch, transformers, pillow — add the rest (fastapi, uvicorn, chromadb,
sqlalchemy, pytesseract, jiwer, …) as each build step needs them.
pytesseract also requires the Tesseract binary installed on the system.

## Environment & commands

- Python 3.11 with a local virtualenv in `venv/` (git-ignored).
- The venv was created at a pre-OneDrive path (`C:\Users\USER\Desktop\Projects\DocBlendAI`).
  Call tools via the interpreter (`venv/Scripts/python -m pip ...`) rather than
  the `venv/Scripts/*.exe` launchers, which may embed the old path.
- Secrets load from `.env` via python-dotenv; `.env.example` lists required keys
  (currently `GEMINI_API_KEY`).

```bash
venv/Scripts/python -m pip install -r requirements.txt
```

## Evaluation metrics

Exact Match, Semantic Match, Character Error Rate (CER), Word Error Rate (WER)
— across all three document formats.

## Git workflow

`main → feature branch → development → commit → push → Pull Request → review → merge`

Never commit directly to `main`. Each member works on their own feature branch
for their owned module(s).

## Build order (do not skip ahead)

1. Typed-text path only (upload → parse → chunk) — no OCR/HTR, no confidence
2. Embedding + ChromaDB storage
3. Retrieval + Gemini answer generation (typed-only) — first working end-to-end checkpoint
4. Add OCR (pytesseract) + HTR (TrOCR) + confidence capture/calibration
5. Content-type identification + confidence-aware combined_score + reliability labeling
6. Evaluation metrics + frontend + polish

Do not build confidence.py, ocr_extractor.py, or reliability.py before step 3's
typed-only pipeline works end-to-end — parallel half-finished modules stall
integration.
