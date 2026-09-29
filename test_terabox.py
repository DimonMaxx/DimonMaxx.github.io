#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для отладки TeraBox.
Запускается из workflow test-terabox.yml.
Выводит в логи всё, что делает, чтобы понять, где ломается.
"""

import os
import sys
import traceback

print("=" * 60)
print("TEST TERABOX — старт")
print("=" * 60)

# ─── 1. Проверка окружения ───
print("\n[1] Проверка переменных окружения:")
cookie = os.environ.get("TERABOX_COOKIE")
if cookie:
    print(f"  ✓ TERABOX_COOKIE задан (длина: {len(cookie)} символов)")
    print(f"    Первые 20 символов: {cookie[:20]}...")
else:
    print("  ✗ TERABOX_COOKIE НЕ задан!")
    print("    Добавьте секрет в Settings → Secrets and variables → Actions")
    sys.exit(1)

# ─── 2. Проверка импорта библиотеки ───
print("\n[2] Проверка импорта terabox-downloader:")
try:
    from TeraboxDL import TeraboxDL
    print("  ✓ Библиотека TeraboxDL импортирована.")
except ImportError as e:
    print(f"  ✗ Ошибка импорта: {e}")
    print("    Убедитесь, что terabox-downloader есть в requirements.txt")
    sys.exit(1)

# ─── 3. Инициализация клиента ───
print("\n[3] Инициализация клиента TeraBox:")
try:
    client = TeraboxDL(cookie)
    print("  ✓ Клиент создан.")
except Exception as e:
    print(f"  ✗ Ошибка создания клиента: {e}")
    traceback.print_exc()
    sys.exit(1)

# ─── 4. Проверка доступных методов ───
print("\n[4] Доступные методы клиента:")
methods = [m for m in dir(client) if not m.startswith("_")]
for m in methods:
    print(f"  • {m}")

# ─── 5. Тестовый запрос к корневой папке "Для сайта" ───
print("\n[5] Тест: корневая папка 'Для сайта'")
root_url = "https://1024terabox.com/s/1w4Vu3UwAFWEx-WEc8jxUCA"
try:
    print(f"  Запрос: {root_url}")
    result = client.get_file_info(root_url)
    print(f"  ✓ Получен ответ. Тип: {type(result).__name__}")
    if isinstance(result, dict):
        print(f"    Ключи ответа: {list(result.keys())}")
        if "error" in result:
            print(f"    ✗ Ошибка API: {result['error']}")
        else:
            for k, v in result.items():
                if k in ("download_link", "dlink"):
                    print(f"    {k}: {str(v)[:80]}...")
                else:
                    print(f"    {k}: {v}")
    elif isinstance(result, list):
        print(f"    Получено элементов: {len(result)}")
        for i, item in enumerate(result[:5]):
            print(f"    [{i}] {item}")
    else:
        print(f"    Сырой ответ: {result}")
except Exception as e:
    print(f"  ✗ Ошибка запроса: {e}")
    traceback.print_exc()

# ─── 6. Тестовый запрос к папке "Программы" ───
print("\n[6] Тест: папка 'Программы'")
programs_url = "https://1024terabox.com/s/1y91_O-V1aszt69FeCBBcxA"
try:
    print(f"  Запрос: {programs_url}")
    result = client.get_file_info(programs_url)
    print(f"  ✓ Получен ответ. Тип: {type(result).__name__}")
    if isinstance(result, dict):
        print(f"    Ключи ответа: {list(result.keys())}")
        if "error" in result:
            print(f"    ✗ Ошибка API: {result['error']}")
        else:
            for k, v in result.items():
                if k in ("download_link", "dlink"):
                    print(f"    {k}: {str(v)[:80]}...")
                else:
                    print(f"    {k}: {v}")
    elif isinstance(result, list):
        print(f"    Получено элементов: {len(result)}")
        for i, item in enumerate(result[:10]):
            print(f"    [{i}] {item}")
except Exception as e:
    print(f"  ✗ Ошибка запроса: {e}")
    traceback.print_exc()

print("\n" + "=" * 60)
print("TEST TERABOX — готово!")
print("=" * 60)
