import os
import re
import json
import time
import requests
import gspread
from google.oauth2.service_account import Credentials
from urllib.parse import unquote

# Конфигурация
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
STORAGE_OWNER = "DimonMaxx"
STORAGE_REPO = "files"
STORAGE_TOKEN = os.environ.get("STORAGE_TOKEN")
PROXY_BASE = "https://gh-release-proxy.macsimenkodima.workers.dev"

# Словарь разделов
SECTIONS = {
    "books": {"sheet": "Книги", "exts": [".fb2", ".txt", ".epub", ".pdf"]},
    "programs": {"sheet": "Программы", "exts": [".exe", ".msi", ".rar", ".zip", ".7z", ".xlsm", ".xlsx", ".bat", ".ps1"]},
    "music": {"sheet": "Музыка", "exts": [".mp3", ".flac", ".wav"]}
}

TAG_TRANSLATIONS = {
    "plaginy": "Плагины", "skripty": "Скрипты", "makrosy": "Макросы", "dlya-windows-svoi": "Для windows свои"
}

def get_gsheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def parse_fb2_from_url(url):
    """Скачивает первые 200КБ файла и ищет метаданные"""
    try:
        # Запрашиваем только начало файла для экономии трафика
        headers = {"Range": "bytes=0-200000"}
        r = requests.get(url, headers=headers, timeout=15)
        content = r.content.decode('utf-8', errors='ignore')
        
        title_m = re.search(r'<book-title>(.*?)</book-title>', content, re.IGNORECASE)
        title = title_m.group(1).strip() if title_m else ""
        
        author_m = re.search(r'<author>.*?<first-name>(.*?)</first-name>.*?<last-name>(.*?)</last-name>.*?</author>', content, re.DOTALL | re.IGNORECASE)
        if not author_m:
            author_m = re.search(r'<author>.*?<nickname>(.*?)</nickname>.*?</author>', content, re.DOTALL | re.IGNORECASE)
            
        author = ""
        if author_m:
            if len(author_m.groups()) == 2:
                author = f"{author_m.group(1).strip()} {author_m.group(2).strip()}"
            else:
                author = author_m.group(1).strip()
                
        anno_m = re.search(r'<annotation>.*?<p>(.*?)</p>', content, re.DOTALL | re.IGNORECASE)
        anno = anno_m.group(1).strip() if anno_m else ""
        anno = re.sub(r'<[^>]+>', '', anno) # убираем теги
        
        return title, author, anno
    except Exception as e:
        print(f"  Ошибка парсинга FB2: {e}")
        return "", "", ""

def parse_txt_from_url(url):
    """Пытается найти автора и название в первых строках TXT"""
    try:
        headers = {"Range": "bytes=0-50000"}
        r = requests.get(url, headers=headers, timeout=15)
        content = r.content.decode('utf-8', errors='ignore')
        lines = [line.strip() for line in content.split('\n') if line.strip()][:10]
        
        author = ""
        title = ""
        for line in lines:
            if "автор:" in line.lower():
                author = line.split(":", 1)[1].strip()
            elif "название:" in line.lower():
                title = line.split(":", 1)[1].strip()
        
        return title, author, ""
    except Exception:
        return "", "", ""

