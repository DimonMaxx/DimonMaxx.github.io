#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
terabox_sync.py (v4)
Синхронизация TeraBox → Google Sheets через Playwright.

Логика:
  1. Читает активные разделы из Supabase (site_sections).
  2. Оставляет только те, чей yandex_url содержит terabox.com / 1024terabox.com.
  3. Для каждого раздела:
       • Открывает Chromium, авторизуется cookie 'ndus'.
       • Заходит в рабочую папку (yandex_path или автоматически «Программы»).
       • Скачивает и парсит файлы описаний (1_Software.txt, описание*.txt).
       • Обходит все подпапки, собирая файлы (folder = имя подпапки).
       • Пишет результаты в Google Sheets.
       • Делает backup, находит orphans, сохраняет их в Supabase.
  4. По завершении отправляет итоговый отчёт в Telegram (через notify.py).

Переменные окружения:
  TERABOX_COOKIE, GOOGLE_CREDENTIALS_JSON, SPREADSHEET_ID,
  SUPABASE_SERVICE_ROLE_KEY, PRESERVE_USER_EDITS, BACKUP_BEFORE_SYNC,
  BACKUP_KEEP_COUNT, SYNC_SECTIONS,
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (для уведомлений).
"""

import os
import re
import sys
import json
import time
import datetime
import traceback

import gspread
from google.oauth2.service_account import Credentials

try:
    from supabase import create_client as supa_create_client
except ImportError:
    supa_create_client = None

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None

# ─── Уведомления в Telegram (опционально) ───
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

TITLE_HEADER_CANDIDATES  = ("Название", "название", "Title", "title")
FOLDER_HEADER_CANDIDATES = ("Папка", "папка", "Folder", "folder")

COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com", ".d.terabox.app",
]

DESC_FILE_PATTERNS = [
    re.compile(r"^1_Software\.txt$", re.IGNORECASE),
    re.compile(r"^описание( \d+)?\.txt$", re.IGNORECASE),
]

ARCH_SUFFIXES = re.compile(
    r"[-_.]?(x86|x64|x32|win32|win64|32|64|32bit|64bit)$",
    re.IGNORECASE,
)

FOLDER_OPEN_ATTEMPTS = 3


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
        self.matched_with_desc = 0
        self.without_desc      = 0
        self.failed_folders    = []

    def report(self):
        print("\n  ── ДИАГНОСТИКА ──")
        print(f"  Найдено файлов:          {self.found}")
        print(f"  Оставлено к записи:      {self.kept}")
        print(f"    в т.ч. с описанием:    {self.matched_with_desc}")
        print(f"    без описания:          {self.without_desc}")
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
        if self.failed_folders:
            print(f"  Не открыто папок:        {len(self.failed_folders)}")
            for f in self.failed_folders[:10]:
                print(f"    • {f}")
        if self.errors:
            print(f"  Ошибок:                  {len(self.errors)}")
            for e in self.errors[:5]:
                print(f"    - {e}")
        print("  ───────────────────\n")


# ============================================================
# ОПРЕДЕЛЕНИЕ ИСТОЧНИКА ПО URL
# ============================================================

def _detect_source(link):
    """
    Определяет источник по URL.
    Возвращает: 'terabox' | 'yandex' | 'unknown'.
    """
    if not link:
        return "unknown"
    s = str(link).lower()
    if ("terabox" in s or "1024tera" in s
            or "4funbox" in s or "teraboxapp" in s):
        return "terabox"
    if "disk.yandex" in s or "yadi.sk" in s:
        return "yandex"
    return "unknown"


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


def load_sheet_snapshot(sheet, headers):
    """
    Возвращает (all_values, existing_by_link, existing_by_key).

      existing_by_link — {download_link: {"row":N, "values":[...]}}
      existing_by_key  — {(folder_lower, title_lower): {...}}
    """
    try:
        rows = sheet.get_all_values()
    except Exception as e:
        print(f"    [!] Не удалось прочитать лист: {e}")
        return [], {}, {}

    if not rows:
        return [], {}, {}

    header = [(h or "").strip().lower() for h in rows[0]]

    link_idx = None
    for cand in ("ссылка для скачивания", "ссылка", "download_link", "link"):
        if cand in header:
            link_idx = header.index(cand)
            break

    title_idx = None
    for cand in [c.lower() for c in TITLE_HEADER_CANDIDATES]:
        if cand in header:
            title_idx = header.index(cand)
            break

    folder_idx = None
    for cand in [c.lower() for c in FOLDER_HEADER_CANDIDATES]:
        if cand in header:
            folder_idx = header.index(cand)
            break

    existing_by_link = {}
    existing_by_key  = {}

    if len(rows) >= 2:
        for i, r in enumerate(rows[1:], start=2):
            info = {"row": i, "values": list(r)}

            link = ""
            if link_idx is not None and link_idx < len(r):
                link = (r[link_idx] or "").strip()
            if link:
                existing_by_link[link] = info

            title = ""
            if title_idx is not None and title_idx < len(r):
                title = (r[title_idx] or "").strip().lower()

            folder = ""
            if folder_idx is not None and folder_idx < len(r):
                folder = (r[folder_idx] or "").strip().lower()

            if title or folder:
                existing_by_key[(folder, title)] = info

    return rows, existing_by_link, existing_by_key


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


# ============================================================
# PLAYWRIGHT: ПЕРЕХВАТ И СБОР
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


def collect_items(page, catcher, start_resp_idx,
                  max_iters=40, iter_wait_ms=700):
    seen = {}
    last_total = 0
    stable = 0

    for _ in range(max_iters):
        for resp in catcher.responses[start_resp_idx:]:
            for it in resp.get("data", {}).get("list") or []:
                name = it.get("server_filename") or ""
                if name and name not in seen:
                    seen[name] = it

        total = len(seen)
        if total == last_total and total > 0:
            stable += 1
            if stable >= 4:
                break
        else:
            stable = 0
            last_total = total

        try:
            page.mouse.wheel(0, 2500)
        except Exception:
            pass
        page.wait_for_timeout(iter_wait_ms)

    for resp in catcher.responses[start_resp_idx:]:
        for it in resp.get("data", {}).get("list") or []:
            name = it.get("server_filename") or ""
            if name and name not in seen:
                seen[name] = it

    pages = catcher.count() - start_resp_idx
    if pages > 0:
        print(f"    [collect] страниц: {pages}, элементов: {len(seen)}")

    return list(seen.values())


def scroll_list_top(page):
    try:
        page.mouse.wheel(0, -100000)
    except Exception:
        pass
    page.wait_for_timeout(400)


def find_folder_locator(page, name):
    selectors = [
        f'.file-item-listmode:has(.file-item-name:text-is("{name}"))',
        f'.file-item-listmode:has-text("{name}")',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


def open_folder(page, catcher, name, max_attempts=FOLDER_OPEN_ATTEMPTS):
    for attempt in range(max_attempts):
        prev_resp = catcher.count()
        scroll_list_top(page)
        page.wait_for_timeout(300)

        loc = find_folder_locator(page, name)
        if loc is None:
            print(f"    [open] попытка {attempt+1}: '{name}' не в DOM")
            page.mouse.wheel(0, 2500)
            page.wait_for_timeout(700)
            continue

        try:
            loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(250)

        clicked = False
        try:
            loc.dblclick(timeout=6000)
            clicked = True
        except Exception:
            try:
                loc.click(timeout=4000)
                clicked = True
            except Exception:
                pass

        if not clicked:
            page.wait_for_timeout(800)
            continue

        page.wait_for_timeout(2500)

        elapsed = 0
        while elapsed < 12000:
            if catcher.count() > prev_resp:
                break
            page.wait_for_timeout(200)
            elapsed += 200

        if catcher.count() <= prev_resp:
            print(f"    [open] попытка {attempt+1}: нет /share/list")
            continue

        items = collect_items(page, catcher, prev_resp)
        if not items:
            print(f"    [open] попытка {attempt+1}: пусто")
            continue

        return items

    return None


def download_file(context, dlink, save_path):
    print(f"    GET {dlink[:100]}...")
    resp = context.request.get(dlink, timeout=180000)
    if resp.status != 200:
        print(f"    HTTP {resp.status}")
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    print(f"    ✓ {save_path} ({len(body)} байт)")
    return save_path


# ============================================================
# КОДИРОВКИ И ПАРСИНГ ОПИСАНИЙ
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

    try:
        text = raw.decode("utf-8")
        markers = ("prog[pn]", "desc[pn]", "cmds[pn]",
                   "[MInst]", "Name=", "Patch=", "// WPI")
        if any(m in text for m in markers):
            return text
    except UnicodeDecodeError:
        pass

    for enc in ("cp1251", "koi8-r", "cp866"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue

    return raw.decode("cp1251", errors="replace")


def read_text_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    return decode_bytes(raw)


def clean_patch_filename(name):
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r'"\s+.*$', '"', s)
    s = re.split(r"\s+", s)[0]
    s = s.strip("\"'")
    parts = re.split(r"[\\/]", s)
    last = parts[-1] if parts else s
    last = re.sub(r"-?\{[^}]+\}", "", last)
    return last.strip()


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


def load_all_programs(context, desc_items):
    all_programs = []
    seen = set()

    for item in desc_items:
        name = item["name"]
        dlink = item.get("dlink")
        if not dlink:
            continue

        save = f"/tmp/{name}"
        try:
            if not download_file(context, dlink, save):
                continue
        except Exception as e:
            print(f"    [!] скачивание {name}: {e}")
            continue

        content = read_text_file(save)
        fmt = detect_format(content)

        if fmt == "wpi":
            programs = parse_wpi_format(content)
        elif fmt == "old":
            programs = parse_old_format(content)
        else:
            print(f"  ── {name} ── формат неизвестен, пропуск")
            continue

        print(f"  ── {name} ── формат: {fmt}, программ: {len(programs)}")

        for p in programs:
            key = normalize_filename(p.get("patch_filename", "")) or \
                  p.get("name", "").lower()
            if not key or key in seen:
                continue
            seen.add(key)
            all_programs.append(p)

    return all_programs


# ============================================================
# СОПОСТАВЛЕНИЕ
# ============================================================

def strip_arch_suffix(name):
    return ARCH_SUFFIXES.sub("", name)


def normalize_filename(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(
        r"\.(exe|msi|zip|rar|7z|tar|gz|txt|dll|bat|cmd|ps1|iso|bin)$", "", name
    )
    return name.strip()


def normalize_aggressive(name):
    return re.sub(r"[\s\.\-_+]+", "", (name or "").lower())


def match_file_to_program(filename, programs):
    fn_norm = normalize_filename(filename)
    fn_nosuf = strip_arch_suffix(fn_norm)
    fn_agg = normalize_aggressive(fn_nosuf)
    if not fn_agg:
        return None

    for p in programs:
        if normalize_filename(p.get("patch_filename", "")) == fn_norm:
            return p
    for p in programs:
        pn = strip_arch_suffix(normalize_filename(p.get("patch_filename", "")))
        if pn and pn == fn_nosuf:
            return p
    for p in programs:
        pa = normalize_aggressive(
            strip_arch_suffix(normalize_filename(p.get("patch_filename", "")))
        )
        if pa and pa == fn_agg:
            return p
    for p in programs:
        pa = normalize_aggressive(
            strip_arch_suffix(normalize_filename(p.get("patch_filename", "")))
        )
        if len(fn_agg) >= 5 and len(pa) >= 5:
            if fn_agg in pa or pa in fn_agg:
                return p

    fn_words = set(re.findall(r"[a-zа-яё0-9]{3,}",
                              fn_nosuf.replace("ё", "е")))
    fn_words -= {"win", "exe", "setup", "install", "full", "pro", "portable"}
    if not fn_words:
        return None

    best, best_score = None, 0
    for p in programs:
        name_norm = (p.get("name", "") or "").lower().replace("ё", "е")
        name_words = set(re.findall(r"[a-zа-яё0-9]{3,}", name_norm))
        if not name_words:
            continue
        inter = fn_words & name_words
        if len(inter) >= 1:
            score = len(inter) / max(len(fn_words), 1)
            if score >= 0.5 and score > best_score:
                best_score = score
                best = p
    return best


def parse_filename_title(filename):
    if not filename:
        return ""
    stem = os.path.splitext(filename)[0]
    return re.sub(r"\s+", " ", stem).strip()


# ============================================================
# ГЛАВНАЯ ФУНКЦИЯ: ОБХОД РАЗДЕЛА ЧЕРЕЗ PLAYWRIGHT
# ============================================================

def fetch_terabox_records(start_url, section, diag):
    if sync_playwright is None:
        print("  [!] playwright не установлен.")
        return []

    handler = section.get("handler_type") or "universal"
    yandex_path = (section.get("yandex_path") or "").strip("/")

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

            elapsed = 0
            while elapsed < 15000 and catcher.count() == 0:
                page.wait_for_timeout(300)
                elapsed += 300

            if catcher.count() == 0:
                print("  [!] нет ответа /share/list")
                return []

            root_items = collect_items(page, catcher, 0)
            print(f"  Корень: {len(root_items)} элементов")

            work_items = root_items
            work_folder_name = None

            if yandex_path:
                first_seg = yandex_path.split("/")[-1]
                subdir_names = [
                    it.get("server_filename") for it in root_items
                    if str(it.get("isdir")) == "1"
                ]
                if first_seg in subdir_names:
                    work_folder_name = first_seg
            else:
                subdirs_in_root = [
                    it for it in root_items
                    if str(it.get("isdir")) == "1"
                ]
                if len(subdirs_in_root) == 1 and not any(
                    str(it.get("isdir")) != "1" for it in root_items
                ):
                    work_folder_name = subdirs_in_root[0].get("server_filename")

            if work_folder_name:
                print(f"  Вход в рабочую папку: {work_folder_name}")
                work_items = open_folder(page, catcher, work_folder_name)
                if work_items is None:
                    print(f"  [!] не удалось войти в {work_folder_name}")
                    return []

            print(f"  Содержимое рабочей папки: {len(work_items)} элементов")

            desc_items = []
            root_files = []
            subdirs = []

            for it in work_items:
                name = it.get("server_filename") or ""
                if str(it.get("isdir")) == "1":
                    subdirs.append(it)
                elif handler == "programs" and any(
                    p.match(name) for p in DESC_FILE_PATTERNS
                ):
                    desc_items.append({
                        "name": name,
                        "dlink": it.get("dlink") or "",
                    })
                else:
                    root_files.append(it)

            print(f"    Файлов-описаний: {len(desc_items)}")
            for d in desc_items:
                print(f"      • {d['name']}")
            print(f"    Прочих файлов:   {len(root_files)}")
            print(f"    Подпапок:        {len(subdirs)}")

            programs = []
            if handler == "programs" and desc_items:
                print(f"\n  Парсинг описаний...")
                programs = load_all_programs(context, desc_items)
                print(f"  Программ с описанием: {len(programs)}")

            def _make_record(item, folder_name):
                fname = item.get("server_filename") or ""
                if not fname:
                    return None

                matched = None
                if programs:
                    matched = match_file_to_program(fname, programs)

                if matched:
                    title = matched["name"]
                    description = matched.get("description", "")
                    diag.matched_with_desc += 1
                else:
                    title = parse_filename_title(fname)
                    description = ""
                    diag.without_desc += 1

                size_bytes = item.get("size") or 0
                try:
                    size_mb = str(round(int(size_bytes) / (1024 * 1024), 1))
                except Exception:
                    size_mb = ""

                return {
                    "folder":        folder_name or "",
                    "title":         title,
                    "description":   description,
                    "version":       "",
                    "size":          size_mb,
                    "download_link": item.get("dlink", ""),
                }

            for it in root_files:
                rec = _make_record(it, "")
                if rec:
                    records.append(rec)

            for i, sub in enumerate(subdirs):
                sub_name = sub.get("server_filename")
                print(f"\n    ── [{i+1}/{len(subdirs)}] {sub_name}")

                if i > 0 or work_folder_name:
                    page.goto(start_url, wait_until="domcontentloaded",
                              timeout=60000)
                    page.wait_for_timeout(5000)

                    elapsed = 0
                    start_idx = catcher.count()
                    while (elapsed < 10000
                           and catcher.count() == start_idx):
                        page.wait_for_timeout(300)
                        elapsed += 300

                    if work_folder_name:
                        back = open_folder(page, catcher, work_folder_name)
                        if back is None:
                            print(f"      ✗ не вернулись в {work_folder_name}")
                            diag.failed_folders.append(sub_name)
                            continue

                items_sub = open_folder(page, catcher, sub_name)
                if items_sub is None:
                    print(f"      ✗ не удалось открыть '{sub_name}'")
                    diag.failed_folders.append(sub_name)
                    continue

                files_only = [
                    it for it in items_sub
                    if str(it.get("isdir")) != "1"
                ]
                matched_here = 0
                for it in files_only:
                    rec = _make_record(it, sub_name)
                    if rec:
                        records.append(rec)
                        if rec["description"]:
                            matched_here += 1

                print(f"      файлов: {len(files_only)}, "
                      f"с описанием: {matched_here}")

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
    """
    Синхронизирует один раздел.
    Возвращает dict со статистикой {added, updated, orphans, errors}
    или None, если раздел был пропущен.
    """
    label = section.get("label") or section.get("key")
    section_key = section.get("key")
    yandex_url = section.get("yandex_url") or ""
    sheet_name = section.get("sheet_name") or label
    columns = section.get("columns") or ["folder", "title", "description",
                                          "download_link"]

    print(f"\n=== Раздел TeraBox: {label} ({section_key}) ===")
    print(f"Ссылка:      {yandex_url[:100]}")
    print(f"Лист Sheets: {sheet_name}")
    print(f"Handler:     {section.get('handler_type') or 'universal'}")
    print(f"yandex_path: {section.get('yandex_path') or '(авто)'}")

    if not TERABOX_COOKIE:
        print("  [!] TERABOX_COOKIE не задан — пропускаю раздел.")
        return None

    diag = Diag(label)

    urls = [u.strip() for u in yandex_url.split("\n") if u.strip()]
    all_records = []
    for u in urls:
        print(f"\n  Загрузка TeraBox: {u[:90]}")
        recs = fetch_terabox_records(u, section, diag)
        print(f"  Получено записей: {len(recs)}")
        all_records.extend(recs)

    dedup = {}
    for r in all_records:
        key = ((r.get("folder") or "").lower(),
               (r.get("title") or "").lower())
        if key not in dedup:
            dedup[key] = r
    all_records = list(dedup.values())

    diag.found = len(all_records)
    print(f"\n  Итого уникальных записей: {len(all_records)}")

    headers = headers_from_columns(columns)
    rows = [_row_from_record(rec, headers) for rec in all_records]
    diag.kept = len(rows)

    try:
        sh = open_spreadsheet(gs_client)
    except Exception as e:
        print(f"  [!] Не удалось открыть таблицу: {e}")
        return None

    sheet = get_or_create_sheet(sh, sheet_name)
    ensure_headers(sheet, headers)

    all_values, existing_by_link, existing_by_key = load_sheet_snapshot(
        sheet, headers
    )
    print(f"  Существующих строк в Sheets: "
          f"{len(existing_by_link)} (по ссылке), "
          f"{len(existing_by_key)} (по папке+названию)")

    link_ru = "Ссылка для скачивания"
    link_idx = headers.index(link_ru) if link_ru in headers else 0
    n_cols = len(headers)
    end_col_letter = _col_letter(n_cols - 1)

    # ─── Осиротевшие строки (только TeraBox) ───
    new_keys = set()
    for r in all_records:
        new_keys.add(((r.get("folder") or "").lower(),
                      (r.get("title") or "").lower()))

    title_hdr_idx = None
    for cand in TITLE_HEADER_CANDIDATES:
        if cand in headers:
            title_hdr_idx = headers.index(cand)
            break
    folder_hdr_idx = None
    for cand in FOLDER_HEADER_CANDIDATES:
        if cand in headers:
            folder_hdr_idx = headers.index(cand)
            break

    orphans = []
    for (key, info) in existing_by_key.items():
        if key in new_keys:
            continue

        values = info["values"]
        link_val = values[link_idx] if link_idx < len(values) else ""
        if _detect_source(link_val) != "terabox":
            continue

        title = ""
        if title_hdr_idx is not None and title_hdr_idx < len(values):
            title = str(values[title_hdr_idx]).strip()
        padded = list(values) + [""] * max(0, len(headers) - len(values))
        orphans.append({
            "row":    info["row"],
            "title":  title,
            "link":   link_val,
            "values": padded[:len(headers)],
        })

    diag.orphans_found = len(orphans)
    if orphans:
        print(f"  Осиротевших строк: {len(orphans)}")
    save_orphans_to_supabase(section_key, label, sheet_name,
                             orphans, headers)

    updates = []
    to_add = []
    preserved = 0
    unchanged = 0

    for rec in all_records:
        row = _row_from_record(rec, headers)
        link = str(row[link_idx]).strip() if link_idx < len(row) else ""

        key = ((rec.get("folder") or "").lower(),
               (rec.get("title") or "").lower())

        existing_info = existing_by_key.get(key)
        if existing_info is None and link:
            existing_info = existing_by_link.get(link)

        if existing_info is None:
            to_add.append(row)
            continue

        old_values = existing_info["values"]
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

        rng = f"A{existing_info['row']}:{end_col_letter}{existing_info['row']}"
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

    return {
        "added":   diag.added,
        "updated": diag.updated,
        "orphans": diag.orphans_found,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 60)
    print("terabox_sync.py (v4) — старт")
    print("=" * 60)
    print(f"PRESERVE_USER_EDITS = {PRESERVE_USER_EDITS}")
    print(f"BACKUP_BEFORE_SYNC  = {BACKUP_BEFORE_SYNC}")
    print(f"TERABOX_COOKIE      = {'задан' if TERABOX_COOKIE else 'НЕ задан'}")
    if SYNC_SECTIONS_FILTER:
        print(f"SYNC_SECTIONS_FILTER = {SYNC_SECTIONS_FILTER}")

    if sync_playwright is None:
        print("[!] playwright не установлен.")
        print("    Добавьте 'playwright' в requirements.txt и выполните")
        print("    python -m playwright install chromium")
        notify_result(
            title="Sync TeraBox",
            status="failure",
            details="playwright не установлен",
        )
        return

    if not TERABOX_COOKIE:
        print("[!] TERABOX_COOKIE не задан — выходим.")
        notify_result(
            title="Sync TeraBox",
            status="failure",
            details="TERABOX_COOKIE не задан",
        )
        return

    print("\nЗагрузка разделов из Supabase...")
    sections = load_sections_from_supabase()
    if not sections:
        print("[!] Нет активных разделов — выходим.")
        notify_result(
            title="Sync TeraBox",
            status="failure",
            details="Не удалось загрузить разделы из Supabase",
        )
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
        print("  Нет TeraBox-разделов для синхронизации — выходим.")
        return

    for s in terabox_sections:
        print(f"    • {s.get('key')}: {s.get('label')}")

    print("\nПодключение к Google Sheets...")
    try:
        gs_client = get_gspread_client()
    except Exception as e:
        print(f"[!] Google Sheets: {e}")
        notify_result(
            title="Sync TeraBox",
            status="failure",
            details=f"Ошибка Google Sheets: {e}",
        )
        return
    print("Клиент создан.")

    # ─── Аккумулируем статистику по всем разделам ───
    total_stats = {
        "added":    0,
        "updated":  0,
        "orphans":  0,
        "errors":   0,
        "sections": [],
    }

    for section in terabox_sections:
        try:
            stats = sync_terabox_section(section, gs_client)
            if stats:
                total_stats["added"]   += stats.get("added", 0)
                total_stats["updated"] += stats.get("updated", 0)
                total_stats["orphans"] += stats.get("orphans", 0)
                total_stats["sections"].append(
                    f"{section.get('label')}: +{stats.get('added', 0)} / "
                    f"~{stats.get('updated', 0)}"
                )
        except Exception as e:
            total_stats["errors"] += 1
            print(f"\n[!!!] Ошибка в разделе {section.get('key')}: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("terabox_sync.py — готово!")
    print("=" * 60)

    # ─── Telegram-уведомление с итогами ───
    run_url = None
    if os.environ.get("GITHUB_RUN_ID"):
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        run_url = (f"https://github.com/{repo}/actions/runs/"
                   f"{os.environ['GITHUB_RUN_ID']}")

    status = "failure" if total_stats["errors"] > 0 else "success"

    details = (f"Обновлено: {total_stats['updated']}, "
               f"добавлено: {total_stats['added']}, "
               f"осиротевших: {total_stats['orphans']}")

    if total_stats["errors"]:
        details += f" • Ошибок: {total_stats['errors']}"

    notify_result(
        title="Sync TeraBox",
        status=status,
        details=details,
        extra_lines=total_stats["sections"] or None,
        run_url=run_url,
    )


if __name__ == "__main__":
    main()
