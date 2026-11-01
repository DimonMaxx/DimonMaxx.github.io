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

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "https://dimonmaxx.github.io").rstrip("/")
HTTP_TIMEOUT = 30
GITHUB_PER_PAGE = 100
GITHUB_API_SLEEP = 0.3

# Колонки, которые НЕЛЬЗЯ перезаписывать, если строка уже существует
IMMUTABLE_COLUMNS = ["folder", "title", "description", "author", "artist", "year", "cover"]

FOLDER_TRANSLATIONS = {
    "plaginy": "Плагины",
    "skripty": "Скрипты",
    "makrosy": "Макросы",
    "dlya-windows-svoi": "Для windows свои",
}

SECTION_CONFIG = {
    "books": {
        "label": "Книги", "sheet_name": "Книги", "json_path": "_content/books.json",
        "columns": ["folder", "cover", "title", "author", "description", "format", "size", "download_link"],
    },
    "programs": {
        "label": "Программы", "sheet_name": "Программы", "json_path": "_content/programs.json",
        "columns": ["folder", "title", "description", "version", "size", "download_link"],
    },
    "music": {
        "label": "Музыка", "sheet_name": "Музыка", "json_path": "_content/music.json",
        "columns": ["folder", "title", "artist", "year", "size", "download_link"],
    },
    "games": {
        "label": "Игры", "sheet_name": "Игры", "json_path": "_content/games.json",
        "columns": ["title", "platform", "year", "description", "download_link"],
    },
    "movies": {
        "label": "Фильмы", "sheet_name": "Фильмы", "json_path": "_content/movies.json",
        "columns": ["title", "year", "description", "download_link"],
    },
    "misc": {
        "label": "Разное", "sheet_name": "Разное", "json_path": "_content/misc.json",
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


# ============================================================
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def slugify(text: str) -> str:
    if not text: return ""
    s = str(text)
    s = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ\s\-]", "", s)
    s = s.strip().lower()
    s = re.sub(r"[\s\-]+", "-", s)
    return s

def norm_text(text: str) -> str:
    """Очистка текста для умного сравнения."""
    if not text: return ""
    t = str(text).lower()
    t = re.sub(r"\(.*?\)|\[.*?\]", "", t) # убираем скобки
    t = re.sub(r"[^\w\s]", "", t)
    return re.sub(r"\s+", " ", t).strip()

def norm_url_for_comparison(url: str) -> str:
    if not url: return ""
    u = urllib.parse.unquote(str(url)).strip().lower()
    return u.split('?')[0]

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


# ============================================================
# GOOGLE SHEETS
# ============================================================
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


# ============================================================
# ОСНОВНАЯ ЛОГИКА МИГРАЦИИ И СИНХРОНИЗАЦИИ
# ============================================================
def sync_section(sh, section_key, config, repo_assets_by_tag, dry_run=False):
    sheet_name = config["sheet_name"]
    columns = config["columns"]
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

    # Собираем данные о том, что уже есть в таблице
    existing_rows = [] # list of dicts
    url_to_row_idx = {} # norm_url -> row_index
    legacy_rows_by_title = {} # norm_title -> row_index

    for i, row in enumerate(all_values[1:], start=2):
        title = row[idx_title] if idx_title < len(row) else ""
        link = row[idx_link] if idx_link < len(row) else ""
        folder = row[idx_folder] if idx_folder != -1 and idx_folder < len(row) else ""
        
        row_data = {
            "_row_num": i,
            "_raw": row,
            "title": title,
            "link": link,
            "folder": folder
        }
        existing_rows.append(row_data)
        
        norm_l = norm_url_for_comparison(link)
        if norm_l:
            url_to_row_idx[norm_l] = i
            if "terabox" in norm_l or "yandex" in norm_l:
                legacy_rows_by_title[norm_text(title)] = row_data

    # Списки для обновления
    updates = []
    to_add = []
    stats = {"migrated": 0, "added": 0, "unchanged": 0}
    
    # Проходим по всем файлам в GitHub
    for tag, assets in repo_assets_by_tag.items():
        for asset in assets:
            fname = asset["name"]
            ext = os.path.splitext(fname)[1].lower()
            
            # Пропускаем файлы не из этого раздела
            if EXT_TO_SECTION.get(ext) != section_key:
                continue
                
            new_link = build_asset_url(tag, fname)
            norm_new_link = norm_url_for_comparison(new_link)
            
            # 1. Если ссылка уже есть в таблице — НИЧЕГО НЕ ТРОГАЕМ (сохраняем ручные правки)
            if norm_new_link in url_to_row_idx:
                stats["unchanged"] += 1
                continue
                
            # 2. Ищем, нет ли этого файла под видом legacy (Терабокс/Яндекс)
            clean_title = os.path.splitext(fname)[0]
            clean_title = re.sub(r'^[\d\.\-\_]+', '', clean_title).strip()
            norm_clean_title = norm_text(clean_title)
            
            # Ищем совпадение среди legacy строк
            matched_legacy_row = None
            # Сначала точное совпадение, потом частичное
            if norm_clean_title in legacy_rows_by_title:
                matched_legacy_row = legacy_rows_by_title[norm_clean_title]
            else:
                for l_title, l_row in legacy_rows_by_title.items():
                    # Если одно название содержит другое (например, "potplayer" и "potplayer 7sh3")
                    if norm_clean_title in l_title or l_title in norm_clean_title:
                        # Проверяем, что это из той же папки (если папка указана)
                        if not l_row["folder"] or l_row["folder"].lower() in tag.lower() or FOLDER_TRANSLATIONS.get(tag, tag).lower() == l_row["folder"].lower():
                            matched_legacy_row = l_row
                            break
                            
            if matched_legacy_row:
                # МИГРАЦИЯ! Заменяем ссылку в старой строке на GitHub
                row_idx = matched_legacy_row["_row_num"]
                old_row = matched_legacy_row["_raw"]
                
                # Создаем новую строку на основе старой (сохраняем все ручные правки)
                new_row_data = list(old_row)
                # Обновляем только ссылку и размер (если колонка размера есть)
                new_row_data[idx_link] = new_link
                
                # Проверяем колонку размера
                idx_size = header.index("Размер (МБ)") if "Размер (МБ)" in header else -1
                if idx_size != -1:
                    new_row_data[idx_size] = str(round(asset["size"] / (1024 * 1024), 1))

                rng = f"A{row_idx}:{_col_letter(len(header)-1)}{row_idx}"
                updates.append({"range": rng, "values": [new_row_data]})
                
                print(f"     🔄 Миграция: {matched_legacy_row['title']} ➔ GitHub")
                stats["migrated"] += 1
                # Удаляем из legacy словаря, чтобы не мигрировать дважды
                del legacy_rows_by_title[norm_text(matched_legacy_row['title'])]
                continue

            # 3. Если это абсолютно новый файл (нет в таблице и нет в legacy)
            folder_name = FOLDER_TRANSLATIONS.get(tag, tag)
            
            # Формируем запись по стандартным правилам
            record = {k: "" for k in EN_TO_RU.keys()}
            record["title"] = clean_title
            record["folder"] = folder_name
            record["download_link"] = new_link
            record["size"] = str(round(asset["size"] / (1024 * 1024), 1))
            record["format"] = ext.replace(".", "")
            
            # Собираем строку по заголовкам
            final_row = []
            for h in header:
                en = RU_TO_EN.get(h)
                final_row.append(record.get(en, "") if en else "")
                
            to_add.append(final_row)
            stats["added"] += 1

    # Применяем изменения
    if not dry_run:
        if updates:
            print(f"     Обновление ссылок: {len(updates)}")
            batch_update_rows(sheet, updates)
        if to_add:
            print(f"     Добавление новых: {len(to_add)}")
            append_rows_safe(sheet, to_add)
            
            # Запись в лог добавленных файлов (в Telegram)
            for row in to_add:
                # Ищем название для лога
                title_idx = header.index("Название") if "Название" in header else -1
                title_val = row[title_idx] if title_idx != -1 else "Неизвестно"
                stats.setdefault("added_titles", []).append(title_val)

    return stats


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["all"], default="all")
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--sections", default="")
    parser.add_argument("--repo-dir", default=".")
    args = parser.parse_args()

    dry_run = not args.in_place
    section_filter = [s.strip() for s in args.sections.split(",") if s.strip()] or None
    run_url = f"https://github.com/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ.get('GITHUB_RUN_ID', '')}"

    print("=" * 60)
    print(f"Синхронизация GitHub ➔ Google Sheets (Режим: {'DRY-RUN' if dry_run else 'LIVE'})")
    print("=" * 60)

    try:
        gs_client = get_gspread_client()
        sh = open_spreadsheet(gs_client)
        
        print("\nЗагрузка релизов из GitHub...")
        releases = list_all_releases()
        
        repo_assets_by_tag = {}
        for rel in releases:
            tag = rel.get("tag_name")
            if tag:
                repo_assets_by_tag[tag] = rel.get("assets", [])
                
        print(f"Получено тегов: {len(repo_assets_by_tag)}")
        
        total_stats = {"migrated": 0, "added": 0, "unchanged": 0, "added_titles": []}
        
        for key, cfg in SECTION_CONFIG.items():
            if section_filter and key not in section_filter:
                continue
                
            stats = sync_section(sh, key, cfg, repo_assets_by_tag, dry_run)
            for k in ["migrated", "added", "unchanged"]:
                total_stats[k] += stats.get(k, 0)
            total_stats["added_titles"].extend(stats.get("added_titles", []))

        # Отчет в Telegram
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
            lines.append(f"✅ Без изменений (сохранены ваши правки): {total_stats['unchanged']}")
            
        notify_telegram("\n".join(lines))
        print("\n" + "=" * 60)
        print("Готово!")
        
    except Exception as e:
        print(f"\n[!!!] Критическая ошибка: {e}")
        traceback.print_exc()
        notify_telegram(f"❌ Ошибка синхронизации: {e}")

if __name__ == "__main__":
    main()
