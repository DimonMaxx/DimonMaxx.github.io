# common.py
# Общие константы и функции для всех скриптов проекта.
#
# Функция check_sheets_health() — предполётная проверка Google Sheets
# перед синхронизацией. Если что-то не так (таблица недоступна, лист
# не найден, нет header row), sync не запускается — вместо этого
# отправляется алерт в Telegram.

import os
import re
import json
import gspread
from google.oauth2.service_account import Credentials


# ============================================================
# КОНСТАНТЫ
# ============================================================

SPREADSHEET_ID = os.environ.get(
    "SPREADSHEET_ID",
    "1kcG0TG4GZtSM2mypjgvNDUpIbLfIvcmW80_hBKA11nw",
)

SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "НаполнениеСайта")

CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")


SHEET_CONFIG = {
    "Книги":     {"json": "_content/books.json"},
    "Программы": {"json": "_content/programs.json"},
    "Музыка":    {"json": "_content/music.json"},
    "Игры":      {"json": "_content/games.json"},
    "Статьи":    {"json": "_content/articles.json"},
    "Фильмы":    {"json": "_content/movies.json"},
    "Разное":    {"json": "_content/misc.json"},
    "Новости":   {"json": "_content/news.json"},
}


# Соответствие русских заголовков колонок в Sheets → английским ключам в JSON.
COLUMN_MAPPING = {
    "Название":              "title",
    "Автор":                 "author",
    "Описание":              "description",
    "Формат":                "format",
    "Размер (МБ)":           "size",
    "Размер":                "size",
    "Ссылка для скачивания": "download_link",
    "Ссылка":                "download_link",
    "Обложка":               "cover",
    "Папка":                 "folder",
    "Версия":                "version",
    "Текст":                 "text",
    "Дата":                  "date",
    "Категория":             "category",
    "Теги":                  "tags",
}


SECTION_TO_SHEET = {
    "programs": "Программы",
    "books":    "Книги",
    "news":     "Новости",
    "articles": "Статьи",
    "movies":   "Фильмы",
    "music":    "Музыка",
    "games":    "Игры",
    "misc":     "Разное",
}


# ─── Валидация листов Google Sheets (п. 1.12) ───
# Ключевые колонки, наличие которых проверяем в header row.
# Проверка нестрогая: достаточно, чтобы нашлась хотя бы одна из групп.
REQUIRED_COLUMN_GROUPS = [
    # Название — обязательно (без него запись не построить)
    ["Название", "Title", "название", "title"],
    # Ссылка на файл — обязательно
    ["Ссылка для скачивания", "Ссылка", "download_link", "link"],
]


# ============================================================
# УТИЛИТЫ
# ============================================================

def normalize(s) -> str:
    """Нормализация строки для сравнения названий."""
    if not s:
        return ""
    return (
        str(s).strip().lower()
        .replace("ё", "е")
        .replace(" ", "")
        .replace("-", "")
        .replace("_", "")
    )


# ============================================================
# АВТОРИЗАЦИЯ GOOGLE
# ============================================================

