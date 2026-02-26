"""
run.py — Fetch a Google Sheet as CSV and inject it into the mock-test quiz.

Usage:
    python run.py

It will prompt for:
  1. Google Sheet link (public or "Anyone with the link" sharing)
  2. Quiz title — auto-detected from the sheet name (with option to override)
  3. Positive marks per correct answer
  4. Negative marks per wrong answer
  5. Total time for the exam (in minutes)
Then it downloads the CSV, saves it as Questions.csv, and updates index.html
(the <title>, inline csv-data, and quiz-data JSON with all dynamic values).
"""

import re
import os
import sys
import json
import csv
import io
import math
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
INDEX_PATH = os.path.join(SCRIPT_DIR, "index.html")
CSV_PATH = os.path.join(SCRIPT_DIR, "Questions.csv")


def extract_sheet_id(url: str) -> str:
    """Extract the spreadsheet ID from various Google Sheets URL formats."""
    # Pattern: /spreadsheets/d/SHEET_ID/...
    m = re.search(r'/spreadsheets/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    raise ValueError(
        "Could not extract a Google Sheet ID from the provided URL.\n"
        "Expected a link like: https://docs.google.com/spreadsheets/d/SHEET_ID/..."
    )


def extract_gid(url: str) -> str:
    """Extract the gid (sheet tab) from the URL, default '0'."""
    m = re.search(r'[#&?]gid=(\d+)', url)
    return m.group(1) if m else "0"


def build_csv_export_url(sheet_id: str, gid: str = "0") -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def fetch_sheet_name(sheet_id: str) -> str:
    """Fetch the spreadsheet title by loading the public HTML page and parsing <title>."""
    url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/edit"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            # Read just enough to get the <title>
            html = resp.read(50000).decode("utf-8", errors="replace")
            m = re.search(r'<title>(.+?)</title>', html, re.IGNORECASE)
            if m:
                title = m.group(1).strip()
                # Google Sheets titles look like "Sheet Name - Google Sheets"
                title = re.sub(r'\s*-\s*Google (Sheets|Spreadsheets)\s*$', '', title)
                if title:
                    return html_unescape(title)
    except Exception:
        pass
    return ""


def html_unescape(s: str) -> str:
    """Basic HTML entity unescaping."""
    s = s.replace('&amp;', '&')
    s = s.replace('&lt;', '<')
    s = s.replace('&gt;', '>')
    s = s.replace('&quot;', '"')
    s = s.replace('&#39;', "'")
    return s


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


def count_questions(csv_text: str) -> int:
    """Count data rows (excluding header) in the CSV."""
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    # Skip header, count non-empty rows
    count = 0
    for row in rows[1:]:
        if row and row[0].strip():
            count += 1
    return count


