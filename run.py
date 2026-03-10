"""
run.py — Fetch questions from Testbook LMS and update the mock-test app.

Google Sheet columns:
  A: Test Name
  B: QID (comma separated)
  C: Lang  (e.g. "en,hi")
  D: Positive Marks  (optional — uses default if blank)
  E: Negative Marks  (optional — uses default if blank)
  F: Test Duration   (minutes, optional — computed from question count if blank)
  G: Test link       (auto-generated from Test Name slug — not read from sheet)

Create a .env file in the same directory with:
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
    print("[ERROR] 'requests' not installed. Run: python -m pip install requests python-dotenv")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("[ERROR] 'python-dotenv' not installed. Run: python -m pip install requests python-dotenv")
    sys.exit(1)

# ── Load .env ────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(SCRIPT_DIR, ".env"))

LMS_EMAIL    = os.getenv("LMS_EMAIL", "")
LMS_PASSWORD = os.getenv("LMS_PASSWORD", "")

# ── CONFIG ───────────────────────────────────────────────────────────
# New sheet: Col A = Test Name, Col B = comma-separated QIDs, Col D = test_link
QID_SHEET_ID  = "1yZAwshv5r5m-sK1JRyGXb0xWlMKcS219rzU7qWpPPN8"
QID_SHEET_GID = "0"

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

# Language keys are now read per-row from the sheet (Col C)

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

def build_csv_export_url(sheet_id: str, gid: str = "0") -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def download_csv(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError(
                "Access denied (HTTP 403). Make sure the Google Sheet sharing is "
                '"Anyone with the link" → view.'
            )
        raise RuntimeError(f"HTTP error {e.code} when fetching the sheet.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def slugify(text: str) -> str:
    s = text.strip().lower()
    s = re.sub(r'[_\s]+', '-', s)
    s = re.sub(r'[^a-z0-9-]', '', s)
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


# ── LMS AUTH ─────────────────────────────────────────────────────────

def auto_login(email: str, password: str) -> str:
    """POST to LMS login and return the Bearer token."""
    payload = {"email": email, "password": password, "otp": ""}
    try:
        resp = requests.post(LMS_LOGIN_URL, json=payload, timeout=30)
        resp.raise_for_status()
        data = resp.json().get("data", {})
        token = data.get("token", "")
        if not token:
            raise RuntimeError("Login succeeded but no token returned. Check credentials.")
        return token
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
    statement = stmt_p + ("\n" + stmt_s if stmt_s else "")

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
        test_link,
    ]


# ── PARSE QID SHEET ──────────────────────────────────────────────────

def parse_qid_sheet(csv_text: str) -> list[dict]:
    """
    Parse the QID sheet.
    Columns: A=Test Name, B=QIDs, C=Lang, D=Positive Marks, E=Negative Marks, F=Test Duration
    Test link is auto-generated from the Test Name slug — not read from sheet.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows   = list(reader)
    result = []

    def _float(val):
        try:    return float(val.strip())
        except: return None

    def _int(val):
        try:    return int(float(val.strip()))
        except: return None

    for row in rows[1:]:          # skip header
        if not row or not row[0].strip():
            continue
        test_name = row[0].strip()
        qids_raw  = row[1].strip() if len(row) > 1 else ""
        lang      = row[2].strip() if len(row) > 2 else "en,hi"
        positive  = _float(row[3]) if len(row) > 3 else None
        negative  = _float(row[4]) if len(row) > 4 else None
        duration  = _int(row[5])   if len(row) > 5 else None   # total minutes

        qids = [q.strip() for q in qids_raw.split(",") if q.strip()]
        if not qids:
            continue

        # Auto-generate test link from slug
        test_link = f"{VERCEL_DOMAIN}?test={slugify(test_name)}"

        result.append({
            "test_name": test_name,
            "qids":      qids,
            "lang":      lang,
            "positive":  positive,  # None = use default
            "negative":  negative,  # None = use default
            "duration":  duration,  # None = count * DEFAULT_TIME_PER_Q
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


# ── UPDATE index.html ────────────────────────────────────────────────

def update_index_html(csv_text: str, tests: dict, total_q: int):
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    page_title = list(tests.keys())[0] if len(tests) == 1 else "Mock Tests"

    # title tag
    tp = re.compile(r'(<title>)(.*?)(</title>)', re.DOTALL)
    if tp.search(html):
        html = tp.sub(lambda m: m.group(1) + f"Testbook | {page_title}" + m.group(3), html)

    # inline CSV
    csv_pat = re.compile(r'(<script\s+id="csv-data"\s+type="text/csv">)(.*?)(</script>)', re.DOTALL)
    if csv_pat.search(html):
        html = csv_pat.sub(
            lambda m: m.group(1) + "\n" + csv_text.strip() + "\n    " + m.group(3), html
        )
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

    # Step 1 – Download QID sheet
    print("  [1/4] Downloading QID sheet...")
    try:
        qid_csv = download_csv(build_csv_export_url(QID_SHEET_ID, QID_SHEET_GID))
    except RuntimeError as e:
        print(f"\n  [ERROR] {e}")
        sys.exit(1)

    tests_input = parse_qid_sheet(qid_csv)
    if not tests_input:
        print("\n  [ERROR] No rows found in the QID sheet. Check its format.")
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
        "Correct Answer", "Positive", "Negative", "Time", "Test_link",
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
        print(f"  ▸ [{test_name}] — {len(qids)} QID(s)  +{pos_disp} -{neg_disp} {dur_disp}")
        print(f"    link: {test_link}")

        for qid in qids:
            qid = qid.strip()

            # ── Cache hit: reuse stored row ──────────────────────────
            if qid in cache:
                all_rows.append(cache[qid])
                total_fetched += 1
                cache_hits    += 1
                print(f"    ↩ QID {qid}  (cached)")
                continue

            # ── Cache miss: fetch from LMS ───────────────────────────
            q = fetch_question(qid, token)
            if q is None:
                print(f"    ✗ QID {qid} — no data returned, skipping.")
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
                print(f"    ✗ QID {qid} — could not extract question data, skipping.")
                continue

            cache[qid] = row        # store in cache
            all_rows.append(row)
            total_fetched += 1
            newly_fetched += 1
            print(f"    ✓ QID {qid}  (fetched)")

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


if __name__ == "__main__":
    main()
