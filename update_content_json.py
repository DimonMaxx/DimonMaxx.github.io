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

# ─── СЛОВАРЬ ПЕРЕВОДОВ ДЛЯ ПАПОК ───
FOLDER_TRANSLATIONS = {
    "plaginy": "Плагины",
    "skripty": "Скрипты",
    "makrosy": "Макросы",
    "dlya-windows-svoi": "Для windows свои",
}


# ============================================================
# СООТВЕТСТВИЕ ЛИСТОВ И СЕКЦИЙ
# ============================================================
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
        "label": "Книги",
        "icon": "fa-book",
        "sheet_name": "Книги",
        "json_path": "_content/books.json",
        "container": "books-container",
        "folderable": True,
        "columns": ["folder", "cover", "title", "author", "description", "format", "size", "download_link"],
    },
    "programs": {
        "label": "Программы",
        "icon": "fa-code",
        "sheet_name": "Программы",
        "json_path": "_content/programs.json",
        "container": "programs-container",
        "folderable": True,
        "columns": ["folder", "title", "description", "version", "size", "download_link"],
    },
    "music": {
        "label": "Музыка",
        "icon": "fa-music",
        "sheet_name": "Музыка",
        "json_path": "_content/music.json",
        "container": "music-container",
        "folderable": True,
        "columns": ["folder", "title", "artist", "year", "size", "download_link"],
    },
    "games": {
        "label": "Игры",
        "icon": "fa-gamepad",
        "sheet_name": "Игры",
        "json_path": "_content/games.json",
        "container": "games-container",
        "folderable": False,
        "columns": ["title", "platform", "year", "description", "download_link"],
    },
    "movies": {
        "label": "Фильмы",
        "icon": "fa-film",
        "sheet_name": "Фильмы",
        "json_path": "_content/movies.json",
        "container": "movies-container",
        "folderable": False,
        "columns": ["title", "year", "description", "download_link"],
    },
    "misc": {
        "label": "Разное",
        "icon": "fa-ellipsis-h",
        "sheet_name": "Разное",
        "json_path": "_content/misc.json",
        "container": "misc-container",
        "folderable": False,
        "columns": ["title", "description", "download_link"],
    },
}

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
    "Дата":                  "date",
    "Категория":             "category",
    "Теги":                  "tags",
    "Текст":                 "text",
    "Legacy":                "legacy",
}

EN_TO_RU: dict[str, list[str]] = {}
for ru, en in RU_TO_EN.items():
    EN_TO_RU.setdefault(en, []).append(ru)


EXT_TO_SECTION = {
    ".fb2": "books", ".epub": "books", ".mobi": "books", ".djvu": "books",
    ".pdf": "books", ".rtf": "books", ".doc": "books", ".docx": "books",
    ".mp3": "music", ".flac": "music", ".wav": "music", ".ogg": "music",
    ".m4a": "music", ".aac": "music", ".wma": "music", ".opus": "music",
    ".ape": "music", ".aiff": "music", ".alac": "music",
    ".exe": "programs", ".msi": "programs", ".rar": "programs", ".zip": "programs",
    ".7z": "programs", ".tar": "programs", ".gz": "programs", ".xlsm": "programs",
    ".xlsx": "programs", ".xls": "programs", ".ods": "programs", ".odt": "programs",
    ".bat": "programs", ".ps1": "programs", ".sh": "programs", ".py": "programs",
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


# ============================================================
# SLUGIFY и ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ============================================================
def slugify(text: str) -> str:
    if not text:
        return ""
    s = str(text)
    s = re.sub(r"[^a-zA-Z0-9а-яА-ЯёЁ\s\-]", "", s)
    s = s.strip().lower()
    s = re.sub(r"[\s\-]+", "-", s)
    return s

def has_cyrillic(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r'[а-яА-ЯёЁ]', str(text)))

def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "MyFiles-Sync/1.0",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
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
        if r.status_code != 200:
            print(f"[!] GitHub API HTTP {r.status_code}: {r.text[:300]}")
            return releases
        batch = r.json()
        if not batch:
            break
        releases.extend(batch)
        if len(batch) < GITHUB_PER_PAGE:
            break
        page += 1
        time.sleep(GITHUB_API_SLEEP)
    print(f"[GitHub] Получено релизов: {len(releases)}")
    return releases

