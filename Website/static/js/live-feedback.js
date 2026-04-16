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
        smsWrap: document.getElementById('liveFeedbackSmsWrap'),
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

    let selectedSide = 'buy';
    let selectedMarketData = null;
    let searchTimer = null;
    let currentWatches = [];
    let editingWatchId = null;

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

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
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
        els.smsRecipient.value = '';
        els.smsWrap.classList.remove('visible');
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

    async function selectItem(item) {
        els.search.value = item.name;
        els.itemId.value = item.id;
        els.itemName.value = item.name;
        els.suggestions.classList.remove('open');
        selectedMarketData = null;
        showError('');

        try {
            const response = await fetch(`/api/item/data/?id=${encodeURIComponent(item.id)}`, {
                credentials: 'same-origin',
            });
            selectedMarketData = response.ok ? await response.json() : null;
        } catch (error) {
            selectedMarketData = null;
        }
        updatePreview();
    }

    async function startEdit(watch) {
        editingWatchId = watch.id;
        els.search.value = watch.item_name;
        els.itemId.value = watch.item_id;
        els.itemName.value = watch.item_name;
        els.price.value = watch.target_price;
        els.email.checked = Boolean(watch.email_notification);
        els.sms.checked = Boolean(watch.sms_notification);
        els.smsRecipient.value = watch.sms_recipient || '';
        els.smsWrap.classList.toggle('visible', els.sms.checked);
        selectedMarketData = null;
        setSide(watch.side);
        updateSubmitMode();
        showError('');
        flashEditForm();

        await selectItem({
            id: watch.item_id,
            name: watch.item_name,
        });
        els.search.focus();
    }

    function updatePreview() {
        const target = Number(els.price.value || 0);
        if (!selectedMarketData || !els.itemId.value) {
            els.preview.hidden = true;
            els.preview.innerHTML = '';
            return;
        }

        const high = selectedMarketData.high;
        const low = selectedMarketData.low;
        const marketPrice = selectedSide === 'buy' ? high : low;
        const marketLabel = selectedSide === 'buy' ? 'Highest buy' : 'Lowest sell';
        let status = 'Waiting for price';

        if (target > 0 && marketPrice) {
            if (selectedSide === 'buy') {
                status = marketPrice > target
                    ? `Overcut by ${formatNumber(marketPrice - target)} gp`
                    : `Safe by ${formatNumber(target - marketPrice)} gp`;
            } else {
                status = marketPrice < target
                    ? `Undercut by ${formatNumber(target - marketPrice)} gp`
                    : `Safe by ${formatNumber(marketPrice - target)} gp`;
            }
        }

        els.preview.innerHTML = `
            <strong>${escapeHtml(selectedMarketData.name)}</strong>
            <span>${marketLabel}: ${formatNumber(marketPrice)} gp</span>
            <span>High: ${formatNumber(high)} gp</span>
            <span>Low: ${formatNumber(low)} gp</span>
            <span>${escapeHtml(status)}</span>
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
                await startEdit(watch);
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
        els.smsWrap.classList.toggle('visible', els.sms.checked);
        if (!els.sms.checked) {
            els.smsRecipient.value = '';
        }
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
        if (els.sms.checked && !els.smsRecipient.value.trim()) {
            showError('Enter an SMS gateway address.');
            return;
        }

        const payload = {
            item_id: Number(els.itemId.value),
            item_name: els.itemName.value,
            side: selectedSide,
            target_price: Number(els.price.value),
            email_notification: els.email.checked,
            sms_notification: els.sms.checked,
            sms_recipient: els.smsRecipient.value.trim(),
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
