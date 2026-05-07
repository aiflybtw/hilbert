# DevOps Salary Model

Crawler + parser для сбора данных по вакансиям с агрегаторов вакансий hh.ru, career.habr.com и каналов в мессенджере Telegram. Собранные данные используются для построения эконометрической зарплатной модели. 

### Запуск 

```bash
# 1. Установить зависимости
pip install -e .

# 2. Настроить .env (скопировать из шаблона)
cp .env.template .env
# Отредактировать .env: указать пароль БД, API Telegram

# 3. Запустить сбор данных
python -m src.cli.main --query DevOps
```

### Структура проекта

```
src/
├── config.py              # Настройки из .env
├── session.py             # HTTP-сессия (имитация браузера)
├── db.py                  # PostgreSQL: таблицы, репозитории
├── base_crawler.py        # Базовый crawler
├── base_parser.py         # Базовый parser (JSON-LD, зарплата)
├── crawlers/              # hh, habr, telegram
├── parsers/               # hh, habr (telegram — позже через NER модель)
├── cleaners/              # Очистка HTML из описаний
└── cli/                   # main.py (оркестратор), review.py (Excel)
```

### Команды 

| Команда | Что делает |
|---|---|
| `python -m src.cli.main` | Полный пайплайн: crawling -> parsing |
| `python -m src.cli.main --crawl-only` | Только сбор ссылок |
| `python -m src.cli.main --parse-only` | Только парсинг из очереди |
| `python -m src.cli.main --sources hh` | Только HH |
| `python -m src.cli.main --query SRE` | Один запрос |
| `python -m src.crawlers.telegram` | Только Telegram |
| `python -m src.cleaners.description` | Очистка описаний от HTML |
| `python -m src.cli.review` | Экспорт в Excel |

### База данных

- `crawl_queue` — очередь URL для HH/Habr (статусы: pending -> processing -> done/error)
- `vacancies` — итоговые данные. На текущий момент данные из Telegram сохраняются как сырой текст с `needs_review=True`

### Работа с Telegram

1. Получить `api_id` и `api_hash` на https://my.telegram.org 
2. Вписать в `.env`
3. При первом запуске Telethon запросит номер телефона и код подтверждения
4. Сессия сохранится в `tg_session` 

