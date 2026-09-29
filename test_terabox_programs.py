#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перехват ответов Vue (исправлено: wait_for_timeout вместо time.sleep).
"""

import os
import re
import sys
import json
import time
import random

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
    """Собирает ответы Vue на /share/list."""

    def __init__(self):
        self.responses = []

    def attach(self, page):
        def on_response(resp):
            if "/share/list" in resp.url and "/static/" not in resp.url:
                try:
                    data = resp.json()
                    self.responses.append({
                        "url": resp.url,
                        "data": data,
                        "ts": time.time(),
                    })
                except Exception:
                    pass
        page.on("response", on_response)

    def count(self):
        return len(self.responses)

    def wait_new(self, page, prev_count, timeout_ms=15000):
        """Ждёт новый ответ, используя page.wait_for_timeout (не блокирует)."""
        elapsed = 0
        while elapsed < timeout_ms:
            if len(self.responses) > prev_count:
                return self.responses[-1]
            page.wait_for_timeout(200)
            elapsed += 200
        return None


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
                    "name": name, "hint": "", "icon": "", "icon_index": "",
                    "group": "", "version": "", "url": "", "key": "",
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


def click_folder(page, folder_name):
    """
    Кликает по папке в основной области.
    Пробует несколько стратегий для надёжности.
    """
    # Стратегия 1: ищем в .file-item-listmode (основная область)
    selectors = [
        '.file-item-listmode .file-item-name',
        '.file-item-name',
        '.file-content .file-item-name',
    ]
    for sel in selectors:
        elements = page.query_selector_all(sel)
        for el in elements:
            try:
                txt = (el.inner_text() or "").strip()
                if txt == folder_name:
                    el.scroll_into_view_if_needed()
                    page.wait_for_timeout(200)
                    el.click(timeout=5000)
                    return True
            except Exception:
                pass
    return False


def click_breadcrumb(page, name):
    """Кликает по breadcrumb (возврат в родительскую папку)."""
    for el in page.query_selector_all('.breadcrumb-item'):
        try:
            txt = (el.inner_text() or "").strip()
            if txt == name:
                el.click(timeout=5000)
                return True
        except Exception:
            pass
    return False


def print_items(items, indent="    "):
    for i, it in enumerate(items):
        name = it.get("server_filename")
        is_dir = str(it.get("isdir")) == "1"
        has_dlink = "✓" if it.get("dlink") else "✗"
        kind = "DIR " if is_dir else "FILE"
        print(f"{indent}[{i:>2}] [{kind}] {name:<35} "
              f"{it.get('size', 0):>12} b  dlink:{has_dlink}")


def navigate_and_capture(page, catcher, path, timeout_ms=20000):
    """
    Кликает по цепочке папок и ждёт новый ответ Vue.
    ВАЖНО: используем page.wait_for_timeout, а не time.sleep.
    """
    prev = catcher.count()

    for name in path:
        ok = click_folder(page, name)
        if not ok:
            print(f"  ✗ Не удалось кликнуть '{name}'")
            return None
        # Даём Vue время отправить запрос и Playwright — обработать событие
        page.wait_for_timeout(500)

    result = catcher.wait_new(page, prev, timeout_ms=timeout_ms)
    return result


def main():
    print("=" * 70)
    print("ПЕРЕХВАТ ОТВЕТОВ Vue (исправлено: wait_for_timeout)")
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

        # ─── Открываем страницу ───
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print(f"Финальный URL: {page.url}")

        # Ждём первого ответа Vue
        initial = catcher.wait_new(page, 0, timeout_ms=10000)
        if not initial:
            print("✗ Vue не сделал ни одного запроса /share/list")
            browser.close()
            return

        data_root = initial["data"]
        items_root = data_root.get("list") or []
        print(f"\n✓ Корень ссылки — errno: {data_root.get('errno')}, "
              f"элементов: {len(items_root)}")
        print_items(items_root)

        # ─── Кликаем "Программы" ───
        print(f"\n{'─' * 70}\nШАГ 1: Клик по папке «Программы»\n{'─' * 70}")
        res1 = navigate_and_capture(page, catcher, ["Программы"])
        if not res1:
            print("✗ Не удалось открыть папку")
            # Делаем скриншот и HTML для отладки
            page.screenshot(path="/tmp/fail_programs.png")
            with open("/tmp/fail_programs.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("  Сохранены: /tmp/fail_programs.png и .html")
            browser.close()
            return

        data1 = res1["data"]
        items1 = data1.get("list") or []
        print(f"errno: {data1.get('errno')}, элементов: {len(items1)}")
        print_items(items1)

        subdirs = []
        desc_file = None
        dll_file = None
        for it in items1:
            name = it.get("server_filename")
            if name == "1_Software.txt":
                desc_file = it
            elif name == "belico.dll":
                dll_file = it
            elif str(it.get("isdir")) == "1":
                subdirs.append(it)

        # ─── Скачиваем 1_Software.txt ───
        print(f"\n{'─' * 70}\nШАГ 2: Скачиваем 1_Software.txt\n{'─' * 70}")
        programs_map = {}
        if desc_file and desc_file.get("dlink"):
            save = download_file(context, desc_file["dlink"], "/tmp/1_Software.txt")
            if save:
                programs_map = parse_software_txt(save)
                print(f"  ✓ Программ в файле: {len(programs_map)}")
                for i, (key, val) in enumerate(list(programs_map.items())[:12]):
                    print(f"    [{i}] Name={val['name']}")
                    print(f"         Group={val['group']}  Ver={val['version']}")
                    print(f"         Hint={(val.get('hint') or '')[:100]}...")

        # ─── Скачиваем belico.dll ───
        print(f"\n{'─' * 70}\nШАГ 3: Скачиваем belico.dll\n{'─' * 70}")
        if dll_file and dll_file.get("dlink"):
            print(f"  Размер: {dll_file.get('size')} байт")
            download_file(context, dll_file["dlink"], "/tmp/belico.dll")

        # ─── Обходим подпапки ───
        print(f"\n{'─' * 70}\nШАГ 4: Обход подпапок\n{'─' * 70}")

        for i, sub in enumerate(subdirs):
            sub_name = sub.get("server_filename")
            print(f"\n[{i}] Подпапка: {sub_name}")

            # Возвращаемся в "Программы"
            if i > 0:
                print(f"    Возвращаемся в «Программы»...")
                click_breadcrumb(page, "Программы")
                page.wait_for_timeout(2000)

            # Кликаем по подпапке
            res_sub = navigate_and_capture(page, catcher, [sub_name])
            if not res_sub:
                print(f"    ✗ Не удалось открыть подпапку")
                continue
            data_sub = res_sub["data"]
            items_sub = data_sub.get("list") or []
            print(f"    errno: {data_sub.get('errno')}, файлов: {len(items_sub)}")
            print_items(items_sub, indent="      ")

            if programs_map:
                print(f"\n    Сопоставление с 1_Software.txt:")
                matched = 0
                files_only = [it for it in items_sub if str(it.get("isdir")) != "1"]
                for it in files_only:
                    fname = it.get("server_filename") or ""
                    base = re.sub(r"\.(exe|msi|zip|rar|7z|txt|dll)$", "", fname, flags=re.IGNORECASE)
                    base_clean = re.sub(r"[\-_.](x86|x64|win|setup|installer|portable|install)$",
                                        "", base, flags=re.IGNORECASE)
                    base_lower = base_clean.lower()

                    found = None
                    if base_lower in programs_map:
                        found = programs_map[base_lower]
                    else:
                        for key, val in programs_map.items():
                            key_clean = re.sub(r"[\s\.\-_]", "", key)
                            base_cleanest = re.sub(r"[\s\.\-_]", "", base_lower)
                            if key_clean == base_cleanest:
                                found = val
                                break
                            if abs(len(key_clean) - len(base_cleanest)) < 5:
                                if base_cleanest and (base_cleanest in key_clean or key_clean in base_cleanest):
                                    found = val
                                    break

                    if found:
                        matched += 1
                        print(f"      ✓ {fname} → {found['name']}")
                        print(f"        Hint: {(found.get('hint') or '')[:110]}...")
                    else:
                        print(f"      ✗ {fname}")
                print(f"    Совпадений: {matched}/{len(files_only)}")

        # Финальный скриншот
        page.screenshot(path="/tmp/final_state.png")
        with open("/tmp/final_state.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print(f"\nФинальные скриншот и HTML: /tmp/final_state.png, .html")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