def update_index_html(csv_text: str, quiz_title: str, positive_marking: float,
                      negative_marking: float, total_time_minutes: int, question_count: int):
    """Replace the inline csv-data, quiz-data, and <title> in index.html."""
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        html = f.read()

    total_time_seconds = total_time_minutes * 60
    max_marks = question_count * positive_marking

    # --- Replace <title> tag ---
    title_pattern = re.compile(r'(<title>)(.*?)(</title>)', re.DOTALL)
    if title_pattern.search(html):
        html = title_pattern.sub(
            lambda m: m.group(1) + f"Testbook | {quiz_title}" + m.group(3),
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

        quiz_data["quizTitle"] = quiz_title
        quiz_data["questions"] = []
        quiz_data["totalTime"] = total_time_seconds
        quiz_data["positiveMarking"] = positive_marking
        quiz_data["negativeMarking"] = negative_marking

        # Update instruction strings
        instructions = quiz_data.get("instructionStrings", {})
        instructions["totalTime"] = f"Time: {total_time_minutes} minutes"
        instructions["totalMarks"] = f"Total Marks: {max_marks:g}"
        instructions["instruction1"] = f"The quiz contains {question_count} questions."
        instructions["instruction2"] = f"Each question has 4 options, and only 1 option is correct."
        instructions["instruction3"] = f"You will have {total_time_minutes} minutes to complete the quiz."
        pos_display = f"{positive_marking:g}"
        neg_display = f"{negative_marking:g}"
        if negative_marking > 0:
            instructions["instruction4"] = f"Negative marking applies: {neg_display} marks will be deducted for each incorrect answer."
        else:
            instructions["instruction4"] = "There is no negative marking."
        instructions["instruction5"] = f"{pos_display} mark(s) will be awarded for each correct answer."
        instructions["instruction6"] = "No marks will be deducted for unattempted questions."
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
    print("  Mock Test — Google Sheet Importer")
    print("=" * 60)
    print()

    # 1. Ask for Google Sheet link
    sheet_url = input("Enter Google Sheet link: ").strip()
    if not sheet_url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    # 2. Auto-fetch sheet name → use as quiz title
    try:
        sheet_id_for_name = extract_sheet_id(sheet_url)
        print("\nFetching sheet name...")
        auto_title = fetch_sheet_name(sheet_id_for_name)
    except Exception:
        auto_title = ""

    if auto_title:
        print(f"  Sheet name: {auto_title}")
        override = input(f"Use \"{auto_title}\" as quiz title? (Y/n): ").strip().lower()
        if override == 'n':
            quiz_title = input("Enter quiz title: ").strip() or auto_title
        else:
            quiz_title = auto_title
    else:
        print("  Could not auto-detect sheet name.")
        quiz_title = input("Enter quiz title: ").strip() or "Mock Test"

    # 3. Ask for positive marks per question
    pos_input = input("Positive marks per correct answer (press Enter for 1): ").strip()
    if pos_input:
        try:
            positive_marking = float(pos_input)
        except ValueError:
            print("Invalid number. Using default 1.")
            positive_marking = 1.0
    else:
        positive_marking = 1.0

    # 4. Ask for negative marks per wrong answer
    neg_input = input("Negative marks per wrong answer (press Enter for 0.33): ").strip()
    if neg_input:
        try:
            negative_marking = float(neg_input)
        except ValueError:
            print("Invalid number. Using default 0.33.")
            negative_marking = 1 / 3
    else:
        negative_marking = 1 / 3

    # 5. Ask for total time
    time_input = input("Total exam time in minutes (press Enter for auto = 2 min/question): ").strip()

    # Extract sheet info
    try:
        sheet_id = extract_sheet_id(sheet_url)
        gid = extract_gid(sheet_url)
    except ValueError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    export_url = build_csv_export_url(sheet_id, gid)
    print(f"\nFetching CSV from Google Sheets...")

    # Download
    try:
        csv_text = download_csv(export_url)
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        sys.exit(1)

    question_count = count_questions(csv_text)
    if question_count == 0:
        print("\n[ERROR] No questions found in the sheet. Check the format:")
        print("  Row 1: Header (Statement, Option 1, Option 2, Option 3, Option 4, Correct Answer)")
        print("  Row 2+: Questions")
        sys.exit(1)

    print(f"  Found {question_count} questions.")

    # Resolve total time
    if time_input:
        try:
            total_time_minutes = int(time_input)
        except ValueError:
            print("Invalid number. Using auto (2 min/question).")
            total_time_minutes = question_count * 2
    else:
        total_time_minutes = question_count * 2

    max_marks = question_count * positive_marking

    # Save Questions.csv
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(csv_text)
    print(f"  Saved → Questions.csv")

    # Update index.html
    if os.path.exists(INDEX_PATH):
        update_index_html(csv_text, quiz_title, positive_marking, negative_marking,
                          total_time_minutes, question_count)
        print(f"  Updated → index.html (inline CSV + quiz config)")
    else:
        print(f"  [WARNING] index.html not found. Only Questions.csv was saved.")

    print(f"\nDone! Quiz is ready with {question_count} questions.")
    print(f"  Title:    {quiz_title}")
    print(f"  Time:     {total_time_minutes} minutes")
    print(f"  +Marks:   {positive_marking:g} per correct")
    print(f"  -Marks:   {negative_marking:g} per wrong")
    print(f"  Max Marks: {max_marks:g}")
    print()


if __name__ == "__main__":
    main()
