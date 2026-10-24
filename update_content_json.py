#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
update_content_json.py
======================
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import base64
import hashlib
import datetime
import argparse
import traceback
import difflib
import urllib.parse
from typing import Any

import requests

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    gspread = None
    Credentials = None

try:
    from supabase import create_client as supa_create_client
except ImportError:
    supa_create_client = None

try:
    from notify import notify_telegram, notify_result
except ImportError:
    def notify_telegram(text, **kw):
        return False

    def notify_result(**kw):
        return False


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

GITHUB_OWNER = os.environ.get("STORAGE_OWNER", "DimonMaxx")
GITHUB_REPO  = os.environ.get("STORAGE_REPO",  "files")
GITHUB_TOKEN = os.environ.get("STORAGE_TOKEN", "") or os.environ.get("GITHUB_TOKEN", "")

RELEASE_PROXY_BASE = os.environ.get(
    "RELEASE_PROXY_BASE",
    "https://gh-release-proxy.macsimenkodima.workers.dev",
).rstrip("/")

SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "НаполнениеСайта")

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "https://rmoonebbvpmvthvpcmpt.supabase.co",
)
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
COVERS_BUCKET = "covers"

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://dimonmaxx.github.io").rstrip("/")

HTTP_TIMEOUT = 30
GITHUB_PER_PAGE = 100
GITHUB_API_SLEEP = 0.3

PRESERVE_USER_EDITS = os.environ.get("PRESERVE_USER_EDITS", "1") == "1"
BACKUP_BEFORE_SYNC = os.environ.get("BACKUP_BEFORE_SYNC", "1") == "1"
BACKUP_KEEP_COUNT = int(os.environ.get("BACKUP_KEEP_COUNT", "3"))
ENRICH_BOOKS = os.environ.get("ENRICH_BOOKS", "0") == "1"
PARSE_FILE_DESCRIPTIONS = os.environ.get("PARSE_FILE_DESCRIPTIONS", "0") == "1"
MIN_DESCRIPTION_LENGTH = int(os.environ.get("MIN_DESCRIPTION_LENGTH", "20"))
GITHUB_STEP_SUMMARY = os.environ.get("GITHUB_STEP_SUMMARY", "")
REPORTS_DIR = os.environ.get("REPORTS_DIR", "_reports")

FOLDER_TRANSLATIONS = {
    "plaginy": "Плагины",
    "skripty": "Скрипты",
    "makrosy": "Макросы",
    "dlya-windows-svoi": "Для windows свои",
}

SECTION_TO_SHEET_FALLBACK = {
    "programs": "Программы",
    "books":    "Книги",
    "music":    "Музыка",
    "games":    "Игры",
    "movies":   "Фильмы",
    "misc":     "Разное",
}

SECTION_CONFIG_FALLBACK = {
    "books": {
        "label": "Книги", "icon": "fa-book", "sheet_name": "Книги", "json_path": "_content/books.json",
        "container": "books-container", "folderable": True,
        "columns": ["folder", "cover", "title", "author", "description", "format", "size", "download_link"],
    },
    "programs": {
        "label": "Программы", "icon": "fa-code", "sheet_name": "Программы", "json_path": "_content/programs.json",
        "container": "programs-container", "folderable": True,
        "columns": ["folder", "title", "description", "version", "size", "download_link"],
    },
    "music": {
        "label": "Музыка", "icon": "fa-music", "sheet_name": "Музыка", "json_path": "_content/music.json",
        "container": "music-container", "folderable": True,
        "columns": ["folder", "title", "artist", "year", "size", "download_link"],
    },
    "games": {
        "label": "Игры", "icon": "fa-gamepad", "sheet_name": "Игры", "json_path": "_content/games.json",
        "container": "games-container", "folderable": False,
        "columns": ["title", "platform", "year", "description", "download_link"],
    },
    "movies": {
        "label": "Фильмы", "icon": "fa-film", "sheet_name": "Фильмы", "json_path": "_content/movies.json",
        "container": "movies-container", "folderable": False,
        "columns": ["title", "year", "description", "download_link"],
    },
    "misc": {
        "label": "Разное", "icon": "fa-ellipsis-h", "sheet_name": "Разное", "json_path": "_content/misc.json",
        "container": "misc-container", "folderable": False,
        "columns": ["title", "description", "download_link"],
    },
}

