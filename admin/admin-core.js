/* admin-core.js — базовый модуль админ-панели MyFiles */
(function () {
    'use strict';

    if (!window.Admin) window.Admin = {};
    if (!window.AdminState) window.AdminState = {};

    const CFG = window.APP_CONFIG;
    const MF  = window.MF;
    const supabaseClient = MF.getSupabaseClient();
    const SUPABASE_URL   = CFG.SUPABASE_URL;

    const state = window.AdminState;

    // ─── Значения по умолчанию ───
    state.currentUser         = null;
    state.currentProfile      = null;
    state.currentTab          = 'programs';
    state.sectionsList        = [];
    state.currentFolderSection = null;
    state.foldersList         = [];
    state.sectionData         = {};
    state.tableStates         = {};
    state.contentViews        = {};
    state.contentFolderFilters = {};
    state.hiddenItems         = new Map();
    state.hiddenTotalCount    = 0;
    state.orphansTotalCount   = 0;
    state.errorsBadgeCount    = 0;
    state.actionsBadgeCount   = 0;
    state.downloadCounts      = {};
    state.hideInProgress      = false;
    state.unhideInProgress    = false;

    let _badgesIntervalId = null;

    // ============================================================
    // ЖУРНАЛ ДЕЙСТВИЙ АДМИНИСТРАТОРА
    // ============================================================
    function logAdminAction(action, sectionKey, target, details) {
        if (!state.currentUser) return;
        if (!action) return;

        const payload = {
            admin_id:    state.currentUser.id,
            admin_name:  state.currentProfile?.username
                         || state.currentUser.email
                         || 'unknown',
            action:      String(action).slice(0, 100),
            section_key: sectionKey ? String(sectionKey).slice(0, 100) : null,
            target:      target ? String(target).slice(0, 500) : null,
            details:     details || null,
        };

        supabaseClient
            .from('admin_actions')
            .insert([payload])
            .then(({ error }) => {
                if (error) {
                    console.warn('[logAdminAction] ошибка записи:', error.message);
                }
            })
            .catch((e) => {
                console.warn('[logAdminAction] исключение:', e);
            });
    }

    // ============================================================
    // ПРОКСИ-ССЫЛКА ДЛЯ СКАЧИВАНИЯ
    // ============================================================
    // Единый источник правды — MF.buildProxyUrl в shared.js.
    // Здесь оставлен публичный алиас для обратной совместимости
    // (admin-content.js вызывает Admin.buildProxyUrl).
    // ============================================================
    const buildProxyUrl = MF.buildProxyUrl;

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
    // МОДАЛКА ОБНОВЛЕНИЯ КОНТЕНТА
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

        function renderSourceBlock(sourceKey, sourceLabel, iconClass, sections) {
            if (sections.length === 0) {
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
            const listHtml = sections.map(s => `
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
                label:    'Яндекс.Диск',
                workflow: 'sync-yandex.yml',
                inputs:   { sections: yandexSections.join(',') },
            });
        }
        if (teraboxSections.length > 0) {
            tasks.push({
                label:    'TeraBox',
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
            logAdminAction('run_workflow', null, null, {
                tasks: tasks.map(t => ({
                    workflow: t.workflow,
                    sections: t.inputs.sections,
                })),
            });
            const text = launched.length === 1
                ? `Обновление ${launched[0]} запущено. Результат придёт в Telegram.`
                : `Обновление запущено (${launched.join(', ')}). Результат придёт в Telegram.`;
            showToast(text, 'success');
        } else if (launched.length > 0) {
            closeRefreshModal();
            logAdminAction('run_workflow_partial', null, null, {
                launched: launched,
                failed: failed,
            });
            showToast(`Запущено: ${launched.join(', ')}. Ошибки: ${failed.join('; ')}`, 'info');
        } else {
            showToast('Не удалось запустить: ' + failed.join('; '), 'error');
        }
    }

    // ============================================================
    // СКРЫТЫЕ (общие функции)
    // ============================================================
    function makeHiddenKey(sectionKey, folder, title) {
        const f = (folder || '').trim().toLowerCase();
        const t = (title  || '').trim().toLowerCase();
        return `${sectionKey}|${f}|${t}`;
    }

    function isHidden(sectionKey, folder, title) {
        return state.hiddenItems.has(makeHiddenKey(sectionKey, folder, title));
    }

    async function loadHiddenItems() {
        try {
            const { data, error } = await supabaseClient
                .from('hidden_items')
                .select('id, section_key, folder, title, hidden_at, note');
            if (error) {
                console.warn('hidden_items:', error);
                state.hiddenItems = new Map();
                state.hiddenTotalCount = 0;
            } else {
                state.hiddenItems = new Map();
                (data || []).forEach(row => {
                    const key = makeHiddenKey(row.section_key, row.folder, row.title);
                    state.hiddenItems.set(key, {
                        id: row.id,
                        section_key: row.section_key,
                        folder: row.folder,
                        title: row.title,
                        hidden_at: row.hidden_at,
                        note: row.note,
                    });
                });
                state.hiddenTotalCount = state.hiddenItems.size;
            }
            updateHiddenBadge();
        } catch (e) {
            console.warn('loadHiddenItems exception:', e);
            state.hiddenItems = new Map();
            state.hiddenTotalCount = 0;
            updateHiddenBadge();
        }
    }

    function updateHiddenBadge() {
        const badge = document.getElementById('hiddenBadge');
        if (!badge) return;
        if (state.hiddenTotalCount > 0) {
            badge.textContent = state.hiddenTotalCount;
            badge.style.display = 'inline-block';
        } else {
            badge.style.display = 'none';
        }
    }

    // ============================================================
    // BADGES: ОСИРОТЕВШИЕ + ОШИБКИ JS + ЖУРНАЛ
    // ============================================================
    async function refreshOrphansBadge() {
        try {
            const { data, error } = await supabaseClient
                .from('sync_orphans')
                .select('orphans');
            if (error) return;
            let total = 0;
            (data || []).forEach(item => {
                if (Array.isArray(item.orphans)) total += item.orphans.length;
            });
            state.orphansTotalCount = total;
            const badge = document.getElementById('orphansBadge');
            if (!badge) return;
            if (total > 0) {
                badge.textContent = total;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        } catch (e) {
            /* тихо */
        }
    }

    async function refreshErrorsBadge() {
        try {
            const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
            const { count, error } = await supabaseClient
                .from('client_errors')
                .select('*', { count: 'exact', head: true })
                .gte('created_at', cutoff);
            if (error) return;
            state.errorsBadgeCount = count || 0;
            const badge = document.getElementById('errorsBadge');
            if (!badge) return;
            if (state.errorsBadgeCount > 0) {
                badge.textContent = state.errorsBadgeCount;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        } catch (e) {
            /* тихо */
        }
    }

    async function refreshActionsBadge() {
        try {
            const cutoff = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
            const { count, error } = await supabaseClient
                .from('admin_actions')
                .select('*', { count: 'exact', head: true })
                .gte('created_at', cutoff);
            if (error) return;
            state.actionsBadgeCount = count || 0;
            const badge = document.getElementById('actionsBadge');
            if (!badge) return;
            if (state.actionsBadgeCount > 0) {
                badge.textContent = state.actionsBadgeCount;
                badge.style.display = 'inline-block';
            } else {
                badge.style.display = 'none';
            }
        } catch (e) {
            /* тихо */
        }
    }

    function startBadgesAutoRefresh() {
        if (_badgesIntervalId !== null) {
            clearInterval(_badgesIntervalId);
        }
        _badgesIntervalId = setInterval(async () => {
            await Promise.all([
                refreshOrphansBadge(),
                refreshErrorsBadge(),
                refreshActionsBadge(),
            ]);
        }, 60 * 1000);
    }

    function stopBadgesAutoRefresh() {
        if (_badgesIntervalId !== null) {
            clearInterval(_badgesIntervalId);
            _badgesIntervalId = null;
        }
    }

    // ============================================================
    // СКАЧИВАНИЯ (счётчики)
    // ============================================================
    async function loadDownloadCounts() {
        try {
            const { data } = await supabaseClient
                .from('downloads').select('file_id, count');
            state.downloadCounts = {};
            (data || []).forEach(item => {
                state.downloadCounts[item.file_id] = item.count;
            });
        } catch (e) {
            console.error(e);
        }
    }

    // ============================================================
    // АВТОРИЗАЦИЯ
    // ============================================================
    async function checkAuth() {
        const { data, error } = await supabaseClient.auth.getUser();
        if (error || !data?.user) {
            window.location.href = '../login.html';
            return false;
        }
        state.currentUser = data.user;

        const { data: profile, error: pe } = await supabaseClient
            .from('profiles').select('*').eq('id', state.currentUser.id).single();
        if (pe || profile?.role !== 'admin') {
            alert('Доступ запрещён. Только для администраторов.');
            window.location.href = '../index.html';
            return false;
        }
        state.currentProfile = profile;
        const adminNameEl = document.getElementById('adminName');
        if (adminNameEl) {
            adminNameEl.textContent = profile.username || state.currentUser.email;
        }
        return true;
    }

    // ============================================================
    // НАВИГАЦИЯ
    // ============================================================
    function buildAdminNav() {
        const nav = document.getElementById('adminContentNav');
        if (!nav) return;
        nav.innerHTML = '';
        Object.entries(CFG.SECTIONS).forEach(([key, meta]) => {
            const btn = document.createElement('button');
            btn.className = 'nav-link' + (key === state.currentTab ? ' active' : '');
            btn.dataset.tab = key;
            btn.innerHTML = `<i class="fas ${meta.icon}"></i> ${MF.escapeHtml(meta.label)}`;
            nav.appendChild(btn);
        });
        nav.querySelectorAll('.nav-link').forEach(btn => {
            btn.addEventListener('click', function () {
                document.querySelectorAll('.sidebar .nav-link')
                    .forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                switchToTab(this.dataset.tab);
            });
        });
    }

    function switchToTab(tab) {
        state.currentTab = tab;
        const wrapper = document.getElementById('tableWrapper');
        if (wrapper) wrapper.style.display = 'block';

        if (CFG.SECTIONS[tab]) {
            state.contentFolderFilters[tab] = null;
            state.contentViews[tab] = null;
        }

        if (tab === 'sections')           Admin.renderSectionsAdmin?.();
        else if (tab === 'folders')       Admin.renderFoldersAdmin?.();
        else if (tab === 'downloads')     Admin.loadDownloads?.();
        else if (tab === 'stats')         Admin.loadStats?.();
        else if (tab === 'users')         Admin.loadUsers?.();
        else if (tab === 'visitors')      Admin.loadVisitors?.();
        else if (tab === 'orphans')       Admin.loadOrphans?.();
        else if (tab === 'hidden')        Admin.loadHidden?.();
        else if (tab === 'errors')        Admin.loadErrors?.();
        else if (tab === 'actions')       Admin.loadAdminActions?.();
        else                              Admin.loadSection?.(tab);
    }

    // ============================================================
    // МОДАЛКА ПОЛЬЗОВАТЕЛЯ (закрытие общее)
    // ============================================================
    function closeUserEditModal() {
        document.getElementById('userEditModal').classList.remove('active');
    }

    // ============================================================
    // ОБРАБОТЧИКИ КНОПОК В ШАПКЕ
    // ============================================================
    function bindHeaderButtons() {
        const logoutBtn = document.getElementById('logoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', async () => {
                stopBadgesAutoRefresh();
                await supabaseClient.auth.signOut();
                window.location.href = '../index.html';
            });
        }

        const refreshContentBtn = document.getElementById('contentRefreshBtn');
        if (refreshContentBtn) {
            refreshContentBtn.addEventListener('click', openRefreshModal);
        }

        const cancelBtn = document.getElementById('refreshCancelBtn');
        if (cancelBtn) cancelBtn.addEventListener('click', closeRefreshModal);

        const startBtn = document.getElementById('refreshStartBtn');
        if (startBtn) startBtn.addEventListener('click', startRefresh);

        const refreshModal = document.getElementById('refreshModal');
        if (refreshModal) {
            refreshModal.addEventListener('click', function (e) {
                if (e.target === this) closeRefreshModal();
            });
        }
    }

    // ============================================================
    // ОБРАБОТЧИКИ САЙДБАРА
    // ============================================================
    function bindSidebar() {
        document.querySelectorAll('.sidebar .nav-link[data-tab]').forEach(btn => {
            btn.addEventListener('click', function () {
                document.querySelectorAll('.sidebar .nav-link')
                    .forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                switchToTab(this.dataset.tab);
            });
        });
    }

    // ============================================================
    // ОБРАБОТЧИКИ TOOLBAR
    // ============================================================
    function bindToolbar() {
        const refreshBtn = document.getElementById('refreshBtn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', async () => {
                await loadHiddenItems();

                const tab = state.currentTab;
                if (tab === 'sections')        Admin.renderSectionsAdmin?.();
                else if (tab === 'folders')    Admin.renderFoldersAdmin?.();
                else if (tab === 'downloads')  Admin.loadDownloads?.();
                else if (tab === 'stats')      Admin.loadStats?.();
                else if (tab === 'users')      Admin.loadUsers?.();
                else if (tab === 'visitors')   Admin.loadVisitors?.();
                else if (tab === 'orphans')    Admin.loadOrphans?.();
                else if (tab === 'hidden')     Admin.loadHidden?.();
                else if (tab === 'errors')     Admin.loadErrors?.();
                else if (tab === 'actions')    Admin.loadAdminActions?.();
                else                           Admin.loadSection?.(tab);
            });
        }

        const hideBtn = document.getElementById('hideSelectedBtn');
        if (hideBtn) hideBtn.addEventListener('click', () => Admin.hideSelected?.());

        const unhideBtn = document.getElementById('unhideSelectedBtn');
        if (unhideBtn) unhideBtn.addEventListener('click', () => Admin.unhideSelected?.());

        const deleteBtn = document.getElementById('deleteSelectedBtn');
        if (deleteBtn) deleteBtn.addEventListener('click', () => Admin.deleteSelected?.());
    }

    // ============================================================
    // ПЕРЕРИСОВКА ПРИ RESIZE
    // ============================================================
    let _resizeTimer = null;
    function bindResize() {
        window.addEventListener('resize', () => {
            clearTimeout(_resizeTimer);
            _resizeTimer = setTimeout(() => {
                const tab = state.currentTab;
                if (CFG.SECTIONS[tab]) {
                    Admin.renderContent?.(tab);
                } else if (tab === 'users') {
                    Admin.loadUsers?.();
                } else if (tab === 'visitors') {
                    Admin.loadVisitors?.();
                }
            }, 300);
        });
    }

    // ============================================================
    // ИНИЦИАЛИЗАЦИЯ
    // ============================================================
    async function init() {
        await MF.loadSections();
        buildAdminNav();

        const ok = await checkAuth();
        if (!ok) return;

        await loadDownloadCounts();
        await loadHiddenItems();
        await refreshOrphansBadge();
        await refreshErrorsBadge();
        await refreshActionsBadge();

        bindHeaderButtons();
        bindSidebar();
        bindToolbar();
        bindResize();

        startBadgesAutoRefresh();

        await switchToTab('programs');
    }

    // ============================================================
    // ЭКСПОРТ В window.Admin
    // ============================================================
    Object.assign(Admin, {
        getState: () => state,
        showToast,

        logAdminAction,

        buildProxyUrl,

        checkAuth,
        buildAdminNav,
        switchToTab,
        loadHiddenItems,
        updateHiddenBadge,
        refreshOrphansBadge,
        refreshErrorsBadge,
        refreshActionsBadge,
        startBadgesAutoRefresh,
        stopBadgesAutoRefresh,
        makeHiddenKey,
        isHidden,
        loadDownloadCounts,
        closeUserEditModal,
        openRefreshModal,
        closeRefreshModal,
        startRefresh,
        detectSectionSources,
        init,
    });

    window.Admin = Admin;
})();
