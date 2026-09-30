# delete_content.py
# Удаление строк из Google Sheets по названию.
# Общие константы и функции — в common.py
#
# v2: группировка смежных строк в диапазоны + batch_update,
#     чтобы не ловить 429 Quota Exceeded при массовых удалениях.

import os
import json
import time

import gspread

from common import (
    SPREADSHEET_ID,
    SECTION_TO_SHEET,
    get_gspread_client,
    normalize,
)


# Максимум диапазонов в одном batch_update
CHUNK_SIZE = 100
# Задержка между чанками (сек), чтобы не выйти за квоту 60 req/min
CHUNK_DELAY = 2


def _group_rows_into_ranges(rows_sorted_asc):
    """
    [1, 2, 5, 6, 7] → [(1, 2), (5, 7)] (1-based, inclusive).
    """
    ranges = []
    for r in rows_sorted_asc:
        if ranges and r == ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], r)
        else:
            ranges.append((r, r))
    return ranges


def _delete_ranges(worksheet, ranges_1based):
    """
    Удаляет диапазоны строк одним/несколькими batch_update.
    Google применяет deleteDimension последовательно, поэтому удаляем
    с конца (наибольшие индексы первыми), чтобы индексы меньших
    диапазонов не сдвигались.
    """
    if not ranges_1based:
        return 0

    ranges_desc = sorted(ranges_1based, key=lambda x: -x[0])
    sheet_id = worksheet.id
    total_deleted = 0

    for i in range(0, len(ranges_desc), CHUNK_SIZE):
        chunk = ranges_desc[i:i + CHUNK_SIZE]

        requests = []
        for start, end in chunk:
            requests.append({
                "deleteDimension": {
                    "range": {
                        "sheetId":    sheet_id,
                        "dimension":  "ROWS",
                        # API 0-based, endIndex эксклюзивный
                        "startIndex": start - 1,
                        "endIndex":   end,
                    }
                }
            })

        ok = False
        for attempt in range(4):
            try:
                worksheet.spreadsheet.batch_update({"requests": requests})
                ok = True
                break
            except gspread.exceptions.APIError as e:
                msg = str(e)
                if "429" in msg or "Quota exceeded" in msg:
                    wait = 20 * (attempt + 1)
                    print(f"    [!] 429 quota, ждём {wait} сек...")
                    time.sleep(wait)
                else:
                    raise

        if ok:
            for start, end in chunk:
                total_deleted += (end - start + 1)
        else:
            print(f"    [!] чанк {i//CHUNK_SIZE} не удалось удалить")

        if i + CHUNK_SIZE < len(ranges_desc):
            time.sleep(CHUNK_DELAY)

    return total_deleted


def main():
    delete_list_json = os.environ.get('DELETE_LIST', '[]')
    try:
        delete_list = json.loads(delete_list_json)
    except Exception as e:
        print(f"Ошибка парсинга DELETE_LIST: {e}")
        return

    if not delete_list:
        print("Список удаляемых записей пуст.")
        return

    print(f"Получено на удаление: {len(delete_list)} записей")

    gc = get_gspread_client()
    sh = gc.open_by_key(SPREADSHEET_ID)

    # Группируем по листам
    by_sheet = {}
    for item in delete_list:
        section = item.get('section')
        title = item.get('title')
        if not section or not title:
            continue
        sheet_name = SECTION_TO_SHEET.get(section)
        if not sheet_name:
            continue
        by_sheet.setdefault(sheet_name, []).append(title)

    # Удаляем
    for sheet_name, titles in by_sheet.items():
        print(f"\nЛист '{sheet_name}': удаляем {len(titles)} записей")
        try:
            worksheet = sh.worksheet(sheet_name)
        except gspread.exceptions.WorksheetNotFound:
            print(f"  Лист '{sheet_name}' не найден, пропускаем.")
            continue

        all_values = worksheet.get_all_values()
        if not all_values:
            print("  Лист пустой.")
            continue

        headers = all_values[0]
        try:
            col_title = headers.index("Название")
        except ValueError:
            print(f"  На листе '{sheet_name}' нет колонки 'Название'")
            continue

        rows_to_delete = []
        titles_norm = [normalize(t) for t in titles]
        for i, row in enumerate(all_values[1:], start=2):
            if col_title < len(row):
                row_title_norm = normalize(row[col_title])
                if row_title_norm in titles_norm:
                    rows_to_delete.append(i)
                    titles_norm.remove(row_title_norm)

        if not rows_to_delete:
            print(f"  Ничего не найдено для удаления.")
            continue

        rows_to_delete.sort()
        ranges = _group_rows_into_ranges(rows_to_delete)

        print(f"  К удалению: {len(rows_to_delete)} строк "
              f"в {len(ranges)} диапазонах")

        deleted = _delete_ranges(worksheet, ranges)
        print(f"  ✓ Удалено {deleted} строк.")

    print("\nГотово!")


if __name__ == "__main__":
    main()
