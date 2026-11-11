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

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://rmoonebbvpmvthvpcmpt.supabase.co")
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
GARBAGE_CHARS = set("╞░─┘╦╪╟┌┐└┴┬├┤│╫╬═║╔╗╚╝")

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

def has_cyrillic(text: str) -> bool:
    if not text: return False
    return bool(re.search(r'[а-яА-ЯёЁ]', str(text)))

def has_garbage(text: str) -> bool:
    if not text: return False
    return any(ch in str(text) for ch in GARBAGE_CHARS)

def score_row(row: dict) -> int:
    score = 0
    title = str(row.get("title", "")).strip()
    desc = str(row.get("description", "")).strip()
    author = str(row.get("author", "")).strip()
    
    if has_cyrillic(title): score += 100
    if has_cyrillic(desc): score += 50
    if has_cyrillic(author): score += 20
    
    if has_garbage(title): score -= 200
    if has_garbage(desc): score -= 200
    
    if title: score += 10
    if desc: 
        score += 30
        score += min(len(desc), 1000) // 10 
    if author: score += 10
    if row.get("cover"): score += 10
    
    return score

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
    releases = []
    page = 1
    while True:
        url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases?per_page={GITHUB_PER_PAGE}&page={page}"
        try:
            r = requests.get(url, headers=_github_headers(), timeout=HTTP_TIMEOUT)
            if r.status_code != 200: break
            batch = r.json()
            if not batch: break
            releases.extend(batch)
            if len(batch) < GITHUB_PER_PAGE: break
            page += 1
            time.sleep(GITHUB_API_SLEEP)
        except Exception:
            break
    return releases

def build_asset_url(tag: str, filename: str) -> str:
    return f"{RELEASE_PROXY_BASE}/download/{tag}/{filename}"

def detect_section_by_assets(assets: list[dict], tag: str = "") -> str | None:
    if tag and tag in TAG_TO_SECTION: return TAG_TO_SECTION[tag]
    if not assets: return None
    votes = {}
    for a in assets:
        ext = os.path.splitext(a.get("name", ""))[1].lower()
        section = EXT_TO_SECTION.get(ext)
        if section: votes[section] = votes.get(section, 0) + 1
    if not votes: return None
    winner = max(votes.items(), key=lambda x: x[1])[0]
    return winner

def get_gspread_client():
    if gspread is None or Credentials is None: raise RuntimeError("gspread не установлен.")
    creds_dict = json.loads(os.environ.get("GOOGLE_CREDENTIALS_JSON"))
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def open_spreadsheet(gs_client):
    for attempt in range(4):
        try:
            return gs_client.open_by_key(SPREADSHEET_ID)
        except Exception as e:
            if "500" in str(e) or "429" in str(e) or "503" in str(e):
                time.sleep(5)
                continue
            raise e

def get_or_create_sheet(sh, name: str):
    try: return sh.worksheet(name)
    except gspread.WorksheetNotFound: return sh.add_worksheet(title=name, rows=2000, cols=12)

def _col_letter(n: int) -> str:
    s = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s

def batch_update_rows(sheet, updates: list[dict]) -> int:
    if not updates: return 0
    chunk = 100
    updated = 0
    for i in range(0, len(updates), chunk):
        part = updates[i:i + chunk]
        try:
            time.sleep(1)
            sheet.batch_update(part, value_input_option="USER_ENTERED")
            updated += len(part)
        except Exception as e:
            print(f"    [!] Ошибка batch_update: {e}")
    return updated

def append_rows_safe(sheet, rows: list[list[str]], batch_size: int = 50):
    added = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        for attempt in range(3):
            try:
                time.sleep(2)
                sheet.append_rows(batch, value_input_option="USER_ENTERED")
                added += len(batch)
                break
            except Exception:
                time.sleep(5)
    return added

def _row_from_record(record: dict, headers: list[str]) -> list[str]:
    row: list[str] = []
    for ru in headers:
        en = RU_TO_EN.get(ru, ru)
        row.append(record.get(en, ""))
    return row

