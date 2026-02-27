"""
run.py — Sync master Google Sheet and update the mock-test app.

The master sheet ID is hardcoded. Just run `python run.py` — no prompts.
It downloads the CSV, discovers all tests (by test_id in Column A),
reads per-test config from columns H/I/J of the first row of each test,
updates Questions.csv + index.html, and prints ready-to-share URLs.

Master Sheet Columns:
  A: test_id  |  B: Statement  |  C-F: Options 1-4  |  G: Correct Answer
  H: Positive marks (first row only)  |  I: Negative marks  |  J: Time in minutes
"""

import re
import os
import sys
import json
import csv
import io
import subprocess
import urllib.request
import urllib.error

# ── CONFIG (edit these) ─────────────────────────────────────────────
MASTER_SHEET_ID = "1Jij5oLCynk5tsOYQdd-QSIYqNKE0vNMVJcEsGt817VY"
MASTER_SHEET_GID = "0"
VERCEL_DOMAIN = "https://mock-test-kappa.vercel.app"

# Defaults (used when columns H/I/J are empty)
DEFAULT_POSITIVE = 2.0
DEFAULT_NEGATIVE = 0.5
DEFAULT_TIME_PER_Q = 2  # minutes per question
# ────────────────────────────────────────────────────────────────────

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(SCRIPT_DIR, "index.html")
CSV_PATH = os.path.join(SCRIPT_DIR, "Questions.csv")


def build_csv_export_url(sheet_id: str, gid: str = "0") -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def download_csv(url: str) -> str:
    """Download CSV text from a URL."""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
            return data.decode("utf-8-sig")  # handle BOM
    except urllib.error.HTTPError as e:
        if e.code == 403:
            raise RuntimeError(
                "Access denied (HTTP 403). Make sure the Google Sheet sharing is set to "
                "\"Anyone with the link\" can view."
            )
        raise RuntimeError(f"HTTP error {e.code} when fetching the sheet.")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def slugify(text: str) -> str:
    """Create a URL-friendly slug from a string."""
    s = text.strip().lower()
    s = re.sub(r'[_\s]+', '-', s)       # underscores/spaces -> hyphens first
    s = re.sub(r'[^a-z0-9-]', '', s)    # then strip everything else
    s = re.sub(r'-+', '-', s)
    return s.strip('-')


def analyze_tests(csv_text: str) -> dict:
    """Parse CSV and return dict of test_id -> {slug, count, positive, negative, time_min}.

    Config is read from columns H/I/J of the FIRST row of each test_id.
    """
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    tests = {}
    total_q = 0

    for row in rows[1:]:
        if not row or not row[0].strip():
            continue
        # Need at least 7 cols: test_id, statement, 4 options, answer
        if len(row) < 7 or not row[1].strip():
            continue

        test_id = row[0].strip()
        total_q += 1

        if test_id not in tests:
            # Read config from columns H(7), I(8), J(9) of first occurrence
            positive = negative = time_min = None
            if len(row) > 7 and row[7].strip():
                try: positive = float(row[7].strip())
                except ValueError: pass
            if len(row) > 8 and row[8].strip():
                try: negative = float(row[8].strip())
                except ValueError: pass
            if len(row) > 9 and row[9].strip():
                try: time_min = int(float(row[9].strip()))
                except ValueError: pass

            tests[test_id] = {
                'slug': slugify(test_id),
                'count': 0,
                'positive': positive,
                'negative': negative,
                'time_min': time_min,
            }

        tests[test_id]['count'] += 1

    return tests, total_q