RU_TO_EN = {
    "Название": "title", "Автор": "author", "Исполнитель": "artist", "Год": "year",
    "Описание": "description", "Формат": "format", "Размер (МБ)": "size",
    "Ссылка для скачивания": "download_link", "Обложка": "cover", "Папка": "folder",
    "Версия": "version", "Платформа": "platform", "Дата": "date",
    "Категория": "category", "Теги": "tags", "Текст": "text", "Legacy": "legacy",
}
EN_TO_RU: dict[str, list[str]] = {}
for ru, en in RU_TO_EN.items():
    EN_TO_RU.setdefault(en, []).append(ru)

EXT_TO_SECTION = {
    ".fb2": "books", ".epub": "books", ".mobi": "books", ".djvu": "books", ".pdf": "books", ".rtf": "books", ".doc": "books", ".docx": "books",
    ".mp3": "music", ".flac": "music", ".wav": "music", ".ogg": "music", ".m4a": "music", ".aac": "music", ".wma": "music", ".opus": "music", ".ape": "music", ".aiff": "music", ".alac": "music",
    ".exe": "programs", ".msi": "programs", ".rar": "programs", ".zip": "programs", ".7z": "programs", ".tar": "programs", ".gz": "programs", ".xlsm": "programs", ".xlsx": "programs", ".xls": "programs", ".ods": "programs", ".odt": "programs", ".bat": "programs", ".ps1": "programs", ".sh": "programs", ".py": "programs",
    ".iso": "games", ".bin": "games",
    ".mp4": "movies", ".mkv": "movies", ".avi": "movies", ".mov": "movies", ".wmv": "movies",
}

SECTION_VOTE_THRESHOLD = 0.5

TAG_TO_SECTION = {
    "ajzek-azimov": "books", "aksenov-daniil": "books", "aleksandr-rudazov": "books",
    "alekseeva-yana": "books", "aliya-ya": "books", "andre-norton": "books",
    "andrej-kruz": "books", "andrej-lazarchuk": "books", "andzhej-sapkovskij": "books",
    "andzhej-yasinskij": "books", "arina-alison": "books", "arkadij-strugackij": "books",
    "badej": "books", "bastars-roda-demonov": "books", "batcher-dzhim": "books",
    "dmitrij-ra": "books", "dmitrij-serebryakov-novaya-zhizn": "books", "drugoj-mir": "books",
    "dzh-lokhard": "books", "dzhon-karter": "books", "egida": "books", "ezdovoj-gnom": "books",
    "glushanovskij-aleksej": "books", "gordon-dikson": "books", "inoj": "books",
    "legenda": "books", "lesovik": "books", "lisina": "books", "lorel-gamilton": "books",
    "mir-karika": "books", "nashi-tam": "books", "naslednik-dyavola": "books",
    "nepravilnyj-lekar": "books", "nik-perunov": "books", "olga-gromyko": "books",
    "pivko-aleksandr": "books", "porri-gatter": "books", "sergej-lukyanenko": "books",
    "serzh-vinterkej-egida-15-knig": "books", "shumil-pavel": "books", "sistema": "books",
    "stalker": "books", "sumerechnaya-saga": "books", "tanya-haff": "books",
    "temnaya-bashnya": "books", "temnyj-angel": "books", "vadim-panov": "books",
    "viktor-viktorov": "books", "linkin-park": "music", "skillet": "music",
    "within-temptation": "music", "adobe": "programs", "aeditor": "programs",
    "ams": "programs", "archive": "programs", "ascomp": "programs", "contact": "programs",
    "converter": "programs", "defrag": "programs", "diagnostics": "programs",
    "disc": "programs", "dlya-windows-svoi": "programs", "download": "programs",
    "file": "programs", "graphics": "programs", "hdd": "programs",
    "interface": "programs", "internet": "programs", "makrosy": "programs",
    "media": "programs", "meditor": "programs", "mso": "programs", "office": "programs",
    "optimizers": "programs", "pdf": "programs", "phone": "programs",
    "photo": "programs", "plaginy": "programs", "print": "programs", "radiotv": "programs",
    "recovery": "programs", "recscreen": "programs", "registry": "programs",
    "search": "programs", "security": "programs", "service": "programs",
    "skripty": "programs", "system": "programs", "text": "programs", "uninstall": "programs",
}

