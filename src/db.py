from __future__ import annotations

from contextlib import contextmanager
from typing import Optional

import psycopg2
import psycopg2.extras


class QueueStatus:
    PENDING = "pending"
    PROCESSING = "processing"
    DONE = "done"
    ERROR = "error"


DDL = """
CREATE TABLE IF NOT EXISTS crawl_queue (
    id         SERIAL PRIMARY KEY,
    url        TEXT        NOT NULL UNIQUE,
    source     TEXT        NOT NULL,
    status     TEXT        NOT NULL DEFAULT 'pending',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    error      TEXT
);

CREATE INDEX IF NOT EXISTS idx_queue_status_source
    ON crawl_queue (status, source);

CREATE TABLE IF NOT EXISTS vacancies (
    id             SERIAL PRIMARY KEY,
    vacancy_id     TEXT        NOT NULL,
    source         TEXT        NOT NULL,
    title          TEXT,
    company_name   TEXT,
    location       TEXT,
    salary_from    NUMERIC,
    salary_to      NUMERIC,
    currency       TEXT,
    description    TEXT,
    remote         BOOLEAN,
    published_at   TIMESTAMPTZ,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    needs_review   BOOLEAN     NOT NULL DEFAULT FALSE,
    review_reasons TEXT,
    UNIQUE (vacancy_id, source)
);

CREATE INDEX IF NOT EXISTS idx_vacancies_source
    ON vacancies (source);

ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS needs_review   BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE vacancies ADD COLUMN IF NOT EXISTS review_reasons TEXT;

CREATE INDEX IF NOT EXISTS idx_vacancies_needs_review
    ON vacancies (needs_review) WHERE needs_review = TRUE;
"""


class PostgresDB:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = False
        self._apply_ddl()
        print(f"[PostgresDB] Connected: {dsn}")

    def _apply_ddl(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(DDL)
        self._conn.commit()

    @contextmanager
    def cursor(self):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            cur.close()

    def close(self) -> None:
        self._conn.close()


class CrawlQueueRepo:
    def __init__(self, db: PostgresDB):
        self._db = db

    def push_urls(self, urls: list[str], source: str) -> int:
        if not urls:
            return 0
        added = 0
        with self._db.cursor() as cur:
            for url in urls:
                cur.execute(
                    """
                    INSERT INTO crawl_queue (url, source, status, created_at, updated_at)
                    VALUES (%s, %s, 'pending', NOW(), NOW())
                    ON CONFLICT (url) DO NOTHING
                    """,
                    (url, source),
                )
                added += cur.rowcount
        print(f"[queue] +{added} new URLs (source={source})")
        return added

    def set_status(self, url: str, status: str, error: Optional[str] = None) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                """
                UPDATE crawl_queue
                SET status = %s, updated_at = NOW(), error = %s
                WHERE url = %s
                """,
                (status, error, url),
            )
        print(f"  [queue] {url!r} -> {status}" + (f" ({error})" if error else ""))

    def pull_pending(self, source: Optional[str] = None, limit: int = 50) -> list[dict]:
        if source:
            source_filter = "AND source = %s"
            params: list = [source, limit]
        else:
            source_filter = ""
            params = [limit]

        with self._db.cursor() as cur:
            cur.execute(
                f"""
                UPDATE crawl_queue
                SET status = 'processing', updated_at = NOW()
                WHERE id IN (
                    SELECT id FROM crawl_queue
                    WHERE status = 'pending'
                    {source_filter}
                    ORDER BY id
                    LIMIT %s
                    FOR UPDATE SKIP LOCKED
                )
                RETURNING id, url, source
                """,
                params,
            )
            rows = cur.fetchall()

        return [dict(r) for r in rows]

    def count(self, status: Optional[str] = None, source: Optional[str] = None) -> int:
        conditions: list[str] = []
        params: list = []
        if status:
            conditions.append("status = %s")
            params.append(status)
        if source:
            conditions.append("source = %s")
            params.append(source)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        with self._db.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS n FROM crawl_queue {where}", params)
            row = cur.fetchone()

        return int(row["n"]) if row else 0


class VacancyRepo:
    def __init__(self, db: PostgresDB):
        self._db = db

    def upsert(self, vacancy: dict) -> bool:
        _validate(vacancy, required=("vacancy_id", "source"))

        with self._db.cursor() as cur:
            cur.execute(
                """
                INSERT INTO vacancies (
                    vacancy_id, source, title, company_name, location,
                    salary_from, salary_to, currency, description,
                    remote, published_at, needs_review, review_reasons,
                    created_at, updated_at
                ) VALUES (
                    %(vacancy_id)s, %(source)s, %(title)s, %(company_name)s, %(location)s,
                    %(salary_from)s, %(salary_to)s, %(currency)s, %(description)s,
                    %(remote)s, %(published_at)s, %(needs_review)s, %(review_reasons)s,
                    NOW(), NOW()
                )
                ON CONFLICT (vacancy_id, source) DO UPDATE SET
                    title          = EXCLUDED.title,
                    company_name   = EXCLUDED.company_name,
                    location       = EXCLUDED.location,
                    salary_from    = EXCLUDED.salary_from,
                    salary_to      = EXCLUDED.salary_to,
                    currency       = EXCLUDED.currency,
                    description    = EXCLUDED.description,
                    remote         = EXCLUDED.remote,
                    published_at   = EXCLUDED.published_at,
                    needs_review   = EXCLUDED.needs_review,
                    review_reasons = EXCLUDED.review_reasons,
                    updated_at     = NOW()
                """,
                {
                    "vacancy_id": vacancy.get("vacancy_id"),
                    "source": vacancy.get("source"),
                    "title": vacancy.get("title"),
                    "company_name": vacancy.get("company_name"),
                    "location": vacancy.get("location"),
                    "salary_from": vacancy.get("salary_from"),
                    "salary_to": vacancy.get("salary_to"),
                    "currency": vacancy.get("currency"),
                    "description": vacancy.get("description"),
                    "remote": vacancy.get("remote"),
                    "published_at": vacancy.get("published_at"),
                    "needs_review": vacancy.get("needs_review", False),
                    "review_reasons": vacancy.get("review_reasons", None),
                },
            )
            inserted = cur.rowcount == 1

        flag = " ⚑ needs_review" if vacancy.get("needs_review") else ""
        print(f"  [vacancies] upsert: {vacancy.get('vacancy_id')} [{vacancy.get('source')}]{flag}")
        return inserted

    def find_by_source(self, source: str, limit: int = 10000) -> list[dict]:
        with self._db.cursor() as cur:
            cur.execute(
                "SELECT * FROM vacancies WHERE source = %s LIMIT %s",
                (source, limit),
            )
            return [dict(r) for r in cur.fetchall()]


def _validate(doc: dict, required: tuple) -> None:
    missing = [k for k in required if k not in doc or doc[k] is None]
    if missing:
        raise ValueError(f"Vacancy missing required fields: {missing}")
