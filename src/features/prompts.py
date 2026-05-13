ZERO_SHOT_TEMPLATE = """\
You are a parser that extracts structured data from job postings in Russian or English.

Extract the following fields from the job posting below. Return ONLY valid JSON.

Fields:
- title: str | null — position name, e.g. "Senior DevOps Engineer"
- company_name: str | null
- location: str | null — city or country
- salary_from: float | null — lower bound (convert K/thousands)
- salary_to: float | null — upper bound
- currency: str | null — "RUB", "USD", "EUR", "USDT"
- remote: bool — is the position remote
- description_clean: str — full text WITHOUT hashtags, @mentions, emoji

Post:
{text}
"""

FEW_SHOT_EXAMPLES = [
    # Example 1
    {
        "raw": (
            "Компания: ExampleCorp\n"
            "Позиция: Middle DevOps Инженер\n"
            "Формат: удаленка\n"
            "З/П: от 200 000 до 350 000 руб.\n\n"
            "Обязанности:\n"
            "- Поддержка Kubernetes\n"
            "- CI/CD pipelines\n\n"
            "Стек: Docker, K8s, GitLab CI"
        ),
        "expected": {
            "title": "Middle DevOps Engineer",
            "company_name": "ExampleCorp",
            "location": None,
            "salary_from": 200000,
            "salary_to": 350000,
            "currency": "RUB",
            "remote": True,
            "description_clean": "Компания: ExampleCorp\nПозиция: Middle DevOps Engineer\nФормат: удаленка\nЗП: от 200 000 до 350 000 ₽\n\nОбязанности:\n- Поддержка Kubernetes\n- CI/CD pipelines\n\nСтек: Docker, K8s, GitLab CI",
        },
    },
    # Example 2: More informal raw text (no seniority grade as well)
    {
        "raw": (
            "Компания ClosedAI в поисках SRE/DevOps\n"
            "Вилка: 300-400к\n\n"
            "Основные задачи:\n"
            "- проектирование и развитие on-prem инфраструктуры;\n"
            "- настройка и оптимизация Kubernetes-кластеров;\n"
            "- автоматизация CI/CD и IaC (Terraform, Ansible, GitLab CI/CD);\n"
            "- настройка observability и HA/DR (Prometheus, Grafana, PostgreSQL, Redis, Kafka и др.).\n\n"
            "Технологический стек:\n"
            "Linux, Kubernetes, Ansible, Terraform, GitLab CI/CD, PostgreSQL, Redis, RabbitMQ, Elasticsearch, Prometheus, Grafana.\n"
            "(Будет плюсом: Go/Python, Kafka, Vault, NATS.)\n\n"
            "Требования:\n"
            "- 4-6+ лет опыта девопсом в on-prem или гибридных инфраструктурах;\n"
            "- глубокое понимание ОС и принципов работы оборудования;\n"
            "- опыт работы с Bash / Python / Go;\n"
            "- системное мышление и умение работать с архитектурными решениями.\n"
        ),
        "expected": {
            "title": "SRE/DevOps",
            "company_name": "ClosedAI",
            "location": None,
            "salary_from": 300000,
            "salary_to": 400000,
            "currency": "RUB",
            "remote": None,
            "description_clean": (
                "Компания ClosedAI в поисках SRE/DevOps\n"
                "Вилка: 300-400к\n\n"
                "Основные задачи:\n"
                "- проектирование и развитие on-prem инфраструктуры;\n"
                "- настройка и оптимизация Kubernetes-кластеров;\n"
                "- автоматизация CI/CD и IaC (Terraform, Ansible, GitLab CI/CD);\n"
                "- настройка observability и HA/DR (Prometheus, Grafana, PostgreSQL, Redis, Kafka и др.).\n\n"
                "Технологический стек:\n"
                "Linux, Kubernetes, Ansible, Terraform, GitLab CI/CD, PostgreSQL, Redis, RabbitMQ, Elasticsearch, Prometheus, Grafana.\n"
                "(Будет плюсом: Go/Python, Kafka, Vault, NATS.)\n\n"
                "Требования:\n"
                "- 4-6+ лет опыта девопсом в on-prem или гибридных инфраструктурах;\n"
                "- глубокое понимание ОС и принципов работы оборудования;\n"
                "- опыт работы с Bash / Python / Go;\n"
                "- системное мышление и умение работать с архитектурными решениями."
            ),
        },
    },
    # Example 3: raw text in English and salary in USD
    {
        "raw": (
            "Position: Senior SRE\n"
            "Location: Moscow\n"
            "Salary: $8000-10000\n"
            "Requirements:\n- 5+ years experience\n- AWS, Terraform"
        ),
        "expected": {
            "title": "Senior SRE",
            "company_name": None,
            "location": "Moscow",
            "salary_from": 8000,
            "salary_to": 10000,
            "currency": "USD",
            "remote": False,
            "description_clean": "Position: Senior SRE\nLocation: Moscow\nSalary: $8000-10000\n\nRequirements:\n- 5+ years experience\n- AWS, Terraform",
        },
    },
]

FEW_SHOT_TEMPLATE = (
    "You are a parser that extracts structured data from job postings.\n"
    "Return ONLY valid JSON with these fields:\n"
    "- title, company_name, location, salary_from, salary_to, currency, remote, description_clean\n\n"
    "Examples:\n"
)

for ex in FEW_SHOT_EXAMPLES:
    FEW_SHOT_TEMPLATE += f"\nInput:\n{ex['raw']}\n\nOutput:\n{ex['expected']}\n\n"

FEW_SHOT_TEMPLATE += "Now extract from:\n\n{text}"
