# DevOps Salary Model

Проект сбора, обработки и моделирования зарплат DevOps/SRE-специалистов.

---

## 1. Быстрый старт

```bash
# Установка
pip install -e .

# Настройка (создать .env из шаблона ниже)
# Запуск сбора данных
python -m src.cli.main
```

---

## 2. Переменные окружения (.env)

Файл `.env` в корне проекта:

```env
# PostgreSQL
DB_DSN=postgresql://postgres:пароль@localhost:5432/hilbert

# Telegram API (https://my.telegram.org → API development tools)
TG_API_ID=ваш_id
TG_API_HASH=ваш_hash
TG_SESSION_FILE=tg_session

# DeepSeek API
LLM_API_KEY=sk-...ваш_ключ...
```

---

## 3. Пайплайн (унифицированный запуск)

```bash
python scripts/pipeline.py --all                    # полный цикл
python scripts/pipeline.py --collect                # только crawl + parse
python scripts/pipeline.py --step assign            # конкретный шаг
python scripts/pipeline.py --steps extract,normalize,assign  # несколько шагов
python scripts/pipeline.py --all --force            # переобработать всё
python scripts/pipeline.py --all --tail-alpha 0.05  # 90% интервалы
```

Шаги выполняются инкрементально (только новые/необработанные записи) и автоматически подтягивают зависимости. `--force` переобрабатывает все данные.

### 3.2 Пошагово

| Команда | Шаг | Что делает |
|---|---|---|
| `python scripts/pipeline.py --step collect` | collect | Crawl + parse (все источники) через `python -m src.cli.main` |
| `python scripts/pipeline.py --step filter` | filter | Флаг нерелевантных записей |
| `python scripts/pipeline.py --step extract` | extract | LLM-извлечение hard/soft skills, seniority |
| `python scripts/pipeline.py --step normalize` | normalize | Нормализация hard skills (alias, compound split, singleton removal) |
| `python scripts/pipeline.py --step assign` | assign | Маппинг skills → существующие кластеры (24 hard + 6 soft) |
| `python scripts/pipeline.py --step model` | model | Переобучение зарплатной модели |

### 3.3 Сбор данных (отдельно)

| Команда | Что делает |
|---|---|
| `python -m src.cli.main` | Crawl + parse (все источники) |
| `python -m src.cli.main --crawl-only` | Только сбор ссылок |
| `python -m src.cli.main --parse-only` | Только парсинг из очереди |
| `python -m src.cli.main --sources hh` | Только HH |
| `python -m src.cli.main --query SRE` | Поиск по одному запросу |
| `python -m src.cli.main --queries DevOps SRE MLops` | Поиск по нескольким запросам |
| `python -m src.crawlers.telegram` | Только Telegram |

---

## 4. Зарплатная модель

### 4.1 Запуск

```bash
# Стандартный запуск (80% prediction intervals)
python scripts/salary_model.py

# Смена ширины интервалов (90%)
python scripts/salary_model.py --tail-alpha 0.05

# Смена ширины интервалов (70%)
python scripts/salary_model.py --tail-alpha 0.15
```

Параметр `--tail-alpha` контролирует хвостовую вероятность:
- `0.10` → 80% интервал (по умолчанию)
- `0.05` → 90% интервал
- `0.15` → 70% интервал

Интервалы считаются **бутстрепом** (10 000 итераций, выборка с возвратом из пула остатков своего грейда). Второй интервал в输出的 файлах — вдвое уже (`2 * tail_alpha`).

### 4.2 Результаты

| Файл | Что содержит |
|---|---|
| `data/salary_model/salary_model_coefficients_k15.json` | β-коэффициенты, p-values, CI |
| `data/salary_model/salary_model_predictions_k15.json` | Поточечные прогнозы + интервалы |
| `data/salary_model/salary_model_k15_full.json` | Полная модель для загрузки |

### 4.3 Визуализации

```bash
python scripts/generate_salary_figures.py
```

Результат: 11 PNG в `data/figures/`.

### 4.4 Дискриминативная модель (разделимость грейдов)

```bash
python scripts/bootstrap_grade_model.py
```

Результат: `data/salary_model/bootstrap_ci.json` (1000 бутстреп-итераций, β, Δβ, OOB метрики).

---

## 5. Архитектура PostgreSQL

```sql
-- Таблица вакансий (ключевые поля)
vacancies (
    vacancy_id     TEXT,          -- ID из источника
    source         TEXT,          -- hh / habr / telegram
    title          TEXT,          -- Название вакансии
    salary_from    NUMERIC,       -- Нижняя граница
    salary_to      NUMERIC,       -- Верхняя граница
    currency       TEXT,          -- RUR / USD / EUR
    description    TEXT,          -- Очищенное описание
    remote         BOOLEAN,       -- Удалёнка
    needs_review   BOOLEAN,       -- Требует проверки (telegram raw)
    
    -- Обогащённые поля (заполняются пайплайном)
    salary_from_rub    NUMERIC,   -- Конвертировано в RUB
    skills_extracted   JSONB,     -- Полный ответ LLM
    hard_skills_json   JSONB,     -- [{name, priority, context_snippet}]
    soft_skills_json   JSONB,     -- [{name, context_snippet}]
    responsibilities_json JSONB,  -- [{action, object, context_snippet}]
    seniority_grade    VARCHAR,   -- Intern / Junior / Middle / Senior / Lead
    soft_clusters      JSONB,     -- [cluster_id, ...]
)
```

---

## 6. Структура проекта

```
src/                    # Исходный код (crawler, parser, DB, LLM)
scripts/
  ├── pipeline.py       # Единый entry point
  ├── assign_clusters.py# Маппинг skills → кластеры
  ├── salary_model.py   # Зарплатная модель
  ├── setup/            # Одноразовые скрипты (BERTopic, финальная кластеризация)
  └── ...               # extract, normalize, export и т.д.
data/                   # Результаты (коэффициенты, кластеры, фигуры)
  ├── clustering/       # Кластеризация hard skills
  ├── figures/          # PNG-визуализации
  └── salary_model/     # Коэффициенты, предикшены, бутстреп
```

---

## 7. Зависимости

Полный список в `pyproject.toml`. Установка:

```bash
pip install -e .
```

