#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тера: используем context.request.get вместо page.evaluate/fetch.
Обходим CORS, получаем список файлов и dlink для скачивания.
"""

import os
import re
import sys
import json
import time
import traceback
from urllib.parse import quote

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


def get_tokens(page):
    """Извлекает токены из window страницы."""
    return page.evaluate("""() => ({
        jsToken: window.jsToken || '',
        bdstoken: (window.templateData && window.templateData.bdstoken) || '',
        pcftoken: (window.templateData && window.templateData.pcftoken) || '',
        uk: (window.templateData && window.templateData.uk) || '',
    })""")


def share_list(context, tokens, surl, dir_path=None):
    """Запрос к /share/list через context.request.get (без CORS)."""
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
    }
    if tokens["bdstoken"]:
        params["bdstoken"] = tokens["bdstoken"]
    if dir_path:
        params["dir"] = dir_path

    qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
    url = f"https://www.terabox.app/share/list?{qs}"

    print(f"  GET {url[:140]}...")
    resp = context.request.get(url, timeout=60000)
    print(f"  HTTP {resp.status}")
    if resp.status != 200:
        return {"errno": -1, "errmsg": f"HTTP {resp.status}"}
    try:
        return resp.json()
    except Exception as e:
        return {"errno": -1, "errmsg": f"not json: {e}"}


def download_file(context, dlink, save_path):
    """Скачивает файл через context.request.get."""
    print(f"  GET {dlink[:100]}...")
    t0 = time.time()
    resp = context.request.get(dlink, timeout=180000)
    elapsed = round(time.time() - t0, 2)
    print(f"  HTTP {resp.status} за {elapsed} сек")
    if resp.status != 200:
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    print(f"  ✓ Сохранено: {save_path} ({len(body)} байт)")
    return save_path


def parse_software_txt(file_path):
    """Парсит 1_Software.txt: возвращает {name: {hint, ...}}."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    programs = {}
    current = None
    for line in content.split("\n"):
        line = line.rstrip("\r")
        if line.startswith("Name="):
            name = line[5:].strip()
            if name:
                current = {"name": name, "hint": "", "group": "", "version": ""}
                programs[name.lower()] = current
        elif current is not None:
            if line.startswith("Hint="):
                current["hint"] = line[5:].strip().lstrip("|").strip()
            elif line.startswith("Group="):
                current["group"] = line[6:].strip()
            elif line.startswith("Ver="):
                current["version"] = line[4:].strip()
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
    print("ТЕСТ TERABOX через context.request (без CORS)")
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
        page.wait_for_timeout(5000)

        tokens = get_tokens(page)
        print(f"Токены: jsToken={tokens['jsToken'][:30]}..., "
              f"bdstoken={tokens['bdstoken'][:20]}..., "
              f"pcftoken={tokens['pcftoken'][:20]}..., uk={tokens['uk']}")

        surl = extract_surl(PROGRAMS_URL)
        print(f"surl: {surl}")

        # ─── Корень ссылки ───
        print(f"\n{'─' * 70}\nШАГ 1: Корень ссылки\n{'─' * 70}")
        data = share_list(context, tokens, surl)
        print(f"errno: {data.get('errno')}, элементов: {len(data.get('list') or [])}")
        for it in (data.get("list") or []):
            print(f"  {it.get('server_filename')}  dir={it.get('isdir')}  path={it.get('path')}")

        # ─── Папка "Программы" ───
        prog_dir = None
        for it in (data.get("list") or []):
            if it.get("server_filename") == "Программы":
                prog_dir = it.get("path")
                break

        if not prog_dir:
            print("✗ Папка 'Программы' не найдена")
            browser.close()
            return
        print(f"\nНайдена папка: {prog_dir}")

        # ─── Содержимое "Программы" ───
        print(f"\n{'─' * 70}\nШАГ 2: Содержимое папки Программы\n{'─' * 70}")
        data2 = share_list(context, tokens, surl, dir_path=prog_dir)
        print(f"errno: {data2.get('errno')}, элементов: {len(data2.get('list') or [])}")

        programs_subdirs = []
        desc_file = None
        dll_file = None
        for it in (data2.get("list") or []):
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

        # ─── Скачиваем 1_Software.txt ───
        print(f"\n{'─' * 70}\nШАГ 3: 1_Software.txt\n{'─' * 70}")
        programs_map = {}
        if desc_file and desc_file.get("dlink"):
            save_path = download_file(context, desc_file["dlink"], "/tmp/1_Software.txt")
            if save_path:
                programs_map = parse_software_txt(save_path)
                print(f"  ✓ Программ в файле: {len(programs_map)}")
                for i, (key, val) in enumerate(list(programs_map.items())[:10]):
                    print(f"    [{i}] Name={val['name']}")
                    print(f"         Hint={(val.get('hint') or '')[:90]}...")
                if len(programs_map) > 10:
                    print(f"    ... и ещё {len(programs_map) - 10}")
        else:
            print("  ✗ Нет 1_Software.txt или dlink отсутствует")

        # ─── Скачиваем belico.dll ───
        print(f"\n{'─' * 70}\nШАГ 4: belico.dll\n{'─' * 70}")
        if dll_file and dll_file.get("dlink"):
            print(f"  Размер: {dll_file.get('size')} байт")
            download_file(context, dll_file["dlink"], "/tmp/belico.dll")
        else:
            print("  ✗ Нет belico.dll или dlink отсутствует")

        # ─── Содержимое первой программы ───
        print(f"\n{'─' * 70}\nШАГ 5: Содержимое подпапок-программ\n{'─' * 70}")
        for i, sub in enumerate(programs_subdirs[:3]):
            sub_dir = sub.get("path")
            sub_name = sub.get("server_filename")
            print(f"\n[{i}] {sub_name}  dir={sub_dir}")
            data3 = share_list(context, tokens, surl, dir_path=sub_dir)
            errno = data3.get("errno")
            items = data3.get("list") or []
            print(f"    errno: {errno}, элементов: {len(items)}")
            for j, it in enumerate(items[:10]):
                kind = "DIR " if str(it.get("isdir")) == "1" else "FILE"
                has_dlink = "✓" if it.get("dlink") else "✗"
                print(f"      [{j}] [{kind}] {it.get('server_filename'):<30} "
                      f"{it.get('size', 0):>12} b  dlink:{has_dlink}")

            # Сопоставление с 1_Software.txt
            if programs_map:
                key = sub_name.lower()
                if key in programs_map:
                    print(f"    ✓ Найдено в 1_Software.txt:")
                    print(f"      Hint: {programs_map[key].get('hint', '')[:120]}...")
                else:
                    # Пробуем частичное совпадение
                    matches = [k for k in programs_map if key in k or k in key]
                    if matches:
                        print(f"    ⚠ Частичные совпадения: {matches[:3]}")
                    else:
                        print(f"    ✗ Нет совпадения в 1_Software.txt")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
