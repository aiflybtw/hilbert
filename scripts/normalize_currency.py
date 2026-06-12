"""normalize_currency.py — Currency conversion to RUB via CBR API + heuristics for Telegram."""
import json, os, re, sys, xml.etree.ElementTree as ET
from datetime import datetime, timezone
from decimal import Decimal
import requests, psycopg2

BASE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(BASE, ".."))
from src.config import config

DB_DSN = config.db_dsn
CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
MONTHLY_THRESHOLD = 10_000  # below = hourly
YEARLY_THRESHOLD = 2_000_000  # above = yearly
HOURS_PER_MONTH = 160
MONTHS_PER_YEAR = 12

CURRENCY_ALIASES = {
    "rub": "RUB", "rur": "RUB", "руб": "RUB", "рублей": "RUB",
    "usd": "USD", "usd.": "USD", "долл": "USD", "долларов": "USD", "$": "USD",
    "eur": "EUR", "euro": "EUR", "евро": "EUR", "€": "EUR",
    "kzt": "KZT", "тенге": "KZT", "тг": "KZT",
    "gbp": "GBP", "фунт": "GBP", "£": "GBP",
    "cny": "CNY", "юань": "CNY", "¥": "CNY",
    "try": "TRY", "lira": "TRY", "tl": "TRY", "лир": "TRY",
    "uah": "UAH", "гривна": "UAH", "₴": "UAH",
    "byn": "BYN", "бел": "BYN", "br": "BYN",
    "uzs": "UZS", "сум": "UZS",
    "gel": "GEL", "лари": "GEL",
    "amd": "AMD", "драм": "AMD",
    "azn": "AZN", "манат": "AZN",
}

CURRENCY_PATTERN = re.compile(
    r'(?:(?P<amount>[\d\s]+)\s*(?P<currency>usd|eur|rub|kzt|gbp|cny|try|uah|byn|'
    r'uzs|gel|amd|azn|\$|€|£|¥|₴|тг|руб|долл|евро|тенге|фунт|юань|лир|гривна|'
    r'бел|сум|лари|драм|манат))'
    r'|(?:(?P<currency2>\$|€|£|¥)\s*(?P<amount2>[\d\s]+))',
    re.IGNORECASE,
)

LLM_CURRENCY_PROMPT = """Определи валюту зарплаты по тексту вакансии.
Если в тексте прямо не указана валюта, определи по расположению офиса или другим косвенным признакам.
Ответь ТОЛЬКО кодом валюты: RUB, USD, EUR, KZT, GBP, CNY, TRY, UAH, BYN, UZS, GEL, AMD, AZN.
Если определить невозможно — ответь NULL.
"""


def fetch_cbr_rates():
    resp = requests.get(CBR_URL, timeout=10)
    resp.encoding = "windows-1251"
    root = ET.fromstring(resp.text)
    rates = {"RUB": Decimal("1")}
    for valute in root.findall("Valute"):
        code = valute.find("CharCode").text
        nominal = Decimal(valute.find("Nominal").text.replace(",", "."))
        value = Decimal(valute.find("Vuale").text.replace(",", "."))
        rates[code] = value / nominal
    return rates, root.attrib.get("Date", "")


def normalize(vacancy_id, sfr, sto, currency, description, location):
    if currency:
        currency = CURRENCY_ALIASES.get(currency.lower().strip(), currency.upper())
    else:
        currency = guess_currency_from_text(description)
    if not currency:
        currency = guess_currency_from_location(location)
    if not currency:
        return None, None, None
    
    sfr = float(sfr) if sfr else None
    sto = float(sto) if sto else None
    
    mid = (sfr or sto or 0)
    if mid < MONTHLY_THRESHOLD:
        if sfr: sfr *= HOURS_PER_MONTH
        if sto: sto *= HOURS_PER_MONTH
    elif mid > YEARLY_THRESHOLD:
        if sfr: sfr /= MONTHS_PER_YEAR
        if sto: sto /= MONTHS_PER_YEAR
    
    return sfr, sto, currency


def guess_currency_from_text(text):
    if not text: return None
    for m in CURRENCY_PATTERN.finditer(text):
        cur = m.group("currency") or m.group("currency2")
        if cur:
            cur = CURRENCY_ALIASES.get(cur.lower().strip(), cur.upper())
            if cur != "RUB":
                return cur
    return None


def guess_currency_from_location(location):
    if not location: return None
    loc_lower = location.lower()
    if any(x in loc_lower for x in ["москва", "россия", "санкт-петербург", "казань", "новосибирск"]):
        return "RUB"
    if any(x in loc_lower for x in ["алматы", "астана", "нур-султан", "казахстан"]):
        return "KZT"
    if any(x in loc_lower for x in ["минск", "беларусь"]):
        return "BYN"
    if any(x in loc_lower for x in ["ташкент", "узбекистан"]):
        return "UZS"
    if any(x in loc_lower for x in ["тбилиси", "грузия"]):
        return "GEL"
    return None


def main():
    rates, date_str = fetch_cbr_rates()
    print(f"[currency] CBR rates loaded ({date_str}): {len(rates)} currencies")
    
    conn = psycopg2.connect(DB_DSN)
    cur = conn.cursor()
    cur.execute("SELECT vacancy_id, salary_from, salary_to, currency, description, location FROM vacancies WHERE (salary_from IS NOT NULL OR salary_to IS NOT NULL)")
    rows = cur.fetchall()
    print(f"[currency] Processing {len(rows)} vacancies...")
    
    updated = 0
    for r in rows:
        vid, sfr, sto, currency, desc, loc = r
        sfr_f, sto_f, cur = normalize(vid, sfr, sto, currency, desc, loc)
        if sfr_f is None and sto_f is None:
            continue
        if cur and cur != "RUB":
            rate = rates.get(cur)
            if rate:
                if sfr_f: sfr_f = float(Decimal(str(sfr_f)) / rate)
                if sto_f: sto_f = float(Decimal(str(sto_f)) / rate)
        cur.execute(
            "UPDATE vacancies SET salary_from_rub = %s, salary_to_rub = %s, currency = %s WHERE vacancy_id = %s",
            (sfr_f, sto_f, cur, vid),
        )
        updated += 1
        if updated % 100 == 0:
            print(f"[currency] {updated}/{len(rows)} updated")
    
    conn.commit()
    cur.close()
    conn.close()
    print(f"[currency] Done. {updated} vacancies updated.")


if __name__ == "__main__":
    main()
