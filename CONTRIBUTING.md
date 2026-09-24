# Contributing to DocBlendAI

Team guide for Group C4. Read `README.md` for what the project does and `CLAUDE.md`
for the architecture decisions (they are locked; discuss before changing them).

## First-time setup (Windows)

1. **Clone** (you need to be a collaborator on the private repo):
   ```bash
   git clone https://github.com/om-upadhye/DocBlendAI.git
   cd DocBlendAI
   ```
2. **Python 3.11 virtualenv** and dependencies:
   ```bash
   py -3.11 -m venv venv
   venv/Scripts/python -m pip install -r requirements.txt
   ```
   Always run tools through `venv/Scripts/python -m ...` (not the `venv/Scripts/*.exe` launchers).
3. **Tesseract OCR** (needed for scanned PDFs):
   ```bash
   winget install UB-Mannheim.TesseractOCR
   ```
   It installs to `C:\Program Files\Tesseract-OCR`, which the app finds automatically.
4. **Gemini API key:** copy `.env.example` to `.env` and put your key after `GEMINI_API_KEY=`.
   Get a key at https://aistudio.google.com/apikey.
   > **Never put a real key in `.env.example`** or any other committed file. `.env` is git-ignored; `.env.example` is not.
5. **Run it:**
   ```bash
   venv/Scripts/python -m uvicorn app.main:app --reload
   ```
   Open http://127.0.0.1:8000/ (app) or http://127.0.0.1:8000/docs (API).
   The first handwritten upload downloads the TrOCR model (~250 MB, once).

## Daily workflow

`main` → feature branch → commits → push → Pull Request → review → merge.

1. Start from an up-to-date `main`:
   ```bash
   git checkout main
   git pull
   git checkout -b feature/<short-name>
   ```
2. Commit small, focused changes with messages that say **what** changed and **why**.
3. Run the tests before pushing:
   ```bash
   venv/Scripts/python -m pytest
   ```
4. Push and open a PR into `main`:
   ```bash
   git push -u origin feature/<short-name>
   ```
5. At least **one teammate reviews** before merging. The author merges after approval.

Rules:
- **Never commit directly to `main`.**
- **Never commit secrets** (`.env`, API keys) or local data (`data/uploads/`, `data/chroma_db/`, `data/*.db` are git-ignored).
- Keep module names and boundaries as listed in `CLAUDE.md` (the 7 synopsis modules).
- `app/models/schemas.py` must match the synopsis entity table exactly.

## Where things live

| Module | File(s) |
|---|---|
| 1. Document Upload | `app/routers/upload.py` |
| 2. Format Detection & Text Extraction | `app/modules/format_detection.py`, `text_parser.py`, `ocr_extractor.py`, `htr_extractor.py`, `pdf_render.py` |
| 3. Confidence Capture & Calibration | `app/modules/confidence_capture.py`, `data/calibration.json` |
| 4. Content-Type Identification | `app/modules/content_type.py` |
| 5. Confidence-Aware Retrieval | `app/modules/chunker.py`, `embedder.py`, `vector_store.py`, `retrieval.py` |
| 6. Reliability Tier Classification | `app/modules/reliability.py` |
| 7. LLM Answer Generation | `app/modules/llm_answer.py`, `app/routers/query.py` |
| Evaluation | `evaluation/`, `tests/eval_metrics.py` |
| Frontend | `app/static/index.html` |

## Tests and evaluation

- `venv/Scripts/python -m pytest`: offline unit/API tests. Tesseract, TrOCR, and Gemini are faked, so no key or network is needed. A guard fails any test that tries to load the real TrOCR model.
- Full evaluation with the real engines and Gemini (takes ~15 minutes):
  ```bash
  venv/Scripts/python -m evaluation.make_dataset
  venv/Scripts/python -m evaluation.run_eval --fit-calibration
  ```
  Writes `evaluation/results/report.md` and refits `data/calibration.json`. Commit both when you change recognition or calibration.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Server refuses to start: "database … is out of date" | The table layout changed. Stop the server, delete `data/docblendai.db` and the contents of `data/chroma_db/` (keep `.gitkeep`), restart, re-upload. |
| Upload returns **503** mentioning Tesseract | Install Tesseract (setup step 3), or set `TESSERACT_CMD` in `.env` to the full path of `tesseract.exe`. |
| Upload returns **503** mentioning the HTR model | First run needs internet to download TrOCR; also rerun `pip install -r requirements.txt` (needs `sentencepiece`, `torchvision`). |
| `/ask` returns **502** | Gemini is busy or rate-limited (the app already retries). Wait a minute; check `GEMINI_API_KEY` in `.env`. |
| `/ask` returns **409** | That `query_id` was used before; send a new one (the web UI does this for you). |
| `gh` not found after installing GitHub CLI | Open a new terminal, or call `"C:\Program Files\GitHub CLI\gh.exe"`. |
