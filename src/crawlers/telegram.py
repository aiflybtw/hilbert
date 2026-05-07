from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from telethon import TelegramClient
from telethon.tl.types import Message

from src.config import config
from src.db import PostgresDB, VacancyRepo


class TelegramCrawler:
    SOURCE = "telegram"

    def __init__(
        self,
        vacancies: VacancyRepo,
        channel: str,
        max_age_days: int = 30,
        batch_size: int = 100,
    ):
        self.vacancies = vacancies
        self.channel = channel
        self.max_age_days = max_age_days
        self.batch_size = batch_size
        self._cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)

    def run(self) -> None:
        asyncio.run(self._run_async())

    async def _run_async(self) -> None:
        async with TelegramClient(config.tg_session_file, config.tg_api_id, config.tg_api_hash) as client:
            print(f"[telegram] crawling @{self.channel}, cutoff={self._cutoff.date()}")
            await self._collect(client)

    async def _collect(self, client: TelegramClient) -> None:
        saved = 0
        offset_id = 0

        while True:
            messages: list[Message] = await client.get_messages(
                self.channel,
                limit=self.batch_size,
                offset_id=offset_id,
            )

            if not messages:
                print("[telegram] No more messages.")
                break

            stop = False
            for msg in messages:
                if msg.date < self._cutoff:
                    print(f"[telegram] Reached posts older than {self.max_age_days} days. Stopping.")
                    stop = True
                    break

                text = msg.message or ""
                low = text.lower()
                if "#резюме" in low or "#resume" in low:
                    continue
                if "#vacancy" not in low and "#вакансия" not in low:
                    continue

                vacancy = _parse_post(text, msg.id, msg.date, self.channel)
                self.vacancies.upsert(vacancy)
                saved += 1

            if stop or len(messages) < self.batch_size:
                break

            offset_id = messages[-1].id

        print(f"[telegram] Done. Vacancies upserted: {saved}")


# ── парсер текста поста ───────────────────────────────────────────────────

_FIELD_PREFIXES = re.compile(
    r"^(?:"
    r"позиция|position"
    r"|должность|вакансия|vacancy"
    r"|название\s+вакансии"
    r"|локация|location"
    r"|город\s+и\s+адрес(?:\s+офиса)?"
    r"|город|city"
    r"|формат\s+работы|формат"
    r"|занятость|employment"
    r"|зп|з/п|зарплат[а-я]*(?:\s+вилка)?|зарплатная\s+вилка"
    r"|salary|вилка|компенсация|ставка|оплата"
    r"|оформление"
    r"|домены"
    r"|компания\s+\w"
    r"|работодатель|company|название\s+компании"
    r")\s*[:\-–—]",
    re.IGNORECASE,
)

_META_TAGS = re.compile(
    r"^(?:вакансия|vacancy|fulltime|full.time|remote|удаленка|удалёнка|relocate"
    r"|москва|спб|russia|россия|spain|испания|казахстан|армения|armenia|cyprus|кипр"
    r"|middle|senior|junior|lead|офис|оффлайн|гибрид|office|onsite"
    r"|devops|девопс|sre|mlops|dataops|finops|devsecops|инфраструктура|инженер"
    r"|удаленно|fulltime|job|работа|hiring|ищу|outstaff|аутстафф"
    r"|kubernetes|k8s|docker|linux|sql|python|golang|java|bash|ci_cd"
    r"|blockchain|web3|ai|fintech|gamedev|igaming|биометрия|computervision"
    r"|platform|dsml|архитектор|руководитель|teamlead|techlead|engineeringmanager"
    r"|индия|инфобез|кибербезопасность|informationsecurity|infosec"
    r"|head|itjobs|devopsинженер|devopsвакансия|спб|минск|мск|moscow"
    r"|казахстан|relocation|внедрение|вк|redlab|litotagroup"
    r"|java|csharp|sonarqube|sast|cicd|elasticsearch|elk|php"
    r"|сисадмин|системныйадминистратор|sysadmin"
    r"|redis|kafka|keycloak|postgres|monetdb|airflow|jupyterhub"
    r"|coder|argowf|mlflow|seldon|cuda|kserv"
    r"|deckhouse|prometheus|grafana|zabbix|gitlabci|terraform|ansible|gitops"
    r"|mariadb|mysql|postgresql|удаленнаяработа|kyverno|istio|s3"
    r"|netops|netopsengiveer|elasticstack)$",
    re.IGNORECASE,
)

