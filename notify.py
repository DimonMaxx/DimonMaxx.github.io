# notify.py
# -*- coding: utf-8 -*-
"""
Отправка уведомлений в Telegram.

Использование:
    from notify import notify_telegram, notify_result

    # Простое сообщение
    notify_telegram("Текст сообщения")

    # Стандартный отчёт о результате (со смайликом, ссылкой на run)
    notify_result(
        title="Sync TeraBox",
        status="success",
        details="Обновлено: 12, добавлено: 843",
        extra_lines=["Программы: +843 / ~12"],
        run_url="https://github.com/.../runs/12345",
    )

Переменные окружения:
    TELEGRAM_BOT_TOKEN — токен бота (из @BotFather)
    TELEGRAM_CHAT_ID   — ID чата / группы / канала

Если переменные не заданы — все функции становятся no-op и возвращают False.
Скрипты, которые импортируют модуль, работают без изменений.
"""

import os
import logging
import requests

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"

# Telegram ограничивает длину текста сообщения 4096 символами.
# Оставляем небольшой запас на служебные символы и служебный хвост.
MAX_MSG_LEN = 3900


# ============================================================
# ВСПОМОГАТЕЛЬНОЕ
# ============================================================

def _escape_md(text):
    """
    Экранирует спецсимволы для Telegram MarkdownV2.

    MarkdownV2 требует экранировать: _ * [ ] ( ) ~ ` > # + - = | { } . !

    Используется только когда parse_mode='MarkdownV2'.
    """
    if text is None:
        return ""
    s = str(text)
    special = "_*[]()~`>#+-=|{}.!"
    return "".join(("\\" + ch) if ch in special else ch for ch in s)


def _truncate(text, limit=MAX_MSG_LEN):
    """Обрезает слишком длинное сообщение с многоточием."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit - 3] + "..."


def is_telegram_enabled():
    """Возвращает True, если токен и chat_id настроены."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN")
                and os.environ.get("TELEGRAM_CHAT_ID"))


# ============================================================
# ОТПРАВКА
# ============================================================

