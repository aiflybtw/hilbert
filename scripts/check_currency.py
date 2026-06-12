"""check_currency.py — Currency validation and export."""
import os, sys
from collections import defaultdict

import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
DATA = os.path.join(BASE, "..", "data")


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()

    print("[currency] Reading vacancies...")
    cur.execute("""
        SELECT currency, salary_from, salary_to, salary_from_rub, salary_to_rub
        FROM vacancies
        WHERE salary_from IS NOT NULL OR salary_to IS NOT NULL
    """)
    rows = cur.fetchall()
    print(f"[currency] {len(rows)} vacancies with salary data")

    # Stats by currency
    currency_counts = defaultdict(int)
    currency_ranges = defaultdict(lambda: {"min": float("inf"), "max": float("-inf")})
    null_currency = 0
    converted_to_rub = 0

    for r in rows:
        cur_val, sfr, sto, sfr_rub, sto_rub = r
        if cur_val is None:
            null_currency += 1
        else:
            currency_counts[cur_val] += 1
            for val in [sfr, sto]:
                if val is not None:
                    fval = float(val)
                    if fval < currency_ranges[cur_val]["min"]:
                        currency_ranges[cur_val]["min"] = fval
                    if fval > currency_ranges[cur_val]["max"]:
                        currency_ranges[cur_val]["max"] = fval

        if sfr_rub is not None or sto_rub is not None:
            converted_to_rub += 1

    # Build report
    lines = []
    lines.append("=" * 60)
    lines.append("CURRENCY REPORT")
    lines.append("=" * 60)
    lines.append(f"Total vacancies with salary data: {len(rows)}")
    lines.append(f"Vacancies with NULL currency:     {null_currency}")
    lines.append(f"Vacancies converted to RUB:       {converted_to_rub}")
    lines.append("")
    lines.append("Currency distribution:")
    lines.append(f"  {'Currency':<12} {'Count':<8} {'Salary Range':<30}")
    lines.append(f"  {'-'*12} {'-'*8} {'-'*30}")
    for cur_val in sorted(currency_counts.keys()):
        cnt = currency_counts[cur_val]
        rng = currency_ranges[cur_val]
        if rng["min"] == float("inf"):
            range_str = "N/A"
        else:
            range_str = f"{rng['min']:,.0f} - {rng['max']:,.0f}"
        lines.append(f"  {cur_val:<12} {cnt:<8} {range_str:<30}")
    lines.append("")

    report = "\n".join(lines)
    print("\n" + report)

    path = os.path.join(DATA, "currency_report.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print(f"[currency] Report saved: {path}")

    cur.close()
    conn.close()
    print("[currency] Done.")


if __name__ == "__main__":
    main()
