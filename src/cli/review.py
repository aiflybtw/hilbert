"""Export all vacancies to CSV or XLSX."""

from __future__ import annotations

import argparse

import pandas as pd
from sqlalchemy import create_engine

from src.config import config


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Export vacancies to CSV/XLSX")
    p.add_argument("--dsn", default=None, help="PostgreSQL DSN")
    p.add_argument("--format", choices=["csv", "xlsx"], default="csv", help="Output format")
    p.add_argument("--output", default=None, help="Output file name")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    dsn = args.dsn or config.db_dsn

    output = args.output or f"vacancies.{args.format}"
    engine = create_engine(dsn)
    df = pd.read_sql(
        "SELECT id, vacancy_id, source, title, company_name, location, "
        "salary_from, salary_to, currency, description, remote, published_at, "
        "created_at, updated_at, needs_review, review_reasons "
        "FROM vacancies ORDER BY source, id",
        engine,
    )

    for col in df.select_dtypes(include="datetimetz"):
        df[col] = df[col].dt.tz_localize(None)

    if args.format == "csv":
        df.to_csv(output, index=False)
    else:
        df.to_excel(output, index=False)

    print(f"Exported {len(df)} vacancies to {output}")


if __name__ == "__main__":
    main()
