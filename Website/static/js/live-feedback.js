(function () {
    const els = {
        form: document.getElementById('liveFeedbackForm'),
        search: document.getElementById('liveFeedbackItemSearch'),
        itemId: document.getElementById('liveFeedbackItemId'),
        itemName: document.getElementById('liveFeedbackItemName'),
        suggestions: document.getElementById('liveFeedbackSuggestions'),
        price: document.getElementById('liveFeedbackPrice'),
        email: document.getElementById('liveFeedbackEmail'),
        sms: document.getElementById('liveFeedbackSms'),
        smsRecipient: document.getElementById('liveFeedbackSmsRecipient'),
        preview: document.getElementById('liveFeedbackPreview'),
        error: document.getElementById('liveFeedbackError'),
        list: document.getElementById('liveFeedbackWatchList'),
        activeCount: document.getElementById('liveFeedbackActiveCount'),
        triggeredCount: document.getElementById('liveFeedbackTriggeredCount'),
        totalCount: document.getElementById('liveFeedbackTotalCount'),
        lastChecked: document.getElementById('liveFeedbackLastChecked'),
        addBtn: document.getElementById('liveFeedbackAddBtn'),
        addBtnLabel: document.querySelector('#liveFeedbackAddBtn span'),
        cancelEdit: document.getElementById('liveFeedbackCancelEdit'),
    };

    if (!els.form) {
        return;
    }

    const fixedSmsRecipient = '9024483867@msg.telus.com';
    els.smsRecipient.value = fixedSmsRecipient;

    let selectedSide = 'buy';
    let selectedMarketData = null;
    let searchTimer = null;
    let currentWatches = [];
    let editingWatchId = null;
    const marketDataByItemId = new Map();

    function formatNumber(value) {
        if (value === null || value === undefined || value === '') {
            return '--';
        }
        return Number(value).toLocaleString();
    }

    function formatDate(value) {
        if (!value) {
            return '--';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return '--';
        }
        return date.toLocaleString();
    }

    function formatPriceTime(value) {
        if (!value) {
            return 'Last changed --';
        }
        const date = new Date(Number(value) * 1000);
        if (Number.isNaN(date.getTime())) {
            return 'Last changed --';
        }

        const seconds = Math.floor((Date.now() - date.getTime()) / 1000);
        if (seconds < 60) {
            return 'Last changed just now';
        }
        if (seconds < 3600) {
            return `Last changed ${Math.floor(seconds / 60)}m ago`;
        }
        if (seconds < 86400) {
            return `Last changed ${Math.floor(seconds / 3600)}h ago`;
        }
        return `Last changed ${Math.floor(seconds / 86400)}d ago`;
    }

    function getWikiIconUrl(icon) {
        if (!icon) {
            return '';
        }
        return `https://oldschool.runescape.wiki/images/${encodeURIComponent(String(icon).replace(/ /g, '_'))}`;
    }

    function renderPreviewIcon() {
        const iconUrl = getWikiIconUrl(selectedMarketData.icon);
        if (!iconUrl) {
            return `
                <div class="live-feedback-preview-icon live-feedback-preview-icon-fallback" aria-hidden="true">
                    <svg viewBox="0 0 20 20" fill="currentColor">
                        <path d="M11 3a1 1 0 00-1.832-.555l-6 9A1 1 0 004 13h4l-1 4a1 1 0 001.832.555l6-9A1 1 0 0014 7h-4l1-4z" />
                    </svg>
                </div>
            `;
        }

        return `
            <div class="live-feedback-preview-icon">
                <img src="${escapeHtml(iconUrl)}" alt="${escapeHtml(selectedMarketData.name)}">
            </div>
        `;
    }

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function normalizeMarketData(itemId, data = {}, fallbackName = '') {
        data = data || {};
        const normalizedId = Number(itemId ?? data.id ?? data.item_id);
        if (!normalizedId) {
            return null;
        }

        return {
            id: normalizedId,
            name: data.name || data.item_name || fallbackName || `Item ${normalizedId}`,
            icon: data.icon || '',
            high: data.high ?? null,
            low: data.low ?? null,
            highTime: data.highTime ?? null,
            lowTime: data.lowTime ?? null,
        };
    }

    function cacheMarketData(itemId, data, fallbackName = '') {
        const normalized = normalizeMarketData(itemId, data, fallbackName);
        if (!normalized) {
            return null;
        }
        marketDataByItemId.set(String(normalized.id), normalized);
        return normalized;
    }

    function getCachedMarketData(itemId) {
        return marketDataByItemId.get(String(itemId)) || null;
    }

    async function refreshSelectedMarketData(item) {
        const itemId = String(item.id);

        try {
            const response = await fetch(`/api/item/data/?id=${encodeURIComponent(item.id)}`, {
                credentials: 'same-origin',
            });
            if (!response.ok) {
                return;
            }
            const freshData = cacheMarketData(item.id, await response.json(), item.name);
            if (freshData && String(els.itemId.value) === itemId) {
                selectedMarketData = freshData;
                updatePreview();
            }
        } catch (error) {
            if (String(els.itemId.value) === itemId && !selectedMarketData) {
                updatePreview();
            }
        }
    }

    function showError(message) {
        if (!message) {
            els.error.hidden = true;
            els.error.textContent = '';
            return;
        }
        els.error.textContent = message;
        els.error.hidden = false;
    }

    function setSide(side) {
        selectedSide = side === 'sell' ? 'sell' : 'buy';
        document.querySelectorAll('.live-feedback-side-btn').forEach((button) => {
            button.classList.toggle('active', button.dataset.side === selectedSide);
        });
        updatePreview();
    }

    function updateSubmitMode() {
        const isEditing = editingWatchId !== null;
        if (els.addBtnLabel) {
            els.addBtnLabel.textContent = isEditing ? 'Save' : 'Add';
        }
        if (els.addBtn) {
            els.addBtn.classList.toggle('editing', isEditing);
        }
        els.form.classList.toggle('live-feedback-form-editing', isEditing);
        if (els.cancelEdit) {
            els.cancelEdit.hidden = !isEditing;
        }
    }

    function flashEditForm() {
        els.form.classList.remove('live-feedback-form-edit-flash');
        void els.form.offsetWidth;
        els.form.classList.add('live-feedback-form-edit-flash');
        window.setTimeout(() => {
            els.form.classList.remove('live-feedback-form-edit-flash');
        }, 1900);
    }

    function resetForm() {
        editingWatchId = null;
        els.search.value = '';
        els.itemId.value = '';
        els.itemName.value = '';
        els.price.value = '';
        els.email.checked = false;
        els.sms.checked = false;
        els.smsRecipient.value = fixedSmsRecipient;
        selectedMarketData = null;
        setSuggestions([]);
        setSide('buy');
        updatePreview();
        updateSubmitMode();
    }

    function setSuggestions(items) {
        els.suggestions.innerHTML = '';
        if (!items.length) {
            els.suggestions.classList.remove('open');
            return;
        }

        items.forEach((item) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'live-feedback-suggestion';
            button.textContent = item.name;
            button.addEventListener('click', () => selectItem(item));
            els.suggestions.appendChild(button);
        });
        els.suggestions.classList.add('open');
    }

    async function searchItems(query) {
        if (query.trim().length < 2) {
            setSuggestions([]);
            return;
        }

        const response = await fetch(`/api/items/?q=${encodeURIComponent(query.trim())}`, {
            credentials: 'same-origin',
        });
        if (!response.ok) {
            setSuggestions([]);
            return;
        }
        const items = await response.json();
        setSuggestions(Array.isArray(items) ? items : []);
    }

    function selectItem(item) {
        els.search.value = item.name;
        els.itemId.value = item.id;
        els.itemName.value = item.name;
        els.suggestions.classList.remove('open');
        selectedMarketData = getCachedMarketData(item.id);
        showError('');
        updatePreview();
        void refreshSelectedMarketData(item);
    }

    function startEdit(watch) {
        editingWatchId = watch.id;
        els.search.value = watch.item_name;
        els.itemId.value = watch.item_id;
        els.itemName.value = watch.item_name;
        els.price.value = watch.target_price;
        els.email.checked = Boolean(watch.email_notification);
        els.sms.checked = Boolean(watch.sms_notification);
        els.smsRecipient.value = fixedSmsRecipient;
        selectedMarketData = cacheMarketData(watch.item_id, watch.market_data, watch.item_name)
            || getCachedMarketData(watch.item_id);
        setSide(watch.side);
        updateSubmitMode();
        showError('');
        flashEditForm();
        updatePreview();
        void refreshSelectedMarketData({
            id: watch.item_id,
            name: watch.item_name,
        });
        els.search.focus();
    }

    function updatePreview() {
        if (!selectedMarketData || !els.itemId.value) {
            els.preview.hidden = true;
            els.preview.innerHTML = '';
            return;
        }

        const high = selectedMarketData.high;
        const low = selectedMarketData.low;
        const highTime = selectedMarketData.highTime;
        const lowTime = selectedMarketData.lowTime;

        els.preview.innerHTML = `
            <div class="live-feedback-preview-main">
                ${renderPreviewIcon()}
                <div class="live-feedback-preview-item">
                    <span class="live-feedback-preview-eyebrow">Selected item</span>
                    <strong>${escapeHtml(selectedMarketData.name)}</strong>
                </div>
            </div>
            <div class="live-feedback-preview-prices">
                <div class="live-feedback-preview-price-card live-feedback-preview-price-card-buy">
                    <span class="live-feedback-preview-price-label">Instant Buy</span>
                    <strong>${formatNumber(high)} gp</strong>
                    <span class="live-feedback-preview-time">${formatPriceTime(highTime)}</span>
                </div>
                <div class="live-feedback-preview-price-card live-feedback-preview-price-card-sell">
                    <span class="live-feedback-preview-price-label">Instant Sell</span>
                    <strong>${formatNumber(low)} gp</strong>
                    <span class="live-feedback-preview-time">${formatPriceTime(lowTime)}</span>
                </div>
            </div>
        `;
        els.preview.hidden = false;
    }

    async function postJson(url, data = {}) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify(data),
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || payload.success === false) {
            throw new Error(payload.error || 'Request failed');
        }
        return payload;
    }

    async function loadWatches() {
        try {
            const response = await fetch('/api/live-feedback/', {credentials: 'same-origin'});
            const payload = await response.json();
            if (!response.ok || payload.success === false) {
                throw new Error(payload.error || 'Failed to load watches');
            }
            currentWatches = payload.watches || [];
            currentWatches.forEach((watch) => {
                const cachedData = cacheMarketData(watch.item_id, watch.market_data, watch.item_name);
                if (cachedData && String(els.itemId.value) === String(watch.item_id)) {
                    selectedMarketData = cachedData;
                    updatePreview();
                }
            });
            renderWatches(currentWatches);
            els.activeCount.textContent = payload.stats?.active ?? 0;
            els.triggeredCount.textContent = payload.stats?.triggered ?? 0;
            els.totalCount.textContent = payload.stats?.total ?? 0;
            els.lastChecked.textContent = `Last checked: ${formatDate(payload.checked_at)}`;
        } catch (error) {
            showError(error.message);
        }
    }

    function renderWatches(watches) {
        if (!watches.length) {
            els.list.innerHTML = '<div class="live-feedback-empty">No watches yet.</div>';
            return;
        }

        els.list.innerHTML = watches.map(renderWatch).join('');
        els.list.querySelectorAll('[data-action]').forEach((button) => {
            button.addEventListener('click', handleWatchAction);
        });
    }

    function renderWatch(watch) {
        const triggeredClass = watch.is_currently_triggered && !watch.is_dismissed ? ' triggered' : '';
        const pausedClass = watch.is_active ? '' : ' paused';
        const status = watch.is_active ? watch.status : 'paused';
        const statusLabel = getStatusLabel(status);
        const sideLabel = watch.side === 'buy' ? 'Buy' : 'Sell';
        const marketPrice = watch.market_price ? `${formatNumber(watch.market_price)} gp` : '--';
        const gap = watch.difference === null || watch.difference === undefined
            ? '--'
            : `${formatNumber(watch.difference)} gp`;

        return `
            <div class="live-feedback-watch-row${triggeredClass}${pausedClass}">
                <div class="live-feedback-item-cell">
                    <div class="live-feedback-item-name">${escapeHtml(watch.item_name)}</div>
                </div>
                <div>
                    <span class="live-feedback-cell-label">Side</span>
                    <span>${sideLabel}</span>
                </div>
                <div>
                    <span class="live-feedback-cell-label">Your Price</span>
                    <span class="live-feedback-price">${formatNumber(watch.target_price)} gp</span>
                </div>
                <div>
                    <span class="live-feedback-cell-label">${escapeHtml(watch.market_label)}</span>
                    <span class="live-feedback-price">${marketPrice}</span>
                </div>
                <div>
                    <span class="live-feedback-cell-label">Gap</span>
                    <span class="live-feedback-price">${gap}</span>
                </div>
                <div class="live-feedback-status-cell">
                    <span class="live-feedback-status ${status}">${statusLabel}</span>
                </div>
                <div class="live-feedback-actions">
                    <button class="live-feedback-action edit" data-action="edit" data-id="${watch.id}">Edit</button>
                    <button class="live-feedback-action delete" data-action="delete" data-id="${watch.id}">Delete</button>
                </div>
            </div>
        `;
    }

    function getStatusLabel(status) {
        const labels = {
            watching: 'Safe',
            undercut: 'Undercut',
            overcut: 'Overcut',
            no_price: 'No price',
            paused: 'Paused',
        };
        return labels[status] || 'Safe';
    }

    async function handleWatchAction(event) {
        const button = event.currentTarget;
        const id = Number(button.dataset.id);
        const action = button.dataset.action;

        try {
            if (action === 'edit') {
                const watch = currentWatches.find((item) => item.id === id);
                if (!watch) {
                    throw new Error('Watch not found');
                }
                startEdit(watch);
                return;
            }

            if (action === 'delete') {
                await postJson(`/api/live-feedback/${id}/delete/`);
            }
            await loadWatches();
        } catch (error) {
            showError(error.message);
        }
    }

    els.search.addEventListener('input', () => {
        els.itemId.value = '';
        els.itemName.value = '';
        selectedMarketData = null;
        updatePreview();
        window.clearTimeout(searchTimer);
        searchTimer = window.setTimeout(() => searchItems(els.search.value), 180);
    });

    document.addEventListener('click', (event) => {
        if (!els.suggestions.contains(event.target) && event.target !== els.search) {
            els.suggestions.classList.remove('open');
        }
    });

    document.querySelectorAll('.live-feedback-side-btn').forEach((button) => {
        button.addEventListener('click', () => {
            setSide(button.dataset.side);
        });
    });

    els.price.addEventListener('input', updatePreview);

    els.sms.addEventListener('change', () => {
        els.smsRecipient.value = fixedSmsRecipient;
    });

    if (els.cancelEdit) {
        els.cancelEdit.addEventListener('click', (event) => {
            event.preventDefault();
            showError('');
            resetForm();
        });
    }

    els.form.addEventListener('submit', async (event) => {
        event.preventDefault();
        showError('');

        if (!els.itemId.value || !els.itemName.value) {
            showError('Select an item from the search results.');
            return;
        }
        if (!els.price.value || Number(els.price.value) <= 0) {
            showError('Enter a positive price.');
            return;
        }
        const payload = {
            item_id: Number(els.itemId.value),
            item_name: els.itemName.value,
            side: selectedSide,
            target_price: Number(els.price.value),
            email_notification: els.email.checked,
            sms_notification: els.sms.checked,
            sms_recipient: els.sms.checked ? fixedSmsRecipient : '',
        };
        const url = editingWatchId === null
            ? '/api/live-feedback/create/'
            : `/api/live-feedback/${editingWatchId}/update/`;

        try {
            await postJson(url, payload);
            resetForm();
            await loadWatches();
        } catch (error) {
            showError(error.message);
        }
    });

    updateSubmitMode();
    loadWatches();
    window.setInterval(loadWatches, 10000);
}());
