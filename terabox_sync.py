# terabox_sync.py
# Модуль для получения информации о файлах из TeraBox через Python-библиотеку.

import os
import re
import time
from TeraboxDL import TeraboxDL

def get_terabox_file_info(share_url, cookie_string):
    """
    Получает прямую ссылку и метаданные файла по публичной ссылке TeraBox.
    """
    if not cookie_string:
        print("  [!] TeraBox cookie не задан. Пропускаем раздел.")
        return None

    try:
        # Инициализация клиента с вашим cookie
        terabox = TeraboxDL(cookie_string)
        
        # Запрос информации о файле
        print(f"  [i] Запрос к TeraBox API для ссылки: {share_url[:60]}...")
        file_info = terabox.get_file_info(share_url, direct_url=True)

        if "error" in file_info:
            print(f"  [!] Ошибка TeraBox API: {file_info['error']}")
            return None

        # Проверяем, что получили прямую ссылку
        direct_link = file_info.get('download_link')
        if not direct_link:
            print("  [!] Не удалось получить прямую ссылку на файл.")
            return None

        print(f"  [✓] Успешно получена прямая ссылка для: {file_info.get('file_name')}")

        return {
            "title": file_info.get('file_name', 'Без названия'),
            "size": file_info.get('file_size', '0'),
            "download_link": direct_link,
            "source": "terabox",
            # Дополнительно можно попытаться распарсить название файла
            # для извлечения автора, года и т.д.
        }
    except Exception as e:
        print(f"  [!] Исключение при работе с TeraBox: {e}")
        return None
