"""Модуль нормализации текстовых записей движения товаров."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CATALOG_PATH = Path("../data/catalog.json")

OPERATION_MAP: dict[str, str] = {
    "приход": "receipt",
    "расход": "consume",
    "списание": "writeoff",
    "возврат": "return",
    "корректировка": "correction",
}

RU_MONTHS: dict[str, int] = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}

KNOWN_LOCATIONS: dict[str, str] = {
    "ms-01": "MS-01",
    "ms-02": "MS-02",
    "сочи": "Сочи",
    "красная поляна": "Красная Поляна",
}

_CATALOG_CACHE: dict[str, dict[str, Any]] | None = None

def get_catalog() -> dict[str, dict[str, Any]]:
    """Ленивая загрузка и кэширование справочника catalog.json."""
    global _CATALOG_CACHE
    if _CATALOG_CACHE is not None:
        return _CATALOG_CACHE

    _CATALOG_CACHE = {}
    if CATALOG_PATH.exists():
        with open(CATALOG_PATH, "r", encoding="utf-8") as f:
            catalog_list = json.load(f)
            for item in catalog_list:
                _CATALOG_CACHE[item["sku"].upper()] = item
    return _CATALOG_CACHE

# ---------------------------------------------------------------------------
# Вспомогательные парсеры
# ---------------------------------------------------------------------------

def parse_date(text: str) -> str | None:
    """Извлекает дату из строки и возвращает её в формате ISO (YYYY-MM-DD)."""
    if m := re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", text):
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"

    ru_date_pattern = (
        r"\b(\d{1,2})\s+([а-яё]+)\s+(\d{4})(?:\s*г\.?)?\b"
    )
    if m := re.search(ru_date_pattern, text, flags=re.IGNORECASE):
        day = int(m.group(1))
        month_str = m.group(2).lower()
        year = int(m.group(3))
        if month_str in RU_MONTHS:
            return f"{year:04d}-{RU_MONTHS[month_str]:02d}-{day:02d}"

    if m := re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b", text):
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"

    if m := re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", text):
        month = int(m.group(1))
        day = int(m.group(2))
        year = int(m.group(3))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"

    return None

def match_sku(text: str, catalog: dict[str, dict[str, Any]]) -> str | None:
    """Находит SKU в тексте по коду позиции либо по смысловому совпадению названия."""
    # Прямой поиск SKU кода (например, OIL-001, WRAP 030, «oil 001»)
    sku_pattern = r"\b([A-Za-z]{3,4})[-_\s]?(\d{3})\b"
    for m in re.finditer(sku_pattern, text):
        candidate = f"{m.group(1).upper()}-{m.group(2)}"
        if candidate in catalog:
            return candidate

    # Семантический поиск по ключевым словам из справочника
    text_lower = text.lower()
    for sku, item in catalog.items():
        name_lower = item["name"].lower()
        words = [w for w in re.findall(r"[а-яёa-z]{4,}", name_lower)]
        # Если хотя бы 2 значимых слова из названия есть в тексте
        hits = sum(1 for w in words if w in text_lower)
        if hits >= 2:
            return sku
        # Специфические ключевые слова (например, "тапочек" -> CONS-051)
        if "тапочек" in text_lower and "тапочки" in name_lower:
            return sku
        if "шапочек" in text_lower and "шапочки" in name_lower:
            return sku

    return None

def parse_location(text: str) -> str | None:
    """Извлекает склад или географическую точку."""
    text_lower = text.lower()
    for loc_key, loc_val in KNOWN_LOCATIONS.items():
        if loc_key in text_lower:
            return loc_val
    return None

def parse_operation(text: str) -> str | None:
    """Определяет тип складской операции."""
    text_lower = text.lower()
    for key, op in OPERATION_MAP.items():
        if key in text_lower:
            return op
    return None

def parse_batch_and_doc(text: str) -> tuple[str | None, str | None]:
    """Извлекает номер партии (batch) и номер накладной/документа (doc_no)."""
    batch: str | None = None
    doc_no: str | None = None

    # Поиск номера партии (B-OIL-001-012, В-WRAP-030-004 с латинской или кириллической B/В)
    batch_pattern = r"(?:парт\.?\s*)?([BВ]-[\w-]+)"
    if m := re.search(batch_pattern, text):
        batch = m.group(1).replace("В", "B")  # приведение кириллической 'В' к латинице
     # Поиск накладной (НК-345 и аналогичные)
    doc_pattern = r"\b([Нн][Кк]-\d+)\b"
    if m := re.search(doc_pattern, text):
        doc_no = m.group(1).upper()

    return batch, doc_no

def parse_qty_and_unit(
    text: str, sku: str | None, catalog: dict[str, dict[str, Any]]
) -> tuple[float | None, str | None]:
    """Извлекает количество, пересчитывает его в базовую единицу SKU из справочника."""
    base_unit = catalog[sku]["unit"] if (sku and sku in catalog) else None
    low = text.lower()

    # 1. Составные упаковки: "2 канистры по 5 л", "4 уп. по 50 пар"
    pack_pattern = (
        r"(\d+(?:[.,]\d+)?)\s*(?:канистр\w*|уп(?:\.|аков\w*)?)\s*по\s*(\d+(?:[.,]\d+)?)\s*([а-яёa-z]+)?"
    )
    if m := re.search(pack_pattern, low):
        count = float(m.group(1).replace(",", "."))
        volume = float(m.group(2).replace(",", "."))
        unit_str = m.group(3) or ""
        total = count * volume

        if "мл" in unit_str:
            total /= 1000.0
        return total, base_unit or ("л" if "л" in unit_str else "пар")

    # 2. Одиночные объемы строго перед единицей измерения (с поддержкой минуса для корректировок)
    # Исключаем 'г.' (сокращение года), требуя словообразующие границы или пробелы
    single_pattern = r"(-?\d+(?:[.,]\d+)?)\s*(мл|л|кг|пар|шт)\b"
    if m := re.search(single_pattern, low):
        val = float(m.group(1).replace(",", "."))
        unit_found = m.group(2)

        if unit_found == "мл":
            val /= 1000.0

        return val, base_unit or unit_found

    return None, base_unit

# ---------------------------------------------------------------------------
# Главная функция по ТЗ
# ---------------------------------------------------------------------------

def normalize_movement(text: str) -> dict[str, Any]:
    """Разбирает текстовую строку складской операции в структурированный словарь.

    :param text: Исходная строка описания движения товара.
    :return: Словарь с ключами: date, sku, location, operation, qty, unit, batch, doc_no.
    """
    catalog = get_catalog()

    sku = match_sku(text, catalog)
    date_iso = parse_date(text)
    location = parse_location(text)
    operation = parse_operation(text)
    batch, doc_no = parse_batch_and_doc(text)
    qty, unit = parse_qty_and_unit(text, sku, catalog)

    return {
        "date": date_iso,
        "sku": sku,
        "location": location,
        "operation": operation,
        "qty": qty,
        "unit": unit,
        "batch": batch,
        "doc_no": doc_no,
    }

if __name__ == "__main__":
    test_cases = [
        "05.03.2026 MS-01 приход OIL-001, 2 канистры по 5 л, НК-345",
        "1 марта 2026 MS-01 расход oil 001 450 мл, В-OIL-001-012",
        "03/06/26 Сочи списание SCRB-020 1,2 кг, истёк срок",
        "07.03.26 ms-02 WRAP 030 расход 3,5кг, парт. В-WRAP-030-004",
        "Возврат 12 марта 2026 г.: OIL-002, 2 л, брак упаковки",
        "2026-03-08; MS-01; CONS-051; расход; 48 пар",
        "Корректировка 15.03.2026, MS-02, CONS-052: -120 шт",
        "Приход тапочек одноразовых, 4 уп. по 50 пар, Красная Поляна",
    ]

    for idx, sample in enumerate(test_cases, 1):
        parsed = normalize_movement(sample)
        print(f"M{idx}: {sample}")
        print(f"    -> {parsed}\n")