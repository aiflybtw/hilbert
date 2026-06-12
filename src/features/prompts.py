LLM_TELEGRAM_PARSE_PROMPT = """\
Ты — парсер вакансий. Извлеки из текста структурированные поля и верни строго JSON.

СТРУКТУРА JSON:
{
  "title": "название позиции или null",
  "seniority": "Junior | Middle | Senior | Lead | null",
  "company_name": "название компании или null",
  "location": "город или null",
  "salary_from": число (число месяц руб, без тысяч/миллионов) или null,
  "salary_to": число или null,
  "currency": "RUB | USD | EUR | ... |null",
  "remote": true | false | null,
  "description_clean": "полный текст"
}

ОСОБЫЕ ИНСТРУКЦИИ:
- salary_from/salary_to: указывай сумму за месяц в рублях/валюте. Если указано "200k" → 200000.
  Не путай с годовой зарплатой (годовая /12, почасовой ×160).
- seniority: извлекай ТОЛЬКО если грейд явно указан (Junior, Middle, Senior, Lead).
  Если не указан — null. Не выдумывай.
- description_clean: полный текст вакансии без изменений.
- remote: true если есть "удалённо/remote/удаленка", false если указан офис, null если неясно.
- Если данных нет — null. Не выдумывай.

ПРИМЕР 1:
Вход:
Компания: ExampleCorp
Позиция: Middle DevOps Инженер
Формат: удаленка
З/П: от 200 000 до 350 000 руб.

Обязанности:
- Поддержка Kubernetes
- CI/CD pipelines

Стек: Docker, K8s, GitLab CI

Выход:
{
  "title": "DevOps Engineer",
  "seniority": "Middle",
  "company_name": "ExampleCorp",
  "location": null,
  "salary_from": 200000,
  "salary_to": 350000,
  "currency": "RUB",
  "remote": true,
  "description_clean": "Компания: ExampleCorp\nПозиция: Middle DevOps Engineer\nФормат: удаленка\nЗП: от 200 000 до 350 000 руб.\n\nОбязанности:\n- Поддержка Kubernetes\n- CI/CD pipelines\n\nСтек: Docker, K8s, GitLab CI"
}

ПРИМЕР 2:
Вход:
Компания ClosedAI в поисках SRE/DevOps
Вилка: 300-400к
Основные задачи:
- проектирование и развитие on-prem инфраструктуры
- настройка и оптимизация Kubernetes-кластеров
- автоматизация CI/CD

Выход:
{
  "title": "SRE/DevOps",
  "seniority": null,
  "company_name": "ClosedAI",
  "location": null,
  "salary_from": 300000,
  "salary_to": 400000,
  "currency": "RUB",
  "remote": null,
  "description_clean": "Компания ClosedAI в поисках SRE/DevOps\nВилка: 300-400к\nОсновные задачи:\n- проектирование и развитие on-prem инфраструктуры\n- настройка и оптимизация Kubernetes-кластеров\n- автоматизация CI/CD"
}

ПРИМЕР 3:
Вход:
Position: Senior SRE
Location: Moscow
Salary: $8000-10000
Requirements:
- 5+ years experience
- AWS, Terraform

Выход:
{
  "title": "SRE",
  "seniority": "Senior",
  "company_name": null,
  "location": "Moscow",
  "salary_from": 8000,
  "salary_to": 10000,
  "currency": "USD",
  "remote": false,
  "description_clean": "Position: Senior SRE\nLocation: Moscow\nSalary: $8000-10000\n\nRequirements:\n- 5+ years experience\n- AWS, Terraform"
}

ТЕКСТ ВАКАНСИИ:
{text}
"""

