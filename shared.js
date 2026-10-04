/* shared.js — общие утилиты MyFiles */
(function () {
    'use strict';

    // ============================================================
    // Экранирование
    // ============================================================
    function escapeHtml(str) {
        if (str === null || str === undefined) return '';
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }
    function escapeAttr(str) {
        if (str === null || str === undefined) return '';
        return String(str).replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // ============================================================
    // Slug
    // ============================================================
    function slugify(text) {
        if (!text) return '';
        let slug = text.replace(/[^a-zA-Z0-9а-яА-ЯёЁ\s\-]/g, '').trim().toLowerCase();
        return slug.replace(/[\s\-]+/g, '-');
    }

    // ============================================================
    // Пагинация
    // ============================================================
    function getMaxPageButtons() {
        const w = window.innerWidth;
        if (w < 480) return 5;
        if (w < 768) return 7;
        return 11;
    }

    function getVisiblePages(currentPage, totalPages) {
        const MAX = getMaxPageButtons();
        const pages = [];
        if (totalPages <= MAX) {
            for (let i = 1; i <= totalPages; i++) pages.push(i);
            return pages;
        }
        const half = Math.floor(MAX / 2);
        let start = currentPage - half;
        let end = start + MAX - 1;
        if (start < 1) { start = 1; end = MAX; }
        if (end > totalPages) { end = totalPages; start = end - MAX + 1; }
        for (let i = start; i <= end; i++) pages.push(i);
        return pages;
    }

    function renderPagination(containerId, totalItems, totalPages, state, position) {
        position = position === 'top' ? 'top' : 'bottom';
        const PAGE_SIZES = window.APP_CONFIG.PAGE_SIZES;
        const sizes = PAGE_SIZES.map(sz =>
            `<option value="${sz}"${state.pageSize === sz ? ' selected' : ''}>${sz}</option>`
        ).join('');
        const visible = getVisiblePages(state.currentPage, totalPages);
        const pageNums = visible.map(p =>
            `<button class="page-num${p === state.currentPage ? ' active' : ''}" data-page="${p}">${p}</button>`
        ).join('');
        return `
            <div class="pagination-bar pagination-${position}"
                 data-pagination-for="${escapeAttr(containerId)}"
                 data-position="${position}">
                <div class="pagination-total">Всего: <strong>${totalItems}</strong> • Стр. <strong>${state.currentPage}</strong> из <strong>${totalPages}</strong></div>
                <div class="pagination-controls">
                    <label>Показывать по:
                        <select class="page-size-select" data-container="${escapeAttr(containerId)}">${sizes}</select>
                    </label>
                    <button class="page-btn prev-btn" data-container="${escapeAttr(containerId)}" ${state.currentPage <= 1 ? 'disabled' : ''}><i class="fas fa-chevron-left"></i></button>
                    <div class="page-numbers" data-container="${escapeAttr(containerId)}">${pageNums}</div>
                    <button class="page-btn next-btn" data-container="${escapeAttr(containerId)}" ${state.currentPage >= totalPages ? 'disabled' : ''}><i class="fas fa-chevron-right"></i></button>
                    <div class="page-jump">
                        <label>Стр.:</label>
                        <input type="number" class="page-jump-input" data-container="${escapeAttr(containerId)}" min="1" max="${totalPages}" placeholder="#">
                        <button class="page-jump-btn" data-container="${escapeAttr(containerId)}">Перейти</button>
                    </div>
                </div>
            </div>
        `;
    }

    function scrollToContainer(el, offset) {
        if (!el) return;
        const off = typeof offset === 'number' ? offset : 100;
        const top = el.getBoundingClientRect().top + window.scrollY - off;
        window.scrollTo({ top: Math.max(0, top), behavior: 'smooth' });
    }

    function attachPaginationHandlers(container, containerId, state, onRender, opts) {
        if (!state || !container) return;
        opts = opts || {};
        const scrollOffset = typeof opts.scrollOffset === 'number' ? opts.scrollOffset : 100;

        const bars = container.querySelectorAll(
            `.pagination-bar[data-pagination-for="${containerId}"]`
        );
        if (!bars.length) return;

        const doScroll = () => {
            let target = null;
            if (opts.scrollTarget) {
                if (typeof opts.scrollTarget === 'string') {
                    target = container.querySelector(opts.scrollTarget);
                } else if (opts.scrollTarget instanceof HTMLElement) {
                    target = opts.scrollTarget;
                }
            }
            if (!target) {
                target = container.querySelector('.content-table-wrapper') || container;
            }
            scrollToContainer(target, scrollOffset);
        };

        const afterRender = () => {
            onRender();
            setTimeout(doScroll, 60);
        };

        bars.forEach(bar => {
            const sizeSelect = bar.querySelector('.page-size-select');
            if (sizeSelect) {
                sizeSelect.addEventListener('change', function () {
                    state.pageSize = parseInt(this.value, 10) || 10;
                    state.currentPage = 1;
                    afterRender();
                });
            }

            const prevBtn = bar.querySelector('.prev-btn');
            if (prevBtn) {
                prevBtn.addEventListener('click', function () {
                    if (state.currentPage > 1) {
                        state.currentPage--;
                        afterRender();
                    }
                });
            }

            const nextBtn = bar.querySelector('.next-btn');
            if (nextBtn) {
                nextBtn.addEventListener('click', function () {
                    const totalPages = Math.max(1,
                        Math.ceil(state.totalItems / state.pageSize));
                    if (state.currentPage < totalPages) {
                        state.currentPage++;
                        afterRender();
                    }
                });
            }

            bar.querySelectorAll('.page-num[data-page]').forEach(btn => {
                btn.addEventListener('click', function () {
                    const p = parseInt(this.dataset.page, 10);
                    if (!isNaN(p) && p !== state.currentPage) {
                        state.currentPage = p;
                        afterRender();
                    }
                });
            });

            const jumpBtn = bar.querySelector('.page-jump-btn');
            const jumpInput = bar.querySelector('.page-jump-input');
            if (jumpBtn && jumpInput) {
                const doJump = () => {
                    const totalPages = Math.max(1,
                        Math.ceil(state.totalItems / state.pageSize));
                    let p = parseInt(jumpInput.value, 10);
                    if (isNaN(p)) p = 1;
                    if (p < 1) p = 1;
                    if (p > totalPages) p = totalPages;
                    state.currentPage = p;
                    afterRender();
                };
                jumpBtn.addEventListener('click', doJump);
                jumpInput.addEventListener('keydown', function (e) {
                    if (e.key === 'Enter') { e.preventDefault(); doJump(); }
                });
            }
        });
    }

    // ============================================================
    // Прочие утилиты
    // ============================================================
    function toggleDesc(btn) {
        const cell = btn.closest('td');
        if (!cell) return;
        const shortEl = cell.querySelector('.desc-short');
        const fullEl = cell.querySelector('.desc-full');
        if (!shortEl || !fullEl) return;
        if (fullEl.style.display === 'block') {
            fullEl.style.display = 'none';
            shortEl.style.display = '-webkit-box';
            btn.textContent = 'Развернуть';
        } else {
            fullEl.style.display = 'block';
            shortEl.style.display = 'none';
            btn.textContent = 'Свернуть';
        }
    }

    function triggerDownload(url, filename) {
        const a = document.createElement('a');
        a.href = url;
        if (filename) a.download = String(filename);
        a.rel = 'noopener';
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    }

    function formatDateRu(date) {
        if (!date) return '—';
        const d = date instanceof Date ? date : new Date(date);
        if (isNaN(d.getTime())) return '—';
        return d.toLocaleDateString('ru-RU') + ' ' +
               d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });
    }

    // ============================================================
    // Прокси-ссылки для скачивания
    // ============================================================
    // Единый источник правды: определяет источник по домену URL и
    // формирует ссылку на соответствующую Edge Function.
    //   TeraBox  → /functions/v1/terabox-download?url=...&name=...
    //   Яндекс   → /functions/v1/yandex-download?folder=...&path=...
    // Прочие   → исходный URL без изменений
    // ============================================================
    function buildProxyUrl(downloadUrl, fileName) {
        if (!downloadUrl) return '';
        try {
            const cfg = window.APP_CONFIG;
            const SUPABASE_URL = cfg && cfg.SUPABASE_URL
                ? cfg.SUPABASE_URL
                : '';

            const parsed = new URL(downloadUrl);
            const host = parsed.hostname.toLowerCase();

            // ─── TeraBox ───
            if (host.includes('terabox')
                || host.includes('1024tera')
                || host.includes('4funbox')
                || host.includes('teraboxapp')) {
                let fname = fileName && String(fileName).trim();
                if (!fname) {
                    const fromPath = parsed.searchParams.get('path');
                    fname = fromPath
                        ? decodeURIComponent(fromPath).split('/').pop()
                        : 'file.bin';
                }
                if (!/\.[a-z0-9]{1,6}$/i.test(fname)) fname += '.bin';
                return `${SUPABASE_URL}/functions/v1/terabox-download`
                     + `?url=${encodeURIComponent(downloadUrl)}`
                     + `&name=${encodeURIComponent(fname)}`;
            }

            // ─── Яндекс.Диск ───
            const folder = `${parsed.origin}${parsed.pathname}`;
            const path = parsed.searchParams.get('path');
            if (!folder || !path) return downloadUrl;
            return `${SUPABASE_URL}/functions/v1/yandex-download`
                 + `?folder=${encodeURIComponent(folder)}`
                 + `&path=${encodeURIComponent(path)}`;
        } catch (e) { return downloadUrl; }
    }

    // ============================================================
    // Определение MIME-типа аудио по расширению
    // ============================================================
    function getAudioMimeType(url) {
        if (!url) return '';
        const m = String(url).match(/\.([a-zA-Z0-9]+)(?:\?|$)/);
        const ext = m ? m[1].toLowerCase() : '';
        const map = {
            mp3:  'audio/mpeg',
            flac: 'audio/flac',
            wav:  'audio/wav',
            ogg:  'audio/ogg',
            m4a:  'audio/mp4',
            aac:  'audio/aac',
            wma:  'audio/x-ms-wma',
            opus: 'audio/opus',
            ape:  'audio/x-ape',
            aiff: 'audio/aiff',
            alac: 'audio/mp4'
        };
        return map[ext] || '';
    }

    // ============================================================
    // Supabase client (singleton)
    // ============================================================
    let _supabaseClient = null;
    function getSupabaseClient() {
        if (_supabaseClient) return _supabaseClient;
        if (!window.supabase) throw new Error('Supabase SDK не загружен');
        const cfg = window.APP_CONFIG;
        if (!cfg) throw new Error('config.js не загружен');
        _supabaseClient = window.supabase.createClient(cfg.SUPABASE_URL, cfg.SUPABASE_ANON_KEY);
        return _supabaseClient;
    }

    // ============================================================
    // Таймаут-обёртка
    // ============================================================
    function _withTimeout(promise, ms, label) {
        return new Promise((resolve, reject) => {
            const t = setTimeout(() => {
                reject(new Error(`${label}: таймаут ${ms}ms`));
            }, ms);
            promise.then(
                v => { clearTimeout(t); resolve(v); },
                e => { clearTimeout(t); reject(e); }
            );
        });
    }

    // ============================================================
    // ЛОГИРОВАНИЕ JS-ОШИБОК В SUPABASE
    // ============================================================
    // Защита от лавины: не более 5 ошибок в минуту с одной вкладки.
    // Защита от бесконечного цикла: если ошибка возникла внутри самой
    // отправки — не пытаемся снова.
    let _errorQueue = [];
    let _errorWindowStart = Date.now();
    let _errorSendInFlight = false;
    let _errorHandlerInstalled = false;

    const ERR_MAX_PER_WINDOW = 5;
    const ERR_WINDOW_MS      = 60 * 1000; // 1 минута

    function _truncate(s, n) {
        if (!s) return '';
        const str = String(s);
        return str.length > n ? str.slice(0, n) : str;
    }

    function _sendQueuedErrors() {
        if (_errorSendInFlight) return;
        if (_errorQueue.length === 0) return;

        _errorSendInFlight = true;
        const batch = _errorQueue.splice(0, _errorQueue.length);

        let client;
        try {
            client = getSupabaseClient();
        } catch (_) {
            _errorSendInFlight = false;
            return;
        }

        client.auth.getUser().then(({ data }) => {
            const userId = data?.user?.id || null;
            const rows = batch.map(item => ({
                user_id:    userId,
                page:       item.page,
                message:    item.message,
                stack:      item.stack,
                user_agent: item.user_agent,
                meta:       item.meta || null,
            }));

            client.from('client_errors').insert(rows).then(
                () => { _errorSendInFlight = false; },
                () => { _errorSendInFlight = false; }
            );
        }).catch(() => {
            _errorSendInFlight = false;
        });
    }

    function _pushError(payload) {
        const now = Date.now();
        if (now - _errorWindowStart > ERR_WINDOW_MS) {
            _errorWindowStart = now;
            _errorQueue = [];
        }
        if (_errorQueue.length >= ERR_MAX_PER_WINDOW) {
            return;
        }

        _errorQueue.push(payload);
        setTimeout(_sendQueuedErrors, 500);
    }

    function installErrorHandler(extraMeta) {
        if (_errorHandlerInstalled) return;
        _errorHandlerInstalled = true;

        window.addEventListener('error', function (e) {
            try {
                if (!e.message && !e.error) return;

                const message = e.message || String(e.error && e.error.message) || 'Unknown error';
                const stack   = (e.error && e.error.stack) || `${e.filename || ''}:${e.lineno || 0}:${e.colno || 0}`;

                _pushError({
                    page:       window.location.pathname,
                    message:    _truncate(message, 500),
                    stack:      _truncate(stack, 2000),
                    user_agent: _truncate(navigator.userAgent, 500),
                    meta:       extraMeta || null,
                });
            } catch (_) { /* сам хендлер не должен падать */ }
        }, true);

        window.addEventListener('unhandledrejection', function (e) {
            try {
                const reason = e.reason;
                let message;
                let stack;

                if (reason instanceof Error) {
                    message = reason.message;
                    stack   = reason.stack;
                } else if (typeof reason === 'string') {
                    message = reason;
                    stack   = '';
                } else {
                    try {
                        message = 'Unhandled rejection: ' + JSON.stringify(reason).slice(0, 500);
                    } catch (_) {
                        message = 'Unhandled rejection: ' + String(reason);
                    }
                    stack = '';
                }

                _pushError({
                    page:       window.location.pathname,
                    message:    _truncate('Unhandled: ' + message, 500),
                    stack:      _truncate(stack, 2000),
                    user_agent: _truncate(navigator.userAgent, 500),
                    meta:       extraMeta || null,
                });
            } catch (_) { /* ignore */ }
        });
    }

    // ============================================================
    // Безопасная замена содержимого SECTIONS
    // ============================================================
    function _replaceSections(cfg, newSections) {
        if (!cfg.SECTIONS || typeof cfg.SECTIONS !== 'object') {
            cfg.SECTIONS = {};
        }
        Object.keys(cfg.SECTIONS).forEach(k => { delete cfg.SECTIONS[k]; });
        Object.keys(newSections).forEach(k => { cfg.SECTIONS[k] = newSections[k]; });
    }

    // ============================================================
    // КЭШ site_sections В localStorage
    // ============================================================
    // Схема:
    //   localStorage['mf_site_sections_v1'] = {
    //       ts: <timestamp ms>,
    //       sections: { key: { label, icon, json, ... }, ... }
    //   }
    //
    // Зачем:
    //   При каждом открытии страницы идёт fetch site_sections из Supabase.
    //   Это 200-500 мс. Кэш на 5 минут убирает эти запросы почти полностью.
    //
    // Инвалидация:
    //   - Автоматически по TTL (5 минут).
    //   - Вручную через MF.invalidateSectionsCache() — вызывать из админки
    //     после создания/редактирования/удаления раздела.
    //
    // Версия в ключе (_v1) — если изменится структура sections,
    // достаточно поменять на _v2, и старый кэш не помешает.
    // ============================================================

    const SECTIONS_CACHE_KEY    = 'mf_site_sections_v1';
    const SECTIONS_CACHE_TTL_MS = 5 * 60 * 1000;  // 5 минут

    function _readSectionsCache(force) {
        if (force) return null;
        try {
            const raw = localStorage.getItem(SECTIONS_CACHE_KEY);
            if (!raw) return null;
            const parsed = JSON.parse(raw);
            if (!parsed || !parsed.sections || !parsed.ts) return null;
            const age = Date.now() - Number(parsed.ts);
            if (age > SECTIONS_CACHE_TTL_MS) {
                // кэш протух — удаляем, чтобы не занимал место
                localStorage.removeItem(SECTIONS_CACHE_KEY);
                return null;
            }
            return parsed.sections;
        } catch (e) {
            console.warn('[sections cache] read failed:', e);
            return null;
        }
    }

    function _writeSectionsCache(sections) {
        try {
            const payload = {
                ts: Date.now(),
                sections: sections || {},
            };
            localStorage.setItem(SECTIONS_CACHE_KEY, JSON.stringify(payload));
        } catch (e) {
            // localStorage может быть переполнен или отключён (приватный режим)
            console.warn('[sections cache] write failed:', e);
        }
    }

    function invalidateSectionsCache() {
        try {
            localStorage.removeItem(SECTIONS_CACHE_KEY);
        } catch (_) { /* ignore */ }
        // Сбрасываем и внутрисессионный промис-мемоизатор,
        // чтобы следующий вызов loadSections() пошёл в Supabase
        _sectionsLoaded = null;
    }

    // ============================================================
    // Загрузка разделов из Supabase (с кэшем + fallback на DEFAULT_SECTIONS)
    // ============================================================
    //
    // Приоритеты:
    //   1. force=true               → игнорировать кэш, идти в Supabase
    //   2. localStorage (свежий)    → использовать мгновенно
    //   3. Supabase (успех)         → записать в localStorage и применить
    //   4. Supabase (ошибка)        → старый localStorage или DEFAULT_SECTIONS
    //
    // Возвращает Promise<объект SECTIONS>.
    // ============================================================
    let _sectionsLoaded = null;

    function loadSections(force) {
        // Если force=true — сбросить мемоизацию внутри сессии
        if (force) {
            _sectionsLoaded = null;
        }
        if (_sectionsLoaded && !force) return _sectionsLoaded;

        _sectionsLoaded = (async function () {
            const cfg = window.APP_CONFIG;

            if (!cfg) {
                console.error('[loadSections] APP_CONFIG не загружен');
                return {};
            }

            // ─── 1. Попытка взять из localStorage ───
            const cached = _readSectionsCache(force);
            if (cached) {
                console.log('[loadSections] из localStorage (кэш):',
                    Object.keys(cached));
                _replaceSections(cfg, cached);
                // Дальше не идём — используем кэш.
                // Если хочешь ещё и «фоновое обновление» — раскомментируй блок ниже.
                //
                // _refreshSectionsInBackground(cfg);
                //
                return cfg.SECTIONS;
            }

            // ─── 2. Идём в Supabase ───
            const applyFallback = () => {
                console.warn('[loadSections] → fallback на DEFAULT_SECTIONS');
                _replaceSections(cfg, cfg.DEFAULT_SECTIONS || {});
                return cfg.SECTIONS;
            };

            try {
                const client = getSupabaseClient();

                const { data, error } = await _withTimeout(
                    client
                        .from('site_sections')
                        .select('key,label,icon,json_path,container,folderable,columns,sort_order,is_active,manual_override')
                        .eq('is_active', true)
                        .order('sort_order', { ascending: true }),
                    8000,
                    'site_sections'
                );

                if (error) {
                    console.error('[loadSections] Supabase error:', error);
                    return applyFallback();
                }

                if (Array.isArray(data) && data.length > 0) {
                    const sections = {};
                    data.forEach(row => {
                        if (!row || !row.key) return;
                        sections[row.key] = {
                            label: row.label || row.key,
                            icon: row.icon || 'fa-folder',
                            json: row.json_path || '',
                            container: row.container || (row.key + '-container'),
                            folderable: !!row.folderable,
                            columns: Array.isArray(row.columns) ? row.columns : [],
                            manual_override: !!row.manual_override,
                            sort_order: row.sort_order || 100,
                        };
                    });
                    const sorted = {};
                    Object.entries(sections)
                        .sort((a, b) => (a[1].sort_order || 100) - (b[1].sort_order || 100))
                        .forEach(([k, v]) => { sorted[k] = v; });

                    _replaceSections(cfg, sorted);

                    // ─── Записываем в localStorage ───
                    _writeSectionsCache(sorted);

                    console.log('[loadSections] из Supabase (свежие):',
                        Object.keys(cfg.SECTIONS));
                    return cfg.SECTIONS;
                }

                console.warn('[loadSections] Supabase вернул пусто → fallback');
                return applyFallback();
            } catch (e) {
                console.error('[loadSections] исключение:', e);
                // Если есть устаревший кэш — лучше использовать его,
                // чем DEFAULT_SECTIONS (вдруг разделы кастомные).
                try {
                    const raw = localStorage.getItem(SECTIONS_CACHE_KEY);
                    if (raw) {
                        const parsed = JSON.parse(raw);
                        if (parsed && parsed.sections) {
                            console.warn('[loadSections] используем устаревший кэш');
                            _replaceSections(cfg, parsed.sections);
                            return cfg.SECTIONS;
                        }
                    }
                } catch (_) { /* ignore */ }
                return applyFallback();
            }
        })();

        return _sectionsLoaded;
    }

    // ============================================================
    // Экспорт
    // ============================================================
    window.MF = Object.freeze({
        escapeHtml, escapeAttr, slugify,
        getMaxPageButtons, getVisiblePages,
        renderPagination, attachPaginationHandlers,
        scrollToContainer,
        toggleDesc, triggerDownload, formatDateRu,
        buildProxyUrl, getAudioMimeType,
        getSupabaseClient, loadSections,
        invalidateSectionsCache,
        installErrorHandler,
    });

    window.toggleDesc = toggleDesc;

    // ─── Автоматически подключаем перехват ошибок, если есть конфиг ───
    if (window.APP_CONFIG) {
        installErrorHandler();
    } else {
        document.addEventListener('DOMContentLoaded', function () {
            if (window.APP_CONFIG) {
                installErrorHandler();
            }
        });
    }
})();
