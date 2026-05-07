from __future__ import annotations

import argparse
import re
import unicodedata
from html import unescape

from bs4 import BeautifulSoup

from src.db import PostgresDB


DDL_ALTER = """
ALTER TABLE vacancies
    ADD COLUMN IF NOT EXISTS description_raw TEXT;
"""


class DescriptionCleaner:
    _JUNK_LINE_RE = re.compile(
        r"^[\s\-─━═■□▪▸►•*~=_|/\\,.;:!?@#$%^&*()\[\]{}<>«»""''`]+$"
    )

    _MULTI_BLANK_RE = re.compile(r"\n{3,}")

    _REPEAT_PUNCT_RE = re.compile(r"([!?]){2,}")
    _REPEAT_DOT_RE = re.compile(r"\.{4,}")

    _CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    def clean(self, raw: str | None) -> str | None:
        if not raw or not raw.strip():
            return None

        text = raw

        text = unescape(text)
        text = self._strip_html(text)
        text = unescape(text)
        text = self._CONTROL_RE.sub("", text)
        text = unicodedata.normalize("NFKC", text)
        text = self._REPEAT_PUNCT_RE.sub(r"\1", text)
        text = self._REPEAT_DOT_RE.sub("...", text)

        lines = text.splitlines()
        lines = [self._clean_line(line) for line in lines]
        lines = [l for l in lines if not self._is_junk_line(l)]

        text = "\n".join(lines)
        text = self._MULTI_BLANK_RE.sub("\n\n", text)
        text = text.strip()

        return text if text else None

    def _strip_html(self, html: str) -> str:
        soup = BeautifulSoup(html, "lxml")

        for tag in soup.find_all(["p", "div", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6"]):
            tag.insert_before("\n")
            tag.insert_after("\n")

        for tag in soup.find_all("li"):
            tag.insert_before("\n• ")
            tag.insert_after("\n")

        return soup.get_text(separator="")

    def _clean_line(self, line: str) -> str:
        return line.rstrip()

    def _is_junk_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped:
            return False
        if len(stripped) <= 2:
            return True
        return bool(self._JUNK_LINE_RE.match(stripped))


class DescriptionProcessor:
    def __init__(
        self,
        db: PostgresDB,
        cleaner: DescriptionCleaner,
        batch_size: int = 100,
        source: str | None = None,
        dry_run: bool = False,
    ):
        self._db = db
        self._cleaner = cleaner
        self._batch_size = batch_size
        self._source = source
        self._dry_run = dry_run

    def run(self) -> None:
        self._apply_ddl()

        total = self._count()
        processed = 0
        changed = 0
        empty = 0
        offset = 0

        print(f"[cleaner] Total vacancies to process: {total}")
        if self._dry_run:
            print("[cleaner] DRY RUN — БД не изменяется")

        while True:
            rows = self._fetch_batch(offset)
            if not rows:
                break

            for row in rows:
                result = self._process_row(row)
                if result == "changed":
                    changed += 1
                elif result == "empty":
                    empty += 1
                processed += 1

            offset += self._batch_size
            print(f"  [{processed}/{total}] changed={changed} empty={empty}")

        print(f"\n── РЕЗУЛЬТАТ ────────────────────────────────────────────")
        print(f"  Обработано:              {processed}")
        print(f"  Описание изменилось:     {changed}")
        print(f"  Описание стало пустым:   {empty}")
        print(f"  Без изменений:           {processed - changed - empty}")
        if self._dry_run:
            print("  (dry-run, БД не изменялась)")

    def _apply_ddl(self) -> None:
        with self._db.cursor() as cur:
            cur.execute(DDL_ALTER)
        print("[cleaner] Column description_raw ensured")

    def _count(self) -> int:
        source_filter = "WHERE source = %s" if self._source else ""
        params = [self._source] if self._source else []
        with self._db.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) AS n FROM vacancies {source_filter}", params
            )
            return cur.fetchone()["n"]

    def _fetch_batch(self, offset: int) -> list[dict]:
        source_filter = "AND source = %s" if self._source else ""
        params: list = []
        if self._source:
            params.append(self._source)
        params += [self._batch_size, offset]

        with self._db.cursor() as cur:
            cur.execute(
                f"""
                SELECT id, vacancy_id, source, description
                FROM vacancies
                WHERE description IS NOT NULL
                {source_filter}
                ORDER BY id
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return [dict(r) for r in cur.fetchall()]

    def _process_row(self, row: dict) -> str:
        original = row["description"]
        cleaned = self._cleaner.clean(original)

        if cleaned == original:
            return "unchanged"

        if not self._dry_run:
            self._save(row["id"], original, cleaned)

        if cleaned is None:
            return "empty"
        return "changed"

    def _save(self, row_id: int, original: str, cleaned: str | None) -> None:
        with self._db.cursor() as cur:
            cur.execute(
                """
                UPDATE vacancies
                SET
                    description     = %s,
                    description_raw = COALESCE(description_raw, %s),
                    updated_at      = NOW()
                WHERE id = %s
                """,
                (cleaned, original, row_id),
            )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Очистка описаний вакансий от HTML-артефактов"
    )
    p.add_argument("--dsn", default=None, help="PostgreSQL DSN")
    p.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Количество вакансий за один проход (default: 100)",
    )
    p.add_argument(
        "--source",
        choices=["hh", "habr"],
        default=None,
        help="Обработать только один источник",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Показать статистику без записи в БД",
    )
    return p.parse_args()


def main() -> None:
    from src.config import config

    args = parse_args()
    dsn = args.dsn or config.db_dsn
    db = PostgresDB(dsn)
    cleaner = DescriptionCleaner()

    processor = DescriptionProcessor(
        db=db,
        cleaner=cleaner,
        batch_size=args.batch_size,
        source=args.source,
        dry_run=args.dry_run,
    )

    processor.run()
    db.close()


if __name__ == "__main__":
    main()