def list_release_assets(tag: str) -> list[dict]:
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tags/{tag}"
    try:
        r = requests.get(url, headers=_github_headers(), timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return []
        data = r.json()
        return [{"name": a.get("name", ""), "size": a.get("size", 0)} for a in data.get("assets", [])]
    except Exception as e:
        print(f"[!] Ошибка получения ассетов для тега '{tag}': {e}")
        return []

def build_asset_url(tag: str, filename: str) -> str:
    return f"{RELEASE_PROXY_BASE}/download/{tag}/{filename}"

def detect_section_by_assets(assets: list[dict], tag: str = "") -> str | None:
    if tag and tag in TAG_TO_SECTION:
        return TAG_TO_SECTION[tag]
    if not assets:
        return None
    votes: dict[str, int] = {}
    for a in assets:
        ext = os.path.splitext(a.get("name", ""))[1].lower()
        section = EXT_TO_SECTION.get(ext)
        if section:
            votes[section] = votes.get(section, 0) + 1
    if not votes:
        txt_count = sum(1 for a in assets if a.get("name", "").lower().endswith(".txt"))
        if txt_count == len(assets) and txt_count > 0:
            return "books"
        return None
    winner, winner_count = max(votes.items(), key=lambda x: x[1])
    ratio = winner_count / len(assets)
    if ratio >= SECTION_VOTE_THRESHOLD:
        return winner
    priority = ["books", "music", "programs", "games", "movies"]
    for p in priority:
        if votes.get(p, 0) > 0:
            return p
    return None

SEPARATORS = [" - ", " — ", " – ", " –– "]
_CP866_JUNK = set("╞░─┘╦╪╟┌┐└┴┬├┤│╫╬═║╔╗╚╝")

def _is_garbage_stem(stem: str) -> bool:
    if not stem:
        return True
    s = stem.strip()
    if re.match(r"^fanfic_\d+$", s, re.IGNORECASE): return True
    if re.match(r"^[\d\.\s]+$", s): return True
    if re.match(r"^[\*\-_\.\s]+$", s): return True
    if any(ch in s for ch in _CP866_JUNK): return True
    if len(s) < 2: return True
    # ИСПРАВЛЕНО: теперь разрешаем цифры (например, -.01)
    if not re.search(r"[A-Za-zА-Яа-яЁё0-9]{2,}", s): return True
    return False

_FILENAME_PREFIX_RE = re.compile(r"^\d{1,4}\s*[_\.\-]\s*")

def _strip_numeric_prefix(stem: str) -> str:
    return _FILENAME_PREFIX_RE.sub("", stem).strip()

def parse_book_name(filename: str) -> dict[str, str]:
    stem = os.path.splitext(filename)[0].strip()
    if _is_garbage_stem(stem): return {"title": "", "author": ""}
    stem = _strip_numeric_prefix(stem)
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"\s*\[.*?\]\s*", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    author, title = "", stem
    for sep in SEPARATORS:
        if sep in stem:
            head, tail = stem.split(sep, 1)
            head, tail = head.strip(), tail.strip()
            if head and tail:
                author, title = head, tail
                break
    if not author and "." in title:
        m = re.match(r"^([А-ЯA-Z][^.]{1,60}\.)\s+(.+)$", title)
        if m:
            author = m.group(1).strip()
            title = m.group(2).strip()
    author = re.sub(r"\s+", " ", author).strip(" ,;")
    title = re.sub(r"\s+", " ", title).strip(" ,;")
    return {"title": title, "author": author}

def parse_program_name(filename: str) -> dict[str, str]:
    stem = os.path.splitext(filename)[0].strip()
    stem = re.sub(r"\s+", " ", stem).strip()
    if not stem: return {"title": "", "version": ""}
    version = ""
    m = re.search(r"\b[vV]?(\d+(?:\.\d+){1,3})\b", stem)
    if m: version = m.group(1)
    return {"title": stem, "version": version}

def parse_music_name(filename: str) -> dict[str, str]:
    stem = os.path.splitext(filename)[0].strip()
    stem = re.sub(r"\s+", " ", stem).strip()
    result = {"title": stem, "artist": "", "year": ""}
    if not stem: return result
    year_m = re.search(r"\b(19[5-9]\d|20[0-3]\d)\b", stem)
    if year_m: result["year"] = year_m.group(1)
    stem = _strip_numeric_prefix(stem)
    stem = re.sub(r"^\d{1,2}[\s\.\-–]+", "", stem).strip()
    if ".-." in stem: stem = stem.replace(".-.", " - ")
    parts = re.split(r"\s+[-–—]\s+", stem, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        artist_raw, title_raw = parts[0].strip(), parts[1].strip()
        artist_clean = re.sub(r"\.+", " ", artist_raw)
        artist_clean = re.sub(r"\s+", " ", artist_clean).strip()
        title_clean = re.sub(r"\.+", " ", title_raw)
        title_clean = re.sub(r"\s+", " ", title_clean).strip()
        result["artist"] = artist_clean
        result["title"] = title_clean
    else:
        stem = re.sub(r"\.+", " ", stem)
        stem = re.sub(r"\s+", " ", stem).strip()
        result["title"] = stem
    result["title"] = re.sub(r"\s*\(?\b(19[5-9]\d|20[0-3]\d)\b\)?\s*", " ", result["title"]).strip(" -–—")
    return result

def parse_universal_name(filename: str) -> dict[str, str]:
    stem = os.path.splitext(filename)[0].strip()
    stem = _strip_numeric_prefix(stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return {"title": stem}

def parse_filename_by_section(filename: str, section: str) -> dict[str, str]:
    if section == "books": return parse_book_name(filename)
    if section == "music": return parse_music_name(filename)
    if section == "programs": return parse_program_name(filename)
    return parse_universal_name(filename)

_STOP_WORDS = {
    "или", "как", "для", "при", "над", "под", "без", "про",
    "the", "and", "for", "with", "from", "that", "this",
    "его", "её", "ее", "их", "все", "весь", "себя", "это",
}

def normalize_for_match(text: str) -> str:
    if not text: return ""
    t = str(text).lower().replace("ё", "е")
    t = re.sub(r"[^\w\s]", " ", t, flags=re.UNICODE)
    return re.sub(r"\s+", " ", t).strip()

_TRANSLIT_MAP = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "zh", "з": "z", "и": "i", "й": "i", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
    "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
}

def _translit_ru_to_en(text: str) -> str:
    if not text: return ""
    result = []
    for ch in str(text).lower():
        if ch in _TRANSLIT_MAP:
            result.append(_TRANSLIT_MAP[ch])
        elif ch.isascii() and (ch.isalnum() or ch == " "):
            result.append(ch)
        elif ch in " -–—.,:;!?()[]{}":
            result.append(" ")
    return re.sub(r"\s+", " ", "".join(result)).strip()

def _words_set(text: str) -> set[str]:
    if not text: return set()
    return set(w for w in re.split(r"[^\w]+", text.lower()) if len(w) >= 3 and w not in _STOP_WORDS)

def _compact_match_str(text: str) -> str:
    t = normalize_for_match(text)
    t = _translit_ru_to_en(t)
    return t.replace(" ", "")

def match_asset_to_row(asset_name: str, rows: list[dict], section: str, folder: str = "") -> dict | None:
    asset_info = parse_filename_by_section(asset_name, section)
    asset_title = asset_info.get("title", "")
    if not asset_title: return None

    asset_norm = normalize_for_match(asset_title)
    asset_slug = slugify(asset_title)
    asset_compact = _compact_match_str(asset_title)
    asset_words = set(w for w in asset_norm.split() if len(w) >= 3 and w not in _STOP_WORDS)
    folder_norm = normalize_for_match(folder) if folder else ""

    # 1. Точное (folder + title)
    for r in rows:
        if folder_norm and normalize_for_match(r.get("folder", "")) != folder_norm: continue
        if normalize_for_match(r.get("title", "")) == asset_norm: return r

    # 2. Точное по title (без folder)
    for r in rows:
        if normalize_for_match(r.get("title", "")) == asset_norm: return r

    # 3. По slug
    for r in rows:
        if slugify(r.get("title", "")) == asset_slug: return r

    # 3.5. По транслиту кириллица → латиница
    for r in rows:
        row_title = r.get("title", "") or ""
        row_translit = _translit_ru_to_en(row_title)
        row_words = _words_set(row_translit)
        if not row_words or not asset_words: continue
        if row_words == asset_words: return r

    # 3.6. По компактной строке (без пробелов)
    for r in rows:
        if _compact_match_str(r.get("title", "")) == asset_compact: return r

    # 3.7. По нечёткому совпадению (difflib)
    for r in rows:
        row_compact = _compact_match_str(r.get("title", ""))
        if not row_compact: continue
        if difflib.SequenceMatcher(None, asset_compact, row_compact).ratio() >= 0.65: 
            return r

    # 3.8. Совпадение по началу названия (первые 7 символов без пробелов)
    for r in rows:
        row_compact = _compact_match_str(r.get("title", ""))
        if len(asset_compact) >= 7 and len(row_compact) >= 7:
            if asset_compact[:7] == row_compact[:7]:
                return r

    # 4. Частичное совпадение по словам (Jaccard)
    best, best_score = None, 0.0
    for r in rows:
        row_words = set(w for w in normalize_for_match(r.get("title", "")).split() if len(w) >= 3 and w not in _STOP_WORDS)
        if not row_words or not asset_words: continue
        inter, union = asset_words & row_words, asset_words | row_words
        score = len(inter) / len(union)
        if score >= 0.7 and score > best_score:
            best_score, best = score, r

    return best


def bytes_to_mb(size_bytes: int | float | str | None) -> str:
    try:
        n = int(size_bytes or 0)
    except (TypeError, ValueError):
        return "0"
    if n <= 0: return "0"
    return str(round(n / (1024 * 1024), 1))

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

# ─── УЛУЧШЕННАЯ ФУНКЦИЯ ДЛЯ СРАВНЕНИЯ ССЫЛОК ───
def normalize_url(url: str) -> str:
    if not url: return ""
    try:
        # Приводим к нижнему регистру и убираем пробелы
        u = str(url).strip().lower()
        # Заменяем http на https
        u = u.replace("http://", "https://")
        # Убираем слэш в конце
        u = u.rstrip("/")
        # Декодируем %20 и %D0... (кириллицу) в обычные символы
        u = urllib.parse.unquote_plus(u)
        # Игнорируем пробелы, которые могли случайно попасть
        u = u.replace(" ", "")
        return u
    except Exception:
        return url


# ============================================================
# GOOGLE SHEETS — АВТОРИЗАЦИЯ И УТИЛИТЫ
# ============================================================

def get_gspread_client():
    if gspread is None or Credentials is None:
        raise RuntimeError("gspread / google-auth не установлены.")
    creds_dict = None
    raw_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if raw_json:
        try: creds_dict = json.loads(raw_json)
        except json.JSONDecodeError as e: raise RuntimeError(f"Invalid GOOGLE_CREDENTIALS_JSON: {e}")
    if creds_dict is None:
        creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
        if os.path.exists(creds_file):
            with open(creds_file, "r", encoding="utf-8") as f: creds_dict = json.load(f)
    if creds_dict is None:
        raise RuntimeError("Не найдены Google-credentials.")
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    return gspread.authorize(creds)

def open_spreadsheet(gs_client):
    if SPREADSHEET_ID:
        return gs_client.open_by_key(SPREADSHEET_ID)
    return gs_client.open(SPREADSHEET_NAME)

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

def ensure_headers(sheet, headers: list[str]) -> None:
    try: current = sheet.row_values(1)
    except Exception: current = []
    need_update = False
    if len(current) != len(headers): need_update = True
    else:
        for i, h in enumerate(headers):
            if (current[i] or "").strip() != h.strip():
                need_update = True
                break
    if not need_update: return
    try:
        all_values = sheet.get_all_values()
        max_cols = max((len(r) for r in all_values), default=len(headers))
    except Exception: max_cols = len(headers)
    max_cols = max(max_cols, len(headers))
    new_row = list(headers) + [""] * (max_cols - len(headers))
    range_a1 = f"A1:{_col_letter(max_cols - 1)}1"
    try:
        sheet.update(values=[new_row], range_name=range_a1, value_input_option="USER_ENTERED")
    except Exception as e:
        print(f"    [!] Не удалось обновить заголовки: {e}")

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

def backup_sheet(sh, worksheet, section_key: str, all_values: list[list[str]], max_backups: int | None = None) -> str | None:
    if not all_values: return None
    if max_backups is None: max_backups = BACKUP_KEEP_COUNT
    ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"_backup_{section_key}_{ts}"
    max_cols = max((len(r) for r in all_values), default=1)
    max_rows = len(all_values)
    try:
        for attempt in range(3):
            try:
                time.sleep(2)
                backup = sh.add_worksheet(title=backup_name, rows=max(max_rows + 10, 100), cols=max(max_cols + 2, 10))
                backup.update(values=all_values, range_name="A1", value_input_option="USER_ENTERED")
                break
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(5)
                    continue
                raise e
    except Exception as e:
        print(f"    [!] Backup: ошибка создания: {e}")
        return None
    
    try:
        prefix = f"_backup_{section_key}_"
        backups = [ws for ws in sh.worksheets() if ws.title.startswith(prefix)]
        backups.sort(key=lambda w: w.title, reverse=True)
        for old in backups[max_backups:]:
            try: sh.del_worksheet(old)
            except Exception: pass
    except Exception: pass
    return backup_name

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

def append_rows_safe(sheet, rows: list[list[str]], batch_size: int = 200) -> tuple[int, int]:
    added, failed = 0, 0
    total = len(rows)
    for i in range(0, total, batch_size):
        batch = rows[i:i + batch_size]
        success = False
        for attempt in range(3):
            try:
                time.sleep(2)
                sheet.append_rows(batch, value_input_option="USER_ENTERED")
                added += len(batch)
                success = True
                break
            except Exception as e:
                time.sleep(5)
        if not success: failed += len(batch)
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


# ============================================================
# SUPABASE
# ============================================================
def _get_supabase_client():
    if not supa_create_client or not SUPABASE_SERVICE_KEY: return None
    try: return supa_create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception: return None

def load_active_sections() -> list[dict]:
    client = _get_supabase_client()
    if client is None: return []
    try:
        resp = client.table("site_sections").select("key,label,icon,handler_type,yandex_url,yandex_path,sheet_name,json_path,container,columns,folderable,is_active,sort_order,manual_override,strip_prefix_mode").eq("is_active", True).order("sort_order").execute()
        return resp.data or []
    except Exception:
        try:
            resp = client.table("site_sections").select("key,label,icon,handler_type,yandex_url,yandex_path,sheet_name,json_path,container,columns,folderable,is_active,sort_order").eq("is_active", True).order("sort_order").execute()
            return resp.data or []
        except Exception: return []

def load_hidden_items(section_key: str) -> set[tuple[str, str]]:
    client = _get_supabase_client()
    if client is None: return set()
    try:
        resp = client.table("hidden_items").select("folder,title").eq("section_key", section_key).execute()
        hidden: set[tuple[str, str]] = set()
        for row in resp.data or []:
            folder = (row.get("folder") or "").strip().lower()
            title  = (row.get("title")  or "").strip().lower()
            if title: hidden.add((folder, title))
        return hidden
    except Exception: return set()


# ============================================================
# ПРОВЕРКА ЗДОРОВЬЯ
# ============================================================
def check_sheets_health(gs_client, sections: list[dict]) -> dict:
    result = {"ok": False, "errors": [], "warnings": [], "spreadsheet_title": "", "checked_sheets": []}
    try:
        sh = open_spreadsheet(gs_client)
        result["spreadsheet_title"] = sh.title or ""
    except Exception as e:
        result["errors"].append(f"Не удалось открыть таблицу: {e}")
        return result
    if not sections:
        result["ok"] = True
        return result
    seen: set[str] = set()
    for s in sections:
        if not isinstance(s, dict): continue
        key, label = s.get("key") or "?", s.get("label") or key
        sheet_name = s.get("sheet_name") or label
        if not sheet_name or sheet_name in seen: continue
        seen.add(sheet_name)
        try: ws = sh.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            result["errors"].append(f"[{key}] Лист «{sheet_name}» не найден.")
            continue
        except Exception as e:
            result["errors"].append(f"[{key}] Ошибка доступа к листу «{sheet_name}»: {e}")
            continue
        result["checked_sheets"].append(sheet_name)
        try: header = ws.row_values(1)
        except Exception as e:
            result["errors"].append(f"[{key}] Не удалось прочитать header: {e}")
            continue
        if not header or not any((h or "").strip() for h in header):
            result["errors"].append(f"[{key}] Лист «{sheet_name}»: пустая header row.")
            continue
        header_lower = [(h or "").strip().lower() for h in header]
        for group in (["Название", "Title", "название", "title"], ["Ссылка для скачивания", "Ссылка", "download_link", "link"]):
            group_lower = [c.strip().lower() for c in group]
            if not any(c in header_lower for c in group_lower):
                result["errors"].append(f"[{key}] Лист «{sheet_name}»: не найдена колонка «{group[0]}».")
    result["ok"] = len(result["errors"]) == 0
    return result

def print_sheets_health(health: dict) -> None:
    print("=" * 60)
    print("=== Проверка здоровья Google Sheets ===")
    if health.get("spreadsheet_title"): print(f"  Таблица: {health['spreadsheet_title']}")
    checked = health.get("checked_sheets") or []
    if checked:
        print(f"  Проверено листов: {len(checked)}")
    errors = health.get("errors") or []
    if errors:
        print("\n  Ошибки:")
        for e in errors: print(f"    ✗ {e}")
    if health.get("ok"): print("\n  ✓ Проверка пройдена.")
    else: print(f"\n  ✗ Проверка не пройдена ({len(errors)} ошибок).")
    print("=" * 60)


# ============================================================
# ОЧИСТКА ДУБЛИКАТОВ (БЕЗ ПРЕВЫШЕНИЯ ЛИМИТОВ)
# ============================================================
def clean_sheet_duplicates(sh, sections, dry_run=False):
    print("\n" + "=" * 60)
    print("=== ПРЕДВАРИТЕЛЬНАЯ ОЧИСТКА ДУБЛИКАТОВ (ОСТАВЛЯЕМ С ОПИСАНИЕМ) ===")
    print("=" * 60)
    total_deleted = 0
    
    for section in sections:
        key = section.get("key")
        sheet_name = section.get("sheet_name")
        if not sheet_name: continue
        
        try: sheet = sh.worksheet(sheet_name)
        except Exception: continue
        
        all_values = sheet.get_all_values()
        if len(all_values) < 2: continue
        
        header = [(h or "").strip().lower() for h in all_values[0]]
        def get_idx(names):
            for n in names:
                if n in header: return header.index(n)
            return -1
            
        idx_folder = get_idx(["папка", "folder"])
        idx_title = get_idx(["название", "title"])
        idx_desc = get_idx(["описание", "description"])
        
        if idx_title == -1 or idx_desc == -1: continue
        
        valid_rows, empty_desc_rows = [], []
        for i, r in enumerate(all_values[1:], start=2):
            folder = r[idx_folder] if idx_folder != -1 and idx_folder < len(r) else ""
            title = r[idx_title] if idx_title < len(r) else ""
            desc = r[idx_desc] if idx_desc < len(r) else ""
            if not title.strip(): continue
            row_dict = {"_row": i, "_raw": r, "folder": folder, "title": title, "description": desc.strip()}
            if row_dict["description"]: valid_rows.append(row_dict)
            else: empty_desc_rows.append(row_dict)
                
        rows_to_delete = []
        for empty_row in empty_desc_rows:
            matched = match_asset_to_row(empty_row["title"], valid_rows, key, folder=empty_row["folder"])
            if matched:
                rows_to_delete.append(empty_row["_row"])
                continue
            compact_empty = _compact_match_str(empty_row["title"])
            if not compact_empty: continue
            for v_row in valid_rows:
                compact_valid = _compact_match_str(v_row["title"])
                if difflib.SequenceMatcher(None, compact_empty, compact_valid).ratio() > 0.65:
                    rows_to_delete.append(empty_row["_row"])
                    break
                    
        if rows_to_delete:
            rows_to_delete.sort()
            if not dry_run:
                blocks = []
                start = rows_to_delete[0]
                prev = start
                for r in rows_to_delete[1:]:
                    if r == prev + 1: prev = r
                    else: blocks.append((start, prev)); start = r; prev = r
                blocks.append((start, prev))
                blocks.reverse()
                for start, end in blocks:
                    try:
                        sheet.delete_rows(start, end)
                        print(f"    [-] [{key}] Удален блок строк {start}-{end} ({end - start + 1} шт.)")
                        total_deleted += (end - start + 1)
                        time.sleep(2)
                    except Exception as e:
                        print(f"    [!] Ошибка удаления блока {start}-{end}: {e}")
            else:
                print(f"    [DRY-RUN] [{key}] Будет удалено строк: {len(rows_to_delete)}")
    
    if total_deleted > 0: print(f"\n  ✓ Очистка завершена. Удалено строк: {total_deleted}")
    else: print("\n  ✓ Дублей без описания не найдено.")


# ============================================================
# ШАГ A: GitHub Releases → Google Sheets
# ============================================================
def _is_release_link(link: str) -> bool:
    return detect_link_source(link) == "release"

def _slug_for_asset(asset_name: str, section: str) -> str:
    info = parse_filename_by_section(asset_name, section)
    title = info.get("title", "") or os.path.splitext(asset_name)[0]
    return slugify(title)

def repo_to_sheets(gs_client, sections: list[dict], dry_run: bool, tag_filter: list[str] | None = None) -> dict:
    stats = {"sections": {}, "to_update_rows": [], "new_in_repo_rows": [], "legacy_only_rows": [], "errors": []}
    print("\n" + "=" * 60 + "\nШАГ A: GitHub Releases → Google Sheets\n" + "=" * 60)

    print("\n[1/5] Загрузка релизов из GitHub...")
    releases = list_all_releases()
    if not releases:
        stats["errors"].append("Не получено ни одного релиза — шаг A пропущен.")
        return stats

    if tag_filter:
        tag_set = set(tag_filter)
        releases = [r for r in releases if r.get("tag_name") in tag_set]

    if not sections:
        sections = [{"key": k, "label": k, "sheet_name": v, "columns": ["title", "description", "download_link"]} for k, v in SECTION_TO_SHEET_FALLBACK.items()]

    print("\n[2/5] Определение секций для тегов...")
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

    clean_sheet_duplicates(sh, sections, dry_run)

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

        if dry_run: print(f"     [DRY-RUN] Заголовки НЕ обновляются. Ожидаемые: {headers}")
        else: ensure_headers(sheet, headers)

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

        all_assets: list[tuple[str, dict]] = []
        for rel in by_section[key]:
            tag = rel.get("tag_name") or ""
            for a in rel.get("assets") or []:
                all_assets.append((tag, a))

        matched_row_indices: set[int] = set()
        updates: list[dict] = []
        to_add: list[list[str]] = []
        n_cols = len(headers)
        end_col_letter = _col_letter(n_cols - 1)

        for tag, asset in all_assets:
            fname = asset.get("name") or ""
            size = asset.get("size") or 0
            if not fname: continue

            new_link = build_asset_url(tag, fname)
            size_mb = bytes_to_mb(size)
            info = parse_filename_by_section(fname, key)
            title = info.get("title", "") or os.path.splitext(fname)[0]
            file_id = _slug_for_asset(fname, key)
            folder_name = FOLDER_TRANSLATIONS.get(tag, tag)

            record = {
                "title": title, "description": "", "format": os.path.splitext(fname)[1].lstrip("."),
                "size": size_mb, "download_link": new_link, "folder": folder_name,
                "author": info.get("author", ""), "artist": info.get("artist", ""),
                "year": info.get("year", ""), "version": info.get("version", ""),
                "cover": "", "file_id": file_id, "legacy": "",
            }

            matched = match_asset_to_row(fname, rows_for_match, key, folder=folder_name)

            if matched:
                matched_row_indices.add(matched["_row"])
                old_link = str(matched.get("download_link", "") or "").strip()
                old_source = detect_link_source(old_link)
                
                # ─── СРАВНЕНИЕ ССЫЛОК ───
                is_same_link = False
                if old_source == "release":
                    if normalize_url(old_link) == normalize_url(new_link):
                        is_same_link = True

                if is_same_link:
                    sec_stats["unchanged"] += 1
                    continue

                new_row = _row_from_record(record, headers)
                merged = merge_row(matched["_raw"], new_row, headers)
                rng = f"A{matched['_row']}:{end_col_letter}{matched['_row']}"
                updates.append({"range": rng, "values": [merged]})
                stats["to_update_rows"].append({
                    "section": key,
                    "tag": tag,
                    "file": fname,
                    "title": matched.get("title", ""),
                    "old_link": old_link,
                    "new_link": new_link,
                    "old_source": old_source
                })
                sec_stats["to_update"] += 1
            else:
                to_add.append(_row_from_record(record, headers))
                display_title = f"{folder_name} - {title}"
                stats["new_in_repo_rows"].append({"section": key, "tag": tag, "file": fname, "title": display_title, "link": new_link, "size": size_mb})
                sec_stats["new_in_repo"] += 1

        for r in rows_for_match:
            if r["_row"] in matched_row_indices: continue
            link = str(r.get("download_link", "") or "").strip()
            if not link: continue
            source = detect_link_source(link)
            if source in ("yandex", "terabox"):
                stats["legacy_only_rows"].append({"section": key, "row": r["_row"], "title": r.get("title", ""), "folder": r.get("folder", ""), "link": link, "source": source})
                sec_stats["legacy_only"] += 1

        print(f"     К обновлению ссылок:  {sec_stats['to_update']}")
        print(f"     Новых в репо:         {sec_stats['new_in_repo']}")
        print(f"     Legacy (без миграции): {sec_stats['legacy_only']}")
        print(f"     Без изменений:        {sec_stats['unchanged']}")

        stats["sections"][key] = sec_stats

        if dry_run: continue
        if (updates or to_add) and BACKUP_BEFORE_SYNC: backup_sheet(sh, sheet, key, all_values)
        if updates: batch_update_rows(sheet, updates)
        if to_add: append_rows_safe(sheet, to_add)

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

    if item.get("title"):
        item["file_id"] = slugify(item["title"])

    folder_val = item.get("folder", "")
    if folder_val:
        lower_folder = folder_val.strip().lower()
        if lower_folder in FOLDER_TRANSLATIONS:
            item["folder"] = FOLDER_TRANSLATIONS[lower_folder]

    return item

def _check_description_length(item: dict) -> int:
    desc = item.get("description") or item.get("body") or item.get("text") or ""
    return len(str(desc).strip())

def generate_json_for_section(worksheet, json_path: str, columns: list[str] | None = None, headers: list[str] | None = None, hidden_set: set[tuple[str, str]] | None = None) -> dict | None:
    if hidden_set is None: hidden_set = set()
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
        print("  Лист пуст → записываем []")
        try:
            with open(json_path, "w", encoding="utf-8") as f: json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e: print(f"  ОШИБКА записи JSON: {e}"); return None
        return {"count": 0, "short_descs": []}

    json_data: list[dict] = []
    skipped_no_title, skipped_hidden, short_descs = 0, 0, []
    unique_items_dict = {}
    skipped_duplicates = 0

    for row in records:
        item = row_to_item(row, columns)
        if not item.get("title"): skipped_no_title += 1; continue

        if hidden_set:
            folder_val, title_val = (item.get("folder") or "").strip().lower(), (item.get("title") or "").strip().lower()
            if (folder_val, title_val) in hidden_set: skipped_hidden += 1; continue

        compact_key = _compact_match_str(item["title"])

        if compact_key in unique_items_dict:
            skipped_duplicates += 1
            existing = unique_items_dict[compact_key]
            has_desc_new = len(str(item.get("description", "")).strip()) > 0
            has_desc_old = len(str(existing.get("description", "")).strip()) > 0
            
            if has_desc_new and not has_desc_old:
                unique_items_dict[compact_key] = item
            elif has_desc_new == has_desc_old:
                link_new = detect_link_source(item.get("download_link", "")) == "release"
                link_old = detect_link_source(existing.get("download_link", "")) == "release"
                if link_new and not link_old:
                    unique_items_dict[compact_key] = item
        else:
            unique_items_dict[compact_key] = item

    for item in unique_items_dict.values():
        if MIN_DESCRIPTION_LENGTH > 0:
            desc_len = _check_description_length(item)
            if desc_len < MIN_DESCRIPTION_LENGTH:
                short_descs.append({"title": item.get("title", ""), "length": desc_len, "file_id": item.get("file_id", "")})
        json_data.append(item)

    try:
        with open(json_path, "w", encoding="utf-8") as f: json.dump(json_data, f, ensure_ascii=False, indent=2)
    except Exception as e: print(f"  ОШИБКА записи JSON: {e}"); return None

    msg = f"  ✓ Записано: {len(json_data)} записей"
    extras = []
    if skipped_no_title: extras.append(f"без title: {skipped_no_title}")
    if skipped_hidden: extras.append(f"скрытых: {skipped_hidden}")
    if skipped_duplicates: extras.append(f"удалено дублей (в JSON): {skipped_duplicates}")
    if short_descs: extras.append(f"коротких описаний: {len(short_descs)}")
    if extras: msg += " (пропущено — " + ", ".join(extras) + ")"
    print(msg)
    return {"count": len(json_data), "short_descs": short_descs}

def sheets_to_json(gs_client, sections: list[dict], dry_run: bool, repo_dir: str = ".") -> dict:
    stats = {"sections_ok": 0, "sections_failed": [], "total_records": 0, "sections_stats": [], "errors": []}
    print("\n" + "=" * 60 + "\nШАГ B: Google Sheets → JSON\n" + "=" * 60)
    if not sections: stats["errors"].append("Нет активных разделов"); return stats
    try: sh = open_spreadsheet(gs_client)
    except Exception as e: stats["errors"].append(f"Не удалось открыть таблицу: {e}"); return stats

    for section in sections:
        key, label = section.get("key") or "?", section.get("label") or key
        sheet_name, json_path = section.get("sheet_name") or label, section.get("json_path")
        columns = section.get("columns") or []
        print(f"\n=== Раздел: {label} ({key}) ===")
        if not json_path: stats["sections_failed"].append((key, "нет json_path")); continue
        json_path = os.path.join(repo_dir, json_path)
        try: worksheet = sh.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            stats["sections_failed"].append((key, f"лист «{sheet_name}» не найден")); continue
        except Exception as e:
            stats["sections_failed"].append((key, str(e))); continue
        hidden_set = load_hidden_items(key)
        result = generate_json_for_section(worksheet, json_path, columns, hidden_set=hidden_set)
        if result is not None:
            stats["sections_ok"] += 1
            stats["total_records"] += result["count"]
            stats["sections_stats"].append({"key": key, "label": label, "short_descs": result["short_descs"]})
        else: stats["sections_failed"].append((key, "ошибка генерации"))

    try: generate_sitemap(sections, repo_dir)
    except Exception as e: stats["errors"].append(str(e))
    print_short_desc_report(stats["sections_stats"])

    print("\n" + "=" * 60)
    print(f"Обработано разделов: {stats['sections_ok']} из {len(sections)}\nВсего записей:       {stats['total_records']}")
    if stats["sections_failed"]:
        print(f"\nПроблемные разделы ({len(stats['sections_failed'])}):")
        for k, reason in stats["sections_failed"]: print(f"  • {k}: {reason}")
    print("=" * 60)
    return stats


# ============================================================
# SITEMAP.XML
# ============================================================
def generate_sitemap(sections: list[dict], repo_dir: str = ".") -> None:
    static_pages = [{"loc": "/index.html", "changefreq": "daily",  "priority": "1.0"}, {"loc": "/forum.html", "changefreq": "weekly", "priority": "0.7"}]
    section_pages = [{"loc": f"/#{s.get('key')}", "changefreq": "daily", "priority": "0.9"} for s in sections if s.get("key")]
    today = datetime.datetime.utcnow().strftime("%Y-%m-%d")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for page in static_pages + section_pages:
        lines.extend(["  <url>", f"    <loc>{SITE_BASE_URL}{page['loc']}</loc>", f"    <lastmod>{today}</lastmod>", f"    <changefreq>{page['changefreq']}</changefreq>", f"    <priority>{page['priority']}</priority>", "  </url>"])
    lines.append("</urlset>")
    path = os.path.join(repo_dir, "sitemap.xml")
    try:
        with open(path, "w", encoding="utf-8") as f: f.write("\n".join(lines) + "\n")
        print(f"\n=== sitemap.xml ===\n  ✓ Создан: {len(static_pages) + len(section_pages)} URL (base: {SITE_BASE_URL})")
    except Exception as e: print(f"  [!] Ошибка sitemap.xml: {e}")


# ============================================================
# ОТЧЁТЫ
# ============================================================
def _append_github_summary(text: str) -> None:
    if not GITHUB_STEP_SUMMARY: return
    try:
        with open(GITHUB_STEP_SUMMARY, "a", encoding="utf-8") as f: f.write(text)
    except Exception: pass

def print_short_desc_report(sections_stats: list[dict]) -> None:
    total_short = sum(len(s["short_descs"]) for s in sections_stats)
    if total_short == 0: return
    print("\n" + "=" * 60 + f"\n=== ВАЛИДАЦИЯ ОПИСАНИЙ ===\nПорог: описание < {MIN_DESCRIPTION_LENGTH} символов\nНайдено: {total_short}\n" + "=" * 60)
    md_lines = [f"## Валидация описаний\n", f"- Порог: **< {MIN_DESCRIPTION_LENGTH} символов**", f"- Найдено записей: **{total_short}**\n"]
    for s in sections_stats:
        if not s["short_descs"]: continue
        print(f"\n{s['label']} ({s['key']}):")
        md_lines.extend([f"### {s['label']} (`{s['key']}`)\n", "| Название | Длина | file_id |", "|----------|-------|---------|"])
        for item in s["short_descs"]:
            title = item["title"] or "(без названия)"
            print(f"  • {title} — {item['length']} симв.")
            md_lines.append(f"| {title} | {item['length']} | `{item['file_id']}` |")
        md_lines.append("")
    _append_github_summary("\n".join(md_lines) + "\n")

def build_migration_report(repo_stats: dict, json_stats: dict, mode: str) -> dict:
    return {"ts": datetime.datetime.utcnow().isoformat() + "Z", "mode": mode, "repo_to_sheets": repo_stats, "sheets_to_json": json_stats}

def save_migration_report(report: dict, repo_dir: str = ".") -> str | None:
    try:
        os.makedirs(os.path.join(repo_dir, REPORTS_DIR), exist_ok=True)
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        path = os.path.join(repo_dir, REPORTS_DIR, f"migration_{ts}.json")
        with open(path, "w", encoding="utf-8") as f: json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[report] Сохранён: {path}")
        return path
    except Exception as e:
        print(f"[!] Не удалось сохранить отчёт: {e}")
        return None

def _fmt_titles_list(titles: list[str], max_show: int = 20) -> str:
    if not titles: return ""
    shown = titles[:max_show]
    tail = len(titles) - len(shown)
    s = ", ".join(shown)
    if tail > 0: s += f" … (+{tail} ещё)"
    return s

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
            
        # ─── ДЕТАЛЬНЫЙ ВЫВОД ОБНОВЛЕННЫХ ССЫЛОК ───
        to_update_rows = repo_stats.get("to_update_rows") or []
        if to_update_rows:
            lines.append(f"\n🔄 *Детали обновления ссылок* ({len(to_update_rows)}):")
            for r in to_update_rows[:20]: # Выводим первые 20
                lines.append(f"  • {r.get('title', '')}")
                lines.append(f"    Было:  `{r.get('old_link', '')}`")
                lines.append(f"    Стало: `{r.get('new_link', '')}`")
            if len(to_update_rows) > 20:
                lines.append(f"  ... и еще {len(to_update_rows) - 20}")

    if json_stats:
        lines.extend(["", "*Генерация JSON*", f"• разделов: {json_stats.get('sections_ok', 0)}", f"• записей: {json_stats.get('total_records', 0)}"])
        if json_stats.get("sections_failed"): lines.append(f"• ошибок: {len(json_stats['sections_failed'])}")
        
    # ─── УЛУЧШЕННЫЙ ВЫВОД LEGACY-ССЫЛОК ───
    legacy_rows = (repo_stats or {}).get("legacy_only_rows") or []
    if legacy_rows:
        yandex_rows = [r for r in legacy_rows if r.get("source") == "yandex"]
        terabox_rows = [r for r in legacy_rows if r.get("source") == "terabox"]
        
        lines.append("")
        lines.append(f"⚠️ *Legacy требует решения* (всего {len(legacy_rows)}):")
        
        if yandex_rows:
            lines.append(f"\n🔴 *Яндекс.Диск* ({len(yandex_rows)}):")
            for r in yandex_rows[:15]:
                lines.append(f"  • {r.get('title', '')} (`{r.get('folder', '')}`)")
            if len(yandex_rows) > 15:
                lines.append(f"  ... и еще {len(yandex_rows) - 15}")
                
        if terabox_rows:
            lines.append(f"\n🟡 *TeraBox* ({len(terabox_rows)}):")
            for r in terabox_rows[:15]:
                lines.append(f"  • {r.get('title', '')} (`{r.get('folder', '')}`)")
            if len(terabox_rows) > 15:
                lines.append(f"  ... и еще {len(terabox_rows) - 15}")

    new_rows = (repo_stats or {}).get("new_in_repo_rows") or []
    if new_rows:
        new_titles = [r.get("title", "") for r in new_rows if r.get("title")]
        lines.extend(["", f"➕ *Новые в репо* ({len(new_rows)}):", _fmt_titles_list(new_titles, max_show=10)])
    notify_telegram("\n".join(lines))


# ============================================================
# MAIN
# ============================================================
def _resolve_sections_for_run(all_sections: list[dict], filter_keys: list[str] | None) -> list[dict]:
    if not all_sections:
        all_sections = []
        for k, cfg in SECTION_CONFIG_FALLBACK.items():
            all_sections.append({"key": k, "label": cfg["label"], "icon": cfg.get("icon", "fa-folder"), "sheet_name": cfg["sheet_name"], "json_path": cfg["json_path"], "container": cfg["container"], "folderable": cfg.get("folderable", False), "columns": cfg["columns"]})
    if filter_keys:
        wanted = set(filter_keys)
        all_sections = [s for s in all_sections if s.get("key") in wanted]
    return all_sections

def main() -> None:
    parser = argparse.ArgumentParser(description="MyFiles: GitHub Releases → Sheets → JSON")
    parser.add_argument("--mode", choices=["repo-to-sheets", "sheets-to-json", "all", "report-only"], default="all")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--in-place", action="store_true")
    parser.add_argument("--sections", default="")
    parser.add_argument("--tags", default="")
    parser.add_argument("--repo-dir", default=".")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    dry_run = not args.in_place
    if args.dry_run and args.in_place: dry_run = False

    section_filter = [s.strip() for s in args.sections.split(",") if s.strip()] or None
    tag_filter = [t.strip() for t in args.tags.split(",") if t.strip()] or None

    print("=" * 60 + f"\nupdate_content_json.py\nРежим: {args.mode}\nDry-run: {dry_run}\n" + "=" * 60)

    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run_url = f"https://github.com/{repo}/actions/runs/{os.environ['GITHUB_RUN_ID']}"

    repo_stats, json_stats = {}, {}
    try:
        all_sections = load_active_sections()
        sections = _resolve_sections_for_run(all_sections, section_filter)

        need_sheets = args.mode in ("repo-to-sheets", "sheets-to-json", "all")
        gs_client = None
        if need_sheets:
            gs_client = get_gspread_client()
            health = check_sheets_health(gs_client, sections)
            print_sheets_health(health)
            if not health.get("ok"):
                notify_result(title="Update content JSON", status="failure", details="Проверка Google Sheets не пройдена", extra_lines=(health.get("errors") or [])[:10], run_url=run_url)
                sys.exit(1)

        if args.mode in ("repo-to-sheets", "all"):
            repo_stats = repo_to_sheets(gs_client, sections, dry_run, tag_filter=tag_filter)
        if args.mode in ("sheets-to-json", "all"):
            json_stats = sheets_to_json(gs_client, sections, dry_run, repo_dir=args.repo_dir)

        report = build_migration_report(repo_stats, json_stats, args.mode)
        save_migration_report(report, repo_dir=args.repo_dir)

        errors_count = len(repo_stats.get("errors") or []) + len(json_stats.get("errors") or []) + len(json_stats.get("sections_failed") or [])
        status = "failure" if errors_count > 0 else "success"

        total_to_update = sum(s["to_update"] for s in (repo_stats.get("sections") or {}).values())
        total_new = sum(s["new_in_repo"] for s in (repo_stats.get("sections") or {}).values())
        total_legacy = sum(s["legacy_only"] for s in (repo_stats.get("sections") or {}).values())
        details = f"обновлено ссылок: {total_to_update}, новых в репо: {total_new}, legacy: {total_legacy}"
        if dry_run: details = "[DRY-RUN] " + details

        notify_migration_report(repo_stats, json_stats, run_url=run_url)
        notify_result(title="Update content JSON", status=status, details=details, extra_lines=[f"Режим: {args.mode}", f"Секций: {len(sections)}"], run_url=run_url)

        if errors_count > 0: sys.exit(1)
    except Exception as e:
        print(f"\n[!!!] Критическая ошибка: {e}")
        traceback.print_exc()
        notify_result(title="Update content JSON", status="failure", details=f"Критическая ошибка: {e}", run_url=run_url)
        sys.exit(1)

if __name__ == "__main__":
    main()
