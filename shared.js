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
        const PAGE_SIZES = window.APP_CONFIG.PAGE_SIZES || [10, 20, 50, 100];
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
                    const totalPages = Math.max(1, Math.ceil(state.totalItems / state.pageSize));
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
                    const totalPages = Math.max(1, Math.ceil(state.totalItems / state.pageSize));
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
    // Скачивание файлов (ПРЯМАЯ ССЫЛКА, БЕЗ ЗАДЕРЖЕК)
    // ============================================================
    function triggerDownload(url, filename) {
        if (!url) return;
        const a = document.createElement('a');
        a.href = url;
        if (filename) a.download = String(filename);
        a.rel = 'noopener noreferrer';
        a.target = '_blank'; // Открываем в новой вкладке
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
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
    function buildProxyUrl(downloadUrl, fileName) {
        if (!downloadUrl) return '';
        const urlStr = String(downloadUrl);

        // 1. Уже готовый release-прокси (Cloudflare Worker) → возвращаем как есть
        if (/^https:\/\/gh-release-proxy\.[^/]+\//i.test(urlStr)) {
            return urlStr;
        }

        // 2. Legacy: TeraBox / Яндекс → через Supabase (если такие еще остались)
        try {
            const cfg = window.APP_CONFIG;
            const SUPABASE_URL = cfg && cfg.SUPABASE_URL ? cfg.SUPABASE_URL : '';
            const parsed = new URL(urlStr);
            const host = parsed.hostname.toLowerCase();

            if (host.includes('terabox') || host.includes('1024tera') || host.includes('4funbox')) {
                let fname = fileName && String(fileName).trim();
                if (!fname) fname = 'file.bin';
                if (!/\.[a-z0-9]{1,6}$/i.test(fname)) fname += '.bin';
                return `${SUPABASE_URL}/functions/v1/terabox-download?url=${encodeURIComponent(urlStr)}&name=${encodeURIComponent(fname)}`;
            }

            if (host.includes('disk.yandex') || host.includes('yadi.sk')) {
                let fname = fileName && String(fileName).trim();
                if (!fname) fname = 'file.bin';
                if (!/\.[a-z0-9]{1,6}$/i.test(fname)) fname += '.bin';
                return `${SUPABASE_URL}/functions/v1/yandex-download?url=${encodeURIComponent(urlStr)}&name=${encodeURIComponent(fname)}`;
            }
        } catch (e) {
            // Если URL кривой, просто вернем как есть
        }

        // 3. Прямые ссылки (обычно не используется)
        return urlStr;
    }

    // ============================================================
    // Экспорт в window.MF
    // ============================================================
    window.MF = {
        escapeHtml,
        escapeAttr,
        slugify,
        renderPagination,
        scrollToContainer,
        attachPaginationHandlers,
        triggerDownload,
        toggleDesc,
        formatDateRu,
        buildProxyUrl
    };
})();