LLM_SKILLS_EXTRACTION_PROMPT = """\
Ты — эксперт по анализу IT-вакансий. Извлеки структурированную информацию: hard \
(конкретные технологии и инструменты, например, Kubernetes, PostgreSQL...) и soft \
(лидерство и управление командой, коммуникабельность и работа в команде, \
планирование, ответственность) навыки из текста вакансии и верни строго JSON.

СТРУКТУРА JSON:
{
  "seniority": "Junior | Middle | Senior | Lead | null",
  "experience": {
    "min_years": число или null,
    "description": "краткое описание требований к опыту"
  },
  "hard_skills": [
    {
      "name": "Kubernetes",
      "priority": "required | preferred",
      "context_snippet": "дословная цитата из текста (5-15 слов)"
    }
  ],
  "soft_skills": [
    {
      "name": "Team leadership",
      "context_snippet": "дословная цитата из текста"
    }
  ],
  "responsibilities": [
    {
      "action": "проектирование",
      "object": "инфраструктура",
      "context_snippet": "дословная цитата из текста (5-15 слов)"
    }
  ],
  "languages": [{"name": "English", "level": "A2 | B1 | B2 | C1 | C2 | null"}]
}

ОСОБЫЕ ИНСТРУКЦИИ:
- priority: "required" из "Требования/Обязанности", \
              "preferred" из "Будет плюсом/Желательно"
- context_snippet: дословно 5-15 слов из текста, где упоминается навык
- seniority: извлекай ТОЛЬКО если грейд явно указан в тексте (Junior, Middle, \
  Senior, Lead). Если не указан — ставь null. Не выдумывай.
- Если данных нет — null. Не выдумывай.

ПРИМЕР 1:
Вход:
Обязательные требования: Опыт работы в роли DevOps не менее 3х лет. Управление Kubernetes кластерами в production, настройка CI/CD в GitLab CI, опыт работы с AWS (EKS, VPC, IAM), знание Python для автоматизации, умение работать в команде и документировать выполняемые задачи.
Будет плюсом: Опыт с Terraform
Задачи: Объединение всех процессов из разработки в поставку, настройка и развертывание инфраструктуры. 


Выход:
{
  "seniority": null,
  "experience": {"min_years": 3, "description": "Опыт работы в роли DevOps не менее 3х лет"},
  "hard_skills": [
    {"name": "Kubernetes", "priority": "required", "context_snippet": "Управление Kubernetes кластерами в production"},
    {"name": "GitLab CI", "priority": "required", "context_snippet": "Настройка CI/CD в GitLab CI"},
    {"name": "AWS", "priority": "required", "context_snippet": "Опыт работы с AWS (EKS, VPC, IAM)"},
    {"name": "Python", "priority": "required", "context_snippet": "Знание Python для автоматизации"},
    {"name": "Terraform", "priority": "preferred", "context_snippet": "Опыт с Terraform"}
  ],
  "soft_skills": [
    {"name": "Работа в команде", "priority": "required", "context_snippet": "Умение работать в команде"},
    {"name": "Документация", "priority": "required", "context_snippet": "Умение работать в команде и документировать выполняемые задачи"}
  ],
  "responsibilities": [
    {"action": "Объединение", "object": "процессы", "context_snippet": "Объединение всех процессов из разработки в поставку"},
    {"action": "Настройка", "object": "инфраструктура", "context_snippet": "настройка и развертывание инфраструктуры"},
    {"action": "Развертывание", "object": "инфраструктура", "context_snippet": "настройка и развертывание инфраструктуры"}
  ],
  "languages": []
}

ПРИМЕР 2:
Вход:
Senior DevOps Engineer
Требования:
- 5+ лет опыта
- Kubernetes, CI/CD, AWS
- Управление командой
Обязанности:
- Проектирование on-prem инфраструктуры

Выход:
{
  "seniority": "Senior",
  "experience": {"min_years": 5, "description": "5+ лет опыта"},
  "hard_skills": [
    {"name": "Kubernetes", "priority": "required", "context_snippet": "Kubernetes"},
    {"name": "AWS", "priority": "required", "context_snippet": "AWS"}
  ],
  "soft_skills": [
    {"name": "Управление командой", "priority": "required", "context_snippet": "Управление командой"}
  ],
  "responsibilities": [
    {"action": "Проектирование", "object": "инфраструктура", "context_snippet": "Проектирование on-prem инфраструктуры"}
  ],
  "languages": []
}

ТЕКСТ ВАКАНСИИ:
{text}
"""

