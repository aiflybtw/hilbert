from __future__ import annotations

from bs4 import BeautifulSoup

from src.base_parser import BaseParser
from src.db import PostgresDB, CrawlQueueRepo, VacancyRepo
from src.session import StealthSession


class HHParser(BaseParser):
    SOURCE = "hh"

    def _parse(self, html: str, url: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        ld = self.extract_jsonld(soup)
        vacancy_id = self.vacancy_id_from_url(url, pattern=r"/vacancy/(\d+)")

        salary_from, salary_to, currency = self.parse_salary_jsonld(ld)
        if salary_from is None and salary_to is None:
            salary_from, salary_to, currency = self.parse_salary_html(
                soup, selector='[data-qa="vacancy-salary"]'
            )

        return {
            "vacancy_id": vacancy_id,
            "source": self.SOURCE,
            "title": ld.get("title") or self.text(soup, '[data-qa="vacancy-title"]'),
            "company_name": (
                self.nested(ld, "hiringOrganization", "name")
                or self.text(soup, '[data-qa="vacancy-company-name"]')
            ),
            "location": (
                self.nested(ld, "jobLocation", "address", "addressLocality")
                or self.text(soup, '[data-qa="vacancy-view-location"]')
            ),
            "salary_from": salary_from,
            "salary_to": salary_to,
            "currency": currency,
            "description": ld.get("description") or self.text(soup, '[data-qa="vacancy-description"]'),
            "remote": self.is_remote(ld, soup),
            "published_at": self.parse_dt(ld.get("datePosted")),
        }


if __name__ == "__main__":
    from src.config import config

    db = PostgresDB(config.db_dsn)
    queue = CrawlQueueRepo(db)
    vacancies = VacancyRepo(db)

    parser = HHParser(StealthSession(), queue, vacancies)
    parser.run()
    db.close()
