"""populate_title_parser.py — Seed data for heuristic seniority classification."""
import json, os, re, sys

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
DATA = os.path.join(BASE, "..", "data")

SENIORITY_KEYWORDS = {
    "senior": [
        "Senior", "Lead", "Team Lead", "Head", "Architect", "Principal",
        "Старший", "Ведущий", "Руководитель", "Архитектор",
    ],
    "middle": [
        "Middle", "Middle+", "Strong Middle",
    ],
    "junior": [
        "Junior", "Trainee", "Intern", "Internship",
        "Младший", "Стажер",
    ],
}


def classify_title(title):
    if not title:
        return None
    t_lower = title.lower()
    for grade, keywords in [("junior", SENIORITY_KEYWORDS["junior"]),
                            ("senior", SENIORITY_KEYWORDS["senior"]),
                            ("middle", SENIORITY_KEYWORDS["middle"])]:
        for kw in keywords:
            if kw.lower() in t_lower:
                return grade
    return None


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    print("[title_parser] Loading titles from DB...")
    cur.execute("SELECT vacancy_id, title FROM vacancies WHERE title IS NOT NULL")
    rows = cur.fetchall()
    print(f"[title_parser] {len(rows)} titles loaded")

    counts = {"senior": 0, "middle": 0, "junior": 0, "unknown": 0}

    for vid, title in rows:
        grade = classify_title(title)
        if grade:
            counts[grade] += 1
        else:
            counts["unknown"] += 1

    print(f"[title_parser] Classification results:")
    for grade in ["senior", "middle", "junior", "unknown"]:
        print(f"  {grade}: {counts[grade]}")

    # Save keywords to JSON
    path = os.path.join(DATA, "seniority_keywords.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(SENIORITY_KEYWORDS, f, ensure_ascii=False, indent=2)
    print(f"[title_parser] Keywords saved: {path}")

    cur.close()
    conn.close()
    print("[title_parser] Done.")


if __name__ == "__main__":
    main()