LLM_HARD_SKILL_DESCRIBE_PROMPT = """\
Ты — таксономист DevOps/SRE инструментов. Каждый навык должен быть классифицирован \
по домену (категории) и описан по единому шаблону для последующей векторной кластеризации.
Описания пойдут в Sentence-BERT → UMAP → HDBSCAN. Чтобы кластеры получились \
семантически плотными, используй ОДИНАКОВЫЕ формулировки для навыков из одного домена.

Для каждого навыка верни JSON-объект с двумя полями:
- "domain": категория из списка ниже (строго одно значение)
- "description": описание по шаблону (15-30 слов, максимум 40)

СТРОГИЙ СПИСОК ДОМЕНОВ (выбери ОДИН наиболее подходящий):
  container-orchestration, containerization, ci-cd, monitoring, alerting, logging,
  tracing, infrastructure-as-code, config-management, cloud-provider, database,
  relational-database, nosql-database, messaging-queue, streaming, networking,
  security, secret-management, programming-language, scripting, version-control,
  storage, virtualization, service-mesh, load-balancing, web-server, reverse-proxy,
  build-tools, data-processing, machine-learning, backup, dns, observability-platform,
  api-gateway, key-value-store, cache, automation, package-management

ШАБЛОН DESCRIPTION (строго):
"Домен: {domain}. {роль технологии: что делает}. {ключевые операции}. {экосистема и интеграции}."

ПРИМЕРЫ КОРРЕКТНЫХ ОТВЕТОВ:

Пример 1:
Вход: {"name": "Kubernetes", "frequency": 809, "co_occurring": ["Docker", "Helm", "Prometheus", "GitLab CI", "Terraform"], "priority": "required"}
Ответ: {"Kubernetes": {"domain": "container-orchestration", "description": "Домен: container-orchestration. Оркестрация контейнеров: автоматизация деплоя, масштабирования и управления контейнеризованными приложениями. Управление Pod'ами, сервисами, Ingress. Экосистема: Helm, Prometheus, Istio."}}

Пример 2:
Вход: {"name": "Prometheus", "frequency": 503, "co_occurring": ["Grafana", "Kubernetes", "Docker", "VictoriaMetrics", "Loki"], "priority": "required"}
Ответ: {"Prometheus": {"domain": "monitoring", "description": "Домен: monitoring. Мониторинг и алертинг: сбор метрик с таймсериями, PromQL для запросов, AlertManager для нотификаций. Экосистема: Grafana, VictoriaMetrics, exporters."}}

Пример 3:
Вход: {"name": "Terraform", "frequency": 388, "co_occurring": ["Ansible", "AWS", "Kubernetes", "GitLab CI", "Docker"], "priority": "required"}
Ответ: {"Terraform": {"domain": "infrastructure-as-code", "description": "Домен: infrastructure-as-code. IaC: декларативное управление инфраструктурой через HCL, план/apply, управление state. Экосистема: AWS, OpenTofu, Terragrunt."}}

Пример 4:
Вход: {"name": "GitLab CI", "frequency": 332, "co_occurring": ["Kubernetes", "Docker", "Ansible", "Terraform", "Helm"], "priority": "required"}
Ответ: {"GitLab CI": {"domain": "ci-cd", "description": "Домен: ci-cd. CI/CD: пайплайны автоматизации сборки, тестирования и деплоя в GitLab. YAML-конфигурация, GitLab Runner, registry. Экосистема: Kubernetes, Docker."}}

Пример 5:
Вход: {"name": "Nginx", "frequency": 219, "co_occurring": ["Linux", "Docker", "Kubernetes", "Python", "Bash"], "priority": "required"}
Ответ: {"Nginx": {"domain": "reverse-proxy", "description": "Домен: reverse-proxy. Обратный прокси и веб-сервер: балансировка трафика, TLS-терминация, проксирование микросервисов, ограничение скорости. Экосистема: Linux, Docker."}}

ПРАВИЛА:
1. Используй ОДИНАКОВЫЕ формулировки для инструментов одного домена (все CI/CD через "пайплайны автоматизации", все мониторинг через "сбор метрик/логов")
2. Поле domain — строго из списка, без вариаций
3. Description в одном предложении, без переносов строк
4. Не добавляй общих абстракций вроде "автоматизация", "современная инфраструктура"
5. Технические термины — на английском, связки — на русском
6. Если сомневаешься между двумя доменами — выбери более конкретный
7. Ответь ТОЛЬКО JSON-объектом, без пояснений и markdown

Входные данные:
{input_json}
"""
