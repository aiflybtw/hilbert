from __future__ import annotations

import argparse
import time

from src.config import config
from src.db import PostgresDB, CrawlQueueRepo, VacancyRepo, QueueStatus
from src.session import StealthSession
import browser_cookie3

from src.crawlers.hh import HHCrawler
from src.crawlers.habr import HabrCrawler
from src.crawlers.telegram import TelegramCrawler
from src.parsers.hh import HHParser
from src.parsers.habr import HabrParser


class Orchestrator:
    def __init__(
        self,
        dsn: str | None = None,
        queries: list[str] | None = None,
        sources: list[str] | None = None,
        crawl_only: bool = False,
        parse_only: bool = False,
    ):
        self.queries = queries if queries is not None else config.search_queries
        self.sources = sources if sources is not None else config.default_sources
        self.crawl_only = crawl_only
        self.parse_only = parse_only
        self.dsn = dsn or config.db_dsn

        self.db = PostgresDB(dsn=self.dsn)
        self.queue = CrawlQueueRepo(self.db)
        self.vacancies = VacancyRepo(self.db)

    def run(self) -> None:
        print(f"\n{'='*60}")
        print(f"  Job crawler")
        print(f"  Queries : {self.queries}")
        print(f"  Sources : {self.sources}")
        print(f"{'='*60}\n")

        try:
            if not self.parse_only:
                self._run_crawlers()
            if not self.crawl_only:
                self._run_parsers()
        finally:
            self._print_stats()
            self.db.close()

    def _run_crawlers(self) -> None:
        print("── CRAWLING ─────────────────────────────────────────────")
        total_queries = len(self.queries)

        for i, query in enumerate(self.queries, 1):
            print(f"\n[{i}/{total_queries}] Query: {query!r}")

            if "hh" in self.sources:
                print("  [hh] crawling...")
                try:
                    cookies = browser_cookie3.chrome(domain_name=".hh.ru")
                    hh_session = StealthSession(referer="https://hh.ru/", cookies=dict(cookies))
                except Exception:
                    print("  [hh] Could not load Chrome cookies, using bare session")
                    hh_session = StealthSession()
                HHCrawler(hh_session, self.queue, text=query, delay=config.crawl_delay).run()

            if "habr" in self.sources:
                print("  [habr] crawling...")
                HabrCrawler(
                    StealthSession(referer="https://career.habr.com/"),
                    self.queue, text=query, delay=config.crawl_delay,
                ).run()

            if i < total_queries:
                print(f"  Sleeping {config.inter_query_delay}s before next query...")
                time.sleep(config.inter_query_delay)

        if "telegram" in self.sources:
            print(f"\n── TELEGRAM ({'  '.join('@' + c for c in config.tg_channels)}) ──")
            for channel in config.tg_channels:
                print(f"\n  [telegram] @{channel} → vacancies ...")
                TelegramCrawler(
                    vacancies=self.vacancies,
                    channel=channel,
                    max_age_days=config.tg_max_age_days,
                ).run()

        pending = self.queue.count(status=QueueStatus.PENDING)
        print(f"\nCrawling done. Pending URLs in queue (hh/habr): {pending}")

    def _run_parsers(self) -> None:
        print("\n── PARSING (hh / habr) ──────────────────────────────────")

        if "hh" in self.sources:
            print("\n[hh] Starting parser...")
            HHParser(
                StealthSession(), self.queue, self.vacancies,
                delay=config.parse_delay, batch_size=config.batch_size,
            ).run()

        if "habr" in self.sources:
            print("\n[habr] Starting parser...")
            HabrParser(
                StealthSession(referer="https://career.habr.com/"),
                self.queue, self.vacancies,
                delay=config.parse_delay, batch_size=config.batch_size,
            ).run()

    def _print_stats(self) -> None:
        print("\n── STATS ────────────────────────────────────────────────")
        for source in self.sources:
            saved = len(self.vacancies.find_by_source(source))
            if source == "telegram":
                print(f"  [telegram] vacancies saved={saved}")
            else:
                pending = self.queue.count(status=QueueStatus.PENDING, source=source)
                processing = self.queue.count(status=QueueStatus.PROCESSING, source=source)
                done = self.queue.count(status=QueueStatus.DONE, source=source)
                error = self.queue.count(status=QueueStatus.ERROR, source=source)
                print(
                    f"  [{source}] queue: pending={pending} processing={processing} "
                    f"done={done} error={error} | vacancies saved={saved}"
                )
        print()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Job vacancy crawler + parser (PostgreSQL)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Запросы по умолчанию:\n  " + "\n  ".join(f"- {q}" for q in config.search_queries),
    )
    p.add_argument("--query", help="Один поисковый запрос.")
    p.add_argument("--queries", nargs="+", metavar="QUERY",
                   help='Несколько запросов: --queries "DevOps" "SRE"')
    p.add_argument("--sources", nargs="+", default=config.default_sources,
                   choices=["hh", "habr", "telegram"])
    p.add_argument("--dsn", default=None)
    p.add_argument("--crawl-only", action="store_true")
    p.add_argument("--parse-only", action="store_true")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    if args.queries:
        queries = args.queries
    elif args.query:
        queries = [args.query]
    else:
        queries = None

    Orchestrator(
        dsn=args.dsn,
        queries=queries,
        sources=args.sources,
        crawl_only=args.crawl_only,
        parse_only=args.parse_only,
    ).run()


if __name__ == "__main__":
    main()
