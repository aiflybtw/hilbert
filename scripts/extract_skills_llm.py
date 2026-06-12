"""extract_skills_llm.py — LLM extraction of hard/soft skills, responsibilities, seniority from descriptions."""
import json, os, sys, time, re
import psycopg2
from psycopg2.extras import RealDictCursor

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config
from src.features.deepseek_client import call_deepseek
from src.features.prompts import LLM_SKILLS_EXTRACTION_PROMPT

DB_DSN = config.db_dsn
BATCH_SIZE = 10


def extract_skills(title, description):
    text = f"Title: {title or ''}\n{description or ''}"
    prompt = LLM_SKILLS_EXTRACTION_PROMPT.format(text=text)
    
    try:
        resp = call_deepseek(prompt)
        if not resp:
            return None
        result = json.loads(resp)
        for key in ['hard_skills', 'soft_skills', 'responsibilities', 'seniority']:
            if key not in result:
                result[key] = [] if key != 'seniority' else None
        return result
    except Exception as e:
        print(f"  LLM error: {e}")
        return None


def title_seniority_heuristic(title):
    if not title: return None
    t = title.lower()
    if re.search(r'\bintern\b|\bстажер|\binternship\b|\bjunior\b.*\bdevops|\bстаж', t):
        return 'Intern'
    if re.search(r'\bjunior\b|\bджуниор|\bджу н|\bмладш', t):
        return 'Junior'
    if re.search(r'\bsenior\b|\bсиньор|\bсеньор|\bстарш', t):
        return 'Senior'
    if re.search(r'\blead\b|\bлид\b|\bhead of\b|\bруководител', t):
        return 'Lead'
    if re.search(r'\bmiddle\b|\bмидл\b', t):
        return 'Middle'
    if re.search(r'\b(middle|mid)\s*[/-]\s*(senior|sr)\b', t):
        return 'Middle/Senior'
    return None


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor(cursor_factory=RealDictCursor)
    
    cur.execute("""
        SELECT vacancy_id, title, description
        FROM vacancies
        WHERE skills_extracted IS NULL
          AND (needs_review IS NULL OR needs_review = false)
        ORDER BY created_at
    """)
    rows = cur.fetchall()
    print(f"[llm_extract] {len(rows)} vacancies to process")
    
    done = 0
    for i, r in enumerate(rows):
        vid = r['vacancy_id']
        title = r['title']
        desc = r['description'] or ''
        
        # Heuristic seniority first
        heur_grade = title_seniority_heuristic(title)
        
        if len(desc) < 50:
            skills = {"hard_skills": [], "soft_skills": [], "responsibilities": [], "seniority": heur_grade}
        else:
            skills = extract_skills(title, desc)
            if skills is None:
                print(f"  [{i+1}/{len(rows)}] {vid}: SKIP (LLM error)")
                continue
            if skills.get('seniority') is None:
                skills['seniority'] = heur_grade
        
        cur.execute(
            """UPDATE vacancies
               SET skills_extracted = %s,
                   hard_skills_json = %s,
                   soft_skills_json = %s,
                   responsibilities_json = %s,
                   seniority_grade = COALESCE(%s, seniority_grade)
               WHERE vacancy_id = %s""",
            (
                json.dumps(skills, ensure_ascii=False),
                json.dumps(skills.get('hard_skills', []), ensure_ascii=False),
                json.dumps(skills.get('soft_skills', []), ensure_ascii=False),
                json.dumps(skills.get('responsibilities', []), ensure_ascii=False),
                skills.get('seniority'),
                vid,
            ),
        )
        done += 1
        
        if done % BATCH_SIZE == 0:
            conn.commit()
            print(f"[llm_extract] {done}/{len(rows)} ({done/len(rows)*100:.0f}%)")
        
        time.sleep(0.5)
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"[llm_extract] Done. {done} vacancies processed.")


if __name__ == "__main__":
    main()
