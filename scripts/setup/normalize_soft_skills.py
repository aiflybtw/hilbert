"""normalize_soft_skills.py — Alias normalization for soft skills.

Reads soft_skills_json from DB, applies alias mapping to merge similar names,
writes back normalized names. Saves unique normalized names to data/soft_skills_names.json.
"""
import json, os, sys
from collections import Counter

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
OUTPUT_PATH = os.path.join(BASE, "..", "data", "soft_skills_names.json")

SOFT_ALIASES = {
    "коммуникабельность": "Коммуникабельность",
    "коммуникация и сотрудничество": "Коммуникация и сотрудничество",
    "коммуникация с заказчиком": "Коммуникация с заказчиком",
    "коммуникация с разработчиками": "Коммуникация с разработчиками",
    "коммуникация с техническими специалистами": "Коммуникация с техническими специалистами",
    "работа в команде": "Работа в команде",
    "работа в распределенных командах": "Работа в распределенных командах",
    "коллаборация": "Коллаборация",
    "сотрудничество между разработчиками и администраторами": "Сотрудничество между разработчиками и администраторами",
    "team leadership": "Лидерство",
    "лидерство": "Лидерство",
    "лидерство и наставничество": "Лидерство и наставничество",
    "техническое лидерство": "Техническое лидерство",
    "инициативность": "Инициативность",
    "самостоятельность": "Самостоятельность",
    "самостоятельность и доведение задач до результата": "Самостоятельность и доведение задач до результата",
    "самостоятельное принятие решений": "Самостоятельное принятие решений",
    "самоорганизация": "Самоорганизация",
    "ответственность": "Ответственность",
    "ориентация на результат": "Ориентация на результат",
    "аналитическое мышление": "Аналитическое мышление",
    "системное мышление": "Системное мышление",
    "критическое мышление": "Критическое мышление",
    "архитектурное мышление": "Архитектурное мышление",
    "продуктовое мышление": "Продуктовое мышление",
    "решение проблем": "Решение проблем",
    "диагностика и устранение проблем": "Диагностика и устранение проблем",
    "устранение неполадок и решение проблем": "Устранение неполадок и решение проблем",
    "управление инцидентами": "Управление инцидентами",
    "управление проектами": "Управление проектами",
    "планирование": "Планирование",
    "стратегическое планирование": "Стратегическое планирование",
    "стратегическое планирование инфраструктуры": "Стратегическое планирование инфраструктуры",
    "делегирование задач": "Делегирование задач",
    "наставничество": "Наставничество",
    "обучение": "Обучение",
    "обучение команд": "Обучение команд",
    "передача знаний": "Передача знаний",
    "обмен знаниями": "Обмен знаниями",
    "документирование": "Документирование",
    "адаптивность": "Адаптивность",
    "быстрое обучение и адаптивность": "Быстрое обучение и адаптивность",
    "обучаемость": "Обучаемость",
    "стремление обучаться": "Стремление обучаться",
    "самообразование": "Самообразование",
    "стрессоустойчивость": "Стрессоустойчивость",
    "тайм-менеджмент": "Тайм-менеджмент",
    "многозадачность": "Многозадачность",
    "внимание к деталям": "Внимание к деталям",
    "работа с open source": "Работа с Open Source",
    "code review": "Code Review",
    "agile / scrum": "Agile / Scrum",
    "on-call / дежурства": "On-call / Дежурства",
    "communication with stakeholders": "Communication with stakeholders",
}

SOFT_ALIASES.update({
    "teamwork": "Работа в команде",
    "team work": "Работа в команде",
    "collaboration": "Коллаборация",
    "communication": "Коммуникабельность",
    "leadership": "Лидерство",
    "mentoring": "Наставничество",
    "mentorship": "Наставничество",
    "problem solving": "Решение проблем",
    "problem-solving": "Решение проблем",
    "time management": "Тайм-менеджмент",
    "time-management": "Тайм-менеджмент",
    "adaptability": "Адаптивность",
    "self-organization": "Самоорганизация",
    "self organization": "Самоорганизация",
    "responsibility": "Ответственность",
    "proactivity": "Инициативность",
    "proactive": "Инициативность",
    "initiative": "Инициативность",
    "documentation": "Документирование",
    "knowledge sharing": "Обмен знаниями",
    "knowledge transfer": "Передача знаний",
})


def normalize(name):
    name = name.strip()
    if not name:
        return None
    key = name.lower().strip('.').strip()
    if key in SOFT_ALIASES:
        return SOFT_ALIASES[key]
    if name[0].isupper() or name[0].islower():
        if name[0].islower():
            name = name[0].upper() + name[1:]
    return name


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    print("[normalize_soft] Loading soft skills from DB...")
    cur.execute("""
        SELECT vacancy_id, soft_skills_json
        FROM vacancies
        WHERE soft_skills_json IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[normalize_soft] {len(rows)} vacancies with soft_skills_json")

    all_names = Counter()
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

        changed = False
        for s in skills:
            if isinstance(s, dict) and 'name' in s:
                original = s['name']
                normed = normalize(original)
                if normed and normed != original:
                    s['name'] = normed
                    changed = True
                if normed:
                    all_names[normed] += 1
            elif isinstance(s, str):
                normed = normalize(s)
                if normed and normed != s:
                    skills[skills.index(s)] = normed
                    changed = True
                if normed:
                    all_names[normed] += 1

        if changed:
            cur.execute(
                "UPDATE vacancies SET soft_skills_json = %s WHERE vacancy_id = %s",
                (json.dumps(skills, ensure_ascii=False), vid),
            )
            updated += 1

        if updated > 0 and updated % 200 == 0:
            conn.commit()
            print(f"[normalize_soft] {updated}/{len(rows)} updated")

    conn.commit()

    unique_names = sorted(all_names.keys())
    print(f"[normalize_soft] {len(unique_names)} unique normalized soft skill names")

    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(unique_names, f, ensure_ascii=False, indent=2)
    print(f"[normalize_soft] Saved unique names to {OUTPUT_PATH}")

    cur.close()
    conn.close()
    print(f"[normalize_soft] Done. {updated} vacancies updated.")


if __name__ == "__main__":
    main()
