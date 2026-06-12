"""finalize_clusters.py — Final 24-cluster taxonomy for salary model.

Reads consolidated clusters, maps skills to clusters, assigns human-readable
names, saves clusters_final_model.json and skill_to_cluster_final_model.json.
Also writes hard skill cluster IDs to the vacancies table (hard_clusters column).
"""
import json, os, sys
from collections import defaultdict

import psycopg2

BASE = os.path.dirname(__file__)
CLUSTER = os.path.join(BASE, "..", "data", "clustering")

INPUT_PATH = os.path.join(CLUSTER, "clusters_consolidated.json")
EXISTING_CLUSTERS = os.path.join(CLUSTER, "clusters_final_model.json")
EXISTING_MAPPING = os.path.join(CLUSTER, "skill_to_cluster_final_model.json")
OUTPUT_CLUSTERS = os.path.join(CLUSTER, "clusters_final_model.json")
OUTPUT_MAPPING = os.path.join(CLUSTER, "skill_to_cluster_final_model.json")

DEFAULT_CLUSTER_NAMES = [
    "Networking, Protocols & Traffic",
    "Security & DevSecOps",
    "ML & AI Infrastructure",
    "Observability & Monitoring",
    "Containers & Orchestration",
    "Big Data & Data Engineering",
    "CI/CD & GitOps",
    "Build & Package Management",
    "Cloud Platforms",
    "Virtualization & Hypervisors",
    "IaC & Config Management",
    "Relational Databases",
    "Messaging & API Gateway",
    "Web Servers",
    "Backup & Recovery",
    "Linux & OS Administration",
    "Scripting & Automation",
    "Storage & Filesystems",
    "NoSQL & Time-Series DB",
    "VoIP & Telephony",
    "Email & Collaboration",
    "Load Balancing & Service Mesh",
    "Backend Languages",
    "Web & Frontend",
]


def load_consolidated():
    with open(INPUT_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_existing_mapping():
    if os.path.exists(EXISTING_MAPPING):
        with open(EXISTING_MAPPING, encoding='utf-8') as f:
            return json.load(f)
    return None


def main():
    sys.path.insert(0, os.path.join(BASE, ".."))
    from src.config import config

    print("[finalize] Loading consolidated clusters...")
    consolidated = load_consolidated()
    print(f"[finalize] {len(consolidated)} consolidated clusters")

    existing_mapping = load_existing_mapping()
    if existing_mapping:
        print(f"[finalize] Found existing mapping with {len(existing_mapping)} skills")

    cluster_skills = {}
    for cid, info in consolidated.items():
        skills = info['skills'] if isinstance(info, dict) else info
        cluster_skills[cid] = list(dict.fromkeys(skills))

    sorted_clusters = sorted(cluster_skills.items(), key=lambda x: -len(x[1]))
    n = min(len(sorted_clusters), len(DEFAULT_CLUSTER_NAMES))

    cluster_info = {}
    skill_to_cluster = {}
    for i, (cid, skills) in enumerate(sorted_clusters[:n]):
        name = DEFAULT_CLUSTER_NAMES[i] if i < len(DEFAULT_CLUSTER_NAMES) else f"Cluster {cid}"
        cluster_info[cid] = {
            "name": name,
            "size": len(skills),
            "skills": skills,
        }
        for s in skills:
            skill_to_cluster[s] = cid

    if len(sorted_clusters) > n:
        remaining = []
        for cid, skills in sorted_clusters[n:]:
            for s in skills:
                skill_to_cluster[s] = cid
            remaining.extend(skills)
        if remaining:
            cluster_info[cid] = {
                "name": "Other",
                "size": len(remaining),
                "skills": remaining,
            }

    if existing_mapping:
        for skill_name, cid in existing_mapping.items():
            if skill_name not in skill_to_cluster:
                skill_to_cluster[skill_name] = cid

    final = {
        "n_clusters": len(cluster_info),
        "note": f"Restructured: {len(cluster_info)} clusters",
        "cluster_info": cluster_info,
    }

    with open(OUTPUT_CLUSTERS, 'w', encoding='utf-8') as f:
        json.dump(final, f, ensure_ascii=False, indent=2)
    print(f"[finalize] Saved: {OUTPUT_CLUSTERS}")

    with open(OUTPUT_MAPPING, 'w', encoding='utf-8') as f:
        json.dump(skill_to_cluster, f, ensure_ascii=False, indent=2)
    print(f"[finalize] Saved: {OUTPUT_MAPPING}")

    print(f"[finalize] Writing hard_clusters to vacancies table...")
    DB_DSN = config.db_dsn
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    cur.execute("""
        SELECT vacancy_id, hard_skills_json FROM vacancies
        WHERE hard_skills_json IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[finalize] {len(rows)} vacancies to process")

    updated = 0
    for vid, skills_json in rows:
        if not skills_json:
            continue
        if isinstance(skills_json, str):
            skills = json.loads(skills_json)
        else:
            skills = skills_json
        if not isinstance(skills, list):
            continue

        cluster_ids = []
        seen_clusters = set()
        for s in skills:
            name = s.get('name', '') if isinstance(s, dict) else ''
            if not name:
                continue
            cid = skill_to_cluster.get(name)
            if cid and cid not in seen_clusters:
                cluster_ids.append(cid)
                seen_clusters.add(cid)

        cur.execute(
            "UPDATE vacancies SET hard_clusters = %s WHERE vacancy_id = %s",
            (json.dumps(cluster_ids, ensure_ascii=False), vid),
        )
        updated += 1
        if updated % 200 == 0:
            conn.commit()
            print(f"[finalize] {updated}/{len(rows)}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[finalize] {updated} vacancies updated with hard_clusters")
    print(f"[finalize] Done.")


if __name__ == "__main__":
    main()