def update_index_html(csv_text: str, tests: dict, total_q: int):
    """Replace the inline csv-data, quiz-data, and <title> in index.html."""
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    page_title = "Mock Tests"
    if len(tests) == 1:
        page_title = list(tests.keys())[0]

    # --- Replace <title> tag ---
    title_pattern = re.compile(r'(<title>)(.*?)(</title>)', re.DOTALL)
    if title_pattern.search(html):
        html = title_pattern.sub(
            lambda m: m.group(1) + f"Testbook | {page_title}" + m.group(3),
            html
        )

    # --- Replace inline CSV ---
    # Pattern: <script id="csv-data" type="text/csv"> ... </script>
    csv_pattern = re.compile(
        r'(<script\s+id="csv-data"\s+type="text/csv">)(.*?)(</script>)',
        re.DOTALL
    )
    if not csv_pattern.search(html):
        print("[WARNING] Could not find <script id=\"csv-data\"> in index.html. Skipping inline CSV update.")
    else:
        html = csv_pattern.sub(
            lambda m: m.group(1) + "\n" + csv_text.strip() + "\n    " + m.group(3),
            html
        )

    # --- Replace quiz-data JSON ---
    json_pattern = re.compile(
        r'(<script\s+id="quiz-data"\s+type="application/json">)(.*?)(</script>)',
        re.DOTALL
    )
    json_match = json_pattern.search(html)
    if not json_match:
        print("[WARNING] Could not find <script id=\"quiz-data\"> in index.html. Skipping config update.")
    else:
        try:
            quiz_data = json.loads(json_match.group(2))
        except json.JSONDecodeError:
            print("[WARNING] Could not parse existing quiz-data JSON. Rebuilding from scratch.")
            quiz_data = {}

        quiz_data["quizTitle"] = page_title
        quiz_data["questions"] = []
        quiz_data["totalTime"] = 0  # Computed per-test at runtime from CSV cols
        quiz_data["positiveMarking"] = DEFAULT_POSITIVE
        quiz_data["negativeMarking"] = DEFAULT_NEGATIVE
        quiz_data["timePerQuestion"] = DEFAULT_TIME_PER_Q

        # Default instruction strings (overridden per-test in JS)
        instructions = quiz_data.get("instructionStrings", {})
        instructions["totalTime"] = "Time: -- minutes"
        instructions["totalMarks"] = "Total Marks: --"
        instructions["instruction1"] = f"The quiz contains {total_q} questions total."
        instructions["instruction2"] = "Each question has 4 options, and only 1 option is correct."
        instructions["instruction3"] = "Time will be computed based on test selected."
        pos_display = f"{DEFAULT_POSITIVE:g}"
        neg_display = f"{DEFAULT_NEGATIVE:g}"
        if DEFAULT_NEGATIVE > 0:
            instructions["instruction4"] = f"Negative marking applies: {neg_display} marks will be deducted for each incorrect answer."
        else:
            instructions["instruction4"] = "There is no negative marking."
        instructions["instruction5"] = f"{pos_display} mark(s) will be awarded for each correct answer."
        quiz_data["instructionStrings"] = instructions

        new_json = json.dumps(quiz_data, indent=4, ensure_ascii=False)
        html = json_pattern.sub(
            lambda m: m.group(1) + "\n" + new_json + "\n    " + m.group(3),
            html
        )

    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        f.write(html)


def main():
    print("=" * 60)
    print("  Mock Test — Master Sheet Sync")
    print("=" * 60)
    print()

    export_url = build_csv_export_url(MASTER_SHEET_ID, MASTER_SHEET_GID)
    print("  Fetching CSV from master sheet...")

    # Download
    try:
        csv_text = download_csv(export_url)
    except RuntimeError as e:
        print(f"\n  [ERROR] {e}")
        sys.exit(1)

    # Analyze
    tests, total_q = analyze_tests(csv_text)

    if total_q == 0:
        print("\n  [ERROR] No questions found. Check the sheet format:")
        print("    Row 1: Header")
        print("    Row 2+: test_id | Statement | Opt1 | Opt2 | Opt3 | Opt4 | Answer | +Marks | -Marks | Time(min)")
        sys.exit(1)

    print(f"  Found {total_q} questions across {len(tests)} test(s).\n")

    # Save Questions.csv
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    print("  Saved  -> Questions.csv")

    # Update index.html
    if os.path.exists(INDEX_PATH):
        update_index_html(csv_text, tests, total_q)
        print("  Updated -> index.html\n")
    else:
        print("  [WARNING] index.html not found. Only Questions.csv was saved.\n")

    # Print test summary table
    print(f"  {'#':<4} {'Test Name':<35} {'Qs':<5} {'+':<6} {'-':<6} {'Time':<8}")
    print("  " + "-" * 70)
    for i, (name, info) in enumerate(tests.items(), 1):
        pos_str = f"{info['positive']:g}" if info['positive'] is not None else f"{DEFAULT_POSITIVE:g}*"
        neg_str = f"{info['negative']:g}" if info['negative'] is not None else f"{DEFAULT_NEGATIVE:g}*"
        if info['time_min'] is not None:
            t_str = f"{info['time_min']}m"
        else:
            t_str = f"{info['count'] * DEFAULT_TIME_PER_Q}m*"
        print(f"  {i:<4} {name:<35} {info['count']:<5} {pos_str:<6} {neg_str:<6} {t_str:<8}")

    print("\n  (* = using defaults from run.py config)\n")

    # Print URLs
    print("  " + "=" * 60)
    print("  LINKS")
    print("  " + "=" * 60)
    print(f"\n  Test Picker: {VERCEL_DOMAIN}/\n")
    for name, info in tests.items():
        url = f"{VERCEL_DOMAIN}/?test={info['slug']}"
        print(f"  {name}")
        print(f"  -> {url}\n")

    # Auto git push
    print("  " + "-" * 60)
    choice = input("  Git push now? (y/n): ").strip().lower()
    if choice == 'y':
        try:
            subprocess.run(["git", "add", "-A"], check=True, cwd=SCRIPT_DIR)
            subprocess.run(["git", "commit", "-m", "sync: update tests from master sheet"],
                           check=True, cwd=SCRIPT_DIR)
            subprocess.run(["git", "push"], check=True, cwd=SCRIPT_DIR)
            print("\n  Pushed! Vercel will deploy automatically.")
        except subprocess.CalledProcessError as e:
            print(f"\n  Git failed: {e}")
            print("  You may need to push manually.")
    print()


if __name__ == "__main__":
    main()
