#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест TeraBox v4:
- Улучшенный скроллинг после каждого возврата в «Программы»
- Правильное определение кодировок (utf-8 → cp1251 → utf-16)
- Мягкий матчинг (учитывает суффиксы -x86/-x64/-x32)
- Fallback: если описания нет — программа всё равно попадает в список
- Полный обход всех подпапок раздела «Программы»
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

DESC_FILE_PATTERNS = [
    re.compile(r"^1_Software\.txt$", re.IGNORECASE),
    re.compile(r"^описание( \d+)?\.txt$", re.IGNORECASE),
]

# Суффиксы разрядности — убираем при сравнении патча с именем файла
ARCH_SUFFIXES = re.compile(
    r"[-_.]?(x86|x64|x32|win32|win64|32|64|32bit|64bit)$",
    re.IGNORECASE,
)


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

    def wait_new(self, page, prev_count, timeout_ms=20000):
        elapsed = 0
        while elapsed < timeout_ms:
            if len(self.responses) > prev_count:
                return self.responses[-1]
            page.wait_for_timeout(200)
            elapsed += 200
        return None


# ============================================================
# СКРОЛЛИНГ ВИРТУАЛЬНОГО СПИСКА
# ============================================================

def scroll_full_list(page, expected_min_count=None, max_iter=25):
    """
    Скроллит список до конца, догружая виртуально-скрытые элементы.
    Останавливается когда DOM-элементов перестаёт расти.
    В конце скроллит обратно вверх.
    """
    last_dom_count = 0
    stable_iters = 0

    for i in range(max_iter):
        try:
            page.mouse.wheel(0, 2500)
        except Exception:
            pass
        page.wait_for_timeout(600)

        try:
            dom_count = page.locator(".file-item-listmode").count()
        except Exception:
            dom_count = 0

        if dom_count == last_dom_count:
            stable_iters += 1
            if stable_iters >= 3:
                break
        else:
            stable_iters = 0
            last_dom_count = dom_count

    # Вернуть список наверх
    try:
        page.mouse.wheel(0, -50000)
    except Exception:
        pass
    page.wait_for_timeout(500)

    return last_dom_count


# ============================================================
# КЛИК ПО ПАПКЕ
# ============================================================

def find_folder_locator(page, name):
    """
    Ищет локатор для элемента папки по точному имени.
    Vue-структура: .file-item-listmode содержит .file-item-name.
    """
    # Точное совпадение имени — через XPath по span с текстом
    for sel in (
        f'.file-item-listmode:has(.file-item-name:text-is("{name}"))',
        f'.file-item-listmode:has-text("{name}")',
    ):
        try:
            loc = page.locator(sel).first
            if loc.count() > 0:
                return loc
        except Exception:
            continue
    return None


def open_folder(page, catcher, name, expected_parent=None, max_attempts=3):
    """
    Открывает папку. Возвращает ответ /share/list или None.

    expected_parent — имя родительской папки, чтобы не перепутать
    её содержимое с содержимым искомой папки.
    """
    for attempt in range(max_attempts):
        prev = catcher.count()

        # Убедиться что список полностью проскроллен
        scroll_full_list(page)

        loc = find_folder_locator(page, name)
        if loc is None:
            print(f"    [open] попытка {attempt+1}: '{name}' не найдена в DOM")
            page.wait_for_timeout(1000)
            continue

        try:
            loc.scroll_into_view_if_needed(timeout=3000)
        except Exception:
            pass
        page.wait_for_timeout(300)

        try:
            loc.dblclick(timeout=6000)
        except Exception as e:
            print(f"    [open] dblclick ошибка: {e}")
            # Fallback: обычный клик
            try:
                loc.click(timeout=4000)
            except Exception:
                pass

        page.wait_for_timeout(3500)

        res = catcher.wait_new(page, prev, timeout_ms=12000)
        if not res:
            print(f"    [open] нет ответа /share/list после клика")
            continue

        data = res.get("data") or {}
        items = data.get("list") or []

        # Проверяем что это не тот же список, что был (т.е. клик сработал)
        names = {it.get("server_filename") for it in items}
        if expected_parent and len(items) == 1 and expected_parent in names:
            # Вернулось содержимое корня «Программы»
            continue

        # Проверяем что внутри — не тот же самый набор папок (что и «Программы»)
        # Эвристика: если это «Программы» — там нет файлов в корне
        # (все .exe и т.д. лежат в подпапках)
        return res

    return None


# ============================================================
# СКАЧИВАНИЕ ФАЙЛОВ
# ============================================================

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
# КОДИРОВКИ
# ============================================================

