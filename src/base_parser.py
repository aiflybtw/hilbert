from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from src.db import CrawlQueueRepo, VacancyRepo, QueueStatus
from src.session import StealthSession


class BaseParser:
    SOURCE: str = ""

    def __init__(
        self,
        session: StealthSession,
        queue: CrawlQueueRepo,
        vacancies: VacancyRepo,
        delay: float = 1.0,
        batch_size: int = 50,
    ):
        self.session = session
        self.queue = queue
        self.vacancies = vacancies
        self.delay = delay
        self.batch_size = batch_size

    def run(self) -> None:
        while True:
            batch = self.queue.pull_pending(source=self.SOURCE, limit=self.batch_size)
            if not batch:
                print(f"[{self.SOURCE}] Queue empty, stopping parser.")
                break
            print(f"[{self.SOURCE}] Processing batch of {len(batch)} URLs")
            for item in batch:
                self._process(item["url"])
                time.sleep(self.delay)

    def _process(self, url: str) -> None:
        print(f"  Parsing: {url}")
        try:
            resp = self.session.get(url)
            vacancy = self._parse(resp.text, url)
            self.vacancies.upsert(vacancy)
            self.queue.set_status(url, QueueStatus.DONE)
        except Exception as e:
            print(f"  ERROR: {e}")
            self.queue.set_status(url, QueueStatus.ERROR, error=str(e))

    def _parse(self, html: str, url: str) -> dict:
        raise NotImplementedError

    # ── helpers ────────────────────────────────────────────────────────

    @staticmethod
    def extract_jsonld(soup: BeautifulSoup) -> dict:
        for tag in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(tag.string or "")
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    return data
                if isinstance(data, list):
                    for item in data:
                        if isinstance(item, dict) and item.get("@type") == "JobPosting":
                            return item
            except (json.JSONDecodeError, TypeError):
                continue
        return {}

    @staticmethod
    def vacancy_id_from_url(url: str, pattern: str) -> str:
        m = re.search(pattern, url)
        return m.group(1) if m else urlparse(url).path.rstrip("/").split("/")[-1]

    @staticmethod
    def text(soup: BeautifulSoup, selector: str) -> Optional[str]:
        el = soup.select_one(selector)
        return el.get_text(strip=True) if el else None

    @staticmethod
    def nested(d: dict, *keys: str) -> Optional[str]:
        for k in keys:
            if not isinstance(d, dict):
                return None
            d = d.get(k)
        return d if isinstance(d, str) else None

    @staticmethod
    def is_remote(ld: dict, soup: BeautifulSoup) -> bool:
        if ld.get("jobLocationType") == "TELECOMMUTE":
            return True
        return bool(soup.find(string=re.compile(r"удалённ|remote", re.I)))

    @staticmethod
    def parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    @staticmethod
    def parse_salary_jsonld(ld: dict) -> tuple[Optional[float], Optional[float], Optional[str]]:
        base = ld.get("baseSalary")
        if not isinstance(base, dict):
            return None, None, None
        value = base.get("value", {})
        currency = base.get("currency")
        if isinstance(value, dict):
            return BaseParser.to_float(value.get("minValue")), BaseParser.to_float(value.get("maxValue")), currency
        single = BaseParser.to_float(value)
        return single, single, currency

    @staticmethod
    def parse_salary_html(soup: BeautifulSoup, selector: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
        el = soup.select_one(selector)
        if not el:
            return None, None, None
        return BaseParser.parse_salary_text(el.get_text(" ", strip=True))

    @staticmethod
    def parse_salary_text(raw: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
        currency_map = {"₽": "RUB", "руб": "RUB", "$": "USD", "€": "EUR"}
        currency = next((code for sym, code in currency_map.items() if sym in raw), None)
        numbers = [
            float(n.replace(" ", "").replace("\xa0", ""))
            for n in re.findall(r"[\d\s\xa0]+", raw)
            if re.search(r"\d", n)
        ]
        if not numbers:
            return None, None, currency
        if "до" in raw and "от" not in raw:
            return None, numbers[0], currency
        if len(numbers) == 1:
            return numbers[0], None, currency
        return numbers[0], numbers[1], currency

    @staticmethod
    def to_float(value) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
