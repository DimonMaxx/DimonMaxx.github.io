#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перехватываем реальный запрос Vue к /share/list и повторяем его 1-в-1.
Так мы узнаем все заголовки, которые требует TeraBox.
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

# Открываем на 1024terabox.com — как в самом первом успешном тесте
START_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"

COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com", ".d.terabox.app",
]


def main():
    print("=" * 70)
    print("ПЕРЕХВАТ РЕАЛЬНОГО ЗАПРОСА VUE К /share/list")
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

        # Перехватываем все запросы/ответы
        share_requests = []
        share_responses = []

        def on_request(req):
            if "/share/list" in req.url and req.resource_type in ("xhr", "fetch"):
                try:
                    headers = req.all_headers()
                except Exception:
                    headers = {}
                share_requests.append({
                    "url": req.url,
                    "method": req.method,
                    "headers": headers,
                    "post_data": req.post_data,
                })

        def on_response(resp):
            if "/share/list" in resp.url:
                try:
                    body = resp.text()
                except Exception:
                    body = ""
                share_responses.append({
                    "url": resp.url,
                    "status": resp.status,
                    "body": body[:2000],
                })

        page.on("request", on_request)
        page.on("response", on_response)

        # ─── Открываем страницу ───
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print(f"Финальный URL: {page.url}")

        print(f"\nЗапросов /share/list при загрузке: {len(share_requests)}")
        for i, req in enumerate(share_requests):
            print(f"  [{i}] {req['method']} {req['url'][:150]}")

        # ─── Кликаем по папке «Программы» ───
        print(f"\n{'─' * 70}")
        print("Кликаем по папке «Программы»")
        print(f"{'─' * 70}")

        # Сбрасываем перехват, чтобы видеть только новые запросы
        share_requests.clear()
        share_responses.clear()

        target = None
        for el in page.query_selector_all('.file-item-name'):
            try:
                if (el.inner_text() or "").strip() == "Программы":
                    target = el
                    break
            except Exception:
                pass

        if not target:
            print("✗ Папка 'Программы' не найдена")
            browser.close()
            return

        target.click(timeout=5000)
        page.wait_for_timeout(5000)

        print(f"\nПосле клика запросов /share/list: {len(share_requests)}")

        # ─── Анализируем перехваченные запросы ───
        for i, req in enumerate(share_requests):
            print(f"\n{'═' * 70}")
            print(f"ЗАПРОС #{i}")
            print(f"{'═' * 70}")
            print(f"URL: {req['url']}")
            print(f"Method: {req['method']}")
            if req.get("post_data"):
                print(f"POST data: {req['post_data']}")
            print(f"\nВСЕ ЗАГОЛОВКИ:")
            for k, v in sorted(req["headers"].items()):
                # Скрываем длинные токены в выводе
                if k.lower() in ("cookie",) and len(v) > 200:
                    print(f"  {k}: {v[:200]}...")
                else:
                    print(f"  {k}: {v}")

        # ─── Анализируем ответы ───
        for i, resp in enumerate(share_responses):
            print(f"\n{'═' * 70}")
            print(f"ОТВЕТ #{i}")
            print(f"{'═' * 70}")
            print(f"URL: {resp['url']}")
            print(f"Status: {resp['status']}")
            print(f"Body (первые 500 символов):")
            print(f"  {resp['body'][:500]}")

        # ─── Проверяем, что запрос от Vue сработал ───
        if share_responses:
            body = share_responses[0]["body"]
            try:
                data = json.loads(body)
                errno = data.get("errno")
                items = data.get("list") or []
                print(f"\n✓ errno: {errno}, элементов: {len(items)}")
                for it in items:
                    print(f"    {it.get('server_filename')}  "
                          f"isdir={it.get('isdir')}  dlink={'✓' if it.get('dlink') else '✗'}")
            except Exception as e:
                print(f"Не JSON: {e}")

        # ─── Пробуем повторить запрос через fetch ───
        if share_requests:
            last_req = share_requests[-1]
            print(f"\n{'─' * 70}")
            print("ПРОБУЕМ ПОВТОРИТЬ ЗАПРОС ЧЕРЕЗ fetch с теми же параметрами")
            print(f"{'─' * 70}")

            # Извлекаем query-параметры из URL
            from urllib.parse import urlparse, parse_qs
            parsed = urlparse(last_req["url"])
            params = parse_qs(parsed.query)
            # Упрощаем до dict
            params_simple = {k: v[0] for k, v in params.items()}

            result = page.evaluate("""async ({params}) => {
                const search = new URLSearchParams();
                for (const k in params) search.set(k, params[k]);
                const url = '/share/list?' + search.toString();
                try {
                    const resp = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'X-Requested-With': 'XMLHttpRequest',
                            'Accept': 'application/json, text/plain, */*',
                        },
                    });
                    const text = await resp.text();
                    return {status: resp.status, body: text.slice(0, 500)};
                } catch (e) {
                    return {error: String(e)};
                }
            }""", {"params": params_simple})

            print(f"Ответ: {result}")

        browser.close()

    print("\n" + "=" * 70)
    print("ПЕРЕХВАТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
