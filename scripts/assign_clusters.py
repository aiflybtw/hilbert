"""assign_clusters.py — Map hard/soft skills to existing cluster taxonomies.

Reads skill_to_cluster_final_model.json (24 hard clusters) and
soft_skills_llm_clusters.json (6 soft clusters), then writes
hard_clusters and soft_clusters columns for all vacancies.

Incremental by default: only processes rows with NULL target columns.
Use --force to re-process all.

Usage:
  python scripts/assign_clusters.py
  python scripts/assign_clusters.py --force
  python scripts/assign_clusters.py --hard-only
  python scripts/assign_clusters.py --soft-only
"""
import argparse, json, os, sys
from collections import defaultdict

import psycopg2

BASE = os.path.dirname(__file__)
DATA = os.path.join(BASE, "..", "data")
CLUSTER = os.path.join(DATA, "clustering")

HARD_MAPPING_PATH = os.path.join(CLUSTER, "skill_to_cluster_final_model.json")
SOFT_MAPPING_PATH = os.path.join(DATA, "soft_skills_llm_clusters.json")


def load_hard_mapping():
    with open(HARD_MAPPING_PATH, encoding="utf-8") as f:
        return json.load(f)


def load_soft_mapping():
    with open(SOFT_MAPPING_PATH, encoding="utf-8") as f:
        return json.load(f)


def assign_hard_clusters(conn, force=False):
    cur = conn.cursor()
    mapping = load_hard_mapping()
    print(f"[assign] Loaded hard cluster mapping: {len(mapping)} skills")

    if force:
        cur.execute("SELECT vacancy_id, hard_skills_json FROM vacancies WHERE hard_skills_json IS NOT NULL")
    else:
        cur.execute("SELECT vacancy_id, hard_skills_json FROM vacancies WHERE hard_skills_json IS NOT NULL AND hard_clusters IS NULL")
    rows = cur.fetchall()
    print(f"[assign] Hard clusters: {len(rows)} vacancies to process")

    unmapped = defaultdict(int)
    updated = 0
    for vid, skills_json in rows:
        if not skills_json:
            continue
        skills = skills_json if isinstance(skills_json, list) else json.loads(skills_json)
        cluster_ids = []
        seen = set()
        for s in skills:
            name = s.get("name", "") if isinstance(s, dict) else ""
            if not name:
                continue
            cid = mapping.get(name)
            if cid and cid not in seen:
                cluster_ids.append(cid)
                seen.add(cid)
            elif not cid:
                unmapped[name] += 1

        cur.execute(
            "UPDATE vacancies SET hard_clusters = %s WHERE vacancy_id = %s",
            (json.dumps(cluster_ids, ensure_ascii=False), vid),
        )
        updated += 1
        if updated % 200 == 0:
            conn.commit()
            print(f"[assign] hard: {updated}/{len(rows)}")

    conn.commit()
    cur.close()
    print(f"[assign] Hard clusters updated: {updated}")
    if unmapped:
        print(f"[assign] Unmapped hard skills ({len(unmapped)} unique):")
        for name, cnt in sorted(unmapped.items(), key=lambda x: -x[1])[:10]:
            print(f"         {name}: {cnt} occurrences")


def assign_soft_clusters(conn, force=False):
    cur = conn.cursor()
    mapping = load_soft_mapping()
    print(f"[assign] Loaded soft cluster mapping: {len(mapping)} skills")

    if force:
        cur.execute("SELECT vacancy_id, soft_skills_json FROM vacancies WHERE soft_skills_json IS NOT NULL")
    else:
        cur.execute("SELECT vacancy_id, soft_skills_json FROM vacancies WHERE soft_skills_json IS NOT NULL AND soft_clusters IS NULL")
    rows = cur.fetchall()
    print(f"[assign] Soft clusters: {len(rows)} vacancies to process")

    unmapped = defaultdict(int)
    updated = 0
    for vid, skills_json in rows:
        if not skills_json:
            continue
        skills = skills_json if isinstance(skills_json, list) else json.loads(skills_json)
        cluster_ids = []
        seen = set()
        for s in skills:
            name = s.get("name", "") if isinstance(s, dict) else (s if isinstance(s, str) else "")
            if not name:
                continue
            cid = mapping.get(name)
            if cid is not None and cid not in seen:
                cluster_ids.append(cid)
                seen.add(cid)
            elif cid is None:
                unmapped[name] += 1

        cur.execute(
            "UPDATE vacancies SET soft_clusters = %s WHERE vacancy_id = %s",
            (json.dumps(cluster_ids, ensure_ascii=False), vid),
        )
        updated += 1
        if updated % 200 == 0:
            conn.commit()
            print(f"[assign] soft: {updated}/{len(rows)}")

    conn.commit()
    cur.close()
    print(f"[assign] Soft clusters updated: {updated}")
    if unmapped:
        print(f"[assign] Unmapped soft skills ({len(unmapped)} unique):")
        for name, cnt in sorted(unmapped.items(), key=lambda x: -x[1])[:10]:
            print(f"         {name}: {cnt} occurrences")


def main():
    sys.path.insert(0, os.path.join(BASE, ".."))
    from src.config import config

    parser = argparse.ArgumentParser(description="Assign skills to existing clusters")
    parser.add_argument("--force", action="store_true", help="Re-process all, not just NULL columns")
    parser.add_argument("--hard-only", action="store_true")
    parser.add_argument("--soft-only", action="store_true")
    args = parser.parse_args()

    conn = psycopg2.connect(config.db_dsn)

    if not args.soft_only:
        assign_hard_clusters(conn, force=args.force)
    if not args.hard_only:
        assign_soft_clusters(conn, force=args.force)

    conn.close()
    print("[assign] Done.")


if __name__ == "__main__":
    main()
