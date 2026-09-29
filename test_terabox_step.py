#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пошаговый тест TeraBox с подробным логированием каждого этапа.
Запускается в GitHub Actions, где сеть работает стабильно.
"""

import os
import re
import sys
import json
import time
import socket
import traceback

# ─── Цвета (в GitHub Actions работают) ───
class C:
    OK    = "\033[92m"
    WARN  = "\033[93m"
    FAIL  = "\033[91m"
    INFO  = "\033[94m"
    BOLD  = "\033[1m"
    END   = "\033[0m"

def step(n, msg):
    print(f"\n{C.BOLD}[ШАГ {n}] {msg}{C.END}")
def ok(msg):   print(f"{C.OK}  ✓ {msg}{C.END}")
def warn(msg): print(f"{C.WARN}  ⚠ {msg}{C.END}")
def fail(msg): print(f"{C.FAIL}  ✗ {msg}{C.END}")
def info(msg): print(f"    {msg}")

URLS = {
    "Для сайта": "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA",
    "Программы": "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA",
}

# ШАГ 1 — cookie
step(1, "Проверка переменной окружения TERABOX_COOKIE")
cookie = os.environ.get("TERABOX_COOKIE")
if not cookie:
    fail("TERABOX_COOKIE не задан")
    sys.exit(1)
ok(f"Cookie найден, длина: {len(cookie)}")

# ШАГ 2 — базовый интернет
step(2, "Проверка базового интернета (google.com)")
try:
    t0 = time.time()
    sock = socket.create_connection(("google.com", 443), timeout=10)
    sock.close()
    ok(f"google.com доступен за {round(time.time() - t0, 2)} сек")
except Exception as e:
    fail(f"Нет доступа к google.com: {e}")

# ШАГ 3 — DNS TeraBox
step(3, "DNS-разрешение 1024terabox.com")
try:
    ip = socket.gethostbyname("1024terabox.com")
    ok(f"DNS OK, IP: {ip}")
except Exception as e:
    fail(f"DNS не резолвит: {e}")
    sys.exit(1)

# ШАГ 4 — TCP-соединение
step(4, "TCP-соединение с 1024terabox.com:443")
try:
    t0 = time.time()
    sock = socket.create_connection(("1024terabox.com", 443), timeout=15)
    sock.close()
    ok(f"TCP установлен за {round(time.time() - t0, 2)} сек")
except Exception as e:
    fail(f"TCP не открывается: {e}")
    sys.exit(1)

# ШАГ 5 — requests
step(5, "Импорт requests")
import requests
ok(f"requests {requests.__version__}")

# ШАГ 6 — GET-запрос для каждой ссылки
for label, url in URLS.items():
    step(6, f"GET-запрос к папке «{label}»")
    try:
        t0 = time.time()
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            "Cookie": f"ndus={cookie}",
        }
        r = requests.get(url, headers=headers, timeout=60, allow_redirects=True)
        ok(f"HTTP {r.status_code} за {round(time.time() - t0, 2)} сек")
        info(f"Финальный URL: {r.url}")
        info(f"Длина HTML: {len(r.text)}")

        # Проверяем токены
        for token in ("jsToken", "bdstoken", "yunData"):
            found = token in r.text
            info(f"  {'✓' if found else '✗'} {token}")

        # Извлекаем surl и jsToken
        m_surl = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
        surl = m_surl.group(1) if m_surl else None
        info(f"  surl: {surl}")

        m_js = re.search(r'jsToken\s*=\s*"([^"]+)"', r.text)
        if not m_js:
            m_js = re.search(r'jsToken\s*=\s*\'([^\']+)\'', r.text)
        js_token = m_js.group(1) if m_js else None
        info(f"  jsToken: {js_token[:50] + '...' if js_token else 'НЕ НАЙДЕН'}")

        if not (surl and js_token):
            warn("Не хватает данных для API-запроса, пропускаем")
            continue

        # ШАГ 7 — API-запрос
        step(7, f"API-запрос share/list для «{label}»")
        api_url = (
            f"https://www.terabox.com/share/list"
            f"?shorturl={surl}&root=1&web=1&app_id=250528&jsToken={js_token}"
        )
        api_headers = {
            "User-Agent": headers["User-Agent"],
            "Referer": r.url,
            "Cookie": f"ndus={cookie}",
            "Accept": "application/json, text/plain, */*",
        }
        t0 = time.time()
        api_resp = requests.get(api_url, headers=api_headers, timeout=60)
        ok(f"API HTTP {api_resp.status_code} за {round(time.time() - t0, 2)} сек")
        info(f"Длина ответа: {len(api_resp.text)} символов")

        try:
            data = api_resp.json()
            print(f"  {C.OK}JSON валидный{C.END}")
            print(f"  Ключи: {list(data.keys())}")
            flist = data.get("list") or data.get("file_list") or []
            if isinstance(flist, list):
                print(f"  {C.OK}Найдено элементов: {len(flist)}{C.END}")
                for i, item in enumerate(flist[:20]):
                    name = item.get("server_filename") or item.get("filename") or "?"
                    isdir = item.get("isdir") or 0
                    size = item.get("size") or 0
                    kind = "DIR " if str(isdir) == "1" else "FILE"
                    print(f"    [{i:>2}] [{kind}] {name}  ({size} b)")
                if len(flist) > 20:
                    print(f"    ... и ещё {len(flist) - 20}")
            else:
                print("  Полный ответ:")
                print(json.dumps(data, ensure_ascii=False, indent=2)[:3000])
        except Exception as e:
            fail(f"Не JSON: {e}")
            print(api_resp.text[:1000])

    except requests.exceptions.Timeout:
        fail("Timeout при GET")
    except Exception as e:
        fail(f"Ошибка: {e}")
        traceback.print_exc()

print()
print("=" * 60)
print(f"{C.OK}ТЕСТ ЗАВЕРШЁН{C.END}")
print("=" * 60)