def norm_url_for_comparison(url: str) -> str:
    if not url: return ""
    u = urllib.parse.unquote(str(url)).strip().lower()
    return u.split('?')[0]

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
def sync_section(sh, section_key, config, repo_assets_by_tag, dry_run=False):
    sheet_name = config["sheet_name"]
    print(f"\n  ── Раздел: {config['label']} ({section_key})")
    
    try:
        sheet = get_or_create_sheet(sh, sheet_name)
        all_values = sheet.get_all_values()
    except Exception as e:
        print(f"     [!] Ошибка доступа к листу: {e}")
        return {}

    if not all_values:
        return {}

    header = [(h or "").strip() for h in all_values[0]]
    idx_folder = header.index("Папка") if "Папка" in header else -1
    idx_title = header.index("Название") if "Название" in header else -1
    idx_link = header.index("Ссылка для скачивания") if "Ссылка для скачивания" in header else -1
    
    if idx_title == -1 or idx_link == -1:
        print(f"     [!] Не найдены колонки 'Название' или 'Ссылка'")
        return {}

    existing_rows = []
    url_to_row_idx = {}
    legacy_rows_by_title = {}

    for i, row in enumerate(all_values[1:], start=2):
        title = row[idx_title] if idx_title < len(row) else ""
        link = row[idx_link] if idx_link < len(row) else ""
        folder = row[idx_folder] if idx_folder != -1 and idx_folder < len(row) else ""
        
        row_data = {"_row_num": i, "_raw": row, "title": title, "link": link, "folder": folder}
        existing_rows.append(row_data)
        
        norm_l = norm_url_for_comparison(link)
        if norm_l:
            url_to_row_idx[norm_l] = i
            if "terabox" in norm_l or "yandex" in norm_l:
                legacy_rows_by_title[norm_text(title)] = row_data

    updates = []
    to_add = []
    stats = {"migrated": 0, "added": 0, "unchanged": 0}
    
    for tag, assets in repo_assets_by_tag.items():
        for asset in assets:
            fname = asset["name"]
            ext = os.path.splitext(fname)[1].lower()
            
            if EXT_TO_SECTION.get(ext) != section_key:
                continue
                
            new_link = build_asset_url(tag, fname)
            norm_new_link = norm_url_for_comparison(new_link)
            
            if norm_new_link in url_to_row_idx:
                stats["unchanged"] += 1
                continue
                
            clean_title = os.path.splitext(fname)[0]
            clean_title = re.sub(r'^[\d\.\-\_]+', '', clean_title).strip()
            norm_clean_title = norm_text(clean_title)
            
            matched_legacy_row = None
            if norm_clean_title in legacy_rows_by_title:
                matched_legacy_row = legacy_rows_by_title[norm_clean_title]
            else:
                for l_title, l_row in legacy_rows_by_title.items():
                    if norm_clean_title in l_title or l_title in norm_clean_title:
                        if not l_row["folder"] or l_row["folder"].lower() in tag.lower() or FOLDER_TRANSLATIONS.get(tag, tag).lower() == l_row["folder"].lower():
                            matched_legacy_row = l_row
                            break
                            
            if matched_legacy_row:
                row_idx = matched_legacy_row["_row_num"]
                old_row = matched_legacy_row["_raw"]
                new_row_data = list(old_row)
                new_row_data[idx_link] = new_link
                
                idx_size = header.index("Размер (МБ)") if "Размер (МБ)" in header else -1
                if idx_size != -1:
                    new_row_data[idx_size] = str(round(asset["size"] / (1024 * 1024), 1))

                rng = f"A{row_idx}:{_col_letter(len(header)-1)}{row_idx}"
                updates.append({"range": rng, "values": [new_row_data]})
                print(f"     🔄 Миграция: {matched_legacy_row['title']} ➔ GitHub")
                stats["migrated"] += 1
                del legacy_rows_by_title[norm_text(matched_legacy_row['title'])]
                continue

            folder_name = FOLDER_TRANSLATIONS.get(tag, tag)
            
            record = {k: "" for k in EN_TO_RU.keys()}
            record["title"] = clean_title
            record["folder"] = folder_name
            record["download_link"] = new_link
            record["size"] = str(round(asset["size"] / (1024 * 1024), 1))
            record["format"] = ext.replace(".", "")
            
            final_row = []
            for h in header:
                en = RU_TO_EN.get(h)
                final_row.append(record.get(en, "") if en else "")
                
            to_add.append(final_row)
            stats["added"] += 1

    if not dry_run:
        if updates:
            print(f"     Обновление ссылок: {len(updates)}")
            batch_update_rows(sheet, updates)
        if to_add:
            print(f"     Добавление новых: {len(to_add)}")
            append_rows_safe(sheet, to_add)
            stats.setdefault("added_titles", []).extend([
                row[header.index("Название")] for row in to_add if "Название" in header
            ])

    print(f"     Без изменений: {stats['unchanged']}")
    return stats


# ============================================================
# ШАГ B: Google Sheets → JSON
# ============================================================
def _read_records_safe(worksheet, headers: list[str]) -> list[dict] | None:
    try: all_values = worksheet.get_all_values()
    except Exception: return None
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
    return item

def generate_json_for_section(worksheet, json_path: str, columns: list[str] | None = None) -> dict | None:
    # Инициализация headers строго здесь, чтобы избежать UnboundLocalError
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
        except: pass
        return {"count": 0}

    json_data: list[dict] = []
    for row in records:
        item = row_to_item(row, columns)
        if item.get("title"): json_data.append(item)

    try:
        with open(json_path, "w", encoding="utf-8") as f: json.dump(json_data, f, ensure_ascii=False, indent=2)
    except: pass
    return {"count": len(json_data)}

