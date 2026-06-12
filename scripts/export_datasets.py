"""export_datasets.py — Export CSV subsets from DB to data/ folder."""
import csv, json, os, sys
from collections import defaultdict

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
DATA = os.path.join(BASE, "..", "data")


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    # ── Export salary dataset (all with salary) ──
    print("[export] Loading vacancies with salary...")
    cur.execute("""
        SELECT vacancy_id, title, seniority_grade, salary_from_rub, salary_to_rub,
               hard_skills_json, soft_skills_json, responsibilities_json,
               soft_clusters, hard_clusters
        FROM vacancies
        WHERE salary_from_rub IS NOT NULL
        ORDER BY vacancy_id
    """)
    rows = cur.fetchall()
    print(f"[export] {len(rows)} vacancies with salary data")

    columns = [
        "vacancy_id", "title", "seniority_grade",
        "salary_from_rub", "salary_to_rub",
        "hard_skills_json", "soft_skills_json", "responsibilities_json",
        "soft_clusters", "hard_clusters",
    ]

    path_full = os.path.join(DATA, "salary_dataset.csv")
    with open(path_full, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            row = list(r)
            # Serialize JSONB columns as JSON strings
            for i in [5, 6, 7, 8, 9]:
                if row[i] is not None:
                    if isinstance(row[i], (list, dict)):
                        row[i] = json.dumps(row[i], ensure_ascii=False)
                    elif not isinstance(row[i], str):
                        row[i] = str(row[i])
                else:
                    row[i] = ""
            w.writerow(row)
    print(f"[export] Saved: {path_full}")

    # ── Export filtered dataset (salary + seniority) ──
    print("[export] Filtering vacancies with seniority grade...")
    filtered = [r for r in rows if r[2] is not None]
    print(f"[export] {len(filtered)} vacancies with salary + seniority")

    path_filtered = os.path.join(DATA, "salary_dataset_filtered.csv")
    with open(path_filtered, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in filtered:
            row = list(r)
            for i in [5, 6, 7, 8, 9]:
                if row[i] is not None:
                    if isinstance(row[i], (list, dict)):
                        row[i] = json.dumps(row[i], ensure_ascii=False)
                    elif not isinstance(row[i], str):
                        row[i] = str(row[i])
                else:
                    row[i] = ""
            w.writerow(row)
    print(f"[export] Saved: {path_filtered}")

    # ── Export skill presence matrix ──
    print("[export] Building skill presence matrix...")

    # Collect all unique hard skill names
    skill_names = set()
    vacancy_skills = {}
    for r in rows:
        vid = r[0]
        hs = r[5]
        if hs is None:
            vacancy_skills[vid] = set()
            continue
        if isinstance(hs, str):
            hs = json.loads(hs)
        names = set()
        for s in hs:
            name = s.get("name", "") if isinstance(s, dict) else ""
            if name:
                name = name.strip()
                if name:
                    names.add(name)
                    skill_names.add(name)
        vacancy_skills[vid] = names

    skill_names = sorted(skill_names)
    print(f"[export] {len(skill_names)} unique hard skills, {len(vacancy_skills)} vacancies")

    path_matrix = os.path.join(DATA, "skill_matrix.csv")
    with open(path_matrix, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["vacancy_id"] + skill_names)
        for r in rows:
            vid = r[0]
            names = vacancy_skills.get(vid, set())
            row = [vid] + [1 if s in names else 0 for s in skill_names]
            w.writerow(row)
    print(f"[export] Saved: {path_matrix}")

    cur.close()
    conn.close()
    print("[export] Done.")


if __name__ == "__main__":
    main()
