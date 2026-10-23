import os
import re
import json
import time
import requests
import gspread
from google.oauth2.service_account import Credentials

SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")
GOOGLE_CREDENTIALS_JSON = os.environ.get("GOOGLE_CREDENTIALS_JSON")
STORAGE_OWNER = "DimonMaxx"
STORAGE_REPO = "files"
STORAGE_TOKEN = os.environ.get("STORAGE_TOKEN")
PROXY_BASE = "https://gh-release-proxy.macsimenkodima.workers.dev"

SECTIONS = {
    "books": {"sheet": "Книги", "exts": [".fb2", ".txt", ".epub", ".pdf"]},
    "programs": {"sheet": "Программы", "exts": [".exe", ".msi", ".rar", ".zip", ".7z", ".xlsm", ".xlsx", ".bat", ".ps1"]},
    "music": {"sheet": "Музыка", "exts": [".mp3", ".flac", ".wav"]}
}

TAG_TRANSLATIONS = {
    "ajzek-azimov": "Айзек Азимов", "aksenov-daniil": "Аксенов Даниил", "aleksandr-rudazov": "Александр Рудазов",
    "alekseeva-yana": "Алексеева Яна", "aliya-ya": "Алия Я", "andre-norton": "Андрэ Нортон",
    "andrej-kruz": "Андрей Круз", "andrej-lazarchuk": "Андрей Лазарчук", "andzhej-sapkovskij": "Анджей Сапковский",
    "andzhej-yasinskij": "Анджей Ясинский", "arina-alison": "Арина Алисон", "arkadij-strugackij": "АРКАДИЙ СТРУГАЦКИЙ",
    "badej": "Бадей", "bastars-roda-demonov": "Бастарс рода демонов", "batcher-dzhim": "Батчер Джим",
    "dmitrij-ra": "Дмитрий Ра", "dmitrij-serebryakov-novaya-zhizn": "Дмитрий Серебряков - Новая жизнь",
    "drugoj-mir": "Другой мир", "dzh-lokhard": "Дж. Локхард", "dzhon-karter": "Джон Картер",
    "egida": "Эгида", "ezdovoj-gnom": "ездовой гном", "glushanovskij-aleksej": "Глушановский Алексей",
    "gordon-dikson": "Гордон Диксон", "inoj": "Иной", "legenda": "Легенда", "lesovik": "Лесовик",
    "lisina": "Лисина", "lorel-gamilton": "Лорел Гамильтон", "mir-karika": "Мир Карика", "nashi-tam": "Наши там",
    "naslednik-dyavola": "Наследник дьявола", "nepravilnyj-lekar": "Неправильный лекарь", "nik-perunov": "Ник Перунов",
    "olga-gromyko": "Ольга Громыко", "pivko-aleksandr": "Пивко Александр", "porri-gatter": "Порри Гаттер",
    "sergej-lukyanenko": "Сергей Лукьяненко", "serzh-vinterkej-egida-15-knig": "Серж Винтеркей. Эгида",
    "shumil-pavel": "Шумил Павел", "sistema": "Система", "stalker": "Сталкер", "sumerechnaya-saga": "Сумеречная сага",
    "tanya-haff": "Таня Хафф", "temnaya-bashnya": "Темная башня", "temnyj-angel": "Темный ангел",
    "vadim-panov": "Вадим Панов", "viktor-viktorov": "Виктор Викторов",
    "linkin-park": "Linkin Park", "skillet": "Skillet", "within-temptation": "Within Temptation",
    "adobe": "Adobe", "aeditor": "AEditor", "ams": "AMS", "archive": "Archive", "ascomp": "ASComp",
    "contact": "Contact", "converter": "Converter", "defrag": "Defrag", "diagnostics": "Diagnostics",
    "disc": "Disc", "dlya-windows-svoi": "Для windows свои", "download": "Download", "file": "File",
    "graphics": "Graphics", "hdd": "HDD", "interface": "Interface", "internet": "Internet",
    "makrosy": "Макросы", "media": "Media", "meditor": "MEditor", "mso": "MSO", "office": "Office",
    "optimizers": "Optimizers", "pdf": "PDF", "phone": "Phone", "photo": "Photo", "plaginy": "Плагины",
    "print": "Print", "radiotv": "RadioTV", "recovery": "Recovery", "recscreen": "RecScreen", "registry": "Registry",
    "search": "Search", "security": "Security", "service": "Service", "skripty": "Скрипты", "system": "System",
    "text": "Text", "uninstall": "Uninstall"
}

