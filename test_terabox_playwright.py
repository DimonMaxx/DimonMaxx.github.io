#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест TeraBox через Playwright.
Открывает share-ссылку в headless-браузере, ждёт загрузки,
извлекает список файлов и папок из DOM.
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

URLS = {
    "Для сайта":  "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA",
    "Программы":  "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA",
}


def extract_files_from_page(page):
    """
    Извлекает список файлов через JavaScript внутри страницы.
    Обращается к внутреннему API TeraBox, который уже использует
    все токены, установленные страницей.
    """
    # Перехватываем запросы к API и собираем ответы
    captured = []

    def on_response(response):
        try:
            url = response.url
            if "/share/list" in url or "/api/list" in url:
                if response.status == 200:
                    try:
                        data = response.json()
                        captured.append({"url": url, "data": data})
                    except Exception:
                        pass
        except Exception:
            pass

    # Уже загруженная страница — теперь пробуем вызвать fetch из JS
    # с теми же заголовками, что использует фронтенд
    result = page.evaluate("""
        async () => {
            try {
                // Получаем surl из URL
                const url = new URL(window.location.href);
                const surl = url.searchParams.get('surl');
                if (!surl) return {error: 'surl not found in URL'};

                // jsToken есть в window
                const jsToken = window.jsToken || '';
                if (!jsToken) return {error: 'jsToken not found in window'};

                // Строим запрос
                const apiUrl = 'https://www.terabox.app/share/list'
                    + '?shorturl=' + encodeURIComponent(surl)
                    + '&root=1&web=1&app_id=250528'
                    + '&jsToken=' + encodeURIComponent(jsToken)
                    + '&page=1&num=1000';

                const resp = await fetch(apiUrl, {
                    method: 'GET',
                    credentials: 'include',
                    headers: {
                        'Accept': 'application/json, text/plain, */*',
                    }
                });

                const text = await resp.text();
                let json = null;
                try { json = JSON.parse(text); } catch (e) {
                    return {error: 'not json', status: resp.status, text: text.slice(0, 500)};
                }
                return {status: resp.status, data: json};
            } catch (e) {
                return {error: String(e)};
            }
        }
    """)
    return result


def main():
    print("=" * 70)
    print("TEST TERABOX через Playwright")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1366, "height": 768},
        )

        # Устанавливаем cookie ndus
        context.add_cookies([{
            "name": "ndus",
            "value": COOKIE,
            "domain": ".terabox.app",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }])
        context.add_cookies([{
            "name": "ndus",
            "value": COOKIE,
            "domain": ".1024terabox.com",
            "path": "/",
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        }])

        for label, url in URLS.items():
            print(f"\n{'=' * 70}")
            print(f"ПАПКА: {label}")
            print(f"URL: {url}")
            print("=" * 70)

            page = context.new_page()
            try:
                # Открываем страницу
                t0 = time.time()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                print(f"Страница загружена за {round(time.time() - t0, 2)} сек")
                print(f"Финальный URL: {page.url}")
                print(f"Title: {page.title()}")

                # Ждём, пока появится jsToken
                page.wait_for_timeout(3000)

                # Пытаемся найти список файлов в DOM
                print("\nПоиск элементов на странице...")
                file_items = page.query_selector_all(
                    '.file-item, .list-item, [class*="item"], [class*="file"]'
                )
                print(f"Найдено элементов с классом item/file: {len(file_items)}")

                # Основной подход — вызвать fetch из JS
                print("\nПробуем вызвать API через fetch из JS...")
                result = extract_files_from_page(page)

                if "error" in result:
                    print(f"✗ Ошибка: {result['error']}")
                    if "status" in result:
                        print(f"  HTTP {result['status']}, ответ: {result.get('text', '')[:300]}")
                else:
                    print(f"✓ HTTP {result.get('status')}")
                    data = result.get("data", {})
                    print(f"  errno: {data.get('errno')}")
                    flist = data.get("list") or []
                    if isinstance(flist, list):
                        print(f"  Файлов: {len(flist)}")
                        for i, item in enumerate(flist[:25]):
                            name = item.get("server_filename") or item.get("filename") or "?"
                            isdir = item.get("isdir") or 0
                            size = item.get("size") or 0
                            fs_id = item.get("fs_id") or ""
                            kind = "DIR " if str(isdir) == "1" else "FILE"
                            print(f"    [{i:>2}] [{kind}] {name}  ({size} b)  fs_id={fs_id}")
                        if len(flist) > 25:
                            print(f"    ... и ещё {len(flist) - 25}")

                # Скриншот для наглядности (можно удалить)
                page.screenshot(path=f"/tmp/{label.replace(' ', '_')}.png",
                                full_page=False)
                print(f"Скриншот сохранён: /tmp/{label.replace(' ', '_')}.png")

            except Exception as e:
                print(f"✗ Ошибка Playwright: {e}")
                traceback.print_exc()
            finally:
                page.close()

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
