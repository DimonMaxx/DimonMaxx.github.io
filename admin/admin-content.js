/* admin-content.js — модуль контента разделов для админ-панели MyFiles */
(function () {
    'use strict';

    if (!window.Admin) {
        console.error('[admin-content] admin-core.js не загружен');
        return;
    }
    if (!window.AdminState) window.AdminState = {};

    const CFG = window.APP_CONFIG;
    const MF  = window.MF;
    const supabaseClient = MF.getSupabaseClient();
    const SUPABASE_URL   = CFG.SUPABASE_URL;

    const state = window.AdminState;

    // ============================================================
    // СБОРКА КОЛОНОК ДЛЯ АДМИН-ТАБЛИЦЫ
    // ============================================================
    function buildAdminColumns(meta) {
        const labels = CFG.COLUMN_LABELS || {};
        const out = [];
        (meta.columns || []).forEach(key => {
            if (key === 'cover') {
                out.push({ key: 'cover', label: '', type: 'cover' });
            } else if (key === 'description' || key === 'body') {
                out.push({ key, label: labels[key] || key, type: 'description' });
            } else if (key === 'download_link') {
                out.push({ key, label: labels[key] || 'Ссылка', type: 'download' });
            } else {
                out.push({ key, label: labels[key] || key, type: 'text' });
            }
        });
        return out;
    }

    // ============================================================
    // ЗАГРУЗКА РАЗДЕЛА КОНТЕНТА
    // ============================================================
    async function loadSection(section) {
        const info = CFG.SECTIONS[section];
        if (!info) return;

        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas ${info.icon}"></i> ${MF.escapeHtml(info.label)}`;
        document.getElementById('toolbar').style.display = 'flex';
        document.getElementById('deleteSelectedBtn').style.display = 'inline-flex';
        document.getElementById('hideSelectedBtn').style.display = 'inline-flex';
        document.getElementById('unhideSelectedBtn').style.display = 'inline-flex';

        try {
            const resp = await fetch('../' + info.json + '?t=' + Date.now());
            state.sectionData[section] = resp.ok ? await resp.json() : [];
        } catch (e) {
            state.sectionData[section] = [];
        }

        if (!state.tableStates[section]) {
            state.tableStates[section] = {
                sortKey: null,
                sortDir: 'asc',
                searches: {},
                pageSize: CFG.DEFAULT_PAGE_SIZE,
                currentPage: 1,
                totalItems: 0,
            };
        }

        const data = state.sectionData[section] || [];
        const hasFolders = data.some(it => (it.folder || '').trim());

        if (!state.contentViews[section]) {
            if (info.folderable && hasFolders) {
                state.contentViews[section] = 'folders';
                state.contentFolderFilters[section] = null;
            } else {
                state.contentViews[section] = 'table';
                state.contentFolderFilters[section] = null;
            }
        }

        renderContent(section);
    }

    function renderContent(section) {
        const view = state.contentViews[section] || 'table';
        if (view === 'folders') {
            renderAdminFolderGrid(section);
        } else {
            renderContentTable(section);
        }
    }

    // ============================================================
    // СЕТКА ПАПОК В АДМИНКЕ
    // ============================================================
    function renderAdminFolderGrid(section) {
        const data = state.sectionData[section] || [];

        const counts = {};
        const hiddenCounts = {};
        let withFolder = 0;

        data.forEach(it => {
            const f = (it.folder || '').trim();
            const h = Admin.isHidden(section, f, it.title || '');
            if (f) {
                counts[f] = (counts[f] || 0) + 1;
                if (h) hiddenCounts[f] = (hiddenCounts[f] || 0) + 1;
                withFolder++;
            }
        });
        const withoutFolder = data.length - withFolder;
        const folders = Object.keys(counts).sort((a, b) => a.localeCompare(b, 'ru'));

        let hiddenInSection = 0;
        state.hiddenItems.forEach((item) => {
            if (item.section_key === section) hiddenInSection++;
        });

        let html = '';
        if (hiddenInSection > 0) {
            html += `<div class="section-hidden-notice">
                        <i class="fas fa-eye-slash"></i>
                        Скрыто в разделе: <strong>${hiddenInSection}</strong>
                        <span style="flex:1;"></span>
                        <button class="btn-unhide" onclick="Admin.unhideAllInSection('${MF.escapeAttr(section)}')">
                            <i class="fas fa-eye"></i> Показать все
                        </button>
                     </div>`;
        }

        html += '<div class="admin-folder-grid">';

        html += `<div class="admin-folder-card all-card" data-folder="__ALL__">
                    <div class="folder-icon"><i class="fas fa-layer-group"></i></div>
                    <div class="folder-name">Все материалы</div>
                    <div class="folder-count">${data.length}</div>
                    ${hiddenInSection > 0 ? `<div class="folder-hidden-badge">${hiddenInSection} скрыто</div>` : ''}
                 </div>`;

        folders.forEach(f => {
            const total = counts[f];
            const hidden = hiddenCounts[f] || 0;
            const isEmpty = total === 0;
            const isAllHidden = hidden > 0 && hidden === total;

            html += `<div class="admin-folder-card${isEmpty ? ' empty-card' : ''}" data-folder="${MF.escapeAttr(f)}">
                        <div class="folder-icon">
                            <i class="fas fa-folder${isEmpty ? '-open' : ''}" ${isAllHidden ? 'style="color:#dc2626;"' : ''}></i>
                        </div>
                        <div class="folder-name">${MF.escapeHtml(f)}</div>
                        <div class="folder-count">${total}${hidden > 0 ? ` / <span style="color:#dc2626; font-weight:700;">${hidden}</span>` : ''}</div>
                        ${hidden > 0 ? `<div class="folder-hidden-badge">${hidden} скрыто</div>` : ''}
                     </div>`;
        });

        if (withoutFolder > 0) {
            html += `<div class="admin-folder-card nofolder-card" data-folder="__NOFOLDER__">
                        <div class="folder-icon"><i class="fas fa-question-circle"></i></div>
                        <div class="folder-name">Без папки</div>
                        <div class="folder-count">${withoutFolder}</div>
                     </div>`;
        }

        html += '</div>';

        document.getElementById('tableWrapper').innerHTML = html;

        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';

        document.querySelectorAll('.admin-folder-card').forEach(card => {
            card.addEventListener('click', () => {
                const folder = card.dataset.folder;
                if (folder === '__ALL__') {
                    state.contentFolderFilters[section] = null;
                } else if (folder === '__NOFOLDER__') {
                    state.contentFolderFilters[section] = '__NOFOLDER__';
                } else {
                    state.contentFolderFilters[section] = folder;
                }
                state.contentViews[section] = 'table';

                if (!state.tableStates[section]) {
                    state.tableStates[section] = {
                        sortKey: null, sortDir: 'asc', searches: {},
                        pageSize: CFG.DEFAULT_PAGE_SIZE, currentPage: 1, totalItems: 0,
                    };
                }
                state.tableStates[section].currentPage = 1;
                state.tableStates[section].searches = {};
                state.tableStates[section].sortKey = null;
                state.tableStates[section].sortDir = 'asc';

                renderContent(section);

                document.getElementById('hideSelectedBtn').style.display = 'inline-flex';
                document.getElementById('unhideSelectedBtn').style.display = 'inline-flex';
                document.getElementById('deleteSelectedBtn').style.display = 'inline-flex';

                MF.scrollToContainer(document.getElementById('tableWrapper'), 120);
            });
        });
    }

    async function unhideAllInSection(section) {
        const ids = [];
        state.hiddenItems.forEach(item => {
            if (item.section_key === section) ids.push(item.id);
        });
        if (ids.length === 0) return;
        if (!confirm(`Показать все ${ids.length} скрытых в разделе?`)) return;

        const { error } = await supabaseClient
            .from('hidden_items').delete().in('id', ids);
        if (error) {
            alert('Ошибка: ' + error.message);
            return;
        }

        await Admin.loadHiddenItems();
        renderContent(section);
        Admin.showToast(`Возвращено на сайт: ${ids.length}.`, 'success');
    }

    // ============================================================
    // ТАБЛИЦА КОНТЕНТА
    // ============================================================
    function getFilteredSorted(stateTbl, data, section) {
        let filtered = data.slice();

        const folderFilter = state.contentFolderFilters[section];
        if (folderFilter) {
            if (folderFilter === '__NOFOLDER__') {
                filtered = filtered.filter(it => !(it.folder || '').trim());
            } else {
                filtered = filtered.filter(it => (it.folder || '').trim() === folderFilter);
            }
        }

        Object.keys(stateTbl.searches).forEach(key => {
            const q = (stateTbl.searches[key] || '').trim().toLowerCase();
            if (!q) return;
            filtered = filtered.filter(item => {
                const v = item[key];
                return v !== undefined && String(v).toLowerCase().includes(q);
            });
        });

        if (stateTbl.sortKey) {
            const key = stateTbl.sortKey;
            const dir = stateTbl.sortDir === 'asc' ? 1 : -1;
            filtered.sort((a, b) => {
                const va = a[key], vb = b[key];
                if (va === undefined) return 1;
                if (vb === undefined) return -1;
                if (!isNaN(va) && !isNaN(vb) && va !== '' && vb !== '') {
                    return (parseFloat(va) - parseFloat(vb)) * dir;
                }
                return String(va).localeCompare(String(vb), 'ru') * dir;
            });
        }
        return filtered;
    }

    function renderContentTable(section) {
        const info = CFG.SECTIONS[section];
        const stateTbl = state.tableStates[section];
        const data = state.sectionData[section] || [];
        const cols = buildAdminColumns(info);

        const filtered = getFilteredSorted(stateTbl, data, section);
        const totalItems = filtered.length;
        stateTbl.totalItems = totalItems;
        const totalPages = Math.max(1, Math.ceil(totalItems / stateTbl.pageSize));
        if (stateTbl.currentPage > totalPages) stateTbl.currentPage = totalPages;
        if (stateTbl.currentPage < 1) stateTbl.currentPage = 1;
        const startIdx = (stateTbl.currentPage - 1) * stateTbl.pageSize;
        const pageItems = filtered.slice(startIdx, startIdx + stateTbl.pageSize);

        let backBar = '';
        if (info.folderable) {
            const folderFilter = state.contentFolderFilters[section];
            let folderLabel = 'Все материалы';
            if (folderFilter === '__NOFOLDER__') folderLabel = 'Без папки';
            else if (folderFilter) folderLabel = folderFilter;

            backBar = `
                <div class="admin-back-bar">
                    <button class="admin-back-btn" id="backToFoldersBtn">
                        <i class="fas fa-arrow-left"></i> К папкам
                    </button>
                    <span class="admin-current-folder">
                        <i class="fas fa-folder-open"></i> ${MF.escapeHtml(folderLabel)}
                    </span>
                </div>`;
        }

        let headHtml = '<tr>';
        headHtml += `<th class="center"><input type="checkbox" id="selectAllCheckbox"></th>`;
        cols.forEach(col => {
            const isSorted = stateTbl.sortKey === col.key;
            let icon = '<i class="fas fa-sort sort-icon"></i>';
            if (isSorted) {
                icon = stateTbl.sortDir === 'asc'
                    ? '<i class="fas fa-sort-up sort-icon active"></i>'
                    : '<i class="fas fa-sort-down sort-icon active"></i>';
            }
            headHtml += `<th>
                <div class="th-label" data-sort-key="${MF.escapeAttr(col.key)}">
                    ${MF.escapeHtml(col.label)} ${icon}
                </div>
                <input type="text" class="col-search"
                       data-search-key="${MF.escapeAttr(col.key)}"
                       placeholder="Поиск..."
                       value="${MF.escapeAttr(stateTbl.searches[col.key] || '')}">
            </th>`;
        });
        headHtml += '</tr>';

        let tbodyHtml = '';
        if (pageItems.length === 0) {
            tbodyHtml = `<tr><td colspan="${cols.length + 1}" class="empty-block">Ничего не найдено</td></tr>`;
        } else {
            pageItems.forEach(item => {
                const rowIdx = data.indexOf(item);
                const folderVal = item.folder || '';
                const titleVal = item.title || '';
                const rowHidden = Admin.isHidden(section, folderVal, titleVal);

                const rowClass = rowHidden ? 'row-hidden' : '';
                tbodyHtml += `<tr class="${rowClass}" data-row-index="${rowIdx}">`;
                tbodyHtml += `<td class="center checkbox-cell">
                    <input type="checkbox" class="row-checkbox" data-row-index="${rowIdx}">
                </td>`;

                cols.forEach(col => {
                    const val = item[col.key];

                    if (col.type === 'cover') {
                        tbodyHtml += val
                            ? `<td class="col-cover"><img src="${MF.escapeAttr(val)}" alt=""></td>`
                            : `<td class="col-cover"><div class="no-cover"><i class="fas fa-book"></i></div></td>`;
                    } else if (col.type === 'description') {
                        const s = val ? String(val) : '';
                        const shortVal = s.length > 120 ? s.slice(0, 120) + '...' : s;
                        tbodyHtml += `<td title="${MF.escapeAttr(val || '')}">${MF.escapeHtml(shortVal)}</td>`;
                    } else if (col.type === 'download') {
                        // ← ИЗМЕНЕНО: используем прокси-ссылку через Edge Function
                        if (val) {
                            const proxied = Admin.buildProxyUrl(val, titleVal);
                            tbodyHtml += `<td>
                                <a href="${MF.escapeAttr(proxied)}"
                                   target="_blank" rel="noopener"
                                   style="color:#2563eb; font-weight:600;">
                                    <i class="fas fa-download"></i> Скачать
                                </a>
                            </td>`;
                        } else {
                            tbodyHtml += `<td>—</td>`;
                        }
                    } else if (col.key === 'title') {
                        const badge = rowHidden
                            ? '<span class="hidden-badge"><i class="fas fa-eye-slash"></i> Скрыто</span>'
                            : '';
                        tbodyHtml += `<td class="title-cell">${MF.escapeHtml(val || '')}${badge}</td>`;
                    } else {
                        const s = val ? String(val) : '';
                        const shortVal = s.length > 120 ? s.slice(0, 120) + '...' : s;
                        tbodyHtml += `<td title="${MF.escapeAttr(val || '')}">${MF.escapeHtml(shortVal)}</td>`;
                    }
                });
                tbodyHtml += '</tr>';
            });
        }

        const paginationTop = (totalPages > 1)
            ? MF.renderPagination(section, totalItems, totalPages, stateTbl, 'top')
            : '';
        const paginationBottom = (totalPages > 1)
            ? MF.renderPagination(section, totalItems, totalPages, stateTbl, 'bottom')
            : '';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `
            ${backBar}
            <div class="content-table-wrap-outer" data-section="${MF.escapeAttr(section)}">
                ${paginationTop}
                <div class="content-table-wrapper">
                    <table class="content-table">
                        <thead>${headHtml}</thead>
                        <tbody>${tbodyHtml}</tbody>
                    </table>
                </div>
                ${paginationBottom}
            </div>`;

        const backBtn = document.getElementById('backToFoldersBtn');
        if (backBtn) {
            backBtn.addEventListener('click', () => {
                state.contentViews[section] = 'folders';
                state.contentFolderFilters[section] = null;
                if (state.tableStates[section]) {
                    state.tableStates[section].currentPage = 1;
                    state.tableStates[section].searches = {};
                    state.tableStates[section].sortKey = null;
                    state.tableStates[section].sortDir = 'asc';
                }
                renderContent(section);
                MF.scrollToContainer(document.getElementById('tableWrapper'), 120);
            });
        }

        wrapper.querySelectorAll('.th-label').forEach(el => el.addEventListener('click', function () {
            const key = this.dataset.sortKey;
            if (stateTbl.sortKey === key) {
                stateTbl.sortDir = stateTbl.sortDir === 'asc' ? 'desc' : 'asc';
            } else {
                stateTbl.sortKey = key;
                stateTbl.sortDir = 'asc';
            }
            stateTbl.currentPage = 1;
            renderContentTable(section);
        }));

        wrapper.querySelectorAll('.col-search').forEach(input => input.addEventListener('input', function () {
            const key = this.dataset.searchKey;
            stateTbl.searches[key] = this.value;
            stateTbl.currentPage = 1;
            clearTimeout(input._t);
            input._t = setTimeout(() => {
                renderContentTable(section);
                const ni = wrapper.querySelector(`.col-search[data-search-key="${key}"]`);
                if (ni) {
                    ni.focus();
                    ni.setSelectionRange(ni.value.length, ni.value.length);
                }
            }, 250);
        }));

        const selectAll = document.getElementById('selectAllCheckbox');
        if (selectAll) {
            selectAll.addEventListener('change', function () {
                wrapper.querySelectorAll('.row-checkbox').forEach(cb => cb.checked = this.checked);
                updateSelectionButtons();
            });
        }
        wrapper.querySelectorAll('.row-checkbox').forEach(cb =>
            cb.addEventListener('change', updateSelectionButtons)
        );
        updateSelectionButtons();

        MF.attachPaginationHandlers(
            wrapper,
            section,
            stateTbl,
            () => renderContentTable(section),
            { scrollTarget: wrapper, scrollOffset: 120 }
        );
    }

    // ============================================================
    // ВЫБРАННЫЕ СТРОКИ + КНОПКИ
    // ============================================================
    function getSelectedRows() {
        const rows = [];
        document.querySelectorAll('.row-checkbox:checked').forEach(cb => {
            rows.push(parseInt(cb.dataset.rowIndex, 10));
        });
        return rows;
    }

    function updateSelectionButtons() {
        const selected = getSelectedRows();
        const info = document.getElementById('selectedInfo');
        const deleteBtn = document.getElementById('deleteSelectedBtn');
        const hideBtn   = document.getElementById('hideSelectedBtn');
        const unhideBtn = document.getElementById('unhideSelectedBtn');

        const isContent = !!CFG.SECTIONS[state.currentTab];

        if (selected.length === 0 || !isContent) {
            info.style.display = 'none';
            deleteBtn.disabled = true;
            hideBtn.disabled = true;
            unhideBtn.disabled = true;
            return;
        }

        const data = state.sectionData[state.currentTab] || [];
        let hasVisible = false;
        let hasHidden  = false;

        selected.forEach(idx => {
            const item = data[idx];
            if (!item) return;
            const rowHidden = Admin.isHidden(state.currentTab, item.folder || '', item.title || '');
            if (rowHidden) hasHidden = true;
            else hasVisible = true;
        });

        info.textContent = `Выбрано: ${selected.length}`;
        info.style.display = 'inline';

        deleteBtn.disabled = false;
        hideBtn.disabled   = !hasVisible;
        unhideBtn.disabled = !hasHidden;
    }

    // ============================================================
    // СКРЫТИЕ / ВОССТАНОВЛЕНИЕ
    // ============================================================
    async function hideSelected() {
        if (state.hideInProgress) return;
        const selected = getSelectedRows();
        if (selected.length === 0) return;

        const section = state.currentTab;
        const data = state.sectionData[section] || [];

        const toHide = [];
        selected.forEach(idx => {
            const item = data[idx];
            if (!item) return;
            const folder = (item.folder || '').trim();
            const title = (item.title || '').trim();
            if (!title) return;
            if (Admin.isHidden(section, folder, title)) return;
            toHide.push({ folder, title });
        });

        if (toHide.length === 0) {
            alert('Все выбранные записи уже скрыты.');
            return;
        }

        if (!confirm(
            `Скрыть ${toHide.length} записей на сайте?\n\n` +
            `Записи останутся в Google Sheets, но не будут показываться ` +
            `посетителям. Их можно вернуть в любой момент.`
        )) return;

        state.hideInProgress = true;
        const hideBtn = document.getElementById('hideSelectedBtn');
        if (hideBtn) {
            hideBtn.disabled = true;
            hideBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Скрываю...';
        }

        const payload = toHide.map(it => ({
            section_key: section,
            folder:      it.folder || null,
            title:       it.title,
            hidden_by:   state.currentUser.id,
        }));

        const { error } = await supabaseClient
            .from('hidden_items')
            .insert(payload);

        state.hideInProgress = false;
        if (hideBtn) {
            hideBtn.disabled = false;
            hideBtn.innerHTML = '<i class="fas fa-eye-slash"></i> Скрыть выбранные';
        }

        if (error) {
            alert('Ошибка: ' + error.message);
            return;
        }

        await Admin.loadHiddenItems();
        renderContent(section);
        Admin.showToast(
            `Скрыто: ${toHide.length}. Изменения появятся на сайте после синхронизации.`,
            'success'
        );
    }

    async function unhideSelected() {
        if (state.unhideInProgress) return;
        const selected = getSelectedRows();
        if (selected.length === 0) return;

        const section = state.currentTab;
        const data = state.sectionData[section] || [];

        const idsToDelete = [];
        selected.forEach(idx => {
            const item = data[idx];
            if (!item) return;
            const folder = (item.folder || '').trim();
            const title = (item.title || '').trim();
            if (!title) return;
            const key = Admin.makeHiddenKey(section, folder, title);
            const hidden = state.hiddenItems.get(key);
            if (hidden && hidden.id) idsToDelete.push(hidden.id);
        });

        if (idsToDelete.length === 0) {
            alert('Среди выбранных нет скрытых записей.');
            return;
        }

        if (!confirm(`Показать на сайте ${idsToDelete.length} записей?`)) return;

        state.unhideInProgress = true;
        const unhideBtn = document.getElementById('unhideSelectedBtn');
        if (unhideBtn) {
            unhideBtn.disabled = true;
            unhideBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Возвращаю...';
        }

        const { error } = await supabaseClient
            .from('hidden_items')
            .delete()
            .in('id', idsToDelete);

        state.unhideInProgress = false;
        if (unhideBtn) {
            unhideBtn.disabled = false;
            unhideBtn.innerHTML = '<i class="fas fa-eye"></i> Показать выбранные';
        }

        if (error) {
            alert('Ошибка: ' + error.message);
            return;
        }

        await Admin.loadHiddenItems();
        renderContent(section);
        Admin.showToast(`Возвращено на сайт: ${idsToDelete.length}.`, 'success');
    }

    // ============================================================
    // УДАЛЕНИЕ (через GitHub Actions)
    // ============================================================
    async function _dispatchDeleteOrphans(items) {
        if (!items || items.length === 0) {
            alert('Нет записей для удаления.');
            return false;
        }
        const approxSize = JSON.stringify(items).length;
        if (approxSize > 60000) {
            alert(
                `Список слишком большой (${approxSize} байт, лимит GitHub — 65 535).\n\n` +
                `Разбейте удаление: сначала удалите часть вручную из Google Sheets, ` +
                `потом повторите.`
            );
            return false;
        }

        const { data: { session } } = await supabaseClient.auth.getSession();
        if (!session) {
            alert('Сессия истекла. Войдите заново.');
            return false;
        }

        const url = `${SUPABASE_URL}/functions/v1/github-dispatch`;
        const body = JSON.stringify({
            workflow: CFG.WORKFLOW_DELETE,
            inputs: { delete_list: JSON.stringify(items) },
        });
        const headers = {
            'Content-Type': 'application/json',
            'Authorization': `Bearer ${session.access_token}`,
        };

        const MAX_ATTEMPTS = 2;
        const TIMEOUT_MS = 90000;

        for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
            const controller = new AbortController();
            const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
            let resp;
            try {
                resp = await fetch(url, {
                    method: 'POST', headers, body,
                    signal: controller.signal,
                });
            } catch (e) {
                clearTimeout(timer);
                const isAbort = (e.name === 'AbortError');
                const isNet = (e.name === 'TypeError');
                if (attempt < MAX_ATTEMPTS && (isAbort || isNet)) {
                    await new Promise(r => setTimeout(r, 3000));
                    continue;
                }
                alert(
                    isAbort
                        ? `Превышено время ожидания (${TIMEOUT_MS / 1000} сек).\n\n` +
                          `Возможно, workflow уже запущен — проверьте GitHub Actions.`
                        : `Не удалось связаться с сервером.\n\nОшибка: ${e.message}`
                );
                return false;
            }
            clearTimeout(timer);

            let result = {};
            try { result = await resp.json(); } catch (_) {}
            if (resp.ok && result.ok) return true;

            const msg = result.error || result.message || `HTTP ${resp.status}`;
            if (resp.status >= 500 && attempt < MAX_ATTEMPTS) {
                await new Promise(r => setTimeout(r, 3000));
                continue;
            }
            alert('Ошибка сервера: ' + msg);
            return false;
        }
        return false;
    }

    async function deleteSelected() {
        const rows = getSelectedRows();
        if (rows.length === 0) return;
        const section = state.currentTab;
        const data = state.sectionData[section] || [];
        const items = rows.map(idx => ({
            section,
            title: data[idx]?.title || '',
        }));

        if (!confirm(
            `Удалить ${rows.length} записей?\n\n` +
            `После подтверждения потребуется 1–2 минуты.`
        )) return;

        const ok = await _dispatchDeleteOrphans(items);
        if (ok) {
            Admin.showToast(
                `Запрос на удаление ${items.length} записей отправлен.`,
                'success'
            );
        }
    }

    // ============================================================
    // ЭКСПОРТ
    // ============================================================
    Object.assign(Admin, {
        loadSection,
        renderContent,
        renderAdminFolderGrid,
        renderContentTable,
        buildAdminColumns,
        getFilteredSorted,

        getSelectedRows,
        updateSelectionButtons,

        hideSelected,
        unhideSelected,
        unhideAllInSection,

        deleteSelected,
        _dispatchDeleteOrphans,
    });
})();