def _load_credentials_dict() -> dict:
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"GOOGLE_CREDENTIALS_JSON содержит невалидный JSON: {e}"
            )

    if os.path.exists(CREDENTIALS_FILE):
        with open(CREDENTIALS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    raise RuntimeError(
        "Не найдены credentials ни в GOOGLE_CREDENTIALS_JSON, "
        f"ни в файле '{CREDENTIALS_FILE}'."
    )


def get_gspread_client():
    creds_dict = _load_credentials_dict()
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


# ============================================================
# ПРОВЕРКА ЗДОРОВЬЯ GOOGLE SHEETS (п. 1.12)
# ============================================================

def _try_notify_telegram(text: str) -> bool:
    """
    Пытается отправить сообщение в Telegram через notify.py.
    Если notify.py нет или переменные окружения не заданы — тихо игнорирует.
    Возвращает True при успехе.
    """
    try:
        from notify import notify_telegram
    except ImportError:
        return False
    try:
        return bool(notify_telegram(text))
    except Exception:
        return False


def notify_sheets_health_issue(health: dict, script_name: str = "sync"):
    """
    Отправляет алерт в Telegram по результату check_sheets_health().

    :param health: dict из check_sheets_health() — {"ok": bool, "errors": [...], "warnings": [...]}
    :param script_name: имя скрипта для заголовка сообщения
    """
    if health.get("ok"):
        return

    errors   = health.get("errors", []) or []
    warnings = health.get("warnings", []) or []

    lines = [f"❌ {script_name}: проверка Google Sheets не пройдена", ""]
    if errors:
        lines.append("Ошибки:")
        for e in errors[:20]:
            lines.append(f"  • {e}")
    if warnings:
        lines.append("")
        lines.append("Предупреждения:")
        for w in warnings[:10]:
            lines.append(f"  • {w}")
    lines.append("")
    lines.append("Синхронизация НЕ запущена. Проверьте таблицу и повторите.")

    _try_notify_telegram("\n".join(lines))


def check_sheets_health(gs_client, spreadsheet_id: str, sections=None) -> dict:
    """
    Предполётная проверка Google Sheets перед синхронизацией.

    :param gs_client: gspread.Client (результат get_gspread_client())
    :param spreadsheet_id: str — ID таблицы
    :param sections: список разделов (dict с ключами key, label, sheet_name).
                     Если None — проверяется только доступность таблицы.
    :return: dict {
        "ok": bool,                 # True — можно продолжать
        "errors":   [str, ...],     # критичные проблемы
        "warnings": [str, ...],     # некритичные (нет колонки и т.п.)
        "spreadsheet_title": str,   # название таблицы (если открылась)
        "checked_sheets": [str],    # список листов, которые проверили
    }

    Алгоритм:
      1. Открыть таблицу по ID. Если не открылась → error, выход.
      2. Если sections заданы — для каждого раздела:
         a. Найти лист по sheet_name (или label).
         b. Прочитать header row (row_values(1)).
         c. Проверить, что header не пустой (хотя бы одна колонка).
         d. Проверить наличие хотя бы одной колонки из каждой группы
            в REQUIRED_COLUMN_GROUPS.
      3. Собрать errors и warnings.
      4. ok = непустой результат без errors.
    """
    result = {
        "ok": False,
        "errors": [],
        "warnings": [],
        "spreadsheet_title": "",
        "checked_sheets": [],
    }

    # ─── 1. Открытие таблицы ───
    sh = None
    try:
        sh = gs_client.open_by_key(spreadsheet_id)
        result["spreadsheet_title"] = sh.title or ""
    except gspread.exceptions.SpreadsheetNotFound:
        result["errors"].append(
            f"Таблица с ID '{spreadsheet_id}' не найдена (SpreadsheetNotFound)."
        )
        return result
    except Exception as e:
        result["errors"].append(
            f"Не удалось открыть таблицу: {type(e).__name__}: {e}"
        )
        return result

    # ─── 2. Если разделы не переданы — базовая проверка пройдена ───
    if not sections:
        result["ok"] = True
        return result

    # ─── 3. Проверка листов по разделам ───
    # Кэш уже проверенных листов, чтобы не дёргать API дважды
    seen_sheets = set()

    for section in sections:
        if not isinstance(section, dict):
            continue

        key        = section.get("key") or "?"
        label      = section.get("label") or key
        sheet_name = section.get("sheet_name") or label

        if not sheet_name:
            result["errors"].append(
                f"[{key}] Не задано имя листа (sheet_name)."
            )
            continue

        # Пропускаем уже проверенный лист (два раздела могут указывать на один лист)
        if sheet_name in seen_sheets:
            continue
        seen_sheets.add(sheet_name)

        # ─── 3a. Лист существует? ───
        try:
            ws = sh.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            result["errors"].append(
                f"[{key}] Лист «{sheet_name}» не найден в таблице."
            )
            continue
        except Exception as e:
            result["errors"].append(
                f"[{key}] Ошибка доступа к листу «{sheet_name}»: "
                f"{type(e).__name__}: {e}"
            )
            continue

        result["checked_sheets"].append(sheet_name)

        # ─── 3b. Header row не пустая? ───
        try:
            header = ws.row_values(1)
        except Exception as e:
            result["errors"].append(
                f"[{key}] Не удалось прочитать header листа «{sheet_name}»: "
                f"{type(e).__name__}: {e}"
            )
            continue

        if not header or not any((h or "").strip() for h in header):
            result["errors"].append(
                f"[{key}] Лист «{sheet_name}»: пустая header row "
                f"(первая строка без заголовков)."
            )
            continue

        # ─── 3c. Ключевые колонки на месте? ───
        header_lower = [(h or "").strip().lower() for h in header]

        for group in REQUIRED_COLUMN_GROUPS:
            group_lower = [c.strip().lower() for c in group]
            found = any(c in header_lower for c in group_lower)
            if not found:
                # Формируем читаемое имя группы — берём первый вариант
                human = group[0]
                result["errors"].append(
                    f"[{key}] Лист «{sheet_name}»: не найдена колонка "
                    f"«{human}» (варианты: {', '.join(group)})."
                )

    # ─── 4. Итоговый статус ───
    result["ok"] = len(result["errors"]) == 0
    return result


def print_sheets_health(health: dict):
    """
    Печатает отчёт проверки в stdout для логов GitHub Actions.
    """
    print("=" * 60)
    print("=== Проверка здоровья Google Sheets ===")
    print("=" * 60)

    if health.get("spreadsheet_title"):
        print(f"  Таблица: {health['spreadsheet_title']}")
    checked = health.get("checked_sheets") or []
    if checked:
        print(f"  Проверено листов: {len(checked)}")
        for s in checked:
            print(f"    • {s}")

    errors   = health.get("errors", []) or []
    warnings = health.get("warnings", []) or []

    if errors:
        print("\n  Ошибки:")
        for e in errors:
            print(f"    ✗ {e}")
    if warnings:
        print("\n  Предупреждения:")
        for w in warnings:
            print(f"    ⚠ {w}")

    if health.get("ok"):
        print("\n  ✓ Проверка пройдена. Можно начинать синхронизацию.")
    else:
        print(f"\n  ✗ Проверка не пройдена ({len(errors)} ошибок).")

    print("=" * 60)
