#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Диагностика содержимого папки «Программы» в TeraBox:
- Список всех файлов и подпапок
- Скачивание и вывод первых 5000 символов 1_Software.txt
- Извлечение иконок из belico.dll
"""

import os
import sys
import json
import time
import base64
import subprocess
import traceback

from playwright.sync_api import sync_playwright

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

PROGRAMS_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"
COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com",
]

# JS-функция для получения списка через fetch
FETCH_LIST_JS = """
async ({surl, dirPath}) => {
    try {
        const jsToken = window.jsToken || '';
        const templateData = window.templateData || {};
        const bdstoken = templateData.bdstoken || '';
        const pcftoken = templateData.pcftoken || '';
        const uk = templateData.uk || '';

        const params = new URLSearchParams({
            clientfrom: 'h5', psign: '0',
            pcftoken: pcftoken,
            clienttype: '0', channel: 'dubox',
            page: '1', num: '1000', web: '1',
            scene: '',
            shorturl: surl,
            by: 'time', order: 'desc',
            app_id: '250528',
            jsToken: jsToken,
        });
        if (dirPath) params.set('dir', dirPath);
        if (bdstoken) params.set('bdstoken', bdstoken);
        if (uk) params.set('uk', uk);

        const apiUrl = 'https://www.terabox.app/share/list?' + params.toString();
        const resp = await fetch(apiUrl, {
            method: 'GET',
            credentials: 'include',
            headers: { 'Accept': 'application/json, text/plain, */*' },
        });
        const json = await resp.json();
        return {ok: true, data: json};
    } catch (e) {
        return {ok: false, error: String(e)};
    }
}
"""

FETCH_DOWNLOAD_JS = """
async ({dlink}) => {
    try {
        const resp = await fetch(dlink, {
            method: 'GET',
            credentials: 'include',
        });
        if (!resp.ok) return {ok: false, status: resp.status};
        const blob = await resp.blob();
        const arrayBuffer = await blob.arrayBuffer();
        const bytes = new Uint8Array(arrayBuffer);
        // Передаём как base64
        let binary = '';
        const chunkSize = 8192;
        for (let i = 0; i < bytes.length; i += chunkSize) {
            binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
        }
        return {ok: true, base64: btoa(binary), size: bytes.length};
    } catch (e) {
        return {ok: false, error: String(e)};
    }
}
"""


def fetch_list(page, surl, dir_path=None):
    return page.evaluate(FETCH_LIST_JS, {"surl": surl, "dirPath": dir_path})


def fetch_download(page, dlink):
    """Возвращает bytes из dlink."""
    res = page.evaluate(FETCH_DOWNLOAD_JS, {"dlink": dlink})
    if not res.get("ok"):
        return None, res
    import base64 as b64
    data = b64.b64decode(res["base64"])
    return data, {"size": res["size"]}


def extract_surl(url):
    import re
    m = re.search(r'/s/([A-Za-z0-9_\-]+)', url)
    if not m:
        return None
    s = m.group(1)
    if s.startswith("1") and len(s) > 20:
        return s[1:]
    return s


def parse_software_txt(content_str):
    """Парсит txt, возвращает список блоков {Name, Hint, GUID, Group, Ver, ...}."""
    blocks = []
    current = {}
    for line in content_str.split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("Group="):
            if current:
                blocks.append(current)
            current = {"Group": line[6:]}
        elif "=" in line:
            key, _, val = line.partition("=")
            current[key.strip()] = val.strip()
    if current:
        blocks.append(current)
    return blocks


def main():
    print("=" * 70)
    print("ДИАГНОСТИКА ПАПКИ «Программы»")
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
        page.goto(PROGRAMS_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        print(f"Финальный URL: {page.url}")

        surl = extract_surl(PROGRAMS_URL)
        print(f"surl: {surl}")

        # Получаем содержимое «Программы» через dir=/Для сайта/Программы
        res = fetch_list(page, surl, "/Для сайта/Программы")
        if not res.get("ok"):
            print(f"✗ Ошибка: {res.get('error')}")
            browser.close()
            return

        data = res["data"]
        print(f"errno: {data.get('errno')}")
        flist = data.get("list") or []
        print(f"Элементов: {len(flist)}\n")

        # Собираем нужные файлы
        desc_dlink = None
        dll_dlink = None
        folders = []
        for item in flist:
            name = item.get("server_filename") or ""
            isdir = str(item.get("isdir") or 0) == "1"
            if isdir:
                folders.append(item)
            elif name == "1_Software.txt":
                desc_dlink = item.get("dlink")
            elif name == "belico.dll":
                dll_dlink = item.get("dlink")

        print(f"📁 Подпапок: {len(folders)}")
        for i, f in enumerate(folders[:50]):
            print(f"  [{i}] {f.get('server_filename')}  fs_id={f.get('fs_id')}")
        if len(folders) > 50:
            print(f"  ... и ещё {len(folders) - 50}")

        # Скачиваем 1_Software.txt
        if desc_dlink:
            print("\n" + "─" * 70)
            print("Скачивание 1_Software.txt")
            print("─" * 70)
            txt_data, info = fetch_download(page, desc_dlink)
            if txt_data:
                print(f"  ✓ Получено {len(txt_data)} байт")
                # Декодируем
                try:
                    content = txt_data.decode("utf-8", errors="replace")
                except Exception:
                    content = txt_data.decode("cp1251", errors="replace")
                print("\n  Первые 5000 символов:")
                print("─" * 70)
                print(content[:5000])
                print("─" * 70)

                blocks = parse_software_txt(content)
                print(f"\n  Всего блоков (программ): {len(blocks)}")
                for i, b in enumerate(blocks[:10]):
                    print(f"\n  Блок #{i}:")
                    for k, v in b.items():
                        if len(str(v)) > 200:
                            v = str(v)[:200] + "..."
                        print(f"    {k}={v}")
                if len(blocks) > 10:
                    print(f"\n  ... и ещё {len(blocks) - 10} блоков")
            else:
                print(f"  ✗ Ошибка: {info}")

        # Скачиваем belico.dll (только если он не очень большой)
        if dll_dlink:
            print("\n" + "─" * 70)
            print("Скачивание belico.dll")
            print("─" * 70)
            # Найдём его размер
            dll_info = next((i for i in flist if i.get("server_filename") == "belico.dll"), None)
            if dll_info:
                size = dll_info.get("size") or 0
                print(f"  Размер: {size} байт ({size // 1024 // 1024} МБ)")

            dll_data, info = fetch_download(page, dll_dlink)
            if dll_data:
                print(f"  ✓ Получено {len(dll_data)} байт")
                with open("/tmp/belico.dll", "wb") as f:
                    f.write(dll_data)
                print("  Сохранён в /tmp/belico.dll")

                # Извлекаем иконки через icotool (icoutils)
                try:
                    # Устанавливаем icoutils если нет
                    subprocess.run(["which", "icotool"], check=True, capture_output=True)
                except Exception:
                    print("  Устанавливаю icoutils...")
                    subprocess.run(["sudo", "apt-get", "update", "-qq"], capture_output=True)
                    subprocess.run(["sudo", "apt-get", "install", "-y", "-qq", "icoutils"], capture_output=True)

                try:
                    result = subprocess.run(
                        ["icotool", "-l", "/tmp/belico.dll"],
                        capture_output=True, text=True, timeout=30,
                    )
                    print(f"\n  ─── Список иконок в belico.dll ───")
                    print(result.stdout[:3000])
                    if result.stderr:
                        print(f"  stderr: {result.stderr[:500]}")
                except Exception as e:
                    print(f"  ✗ Ошибка icotool: {e}")
            else:
                print(f"  ✗ Ошибка: {info}")

        browser.close()

    print("\n" + "=" * 70)
    print("ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 70)


if __name__ == "__main__":
    main()
