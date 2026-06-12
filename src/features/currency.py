"""
currency.py — конвертация зарплаты в рубли и нормализация в месячные ставки.

Курсы: сначала ЦБ РФ API, при ошибке — fallback.
Если валюта не определена ни через JSON-LD/HTML, ни через текстовые маркеры —
вызывается LLM (DeepSeek) для редких/неизвестных валют.

Обработка почасовых ставок: эвристика - если значение для той или иной валюты слишком мало, то смотрится описание и из него выявялется, действительно ли это почасовая ставка. 
Если ставка действительно почасовая -  *160 (предпосылка: график 5/2 8часов -> 160 часов/месяц)
Обработка годовых стаовк: эвристика. Если ставка годовая - /12. 
"""

from __future__ import annotations

import re
from typing import Optional

import requests

from src.features.deepseek_client import call_deepseek


# ── синонимы валют ───────────────────────────────────────────────────────

CURRENCY_ALIASES = {
    "RUR": "RUB",
    "USDT": "USD",
    "SO'M": "UZS",
    "СУМ": "UZS",
    "SO`M": "UZS",
}

# ── fallback-курсы (если API ЦБ недоступен) ─────────────────────────────

FALLBACK_RATES: dict[str, float] = {
    "USD": 85.0,
    "EUR": 92.0,
    "AED": 23.0,
    "BYN": 27.0,
    "KZT": 0.17,
    "UZS": 0.0061,
    "USDT": 85.0,
}


def _fetch_cbr_rates() -> dict[str, float]:
    try:
        resp = requests.get("https://www.cbr-xml-daily.ru/daily_json.js", timeout=3)
        resp.raise_for_status()
        data = resp.json()
        rates = {}
        for code, info in data.get("Valute", {}).items():
            rates[code] = info["Value"] / info.get("Nominal", 1)
        return rates
    except Exception as e:
        print(f"[currency] CBR API failed: {e}")
        return {}


def _normalize_currency(currency: Optional[str]) -> Optional[str]:
    if not currency:
        return None
    c = currency.upper().strip()
    return CURRENCY_ALIASES.get(c, c)


_RATES_CACHE: dict[str, float] | None = None


def get_rate(target_currency: str) -> Optional[float]:
    c = _normalize_currency(target_currency)
    if not c or c == "RUB":
        return 1.0

    global _RATES_CACHE
    if _RATES_CACHE is None:
        _RATES_CACHE = _fetch_cbr_rates()

    if c in _RATES_CACHE:
        return _RATES_CACHE[c]

    if c in FALLBACK_RATES:
        return FALLBACK_RATES[c]

    return None


def infer_currency_from_text(text: Optional[str]) -> Optional[str]:
    """Определяет валюту по текстовым маркерам (знак $, слово 'евро' и т.д.)."""
    if not text:
        return None

    patterns = [
        (r"\$\s*\d|usd|доллар", "USD"),
        (r"€|eur|евро", "EUR"),
        (r"so'?m|сум[а-я]*\b", "UZS"),
        (r"тенге|₸|kzt", "KZT"),
        (r"дирхам|aed", "AED"),
        (r"usdt|usdc", "USDT"),
    ]

    for pattern, code in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return code
    return None


def _infer_currency_with_llm(
    salary_from: Optional[float],
    salary_to: Optional[float],
    description: Optional[str],
    location: Optional[str],
) -> Optional[str]:
    """
    Определяет валюту через DeepSeek, когда текстовые маркеры не сработали.
    Вызывается только для редких edge-кейсов.
    """
    snippet = (description or "")[:600]
    prompt = (
        "Определи валюту зарплаты по следующим данным. Ответь ТОЛЬКО кодом валюты (RUB, USD, EUR, KZT, UZS, AED, ...).\n"
        f"Зарплата: от {salary_from} до {salary_to}\n"
        f"Локация: {location or 'не указана'}\n"
        f"Описание: {snippet}\n\n"
        "Валюта:"
    )
    result = call_deepseek(prompt, model="deepseek-v4-flash")
    if result:
        result = result.strip().upper()[:4]
        if result and result in ("RUB", "USD", "EUR", "KZT", "UZS", "AED", "USDT", "GBP", "CNY", "UAH", "BYN", "GEL", "AMD", "AZN", "KGS", "TJS", "TRY", "INR"):
            return result
    return None


