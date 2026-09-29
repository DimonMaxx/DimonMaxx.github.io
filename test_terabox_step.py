#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Финальная диагностика TeraBox API.
Цель: понять, как получить содержимое конкретной расшаренной папки.
"""

import os
import re
import sys
import json
import time
import traceback
from urllib.parse import unquote

import requests

SHARE_URLS = {
    "Для сайта":  "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA",
    "Программы":  "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA",
}

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

BASE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cookie": f"ndus={COOKIE}",
}

# Известные домены TeraBox
DOMAINS = [
    "https://www.terabox.app",
    "https://www.1024tera.com",
    "https://www.terabox.com",
]


def extract_tokens(html):
    """Извлекает jsToken, pcftoken из HTML."""
    js_token = None
    pcftoken = None

    m = re.search(r'fn%28%22([A-Za-z0-9_\-]+)%22%29', html)
    if m:
        js_token = m.group(1)

    m = re.search(r'"pcftoken"\s*:\s*"([^"]+)"', html)
    if m:
        pcftoken = m.group(1)

    return js_token, pcftoken


def extract_surls(url):
    """Возвращает все варианты surl (с ведущей 1 и без)."""
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return []
    full = m.group(1)
    no1 = full[1:] if full.startswith("1") else full
    return list({full, no1})


def analyze_response(data, label):
    """Анализирует JSON-ответ и выводит структуру."""
    print(f"\n  ── Анализ ответа ({label}) ──")
    if not isinstance(data, dict):
        print(f"    Тип ответа: {type(data).__name__}, не dict")
        return

    errno = data.get("errno")
    print(f"    errno: {errno}")
    if errno != 0:
        errmsg = data.get("errmsg") or data.get("error") or "?"
        print(f"    errmsg: {errmsg}")
        # Показываем любые подсказки
        for k, v in data.items():
            if k not in ("errno", "errmsg"):
                print(f"    {k}: {str(v)[:200]}")
        return

    flist = data.get("list") or data.get("file_list") or []
    if not isinstance(flist, list):
        print(f"    Поле 'list' не список: {type(flist)}")
        return

    print(f"    ✅ Файлов: {len(flist)}")
    for i, item in enumerate(flist[:30]):
        if not isinstance(item, dict):
            print(f"      [{i}] (не dict): {item}")
            continue
        name = item.get("server_filename") or item.get("filename") or "?"
        isdir = item.get("isdir") or 0
        size = item.get("size") or 0
        path = item.get("path") or ""
        fsid = item.get("fs_id") or ""
        kind = "DIR " if str(isdir) == "1" else "FILE"
        print(f"      [{i:>2}] [{kind}] {name}  ({size} b)  fs_id={fsid}  path={path}")


def try_endpoint(domain, endpoint, params, referer):
    """Один запрос к API."""
    api_url = f"{domain}{endpoint}"
    headers = {
        "User-Agent": BASE_HEADERS["User-Agent"],
        "Referer": referer,
        "Cookie": f"ndus={COOKIE}",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        t0 = time.time()
        r = requests.get(api_url, params=params, headers=headers, timeout=20)
        elapsed = round(time.time() - t0, 2)
        try:
            data = r.json()
            return r.status_code, data, elapsed
        except Exception:
            return r.status_code, {"_raw": r.text[:300]}, elapsed
    except requests.exceptions.Timeout:
        return None, {"_error": "timeout"}, 0
    except Exception as e:
        return None, {"_error": str(e)}, 0


def main():
    print("=" * 70)
    print("ФИНАЛЬНАЯ ДИАГНОСТИКА TERABOX API")
    print("=" * 70)

    for label, url in SHARE_URLS.items():
        print(f"\n{'=' * 70}")
        print(f"ПАПКА: {label}")
        print(f"URL: {url}")
        print("=" * 70)

        # 1. Получаем HTML
        try:
            t0 = time.time()
            r = requests.get(url, headers=BASE_HEADERS, timeout=60, allow_redirects=True)
            print(f"GET → HTTP {r.status_code} за {round(time.time() - t0, 2)} сек")
            print(f"Финальный URL: {r.url}")
            html = r.text
        except Exception as e:
            print(f"✗ Ошибка GET: {e}")
            continue

        # 2. Извлекаем токены
        js_token, pcftoken = extract_tokens(html)
        print(f"\nТокены:")
        print(f"  jsToken:  {js_token[:50] + '...' if js_token else 'НЕ НАЙДЕН'}")
        print(f"  pcftoken: {pcftoken[:50] + '...' if pcftoken else 'НЕ НАЙДЕН'}")

        if not js_token:
            print("  ✗ Без jsToken пропускаем")
            continue

        # 3. Извлекаем все варианты surl
        surls = extract_surls(url)
        print(f"\nВарианты surl: {surls}")

        # 4. Перебираем варианты. Сначала пробуем /api/list с разными именами параметра
        print(f"\n{'─' * 70}")
        print("ЭТАП 1: /api/list с разными именами параметра surl")
        print('─' * 70)

        param_names = ["shorturl", "surl", "short_url", "surl_no1"]

        for surl in surls:
            for param_name in param_names:
                params = {
                    param_name: surl,
                    "root": "1",
                    "web": "1",
                    "app_id": "250528",
                    "jsToken": js_token,
                }
                status, data, elapsed = try_endpoint(
                    "https://www.terabox.app", "/api/list",
                    params, r.url
                )
                errno = data.get("errno") if isinstance(data, dict) else "?"
                flist = data.get("list") if isinstance(data, dict) else None
                count = len(flist) if isinstance(flist, list) else 0

                # Проверяем — не вернул ли он корень диска
                is_root = False
                if isinstance(flist, list) and flist:
                    names = [i.get("server_filename") for i in flist if isinstance(i, dict)]
                    if "Для сайта" in names and "Программы" in names:
                        is_root = True

                mark = "📁 КОРЕНЬ" if is_root else ("✅ OK" if errno == 0 else "⚠")
                print(f"  {mark} param={param_name:<12} surl={surl[:25]:<25} → errno={errno}, файлов={count}")

        # 5. ЭТАП 2: /share/list на разных доменах
        print(f"\n{'─' * 70}")
        print("ЭТАП 2: /share/list на разных доменах")
        print('─' * 70)

        for surl in surls:
            for domain in DOMAINS:
                params = {
                    "shorturl": surl,
                    "root": "1",
                    "web": "1",
                    "app_id": "250528",
                    "jsToken": js_token,
                }
                status, data, elapsed = try_endpoint(domain, "/share/list", params, r.url)
                errno = data.get("errno") if isinstance(data, dict) else "?"
                errmsg = data.get("errmsg") if isinstance(data, dict) else "?"
                flist = data.get("list") if isinstance(data, dict) else None
                count = len(flist) if isinstance(flist, list) else 0
                print(f"  {domain:<30} surl={surl[:20]:<20} → errno={errno} ({errmsg}), файлов={count}")

        # 6. Сохраняем полный ответ для анализа
        # Возьмём самый успешный вариант
        print(f"\n{'─' * 70}")
        print("ЭТАП 3: Полный JSON ответа /api/list (для анализа)")
        print('─' * 70)

        for surl in surls:
            params = {
                "shorturl": surl,
                "root": "1",
                "web": "1",
                "app_id": "250528",
                "jsToken": js_token,
            }
            status, data, elapsed = try_endpoint(
                "https://www.terabox.app", "/api/list", params, r.url
            )
            print(f"\n  Запрос: surl={surl}")
            print(f"  Ответ (первые 2000 символов):")
            print(f"  {json.dumps(data, ensure_ascii=False, indent=2)[:2000]}")

    print("\n" + "=" * 70)
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 70)


if __name__ == "__main__":
    main()
