#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Финальный тест TeraBox:
1. Открываем корень ссылки
2. Двойной клик по "Программы" → собираем содержимое
3. Скачиваем 1_Software.txt и belico.dll
4. Заходим в каждую подпапку, собираем .exe файлы
5. Сопоставляем с описаниями из 1_Software.txt
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
    """Двойной клик по папке с заданным именем."""
    loc = page.locator(f'.file-item-listmode:has-text("{name}")').first
    if loc.count() == 0:
        return False
    loc.scroll_into_view_if_needed(timeout=3000)
    page.wait_for_timeout(200)
    loc.dblclick(timeout=5000)
    return True


def download_file(context, dlink, save_path):
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
    """Парсит 1_Software.txt."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    programs = {}
    current = None
    for raw in content.split("\n"):
        line = raw.rstrip("\r").strip()
        if not line:
            continue
        if line.startswith("Name="):
            name = line[5:].strip()
            if name:
                current = {
                    "name": name, "hint": "", "icon": "",
                    "icon_index": "", "group": "", "version": "",
                    "url": "", "key": "",
                }
                programs[name.lower()] = current
        elif current is not None:
            if line.startswith("Hint="):
                current["hint"] = line[5:].strip().lstrip("|").strip()
            elif line.startswith("Icon="):
                current["icon"] = line[5:].strip()
            elif line.startswith("IconIndex="):
                current["icon_index"] = line[10:].strip()
            elif line.startswith("Group="):
                current["group"] = line[6:].strip()
            elif line.startswith("Ver="):
                current["version"] = line[4:].strip()
            elif line.startswith("URL="):
                current["url"] = line[4:].strip()
            elif line.startswith("Key="):
                current["key"] = line[4:].strip()
    return programs


def match_program(filename, programs_map):
    """Ищет программу в programs_map по имени файла."""
    base = re.sub(r"\.(exe|msi|zip|rar|7z|txt|dll)$", "",
                  filename, flags=re.IGNORECASE)
    # Убираем суффиксы: -x86, -x64, .win, _setup, _portable
    base_clean = re.sub(
        r"[\-_.](x86|x64|win|setup|installer|portable|install|full)$",
        "", base, flags=re.IGNORECASE)
    base_lower = base_clean.lower()
    base_cleanest = re.sub(r"[\s\.\-_]", "", base_lower)

    # Прямое совпадение
    if base_lower in programs_map:
        return programs_map[base_lower]

    # Совпадение без разделителей
    for key, val in programs_map.items():
        key_clean = re.sub(r"[\s\.\-_]", "", key)
        if key_clean == base_cleanest:
            return val

    # Частичное (разница < 5 символов)
    for key, val in programs_map.items():
        key_clean = re.sub(r"[\s\.\-_]", "", key)
        if abs(len(key_clean) - len(base_cleanest)) < 5:
            if base_cleanest and (base_cleanest in key_clean
                                  or key_clean in base_cleanest):
                return val
    return None


def print_items(items, indent="    "):
    for i, it in enumerate(items):
        name = it.get("server_filename")
        is_dir = str(it.get("isdir")) == "1"
        kind = "DIR " if is_dir else "FILE"
        has_dl = "✓" if it.get("dlink") else "✗"
        print(f"{indent}[{i:>2}] [{kind}] {name:<35} "
              f"{it.get('size', 0):>12} b  dlink:{has_dl}")


def main():
    print("=" * 70)
    print("ФИНАЛЬНЫЙ ТЕСТ: обход TeraBox + сопоставление с 1_Software.txt")
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
        items_root = data_root.get("list") or []
        print(f"\n✓ Корень — errno: {data_root.get('errno')}, "
              f"элементов: {len(items_root)}")
        print_items(items_root)

        # ═══ ШАГ 1: вход в "Программы" ═══
        print(f"\n{'─' * 70}\nШАГ 1: Вход в папку «Программы»\n{'─' * 70}")
        prev = catcher.count()
        if not double_click_folder(page, "Программы"):
            print("✗ Не удалось войти в папку")
            browser.close()
            return
        page.wait_for_timeout(4000)

        res_prog = catcher.wait_new(page, prev, timeout_ms=15000)
        if not res_prog:
            print("✗ Нет ответа после клика")
            browser.close()
            return

        data_prog = res_prog["data"]
        items_prog = data_prog.get("list") or []
        print(f"errno: {data_prog.get('errno')}, элементов: {len(items_prog)}")
        print_items(items_prog)

        # Разделяем на подпапки и файлы
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
        programs_map = {}
        if desc_file and desc_file.get("dlink"):
            save = download_file(context, desc_file["dlink"],
                                 "/tmp/1_Software.txt")
            if save:
                programs_map = parse_software_txt(save)
                print(f"  ✓ Программ в файле: {len(programs_map)}")
                for i, (key, val) in enumerate(list(programs_map.items())[:15]):
                    print(f"    [{i}] Name={val['name']}")
                    print(f"         Group={val['group']}  Ver={val['version']}")
                    hint = (val.get('hint') or '')[:100]
                    print(f"         Hint={hint}...")
                if len(programs_map) > 15:
                    print(f"    ... и ещё {len(programs_map) - 15}")

        # ═══ ШАГ 3: скачиваем belico.dll ═══
        print(f"\n{'─' * 70}\nШАГ 3: belico.dll\n{'─' * 70}")
        if dll_file and dll_file.get("dlink"):
            print(f"  Размер: {dll_file.get('size')} байт")
            download_file(context, dll_file["dlink"], "/tmp/belico.dll")

        # ═══ ШАГ 4: обход каждой подпапки ═══
        print(f"\n{'─' * 70}\nШАГ 4: Обход подпапок\n{'─' * 70}")

        all_files_matched = []

        for i, sub in enumerate(subdirs):
            sub_name = sub.get("server_filename")
            print(f"\n{'━' * 70}")
            print(f"ПОДПАПКА [{i+1}/{len(subdirs)}]: {sub_name}")
            print(f"{'━' * 70}")

            # Возвращаемся в "Программы" через reload
            if i > 0:
                print(f"  → Возврат в «Программы» (перезагрузка)...")
                page.goto(START_URL, wait_until="domcontentloaded",
                          timeout=60000)
                page.wait_for_timeout(5000)
                # И снова входим в "Программы"
                prev = catcher.count()
                if not double_click_folder(page, "Программы"):
                    print(f"  ✗ Не удалось вернуться")
                    continue
                page.wait_for_timeout(3000)
                catcher.wait_new(page, prev, timeout_ms=10000)

            # Входим в подпапку
            prev = catcher.count()
            if not double_click_folder(page, sub_name):
                print(f"  ✗ Не удалось открыть '{sub_name}'")
                continue
            page.wait_for_timeout(4000)

            res_sub = catcher.wait_new(page, prev, timeout_ms=15000)
            if not res_sub:
                print(f"  ✗ Нет ответа для '{sub_name}'")
                continue

            data_sub = res_sub["data"]
            items_sub = data_sub.get("list") or []
            print(f"  errno: {data_sub.get('errno')}, "
                  f"файлов: {len(items_sub)}")
            print_items(items_sub, indent="    ")

            # Обрабатываем файлы
            files_only = [it for it in items_sub
                          if str(it.get("isdir")) != "1"]
            print(f"\n  Сопоставление с 1_Software.txt:")
            matched_in_sub = 0
            for it in files_only:
                fname = it.get("server_filename") or ""
                found = match_program(fname, programs_map)
                if found:
                    matched_in_sub += 1
                    print(f"    ✓ {fname}")
                    print(f"      → Name: {found['name']}")
                    hint = (found.get('hint') or '')[:120]
                    print(f"      → Hint: {hint}...")
                    all_files_matched.append({
                        "subfolder": sub_name,
                        "filename": fname,
                        "name": found["name"],
                        "hint": found.get("hint", ""),
                        "size": it.get("size", 0),
                        "dlink": it.get("dlink", ""),
                    })
                else:
                    print(f"    ✗ {fname}")

            print(f"\n  Совпадений: {matched_in_sub}/{len(files_only)}")

        # ═══ ИТОГО ═══
        print(f"\n{'═' * 70}")
        print(f"ИТОГО: сопоставлено {len(all_files_matched)} программ")
        print(f"{'═' * 70}")
        for m in all_files_matched:
            print(f"  [{m['subfolder']}] {m['name']} "
                  f"({m['size']} b) → {m['filename']}")

        # Сохраняем JSON с результатом
        with open("/tmp/matched_programs.json", "w", encoding="utf-8") as f:
            json.dump(all_files_matched, f, ensure_ascii=False, indent=2)
        print(f"\nСохранено: /tmp/matched_programs.json")

        page.screenshot(path="/tmp/final.png")
        print(f"Скриншот: /tmp/final.png")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН УСПЕШНО")
    print("=" * 70)


if __name__ == "__main__":
    main()
