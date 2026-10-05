/* ============================================================
   app-core.js — ядро главной страницы MyFiles
   Содержит: состояние, утилиты, авторизацию, статистику,
             топ-10 с фильтром удалённых и подтягиванием
             актуальных названий, модалку обновления контента,
             hash-роутинг (deep-link на раздел/папку/файл),
             копирование ссылки в буфер, switchTab, bindNav.
   Рендеры разделов/папок/таблиц живут в app-content.js.

   Hash-роутинг:
   - #home / ''            → главная
   - #top10                → топ-10
   - #programs             → раздел, сетка папок
   - #programs/Converter   → раздел, папка Converter
   - #programs/file-slug   → раздел, фильтр по файлу + скролл к строке
   ============================================================ */
(function () {
    'use strict';

    // Ссылки на глобальные утилиты (загружены из config.js и shared.js)
    const CFG = window.APP_CONFIG;
    const MF  = window.MF;
    const supabaseClient = MF.getSupabaseClient();
    const SUPABASE_URL   = CFG.SUPABASE_URL;

    // ============================================================
    // ОБЩЕЕ СОСТОЯНИЕ (доступно обоим модулям через window.MFState)
    // ============================================================
    const state = {
        currentUser:    null,
        currentProfile: null,
        currentTab:     'home',
        loadedSections: new Set(),
        tableStates:    {},
        sectionRenderers: {},
        extraFolders:   {},
        downloadCounts: {},
    };

    // ============================================================
    // ТОП-10: КЭШ JSON-ИНДЕКСА
    // ============================================================
    let _top10SectionCache = null;
    let _top10SectionCacheTs = 0;
    const TOP10_CACHE_TTL_MS = 5 * 60 * 1000;
    let _top10FirstLoadDone = false;
    let _top10Debug = true;

    function _top10log(...args) {
        if (_top10Debug) console.log('[top10]', ...args);
    }

    // ============================================================
    // HASH-РОУТИНГ: ФЛАГИ И УТИЛИТЫ
    // ============================================================
    let _suppressHashchange = false;       // не реагировать на hashchange
    let _applyHashRouteInProgress = false; // защита от параллельных вызовов

    /**
     * Разбирает location.hash в объект.
     * Возвращает { tab, segment } | null.
     *   ''                        → null
     *   '#home'                   → { tab: 'home', segment: null }
     *   '#top10'                  → { tab: 'top10', segment: null }
     *   '#programs'               → { tab: 'programs', segment: null }
     *   '#programs/Converter'     → { tab: 'programs', segment: 'Converter' }
     *   '#programs/some-file-id'  → { tab: 'programs', segment: 'some-file-id' }
     */
    function parseHash() {
        let raw = location.hash || '';
        if (raw.startsWith('#')) raw = raw.slice(1);
        if (!raw) return null;

        const parts = raw.split('/').filter(Boolean);
        if (!parts.length) return null;

        const tab = parts[0];
        let segment = null;
        if (parts.length >= 2) {
            // Папка или file_id могут содержать пробелы/кириллицу —
            // декодируем каждый сегмент.
            try { segment = decodeURIComponent(parts.slice(1).join('/')); }
            catch (_) { segment = parts.slice(1).join('/'); }
        }
        return { tab, segment };
    }

    /**
     * Устанавливает location.hash.
     *   setHash('home')                → URL без хэша
     *   setHash('top10')               → #top10
     *   setHash('programs')            → #programs
     *   setHash('programs', 'Converter') → #programs/Converter
     *
     * Пока hash меняется, поднимаем флаг _suppressHashchange,
     * чтобы не запустить applyHashRoute повторно.
     */
    function setHash(tab, segment) {
        let newHash = '';
        if (tab && tab !== 'home') {
            newHash = '#' + tab;
            if (segment) {
                newHash += '/' + encodeURIComponent(segment);
            }
        }
        if (location.hash === newHash) return;

        _suppressHashchange = true;
        if (newHash) {
            location.hash = newHash;
        } else {
            // Убираем хэш полностью (без перезагрузки страницы)
            history.replaceState(
                null, '',
                location.pathname + location.search
            );
        }
        // Снимаем флаг асинхронно — hashchange уже не сработает
        setTimeout(() => { _suppressHashchange = false; }, 80);
    }

    /**
     * Ждёт, пока раздел загрузит JSON (или пока не истечёт таймаут).
     */
    async function _waitForSectionLoaded(tabId) {
        const meta = CFG.SECTIONS[tabId];
        if (!meta) return;
        const maxAttempts = 60; // 60 × 100 мс = 6 секунд
        for (let i = 0; i < maxAttempts; i++) {
            const st = state.tableStates[meta.container];
            if (st && Array.isArray(st.data)) return;
            await new Promise(r => setTimeout(r, 100));
        }
    }

    /**
     * Применяет текущий location.hash.
     * Логика:
     *   1. Парсим хэш.
     *   2. Если tab невалидный → переключаемся на home.
     *   3. switchTab(tab, { skipHash: true }).
     *   4. Если есть segment — ждём загрузки раздела и решаем,
     *      это папка или file_id, применяем фильтр и скролл.
     */
    async function applyHashRoute() {
        if (_applyHashRouteInProgress) return;
        _applyHashRouteInProgress = true;

        try {
            const route = parseHash();
            if (!route) {
                // Пустой хэш → главная
                switchTab('home', { skipHash: true });
                return;
            }

            const { tab, segment } = route;

            if (tab === 'home' || (!CFG.SECTIONS[tab] && tab !== 'top10')) {
                switchTab('home', { skipHash: true });
                return;
            }

            if (tab === 'top10') {
                switchTab('top10', { skipHash: true });
                return;
            }

            // ─── Раздел ───
            switchTab(tab, { skipHash: true });

            if (!segment) return;

            // Ждём загрузку данных
            await _waitForSectionLoaded(tab);

            const meta = CFG.SECTIONS[tab];
            if (!meta) return;
            const st = state.tableStates[meta.container];
            if (!st || !Array.isArray(st.data) || st.data.length === 0) return;

            const container = document.getElementById(meta.container);
            const renderFn  = state.sectionRenderers[meta.container];
            if (!container || !renderFn) return;

            // ─── Это файл? ───
            const segmentLower = String(segment).toLowerCase();
            const fileItem = st.data.find(item => {
                const fid = (item.file_id || MF.slugify(item.title || '')).toLowerCase();
                return fid === segmentLower;
            });

            if (fileItem) {
                _top10log('applyHashRoute: file found', fileItem.file_id || fileItem.title);
                st.viewMode = 'table';
                st.folderFilter = null;
                st.sortKey = null;
                st.sortDir = 'asc';
                st.currentPage = 1;
                st.searches = { title: fileItem.title || '' };

                window.MFApp.renderSection(meta.container, container, renderFn);

                // Скроллим и подсвечиваем строку
                setTimeout(() => {
                    window.MFApp.highlightFileRow?.(
                        fileItem.file_id || MF.slugify(fileItem.title || '')
                    );
                }, 300);
                return;
            }

            // ─── Это папка? ───
            const hasFolderInData = st.data.some(
                i => String(i.folder || '').trim().toLowerCase() === segmentLower
            );
            const extraFolders = state.extraFolders[tab] || [];
            const hasFolderInExtra = extraFolders.some(
                f => String(f).trim().toLowerCase() === segmentLower
            );

            if (hasFolderInData || hasFolderInExtra) {
                // Восстанавливаем оригинальное имя папки из данных (с учётом регистра)
                let realName = segment;
                const found = st.data.find(
                    i => String(i.folder || '').trim().toLowerCase() === segmentLower
                );
                if (found) realName = String(found.folder).trim();
                else {
                    const foundExtra = extraFolders.find(
                        f => String(f).trim().toLowerCase() === segmentLower
                    );
                    if (foundExtra) realName = String(foundExtra).trim();
                }

                _top10log('applyHashRoute: folder found', realName);
                st.viewMode = 'table';
                st.folderFilter = realName;
                st.searches = {};
                st.sortKey = null;
                st.sortDir = 'asc';
                st.currentPage = 1;

                window.MFApp.renderSection(meta.container, container, renderFn);
                return;
            }

            // Ни файл, ни папка — просто остаёмся в разделе.
            _top10log('applyHashRoute: segment not found, showing section', tab);
        } finally {
            _applyHashRouteInProgress = false;
        }
    }

    /**
     * Копирует deep-link на файл в буфер обмена.
     * Возвращает Promise<boolean>.
     */
    async function copyFileLink(sectionKey, fileId) {
        if (!sectionKey || !fileId) return false;
        const origin = location.origin + location.pathname;
        const url = `${origin}#${sectionKey}/${encodeURIComponent(fileId)}`;

        try {
            await navigator.clipboard.writeText(url);
            return true;
        } catch (_) {
            // Fallback через невидимый textarea
            try {
                const ta = document.createElement('textarea');
                ta.value = url;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                ta.style.pointerEvents = 'none';
                document.body.appendChild(ta);
                ta.select();
                const ok = document.execCommand('copy');
                document.body.removeChild(ta);
                return !!ok;
            } catch (_) {
                return false;
            }
        }
    }

    // Подписка на изменение хэша (кнопки Назад/Вперёд, ручной ввод)
    window.addEventListener('hashchange', function () {
        if (_suppressHashchange) return;
        applyHashRoute();
    });

    // ============================================================
    // ЗАЩИТА ОТ КОНТЕКСТНОГО МЕНЮ И DRAG НА АУДИО
    // ============================================================
    document.addEventListener('contextmenu', function (e) {
        const target = e.target;
        if (!target) return;
        if (target.tagName === 'AUDIO'
            || target.closest('audio')
            || target.closest('.audio-cell')) {
            e.preventDefault();
            return false;
        }
    }, true);

    document.addEventListener('dragstart', function (e) {
        if (e.target && e.target.tagName === 'AUDIO') {
            e.preventDefault();
            return false;
        }
    }, true);

    // ============================================================
    // ТОСТ-УВЕДОМЛЕНИЯ
    // ============================================================
    function showToast(message, type) {
        type = type || 'success';
        const iconMap = {
            success: 'check-circle',
            error:   'exclamation-circle',
            info:    'info-circle',
        };
        const icon = iconMap[type] || 'check-circle';

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `<i class="fas fa-${icon}"></i><div>${MF.escapeHtml(message)}</div>`;
        document.body.appendChild(toast);
        setTimeout(() => toast.classList.add('show'), 20);
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 400);
        }, 4500);
    }

    // ============================================================
    // НОРМАЛИЗАЦИЯ ДЛЯ ФИЛЬТРА ТОП-10
    // ============================================================
    function _normalizeTitleForMatch(s) {
        if (!s) return '';
        return String(s)
            .toLowerCase()
            .replace(/ё/g, 'е')
            .replace(/[^a-z0-9а-я\s]/g, ' ')
            .replace(/\s+/g, ' ')
            .trim();
    }

    function _normalizeSlugForMatch(s) {
        if (!s) return '';
        return String(s)
            .toLowerCase()
            .replace(/ё/g, 'е')
            .replace(/[^a-z0-9а-я\-]/g, '')
            .replace(/-+/g, '-')
            .replace(/^-|-$/g, '');
    }

    // ============================================================
    // АВТОРИЗАЦИЯ
    // ============================================================
    async function checkAuth() {
        const { data, error } = await supabaseClient.auth.getUser();
        if (error || !data?.user) {
            state.currentUser = null;
            state.currentProfile = null;
            renderAuthWidget(false);
            return;
        }
        state.currentUser = data.user;
        const { data: profile } = await supabaseClient
            .from('profiles').select('*').eq('id', state.currentUser.id).single();
        state.currentProfile = profile || null;
        renderAuthWidget(true);
    }

    function renderAuthWidget(isLoggedIn) {
        const widget = document.getElementById('authWidget');
        if (!isLoggedIn) {
            widget.innerHTML = `
                <a href="login.html" class="btn-primary"><i class="fas fa-sign-in-alt"></i> Войти</a>
                <a href="login.html" class="btn-primary" style="background:#f59e0b;"><i class="fas fa-user-plus"></i> Регистрация</a>`;
        } else {
            const av = state.currentProfile?.avatar_url || '';
            const name = state.currentProfile?.username || state.currentUser.email;
            widget.innerHTML = `
                <span class="username">${MF.escapeHtml(name)}</span>
                <div class="user-avatar">${av ? `<img src="${MF.escapeAttr(av)}">` : '<i class="fas fa-user"></i>'}</div>
                <a href="profile.html" class="btn-primary" style="background:#64748b;"><i class="fas fa-user-cog"></i> Профиль</a>
                <button id="logoutBtnMain" class="btn-danger"><i class="fas fa-sign-out-alt"></i> Выйти</button>`;
            document.getElementById('logoutBtnMain').addEventListener('click', async () => {
                await supabaseClient.auth.signOut();
                window.location.href = 'index.html';
            });
        }

        const heroLogin    = document.getElementById('heroLoginBtn');
        const heroRegister = document.getElementById('heroRegisterBtn');
        if (heroLogin)    heroLogin.style.display    = isLoggedIn ? 'none' : 'inline-flex';
        if (heroRegister) heroRegister.style.display = isLoggedIn ? 'none' : 'inline-flex';

        const isAdmin = isLoggedIn && state.currentProfile?.role === 'admin';
        const pl = document.getElementById('adminPanelLink');
        const refreshBtn = document.getElementById('contentRefreshBtn');
        if (pl) pl.style.display = isAdmin ? 'inline-flex' : 'none';
        if (refreshBtn) {
            refreshBtn.style.display = isAdmin ? 'inline-flex' : 'none';
            refreshBtn.onclick = isAdmin ? openRefreshModal : null;
        }
    }

    // ============================================================
    // СТАТИСТИКА ПОСЕЩЕНИЙ (панель в сайдбаре)
    // ============================================================
    async function loadStats() {
        try {
            const r1 = await supabaseClient.rpc('get_total_visitors');
            const r2 = await supabaseClient.rpc('get_visitors_last_year');
            const r3 = await supabaseClient.rpc('get_visitors_last_month');
            const r4 = await supabaseClient.rpc('get_visitors_last_week');
            const r5 = await supabaseClient.rpc('get_visitors_today');
            document.getElementById('stat-total').textContent = r1.data || 0;
            document.getElementById('stat-year').textContent  = r2.data || 0;
            document.getElementById('stat-month').textContent = r3.data || 0;
            document.getElementById('stat-week').textContent  = r4.data || 0;
            document.getElementById('stat-today').textContent = r5.data || 0;
        } catch (e) { /* тихо */ }
    }

    // ============================================================
    // ТОП-10
    // ============================================================

    // Публичный сброс кэша (для кнопки «Обновить» и ручного вызова)
    window.resetTop10SectionCache = function () {
        _top10SectionCache = null;
        _top10SectionCacheTs = 0;
        _top10FirstLoadDone = false;
        _top10log('cache reset by external call');
    };

    async function _loadTop10SectionIndex(force, onlySections) {
        const now = Date.now();
        const isFresh = _top10SectionCache
            && (now - _top10SectionCacheTs) < TOP10_CACHE_TTL_MS;

        if (!force && isFresh) {
            _top10log('section index: using cached version (age:',
                Math.round((now - _top10SectionCacheTs) / 1000) + 's)');
            return _top10SectionCache;
        }

        _top10log('section index: fetching fresh from server',
            force ? '(force)' : '(TTL expired)');

        const cache = {};

        const targetKeys = onlySections && onlySections.size
            ? Array.from(onlySections)
            : Object.keys(CFG.SECTIONS);

        await Promise.all(
            targetKeys.map(async (sectionKey) => {
                const meta = CFG.SECTIONS[sectionKey];
                if (!meta || !meta.json) return;
                try {
                    const resp = await fetch(meta.json + '?t=' + Date.now());
                    if (!resp.ok) {
                        _top10log('fetch failed for', sectionKey, 'HTTP', resp.status);
                        return;
                    }
                    const items = await resp.json();
                    const ids = new Set();
                    const titles = new Set();
                    const bySlug = new Map();
                    const byNormTitle = new Map();

                    (items || []).forEach(item => {
                        if (!item.title) return;
                        const fid = item.file_id || MF.slugify(item.title);
                        const normFid = _normalizeSlugForMatch(fid);
                        const normTitle = _normalizeTitleForMatch(item.title);

                        if (fid) {
                            ids.add(fid);
                            if (!bySlug.has(fid)) {
                                bySlug.set(fid, { title: item.title, file_id: fid });
                            }
                        }
                        if (normFid && normFid !== fid) {
                            ids.add(normFid);
                            if (!bySlug.has(normFid)) {
                                bySlug.set(normFid, { title: item.title, file_id: fid });
                            }
                        }
                        if (normTitle) {
                            titles.add(normTitle);
                            if (!byNormTitle.has(normTitle)) {
                                byNormTitle.set(normTitle, { title: item.title, file_id: fid });
                            }
                        }
                    });

                    cache[sectionKey] = { ids, titles, bySlug, byNormTitle };
                    _top10log('section', sectionKey, '→',
                        'ids:', ids.size, 'titles:', titles.size);
                } catch (e) {
                    _top10log('fetch error for', sectionKey, e);
                }
            })
        );

        _top10SectionCache = cache;
        _top10SectionCacheTs = now;
        return cache;
    }

    function _top10Resolve(it, sectionIndex) {
        const sk = it.section_key;
        if (!sk || !CFG.SECTIONS[sk]) return null;
        const idx = sectionIndex[sk];
        if (!idx) return null;

        const fidFromRpc = it.file_id || '';
        if (fidFromRpc && idx.bySlug.has(fidFromRpc)) {
            return idx.bySlug.get(fidFromRpc);
        }
        if (fidFromRpc) {
            const normFid = _normalizeSlugForMatch(fidFromRpc);
            if (normFid && idx.bySlug.has(normFid)) {
                return idx.bySlug.get(normFid);
            }
        }
        if (it.file_name) {
            const normName = _normalizeTitleForMatch(it.file_name);
            if (normName && idx.byNormTitle.has(normName)) {
                return idx.byNormTitle.get(normName);
            }
        }
        return null;
    }

    async function loadTop10(force) {
        const section = document.getElementById('top10');
        const grid = document.getElementById('top10Grid');
        if (!section || !grid) return;

        if (force) {
            grid.innerHTML = '<div class="top10-loading"><i class="fas fa-spinner fa-spin"></i> Загрузка...</div>';
        }

        const refreshBtn = document.getElementById('top10RefreshBtn');
        if (refreshBtn) refreshBtn.disabled = true;

        try {
            const { data, error } = await supabaseClient.rpc('get_top_downloads', {
                p_limit: 30,
            });
            if (error) throw error;

            const rawItems = Array.isArray(data) ? data : [];
            _top10log('RPC returned', rawItems.length, 'items');
            if (rawItems.length === 0) {
                grid.innerHTML = '<div class="top10-empty">Пока нет данных о скачиваниях</div>';
                _top10FirstLoadDone = true;
                return;
            }

            const neededSections = new Set(
                rawItems
                    .map(it => it.section_key)
                    .filter(sk => sk && CFG.SECTIONS[sk])
            );
            _top10log('needed sections:', Array.from(neededSections));

            const sectionIndex = await _loadTop10SectionIndex(force, neededSections);

            const resolved = [];
            const dropped = [];
            rawItems.forEach(it => {
                const found = _top10Resolve(it, sectionIndex);
                if (found) {
                    resolved.push({
                        file_id:      it.file_id,
                        file_name:    it.file_name,
                        section_key:  it.section_key,
                        count:        it.count,
                        actual_title: found.title,
                        actual_fid:   found.file_id,
                        renamed:      found.title !== it.file_name,
                    });
                } else {
                    dropped.push({
                        file_id: it.file_id,
                        file_name: it.file_name,
                        section_key: it.section_key,
                        count: it.count,
                    });
                }
            });

            const renamed = resolved.filter(r => r.renamed);
            if (renamed.length) {
                _top10log('renamed', renamed.length, 'items — показываем актуальное название:');
                renamed.forEach(r => {
                    _top10log('   ',
                        `file_id="${r.file_id}"`,
                        `было: "${r.file_name}"`,
                        `→ стало: "${r.actual_title}"`);
                });
            }
            if (dropped.length) {
                _top10log('dropped', dropped.length, 'items (нет в JSON):');
                console.table(dropped);
            }

            const items = resolved.slice(0, 10);
            _top10log('kept:', items.length, 'shown:', items.length);

            if (items.length === 0) {
                grid.innerHTML = '<div class="top10-empty">Пока нет доступных материалов</div>';
                _top10FirstLoadDone = true;
                return;
            }

            // ─── Карточки теперь нативные <a> ───
            // href указывает на #section/file_id → срабатывает hashchange → applyHashRoute.
            // Ctrl+клик открывает в новой вкладке.
            let html = '';
            items.forEach((it, idx) => {
                const rank = idx + 1;
                const displayName = it.actual_title || it.file_name || it.file_id || 'Без названия';
                const sectionKey = it.section_key || '';
                const sectionLabel = CFG.SECTIONS[sectionKey]?.label || sectionKey;
                const count = it.count || 0;
                const fileId = it.actual_fid || it.file_id || '';
                const href = sectionKey && fileId
                    ? `#${sectionKey}/${encodeURIComponent(fileId)}`
                    : `#${sectionKey}`;

                html += `
                    <a class="top10-item"
                       href="${MF.escapeAttr(href)}"
                       title="Открыть: ${MF.escapeAttr(displayName)}">
                        <div class="top10-rank">${rank}</div>
                        <div class="top10-body">
                            <div class="top10-name">${MF.escapeHtml(displayName)}</div>
                            <div class="top10-meta">
                                <span><i class="fas fa-folder"></i> ${MF.escapeHtml(sectionLabel)}</span>
                            </div>
                        </div>
                        <div class="top10-badge">
                            <i class="fas fa-download"></i> ${count}
                        </div>
                    </a>`;
            });
            grid.innerHTML = html;

            _top10FirstLoadDone = true;
        } catch (e) {
            console.warn('[top10]', e);
            grid.innerHTML = '<div class="top10-empty">Не удалось загрузить топ-10. Попробуйте позже.</div>';
        } finally {
            if (refreshBtn) refreshBtn.disabled = false;
        }
    }

    // Fallback: программный переход (не используется в UI, но полезен)
    function openTop10Item(sectionKey, fileName) {
        const meta = CFG.SECTIONS[sectionKey];
        if (!meta) return;

        switchTab(sectionKey);

        const tryApply = (attempt) => {
            const container = document.getElementById(meta.container);
            const st = state.tableStates[meta.container];
            if (!st || !container) {
                if (attempt < 15) {
                    setTimeout(() => tryApply(attempt + 1), 200);
                }
                return;
            }
            st.viewMode = 'table';
            st.folderFilter = null;
            st.sortKey = null;
            st.sortDir = 'asc';
            st.currentPage = 1;
            st.searches = { title: fileName || '' };
            window.MFApp.renderSection(meta.container, container,
                                       state.sectionRenderers[meta.container]);
            MF.scrollToContainer(container, 120);
        };
        setTimeout(() => tryApply(0), 300);
    }

    // Кнопка «Обновить» внутри раздела топ-10
    function bindTop10Refresh() {
        const btn = document.getElementById('top10RefreshBtn');
        if (!btn) return;
        btn.addEventListener('click', () => {
            window.resetTop10SectionCache();
            loadTop10(true);
        });
    }

    // ============================================================
    // МОДАЛКА «ОБНОВЛЕНИЕ КОНТЕНТА»
    // ============================================================
    function detectSectionSources(section) {
        const urlRaw = section.yandex_url || '';
        const urls = urlRaw.split(/[\n;]+/).map(s => s.trim()).filter(Boolean);
        let hasYandex = false;
        let hasTerabox = false;
        for (const u of urls) {
            const l = u.toLowerCase();
            if (l.includes('disk.yandex') || l.includes('yadi.sk')) hasYandex = true;
            if (l.includes('terabox') || l.includes('1024tera')
                || l.includes('4funbox') || l.includes('teraboxapp')) hasTerabox = true;
        }
        return { hasYandex, hasTerabox };
    }

    async function openRefreshModal() {
        const modal = document.getElementById('refreshModal');
        const sourcesEl = document.getElementById('refreshSources');
        const startBtn = document.getElementById('refreshStartBtn');

        sourcesEl.innerHTML = '<div class="refresh-loading"><i class="fas fa-spinner fa-spin"></i> Загрузка разделов...</div>';
        startBtn.disabled = true;
        modal.classList.add('active');

        let sections = [];
        try {
            const { data, error } = await supabaseClient
                .from('site_sections')
                .select('key, label, icon, yandex_url, sort_order')
                .eq('is_active', true)
                .order('sort_order');
            if (error) throw error;
            sections = data || [];
        } catch (e) {
            sourcesEl.innerHTML = `<div class="refresh-empty">Ошибка загрузки: ${MF.escapeHtml(e.message || '')}</div>`;
            return;
        }

        const yandexList = [];
        const teraboxList = [];
        sections.forEach(s => {
            const src = detectSectionSources(s);
            if (src.hasYandex) yandexList.push(s);
            if (src.hasTerabox) teraboxList.push(s);
        });

        function renderSourceBlock(sourceKey, sourceLabel, iconClass, list) {
            if (list.length === 0) {
                return `
                    <div class="refresh-source-block" data-source="${sourceKey}">
                        <label class="refresh-source-header">
                            <input type="checkbox" class="source-cb" data-source="${sourceKey}" disabled>
                            <i class="fas ${iconClass}"></i> ${sourceLabel}
                        </label>
                        <div class="refresh-source-sections">
                            <div class="refresh-empty">Нет разделов с ссылками на ${sourceLabel}</div>
                        </div>
                    </div>`;
            }
            const listHtml = list.map(s => `
                <label>
                    <input type="checkbox" class="section-cb"
                           data-source="${sourceKey}"
                           data-key="${MF.escapeAttr(s.key)}" checked>
                    <span>${MF.escapeHtml(s.label)}</span>
                </label>
            `).join('');

            return `
                <div class="refresh-source-block" data-source="${sourceKey}">
                    <label class="refresh-source-header">
                        <input type="checkbox" class="source-cb" data-source="${sourceKey}" checked>
                        <i class="fas ${iconClass}"></i> ${sourceLabel}
                    </label>
                    <div class="refresh-source-sections">
                        ${listHtml}
                    </div>
                </div>`;
        }

        sourcesEl.innerHTML =
            renderSourceBlock('yandex', 'Яндекс.Диск', 'fa-cloud', yandexList) +
            renderSourceBlock('terabox', 'TeraBox', 'fa-cloud-upload-alt', teraboxList);

        sourcesEl.querySelectorAll('.source-cb').forEach(cb => {
            cb.addEventListener('change', function () {
                const src = this.dataset.source;
                const checked = this.checked;
                sourcesEl.querySelectorAll(`.section-cb[data-source="${src}"]`)
                    .forEach(inner => { inner.checked = checked; });
                updateStartBtnState();
            });
        });
        sourcesEl.querySelectorAll('.section-cb').forEach(cb => {
            cb.addEventListener('change', updateStartBtnState);
        });

        function updateStartBtnState() {
            const anyChecked = sourcesEl.querySelectorAll('.section-cb:checked').length > 0;
            startBtn.disabled = !anyChecked;
        }
        updateStartBtnState();
    }

    function closeRefreshModal() {
        document.getElementById('refreshModal').classList.remove('active');
    }

    async function startRefresh() {
        const startBtn = document.getElementById('refreshStartBtn');
        const sourcesEl = document.getElementById('refreshSources');

        const yandexSections = [];
        const teraboxSections = [];

        sourcesEl.querySelectorAll('.section-cb[data-source="yandex"]:checked').forEach(cb => {
            yandexSections.push(cb.dataset.key);
        });
        sourcesEl.querySelectorAll('.section-cb[data-source="terabox"]:checked').forEach(cb => {
            teraboxSections.push(cb.dataset.key);
        });

        if (yandexSections.length === 0 && teraboxSections.length === 0) {
            showToast('Не выбрано ни одного раздела', 'error');
            return;
        }

        const { data: { session } } = await supabaseClient.auth.getSession();
        if (!session) {
            showToast('Сессия истекла. Войдите заново.', 'error');
            return;
        }
        const token = session.access_token;

        const tasks = [];
        if (yandexSections.length > 0) {
            tasks.push({
                label:   'Яндекс.Диск',
                workflow: 'sync-yandex.yml',
                inputs:   { sections: yandexSections.join(',') },
            });
        }
        if (teraboxSections.length > 0) {
            tasks.push({
                label:   'TeraBox',
                workflow: 'sync-terabox.yml',
                inputs:   { sections: teraboxSections.join(',') },
            });
        }

        startBtn.disabled = true;
        startBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Запускаю...';

        const launched = [];
        const failed = [];

        for (const t of tasks) {
            try {
                const resp = await fetch(`${SUPABASE_URL}/functions/v1/github-dispatch`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${token}`,
                    },
                    body: JSON.stringify({
                        workflow: t.workflow,
                        inputs: t.inputs,
                    }),
                });
                let payload = {};
                try { payload = await resp.json(); } catch (_) {}
                if (resp.ok && payload.ok) {
                    launched.push(t.label);
                } else {
                    failed.push(`${t.label}: ${payload.error || 'HTTP ' + resp.status}`);
                }
            } catch (e) {
                failed.push(`${t.label}: ${e.message}`);
            }
            if (tasks.indexOf(t) < tasks.length - 1) {
                await new Promise(r => setTimeout(r, 1500));
            }
        }

        startBtn.disabled = false;
        startBtn.innerHTML = '<i class="fas fa-play"></i> Запустить обновление';

        if (failed.length === 0) {
            closeRefreshModal();
            const text = launched.length === 1
                ? `Обновление ${launched[0]} запущено. Результат придёт в Telegram.`
                : `Обновление запущено (${launched.join(', ')}). Результат придёт в Telegram.`;
            showToast(text, 'success');
        } else if (launched.length > 0) {
            closeRefreshModal();
            showToast(`Запущено: ${launched.join(', ')}. Ошибки: ${failed.join('; ')}`, 'info');
        } else {
            showToast('Не удалось запустить: ' + failed.join('; '), 'error');
        }
    }

    function bindRefreshModal() {
        const cancelBtn = document.getElementById('refreshCancelBtn');
        if (cancelBtn) cancelBtn.addEventListener('click', closeRefreshModal);

        const startBtn = document.getElementById('refreshStartBtn');
        if (startBtn) startBtn.addEventListener('click', startRefresh);

        const modal = document.getElementById('refreshModal');
        if (modal) {
            modal.addEventListener('click', function (e) {
                if (e.target === this) closeRefreshModal();
            });
        }
    }

    // ============================================================
    // НАВИГАЦИЯ ПО ТАБАМ
    //
    // switchTab(tabId, opts):
    //   opts.skipHash = true → не писать URL (используется из applyHashRoute / init)
    // ============================================================
    function switchTab(tabId, opts) {
        opts = opts || {};
        state.currentTab = tabId;

        document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
        const target = document.getElementById(tabId);
        if (target) target.classList.add('active');
        document.querySelectorAll('.sidebar .nav-link').forEach(link => {
            link.classList.remove('active');
            if (link.dataset.tab === tabId) link.classList.add('active');
        });
        localStorage.setItem('activeTab', tabId);

        // Обновляем URL (если не просят обратного)
        if (!opts.skipHash) {
            setHash(tabId);
        }

        if (tabId === 'top10') {
            if (!_top10FirstLoadDone) {
                loadTop10(false);
            } else {
                const age = Date.now() - _top10SectionCacheTs;
                if (age > TOP10_CACHE_TTL_MS) {
                    _top10log('switchTab: cache stale, refreshing');
                    window.resetTop10SectionCache();
                    loadTop10(true);
                }
            }
        } else if (tabId !== 'home') {
            window.MFApp?.loadSectionIfNeeded?.(tabId);
        }

        // Обновляем хлебные крошки под текущий таб
        window.MFApp?.renderBreadcrumbs?.();
    }

    function bindNav() {
        document.querySelectorAll('.sidebar .nav-link').forEach(link => {
            link.addEventListener('click', function () {
                switchTab(this.dataset.tab);
            });
        });
    }

    // ============================================================
    // ТРЕК ВИЗИТА
    // ============================================================
    async function trackVisit() {
        let vid = localStorage.getItem('visitor_id');
        if (!vid) {
            vid = crypto.randomUUID();
            localStorage.setItem('visitor_id', vid);
        }
        const uid = state.currentUser?.id || null;
        await supabaseClient.from('visits').insert([{
            visitor_id: vid,
            user_id:    uid,
            page:       window.location.pathname,
        }]);
    }

    // ============================================================
    // ЭКСПОРТ В window.MFApp и window.MFState
    // ============================================================
    window.MFState = state;
    window.MFApp = {
        // Ссылки
        CFG, MF, supabaseClient, SUPABASE_URL,

        // Утилиты
        showToast,

        // Авторизация
        checkAuth,
        renderAuthWidget,

        // Статистика
        loadStats,

        // Топ-10
        loadTop10,
        openTop10Item,
        resetTop10Cache: window.resetTop10SectionCache,

        // Модалка обновления контента
        openRefreshModal,
        closeRefreshModal,
        detectSectionSources,

        // Навигация
        switchTab,
        bindNav,

        // Hash-роутинг
        parseHash,
        setHash,
        applyHashRoute,
        copyFileLink,

        // Трек визита
        trackVisit,

        // Bind-хелперы
        bindTop10Refresh,
        bindRefreshModal,

        // Заглушки, которые заполнит app-content.js:
        // loadSectionIfNeeded, renderSection, renderBreadcrumbs,
        // highlightFileRow, buildRenderers, buildSidebarAndTabs,
        // loadExtraFolders, loadDownloadCounts, loadCollection,
        // renderFolderGrid, renderTableWithState, incrementDownload,
        // initTableState, getFilteredSorted, buildProgramsNotice, init.
    };
})();
