import os
import json
import requests
import urllib.parse

TOKEN = os.environ.get("GITHUB_TOKEN")
OWNER = "DimonMaxx"
REPO = "files"
TAG = "vadim-panov"

headers = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def get_assets():
    r = requests.get(f"https://api.github.com/repos/{OWNER}/{REPO}/releases/tags/{TAG}", headers=headers)
    if r.status_code != 200: return []
    rel_id = r.json()["id"]
    assets = []
    page = 1
    while True:
        r = requests.get(f"https://api.github.com/repos/{OWNER}/{REPO}/releases/{rel_id}/assets?per_page=100&page={page}", headers=headers)
        data = r.json()
        if not data: break
        assets.extend(data)
        if len(data) < 100: break
        page += 1
    return assets

def main():
    assets = get_assets()
    tree = {}

    for a in assets:
        name = a["name"]
        # GitHub заменил пробелы на точки. Возвращаем обратно для красоты.
        display_name = name.replace(".", " ")
        
        # Разделяем по " - "
        if " - " in display_name:
            folder, filename = display_name.split(" - ", 1)
        else:
            folder = "Разное"
            filename = display_name

        if folder not in tree:
            tree[folder] = []
        
        # Ссылка на скачивание через Worker
        download_url = f"https://gh-release-proxy.macsimenkodima.workers.dev/download/{TAG}/{urllib.parse.quote(name)}"

        tree[folder].append({
            "title": filename.strip(),
            "url": download_url,
            "size": a["size"]
        })

    # Сортируем папки и файлы по алфавиту
    sorted_tree = {}
    for folder in sorted(tree.keys()):
        sorted_tree[folder] = sorted(tree[folder], key=lambda x: x["title"])

    os.makedirs("_content", exist_ok=True)
    with open("_content/vadim_panov_tree.json", "w", encoding="utf-8") as f:
        json.dump(sorted_tree, f, ensure_ascii=False, indent=2)
    
    print(f"Сгенерировано папок: {len(sorted_tree)}")
    for folder, files in sorted_tree.items():
        print(f"  {folder}: {len(files)} файлов")

if __name__ == "__main__":
    main()
