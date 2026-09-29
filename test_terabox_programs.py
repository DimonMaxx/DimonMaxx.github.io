#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Финальный тест TeraBox:
- Двойной клик по папкам (работает!)
- Скачивание 1_Software.txt и belico.dll
- Сопоставление файлов из TeraBox с описаниями из 1_Software.txt
  по полю Patch (там реальное имя файла), а не по Name.
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
    """Двойной клик по папке."""
    loc = page.locator(f'.file-item-listmode:has-text("{name}")').first
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed(timeout=3000)
    page.wait_for_timeout(200)
    loc.dblclick(timeout=5000)
    return True


def download_file(context, dlink, save_path):
    """Скачивает файл через context.request."""
    print(f"  GET {dlink[:100]}...")
    t0 = time.time()
    resp = context.request.get(dlink, timeout=180000)
    print(f"  HTTP {resp.status} за {round(time.time() - t0, 2)} сек")
    if resp.status != 200:
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    print(f"  ✓ Сохранено: {save_path} ({len(body)} байт)")
    return save_path


def parse_software_txt(file_path):
    """
    Парсит 1_Software.txt.
    Возвращает список dict:
    {
      "name": "Calibre",
      "hint": "Calibre - простая и удобная программа...",
      "patch": "{Patch}\\install\\text\\Calibre.win.exe",
      "patch_filename": "Calibre.win.exe",   # извлечено из patch
      "group": "11",
      "version": "9.8.0",
      "icon": "{Patch}\\userfiles\\belico.dll,312",
      "icon_index": "162",
    }
    """
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    programs = []
    current = None
    state = None  # какое поле сейчас парсим

    for raw in content.split("\n"):
        line = raw.rstrip("\r").rstrip()

        # Начало новой записи
        m_section = re.match(r"^\[(\d+)\]$", line.strip())
        if m_section:
            if current and current.get("name"):
                programs.append(current)
            current = {
                "name": "", "hint": "", "patch": "",
                "patch_filename": "", "group": "", "version": "",
                "icon": "", "icon_index": "", "url": "",
                "key": "", "section": m_section.group(1),
            }
            state = None
            continue

        if current is None:
            continue

        # Парсим поля
        if line.startswith("Name="):
            current["name"] = line[5:].strip()
            state = None
        elif line.startswith("Hint="):
            current["hint"] = line[5:].strip()
            state = "hint"
        elif line.startswith("Patch="):
            current["patch"] = line[6:].strip()
            state = None
        elif line.startswith("Group="):
            current["group"] = line[6:].strip()
            state = None
        elif line.startswith("Ver="):
            current["version"] = line[4:].strip()
            state = None
        elif line.startswith("Icon="):
            current["icon"] = line[5:].strip()
            state = None
        elif line.startswith("IconIndex="):
            current["icon_index"] = line[10:].strip()
            state = None
        elif line.startswith("URL="):
            current["url"] = line[4:].strip()
            state = None
        elif line.startswith("Key="):
            current["key"] = line[4:].strip()
            state = None
        elif state == "hint" and line and not line.startswith("["):
            # Продолжение многострочного Hint
            current["hint"] += "\n" + line
        else:
            state = None

    if current and current.get("name"):
        programs.append(current)

    # Извлекаем имя файла из Patch
    for p in programs:
        patch = p.get("patch", "")
        if patch:
            # {Patch}\install\text\Calibre.win.exe → Calibre.win.exe
            # {Root}\apps\tools\tweaks\Tweaks.reg → Tweaks.reg
            parts = re.split(r"[\\/]", patch)
            p["patch_filename"] = parts[-1] if parts else ""
        else:
            p["patch_filename"] = ""

    # Очищаем Hint от разделителей |
    for p in programs:
        hint = p.get("hint", "")
        if hint:
            # Убираем ведущий | и разбиваем по |
            if hint.startswith("|"):
                hint = hint[1:]
            hint = hint.replace("|", "\n")
            # Схлопываем множественные переводы строк
            hint = re.sub(r"\n+", "\n", hint).strip()
            p["hint"] = hint

    return programs


def normalize_filename(name):
    """Убираем расширение и нормализуем для сравнения."""
    if not name:
        return ""
    name = name.lower()
    # Убираем расширение
    name = re.sub(r"\.(exe|msi|zip|rar|7z|tar|gz|txt|dll)$", "", name)
    return name.strip()


def normalize_patch_filename(patch_fn):
    """
    Нормализует имя файла из Patch для сравнения с реальным файлом.
    Notepad3-{P}.exe → notepad3
    Calibre.win.exe  → calibre.win
    """
    if not patch_fn:
        return ""
    fn = patch_fn.lower()
    # Убираем расширение
    fn = re.sub(r"\.(exe|msi|zip|rar|7z|tar|gz|txt|dll)$", "", fn)
    # Убираем {P} (placeholder разрядности)
    fn = fn.replace("-{p}", "")
    fn = fn.replace("_{p}", "")
    fn = fn.replace("{p}", "")
    return fn.strip()


