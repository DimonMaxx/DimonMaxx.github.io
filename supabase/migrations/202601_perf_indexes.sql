-- ============================================================
-- Миграция: индексы для производительности админки и аналитики
-- ------------------------------------------------------------
-- Добавляет индексы на временные поля часто используемых таблиц.
-- Все CREATE INDEX идут с IF NOT EXISTS — миграция идемпотентна,
-- можно запускать повторно без последствий.
--
-- Зачем:
--   client_errors  — ORDER BY created_at DESC LIMIT 500 в админке
--   admin_actions  — ORDER BY created_at DESC LIMIT 500 в журнале
--   download_logs  — ORDER BY downloaded_at DESC LIMIT 1000
--   visits         — статистика за год/месяц/неделю/день
--   sync_orphans   — ORDER BY updated_at DESC во вкладке «Осиротевшие»
--   auth_failures  — подготовка к п. 2.4 (логирование неудачных входов)
--
-- Примечание: таблица auth_failures создаётся отдельной миграцией
-- (пункт 2.4 плана). Если таблицы ещё нет — блок с ней просто
-- ничего не сделает благодаря DO ... IF EXISTS.
-- ============================================================


-- ─── client_errors ───
-- Используется в админке: загрузка последних 500 записей,
-- фильтр по периоду (today/week/month/all).
CREATE INDEX IF NOT EXISTS idx_client_errors_created_at
    ON client_errors (created_at DESC);


-- ─── admin_actions ───
-- Журнал действий: последние 500 + фильтр по периоду.
CREATE INDEX IF NOT EXISTS idx_admin_actions_created_at
    ON admin_actions (created_at DESC);


-- ─── download_logs ───
-- История скачиваний: ORDER BY downloaded_at DESC LIMIT 1000,
-- фильтр по периоду (24 ч / неделя / месяц / всё).
CREATE INDEX IF NOT EXISTS idx_download_logs_downloaded_at
    ON download_logs (downloaded_at DESC);


-- ─── visits ───
-- Статистика посещений: за год / месяц / неделю / день.
-- Индекс на created_at покрывает все эти запросы.
CREATE INDEX IF NOT EXISTS idx_visits_created_at
    ON visits (created_at DESC);


-- ─── sync_orphans ───
-- Вкладка «Осиротевшие»: ORDER BY updated_at DESC.
CREATE INDEX IF NOT EXISTS idx_sync_orphans_updated_at
    ON sync_orphans (updated_at DESC);


-- ─── auth_failures (опционально, для п. 2.4) ───
-- Если таблица уже создана — добавит индексы.
-- Если ещё нет — просто ничего не произойдёт.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.tables
         WHERE table_schema = 'public'
           AND table_name = 'auth_failures'
    ) THEN
        CREATE INDEX IF NOT EXISTS idx_auth_failures_created_at
            ON auth_failures (created_at DESC);

        CREATE INDEX IF NOT EXISTS idx_auth_failures_email_hash
            ON auth_failures (email_hash);
    END IF;
END $$;


-- ============================================================
-- Проверка (опционально, только для просмотра результата)
-- ============================================================
-- Раскомментируй, если хочешь убедиться, что индексы созданы:
--
-- SELECT
--     schemaname,
--     tablename,
--     indexname,
--     indexdef
-- FROM pg_indexes
-- WHERE schemaname = 'public'
--   AND tablename IN (
--     'client_errors', 'admin_actions', 'download_logs',
--     'visits', 'sync_orphans', 'auth_failures'
--   )
-- ORDER BY tablename, indexname;
