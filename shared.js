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
            // Supabase не готов — тихо выходим
            _errorSendInFlight = false;
            return;
        }

        // Пытаемся получить user_id (может быть null)
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
        // Защита от лавины
        const now = Date.now();
        if (now - _errorWindowStart > ERR_WINDOW_MS) {
            _errorWindowStart = now;
            _errorQueue = [];
        }
        if (_errorQueue.length >= ERR_MAX_PER_WINDOW) {
            return; // слишком много — пропускаем
        }

        _errorQueue.push(payload);
        // Дебаунс: отправляем батчем через 500 мс
        setTimeout(_sendQueuedErrors, 500);
    }

    function installErrorHandler(extraMeta) {
        if (_errorHandlerInstalled) return;
        _errorHandlerInstalled = true;

        // 1. Синхронные ошибки
        window.addEventListener('error', function (e) {
            try {
                // Игнорируем ошибки от сторонних скриптов (без e.error)
                // и ошибки загрузки ресурсов (target, а не message)
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
        }, true); // capture: true — ловит и на этапе capturing

        // 2. Необработанные отклонения промисов
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
    // Загрузка разделов из Supabase (с fallback на DEFAULT_SECTIONS)
    // ============================================================
    let _sectionsLoaded = null;

    function loadSections(force) {
        if (_sectionsLoaded && !force) return _sectionsLoaded;

        _sectionsLoaded = (async function () {
            const cfg = window.APP_CONFIG;

            if (!cfg) {
                console.error('[loadSections] APP_CONFIG не загружен');
                return {};
            }

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
                    console.log('[loadSections] загружено из Supabase:',
                        Object.keys(cfg.SECTIONS));
                    return cfg.SECTIONS;
                }

                console.warn('[loadSections] Supabase вернул пусто → fallback');
                return applyFallback();
            } catch (e) {
                console.error('[loadSections] исключение:', e);
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
        getSupabaseClient, loadSections,
        installErrorHandler,
    });

    window.toggleDesc = toggleDesc;

    // ─── Автоматически подключаем перехват ошибок, если есть конфиг ───
    // Небольшая задержка: даём config.js и supabase-js прогрузиться.
    if (window.APP_CONFIG) {
        // Уже загружен — сразу
        installErrorHandler();
    } else {
        // Ещё нет — ждём DOMContentLoaded
        document.addEventListener('DOMContentLoaded', function () {
            if (window.APP_CONFIG) {
                installErrorHandler();
            }
        });
    }
})();
