"""
run.py — Fetch questions from Testbook LMS and publish to Vercel.

Reads test config from Google Sheet (private, via service account):
  Sheet ID : 1EkDmE_F2_owUGNOZGkFIa7nNAxFPbeVbn6rsMJAhA2U
  Sub-sheet: Main

Expected columns (header names, order doesn't matter):
  Task Id          — test name / identifier
  Qids             — comma-separated LMS question IDs
  Paid or YT/Master class — filter: only rows with "YT/Master class" are published
  Lang             — (optional) e.g. "en,hi"  default: en,hi
  Positive Marks   — (optional) default 2.0
  Negative Marks   — (optional) default 0.5
  Test Duration    — (optional) minutes; default = question_count × 2

Place your Google service account JSON at:
  service_account.json  (same folder as run.py)

Create a .env file with:
  LMS_EMAIL=your_email@testbook.com
  LMS_PASSWORD=your_password
"""

import re
import os
import sys
import json
import csv
import io
import urllib.request
import urllib.error

try:
    import requests
except ImportError:
    print("[ERROR] 'requests' not installed. Run: pip install requests python-dotenv gspread google-auth")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[ERROR] 'python-dotenv' not installed. Run: pip install requests python-dotenv gspread google-auth")
    sys.exit(1)

try:
    from google.oauth2.service_account import Credentials as SACredentials
    from googleapiclient.discovery import build as google_build
except ImportError:
    print("[ERROR] 'google-auth' / 'google-api-python-client' not installed. Run: pip install google-auth google-api-python-client")
    sys.exit(1)

# ── Load .env ────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"), override=True)

LMS_EMAIL    = os.getenv("LMS_EMAIL", "")
LMS_PASSWORD = os.getenv("LMS_PASSWORD", "")

# ── CONFIG ───────────────────────────────────────────────────────────
SHEET_ID       = "1EkDmE_F2_owUGNOZGkFIa7nNAxFPbeVbn6rsMJAhA2U"
SHEET_TAB      = "Main sheet"
SA_CREDS_PATH  = os.path.join(SCRIPT_DIR, "service_account.json")

VERCEL_DOMAIN = "https://mock-test-new.vercel.app"

# Defaults (used when not overridden per test)
DEFAULT_POSITIVE      = 2.0
DEFAULT_NEGATIVE      = 0.5
DEFAULT_TIME_PER_Q    = 2   # minutes per question

LMS_BASE          = "http://lms-api.testbook.com"
LMS_LOGIN_URL     = LMS_BASE + "/api/v2/admin/login"
LMS_QUESTIONS_URL = "https://lms-api.testbook.com/api/v2/questions/get?language=All&limit=1&skip=0"

INDEX_PATH  = os.path.join(SCRIPT_DIR, "index.html")
CSV_PATH    = os.path.join(SCRIPT_DIR, "Questions.csv")
CACHE_PATH  = os.path.join(SCRIPT_DIR, ".qid_cache.json")
DATA_DIR    = os.path.join(SCRIPT_DIR, "data")

# Language keys are read per-row from the sheet

# ── CACHE ─────────────────────────────────────────────────────────────

def load_cache() -> dict:
    """Load {qid: [csv_row_list]} from the local cache file."""
    if os.path.exists(CACHE_PATH):
        try:
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def save_cache(cache: dict):
    """Persist the cache to disk."""
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


# ── HELPERS ──────────────────────────────────────────────────────────

