# Deploying DocBlendAI on Render

The repo is ready for [Render](https://render.com): `render.yaml` (a Render "Blueprint") builds the
existing `Dockerfile`, which already includes Tesseract and the handwriting models.

## What the hosted demo does

- **Upload → preview → ask.** The uploaded document is shown in the middle panel (PDF viewer, image,
  or page text for Word/PowerPoint/text) while the visitor asks questions on the right.
- **Private, temporary files.** `PUBLIC_DEMO=true` gives every browser tab its own session: a visitor
  only sees their own uploads. When the tab closes (or stops sending its heartbeat for
  `SESSION_TTL_SECONDS`, default 5 minutes), the file, its page images, and its vectors are deleted.
  A page reload within ~20 seconds keeps the files.
- **Usage counter.** The header shows *visitors today* and *questions today* (hover for all-time
  totals). Days roll over at midnight India time (`STATS_UTC_OFFSET_HOURS=5.5`).
- **Limits** for a small server: 20 MB per file, 30 pages per document (`MAX_UPLOAD_MB`, `MAX_PAGES`).

## Step 1: Put the code on GitHub

```bash
git push -u <remote> <branch>
```

Render deploys from a GitHub branch. Keep `.env` out of git; it already is (`.gitignore`). Never
put the real key in `.env.example`.

## Step 2: Create the service on Render

1. Sign in at https://dashboard.render.com with GitHub.
2. **New → Blueprint**, choose the repository, and the branch you pushed.
3. Render reads `render.yaml` and shows a service called `docblendai`. It asks for
   **`GEMINI_API_KEY`**: paste your key there (it is stored as a secret on Render, not in git).
4. Click **Apply**. The first build takes about 5 to 10 minutes (it installs OCR packages).
5. When the status is **Live**, open the URL Render shows (`https://docblendai-xxxx.onrender.com`).
   `/health` should return `{"status":"ok"}`.

If you would rather not use a Blueprint: **New → Web Service → your repo → Language: Docker**,
Health Check Path `/health`, and add the environment variables from `render.yaml` by hand.

To deploy from a branch other than `main`, change `branch:` in `render.yaml` (or the service's
**Settings → Build & Deploy → Branch**).

## Step 3: Updating the site

`autoDeploy: true`: every push (or merged pull request) to the deployed branch rebuilds and
redeploys automatically. Manual redeploy: **Manual Deploy → Deploy latest commit**.

## Contributors: pull requests

Contributors never push to the deployed branch directly:

1. The owner adds them under GitHub **Settings → Collaborators** (or they fork the repo).
2. They create a branch: `git checkout -b feature/<what>`.
3. Commit, `git push -u origin feature/<what>`, and open a Pull Request into the deployed branch.
4. The owner reviews and merges; Render then redeploys on its own.

Optional: **Settings → Branches → Add rule** on the deployed branch with *Require a pull request
before merging*, so nobody (including you) can push to it by accident.

## Free plan limits (good to know before a demo)

| Limit | Effect | Fix |
|---|---|---|
| Sleeps after 15 min without visitors | First visit then takes ~1 minute to wake up | Open the site a few minutes before the demo, or use a paid plan |
| 512 MB memory | Typed PDFs and printed scans are fine; long handwritten scans may run out of memory and restart | `plan: standard` (2 GB) in `render.yaml` |
| No permanent disk | Visitor/question counters reset on every redeploy or wake-up | Paid plan + a Render Disk mounted at `/data` |
| Gemini free quota | When the daily quota is used up, questions fail with "Gemini service failed" | Paid Gemini key, or `LLM_MODEL` with a higher free quota |

## Settings

All optional except the key; set them under **Environment** on Render.

| Variable | Render value | Meaning |
|---|---|---|
| `GEMINI_API_KEY` | (secret) | Gemini key for embeddings and answers |
| `PUBLIC_DEMO` | `true` | Private per-tab documents, deleted when the visitor leaves. Leave unset for local/team use |
| `SESSION_TTL_SECONDS` | `300` | Delete a session's files after this long without a heartbeat |
| `MAX_UPLOAD_MB` | `20` | Largest accepted file (0 = no limit) |
| `MAX_PAGES` | `30` | Most pages per document (0 = no limit) |
| `OCR_THREADS` | `1` | CPU threads for handwriting recognition |
| `LLM_MODEL` | (default) | Gemini model for answers |
