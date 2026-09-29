#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
terabox_sync.py
Синхронизация TeraBox → Google Sheets.

Полностью независимый скрипт. Не использует и не изменяет логику
yandex_disk_sync.py. Обрабатывает только те разделы из site_sections,
у которых в yandex_url указан домен terabox.com или 1024terabox.com.

Для аутентификации нужен cookie 'ndus' из аккаунта TeraBox владельца файлов.
Передаётся через переменную окружения TERABOX_COOKIE.

Разделы с другими доменами (yandex.ru и т.д.) ИГНОРИРУЮТСЯ.
"""

import os
import sys
import json
import time
import datetime
import traceback

import gspread
import requests
from google.oauth2.service_account import Credentials

try:
    from supabase import create_client as supa_create_client
except ImportError:
    supa_create_client = None

try:
    from TeraboxDL import TeraboxDL
except ImportError:
    TeraboxDL = None


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "НаполнениеСайта")

SUPABASE_URL = "https://rmoonebbvpmvthvpcmpt.supabase.co"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE", "")

# Домены, которые обрабатывает этот скрипт
TERABOX_DOMAINS = ("terabox.com", "1024terabox.com")

# Наследуем поведение от yandex_disk_sync для единообразия
PRESERVE_USER_EDITS = os.environ.get("PRESERVE_USER_EDITS", "1") == "1"
BACKUP_BEFORE_SYNC  = os.environ.get("BACKUP_BEFORE_SYNC", "1") == "1"
BACKUP_KEEP_COUNT   = int(os.environ.get("BACKUP_KEEP_COUNT", "3"))

_raw_sync_sections = os.environ.get("SYNC_SECTIONS", "").strip()
SYNC_SECTIONS_FILTER = [
    s.strip() for s in _raw_sync_sections.split(",") if s.strip()
] if _raw_sync_sections else []

# Соответствие ключей (как в yandex_disk_sync.py) — чтобы JSON-файлы
# генерировались одинаково, независимо от источника.
RU_TO_EN = {
    "Название":              "title",
    "Автор":                 "author",
    "Исполнитель":           "artist",
    "Год":                   "year",
    "Описание":              "description",
    "Формат":                "format",
    "Размер (МБ)":           "size",
    "Ссылка для скачивания": "download_link",
    "Обложка":               "cover",
    "Папка":                 "folder",
    "Версия":                "version",
    "Платформа":             "platform",
}
EN_TO_RU = {v: k for k, v in RU_TO_EN.items()}

# Колонки, которые перезаписываются всегда (не сохраняют ручные правки)
ALWAYS_UPDATE_HEADERS = {
    "Ссылка для скачивания", "Ссылка",
    "Размер (МБ)", "Размер",
    "Формат",
    "download_link", "link", "size", "format",
}

TITLE_HEADER_CANDIDATES = ("Название", "название", "Title", "title")


# ============================================================
# ДИАГНОСТИКА
# ============================================================

class Diag:
    def __init__(self, section_label=""):
        self.section_label = section_label
        self.found     = 0
        self.kept      = 0
        self.updated   = 0
        self.added     = 0
        self.preserved_edits = 0
        self.unchanged_rows  = 0
        self.orphans_found   = 0
        self.backup_name     = ""
        self.errors    = []

    def report(self):
        print("\n  ── ДИАГНОСТИКА ──")
        print(f"  Найдено файлов:        {self.found}")
        print(f"  Оставлено к записи:    {self.kept}")
        print(f"  Обновлено строк:       {self.updated}")
        print(f"  Добавлено строк:       {self.added}")
        if self.preserved_edits:
            print(f"  Сохранено ручных правок: {self.preserved_edits}")
        if self.unchanged_rows:
            print(f"  Без изменений:         {self.unchanged_rows}")
        if self.orphans_found:
            print(f"  Осиротевших строк:     {self.orphans_found}")
        if self.backup_name:
            print(f"  Резервная копия:       {self.backup_name}")
        if self.errors:
            print(f"  Ошибок:                {len(self.errors)}")
            for e in self.errors[:5]:
                print(f"    - {e}")
        print("  ───────────────────\n")


# ============================================================
# SUPABASE — читаем разделы
# ============================================================

def load_sections_from_supabase():
    if not supa_create_client:
        print("[!] supabase-py не установлен.")
        return []
    if not SUPABASE_SERVICE_KEY:
        print("[!] SUPABASE_SERVICE_ROLE_KEY не задан.")
        return []
    try:
        client = supa_create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        resp = (
            client.table("site_sections")
            .select("key,label,icon,handler_type,yandex_url,yandex_path,"
                    "sheet_name,json_path,container,columns,folderable,"
                    "is_active,manual_override,sort_order,strip_prefix_mode")
            .eq("is_active", True)
            .order("sort_order")
            .execute()
        )
        return resp.data or []
    except Exception as e:
        print(f"[!] Ошибка загрузки разделов из Supabase: {e}")
        return []


def is_terabox_url(url):
    if not url:
        return False
    return any(d in url.lower() for d in TERABOX_DOMAINS)


# ============================================================
# GOOGLE SHEETS — копии функций из yandex_disk_sync.py
# (сделаны локально, чтобы не импортировать главный модуль)
# ============================================================

def get_gspread_client():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON не задан")
    creds_dict = json.loads(creds_json)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)


def open_spreadsheet(gs_client):
    if SPREADSHEET_ID:
        return gs_client.open_by_key(SPREADSHEET_ID)
    return gs_client.open(SPREADSHEET_NAME)


def get_or_create_sheet(sh, name):
    try:
        return sh.worksheet(name)
    except gspread.WorksheetNotFound:
        print(f"  [!] Лист '{name}' не найден, создаю...")
        return sh.add_worksheet(title=name, rows=2000, cols=12)


def _col_letter(n):
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def ensure_headers(sheet, headers):
    """Полностью перезаписывает первую строку до максимальной ширины листа."""
    try:
        current = sheet.row_values(1)
    except Exception:
        current = []

    need_update = False
    if len(current) != len(headers):
        need_update = True
    else:
        for i, h in enumerate(headers):
            if (current[i] or "").strip() != h.strip():
                need_update = True
                break
    if not need_update:
        return

    try:
        all_values = sheet.get_all_values()
        max_cols = max((len(r) for r in all_values), default=len(headers))
    except Exception:
        max_cols = len(headers)
    max_cols = max(max_cols, len(headers))

    new_row = list(headers) + [""] * (max_cols - len(headers))
    end_col_letter = _col_letter(max_cols - 1)
    range_a1 = f"A1:{end_col_letter}1"
    try:
        sheet.update(values=[new_row], range_name=range_a1,
                     value_input_option="USER_ENTERED")
        print(f"    [+] Обновлены заголовки: {headers} "
              f"(очищено до {max_cols} колонок)")
    except Exception as e:
        print(f"    [!] Заголовки: {e}")


def load_sheet_snapshot(sheet):
    try:
        rows = sheet.get_all_values()
    except Exception as e:
        print(f"    [!] Не удалось прочитать лист: {e}")
        return [], {}

    if not rows:
        return [], {}

    header = [h.strip().lower() for h in rows[0]]
    idx = None
    for cand in ("ссылка для скачивания", "ссылка",
                 "download_link", "link"):
        if cand in header:
            idx = header.index(cand)
            break

    existing = {}
    if idx is not None and len(rows) >= 2:
        for i, r in enumerate(rows[1:], start=2):
            if len(r) > idx and r[idx].strip():
                existing[r[idx].strip()] = {
                    "row":    i,
                    "values": list(r),
                }
    return rows, existing


def merge_row(old_values, new_values, headers, always_update=None):
    if always_update is None:
        always_update = ALWAYS_UPDATE_HEADERS
    if not PRESERVE_USER_EDITS:
        return list(new_values)
    result = []
    n = len(headers)
    for i in range(n):
        header = headers[i]
        old_val = old_values[i] if i < len(old_values) else ""
        new_val = new_values[i] if i < len(new_values) else ""
        old_s = str(old_val).strip() if old_val is not None else ""
        new_s = str(new_val).strip() if new_val is not None else ""
        if header in always_update:
            result.append(new_s if new_s else old_s)
        else:
            result.append(old_val if old_s else new_val)
    return result


def backup_sheet(sh, worksheet, section_key, all_values, max_backups=None):
    if not all_values:
        return None
    if max_backups is None:
        max_backups = BACKUP_KEEP_COUNT

    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"_backup_{section_key}_{ts}"

    max_cols = max((len(r) for r in all_values), default=1)
    max_rows = len(all_values)

    try:
        backup = sh.add_worksheet(
            title=backup_name,
            rows=max(max_rows + 10, 100),
            cols=max(max_cols + 2, 10),
        )
        backup.update(values=all_values, range_name="A1",
                      value_input_option="USER_ENTERED")
        print(f"    [b] Backup создан: {backup_name}")
    except Exception as e:
        print(f"    [!] Backup: ошибка создания: {e}")
        return None

    try:
        prefix = f"_backup_{section_key}_"
        backups = [ws for ws in sh.worksheets() if ws.title.startswith(prefix)]
        backups.sort(key=lambda w: w.title, reverse=True)
        for old in backups[max_backups:]:
            try:
                sh.del_worksheet(old)
            except Exception:
                pass
    except Exception:
        pass

    return backup_name


def batch_update_rows(sheet, updates):
    if not updates:
        return 0
    total = len(updates)
    updated = 0
    chunk = 100
    for i in range(0, total, chunk):
        part = updates[i:i + chunk]
        try:
            sheet.batch_update(part, value_input_option="USER_ENTERED")
            updated += len(part)
            print(f"    [+] Обновлено {updated}/{total}")
        except Exception as e:
            print(f"    [!] batch_update {i//chunk}: {e}")
        time.sleep(0.5)
    return updated


def append_rows_safe(sheet, rows, batch_size=200):
    added = 0
    failed = 0
    total = len(rows)
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        for attempt in range(3):
            try:
                sheet.append_rows(batch, value_input_option="USER_ENTERED")
                added += len(batch)
                print(f"    [+] Записано {added}/{total}")
                break
            except Exception as e:
                print(f"    [!] Попытка {attempt+1}: {e}")
                time.sleep(2 * (attempt + 1))
        else:
            failed += len(batch)
        time.sleep(1)
    return added, failed


def headers_from_columns(columns):
    headers = []
    for key in columns or []:
        ru = EN_TO_RU.get(key)
        if ru:
            headers.append(ru)
    if "Ссылка для скачивания" not in headers:
        headers.append("Ссылка для скачивания")
    return headers


def _row_from_record(record, headers):
    row = []
    for ru in headers:
        en = RU_TO_EN.get(ru, ru)
        row.append(record.get(en, ""))
    return row


def find_orphan_rows(existing_index, rows, headers, link_idx):
    new_links = set()
    for row in rows:
        if link_idx < len(row):
            v = str(row[link_idx]).strip()
            if v:
                new_links.add(v)

    title_idx = None
    for cand in TITLE_HEADER_CANDIDATES:
        if cand in headers:
            title_idx = headers.index(cand)
            break

    orphans = []
    for link, info in existing_index.items():
        if link in new_links:
            continue
        values = info["values"]
        title = ""
        if title_idx is not None and title_idx < len(values):
            title = str(values[title_idx]).strip()
        padded = list(values) + [""] * max(0, len(headers) - len(values))
        orphans.append({
            "row":    info["row"],
            "title":  title,
            "link":   link,
            "values": padded[:len(headers)],
        })
    return orphans


def save_orphans_to_supabase(section_key, section_label,
                             sheet_name, orphans, headers=None):
    if not supa_create_client or not SUPABASE_SERVICE_KEY:
        return
    try:
        client = supa_create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
        payload = {
            "section_key":   section_key,
            "section_label": section_label,
            "sheet_name":    sheet_name,
            "orphans":       orphans or [],
            "updated_at":    datetime.datetime.utcnow().isoformat() + "Z",
        }
        if headers is not None:
            payload["headers"] = headers
        client.table("sync_orphans").upsert(payload).execute()
    except Exception as e:
        print(f"    [!] Не удалось сохранить orphans: {e}")


# ============================================================
# TERABOX — получение файлов
# ============================================================

def _parse_filename_simple(filename):
    """Простое извлечение названия из имени файла."""
    import re
    stem = os.path.splitext(filename)[0].strip()
    stem = re.sub(r"\s+", " ", stem).strip()
    return {"title": stem}


def _format_size_mb(size_bytes):
    try:
        return str(round(int(size_bytes) / (1024 * 1024), 1))
    except Exception:
        return ""


def extract_files_from_terabox(share_url, cookie, diag):
    """
    Возвращает список записей-словарей с ключами:
        title, size, download_link, folder
    """
    if TeraboxDL is None:
        print("  [!] Библиотека TeraboxDL не установлена.")
        return []

    try:
        api = TeraboxDL(cookie)
        print(f"  [i] Запрос к TeraBox: {share_url[:70]}...")
        result = api.get_file_info(share_url)
    except Exception as e:
        print(f"  [!] Ошибка запроса TeraboxDL: {e}")
        diag.errors.append(str(e))
        return []

    if not result:
        print("  [!] Пустой ответ от TeraBox.")
        return []

    # Библиотека может вернуть:
    # 1) словарь с одним файлом {'file_name', 'download_link', 'file_size'}
    # 2) список файлов (если ссылка ведёт на папку)
    items = []
    if isinstance(result, dict):
        if "error" in result:
            print(f"  [!] TeraBox error: {result['error']}")
            return []
        items = [result]
    elif isinstance(result, list):
        items = result
    else:
        return []

    files = []
    for it in items:
        if not isinstance(it, dict):
            continue
        name = it.get("file_name") or it.get("server_filename") or ""
        dl = it.get("download_link") or it.get("dlink") or ""
        size = it.get("file_size") or it.get("size") or 0

        if not name or not dl:
            continue

        parsed = _parse_filename_simple(name)
        files.append({
            "title":         parsed["title"],
            "size":          _format_size_mb(size),
            "download_link": dl,
            "folder":        "",
            "description":   "",
            "version":       "",
        })
    return files


# ============================================================
# СИНХРОНИЗАЦИЯ ОДНОГО РАЗДЕЛА
# ============================================================

def sync_terabox_section(section, gs_client):
    label = section.get("label") or section.get("key")
    section_key = section.get("key")
    yandex_url  = section.get("yandex_url") or ""
    sheet_name  = section.get("sheet_name") or label
    columns     = section.get("columns") or ["title", "description", "download_link"]

    print(f"\n=== Раздел TeraBox: {label} ({section_key}) ===")
    print(f"Ссылка TeraBox: {yandex_url[:90]}...")
    print(f"Лист Sheets:    {sheet_name}")

    if not TERABOX_COOKIE:
        print("  [!] TERABOX_COOKIE не задан. Пропускаем раздел.")
        return

    diag = Diag(label)

    # Поддерживаем несколько ссылок через перенос строки
    urls = [u.strip() for u in yandex_url.split("\n") if u.strip()]
    all_files = []
    for u in urls:
        files = extract_files_from_terabox(u, TERABOX_COOKIE, diag)
        all_files.extend(files)

    diag.found = len(all_files)
    print(f"  Получено файлов из TeraBox: {len(all_files)}")

    headers = headers_from_columns(columns)
    rows = [_row_from_record(rec, headers) for rec in all_files]
    diag.kept = len(rows)

    # Открываем таблицу
    try:
        sh = open_spreadsheet(gs_client)
    except Exception as e:
        print(f"  [!] Не удалось открыть таблицу: {e}")
        return

    sheet = get_or_create_sheet(sh, sheet_name)
    ensure_headers(sheet, headers)

    all_values, existing = load_sheet_snapshot(sheet)
    print(f"  Существующих строк: {len(existing)}")

    link_ru = "Ссылка для скачивания"
    link_idx = headers.index(link_ru) if link_ru in headers else 0
    n_cols = len(headers)
    end_col_letter = _col_letter(n_cols - 1)

    # Сироты
    orphans = find_orphan_rows(existing, rows, headers, link_idx)
    diag.orphans_found = len(orphans)
    if orphans:
        print(f"  Осиротевших строк: {len(orphans)}")
    save_orphans_to_supabase(section_key, label, sheet_name,
                             orphans, headers)

    updates = []
    to_add = []
    preserved = 0
    unchanged = 0

    for row in rows:
        link = str(row[link_idx]).strip() if link_idx < len(row) else ""
        if not link or link not in existing:
            to_add.append(row)
            continue

        info = existing[link]
        old_values = info["values"]
        merged = merge_row(old_values, row, headers)

        old_cmp = [str(v) for v in old_values[:n_cols]]
        new_cmp = [str(v) for v in merged]
        if old_cmp == new_cmp:
            unchanged += 1
            continue

        if PRESERVE_USER_EDITS:
            for j, h in enumerate(headers):
                if h in ALWAYS_UPDATE_HEADERS:
                    continue
                ov = (old_values[j] if j < len(old_values) else "").strip()
                nv = (row[j] if j < len(row) else "").strip()
                if ov and ov != nv:
                    preserved += 1
                    break

        rng = f"A{info['row']}:{end_col_letter}{info['row']}"
        updates.append({"range": rng, "values": [merged]})

    print(f"\n    К обновлению:      {len(updates)}")
    print(f"    К добавлению:      {len(to_add)}")
    if preserved:
        print(f"    Сохранено правок:  {preserved}")
    if unchanged:
        print(f"    Без изменений:     {unchanged}")

    diag.preserved_edits = preserved
    diag.unchanged_rows  = unchanged

    if (updates or to_add) and BACKUP_BEFORE_SYNC:
        diag.backup_name = backup_sheet(sh, sheet, section_key, all_values) or ""

    if updates:
        diag.updated = batch_update_rows(sheet, updates)
    if to_add:
        added, failed = append_rows_safe(sheet, to_add)
        diag.added = added

    diag.report()


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("terabox_sync.py — старт")
    print("=" * 60)
    print(f"PRESERVE_USER_EDITS = {PRESERVE_USER_EDITS}")
    print(f"BACKUP_BEFORE_SYNC  = {BACKUP_BEFORE_SYNC}")
    print(f"TERABOX_COOKIE      = {'задан' if TERABOX_COOKIE else 'НЕ задан'}")
    if SYNC_SECTIONS_FILTER:
        print(f"SYNC_SECTIONS_FILTER = {SYNC_SECTIONS_FILTER}")

    if TeraboxDL is None:
        print("[!] Библиотека terabox-downloader не установлена.")
        print("    Добавьте её в requirements.txt и переустановите зависимости.")
        return

    if not TERABOX_COOKIE:
        print("[!] TERABOX_COOKIE не задан — ничего не делаем.")
        return

    print("\nЗагрузка разделов из Supabase...")
    sections = load_sections_from_supabase()
    if not sections:
        print("[!] Нет разделов — выходим.")
        return

    # Фильтруем только TeraBox-разделы
    terabox_sections = [s for s in sections if is_terabox_url(s.get("yandex_url", ""))]
    print(f"  Найдено TeraBox-разделов: {len(terabox_sections)}")

    if SYNC_SECTIONS_FILTER:
        before = len(terabox_sections)
        terabox_sections = [
            s for s in terabox_sections
            if s.get("key") in SYNC_SECTIONS_FILTER
        ]
        print(f"  После фильтра SYNC_SECTIONS: {len(terabox_sections)} из {before}")

    if not terabox_sections:
        print("  Нет TeraBox-разделов для синхронизации — выходим.")
        return

    for s in terabox_sections:
        print(f"    • {s.get('key')}: {s.get('label')}")

    print("\nПодключение к Google Sheets...")
    try:
        gs_client = get_gspread_client()
    except Exception as e:
        print(f"[!] Google Sheets: {e}")
        return
    print("Клиент создан.")

    for section in terabox_sections:
        try:
            sync_terabox_section(section, gs_client)
        except Exception as e:
            print(f"\n[!!!] Ошибка в разделе {section.get('key')}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("terabox_sync.py — готово!")


if __name__ == "__main__":
    main()
