#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cleanup_errors.py
Удаляет устаревшие записи из таблицы client_errors (Supabase).

Логика:
  1. Читает CLEANUP_ERRORS_DAYS (по умолчанию 30).
  2. Считает, сколько записей старше cutoff.
  3. Удаляет их батчами через REST API.
  4. Отправляет отчёт в Telegram (если настроен notify.py).

Переменные окружения:
  SUPABASE_URL             — URL проекта (по умолчанию из notify)
  SUPABASE_SERVICE_ROLE_KEY — сервисный ключ (обязательно)
  CLEANUP_ERRORS_DAYS      — сколько дней хранить (по умолчанию 30)
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID — для уведомлений
"""

import os
import sys
import time
import datetime
import requests

try:
    from notify import notify_result
except ImportError:
    def notify_result(**kw):
        return False


SUPABASE_URL         = os.environ.get("SUPABASE_URL",
                                      "https://rmoonebbvpmvthvpcmpt.supabase.co")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")

CLEANUP_DAYS_DEFAULT = 30
try:
    CLEANUP_DAYS = int(os.environ.get("CLEANUP_ERRORS_DAYS", str(CLEANUP_DAYS_DEFAULT)))
except ValueError:
    CLEANUP_DAYS = CLEANUP_DAYS_DEFAULT

TABLE       = "client_errors"
BATCH_SIZE  = 500   # сколько записей удаляем за один запрос
MAX_BATCHES = 200   # предохранитель: не более 100 000 записей за раз


def _headers():
    if not SUPABASE_SERVICE_KEY:
        raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY не задан")
    return {
        "apikey":        SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type":  "application/json",
        "Prefer":        "count=exact",
    }


def _count_before(cutoff_iso):
    """Считает, сколько записей старше cutoff."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
    params = {
        "select":     "id",
        "created_at": f"lt.{cutoff_iso}",
        "limit":      "1",
    }
    r = requests.get(url, params=params, headers=_headers(), timeout=30)
    if r.status_code not in (200, 206):
        raise RuntimeError(f"count HTTP {r.status_code}: {r.text[:300]}")
    # Заголовок content-range имеет вид: 0-0/12345
    cr = r.headers.get("Content-Range", "")
    if "/" in cr:
        try:
            return int(cr.rsplit("/", 1)[-1])
        except Exception:
            pass
    return 0


def _delete_batch(cutoff_iso, limit=BATCH_SIZE):
    """Удаляет один батч старых записей. Возвращает число удалённых."""
    url = f"{SUPABASE_URL}/rest/v1/{TABLE}"
    params = {
        "created_at": f"lt.{cutoff_iso}",
        "limit":      str(limit),
    }
    # Prefer: return=representation — узнать, сколько удалили
    headers = _headers()
    headers["Prefer"] = "return=representation"
    r = requests.delete(url, params=params, headers=headers, timeout=60)
    if r.status_code not in (200, 204, 206):
        raise RuntimeError(f"delete HTTP {r.status_code}: {r.text[:300]}")
    try:
        body = r.json()
        if isinstance(body, list):
            return len(body)
    except Exception:
        pass
    # Если вернулось 204 — считаем, что батч удалён
    return limit if r.status_code == 204 else 0


def main():
    print("=" * 60)
    print("cleanup_errors.py — старт")
    print("=" * 60)

    if not SUPABASE_SERVICE_KEY:
        print("[!] SUPABASE_SERVICE_ROLE_KEY не задан")
        notify_result(
            title="Cleanup JS errors",
            status="failure",
            details="SUPABASE_SERVICE_ROLE_KEY не задан",
        )
        sys.exit(1)

    now = datetime.datetime.utcnow()
    cutoff = now - datetime.timedelta(days=CLEANUP_DAYS)
    cutoff_iso = cutoff.isoformat(timespec="seconds") + "Z"

    print(f"Порог: {cutoff_iso} (старше {CLEANUP_DAYS} дней)")

    # ─── Считаем сколько всего ───
    try:
        total_before = _count_before(cutoff_iso)
    except Exception as e:
        print(f"[!] Ошибка подсчёта: {e}")
        notify_result(
            title="Cleanup JS errors",
            status="failure",
            details=f"Ошибка подсчёта: {e}",
        )
        sys.exit(1)

    print(f"К удалению: {total_before} записей")

    if total_before == 0:
        print("Нечего удалять.")
        notify_result(
            title="Cleanup JS errors",
            status="success",
            details=f"Нечего удалять (записей старше {CLEANUP_DAYS} дней нет)",
        )
        return

    # ─── Удаляем батчами ───
    deleted = 0
    batches = 0
    t0 = time.time()

    while batches < MAX_BATCHES:
        try:
            n = _delete_batch(cutoff_iso, BATCH_SIZE)
        except Exception as e:
            print(f"[!] Ошибка удаления батча {batches + 1}: {e}")
            notify_result(
                title="Cleanup JS errors",
                status="failure",
                details=f"Удалено {deleted} из {total_before}; ошибка: {e}",
            )
            sys.exit(1)

        if n == 0:
            break

        deleted += n
        batches += 1

        print(f"  ✓ батч {batches}: удалено {n}, всего {deleted}")

        # Небольшая пауза, чтобы не перегружать Supabase
        time.sleep(0.5)

    elapsed = round(time.time() - t0, 1)
    print(f"\nГотово: удалено {deleted} из {total_before} за {elapsed} сек")

    notify_result(
        title="Cleanup JS errors",
        status="success",
        details=(f"Удалено {deleted} записей старше {CLEANUP_DAYS} дней "
                 f"за {elapsed} сек"),
        extra_lines=[
            f"Порог: {cutoff_iso}",
            f"Батчей: {batches}",
        ],
    )


if __name__ == "__main__":
    main()
