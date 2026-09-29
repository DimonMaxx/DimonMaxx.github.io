#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скачиваем 1_Software.txt и belico.dll через context.request.get(dlink).
dlink уже приходит в ответе /share/list — просто используем его.
"""

import os
import re
import sys
import json
import time
import traceback

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


def fetch_share_list(page, surl, dir_path=None):
    """Получает содержимое папки через /share/list с параметром dir."""
    js_code = """
    async ({surl, dirPath}) => {
        const jsToken = window.jsToken || '';
        const td = window.templateData || {};
        const params = new URLSearchParams({
            clientfrom: 'h5', psign: '0',
            pcftoken: td.pcftoken || '',
            clienttype: '0', channel: 'dubox',
            page: '1', num: '1000', web: '1', scene: '',
            shorturl: surl,
            by: 'time', order: 'desc',
            app_id: '250528',
            jsToken: jsToken,
        });
        if (td.bdstoken) params.set('bdstoken', td.bdstoken);
        if (dirPath) params.set('dir', dirPath);
        const apiUrl = 'https://www.terabox.app/share/list?' + params.toString();
        const resp = await fetch(apiUrl, {credentials: 'include'});
        return await resp.json();
    }
    """
    return page.evaluate(js_code, {"surl": surl, "dirPath": dir_path})


def extract_surl(url):
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return None
    s = m.group(1)
    if s.startswith("1") and len(s) > 20:
        return s[1:]
    return s


def download_via_context(context, dlink, save_path):
    """Скачивает файл через Playwright HTTP-клиент (без CORS)."""
    print(f"  GET {dlink[:100]}...")
    t0 = time.time()
    try:
        resp = context.request.get(dlink, timeout=120000)
    except Exception as e:
        print(f"  ✗ Ошибка запроса: {e}")
        return None
    print(f"  HTTP {resp.status} за {round(time.time() - t0, 2)} сек")
    if resp.status != 200:
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    print(f"  ✓ Сохранено: {save_path} ({len(body)} байт)")
    return save_path


def parse_software_txt(file_path):
    """Парсит 1_Software.txt: возвращает список {name, hint}."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except Exception as e:
        return [], f"Ошибка чтения: {e}"

    blocks = []
    current = {}
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("Name="):
            if current.get("name"):
                blocks.append(current)
            current = {"name": line[5:].strip()}
        elif line.startswith("Hint="):
            current["hint"] = line[5:].strip().lstrip("|").strip()
        elif line.startswith("Group="):
            if current.get("name"):
                blocks.append(current)
                current = {}
    if current.get("name"):
        blocks.append(current)

    return blocks, None


def main():
    print("=" * 70)
    print("СКАЧИВАНИЕ ФАЙЛОВ ЧЕРЕЗ context.request.get(dlink)")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
            locale="ru-RU",
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

        surl = extract_surl(PROGRAMS_URL)
        print(f"surl: {surl}")

        # Содержимое корня ссылки
        data = fetch_share_list(page, surl)
        print(f"errno: {data.get('errno')}")

        # Папка "Программы"
        program_folder = None
        for item in data.get("list", []):
            if item.get("server_filename") == "Программы":
                program_folder = item
                break

        if not program_folder:
            print("✗ Папка Программы не найдена")
            browser.close()
            return

        prog_dir = program_folder.get("path")
        print(f"Папка Программы: {prog_dir}")

        # Содержимое папки "Программы"
        data2 = fetch_share_list(page, surl, dir_path=prog_dir)
        if data2.get("errno") != 0:
            print(f"✗ errno: {data2.get('errno')}")
            browser.close()
            return

        flist = data2.get("list", [])
        print(f"\n📂 Элементов в папке: {len(flist)}")
        for i, it in enumerate(flist):
            kind = "DIR " if str(it.get("isdir")) == "1" else "FILE"
            has_dlink = "✓" if it.get("dlink") else "✗"
            print(f"  [{i}] [{kind}] {it.get('server_filename'):<30} "
                  f"{it.get('size', 0):>12} b  dlink:{has_dlink}")

        # Ищем нужные файлы и подпапки
        desc_file = None
        dll_file = None
        subfolders = []
        for item in flist:
            name = item.get("server_filename")
            if name == "1_Software.txt":
                desc_file = item
            elif name == "belico.dll":
                dll_file = item
            elif str(item.get("isdir")) == "1":
                subfolders.append(item)

        # Скачиваем 1_Software.txt
        if desc_file:
            print(f"\n{'─' * 70}")
            print(f"1_Software.txt")
            print(f"{'─' * 70}")
            if desc_file.get("dlink"):
                save = download_via_context(context, desc_file["dlink"], "/tmp/1_Software.txt")
                if save:
                    blocks, err = parse_software_txt(save)
                    if err:
                        print(f"  ✗ {err}")
                    else:
                        print(f"  ✓ Блоков: {len(blocks)}")
                        for i, b in enumerate(blocks[:15]):
                            print(f"  [{i}] Name={b.get('name')}")
                            print(f"       Hint={(b.get('hint','') or '')[:80]}...")
                        if len(blocks) > 15:
                            print(f"  ... и ещё {len(blocks) - 15}")
            else:
                print("  ✗ Нет dlink в ответе")

        # Скачиваем belico.dll
        if dll_file:
            print(f"\n{'─' * 70}")
            print(f"belico.dll ({dll_file.get('size')} байт)")
            print(f"{'─' * 70}")
            if dll_file.get("dlink"):
                download_via_context(context, dll_file["dlink"], "/tmp/belico.dll")
            else:
                print("  ✗ Нет dlink")

        # Подпапки = программы
        print(f"\n{'─' * 70}")
        print(f"ПРОГРАММЫ (подпапки в корне): {len(subfolders)}")
        print(f"{'─' * 70}")
        for i, sf in enumerate(subfolders):
            print(f"  [{i}] {sf.get('server_filename')}")

        # Смотрим содержимое первых 2 программ
        print(f"\n{'─' * 70}")
        print(f"СОДЕРЖИМОЕ ПРОГРАММ (первые 2)")
        print(f"{'─' * 70}")
        for i, sf in enumerate(subfolders[:2]):
            sub_dir = sf.get("path")
            print(f"\n[{i}] {sf.get('server_filename')}  dir={sub_dir}")
            data3 = fetch_share_list(page, surl, dir_path=sub_dir)
            if data3.get("errno") != 0:
                print(f"    ✗ errno: {data3.get('errno')}")
                continue
            sub_list = data3.get("list", [])
            print(f"    Элементов: {len(sub_list)}")
            for j, it in enumerate(sub_list[:15]):
                kind = "DIR " if str(it.get("isdir")) == "1" else "FILE"
                print(f"      [{j}] [{kind}] {it.get('server_filename')}  ({it.get('size', 0)} b)")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
