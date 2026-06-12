"""deduplicate.py — Remove duplicate vacancies by (title, salary_from, salary_to, company_name)."""
import os, sys
import psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn


def main():
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    
    print("[dedup] Finding duplicates by (title, salary_from, salary_to, company_name)...")
    cur.execute("""
        DELETE FROM vacancies
        WHERE id IN (
            SELECT id FROM (
                SELECT id, ROW_NUMBER() OVER (
                    PARTITION BY lower(trim(title)), COALESCE(salary_from, 0), COALESCE(salary_to, 0), COALESCE(lower(trim(company_name)), '')
                    ORDER BY published_at DESC NULLS LAST, created_at DESC
                ) AS rn
                FROM vacancies
            ) sub
            WHERE rn > 1
        )
    """)
    deleted = cur.rowcount
    conn.commit()
    
    cur.execute("SELECT COUNT(*) FROM vacancies")
    remaining = cur.fetchone()[0]
    cur.close()
    conn.close()
    print(f"[dedup] Deleted {deleted} duplicates. Remaining: {remaining} vacancies.")


if __name__ == "__main__":
    main()
