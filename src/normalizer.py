import re
import json

def normalize_movement(text: str) -> dict:
    pass


MONTHS_MAP = {
    "янв": "01", "фев": "02", "мар": "03", "апр": "04", "май": "05", "июн": "06",
    "июл": "07", "авг": "08", "сен": "09", "окт": "10", "ноя": "11", "дек": "12"
}
DATE_PATTERN = re.compile(
    r'(?P<year_iso>\d{4})-(?P<month_iso>\d{2})-(?P<day_iso>\d{2})'  # 1. ISO: 2026-03-08
    r'|'
    r'(?P<day_txt>\d{1,2})\s+(?P<month_txt>[а-яА-Яa-zA-Z]+)\s+(?P<year_txt>\d{4})'  # 2. Текст: 1 марта 2026
    r'|'
    r'(?P<day_num>\d{2})[./](?P<month_num>\d{2})[./](?P<year_num>\d{2,4})'  # 3. Цифры: 05.03.2026 или 03/06/26
)
def parse_date_to_iso(text: str) -> str | None:
    if not text:
        return None
    
    match = DATE_PATTERN.search(text)
    if not match:
        return None
    
    gd = match.groupdict()   
    day, month, year = None, None, None
    
    # 1. Вариант ISO (2026-03-08)
    if gd['year_iso']:
        day = gd['day_iso']
        month = gd['month_iso']
        year = gd['year_iso']
        
    # 2. Вариант с текстом (1 марта 2026)
    elif gd['day_txt']:
        day = gd['day_txt'].zfill(2) # '1' -> '01'
        # Берем первые 3 буквы месяца в нижнем регистре (например, "марта" -> "мар")
        month_word = gd['month_txt'].lower()[:3]
        month = MONTHS_MAP.get(month_word, "01")
        year = gd['year_txt']
        
    # 3. Вариант с цифрами (05.03.2026 или 03/06/26)
    elif gd['day_num']:
        day = gd['day_num']
        month = gd['month_num']
        year = gd['year_num']
        if len(year) == 2: # Если год '26', делаем '2026'
            year = "20" + year

    if day and month and year:
        return f"{year}-{month}-{day}"
    
    return None

if __name__ == "__main__":
    with open("../data/dataset.json", "r", encoding="utf-8") as f:
        movements = json.load(f)

    for item in movements:
        print(f"{item["text"]} -> {parse_date_to_iso(item["text"])}\n")
