"""llm_cluster_soft_skills.py — LLM clusters soft skills into 6 groups.

Reads normalized soft skill names, builds a prompt asking LLM to cluster ~120
skill names into 6 categories, saves mapping, and writes soft_clusters to DB.
"""
import json, os, sys, time

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config
from src.features.deepseek_client import call_deepseek

DB_DSN = config.db_dsn
NAMES_PATH = os.path.join(BASE, "..", "data", "soft_skills_names.json")
OUTPUT_PATH = os.path.join(BASE, "..", "data", "soft_skills_llm_clusters.json")

SOFT_CLUSTER_NAMES = {
    1: "Collaboration & Communication",
    2: "Analytical & Systems Thinking",
    3: "Adaptability & Learning",
    4: "Leadership & Initiative",
    5: "Self-organization & Responsibility",
    6: "Mentoring & Knowledge Sharing",
}

CLUSTER_PROMPT = """\
Ты — таксономист soft skills для DevOps/SRE специалистов.

У тебя есть список soft skills (софт скиллов). Распредели их по 6 категориям.
Верни строго JSON-объект вида: {{"skill_name": cluster_id, ...}}

Категории (cluster_id от 1 до 6):
1 - Collaboration & Communication (коллаборация, коммуникация, работа в команде, взаимодействие)
2 - Analytical & Systems Thinking (аналитическое мышление, системное мышление, решение проблем)
3 - Adaptability & Learning (адаптивность, обучаемость, самообразование)
4 - Leadership & Initiative (лидерство, инициативность, планирование, управление)
5 - Self-organization & Responsibility (самоорганизация, ответственность, тайм-менеджмент)
6 - Mentoring & Knowledge Sharing (наставничество, обучение, обмен знаниями)

ПРАВИЛА:
- Каждому навыку присвой ровно одну категорию
- Если навык подходит к нескольким — выбери наиболее подходящую
- Ответь ТОЛЬКО JSON-объектом, без пояснений и markdown

СПИСОК НАВЫКОВ:
{skills_list}
"""


def main():
    print("[llm_soft] Loading soft skill names...")
    with open(NAMES_PATH, encoding='utf-8') as f:
        names = json.load(f)
    print(f"[llm_soft] {len(names)} soft skill names")

    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding='utf-8') as f:
            existing = json.load(f)
        print(f"[llm_soft] Loaded existing mapping with {len(existing)} entries")
    else:
        existing = {}

    remaining = [n for n in names if n not in existing]
    if not remaining:
        print(f"[llm_soft] All skills already clustered")
    else:
        prompt = CLUSTER_PROMPT.format(skills_list=json.dumps(remaining, ensure_ascii=False))
        print(f"[llm_soft] Sending {len(remaining)} skills to LLM for clustering...")
        resp = call_deepseek(prompt)
        if resp:
            try:
                new_mapping = json.loads(resp)
                if isinstance(new_mapping, dict):
                    existing.update(new_mapping)
            except json.JSONDecodeError:
                try:
                    start = resp.index('{')
                    end = resp.rindex('}') + 1
                    new_mapping = json.loads(resp[start:end])
                    if isinstance(new_mapping, dict):
                        existing.update(new_mapping)
                except (ValueError, json.JSONDecodeError):
                    print(f"[llm_soft] Failed to parse LLM response")
        else:
            print(f"[llm_soft] LLM returned empty response")

        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        print(f"[llm_soft] Saved to {OUTPUT_PATH}")

    print(f"[llm_soft] Writing soft_clusters to DB...")
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    cur.execute("""
        SELECT vacancy_id, soft_skills_json
        FROM vacancies
        WHERE soft_skills_json IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[llm_soft] {len(rows)} vacancies to process")

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
        seen = set()
        for s in skills:
            name = s.get('name', '') if isinstance(s, dict) else (s if isinstance(s, str) else '')
            if not name:
                continue
            cid = existing.get(name)
            if cid is not None and cid not in seen:
                cluster_ids.append(cid)
                seen.add(cid)

        cur.execute(
            "UPDATE vacancies SET soft_clusters = %s WHERE vacancy_id = %s",
            (json.dumps(cluster_ids, ensure_ascii=False), vid),
        )
        updated += 1
        if updated % 200 == 0:
            conn.commit()
            print(f"[llm_soft] {updated}/{len(rows)}")

    conn.commit()
    cur.close()
    conn.close()
    print(f"[llm_soft] Done. {updated} vacancies updated with soft_clusters.")


if __name__ == "__main__":
    main()
