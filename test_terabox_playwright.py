#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перехват XHR-запросов TeraBox с правильным кликом по папке.
Сохраняем ВСЕ запросы от загрузки страницы, не очищаем captured.
Пробуем разные стратегии клика.
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


def analyze_requests(captured, label=""):
    """Печатает все XHR-запросы и их параметры."""
    reqs = [c for c in captured if c["kind"] == "request"]
    resps = [c for c in captured if c["kind"] == "response"]

    print(f"\n{'═' * 70}")
    print(f"АНАЛИЗ ЗАПРОСОВ {label}")
    print(f"{'═' * 70}")
    print(f"Всего request: {len(reqs)}, response: {len(resps)}")

    # Смотрим только API-запросы (не статику)
    api_reqs = [r for r in reqs
                if any(x in r["url"] for x in ("/share/", "/api/", "/list", "/main"))
                and "/static/" not in r["url"]
                and not r["url"].endswith((".js", ".css", ".png", ".jpg"))]

    print(f"\n── API-запросы ({len(api_reqs)}) ──")
    for i, r in enumerate(api_reqs):
        print(f"\n[{i}] {r['method']} {r['url'][:180]}")
        if r.get("post_data"):
            print(f"    POST: {r['post_data'][:400]}")

    # Ответы на них
    api_resps = [c for c in resps
                 if any(x in c["url"] for x in ("/share/", "/api/", "/list", "/main"))
                 and "/static/" not in c["url"]]
    print(f"\n── API-ответы ({len(api_resps)}) ──")
    for i, c in enumerate(api_resps):
        print(f"\n[{i}] HTTP {c['status']}  {c['url'][:180]}")
        preview = c.get("body_preview", "")
        if preview:
            try:
                parsed = json.loads(preview)
                if isinstance(parsed, dict):
                    print(f"    errno: {parsed.get('errno')}")
                    flist = parsed.get("list") or []
                    if isinstance(flist, list):
                        print(f"    list: {len(flist)} элементов")
                        for j, item in enumerate(flist[:5]):
                            name = item.get("server_filename") or "?"
                            isdir = item.get("isdir") or 0
                            print(f"      [{j}] {'DIR' if str(isdir) == '1' else 'FILE'} {name}")
            except Exception:
                print(f"    Body (не JSON): {preview[:200]}")


def main():
    print("=" * 70)
    print("ПЕРЕХВАТ XHR + ПРАВИЛЬНЫЙ КЛИК ПО ПАПКЕ")
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

        # ═══ Перехват ═══
        captured = []

        def on_request(req):
            try:
                if req.resource_type in ("xhr", "fetch"):
                    captured.append({
                        "kind": "request",
                        "method": req.method,
                        "url": req.url,
                        "post_data": req.post_data,
                    })
            except Exception:
                pass

        def on_response(resp):
            try:
                if resp.request.resource_type in ("xhr", "fetch"):
                    body_text = ""
                    try:
                        body_text = resp.text()[:3000]
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

        # ═══ 1. Открываем страницу ═══
        print(f"\nОткрываем: {PROGRAMS_URL}")
        page.goto(PROGRAMS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        print(f"Финальный URL: {page.url}")

        # Анализ того, что было при загрузке
        analyze_requests(captured, "(при загрузке страницы)")

        # ═══ 2. Пробуем кликнуть разными способами ═══
        print("\n" + "═" * 70)
        print("КЛИК ПО ПАПКЕ «Программы» — несколько стратегий")
        print("═" * 70)

        # Снимок состояния DOM до клика
        before_html_len = len(page.content())

        # Стратегия 1: клик по .file-item-name с текстом "Программы"
        print("\n[Стратегия 1] Клик по .file-item-name с текстом 'Программы'")
        try:
            elements = page.query_selector_all('.file-item-name')
            print(f"  Найдено .file-item-name: {len(elements)}")
            target = None
            for el in elements:
                try:
                    txt = (el.inner_text() or "").strip()
                    if txt == "Программы":
                        target = el
                        print(f"  Найден: '{txt}'")
                        break
                except Exception:
                    pass

            if target:
                captured.clear()  # очищаем, чтобы видеть только запросы от клика
                target.click(timeout=5000)
                page.wait_for_timeout(4000)
                print(f"  ✓ Клик выполнен")
            else:
                print(f"  ✗ Элемент с текстом 'Программы' не найден")
        except Exception as e:
            print(f"  ✗ Ошибка: {e}")

        # Проверяем, изменилось ли что-то
        after_html_len = len(page.content())
        print(f"\n  HTML до: {before_html_len}, после: {after_html_len}, "
              f"разница: {after_html_len - before_html_len}")

        analyze_requests(captured, "(после клика)")

        # ═══ 3. Если ничего не помогло — пробуем двойной клик ═══
        if not any(c["kind"] == "request" and "/share/" in c["url"] for c in captured):
            print("\n[Стратегия 2] Двойной клик по .file-item-name")
            try:
                elements = page.query_selector_all('.file-item-name')
                for el in elements:
                    try:
                        txt = (el.inner_text() or "").strip()
                        if txt == "Программы":
                            captured.clear()
                            el.dblclick(timeout=5000)
                            page.wait_for_timeout(4000)
                            print(f"  ✓ Двойной клик выполнен")
                            break
                    except Exception:
                        pass
            except Exception as e:
                print(f"  ✗ Ошибка: {e}")
            analyze_requests(captured, "(после двойного клика)")

        # ═══ 4. Если всё ещё нет — клик по родителю ═══
        if not any(c["kind"] == "request" and "/share/" in c["url"] for c in captured):
            print("\n[Стратегия 3] Клик по .file-content (родитель)")
            try:
                elements = page.query_selector_all('.file-content')
                print(f"  Найдено .file-content: {len(elements)}")
                for el in elements:
                    try:
                        txt = (el.inner_text() or "").strip()
                        if "Программы" in txt:
                            captured.clear()
                            el.click(timeout=5000)
                            page.wait_for_timeout(4000)
                            print(f"  ✓ Клик по родителю выполнен")
                            break
                    except Exception:
                        pass
            except Exception as e:
                print(f"  ✗ Ошибка: {e}")
            analyze_requests(captured, "(после клика по родителю)")

        # ═══ 5. Финальный анализ ═══
        print("\n" + "═" * 70)
        print("ИТОГОВЫЙ АНАЛИЗ")
        print("═" * 70)

        share_reqs = [c for c in captured if c["kind"] == "request" and "/share/" in c["url"]]
        print(f"Запросов к /share/: {len(share_reqs)}")

        if share_reqs:
            print("\n✅ Найдены запросы к /share/! Вот параметры:")
            for r in share_reqs:
                print(f"\n  {r['method']} {r['url']}")
        else:
            print("\n❌ Запросов к /share/ по-прежнему нет.")
            print("   Возможно, TeraBox делает их на другом домене или с другим путём.")

        # Сохраняем все запросы
        with open("/tmp/terabox_requests.json", "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=2, default=str)
        print(f"\nВсе запросы сохранены в /tmp/terabox_requests.json")

        # Скриншот
        page.screenshot(path="/tmp/after_click.png", full_page=False)
        print("Скриншот: /tmp/after_click.png")

        # Сохраняем HTML
        with open("/tmp/after_click.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("HTML: /tmp/after_click.html")

        browser.close()

    print("\n" + "=" * 70)
    print("ПЕРЕХВАТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