def open_sheet() -> list[dict]:
    """Open the private Google Sheet using service account credentials.
    Returns all rows as a list of dicts keyed by header name.
    """
    if not os.path.exists(SA_CREDS_PATH):
        raise RuntimeError(
            f"Service account credentials not found at: {SA_CREDS_PATH}\n"
            "  1. Create a service account in Google Cloud Console.\n"
            "  2. Download the JSON key and save it as service_account.json\n"
            "  3. Share the Google Sheet with the service account email (client_email in the JSON)."
        )
    scopes  = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds   = SACredentials.from_service_account_file(SA_CREDS_PATH, scopes=scopes)
    service = google_build("sheets", "v4", credentials=creds)
    result  = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{SHEET_TAB}!A:Z"
    ).execute()
    values  = result.get("values", [])
    if not values:
        return []
    headers = values[0]
    rows = []
    for row in values[1:]:
        padded = row + [""] * (len(headers) - len(row))
        rows.append(dict(zip(headers, padded)))
    return rows


def slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r'[_\s]+', '-', s)
    s = re.sub(r'[^a-z0-9-]', '', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


# ── LANGUAGE NORMALIZATION ─────────────────────────────────────────
LANGUAGE_MAP = {
    # codes
    "en": "en", "hi": "hi", "hn": "hi",  # accept common typo 'hn' → 'hi'
    "te": "te", "mr": "mr", "bn": "bn", "gu": "gu",
    "kn": "kn", "ta": "ta", "or": "or", "pa": "pa",
    # full names
    "english": "en", "hindi": "hi", "telugu": "te",
    "marathi": "mr", "bengali": "bn", "gujarati": "gu",
    "kannada": "kn", "tamil": "ta", "odia": "or", "oriya": "or",
    "punjabi": "pa",
}


def normalize_lang_token(tok: str) -> str | None:
    """Convert a single token (code or name) into an LMS language code.

    Returns None if token is empty or unrecognized.
    """
    if not tok:
        return None
    t = tok.strip().lower()
    # direct map
    if t in LANGUAGE_MAP:
        return LANGUAGE_MAP[t]
    # try stripping non-letters and map again
    t2 = re.sub(r'[^a-z]', '', t)
    return LANGUAGE_MAP.get(t2)


def extract_langs_from_row(row: dict) -> list:
    """Find a language field in `row` and return a list of LMS language codes.

    Looks for common header names ('Languages', 'Lang', 'Language', case-insensitive).
    If nothing is found or parsed, returns default ['en','hi'].
    """
    candidates = [
        "Languages", "Languages ", "Lang", "Language", "language", "languages",
    ]
    raw = None
    # prefer explicit keys if present
    for k in candidates:
        if k in row and str(row.get(k, "")).strip():
            raw = str(row.get(k, "") or "").strip()
            break

    # fallback: try to find any header with 'lang' or 'language' in its name (case-insensitive)
    if not raw:
        for k in row.keys():
            if "lang" in k.lower() or "language" in k.lower():
                v = str(row.get(k, "") or "").strip()
                if v:
                    raw = v
                    break

    if not raw:
        return ["en", "hi"]

    # Split on common separators
    parts = re.split(r"[,/|;+]", raw)
    codes = []
    for p in parts:
        c = normalize_lang_token(p)
        if c and c not in codes:
            codes.append(c)

    if not codes:
        return ["en", "hi"]
    return codes


# ── LMS AUTH ─────────────────────────────────────────────────────────

def auto_login(email: str, password: str) -> str:
    """POST to LMS login and return the Bearer token.
    The JS callApi sends payload as form-encoded (not JSON), so we do the same.
    """
    payload = {"email": email, "password": password, "otp": ""}
    try:
        # Use data= (form-encoded) — matches UrlFetchApp 'payload' in the JS reference
        resp = requests.post(LMS_LOGIN_URL, data=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        token = data.get("token", "")
        if not token:
            raise RuntimeError(
                f"Login succeeded but no token returned.\nResponse: {resp.text[:200]}"
            )
        return token
    except requests.HTTPError as e:
        msg = f"LMS login HTTP error {e.response.status_code}"
        msg += f"\nResponse: {e.response.text[:300]}"
        raise RuntimeError(msg)
    except requests.RequestException as e:
        raise RuntimeError(f"LMS login failed: {e}")


# ── FETCH QUESTION ───────────────────────────────────────────────────

def fetch_question(qid: str, token: str) -> dict | None:
    """Fetch one question from LMS API and return the raw question dict."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {"role": "admin", "ids": [qid]}
    try:
        resp = requests.post(LMS_QUESTIONS_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        questions = resp.json().get("data", {}).get("questions", [])
        if not questions:
            return None
        return questions[0]
    except requests.RequestException as e:
        print(f"    [WARN] Failed to fetch QID {qid}: {e}")
        return None


# ── MULTILANG EXTRACTION (mirrors reference JS multiLang function) ─────

def combine(val_en: str, val_hi: str) -> str:
    """Return combined value: same → keep one, different → 'en / hi'."""
    en = (val_en or "").strip()
    hi = (val_hi or "").strip()
    if en == hi:
        return en
    return f"{en} / {hi}"




def extract_multilang_row(test_id: str, q: dict, test_link: str,
                           positive: float, negative: float, time_val: int,
                           lang_primary: str = "en",
                           lang_secondary: str | None = "hi") -> list | None:
    """
    Mirror of the JS multiLang function.
    Returns a CSV row list or None if data is missing.
    """
    primary   = q.get(lang_primary)
    secondary = q.get(lang_secondary) if lang_secondary else None

    if not primary:
        return None

    # ── Statement ────────────────────────────────────────────────────
    stmt_p = (primary.get("value") or "").strip()
    stmt_s = (secondary.get("value") or "").strip() if secondary else ""
    # Use <br> so the Hindi line renders on a new line (index.html uses innerHTML)
    statement = stmt_p + ("<br>" + stmt_s if stmt_s else "")

    # ── Correct option index ─────────────────────────────────────────
    correct_answer = primary.get("co", 1)

    # ── Options ──────────────────────────────────────────────────────
    p_opts = primary.get("options", [])
    s_opts = secondary.get("options", []) if secondary else []

    def get_opt(opts, idx):
        if idx < len(opts) and opts[idx]:
            return (opts[idx].get("value") or "").strip()
        return ""

    opt1 = combine(get_opt(p_opts, 0), get_opt(s_opts, 0))
    opt2 = combine(get_opt(p_opts, 1), get_opt(s_opts, 1))
    opt3 = combine(get_opt(p_opts, 2), get_opt(s_opts, 2))
    opt4 = combine(get_opt(p_opts, 3), get_opt(s_opts, 3))

    # ── Solution ──────────────────────────────────────────────────────
    def get_sol(lang_data):
        sols = lang_data.get("sol", [])
        if sols and len(sols) > 0:
            return (sols[0].get("value") or "").strip()
        return ""

    sol_p = get_sol(primary)
    sol_s = get_sol(secondary) if secondary else ""
    # Combine solutions similar to statements (with a new line)
    solution = sol_p + ("<br><br>" + sol_s if sol_s else "")

    return [
        test_id,
        statement,
        opt1,
        opt2,
        opt3,
        opt4,
        correct_answer,
        positive,
        negative,
        time_val,
        solution,
        test_link,
    ]


# ── WRITE HTML LINKS BACK TO SHEET ───────────────────────────────────

def _col_letter(idx: int) -> str:
    """Convert 0-based column index to A1 column letter (supports up to ZZ)."""
    result = ""
    n = idx + 1
    while n > 0:
        n, rem = divmod(n - 1, 26)
        result = chr(ord("A") + rem) + result
    return result


ALLOWED_CATEGORIES_FOR_LINKS = {
    "Teaching Exams",
    "State Exams",
    "Banking Exams",
    "SSC Exams",
    "Railway Exams",
    "Defence Exams",
}


def write_html_links_to_sheet(sheet_rows: list[dict]):
    """Write generated test URLs into the 'HTML Link' column of the Google Sheet.

    Applies the same two filters used in parse_sheet_rows:
      • 'Paid or YT/Master class' == 'YT/Master class'
      • 'Category Name'  in ALLOWED_CATEGORIES_FOR_LINKS
    The link is computed directly from the Task Id slug — no current-run
    dependency, so it works for all matching rows in one shot.
    """
    if not os.path.exists(SA_CREDS_PATH):
        print("  [WARN] Service account credentials not found — skipping HTML Link update.")
        return

    scopes  = ["https://www.googleapis.com/auth/spreadsheets"]
    creds   = SACredentials.from_service_account_file(SA_CREDS_PATH, scopes=scopes)
    service = google_build("sheets", "v4", credentials=creds)

    # Read current sheet to locate column positions
    result = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{SHEET_TAB}!A:ZZ"
    ).execute()
    values = result.get("values", [])
    if not values:
        print("  [WARN] Sheet is empty — skipping HTML Link update.")
        return

    headers = list(values[0])

    def _col(name):
        return headers.index(name) if name in headers else None

    task_id_col   = _col("Task Id")
    category_col  = _col("Paid or YT/Master class")
    cat_name_col  = _col("Category Name")

    if task_id_col is None:
        print("  [WARN] 'Task Id' column not found in sheet — skipping HTML Link update.")
        return

    if "HTML Link" in headers:
        link_col_idx = headers.index("HTML Link")
    else:
        # Column doesn't exist yet — append it to the header row
        link_col_idx = len(headers)
        header_col = _col_letter(link_col_idx)
        service.spreadsheets().values().update(
            spreadsheetId=SHEET_ID,
            range=f"{SHEET_TAB}!{header_col}1",
            valueInputOption="RAW",
            body={"values": [["HTML Link"]]},
        ).execute()

    link_col = _col_letter(link_col_idx)

    def _cell(row, idx):
        return row[idx].strip() if idx is not None and idx < len(row) else ""

    updates = []
    for row_idx, row in enumerate(values[1:], start=2):   # row 1 is the header
        task_id       = _cell(row, task_id_col)
        category      = _cell(row, category_col)
        category_name = _cell(row, cat_name_col)

        if not task_id:
            continue
        if category != "YT/Master class":
            continue
        if category_name not in ALLOWED_CATEGORIES_FOR_LINKS:
            continue

        link = f"{VERCEL_DOMAIN}?test={slugify(task_id)}"
        updates.append({
            "range":  f"{SHEET_TAB}!{link_col}{row_idx}",
            "values": [[link]],
        })

    if not updates:
        print("  [WARN] No rows matched the filters for 'HTML Link' update.")
        return

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "RAW", "data": updates},
    ).execute()
    print(f"  Updated 'HTML Link' column for {len(updates)} row(s) in Google Sheet.")


# ── PARSE QID SHEET ──────────────────────────────────────────────────

def parse_sheet_rows(rows: list[dict]) -> list[dict]:
    """
    Parse rows from the Google Sheet (list of dicts from gspread).
    Filters to rows where 'Paid or YT/Master class' == 'YT/Master class'.
    Selects a sample of QIDs from the end based on total count.
    """
    result = []

    def _float(val):
        try:    return float(str(val).strip())
        except: return None

    def _int(val):
        try:    return int(float(str(val).strip()))
        except: return None

    for row in rows:
        task_id       = str(row.get("Task Id", "")).strip()
        qids_raw      = str(row.get("Qids", "")).strip()
        category      = str(row.get("Paid or YT/Master class", "")).strip()
        category_name = str(row.get("Category Name", "")).strip()

        if not task_id or not qids_raw:
            continue

        if category != "YT/Master class":
            continue

        if category_name not in ALLOWED_CATEGORIES_FOR_LINKS:
            continue

        all_qids = [q.strip() for q in qids_raw.split(",") if q.strip()]
        if not all_qids:
            continue

        n = len(all_qids)
        if n < 30:
            keep = 5
        elif 30 <= n <= 50:
            keep = 10
        elif 51 <= n <= 150:
            keep = 25
        elif 151 <= n <= 200:
            keep = 5
        else:
            keep = 5

        qids = all_qids[-keep:] if keep > 0 else all_qids

        # Normalize language field: accept 'Lang' or 'Languages' (or similar)
        lang_list = extract_langs_from_row(row)
        lang = ",".join(lang_list)
        positive = _float(row.get("Positive Marks", ""))
        negative = _float(row.get("Negative Marks", ""))
        duration = _int(row.get("Test Duration", ""))

        test_link = f"{VERCEL_DOMAIN}?test={slugify(task_id)}"

        result.append({
            "test_name": task_id,
            "qids":      qids,
            "lang":      lang,
            "positive":  positive,
            "negative":  negative,
            "duration":  duration,
            "test_link": test_link,
        })

    return result


# ── ANALYZE (same logic as before, works on CSV text) ────────────────

def analyze_tests(csv_text: str):
    reader = csv.reader(io.StringIO(csv_text))
    rows   = list(reader)
    tests  = {}
    total  = 0

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        if len(row) < 7 or not row[1].strip():
            continue

        test_id = row[0].strip()
        total  += 1

        if test_id not in tests:
            positive = negative = time_min = None
            try: positive = float(row[7].strip()) if len(row) > 7 and row[7].strip() else None
            except ValueError: pass
            try: negative = float(row[8].strip()) if len(row) > 8 and row[8].strip() else None
            except ValueError: pass
            try: time_min = int(float(row[9].strip())) if len(row) > 9 and row[9].strip() else None
            except ValueError: pass

            tests[test_id] = {
                "slug":     slugify(test_id),
                "count":    0,
                "positive": positive,
                "negative": negative,
                "time_min": time_min,
            }
        tests[test_id]["count"] += 1

    return tests, total


# ── WRITE PER-TEST JSON FILES ───────────────────────────────────────

def write_data_files(all_rows: list, tests: dict):
    """Write data/manifest.json and data/{slug}.json for every test."""
    os.makedirs(DATA_DIR, exist_ok=True)

    # Build a lookup: test_id -> list of question rows (skip header at index 0)
    test_rows: dict[str, list] = {}
    for row in all_rows[1:]:
        if not row or not row[0].strip():
            continue
        tid = row[0].strip()
        test_rows.setdefault(tid, []).append(row)

    manifest = []
    for test_id, info in tests.items():
        slug = info["slug"]
        rows = test_rows.get(test_id, [])

        questions = []
        for row in rows:
            questions.append({
                "statement":   row[1] if len(row) > 1 else "",
                "options":     [row[i] if len(row) > i else "" for i in range(2, 6)],
                "answer":      row[6] if len(row) > 6 else "1",
                "explanation": row[10] if len(row) > 10 else "",
            })

        test_data = {
            "title":           test_id,
            "slug":            slug,
            "positiveMarking": info["positive"],
            "negativeMarking": info["negative"],
            "timeMinutes":     info["time_min"],
            "questions":       questions,
        }

        out_path = os.path.join(DATA_DIR, f"{slug}.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(test_data, f, ensure_ascii=False, separators=(",", ":"))

        manifest.append({"title": test_id, "slug": slug, "count": info["count"]})

    manifest_path = os.path.join(DATA_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    return len(tests)


# ── UPDATE index.html ────────────────────────────────────────────────

def update_index_html(csv_text: str, tests: dict, total_q: int):
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    page_title = list(tests.keys())[0] if len(tests) == 1 else "Mock Tests"

    # title tag
    tp = re.compile(r'(<title>)(.*?)(</title>)', re.DOTALL)
    if tp.search(html):
        html = tp.sub(lambda m: m.group(1) + f"Testbook | {page_title}" + m.group(3), html)

    # Empty the inline CSV (data is now served via data/{slug}.json)
    csv_pat = re.compile(r'(<script\s+id="csv-data"\s+type="text/csv">)(.*?)(</script>)', re.DOTALL)
    if csv_pat.search(html):
        html = csv_pat.sub(lambda m: m.group(1) + m.group(3), html)
    else:
        print("[WARNING] Could not find <script id=\"csv-data\"> in index.html.")

    # quiz-data JSON
    jp = re.compile(r'(<script\s+id="quiz-data"\s+type="application/json">)(.*?)(</script>)', re.DOTALL)
    jm = jp.search(html)
    if jm:
        try:
            qd = json.loads(jm.group(2))
        except json.JSONDecodeError:
            qd = {}

        qd["quizTitle"]        = page_title
        qd["questions"]        = []
        qd["totalTime"]        = 0
        qd["positiveMarking"]  = DEFAULT_POSITIVE
        qd["negativeMarking"]  = DEFAULT_NEGATIVE
        qd["timePerQuestion"]  = DEFAULT_TIME_PER_Q

        ins = qd.get("instructionStrings", {})
        ins["totalTime"]   = "Time: -- minutes"
        ins["totalMarks"]  = "Total Marks: --"
        ins["instruction1"] = f"The quiz contains {total_q} questions total."
        ins["instruction2"] = "Each question has 4 options, and only 1 option is correct."
        ins["instruction3"] = "Time will be computed based on test selected."
        pos_d = f"{DEFAULT_POSITIVE:g}"
        neg_d = f"{DEFAULT_NEGATIVE:g}"
        ins["instruction4"] = (
            f"Negative marking applies: {neg_d} marks will be deducted for each incorrect answer."
            if DEFAULT_NEGATIVE > 0 else "There is no negative marking."
        )
        ins["instruction5"] = f"{pos_d} mark(s) will be awarded for each correct answer."
        qd["instructionStrings"] = ins

        html = jp.sub(
            lambda m: m.group(1) + "\n" + json.dumps(qd, indent=4, ensure_ascii=False) + "\n    " + m.group(3),
            html,
        )
    else:
        print("[WARNING] Could not find <script id=\"quiz-data\"> in index.html.")

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)


# ── MAIN ─────────────────────────────────────────────────────────────

def main():
    # Force UTF-8 for stdout/stderr to avoid charmap errors on Windows terminals
    if sys.stdout.encoding != 'utf-8':
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

    print("=" * 60)
    print("  Mock Test — LMS Question Sync")
    print("=" * 60)
    print()

    # Validate credentials
    if not LMS_EMAIL or not LMS_PASSWORD:
        print("[ERROR] LMS credentials missing.")
        print("  Create a .env file next to run.py with:")
        print("    LMS_EMAIL=your_email@testbook.com")
        print("    LMS_PASSWORD=your_password")
        sys.exit(1)

    # Step 1 – Read Google Sheet via service account
    print("  [1/4] Reading Google Sheet via service account...")
    try:
        sheet_rows  = open_sheet()
        tests_input = parse_sheet_rows(sheet_rows)
    except RuntimeError as e:
        print(f"\n  [ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  [ERROR] Could not read Google Sheet: {e}")
        sys.exit(1)

    if not tests_input:
        print("\n  [ERROR] No 'YT/Master class' rows with QIDs found in the sheet.")
        print("  Make sure the 'Paid or YT/Master class' column contains 'YT/Master class'")
        print("  and the 'Qids' column has comma-separated question IDs.")
        sys.exit(1)

    total_qids = sum(len(t["qids"]) for t in tests_input)
    print(f"  Found {len(tests_input)} test(s) with {total_qids} QID(s) total.\n")

    # ── Step 2: figure out which QIDs need fresh API calls ──────────
    cache = load_cache()

    new_qids_exist = any(
        qid.strip() not in cache
        for t in tests_input
        for qid in t["qids"]
    )

    token = None
    if new_qids_exist:
        # Step 2 – LMS Login (only when there's something new to fetch)
        print("  [2/4] Authenticating with Testbook LMS...")
        try:
            token = auto_login(LMS_EMAIL, LMS_PASSWORD)
            print("  Login successful.\n")
        except RuntimeError as e:
            print(f"\n  [ERROR] {e}")
            sys.exit(1)
    else:
        print("  [2/4] All QIDs already cached — skipping LMS login.\n")

    # Step 3 – Fetch & format questions
    print("  [3/4] Processing questions...\n")

    CSV_HEADERS = [
        "test_id", "Statement",
        "Option 1", "Option 2", "Option 3", "Option 4",
        "Correct Answer", "Positive", "Negative", "Time", "Solution", "Test_link",
    ]
    all_rows      = [CSV_HEADERS]
    total_fetched = 0
    newly_fetched = 0
    cache_hits    = 0

    for t in tests_input:
        test_name = t["test_name"]
        test_link = t["test_link"]
        qids      = t["qids"]
        lang      = t.get("lang", "en,hi")

        # Use per-row values from sheet, fall back to defaults
        positive = t["positive"] if t["positive"] is not None else DEFAULT_POSITIVE
        negative = t["negative"] if t["negative"] is not None else DEFAULT_NEGATIVE
        time_val = t["duration"] if t["duration"] is not None else len(qids) * DEFAULT_TIME_PER_Q

        # Determine which languages to combine
        langs = [l.strip() for l in lang.split(",") if l.strip()]
        lang_primary   = langs[0] if len(langs) > 0 else "en"
        lang_secondary = langs[1] if len(langs) > 1 else None

        pos_disp = f"{positive:g}" if t["positive"] is not None else f"{positive:g}*"
        neg_disp = f"{negative:g}" if t["negative"] is not None else f"{negative:g}*"
        dur_disp = f"{time_val}m"  if t["duration"] is not None else f"{time_val}m*"
        print(f"  > [{test_name}] - {len(qids)} QID(s)  +{pos_disp} -{neg_disp} {dur_disp}")
        print(f"    link: {test_link}")

        for qid in qids:
            qid = qid.strip()

            # ── Cache hit: reuse stored row ──────────────────────────
            if qid in cache:
                cached_row = list(cache[qid])
                cached_row[0] = test_name
                # Indices 7, 8, 9, 11 correspond to positive, negative, time_val, test_link in extract_multilang_row
                cached_row[7] = positive
                cached_row[8] = negative
                cached_row[9] = time_val
                cached_row[11] = test_link
                all_rows.append(cached_row)
                total_fetched += 1
                cache_hits    += 1
                print(f"    [cached] QID {qid}")
                continue

            # ── Cache miss: fetch from LMS ───────────────────────────
            q = fetch_question(qid, token)
            if q is None:
                print(f"    [SKIP] QID {qid} - no data returned.")
                continue

            row = extract_multilang_row(
                test_id        = test_name,
                q              = q,
                test_link      = test_link,
                positive       = positive,
                negative       = negative,
                time_val       = time_val,
                lang_primary   = lang_primary,
                lang_secondary = lang_secondary,
            )
            if row is None:
                print(f"    [SKIP] QID {qid} - could not extract data.")
                continue

            cache[qid] = row        # store in cache
            all_rows.append(row)
            total_fetched += 1
            newly_fetched += 1
            print(f"    [OK] QID {qid}")

        print()

    if total_fetched == 0:
        print("\n  [ERROR] No questions were processed successfully.")
        sys.exit(1)

    # Persist updated cache
    if newly_fetched > 0:
        save_cache(cache)
        print(f"  Cache updated: {newly_fetched} new QID(s) added  ({cache_hits} from cache).\n")
    else:
        print(f"  All {cache_hits} question(s) loaded from cache — no API calls made.\n")

    # Step 4 – Write CSV & update index.html
    print(f"  [4/4] Writing {total_fetched} question(s) to Questions.csv...")

    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerows(all_rows)
    csv_text = output.getvalue()

    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    print("  Saved  -> Questions.csv")

    tests, total_q = analyze_tests(csv_text)

    if os.path.exists(INDEX_PATH):
        update_index_html(csv_text, tests, total_q)
        print("  Updated -> index.html\n")
    else:
        print("  [WARNING] index.html not found. Only Questions.csv was saved.\n")

    n_tests = write_data_files(all_rows, tests)
    print(f"  Written -> data/ ({n_tests} test JSON file(s) + manifest.json)\n")

    # Write test links back to the Google Sheet (all filtered rows, not just current run)
    print("  Writing HTML links back to Google Sheet...")
    try:
        write_html_links_to_sheet(sheet_rows)
    except Exception as e:
        print(f"  [WARN] Could not update 'HTML Link' column in sheet: {e}")

    # Summary table
    print(f"  {'#':<4} {'Test Name':<35} {'Qs':<5} {'+':<6} {'-':<6} {'Time':<8}")
    print("  " + "-" * 70)
    for i, (name, info) in enumerate(tests.items(), 1):
        pos_s = f"{info['positive']:g}" if info['positive'] is not None else f"{DEFAULT_POSITIVE:g}*"
        neg_s = f"{info['negative']:g}" if info['negative'] is not None else f"{DEFAULT_NEGATIVE:g}*"
        t_s   = f"{info['time_min']}m" if info['time_min'] is not None else f"{info['count'] * DEFAULT_TIME_PER_Q}m*"
        print(f"  {i:<4} {name:<35} {info['count']:<5} {pos_s:<6} {neg_s:<6} {t_s:<8}")

    print("\n  (* = using defaults from run.py config)\n")

    # URLs
    print("  " + "=" * 60)
    print("  Ready-to-share test URLs:\n")
    for name, info in tests.items():
        url = f"{VERCEL_DOMAIN}?test={info['slug']}"
        print(f"  {name}")
        print(f"    {url}\n")

    print("  Done!")

    # ── Git push prompt ──────────────────────────────────────────────
    print()
    if os.getenv("CI") or os.getenv("GITHUB_ACTIONS"):
        print("  Running in CI environment — skipping interactive git push.")
        sys.exit(0)

    answer = input("  Push to GitHub now? [y/N]: ").strip().lower()
    if answer in ("y", "yes"):
        import subprocess, datetime

        today    = datetime.date.today().strftime("%d %b %Y")
        names    = ", ".join(tests.keys())
        msg      = f"sync: {names} ({today})"

        def run_git(*args):
            result = subprocess.run(
                ["git"] + list(args),
                cwd=SCRIPT_DIR,
                capture_output=True,
                text=True,
            )
            combined = (result.stdout + result.stderr).lower()
            if result.returncode != 0:
                # These are non-error informational states from git on Windows
                if any(s in combined for s in (
                    "everything up-to-date", "up to date", "nothing to commit"
                )):
                    return True
                out = (result.stderr or result.stdout).strip()
                print(f"  [git error] {out}")
                return False
            return True

        print()
        if not run_git("add", "Questions.csv", "index.html", "data/"):
            print("  ✗ git add failed.")
        else:
            committed = run_git("commit", "-m", msg)
            pushed    = run_git("push", "new-origin", "main")
            if pushed:
                if committed:
                    print(f"  ✓ Pushed to GitHub — commit: \"{msg}\"")
                else:
                    print(f"  ✓ Pushed to GitHub (no new changes to commit).")
                print(f"  ✓ Vercel will auto-deploy in ~30 seconds.")
            else:
                print("  ✗ Push failed. Run manually (PowerShell compatible):")
                print(f'    git add Questions.csv index.html data/; git commit -m "{msg}"; git push new-origin main')
    else:
        print("  Skipped. Run when ready (PowerShell compatible):")
        names = ", ".join(tests.keys())
        today = __import__("datetime").date.today().strftime("%d %b %Y")
        print(f'    git add Questions.csv index.html data/; git commit -m "sync: {names} ({today})"; git push new-origin main')


if __name__ == "__main__":
    main()
