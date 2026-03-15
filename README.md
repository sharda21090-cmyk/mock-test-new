# Mock Test — Automated (Testbook LMS)

A self-contained mock-test web application that **automatically pulls questions from the Testbook LMS**, builds a bilingual (English / Hindi) quiz, and publishes it on **Vercel** — all from a single Python script.

---

## Table of Contents

1. [How It Works](#how-it-works)
2. [Project Structure](#project-structure)
3. [Prerequisites](#prerequisites)
4. [Setup & Installation](#setup--installation)
5. [Configuration](#configuration)
6. [Running the Script](#running-the-script)
7. [Deploying to Vercel](#deploying-to-vercel)
8. [Quiz Features](#quiz-features)
9. [Google Sheet Format](#google-sheet-format)
10. [Caching](#caching)
11. [Troubleshooting](#troubleshooting)

---

## How It Works

```
Google Sheet  ──►  run.py  ──►  Questions.csv  ──►  index.html  ──►  Vercel
(QIDs, config)      │            (auto-updated)      (auto-updated)   (live URL)
                    │
               Testbook LMS API
               (fetches question text & options)
```

1. `run.py` downloads a **Google Sheet** that lists test names, question IDs (QIDs), languages, and marking schemes.
2. It logs into the **Testbook LMS API** and fetches the full content for each question ID.
3. Questions are formatted and saved to **`Questions.csv`**.
4. **`index.html`** is updated in-place — the CSV data is embedded directly inside the HTML file.
5. Commit and push the updated files; Vercel auto-deploys and the live URLs are immediately usable.

---

## Project Structure

```
mock-test - automated/
│
├── run.py                  # Main automation script
├── index.html              # Frontend quiz app (self-contained, no build step)
├── Questions.csv           # Auto-generated question data (do not edit manually)
├── vercel.json             # Vercel routing config (/test/:slug → index.html)
├── testbook_logo.png       # Logo used in the quiz UI
│
├── reference js code       # Google Apps Script reference (for Google Sheets integration)
│
├── .env                    # YOUR CREDENTIALS — never commit this file
├── .env.example            # Template showing required environment variables
├── .gitignore              # Excludes .env, cache, and compiled Python files
└── .qid_cache.json         # Local cache of fetched questions (auto-created, auto-updated)
```

---

## Prerequisites

| Requirement | Version / Notes |
|---|---|
| Python | 3.10 or later (uses `dict \| None` type hints) |
| pip packages | `requests`, `python-dotenv` |
| Testbook LMS account | Admin credentials required |
| Google Sheet | Must be shared as "Anyone with the link can view" |
| Vercel account | Free tier is sufficient |

---

## Setup & Installation

### 1. Clone / copy the project

```bash
git clone <your-repo-url>
cd "mock-test - automated"
```

### 2. Install Python dependencies

```bash
pip install requests python-dotenv
```

> If you get a permissions error on Windows, try:
> ```bash
> pip install --user requests python-dotenv
> ```

### 3. Create the `.env` credentials file

Copy the example file and fill in your Testbook LMS credentials:

```bash
copy .env.example .env
```

Edit `.env`:

```
LMS_EMAIL=your_email@testbook.com
LMS_PASSWORD=your_password
```

> **Security:** `.env` is listed in `.gitignore` and will never be committed to Git. Never share this file.

---

## Configuration

All configuration constants live at the top of `run.py` (under the `# ── CONFIG ───` section):

| Constant | Default | Description |
|---|---|---|
| `QID_SHEET_ID` | *(Google Sheet ID)* | The ID of the Google Sheet containing test configs |
| `QID_SHEET_GID` | `"0"` | Sheet/tab ID within the spreadsheet (0 = first tab) |
| `VERCEL_DOMAIN` | `https://mock-test-new.vercel.app` | Your Vercel deployment URL |
| `DEFAULT_POSITIVE` | `2.0` | Marks awarded per correct answer (fallback) |
| `DEFAULT_NEGATIVE` | `0.5` | Marks deducted per wrong answer (fallback) |
| `DEFAULT_TIME_PER_Q` | `2` | Minutes allocated per question (fallback) |

> Per-test overrides for positive marks, negative marks, and duration can be set in the Google Sheet (columns D, E, F). Values marked with `*` in the run summary use the defaults above.

---

## Running the Script

From the project folder, simply run:

```bash
python run.py
```

### What happens step by step

```
[1/4] Downloading QID sheet...        ← fetches config from Google Sheets
[2/4] Authenticating with LMS...      ← logs in if new QIDs need fetching
[3/4] Processing questions...         ← fetches/caches each question
[4/4] Writing Questions.csv...        ← saves CSV and updates index.html
```

### Sample output

```
============================================================
  Mock Test — LMS Question Sync
============================================================

  [1/4] Downloading QID sheet...
  Found 2 test(s) with 30 QID(s) total.

  [2/4] Authenticating with Testbook LMS...
  Login successful.

  [3/4] Processing questions...

  ▸ [Reasoning Quiz - March] — 15 QID(s)  +2 -0.5 30m
    link: https://mock-test-new.vercel.app?test=reasoning-quiz-march
    ↩ QID 6801abc  (cached)
    ✓ QID 6801def  (fetched)
    ...

  [4/4] Writing 30 question(s) to Questions.csv...
  Saved  -> Questions.csv
  Updated -> index.html

  Ready-to-share test URLs:

  Reasoning Quiz - March
    https://mock-test-new.vercel.app?test=reasoning-quiz-march
```

After the script finishes:
1. **Commit** the updated `Questions.csv` and `index.html`.
2. **Push** to your Git repository linked to Vercel.
3. Vercel will auto-deploy within ~30 seconds and the URLs will be live.

---

## Deploying to Vercel

### First-time setup

1. Create a free account at [vercel.com](https://vercel.com).
2. Click **Add New → Project** and import your repository.
3. No build settings are needed — the project is pure HTML/JS/CSS.
4. After deployment, copy your project's domain and update `VERCEL_DOMAIN` in `run.py`.

### `vercel.json` routing

The included `vercel.json` enables clean URLs:

```
https://your-domain.vercel.app/test/reasoning-quiz-march
```

is treated the same as:

```
https://your-domain.vercel.app?test=reasoning-quiz-march
```

Both URL formats work and can be freely shared.

---

## Quiz Features

The `index.html` front-end app includes:

- **Multiple tests** on one page — a test-picker card on landing
- **Bilingual questions** (English / Hindi combined in a single card)
- **MathJax rendering** for mathematical equations
- **Live countdown timer** per test
- **Question palette** sidebar — shows answered / marked / not-visited status at a glance
- **Mark for Review** functionality
- **Result screen** — score, accuracy, section-wise breakdown after submission
- **Solution review** — step through all questions with correct answers and explanations
- **Light / Dark theme** toggle
- **Mobile responsive** layout

---

## Google Sheet Format

The script reads from a Google Sheet with the following column layout:

| Col | Field | Required | Description |
|---|---|---|---|
| A | **Test Name** | ✅ | Display name of the test (also used to generate the URL slug) |
| B | **QIDs** | ✅ | Comma-separated Testbook question IDs (e.g. `6801abc, 6801def`) |
| C | **Lang** | ✅ | Languages to combine (e.g. `en,hi` for bilingual, `en` for English only) |
| D | **Positive Marks** | optional | Marks per correct answer. Leave blank to use default (`2.0`) |
| E | **Negative Marks** | optional | Marks deducted per wrong answer. Leave blank to use default (`0.5`) |
| F | **Test Duration** | optional | Total minutes for the test. Leave blank to auto-calculate (`questions × 2 min`) |

**Row 1** must be a header row (it is skipped automatically).

### Example sheet

| Test Name | QIDs | Lang | Positive Marks | Negative Marks | Test Duration |
|---|---|---|---|---|---|
| Reasoning Quiz March | 6801abc, 6801def, 6801ghi | en,hi | 2 | 0.5 | 30 |
| GK Quiz April | 6802xyz, 6802pqr | en | 1 | 0.25 | |

> The Google Sheet must be shared with **"Anyone with the link" → Viewer** access. The script reads it as a public CSV export — no OAuth is required.

---

## Caching

The script maintains a local `.qid_cache.json` file:

- Questions already fetched are stored here and **reused on the next run** — no redundant API calls.
- This makes re-runs very fast when only a few new questions are added to the sheet.
- The cache file is excluded from Git (`.gitignore`) since it is a local build artifact.
- To **force a full re-fetch**, delete `.qid_cache.json` and run `python run.py` again.

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `[ERROR] 'requests' not installed` | Missing dependency | Run `pip install requests python-dotenv` |
| `[ERROR] LMS credentials missing` | No `.env` file | Copy `.env.example` to `.env` and fill in credentials |
| `LMS login failed` | Wrong email/password | Double-check credentials in `.env` |
| `Access denied (HTTP 403)` on sheet | Sheet not public | Set Google Sheet sharing to "Anyone with the link → Viewer" |
| `Could not find <script id="csv-data">` | `index.html` modified | Ensure the `<script id="csv-data" type="text/csv">` tag exists in `index.html` |
| Questions show garbled HTML | Expected — HTML entities in source | The quiz front-end renders them correctly in the browser |
| New test not appearing | Slug mismatch | The URL slug is auto-generated from the Test Name (lowercased, spaces → hyphens). Verify the URL printed at the end of the run |
| Vercel shows old content | Deployment not triggered | Ensure `Questions.csv` and `index.html` were committed and pushed |

---

## Quick-Start Checklist

- [ ] Python 3.10+ installed
- [ ] `pip install requests python-dotenv` done
- [ ] `.env` file created with valid `LMS_EMAIL` and `LMS_PASSWORD`
- [ ] Google Sheet populated and shared publicly
- [ ] `QID_SHEET_ID` in `run.py` points to your sheet
- [ ] `VERCEL_DOMAIN` in `run.py` updated to your Vercel URL
- [ ] `python run.py` runs without errors
- [ ] `Questions.csv` and `index.html` committed and pushed
- [ ] Vercel deployment completed — test URLs are live ✅
