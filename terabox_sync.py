#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
terabox_sync.py (v2)
Синхронизация TeraBox → Google Sheets.

Ключевые изменения против v1:
- Используется Playwright (Chromium) вместо terabox-api/gateway,
  т.к. только так можно обойти вложенные папки публичной ссылки.
- Обходит ВСЕ подпапки разделов, формируя поле `folder` из имени папки TeraBox.
- Скачивает и парсит 4 файла описаний (1_Software.txt + описание*.txt)
  в любых кодировках (UTF-16 LE/BE, cp1251, utf-8).
- Сопоставляет файлы TeraBox с описаниями по имени файла.

Обрабатываются только разделы из site_sections, у которых
yandex_url содержит домен terabox.com или 1024terabox.com.

TERABOX_COOKIE — cookie 'ndus' аккаунта TeraBox.
"""

import os
import re
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
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


# ============================================================
# КОНФИГУРАЦИЯ
# ============================================================

SPREADSHEET_ID   = os.environ.get("SPREADSHEET_ID", "")
SPREADSHEET_NAME = os.environ.get("SPREADSHEET_NAME", "НаполнениеСайта")

SUPABASE_URL = "https://rmoonebbvpmvthvpcmpt.supabase.co"
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

TERABOX_COOKIE = os.environ.get("TERABOX_COOKIE", "")

TERABOX_DOMAINS = ("terabox.com", "1024terabox.com")

PRESERVE_USER_EDITS = os.environ.get("PRESERVE_USER_EDITS", "1") == "1"
BACKUP_BEFORE_SYNC  = os.environ.get("BACKUP_BEFORE_SYNC", "1") == "1"
BACKUP_KEEP_COUNT   = int(os.environ.get("BACKUP_KEEP_COUNT", "3"))

_raw_sync_sections = os.environ.get("SYNC_SECTIONS", "").strip()
SYNC_SECTIONS_FILTER = [
    s.strip() for s in _raw_sync_sections.split(",") if s.strip()
] if _raw_sync_sections else []

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

ALWAYS_UPDATE_HEADERS = {
    "Ссылка для скачивания", "Ссылка",
    "Размер (МБ)", "Размер",
    "Формат",
    "download_link", "link", "size", "format",
}

TITLE_HEADER_CANDIDATES = ("Название", "название", "Title", "title")

COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com", ".d.terabox.app",
]

DESC_FILE_PATTERNS = [
    re.compile(r"^1_Software\.txt$", re.IGNORECASE),
    re.compile(r"^описание( \d+)?\.txt$", re.IGNORECASE),
]

# Папки, которые НЕ являются контейнерами программ (служебные)
SKIP_FOLDER_NAMES = set()


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
        print(f"  Найдено файлов:          {self.found}")
        print(f"  Оставлено к записи:      {self.kept}")
        print(f"  Обновлено строк:         {self.updated}")
        print(f"  Добавлено строк:         {self.added}")
        if self.preserved_edits:
            print(f"  Сохранено ручных правок: {self.preserved_edits}")
        if self.unchanged_rows:
            print(f"  Без изменений:           {self.unchanged_rows}")
        if self.orphans_found:
            print(f"  Осиротевших строк:       {self.orphans_found}")
        if self.backup_name:
            print(f"  Резервная копия:         {self.backup_name}")
        if self.errors:
            print(f"  Ошибок:                  {len(self.errors)}")
            for e in self.errors[:5]:
                print(f"    - {e}")
        print("  ───────────────────\n")


# ============================================================
# SUPABASE
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
# GOOGLE SHEETS
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
        print(f"    [+] Обновлены заголовки: {headers}")
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


# ============================================================
# PLAYWRIGHT: ПЕРЕХВАТ XHR
# ============================================================

class Catcher:
    def __init__(self):
        self.responses = []

    def attach(self, page):
        def on_response(resp):
            if "/share/list" in resp.url and "/static/" not in resp.url:
                try:
                    data = resp.json()
                    self.responses.append({"data": data, "ts": time.time()})
                except Exception:
                    pass
        page.on("response", on_response)

    def count(self):
        return len(self.responses)

    def wait_new(self, page, prev_count, timeout_ms=15000):
        elapsed = 0
        while elapsed < timeout_ms:
            if len(self.responses) > prev_count:
                return self.responses[-1]
            page.wait_for_timeout(200)
            elapsed += 200
        return None


def _double_click_folder(page, name):
    loc = page.locator(f'.file-item-listmode:has-text("{name}")').first
    if loc.count() == 0:
        return False
    try:
        loc.scroll_into_view_if_needed(timeout=3000)
    except Exception:
        pass
    page.wait_for_timeout(200)
    try:
        loc.dblclick(timeout=5000)
        return True
    except Exception:
        return False


# ============================================================
# ДЕКОДИРОВАНИЕ ТЕКСТА
# ============================================================

def decode_bytes(raw):
    if not raw:
        return ""
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16-le", errors="replace")
    if raw[:2] == b"\xfe\xff":
        return raw.decode("utf-16-be", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig", errors="replace")

    sample = raw[:400]
    if len(sample) >= 8:
        nulls_odd  = sum(1 for i in range(1, min(200, len(sample)), 2) if sample[i] == 0)
        nulls_even = sum(1 for i in range(0, min(200, len(sample)), 2) if sample[i] == 0)
        if nulls_odd > 40:
            return raw.decode("utf-16-le", errors="replace")
        if nulls_even > 40:
            return raw.decode("utf-16-be", errors="replace")

    markers = ("prog[pn]", "desc[pn]", "cmds[pn]", "[MInst]", "Name=", "Patch=")
    for enc in ("cp1251", "utf-8", "koi8-r", "cp866"):
        try:
            text = raw.decode(enc)
            if any(m in text for m in markers):
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", errors="replace")


def read_text_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    return decode_bytes(raw)


# ============================================================
# ОЧИСТКА ИМЁН ФАЙЛОВ
# ============================================================

def clean_patch_filename(name):
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r'"\s+.*$', '"', s)
    parts = re.split(r"[\\/]", s)
    last = parts[-1] if parts else s
    last = re.split(r"\s+", last)[0]
    last = last.strip("\"'")
    last = re.sub(r"-?\{P\}", "", last, flags=re.IGNORECASE)
    return last.strip()


# ============================================================
# ПАРСИНГ ОПИСАНИЙ
# ============================================================

def parse_old_format(content):
    programs = []
    current = None
    state = None

    for raw_line in content.split("\n"):
        line = raw_line.rstrip("\r")
        if re.match(r"^\[\d+\]\s*$", line.strip()):
            if current and current.get("name"):
                programs.append(current)
            current = {"name": "", "description": "",
                       "patch": "", "patch_filename": ""}
            state = None
            continue
        if current is None:
            continue
        if line.startswith("Name="):
            current["name"] = line[5:].strip(); state = None
        elif line.startswith("Hint="):
            current["description"] = line[5:].strip(); state = "hint"
        elif line.startswith("Patch="):
            current["patch"] = line[6:].strip(); state = None
        elif state == "hint" and line.strip() and not line.startswith("["):
            current["description"] += "\n" + line
        else:
            state = None

    if current and current.get("name"):
        programs.append(current)

    for p in programs:
        p["patch_filename"] = clean_patch_filename(p.get("patch", ""))
        hint = p.get("description", "")
        if hint:
            if hint.startswith("|"):
                hint = hint[1:]
            hint = hint.replace("|", "\n")
            hint = re.sub(r"\n+", "\n", hint).strip()
            p["description"] = hint
    return programs


def parse_wpi_format(content):
    programs = []
    blocks = re.split(r"\bpn\s*\+\+\s*;", content)
    for block in blocks:
        if "prog[pn]" not in block:
            continue
        entry = {"name": "", "description": "",
                 "patch": "", "patch_filename": ""}
        m = re.search(r"prog\[pn\]\s*=\s*\[(.+?)\]\s*;", block, re.DOTALL)
        if m:
            parts = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
            entry["name"] = "".join(parts).strip()
        m = re.search(r"desc\[pn\]\s*=\s*\[(.+?)\]\s*;", block, re.DOTALL)
        if m:
            parts = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
            entry["description"] = "".join(parts).strip()
        m = re.search(r"cmds\[pn\]\s*=\s*\[(.+?)\]\s*;", block, re.DOTALL)
        if m:
            parts = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
            cmds_str = "".join(parts)
            entry["patch"] = cmds_str
            entry["patch_filename"] = clean_patch_filename(cmds_str)
        if entry["name"]:
            programs.append(entry)
    return programs


def detect_format(content):
    if "prog[pn]" in content:
        return "wpi"
    if "Name=" in content and re.search(r"^\[\d+\]", content, re.MULTILINE):
        return "old"
    return "unknown"


# ============================================================
# СОПОСТАВЛЕНИЕ
# ============================================================

def normalize_filename(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(
        r"\.(exe|msi|zip|rar|7z|tar|gz|txt|dll|bat|cmd|ps1)$", "", name
    )
    return name.strip()


def normalize_aggressive(name):
    return re.sub(r"[\s\.\-_]+", "", (name or "").lower())


def match_file_to_program(filename, programs):
    fn_norm = normalize_filename(filename)
    fn_agg = normalize_aggressive(fn_norm)
    if not fn_agg:
        return None

    for p in programs:
        if normalize_filename(p.get("patch_filename", "")) == fn_norm:
            return p
    for p in programs:
        if normalize_aggressive(p.get("patch_filename", "")) == fn_agg:
            return p
    for p in programs:
        p_agg = normalize_aggressive(p.get("patch_filename", ""))
        if len(fn_agg) >= 6 and len(p_agg) >= 6:
            if fn_agg in p_agg or p_agg in fn_agg:
                return p

    # Fallback: по названию программы
    fn_words = set(re.findall(r"[a-zа-яё0-9]{4,}", fn_norm.replace("ё", "е")))
    if not fn_words:
        return None
    best, best_score = None, 0
    for p in programs:
        name_words = set(
            re.findall(r"[a-zа-яё0-9]{4,}",
                       (p.get("name", "") or "").lower().replace("ё", "е"))
        )
        if not name_words:
            continue
        inter = fn_words & name_words
        if len(inter) >= 2:
            score = len(inter) / len(name_words)
            if score >= 0.6 and score > best_score:
                best_score = score
                best = p
    return best


def parse_filename_title(filename):
    """Простое извлечение названия из имени файла, если описания нет."""
    if not filename:
        return ""
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


# ============================================================
# PLAYWRIGHT: ОБХОД TERABOX И СБОР ДАННЫХ
# ============================================================

def _download_desc_file(context, dlink, save_path):
    resp = context.request.get(dlink, timeout=180000)
    if resp.status != 200:
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    return save_path


def _load_all_programs(context, desc_items, diag):
    all_programs = []
    seen = set()
    for item in desc_items:
        name = item["name"]
        dlink = item.get("dlink")
        if not dlink:
            continue
        save = f"/tmp/{name}"
        try:
            if not _download_desc_file(context, dlink, save):
                print(f"    [!] Не удалось скачать {name}")
                continue
        except Exception as e:
            print(f"    [!] Ошибка скачивания {name}: {e}")
            continue

        content = read_text_file(save)
        fmt = detect_format(content)
        if fmt == "wpi":
            programs = parse_wpi_format(content)
        elif fmt == "old":
            programs = parse_old_format(content)
        else:
            print(f"    [!] Неизвестный формат: {name}")
            continue

        print(f"    • {name}: {len(programs)} записей ({fmt})")
        for p in programs:
            key = (p.get("patch_filename") or "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            all_programs.append(p)
    return all_programs


def _build_record(item, folder_name, programs):
    """Формирует запись для Sheets из одного файла TeraBox."""
    fname = item.get("server_filename") or ""
    if not fname:
        return None

    matched = match_file_to_program(fname, programs) if programs else None

    if matched:
        title = matched["name"]
        description = matched.get("description", "")
    else:
        title = parse_filename_title(fname)
        description = ""

    size_bytes = item.get("size") or 0
    try:
        size_mb = str(round(int(size_bytes) / (1024 * 1024), 1))
    except Exception:
        size_mb = ""

    return {
        "title":         title,
        "description":   description,
        "version":       "",
        "size":          size_mb,
        "download_link": item.get("dlink", ""),
        "folder":        folder_name,
    }


def fetch_terabox_records(start_url, section, diag):
    """
    Открывает Playwright, обходит раздел TeraBox, возвращает список записей.
    """
    if sync_playwright is None:
        print("  [!] playwright не установлен.")
        return []

    records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(
                user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/120.0.0.0 Safari/537.36"),
                locale="ru-RU",
                viewport={"width": 1366, "height": 900},
            )
            for domain in COOKIE_DOMAINS:
                try:
                    context.add_cookies([{
                        "name": "ndus", "value": TERABOX_COOKIE,
                        "domain": domain, "path": "/",
                        "secure": True, "sameSite": "None",
                    }])
                except Exception:
                    pass

            page = context.new_page()
            catcher = Catcher()
            catcher.attach(page)

            print(f"  Открываю {start_url}")
            page.goto(start_url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)

            initial = catcher.wait_new(page, 0, timeout_ms=15000)
            if not initial:
                print("  [!] Нет ответа /share/list")
                return []

            items = initial["data"].get("list") or []
            print(f"  Содержимое корня: {len(items)} элементов")

            # ─── Определяем целевую подпапку ───
            target_subfolder = None
            yandex_path = (section.get("yandex_path") or "").strip("/")

            if yandex_path:
                # yandex_path = имя папки внутри шаренной ссылки
                first_seg = yandex_path.split("/")[-1]
                for it in items:
                    if (str(it.get("isdir")) == "1"
                            and it.get("server_filename") == first_seg):
                        target_subfolder = first_seg
                        break
            else:
                # Если в корне только одна папка «Программы» — заходим
                subdir_names = [it.get("server_filename") for it in items
                                if str(it.get("isdir")) == "1"]
                if "Программы" in subdir_names:
                    target_subfolder = "Программы"
                elif len(subdir_names) == 1:
                    target_subfolder = subdir_names[0]

            if target_subfolder:
                print(f"  Вход в подпапку: {target_subfolder}")
                prev = catcher.count()
                if not _double_click_folder(page, target_subfolder):
                    print(f"  [!] Не удалось войти в {target_subfolder}")
                    return []
                page.wait_for_timeout(4000)
                res = catcher.wait_new(page, prev, timeout_ms=15000)
                if not res:
                    print("  [!] Нет ответа после входа")
                    return []
                items = res["data"].get("list") or []
                print(f"  Содержимое {target_subfolder}: {len(items)} элементов")

            # ─── Разделяем содержимое ───
            desc_items = []
            root_files = []
            subdirs = []

            for it in items:
                name = it.get("server_filename") or ""
                if str(it.get("isdir")) == "1":
                    subdirs.append(it)
                elif any(p.match(name) for p in DESC_FILE_PATTERNS):
                    desc_items.append({"name": name,
                                       "dlink": it.get("dlink") or ""})
                else:
                    root_files.append(it)

            print(f"  Файлов описаний: {len(desc_items)}, "
                  f"файлов в корне: {len(root_files)}, "
                  f"подпапок: {len(subdirs)}")

            # ─── Парсим описания ───
            programs = _load_all_programs(context, desc_items, diag)
            print(f"  Программ из описаний: {len(programs)}")

            # ─── Файлы в корне «Программы» (folder = "") ───
            for it in root_files:
                rec = _build_record(it, "", programs)
                if rec:
                    records.append(rec)

            # ─── Обход подпапок ───
            for i, sub in enumerate(subdirs):
                sub_name = sub.get("server_filename")
                print(f"\n  ── [{i+1}/{len(subdirs)}] {sub_name}")

                # Возврат в родительскую папку
                if i > 0 or target_subfolder:
                    page.goto(start_url,
                              wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(5000)
                    if target_subfolder:
                        prev = catcher.count()
                        if not _double_click_folder(page, target_subfolder):
                            print(f"    [!] Не удалось вернуться")
                            continue
                        page.wait_for_timeout(3000)
                        catcher.wait_new(page, prev, timeout_ms=10000)

                prev = catcher.count()
                if not _double_click_folder(page, sub_name):
                    print(f"    [!] Не удалось открыть '{sub_name}'")
                    continue
                page.wait_for_timeout(4000)

                res_sub = catcher.wait_new(page, prev, timeout_ms=15000)
                if not res_sub:
                    print(f"    [!] Нет ответа")
                    continue

                items_sub = res_sub["data"].get("list") or []
                files_only = [it for it in items_sub
                              if str(it.get("isdir")) != "1"]
                matched = 0
                for it in files_only:
                    rec = _build_record(it, sub_name, programs)
                    if rec:
                        records.append(rec)
                        if match_file_to_program(
                                it.get("server_filename", ""), programs):
                            matched += 1
                print(f"    Файлов: {len(files_only)}, "
                      f"с описанием: {matched}")

        except Exception as e:
            print(f"  [!!!] Ошибка Playwright: {e}")
            traceback.print_exc()
        finally:
            try:
                browser.close()
            except Exception:
                pass

    return records


# ============================================================
# СИНХРОНИЗАЦИЯ РАЗДЕЛА
# ============================================================

def sync_terabox_section(section, gs_client):
    label = section.get("label") or section.get("key")
    section_key = section.get("key")
    yandex_url = section.get("yandex_url") or ""
    sheet_name = section.get("sheet_name") or label
    columns = section.get("columns") or ["title", "description", "download_link"]

    print(f"\n=== Раздел TeraBox: {label} ({section_key}) ===")
    print(f"Ссылка:      {yandex_url[:100]}")
    print(f"Лист Sheets: {sheet_name}")

    if not TERABOX_COOKIE:
        print("  [!] TERABOX_COOKIE не задан — пропускаю раздел.")
        return

    diag = Diag(label)

    # Поддерживаем несколько ссылок через перевод строки
    urls = [u.strip() for u in yandex_url.split("\n") if u.strip()]
    all_records = []
    for u in urls:
        print(f"\n  Загрузка TeraBox: {u[:90]}")
        recs = fetch_terabox_records(u, section, diag)
        print(f"  Получено записей: {len(recs)}")
        all_records.extend(recs)

    # Дедупликация по download_link
    dedup = {}
    for r in all_records:
        link = r.get("download_link")
        if link and link not in dedup:
            dedup[link] = r
    all_records = list(dedup.values())

    diag.found = len(all_records)
    print(f"\n  Итого уникальных записей: {len(all_records)}")

    # ─── Формируем строки для Sheets ───
    headers = headers_from_columns(columns)
    rows = [_row_from_record(rec, headers) for rec in all_records]
    diag.kept = len(rows)

    # ─── Открываем таблицу ───
    try:
        sh = open_spreadsheet(gs_client)
    except Exception as e:
        print(f"  [!] Не удалось открыть таблицу: {e}")
        return

    sheet = get_or_create_sheet(sh, sheet_name)
    ensure_headers(sheet, headers)

    all_values, existing = load_sheet_snapshot(sheet)
    print(f"  Существующих строк в Sheets: {len(existing)}")

    link_ru = "Ссылка для скачивания"
    link_idx = headers.index(link_ru) if link_ru in headers else 0
    n_cols = len(headers)
    end_col_letter = _col_letter(n_cols - 1)

    # ─── Сироты ───
    orphans = find_orphan_rows(existing, rows, headers, link_idx)
    diag.orphans_found = len(orphans)
    if orphans:
        print(f"  Осиротевших строк: {len(orphans)}")
    save_orphans_to_supabase(section_key, label, sheet_name,
                             orphans, headers)

    # ─── Изменения ───
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
        diag.backup_name = backup_sheet(sh, sheet, section_key,
                                        all_values) or ""

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
    print("terabox_sync.py (v2) — старт")
    print("=" * 60)
    print(f"PRESERVE_USER_EDITS = {PRESERVE_USER_EDITS}")
    print(f"BACKUP_BEFORE_SYNC  = {BACKUP_BEFORE_SYNC}")
    print(f"TERABOX_COOKIE      = {'задан' if TERABOX_COOKIE else 'НЕ задан'}")
    if SYNC_SECTIONS_FILTER:
        print(f"SYNC_SECTIONS_FILTER = {SYNC_SECTIONS_FILTER}")

    if sync_playwright is None:
        print("[!] playwright не установлен.")
        print("    Добавьте 'playwright' в requirements.txt")
        print("    и выполните: python -m playwright install chromium")
        return

    if not TERABOX_COOKIE:
        print("[!] TERABOX_COOKIE не задан — выходим.")
        return

    print("\nЗагрузка разделов из Supabase...")
    sections = load_sections_from_supabase()
    if not sections:
        print("[!] Нет активных разделов — выходим.")
        return

    terabox_sections = [
        s for s in sections if is_terabox_url(s.get("yandex_url", ""))
    ]
    print(f"  Найдено TeraBox-разделов: {len(terabox_sections)}")

    if SYNC_SECTIONS_FILTER:
        before = len(terabox_sections)
        terabox_sections = [
            s for s in terabox_sections
            if s.get("key") in SYNC_SECTIONS_FILTER
        ]
        print(f"  После фильтра: {len(terabox_sections)} из {before}")

    if not terabox_sections:
        print("  Нет TeraBox-разделов для синхронизации.")
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
    print("=" * 60)


if __name__ == "__main__":
    main()
