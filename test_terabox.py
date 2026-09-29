#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест TeraBox через библиотеку terabox-api.
"""

import os
import sys
import traceback

print("=" * 60)
print("TEST TERABOX-API — старт")
print("=" * 60)

# ─── 1. Проверка окружения ───
print("\n[1] Проверка переменных окружения:")
cookie = os.environ.get("TERABOX_COOKIE")
if not cookie:
    print("  ✗ TERABOX_COOKIE НЕ задан!")
    sys.exit(1)
print(f"  ✓ TERABOX_COOKIE задан (длина: {len(cookie)})")

# ─── 2. Импорт библиотеки ───
print("\n[2] Импорт terabox-api:")
try:
    from terabox_api import TeraBox
    print("  ✓ Модуль TeraBox импортирован.")
except ImportError as e:
    print(f"  ✗ Не удалось импортировать: {e}")
    sys.exit(1)

# ─── 3. Инициализация клиента ───
print("\n[3] Инициализация клиента:")
try:
    client = TeraBox(cookie=cookie)
    print("  ✓ Клиент создан.")
except Exception as e:
    print(f"  ✗ Ошибка: {e}")
    traceback.print_exc()
    sys.exit(1)

# ─── 4. Методы клиента ───
print("\n[4] Доступные методы:")
for m in dir(client):
    if not m.startswith("_"):
        print(f"  • {m}")

# ─── 5. Тестовый запрос к папке "Программы" ───
print("\n[5] Запрос к папке 'Программы':")
url = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"
try:
    # Пробуем разные методы (названия зависят от версии)
    result = None
    for method_name in ("get_files", "list_files", "get_file_list", "get_data"):
        if hasattr(client, method_name):
            print(f"  Использую метод: {method_name}()")
            method = getattr(client, method_name)
            try:
                result = method(url)
                break
            except Exception as e:
                print(f"    [!] Метод {method_name} упал: {e}")

    if result is None:
        print("  [!] Ни один метод не сработал.")
    else:
        print(f"  ✓ Получен результат. Тип: {type(result).__name__}")
        if isinstance(result, list):
            print(f"    Элементов: {len(result)}")
            for i, item in enumerate(result[:10]):
                print(f"    [{i}] {item}")
        elif isinstance(result, dict):
            print(f"    Ключи: {list(result.keys())}")
            for k, v in result.items():
                if isinstance(v, (list, dict)):
                    print(f"    {k}: ({type(v).__name__}, длина {len(v)})")
                else:
                    print(f"    {k}: {str(v)[:100]}")

except Exception as e:
    print(f"  ✗ Ошибка: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST TERABOX-API — готово!")
print("=" * 60)
