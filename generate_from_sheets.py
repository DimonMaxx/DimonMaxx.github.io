# generate_from_sheets.py
# Google Sheets → JSON + sitemap.xml.
# Разделы читаются из Supabase (site_sections, is_active = true),
# поэтому новые разделы, добавленные через админ-панель,
# генерируются автоматически без правки этого файла.
#
# Поддерживает SYNC_SECTIONS=programs,music — генерирует JSON только для
# перечисленных разделов (для селективной синхронизации).
#
# Поддерживает скрытие записей через Supabase-таблицу hidden_items:
# строки, у которых (folder, title) в hidden_items, НЕ попадают в JSON.
#
# Генерирует sitemap.xml (главная + разделы) для SEO.
#
# Устойчив к «дубликатам заголовков» и «хвостам» старых колонок:
# не использует get_all_records(), а читает значения напрямую.
#
# Стабильный file_id:
#   В каждый item добавляется поле file_id = slugify(title).
#   Оно фиксируется в JSON и больше не пересчитывается на фронте.
#
# Валидация описаний (п. 1.6):
#   Записи с description короче MIN_DESCRIPTION_LENGTH символов
#   НЕ отбрасываются, но собираются в отчёт:
#     - в stdout
#     - в $GITHUB_STEP_SUMMARY (если задан)
#   Порог задаётся через env MIN_DESCRIPTION_LENGTH (по умолчанию 20).
#   Отключить проверку: MIN_DESCRIPTION_LENGTH=0

import os
import re
import sys
import json
import datetime
import traceback

import pandas as pd
import gspread

from common import (
    SPREADSHEET_ID,
    COLUMN_MAPPING as BASE_COLUMN_MAPPING,
    get_gspread_client,
)

try:
    from supabase import create_client as supa_create_client
except ImportError:
    supa_create_client = None


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://rmoonebbvpmvthvpcmpt.supabase.co",
)
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

SITE_BASE_URL = os.environ.get(
    "SITE_BASE_URL",
    "https://dimonmaxx.github.io",
).rstrip("/")

_raw_sync_sections = os.environ.get("SYNC_SECTIONS", "").strip()
SYNC_SECTIONS_FILTER = [
    s.strip() for s in _raw_sync_sections.split(",") if s.strip()
] if _raw_sync_sections else []

# Порог длины описания для предупреждения (символов).
# 0 = отключить проверку.
try:
    MIN_DESCRIPTION_LENGTH = int(os.environ.get("MIN_DESCRIPTION_LENGTH", "20"))
except ValueError:
    MIN_DESCRIPTION_LENGTH = 20
if MIN_DESCRIPTION_LENGTH < 0:
    MIN_DESCRIPTION_LENGTH = 0

GITHUB_STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")


# ============================================================
# РАСШИРЕННЫЙ МАППИНГ RU → EN
# ============================================================

_EXTRA_RU_TO_EN = {
    "Исполнитель":  "artist",
    "Год":          "year",
    "Платформа":    "platform",
    "Дата":         "date",
    "Категория":    "category",
    "Теги":         "tags",
    "Текст":        "text",
    "Файл":         "file_name",
    "Пользователь": "username",
    "Дата и время": "downloaded_at",
}

RU_TO_EN = dict(BASE_COLUMN_MAPPING)
for ru, en in _EXTRA_RU_TO_EN.items():
    RU_TO_EN.setdefault(ru, en)

EN_TO_RU = {}
for ru, en in RU_TO_EN.items():
    EN_TO_RU.setdefault(en, []).append(ru)

EN_TO_RU.setdefault("body", []).extend(EN_TO_RU.get("text", []))


# ============================================================
# SLUGIFY (совпадает с MF.slugify на фронте)
# ============================================================

def slugify(text):
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ\s\-]", "", s)
    s = s.strip().lower()
    s = re.sub(r"[\s\-]+", "-", s)
    return s


# ============================================================
# SUPABASE
# ============================================================

def _get_supabase_client():
    if not supa_create_client:
        return None
    if not SUPABASE_SERVICE_KEY:
        return None
    try:
        return supa_create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as e:
        print(f"[!] Ошибка создания Supabase-клиента: {e}")
        return None


