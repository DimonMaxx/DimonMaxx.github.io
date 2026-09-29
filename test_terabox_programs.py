#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TeraBox: рабочий обход через page.evaluate + fetch на www.1024tera.com.
Скачивает 1_Software.txt и belico.dll, обходит подпапки, сопоставляет
файлы с описаниями.
"""

import os
import re
import sys
import json
import time
import random

from playwright.sync_api import sync_playwright

COOKIE = os.environ.get("TERABOX_COOKIE", "")
if not COOKIE:
    print("✗ TERABOX_COOKIE не задан")
    sys.exit(1)

START_URL = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"

COOKIE_DOMAINS = [
    ".terabox.app", ".1024tera.com", ".1024terabox.com",
    ".terabox.com", ".4funbox.com", ".d.terabox.app",
]


def share_list(page, surl, dir_path=None):
    """
    Делает fetch через page.evaluate к /share/list на текущем домене.
    Возвращает распарсенный JSON (без обрезки).
    """
    js_code = """
    async ({surl, dirPath}) => {
        try {
            const jsToken = window.jsToken || '';
            const td = window.templateData || {};
            if (!jsToken) return {error: 'no jsToken'};

            const params = new URLSearchParams({
                clientfrom: 'h5',
                psign: '0',
                pcftoken: td.pcftoken || '',
                clienttype: '0',
                channel: 'dubox',
                page: '1',
                num: '100',
                web: '1',
                scene: '',
                shorturl: surl,
                by: 'time',
                order: 'desc',
                app_id: '250528',
                jsToken: jsToken,
                'dp-logid': String(Math.floor(Math.random() * 1e16)),
            });
            if (td.bdstoken) params.set('bdstoken', td.bdstoken);
            if (dirPath) params.set('dir', dirPath);

            const url = '/share/list?' + params.toString();
            const resp = await fetch(url, {
                method: 'GET',
                credentials: 'include',
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                    'Accept': 'application/json, text/plain, */*',
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
            });
            const text = await resp.text();
            try {
                return {status: resp.status, data: JSON.parse(text)};
            } catch (e) {
                return {status: resp.status, error: 'not json: ' + String(e), text: text.slice(0, 200)};
            }
        } catch (e) {
            return {error: String(e)};
        }
    }
    """
    return page.evaluate(js_code, {"surl": surl, "dirPath": dir_path})


def download_file(context, dlink, save_path):
    """Скачивает файл через context.request (вне CORS, dlink подписан)."""
    print(f"  GET {dlink[:110]}...")
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


def print_list(items, indent="    "):
    for i, it in enumerate(items):
        name = it.get("server_filename")
        is_dir = str(it.get("isdir")) == "1"
        has_dlink = "✓" if it.get("dlink") else "✗"
        kind = "DIR " if is_dir else "FILE"
        print(f"{indent}[{i:>2}] [{kind}] {name:<35} "
              f"{it.get('size', 0):>12} b  dlink:{has_dlink}")


def main():
    print("=" * 70)
    print("ФИНАЛЬНЫЙ ТЕСТ: обход TeraBox и сопоставление с 1_Software.txt")
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

        # ⚠️ Открываем через 1024terabox.com — Vue редиректит на 1024tera.com
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(7000)
        final_url = page.url
        print(f"Финальный URL: {final_url}")

        state = page.evaluate("""() => ({
            hasJsToken: !!window.jsToken,
            hasBdstoken: !!(window.templateData && window.templateData.bdstoken),
            username: (document.querySelector('.card-username') || {}).textContent || null,
        })""")
        print(f"Состояние: {state}")

        surl = extract_surl(START_URL)
        print(f"surl: {surl}")

        # ─── ШАГ 1: корень ссылки ───
        print(f"\n{'─' * 70}\nШАГ 1: Корень ссылки\n{'─' * 70}")
        r1 = share_list(page, surl)
        if "error" in r1:
            print(f"✗ Ошибка: {r1}")
            browser.close()
            return
        data = r1["data"]
        print(f"errno: {data.get('errno')}, errmsg: {data.get('errmsg', '')}")
        items = data.get("list") or []
        print(f"Элементов: {len(items)}")
        print_list(items)

        # Ищем папку Программы
        prog_dir = None
        for it in items:
            if it.get("server_filename") == "Программы":
                prog_dir = it.get("path")
                break
        if not prog_dir:
            print("✗ Папка Программы не найдена")
            browser.close()
            return
        print(f"\nПапка: {prog_dir}")

        # ─── ШАГ 2: содержимое папки ───
        print(f"\n{'─' * 70}\nШАГ 2: Содержимое папки Программы\n{'─' * 70}")
        r2 = share_list(page, surl, dir_path=prog_dir)
        if "error" in r2:
            print(f"✗ Ошибка: {r2}")
            browser.close()
            return
        data2 = r2["data"]
        print(f"errno: {data2.get('errno')}, errmsg: {data2.get('errmsg', '')}")
        items2 = data2.get("list") or []
        print(f"Элементов: {len(items2)}")
        print_list(items2)

        subdirs = []
        desc_file = None
        dll_file = None
        for it in items2:
            name = it.get("server_filename")
            if name == "1_Software.txt":
                desc_file = it
            elif name == "belico.dll":
                dll_file = it
            elif str(it.get("isdir")) == "1":
                subdirs.append(it)

        # ─── ШАГ 3: скачиваем 1_Software.txt ───
        print(f"\n{'─' * 70}\nШАГ 3: 1_Software.txt\n{'─' * 70}")
        programs_map = {}
        if desc_file and desc_file.get("dlink"):
            save = download_file(context, desc_file["dlink"], "/tmp/1_Software.txt")
            if save:
                programs_map = parse_software_txt(save)
                print(f"  ✓ Программ в файле: {len(programs_map)}")
                for i, (key, val) in enumerate(list(programs_map.items())[:15]):
                    print(f"    [{i}] Name={val['name']}")
                    print(f"         Group={val['group']}  Ver={val['version']}")
                    print(f"         Hint={(val.get('hint') or '')[:100]}...")
                if len(programs_map) > 15:
                    print(f"    ... и ещё {len(programs_map) - 15}")

        # ─── ШАГ 4: скачиваем belico.dll ───
        print(f"\n{'─' * 70}\nШАГ 4: belico.dll\n{'─' * 70}")
        if dll_file and dll_file.get("dlink"):
            print(f"  Размер: {dll_file.get('size')} байт")
            download_file(context, dll_file["dlink"], "/tmp/belico.dll")

        # ─── ШАГ 5: обход подпапок ───
        print(f"\n{'─' * 70}\nШАГ 5: Обход подпапок\n{'─' * 70}")
        for i, sub in enumerate(subdirs):
            sub_dir = sub.get("path")
            sub_name = sub.get("server_filename")
            print(f"\n[{i}] Папка: {sub_name}  dir={sub_dir}")
            r3 = share_list(page, surl, dir_path=sub_dir)
            if "error" in r3:
                print(f"    ✗ {r3}")
                continue
            data3 = r3["data"]
            files = data3.get("list") or []
            print(f"    errno: {data3.get('errno')}, файлов: {len(files)}")
            for j, it in enumerate(files):
                if str(it.get("isdir")) == "1":
                    continue
                fname = it.get("server_filename")
                has_dlink = "✓" if it.get("dlink") else "✗"
                print(f"      [{j:>2}] {fname:<40} {it.get('size', 0):>12} b  dlink:{has_dlink}")

            # ─── Сопоставление ───
            if programs_map:
                print(f"\n    Сопоставление с 1_Software.txt:")
                matched = 0
                for it in files:
                    if str(it.get("isdir")) == "1":
                        continue
                    fname = it.get("server_filename") or ""
                    # Убираем расширение
                    base = re.sub(r"\.(exe|msi|zip|rar|7z|txt|dll)$", "", fname, flags=re.IGNORECASE)
                    # Убираем суффиксы -x86, -x64, .win, _setup, _portable
                    base_clean = re.sub(r"[\-_.](x86|x64|win|setup|installer|portable|install)$",
                                        "", base, flags=re.IGNORECASE)
                    base_lower = base_clean.lower()

                    # Прямое совпадение
                    found = None
                    if base_lower in programs_map:
                        found = programs_map[base_lower]
                    else:
                        # Частичное
                        for key, val in programs_map.items():
                            # Пробуем разные варианты
                            if base_lower == key:
                                found = val
                                break
                            # Убираем точки и пробелы
                            key_clean = re.sub(r"[\s\.\-_]", "", key)
                            base_cleanest = re.sub(r"[\s\.\-_]", "", base_lower)
                            if key_clean == base_cleanest:
                                found = val
                                break
                            # Вхождение подстроки (только если разница >3 символов)
                            if abs(len(key_clean) - len(base_cleanest)) < 5:
                                if base_cleanest and (base_cleanest in key_clean or key_clean in base_cleanest):
                                    found = val
                                    break

                    if found:
                        matched += 1
                        print(f"      ✓ {fname}")
                        print(f"        → Name: {found['name']}")
                        print(f"        → Hint: {(found.get('hint') or '')[:120]}...")
                    else:
                        print(f"      ✗ {fname} → не найдено")
                print(f"\n    Итого совпадений: {matched}/{len([it for it in files if str(it.get('isdir')) != '1'])}")

        browser.close()

    print("\n" + "=" * 70)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 70)


if __name__ == "__main__":
    main()
