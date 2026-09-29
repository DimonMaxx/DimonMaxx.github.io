#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика TeraBox API с правильным извлечением jsToken
из eval(decodeURIComponent(...)) и попыткой на нескольких доменах.
"""

import os
import re
import sys
import json
import time
import traceback
from urllib.parse import unquote

import requests

URLS = {
    "Для сайта":  "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA",
    "Программы":  "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA",
}

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/120.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Cookie": f"ndus={COOKIE}",
}

# Все известные домены TeraBox (проверим все)
API_DOMAINS = [
    "https://www.terabox.app",
    "https://www.1024tera.com",
    "https://www.terabox.com",
    "https://www.4funbox.com",
]


def extract_tokens(html):
    """Извлекает jsToken, pcftoken и другие токены из HTML."""
    result = {
        "jsToken": None,
        "pcftoken": None,
    }

    # 1. jsToken — внутри eval(decodeURIComponent(`...fn%28%22XXX%22%29...`))
    # Ищем паттерн fn%28%22<token>%22%29 в URL-encoded виде
    m = re.search(r'fn%28%22([A-Za-z0-9_\-]+)%22%29', html)
    if m:
        result["jsToken"] = m.group(1)
    else:
        # Резервный вариант: ищем всё, декодируем и уже там ищем
        m_eval = re.search(r'decodeURIComponent\(`([^`]+)`\)', html)
        if m_eval:
            decoded = unquote(m_eval.group(1))
            m2 = re.search(r'fn\("([A-Za-z0-9_\-]+)"\)', decoded)
            if m2:
                result["jsToken"] = m2.group(1)

    # 2. pcftoken — в templateData JSON
    m = re.search(r'"pcftoken"\s*:\s*"([^"]+)"', html)
    if m:
        result["pcftoken"] = m.group(1)

    return result


def extract_surl(url):
    """Извлекает surl без ведущей '1'."""
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return None
    surl = m.group(1)
    # TeraBox API принимает surl без ведущей '1'
    if surl.startswith("1") and len(surl) > 20:
        return surl[1:]
    return surl


def try_api_requests(surl, js_token, referer_url, label):
    """Пробует API на нескольких доменах и эндпоинтах."""
    endpoints = [
        "/share/list",
        "/api/list",
        "/share/listall",
    ]
    params_variants = [
        # Стандартный набор параметров
        lambda surl, js: {
            "shorturl": surl, "root": "1", "web": "1",
            "app_id": "250528", "jsToken": js,
        },
        # Без jsToken (иногда работает)
        lambda surl, js: {
            "shorturl": surl, "root": "1", "web": "1",
            "app_id": "250528",
        },
        # С page
        lambda surl, js: {
            "shorturl": surl, "root": "1", "web": "1",
            "app_id": "250528", "jsToken": js, "page": "1", "num": "1000",
        },
    ]

    for domain in API_DOMAINS:
        for endpoint in endpoints:
            for i, params_fn in enumerate(params_variants):
                api_url = f"{domain}{endpoint}"
                params = params_fn(surl, js_token)
                api_headers = {
                    "User-Agent": HEADERS_BASE["User-Agent"],
                    "Referer": referer_url,
                    "Cookie": f"ndus={COOKIE}",
                    "Accept": "application/json, text/plain, */*",
                }
                try:
                    t0 = time.time()
                    r = requests.get(api_url, params=params,
                                     headers=api_headers, timeout=20)
                    elapsed = round(time.time() - t0, 2)
                    status = r.status_code
                    text_preview = r.text[:150].replace("\n", " ")

                    # Проверяем, JSON ли это и есть ли errno
                    try:
                        data = r.json()
                        errno = data.get("errno")
                        if errno == 0:
                            print(f"    ✅ УСПЕХ!")
                            print(f"       Domain:   {domain}")
                            print(f"       Endpoint: {endpoint}")
                            print(f"       Params:   {list(params.keys())}")
                            print(f"       Status:   {status}  Time: {elapsed} sec")
                            print(f"       Keys:     {list(data.keys())}")
                            return domain, endpoint, data
                        else:
                            errmsg = data.get("errmsg") or data.get("error") or "?"
                            print(f"    ⚠ {domain}{endpoint} [P{i}] → errno={errno} ({errmsg})")
                    except Exception:
                        # Не JSON
                        print(f"    ⚠ {domain}{endpoint} [P{i}] → HTTP {status}, не JSON: {text_preview[:80]}")

                except requests.exceptions.Timeout:
                    print(f"    ✗ {domain}{endpoint} [P{i}] → timeout")
                except Exception as e:
                    print(f"    ✗ {domain}{endpoint} [P{i}] → {e}")

    return None, None, None


def main():
    print("=" * 60)
    print("ДИАГНОСТИКА API TERABOX")
    print("=" * 60)

    for label, url in URLS.items():
        print(f"\n{'=' * 60}")
        print(f"ПАПКА: {label}")
        print(f"URL: {url}")
        print("=" * 60)

        try:
            # Шаг 1. Получаем HTML
            t0 = time.time()
            r = requests.get(url, headers=HEADERS_BASE, timeout=60,
                             allow_redirects=True)
            print(f"GET → HTTP {r.status_code} за {round(time.time() - t0, 2)} сек")
            print(f"Финальный URL: {r.url}")
            html = r.text

            # Шаг 2. Извлекаем токены
            tokens = extract_tokens(html)
            print(f"\nИзвлечённые токены:")
            print(f"  jsToken:  {tokens['jsToken'][:60] + '...' if tokens['jsToken'] else 'НЕ НАЙДЕН'}")
            print(f"  pcftoken: {tokens['pcftoken'][:60] + '...' if tokens['pcftoken'] else 'НЕ НАЙДЕН'}")

            if not tokens["jsToken"]:
                print("  ✗ Без jsToken API-запрос невозможен, пропускаем")
                continue

            # Шаг 3. Извлекаем surl
            surl = extract_surl(url)
            print(f"\nsurl (без ведущей '1'): {surl}")

            # Шаг 4. Пробуем API
            print(f"\nПеребор вариантов API:")
            domain, endpoint, data = try_api_requests(
                surl, tokens["jsToken"], r.url, label
            )

            if data:
                print(f"\n🎉 РАБОЧАЯ КОМБИНАЦИЯ НАЙДЕНА:")
                print(f"   Domain:   {domain}")
                print(f"   Endpoint: {endpoint}")
                print(f"\nОтвет (первые 3000 символов):")
                print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])

                # Анализ структуры
                flist = data.get("list") or data.get("file_list") or []
                if isinstance(flist, list):
                    print(f"\n📂 Файлов в ответе: {len(flist)}")
                    for i, item in enumerate(flist[:20]):
                        name = item.get("server_filename") or item.get("filename") or "?"
                        isdir = item.get("isdir") or 0
                        size = item.get("size") or 0
                        kind = "DIR " if str(isdir) == "1" else "FILE"
                        print(f"  [{i:>2}] [{kind}] {name}  ({size} b)")
                    if len(flist) > 20:
                        print(f"  ... и ещё {len(flist) - 20}")
            else:
                print(f"\n❌ Ни одна комбинация не сработала")

        except Exception as e:
            print(f"✗ Ошибка: {e}")
            traceback.print_exc()

    print("\n" + "=" * 60)
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 60)


if __name__ == "__main__":
    main()