def notify_telegram(text, parse_mode=None, silent=False, timeout=15):
    """
    Отправляет одно сообщение в Telegram.

    :param text:       текст сообщения
    :param parse_mode: 'MarkdownV2' | 'HTML' | None (plain text)
    :param silent:     True — без звука у получателя
    :param timeout:    таймаут HTTP-запроса (сек)
    :return:           True при успехе, False иначе
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.info("Telegram не настроен (нет TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID)")
        return False

    if not text:
        return False

    text = _truncate(text)

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True,
        "disable_notification": bool(silent),
    }

    if parse_mode:
        payload["parse_mode"] = parse_mode
        if parse_mode == "MarkdownV2":
            # Применяем экранирование только здесь, чтобы вызывающий мог
            # передать текст с уже готовой разметкой или без неё — единообразно.
            payload["text"] = _escape_md(text)

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"

    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except requests.exceptions.Timeout:
        logger.warning("Telegram: timeout после %s сек", timeout)
        return False
    except requests.exceptions.RequestException as e:
        logger.warning("Telegram: сетевая ошибка: %s", e)
        return False
    except Exception as e:
        logger.warning("Telegram: неожиданная ошибка: %s", e)
        return False

    if r.status_code == 200:
        return True

    # Тело ответа может содержать причину (например, chat not found,
    # message is too long, can't parse entities).
    try:
        detail = r.text[:300]
    except Exception:
        detail = "<no body>"

    logger.warning("Telegram HTTP %s: %s", r.status_code, detail)
    return False


def notify_result(title, status, details="", extra_lines=None,
                  run_url=None, silent=False):
    """
    Отправляет стандартизованное сообщение о завершении job/скрипта.

    :param title:       заголовок (например, "Sync TeraBox")
    :param status:      "success" | "failure" | "cancelled" | любое (по умолчанию ℹ️)
    :param details:     одна короткая строка (необязательно)
    :param extra_lines: список дополнительных строк (необязательно)
    :param run_url:     ссылка на запуск в GitHub Actions (необязательно)
    :param silent:      True — без звука
    :return:            True при успехе, False иначе
    """
    emoji = {
        "success":   "✅",
        "failure":   "❌",
        "cancelled": "⚠️",
        "warning":   "⚠️",
    }.get((status or "").lower(), "ℹ️")

    # Формируем plain-текст, экранирование MarkdownV2 произойдёт внутри
    # notify_telegram. Здесь мы только собираем строки в естественном виде.
    lines = [f"{emoji} {title}"]

    if details:
        lines.append(details)

    if extra_lines:
        for ln in extra_lines:
            if ln:
                lines.append(str(ln))

    if run_url:
        # Ссылку не экранируем — Telegram MarkdownV2 требует особого
        # формата ссылок. Используем "инлайн-ссылку" [текст](URL),
        # для этого экранирование url не нужно, только текст.
        lines.append(f"[Открыть запуск]({run_url})")

    text = "\n".join(lines)

    # Для ссылки внутри MarkdownV2 надо обработать отдельно:
    # markdown escape портит сам url. Поэтому собираем вручную:
    if run_url:
        text_escaped_lines = []
        text_escaped_lines.append(f"{emoji} {_escape_md(title)}")
        if details:
            text_escaped_lines.append(_escape_md(details))
        if extra_lines:
            for ln in extra_lines:
                if ln:
                    text_escaped_lines.append(_escape_md(ln))
        text_escaped_lines.append(f"[Открыть запуск]({run_url})")
        final_text = "\n".join(text_escaped_lines)
        return _send_raw(final_text, silent=silent)

    # Без ссылки — обычный путь
    return notify_telegram(text, parse_mode="MarkdownV2", silent=silent)


def _send_raw(escaped_text, silent=False, timeout=15):
    """
    Отправляет уже готовый MarkdownV2 (с экранированием и ссылками).
    Используется внутри notify_result, чтобы не экранировать URL.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        return False

    payload = {
        "chat_id": chat_id,
        "text": _truncate(escaped_text),
        "parse_mode": "MarkdownV2",
        "disable_web_page_preview": True,
        "disable_notification": bool(silent),
    }

    url = f"{TELEGRAM_API}/bot{token}/sendMessage"

    try:
        r = requests.post(url, json=payload, timeout=timeout)
    except Exception as e:
        logger.warning("Telegram _send_raw: %s", e)
        return False

    if r.status_code == 200:
        return True

    try:
        detail = r.text[:300]
    except Exception:
        detail = "<no body>"
    logger.warning("Telegram HTTP %s (raw): %s", r.status_code, detail)
    return False


# ============================================================
# БЫСТРАЯ ПРОВЕРКА
# ============================================================

if __name__ == "__main__":
    """
    Запуск напрямую:
        python notify.py

    Отправляет тестовое сообщение, чтобы проверить связку
    TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if not is_telegram_enabled():
        print("✗ Telegram не настроен.")
        print("  Проверьте переменные окружения:")
        print("    TELEGRAM_BOT_TOKEN — задан:", bool(os.environ.get("TELEGRAM_BOT_TOKEN")))
        print("    TELEGRAM_CHAT_ID   — задан:", bool(os.environ.get("TELEGRAM_CHAT_ID")))
        raise SystemExit(1)

    ok = notify_result(
        title="Проверка notify.py",
        status="success",
        details="Если вы видите это сообщение — всё настроено правильно.",
        extra_lines=[
            "Источник: notify.py → __main__",
            "Проверка выполнена вручную",
        ],
    )

    if ok:
        print("✓ Сообщение отправлено. Проверьте Telegram.")
    else:
        print("✗ Не удалось отправить сообщение. Смотрите логи выше.")
        raise SystemExit(1)