_LEADING_EMOJI = re.compile(
    r"^[\U00010000-\U0010ffff\u2600-\u27BF\uFE00-\uFE0F\u200d\u231A-\u23FF\u2B50\u2700-\u27BF\u2600-\u26FF\u2702-\u27B0\u24C2-\U0001F9FF]+\s*"
)

_GREETINGS = re.compile(
    r"^(?:"
    r"добрый\s+(день|вечер|утро)"
    r"|привет!?"
    r"|всем\s+привет!?"
    r"|hi!?|hello!?"
    r"|привет!?\s*меня\s+зовут"
    r"|всем\s+привет!?\s*мы\s+в"
    r")\b",
    re.IGNORECASE,
)

_REQUIRED_FIELDS = ("title", "company_name", "salary_from", "salary_to")


def _parse_post(text: str, msg_id: int, date: datetime, channel: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    sal = _parse_salary(text)
    title = _extract_title(lines, text)
    company = _extract_company(text, title, lines)
    location = _extract_location(text)
    remote = _is_remote(text)

    vacancy = {
        "vacancy_id": str(msg_id),
        "source": "telegram",
        "title": title,
        "company_name": company,
        "location": location,
        "salary_from": sal[0],
        "salary_to": sal[1],
        "currency": sal[2],
        "description": text,
        "remote": remote,
        "published_at": date if date.tzinfo else date.replace(tzinfo=timezone.utc),
    }

    missing = _check_missing(vacancy)
    vacancy["needs_review"] = bool(missing)
    vacancy["review_reasons"] = ", ".join(missing) if missing else None

    return vacancy


def _check_missing(v: dict) -> list[str]:
    missing: list[str] = []

    if not v.get("title"):
        missing.append("title")

    if v.get("salary_from") is None and v.get("salary_to") is None:
        missing.append("salary")

    if not v.get("location") and not v.get("remote"):
        missing.append("location")

    salary_from = v.get("salary_from")
    salary_to = v.get("salary_to")
    if salary_from is not None and salary_to is not None and salary_from > salary_to:
        missing.append("salary_from > salary_to")

    title = v.get("title")
    if title and _GREETINGS.match(title):
        missing.append("title_is_greeting")

    return missing


# ── извлечение заголовка ──────────────────────────────────────────────────

_TITLE_EXPLICIT = re.compile(
    r"(?:"
    r"^|\n\s*"
    r")"
    r"(?:"
    r"Позиция|Position"
    r"|Должность"
    r"|Название\s+вакансии"
    r"|Вакансия\s*(?!:.*#)"
    r")"
    r"\s*[:\-–—]\s*([^\n]{2,150})",
    re.IGNORECASE,
)

_SECTION_HEADERS = re.compile(
    r"^(?:"
    r"обязанности|требования|условия|задачи"
    r"|чем\s+предстоит\s+заниматься"
    r"|что\s+мы\s+(?:ждём|ожидаем|предлагаем)"
    r"|что\s+(?:ждём|ожидаем|предлагаем)"
    r"|основные\s+задачи"
    r"|стек(?:\s+технологий)?"
    r"|описание\s+вакансии"
    r"|наши\s+ожидания"
    r"|будет\s+плюсом"
    r"|будет\s+преимуществом"
    r"|особенности\s+найма"
    r")\s*[:\-–—]?\s*$",
    re.IGNORECASE,
)

_SEEKING_TITLE = re.compile(
    r"(?:"
    r"ищем|ищет|ищу|требуется"
    r"|мы\s+в\s+поисках|в\s+поисках"
    r"|we\s+are\s+hiring\s+a\s*|we\s+are\s+looking\s+for\s+a?\s*"
    r")"
    r"\s+([^\n,;.!]{3,60})",
    re.IGNORECASE | re.DOTALL,
)

_TARGET_EMOJI_TITLE = re.compile(
    r"🎯\s*"
    r"(?:Ищу|Ищем|Требуется|В\s*поисках)?\s*"
    r"([^\n]{3,80})",
    re.IGNORECASE,
)

_TITLE_LINE = re.compile(
    r"^\s*"
    r"(?:"
    r"Senior|Middle|Junior|Lead|Staff|Principal|Head\s+of"
    r"|DevOps|DevSecOps|MLOps|DataOps|FinOps|SRE|Platform"
    r"|Infrastructure|Cloud|Security|Network|System"
    r"|Blockchain|Web3|AI|ML|Backend|Frontend|Full.?Stack"
    r"|Linux|Dev(?:eloper|Ops)?|Engineer|Architect|Administrator"
    r")"
    r"[^\n]{2,120}",
    re.IGNORECASE,
)

_DECORATED_TITLE = re.compile(
    r"[🔷🔶♦️❇️✅⭐🟢🟠🟣🟡🔹🔸💻💼⚡️🔥🚀🛠🧠🪙💳🌍🌎🏢🎓📌🔐💡☀️💵🔌🖥📊🔧💪⭕️🟤☕️📝💸]+\s*"
    r"([^\n]{3,120})"
    r"\s*[🔷🔶♦️❇️✅⭐🟢🟠🟣🟡🔹🔸💻💼⚡️🔥|]*$",
)


def _extract_title(lines: list[str], full_text: str) -> Optional[str]:
    m = re.search(
        r"(?:^|\n\s*)"
        r"(?:Позиция|Position)"
        r"\s*[:\-–—]\s*"
        r"([^\n]{3,150})",
        full_text, re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        val = _LEADING_EMOJI.sub("", val).strip()
        return val

    for key in ["Должность", "Название\\s+вакансии"]:
        m = re.search(
            rf"(?:^|\n\s*){key}\s*[:\-–—]\s*([^\n]{{3,150}})",
            full_text, re.IGNORECASE,
        )
        if m:
            val = m.group(1).strip()
            val = _LEADING_EMOJI.sub("", val).strip()
            return val

    m = re.search(
        r"(?:^|\n\s*)Вакансия\s*[:\-–—]\s*"
        r"(?:"
        r"(?!#)"
        r"[^\n]{3,150}"
        r")",
        full_text, re.IGNORECASE,
    )
    if m:
        val = re.sub(r"^Вакансия\s*[:\-–—]\s*", "", m.group(0), flags=re.IGNORECASE)
        val = val.strip()
        val = _LEADING_EMOJI.sub("", val).strip()
        if val and not val.startswith("#"):
            return val

    m = _TARGET_EMOJI_TITLE.search(full_text)
    if m:
        val = m.group(1).strip().splitlines()[0].strip()
        val = _strip_emoji(val)
        val = re.split(
            r"\s+(?:в\s+команду|на\s+проект|на\s+банковский|по\s+сбору|для\s+работы)",
            val, flags=re.IGNORECASE,
        )[0].strip()
        val = re.sub(
            r"^(?:опытного|сильного|крутого|хорошего|отличного)\s+",
            "", val, flags=re.IGNORECASE,
        ).strip()
        if not _GREETINGS.match(val) and not _SECTION_HEADERS.match(val):
            return val

    m = _SEEKING_TITLE.search(full_text)
    if m:
        val = m.group(1).strip()
        val = re.split(r"(?:—|–|-)\s*(?:мы|компания|наша)", val, flags=re.IGNORECASE)[0]
        val = val.rstrip(".,;!")
        val = val.strip()
        if (val and not _GREETINGS.match(val) and not _SECTION_HEADERS.match(val)
                and len(val) >= 3 and not _is_generic_role(val)):
            val = _strip_emoji(val.splitlines()[0].strip())
            val = re.sub(
                r"^(?:опытного|сильного|крутого|хорошего|отличного)\s+",
                "", val, flags=re.IGNORECASE,
            ).strip()
            return val

    for line in lines:
        clean = _strip_emoji(line)
        if not clean or _is_service_line(line) or _GREETINGS.match(clean):
            continue
        m = _DECORATED_TITLE.match(line)
        if m:
            val = m.group(1).strip()
            if _SECTION_HEADERS.match(val):
                continue
            val = _LEADING_EMOJI.sub("", val[::-1])
            val = _LEADING_EMOJI.sub("", val[::-1])
            val = _strip_emoji(val)
            if val and len(val) >= 3:
                return val

    role_line = None
    for line in lines:
        clean = _strip_emoji(line)
        if not clean or _is_service_line(line) or _GREETINGS.match(clean):
            continue
        if _TITLE_LINE.match(clean):
            if not re.search(
                r"занимается|находится|разрабатыва|созда[её]м|меня\s+зовут|мы\s+в\s+поисках",
                clean, re.IGNORECASE,
            ):
                role_line = clean
                break

    tags = re.findall(r"#(\w+)", full_text)
    meaningful = [t for t in tags if not _META_TAGS.match(t)]
    meaning_title = None
    if meaningful:
        best = max(meaningful, key=len)
        if best.lower() == "netopsengiveer":
            best = "NetOps Engineer"
        meaning_title = best

    first_line_title = None
    for line in lines:
        clean = _strip_emoji(line)
        if not clean or _is_service_line(line):
            continue
        if _GREETINGS.match(clean):
            continue
        if len(clean) > 80 and re.search(
            r"занимается|находится|разрабатыва|предлага|созда[её]м|меня\s+зовут",
            clean, re.IGNORECASE,
        ):
            continue
        if re.match(r"^(?:мы\s+|в\s+|это\s+|данная\s+)", clean, re.IGNORECASE):
            continue
        if _SECTION_HEADERS.match(clean):
            continue
        if re.match(r"^(?:опыт|требуемый\s+опыт|коммерческий\s+опыт|гражданство|локация"
                     r"|ты\s+подходишь|навыки|знания|что\s+мы\s+жд[её]м|что\s+жд[её]м)\b",
                     clean, re.IGNORECASE):
            continue
        first_line_title = clean.splitlines()[0].strip()
        break

    if role_line:
        return role_line
    if first_line_title:
        return first_line_title
    if meaning_title:
        return meaning_title

    return None


def _is_service_line(line: str) -> bool:
    clean = _strip_emoji(line)
    if not clean:
        return True
    if re.fullmatch(r"(?:#\w+[\s,，]*)+", line):
        return True
    if not clean:
        return True
    if _FIELD_PREFIXES.match(line):
        return True
    if re.match(r"^(?:Публикатор|Обсуждение|Контакты?|Резюме\s+отправлять|Отклик|Писать)\s*:",
                line, re.IGNORECASE):
        return True
    if re.match(r"^https?://", line):
        return True
    if re.match(r"^Описание\s+вакансии\s*:?\s*$", line, re.IGNORECASE):
        return True
    if _SECTION_HEADERS.match(line):
        return True
    return False


def _is_generic_role(val: str) -> bool:
    generic = (
        r"^(?:инженер[а-я]*|девопс[а-я]*|системн(?:ый|ого)\s+администратор[а-я]?|"
        r"devops[а-я]*|специалист[а-я]*|разработчик[а-я]*|аналитик[а-я]*)$"
    )
    return bool(re.match(generic, val.strip(), re.IGNORECASE))


def _strip_emoji(s: str) -> str:
    result = _LEADING_EMOJI.sub("", s).strip()
    if result != s:
        result = _LEADING_EMOJI.sub("", result).strip()
    return result


# ── извлечение компании ───────────────────────────────────────────────────

_COMPANY_EXPLICIT = re.compile(
    r"(?:^|\n\s*)"
    r"(?:"
    r"Компания|Company|Название\s+компании|Работодатель"
    r")"
    r"\s*[:\-–—]?\s*"
    r"([^\n]{2,200})",
    re.IGNORECASE,
)

_COMPANY_NO_COLON = re.compile(
    r"(?:^|\n\s*)"
    r"Компания\s+"
    r"(?!занимается|находится|разрабатыва|созда[её]т|предлагает|меняет|ищет|ищем|в\s+поисках)"
    r"([^\n\s]{2,60})",
    re.IGNORECASE,
)


def _extract_company(text: str, title: Optional[str] = None,
                     lines: Optional[list[str]] = None) -> Optional[str]:
    for pattern in [
        r"Компания\s*[:\-–—]\s*(.+)",
        r"Company\s*[:\-–—]\s*(.+)",
        r"Название\s+компании\s*[:\-–—]\s*(.+)",
        r"Работодатель\s*[:\-–—]\s*(.+)",
    ]:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = re.split(
                r"\s{2,}|\n|[–—](?!\s*\d)"
                r"|(?<=\w)\s+(?:занимается|находится|разрабатыва|созда[её]т|предлагает|меняет|в\s+поисках)"
                r"|\s*[-–—]\s*(?:https?://|@)",
                val,
            )[0]
            val = _strip_emoji(val.strip())
            if len(val) > 80:
                continue
            if val and not val.startswith("#") and not re.match(r"^https?://", val):
                return val

    m = _COMPANY_NO_COLON.search(text)
    if m:
        val = m.group(1).strip()
        val = _strip_emoji(val)
        if val and len(val) <= 60:
            return val

    m = re.search(
        r"(?:^|\n)\s*"
        r"([A-ZА-Я][A-Za-zА-Яа-я0-9&.\s]{2,40})"
        r"\s*[–—]\s*"
        r"(?:финтех|стартап|сервис|компания|проект|платформа|продукт|решение)",
        text, re.IGNORECASE,
    )
    if m:
        val = m.group(1).strip()
        val = _strip_emoji(val)
        if val and len(val) <= 60:
            return val

    if lines and title:
        found_title = False
        for line in lines:
            clean = _strip_emoji(line)
            if not clean or _is_service_line(line):
                continue
            if not found_title:
                if title.lower() in clean.lower():
                    found_title = True
                continue
            if 2 <= len(clean) <= 60 and not _is_service_line(line):
                if not re.search(
                    r"^(?:Локация|Location|Город|ЗП|Зарплат|Вилка|Оплата|Формат|Занятость"
                    r"|Условия|Оформление|Обязанности|Требования|Стек|Задачи|Чем|Что)"
                    r"|руб|USD|EUR|\d{3,}",
                    clean, re.IGNORECASE,
                ):
                    if not _GREETINGS.match(clean):
                        return clean

    return None


# ── извлечение локации ───────────────────────────────────────────────────

_CITY_FALLBACKS = [
    r"\b(Москва|Санкт-Петербург|СПб|Новосибирск|Екатеринбург|Казань"
    r"|Нижний\s+Новгород|Краснодар|Сочи|Владивосток|Хабаровск|Красноярск"
    r"|Минск|Киев|Астана|Алматы|Ташкент|Баку|Тбилиси|Ереван)\b",
    r"\b(Лиссабон|Лондон|Берлин|Париж|Амстердам|Дубай|Абу-?Даби|Доха"
    r"|Лимасол|Кипр|Стамбул|Бильбао|Барселона|Мадрид)\b",
    r"\b(Гургаон|Бангалор|Мумбаи|Дели|Куала-?Лумпур|Сингапур|Токио)\b",
]


def _extract_location(text: str) -> Optional[str]:
    patterns = [
        (
            r"Локация\s+и\s+формат\s*[:\-–—]\s*(.+)",
            lambda v: _extract_city_from_combined(v),
        ),
        (r"(?:Локация|Location)\s*[:\-–—]\s*(.+)", None),
        (r"Локация\s*/\s*гражданство\s*[:\-–—]\s*(.+)", None),
        (r"Город(?:\s+и\s+адрес(?:\s+офиса)?)?\s*[:\-–—]\s*(.+)", None),
        (r"(?:Адрес\s+офиса|Офис)\s*[:\-–—]\s*(.+)", None),
        (r"[🌍📍]\s*(.+)", None),
    ]
    for pattern, transformer in patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip()
            val = val.splitlines()[0].strip()
            if transformer:
                val = transformer(val)
            val = _LEADING_EMOJI.sub("", val).strip()
            if val and not val.startswith("#") and len(val) >= 2:
                return _clean_location(val)

    for city_pattern in _CITY_FALLBACKS:
        m = re.search(city_pattern, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()

    return None


def _extract_city_from_combined(text: str) -> str:
    m = re.search(
        r"(?:удалённ?к[а-я]*|удаленн?к[а-я]*|remote|гибрид|офис)\s*"
        r"(?:по\s+)?"
        r"([А-ЯA-Z][а-яa-z\s.-]{2,50})",
        text, re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    return re.split(r"[,\n(]", text)[0].strip()


def _clean_location(val: str) -> Optional[str]:
    if "\\" in val:
        parts = val.split("\\")
        for part in parts:
            part = part.strip()
            if re.match(r"^[А-ЯA-Z][а-яa-z\s.-]{2,}", part):
                val = part
                break

    val = re.split(r"📍", val)[0].strip()

    if val.lower() in ("рф", "россия", "russia", "rb", "ру", 'только рф', 'только рб'):
        return None

    if len(val) > 100:
        val = re.split(r"[,\n(]", val)[0].strip()

    return val if len(val) >= 2 else None


# ── зарплата ──────────────────────────────────────────────────────────────

_SALARY_KEY = re.compile(
    r"(?:"
    r"^|\n"
    r")"
    r"[\s💵💰🪙💳💶💷💸•▪▸►-]*"
    r"(?:"
    r"з\.?\s*п"
    r"|з\s*/\s*п"
    r"|зарплат[а-я]*(?:\s+вилка)?"
    r"|оплата(?:\s+труда)?"
    r"|вилка"
    r"|salary|compensation"
    r"|финансовая\s+мотивация"
    r"|компенсация"
    r"|ставка"
    r"|доход"
    r")"
    r"\s*[:\-–—🪙💰💳💵]*\s*"
    r"(.+)",
    re.IGNORECASE | re.DOTALL,
)

_CURRENCY_PATTERNS = [
    (r"₽|руб(?:лей|ля|ль)?\.?", "RUB"),
    (r"\$|usd|долл(?:аров)?\.?", "USD"),
    (r"€|eur|евро", "EUR"),
    (r"usdt|usdc", "USDT"),
]

_THOUSANDS_MARKER = re.compile(
    r"(?:\d[\d\s\xa0]*)\s*(?:тыс(?:яч|\.)?|k|к)\b",
    re.IGNORECASE,
)

_HOURLY_MARKER = re.compile(
    r"(?:руб|₽|\$|€|USD|EUR)\s*(?:/|\\|\s+per\s+)?\s*(?:час|hour|ч\.?|h\.?|hr)",
    re.IGNORECASE,
)

_YEARLY_MARKER = re.compile(
    r"(?:/|\s+per\s+)?\s*(?:год|year|yr|annum|annual)",
    re.IGNORECASE,
)


def _parse_salary(text: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    m = _SALARY_KEY.search(text)
    if m:
        raw = m.group(1).strip().splitlines()[0].strip()
        return _parse_salary_str(raw)

    m2 = re.search(r"💰\s*(.+)", text)
    if m2:
        raw = m2.group(1).strip().splitlines()[0].strip()
        result = _parse_salary_str(raw)
        if result[0] is not None or result[1] is not None:
            return result

    return None, None, None


def _parse_salary_str(raw: str) -> tuple[Optional[float], Optional[float], Optional[str]]:
    currency = None
    for pattern, code in _CURRENCY_PATTERNS:
        if re.search(pattern, raw, re.IGNORECASE):
            currency = code
            break

    is_hourly = bool(_HOURLY_MARKER.search(raw))
    is_yearly = bool(_YEARLY_MARKER.search(raw))
    has_thousands_marker = bool(_THOUSANDS_MARKER.search(raw))
    has_k_suffix = bool(re.search(r"\d[\d\s\xa0]*[kк]\b", raw, re.IGNORECASE))

    only_upper = False
    if re.search(r"^\s*до\b", raw, re.IGNORECASE):
        first_num = re.search(r"(\d[\d\s\xa0]*)", raw)
        before_first = raw[:first_num.start()].lower() if first_num else raw.lower()
        if "от " not in before_first:
            only_upper = True

    normalized = raw
    normalized = re.sub(r"\s*[—–]\s*", " - ", normalized)
    normalized = re.sub(r"\bот\b", "", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"\bдо\b", "- ", normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"(\d[\d\s\xa0]*)\s*/\s*(\d)", r"\1 - \2", normalized)
    normalized = re.sub(
        r"\b(?:на\s+руки|net|gross|нетт|чистыми|гросс|на\s+руки)\b",
        "", normalized, flags=re.IGNORECASE,
    )

    clean_for_numbers = normalized
    clean_for_numbers = re.sub(r"[₽$€]", "", clean_for_numbers)
    clean_for_numbers = re.sub(
        r"\b(?:руб(?:лей|ля|ль)?|usd|usdt|usdc|eur|евро|долл(?:аров)?)\b",
        "", clean_for_numbers, flags=re.IGNORECASE,
    )

    clean_for_numbers = re.sub(
        r"(\d[\d\s\xa0]*)\s*[kк]\b",
        lambda m: re.sub(r"[\s\xa0]", "", m.group(1)) + "000",
        clean_for_numbers, flags=re.IGNORECASE,
    )

    clean_for_numbers = re.sub(r"(\d),(\d{3})", r"\1\2", clean_for_numbers)
    clean_for_numbers = re.sub(r"(\d)\.(\d{3})", r"\1\2", clean_for_numbers)

    raw_numbers = re.findall(r"\d[\d\s\xa0]*", clean_for_numbers)
    numbers: list[float] = []
    for n in raw_numbers:
        clean = re.sub(r"[\s\xa0]", "", n)
        try:
            val = float(clean)
            numbers.append(val)
        except ValueError:
            continue

    if not numbers:
        return None, None, currency

    if not is_hourly and not is_yearly:
        if not has_k_suffix and not has_thousands_marker:
            numbers = [_maybe_multiply(n) for n in numbers]
        elif has_thousands_marker:
            numbers = [n * 1000 if n < 1000 else n for n in numbers]

    if len(numbers) == 1:
        if only_upper:
            return None, numbers[0], currency
        return numbers[0], None, currency

    if len(numbers) >= 2:
        return numbers[0], numbers[1], currency


def _maybe_multiply(val: float) -> float:
    if val < 1000:
        return val * 1000
    return val


# ── удалёнка ──────────────────────────────────────────────────────────────

_REMOTE_POSITIVE = re.compile(
    r"(?<!нет\s)"
    r"(?<!без\s)"
    r"(?:"
    r"удалённ|удаленн|remote|дистанц"
    r"|🌍|🌎|🏠"
    r")",
    re.IGNORECASE,
)

_REMOTE_NEGATIVE = re.compile(
    r"(?:"
    r"удалёнки\s+нет|удаленки\s+нет"
    r"|без\s+удалёнки|без\s+удаленки"
    r"|not\s+remote|no\s+remote"
    r"|офис\s*\(?\s*без\s+удалёнки|офис\s*\(?\s*без\s+удаленки"
    r"|onsite|on-site|оффлайн"
    r"|офис\s*/\s*full.time"
    r")",
    re.IGNORECASE,
)

_REMOTE_FORMAT = re.compile(
    r"(?:Формат(?:\s+работы)?)\s*[:\-–—]?\s*"
    r"(?:удалёнка|удаленка|remote|дистанционно|удалённая|удаленная)",
    re.IGNORECASE,
)


def _is_remote(text: str) -> bool:
    if _REMOTE_NEGATIVE.search(text):
        if _REMOTE_FORMAT.search(text) or "Full Remote" in text:
            return True
        return False

    if _REMOTE_FORMAT.search(text):
        return True

    if re.search(r"Full\s+Remote", text, re.IGNORECASE):
        return True

    m = re.search(
        r"(?:"
        r"удалён[а-яё]*|удален[а-яё]*|remote|дистанц"
        r"|🌍|🌎|🏠"
        r")",
        text, re.IGNORECASE,
    )
    if m:
        start = max(0, m.start() - 20)
        end = min(len(text), m.end() + 20)
        context = text[start:end]
        if re.search(r"(?:нет\s+|без\s+)", context, re.IGNORECASE):
            return False
        return True

    return False


# ── хелпер ───────────────────────────────────────────────────────────────


def _field(text: str, pattern: str) -> Optional[str]:
    m = re.search(pattern, text, re.IGNORECASE)
    if not m:
        return None
    return m.group(1).strip().splitlines()[0].strip()


if __name__ == "__main__":
    db = PostgresDB(config.db_dsn)
    vacancies = VacancyRepo(db)

    crawler = TelegramCrawler(
        vacancies=vacancies,
        channel=config.tg_channels[0] if config.tg_channels else "devops_jobs",
        max_age_days=config.tg_max_age_days,
    )
    crawler.run()
    db.close()
