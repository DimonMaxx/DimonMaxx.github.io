#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Улучшенный тест TeraBox через Playwright.
- Устанавливает cookie для всех доменов TeraBox
- Выводит состояние авторизации
- Извлекает список файлов из DOM
- Кликает по папкам и показывает результат
"""

import os
import sys
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

# ─── Домены, для которых устанавливаем cookie ───
COOKIE_DOMAINS = [
    ".terabox.app",
    ".1024tera.com",
    ".1024terabox.com",
    ".terabox.com",
    ".4funbox.com",
]


def dump_page_info(page, label):
    """Собирает и печатает состояние страницы."""
    print(f"\n  ── Состояние страницы ──")

    # Title
    try:
        print(f"  Title: {page.title()}")
    except Exception:
        pass

    # window.jsToken и другие глобальные
    try:
        state = page.evaluate("""() => ({
            jsToken: window.jsToken || null,
            bdstoken: window.bdstoken || null,
            isLogin: window.isLogin || null,
            hasUser: !!document.querySelector('.user-avatar, [class*="avatar"]'),
            cookieStr: document.cookie,
            url: window.location.href,
        })""")
        print(f"  URL: {state.get('url')}")
        print(f"  window.jsToken: {str(state.get('jsToken'))[:60]}")
        print(f"  window.bdstoken: {str(state.get('bdstoken'))[:60]}")
        print(f"  isLogin: {state.get('isLogin')}")
        print(f"  document.cookie: {str(state.get('cookieStr'))[:200]}")

        # Ищем кнопку "Войти"
        login_btn = page.query_selector('text=Войти')
        print(f"  Кнопка 'Войти' на странице: {'ДА (не авторизованы)' if login_btn else 'нет (авторизованы)'}")
    except Exception as e:
        print(f"  Ошибка сбора состояния: {e}")

    # Ищем элементы списка файлов
    print(f"\n  ── Поиск элементов списка файлов ──")

    # Смотрим, какие классы есть на странице
    selectors_to_try = [
        '.file-item',
        '.list-item',
        '.wp-sdk-file-list-item',
        '[class*="file-list"]',
        '[class*="file-item"]',
        '[class*="wp-sdk"]',
        'tr[data-id]',
        'li[data-id]',
        '[class*="item-row"]',
    ]
    for sel in selectors_to_try:
        try:
            items = page.query_selector_all(sel)
            if items:
                print(f"  '{sel}' → {len(items)} элементов")
        except Exception:
            pass

    # Более широкий поиск — все элементы с data-атрибутами fs_id или file
    try:
        wide = page.query_selector_all('[data-id], [data-fs-id], [data-fsid]')
        print(f"  Элементов с data-id/fs-id: {len(wide)}")
        for i, el in enumerate(wide[:10]):
            attrs = page.evaluate("el => Object.fromEntries([...el.attributes].map(a => [a.name, a.value]))", el)
            text = (el.inner_text() or "").strip()[:60]
            print(f"    [{i}] {text!r} attrs={attrs}")
    except Exception as e:
        print(f"  Ошибка: {e}")

    # Выводим фрагмент HTML — ищем блок со списком файлов
    try:
        html = page.content()
        # Ищем, где может быть контейнер списка
        for marker in ("wp-sdk-file-list", "file-list", "share-list", "list-container"):
            if marker in html:
                idx = html.find(marker)
                print(f"\n  Найден маркер '{marker}' на позиции {idx}")
                print(f"  Контекст: ...{html[max(0, idx-100):idx+400]}...")
                break
    except Exception as e:
        print(f"  Ошибка поиска в HTML: {e}")


def try_click_and_read(page, label):
    """Пробует кликнуть по первой папке и посмотреть, что появится."""
    print(f"\n  ── Попытка кликнуть на первую папку ──")

    # Ищем кликабельные элементы
    candidates = [
        'text=Программы',
        'text=Для сайта',
        '[class*="folder"]',
        '[class*="dir"]',
    ]
    clicked = False
    for sel in candidates:
        try:
            els = page.query_selector_all(sel)
            if els:
                print(f"  Найдено '{sel}': {len(els)} элементов")
                # Пробуем кликнуть по первому
                try:
                    els[0].click()
                    page.wait_for_timeout(3000)
                    print(f"  ✓ Клик выполнен, текущий URL: {page.url}")
                    clicked = True
                    break
                except Exception as e:
                    print(f"  ✗ Ошибка клика: {e}")
        except Exception:
            pass

    if not clicked:
        print(f"  Не удалось кликнуть ни по одному элементу")


def main():
    print("=" * 70)
    print("TEST TERABOX — версия 2 (с правильными cookie)")
    print("=" * 70)
    print(f"TERABOX_COOKIE: {COOKIE[:20]}... (длина {len(COOKIE)})")
    print(f"Будет установлен для доменов: {COOKIE_DOMAINS}")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            locale="ru-RU",
            viewport={"width": 1366, "height": 900},
        )

        # Устанавливаем cookie для ВСЕХ доменов
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
                print(f"  Cookie установлен для {domain}")
            except Exception as e:
                print(f"  [!] Не удалось установить cookie для {domain}: {e}")

        for label, url in URLS.items():
            print(f"\n{'=' * 70}")
            print(f"ПАПКА: {label}")
            print(f"URL: {url}")
            print("=" * 70)

            page = context.new_page()
            try:
                # Открываем
                t0 = time.time()
                page.goto(url, wait_until="domcontentloaded", timeout=60000)
                print(f"Страница загружена за {round(time.time() - t0, 2)} сек")
                print(f"Финальный URL: {page.url}")

                # Ждём побольше, чтобы JS успел подгрузить данные
                page.wait_for_timeout(7000)

                # Анализируем страницу
                dump_page_info(page, label)

                # Пробуем кликнуть на папку
                try_click_and_read(page, label)

                # Скриншот
                screenshot_path = f"/tmp/{label.replace(' ', '_')}_v2.png"
                page.screenshot(path=screenshot_path, full_page=True)
                print(f"\n  Скриншот: {screenshot_path}")

                # Сохраняем HTML
                html_path = f"/tmp/{label.replace(' ', '_')}_v2.html"
                with open(html_path, "w", encoding="utf-8") as f:
                    f.write(page.content())
                print(f"  HTML: {html_path}")

            except Exception as e:
                print(f"✗ Ошибка: {e}")
                traceback.print_exc()
            finally:
                page.close()

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
