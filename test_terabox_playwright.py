#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Финальный тест: получаем содержимое папки "Программы" через /share/list
с параметром dir. Находим 1_Software.txt и belico.dll.
"""

import os
import sys
import json
import time
import traceback

from playwright.sync_api import sync_playwright

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

# Ссылка на папку "Программы"
PROGRAMS_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"

COOKIE_DOMAINS = [
    ".terabox.app",
    ".1024tera.com",
    ".1024terabox.com",
    ".terabox.com",
    ".4funbox.com",
]


def fetch_share_list(page, surl, dir_path=None, fs_id=None):
    """
    Выполняет fetch к /share/list через Playwright.
    dir_path — путь внутри ссылки (например, "/Программы").
    fs_id    — ID папки (альтернатива dir_path).
    """
    js_code = """
    async ({surl, dirPath, fsId}) => {
        try {
            const jsToken = window.jsToken || '';
            const templateData = window.templateData || {};
            const bdstoken = templateData.bdstoken || '';
            const pcftoken = templateData.pcftoken || '';
            const uk = templateData.uk || '';

            if (!jsToken) return {error: 'jsToken missing'};

            const params = new URLSearchParams({
                shorturl: surl,
                root: '1',
                web: '1',
                app_id: '250528',
                jsToken: jsToken,
                page: '1',
                num: '1000',
            });
            if (bdstoken) params.set('bdstoken', bdstoken);
            if (pcftoken) params.set('pcftoken', pcftoken);
            if (uk) params.set('uk', uk);
            if (dirPath) params.set('dir', dirPath);
            if (fsId) params.set('fs_id', String(fsId));

            const apiUrl = 'https://www.terabox.app/share/list?' + params.toString();

            const resp = await fetch(apiUrl, {
                method: 'GET',
                credentials: 'include',
                headers: {
                    'Accept': 'application/json, text/plain, */*',
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });
            const text = await resp.text();
            let json = null;
            try { json = JSON.parse(text); } catch (e) {
                return {error: 'not json', status: resp.status, text: text.slice(0, 300)};
            }
            return {status: resp.status, data: json};
        } catch (e) {
            return {error: 'Exception: ' + String(e)};
        }
    }
    """
    return page.evaluate(js_code, {
        "surl": surl,
        "dirPath": dir_path,
        "fsId": fs_id,
    })


def extract_surl(url):
    import re
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return None
    s = m.group(1)
    if s.startswith("1") and len(s) > 20:
        return s[1:]
    return s


def print_list(data, indent="  "):
    """Печатает список элементов."""
    errno = data.get("errno")
    errmsg = data.get("errmsg", "")
    print(f"{indent}errno: {errno} {('(' + errmsg + ')') if errmsg else ''}")

    if errno != 0:
        print(f"{indent}Ответ: {json.dumps(data, ensure_ascii=False)[:400]}")
        return []

    flist = data.get("list") or []
    print(f"{indent}📂 Элементов: {len(flist)}")
    for i, item in enumerate(flist[:60]):
        name = item.get("server_filename") or "?"
        isdir = item.get("isdir") or 0
        size = item.get("size") or 0
        fs_id = item.get("fs_id") or 0
        path = item.get("path") or ""
        kind = "DIR " if str(isdir) == "1" else "FILE"
        size_str = f"{size} b" if size else "—"
        print(f"{indent}  [{i:>2}] [{kind}] {name:<40} {size_str:>12}  fs_id={fs_id}  path={path}")
    return flist


def main():
    print("=" * 70)
    print("ТЕСТ: содержимое папки «Программы» и её подпапок")
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

        # 1. Открываем страницу "Программы"
        print(f"\nОткрываем: {PROGRAMS_URL}")
        page.goto(PROGRAMS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        print(f"Финальный URL: {page.url}")

        surl = extract_surl(PROGRAMS_URL)
        print(f"surl: {surl}")

        # 2. Запрос к корню ссылки (без dir)
        print("\n" + "─" * 70)
        print("ШАГ 1: Запрос без dir (корень ссылки)")
        print("─" * 70)
        r1 = fetch_share_list(page, surl)
        if "error" in r1:
            print(f"  ✗ Ошибка: {r1['error']}")
            browser.close()
            return
        list1 = print_list(r1.get("data", {}))

        # Запоминаем path и fs_id папки "Программы"
        program_folder_path = None
        program_folder_fs_id = None
        if list1:
            for item in list1:
                if item.get("server_filename") == "Программы":
                    program_folder_path = item.get("path")
                    program_folder_fs_id = item.get("fs_id")
                    break

        print(f"\nНайдена папка Программы:")
        print(f"  path:  {program_folder_path}")
        print(f"  fs_id: {program_folder_fs_id}")

        # 3. Пробуем разные варианты dir
        print("\n" + "─" * 70)
        print("ШАГ 2: Пробуем получить содержимое папки Программы")
        print("─" * 70)

        variants = [
            ("dir=/Программы",            {"dir_path": "/Программы"}),
            ("dir=/Для сайта/Программы",  {"dir_path": "/Для сайта/Программы"}),
            ("dir=Программы",             {"dir_path": "Программы"}),
            (f"dir=fs_id({program_folder_fs_id})", {"fs_id": program_folder_fs_id}),
            ("dir=/ (корень)",             {"dir_path": "/"}),
        ]

        working_variant = None
        working_data = None

        for name, kwargs in variants:
            print(f"\n  Пробуем: {name}")
            r = fetch_share_list(page, surl, **kwargs)
            if "error" in r:
                print(f"    ✗ {r['error']}")
                continue
            data = r.get("data", {})
            errno = data.get("errno")
            flist = data.get("list") or []
            if errno == 0 and len(flist) > 1:
                print(f"    ✅ РАБОТАЕТ! Элементов: {len(flist)}")
                print_list(data, indent="      ")
                working_variant = name
                working_data = data
                break
            elif errno == 0:
                print(f"    ⚠ errno=0, но элементов: {len(flist)} (похоже на корень ссылки)")
            else:
                errmsg = data.get("errmsg", "")
                print(f"    ⚠ errno={errno} ({errmsg})")

        if not working_variant:
            print("\n❌ Ни один вариант не дал содержимое папки.")
            print("Нужна дальнейшая диагностика.")
            browser.close()
            return

        print(f"\n✅ РАБОЧИЙ ВАРИАНТ: {working_variant}")

        # 4. Ищем 1_Software.txt и belico.dll
        print("\n" + "─" * 70)
        print("ШАГ 3: Анализ содержимого папки Программы")
        print("─" * 70)

        flist = working_data.get("list") or []
        program_folders = []  # подпапки
        desc_file = None      # 1_Software.txt
        dll_file = None       # belico.dll

        for item in flist:
            name = item.get("server_filename") or ""
            isdir = str(item.get("isdir") or 0) == "1"
            if isdir:
                program_folders.append(item)
            elif name == "1_Software.txt":
                desc_file = item
            elif name == "belico.dll":
                dll_file = item

        print(f"\n📁 Подпапок (программ): {len(program_folders)}")
        for i, p in enumerate(program_folders[:20]):
            print(f"  [{i}] {p.get('server_filename')}  (fs_id={p.get('fs_id')})")

        print(f"\n📄 1_Software.txt:  {'✓ найден' if desc_file else '✗ НЕ найден'}")
        if desc_file:
            print(f"  fs_id={desc_file.get('fs_id')}, size={desc_file.get('size')} b")

        print(f"\n🎨 belico.dll:     {'✓ найден' if dll_file else '✗ НЕ найден'}")
        if dll_file:
            print(f"  fs_id={dll_file.get('fs_id')}, size={dll_file.get('size')} b")

        print(f"\nВсего элементов: {len(flist)}")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