def get_gsheet():
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID)

def download_text(url):
    try:
        r = requests.get(url, timeout=15)
        if r.status_code == 200:
            return r.content.decode('utf-8', errors='ignore')
    except Exception:
        pass
    return ""

def parse_fb2(url):
    try:
        r = requests.get(url, headers={"Range": "bytes=0-250000"}, timeout=20)
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
        desc = anno_m.group(1).strip() if anno_m else ""
        desc = re.sub(r'<[^>]+>', '', desc)
        
        return title, author, desc
    except Exception:
        return "", "", ""

def main():
    sh = get_gsheet()
    
    # 1. Скачиваем описания из релиза Opisanie
    print("1. Загрузка описаний из релиза Opisanie...")
    gh_headers = {"Authorization": f"token {STORAGE_TOKEN}", "Accept": "application/vnd.github.v3+json"}
    program_descriptions = {}
    
    try:
        r = requests.get(f"https://api.github.com/repos/{STORAGE_OWNER}/{STORAGE_REPO}/releases/tags/Opisanie", headers=gh_headers)
        if r.status_code == 200:
            rel = r.json()
            for asset in rel.get("assets", []):
                if asset["name"].endswith(".txt"):
                    print(f"   Чтение {asset['name']}...")
                    content = download_text(asset["browser_download_url"])
                    # Парсим текст: ищем строки, где есть "Название: Описание"
                    lines = content.split('\n')
                    current_prog = None
                    current_desc = []
                    
                    for line in lines:
                        line = line.strip()
                        if not line: continue
                        
                        # Проверяем, не начинается ли новая программа
                        # Допустим, программы разделены пустыми строками, а первая строка - название
                        if len(line) < 100 and (":" in line or len(current_desc) == 0):
                            # Если мы уже собирали описание, сохраняем его
                            if current_prog and current_desc:
                                program_descriptions[current_prog.lower()] = " ".join(current_desc)
                            
                            # Начинаем новую
                            if ":" in line:
                                parts = line.split(":", 1)
                                current_prog = parts[0].strip()
                                current_desc = [parts[1].strip()]
                            else:
                                current_prog = line
                                current_desc = []
                        else:
                            # Продолжение описания
                            current_desc.append(line)
                            
                    # Сохраняем последнее
                    if current_prog and current_desc:
                        program_descriptions[current_prog.lower()] = " ".join(current_desc)
        else:
            print("   Релиз Opisanie не найден.")
    except Exception as e:
        print(f"   Ошибка чтения описаний: {e}")

    print(f"   Загружено описаний для программ: {len(program_descriptions)}")

    # 2. Бэкап старых данных
    print("2. Бэкап старых данных...")
    saved_meta = {}
    legacy_rows = {}
    sheet_headers = {}
    
    for section_key, cfg in SECTIONS.items():
        sheet_name = cfg["sheet"]
        try:
            ws = sh.worksheet(sheet_name)
        except:
            continue
            
        all_vals = ws.get_all_values()
        if not all_vals: continue
        
        header = all_vals[0]
        sheet_headers[sheet_name] = header
        
        idx_folder = header.index("Папка") if "Папка" in header else -1
        idx_title = header.index("Название") if "Название" in header else -1
        idx_desc = header.index("Описание") if "Описание" in header else -1
        idx_author = header.index("Автор") if "Автор" in header else -1
        idx_link = header.index("Ссылка для скачивания") if "Ссылка для скачивания" in header else -1
        
        keep_rows = [header]
        
        for row in all_vals[1:]:
            if len(row) == 0: continue
            def get_val(idx): return row[idx] if idx != -1 and idx < len(row) else ""
            title, folder, link = get_val(idx_title), get_val(idx_folder), get_val(idx_link)
            desc, author = get_val(idx_desc), get_val(idx_author)
            
            if not title.strip(): continue
            norm_key = f"{folder.strip().lower()}|{title.strip().lower()}"
            if desc or author: saved_meta[norm_key] = {"desc": desc, "author": author}
            if "gh-release-proxy" not in link and "github.com" not in link:
                keep_rows.append(row)
        legacy_rows[sheet_name] = keep_rows
        
    # 3. Очистка
    print("3. Очистка листов...")
    for sheet_name, rows in legacy_rows.items():
        ws = sh.worksheet(sheet_name)
        ws.clear()
        if rows: ws.update(values=rows, range_name="A1")

    # 4. Получаем релизы и заполняем
    print("4. Чтение GitHub и заполнение...")
    releases, page = [], 1
    while True:
        r = requests.get(f"https://api.github.com/repos/{STORAGE_OWNER}/{STORAGE_REPO}/releases?per_page=100&page={page}", headers=gh_headers)
        data = r.json()
        if not data: break
        releases.extend(data)
        page += 1

    new_rows_by_sheet = {cfg["sheet"]: [] for cfg in SECTIONS.values()}
    
    for rel in releases:
        tag = rel.get("tag_name", "")
        if tag.lower() == "opisanie": continue # Пропускаем этот служебный тег
        
        section_key = None
        for k in SECTIONS.keys():
            if k in tag: section_key = k; break
        if not section_key:
            ext = os.path.splitext(rel.get("assets", [{}])[0].get("name", ""))[1].lower() if rel.get("assets") else ""
            for k, v in SECTIONS.items():
                if ext in v["exts"]: section_key = k; break
        if not section_key: continue
        
        sheet_name = SECTIONS[section_key]["sheet"]
        headers = sheet_headers.get(sheet_name, ["Папка", "Название", "Ссылка для скачивания"])
        folder_name = TAG_TRANSLATIONS.get(tag, tag)
        
        for asset in rel.get("assets", []):
            fname = asset["name"]
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SECTIONS[section_key]["exts"]: continue
            
            clean_title = os.path.splitext(fname)[0]
            clean_title = re.sub(r'^[\d\.\-\_]+', '', clean_title).strip()
            new_link = f"{PROXY_BASE}/download/{tag}/{fname}"
            size_mb = str(round(asset["size"] / (1024 * 1024), 1))
            
            author, desc = "", ""
            
            # Пытаемся достать метаданные из самого файла
            if ext == ".fb2":
                t, a, d = parse_fb2(new_link)
                if t: clean_title = t
                author, desc = a, d
            
            # Для программ ищем описание в скачанных TXT
            if section_key == "programs":
                # Ищем по точному названию или частичному совпадению
                search_title = clean_title.lower().strip()
                for prog_name, prog_desc in program_descriptions.items():
                    if search_title in prog_name or prog_name in search_title:
                        desc = prog_desc
                        break

            # Если пусто, берем из старой таблицы
            if not desc or not author:
                norm_key = f"{folder_name.lower()}|{clean_title.lower()}"
                alt_key = f"{tag.lower()}|{clean_title.lower()}"
                meta = saved_meta.get(norm_key) or saved_meta.get(alt_key)
                if meta:
                    if not desc: desc = meta["desc"]
                    if not author: author = meta["author"]
            
            artist_val = folder_name if section_key == "music" else ""
            author_val = author if author else (folder_name if section_key == "books" else "")

            row_dict = {
                "folder": folder_name, "title": clean_title, "author": author_val,
                "artist": artist_val, "desc": desc, "format": ext.replace(".", ""),
                "size": size_mb, "link": new_link
            }

            final_row = []
            for h in headers:
                hl = h.strip().lower()
                if "папка" in hl: final_row.append(row_dict["folder"])
                elif "название" in hl: final_row.append(row_dict["title"])
                elif "автор" in hl: final_row.append(row_dict["author"])
                elif "исполнитель" in hl: final_row.append(row_dict["artist"])
                elif "описание" in hl: final_row.append(row_dict["desc"])
                elif "формат" in hl: final_row.append(row_dict["format"])
                elif "размер" in hl: final_row.append(row_dict["size"])
                elif "ссылка" in hl or "скачивания" in hl: final_row.append(row_dict["link"])
                elif "значок" in hl or "обложка" in hl: final_row.append("") # Значки пока пустые
                else: final_row.append("")
                
            new_rows_by_sheet[sheet_name].append(final_row)

    # 5. Запись
    print("5. Сохранение...")
    for sheet_name, new_rows in new_rows_by_sheet.items():
        if not new_rows: continue
        ws = sh.worksheet(sheet_name)
        for i in range(0, len(new_rows), 100):
            ws.append_rows(new_rows[i:i+100], value_input_option="USER_ENTERED")
            time.sleep(1)
        print(f"   {sheet_name}: добавлено {len(new_rows)}")

    print("✅ Готово!")

if __name__ == "__main__":
    main()
