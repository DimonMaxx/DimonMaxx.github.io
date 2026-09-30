#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест TeraBox v3:
- Полное сканирование корня шары и папки «Программы»
- Пагинация: если элементов >20, скроллим и собираем все
- Поиск ВСЕХ файлов *.txt (описания)
- Парсинг 2 форматов (old WPI и WPI prog[pn])
- Обход ВСЕХ подпапок, распределение по папкам
"""

import os
import re
import sys
import json
import time

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

# Любые *.txt-файлы считаем потенциальными описаниями
DESC_EXTS = (".txt",)


class Catcher:
    def __init__(self):
        self.responses = []  # список {"url", "data", "ts"}

    def attach(self, page):
        def on_response(resp):
            if "/share/list" in resp.url and "/static/" not in resp.url:
                try:
                    data = resp.json()
                    self.responses.append({
                        "url": resp.url,
                        "data": data,
                        "ts": time.time(),
                    })
                except Exception:
                    pass
        page.on("response", on_response)

    def count(self):
        return len(self.responses)

    def collect_since(self, prev_count):
        """Собирает все ответы, пришедшие после prev_count."""
        return self.responses[prev_count:]


# ============================================================
# УТИЛИТЫ КЛИКОВ
# ============================================================

def _click_folder_by_name(page, name):
    """
    Клик по папке с точным совпадением имени.
    Возвращает True/False.
    """
    # Ждём появления элементов
    try:
        page.wait_for_selector('.file-item-listmode', timeout=8000)
    except Exception:
        pass

    elements = page.query_selector_all('.file-item-listmode')
    print(f"    [click] Найдено элементов .file-item-listmode: {len(elements)}")

    for el in elements:
        try:
            name_el = el.query_selector('.file-item-name')
            txt = ""
            if name_el:
                txt = (name_el.inner_text() or "").strip()
            else:
                txt = (el.inner_text() or "").strip()

            if txt == name:
                el.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(200)
                el.dblclick(timeout=5000)
                return True
        except Exception as e:
            continue

    # Fallback: has-text
    try:
        loc = page.locator(f'.file-item-listmode:has-text("{name}")').first
        if loc.count() > 0:
            loc.scroll_into_view_if_needed(timeout=3000)
            page.wait_for_timeout(200)
            loc.dblclick(timeout=5000)
            return True
    except Exception:
        pass

    return False


# ============================================================
# СБОР ЭЛЕМЕНТОВ ПАПКИ С ПАГИНАЦИЕЙ
# ============================================================

def collect_folder_items(page, catcher, prev_count,
                          wait_ms=15000, scroll=True):
    """
    Ждёт первый /share/list ответ, потом (опционально) скроллит
    и собирает все элементы, объединяя по fs_id.
    Возвращает список уникальных элементов.
    """
    # Ждём первый ответ
    first = None
    elapsed = 0
    while elapsed < wait_ms:
        new = catcher.collect_since(prev_count)
        if new:
            first = new[0]
            break
        page.wait_for_timeout(200)
        elapsed += 200

    if not first:
        return []

    page.wait_for_timeout(500)

    # Собираем из всех полученных
    all_items = {}

    def add_items(resp):
        items = resp["data"].get("list") or []
        for it in items:
            fid = it.get("fs_id")
            if fid and fid not in all_items:
                all_items[fid] = it

    for resp in catcher.collect_since(prev_count):
        add_items(resp)

    print(f"    [collect] Первый ответ: {len(first['data'].get('list') or [])} элементов")

    # Скролл для догрузки
    if scroll:
        seen_count = catcher.count()
        for attempt in range(6):
            try:
                page.keyboard.press("End")
            except Exception:
                pass
            page.wait_for_timeout(1500)

            new_count = catcher.count()
            if new_count > seen_count:
                for resp in catcher.responses[seen_count:new_count]:
                    add_items(resp)
                print(f"    [collect] Догружено до {len(all_items)} элементов")
                seen_count = new_count
            else:
                # Ничего не пришло — можно прекратить
                pass

    print(f"    [collect] Итого собрано: {len(all_items)} элементов")
    return list(all_items.values())


# ============================================================
# СКАЧИВАНИЕ
# ============================================================

def download_file(context, dlink, save_path):
    print(f"    GET {dlink[:100]}...")
    resp = context.request.get(dlink, timeout=180000)
    print(f"    HTTP {resp.status}")
    if resp.status != 200:
        return None
    body = resp.body()
    with open(save_path, "wb") as f:
        f.write(body)
    print(f"    ✓ Сохранено: {save_path} ({len(body)} байт)")
    return save_path


# ============================================================
# ДЕКОДИРОВАНИЕ
# ============================================================

def decode_bytes(raw):
    if not raw:
        return ""
    if raw[:2] == b"\xff\xfe":
        return raw.decode("utf-16-le", errors="replace")
    if raw[:2] == b"\xfe\xff":
        return raw.decode("utf-16-be", errors="replace")
    if raw[:3] == b"\xef\xbb\xbf":
        return raw.decode("utf-8-sig", errors="replace")

    sample = raw[:400]
    if len(sample) >= 8:
        nulls_odd  = sum(1 for i in range(1, min(200, len(sample)), 2) if sample[i] == 0)
        nulls_even = sum(1 for i in range(0, min(200, len(sample)), 2) if sample[i] == 0)
        if nulls_odd > 40:
            return raw.decode("utf-16-le", errors="replace")
        if nulls_even > 40:
            return raw.decode("utf-16-be", errors="replace")

    markers = ("prog[pn]", "desc[pn]", "cmds[pn]", "[MInst]", "Name=", "Patch=")
    for enc in ("cp1251", "utf-8", "koi8-r", "cp866"):
        try:
            text = raw.decode(enc)
            if any(m in text for m in markers):
                return text
        except UnicodeDecodeError:
            continue
    return raw.decode("cp1251", errors="replace")


def read_text_file(path):
    with open(path, "rb") as f:
        raw = f.read()
    return decode_bytes(raw), raw


# ============================================================
# ПАРСИНГ
# ============================================================

def clean_patch_filename(name):
    if not name:
        return ""
    s = name.strip()
    s = re.sub(r'"\s+.*$', '"', s)
    parts = re.split(r"[\\/]", s)
    last = parts[-1] if parts else s
    last = re.split(r"\s+", last)[0]
    last = last.strip("\"'")
    last = re.sub(r"-?\{P\}", "", last, flags=re.IGNORECASE)
    return last.strip()


def parse_old_format(content):
    programs = []
    current = None
    state = None
    for raw_line in content.split("\n"):
        line = raw_line.rstrip("\r")
        if re.match(r"^\[\d+\]\s*$", line.strip()):
            if current and current.get("name"):
                programs.append(current)
            current = {"name": "", "description": "",
                       "patch": "", "patch_filename": ""}
            state = None
            continue
        if current is None:
            continue
        if line.startswith("Name="):
            current["name"] = line[5:].strip(); state = None
        elif line.startswith("Hint="):
            current["description"] = line[5:].strip(); state = "hint"
        elif line.startswith("Patch="):
            current["patch"] = line[6:].strip(); state = None
        elif state == "hint" and line.strip() and not line.startswith("["):
            current["description"] += "\n" + line
        else:
            state = None
    if current and current.get("name"):
        programs.append(current)
    for p in programs:
        p["patch_filename"] = clean_patch_filename(p.get("patch", ""))
        hint = p.get("description", "")
        if hint:
            if hint.startswith("|"):
                hint = hint[1:]
            hint = hint.replace("|", "\n")
            hint = re.sub(r"\n+", "\n", hint).strip()
            p["description"] = hint
    return programs


def parse_wpi_format(content):
    programs = []
    blocks = re.split(r"\bpn\s*\+\+\s*;", content)
    for block in blocks:
        if "prog[pn]" not in block:
            continue
        entry = {"name": "", "description": "",
                 "patch": "", "patch_filename": ""}
        m = re.search(r"prog\[pn\]\s*=\s*\[(.+?)\]\s*;", block, re.DOTALL)
        if m:
            parts = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
            entry["name"] = "".join(parts).strip()
        m = re.search(r"desc\[pn\]\s*=\s*\[(.+?)\]\s*;", block, re.DOTALL)
        if m:
            parts = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
            entry["description"] = "".join(parts).strip()
        m = re.search(r"cmds\[pn\]\s*=\s*\[(.+?)\]\s*;", block, re.DOTALL)
        if m:
            parts = re.findall(r"['\"]([^'\"]*)['\"]", m.group(1))
            cmds_str = "".join(parts)
            entry["patch"] = cmds_str
            entry["patch_filename"] = clean_patch_filename(cmds_str)
        if entry["name"]:
            programs.append(entry)
    return programs


def detect_format(content):
    if "prog[pn]" in content:
        return "wpi"
    if "Name=" in content and re.search(r"^\[\d+\]", content, re.MULTILINE):
        return "old"
    # Дополнительно проверим на cmds[pn]/dflt[pn]
    if "dflt[pn]" in content or "cat[pn]" in content or "uid[pn]" in content:
        return "wpi"
    return "unknown"


# ============================================================
# СОПОСТАВЛЕНИЕ
# ============================================================

def normalize_filename(name):
    if not name:
        return ""
    name = name.lower()
    name = re.sub(
        r"\.(exe|msi|zip|rar|7z|tar|gz|txt|dll|bat|cmd|ps1|iso)$", "", name
    )
    return name.strip()


def normalize_aggressive(name):
    return re.sub(r"[\s\.\-_]+", "", (name or "").lower())


def match_file_to_program(filename, programs):
    fn_norm = normalize_filename(filename)
    fn_agg = normalize_aggressive(fn_norm)
    if not fn_agg:
        return None

    for p in programs:
        if normalize_filename(p.get("patch_filename", "")) == fn_norm:
            return p
    for p in programs:
        if normalize_aggressive(p.get("patch_filename", "")) == fn_agg:
            return p
    for p in programs:
        p_agg = normalize_aggressive(p.get("patch_filename", ""))
        if len(fn_agg) >= 5 and len(p_agg) >= 5:
            if fn_agg in p_agg or p_agg in fn_agg:
                return p

    # Fallback по названию
    fn_words = set(re.findall(r"[a-zа-яё0-9]{4,}", fn_norm.replace("ё", "е")))
    if not fn_words:
        return None
    best, best_score = None, 0
    for p in programs:
        name_words = set(
            re.findall(r"[a-zа-яё0-9]{4,}",
                       (p.get("name", "") or "").lower().replace("ё", "е"))
        )
        if not name_words:
            continue
        inter = fn_words & name_words
        if len(inter) >= 2:
            score = len(inter) / len(name_words)
            if score >= 0.6 and score > best_score:
                best_score = score
                best = p
    return best


def parse_filename_title(filename):
    if not filename:
        return ""
    stem = os.path.splitext(filename)[0]
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 72)
    print("ТЕСТ TERABOX v3: скроллинг + мультиописания + подпапки")
    print("=" * 72)

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
        catcher = Catcher()
        catcher.attach(page)

        # ─── Открываем корень ───
        print(f"\nОткрываем {START_URL}")
        page.goto(START_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(8000)
        print(f"Финальный URL: {page.url}")

        root_items = collect_folder_items(page, catcher, 0, wait_ms=15000)
        print(f"\n✓ Корень: {len(root_items)} элементов")
        for it in root_items:
            kind = "DIR " if str(it.get("isdir")) == "1" else "FILE"
            print(f"    [{kind}] {it.get('server_filename')}")

        # ─── Вход в «Программы» ───
        print(f"\n{'─' * 72}\nШАГ 1: Вход в «Программы»\n{'─' * 72}")
        prev = catcher.count()
        ok = _click_folder_by_name(page, "Программы")
        if not ok:
            print("✗ Не удалось кликнуть по «Программы»")
            browser.close()
            return
        page.wait_for_timeout(4000)
        prog_items = collect_folder_items(page, catcher, prev, wait_ms=20000)
        print(f"\n  Содержимое «Программ»: {len(prog_items)} элементов")

        desc_items = []   # файлы описаний
        root_files = []   # прочие файлы в корне «Программ»
        subdirs = []      # подпапки

        for it in prog_items:
            name = it.get("server_filename") or ""
            is_dir = str(it.get("isdir")) == "1"
            if is_dir:
                subdirs.append(it)
            elif name.lower().endswith(DESC_EXTS):
                desc_items.append(it)
            else:
                root_files.append(it)

        print(f"\n  Файлов-описаний (.txt): {len(desc_items)}")
        for d in desc_items:
            print(f"    • {d.get('server_filename')} "
                  f"({d.get('size', 0)} b)")
        print(f"  Прочих файлов:          {len(root_files)}")
        for f in root_files:
            print(f"    • {f.get('server_filename')} "
                  f"({f.get('size', 0)} b)")
        print(f"  Подпапок:               {len(subdirs)}")
        for s in subdirs:
            print(f"    • {s.get('server_filename')}")

        # ─── Парсинг описаний ───
        print(f"\n{'─' * 72}\nШАГ 2: Парсинг описаний\n{'─' * 72}")
        all_programs = []
        seen_keys = set()

        for d in desc_items:
            fname = d.get("server_filename")
            dlink = d.get("dlink")
            if not dlink:
                print(f"  [!] Нет dlink для {fname}")
                continue

            save = f"/tmp/{fname}"
            try:
                download_file(context, dlink, save)
            except Exception as e:
                print(f"  [!] Ошибка скачивания {fname}: {e}")
                continue

            content, raw = read_text_file(save)
            fmt = detect_format(content)

            # Диагностика
            print(f"\n  ── {fname} ──")
            print(f"  Размер: {len(raw)} байт, "
                  f"первые байты: {raw[:8].hex()}")
            preview = content[:300].replace("\r", "")
            for i, line in enumerate(preview.split("\n")[:6]):
                print(f"    | {line[:120]}")
            print(f"  Формат: {fmt}")

            if fmt == "wpi":
                programs = parse_wpi_format(content)
            elif fmt == "old":
                programs = parse_old_format(content)
            else:
                print(f"  [!] Формат не распознан, пропуск")
                continue

            print(f"  Программ: {len(programs)}")

            for prog in programs:
                key = (prog.get("patch_filename") or "").lower()
                if not key or key in seen_keys:
                    continue
                seen_keys.add(key)
                all_programs.append(prog)

        print(f"\n✓ Всего уникальных программ: {len(all_programs)}")
        if all_programs:
            for prog in all_programs[:5]:
                print(f"    • {prog['name'][:50]:<50} "
                      f"→ {prog['patch_filename']}")

        # ─── Обход подпапок ───
        print(f"\n{'─' * 72}\nШАГ 3: Обход подпапок\n{'─' * 72}")
        all_matched = []
        total_files = 0

        for i, sub in enumerate(subdirs):
            sub_name = sub.get("server_filename")
            print(f"\n{'━' * 72}")
            print(f"ПАПКА [{i+1}/{len(subdirs)}]: {sub_name}")
            print(f"{'━' * 72}")

            # Возврат в «Программы»
            if i > 0:
                page.goto(START_URL, wait_until="domcontentloaded",
                          timeout=60000)
                page.wait_for_timeout(6000)
                prev = catcher.count()
                if not _click_folder_by_name(page, "Программы"):
                    print(f"  ✗ Не удалось вернуться в «Программы»")
                    continue
                page.wait_for_timeout(4000)
                _ = collect_folder_items(page, catcher, prev,
                                          wait_ms=15000, scroll=False)

            prev = catcher.count()
            if not _click_folder_by_name(page, sub_name):
                print(f"  ✗ Не удалось открыть '{sub_name}'")
                continue
            page.wait_for_timeout(4000)
            sub_items = collect_folder_items(page, catcher, prev,
                                              wait_ms=15000)

            files_only = [it for it in sub_items
                          if str(it.get("isdir")) != "1"]
            total_files += len(files_only)
            print(f"  Файлов: {len(files_only)}")

            matched_in_sub = 0
            for it in files_only:
                fname = it.get("server_filename") or ""
                found = (match_file_to_program(fname, all_programs)
                         if all_programs else None)
                if found:
                    matched_in_sub += 1
                    print(f"    ✓ {fname}")
                    print(f"      → {found['name']}")
                    all_matched.append({
                        "folder":        sub_name,
                        "filename":      fname,
                        "title":         found["name"],
                        "description":   found.get("description", ""),
                        "size_bytes":    it.get("size", 0),
                        "download_link": it.get("dlink", ""),
                    })
                else:
                    print(f"    ✗ {fname}")

            print(f"  Совпадений: {matched_in_sub}/{len(files_only)}")

        # ─── Итоги ───
        print(f"\n{'═' * 72}")
        print(f"ИТОГО: файлов просмотрено {total_files}, "
              f"сопоставлено {len(all_matched)}")
        print(f"{'═' * 72}")

        for m in all_matched[:30]:
            print(f"  [{m['folder']}] {m['title']}  →  {m['filename']}")
        if len(all_matched) > 30:
            print(f"  ... и ещё {len(all_matched) - 30}")

        with open("/tmp/matched_programs.json", "w", encoding="utf-8") as f:
            json.dump(all_matched, f, ensure_ascii=False, indent=2)
        print(f"\nСохранено: /tmp/matched_programs.json")

        page.screenshot(path="/tmp/final.png")
        browser.close()

    print("\n" + "=" * 72)
    print("ТЕСТ ЗАВЕРШЁН")
    print("=" * 72)


if __name__ == "__main__":
    main()
