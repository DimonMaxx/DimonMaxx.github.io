#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeraBox: получаем cookies через Playwright, запросы через requests.
Исправлены: status_code, дедупликация cookies, referer из правильного домена.
"""

import os
import re
import sys
import json
import time
import random
import traceback

import requests
from playwright.sync_api import sync_playwright

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

PROGRAMS_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"

COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com", ".d.terabox.app",
]


def make_dp_logid():
    return str(random.randint(10**17, 10**18 - 1))


def get_tokens_and_cookies(context, page):
    """Собирает токены и уникальные cookies."""
    tokens = page.evaluate("""() => ({
        jsToken: window.jsToken || '',
        bdstoken: (window.templateData && window.templateData.bdstoken) || '',
        pcftoken: (window.templateData && window.templateData.pcftoken) || '',
        uk: (window.templateData && window.templateData.uk) || '',
    })""")

    # Дедупликация: собираем пары name=value в dict, чтобы убрать повторы
    cookies_raw = context.cookies()
    seen = {}
    for c in cookies_raw:
        # Ключ — name; оставляем последнее значение (оно обычно самое свежее)
        seen[c["name"]] = c["value"]
    cookie_header = "; ".join(f"{k}={v}" for k, v in seen.items())

    return tokens, cookie_header


def share_list(session, tokens, cookie_header, surl, referer, dir_path=None):
    """Запрос к /share/list через requests."""
    params = {
        "clientfrom": "h5",
        "psign": "0",
        "pcftoken": tokens["pcftoken"],
        "clienttype": "0",
        "channel": "dubox",
        "page": "1",
        "num": "1000",
        "web": "1",
        "scene": "",
        "shorturl": surl,
        "by": "time",
        "order": "desc",
        "app_id": "250528",
        "jsToken": tokens["jsToken"],
        "dp-logid": make_dp_logid(),
    }
    if tokens["bdstoken"]:
        params["bdstoken"] = tokens["bdstoken"]
    if dir_path:
        params["dir"] = dir_path

    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Referer": referer,
        "Cookie": cookie_header,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "X-Requested-With": "XMLHttpRequest",
    }

    url = "https://www.terabox.app/share/list"
    resp = session.get(url, params=params, headers=headers, timeout=60)
    # ✅ ИСПРАВЛЕНО: status_code вместо status
    print(f"  HTTP {resp.status_code}")
    try:
        return resp.json()
    except Exception as e:
        return {
            "errno": -1,
            "errmsg": f"not json: {e}",
            "text": resp.text[:300],
        }


def download_file(session, dlink, save_path, referer, cookie_header):
    """Скачивает файл через requests."""
    headers = {
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        "Referer": referer,
        "Cookie": cookie_header,
        "Accept": "*/*",
    }
    print(f"  GET {dlink[:110]}...")
    t0 = time.time()
    resp = session.get(dlink, headers=headers, timeout=300,
                       stream=True, allow_redirects=True)
    elapsed = round(time.time() - t0, 2)
    # ✅ ИСПРАВЛЕНО: status_code вместо status
    print(f"  HTTP {resp.status_code} за {elapsed} сек")
    if resp.status_code != 200:
        return None
    with open(save_path, "wb") as f:
        total = 0
        for chunk in resp.iter_content(chunk_size=65536):
            f.write(chunk)
            total += len(chunk)
    print(f"  ✓ Сохранено: {save_path} ({total} байт)")
    return save_path


def parse_software_txt(file_path):
    """Парсит 1_Software.txt."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    programs = {}
    current = None
    for raw in content.split("\n"):
        line = raw.rstrip("\r").strip()
        if not line:
            continue
        if line.startswith("Name="):
            name = line[5:].strip()
            if name:
                current = {
                    "name": name, "hint": "", "icon": "", "icon_index": "",
                    "group": "", "version": "", "url": "", "key": "",
                }
                programs[name.lower()] = current
        elif current is not None:
            if line.startswith("Hint="):
                current["hint"] = line[5:].strip().lstrip("|").strip()
            elif line.startswith("Icon="):
                current["icon"] = line[5:].strip()
            elif line.startswith("IconIndex="):
                current["icon_index"] = line[10:].strip()
            elif line.startswith("Group="):
                current["group"] = line[6:].strip()
            elif line.startswith("Ver="):
                current["version"] = line[4:].strip()
            elif line.startswith("URL="):
                current["url"] = line[4:].strip()
            elif line.startswith("Key="):
                current["key"] = line[4:].strip()
    return programs


def extract_surl(url):
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return None
    s = m.group(1)
    if s.startswith("1") and len(s) > 20:
        return s[1:]
    return s


