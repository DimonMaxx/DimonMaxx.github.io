#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика формата HTML от TeraBox.
Выводит контекст вокруг jsToken, bdstoken, чтобы понять,
как именно они встроены в страницу.
"""

import os
import re
import sys
import json
import time
import traceback

import requests

URLS = {
    "Для сайта": "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA",
    "Программы": "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA",
}

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cookie": f"ndus={COOKIE}",
}

def show_context(html, keyword, window=150, max_hits=3):
    """Показывает контекст вокруг всех вхождений keyword."""
    print(f"\n  Контексты для «{keyword}» (окно ±{window} символов):")
    positions = [m.start() for m in re.finditer(re.escape(keyword), html)]
    if not positions:
        print(f"    ✗ Ни одного вхождения")
        return
    print(f"    Найдено вхождений: {len(positions)}")
    for i, pos in enumerate(positions[:max_hits]):
        start = max(0, pos - window)
        end = min(len(html), pos + window + len(keyword))
        snippet = html[start:end].replace("\n", "\\n")
        print(f"\n    ─── Вхождение #{i+1} на позиции {pos} ───")
        print(f"    ...{snippet}...")

def try_extract(html, label):
    """Пробует все известные регулярки для jsToken и surl."""
    print(f"\n  ─── Попытки извлечь для «{label}» ───")

    patterns = [
        (r'jsToken\s*=\s*"([^"]+)"',      "jsToken = \"...\""),
        (r"jsToken\s*=\s*'([^']+)'",       "jsToken = '...'"),
        (r'"jsToken"\s*:\s*"([^"]+)"',     "\"jsToken\": \"...\""),
        (r"'jsToken'\s*:\s*'([^']+)'",     "'jsToken': '...'"),
        (r"jsToken\s*[:=]\s*['\"]?([^'\";,\s)]+)['\"]?", "jsToken: <anything>"),
        (r"window\.jsToken\s*=\s*['\"]([^'\"]+)",  "window.jsToken = ..."),
    ]
    for pat, desc in patterns:
        m = re.search(pat, html)
        if m:
            print(f"    ✓ [{desc}] → {m.group(1)[:80]}")
        else:
            print(f"    ✗ [{desc}]")

def main():
    print("=" * 60)
    print("ДИАГНОСТИКА ФОРМАТА HTML TERABOX")
    print("=" * 60)

    for label, url in URLS.items():
        print(f"\n{'=' * 60}")
        print(f"ПАПКА: {label}")
        print(f"URL: {url}")
        print("=" * 60)

        try:
            t0 = time.time()
            r = requests.get(url, headers=HEADERS, timeout=60, allow_redirects=True)
            print(f"HTTP {r.status_code} за {round(time.time() - t0, 2)} сек")
            print(f"Финальный URL: {r.url}")
            html = r.text
            print(f"Длина HTML: {len(html)}")

            # Сохраняем в файл на случай анализа
            with open(f"/tmp/{label.replace(' ', '_')}.html", "w", encoding="utf-8") as f:
                f.write(html)
            print(f"HTML сохранён в /tmp/{label.replace(' ', '_')}.html")

            # Показываем контексты ключевых токенов
            show_context(html, "jsToken", window=200, max_hits=3)
            show_context(html, "bdstoken", window=150, max_hits=2)
            show_context(html, "yunData", window=100, max_hits=2)

            # Пробуем регулярки
            try_extract(html, label)

            # Показываем все script-теги, содержащие jsToken
            print("\n  ─── Все <script>-теги с jsToken ───")
            script_re = re.compile(r'<script[^>]*>(.*?)</script>', re.DOTALL | re.IGNORECASE)
            for i, m in enumerate(script_re.finditer(html)):
                content = m.group(1)
                if "jsToken" in content:
                    print(f"\n    <script> #{i} (длина {len(content)}):")
                    # Выводим первые 500 символов содержимого
                    print(f"    {content[:500]}")
                    break

            # Извлекаем surl правильно
            print("\n  ─── Извлечение surl ───")
            m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
            if m:
                full_surl = m.group(1)
                print(f"    Полный surl из URL: {full_surl}")
                # В TeraBox API обычно нужен surl БЕЗ первой '1'
                if full_surl.startswith("1") and len(full_surl) > 20:
                    print(f"    Без ведущей '1':    {full_surl[1:]}")

        except Exception as e:
            print(f"✗ Ошибка: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 60)

if __name__ == "__main__":
    main()
