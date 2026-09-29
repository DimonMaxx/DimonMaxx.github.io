#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка: отдаёт ли TeraBox HTML нашему IP GitHub Actions.
Смотрим, что реально возвращается по ссылке.
"""

import os
import requests

URL = "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA"
COOKIE = os.environ.get("TERABOX_COOKIE", "")

headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cookie": f"ndus={COOKIE}",
}

print("=" * 60)
print("Проверка HTML от TeraBox")
print("=" * 60)
print(f"Cookie передан: {'да' if COOKIE else 'НЕТ'}")

try:
    r = requests.get(URL, headers=headers, timeout=30, allow_redirects=True)
    print(f"\nHTTP статус: {r.status_code}")
    print(f"Финальный URL: {r.url}")
    print(f"Длина HTML: {len(r.text)} символов")
    print(f"Content-Type: {r.headers.get('content-type')}")

    # Ищем признаки блокировки
    html_lower = r.text.lower()
    if "captcha" in html_lower or "капча" in html_lower:
        print("\n⚠️  ОБНАРУЖЕНА КАПЧА — TeraBox блокирует IP GitHub Actions")
    if "cloudflare" in html_lower:
        print("\n⚠️  ОБНАРУЖЕН CLOUDFLARE — IP заблокирован")
    if "jsToken" in r.text:
        print("\n✓ jsToken найден в HTML — библиотека должна работать")
    else:
        print("\n✗ jsToken НЕ найден — вот почему библиотека падает")

    # Сохраняем первые 2000 символов для анализа
    print("\n" + "─" * 60)
    print("Первые 2000 символов HTML:")
    print("─" * 60)
    print(r.text[:2000])

    # Ищем ключевые переменные
    print("\n" + "─" * 60)
    print("Поиск ключевых переменных:")
    print("─" * 60)
    for token in ("jsToken", "dp-logid", "yunData", "bdstoken", "csrfToken"):
        found = token in r.text
        print(f"  {token}: {'✓ найден' if found else '✗ не найден'}")

except Exception as e:
    print(f"\n✗ Ошибка запроса: {e}")
