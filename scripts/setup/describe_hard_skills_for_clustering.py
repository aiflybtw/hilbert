"""describe_hard_skills_for_clustering.py — LLM descriptions for each unique hard skill.

Reads unique skill names from DB, builds a prompt with skill name, frequency,
and co-occurring skills, calls LLM for domain + description, saves results.
Batch size: 10 skills per call. Supports checkpoint/resume.
"""
import json, os, sys, time
from collections import Counter, defaultdict

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config
from src.features.deepseek_client import call_deepseek
from src.features.prompts import LLM_HARD_SKILL_DESCRIBE_PROMPT

DB_DSN = config.db_dsn
OUTPUT_PATH = os.path.join(BASE, "..", "data", "hard_skills_descriptions_clustering.json")
BATCH_SIZE = 10
DELAY = 1.0


def get_skill_data(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT hard_skills_json FROM vacancies
        WHERE hard_skills_json IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()

    skill_vacancies = defaultdict(list)
    for (skills_json,) in rows:
        if not skills_json:
            continue
        if isinstance(skills_json, str):
            skills = json.loads(skills_json)
        else:
            skills = skills_json
        if not isinstance(skills, list):
            continue
        for s in skills:
            name = s.get('name', '') if isinstance(s, dict) else ''
            if name:
                skill_vacancies[name].append(True)

    skill_to_vid_count = {s: len(vids) for s, vids in skill_vacancies.items()}
    total_vacancies = len(rows)
    return skill_to_vid_count, total_vacancies


def get_co_occurring_skills(conn, target_skill):
    cur = conn.cursor()
    cur.execute("""
        SELECT hard_skills_json FROM vacancies
        WHERE hard_skills_json IS NOT NULL
    """)
    rows = cur.fetchall()
    cur.close()

    co_counts = Counter()
    for (skills_json,) in rows:
        if not skills_json:
            continue
        if isinstance(skills_json, str):
            skills = json.loads(skills_json)
        else:
            skills = skills_json
        if not isinstance(skills, list):
            continue
        names = []
        for s in skills:
            n = s.get('name', '') if isinstance(s, dict) else ''
            if n:
                names.append(n)
        if target_skill in names:
            for n in names:
                if n != target_skill:
                    co_counts[n] += 1
    return [s for s, _ in co_counts.most_common(10)]


def build_batch_prompt(batch):
    items = []
    for skill_name, freq, co_skills in batch:
        items.append({
            "name": skill_name,
            "frequency": freq,
            "co_occurring": co_skills[:10],
        })
    prompt = LLM_HARD_SKILL_DESCRIBE_PROMPT.format(
        input_json=json.dumps(items, ensure_ascii=False)
    )
    return prompt


def parse_batch_response(resp_text, batch_names):
    if not resp_text:
        return {}
    try:
        data = json.loads(resp_text)
    except json.JSONDecodeError:
        try:
            start = resp_text.index('{')
            end = resp_text.rindex('}') + 1
            data = json.loads(resp_text[start:end])
        except (ValueError, json.JSONDecodeError):
            print(f"  [describe] Failed to parse LLM response")
            return {}

    result = {}
    if isinstance(data, dict):
        for name in batch_names:
            entry = data.get(name)
            if isinstance(entry, dict) and 'domain' in entry and 'description' in entry:
                result[name] = entry
            elif isinstance(entry, str):
                result[name] = {"domain": "", "description": entry}
    elif isinstance(data, list):
        for item, name in zip(data, batch_names):
            if isinstance(item, dict) and 'domain' in item and 'description' in item:
                result[name] = item
    return result


def main():
    conn = psycopg2.connect(DB_DSN)

    print("[describe] Gathering skill data from DB...")
    skill_freqs, total_vacs = get_skill_data(conn)
    print(f"[describe] {len(skill_freqs)} unique skills from {total_vacs} vacancies")

    skills_sorted = sorted(skill_freqs.items(), key=lambda x: -x[1])

    if os.path.exists(OUTPUT_PATH):
        with open(OUTPUT_PATH, encoding='utf-8') as f:
            existing = json.load(f)
        print(f"[describe] Loaded checkpoint with {len(existing)} skills")
    else:
        existing = {}

    remaining = [(s, f) for s, f in skills_sorted if s not in existing]
    print(f"[describe] {len(remaining)} skills remaining to process")

    batches = [remaining[i:i + BATCH_SIZE] for i in range(0, len(remaining), BATCH_SIZE)]

    for bi, batch in enumerate(batches):
        print(f"[describe] Batch {bi + 1}/{len(batches)} ({len(batch)} skills)")

        batch_with_co = []
        for skill_name, freq in batch:
            co_skills = get_co_occurring_skills(conn, skill_name)
            batch_with_co.append((skill_name, freq, co_skills))

        prompt = build_batch_prompt(batch_with_co)
        resp = call_deepseek(prompt)
        parsed = parse_batch_response(resp, [s for s, _, _ in batch_with_co])

        for skill_name, freq, _ in batch_with_co:
            if skill_name in parsed:
                existing[skill_name] = parsed[skill_name]
            else:
                existing[skill_name] = {
                    "domain": "",
                    "description": f"Skill: {skill_name}. Frequency: {freq}."
                }

        with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)

        print(f"[describe] Saved checkpoint: {len(existing)} total")
        time.sleep(DELAY)

    conn.close()
    print(f"[describe] Done. {len(existing)} skills described.")


if __name__ == "__main__":
    main()