def match_file_to_program(filename, programs):
    """
    Ищет программу из 1_Software.txt по имени файла из TeraBox.
    Сравниваем с полем Patch (там реальное имя файла).
    """
    file_norm = normalize_filename(filename)
    if not file_norm:
        return None

    # 1. Пробуем точное совпадение по patch_filename
    for p in programs:
        p_patch_norm = normalize_patch_filename(p.get("patch_filename", ""))
        if p_patch_norm and p_patch_norm == file_norm:
            return p

    # 2. Пробуем совпадение без разделителей (тире, точки, подчёркивания)
    file_clean = re.sub(r"[\s\.\-_]", "", file_norm)
    for p in programs:
        p_patch_norm = normalize_patch_filename(p.get("patch_filename", ""))
        p_clean = re.sub(r"[\s\.\-_]", "", p_patch_norm)
        if p_clean and p_clean == file_clean:
            return p

    # 3. Частичное совпадение (одно содержит другое)
    for p in programs:
        p_patch_norm = normalize_patch_filename(p.get("patch_filename", ""))
        if not p_patch_norm:
            continue
        if file_clean and p_clean:
            # Ищем пересечение
            if len(file_clean) >= 5 and len(p_clean) >= 5:
                if file_clean in p_clean or p_clean in file_clean:
                    return p

    return None


def print_items(items, indent="    "):
    for i, it in enumerate(items):
        name = it.get("server_filename")
        is_dir = str(it.get("isdir")) == "1"
        kind = "DIR " if is_dir else "FILE"
        has_dl = "✓" if it.get("dlink") else "✗"
        print(f"{indent}[{i:>2}] [{kind}] {name:<40} "
              f"{it.get('size', 0):>12} b  dlink:{has_dl}")


def main():
    print("=" * 70)
    print("ФИНАЛЬНЫЙ ТЕСТ: обход + сопоставление по Patch")
    print("=" * 70)

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

        # ═══ Открываем корень ═══
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print(f"Финальный URL: {page.url}")

        initial = catcher.wait_new(page, 0, timeout_ms=10000)
        if not initial:
            print("✗ Vue не сделал /share/list")
            browser.close()
            return
        data_root = initial["data"]
        print(f"\n✓ Корень — errno: {data_root.get('errno')}")

        # ═══ ШАГ 1: вход в "Программы" ═══
        print(f"\n{'─' * 70}\nШАГ 1: Вход в «Программы»\n{'─' * 70}")
        prev = catcher.count()
        if not double_click_folder(page, "Программы"):
            print("✗ Не удалось войти")
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
        print_items(items_prog)

        subdirs = []
        desc_file = None
        dll_file = None
        for it in items_prog:
            name = it.get("server_filename")
            if name == "1_Software.txt":
                desc_file = it
            elif name == "belico.dll":
                dll_file = it
            elif str(it.get("isdir")) == "1":
                subdirs.append(it)

        # ═══ ШАГ 2: скачиваем 1_Software.txt ═══
        print(f"\n{'─' * 70}\nШАГ 2: 1_Software.txt\n{'─' * 70}")
        programs = []
        if desc_file and desc_file.get("dlink"):
            save = download_file(context, desc_file["dlink"], "/tmp/1_Software.txt")
            if save:
                programs = parse_software_txt(save)
                print(f"  ✓ Программ в файле: {len(programs)}")
                print(f"\n  Первые 5 записей:")
                for i, p in enumerate(programs[:5]):
                    print(f"    [{i}] Name      = {p['name']}")
                    print(f"         Patch     = {p['patch']}")
                    print(f"         File      = {p['patch_filename']}")
                    print(f"         Hint      = {p['hint'][:80]}...")

        # ═══ ШАГ 3: скачиваем belico.dll ═══
        print(f"\n{'─' * 70}\nШАГ 3: belico.dll\n{'─' * 70}")
        if dll_file and dll_file.get("dlink"):
            print(f"  Размер: {dll_file.get('size')} байт")
            download_file(context, dll_file["dlink"], "/tmp/belico.dll")

        # ═══ ШАГ 4: обход подпапок + сопоставление ═══
        print(f"\n{'─' * 70}\nШАГ 4: Обход подпапок\n{'─' * 70}")
        all_matched = []

        for i, sub in enumerate(subdirs):
            sub_name = sub.get("server_filename")
            print(f"\n{'━' * 70}")
            print(f"ПОДПАПКА [{i+1}/{len(subdirs)}]: {sub_name}")
            print(f"{'━' * 70}")

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
            print(f"  errno: {data_sub.get('errno')}, файлов: {len(files_only)}")
            print_items(files_only, indent="    ")

            # Сопоставление
            print(f"\n  Сопоставление с 1_Software.txt (по Patch):")
            matched_in_sub = 0
            for it in files_only:
                fname = it.get("server_filename") or ""
                found = match_file_to_program(fname, programs)
                if found:
                    matched_in_sub += 1
                    print(f"    ✓ {fname}")
                    print(f"      → Name: {found['name']}")
                    print(f"      → Patch: {found['patch_filename']}")
                    hint_short = found.get('hint', '')[:120].replace('\n', ' ')
                    print(f"      → Hint: {hint_short}...")
                    all_matched.append({
                        "subfolder": sub_name,
                        "filename": fname,
                        "title": found["name"],
                        "description": found.get("hint", ""),
                        "version": found.get("version", ""),
                        "size_bytes": it.get("size", 0),
                        "download_link": it.get("dlink", ""),
                        "icon": found.get("icon", ""),
                        "icon_index": found.get("icon_index", ""),
                    })
                else:
                    print(f"    ✗ {fname}")

            print(f"\n  Совпадений: {matched_in_sub}/{len(files_only)}")

        # ═══ ИТОГО ═══
        print(f"\n{'═' * 70}")
        print(f"ИТОГО: сопоставлено {len(all_matched)} программ")
        print(f"{'═' * 70}")
        for m in all_matched:
            print(f"  [{m['subfolder']}] {m['title']}  →  {m['filename']}")

        with open("/tmp/matched_programs.json", "w", encoding="utf-8") as f:
            json.dump(all_matched, f, ensure_ascii=False, indent=2)
        print(f"\nСохранено: /tmp/matched_programs.json")

        page.screenshot(path="/tmp/final.png")
        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