def slugify(text: str) -> str:
    if not text: return ""
    s = str(text)
    s = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ\s\-]", "", s)
    s = s.strip().lower()
    s = re.sub(r"[\s\-]+", "-", s)
    return s

def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "MyFiles-Sync/1.0"}
    if GITHUB_TOKEN: headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers

def list_all_releases() -> list[dict]:
    releases: list[dict] = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page={GITHUB_PER_PAGE}&page={page}"
        try:
            r = requests.get(url, headers=_github_headers(), timeout=HTTP_TIMEOUT)
        except Exception as e:
            print(f"[!] GitHub API недоступен: {e}")
            return releases
        if r.status_code != 200: return releases
        batch = r.json()
        if not batch: break
        releases.extend(batch)
        if len(batch) < GITHUB_PER_PAGE: break
        page += 1
        time.sleep(GITHUB_API_SLEEP)
    return releases

def build_asset_url(tag: str, filename: str) -> str:
    return f"{RELEASE_PROXY_BASE}/download/{tag}/{filename}"

def detect_section_by_assets(assets: list[dict], tag: str = "") -> str | None:
    if tag and tag in TAG_TO_SECTION: return TAG_TO_SECTION[tag]
    if not assets: return None
    votes: dict[str, int] = {}
    for a in assets:
        ext = os.path.splitext(a.get("name", ""))[1].lower()
        section = EXT_TO_SECTION.get(ext)
        if section: votes[section] = votes.get(section, 0) + 1
    if not votes: return None
    winner, winner_count = max(votes.items(), key=lambda x: x[1])
    if (winner_count / len(assets)) >= SECTION_VOTE_THRESHOLD: return winner
    return None

def get_gspread_client():
    if gspread is None or Credentials is None: raise RuntimeError("gspread / google-auth не установлены.")
    creds_dict = None
    raw_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw_json:
        try: creds_dict = json.loads(raw_json)
        except json.JSONDecodeError as e: raise RuntimeError(f"Invalid GOOGLE_CREDENTIALS_JSON: {e}")
    if creds_dict is None:
        creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        if os.path.exists(creds_file):
            with open(creds_file, "r", encoding="utf-8") as f: creds_dict = json.load(f)
    if creds_dict is None: raise RuntimeError("Не найдены Google-credentials.")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def open_spreadsheet(gs_client):
    last_err = None
    for attempt in range(4):
        try:
            if SPREADSHEET_ID: return gs_client.open_by_key(SPREADSHEET_ID)
            return gs_client.open(SPREADSHEET_NAME)
        except Exception as e:
            last_err = e
            if "500" in str(e) or "429" in str(e) or "503" in str(e):
                time.sleep(5)
                continue
            raise e
    raise last_err

