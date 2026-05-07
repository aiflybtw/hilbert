from __future__ import annotations

import time
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from src.base_crawler import BaseCrawler
from src.db import PostgresDB, CrawlQueueRepo
from src.session import StealthSession


class HabrCrawler(BaseCrawler):
    SOURCE = "habr"
    BASE_URL = "https://career.habr.com/vacancies"

    def __init__(
        self,
        session: StealthSession,
        queue: CrawlQueueRepo,
        text: str = "DevOps",
        specializations: list[str] | None = None,
        delay: float = 1.5,
    ):
        super().__init__(session, queue, delay)
        self.text = text
        self.specializations = specializations or []

    def run(self) -> None:
        page = 1
        while True:
            url = self._build_url(page)
            print(f"Fetching page {page}: {url}")
            try:
                resp = self.session.get(url)
            except Exception as e:
                print(f"Request failed: {e}")
                break

            if resp.status_code == 404:
                print("Reached end (404). Stopping.")
                break

            links = self._extract_links(resp.text)
            if not links:
                print("No links found, stopping.")
                break

            self.queue.push_urls(links, source=self.SOURCE)
            page += 1
            time.sleep(self.delay)

    def _build_url(self, page: int) -> str:
        params: dict = {"q": self.text, "page": page, "type": "all"}
        for spec in self.specializations:
            params.setdefault("specialization[]", [])
            params["specialization[]"].append(spec)
        return f"{self.BASE_URL}?{urlencode(params, doseq=True)}"

    def _extract_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        raw_links = [
            a.get("href")
            for a in soup.select("a.vacancy-card__title-link")
            if a.get("href")
        ]
        if not raw_links:
            raw_links = [
                a.get("href")
                for a in soup.select('[class*="vacancy-card"] a[href*="/vacancies/"]')
                if a.get("href")
            ]
        return list({self._clean_url(link, "https://career.habr.com") for link in raw_links})


if __name__ == "__main__":
    from src.config import config

    db = PostgresDB(config.db_dsn)
    queue = CrawlQueueRepo(db)
    crawler = HabrCrawler(StealthSession(referer="https://career.habr.com/"), queue, text="DevOps")
    crawler.run()
    db.close()
