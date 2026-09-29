#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перехват ответов Vue + перебор стратегий клика.
Кликаем на всю строку, а не на иконку/название.
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
        self.requests = []

    def attach(self, page):
        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                self.requests.append({
                    "url": req.url,
                    "method": req.method,
                    "ts": time.time(),
                })

        def on_response(resp):
            if "/share/list" in resp.url and "/static/" not in resp.url:
                try:
                    data = resp.json()
                    self.responses.append({"data": data, "ts": time.time()})
                except Exception:
                    pass

        page.on("request", on_request)
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
                current = {"name": name, "hint": "", "icon": "",
                           "icon_index": "", "group": "", "version": "",
                           "url": "", "key": ""}
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
    return programs


def click_folder_robust(page, folder_name):
    """
    Перебирает несколько стратегий клика. Возвращает True если клик удался.
    """
    strategies = [
        # 1. Клик по всей строке .file-item-listmode через locator
        ("locator file-item-listmode", 
         f'.file-item-listmode:has-text("{folder_name}")'),
        # 2. Клик по .file-content
        ("locator file-content",
         f'.file-item-listmode:has-text("{folder_name}") .file-content'),
        # 3. Клик по .file-item-name (оригинал)
        ("locator file-item-name",
         f'.file-item-listmode .file-item-name:has-text("{folder_name}")'),
        # 4. Клик через has-text на весь .file-item-listmode
        ("has-text selector",
         f'div.file-item-listmode >> text="{folder_name}"'),
    ]

    for name, selector in strategies:
        try:
            loc = page.locator(selector).first
            if loc.count() == 0:
                continue
            loc.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(200)
            # Пробуем обычный клик
            try:
                loc.click(timeout=3000)
                print(f"  ✓ Клик ({name})")
                return True
            except Exception as e1:
                # Пробуем force click
                try:
                    loc.click(timeout=3000, force=True)
                    print(f"  ✓ Force клик ({name})")
                    return True
                except Exception as e2:
                    # Пробуем dispatch_event
                    try:
                        loc.dispatch_event("click")
                        print(f"  ✓ Dispatch click ({name})")
                        return True
                    except Exception as e3:
                        print(f"  ✗ {name}: {e1} / {e2} / {e3}")
                        continue
        except Exception as e:
            print(f"  ✗ {name}: {e}")
            continue
    return False


def click_breadcrumb(page, name):
    try:
        loc = page.locator(f'.breadcrumb-item:has-text("{name}")').first
        if loc.count() > 0:
            loc.click(timeout=5000)
            return True
    except Exception as e:
        print(f"    breadcrumb error: {e}")
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
    prev = catcher.count()
    prev_req = len(catcher.requests)
    url_before = page.url

    for name in path:
        ok = click_folder_robust(page, name)
        if not ok:
            print(f"  ✗ Не удалось кликнуть '{name}'")
            return None
        page.wait_for_timeout(500)

    result = catcher.wait_new(page, prev, timeout_ms=timeout_ms)

    # Диагностика: изменился ли URL?
    if page.url != url_before:
        print(f"  URL изменился: {page.url}")

    # Новые запросы?
    new_reqs = catcher.requests[prev_req:]
    if new_reqs:
        print(f"  Новые XHR-запросы:")
        for r in new_reqs[:5]:
            print(f"    {r['method']} {r['url'][:120]}")

    return result


def main():
    print("=" * 70)
    print("ПЕРЕХВАТ + ПЕРЕБОР СТРАТЕГИЙ КЛИКА")
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

        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        print(f"Финальный URL: {page.url}")

        # Ждём первого ответа Vue
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

        # Диагностика: какие селекторы есть на странице для "Программы"
        print(f"\n{'─' * 70}\nДИАГНОСТИКА СЕЛЕКТОРОВ\n{'─' * 70}")
        for sel in ['.file-item-listmode', '.file-content', '.file-item-name',
                    '.webmaster-file-item']:
            cnt = page.locator(sel).count()
            print(f"  '{sel}': {cnt} элементов")

        # Найдём все элементы с текстом "Программы"
        print(f"\n  Все элементы с текстом 'Программы':")
        try:
            all_p = page.locator('text="Программы"').all()
            for i, el in enumerate(all_p):
                try:
                    cls = el.get_attribute("class") or ""
                    tag = el.evaluate("el => el.tagName")
                    vis = el.is_visible()
                    print(f"    [{i}] <{tag} class='{cls}'> visible={vis}")
                except Exception as e:
                    print(f"    [{i}] error: {e}")
        except Exception as e:
            print(f"    error: {e}")

        # ─── ШАГ 1: клик по "Программы" ───
        print(f"\n{'─' * 70}\nШАГ 1: Клик по «Программы»\n{'─' * 70}")
        res1 = navigate_and_capture(page, catcher, ["Программы"])
        if not res1:
            print("✗ Не удалось")
            page.screenshot(path="/tmp/fail2.png")
            with open("/tmp/fail2.html", "w", encoding="utf-8") as f:
                f.write(page.content())
            print("Сохранены: /tmp/fail2.png и .html")
            browser.close()
            return

        data1 = res1["data"]
        items1 = data1.get("list") or []
        print(f"errno: {data1.get('errno')}, элементов: {len(items1)}")
        print_items(items1)

        # Финальный скриншот
        page.screenshot(path="/tmp/success.png")
        with open("/tmp/success.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("\nСохранены: /tmp/success.png и .html")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