# ── детекция периода зарплаты (годовая / почасовая) ────────────────────

ANNUAL_PATTERNS: list[re.Pattern] = [
    re.compile(r"/\s*years?\b", re.I),
    re.compile(r"/\s*yrs?\b", re.I),
    re.compile(r"per\s+annum", re.I),
]

_HOURLY_SEP = r"(?:/|за|в)"
HOURLY_PATTERNS: list[re.Pattern] = [
    re.compile(
        r"(?:почасов|hourly|\d[\d\s]*(?:\(.*?\))?\s*(?:руб\.?|₽|\$|€|USD|EUR|KZT)\s*"
        + _HOURLY_SEP + r"\s*(?:час|hour|hr))",
        re.I,
    ),
]

_MAX_MONTHLY_THRESHOLDS: dict[str, float] = {
    "RUB": 30_000,
    "USD": 500,
    "EUR": 500,
    "KZT": 50_000,
    "UZS": 1_000_000,
    "AED": 2_000,
    "GBP": 500,
}


def _normalize_to_monthly(
    salary_from: Optional[float],
    salary_to: Optional[float],
    description: Optional[str],
    resolved_currency: Optional[str] = None,
) -> tuple[Optional[float], Optional[float], bool]:
    """
    Корректирует зарплату к месячному периоду:
    - годовая → /12
    - почасовая → ×160
    """
    if not (salary_from or salary_to) or not description:
        return salary_from, salary_to, False

    currency = resolved_currency or "RUB"
    max_val = max(
        (v for v in (salary_from, salary_to) if v is not None),
        default=0,
    )

    # ── годовая ──────────────────────────────────────────────────
    if any(p.search(description) for p in ANNUAL_PATTERNS):
        threshold = _MAX_MONTHLY_THRESHOLDS.get(currency, 25_000) * 12 * 1.5
        if max_val >= threshold:
            sf = float(salary_from) / 12 if salary_from is not None else None
            st = float(salary_to) / 12 if salary_to is not None else None
            print(f"[currency] Annual salary — /12: "
                  f"{salary_from or ''} {currency} -> {sf or ''} {currency}")
            return sf, st, True

    # ── почасовая ─────────────────────────────────────────────────
    # Эвристика: если значение подозрительно маленькое для валюты ИЛИ есть паттерны почасовой оплаты
    is_hourly = any(p.search(description) for p in HOURLY_PATTERNS)
    
    threshold = _MAX_MONTHLY_THRESHOLDS.get(currency, 30_000)
    
    # Чтобы не умножать на 160 обычные зарплаты в рублях (напр. 60000), 
    # которые выше порога, но попали под паттерны, или наоборот.
    if max_val < threshold:
        is_hourly = True
    elif max_val > threshold * 2: # Если зарплата явно месячная/годовая
        is_hourly = False

    if is_hourly:
        sf = float(salary_from) * 160 if salary_from is not None else None
        st = float(salary_to) * 160 if salary_to is not None else None
        print(f"[currency] Hourly rate — ×160: "
              f"{salary_from or ''} {currency} -> {sf or ''} {currency}")
        return sf, st, True

    return salary_from, salary_to, False


def to_rub(
    salary_from: Optional[float],
    salary_to: Optional[float],
    currency: Optional[str],
    description: Optional[str] = None,
    location: Optional[str] = None,
) -> tuple[Optional[float], Optional[float], Optional[str]]:
    """
    Конвертирует зарплату в рубли.

    Returns: (salary_from_rub, salary_to_rub, "RUB" | код валюты)
    """
    if salary_from is None and salary_to is None:
        return None, None, None

    resolved = _normalize_currency(currency)

    if resolved is None:
        resolved = infer_currency_from_text(description)

    if resolved is None:
        resolved = _infer_currency_with_llm(salary_from, salary_to, description, location)

    salary_from, salary_to, _ = _normalize_to_monthly(salary_from, salary_to, description, resolved)

    if resolved is None or resolved == "RUB":
        return salary_from, salary_to, "RUB"

    rate = get_rate(resolved)
    if rate is None:
        print(f"[currency] Unknown currency: {resolved}, skipping conversion")
        return salary_from, salary_to, currency

    return (
        round(float(salary_from) * rate, 2) if salary_from is not None else None,
        round(float(salary_to) * rate, 2) if salary_to is not None else None,
        "RUB",
    )