def decode_bytes(raw):
    """
    Определяет кодировку и декодирует.
    Порядок: UTF-16 (по BOM или по нулям в каждой второй позиции) →
             UTF-8 strict → cp1251 → koi8-r → cp866.
    """
    if not raw:
        return ""

    # BOM
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16-le", errors="replace")
    if raw[:2] == b"\xfe\xff":
        return raw.decode("utf-16-be", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig", errors="replace")

    # UTF-16 без BOM — нули в каждой второй позиции
    sample = raw[:400]
    if len(sample) >= 8:
        nulls_odd  = sum(1 for i in range(1, min(200, len(sample)), 2) if sample[i] == 0)
        nulls_even = sum(1 for i in range(0, min(200, len(sample)), 2) if sample[i] == 0)
        if nulls_odd > 40:
            return raw.decode("utf-16-le", errors="replace")
        if nulls_even > 40:
            return raw.decode("utf-16-be", errors="replace")

    # Пробуем UTF-8 СТРОГО
    try:
        text = raw.decode("utf-8")
        # Дополнительная проверка: должна быть хотя бы одна русская буква
        # или маркер формата
        markers = ("prog[pn]", "desc[pn]", "cmds[pn]",
                   "[MInst]", "Name=", "Patch=", "// WPI")
        if any(m in text for m in markers):
            return text
    except UnicodeDecodeError:
        pass

    # cp1251 (ANSI для русской Windows)
    for enc in ("cp1251", "koi8-r", "cp866"):
        try:
            text = raw.decode(enc)
            return text
        except UnicodeDecodeError:
            continue

    return raw.decode("cp1251", errors="replace")


def read_text_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    return decode_bytes(raw)


# ============================================================
# ОЧИСТКА ПУТИ ДО ИМЕНИ ФАЙЛА
# ============================================================

def clean_patch_filename(name):
    """
    'Install\\MSO\\Libre.Office.exe'     → 'Libre.Office.exe'
    '"%wpipath%\\File.exe" /S /I'         → 'File.exe'
    'Notepad3-{P}.exe'                    → 'Notepad3.exe'
    """
    if not name:
        return ""

    s = name.strip()

    # Убираем всё после закрывающей кавычки с пробелом
    s = re.sub(r'"\s+.*$', '"', s)
    # Убираем аргументы: всё после первого пробела
    s = re.split(r"\s+", s)[0]
    # Снимаем кавычки
    s = s.strip("\"'")
    # Берём последнюю часть пути
    parts = re.split(r"[\\/]", s)
    last = parts[-1] if parts else s
    # Убираем плейсхолдеры {P}, {Root} и т.п. (если остались)
    last = re.sub(r"-?\{[^}]+\}", "", last)
    return last.strip()


# ============================================================
# ПАРСИНГ ФОРМАТОВ
# ============================================================

def parse_old_format(content):
    """Старый формат WPI: [N] / Name= / Hint= / Patch= / ..."""
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
    """WPI-формат: prog[pn]= / desc[pn]= / cmds[pn]= ... pn++"""
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
# СОПОСТАВЛЕНИЕ (УЛУЧШЕННОЕ)
# ============================================================

def strip_arch_suffix(name):
    """Убирает -x86/-x64/-x32/... на конце (без расширения)."""
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
    """
    Многоуровневый матчинг:
      1. точное совпадение patch_filename
      2. без суффикса разрядности (-x86/-x64/...)
      3. агрессивное совпадение (без разделителей)
      4. частичное вхождение (>=5 символов)
      5. совпадение по ключевым словам названия программы
    """
    fn_norm = normalize_filename(filename)
    fn_norm_nosuf = strip_arch_suffix(fn_norm)
    fn_agg = normalize_aggressive(fn_norm_nosuf)

    if not fn_agg:
        return None

    # 1. Точное совпадение
    for p in programs:
        if normalize_filename(p.get("patch_filename", "")) == fn_norm:
            return p

    # 2. Без суффикса разрядности
    for p in programs:
        pn = strip_arch_suffix(normalize_filename(p.get("patch_filename", "")))
        if pn and pn == fn_norm_nosuf:
            return p

    # 3. Агрессивное (без разделителей)
    for p in programs:
        pa = normalize_aggressive(
            strip_arch_suffix(normalize_filename(p.get("patch_filename", "")))
        )
        if pa and pa == fn_agg:
            return p

    # 4. Частичное вхождение
    for p in programs:
        pa = normalize_aggressive(
            strip_arch_suffix(normalize_filename(p.get("patch_filename", "")))
        )
        if len(fn_agg) >= 5 and len(pa) >= 5:
            if fn_agg in pa or pa in fn_agg:
                return p

    # 5. Совпадение по ключевым словам из имени файла и названия программы
    fn_words = set(re.findall(r"[a-zа-яё0-9]{3,}", fn_norm_nosuf.replace("ё", "е")))
    # Удаляем слишком общие слова
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
    """Fallback: название из имени файла."""
    if not filename:
        return ""
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


# ============================================================
# ЗАГРУЗКА ОПИСАНИЙ
# ============================================================

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
            print(f"    [!] ошибка скачивания {name}: {e}")
            continue

        content = read_text_file(save)
        fmt = detect_format(content)

        if fmt == "wpi":
            programs = parse_wpi_format(content)
        elif fmt == "old":
            programs = parse_old_format(content)
        else:
            print(f"  ── {name} ── неизвестный формат, пропуск")
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
# MAIN
# ============================================================

def main():
    print("=" * 72)
    print("ТЕСТ TERABOX v4: скроллинг + мягкий матчинг + fallback")
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

        # ═══ Корень ═══
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print(f"Финальный URL: {page.url}")

        initial = catcher.wait_new(page, 0, timeout_ms=15000)
        if not initial:
            print("✗ нет ответа /share/list")
            browser.close()
            return

        root_items = initial["data"].get("list") or []
        print(f"✓ Корень: {len(root_items)} элементов")
        for it in root_items:
            print(f"    [{'DIR ' if str(it.get('isdir')) == '1' else 'FILE'}] "
                  f"{it.get('server_filename')}")

        # ═══ Вход в «Программы» ═══
        print(f"\n{'─' * 72}\nШАГ 1: Вход в «Программы»\n{'─' * 72}")
        res_prog = open_folder(page, catcher, "Программы")
        if not res_prog:
            print("✗ Не удалось войти в «Программы»")
            browser.close()
            return

        items_prog = res_prog["data"].get("list") or []
        print(f"  В «Программах»: {len(items_prog)} элементов")

        # ═══ Разделяем содержимое ═══
        desc_items = []
        root_files = []
        subdirs = []

        for it in items_prog:
            name = it.get("server_filename") or ""
            if str(it.get("isdir")) == "1":
                subdirs.append(it)
            elif any(p.match(name) for p in DESC_FILE_PATTERNS):
                desc_items.append({"name": name, "dlink": it.get("dlink") or ""})
            else:
                root_files.append(it)

        print(f"\n  Файлов-описаний: {len(desc_items)}")
        for d in desc_items:
            print(f"    • {d['name']}")
        print(f"  Прочих файлов:  {len(root_files)}")
        for f in root_files:
            print(f"    • {f.get('server_filename')}")
        print(f"  Подпапок:       {len(subdirs)}")

        # ═══ Парсинг описаний ═══
        print(f"\n{'─' * 72}\nШАГ 2: Парсинг описаний\n{'─' * 72}")
        all_programs = load_all_programs(context, desc_items)
        print(f"\n✓ Всего программ с описанием: {len(all_programs)}")

        # ═══ Обход подпапок ═══
        print(f"\n{'─' * 72}\nШАГ 3: Обход подпапок\n{'─' * 72}")
        all_matched = []
        total_files = 0
        failed_folders = []

        for i, sub in enumerate(subdirs):
            sub_name = sub.get("server_filename")
            print(f"\n{'━' * 72}")
            print(f"ПАПКА [{i+1}/{len(subdirs)}]: {sub_name}")
            print(f"{'━' * 72}")

            # Возврат в «Программы» перед каждой папкой кроме первой
            if i > 0:
                print(f"  → возврат в «Программы»...")
                page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(6000)
                res_back = open_folder(page, catcher, "Программы",
                                       expected_parent=None)
                if not res_back:
                    print(f"  ✗ не удалось вернуться, пропускаем")
                    failed_folders.append(sub_name)
                    continue

            # Открываем саму папку
            res_sub = open_folder(page, catcher, sub_name,
                                  expected_parent="Программы")
            if not res_sub:
                print(f"  ✗ не удалось открыть '{sub_name}'")
                failed_folders.append(sub_name)
                continue

            data_sub = res_sub["data"]
            items_sub = data_sub.get("list") or []
            files_only = [it for it in items_sub
                          if str(it.get("isdir")) != "1"]
            total_files += len(files_only)
            print(f"  файлов: {len(files_only)}")

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
                    # Fallback: программа без описания
                    title_fb = parse_filename_title(fname)
                    print(f"    ~ {fname}  (без описания → '{title_fb}')")
                    all_matched.append({
                        "folder":        sub_name,
                        "filename":      fname,
                        "title":         title_fb,
                        "description":   "",
                        "size_bytes":    it.get("size", 0),
                        "download_link": it.get("dlink", ""),
                    })

            print(f"  с описанием: {matched_in_sub}/{len(files_only)}")

        # ═══ Итог ═══
        print(f"\n{'═' * 72}")
        print(f"ИТОГО: файлов просмотрено {total_files}, "
              f"записей {len(all_matched)}")
        print(f"{'═' * 72}")

        if failed_folders:
            print(f"\n⚠ Не удалось открыть папок: {len(failed_folders)}")
            for f in failed_folders:
                print(f"    • {f}")

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
