/* admin-manage.js — модуль управления для админ-панели MyFiles */
(function () {
    'use strict';

    if (!window.Admin) {
        console.error('[admin-manage] admin-core.js не загружен');
        return;
    }
    if (!window.AdminState) window.AdminState = {};

    const CFG = window.APP_CONFIG;
    const MF  = window.MF;
    const supabaseClient = MF.getSupabaseClient();
    const SUPABASE_URL   = CFG.SUPABASE_URL;

    const state = window.AdminState;

    // ─── Дополняем state полями ───
    if (state.usersData === undefined)         state.usersData = [];
    if (state.usersDataMap === undefined)      state.usersDataMap = {};
    if (state.usersPage === undefined)         state.usersPage = 1;
    if (state.usersPageSize === undefined)     state.usersPageSize = CFG.DEFAULT_PAGE_SIZE;

    if (state.visitorsData === undefined)      state.visitorsData = [];
    if (state.visitorsPage === undefined)      state.visitorsPage = 1;
    if (state.visitorsPageSize === undefined)  state.visitorsPageSize = CFG.DEFAULT_PAGE_SIZE;

    if (state.orphansData === undefined)       state.orphansData = [];
    if (state.currentOrphansCtx === undefined) state.currentOrphansCtx = { section_key: null, section_label: null };

    if (state.errorsData === undefined)        state.errorsData = [];
    if (state.errorsFiltered === undefined)    state.errorsFiltered = [];
    if (state.errorsGrouped === undefined)     state.errorsGrouped = [];
    if (state.errorsPage === undefined)        state.errorsPage = 1;
    if (state.errorsPageSize === undefined)    state.errorsPageSize = CFG.DEFAULT_PAGE_SIZE;
    if (state.errorsFilter === undefined)      state.errorsFilter = { period: 'week', page: '', search: '' };

    if (state.downloadLogsData === undefined)     state.downloadLogsData = [];
    if (state.downloadLogsFiltered === undefined) state.downloadLogsFiltered = [];
    if (state.downloadLogsSelected === undefined) state.downloadLogsSelected = new Set();
    if (state.downloadLogsFilter === undefined)   state.downloadLogsFilter = { search: '', period: 'all' };

    // ─── Журнал действий ───
    if (state.actionsData === undefined)     state.actionsData = [];
    if (state.actionsFiltered === undefined) state.actionsFiltered = [];
    if (state.actionsPage === undefined)     state.actionsPage = 1;
    if (state.actionsPageSize === undefined) state.actionsPageSize = CFG.DEFAULT_PAGE_SIZE;
    if (state.actionsFilter === undefined)   state.actionsFilter = {
        period: 'week',   // today | week | month | all
        action: '',       // '' = все
        admin:  '',       // '' = все
        search: '',
    };

    // Справочник человекочитаемых названий действий
    const ACTION_LABELS = {
        hide_items:             'Скрытие записей',
        unhide_items:           'Восстановление записей',
        unhide_all_items:       'Восстановление всех в разделе',
        delete_items:           'Удаление записей',
        run_workflow:           'Запуск синхронизации',
        run_workflow_partial:   'Частичный запуск синхронизации',

        section_create:         'Создание раздела',
        section_update:         'Изменение раздела',
        section_delete:         'Удаление раздела',

        folder_create:          'Создание папки',
        folder_delete:          'Удаление папки',

        user_role_change:       'Смена роли',
        user_update:            'Изменение пользователя',
        user_delete:            'Удаление пользователя',

        orphan_delete_selected: 'Удаление выбранных осиротевших',
        orphan_delete_all:      'Удаление всех осиротевших',

        error_delete_group:     'Удаление группы ошибок',
        error_cleanup:          'Очистка старых ошибок',
        error_delete_all:       'Удаление всех ошибок',

        downloads_delete_selected: 'Удаление выбранных скачиваний',
        downloads_delete_all:      'Удаление всех скачиваний',
    };

    function actionLabel(action) {
        return ACTION_LABELS[action] || action;
    }

    // ============================================================
    // РАЗДЕЛЫ САЙТА (CRUD)
    // ============================================================
    async function loadSectionsFromDB() {
        const { data } = await supabaseClient
            .from('site_sections').select('*').order('sort_order');
        state.sectionsList = data || [];
    }

    async function renderSectionsAdmin() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-layer-group"></i> Разделы сайта`;
        document.getElementById('toolbar').style.display = 'flex';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        await loadSectionsFromDB();

        const wrapper = document.getElementById('tableWrapper');
        let html = `<button class="btn-primary" id="newSectionBtn" style="margin-bottom:15px;">
                        <i class="fas fa-plus"></i> Добавить раздел
                    </button>`;
        html += `<div class="content-table-wrapper"><table class="content-table"><thead><tr>
            <th>Ключ</th>
            <th>Название</th>
            <th>Handler</th>
            <th>Источники</th>
            <th>Лист</th>
            <th>Папки</th>
            <th>Ручн.</th>
            <th>Strip</th>
            <th>Сортировка</th>
            <th>Активен</th>
            <th>Действия</th>
        </tr></thead><tbody>`;

        if (state.sectionsList.length === 0) {
            html += `<tr><td colspan="11" class="empty-block">Разделов пока нет</td></tr>`;
        } else {
            state.sectionsList.forEach(s => {
                const url = s.yandex_url || '—';
                const shortUrl = url.length > 40 ? url.slice(0, 40) + '…' : url;
                const stripMode = s.strip_prefix_mode || 'auto';
                const stripColor = stripMode === 'always' ? '#16a34a'
                    : stripMode === 'never' ? '#dc2626' : '#94a3b8';
                html += `<tr>
                    <td><code>${MF.escapeHtml(s.key)}</code></td>
                    <td>${MF.escapeHtml(s.label)}</td>
                    <td><span class="role-badge role-user">${MF.escapeHtml(s.handler_type || 'universal')}</span></td>
                    <td title="${MF.escapeAttr(url)}"><code>${MF.escapeHtml(shortUrl)}</code></td>
                    <td>${MF.escapeHtml(s.sheet_name || '—')}</td>
                    <td>${s.folderable ? 'да' : 'нет'}</td>
                    <td>${s.manual_override ? '<span style="color:#dc2626; font-weight:700;">да</span>' : 'нет'}</td>
                    <td><span style="color:${stripColor}; font-weight:700;">${MF.escapeHtml(stripMode)}</span></td>
                    <td>${s.sort_order}</td>
                    <td>${s.is_active ? 'да' : 'нет'}</td>
                    <td class="actions-cell">
                        <button class="btn-edit" onclick="Admin.editSection('${MF.escapeAttr(s.key)}')">
                            <i class="fas fa-edit"></i>
                        </button>
                        <button class="btn-del-user" onclick="Admin.deleteSection('${MF.escapeAttr(s.key)}')">
                            <i class="fas fa-trash"></i>
                        </button>
                    </td>
                </tr>`;
            });
        }
        html += '</tbody></table></div>';
        wrapper.innerHTML = html;

        document.getElementById('newSectionBtn').addEventListener('click', () => openSectionModal(null));
    }

    function editSection(key) {
        const s = state.sectionsList.find(x => x.key === key);
        if (s) openSectionModal(s);
    }

    async function deleteSection(key) {
        if (!confirm(`Удалить раздел "${key}"?\n\nФайл JSON останется, но раздел исчезнет с сайта.`)) return;

        // Найдём label для журнала
        const sectionObj = state.sectionsList.find(x => x.key === key) || {};
        const label = sectionObj.label || key;

        const { error } = await supabaseClient
            .from('site_sections').delete().eq('key', key);
        if (error) { alert('Ошибка: ' + error.message); return; }

        Admin.logAdminAction('section_delete', key, label, {
            label,
            handler_type: sectionObj.handler_type,
            json_path: sectionObj.json_path,
        });

        alert('Раздел удалён.');
        await renderSectionsAdmin();
    }

    function openSectionModal(section) {
        const isEdit = !!section;
        const modal = document.getElementById('userEditModal');
        const box = modal.querySelector('.modal-box');

        const currentStripMode = isEdit && section.strip_prefix_mode
            ? section.strip_prefix_mode
            : 'auto';

        box.innerHTML = `
            <h3><i class="fas fa-layer-group"></i> ${isEdit ? 'Изменить' : 'Добавить'} раздел</h3>

            <div class="form-group">
                <label>Ключ (латиницей, без пробелов)</label>
                <input type="text" id="sKey"
                       value="${isEdit ? MF.escapeAttr(section.key) : ''}"
                       ${isEdit ? 'disabled' : ''}
                       placeholder="new_section">
                <div class="hint">Используется в URL. После создания изменить нельзя.</div>
            </div>

            <div class="form-group">
                <label>Название</label>
                <input type="text" id="sLabel"
                       value="${isEdit ? MF.escapeAttr(section.label) : ''}"
                       placeholder="Новый раздел">
            </div>

            <div class="form-group">
                <label>Иконка (класс FontAwesome)</label>
                <input type="text" id="sIcon"
                       value="${isEdit ? MF.escapeAttr(section.icon) : 'fa-folder'}"
                       placeholder="fa-book">
                <div class="hint">fa-book, fa-code, fa-film, fa-music, fa-gamepad, fa-folder</div>
            </div>

            <div class="form-group">
                <label>Тип обработки (handler_type)</label>
                <select id="sHandlerType">
                    <option value="universal"  ${isEdit && section.handler_type === 'universal'  ? 'selected' : ''}>universal — базовый</option>
                    <option value="books"      ${isEdit && section.handler_type === 'books'      ? 'selected' : ''}>books — книги (fb2/txt + обогащение)</option>
                    <option value="music"      ${isEdit && section.handler_type === 'music'      ? 'selected' : ''}>music — музыка (плеер)</option>
                    <option value="programs"   ${isEdit && section.handler_type === 'programs'   ? 'selected' : ''}>programs — программы</option>
                </select>
            </div>

            <div class="form-group">
                <label>Ссылки облачных хранилищ (по одной на строку)</label>
                <textarea id="sYandexUrl" rows="4"
                          placeholder="https://disk.yandex.ru/d/XXXXX&#10;https://1024terabox.com/s/YYYYY">${isEdit ? MF.escapeHtml(section.yandex_url || '') : ''}</textarea>
                <div class="hint">
                    Можно указать несколько ссылок — по одной на строку.<br>
                    • <strong>disk.yandex.ru</strong> — обрабатывается yandex_disk_sync.py<br>
                    • <strong>1024terabox.com</strong> — обрабатывается terabox_sync.py<br>
                    Каждый скрипт берёт только свои ссылки, чужие игнорирует.
                </div>
            </div>

            <div class="form-group">
                <label>Путь в аккаунте (yandex_path)</label>
                <input type="text" id="sYandexPath"
                       value="${isEdit ? MF.escapeAttr(section.yandex_path || '') : ''}"
                       placeholder="/Книги">
                <div class="hint">Путь в вашем аккаунте Яндекс.Диска, где лежит папка раздела.</div>
            </div>

            <div class="form-group">
                <label>Режим отрезания префикса (strip_prefix_mode)</label>
                <select id="sStripPrefixMode">
                    <option value="auto"   ${currentStripMode === 'auto'   ? 'selected' : ''}>auto — автоопределение (медленно, иногда ошибается)</option>
                    <option value="always" ${currentStripMode === 'always' ? 'selected' : ''}>always — всегда отрезать (рекомендуется)</option>
                    <option value="never"  ${currentStripMode === 'never'  ? 'selected' : ''}>never — не отрезать (публичная ссылка — родитель)</option>
                </select>
                <div class="hint">
                    <strong>always</strong> — если публичная ссылка ведёт ВНУТРЬ папки
                    <code>yandex_path</code> (типичный случай, работает для книг/музыки/программ).<br>
                    <strong>never</strong> — если публичная ссылка ведёт в родительскую папку, и
                    <code>yandex_path</code> — её подпапка.
                </div>
            </div>

            <div class="form-group">
                <label>Имя листа в Google Sheets</label>
                <input type="text" id="sSheetName"
                       value="${isEdit ? MF.escapeAttr(section.sheet_name || '') : ''}"
                       placeholder="Книги">
            </div>

            <div class="form-group">
                <label>JSON-путь</label>
                <input type="text" id="sJson"
                       value="${isEdit ? MF.escapeAttr(section.json_path) : '_content/new.json'}"
                       placeholder="_content/new.json">
            </div>

            <div class="form-group">
                <label>Container (id div на сайте)</label>
                <input type="text" id="sContainer"
                       value="${isEdit ? MF.escapeAttr(section.container) : 'new-container'}"
                       placeholder="new-container">
            </div>

            <div class="form-group">
                <label>Колонки (JSON-массив ключей)</label>
                <input type="text" id="sColumns"
                       value='${isEdit ? MF.escapeAttr(JSON.stringify(section.columns || [])) : '["title","description","download_link"]'}'
                       placeholder='["title","description","download_link"]'>
                <div class="hint">Доступные ключи: title, description, author, format, year, artist, platform, folder, download_link, cover</div>
            </div>

            <div class="form-group">
                <label>
                    <input type="checkbox" id="sManualOverride"
                           ${isEdit && section.manual_override ? 'checked' : ''}>
                    Ручное управление (не перезаписывать существующие строки)
                </label>
                <div class="hint">
                    Если включено — при синхронизации с Яндекс.Диском существующие
                    строки этого раздела не перезаписываются. Добавляются только
                    новые файлы.
                </div>
            </div>

            <div class="form-group">
                <label><input type="checkbox" id="sFolderable" ${isEdit && section.folderable ? 'checked' : ''}> Папки включены</label>
            </div>

            <div class="form-group">
                <label><input type="checkbox" id="sActive" ${isEdit ? (section.is_active ? 'checked' : '') : 'checked'}> Активен</label>
            </div>

            <div class="form-group">
                <label>Сортировка</label>
                <input type="number" id="sSort" value="${isEdit ? section.sort_order : 100}">
            </div>

            <div class="modal-actions">
                <button class="btn-secondary" onclick="Admin.closeUserEditModal()">Отмена</button>
                <button class="btn-primary" id="saveSectionBtn">
                    <i class="fas fa-save"></i> Сохранить
                </button>
            </div>
        `;
        modal.classList.add('active');
        document.getElementById('saveSectionBtn').addEventListener('click', saveSection);
    }

    async function saveSection() {
        const keyEl = document.getElementById('sKey');
        const isEdit = keyEl.disabled;

        const key = keyEl.value.trim();
        const label = document.getElementById('sLabel').value.trim();
        const icon = document.getElementById('sIcon').value.trim() || 'fa-folder';
        const handlerType = document.getElementById('sHandlerType').value;
        const yandexUrl = document.getElementById('sYandexUrl').value.trim() || null;
        const yandexPath = document.getElementById('sYandexPath').value.trim() || null;
        const stripPrefixMode = document.getElementById('sStripPrefixMode').value;
        const sheetName = document.getElementById('sSheetName').value.trim() || null;
        const jsonPath = document.getElementById('sJson').value.trim();
        const container = document.getElementById('sContainer').value.trim();
        const manualOverride = document.getElementById('sManualOverride').checked;
        const folderable = document.getElementById('sFolderable').checked;
        const isActive = document.getElementById('sActive').checked;
        const sortOrder = parseInt(document.getElementById('sSort').value, 10) || 100;

        let columns = [];
        try {
            columns = JSON.parse(document.getElementById('sColumns').value);
        } catch (e) {
            alert('Ошибка парсинга колонок: ' + e.message);
            return;
        }

        if (!key || !label || !jsonPath || !container) {
            alert('Заполните ключ, название, JSON-путь и container.');
            return;
        }

        const payload = {
            key, label, icon,
            handler_type: handlerType,
            yandex_url: yandexUrl,
            yandex_path: yandexPath,
            strip_prefix_mode: stripPrefixMode,
            sheet_name: sheetName,
            json_path: jsonPath,
            container,
            folderable,
            is_active: isActive,
            manual_override: manualOverride,
            sort_order: sortOrder,
            columns,
        };

        const op = isEdit
            ? supabaseClient.from('site_sections').update(payload).eq('key', key)
            : supabaseClient.from('site_sections').insert([payload]);

        const { error } = await op;
        if (error) { alert('Ошибка: ' + error.message); return; }

        Admin.logAdminAction(
            isEdit ? 'section_update' : 'section_create',
            key,
            label,
            {
                handler_type: handlerType,
                folderable: folderable,
                is_active: isActive,
                sheet_name: sheetName,
                json_path: jsonPath,
            }
        );

        Admin.closeUserEditModal();
        alert('Сохранено. Перезагрузите страницу, чтобы увидеть изменения в меню.');
        await renderSectionsAdmin();
    }

    // ============================================================
    // ПАПКИ РАЗДЕЛОВ (CRUD)
    // ============================================================
    async function renderFoldersAdmin() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-folder"></i> Папки разделов`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        await loadSectionsFromDB();
        const sectionKeys = state.sectionsList.filter(s => s.folderable).map(s => s.key);

        if (!state.currentFolderSection || !sectionKeys.includes(state.currentFolderSection)) {
            state.currentFolderSection = sectionKeys[0] || null;
        }

        const options = sectionKeys.map(k => {
            const s = state.sectionsList.find(x => x.key === k);
            return `<option value="${MF.escapeAttr(k)}" ${k === state.currentFolderSection ? 'selected' : ''}>${MF.escapeHtml(s.label)}</option>`;
        }).join('');

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `
            <div class="filters">
                <label>Раздел:
                    <select id="folderSectionSelect">${options}</select>
                </label>
                <button class="btn-primary" id="newFolderBtn"><i class="fas fa-plus"></i> Добавить папку</button>
            </div>
            <div id="foldersTableWrap"></div>`;

        document.getElementById('folderSectionSelect').addEventListener('change', function () {
            state.currentFolderSection = this.value;
            renderFoldersAdmin();
        });

        document.getElementById('newFolderBtn').addEventListener('click', async () => {
            const name = prompt('Название папки:');
            if (!name || !name.trim()) return;
            const cleanName = name.trim();
            const { error } = await supabaseClient
                .from('section_folders').insert([{
                    section_key: state.currentFolderSection,
                    name: cleanName,
                }]);
            if (error) { alert('Ошибка: ' + error.message); return; }

            Admin.logAdminAction(
                'folder_create',
                state.currentFolderSection,
                cleanName,
                null
            );

            renderFoldersAdmin();
        });

        if (!state.currentFolderSection) {
            document.getElementById('foldersTableWrap').innerHTML =
                `<p class="empty-block">Нет разделов с поддержкой папок</p>`;
            return;
        }
        await renderFoldersTable();
    }

    async function renderFoldersTable() {
        const { data } = await supabaseClient
            .from('section_folders')
            .select('*')
            .eq('section_key', state.currentFolderSection)
            .order('sort_order');

        state.foldersList = data || [];

        const meta = CFG.SECTIONS[state.currentFolderSection];
        let fileCounts = {};
        if (meta) {
            try {
                const resp = await fetch('../' + meta.json + '?t=' + Date.now());
                if (resp.ok) {
                    const items = await resp.json();
                    (items || []).forEach(it => {
                        const f = (it.folder || '').trim();
                        if (f) fileCounts[f] = (fileCounts[f] || 0) + 1;
                    });
                }
            } catch (e) {}
        }

        const wrap = document.getElementById('foldersTableWrap');
        if (state.foldersList.length === 0) {
            wrap.innerHTML = `<p class="empty-block">
                Нет дополнительных папок.<br>
                Файлы группируются по папкам на Яндекс.Диске автоматически.
            </p>`;
            return;
        }

        let html = `<div class="content-table-wrapper"><table class="content-table"><thead><tr>
            <th>Название</th>
            <th>Файлов</th>
            <th>Сортировка</th>
            <th>Действия</th>
        </tr></thead><tbody>`;

        state.foldersList.forEach(f => {
            const cnt = fileCounts[f.name] || 0;
            html += `<tr>
                <td><strong>${MF.escapeHtml(f.name)}</strong></td>
                <td>${cnt}</td>
                <td>${f.sort_order}</td>
                <td class="actions-cell">
                    <button class="btn-del-user" onclick="Admin.deleteFolder(${f.id}, '${MF.escapeAttr(f.name)}')">
                        <i class="fas fa-trash"></i> Удалить
                    </button>
                </td>
            </tr>`;
        });
        html += '</tbody></table></div>';
        wrap.innerHTML = html;
    }

    async function deleteFolder(id, name) {
        if (!confirm(`Удалить папку "${name}"?\n\nЗаписи файлов этой папки будут отправлены на удаление.`)) return;

        const meta = CFG.SECTIONS[state.currentFolderSection];
        let itemsToDelete = [];
        if (meta) {
            try {
                const resp = await fetch('../' + meta.json + '?t=' + Date.now());
                if (resp.ok) {
                    const items = await resp.json();
                    (items || []).forEach(it => {
                        if ((it.folder || '').trim() === name && it.title) {
                            itemsToDelete.push({
                                section: state.currentFolderSection,
                                title: it.title,
                            });
                        }
                    });
                }
            } catch (e) {}
        }

        const { error } = await supabaseClient
            .from('section_folders').delete().eq('id', id);
        if (error) { alert('Ошибка: ' + error.message); return; }

        Admin.logAdminAction(
            'folder_delete',
            state.currentFolderSection,
            name,
            { files_count: itemsToDelete.length }
        );

        if (itemsToDelete.length > 0) {
            try {
                const { data: { session } } = await supabaseClient.auth.getSession();
                const resp = await fetch(`${SUPABASE_URL}/functions/v1/github-dispatch`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${session.access_token}`,
                    },
                    body: JSON.stringify({
                        workflow: CFG.WORKFLOW_DELETE,
                        inputs: { delete_list: JSON.stringify(itemsToDelete) },
                    }),
                });
                const result = await resp.json();
                if (resp.ok && result.ok) {
                    Admin.showToast(`Папка удалена. ${itemsToDelete.length} файлов отправлены на удаление.`, 'success');
                } else {
                    Admin.showToast('Папка удалена, но файлы не удалось отправить: ' + (result.error || ''), 'error');
                }
            } catch (e) {
                Admin.showToast('Папка удалена, но файлы не отправились: ' + e.message, 'error');
            }
        } else {
            Admin.showToast('Папка удалена.', 'success');
        }
        renderFoldersAdmin();
    }

    // ============================================================
    // ПОЛЬЗОВАТЕЛИ
    // ============================================================
    async function loadUsers() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-users"></i> Пользователи`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `<p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка...</p>`;

        const { data, error } = await supabaseClient
            .from('profiles').select('*')
            .order('created_at', { ascending: false });

        if (error) {
            wrapper.innerHTML = `<p class="empty-block">Ошибка: ${MF.escapeHtml(error.message)}</p>`;
            return;
        }

        state.usersData = data || [];
        state.usersDataMap = {};
        state.usersData.forEach(u => { state.usersDataMap[u.id] = u; });

        if (state.usersData.length === 0) {
            wrapper.innerHTML = `<p class="empty-block">Нет пользователей</p>`;
            return;
        }

        const totalItems = state.usersData.length;
        const totalPages = Math.max(1, Math.ceil(totalItems / state.usersPageSize));
        if (state.usersPage > totalPages) state.usersPage = totalPages;
        if (state.usersPage < 1) state.usersPage = 1;
        const startIdx = (state.usersPage - 1) * state.usersPageSize;
        const pageUsers = state.usersData.slice(startIdx, startIdx + state.usersPageSize);

        const stateObj = {
            pageSize: state.usersPageSize,
            currentPage: state.usersPage,
            totalItems: totalItems,
        };

        let headHtml = `<tr>
            <th>#</th><th>Ник</th><th>Полное имя</th><th>Роль</th>
            <th>Заметка</th><th>Регистрация</th><th>Действия</th>
        </tr>`;

        let bodyHtml = '';
        pageUsers.forEach((user, i) => {
            const idx = startIdx + i + 1;
            const role = user.role || 'user';
            const roleLabel = { user: 'Польз.', moderator: 'Модер.', admin: 'Админ' }[role];
            const roleClass = { user: 'role-user', moderator: 'role-moderator', admin: 'role-admin' }[role];
            const created = user.created_at
                ? new Date(user.created_at).toLocaleDateString('ru-RU')
                : '—';
            const isMe = user.id === state.currentUser?.id;
            const note = user.admin_note || '';

            bodyHtml += `<tr>
                <td>${idx}</td>
                <td><span class="role-badge ${roleClass}">${roleLabel}</span>
                    <strong>${MF.escapeHtml(user.username || '—')}</strong></td>
                <td>${MF.escapeHtml(user.full_name || '—')}</td>
                <td>
                    <select class="user-role-select" data-id="${user.id}" ${isMe ? 'disabled' : ''}>
                        <option value="user" ${role === 'user' ? 'selected' : ''}>Пользователь</option>
                        <option value="moderator" ${role === 'moderator' ? 'selected' : ''}>Модератор</option>
                        <option value="admin" ${role === 'admin' ? 'selected' : ''}>Администратор</option>
                    </select>
                </td>
                <td class="admin-note-cell" title="${MF.escapeAttr(note)}">
                    ${MF.escapeHtml(note.slice(0, 40))}${note.length > 40 ? '...' : ''}
                </td>
                <td>${created}</td>
                <td class="actions-cell">
                    <button class="btn-edit" onclick="Admin.openUserEditModal('${user.id}')">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="btn-del-user"
                            onclick="Admin.deleteUser('${user.id}', '${MF.escapeAttr(user.username || '')}')"
                            ${isMe ? 'disabled' : ''}>
                        <i class="fas fa-trash"></i>
                    </button>
                </td>
            </tr>`;
        });

        const paginationTop = (totalPages > 1)
            ? MF.renderPagination('users-container', totalItems, totalPages, stateObj, 'top')
            : '';
        const paginationBottom = (totalPages > 1)
            ? MF.renderPagination('users-container', totalItems, totalPages, stateObj, 'bottom')
            : '';

        wrapper.innerHTML = `
            <div id="users-container">
                ${paginationTop}
                <div class="content-table-wrapper">
                    <table class="content-table">
                        <thead>${headHtml}</thead>
                        <tbody>${bodyHtml}</tbody>
                    </table>
                </div>
                ${paginationBottom}
            </div>`;

        document.querySelectorAll('.user-role-select').forEach(sel => {
            sel.addEventListener('change', async function () {
                const userId = this.dataset.id;
                const newRole = this.value;
                const oldRole = state.usersDataMap[userId]?.role || 'user';
                const username = state.usersDataMap[userId]?.username || '';

                const { error } = await supabaseClient
                    .from('profiles').update({ role: newRole }).eq('id', userId);
                if (error) {
                    alert('Ошибка: ' + error.message);
                    await loadUsers();
                } else {
                    Admin.logAdminAction(
                        'user_role_change',
                        null,
                        userId,
                        { username, from: oldRole, to: newRole }
                    );
                    Admin.showToast('Роль обновлена!', 'success');
                }
            });
        });

        const usersContainer = document.getElementById('users-container');
        MF.attachPaginationHandlers(
            usersContainer,
            'users-container',
            stateObj,
            () => {
                state.usersPage = stateObj.currentPage;
                state.usersPageSize = stateObj.pageSize;
                loadUsers();
            },
            { scrollTarget: usersContainer, scrollOffset: 120 }
        );
    }

    function openUserEditModal(userId) {
        const user = state.usersDataMap[userId];
        if (!user) return;

        const modal = document.getElementById('userEditModal');
        const box = modal.querySelector('.modal-box');

        box.innerHTML = `
            <h3><i class="fas fa-user-edit"></i> Редактирование пользователя</h3>
            <input type="hidden" id="editUserId">

            <div class="form-group">
                <label>Email (не редактируется)</label>
                <input type="text" id="editUserEmail" disabled
                       style="background:#f1f5f9; color:#94a3b8;">
            </div>

            <div class="form-group">
                <label>Имя пользователя (ник)</label>
                <input type="text" id="editUsername">
            </div>

            <div class="form-group">
                <label>Полное имя</label>
                <input type="text" id="editFullName">
            </div>

            <div class="form-group">
                <label>Роль</label>
                <select id="editRole">
                    <option value="user">Пользователь</option>
                    <option value="moderator">Модератор</option>
                    <option value="admin">Администратор</option>
                </select>
            </div>

            <div class="form-group">
                <label>Заметка администратора</label>
                <textarea id="editAdminNote" placeholder="Например: 'Пётр из Москвы'"></textarea>
                <div class="hint">Видна только администраторам.</div>
            </div>

            <div class="modal-actions">
                <button class="btn-secondary" onclick="Admin.closeUserEditModal()">Отмена</button>
                <button class="btn-primary" id="saveUserBtn">
                    <i class="fas fa-save"></i> Сохранить
                </button>
            </div>
        `;

        document.getElementById('editUserId').value = userId;
        document.getElementById('editUserEmail').value = '';
        document.getElementById('editUsername').value = user.username || '';
        document.getElementById('editFullName').value = user.full_name || '';
        document.getElementById('editRole').value = user.role || 'user';
        document.getElementById('editAdminNote').value = user.admin_note || '';

        modal.classList.add('active');
        document.getElementById('saveUserBtn').addEventListener('click', saveUser);
    }

    async function saveUser() {
        const userId = document.getElementById('editUserId').value;
        const username = document.getElementById('editUsername').value.trim();
        const fullName = document.getElementById('editFullName').value.trim();
        const role = document.getElementById('editRole').value;
        const adminNote = document.getElementById('editAdminNote').value.trim();

        if (!userId) return;
        if (!username) { alert('Ник не может быть пустым.'); return; }

        const oldUser = state.usersDataMap[userId] || {};

        const { error } = await supabaseClient.from('profiles').update({
            username,
            full_name: fullName || null,
            role,
            admin_note: adminNote || null,
        }).eq('id', userId);

        if (error) {
            alert('Ошибка сохранения: ' + error.message);
        } else {
            Admin.logAdminAction(
                'user_update',
                null,
                userId,
                {
                    old: {
                        username: oldUser.username,
                        full_name: oldUser.full_name,
                        role: oldUser.role,
                        admin_note: oldUser.admin_note,
                    },
                    new: {
                        username,
                        full_name: fullName || null,
                        role,
                        admin_note: adminNote || null,
                    },
                }
            );
            Admin.showToast('Данные обновлены!', 'success');
            Admin.closeUserEditModal();
            await loadUsers();
        }
    }

    async function deleteUser(userId, username) {
        if (userId === state.currentUser?.id) {
            alert('Нельзя удалить себя.');
            return;
        }
        if (!confirm(`Удалить пользователя "${username}"?\n\nЭто действие необратимо.`)) return;
        try {
            const { data: { session } } = await supabaseClient.auth.getSession();
            if (!session) { alert('Сессия истекла.'); return; }

            const resp = await fetch(`${SUPABASE_URL}/functions/v1/admin-delete-user`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${session.access_token}`,
                },
                body: JSON.stringify({ user_id: userId }),
            });
            const data = await resp.json();
            if (resp.ok && data.success) {
                Admin.logAdminAction(
                    'user_delete',
                    null,
                    userId,
                    { username, email: data.email || null }
                );
                Admin.showToast('Пользователь удалён.', 'success');
                await loadUsers();
            } else {
                alert('Ошибка: ' + (data.error || 'Неизвестная ошибка'));
            }
        } catch (e) {
            alert('Ошибка: ' + e.message);
        }
    }

    // ============================================================
    // ПОСЕТИТЕЛИ
    // ============================================================
    async function loadVisitors() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-user-check"></i> Посетители сайта`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `<p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка...</p>`;

        const { data, error } = await supabaseClient.rpc('get_unique_visitors');

        if (error) {
            wrapper.innerHTML = `<p class="empty-block">Ошибка: ${MF.escapeHtml(error.message)}</p>`;
            return;
        }
        state.visitorsData = data || [];
        if (state.visitorsData.length === 0) {
            wrapper.innerHTML = `<p class="empty-block">Пока нет данных о посетителях</p>`;
            return;
        }

        const totalItems = state.visitorsData.length;
        const totalPages = Math.max(1, Math.ceil(totalItems / state.visitorsPageSize));
        if (state.visitorsPage > totalPages) state.visitorsPage = totalPages;
        if (state.visitorsPage < 1) state.visitorsPage = 1;
        const startIdx = (state.visitorsPage - 1) * state.visitorsPageSize;
        const pageItems = state.visitorsData.slice(startIdx, startIdx + state.visitorsPageSize);

        const stateObj = {
            pageSize: state.visitorsPageSize,
            currentPage: state.visitorsPage,
            totalItems: totalItems,
        };

        let bodyHtml = '';
        pageItems.forEach(v => {
            const last = new Date(v.last_visit);
            const dateStr = last.toLocaleDateString('ru-RU') + ' ' +
                            last.toLocaleTimeString('ru-RU');
            const isReg = v.is_registered;
            const typeBadge = isReg
                ? '<span class="role-badge role-user">Польз.</span>'
                : '<span class="role-badge role-anon">Аноним</span>';
            const idDisplay = isReg
                ? (v.username || '—')
                : ('ID: ' + (v.visitor_key || '').replace('anon_', '').slice(0, 10) + '...');
            const emailDisplay = isReg ? (v.email || '—') : '—';

            bodyHtml += `<tr>
                <td>${typeBadge}</td>
                <td><strong>${MF.escapeHtml(idDisplay)}</strong></td>
                <td>${MF.escapeHtml(emailDisplay)}</td>
                <td>${dateStr}</td>
                <td><strong>${v.visit_count}</strong></td>
            </tr>`;
        });

        const paginationTop = (totalPages > 1)
            ? MF.renderPagination('visitors-container', totalItems, totalPages, stateObj, 'top')
            : '';
        const paginationBottom = (totalPages > 1)
            ? MF.renderPagination('visitors-container', totalItems, totalPages, stateObj, 'bottom')
            : '';

        wrapper.innerHTML = `
            <div id="visitors-container">
                ${paginationTop}
                <div class="content-table-wrapper">
                    <table class="content-table">
                        <thead><tr>
                            <th>Тип</th><th>Ник / ID</th><th>Email</th>
                            <th>Последний визит</th><th>Посещений</th>
                        </tr></thead>
                        <tbody>${bodyHtml}</tbody>
                    </table>
                </div>
                ${paginationBottom}
            </div>`;

        const visitorsContainer = document.getElementById('visitors-container');
        MF.attachPaginationHandlers(
            visitorsContainer,
            'visitors-container',
            stateObj,
            () => {
                state.visitorsPage = stateObj.currentPage;
                state.visitorsPageSize = stateObj.pageSize;
                loadVisitors();
            },
            { scrollTarget: visitorsContainer, scrollOffset: 120 }
        );
    }

    // ============================================================
    // ОСИРОТЕВШИЕ СТРОКИ
    // ============================================================
    async function loadOrphans() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-link-slash"></i> Осиротевшие строки`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `<p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка...</p>`;

        const { data, error } = await supabaseClient
            .from('sync_orphans')
            .select('*')
            .order('updated_at', { ascending: false });

        if (error) {
            wrapper.innerHTML = `<p class="empty-block">Ошибка: ${MF.escapeHtml(error.message)}</p>`;
            return;
        }

        if (!data || data.length === 0) {
            wrapper.innerHTML = `<p class="empty-block">
                Нет данных об осиротевших строках.<br>
                <small>Данные появятся после следующей синхронизации.</small>
            </p>`;
            return;
        }

        state.orphansData = data.filter(item =>
            Array.isArray(item.orphans) && item.orphans.length > 0
        );
        const total = state.orphansData.reduce((s, x) => s + x.orphans.length, 0);

        const badge = document.getElementById('orphansBadge');
        if (badge) {
            if (total > 0) {
                badge.textContent = total;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        }

        if (total === 0) {
            wrapper.innerHTML = `<p class="empty-block">
                Осиротевших строк нет ✓
            </p>`;
            return;
        }

        let html = `
            <div class="orphans-banner">
                <i class="fas fa-exclamation-triangle"></i>
                <div>
                    Найдено <strong>${total}</strong> осиротевших строк
                    в <strong>${state.orphansData.length}</strong> разделах.
                    <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">
                        <button class="btn-danger" id="deleteAllOrphansBtn">
                            <i class="fas fa-broom"></i> Удалить все осиротевшие (${total})
                        </button>
                    </div>
                </div>
            </div>
        `;

        html += `<div class="content-table-wrapper"><table class="content-table"><thead><tr>
            <th>Раздел</th>
            <th>Лист Sheets</th>
            <th>Осиротевших</th>
            <th>Обновлено</th>
            <th>Действия</th>
        </tr></thead><tbody>`;

        state.orphansData.forEach((item, idx) => {
            const updated = item.updated_at
                ? new Date(item.updated_at).toLocaleString('ru-RU')
                : '—';
            const label = item.section_label || item.section_key;
            html += `<tr>
                <td><strong>${MF.escapeHtml(label)}</strong><br>
                    <code style="font-size:11px; color:#94a3b8;">
                        ${MF.escapeHtml(item.section_key)}
                    </code>
                </td>
                <td>${MF.escapeHtml(item.sheet_name || '—')}</td>
                <td><strong style="color:#dc2626;">${item.orphans.length}</strong></td>
                <td>${MF.escapeHtml(updated)}</td>
                <td class="actions-cell">
                    <button class="btn-edit" onclick="Admin.showOrphansByIndex(${idx})">
                        <i class="fas fa-code-compare"></i> Diff-view
                    </button>
                </td>
            </tr>`;
        });
        html += '</tbody></table></div>';
        wrapper.innerHTML = html;

        const delBtn = document.getElementById('deleteAllOrphansBtn');
        if (delBtn) delBtn.addEventListener('click', deleteAllOrphans);
    }

    function showOrphansByIndex(idx) {
        const item = state.orphansData[idx];
        if (!item) return;

        const orphans = item.orphans || [];
        const headers = Array.isArray(item.headers) ? item.headers : [];

        state.currentOrphansCtx.section_key = item.section_key;
        state.currentOrphansCtx.section_label = item.section_label;

        const modal = document.getElementById('userEditModal');
        const box = modal.querySelector('.modal-box');

        let orphanBlocks = '';
        orphans.forEach((o, i) => {
            const values = Array.isArray(o.values) ? o.values : [];
            const title = o.title || '';
            const link = o.link || '';
            const linkShort = link.length > 60 ? link.slice(0, 60) + '…' : link;

            let sourceName = 'облаке';
            let sourceWhere = 'облачный диск';
            if (/terabox|1024tera|4funbox|d\.terabox/i.test(link)) {
                sourceName = 'TeraBox';
                sourceWhere = 'TeraBox';
            } else if (/disk\.yandex|yadi\.sk/i.test(link)) {
                sourceName = 'Яндекс.Диске';
                sourceWhere = 'Яндекс.Диск';
            }

            let rowsHtml = '';
            if (headers.length > 0) {
                headers.forEach((h, j) => {
                    const v = values[j] !== undefined ? String(values[j]) : '';
                    const isLink = (h === 'Ссылка для скачивания' || h === 'Ссылка'
                                    || h.toLowerCase() === 'download_link');
                    const cellCls = isLink ? 'orphan-highlight' : '';

                    const cellContent = v
                        ? (isLink && v.length > 120
                            ? `<span title="${MF.escapeAttr(v)}">${MF.escapeHtml(v.slice(0, 120))}…</span>`
                            : MF.escapeHtml(v))
                        : '<i>пусто</i>';

                    rowsHtml += `<tr>
                        <td>${MF.escapeHtml(h)}</td>
                        <td class="${cellCls} ${!v ? 'orphan-empty' : ''}">${cellContent}</td>
                    </tr>`;
                });
            } else {
                rowsHtml = `
                    <tr><td>Название</td><td>${MF.escapeHtml(title || '—')}</td></tr>
                    <tr><td>Ссылка</td><td class="orphan-highlight">
                        <span title="${MF.escapeAttr(link)}">${MF.escapeHtml(linkShort)}</span>
                    </td></tr>
                    <tr><td>Строка</td><td>${o.row || '—'}</td></tr>
                `;
            }

            orphanBlocks += `
                <div class="orphan-item" data-orphan-idx="${i}">
                    <div class="orphan-header" data-toggle-idx="${i}">
                        <input type="checkbox" class="orphan-checkbox"
                               data-orphan-idx="${i}"
                               onclick="event.stopPropagation();"
                               style="width:18px; height:18px; cursor:pointer; accent-color:#dc2626;">
                        <i class="fas fa-caret-right caret"></i>
                        <span class="row-num">#${o.row || i + 1}</span>
                        <span class="orphan-title" title="${MF.escapeAttr(title)}">
                            ${MF.escapeHtml(title || '(без названия)')}
                        </span>
                    </div>
                    <div class="orphan-body" data-body-idx="${i}">
                        <table>${rowsHtml}</table>
                        <div class="diff-note">
                            <i class="fas fa-info-circle"></i>
                            <strong>Что не так:</strong>
                            файл с этой ссылкой не найден на ${sourceWhere}.
                            Возможные причины: переименован, перемещён или удалён.
                            Если это ошибочно — проверьте ${sourceName}; иначе
                            строку можно удалить кнопкой «Удалить выбранные».
                        </div>
                    </div>
                </div>
            `;
        });

        box.innerHTML = `
            <h3>
                <i class="fas fa-code-compare"></i>
                Осиротевшие строки — ${MF.escapeHtml(item.section_label || item.section_key)}
                (${orphans.length})
            </h3>
            <p style="color:#64748b; font-size:13px; margin-bottom:10px;">
                Лист <strong>${MF.escapeHtml(item.sheet_name || '')}</strong>.
                Кликните на запись, чтобы развернуть diff-view.
                Отметьте нужные галочками, чтобы удалить только их.
            </p>
            <div style="display:flex; gap:10px; align-items:center; margin-bottom:12px; flex-wrap:wrap;">
                <button class="btn-secondary" id="orphansSelectAllBtn" style="font-size:12px; padding:6px 14px;">
                    <i class="fas fa-check-square"></i> Выбрать все
                </button>
                <button class="btn-secondary" id="orphansSelectNoneBtn" style="font-size:12px; padding:6px 14px;">
                    <i class="fas fa-square"></i> Снять все
                </button>
                <span style="color:#94a3b8; font-size:12px;">|</span>
                <span id="orphansSelInfo" style="color:#dc2626; font-weight:600; font-size:13px;">
                    Выбрано: 0
                </span>
                <span style="flex:1;"></span>
                <button class="btn-danger" id="orphansDeleteSelectedBtn" disabled
                        style="font-size:12px; padding:6px 14px;">
                    <i class="fas fa-trash"></i> Удалить выбранные
                </button>
            </div>
            <div style="max-height:55vh; overflow-y:auto; padding-right:4px;">
                ${orphanBlocks}
            </div>
            <div class="modal-actions">
                <button class="btn-secondary" onclick="Admin.closeUserEditModal()">Закрыть</button>
            </div>
        `;
        modal.classList.add('active');

        box.querySelectorAll('.orphan-header').forEach(h => {
            h.addEventListener('click', function (e) {
                if (e.target.tagName === 'INPUT') return;
                const idx2 = this.dataset.toggleIdx;
                const body = box.querySelector(`.orphan-body[data-body-idx="${idx2}"]`);
                const isOpen = this.classList.toggle('expanded');
                body.classList.toggle('expanded', isOpen);
            });
        });

        const updateSel = () => {
            const checked = box.querySelectorAll('.orphan-checkbox:checked').length;
            document.getElementById('orphansSelInfo').textContent = `Выбрано: ${checked}`;
            document.getElementById('orphansDeleteSelectedBtn').disabled = checked === 0;
        };

        box.querySelectorAll('.orphan-checkbox').forEach(cb => {
            cb.addEventListener('change', updateSel);
        });

        document.getElementById('orphansSelectAllBtn').addEventListener('click', () => {
            box.querySelectorAll('.orphan-checkbox').forEach(cb => cb.checked = true);
            updateSel();
        });
        document.getElementById('orphansSelectNoneBtn').addEventListener('click', () => {
            box.querySelectorAll('.orphan-checkbox').forEach(cb => cb.checked = false);
            updateSel();
        });
        document.getElementById('orphansDeleteSelectedBtn').addEventListener('click', () => {
            const indices = [];
            box.querySelectorAll('.orphan-checkbox:checked').forEach(cb => {
                indices.push(parseInt(cb.dataset.orphanIdx, 10));
            });
            if (indices.length === 0) return;
            deleteSelectedOrphans(indices);
        });

        updateSel();
    }

    async function deleteSelectedOrphans(indices) {
        const sectionKey = state.currentOrphansCtx.section_key;
        const sectionLabel = state.currentOrphansCtx.section_label;
        if (!sectionKey) { alert('Не удалось определить раздел.'); return; }

        const src = state.orphansData.find(o => o.section_key === sectionKey);
        if (!src) { alert('Данные раздела не найдены.'); return; }

        const items = [];
        indices.forEach(i => {
            const o = (src.orphans || [])[i];
            if (o && o.title) items.push({ section: sectionKey, title: o.title });
        });

        if (items.length === 0) { alert('Нет названий для удаления.'); return; }

        if (!confirm(
            `Удалить ${items.length} строк из раздела «${sectionLabel}»?\n\n` +
            `Удаление через GitHub Actions. Это действие необратимо.`
        )) return;

        const btn = document.getElementById('orphansDeleteSelectedBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Отправка...';
        }

        const ok = await Admin._dispatchDeleteOrphans(items);

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-trash"></i> Удалить выбранные';
        }

        if (ok) {
            Admin.logAdminAction(
                'orphan_delete_selected',
                sectionKey,
                null,
                { count: items.length, items: items.slice(0, 50) }
            );
            Admin.showToast(`Запрос на удаление ${items.length} строк отправлен.`, 'success');
            setTimeout(() => { window.location.reload(); }, 5000);
        }
    }

    async function deleteAllOrphans() {
        const allItems = [];
        state.orphansData.forEach(sectionItem => {
            (sectionItem.orphans || []).forEach(o => {
                const title = (o.title || '').trim();
                if (!title) return;
                allItems.push({ section: sectionItem.section_key, title });
            });
        });

        if (allItems.length === 0) {
            alert('Нет осиротевших строк для удаления.');
            return;
        }

        if (!confirm(
            `Удалить ${allItems.length} осиротевших строк?\n\n` +
            `Это действие необратимо. Продолжить?`
        )) return;

        const btn = document.getElementById('deleteAllOrphansBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Отправка...';
        }

        const ok = await Admin._dispatchDeleteOrphans(allItems);

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fas fa-broom"></i> Удалить все осиротевшие (${allItems.length})`;
        }

        if (ok) {
            Admin.logAdminAction(
                'orphan_delete_all',
                null,
                null,
                { count: allItems.length, items: allItems.slice(0, 50) }
            );
            Admin.showToast(`Запрос на удаление ${allItems.length} строк отправлен.`, 'success');
            setTimeout(() => { window.location.reload(); }, 5000);
        }
    }

    // ============================================================
    // СКРЫТЫЕ (вкладка со списком)
    // ============================================================
    async function loadHidden() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-eye-slash"></i> Скрытые на сайте`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        await Admin.loadHiddenItems();

        const wrapper = document.getElementById('tableWrapper');

        if (state.hiddenItems.size === 0) {
            wrapper.innerHTML = `<p class="empty-block">
                Скрытых записей нет.<br>
                <small>Скрывайте файлы из таблиц разделов — они появятся здесь.</small>
            </p>`;
            return;
        }

        const list = Array.from(state.hiddenItems.values())
            .sort((a, b) => {
                const ta = a.hidden_at ? new Date(a.hidden_at).getTime() : 0;
                const tb = b.hidden_at ? new Date(b.hidden_at).getTime() : 0;
                return tb - ta;
            });

        const bySection = {};
        list.forEach(it => {
            bySection[it.section_key] = (bySection[it.section_key] || 0) + 1;
        });
        const summaryText = Object.entries(bySection)
            .map(([k, v]) => {
                const label = (CFG.SECTIONS[k]?.label) || k;
                return `${label}: ${v}`;
            })
            .join(' • ');

        let html = `
            <div class="hidden-banner">
                <i class="fas fa-eye-slash"></i>
                <div>
                    Всего скрыто: <strong>${list.length}</strong>.
                    <br>
                    <small>${MF.escapeHtml(summaryText)}</small>
                    <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">
                        <button class="btn-unhide" id="unhideAllBtn">
                            <i class="fas fa-eye"></i> Показать все (${list.length})
                        </button>
                    </div>
                </div>
            </div>
        `;

        html += `<div class="content-table-wrapper"><table class="content-table"><thead><tr>
            <th class="center"><input type="checkbox" id="hiddenSelectAll"></th>
            <th>Раздел</th>
            <th>Папка</th>
            <th>Название</th>
            <th>Скрыто</th>
            <th>Действия</th>
        </tr></thead><tbody>`;

        list.forEach(it => {
            const sectionLabel = (CFG.SECTIONS[it.section_key]?.label) || it.section_key;
            const hiddenAt = it.hidden_at
                ? new Date(it.hidden_at).toLocaleString('ru-RU')
                : '—';
            html += `<tr>
                <td class="center checkbox-cell">
                    <input type="checkbox" class="hidden-row-checkbox" data-id="${it.id}">
                </td>
                <td><span class="role-badge role-user">${MF.escapeHtml(sectionLabel)}</span></td>
                <td>${MF.escapeHtml(it.folder || '—')}</td>
                <td class="title-cell">${MF.escapeHtml(it.title || '')}</td>
                <td>${MF.escapeHtml(hiddenAt)}</td>
                <td class="actions-cell">
                    <button class="btn-unhide" onclick="Admin.unhideOne(${it.id})">
                        <i class="fas fa-eye"></i> Показать
                    </button>
                </td>
            </tr>`;
        });
        html += '</tbody></table></div>';

        wrapper.innerHTML = html;

        const selectAll = document.getElementById('hiddenSelectAll');
        if (selectAll) {
            selectAll.addEventListener('change', function () {
                wrapper.querySelectorAll('.hidden-row-checkbox')
                    .forEach(cb => cb.checked = this.checked);
            });
        }

        const unhideAllBtn = document.getElementById('unhideAllBtn');
        if (unhideAllBtn) unhideAllBtn.addEventListener('click', unhideAll);
    }

    async function unhideOne(id) {
        if (!confirm('Показать этот файл на сайте?')) return;

        // Найдём данные записи для журнала
        let hiddenItem = null;
        state.hiddenItems.forEach(item => {
            if (item.id === id) hiddenItem = item;
        });

        const { error } = await supabaseClient
            .from('hidden_items').delete().eq('id', id);
        if (error) {
            alert('Ошибка: ' + error.message);
            return;
        }

        Admin.logAdminAction(
            'unhide_items',
            hiddenItem?.section_key || null,
            hiddenItem?.title || null,
            { count: 1, items: hiddenItem ? [{
                folder: hiddenItem.folder,
                title:  hiddenItem.title,
            }] : [] }
        );

        await Admin.loadHiddenItems();
        await loadHidden();
    }

    async function unhideAll() {
        const total = state.hiddenItems.size;
        if (total === 0) return;
        if (!confirm(
            `Показать все ${total} скрытых записей на сайте?\n\n` +
            `Они вернутся в каталог после следующей синхронизации.`
        )) return;

        const btn = document.getElementById('unhideAllBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Возвращаю...';
        }

        const allItems = Array.from(state.hiddenItems.values());
        const ids = allItems.map(it => it.id);

        const { error } = await supabaseClient
            .from('hidden_items').delete().in('id', ids);

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = `<i class="fas fa-eye"></i> Показать все (${total})`;
        }

        if (error) {
            alert('Ошибка: ' + error.message);
            return;
        }

        Admin.logAdminAction(
            'unhide_all_items',
            null,
            null,
            {
                count: ids.length,
                items: allItems.slice(0, 50).map(it => ({
                    section: it.section_key,
                    folder:  it.folder,
                    title:   it.title,
                })),
            }
        );

        await Admin.loadHiddenItems();
        await loadHidden();
        Admin.showToast(`Возвращено на сайт: ${ids.length}.`, 'success');
    }

    // ============================================================
    // СКАЧИВАНИЯ (с фильтрами и удалением)
    // ============================================================
    async function loadDownloads() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-download"></i> История скачиваний`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `<p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка...</p>`;

        const { data, error } = await supabaseClient
            .from('download_logs').select('*')
            .order('downloaded_at', { ascending: false })
            .limit(1000);

        if (error) {
            wrapper.innerHTML = `<p class="empty-block">Ошибка: ${MF.escapeHtml(error.message)}</p>`;
            return;
        }

        state.downloadLogsData = data || [];
        state.downloadLogsSelected = new Set();

        renderDownloadsFiltered();
    }

    function renderDownloadsFiltered() {
        const filter = state.downloadLogsFilter;
        const search = (filter.search || '').trim().toLowerCase();
        const period = filter.period || 'all';
        const now = Date.now();

        let filtered = state.downloadLogsData.slice();

        if (search) {
            filtered = filtered.filter(log => {
                const fileName = (log.file_name || '').toLowerCase();
                const fileId = (log.file_id || '').toLowerCase();
                const username = (log.username || '').toLowerCase();
                return fileName.includes(search)
                    || fileId.includes(search)
                    || username.includes(search);
            });
        }

        if (period !== 'all') {
            const limits = { today: 1, week: 7, month: 30 };
            const days = limits[period] || 1;
            const cutoff = now - days * 24 * 60 * 60 * 1000;
            filtered = filtered.filter(log => {
                const t = new Date(log.downloaded_at).getTime();
                return isFinite(t) && t >= cutoff;
            });
        }

        state.downloadLogsFiltered = filtered;
        renderDownloadsTable();
    }

    function renderDownloadsTable() {
        const wrapper = document.getElementById('tableWrapper');
        const data = state.downloadLogsFiltered;

        const filter = state.downloadLogsFilter;
        const periodOptions = [
            { value: 'all',   label: 'Все время' },
            { value: 'today', label: 'За 24 часа' },
            { value: 'week',  label: 'За неделю' },
            { value: 'month', label: 'За месяц' },
        ].map(o => {
            const sel = filter.period === o.value ? ' selected' : '';
            return `<option value="${o.value}"${sel}>${o.label}</option>`;
        }).join('');

        const filterBarHtml = `
            <div class="filters">
                <label>Поиск:
                    <input type="text" id="dlSearchInput"
                           placeholder="Название или пользователь..."
                           value="${MF.escapeAttr(filter.search || '')}">
                </label>
                <label>Период:
                    <select id="dlPeriodSelect">${periodOptions}</select>
                </label>
                <span class="spacer" style="flex:1;"></span>
                <span class="selected-info" id="dlSelectedInfo" style="display:none;"></span>
                <button class="btn-danger" id="dlDeleteSelectedBtn" disabled>
                    <i class="fas fa-trash"></i> Удалить выбранные
                </button>
                <button class="btn-danger" id="dlDeleteAllBtn" ${state.downloadLogsData.length === 0 ? 'disabled' : ''}>
                    <i class="fas fa-trash-alt"></i> Удалить все
                </button>
            </div>
        `;

        if (data.length === 0) {
            wrapper.innerHTML = `
                ${filterBarHtml}
                <p class="empty-block">Нет записей${filter.search || filter.period !== 'all' ? ' по текущим фильтрам' : ''}</p>`;
            attachDownloadsFilterHandlers();
            updateDownloadsSelectionUI();
            return;
        }

        let headHtml = `<tr>
            <th class="center"><input type="checkbox" id="dlSelectAllCheckbox"></th>
            <th>Файл</th>
            <th>Пользователь</th>
            <th>Дата и время</th>
        </tr>`;

        let bodyHtml = '';
        data.forEach(log => {
            const d = new Date(log.downloaded_at);
            const dateStr = isFinite(d.getTime())
                ? d.toLocaleDateString('ru-RU') + ' ' + d.toLocaleTimeString('ru-RU')
                : '—';
            const displayName = log.file_name || log.file_id || 'Без названия';
            const checked = state.downloadLogsSelected.has(log.id) ? 'checked' : '';
            bodyHtml += `<tr>
                <td class="center checkbox-cell">
                    <input type="checkbox" class="dl-row-checkbox"
                           data-id="${log.id}" ${checked}>
                </td>
                <td title="${MF.escapeAttr(displayName)}">
                    ${MF.escapeHtml(displayName)}
                </td>
                <td>${MF.escapeHtml(log.username || 'Неизвестный')}</td>
                <td>${MF.escapeHtml(dateStr)}</td>
            </tr>`;
        });

        const info = `Показано: <strong>${data.length}</strong> из <strong>${state.downloadLogsData.length}</strong>`;

        wrapper.innerHTML = `
            ${filterBarHtml}
            <div class="pagination-bar pagination-top" style="justify-content:flex-start;">
                <div class="pagination-total">${info}</div>
            </div>
            <div class="content-table-wrapper">
                <table class="content-table">
                    <thead>${headHtml}</thead>
                    <tbody>${bodyHtml}</tbody>
                </table>
            </div>`;

        attachDownloadsFilterHandlers();
        attachDownloadsRowHandlers();
        updateDownloadsSelectionUI();
    }

    function attachDownloadsFilterHandlers() {
        const searchInput = document.getElementById('dlSearchInput');
        if (searchInput) {
            let t = null;
            searchInput.addEventListener('input', function () {
                clearTimeout(t);
                const val = this.value;
                t = setTimeout(() => {
                    state.downloadLogsFilter.search = val;
                    renderDownloadsFiltered();
                    const ni = document.getElementById('dlSearchInput');
                    if (ni) {
                        ni.focus();
                        ni.setSelectionRange(ni.value.length, ni.value.length);
                    }
                }, 300);
            });
        }

        const periodSelect = document.getElementById('dlPeriodSelect');
        if (periodSelect) {
            periodSelect.addEventListener('change', function () {
                state.downloadLogsFilter.period = this.value;
                renderDownloadsFiltered();
            });
        }

        const deleteSelectedBtn = document.getElementById('dlDeleteSelectedBtn');
        if (deleteSelectedBtn) {
            deleteSelectedBtn.addEventListener('click', deleteSelectedDownloadLogs);
        }

        const deleteAllBtn = document.getElementById('dlDeleteAllBtn');
        if (deleteAllBtn) {
            deleteAllBtn.addEventListener('click', deleteAllDownloadLogs);
        }
    }

    function attachDownloadsRowHandlers() {
        const wrapper = document.getElementById('tableWrapper');
        if (!wrapper) return;

        const selectAll = document.getElementById('dlSelectAllCheckbox');
        if (selectAll) {
            selectAll.addEventListener('change', function () {
                const checked = this.checked;
                wrapper.querySelectorAll('.dl-row-checkbox').forEach(cb => {
                    const id = parseInt(cb.dataset.id, 10);
                    cb.checked = checked;
                    if (checked) state.downloadLogsSelected.add(id);
                    else state.downloadLogsSelected.delete(id);
                });
                updateDownloadsSelectionUI();
            });
        }

        wrapper.querySelectorAll('.dl-row-checkbox').forEach(cb => {
            cb.addEventListener('change', function () {
                const id = parseInt(this.dataset.id, 10);
                if (this.checked) state.downloadLogsSelected.add(id);
                else state.downloadLogsSelected.delete(id);
                updateDownloadsSelectionUI();
            });
        });
    }

    function updateDownloadsSelectionUI() {
        const selected = state.downloadLogsSelected.size;
        const info = document.getElementById('dlSelectedInfo');
        const deleteBtn = document.getElementById('dlDeleteSelectedBtn');

        if (info) {
            if (selected > 0) {
                info.textContent = `Выбрано: ${selected}`;
                info.style.display = 'inline';
            } else {
                info.style.display = 'none';
            }
        }

        if (deleteBtn) {
            deleteBtn.disabled = selected === 0;
        }

        const selectAll = document.getElementById('dlSelectAllCheckbox');
        const rowCheckboxes = document.querySelectorAll('.dl-row-checkbox');
        if (selectAll && rowCheckboxes.length > 0) {
            selectAll.checked = selected === rowCheckboxes.length;
        }
    }

    async function _deleteDownloadLogsByIds(ids) {
        if (!ids || ids.length === 0) return { ok: true, count: 0 };

        const chunks = [];
        for (let i = 0; i < ids.length; i += 100) {
            chunks.push(ids.slice(i, i + 100));
        }

        let deleted = 0;
        for (const chunk of chunks) {
            const { error } = await supabaseClient
                .from('download_logs')
                .delete()
                .in('id', chunk);
            if (error) {
                return { ok: false, count: deleted, error: error.message };
            }
            deleted += chunk.length;
        }
        return { ok: true, count: deleted };
    }

    async function deleteSelectedDownloadLogs() {
        const ids = Array.from(state.downloadLogsSelected);
        if (ids.length === 0) return;

        if (!confirm(`Удалить ${ids.length} записей из истории скачиваний?\n\nЭто действие необратимо.`)) {
            return;
        }

        const btn = document.getElementById('dlDeleteSelectedBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Удаляю...';
        }

        const result = await _deleteDownloadLogsByIds(ids);

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-trash"></i> Удалить выбранные';
        }

        if (result.ok) {
            Admin.logAdminAction(
                'downloads_delete_selected',
                null,
                null,
                { count: ids.length }
            );
            Admin.showToast(`Удалено ${result.count} записей.`, 'success');
            state.downloadLogsSelected = new Set();
            await loadDownloads();
        } else {
            alert('Ошибка удаления: ' + (result.error || 'неизвестная'));
            await loadDownloads();
        }
    }

    async function deleteAllDownloadLogs() {
        const total = state.downloadLogsData.length;
        if (total === 0) {
            alert('Нечего удалять.');
            return;
        }

        if (!confirm(
            `Удалить ВСЕ записи истории скачиваний (${total})?\n\n` +
            `Это действие необратимо.`
        )) return;

        const btn = document.getElementById('dlDeleteAllBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Удаляю...';
        }

        const ids = state.downloadLogsData.map(l => l.id);
        const result = await _deleteDownloadLogsByIds(ids);

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-trash-alt"></i> Удалить все';
        }

        if (result.ok) {
            Admin.logAdminAction(
                'downloads_delete_all',
                null,
                null,
                { count: result.count }
            );
            Admin.showToast(`Удалено ${result.count} записей.`, 'success');
            state.downloadLogsSelected = new Set();
            await loadDownloads();
        } else {
            alert('Ошибка удаления: ' + (result.error || 'неизвестная'));
            await loadDownloads();
        }
    }

    // ============================================================
    // СТАТИСТИКА
    // ============================================================
    async function loadStats() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-chart-simple"></i> Статистика`;
        document.getElementById('toolbar').style.display = 'none';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = '<div class="stats-grid" id="statsGrid"><div class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка...</div></div>';

        try {
            const r1 = await supabaseClient.rpc('get_total_visitors');
            const r2 = await supabaseClient.rpc('get_visitors_last_year');
            const r3 = await supabaseClient.rpc('get_visitors_last_month');
            const r4 = await supabaseClient.rpc('get_visitors_last_week');
            const r5 = await supabaseClient.rpc('get_visitors_today');
            const r6 = await supabaseClient.rpc('get_total_visit_count');

            document.getElementById('statsGrid').innerHTML = `
                <div class="stat-card"><div class="stat-value">${r6.data || 0}</div><div class="stat-label">Счётчик (всего)</div></div>
                <div class="stat-card"><div class="stat-value">${r1.data || 0}</div><div class="stat-label">Уникальных</div></div>
                <div class="stat-card"><div class="stat-value">${r2.data || 0}</div><div class="stat-label">За год</div></div>
                <div class="stat-card"><div class="stat-value">${r3.data || 0}</div><div class="stat-label">За месяц</div></div>
                <div class="stat-card"><div class="stat-value">${r4.data || 0}</div><div class="stat-label">За неделю</div></div>
                <div class="stat-card"><div class="stat-value">${r5.data || 0}</div><div class="stat-label">За сегодня</div></div>
            `;
        } catch (e) {
            wrapper.innerHTML = `<div class="empty-block">Ошибка загрузки статистики</div>`;
        }
    }

    // ============================================================
    // ОШИБКИ JS (с группировкой и CSV-экспортом)
    // ============================================================

    function groupErrors(entries) {
        const map = new Map();
        entries.forEach(e => {
            const stackHead = (e.stack || '').slice(0, 300);
            const key = `${e.page || ''}\u0001${e.message || ''}\u0001${stackHead}`;
            if (!map.has(key)) {
                map.set(key, {
                    key,
                    page: e.page,
                    message: e.message,
                    stack: e.stack,
                    first_seen: e.created_at,
                    last_seen: e.created_at,
                    count: 0,
                    ids: [],
                    user_agents: [],
                    user_ids: [],
                });
            }
            const g = map.get(key);
            g.count++;
            g.ids.push(e.id);
            if (e.created_at < g.first_seen) g.first_seen = e.created_at;
            if (e.created_at > g.last_seen) g.last_seen = e.created_at;
            if (e.user_agent && g.user_agents.indexOf(e.user_agent) === -1) {
                g.user_agents.push(e.user_agent);
            }
            if (e.user_id && g.user_ids.indexOf(e.user_id) === -1) {
                g.user_ids.push(e.user_id);
            }
        });
        return Array.from(map.values()).sort((a, b) => {
            return new Date(b.last_seen) - new Date(a.last_seen);
        });
    }

    async function loadErrors() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-bug"></i> Ошибки JavaScript`;
        document.getElementById('toolbar').style.display = 'flex';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `<p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка ошибок...</p>`;

        let query = supabaseClient
            .from('client_errors')
            .select('id, user_id, page, message, stack, user_agent, meta, created_at')
            .order('created_at', { ascending: false })
            .limit(500);

        if (state.errorsFilter.period !== 'all') {
            const now = Date.now();
            const daysMap = { today: 1, week: 7, month: 30 };
            const days = daysMap[state.errorsFilter.period] || 30;
            const cutoff = new Date(now - days * 24 * 60 * 60 * 1000).toISOString();
            query = query.gte('created_at', cutoff);
        }

        const { data, error } = await query;

        if (error) {
            wrapper.innerHTML = `<p class="empty-block">Ошибка загрузки: ${MF.escapeHtml(error.message)}</p>`;
            return;
        }

        state.errorsData = data || [];
        state.errorsPage = 1;

        renderErrorsFiltered();
    }

    function renderErrorsFiltered() {
        let filtered = state.errorsData.slice();

        if (state.errorsFilter.page) {
            filtered = filtered.filter(e => (e.page || '') === state.errorsFilter.page);
        }
        if (state.errorsFilter.search) {
            const q = state.errorsFilter.search.toLowerCase();
            filtered = filtered.filter(e => {
                const m = (e.message || '').toLowerCase();
                const s = (e.stack || '').toLowerCase();
                return m.includes(q) || s.includes(q);
            });
        }

        state.errorsFiltered = filtered;
        state.errorsGrouped = groupErrors(filtered);

        renderErrorsTable();
    }

    function renderErrorsTable() {
        const wrapper = document.getElementById('tableWrapper');
        const groups = state.errorsGrouped;
        const totalItems = groups.length;

        const totalPages = Math.max(1, Math.ceil(totalItems / state.errorsPageSize));
        if (state.errorsPage > totalPages) state.errorsPage = totalPages;
        if (state.errorsPage < 1) state.errorsPage = 1;
        const startIdx = (state.errorsPage - 1) * state.errorsPageSize;
        const pageGroups = groups.slice(startIdx, startIdx + state.errorsPageSize);

        const pagesSet = new Set();
        state.errorsData.forEach(e => { if (e.page) pagesSet.add(e.page); });
        const pagesList = Array.from(pagesSet).sort();

        const optionsHtml = pagesList.map(p => {
            const sel = state.errorsFilter.page === p ? ' selected' : '';
            return `<option value="${MF.escapeAttr(p)}"${sel}>${MF.escapeHtml(p)}</option>`;
        }).join('');

        const periodOptions = [
            { value: 'today', label: 'За сегодня' },
            { value: 'week',  label: 'За неделю' },
            { value: 'month', label: 'За месяц' },
            { value: 'all',   label: 'За всё время (500 последних)' },
        ].map(o => {
            const sel = state.errorsFilter.period === o.value ? ' selected' : '';
            return `<option value="${o.value}"${sel}>${o.label}</option>`;
        }).join('');

        const filterBarHtml = `
            <div class="filters">
                <label>Период:
                    <select id="errorsFilterPeriod">${periodOptions}</select>
                </label>
                <label>Страница:
                    <select id="errorsFilterPage">
                        <option value="">Все страницы</option>
                        ${optionsHtml}
                    </select>
                </label>
                <label>Поиск:
                    <input type="text" id="errorsFilterSearch"
                           placeholder="По сообщению или stack..."
                           value="${MF.escapeAttr(state.errorsFilter.search)}">
                </label>
                <span class="spacer" style="flex:1;"></span>
                <button class="btn-secondary" id="errorsExportCsvBtn" title="Скачать как CSV">
                    <i class="fas fa-file-csv"></i> Экспорт в CSV
                </button>
                <button class="btn-secondary" id="errorsFilterReset">
                    <i class="fas fa-times"></i> Сбросить
                </button>
            </div>
        `;

        const totalRecords = state.errorsFiltered.length;
        const uniqueGroups = groups.length;
        const bannerHtml = totalRecords === 0
            ? ''
            : `<div class="errors-banner">
                    <i class="fas fa-bug"></i>
                    <div>
                        Найдено <strong>${uniqueGroups}</strong> уникальных ошибок
                        (${totalRecords} записей).
                        <br>
                        <small>
                            Показаны сгруппированные по сообщению и месту вызова.
                            Вкладка хранит <strong>последние 500 записей</strong>,
                            старые удаляются автоочисткой.
                        </small>
                        <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">
                            <button class="btn-danger" id="errorsCleanupBtn">
                                <i class="fas fa-broom"></i> Очистить старше 30 дней
                            </button>
                            <button class="btn-secondary" id="errorsDeleteAllBtn">
                                <i class="fas fa-trash-alt"></i> Удалить все (${state.errorsData.length})
                            </button>
                        </div>
                    </div>
               </div>`;

        let headHtml = `<tr>
            <th>Последний раз</th>
            <th>Страница</th>
            <th>Сообщение</th>
            <th class="center">Повторов</th>
            <th>Пользователи</th>
            <th>Браузер</th>
        </tr>`;

        let bodyHtml = '';
        if (pageGroups.length === 0) {
            bodyHtml = `<tr><td colspan="6" class="empty-block">Ошибок за выбранный период нет ✓</td></tr>`;
        } else {
            pageGroups.forEach(g => {
                const dt = new Date(g.last_seen);
                const dateStr = dt.toLocaleDateString('ru-RU') + ' ' +
                                dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' });

                const ua = g.user_agents[0] || '';
                let uaShort = '—';
                if (ua) {
                    const browserMatch = ua.match(/(Firefox|Chrome|Safari|Edge|Opera|OPR|YaBrowser)\/[\d.]+/);
                    const osMatch = ua.match(/\((Windows NT [\d.]+|Mac OS X [\d_.]+|Linux|Android [\d.]+|iPhone OS [\d_.]+)\)/);
                    const browser = browserMatch ? browserMatch[0] : ua.slice(0, 25);
                    const os = osMatch ? osMatch[1].replace(/_/g, '.').slice(0, 20) : '';
                    uaShort = (browser + (os ? ' • ' + os : '')).slice(0, 60);
                    if (g.user_agents.length > 1) {
                        uaShort += ` +${g.user_agents.length - 1}`;
                    }
                }

                const usersCount = g.user_ids.length;
                const usersLabel = usersCount === 0 ? 'анонимы' :
                    (usersCount === 1 ? '1 польз.' : `${usersCount} польз.`);

                const groupIdx = state.errorsGrouped.indexOf(g);

                bodyHtml += `<tr data-group-idx="${groupIdx}" style="cursor:pointer;">
                    <td><span class="error-row-time">${MF.escapeHtml(dateStr)}</span></td>
                    <td><span class="error-row-page">${MF.escapeHtml(g.page || '—')}</span></td>
                    <td title="${MF.escapeAttr(g.message || '')}">
                        <span class="error-row-msg">${MF.escapeHtml(g.message || '')}</span>
                    </td>
                    <td class="center"><span class="error-count-badge">×${g.count}</span></td>
                    <td style="font-size:12px; color:#64748b;">${MF.escapeHtml(usersLabel)}</td>
                    <td title="${MF.escapeAttr(ua)}"><span style="font-size:11px; color:#64748b;">${MF.escapeHtml(uaShort)}</span></td>
                </tr>`;
            });
        }

        const stateObj = {
            pageSize: state.errorsPageSize,
            currentPage: state.errorsPage,
            totalItems: totalItems,
        };

        const paginationTop = (totalPages > 1)
            ? MF.renderPagination('errors-container', totalItems, totalPages, stateObj, 'top')
            : '';
        const paginationBottom = (totalPages > 1)
            ? MF.renderPagination('errors-container', totalItems, totalPages, stateObj, 'bottom')
            : '';

        wrapper.innerHTML = `
            ${filterBarHtml}
            ${bannerHtml}
            <div id="errors-container">
                ${paginationTop}
                <div class="content-table-wrapper">
                    <table class="content-table">
                        <thead>${headHtml}</thead>
                        <tbody>${bodyHtml}</tbody>
                    </table>
                </div>
                ${paginationBottom}
            </div>`;

        const periodSel = document.getElementById('errorsFilterPeriod');
        if (periodSel) periodSel.addEventListener('change', function () {
            state.errorsFilter.period = this.value;
            loadErrors();
        });

        const pageSel = document.getElementById('errorsFilterPage');
        if (pageSel) pageSel.addEventListener('change', function () {
            state.errorsFilter.page = this.value;
            state.errorsPage = 1;
            renderErrorsFiltered();
        });

        const searchInput = document.getElementById('errorsFilterSearch');
        if (searchInput) {
            let t = null;
            searchInput.addEventListener('input', function () {
                clearTimeout(t);
                const val = this.value;
                t = setTimeout(() => {
                    state.errorsFilter.search = val;
                    state.errorsPage = 1;
                    renderErrorsFiltered();
                    const ni = document.getElementById('errorsFilterSearch');
                    if (ni) {
                        ni.focus();
                        ni.setSelectionRange(ni.value.length, ni.value.length);
                    }
                }, 300);
            });
        }

        const resetBtn = document.getElementById('errorsFilterReset');
        if (resetBtn) resetBtn.addEventListener('click', () => {
            state.errorsFilter = { period: 'week', page: '', search: '' };
            state.errorsPage = 1;
            loadErrors();
        });

        const exportBtn = document.getElementById('errorsExportCsvBtn');
        if (exportBtn) exportBtn.addEventListener('click', exportErrorsToCSV);

        const cleanupBtn = document.getElementById('errorsCleanupBtn');
        if (cleanupBtn) cleanupBtn.addEventListener('click', cleanupOldErrors);

        const deleteAllBtn = document.getElementById('errorsDeleteAllBtn');
        if (deleteAllBtn) deleteAllBtn.addEventListener('click', deleteAllErrors);

        wrapper.querySelectorAll('tr[data-group-idx]').forEach(tr => {
            tr.addEventListener('click', function () {
                const idx = parseInt(this.dataset.groupIdx, 10);
                openGroupDetails(idx);
            });
        });

        const errorsContainer = document.getElementById('errors-container');
        if (errorsContainer && totalPages > 1) {
            MF.attachPaginationHandlers(
                errorsContainer,
                'errors-container',
                stateObj,
                () => {
                    state.errorsPage = stateObj.currentPage;
                    state.errorsPageSize = stateObj.pageSize;
                    renderErrorsTable();
                },
                { scrollTarget: errorsContainer, scrollOffset: 120 }
            );
        }
    }

    function openGroupDetails(groupIdx) {
        const g = state.errorsGrouped[groupIdx];
        if (!g) return;

        const modal = document.getElementById('userEditModal');
        const box = modal.querySelector('.modal-box');

        const firstSeen = new Date(g.first_seen).toLocaleString('ru-RU');
        const lastSeen  = new Date(g.last_seen).toLocaleString('ru-RU');

        const uaHtml = g.user_agents.length > 0
            ? '<ul style="margin:0; padding-left:18px; font-size:12px; color:#475569; word-break:break-all;">'
                + g.user_agents.map(u => `<li>${MF.escapeHtml(u)}</li>`).join('')
              + '</ul>'
            : '<i style="color:#94a3b8;">нет данных</i>';

        const userIdsHtml = g.user_ids.length > 0
            ? '<ul style="margin:0; padding-left:18px; font-size:12px; color:#475569;">'
                + g.user_ids.map(u => `<li><code>${MF.escapeHtml(u)}</code></li>`).join('')
              + '</ul>'
            : '<i style="color:#94a3b8;">анонимы</i>';

        const idsPreview = g.ids.slice(0, 20).join(', ') + (g.ids.length > 20 ? ' …' : '');

        const stackHtml = g.stack
            ? `<pre class="error-detail-pre" id="errorStackBlock">${MF.escapeHtml(g.stack)}</pre>`
            : '<i style="color:#94a3b8;">стек не передан</i>';

        box.innerHTML = `
            <h3><i class="fas fa-bug" style="color:#dc2626;"></i>
                Группа ошибок <span class="error-count-badge">×${g.count}</span>
            </h3>

            <div class="error-detail-label">Страница</div>
            <div class="error-detail-value">
                <span class="error-row-page">${MF.escapeHtml(g.page || '—')}</span>
            </div>

            <div class="error-detail-label">Сообщение</div>
            <div class="error-detail-value" style="font-weight:600; color:#7f1d1d;">
                ${MF.escapeHtml(g.message || '')}
            </div>

            <div class="error-detail-label">Первый раз / последний раз</div>
            <div class="error-detail-value">
                ${MF.escapeHtml(firstSeen)} → ${MF.escapeHtml(lastSeen)}
            </div>

            <div class="error-detail-label">Пользователи (${g.user_ids.length})</div>
            <div class="error-detail-value">${userIdsHtml}</div>

            <div class="error-detail-label">Браузеры (${g.user_agents.length})</div>
            <div class="error-detail-value">${uaHtml}</div>

            <div class="error-detail-label">Стек вызовов</div>
            ${stackHtml}

            <div class="error-detail-label">ID записей (${g.ids.length})</div>
            <div class="error-detail-value" style="font-size:11px; color:#64748b;">
                ${MF.escapeHtml(idsPreview)}
            </div>

            <div class="modal-actions">
                <button class="btn-secondary" id="errorCopyStackBtn">
                    <i class="fas fa-copy"></i> Копировать stack
                </button>
                <button class="btn-secondary" onclick="Admin.closeUserEditModal()">Закрыть</button>
                <button class="btn-danger" id="errorDeleteGroupBtn">
                    <i class="fas fa-trash"></i> Удалить всю группу (${g.count})
                </button>
            </div>
        `;
        modal.classList.add('active');

        const copyBtn = document.getElementById('errorCopyStackBtn');
        if (copyBtn) {
            copyBtn.addEventListener('click', async () => {
                try {
                    await navigator.clipboard.writeText(g.stack || g.message || '');
                    copyBtn.innerHTML = '<i class="fas fa-check"></i> Скопировано';
                    setTimeout(() => {
                        copyBtn.innerHTML = '<i class="fas fa-copy"></i> Копировать stack';
                    }, 2000);
                } catch (e) {
                    alert('Не удалось скопировать: ' + e.message);
                }
            });
        }

        const deleteGroupBtn = document.getElementById('errorDeleteGroupBtn');
        if (deleteGroupBtn) {
            deleteGroupBtn.addEventListener('click', async () => {
                if (!confirm(
                    `Удалить все ${g.count} записей этой группы?\n\n` +
                    `Это действие необратимо.`
                )) return;

                deleteGroupBtn.disabled = true;
                deleteGroupBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Удаляю...';

                const ids = g.ids;
                const chunks = [];
                for (let i = 0; i < ids.length; i += 100) {
                    chunks.push(ids.slice(i, i + 100));
                }

                let allOk = true;
                for (const chunk of chunks) {
                    const { error } = await supabaseClient
                        .from('client_errors').delete().in('id', chunk);
                    if (error) {
                        allOk = false;
                        alert('Ошибка удаления: ' + error.message);
                        break;
                    }
                }

                deleteGroupBtn.disabled = false;
                deleteGroupBtn.innerHTML = `<i class="fas fa-trash"></i> Удалить всю группу (${g.count})`;

                if (allOk) {
                    Admin.logAdminAction(
                        'error_delete_group',
                        null,
                        null,
                        {
                            count: ids.length,
                            page: g.page,
                            message: (g.message || '').slice(0, 200),
                        }
                    );
                    Admin.showToast(`Удалено ${ids.length} записей группы.`, 'success');
                    Admin.closeUserEditModal();
                    await Admin.refreshErrorsBadge();
                    await loadErrors();
                }
            });
        }
    }

    async function cleanupOldErrors() {
        if (!confirm(
            'Удалить все записи об ошибках старше 30 дней?\n\n' +
            'Это действие необратимо.'
        )) return;

        const cutoff = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();

        const btn = document.getElementById('errorsCleanupBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Очищаю...';
        }

        const { error } = await supabaseClient
            .from('client_errors')
            .delete()
            .lt('created_at', cutoff);

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-broom"></i> Очистить старше 30 дней';
        }

        if (error) {
            alert('Ошибка: ' + error.message);
            return;
        }

        Admin.logAdminAction(
            'error_cleanup',
            null,
            null,
            { cutoff: cutoff, days: 30 }
        );

        Admin.showToast('Старые записи удалены.', 'success');
        await Admin.refreshErrorsBadge();
        await loadErrors();
    }

    async function deleteAllErrors() {
        const total = state.errorsData.length;
        if (total === 0) {
            alert('Нечего удалять.');
            return;
        }
        if (!confirm(
            `Удалить ВСЕ записи об ошибках (${total})?\n\n` +
            `Это действие необратимо.`
        )) return;

        const btn = document.getElementById('errorsDeleteAllBtn');
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Удаляю...';
        }

        const ids = state.errorsData.map(e => e.id);
        const chunks = [];
        for (let i = 0; i < ids.length; i += 100) {
            chunks.push(ids.slice(i, i + 100));
        }

        let allOk = true;
        for (const chunk of chunks) {
            const { error } = await supabaseClient
                .from('client_errors').delete().in('id', chunk);
            if (error) {
                allOk = false;
                alert('Ошибка удаления: ' + error.message);
                break;
            }
        }

        if (btn) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-trash-alt"></i> Удалить все';
        }

        if (allOk) {
            Admin.logAdminAction(
                'error_delete_all',
                null,
                null,
                { count: ids.length }
            );
            Admin.showToast(`Удалено ${ids.length} записей.`, 'success');
            await Admin.refreshErrorsBadge();
            await loadErrors();
        }
    }

    function exportErrorsToCSV() {
        const rows = state.errorsFiltered;
        if (rows.length === 0) {
            alert('Нет данных для экспорта (по текущим фильтрам).');
            return;
        }

        const header = [
            'ID', 'Время', 'Страница', 'Сообщение',
            'Стек', 'User-Agent', 'User ID',
        ];

        function csvCell(cell) {
            const s = cell === null || cell === undefined ? '' : String(cell);
            if (/[",\n\r\t]/.test(s)) {
                return '"' + s.replace(/"/g, '""') + '"';
            }
            return s;
        }

        const lines = [];
        lines.push(header.map(csvCell).join(','));

        rows.forEach(e => {
            lines.push([
                csvCell(e.id),
                csvCell(e.created_at || ''),
                csvCell(e.page || ''),
                csvCell(e.message || ''),
                csvCell(e.stack || ''),
                csvCell(e.user_agent || ''),
                csvCell(e.user_id || ''),
            ].join(','));
        });

        const csv = lines.join('\r\n');

        const blob = new Blob(['\ufeff' + csv], {
            type: 'text/csv;charset=utf-8;',
        });

        const now = new Date();
        const dateStr = now.toISOString().slice(0, 19).replace(/[:T]/g, '-');
        const filename = `client_errors_${dateStr}.csv`;

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 4000);

        Admin.showToast(`Экспортировано ${rows.length} записей → ${filename}`, 'success');
    }

    // ============================================================
    // ЖУРНАЛ ДЕЙСТВИЙ АДМИНИСТРАТОРА
    // ============================================================

    async function loadAdminActions() {
        document.getElementById('sectionTitle').innerHTML =
            `<i class="fas fa-clipboard-list"></i> Журнал действий`;
        document.getElementById('toolbar').style.display = 'flex';
        document.getElementById('deleteSelectedBtn').style.display = 'none';
        document.getElementById('hideSelectedBtn').style.display = 'none';
        document.getElementById('unhideSelectedBtn').style.display = 'none';

        const wrapper = document.getElementById('tableWrapper');
        wrapper.innerHTML = `<p class="empty-block"><i class="fas fa-spinner fa-spin"></i> Загрузка журнала...</p>`;

        // Загружаем последние 500 записей
        let query = supabaseClient
            .from('admin_actions')
            .select('id, admin_id, admin_name, action, section_key, target, details, created_at')
            .order('created_at', { ascending: false })
            .limit(500);

        // Фильтр по периоду (серверный)
        const period = state.actionsFilter.period;
        if (period !== 'all') {
            const now = Date.now();
            const daysMap = { today: 1, week: 7, month: 30 };
            const days = daysMap[period] || 30;
            const cutoff = new Date(now - days * 24 * 60 * 60 * 1000).toISOString();
            query = query.gte('created_at', cutoff);
        }

        const { data, error } = await query;

        if (error) {
            wrapper.innerHTML = `<p class="empty-block">Ошибка загрузки: ${MF.escapeHtml(error.message)}</p>`;
            return;
        }

        state.actionsData = data || [];
        state.actionsPage = 1;

        renderActionsFiltered();
    }

    function renderActionsFiltered() {
        let filtered = state.actionsData.slice();

        // Локальные фильтры: action, admin, поиск
        const f = state.actionsFilter;

        if (f.action) {
            filtered = filtered.filter(a => a.action === f.action);
        }

        if (f.admin) {
            filtered = filtered.filter(a => a.admin_name === f.admin);
        }

        if (f.search) {
            const q = f.search.toLowerCase();
            filtered = filtered.filter(a => {
                const t = (a.target || '').toLowerCase();
                const s = (a.section_key || '').toLowerCase();
                const d = a.details ? JSON.stringify(a.details).toLowerCase() : '';
                return t.includes(q) || s.includes(q) || d.includes(q);
            });
        }

        state.actionsFiltered = filtered;
        renderActionsTable();
    }

    function renderActionsTable() {
        const wrapper = document.getElementById('tableWrapper');
        const data = state.actionsFiltered;
        const totalItems = data.length;

        const totalPages = Math.max(1, Math.ceil(totalItems / state.actionsPageSize));
        if (state.actionsPage > totalPages) state.actionsPage = totalPages;
        if (state.actionsPage < 1) state.actionsPage = 1;
        const startIdx = (state.actionsPage - 1) * state.actionsPageSize;
        const pageItems = data.slice(startIdx, startIdx + state.actionsPageSize);

        // Уникальные значения для селектов фильтра
        const actionSet = new Set();
        state.actionsData.forEach(a => { if (a.action) actionSet.add(a.action); });
        const actionsList = Array.from(actionSet).sort();

        const adminSet = new Set();
        state.actionsData.forEach(a => { if (a.admin_name) adminSet.add(a.admin_name); });
        const adminsList = Array.from(adminSet).sort();

        const actionOptions = actionsList.map(a => {
            const sel = state.actionsFilter.action === a ? ' selected' : '';
            return `<option value="${MF.escapeAttr(a)}"${sel}>${MF.escapeHtml(actionLabel(a))}</option>`;
        }).join('');

        const adminOptions = adminsList.map(a => {
            const sel = state.actionsFilter.admin === a ? ' selected' : '';
            return `<option value="${MF.escapeAttr(a)}"${sel}>${MF.escapeHtml(a)}</option>`;
        }).join('');

        const periodOptions = [
            { value: 'today', label: 'За сегодня' },
            { value: 'week',  label: 'За неделю' },
            { value: 'month', label: 'За месяц' },
            { value: 'all',   label: 'За всё время (500 последних)' },
        ].map(o => {
            const sel = state.actionsFilter.period === o.value ? ' selected' : '';
            return `<option value="${o.value}"${sel}>${o.label}</option>`;
        }).join('');

        const filterBarHtml = `
            <div class="filters">
                <label>Период:
                    <select id="actionsFilterPeriod">${periodOptions}</select>
                </label>
                <label>Действие:
                    <select id="actionsFilterAction">
                        <option value="">Все</option>
                        ${actionOptions}
                    </select>
                </label>
                <label>Администратор:
                    <select id="actionsFilterAdmin">
                        <option value="">Все</option>
                        ${adminOptions}
                    </select>
                </label>
                <label>Поиск:
                    <input type="text" id="actionsFilterSearch"
                           placeholder="Цель или детали..."
                           value="${MF.escapeAttr(state.actionsFilter.search)}">
                </label>
                <span class="spacer" style="flex:1;"></span>
                <button class="btn-secondary" id="actionsExportCsvBtn">
                    <i class="fas fa-file-csv"></i> Экспорт в CSV
                </button>
                <button class="btn-secondary" id="actionsFilterReset">
                    <i class="fas fa-times"></i> Сбросить
                </button>
            </div>
        `;

        const bannerHtml = totalItems === 0
            ? ''
            : `<div class="errors-banner" style="background:#eff6ff; border-color:#93c5fd; color:#1e3a8a;">
                    <i class="fas fa-clipboard-list" style="color:#2563eb;"></i>
                    <div>
                        Найдено <strong>${totalItems}</strong> действий за выбранный период.
                        <br>
                        <small>
                            Журнал хранит <strong>последние 500 записей</strong>.
                            Записи неизменяемы — их можно только удалить целиком.
                        </small>
                    </div>
               </div>`;

        let headHtml = `<tr>
            <th>Время</th>
            <th>Администратор</th>
            <th>Действие</th>
            <th>Раздел</th>
            <th>Цель</th>
            <th class="center">Детали</th>
        </tr>`;

        let bodyHtml = '';
        if (pageItems.length === 0) {
            bodyHtml = `<tr><td colspan="6" class="empty-block">За выбранный период действий нет</td></tr>`;
        } else {
            pageItems.forEach(a => {
                const dt = new Date(a.created_at);
                const dateStr = isFinite(dt.getTime())
                    ? dt.toLocaleDateString('ru-RU') + ' ' +
                      dt.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
                    : '—';

                const hasDetails = a.details && Object.keys(a.details).length > 0;
                const actionIdx = state.actionsFiltered.indexOf(a);

                bodyHtml += `<tr data-action-idx="${actionIdx}" style="cursor:${hasDetails ? 'pointer' : 'default'};">
                    <td><span class="error-row-time">${MF.escapeHtml(dateStr)}</span></td>
                    <td><strong>${MF.escapeHtml(a.admin_name || '—')}</strong></td>
                    <td><span class="role-badge role-user">${MF.escapeHtml(actionLabel(a.action))}</span></td>
                    <td>${a.section_key
                        ? `<code>${MF.escapeHtml(a.section_key)}</code>`
                        : '—'}</td>
                    <td title="${MF.escapeAttr(a.target || '')}">
                        ${a.target
                            ? MF.escapeHtml(String(a.target).slice(0, 60))
                            : '—'}
                    </td>
                    <td class="center">
                        ${hasDetails
                            ? `<i class="fas fa-info-circle" style="color:#2563eb;"></i>`
                            : '—'}
                    </td>
                </tr>`;
            });
        }

        const stateObj = {
            pageSize: state.actionsPageSize,
            currentPage: state.actionsPage,
            totalItems: totalItems,
        };

        const paginationTop = (totalPages > 1)
            ? MF.renderPagination('actions-container', totalItems, totalPages, stateObj, 'top')
            : '';
        const paginationBottom = (totalPages > 1)
            ? MF.renderPagination('actions-container', totalItems, totalPages, stateObj, 'bottom')
            : '';

        wrapper.innerHTML = `
            ${filterBarHtml}
            ${bannerHtml}
            <div id="actions-container">
                ${paginationTop}
                <div class="content-table-wrapper">
                    <table class="content-table">
                        <thead>${headHtml}</thead>
                        <tbody>${bodyHtml}</tbody>
                    </table>
                </div>
                ${paginationBottom}
            </div>`;

        // Обработчики фильтров
        const periodSel = document.getElementById('actionsFilterPeriod');
        if (periodSel) periodSel.addEventListener('change', function () {
            state.actionsFilter.period = this.value;
            loadAdminActions();
        });

        const actionSel = document.getElementById('actionsFilterAction');
        if (actionSel) actionSel.addEventListener('change', function () {
            state.actionsFilter.action = this.value;
            state.actionsPage = 1;
            renderActionsFiltered();
        });

        const adminSel = document.getElementById('actionsFilterAdmin');
        if (adminSel) adminSel.addEventListener('change', function () {
            state.actionsFilter.admin = this.value;
            state.actionsPage = 1;
            renderActionsFiltered();
        });

        const searchInput = document.getElementById('actionsFilterSearch');
        if (searchInput) {
            let t = null;
            searchInput.addEventListener('input', function () {
                clearTimeout(t);
                const val = this.value;
                t = setTimeout(() => {
                    state.actionsFilter.search = val;
                    state.actionsPage = 1;
                    renderActionsFiltered();
                    const ni = document.getElementById('actionsFilterSearch');
                    if (ni) {
                        ni.focus();
                        ni.setSelectionRange(ni.value.length, ni.value.length);
                    }
                }, 300);
            });
        }

        const resetBtn = document.getElementById('actionsFilterReset');
        if (resetBtn) resetBtn.addEventListener('click', () => {
            state.actionsFilter = {
                period: 'week', action: '', admin: '', search: '',
            };
            state.actionsPage = 1;
            loadAdminActions();
        });

        const exportBtn = document.getElementById('actionsExportCsvBtn');
        if (exportBtn) exportBtn.addEventListener('click', exportActionsToCSV);

        // Клик по строке → модалка с деталями
        wrapper.querySelectorAll('tr[data-action-idx]').forEach(tr => {
            tr.addEventListener('click', function () {
                const idx = parseInt(this.dataset.actionIdx, 10);
                const a = state.actionsFiltered[idx];
                if (!a || !a.details) return;
                openActionDetails(a);
            });
        });

        const container = document.getElementById('actions-container');
        if (container && totalPages > 1) {
            MF.attachPaginationHandlers(
                container,
                'actions-container',
                stateObj,
                () => {
                    state.actionsPage = stateObj.currentPage;
                    state.actionsPageSize = stateObj.pageSize;
                    renderActionsTable();
                },
                { scrollTarget: container, scrollOffset: 120 }
            );
        }
    }

    function openActionDetails(a) {
        const modal = document.getElementById('userEditModal');
        const box = modal.querySelector('.modal-box');

        const dt = new Date(a.created_at);
        const dateStr = dt.toLocaleString('ru-RU');

        // Красиво отформатируем JSON
        let detailsJson = '';
        try {
            detailsJson = JSON.stringify(a.details, null, 2);
        } catch (e) {
            detailsJson = String(a.details);
        }

        box.innerHTML = `
            <h3><i class="fas fa-clipboard-list" style="color:#2563eb;"></i>
                Детали действия #${a.id}
            </h3>

            <div class="error-detail-label">Время</div>
            <div class="error-detail-value">${MF.escapeHtml(dateStr)}</div>

            <div class="error-detail-label">Администратор</div>
            <div class="error-detail-value">
                <strong>${MF.escapeHtml(a.admin_name || '—')}</strong>
                <br>
                <small style="color:#94a3b8;">${MF.escapeHtml(a.admin_id || '')}</small>
            </div>

            <div class="error-detail-label">Действие</div>
            <div class="error-detail-value">
                <span class="role-badge role-user">${MF.escapeHtml(actionLabel(a.action))}</span>
                <code style="margin-left:8px;">${MF.escapeHtml(a.action)}</code>
            </div>

            ${a.section_key ? `
                <div class="error-detail-label">Раздел</div>
                <div class="error-detail-value"><code>${MF.escapeHtml(a.section_key)}</code></div>
            ` : ''}

            ${a.target ? `
                <div class="error-detail-label">Цель</div>
                <div class="error-detail-value">${MF.escapeHtml(a.target)}</div>
            ` : ''}

            ${detailsJson ? `
                <div class="error-detail-label">Детали (JSON)</div>
                <pre class="error-detail-pre">${MF.escapeHtml(detailsJson)}</pre>
            ` : ''}

            <div class="modal-actions">
                <button class="btn-secondary" onclick="Admin.closeUserEditModal()">Закрыть</button>
            </div>
        `;
        modal.classList.add('active');
    }

    function exportActionsToCSV() {
        const rows = state.actionsFiltered;
        if (rows.length === 0) {
            alert('Нет данных для экспорта (по текущим фильтрам).');
            return;
        }

        const header = [
            'ID', 'Время', 'Администратор', 'Admin ID',
            'Действие', 'Раздел', 'Цель', 'Детали (JSON)',
        ];

        function csvCell(cell) {
            const s = cell === null || cell === undefined ? '' : String(cell);
            if (/[",\n\r\t]/.test(s)) {
                return '"' + s.replace(/"/g, '""') + '"';
            }
            return s;
        }

        const lines = [];
        lines.push(header.map(csvCell).join(','));

        rows.forEach(a => {
            let detailsStr = '';
            if (a.details) {
                try {
                    detailsStr = JSON.stringify(a.details);
                } catch (e) {
                    detailsStr = String(a.details);
                }
            }
            lines.push([
                csvCell(a.id),
                csvCell(a.created_at || ''),
                csvCell(a.admin_name || ''),
                csvCell(a.admin_id || ''),
                csvCell(a.action || ''),
                csvCell(a.section_key || ''),
                csvCell(a.target || ''),
                csvCell(detailsStr),
            ].join(','));
        });

        const csv = lines.join('\r\n');
        const blob = new Blob(['\ufeff' + csv], {
            type: 'text/csv;charset=utf-8;',
        });

        const now = new Date();
        const dateStr = now.toISOString().slice(0, 19).replace(/[:T]/g, '-');
        const filename = `admin_actions_${dateStr}.csv`;

        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(() => URL.revokeObjectURL(url), 4000);

        Admin.showToast(`Экспортировано ${rows.length} записей → ${filename}`, 'success');
    }

    // ============================================================
    // ЭКСПОРТ
    // ============================================================
    Object.assign(Admin, {
        // Разделы
        renderSectionsAdmin,
        loadSectionsFromDB,
        editSection,
        deleteSection,
        openSectionModal,
        saveSection,

        // Папки
        renderFoldersAdmin,
        renderFoldersTable,
        deleteFolder,

        // Пользователи
        loadUsers,
        openUserEditModal,
        saveUser,
        deleteUser,

        // Посетители
        loadVisitors,

        // Осиротевшие
        loadOrphans,
        showOrphansByIndex,
        deleteSelectedOrphans,
        deleteAllOrphans,

        // Скрытые
        loadHidden,
        unhideOne,
        unhideAll,

        // Скачивания
        loadDownloads,
        renderDownloadsFiltered,
        renderDownloadsTable,
        deleteSelectedDownloadLogs,
        deleteAllDownloadLogs,

        // Статистика
        loadStats,

        // Ошибки JS
        loadErrors,
        renderErrorsFiltered,
        renderErrorsTable,
        openGroupDetails,
        cleanupOldErrors,
        deleteAllErrors,
        exportErrorsToCSV,
        groupErrors,

        // Журнал действий
        loadAdminActions,
        renderActionsFiltered,
        renderActionsTable,
        openActionDetails,
        exportActionsToCSV,
        actionLabel,
    });
})();
