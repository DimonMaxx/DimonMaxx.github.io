#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест TeraBox v2:
- Скачивание 4 файлов описаний из папки «Программы»:
    * 1_Software.txt  (UTF-16 LE/BE, старый формат [N]/Name=/Patch=/Hint=)
    * описание.txt    (ANSI/cp1251, WPI-формат prog[pn]=/desc[pn]=/cmds[pn]=)
    * описание 1.txt
    * описание 2.txt
- Парсинг обоих форматов, объединение в единый список программ
- Обход ВСЕХ подпапок в «Программы» (динамически, без хардкода)
- Сопоставление файлов TeraBox с описаниями
- Распределение по папкам (folder = имя подпапки TeraBox)
"""

import os
import re
import sys
import json
import time

from playwright.sync_api import sync_playwright

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

START_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"

COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com", ".d.terabox.app",
]

# Регулярки имён файлов-описаний
DESC_FILE_PATTERNS = [
    re.compile(r"^1_Software\.txt$", re.IGNORECASE),
    re.compile(r"^описание( \d+)?\.txt$", re.IGNORECASE),
]


# ============================================================
# ПЕРЕХВАТ XHR
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


def double_click_folder(page, name):
    loc = page.locator(f'.file-item-listmode:has-text("{name}")').first
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed(timeout=3000)
    page.wait_for_timeout(200)
    loc.dblclick(timeout=5000)
    return True


def download_file(context, dlink, save_path):
    print(f"  GET {dlink[:110]}...")
    resp = context.request.get(dlink, timeout=180000)
    print(f"  HTTP {resp.status}")
    if resp.status != 200:
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    print(f"  ✓ Сохранено: {save_path} ({len(body)} байт)")
    return save_path


# ============================================================
# ДЕКОДИРОВАНИЕ (UTF-16 LE/BE, cp1251, utf-8, koi8-r)
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

    # UTF-16 без BOM — характерный признак: нули в каждой второй позиции
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
    print(f"  Размер: {len(raw)} байт, hex head: {raw[:12].hex()}")
    return decode_bytes(raw)


# ============================================================
# ОЧИСТКА ИМЕНИ ФАЙЛА ИЗ Patch / cmds
# ============================================================

def clean_patch_filename(name):
    """
    Приводит ссылку на файл из описания к «чистому» имени:
      'Install\\MSO\\Libre.Office.exe'  → 'Libre.Office.exe'
      '"%wpipath%\\MSO\\File.exe" /S'   → 'File.exe'
      'Notepad3-{P}.exe'                → 'Notepad3.exe'
    """
    if not name:
        return ""
    # Убираем аргументы (всё после первого пробела вне кавычек)
    s = name.strip()
    # Отрезаем всё, что идёт после закрывающей кавычки
    s = re.sub(r'"\s+.*$', '"', s)
    # Разбиваем по разделителям пути
    parts = re.split(r"[\\/]", s)
    last = parts[-1] if parts else s
    # Убираем аргументы
    last = re.split(r"\s+", last)[0]
    # Снимаем кавычки
    last = last.strip("\"'")
    # Плейсхолдеры {P}, -{P}
    last = re.sub(r"-?\{P\}", "", last, flags=re.IGNORECASE)
    return last.strip()


# ============================================================
# ПАРСИНГ СТАРОГО ФОРМАТА (1_Software.txt)
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
            current = {
                "name": "", "description": "", "patch": "",
                "patch_filename": "",
            }
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


# ============================================================
# ПАРСИНГ WPI-ФОРМАТА (описание*.txt)
# ============================================================

def parse_wpi_format(content):
    programs = []
    blocks = re.split(r"\bpn\s*\+\+\s*;", content)

    for block in blocks:
        if "prog[pn]" not in block:
            continue
        entry = {
            "name": "", "description": "", "patch": "",
            "patch_filename": "",
        }

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
# ЗАГРУЗКА ВСЕХ ОПИСАНИЙ
# ============================================================

def load_all_programs(context, desc_items):
    """desc_items: [{"name": ..., "dlink": ...}, ...]"""
    all_programs = []
    seen = set()

    for item in desc_items:
        name = item["name"]
        dlink = item.get("dlink")
        if not dlink:
            print(f"  [!] Нет dlink для {name}")
            continue

        save = f"/tmp/{name}"
        try:
            download_file(context, dlink, save)
        except Exception as e:
            print(f"  [!] Ошибка скачивания {name}: {e}")
            continue

        content = read_text_file(save)
        fmt = detect_format(content)

        if fmt == "wpi":
            programs = parse_wpi_format(content)
        elif fmt == "old":
            programs = parse_old_format(content)
        else:
            print(f"  [!] Неизвестный формат: {name}")
            continue

        print(f"  Формат: {fmt}, записей: {len(programs)}")

        for p in programs:
            key = (p.get("patch_filename") or "").lower()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            all_programs.append(p)

    return all_programs


# ============================================================
# СОПОСТАВЛЕНИЕ ФАЙЛА С ПРОГРАММОЙ
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

    # 1. Точное совпадение по нормализованному имени
    for p in programs:
        if normalize_filename(p.get("patch_filename", "")) == fn_norm:
            return p

    # 2. Совпадение без разделителей
    for p in programs:
        if normalize_aggressive(p.get("patch_filename", "")) == fn_agg:
            return p

    # 3. Частичное (одно содержит другое), минимум 6 символов
    for p in programs:
        p_agg = normalize_aggressive(p.get("patch_filename", ""))
        if len(fn_agg) >= 6 and len(p_agg) >= 6:
            if fn_agg in p_agg or p_agg in fn_agg:
                return p

    # 4. Fallback: по названию программы (совпадение >60% слов длиной ≥4)
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


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 72)
    print("ТЕСТ TERABOX v2: мультиописания + распределение по папкам")
    print("=" * 72)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
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
                    "name": "ndus", "value": COOKIE, "domain": domain,
                    "path": "/", "secure": True, "sameSite": "None",
                }])
            except Exception:
                pass

        page = context.new_page()
        catcher = Catcher()
        catcher.attach(page)

        # ─── Открываем корень ───
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print(f"Финальный URL: {page.url}")

        initial = catcher.wait_new(page, 0, timeout_ms=10000)
        if not initial:
            print("✗ Нет ответа /share/list")
            browser.close()
            return
        print(f"✓ Корень — errno: {initial['data'].get('errno')}")

        # ─── Вход в «Программы» ───
        print(f"\n{'─' * 72}\nШАГ 1: Вход в «Программы»\n{'─' * 72}")
        prev = catcher.count()
        if not double_click_folder(page, "Программы"):
            print("✗ Не удалось войти в «Программы»")
            browser.close()
            return
        page.wait_for_timeout(4000)
        res_prog = catcher.wait_new(page, prev, timeout_ms=15000)
        if not res_prog:
            print("✗ Нет ответа")
            browser.close()
            return

        data_prog = res_prog["data"]
        items_prog = data_prog.get("list") or []
        print(f"errno: {data_prog.get('errno')}, элементов: {len(items_prog)}")

        # ─── Разделяем: файлы описаний / файлы / подпапки ───
        desc_items = []
        root_files = []
        subdirs = []

        for it in items_prog:
            name = it.get("server_filename") or ""
            is_dir = str(it.get("isdir")) == "1"
            if is_dir:
                subdirs.append(it)
            elif any(p.match(name) for p in DESC_FILE_PATTERNS):
                desc_items.append({"name": name, "dlink": it.get("dlink") or ""})
            else:
                root_files.append(it)

        print(f"\nФайлов описаний: {len(desc_items)}")
        for d in desc_items:
            print(f"  • {d['name']}  (dlink: {'✓' if d['dlink'] else '✗'})")

        print(f"Файлов в корне:  {len(root_files)}")
        print(f"Подпапок:        {len(subdirs)}")
        for s in subdirs:
            print(f"  • {s.get('server_filename')}")

        # ─── Парсинг описаний ───
        print(f"\n{'─' * 72}\nШАГ 2: Парсинг описаний\n{'─' * 72}")
        all_programs = load_all_programs(context, desc_items)
        print(f"\n✓ Всего программ: {len(all_programs)}")

        # Небольшая диагностика
        if all_programs:
            print("\n  Примеры распарсенных программ:")
            for p in all_programs[:8]:
                print(f"    • name            = {p['name'][:60]}")
                print(f"      patch_filename  = {p['patch_filename']}")
                print(f"      description[:60]= {p['description'][:60]}")

        # ─── Обход подпапок ───
        print(f"\n{'─' * 72}\nШАГ 3: Обход подпапок\n{'─' * 72}")
        all_matched = []
        total_files = 0

        for i, sub in enumerate(subdirs):
            sub_name = sub.get("server_filename")
            print(f"\n{'━' * 72}")
            print(f"ПАПКА [{i+1}/{len(subdirs)}]: {sub_name}")
            print(f"{'━' * 72}")

            if i > 0:
                print(f"  → Возврат в «Программы»...")
                page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)
                prev = catcher.count()
                if not double_click_folder(page, "Программы"):
                    print(f"  ✗ Не удалось вернуться")
                    continue
                page.wait_for_timeout(3000)
                catcher.wait_new(page, prev, timeout_ms=10000)

            prev = catcher.count()
            if not double_click_folder(page, sub_name):
                print(f"  ✗ Не удалось открыть '{sub_name}'")
                continue
            page.wait_for_timeout(4000)

            res_sub = catcher.wait_new(page, prev, timeout_ms=15000)
            if not res_sub:
                print(f"  ✗ Нет ответа")
                continue

            data_sub = res_sub["data"]
            items_sub = data_sub.get("list") or []
            files_only = [it for it in items_sub if str(it.get("isdir")) != "1"]
            total_files += len(files_only)
            print(f"  errno: {data_sub.get('errno')}, файлов: {len(files_only)}")

            matched_in_sub = 0
            for it in files_only:
                fname = it.get("server_filename") or ""
                found = match_file_to_program(fname, all_programs)
                if found:
                    matched_in_sub += 1
                    print(f"    ✓ {fname}")
                    print(f"      → {found['name']}")
                    all_matched.append({
                        "folder":        sub_name,
                        "filename":      fname,
                        "title":         found["name"],
                        "description":   found.get("description", ""),
                        "size_bytes":    it.get("size", 0),
                        "download_link": it.get("dlink", ""),
                    })
                else:
                    print(f"    ✗ {fname}")

            print(f"  Совпадений: {matched_in_sub}/{len(files_only)}")

        # ─── Итоги ───
        print(f"\n{'═' * 72}")
        print(f"ИТОГО: файлов просмотрено {total_files}, "
              f"сопоставлено {len(all_matched)}")
        print(f"{'═' * 72}")

        for m in all_matched:
            print(f"  [{m['folder']}] {m['title']}  →  {m['filename']}")

        with open("/tmp/matched_programs.json", "w", encoding="utf-8") as f:
            json.dump(all_matched, f, ensure_ascii=False, indent=2)
        print(f"\nСохранено: /tmp/matched_programs.json")

        page.screenshot(path="/tmp/final.png")
        browser.close()

    print("\n" + "=" * 72)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 72)


if __name__ == "__main__":
    main()