def main():
    print("=" * 70)
    print("TERABOX через requests + cookies из Playwright")
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
        print(f"\nОткрываем {PROGRAMS_URL}")
        page.goto(PROGRAMS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(6000)

        tokens, cookie_header = get_tokens_and_cookies(context, page)
        print(f"Токены: jsToken={tokens['jsToken'][:30]}..., "
              f"bdstoken={tokens['bdstoken'][:20]}..., "
              f"pcftoken={tokens['pcftoken'][:20]}..., uk={tokens['uk']}")
        print(f"Cookie: {cookie_header[:200]}")

        # Referer должен быть с того же домена, куда мы шлём запрос.
        # Наш запрос идёт на www.terabox.app. Берём текущий URL страницы,
        # но если он на 1024tera.com — подменим на эквивалент terabox.app
        referer = page.url
        if "1024tera.com" in referer:
            referer = referer.replace("www.1024tera.com", "www.terabox.app")
        print(f"Referer: {referer}")

        surl = extract_surl(PROGRAMS_URL)
        print(f"surl: {surl}")

        session = requests.Session()

        # ─── ШАГ 1: корень ссылки ───
        print(f"\n{'─' * 70}\nШАГ 1: Корень ссылки\n{'─' * 70}")
        data = share_list(session, tokens, cookie_header, surl, referer)
        print(f"errno: {data.get('errno')}  errmsg: {data.get('errmsg', '')}")
        items = data.get("list") or []
        print(f"Элементов: {len(items)}")
        for it in items:
            print(f"  {it.get('server_filename')}  "
                  f"isdir={it.get('isdir')}  path={it.get('path')}")

        # ─── ШАГ 2: содержимое папки Программы ───
        prog_dir = None
        for it in items:
            if it.get("server_filename") == "Программы":
                prog_dir = it.get("path")
                break

        if not prog_dir:
            print("✗ Папка 'Программы' не найдена")
            browser.close()
            return
        print(f"\nНайдена папка: {prog_dir}")

        print(f"\n{'─' * 70}\nШАГ 2: Содержимое папки Программы\n{'─' * 70}")
        data2 = share_list(session, tokens, cookie_header, surl, referer,
                           dir_path=prog_dir)
        print(f"errno: {data2.get('errno')}  errmsg: {data2.get('errmsg', '')}")
        items2 = data2.get("list") or []
        print(f"Элементов: {len(items2)}")

        programs_subdirs = []
        desc_file = None
        dll_file = None
        for it in items2:
            name = it.get("server_filename")
            is_dir = str(it.get("isdir")) == "1"
            has_dlink = "✓" if it.get("dlink") else "✗"
            kind = "DIR " if is_dir else "FILE"
            print(f"  [{kind}] {name:<30} {it.get('size', 0):>12} b  dlink:{has_dlink}")
            if name == "1_Software.txt":
                desc_file = it
            elif name == "belico.dll":
                dll_file = it
            elif is_dir:
                programs_subdirs.append(it)

        # ─── ШАГ 3: скачиваем 1_Software.txt ───
        print(f"\n{'─' * 70}\nШАГ 3: 1_Software.txt\n{'─' * 70}")
        programs_map = {}
        if desc_file and desc_file.get("dlink"):
            save = download_file(session, desc_file["dlink"], "/tmp/1_Software.txt",
                                 referer, cookie_header)
            if save:
                programs_map = parse_software_txt(save)
                print(f"  ✓ Программ в файле: {len(programs_map)}")
                for i, (key, val) in enumerate(list(programs_map.items())[:12]):
                    print(f"    [{i}] Name={val['name']}")
                    print(f"         Group={val['group']}  IconIndex={val['icon_index']}")
                    print(f"         Hint={(val.get('hint') or '')[:90]}...")
                if len(programs_map) > 12:
                    print(f"    ... и ещё {len(programs_map) - 12}")
        else:
            print("  ✗ Нет 1_Software.txt")

        # ─── ШАГ 4: скачиваем belico.dll ───
        print(f"\n{'─' * 70}\nШАГ 4: belico.dll\n{'─' * 70}")
        if dll_file and dll_file.get("dlink"):
            print(f"  Размер: {dll_file.get('size')} байт")
            download_file(session, dll_file["dlink"], "/tmp/belico.dll",
                          referer, cookie_header)
        else:
            print("  ✗ Нет belico.dll")

        # ─── ШАГ 5: содержимое подпапок ───
        print(f"\n{'─' * 70}\nШАГ 5: Содержимое подпапок\n{'─' * 70}")
        for i, sub in enumerate(programs_subdirs):
            sub_dir = sub.get("path")
            sub_name = sub.get("server_filename")
            print(f"\n[{i}] Папка: {sub_name}  dir={sub_dir}")
            data3 = share_list(session, tokens, cookie_header, surl, referer,
                               dir_path=sub_dir)
            errno = data3.get("errno")
            files = data3.get("list") or []
            print(f"    errno: {errno}, файлов: {len(files)}")
            for j, it in enumerate(files[:15]):
                if str(it.get("isdir")) == "1":
                    continue
                fname = it.get("server_filename")
                has_dlink = "✓" if it.get("dlink") else "✗"
                print(f"      [{j}] {fname:<40} {it.get('size', 0):>12} b  dlink:{has_dlink}")

            if programs_map:
                print(f"    Сопоставление с 1_Software.txt:")
                for it in files[:15]:
                    if str(it.get("isdir")) == "1":
                        continue
                    fname = it.get("server_filename") or ""
                    base = re.sub(r"\.(exe|msi|zip|rar|7z)$", "", fname, flags=re.IGNORECASE)
                    base_clean = re.sub(r"[\-_.](x86|x64|win|setup|installer|portable)$",
                                        "", base, flags=re.IGNORECASE)
                    base_lower = base_clean.lower()

                    found = None
                    if base_lower in programs_map:
                        found = programs_map[base_lower]
                    else:
                        for key, val in programs_map.items():
                            if base_lower and (base_lower in key or key in base_lower):
                                found = val
                                break

                    if found:
                        print(f"      ✓ {fname} → Name={found['name']}")
                        print(f"        Hint: {(found.get('hint') or '')[:100]}...")
                    else:
                        print(f"      ✗ {fname} → не найдено")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
