"""
section_parser.py — извлечение секций из текста вакансий.

Определяет заголовки секций (Требования, Обязанности, Будет плюсом...),
извлекает содержимое каждой, отбрасывает шум (О компании, Условия),
и форматирует результат для подачи в LLM.

Работает как с однострочным текстом (после HtmlDescriptionCleaner),
так и с многострочным (исходный формат базы).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedDescription:
    sections: dict[str, str] = field(default_factory=dict)
    preamble: str = ""
    original: str = ""

    @property
    def has_sections(self) -> bool:
        return bool(self.sections)

    @property
    def relevant_keys(self) -> list[str]:
        return [k for k in self.sections
                if k not in ("noise_company", "noise_benefits", "noise_conditions", "noise_project")]


# ── Определения секций ──────────────────────────────────────────────────────
# (pattern, key, output_label, is_noise)
# Паттерны ищутся в тексте как есть (не на старте строки).
# Важен порядок: более специфичные — первыми.

_SECTION_DEFS: list[tuple[re.Pattern, str, str | None, bool]] = [
    # ── Responsibilities ──────────────────────────────────────────────
    (
        re.compile(r"Обязанност[ия]\s*:", re.I),
        "responsibilities", "[ОБЯЗАННОСТИ]", False,
    ),
    (
        re.compile(r"Чем\s+предстоит\s+заниматься\s*:", re.I),
        "responsibilities", "[ОБЯЗАННОСТИ]", False,
    ),
    (
        re.compile(r"Основные\s+задачи\s*:", re.I),
        "responsibilities", "[ОБЯЗАННОСТИ]", False,
    ),
    (
        re.compile(r"Вам\s+предстоит\s*:", re.I),
        "responsibilities", "[ОБЯЗАННОСТИ]", False,
    ),
    (
        re.compile(r"Задачи\s*:", re.I),
        "responsibilities", "[ОБЯЗАННОСТИ]", False,
    ),
    # ── Requirements ──────────────────────────────────────────────────
    (
        re.compile(r"Требовани[ейя]\s*:", re.I),
        "requirements", "[ТРЕБОВАНИЯ]", False,
    ),
    (
        re.compile(r"(?:Наши\s+)?(?:Ожидания\s+от\s+кандидат|Что\s+мы\s+ожидаем|Что\s+для\s+нас\s+важно|Мы\s+ожидаем)\s*:", re.I),
        "requirements", "[ТРЕБОВАНИЯ]", False,
    ),
    (
        re.compile(r"(?:Необходимые?\s+(?:навыки|знания|опыт)|Что\s+нам\s+важно)\s*:", re.I),
        "requirements", "[ТРЕБОВАНИЯ]", False,
    ),
    # ── Preferred ─────────────────────────────────────────────────────
    (
        re.compile(r"Будет\s+плюсом\s*:", re.I),
        "preferred", "[БУДЕТ ПЛЮСОМ]", False,
    ),
    (
        re.compile(r"Будет\s+преимуществом\s*:", re.I),
        "preferred", "[БУДЕТ ПЛЮСОМ]", False,
    ),
    (
        re.compile(r"Плюсом\s+будет\s*:", re.I),
        "preferred", "[БУДЕТ ПЛЮСОМ]", False,
    ),
    (
        re.compile(r"(?:Желательно|Приветствуется)\s*:", re.I),
        "preferred", "[БУДЕТ ПЛЮСОМ]", False,
    ),
    (
        re.compile(r"(?:Nice\s+to\s+have|Good\s+to\s+have|Preferred)\s*:", re.I),
        "preferred", "[БУДЕТ ПЛЮСОМ]", False,
    ),
    # ── Experience ────────────────────────────────────────────────────
    (
        re.compile(r"Опыт\s+работы\s*:", re.I),
        "experience", None, False,
    ),
    # ── Key skills ────────────────────────────────────────────────────
    (
        re.compile(r"Ключевые\s+навыки\s*:", re.I),
        "key_skills", "[КЛЮЧЕВЫЕ НАВЫКИ]", False,
    ),
    (
        re.compile(r"(?:Технические\s+)?(?:Стек|Stack|Tech\s+stack)\s*:", re.I),
        "key_skills", "[КЛЮЧЕВЫЕ НАВЫКИ]", False,
    ),
    # ── Noise ─────────────────────────────────────────────────────────
    (
        re.compile(r"Мы\s+предлагаем\s*:", re.I),
        "noise_benefits", None, True,
    ),
    (
        re.compile(r"Условия\s*:", re.I),
        "noise_conditions", None, True,
    ),
    (
        re.compile(r"О\s+компании(?:\s+и\s+команде|\s*:|\s|\Z)", re.I),
        "noise_company", None, True,
    ),
    (
        re.compile(r"О\s+проекте\s*:", re.I),
        "noise_project", None, True,
    ),
    (
        re.compile(r"Преимущества\s*:", re.I),
        "noise_benefits", None, True,
    ),
    (
        re.compile(r"Почему\s+стоит\s+выбрать\s+нас\s*:", re.I),
        "noise_benefits", None, True,
    ),
]


class SectionParser:
    """Парсит текст вакансии на секции и форматирует для LLM."""

    def parse(self, text: str) -> ParsedDescription:
        if not text:
            return ParsedDescription(original=text or "")

        result = ParsedDescription(original=text)

        # Находим все вхождения заголовков секций
        matches: list[tuple[int, int, str, str | None, bool]] = []
        seen_positions: set[int] = set()

        for pattern, key, label, is_noise in _SECTION_DEFS:
            for m in pattern.finditer(text):
                pos = m.start()
                if pos not in seen_positions:
                    seen_positions.add(pos)
                    matches.append((
                        pos, m.end(), key, label, is_noise,
                    ))

        if not matches:
            return result

        matches.sort(key=lambda x: x[0])

        # Первая секция: текст до первого заголовка
        first_pos = matches[0][0]
        preamble = text[:first_pos].strip()
        if preamble:
            result.preamble = preamble

        # Извлекаем содержимое между секциями
        for i, (start, end, key, label, is_noise) in enumerate(matches):
            if i + 1 < len(matches):
                next_start = matches[i + 1][0]
            else:
                next_start = len(text)

            raw_content = text[end:next_start].strip()
            content = self._clean_content(raw_content)

            if content and not is_noise:
                # Если секция с таким ключом уже есть — добавляем
                if key in result.sections:
                    result.sections[key] += "\n" + content
                else:
                    result.sections[key] = content

        return result

    def format_for_llm(self, parsed: ParsedDescription) -> str:
        """Форматирует распарсенный текст для подачи в LLM.

        Если секции не найдены — возвращает оригинальный текст без изменений.
        """
        if not parsed.has_sections:
            return parsed.original

        parts: list[str] = []

        if parsed.preamble:
            parts.append(parsed.preamble)

        for key in parsed.relevant_keys:
            content = parsed.sections[key]
            parts.append(content)

        return "\n\n".join(parts)

    @staticmethod
    def _get_label(key: str) -> Optional[str]:
        for _, k, label, _ in _SECTION_DEFS:
            if k == key and label:
                return label
        return None

    @staticmethod
    def _clean_content(content: str) -> str:
        content = re.sub(r"^[\s•\-*_]+", "", content)
        content = re.sub(r"\s{3,}", "  ", content)
        return content.strip()
