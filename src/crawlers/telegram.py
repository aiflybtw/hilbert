from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.tl.types import Message

from src.config import config
from src.db import PostgresDB, VacancyRepo


class TelegramCrawler:
    SOURCE = "telegram"

    def __init__(
        self,
        vacancies: VacancyRepo,
        channel: str,
        max_age_days: int = 30,
        batch_size: int = 100,
    ):
        self.vacancies = vacancies
        self.channel = channel
        self.max_age_days = max_age_days
        self.batch_size = batch_size
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    def run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        async with TelegramClient(config.tg_session_file, config.tg_api_id, config.tg_api_hash) as client:
            print(f"[telegram] crawling @{self.channel}, cutoff={self._cutoff.date()}")
            await self._collect(client)

    async def _collect(self, client: TelegramClient) -> None:
        saved = 0
        offset_id = 0

        while True:
            messages: list[Message] = await client.get_messages(
                self.channel,
                limit=self.batch_size,
                offset_id=offset_id,
            )

            if not messages:
                print("[telegram] No more messages.")
                break

            stop = False
            for msg in messages:
                if msg.date < self._cutoff:
                    print(f"[telegram] Reached posts older than {self.max_age_days} days. Stopping.")
                    stop = True
                    break

                text = msg.message or ""
                low = text.lower()
                if "#резюме" in low or "#resume" in low:
                    continue
                if "#vacancy" not in low and "#вакансия" not in low:
                    continue

                vacancy = _vacancy_from_message(text, msg.id, msg.date)
                self.vacancies.upsert(vacancy)
                saved += 1

            if stop or len(messages) < self.batch_size:
                break

            offset_id = messages[-1].id

        print(f"[telegram] Done. Vacancies upserted: {saved}")


def _vacancy_from_message(text: str, msg_id: int, date: datetime) -> dict:
    return {
        "vacancy_id": str(msg_id),
        "source": "telegram",
        "description": text,
        "published_at": date if date.tzinfo else date.replace(tzinfo=timezone.utc),
        "needs_review": True,
        "review_reasons": "raw — needs NER extraction",
    }


if __name__ == "__main__":
    db = PostgresDB(config.db_dsn)
    vacancies = VacancyRepo(db)

    crawler = TelegramCrawler(
        vacancies=vacancies,
        channel=config.tg_channels[0] if config.tg_channels else "devops_jobs",
        max_age_days=config.tg_max_age_days,
    )
    crawler.run()
    db.close()
