"""generate_responsibility_clusters.py — Extract, normalize, cluster responsibilities from DB."""
import json, os, sys
from collections import Counter, defaultdict

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
DATA = os.path.join(BASE, "..", "data")

# Action alias map (raw → normalized)
ACTION_ALIASES = {
    "проектирование": "Проектирование",
    "разворачивание": "Развёртывание",
    "развертывание": "Развёртывание",
    "развертывать": "Развёртывание",
    "разворачивать": "Развёртывание",
    "деплой": "Развёртывание",
    "поддержка": "Поддержка",
    "поддерживать": "Поддержка",
    "сопровождение": "Сопровождение",
    "администрирование": "Администрирование",
    "администрировать": "Администрирование",
    "автоматизация": "Автоматизация",
    "автоматизировать": "Автоматизация",
    "настройка": "Настройка",
    "настраивать": "Настройка",
    "конфигурирование": "Настройка",
    "конфигурация": "Настройка",
    "оптимизация": "Оптимизация",
    "оптимизировать": "Оптимизация",
    "развитие": "Развитие",
    "развивать": "Развитие",
    "внедрение": "Внедрение",
    "внедрять": "Внедрение",
    "мониторинг": "Мониторинг",
    "мониторить": "Мониторинг",
    "создание": "Создание",
    "создавать": "Создание",
    "разработка": "Разработка",
    "разрабатывать": "Разработка",
    "управление": "Управление",
    "управлять": "Управление",
    "обеспечение": "Обеспечение",
    "обеспечивать": "Обеспечение",
    "участие": "Участие",
    "участвовать": "Участие",
    "тестирование": "Тестирование",
    "документирование": "Документирование",
    "ведение": "Ведение",
    "вести": "Ведение",
    "построение": "Построение",
    "строить": "Построение",
    "работа": "Работа",
    "работать": "Работа",
    "решение": "Решение",
    "решать": "Решение",
    "реализация": "Реализация",
    "реализовать": "Реализация",
    "сборка": "Сборка",
    "написание": "Написание",
    "писать": "Написание",
    "диагностика": "Диагностика",
    "устранение": "Устранение",
    "интеграция": "Интеграция",
    "интегрировать": "Интеграция",
    "подготовка": "Подготовка",
    "подготавливать": "Подготовка",
    "планирование": "Планирование",
    "контроль": "Контроль",
    "анализ": "Анализ",
    "выявление": "Выявление",
    "масштабирование": "Масштабирование",
    "консультирование": "Консультирование",
    "обучение": "Обучение",
    "взаимодействие": "Взаимодействие",
    "согласование": "Согласование",
    "проведение": "Проведение",
    "проводить": "Проведение",
    "координация": "Координация",
    "организация": "Организация",
    "эксплуатация": "Эксплуатация",
    "эксплуатировать": "Эксплуатация",
    "обновление": "Обновление",
}

# Object alias map (raw → normalized)
OBJECT_ALIASES = {
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "docker": "Docker",
    "ci/cd": "CI/CD",
    "ci cd": "CI/CD",
    "ci-cd": "CI/CD",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "prometheus": "Prometheus",
    "grafana": "Grafana",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "kafka": "Kafka",
    "linux": "Linux",
    "gitlab": "GitLab",
    "git": "Git",
    "python": "Python",
    "bash": "Bash",
    "helm": "Helm",
    "argocd": "ArgoCD",
    "aws": "AWS",
    "azure": "Azure",
    "gcp": "GCP",
    "nginx": "Nginx",
    "redis": "Redis",
    "elk": "ELK Stack",
    "elastichsearch": "Elasticsearch",
    "jenkins": "Jenkins",
    "rabbitmq": "RabbitMQ",
}


def normalize_action(raw):
    if not raw:
        return "Прочее"
    key = raw.lower().strip()
    return ACTION_ALIASES.get(key, raw.strip())