def sheets_to_json(gs_client, sections: list[dict], dry_run: bool, repo_dir: str = ".") -> dict:
    stats = {"sections_ok": 0, "sections_failed": [], "total_records": 0}
    try: sh = open_spreadsheet(gs_client)
    except: return stats

    for section in sections:
        key, label = section.get("key") or "?", section.get("label") or key
        sheet_name, json_path = section.get("sheet_name") or label, section.get("json_path")
        columns = section.get("columns") or []
        
        print(f"\n=== Раздел: {label} ({key}) ===")
        if not json_path: continue
        
        json_path = os.path.join(repo_dir, json_path)
        try: worksheet = sh.worksheet(sheet_name)
        except Exception as e: 
            print(f"  [!] Лист не найден: {sheet_name}")
            continue
            
        result = generate_json_for_section(worksheet, json_path, columns)
        if result is not None:
            stats["sections_ok"] += 1
            stats["total_records"] += result["count"]
            print(f"  ✓ Записано: {result['count']} записей")
    return stats


# ============================================================
# MAIN
# ============================================================
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all", "repo-to-sheets", "sheets-to-json", "report-only"], default="all")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--sections", default="")
    parser.add_argument("--repo-dir", default=".")
    args = parser.parse_args()

    dry_run = not args.in_place
    section_filter = [s.strip() for s in args.sections.split(",") if s.strip()] or None
    run_url = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"

    print("=" * 60)
    print(f"Синхронизация GitHub ➔ Google Sheets ➔ JSON (Режим: {'DRY-RUN' if dry_run else 'LIVE'})")
    print("=" * 60)

    try:
        gs_client = get_gspread_client()
        sh = open_spreadsheet(gs_client)
        
        # Подготовка списка разделов
        sections = []
        for k, cfg in SECTION_CONFIG_FALLBACK.items():
            sections.append({"key": k, "label": cfg["label"], "sheet_name": cfg["sheet_name"], "json_path": cfg["json_path"], "columns": cfg["columns"]})
        if section_filter:
            sections = [s for s in sections if s.get("key") in section_filter]

        total_stats = {"migrated": 0, "added": 0, "unchanged": 0, "added_titles": []}
        json_stats = {}

        # ─── ШАГ A: GitHub ➔ Sheets ───
        if args.mode in ("repo-to-sheets", "all"):
            print("\nЗагрузка релизов из GitHub...")
            releases = list_all_releases()
            
            repo_assets_by_tag = {}
            for rel in releases:
                tag = rel.get("tag_name")
                if tag:
                    repo_assets_by_tag[tag] = rel.get("assets", [])
                    
            print(f"Получено тегов: {len(repo_assets_by_tag)}")
            
            for key, cfg in SECTION_CONFIG_FALLBACK.items():
                if section_filter and key not in section_filter:
                    continue
                stats = sync_section(sh, key, cfg, repo_assets_by_tag, dry_run)
                for k in ["migrated", "added", "unchanged"]:
                    total_stats[k] += stats.get(k, 0)
                total_stats["added_titles"].extend(stats.get("added_titles", []))

        # ─── ШАГ B: Sheets ➔ JSON ───
        if args.mode in ("sheets-to-json", "all"):
            print("\n" + "=" * 60)
            print("ШАГ B: Генерация JSON из Google Sheets")
            print("=" * 60)
            json_stats = sheets_to_json(gs_client, sections, dry_run, repo_dir=args.repo_dir)

        # ─── ОТЧЕТ В TELEGRAM ───
        lines = ["*Синхронизация завершена*"]
        if total_stats["migrated"] > 0:
            lines.append(f"🔄 Мигрировано (Терабокс ➔ GitHub): {total_stats['migrated']}")
        if total_stats["added"] > 0:
            lines.append(f"➕ Добавлено новых файлов: {total_stats['added']}")
            for t in total_stats["added_titles"][:10]:
                lines.append(f"  • {t}")
            if len(total_stats["added_titles"]) > 10:
                lines.append(f"  ... и еще {len(total_stats['added_titles']) - 10}")
        if total_stats["unchanged"] > 0:
            lines.append(f"✅ Без изменений (сохранены правки): {total_stats['unchanged']}")
            
        if json_stats:
            lines.append(f"📄 JSON обновлен: {json_stats.get('total_records', 0)} записей")

        notify_telegram("\n".join(lines))
        print("\n" + "=" * 60)
        print("Готово!")
        
    except Exception as e:
        print(f"\n[!!!] Критическая ошибка: {e}")
        traceback.print_exc()
        notify_telegram(f"❌ Ошибка синхронизации: {e}")

if __name__ == "__main__":
    main()
