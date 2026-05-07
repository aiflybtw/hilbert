from __future__ import annotations

import argparse

import pandas as pd
from sqlalchemy import create_engine

from src.config import config


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Export vacancies to Excel"
    )
    p.add_argument("--dsn", default=None, help="PostgreSQL DSN")
    p.add_argument("--source", default="telegram", help="Source filter (default: telegram)")
    p.add_argument("--output", default="telegram_vacancies.xlsx", help="Output file name")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    dsn = args.dsn or config.db_dsn

    engine = create_engine(dsn)
    query = f"""
    SELECT vacancy_id, title, salary_from, salary_to, currency,
           location, remote, company_name, description
    FROM vacancies
    WHERE source = '{args.source}';
    """

    df = pd.read_sql(query, engine)
    df.to_excel(args.output, index=False)
    print(f"File saved to {args.output}")


if __name__ == "__main__":
    main()
