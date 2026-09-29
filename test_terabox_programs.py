#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перебор ВСЕХ стратегий клика + прямой вызов через JS.
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
        self.all_requests = []

    def attach(self, page):
        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                self.all_requests.append({
                    "url": req.url,
                    "method": req.method,
                    "ts": time.time(),
                })

        def on_response(resp):
            if "/share/list" in resp.url and "/static/" not in resp.url:
                try:
                    data = resp.json()
                    self.responses.append({
                        "data": data,
                        "url": resp.url,
                        "ts": time.time(),
                    })
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

    def count(self):
        return len(self.responses)

    def wait_new(self, page, prev_count, timeout_ms=8000):
        elapsed = 0
        while elapsed < timeout_ms:
            if len(self.responses) > prev_count:
                return self.responses[-1]
            page.wait_for_timeout(200)
            elapsed += 200
        return None


def click_strategy(page, name, strategy_fn, timeout_ms=5000):
    """
    Пробует одну стратегию клика. Возвращает True если новый запрос пришёл.
    """
    print(f"\n  ▶ Стратегия: {name}")
    try:
        prev_count = 0  # заглушка
    except Exception:
        pass

    try:
        strategy_fn()
        page.wait_for_timeout(2500)  # даём Vue время отправить запрос
        return True
    except Exception as e:
        print(f"    ✗ Ошибка: {e}")
        return False


