#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перехватываем все XHR-запросы, которые делает Vue-приложение TeraBox,
когда пользователь кликает по папке. Это покажет правильный endpoint
и параметры для получения содержимого.
"""

import os
import sys
import json
import time
import traceback

from playwright.sync_api import sync_playwright

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

PROGRAMS_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"

COOKIE_DOMAINS = [
    ".terabox.app",
    ".1024tera.com",
    ".1024terabox.com",
    ".terabox.com",
    ".4funbox.com",
]


def main():
    print("=" * 70)
    print("ПЕРЕХВАТ XHR-ЗАПРОСОВ TERABOX")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
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

        # ─── Перехватываем все запросы и ответы ───
        captured = []

        def on_request(req):
            """Фиксируем все XHR/fetch-запросы."""
            try:
                rtype = req.resource_type
                if rtype in ("xhr", "fetch"):
                    captured.append({
                        "kind": "request",
                        "method": req.method,
                        "url": req.url,
                        "post_data": req.post_data,
                        "headers": req.headers,
                    })
            except Exception:
                pass

        def on_response(resp):
            """Фиксируем ответы на XHR/fetch."""
            try:
                req = resp.request
                if req.resource_type in ("xhr", "fetch"):
                    body_text = ""
                    try:
                        # Пробуем взять JSON
                        body_text = resp.text()[:2000]
                    except Exception:
                        pass
                    captured.append({
                        "kind": "response",
                        "url": resp.url,
                        "status": resp.status,
                        "content_type": resp.headers.get("content-type", ""),
                        "body_preview": body_text,
                    })
            except Exception:
                pass

        page.on("request", on_request)
        page.on("response", on_response)

        # ─── 1. Открываем страницу ───
        print(f"\nОткрываем: {PROGRAMS_URL}")
        page.goto(PROGRAMS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        print(f"Финальный URL: {page.url}")

        # Очищаем список — оставим только то, что пойдёт после клика
        captured.clear()

        # ─── 2. Кликаем по папке "Программы" в интерфейсе ───
        print("\n" + "─" * 70)
        print("ШАГ 1: Клик по папке «Программы» в интерфейсе")
        print("─" * 70)

        # Ищем элементы с названием "Программы"
        candidates = page.query_selector_all('text=Программы')
        print(f"Найдено элементов с текстом 'Программы': {len(candidates)}")

        clicked = False
        for el in candidates:
            try:
                # Пропускаем breadcrumb и левый сайдбар, кликаем только по основной папке
                # Пробуем кликнуть по 2-му (обычно это папка в основном окне)
                el.click()
                page.wait_for_timeout(3000)
                print(f"✓ Клик выполнен по элементу")
                clicked = True
                break
            except Exception as e:
                print(f"  Ошибка клика: {e}")

        if not clicked:
            print("✗ Не удалось кликнуть по папке")

        # Даём время на выполнение всех запросов
        page.wait_for_timeout(4000)

        # ─── 3. Анализируем собранные запросы ───
        print("\n" + "─" * 70)
        print("ШАГ 2: Собранные XHR/fetch-запросы и ответы")
        print("─" * 70)

        # Фильтруем — интересуют только запросы к API TeraBox
        api_requests = [c for c in captured
                        if c["kind"] == "request"
                        and "/share/" in c.get("url", "")
                        and "/static/" not in c.get("url", "")]
        api_responses = [c for c in captured
                         if c["kind"] == "response"
                         and "/share/" in c.get("url", "")
                         and "/static/" not in c.get("url", "")]

        print(f"\nВсего XHR/fetch-запросов: {len([c for c in captured if c['kind'] == 'request'])}")
        print(f"Запросов к /share/: {len(api_requests)}")

        print("\n" + "─" * 70)
        print("ЗАПРОСЫ к /share/:")
        print("─" * 70)
        for i, req in enumerate(api_requests):
            print(f"\n[{i}] {req['method']} {req['url'][:200]}")
            if req.get("post_data"):
                print(f"     POST: {req['post_data'][:300]}")

        print("\n" + "─" * 70)
        print("ОТВЕТЫ от /share/:")
        print("─" * 70)
        for i, resp in enumerate(api_responses):
            print(f"\n[{i}] HTTP {resp['status']}  {resp['url'][:200]}")
            print(f"     Content-Type: {resp['content_type']}")
            preview = resp.get("body_preview", "")
            if preview:
                # Красивый JSON
                try:
                    parsed = json.loads(preview)
                    print(f"     JSON keys: {list(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__}")
                    if isinstance(parsed, dict):
                        print(f"     errno: {parsed.get('errno')}")
                        flist = parsed.get("list") or []
                        print(f"     list length: {len(flist) if isinstance(flist, list) else 'not list'}")
                        if isinstance(flist, list) and flist:
                            for j, item in enumerate(flist[:10]):
                                name = item.get("server_filename") or "?"
                                isdir = item.get("isdir") or 0
                                kind = "DIR" if str(isdir) == "1" else "FILE"
                                print(f"       [{j}] [{kind}] {name}")
                except Exception:
                    print(f"     Body: {preview[:300]}")

        # ─── 4. Сохраняем все запросы для анализа ───
        with open("/tmp/terabox_requests.json", "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nВсе запросы сохранены в /tmp/terabox_requests.json")

        # Делаем скриншот после клика
        page.screenshot(path="/tmp/after_click.png", full_page=False)
        print("Скриншот после клика: /tmp/after_click.png")

        browser.close()

    print("\n" + "=" * 70)
    print("ПЕРЕХВАТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