def _col_letter(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def get_or_create_sheet(sh, name: str):
    try: return sh.worksheet(name)
    except gspread.WorksheetNotFound: return sh.add_worksheet(title=name, rows=2000, cols=12)

def load_sheet_snapshot(sheet) -> tuple[list[list[str]], dict[str, dict]]:
    try: rows = sheet.get_all_values()
    except Exception: return [], {}
    if not rows: return [], {}
    header = [(h or "").strip().lower() for h in rows[0]]
    link_idx = None
    for cand in ("ссылка для скачивания", "ссылка", "download_link", "link"):
        if cand in header:
            link_idx = header.index(cand)
            break
    existing: dict[str, dict] = {}
    if link_idx is not None and len(rows) >= 2:
        for i, r in enumerate(rows[1:], start=2):
            if len(r) > link_idx:
                link = (r[link_idx] or "").strip()
                if link: existing[link] = {"row": i, "values": list(r)}
    return rows, existing

def merge_row(old_values: list[str], new_values: list[str], headers: list[str], always_update: set[str] | None = None) -> list[str]:
    if always_update is None:
        always_update = {"Ссылка для скачивания", "Ссылка", "Размер (МБ)", "Размер", "Формат", "download_link", "link", "size", "format", "Legacy"}
    if not PRESERVE_USER_EDITS: return list(new_values)
    result: list[str] = []
    n = len(headers)
    for i in range(n):
        header = headers[i]
        old_val = old_values[i] if i < len(old_values) else ""
        new_val = new_values[i] if i < len(new_values) else ""
        old_s = str(old_val).strip() if old_val is not None else ""
        new_s = str(new_val).strip() if new_val is not None else ""
        if header in always_update: result.append(new_s if new_s else old_s)
        else: result.append(old_val if old_s else new_val)
    return result

def batch_update_rows(sheet, updates: list[dict]) -> int:
    if not updates: return 0
    total = len(updates)
    updated = 0
    chunk = 100
    for i in range(0, total, chunk):
        part = updates[i:i + chunk]
        try:
            time.sleep(2)
            sheet.batch_update(part, value_input_option="USER_ENTERED")
            updated += len(part)
        except Exception as e:
            print(f"    [!] batch_update chunk {i // chunk}: {e}")
    return updated

def append_rows_safe(sheet, rows: list[list[str]], batch_size: int = 50) -> tuple[int, int]:
    added, failed = 0, 0
    total = len(rows)
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        success = False
        for attempt in range(5):
            try:
                time.sleep(3)
                sheet.append_rows(batch, value_input_option="USER_ENTERED")
                added += len(batch)
                success = True
                break
            except Exception as e:
                time.sleep(10)
        if not success:
            failed += len(batch)
            print(f"    [!] Не удалось добавить {len(batch)} строк после 5 попыток")
    return added, failed

def headers_from_columns(columns: list[str]) -> list[str]:
    headers: list[str] = []
    for key in columns or []:
        ru = EN_TO_RU.get(key)
        if ru: headers.append(ru[0])
    if "Ссылка для скачивания" not in headers: headers.append("Ссылка для скачивания")
    return headers

def _row_from_record(record: dict, headers: list[str]) -> list[str]:
    row: list[str] = []
    for ru in headers:
        en = RU_TO_EN.get(ru, ru)
        row.append(record.get(en, ""))
    return row

def parse_release_link(url: str) -> tuple[str, str]:
    if not url: return None, None
    decoded = urllib.parse.unquote(url)
    parts = decoded.split('/download/')
    if len(parts) == 2:
        subparts = parts[1].split('/')
        if len(subparts) >= 2:
            tag = subparts[0]
            filename = '/'.join(subparts[1:])
            return tag, filename
    return None, None

def detect_link_source(link: str) -> str:
    if not link: return ""
    s = str(link).lower()
    if "gh-release-proxy.macsimenkodima.workers.dev" in s or "github.com" in s and "/releases/" in s:
        return "release"
    if "disk.yandex" in s or "yadi.sk" in s:
        return "yandex"
    if "terabox" in s or "1024tera" in s or "4funbox" in s or "teraboxapp" in s:
        return "terabox"
    return "other"

def bytes_to_mb(size_bytes: int | float | str | None) -> str:
    try:
        n = int(size_bytes or 0)
    except (TypeError, ValueError):
        return "0"
    if n <= 0: return "0"
    return str(round(n / (1024 * 1024), 1))

# ============================================================
# ШАГ A: GitHub Releases → Google Sheets
# ============================================================
def repo_to_sheets(gs_client, sections: list[dict], dry_run: bool, tag_filter: list[str] | None = None) -> dict:
    stats = {"sections": {}, "to_update_rows": [], "new_in_repo_rows": [], "legacy_only_rows": [], "errors": []}
    print("\n" + "=" * 60 + "\nШАГ A: GitHub Releases → Google Sheets\n" + "=" * 60)

    releases = list_all_releases()
    if not releases: return stats
    
    if tag_filter:
        tag_set = set(tag_filter)
        releases = [r for r in releases if r.get("tag_name") in tag_set]

    tag_to_section: dict[str, str] = {}
    for rel in releases:
        tag, assets = rel.get("tag_name") or "", rel.get("assets") or []
        if not tag or not assets: continue
        section = detect_section_by_assets(assets, tag)
        if section: tag_to_section[tag] = section

    by_section: dict[str, list[dict]] = {}
    for rel in releases:
        tag = rel.get("tag_name") or ""
        section = tag_to_section.get(tag)
        if section: by_section.setdefault(section, []).append(rel)

    try: sh = open_spreadsheet(gs_client)
    except Exception as e:
        stats["errors"].append(f"Не удалось открыть Google-таблицу: {e}")
        return stats

    # Строим карту всех файлов в репозитории
    repo_assets_by_tag = {}
    for tag, rels in by_section.items():
        for rel in rels:
            repo_assets_by_tag[rel.get("tag_name")] = rel.get("assets") or []

    # Здесь мы будем хранить точные имена файлов, которые уже привязаны в таблице
    matched_assets = set()

    for section in sections:
        key = section.get("key") or "?"
        label = section.get("label") or key
        if key not in by_section: continue

        sheet_name = section.get("sheet_name") or label
        columns = section.get("columns") or ["title", "description", "download_link"]
        headers = headers_from_columns(columns)

        print(f"\n  ── Раздел: {label} ({key})\n     Лист: {sheet_name}")
        try: sheet = get_or_create_sheet(sh, sheet_name)
        except Exception as e:
            stats["errors"].append(f"[{key}] Не удалось открыть лист «{sheet_name}»: {e}")
            continue

        try: all_values, existing_by_link = load_sheet_snapshot(sheet)
        except Exception as e:
            stats["errors"].append(f"[{key}] Ошибка чтения листа: {e}")
            continue

        sec_stats = {"to_update": 0, "new_in_repo": 0, "legacy_only": 0, "unchanged": 0}
        rows_for_match: list[dict] = []
        header = [(h or "").strip() for h in (all_values[0] if all_values else [])]
        for i, r in enumerate(all_values[1:], start=2):
            row_dict: dict[str, Any] = {"_row": i, "_raw": r}
            for j, h in enumerate(header):
                en = RU_TO_EN.get(h, h)
                row_dict[en] = r[j] if j < len(r) else ""
            rows_for_match.append(row_dict)

        updates: list[dict] = []
        to_add: list[list[str]] = []
        n_cols = len(headers)
        end_col_letter = _col_letter(n_cols - 1)

        # 1. ПРОХОД ПО СТРОКАМ ТАБЛИЦЫ
        for row in rows_for_match:
            title = row.get("title", "")
            link = row.get("download_link", "").strip()
            folder = row.get("folder", "")
            old_source = detect_link_source(link)

            # Если ссылка ведет на GitHub — запоминаем этот файл и НЕ ТРОГАЕМ
            if old_source == "release":
                old_tag, old_filename = parse_release_link(link)
                if old_tag and old_filename and old_filename in {a["name"] for a in repo_assets_by_tag.get(old_tag, [])}:
                    matched_assets.add(f"{old_tag}/{old_filename}")
                    sec_stats["unchanged"] += 1
                    continue

            # Если ссылка на Яндекс/Терабокс, пробуем найти замену в GitHub
            target_tag = FOLDER_TRANSLATIONS.get(folder, slugify(folder))
            found_tag, found_name = None, None
            # Поиск по всем тегам
            for tag, assets in repo_assets_by_tag.items():
                for a in assets:
                    if a["name"].lower() == link.split("/")[-1].lower():
                        found_tag, found_name = tag, a["name"]
                        break
                if found_tag: break

            if found_tag and found_name:
                new_link = build_asset_url(found_tag, found_name)
                record = {
                    "title": title, "folder": folder,
                    "size": bytes_to_mb(0), "download_link": new_link
                }
                new_row_data = _row_from_record(record, headers)
                merged = merge_row(row["_raw"], new_row_data, headers)
                rng = f"A{row['_row']}:{end_col_letter}{row['_row']}"
                updates.append({"range": rng, "values": [merged]})
                stats["to_update_rows"].append({
                    "section": key, "tag": found_tag, "file": found_name,
                    "title": title, "old_link": link, "new_link": new_link, "old_source": old_source
                })
                matched_assets.add(f"{found_tag}/{found_name}")
                sec_stats["to_update"] += 1
            else:
                if old_source in ("yandex", "terabox"):
                    stats["legacy_only_rows"].append({
                        "section": key, "row": row["_row"], "title": title,
                        "folder": folder, "link": link, "source": old_source
                    })
                    sec_stats["legacy_only"] += 1

        # 2. ДОБАВЛЕНИЕ НОВЫХ ФАЙЛОВ ИЗ GITHUB
        for rel in by_section[key]:
            tag = rel.get("tag_name")
            for asset in rel.get("assets") or []:
                fname = asset.get("name")
                if not fname: continue
                
                # Если файл уже привязан в таблице — ПРОПУСКАЕМ
                if f"{tag}/{fname}" in matched_assets: continue
                
                info = re.sub(r'^[\d\.\-\_]+', '', os.path.splitext(fname)[0]).strip()
                title = info if info else fname
                folder_name = FOLDER_TRANSLATIONS.get(tag, tag)
                new_link = build_asset_url(tag, fname)
                
                record = {
                    "title": title, "description": "", "format": os.path.splitext(fname)[1].lstrip("."),
                    "size": bytes_to_mb(asset.get("size", 0)), "download_link": new_link, 
                    "folder": folder_name,
                    "author": "", "artist": "", "year": "", "version": "",
                    "cover": "", "file_id": slugify(title), "legacy": "",
                }
                to_add.append(_row_from_record(record, headers))
                stats["new_in_repo_rows"].append({
                    "section": key, "tag": tag, "file": fname, 
                    "title": f"{folder_name} - {title}", "link": new_link, "size": record["size"]
                })
                sec_stats["new_in_repo"] += 1

        print(f"     К обновлению ссылок:  {sec_stats['to_update']}")
        print(f"     Новых в репо:         {sec_stats['new_in_repo']}")
        print(f"     Legacy (без миграции): {sec_stats['legacy_only']}")
        print(f"     Без изменений:        {sec_stats['unchanged']}")

        stats["sections"][key] = sec_stats

        if dry_run: continue
        if updates: batch_update_rows(sheet, updates)
        if to_add: 
            added, failed = append_rows_safe(sheet, to_add)
            if failed > 0: print(f"     [!] ВНИМАНИЕ: {failed} строк не удалось добавить (лимиты Google)")

    print("\n[4/5] Шаг A завершён.")
    return stats

# ============================================================
# ШАГ B: Google Sheets → JSON
# ============================================================
def _read_records_safe(worksheet, headers: list[str]) -> list[dict] | None:
    try: all_values = worksheet.get_all_values()
    except Exception as e:
        print(f"  ОШИБКА чтения листа: {e}")
        return None
    if not all_values: return []
    raw_header = all_values[0]
    positions: dict[str, int | None] = {}
    for want in headers:
        want_clean = want.strip()
        pos = None
        for i, h in enumerate(raw_header):
            if (h or "").strip().lower() == want_clean.lower(): pos = i; break
        if pos is None:
            for i, h in enumerate(raw_header):
                if want_clean.lower() in (h or "").strip().lower(): pos = i; break
        positions[want] = pos
    records: list[dict] = []
    for row in all_values[1:]:
        rec: dict[str, str] = {}
        for want, pos in positions.items():
            rec[want] = row[pos] if (pos is not None and pos < len(row)) else ""
        records.append(rec)
    return records

def _is_empty(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())

def row_to_item(row: dict, columns: list[str] | None = None) -> dict:
    item: dict[str, Any] = {}
    target_keys = [k for k in (columns or []) if k] or list(EN_TO_RU.keys())
    for en_key in target_keys:
        value = None
        for ru_col in EN_TO_RU.get(en_key, []):
            if ru_col in row and not _is_empty(row[ru_col]):
                value = row[ru_col]; break
        if _is_empty(value) and en_key in row and not _is_empty(row[en_key]):
            value = row[en_key]
        if _is_empty(value): continue
        item[en_key] = str(value).strip() if en_key != "description" else str(value)

    if item.get("title"): item["file_id"] = slugify(item["title"])

    folder_val = item.get("folder", "")
    if folder_val:
        lower_folder = folder_val.strip().lower()
        if lower_folder in FOLDER_TRANSLATIONS:
            item["folder"] = FOLDER_TRANSLATIONS[lower_folder]

    return item

def generate_json_for_section(worksheet, json_path: str, columns: list[str] | None = None, headers: list[str] | None = None) -> dict | None:
    print(f"  Лист:    {worksheet.title}\n  JSON:    {json_path}")
    dir_part = os.path.dirname(json_path) or "."
    os.makedirs(dir_part, exist_ok=True)

    if headers is None:
        headers = []
        for key in columns or []:
            variants = EN_TO_RU.get(key, [])
            headers.append(variants[0] if variants else key)
        if "Ссылка для скачивания" not in headers: headers.append("Ссылка для скачивания")

    records = _read_records_safe(worksheet, headers)
    if records is None: return None
    if not records:
        try:
            with open(json_path, "w", encoding="utf-8") as f: json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e: print(f"  ОШИБКА записи JSON: {e}"); return None
        return {"count": 0}

    json_data: list[dict] = []
    for row in records:
        item = row_to_item(row, columns)
        if item.get("title"): json_data.append(item)

    try:
        with open(json_path, "w", encoding="utf-8") as f: json.dump(json_data, f, ensure_ascii=False, indent=2)
    except Exception as e: print(f"  ОШИБКА записи JSON: {e}"); return None

    print(f"  ✓ Записано: {len(json_data)} записей")
    return {"count": len(json_data)}

def sheets_to_json(gs_client, sections: list[dict], dry_run: bool, repo_dir: str = ".") -> dict:
    stats = {"sections_ok": 0, "sections_failed": [], "total_records": 0}
    print("\n" + "=" * 60 + "\nШАГ B: Google Sheets → JSON\n" + "=" * 60)
    if not sections: return stats
    try: sh = open_spreadsheet(gs_client)
    except Exception as e: return stats

    for section in sections:
        key, label = section.get("key") or "?", section.get("label") or key
        sheet_name, json_path = section.get("sheet_name") or label, section.get("json_path")
        columns = section.get("columns") or []
        print(f"\n=== Раздел: {label} ({key}) ===")
        if not json_path: continue
        json_path = os.path.join(repo_dir, json_path)
        try: worksheet = sh.worksheet(sheet_name)
        except Exception: 
            stats["sections_failed"].append((key, f"лист «{sheet_name}» не найден"))
            continue
        
        result = generate_json_for_section(worksheet, json_path, columns)
        if result is not None:
            stats["sections_ok"] += 1
            stats["total_records"] += result["count"]
        else: stats["sections_failed"].append((key, "ошибка генерации"))

    print("\n" + "=" * 60)
    print(f"Обработано разделов: {stats['sections_ok']} из {len(sections)}\nВсего записей:       {stats['total_records']}")
    print("=" * 60)
    return stats

def notify_migration_report(repo_stats: dict, json_stats: dict, run_url: str | None = None) -> None:
    if not repo_stats and not json_stats: return
    lines: list[str] = []
    if repo_stats:
        sections = repo_stats.get("sections") or {}
        total_to_update = sum(s["to_update"] for s in sections.values())
        total_new = sum(s["new_in_repo"] for s in sections.values())
        total_legacy = sum(s["legacy_only"] for s in sections.values())
        total_unchanged = sum(s["unchanged"] for s in sections.values())
        lines.extend(["*Миграция ссылок*", f"• обновлено: {total_to_update}", f"• новых: {total_new}", f"• legacy (без миграции): {total_legacy}", f"• без изменений: {total_unchanged}"])
        if sections:
            lines.extend(["", "*По разделам:*"])
            for key, s in sections.items(): lines.append(f"  `{key}`: +{s['new_in_repo']} / ~{s['to_update']} / legacy {s['legacy_only']}")
            
        to_update_rows = repo_stats.get("to_update_rows") or []
        if to_update_rows:
            lines.append(f"\n🔄 *Детали обновления ссылок* ({len(to_update_rows)}):")
            for r in to_update_rows[:20]:
                lines.append(f"  • {r.get('title', '')}")
                lines.append(f"    Было:  `{r.get('old_link', '')}`")
                lines.append(f"    Стало: `{r.get('new_link', '')}`")
            if len(to_update_rows) > 20: lines.append(f"  ... и еще {len(to_update_rows) - 20}")

        new_rows = repo_stats.get("new_in_repo_rows") or []
        if new_rows:
            lines.append(f"\n➕ *Детально о новых файлах в репо* ({len(new_rows)}):")
            for r in new_rows:
                lines.append(f"  • {r.get('title', '')}")
                lines.append(f"    Размер: `{r.get('size', '')} МБ`")
            if len(new_rows) > 20: lines.append(f"  ... и еще {len(new_rows) - 20}")

    if json_stats:
        lines.extend(["", "*Генерация JSON*", f"• разделов: {json_stats.get('sections_ok', 0)}", f"• записей: {json_stats.get('total_records', 0)}"])
        if json_stats.get("sections_failed"): lines.append(f"• ошибок: {len(json_stats['sections_failed'])}")
        
    legacy_rows = (repo_stats or {}).get("legacy_only_rows") or []
    if legacy_rows:
        lines.append(f"\n⚠️ *Legacy требует решения* ({len(legacy_rows)}):")
        for r in legacy_rows[:10]:
            lines.append(f"  • {r.get('title', '')} (`{r.get('folder', '')}`)")
        if len(legacy_rows) > 10: lines.append(f"  ... и еще {len(legacy_rows) - 10}")

    notify_telegram("\n".join(lines))

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["repo-to-sheets", "sheets-to-json", "all"], default="all")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--sections", default="")
    parser.add_argument("--repo-dir", default=".")
    args = parser.parse_args()

    dry_run = not args.in_place
    section_filter = [s.strip() for s in args.sections.split(",") if s.strip()] or None
    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run_url = f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    repo_stats, json_stats = {}, {}
    try:
        sections = []
        for k, cfg in SECTION_CONFIG_FALLBACK.items():
            sections.append({"key": k, "label": cfg["label"], "sheet_name": cfg["sheet_name"], "json_path": cfg["json_path"], "columns": cfg["columns"]})
        if section_filter:
            sections = [s for s in sections if s.get("key") in section_filter]

        gs_client = get_gspread_client()
        
        if args.mode in ("repo-to-sheets", "all"):
            repo_stats = repo_to_sheets(gs_client, sections, dry_run)
        if args.mode in ("sheets-to-json", "all"):
            json_stats = sheets_to_json(gs_client, sections, dry_run, repo_dir=args.repo_dir)

        notify_migration_report(repo_stats, json_stats, run_url=run_url)
        
        total_to_update = sum(s["to_update"] for s in (repo_stats.get("sections") or {}).values())
        total_new = sum(s["new_in_repo"] for s in (repo_stats.get("sections") or {}).values())
        total_legacy = sum(s["legacy_only"] for s in (repo_stats.get("sections") or {}).values())
        details = f"обновлено ссылок: {total_to_update}, новых в репо: {total_new}, legacy: {total_legacy}"
        notify_result(title="Update content JSON", status="success", details=details, run_url=run_url)

    except Exception as e:
        print(f"\n[!!!] Критическая ошибка: {e}")
        traceback.print_exc()
        notify_result(title="Update content JSON", status="failure", details=f"Критическая ошибка: {e}", run_url=run_url)
        sys.exit(1)

if __name__ == "__main__":
    main()