def load_active_sections():
    client = _get_supabase_client()
    if client is None:
        print("[!] Supabase-клиент недоступен.")
        return []
    try:
        resp = (
            client.table("site_sections")
            .select("key,label,icon,handler_type,yandex_url,yandex_path,"
                    "sheet_name,json_path,container,columns,folderable,"
                    "is_active,sort_order")
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[!] Ошибка загрузки разделов из Supabase: {e}")
        traceback.print_exc()
        return []


def load_hidden_items(section_key):
    client = _get_supabase_client()
    if client is None:
        return set()
    try:
        resp = (
            client.table("hidden_items")
            .select("folder,title")
            .eq("section_key", section_key)
            .execute()
        )
        hidden = set()
        for row in resp.data or []:
            folder = (row.get("folder") or "").strip().lower()
            title  = (row.get("title")  or "").strip().lower()
            if title:
                hidden.add((folder, title))
        return hidden
    except Exception as e:
        print(f"  [!] hidden_items недоступна для '{section_key}': {e}")
        return set()


# ============================================================
# УТИЛИТЫ
# ============================================================

def _is_empty(value):
    if value is None:
        return True
    try:
        if pd.isna(value):
            return True
    except (TypeError, ValueError):
        pass
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _read_records_safe(worksheet, headers):
    try:
        all_values = worksheet.get_all_values()
    except Exception as e:
        print(f"  ОШИБКА чтения листа: {e}")
        return None

    if not all_values:
        return []

    raw_header = all_values[0]

    positions = {}
    for want_idx, want in enumerate(headers):
        want_clean = want.strip()
        pos = None
        for i, h in enumerate(raw_header):
            if (h or "").strip().lower() == want_clean.lower():
                pos = i
                break
        if pos is None:
            for i, h in enumerate(raw_header):
                if want_clean.lower() in (h or "").strip().lower():
                    pos = i
                    break
        positions[want] = pos

    records = []
    for row in all_values[1:]:
        rec = {}
        for want, pos in positions.items():
            if pos is None or pos >= len(row):
                rec[want] = ""
            else:
                rec[want] = row[pos]
        records.append(rec)
    return records


def row_to_item(row, columns=None):
    """
    Преобразует строку Sheets (RU-заголовки) в JSON-объект (EN-ключи).
    Добавляет стабильный file_id = slugify(title).
    """
    item = {}
    target_keys = [k for k in (columns or []) if k]
    if not target_keys:
        target_keys = list(EN_TO_RU.keys())

    for en_key in target_keys:
        value = None
        for ru_col in EN_TO_RU.get(en_key, []):
            if ru_col in row and not _is_empty(row[ru_col]):
                value = row[ru_col]
                break
        if _is_empty(value) and en_key in row and not _is_empty(row[en_key]):
            value = row[en_key]
        if _is_empty(value):
            continue
        if en_key in ("text", "body", "description"):
            item[en_key] = str(value)
        else:
            item[en_key] = str(value).strip()

    if item.get("title"):
        item["file_id"] = slugify(item["title"])

    return item


# ============================================================
# ВАЛИДАЦИЯ ОПИСАНИЙ
# ============================================================

def _check_description_length(item):
    """
    Возвращает длину описания (символов, без учёта крайних пробелов).
    Если description отсутствует — 0.
    """
    desc = item.get("description")
    if not desc:
        # Проверяем также body и text (в редких разделах используется body)
        desc = item.get("body") or item.get("text") or ""
    return len(str(desc).strip())


# ============================================================
# ГЕНЕРАЦИЯ JSON
# ============================================================

def generate_json_for_section(worksheet, json_path, columns=None,
                              headers=None, hidden_set=None):
    """
    Возвращает dict:
      {
        "count": <int>,                # сколько записей записано
        "short_descs": [               # записи с коротким описанием
            {"title": "...", "length": 8, "file_id": "..."},
            ...
        ],
      }
    или None при критической ошибке.
    """
    if hidden_set is None:
        hidden_set = set()

    print(f"  Лист:    {worksheet.title}")
    print(f"  JSON:    {json_path}")
    if hidden_set:
        print(f"  Скрытых: {len(hidden_set)} (будут пропущены)")

    dir_part = os.path.dirname(json_path) or "."
    os.makedirs(dir_part, exist_ok=True)

    if headers is None:
        headers = []
        for key in columns or []:
            variants = EN_TO_RU.get(key, [])
            if variants:
                headers.append(variants[0])
            else:
                headers.append(key)
        if "Ссылка для скачивания" not in headers:
            headers.append("Ссылка для скачивания")

    records = _read_records_safe(worksheet, headers)
    if records is None:
        return None
    if not records:
        print("  Лист пуст → записываем []")
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ОШИБКА записи JSON: {e}")
            return None
        return {"count": 0, "short_descs": []}

    json_data = []
    skipped_no_title = 0
    skipped_hidden = 0
    short_descs = []

    for row in records:
        item = row_to_item(row, columns)
        if not item.get("title"):
            skipped_no_title += 1
            continue

        if hidden_set:
            folder_val = (item.get("folder") or "").strip().lower()
            title_val  = (item.get("title")  or "").strip().lower()
            if (folder_val, title_val) in hidden_set:
                skipped_hidden += 1
                continue

        # ─── Валидация описания ───
        if MIN_DESCRIPTION_LENGTH > 0:
            desc_len = _check_description_length(item)
            if desc_len < MIN_DESCRIPTION_LENGTH:
                short_descs.append({
                    "title":   item.get("title", ""),
                    "length":  desc_len,
                    "file_id": item.get("file_id", ""),
                })

        json_data.append(item)

    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  ОШИБКА записи JSON: {e}")
        return None

    msg = f"  ✓ Записано: {len(json_data)} записей"
    extras = []
    if skipped_no_title:
        extras.append(f"без title: {skipped_no_title}")
    if skipped_hidden:
        extras.append(f"скрытых: {skipped_hidden}")
    if short_descs:
        extras.append(f"коротких описаний: {len(short_descs)}")
    if extras:
        msg += " (пропущено — " + ", ".join(extras) + ")"
    print(msg)

    if json_data:
        sample_keys = list(json_data[0].keys())
        preview = ", ".join(sample_keys[:8])
        if len(sample_keys) > 8:
            preview += ", ..."
        print(f"    Ключи: {preview}")

    return {"count": len(json_data), "short_descs": short_descs}


# ============================================================
# ГЕНЕРАЦИЯ SITEMAP.XML
# ============================================================

def generate_sitemap(sections):
    static_pages = [
        {"loc": "/index.html", "changefreq": "daily",  "priority": "1.0"},
        {"loc": "/forum.html", "changefreq": "weekly", "priority": "0.7"},
    ]

    section_pages = []
    for s in sections:
        key = s.get("key")
        if not key:
            continue
        section_pages.append({
            "loc":        f"/#{key}",
            "changefreq": "daily",
            "priority":   "0.9",
        })

    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for page in static_pages + section_pages:
        lines.append("  <url>")
        lines.append(f"    <loc>{SITE_BASE_URL}{page['loc']}</loc>")
        lines.append(f"    <lastmod>{today}</lastmod>")
        lines.append(f"    <changefreq>{page['changefreq']}</changefreq>")
        lines.append(f"    <priority>{page['priority']}</priority>")
        lines.append("  </url>")

    lines.append("</urlset>")

    try:
        with open("sitemap.xml", "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        total = len(static_pages) + len(section_pages)
        print(f"\n=== sitemap.xml ===")
        print(f"  ✓ Создан: {total} URL (base: {SITE_BASE_URL})")
    except Exception as e:
        print(f"  [!] Ошибка sitemap.xml: {e}")


# ============================================================
# ОТЧЁТ О КОРОТКИХ ОПИСАНИЯХ
# ============================================================

def _append_github_summary(text):
    """
    Пишет текст в $GITHUB_STEP_SUMMARY (если задан).
    Используется для отображения отчёта прямо в GitHub Actions.
    """
    if not GITHUB_STEP_SUMMARY:
        return
    try:
        with open(GITHUB_STEP_SUMMARY, "a", encoding="utf-8") as f:
            f.write(text)
    except Exception:
        pass


def print_short_desc_report(sections_stats):
    """
    :param sections_stats: список dict:
        {"key": str, "label": str, "short_descs": [{"title", "length", "file_id"}]}
    """
    total_short = sum(len(s["short_descs"]) for s in sections_stats)
    if total_short == 0:
        return

    print("\n" + "=" * 60)
    print("=== ВАЛИДАЦИЯ ОПИСАНИЙ ===")
    print(f"Порог: описание < {MIN_DESCRIPTION_LENGTH} символов")
    print(f"Найдено записей с коротким описанием: {total_short}")
    print("=" * 60)

    md_lines = []
    md_lines.append(f"## Валидация описаний\n")
    md_lines.append(f"- Порог: **< {MIN_DESCRIPTION_LENGTH} символов**")
    md_lines.append(f"- Найдено записей: **{total_short}**\n")

    for s in sections_stats:
        if not s["short_descs"]:
            continue
        print(f"\n{s['label']} ({s['key']}):")
        md_lines.append(f"### {s['label']} (`{s['key']}`)\n")
        md_lines.append("| Название | Длина | file_id |")
        md_lines.append("|----------|-------|---------|")

        for item in s["short_descs"]:
            title  = item["title"] or "(без названия)"
            length = item["length"]
            fid    = item["file_id"]
            print(f"  • {title} — {length} симв.")
            md_lines.append(f"| {title} | {length} | `{fid}` |")

        md_lines.append("")

    _append_github_summary("\n".join(md_lines) + "\n")


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("generate_from_sheets.py — старт")
    print("=" * 60)
    print(f"SITE_BASE_URL = {SITE_BASE_URL}")
    print(f"MIN_DESCRIPTION_LENGTH = {MIN_DESCRIPTION_LENGTH}"
          + (" (отключено)" if MIN_DESCRIPTION_LENGTH == 0 else ""))

    if SYNC_SECTIONS_FILTER:
        print(f"SYNC_SECTIONS_FILTER = {SYNC_SECTIONS_FILTER}")
    else:
        print("SYNC_SECTIONS_FILTER = (все активные разделы)")

    if gspread is None:
        print("[!] gspread не установлен.")
        sys.exit(1)

    print("\nЗагрузка разделов из Supabase (site_sections)...")
    sections = load_active_sections()
    if not sections:
        print("[!] Нет активных разделов — завершаю.")
        sys.exit(0)

    sections_for_generation = sections
    if SYNC_SECTIONS_FILTER:
        before = len(sections)
        sections_for_generation = [
            s for s in sections if s.get("key") in SYNC_SECTIONS_FILTER
        ]
        print(f"  [i] SYNC_SECTIONS отфильтровал "
              f"{len(sections_for_generation)} из {before} разделов")
        if not sections_for_generation:
            print("[!] Ни один раздел не попал под фильтр — завершаю.")
            sys.exit(0)

    print(f"  Получено разделов: {len(sections_for_generation)}")
    for s in sections_for_generation:
        print(
            f"    • {s.get('key'):<12} "
            f"→ лист «{s.get('sheet_name') or '—'}», "
            f"JSON «{s.get('json_path') or '—'}»"
        )

    print("\nПодключение к Google Sheets...")
    try:
        gc = get_gspread_client()
    except Exception as e:
        print(f"[!] Не удалось авторизоваться: {e}")
        traceback.print_exc()
        sys.exit(1)

    try:
        sh = gc.open_by_key(SPREADSHEET_ID)
        print(f"  Таблица открыта: {sh.title}")
    except gspread.exceptions.SpreadsheetNotFound:
        print(f"[!] Таблица с ID '{SPREADSHEET_ID}' не найдена.")
        sys.exit(1)
    except Exception as e:
        print(f"[!] Ошибка открытия таблицы: {e}")
        traceback.print_exc()
        sys.exit(1)

    total_ok = 0
    total_records = 0
    failed = []
    sections_stats = []

    for section in sections_for_generation:
        key = section.get("key") or "?"
        label = section.get("label") or key
        sheet_name = section.get("sheet_name") or label
        json_path = section.get("json_path")
        columns = section.get("columns") or []

        print(f"\n=== Раздел: {label} ({key}) ===")

        if not json_path:
            print("  [!] json_path не задан → пропуск.")
            failed.append((key, "нет json_path"))
            continue

        hidden_set = load_hidden_items(key)

        try:
            worksheet = sh.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"  [!] Лист «{sheet_name}» не найден → пропуск.")
            failed.append((key, f"лист «{sheet_name}» не найден"))
            continue
        except Exception as e:
            print(f"  [!] Ошибка доступа к листу: {e}")
            failed.append((key, str(e)))
            continue

        result = generate_json_for_section(
            worksheet, json_path, columns, hidden_set=hidden_set
        )
        if result is not None:
            total_ok += 1
            total_records += result["count"]
            sections_stats.append({
                "key":         key,
                "label":       label,
                "short_descs": result["short_descs"],
            })
        else:
            failed.append((key, "ошибка генерации"))

    try:
        generate_sitemap(sections)
    except Exception as e:
        print(f"[!] Ошибка генерации sitemap: {e}")
        traceback.print_exc()

    # ─── Отчёт по коротким описаниям ───
    print_short_desc_report(sections_stats)

    print("\n" + "=" * 60)
    print(f"Обработано разделов:  {total_ok} из {len(sections_for_generation)}")
    print(f"Всего записей:        {total_records}")
    if failed:
        print(f"\nПроблемные разделы ({len(failed)}):")
        for key, reason in failed:
            print(f"  • {key}: {reason}")
    print("=" * 60)

    if total_ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
