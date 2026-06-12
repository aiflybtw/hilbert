"""
llm_parser.py — LLM-based extraction from raw Telegram vacancies.

Reads vacancies WHERE source='telegram' AND needs_review=TRUE,
calls DeepSeek API to extract structured fields,
and updates the DB rows.

Usage:
    python -m src.features.llm_parser                    # real run
    python -m src.features.llm_parser --dry-run           # preview only
    python -m src.features.llm_parser --limit 5           # process 5 vacancies
    python -m src.features.llm_parser --limit 3 --dry-run # preview 3
"""

from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from src.cleaners.description import TelegramCleaner
from src.db import PostgresDB, VacancyRepo
from src.features.deepseek_client import call_deepseek
from src.features.prompts import LLM_TELEGRAM_PARSE_PROMPT


class TelegramLLMParser:
    def __init__(
        self,
        db: PostgresDB,
        model: str = "deepseek-v4-flash",
        dry_run: bool = False,
        limit: int = 0,
    ):
        self.db = db
        self.vacancies = VacancyRepo(db)
        self.cleaner = TelegramCleaner()
        self.model = model
        self.dry_run = dry_run
        self.limit = limit

    def run(self) -> None:
        print(f"[llm_parser] Model: {self.model}")
        if self.dry_run:
            print("[llm_parser] DRY RUN — DB will NOT be updated")
        print()

        rows = self._fetch_raw()
        total = len(rows)
        print(f"[llm_parser] Fetched {total} vacancies\n")

        ok = 0
        fail = 0

        for i, row in enumerate(rows, 1):
            if self.limit and i > self.limit:
                break

            print(f"[{i}/{total}] id={row['id']} ...")

            cleaned = self.cleaner.clean(row["description"])
            if not cleaned:
                print("  SKIP — empty after cleaning")
                continue

            result = self._call_llm(cleaned)
            if result is None:
                fail += 1
                continue

            if not self.dry_run:
                self._update_vacancy(row["id"], result)

            ok += 1

        print(f"\n── DONE ────────────────────────────────────────")
        print(f"  OK:    {ok}")
        print(f"  FAIL:  {fail}")
        if self.dry_run:
            print("  (dry-run, nothing written to DB)")

    def _fetch_raw(self) -> list[dict]:
        with self.db.cursor() as cur:
            cur.execute(
                "SELECT id, vacancy_id, description "
                "FROM vacancies "
                "WHERE source = 'telegram' AND needs_review = TRUE "
                "ORDER BY RANDOM()"
            )
            return [dict(r) for r in cur.fetchall()]

    def _call_llm(self, text: str) -> dict[str, Any] | None:
        prompt = LLM_TELEGRAM_PARSE_PROMPT.replace("{text}", text)
        raw = call_deepseek(prompt, model=self.model)
        if raw is None:
            return None

        json_str = _extract_json(raw)
        if json_str is None:
            print(f"  FAIL — no JSON in response:\n{raw[:300]}")
            return None

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            print(f"  FAIL — JSON parse error: {e}")
            return None

        if self.dry_run:
            print(f"  [dry-run] extracted:")
            for k in ("title", "company_name", "salary_from", "salary_to", "currency", "remote", "location"):
                v = data.get(k)
                if v is not None:
                    print(f"    {k}: {v}")
            print()

        return data

    def _update_vacancy(self, row_id: int, data: dict) -> None:
        with self.db.cursor() as cur:
            cur.execute(
                """
                UPDATE vacancies SET
                    title          = COALESCE(%s, title),
                    company_name   = COALESCE(%s, company_name),
                    location       = COALESCE(%s, location),
                    salary_from    = COALESCE(%s, salary_from),
                    salary_to      = COALESCE(%s, salary_to),
                    currency       = COALESCE(%s, currency),
                    remote         = COALESCE(%s, remote),
                    description    = COALESCE(%s, description),
                    needs_review   = FALSE,
                    review_reasons = NULL,
                    updated_at     = NOW()
                WHERE id = %s
                """,
                (
                    data.get("title"),
                    data.get("company_name"),
                    data.get("location"),
                    data.get("salary_from"),
                    data.get("salary_to"),
                    data.get("currency"),
                    data.get("remote"),
                    data.get("description_clean"),
                    row_id,
                ),
            )


def _extract_json(raw: str) -> str | None:
    """Извлекает JSON из ответа LLM"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if m:
        return m.group(1)
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        return m.group(0)
    return None


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="LLM extraction for Telegram vacancies")
    p.add_argument("--dsn", default=None, help="PostgreSQL DSN")
    p.add_argument("--model", default="deepseek-v4-flash", help="LLM model (deepseek-v4-flash / deepseek-v4-pro)")
    p.add_argument("--dry-run", action="store_true", help="Preview only, no DB writes")
    p.add_argument("--limit", type=int, default=0, help="Process only N vacancies")
    return p.parse_args()


def main() -> None:
    from src.config import config

    args = parse_args()
    dsn = args.dsn or config.db_dsn
    db = PostgresDB(dsn)
    parser = TelegramLLMParser(
        db=db,
        model=args.model,
        dry_run=args.dry_run,
        limit=args.limit,
    )
    parser.run()
    db.close()


if __name__ == "__main__":
    main()
