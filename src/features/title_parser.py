"""
title_parser.py — нормализация названия вакансии:
извлечение грейда (Junior/Middle/Senior/Lead) и позиции (DevOps/SRE/MLOps...).
"""

from __future__ import annotations

import re
from typing import Optional

# ── грейды ────────────────────────────────────────────────────────────────────

GRADE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(?:intern|trainee|incubat|стаж[её]р|стажировк)\b", re.I), "Intern"),
    (re.compile(r"\b(?:junior|jun|beginner|entry.level|entrylevel)\b", re.I), "Junior"),
    (re.compile(r"\b(?:junior[\s\-/+]*middle|middle[\s\-/+]*junior)\b", re.I), "Junior/Middle"),
    (re.compile(r"\b(?:middle|mid)(?:\W|$|[\s\-/+]*senior|[\s\-/+]*junior)\b", re.I), "Middle"),
    (re.compile(r"\b(?:middle[\s\-/+]*senior|senior[\s\-/+]*middle)\b", re.I), "Middle/Senior"),
    (re.compile(r"\b(?:senior|старший)\b", re.I), "Senior"),
    (re.compile(r"\b(?:lead|head|principal|chief|главный)\b", re.I), "Lead"),
    (re.compile(r"\b(?:руководител.?.?|director|manager|head\s+of)\b", re.I), "Lead"),
]


def extract_grade(title: str) -> Optional[str]:
    """Извлекает грейд из названия вакансии.

    >>> extract_grade("Senior DevOps Engineer")
    'Senior'
    >>> extract_grade("Junior DevOps Engineer (Azure)")
    'Junior'
    >>> extract_grade("DevOps-инженер")
    >>> extract_grade("Middle/Senior DevOps Engineer")
    'Middle/Senior'
    >>> extract_grade("Стажёр DevOps")
    'Intern'
    """
    for pattern, grade in GRADE_PATTERNS:
        if pattern.search(title):
            return grade
    return None


# ── позиции ───────────────────────────────────────────────────────────────────

POSITION_PATTERNS: list[re.Pattern] = [
    re.compile(r"site.reliability.engineer|(?<=[\s(/])sre|^sre", re.I),
    re.compile(r"mlops", re.I),
    re.compile(r"devsecops", re.I),
    re.compile(r"(?<=[\s(/])devops|^devops|[\s(/]devops|[|-]devops", re.I),
    re.compile(r"platform.engineer|platform.eng", re.I),
    re.compile(r"system.admin|sysadmin|системный.администратор|системный.админ", re.I),
    re.compile(r"system.engineer|системный.инженер", re.I),
    re.compile(r"infrastructure.engineer|infra.engineer", re.I),
    re.compile(r"cloud.engineer|cloud.architect", re.I),
    re.compile(r"network.engineer|сетевой", re.I),
    re.compile(r"data.engineer", re.I),
    re.compile(r"security.engineer", re.I),
]


def extract_position(title: str) -> list[str]:
    """Извлекает нормализованные позиции из названия вакансии.

    >>> extract_position("Senior DevOps Engineer")
    ['DevOps']
    >>> extract_position("SRE/DevOps инженер")
    ['SRE', 'DevOps']
    >>> extract_position("MLOps Engineer")
    ['MLOps']
    >>> extract_position("DevOps - инженер")
    ['DevOps']
    >>> extract_position("Системный администратор / DevOps-инженер")
    ['System Administrator', 'DevOps']
    """
    result: list[str] = []

    for pattern in POSITION_PATTERNS:
        m = pattern.search(title)
        if m:
            raw = m.group(0).lstrip("/ (")
            norm = _normalize_position(raw)
            if norm and norm not in result:
                result.append(norm)

    # fallback: если не нашли — пытаемся взять первое слово
    if not result:
        first = title.strip().split()[0].rstrip(" ,-/|")
        norm = _normalize_position(first)
        if norm and norm not in result:
            result.append(norm)

    return result


_POSITION_NORMALIZE: dict[str, str] = {
    "devops": "DevOps",
    "devsecops": "DevSecOps",
    "mlops": "MLOps",
    "site reliability engineer": "SRE",
    "sre": "SRE",
    "platform engineer": "Platform Engineer",
    "platform eng": "Platform Engineer",
    "system administrator": "System Administrator",
    "sysadmin": "System Administrator",
    "системный администратор": "System Administrator",
    "системный админ": "System Administrator",
    "system engineer": "System Engineer",
    "системный инженер": "System Engineer",
    "infrastructure engineer": "Infrastructure Engineer",
    "infra engineer": "Infrastructure Engineer",
    "cloud engineer": "Cloud Engineer",
    "cloud architect": "Cloud Architect",
    "network engineer": "Network Engineer",
    "сетевой": "Network Engineer",
    "data engineer": "Data Engineer",
    "security engineer": "Security Engineer",
}


def _normalize_position(raw: str) -> Optional[str]:
    clean = raw.strip(" \t\r\n/|,()")
    if not clean:
        return None
    lower = clean.lower()
    return _POSITION_NORMALIZE.get(lower, clean)