def normalize_object(raw):
    if not raw:
        return "Прочее"
    key = raw.lower().strip()
    return OBJECT_ALIASES.get(key, raw.strip())


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    print("[resp_clusters] Loading responsibilities from DB...")
    cur.execute("""
        SELECT vacancy_id, seniority_grade, responsibilities_json, description
        FROM vacancies
        WHERE responsibilities_json IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[resp_clusters] {len(rows)} vacancies with responsibilities")

    # ── Extract all (action, object) pairs ──
    raw_records = []
    action_counter = Counter()
    object_counter = Counter()
    pair_counter = Counter()

    for vid, grade, resp_json, desc in rows:
        if isinstance(resp_json, str):
            resp_list = json.loads(resp_json)
        else:
            resp_list = resp_json or []
        if not isinstance(resp_list, list):
            continue

        for item in resp_list:
            if not isinstance(item, dict):
                continue
            action = (item.get("action") or "").strip()
            obj = (item.get("object") or "").strip()
            if not action:
                continue

            raw_records.append({
                "vacancy_id": vid,
                "grade": grade,
                "action": action,
                "object": obj,
                "context": desc[:200] if desc else "",
            })
            action_counter[action] += 1
            if obj:
                object_counter[obj] += 1
            pair_counter[(action, obj)] += 1

    print(f"[resp_clusters] {len(raw_records)} raw responsibility records")
    print(f"[resp_clusters] {len(action_counter)} unique raw actions")
    print(f"[resp_clusters] {len(object_counter)} unique raw objects")

    # ── Save raw records ──
    raw_path = os.path.join(DATA, "responsibilities_raw.json")
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(raw_records, f, ensure_ascii=False, indent=2)
    print(f"[resp_clusters] Saved: {raw_path}")

    # ── Build action normalization map ──
    action_norm = {}
    for raw_action in action_counter:
        norm = normalize_action(raw_action)
        if norm != raw_action:
            action_norm[raw_action] = norm
        else:
            action_norm[raw_action] = raw_action

    action_path = os.path.join(DATA, "action_normalization.json")
    with open(action_path, "w", encoding="utf-8") as f:
        json.dump(action_norm, f, ensure_ascii=False, indent=2)
    print(f"[resp_clusters] Saved: {action_path}")

    # ── Build object normalization map ──
    # For objects, we normalize by checking if any part of the object matches
    object_norm = {}
    for raw_obj in object_counter:
        norm = normalize_object(raw_obj)
        if norm != raw_obj:
            object_norm[raw_obj] = norm
        else:
            object_norm[raw_obj] = raw_obj

    # Also try partial matching for objects not in the direct map
    for raw_obj in object_counter:
        if raw_obj in object_norm:
            continue
        raw_lower = raw_obj.lower()
        found = False
        for alias, canonical in sorted(OBJECT_ALIASES.items(), key=lambda x: -len(x[0])):
            if alias in raw_lower:
                object_norm[raw_obj] = canonical
                found = True
                break
        if not found:
            object_norm[raw_obj] = raw_obj

    obj_path = os.path.join(DATA, "object_normalization.json")
    with open(obj_path, "w", encoding="utf-8") as f:
        json.dump(object_norm, f, ensure_ascii=False, indent=2)
    print(f"[resp_clusters] Saved: {obj_path}")

    # ── Cluster by normalized (action, object) pair ──
    # Simple clustering: group identical normalized pairs together
    # Assign a cluster ID to each unique normalized pair
    pair_to_cluster = {}
    cluster_pairs = defaultdict(list)
    cluster_id = 0

    for (raw_action, raw_obj), cnt in pair_counter.most_common():
        norm_action = action_norm.get(raw_action, raw_action)
        norm_obj = object_norm.get(raw_obj, raw_obj)
        norm_pair = (norm_action, norm_obj)

        if norm_pair not in pair_to_cluster:
            pair_to_cluster[norm_pair] = cluster_id
            cluster_id += 1

        cid = pair_to_cluster[norm_pair]
        cluster_pairs[cid].append({
            "raw_action": raw_action,
            "raw_object": raw_obj,
            "count": cnt,
        })

    print(f"[resp_clusters] {cluster_id} unique normalized (action, object) clusters")

    # ── Write cluster IDs per vacancy ──
    # Build vacancy → cluster IDs mapping
    vacancy_clusters = defaultdict(set)
    for rec in raw_records:
        vid = rec["vacancy_id"]
        norm_action = action_norm.get(rec["action"], rec["action"])
        norm_obj = object_norm.get(rec["object"], rec["object"])
        cid = pair_to_cluster.get((norm_action, norm_obj))
        if cid is not None:
            vacancy_clusters[vid].add(cid)

    # Write to DB
    updated = 0
    for vid, cids in vacancy_clusters.items():
        cur.execute(
            "UPDATE vacancies SET resp_clusters = %s WHERE vacancy_id = %s",
            (json.dumps(sorted(cids)), vid),
        )
        updated += 1
        if updated % 200 == 0:
            conn.commit()
            print(f"[resp_clusters] {updated}/{len(vacancy_clusters)}")

    conn.commit()
    print(f"[resp_clusters] {updated} vacancies updated with resp_clusters")

    # ── Print cluster summary ──
    print(f"\n[resp_clusters] Top 20 clusters by frequency:")
    for cid, pairs in sorted(cluster_pairs.items(), key=lambda x: -sum(p["count"] for p in x[1]))[:20]:
        total = sum(p["count"] for p in pairs)
        top_pair = pairs[0]
        print(f"  Cluster {cid}: {total} occurrences")
        print(f"    Representative: {top_pair['raw_action']} | {top_pair['raw_object']}")

    cur.close()
    conn.close()
    print("[resp_clusters] Done.")


if __name__ == "__main__":
    main()
