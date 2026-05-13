# DevOps Salary Model

### About 
Проект включает в себя сбор, предобработку и использование данных из DevOps-вакансий DevOps для построения зарплатной модели.

### Запуск 

```bash
# 1. Установить зависимости
pip install -e .

# 2. Настроить .env 
cp .env.template .env
# Отредактировать .env: указать путь к БД, API Telegram...

# 3. Запустить сбор данных
python -m src.cli.main 
```

### Структура проекта

```
src/
├── config.py              # Настройки из .env
├── session.py             # HTTP-сессия
├── db.py                  # PostgreSQL connector
├── base_crawler.py        # Базовый crawler
├── base_parser.py         # Базовый parser
├── crawlers/              # hh, habr, telegram 
├── parsers/               # hh, habr (telegram — через LLM few-shot prompting)
├── cleaners/              # Очистка HTML (hh, habr) и хештегов (telegram) из описаний 
└── cli/                   # main.py (оркестратор), review.py (xlsx/csv)
```

### Команды 

| Команда | Что делает |
|---|---|
| `python -m src.cli.main` | Полный пайплайн: crawling -> parsing |
| `python -m src.cli.main --crawl-only` | Только сбор ссылок |
| `python -m src.cli.main --parse-only` | Только парсинг из очереди |
| `python -m src.cli.main --sources hh` | Только hh |
| `python -m src.cli.main --query SRE` | Один запрос |
| `python -m src.crawlers.telegram` | Только Telegram |
| `python -m src.cleaners.description` | Очистка описаний от HTML |
| `python -m src.cli.review ` | Экспорт в csv формате |

### База данных

- `crawl_queue` — очередь URL для HH/Habr (статусы: pending -> processing -> done/error)
- `vacancies` — итоговые данные. 

