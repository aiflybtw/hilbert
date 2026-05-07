from __future__ import annotations

import time
from urllib.parse import urlencode

import browser_cookie3
from bs4 import BeautifulSoup

from src.base_crawler import BaseCrawler
from src.db import PostgresDB, CrawlQueueRepo
from src.session import StealthSession


class HHCrawler(BaseCrawler):
    SOURCE = "hh"
    BASE_URL = "https://hh.ru/search/vacancy"

    def __init__(
        self,
        session: StealthSession,
        queue: CrawlQueueRepo,
        text: str = "DevOps",
        area: int | None = None,
        delay: float = 1.5,
    ):
        super().__init__(session, queue, delay)
        self.text = text
        self.area = area

    def run(self) -> None:
        page = 0
        while True:
            params: dict = {
                "hhtmFrom": "main",
                "hhtmFromLabel": "vacancy_search_line",
                "search_field": ["name", "company_name", "description"],
                "enable_snippets": "false",
                "L_save_area": "true",
                "text": self.text,
                "items_on_page": 20,
                "page": page,
            }
            if self.area:
                params["area"] = self.area

            query = urlencode(params, doseq=True)
            url = f"{self.BASE_URL}?{query}"
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

    def _extract_links(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        raw_links = [
            a.get("href")
            for a in soup.select('a[data-qa="serp-item__title"]')
            if a.get("href")
        ]
        return list({self._clean_url(link, "https://hh.ru") for link in raw_links})


if __name__ == "__main__":
    from src.config import config

    db = PostgresDB(config.db_dsn)
    queue = CrawlQueueRepo(db)

    cookies = browser_cookie3.chrome(domain_name=".hh.ru")
    session = StealthSession(referer="https://hh.ru/", cookies=dict(cookies))

    crawler = HHCrawler(session, queue, text="DevOps")
    crawler.run()
    db.close()
