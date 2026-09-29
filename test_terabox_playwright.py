#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Финальный тест: получаем содержимое расшаренных папок TeraBox
через fetch прямо со страницы, используя все токены (jsToken, bdstoken, pcftoken).
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

COOKIE_DOMAINS = [
    ".terabox.app",
    ".1024tera.com",
    ".1024terabox.com",
    ".terabox.com",
    ".4funbox.com",
]


def fetch_share_list(page, surl, api_domain="https://www.1024tera.com"):
    """
    Выполняет fetch к /share/list прямо из браузера,
    используя window.jsToken, window.templateData.bdstoken и cookie.
    """
    js_code = """
    async ({surl, apiDomain}) => {
        try {
            const jsToken = window.jsToken || '';
            const templateData = window.templateData || {};
            const bdstoken = templateData.bdstoken || '';
            const pcftoken = templateData.pcftoken || '';
            const uk = templateData.uk || '';

            if (!jsToken) {
                return {error: 'jsToken не найден в window'};
            }

            const params = new URLSearchParams({
                shorturl: surl,
                root: '1',
                web: '1',
                app_id: '250528',
                jsToken: jsToken,
                page: '1',
                num: '1000',
            });
            if (bdstoken) params.set('bdstoken', bdstoken);
            if (pcftoken) params.set('pcftoken', pcftoken);
            if (uk) params.set('uk', uk);

            const apiUrl = apiDomain + '/share/list?' + params.toString();

            const resp = await fetch(apiUrl, {
                method: 'GET',
                credentials: 'include',
                headers: {
                    'Accept': 'application/json, text/plain, */*',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            const text = await resp.text();
            let json = null;
            try { json = JSON.parse(text); } catch (e) {
                return {
                    error: 'not json',
                    status: resp.status,
                    text: text.slice(0, 500),
                    tokens: {jsToken, bdstoken, pcftoken, uk},
                };
            }
            return {
                status: resp.status,
                data: json,
                tokens: {
                    jsToken: jsToken.slice(0, 30) + '...',
                    bdstoken: bdstoken.slice(0, 20) + '...',
                    pcftoken: pcftoken.slice(0, 20) + '...',
                    uk: uk,
                },
                apiUrl: apiUrl.slice(0, 200),
            };
        } catch (e) {
            return {error: 'Exception: ' + String(e)};
        }
    }
    """
    return page.evaluate(js_code, {"surl": surl, "apiDomain": api_domain})


def extract_surl(url):
    """surl без ведущей 1."""
    import re
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return None
    s = m.group(1)
    if s.startswith("1") and len(s) > 20:
        return s[1:]
    return s


def pretty_print_result(result, label):
    """Печатает результат в читаемом виде."""
    print(f"\n  ── Результат для «{label}» ──")

    if "error" in result:
        print(f"  ✗ Ошибка: {result['error']}")
        if "text" in result:
            print(f"  Ответ (первые 500 символов): {result['text']}")
        if "tokens" in result:
            print(f"  Токены: {result['tokens']}")
        return

    print(f"  HTTP {result.get('status')}")
    if "tokens" in result:
        print(f"  Токены: {result['tokens']}")

    data = result.get("data", {})
    errno = data.get("errno")
    errmsg = data.get("errmsg", "")
    print(f"  errno: {errno} {('(' + errmsg + ')') if errmsg else ''}")

    if errno != 0:
        print(f"  Полный ответ: {json.dumps(data, ensure_ascii=False)[:500]}")
        return

    flist = data.get("list") or []
    print(f"  📂 Элементов: {len(flist)}")

    for i, item in enumerate(flist[:50]):
        if not isinstance(item, dict):
            print(f"    [{i}] (не dict): {item}")
            continue
        name = item.get("server_filename") or item.get("filename") or "?"
        isdir = item.get("isdir") or 0
        size = item.get("size") or 0
        fs_id = item.get("fs_id") or 0
        path = item.get("path") or ""
        kind = "DIR " if str(isdir) == "1" else "FILE"
        size_str = f"{size} b" if size else "—"
        print(f"    [{i:>2}] [{kind}] {name:<40} {size_str:>12}  fs_id={fs_id}  path={path}")

    if len(flist) > 50:
        print(f"    ... и ещё {len(flist) - 50}")


def main():
    print("=" * 70)
    print("ФИНАЛЬНЫЙ ТЕСТ TERABOX через Playwright + fetch")
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

        # Устанавливаем cookie для всех доменов
        for domain in COOKIE_DOMAINS:
            try:
                context.add_cookies([{
                    "name": "ndus",
                    "value": COOKIE,
                    "domain": domain,
                    "path": "/",
                    "secure": True,
                    "sameSite": "None",
                }])
            except Exception as e:
                print(f"  [!] Cookie для {domain}: {e}")

        for label, url in URLS.items():
            print(f"\n{'=' * 70}")
            print(f"ПАПКА: {label}")
            print(f"URL: {url}")
            print("=" * 70)

            page = context.new_page()
            try:
                # 1. Открываем share-страницу
                t0 = time.time()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                print(f"Страница загружена за {round(time.time() - t0, 2)} сек")
                print(f"Финальный URL: {page.url}")

                # 2. Ждём, чтобы JS полностью выполнился
                page.wait_for_timeout(5000)

                # 3. Проверяем, что мы авторизованы
                state = page.evaluate("""() => ({
                    jsToken: (window.jsToken || '').slice(0, 30) + '...',
                    bdstoken: (window.templateData?.bdstoken || '').slice(0, 20) + '...',
                    pcftoken: (window.templateData?.pcftoken || '').slice(0, 20) + '...',
                    uk: window.templateData?.uk || null,
                    username: document.querySelector('.card-username')?.textContent || null,
                })""")
                print(f"Состояние: {state}")

                # 4. Извлекаем surl
                surl = extract_surl(url)
                print(f"surl: {surl}")

                # 5. Пробуем fetch с разных доменов
                for api_domain in ["https://www.1024tera.com", "https://www.terabox.app"]:
                    print(f"\n  → Запрос к {api_domain}/share/list ...")
                    result = fetch_share_list(page, surl, api_domain)
                    pretty_print_result(result, f"{label} ({api_domain})")

                    # Если получили errno=0, дальше искать не нужно
                    if result.get("data", {}).get("errno") == 0:
                        print(f"\n  ✅ Работает через {api_domain}")
                        break

            except Exception as e:
                print(f"✗ Ошибка: {e}")
                traceback.print_exc()
            finally:
                page.close()

        browser.close()

    print("\n" + "=" * 70)
    print("ФИНАЛЬНЫЙ ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
