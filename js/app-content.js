/* ============================================================
   app-content.js — рендеры разделов и таблиц MyFiles
   Дополняет window.MFApp из app-core.js.
   Работает с общим состоянием window.MFState.
   Содержит: buildRenderers, buildSidebarAndTabs, loadExtraFolders,
             loadCollection, loadSectionIfNeeded, renderSection,
             renderFolderGrid, renderTableWithState,
             incrementDownload, renderBreadcrumbs, goToSection,
             инициализацию init().
   ============================================================ */
(function () {
    'use strict';

    // ─── Ссылки на общие объекты из app-core.js ───
    const App = window.MFApp;
    if (!App) {
        console.error('[app-content] app-core.js не загружен');
        return;
    }
    const state = window.MFState;
    if (!state) {
        console.error('[app-content] MFState не инициализирован');
        return;
    }

    // ─── Локальные сокращения ───
    const CFG              = App.CFG;
    const MF               = App.MF;
    const supabaseClient   = App.supabaseClient;
    const showToast        = App.showToast;
    const buildProxyUrl    = MF.buildProxyUrl;
    const getAudioMimeType = MF.getAudioMimeType;

    // ─── Проверяем все поля state на месте ───
    if (!state.loadedSections)   state.loadedSections = new Set();
    if (!state.tableStates)      state.tableStates = {};
    if (!state.sectionRenderers) state.sectionRenderers = {};
    if (!state.extraFolders)     state.extraFolders = {};
    if (!state.downloadCounts)   state.downloadCounts = {};

    // ============================================================
    // ХЛЕБНЫЕ КРОШКИ
    // ============================================================
    // Правила:
    //   home             → скрыть
    //   top10            → Главная › Топ-10
    //   раздел без папки → Главная › Программы
    //   раздел в папке   → Главная › Программы › Converter
    //
    // Клик по «Главная» → switchTab('home')
    // Клик по названию раздела → goToSection(sectionKey) (сброс фильтра)
    // Текущая папка — не кликабельна (это текущее положение).
    // ============================================================

    function renderBreadcrumbs() {
        const el = document.getElementById('breadcrumbs');
        if (!el) return;

        const tab = state.currentTab || 'home';

        // ─── Главная: скрываем крошки ───
        if (tab === 'home') {
            el.classList.remove('breadcrumbs--active');
            el.innerHTML = '';
            return;
        }

        // ─── Топ-10 ───
        if (tab === 'top10') {
            el.innerHTML = `
                <button type="button" class="breadcrumbs__link" data-bc-action="home">
                    <i class="fas fa-home"></i> Главная
                </button>
                <span class="breadcrumbs__sep">›</span>
                <span class="breadcrumbs__current">
                    <i class="fas fa-fire"></i> Топ-10
                </span>`;
            el.classList.add('breadcrumbs--active');
            bindBreadcrumbHandlers(el);
            return;
        }

        // ─── Раздел ───
        const meta = CFG.SECTIONS[tab];
        if (!meta) {
            el.classList.remove('breadcrumbs--active');
            el.innerHTML = '';
            return;
        }

        const st = state.tableStates[meta.container];
        const folderFilter = st?.folderFilter || null;

        // Раздел показан «текущим» (не кликабельным), если:
        //   • нет фильтра папки
        //   • и режим отображения — сетка папок (мы на верхнем уровне раздела)
        const sectionIsCurrent = !folderFilter
            && (st?.viewMode !== 'table');

        let html = `
            <button type="button" class="breadcrumbs__link" data-bc-action="home">
                <i class="fas fa-home"></i> Главная
            </button>
            <span class="breadcrumbs__sep">›</span>`;

        if (sectionIsCurrent) {
            html += `
                <span class="breadcrumbs__current">
                    <i class="fas ${meta.icon}"></i> ${MF.escapeHtml(meta.label)}
                </span>`;
        } else {
            html += `
                <button type="button" class="breadcrumbs__link"
                        data-bc-action="section"
                        data-bc-section="${MF.escapeAttr(tab)}">
                    <i class="fas ${meta.icon}"></i> ${MF.escapeHtml(meta.label)}
                </button>`;

            if (folderFilter) {
                const folderLabel = (folderFilter === '__NOFOLDER__')
                    ? 'Без папки'
                    : folderFilter;
                html += `
                    <span class="breadcrumbs__sep">›</span>
                    <span class="breadcrumbs__current">
                        <i class="fas fa-folder-open"></i> ${MF.escapeHtml(folderLabel)}
                    </span>`;
            }
        }

        el.innerHTML = html;
        el.classList.add('breadcrumbs--active');
        bindBreadcrumbHandlers(el);
    }

    function bindBreadcrumbHandlers(el) {
        el.querySelectorAll('[data-bc-action]').forEach(btn => {
            btn.addEventListener('click', function () {
                const action = this.dataset.bcAction;
                if (action === 'home') {
                    App.switchTab('home');
                } else if (action === 'section') {
                    goToSection(this.dataset.bcSection);
                }
            });
        });
    }

    /**
     * Возврат в раздел на верхний уровень:
     *  - сбрасывает фильтр папки и поиск
     *  - если раздел folderable — возвращает в режим сетки папок
     *  - если нет — оставляет таблицу
     *  - если это не текущий таб, переключается на него
     */
    function goToSection(sectionKey) {
        const meta = CFG.SECTIONS[sectionKey];
        if (!meta) return;

        const st = state.tableStates[meta.container];
        if (st) {
            st.folderFilter = null;
            st.searches = {};
            st.sortKey = null;
            st.sortDir = 'asc';
            st.currentPage = 1;

            // Раздел folderable — вернуть к сетке папок, если она возможна
            const hasFolders = st.data.some(i => i.folder && String(i.folder).trim());
            const extra = state.extraFolders[sectionKey] || [];
            if (meta.folderable && (hasFolders || extra.length > 0)) {
                st.viewMode = 'grid';
            } else {
                st.viewMode = 'table';
            }
        }

        if (state.currentTab !== sectionKey) {
            // Переключаемся на раздел — там сработает switchTab → renderBreadcrumbs
            App.switchTab(sectionKey);
        } else {
            // Уже в разделе — просто перерисовываем
            const container = document.getElementById(meta.container);
            if (container && st) {
                const renderFn = state.sectionRenderers[meta.container];
                if (renderFn) {
                    renderSection(meta.container, container, renderFn);
                }
            }
        }
    }

    // ============================================================
    // ПОСТРОЕНИЕ КОЛОНОК ПО КОНФИГУ (один раз при init)
    // ============================================================
    function buildRenderers() {
        state.sectionRenderers = {};
        Object.entries(CFG.SECTIONS).forEach(([key, meta]) => {
            const isMusic = key === 'music';
            const cols = meta.columns.map(col => {
                if (col === 'cover') return { key: 'cover', label: '', type: 'cover' };
                if (col === 'description' || col === 'body')
                    return { key: col, label: CFG.COLUMN_LABELS[col] || col, type: 'description' };
                if (col === 'download_link') {
                    if (isMusic) return { key: col, label: 'Слушать', type: 'audio' };
                    return { key: col, label: 'Скачать', type: 'download' };
                }
                return { key: col, label: CFG.COLUMN_LABELS[col] || col, type: 'text' };
            });
            cols.push({ key: 'download_link', label: 'Скачиваний', type: 'count' });
            state.sectionRenderers[meta.container] = { columns: cols };
        });
    }

    // ============================================================
    // САЙДБАР И ТАБЫ (динамически из SECTIONS)
    // ============================================================
    function buildSidebarAndTabs() {
        const navInner    = document.getElementById('sidebarNavInner');
        const tabsWrapper = document.getElementById('tabsWrapper');

        // Удаляем все ранее сгенерированные пункты (кроме home и top10)
        navInner.querySelectorAll('.nav-link:not([data-tab="home"]):not([data-tab="top10"])')
            .forEach(el => el.remove());
        tabsWrapper.querySelectorAll('.tab-content:not(#home):not(#top10)')
            .forEach(el => el.remove());

        Object.entries(CFG.SECTIONS).forEach(([key, meta]) => {
            const nav = document.createElement('div');
            nav.className = 'nav-link';
            nav.dataset.tab = key;
            nav.innerHTML = `<i class="fas ${meta.icon}"></i> ${MF.escapeHtml(meta.label)}`;
            navInner.appendChild(nav);

            const tab = document.createElement('div');
            tab.id = key;
            tab.className = 'tab-content';
            tab.innerHTML = `<h2 class="section-title"><i class="fas ${meta.icon}"></i> ${MF.escapeHtml(meta.label)}</h2>
                             <div id="${meta.container}"><p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка...</p></div>`;
            tabsWrapper.appendChild(tab);
        });
    }

    // ============================================================
    // ЗАГРУЗКА ДОПОЛНИТЕЛЬНЫХ ПАПОК (section_folders)
    // ============================================================
    async function loadExtraFolders() {
        try {
            const { data, error } = await supabaseClient
                .from('section_folders')
                .select('section_key, name, sort_order')
                .order('sort_order', { ascending: true });
            if (error) throw error;
            state.extraFolders = {};
            (data || []).forEach(row => {
                if (!state.extraFolders[row.section_key]) {
                    state.extraFolders[row.section_key] = [];
                }
                state.extraFolders[row.section_key].push(row.name);
            });
        } catch (e) {
            console.warn('[extra folders]', e);
            state.extraFolders = {};
        }
    }

    // ============================================================
    // СЧЁТЧИКИ СКАЧИВАНИЙ
    // ============================================================
    async function loadDownloadCounts() {
        try {
            const { data } = await supabaseClient
                .from('downloads')
                .select('file_id, count');
            state.downloadCounts = {};
            (data || []).forEach(item => {
                state.downloadCounts[item.file_id] = item.count;
            });
            updateDownloadCountsDisplay();
        } catch (e) {
            console.warn('[downloads]', e);
        }
    }

    function updateDownloadCountsDisplay() {
        document.querySelectorAll('[data-count-file-id]').forEach(el => {
            el.textContent = state.downloadCounts[el.dataset.countFileId] || 0;
        });
    }

    // ============================================================
    // ИНКРЕМЕНТ СКАЧИВАНИЯ (RPC + лог + триггер загрузки)
    // ============================================================
    async function incrementDownload(fileId, sectionKey, downloadUrl, fileName) {
        if (!state.currentUser) {
            alert('Для скачивания необходимо зарегистрироваться.');
            return;
        }
        try {
            const { data } = await supabaseClient.rpc('increment_download', {
                p_file_id:     fileId,
                p_file_name:   fileName   || null,
                p_section_key: sectionKey || null,
            });
            state.downloadCounts[fileId] = data;
            updateDownloadCountsDisplay();

            await supabaseClient.from('download_logs').insert([{
                file_id:     fileId,
                file_name:   fileName   || null,
                section_key: sectionKey || null,
                user_id:     state.currentUser.id,
                username:    state.currentProfile?.username || state.currentUser.email,
            }]);

            if (downloadUrl && downloadUrl !== '#') {
                MF.triggerDownload(buildProxyUrl(downloadUrl, fileName), fileName);
            }
        } catch (e) {
            console.warn('[incrementDownload]', e);
            if (downloadUrl && downloadUrl !== '#') {
                MF.triggerDownload(buildProxyUrl(downloadUrl, fileName), fileName);
            }
        }
    }

    // ============================================================
    // СОСТОЯНИЕ ТАБЛИЦЫ (единый инициализатор)
    // ============================================================
    function initTableState(id, cols) {
        if (!state.tableStates[id]) {
            state.tableStates[id] = {
                data: [],
                columns: cols,
                sortKey: null,
                sortDir: 'asc',
                searches: {},
                pageSize: CFG.DEFAULT_PAGE_SIZE,
                currentPage: 1,
                totalItems: 0,
                viewMode: 'table',
                folderFilter: null,
                sectionMeta: null,
                sectionKey: null,
            };
        }
        return state.tableStates[id];
    }

    // ============================================================
    // ЗАГРУЗКА JSON РАЗДЕЛА
    // ============================================================
    async function loadCollection(containerId, jsonPath, renderFn, sectionKey) {
        const container = document.getElementById(containerId);
        if (!container) return;
        try {
            const resp = await fetch(jsonPath + '?t=' + Date.now());
            let items = [];
            if (resp.ok) items = await resp.json();

            const st = initTableState(containerId, renderFn.columns);
            st.data = items || [];
            st.sortKey = null;
            st.sortDir = 'asc';
            st.searches = {};
            st.currentPage = 1;
            st.folderFilter = null;
            st.sectionMeta = CFG.SECTIONS[sectionKey];
            st.sectionKey = sectionKey;

            const hasFilesWithFolders = st.data.some(i => i.folder && String(i.folder).trim());
            const extra = state.extraFolders[sectionKey] || [];
            if (st.sectionMeta?.folderable && (hasFilesWithFolders || extra.length > 0)) {
                st.viewMode = 'grid';
            } else {
                st.viewMode = 'table';
            }
            renderSection(containerId, container, renderFn);
        } catch (e) {
            console.warn('[loadCollection]', e);
            container.innerHTML = `<p class="empty-block" style="color:#ef4444;">Не удалось загрузить раздел.</p>`;
        }
    }

    // ============================================================
    // ЛЕНИВАЯ ЗАГРУЗКА РАЗДЕЛА (при первом switchTab)
    // ============================================================
    async function loadSectionIfNeeded(tabId) {
        if (state.loadedSections.has(tabId)) return;
        const meta = CFG.SECTIONS[tabId];
        if (!meta) return;
        state.loadedSections.add(tabId);

        const renderFn = state.sectionRenderers[meta.container];
        if (!renderFn) return;

        await loadCollection(meta.container, meta.json, renderFn, tabId);
    }

    // ============================================================
    // РОУТЕР РЕНДЕРА: таблица или сетка папок
    // ============================================================
    function renderSection(containerId, container, renderFn) {
        const st = state.tableStates[containerId];
        if (!st) return;
        if (st.viewMode === 'grid' && st.sectionMeta?.folderable) {
            renderFolderGrid(containerId, container, renderFn);
        } else {
            renderTableWithState(containerId, container, renderFn);
        }
    }

    // ============================================================
    // СЕТКА ПАПОК
    // ============================================================
    function renderFolderGrid(containerId, container, renderFn) {
        const st = state.tableStates[containerId];
        const data = st.data;
        const sectionKey = st.sectionKey;

        const counts = {};
        let withFolder = 0;
        data.forEach(item => {
            const f = (item.folder || '').trim();
            if (f) {
                counts[f] = (counts[f] || 0) + 1;
                withFolder++;
            }
        });

        (state.extraFolders[sectionKey] || []).forEach(name => {
            if (!(name in counts)) counts[name] = 0;
        });

        const folders = Object.keys(counts).sort((a, b) => a.localeCompare(b, 'ru'));
        const withoutFolder = data.length - withFolder;

        let html = '<div class="folder-grid">';
        html += `<div class="folder-card folder-card-all" data-folder="__ALL__">
                    <div class="folder-icon"><i class="fas fa-layer-group"></i></div>
                    <div class="folder-name">Все материалы</div>
                    <div class="folder-count">${data.length}</div>
                 </div>`;

        folders.forEach(f => {
            const isEmpty = counts[f] === 0;
            html += `<div class="folder-card${isEmpty ? ' folder-card-empty' : ''}" data-folder="${MF.escapeAttr(f)}">
                        <div class="folder-icon"><i class="fas fa-folder${isEmpty ? '-open' : ''}"></i></div>
                        <div class="folder-name">${MF.escapeHtml(f)}</div>
                        <div class="folder-count">${counts[f]}</div>
                     </div>`;
        });

        if (withoutFolder > 0) {
            html += `<div class="folder-card folder-card-nofolder" data-folder="__NOFOLDER__">
                        <div class="folder-icon"><i class="fas fa-question-circle"></i></div>
                        <div class="folder-name">Без папки</div>
                        <div class="folder-count">${withoutFolder}</div>
                     </div>`;
        }
        html += '</div>';
        container.innerHTML = html;

        container.querySelectorAll('.folder-card').forEach(card => {
            card.addEventListener('click', () => {
                const folder = card.dataset.folder;
                st.viewMode = 'table';
                if (folder === '__ALL__') st.folderFilter = null;
                else if (folder === '__NOFOLDER__') st.folderFilter = '__NOFOLDER__';
                else st.folderFilter = folder;

                st.searches = {};
                st.sortKey = null;
                st.sortDir = 'asc';
                st.currentPage = 1;

                renderSection(containerId, container, renderFn);
                MF.scrollToContainer(container, 120);
            });
        });

        // Обновляем хлебные крошки (путь: Главная › Раздел)
        renderBreadcrumbs();
    }

    // ============================================================
    // ПЛАШКА ДЛЯ ПРОГРАММ
    // ============================================================
    function buildProgramsNotice(folderName) {
        const isRaznye = (folderName || '').trim().toLowerCase() === 'разные';
        if (isRaznye) {
            return `
                <div class="programs-notice warning">
                    <div class="notice-title">
                        <i class="fas fa-shield-halved"></i>
                        Важная информация о программах в папке «Разные»
                    </div>
                    <p>
                        Инструменты, размещённые в этой папке, предназначены исключительно
                        для работы с данными и <strong>не содержат персональных данных</strong>
                        третьих лиц. Некоторые из них могут требовать подключения к сети
                        Интернет для полноценной работы.
                    </p>
                    <p>
                        Обработка любых сведений с помощью этих инструментов осуществляется
                        вами самостоятельно и под вашу ответственность, в соответствии
                        с <a href="http://www.consultant.ru/document/cons_doc_LAW_61801/"
                              target="_blank" rel="noopener">Федеральным законом №152-ФЗ
                        «О персональных данных»</a>.
                    </p>
                </div>
            `;
        }
        return `
            <div class="programs-notice">
                <div class="notice-title">
                    <i class="fas fa-shield-halved"></i>
                    Важная информация о программах, макросах и плагинах
                </div>
                <p>
                    Все инструменты, размещённые в этом разделе, предназначены
                    исключительно для работы с данными и <strong>не содержат
                    персональных данных</strong> третьих лиц. Использование
                    инструментов <strong>не требует подключения к сети Интернет</strong> —
                    они работают полностью автономно на вашем устройстве.
                </p>
                <p>
                    Обработка любых сведений с помощью этих инструментов осуществляется
                    вами самостоятельно и под вашу ответственность, в соответствии
                    с <a href="http://www.consultant.ru/document/cons_doc_LAW_61801/"
                          target="_blank" rel="noopener">Федеральным законом №152-ФЗ
                    «О персональных данных»</a>.
                </p>
            </div>
        `;
    }

    // ============================================================
    // ФИЛЬТРАЦИЯ + СОРТИРОВКА
    // ============================================================
    function getFilteredSorted(st) {
        let result = st.data.slice();

        if (st.folderFilter) {
            if (st.folderFilter === '__NOFOLDER__') {
                result = result.filter(item => !item.folder || !String(item.folder).trim());
            } else {
                result = result.filter(item => String(item.folder || '').trim() === st.folderFilter);
            }
        }

        Object.keys(st.searches).forEach(key => {
            const q = (st.searches[key] || '').trim().toLowerCase();
            if (!q) return;
            result = result.filter(item => {
                const v = item[key];
                return v !== undefined && String(v).toLowerCase().includes(q);
            });
        });

        if (st.sortKey) {
            const key = st.sortKey;
            const dir = st.sortDir === 'asc' ? 1 : -1;
            result.sort((a, b) => {
                let va = a[key], vb = b[key];
                if (!isNaN(va) && !isNaN(vb) && va !== '' && vb !== '') {
                    return (parseFloat(va) - parseFloat(vb)) * dir;
                }
                return String(va || '').localeCompare(String(vb || ''), 'ru') * dir;
            });
        }

        return result;
    }

    // ============================================================
    // ТАБЛИЦА РАЗДЕЛА
    // ============================================================
    function renderTableWithState(containerId, container, renderFn) {
        const st = state.tableStates[containerId];
        if (!st) return;
        const cols = st.columns;
        const allFiltered = getFilteredSorted(st);
        const totalItems = allFiltered.length;
        st.totalItems = totalItems;

        const totalPages = Math.max(1, Math.ceil(totalItems / st.pageSize));
        if (st.currentPage > totalPages) st.currentPage = totalPages;
        if (st.currentPage < 1) st.currentPage = 1;
        const startIdx = (st.currentPage - 1) * st.pageSize;
        const pageItems = allFiltered.slice(startIdx, startIdx + st.pageSize);

        const currentSectionKey = st.sectionKey || '';

        // ─── thead ───
        let thead = '<tr>';
        cols.forEach(col => {
            let cls = '';
            if (col.type === 'download' || col.type === 'audio') cls = 'col-center';
            if (col.type === 'count') cls = 'col-num';
            if (col.type === 'cover') cls = 'col-cover';
            const isSorted = st.sortKey === col.key && col.type !== 'cover';
            let icon = (col.type === 'cover') ? '' : '<i class="fas fa-sort sort-icon"></i>';
            if (isSorted) {
                icon = st.sortDir === 'asc'
                    ? '<i class="fas fa-sort-up sort-icon active"></i>'
                    : '<i class="fas fa-sort-down sort-icon active"></i>';
            }
            const sv = st.searches[col.key] || '';
            const searchField = (col.type === 'cover') ? '' :
                `<input type="text" class="col-search" data-search-key="${MF.escapeAttr(col.key)}" placeholder="Поиск..." value="${MF.escapeAttr(sv)}">`;
            thead += `<th class="${cls}">
                <div class="th-label" data-sort-key="${MF.escapeAttr(col.key)}">${MF.escapeHtml(col.label)} ${icon}</div>
                ${searchField}
            </th>`;
        });
        thead += '</tr>';

        // ─── tbody ───
        let audioIdx = 0;
        let tbody = '';
        if (pageItems.length === 0) {
            tbody = `<tr><td colspan="${cols.length}" class="empty-block">Ничего не найдено</td></tr>`;
        } else {
            pageItems.forEach(item => {
                tbody += '<tr>';
                cols.forEach(col => {
                    if (col.type === 'cover') {
                        const cover = item[col.key];
                        if (cover) tbody += `<td class="col-cover"><img src="${MF.escapeAttr(cover)}" loading="lazy"></td>`;
                        else tbody += `<td class="col-cover"><div class="no-cover"><i class="fas fa-book"></i></div></td>`;
                    } else if (col.type === 'description') {
                        const text = item[col.key] || '';
                        if (!text) {
                            tbody += `<td class="col-desc">—</td>`;
                        } else {
                            const full = MF.escapeHtml(text);
                            tbody += `<td class="col-desc">
                                <div class="desc-short">${full}</div>
                                <div class="desc-full">${full}</div>
                                <button class="desc-toggle" onclick="toggleDesc(this)">Развернуть</button>
                            </td>`;
                        }
                    } else if (col.type === 'audio') {
                        if (!item.download_link) {
                            tbody += `<td class="col-center">—</td>`;
                        } else {
                            const audioUrl = buildProxyUrl(item.download_link);
                            const mime     = getAudioMimeType(item.download_link);
                            const mimeAttr = mime ? ` type="${mime}"` : '';
                            const ftitle   = item.title || 'Трек';
                            const fid      = item.file_id || MF.slugify(ftitle);
                            const isLogged = !!state.currentUser;
                            const dlClass  = isLogged ? 'audio-download' : 'audio-download disabled';
                            const audioId  = `audio-player-${audioIdx++}`;
                            tbody += `<td class="col-center">
                                <div class="audio-cell" oncontextmenu="return false;">
                                    <audio id="${audioId}"
                                           controls
                                           controlsList="nodownload noplaybackrate noremoteplayback"
                                           disableRemotePlayback
                                           draggable="false"
                                           oncontextmenu="return false;"
                                           preload="none"
                                           src="${MF.escapeAttr(audioUrl)}"${mimeAttr}></audio>
                                    <div class="audio-controls">
                                        <button type="button" class="audio-seek-btn" data-audio-id="${audioId}" data-delta="-10" title="Назад на 10 секунд">
                                            <i class="fas fa-backward"></i> 10
                                        </button>
                                        <button type="button" class="audio-seek-btn" data-audio-id="${audioId}" data-delta="10" title="Вперёд на 10 секунд">
                                            10 <i class="fas fa-forward"></i>
                                        </button>
                                    </div>
                                    <a href="#" class="${dlClass}"
                                       data-file-id="${MF.escapeAttr(fid)}"
                                       data-section-key="${MF.escapeAttr(currentSectionKey)}"
                                       data-download-url="${MF.escapeAttr(item.download_link)}"
                                       data-file-name="${MF.escapeAttr(ftitle)}">
                                        <i class="fas fa-download"></i> Скачать
                                    </a>
                                </div>
                            </td>`;
                        }
                    } else if (col.type === 'download') {
                        if (!item.download_link) {
                            tbody += `<td class="col-center">—</td>`;
                        } else {
                            const isLogged = !!state.currentUser;
                            const fid      = item.file_id || MF.slugify(item.title || '');
                            const ftitle   = item.title || 'Без названия';
                            const btnClass = isLogged ? 'btn-download-sm' : 'btn-download-sm disabled';
                            tbody += `<td class="col-center">
                                <a href="#" class="${btnClass}"
                                   data-file-id="${MF.escapeAttr(fid)}"
                                   data-section-key="${MF.escapeAttr(currentSectionKey)}"
                                   data-download-url="${MF.escapeAttr(item.download_link)}"
                                   data-file-name="${MF.escapeAttr(ftitle)}">
                                    <i class="fas fa-download"></i> Скачать
                                </a>
                            </td>`;
                        }
                    } else if (col.type === 'count') {
                        if (!item.download_link) {
                            tbody += `<td class="col-num">—</td>`;
                        } else {
                            const fid = item.file_id || MF.slugify(item.title || '');
                            const c = state.downloadCounts[fid] || 0;
                            tbody += `<td class="col-num" data-count-file-id="${MF.escapeAttr(fid)}">${c}</td>`;
                        }
                    } else {
                        const val = item[col.key];
                        if (col.key === 'title') {
                            tbody += `<td class="col-title">${MF.escapeHtml(val || '')}</td>`;
                        } else {
                            tbody += `<td>${MF.escapeHtml(val || '')}</td>`;
                        }
                    }
                });
                tbody += '</tr>';
            });
        }

        const paginationTop = (totalPages > 1)
            ? MF.renderPagination(containerId, totalItems, totalPages, st, 'top')
            : '';
        const paginationBottom = (totalPages > 1)
            ? MF.renderPagination(containerId, totalItems, totalPages, st, 'bottom')
            : '';

        // ─── кнопка «К папкам» + плашка для программ ───
        let backBtnHtml = '';
        let noticeHtml = '';

        if (st.sectionMeta?.folderable) {
            let label = 'Все материалы';
            if (st.folderFilter === '__NOFOLDER__') label = 'Без папки';
            else if (st.folderFilter) label = st.folderFilter;

            backBtnHtml = `
                <div style="margin-bottom:15px;">
                    <button class="folder-back-btn" data-back-to-folders>
                        <i class="fas fa-arrow-left"></i> К папкам
                    </button>
                    <span class="folder-current">
                        <i class="fas fa-folder-open"></i> ${MF.escapeHtml(label)}
                    </span>
                </div>`;

            if (st.sectionKey === 'programs'
                && st.folderFilter
                && st.folderFilter !== '__NOFOLDER__') {
                noticeHtml = buildProgramsNotice(st.folderFilter);
            }
        }

        container.innerHTML = `
            ${backBtnHtml}
            ${noticeHtml}
            ${paginationTop}
            <div class="content-table-wrapper">
                <table class="content-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table>
            </div>
            ${paginationBottom}`;

        // ─── обработчики ───
        const backBtn = container.querySelector('[data-back-to-folders]');
        if (backBtn) {
            backBtn.addEventListener('click', () => {
                st.viewMode = 'grid';
                st.folderFilter = null;
                st.currentPage = 1;
                st.searches = {};
                st.sortKey = null;
                st.sortDir = 'asc';
                renderSection(containerId, container, renderFn);
                MF.scrollToContainer(container, 120);
            });
        }

        container.querySelectorAll('.th-label').forEach(el => {
            el.addEventListener('click', function () {
                const key = this.dataset.sortKey;
                const stt = state.tableStates[containerId];
                if (stt.sortKey === key) {
                    stt.sortDir = stt.sortDir === 'asc' ? 'desc' : 'asc';
                } else {
                    stt.sortKey = key;
                    stt.sortDir = 'asc';
                }
                stt.currentPage = 1;
                renderTableWithState(containerId, container, renderFn);
            });
        });

        container.querySelectorAll('.col-search').forEach(input => {
            input.addEventListener('input', function () {
                const key = this.dataset.searchKey;
                const stt = state.tableStates[containerId];
                stt.searches[key] = this.value;
                stt.currentPage = 1;
                clearTimeout(input._t);
                input._t = setTimeout(() => {
                    renderTableWithState(containerId, container, renderFn);
                    const ni = container.querySelector(`.col-search[data-search-key="${key}"]`);
                    if (ni) {
                        ni.focus();
                        ni.setSelectionRange(ni.value.length, ni.value.length);
                    }
                }, 250);
            });
        });

        container.querySelectorAll('.btn-download-sm[data-file-id], .audio-download[data-file-id]').forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                if (this.classList.contains('disabled')) {
                    alert('Для скачивания необходимо зарегистрироваться.');
                    return;
                }
                incrementDownload(
                    this.dataset.fileId,
                    this.dataset.sectionKey,
                    this.dataset.downloadUrl,
                    this.dataset.fileName
                );
            });
        });

        container.querySelectorAll('.audio-seek-btn').forEach(btn => {
            btn.addEventListener('click', function (e) {
                e.preventDefault();
                const audioId = this.dataset.audioId;
                const delta = parseFloat(this.dataset.delta) || 0;
                const audio = container.querySelector('audio[id="' + audioId + '"]');
                if (!audio) return;

                const duration = isFinite(audio.duration) ? audio.duration : Infinity;
                const cur = isFinite(audio.currentTime) ? audio.currentTime : 0;
                let next = cur + delta;
                if (next < 0) next = 0;
                if (duration !== Infinity && next > duration) next = duration;

                try { audio.currentTime = next; } catch (err) {}

                this.style.background = '#dbeafe';
                this.style.borderColor = '#2563eb';
                setTimeout(() => {
                    this.style.background = '';
                    this.style.borderColor = '';
                }, 200);
            });
        });

        container.querySelectorAll('.audio-cell audio').forEach(audio => {
            audio.addEventListener('contextmenu', e => {
                e.preventDefault();
                e.stopPropagation();
                return false;
            });
        });
        container.querySelectorAll('.audio-cell').forEach(cell => {
            cell.addEventListener('contextmenu', e => {
                e.preventDefault();
                return false;
            });
        });

        MF.attachPaginationHandlers(
            container,
            containerId,
            st,
            () => renderTableWithState(containerId, container, renderFn),
            { scrollOffset: 120 }
        );

        updateDownloadCountsDisplay();

        // Обновляем хлебные крошки (путь: Главная › Раздел [› Папка])
        renderBreadcrumbs();
    }

    // ============================================================
    // ИНИЦИАЛИЗАЦИЯ
    // ============================================================
    async function init() {
        await MF.loadSections();
        buildRenderers();
        buildSidebarAndTabs();
        App.bindNav();
        await loadExtraFolders();
        await App.checkAuth();
        await App.trackVisit();
        await loadDownloadCounts();
        App.loadStats();

        App.bindTop10Refresh();
        App.bindRefreshModal();

        const saved = localStorage.getItem('activeTab');
        if (saved && document.getElementById(saved)) {
            App.switchTab(saved);
        } else {
            App.switchTab('home');
        }
    }

    // ============================================================
    // ДОБАВЛЯЕМ В MFApp ФУНКЦИИ ЭТОГО МОДУЛЯ
    // ============================================================
    Object.assign(App, {
        // Хлебные крошки
        renderBreadcrumbs,
        goToSection,

        // Рендеры разделов и таблиц
        buildRenderers,
        buildSidebarAndTabs,
        loadExtraFolders,
        loadDownloadCounts,
        updateDownloadCountsDisplay,
        incrementDownload,
        initTableState,
        loadCollection,
        loadSectionIfNeeded,
        renderSection,
        renderFolderGrid,
        buildProgramsNotice,
        getFilteredSorted,
        renderTableWithState,

        // Инициализация
        init,
    });

    // ─── Автозапуск после загрузки DOM ───
    // app-core.js загружается первым, этот файл — вторым.
    // К моменту DOMContentLoaded оба модуля готовы.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            init().catch(err => {
                console.error('[init] ошибка:', err);
            });
        });
    } else {
        // DOM уже загружен — запускаем сразу
        init().catch(err => {
            console.error('[init] ошибка:', err);
        });
    }
})();
