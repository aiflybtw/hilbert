from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    db_dsn: str = os.getenv("DB_DSN", "postgresql://postgres@localhost:5432/hilbert")

    tg_api_id: int = int(os.getenv("TG_API_ID", "0"))
    tg_api_hash: str = os.getenv("TG_API_HASH", "")
    tg_session_file: str = os.getenv("TG_SESSION_FILE", "tg_session")

    search_queries: list[str] = field(default_factory=lambda: [
        "DevOps", "DevOps Engineer", "DevSecOps", "MLOps",
        "DataOps", "FinOps", "SRE", "Site Reliability Engineer",
    ])
    tg_channels: list[str] = field(default_factory=lambda: ["devops_jobs"])
    tg_max_age_days: int = 30
    crawl_delay: float = 1.5
    parse_delay: float = 1.0
    batch_size: int = 50
    inter_query_delay: float = 5.0
    default_sources: list[str] = field(default_factory=lambda: ["hh", "habr", "telegram"])


config = Config()