def main():
    print("=" * 70)
    print("ПЕРЕБОР ВСЕХ СТРАТЕГИЙ КЛИКА")
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

        initial = catcher.wait_new(page, 0, timeout_ms=10000)
        if not initial:
            print("✗ Vue не сделал /share/list")
            browser.close()
            return
        data_root = initial["data"]
        items_root = data_root.get("list") or []
        print(f"✓ Корень — errno: {data_root.get('errno')}, "
              f"элементов: {len(items_root)}")

        # ═══════════════════════════════════════════════════════════════
        # ДИАГНОСТИКА: получим координаты элементов
        # ═══════════════════════════════════════════════════════════════
        print(f"\n{'─' * 70}\nДИАГНОСТИКА: координаты и размеры\n{'─' * 70}")

        diag = page.evaluate("""() => {
            const items = document.querySelectorAll('.file-item-listmode');
            const out = [];
            items.forEach((item, idx) => {
                const rect = item.getBoundingClientRect();
                const name = item.querySelector('.file-item-name')?.textContent || '';
                const icon = item.querySelector('.file-icon-dir') ? 'yes' : 'no';
                const iconBox = item.querySelector('.icon-box') ? 'yes' : 'no';
                const fileContent = item.querySelector('.file-content') ? 'yes' : 'no';
                out.push({
                    idx, name,
                    x: Math.round(rect.x), y: Math.round(rect.y),
                    w: Math.round(rect.width), h: Math.round(rect.height),
                    hasIcon: icon, hasIconBox: iconBox, hasContent: fileContent,
                });
            });
            return out;
        }""")
        for d in diag:
            print(f"  [{d['idx']}] '{d['name']}' "
                  f"x={d['x']} y={d['y']} w={d['w']} h={d['h']} "
                  f"icon={d['hasIcon']} iconBox={d['hasIconBox']} "
                  f"content={d['hasContent']}")

        # ═══════════════════════════════════════════════════════════════
        # ПЕРЕБОР СТРАТЕГИЙ
        # ═══════════════════════════════════════════════════════════════
        print(f"\n{'═' * 70}")
        print("ПЕРЕБОР СТРАТЕГИЙ КЛИКА")
        print(f"{'═' * 70}")

        strategies = [
            # (название, функция)
            ("1. dblclick на .file-item-listmode",
             lambda: page.locator('.file-item-listmode').first.dblclick()),

            ("2. click на .file-content",
             lambda: page.locator('.file-item-listmode .file-content').first.click()),

            ("3. click на .icon-box",
             lambda: page.locator('.file-item-listmode .icon-box').first.click()),

            ("4. click на .file-icon-dir",
             lambda: page.locator('.file-item-listmode .file-icon-dir').first.click()),

            ("5. dblclick на .file-content",
             lambda: page.locator('.file-item-listmode .file-content').first.dblclick()),

            ("6. Клик через mouse.click по координатам центра",
             lambda: _mouse_click_center(page, diag)),

            ("7. dispatchEvent click через JS",
             lambda: _js_click(page)),

            ("8. mousedown + mouseup через mouse",
             lambda: _mouse_down_up(page, diag)),
        ]

        for name, fn in strategies:
            prev_count = catcher.count()
            prev_reqs = len(catcher.all_requests)
            url_before = page.url

            print(f"\n{'─' * 70}\n{name}\n{'─' * 70}")

            try:
                fn()
                page.wait_for_timeout(3000)
            except Exception as e:
                print(f"  ✗ Ошибка выполнения: {e}")
                continue

            # Проверяем, появился ли новый запрос
            new_responses = catcher.count() - prev_count
            new_reqs = catcher.all_requests[prev_reqs:]
            url_changed = page.url != url_before

            print(f"  Новых /share/list: {new_responses}")
            print(f"  Новых XHR/fetch: {len(new_reqs)}")
            print(f"  URL изменился: {url_changed}")

            if new_reqs:
                for r in new_reqs[:3]:
                    print(f"    {r['method']} {r['url'][:130]}")

            if new_responses > 0:
                print(f"\n  🎉 УСПЕХ! Стратегия '{name}' сработала!")
                result = catcher.responses[-1]
                data = result["data"]
                items = data.get("list") or []
                print(f"  errno: {data.get('errno')}, элементов: {len(items)}")
                for i, it in enumerate(items[:15]):
                    name_f = it.get("server_filename")
                    is_dir = str(it.get("isdir")) == "1"
                    kind = "DIR " if is_dir else "FILE"
                    print(f"    [{i:>2}] [{kind}] {name_f:<35} {it.get('size',0)} b")

                page.screenshot(path="/tmp/success.png")
                with open("/tmp/success.html", "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(f"\n  Сохранены: /tmp/success.png и .html")

                browser.close()
                print("\n" + "=" * 70)
                print("ТЕСТ ЗАВЕРШЁН УСПЕШНО")
                print("=" * 70)
                return

        # Если ни одна стратегия не сработала
        print(f"\n{'═' * 70}")
        print("❌ Ни одна стратегия не сработала")
        print(f"{'═' * 70}")
        print("\nПробуем ПРЯМОЙ вызов Vue через клик по DOM-элементу с эмуляцией настоящего пользователя...")

        # Fallback: заходим через URL напрямую
        print(f"\n{'─' * 70}")
        print("FALLBACK: прямой переход по URL с dir")
        print(f"{'─' * 70}")

        # Найдём surl и попробуем зайти напрямую в папку
        new_url = page.url.split('?')[0] + "?surl=y91_O-V1aszt69FeCBBcxA&dir=/Для сайта/Программы"
        # Или проще — используем текущий URL и пробуем добавить path
        from urllib.parse import quote
        try:
            # Пробуем программно вызвать Vue router push
            result = page.evaluate("""() => {
                // Ищем vue-router
                if (window.__VUE_ROUTER__) {
                    return 'has router';
                }
                // Ищем ссылки
                const links = document.querySelectorAll('a[href*="sharing/link"]');
                return {linksCount: links.length};
            }""")
            print(f"  Диагностика: {result}")
        except Exception as e:
            print(f"  Ошибка: {e}")

        page.screenshot(path="/tmp/fail_all.png")
        with open("/tmp/fail_all.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("  Сохранены: /tmp/fail_all.png и .html")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН БЕЗ УСПЕХА")
    print("=" * 70)


def _mouse_click_center(page, diag):
    """Клик через mouse.click по координатам центра строки."""
    if not diag:
        raise Exception("нет diag")
    d = diag[0]  # первая строка = папка "Программы"
    # Кликаем в центр строки
    x = d['x'] + d['w'] / 2
    y = d['y'] + d['h'] / 2
    print(f"    Клик по координатам ({x}, {y})")
    page.mouse.move(x, y)
    page.wait_for_timeout(100)
    page.mouse.click(x, y)


def _js_click(page):
    """Вызов click() через JS с bubbles."""
    result = page.evaluate("""() => {
        const item = document.querySelector('.file-item-listmode');
        if (!item) return 'no item';
        const ev = new MouseEvent('click', {
            bubbles: true,
            cancelable: true,
            view: window,
            detail: 1,
        });
        item.dispatchEvent(ev);
        // Пробуем также dblclick
        const ev2 = new MouseEvent('dblclick', {
            bubbles: true,
            cancelable: true,
            view: window,
            detail: 2,
        });
        item.dispatchEvent(ev2);
        return 'dispatched';
    }""")
    print(f"    JS dispatchEvent: {result}")


def _mouse_down_up(page, diag):
    """Полная эмуляция: move → down → up."""
    if not diag:
        raise Exception("нет diag")
    d = diag[0]
    x = d['x'] + d['w'] / 2
    y = d['y'] + d['h'] / 2
    print(f"    Mouse: move → down → up в ({x}, {y})")
    page.mouse.move(x, y)
    page.wait_for_timeout(50)
    page.mouse.down()
    page.wait_for_timeout(50)
    page.mouse.up()
    page.wait_for_timeout(50)
    # Пробуем двойной
    page.mouse.down()
    page.wait_for_timeout(50)
    page.mouse.up()


if __name__ == "__main__":
    main()
