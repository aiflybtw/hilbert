from __future__ import annotations

from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from src.db import CrawlQueueRepo
from src.session import StealthSession


class BaseCrawler:
    SOURCE: str = ""

    def __init__(self, session: StealthSession, queue: CrawlQueueRepo, delay: float = 1.5):
        self.session = session
        self.queue = queue
        self.delay = delay

    def run(self) -> None:
        raise NotImplementedError

    def _extract_links(self, html: str) -> list[str]:
        raise NotImplementedError

    @staticmethod
    def _clean_url(url: str, base: str) -> str:
        full = urljoin(base, url)
        parsed = urlparse(full)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