def main():
    sh = get_gsheet()
    
    # 1. Собираем старые данные (описания, авторы) и оставляем legacy строки
    print("1. Анализ текущей таблицы...")
    saved_meta = {} # Ключ: "папка|название" -> {"desc": "", "author": ""}
    legacy_rows = {} # sheet_name -> list of rows
    
    for section_key, cfg in SECTIONS.items():
        sheet_name = cfg["sheet"]
        try:
            ws = sh.worksheet(sheet_name)
        except:
            continue
            
        all_vals = ws.get_all_values()
        if len(all_vals) < 2: continue
        
        header = all_vals[0]
        idx_folder = header.index("Папка") if "Папка" in header else -1
        idx_title = header.index("Название") if "Название" in header else -1
        idx_desc = header.index("Описание") if "Описание" in header else -1
        idx_author = header.index("Автор") if "Автор" in header else -1
        idx_link = header.index("Ссылка для скачивания") if "Ссылка для скачивания" in header else -1
        
        keep_rows = [header]
        
        for row in all_vals[1:]:
            title = row[idx_title] if idx_title != -1 and idx_title < len(row) else ""
            folder = row[idx_folder] if idx_folder != -1 and idx_folder < len(row) else ""
            link = row[idx_link] if idx_link != -1 and idx_link < len(row) else ""
            desc = row[idx_desc] if idx_desc != -1 and idx_desc < len(row) else ""
            author = row[idx_author] if idx_author != -1 and idx_author < len(row) else ""
            
            if not title.strip(): continue
            
            # Сохраняем метаданные для сопоставления
            norm_key = f"{folder.strip().lower()}|{title.strip().lower()}"
            if desc or author:
                saved_meta[norm_key] = {"desc": desc, "author": author}
                
            # Оставляем только legacy (не GitHub)
            if "gh-release-proxy" not in link and "github.com" not in link:
                keep_rows.append(row)
                
        legacy_rows[sheet_name] = keep_rows
        print(f"   В листе {sheet_name} оставлено legacy строк: {len(keep_rows)-1}")

    # 2. Очищаем листы и пишем обратно Legacy
    print("2. Очистка листов и восстановление Legacy ссылок...")
    for sheet_name, rows in legacy_rows.items():
        ws = sh.worksheet(sheet_name)
        ws.clear()
        if rows:
            ws.update(values=rows, range_name="A1")

    # 3. Получаем релизы GitHub
    print("3. Загрузка релизов из GitHub...")
    headers = {"Authorization": f"token {STORAGE_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    releases = []
    page = 1
    while True:
        r = requests.get(f"https://api.github.com/repos/{STORAGE_OWNER}/{STORAGE_REPO}/releases?per_page=100&page={page}", headers=headers)
        data = r.json()
        if not data: break
        releases.extend(data)
        page += 1

    # 4. Формируем новые строки
    print("4. Парсинг файлов и заполнение таблицы...")
    new_rows_by_sheet = {cfg["sheet"]: [] for cfg in SECTIONS.values()}
    
    for rel in releases:
        tag = rel.get("tag_name", "")
        
        # Определяем лист
        section_key = None
        for k, v in SECTIONS.items():
            if k in tag: section_key = k; break
        
        if not section_key:
            ext = os.path.splitext(rel.get("assets", [{}])[0].get("name", ""))[1].lower() if rel.get("assets") else ""
            for k, v in SECTIONS.items():
                if ext in v["exts"]: section_key = k; break
                
        if not section_key: continue
        
        sheet_name = SECTIONS[section_key]["sheet"]
        folder_name = TAG_TRANSLATIONS.get(tag, tag)
        
        for asset in rel.get("assets", []):
            fname = asset["name"]
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SECTIONS[section_key]["exts"]: continue
            
            clean_title = os.path.splitext(fname)[0]
            clean_title = re.sub(r'^[\d\.\-\_]+', '', clean_title).strip() # Убираем -., 01. и т.д.
            
            new_link = f"{PROXY_BASE}/download/{tag}/{fname}"
            
            author, desc = "", ""
            
            # Пытаемся достать метаданные из файла
            if ext == ".fb2":
                print(f"  Парсинг FB2: {fname}")
                t, a, d = parse_fb2_from_url(new_link)
                if t: clean_title = t
                author, desc = a, d
            elif ext == ".txt" and section_key == "books":
                t, a, d = parse_txt_from_url(new_link)
                if t: clean_title = t
                author, desc = a, d
            
            # Если не нашли внутри файла, ищем в сохраненных данных
            if not desc or not author:
                norm_key = f"{folder_name.lower()}|{clean_title.lower()}"
                if norm_key in saved_meta:
                    if not desc: desc = saved_meta[norm_key]["desc"]
                    if not author: author = saved_meta[norm_key]["author"]
            
            # Формируем строку
            row_data = []
            for col in ["Папка", "Обложка", "Название", "Автор", "Описание", "Формат", "Размер (МБ)", "Ссылка для скачивания"]:
                if col == "Папка": row_data.append(folder_name)
                elif col == "Название": row_data.append(clean_title)
                elif col == "Автор": row_data.append(author)
                elif col == "Описание": row_data.append(desc)
                elif col == "Формат": row_data.append(ext.replace(".", ""))
                elif col == "Размер (МБ)": row_data.append(str(round(asset["size"]/(1024*1024), 1)))
                elif col == "Ссылка для скачивания": row_data.append(new_link)
                else: row_data.append("")
            
            new_rows_by_sheet[sheet_name].append(row_data)

    # 5. Записываем новые строки в листы
    print("5. Сохранение результатов...")
    for sheet_name, new_rows in new_rows_by_sheet.items():
        if not new_rows: continue
        ws = sh.worksheet(sheet_name)
        # Добавляем к тем, что уже есть (Legacy)
        ws.append_rows(new_rows, value_input_option="USER_ENTERED")
        print(f"   В лист {sheet_name} добавлено новых строк: {len(new_rows)}")

    print("✅ Пересборка завершена!")

if __name__ == "__main__":
    main()
