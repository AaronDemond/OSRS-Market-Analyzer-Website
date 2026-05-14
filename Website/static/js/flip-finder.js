(function () {
    /**
     * Flip Finder client controller.
     *
     * What: Wires the Django-rendered UI to the local Flip Finder JSON APIs.
     * Why: The original page was a client-only mockup; the real page should now
     *      render database-backed candidates, charts, filters, and sort states.
     * How: Fetch result rows whenever filter state changes, then fetch selected
     *      item history separately so row selection stays quick and focused.
     */
    const app = document.getElementById('flipFinderApp');

    if (!app) {
        return;
    }

    const endpoints = {
        results: '/api/flip-finder/results/',
        history: '/api/flip-finder/history/',
    };

    const supportedTimeframes = new Set(['24h', '7d', '30d', '90d', '1y', 'all', 'custom']);

    const defaultState = {
        timeframe: '24h',
        chartTimeframe: '24h',
        page: 1,
        percent: 5,
        signal: 'low',
        search: '',
        sort: 'closest',
        sortDirection: 'asc',
        minVolume: '',
        minPrice: '',
        customDate: '',
        selectedItemId: null,
    };

    const state = {...defaultState};

    const elements = {
        updatedAt: document.getElementById('ffUpdatedAt'),
        resetButton: document.getElementById('ffResetButton'),
        resultsPanel: document.getElementById('ffResultsPanel'),
        timeframeButtons: Array.from(document.querySelectorAll('#ffTimeframeGroup button')),
        chartTimeframeButtons: Array.from(document.querySelectorAll('#ffChartTimeframeGroup button')),
        signalButtons: Array.from(document.querySelectorAll('#ffSignalGroup button')),
        sortHeaders: Array.from(document.querySelectorAll('.ff-sort-header')),
        percentRange: document.getElementById('ffPercentRange'),
        percentInput: document.getElementById('ffPercentInput'),
        minVolumeInput: document.getElementById('ffMinVolumeInput'),
        minPriceInput: document.getElementById('ffMinPriceInput'),
        searchInput: document.getElementById('ffSearchInput'),
        sortSelect: document.getElementById('ffSortSelect'),
        previousPageButton: document.getElementById('ffPreviousPageButton'),
        nextPageButton: document.getElementById('ffNextPageButton'),
        resultsMeta: document.getElementById('ffResultsMeta'),
        resultsBody: document.getElementById('ffResultsBody'),
        resultsTable: document.getElementById('ffResultsTable'),
        resultsScroll: document.getElementById('ffResultsScroll'),
        tableScrollbar: document.getElementById('ffTableScrollbar'),
        tableScrollbarTrack: document.getElementById('ffTableScrollbarTrack'),
        emptyState: document.getElementById('ffEmptyState'),
        chartPanel: document.getElementById('ffChartPanel'),
        selectedMeta: document.getElementById('ffSelectedMeta'),
        selectedIconSlot: document.getElementById('ffSelectedIconSlot'),
        selectedSignal: document.getElementById('ffSelectedSignal'),
        selectedPrice: document.getElementById('ffSelectedPrice'),
        selectedLowDistance: document.getElementById('ffSelectedLowDistance'),
        selectedHighDistance: document.getElementById('ffSelectedHighDistance'),
        selectedRange: document.getElementById('ffSelectedRange'),
        priceChartCanvas: document.getElementById('ffPriceChart'),
        priceChartEmpty: document.getElementById('ffPriceChartEmpty'),
        customDateModal: document.getElementById('ffCustomDateModal'),
        customDateForm: document.getElementById('ffCustomDateForm'),
        customDateInput: document.getElementById('ffCustomDateInput'),
        customDateError: document.getElementById('ffCustomDateError'),
        customDateCancelButton: document.getElementById('ffCustomDateCancelButton'),
        customDateCloseButton: document.getElementById('ffCustomDateCloseButton'),
    };

    let filteredResults = [];
    let selectedResult = null;
    let selectedHistory = null;
    let resultError = null;
    let historyError = null;
    let hasPreviousPage = false;
    let hasNextPage = false;
    let isLoadingResults = false;
    let isLoadingHistory = false;
    let priceChart = null;
    let isSyncingHorizontalScroll = false;
    let resultsRequestId = 0;
    let historyRequestId = 0;
    let refreshTimer = null;
    let customDateTarget = 'results';
    let customDateReturnFocus = null;
    let resultsPanelHeightFrame = 0;

    const defaultSortDirections = {
        closest: 'asc',
        name: 'asc',
        low: 'asc',
        high: 'asc',
    };

    function escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    }

    function clampNumber(value, minValue, maxValue) {
        return Math.min(maxValue, Math.max(minValue, Number(value) || minValue));
    }

    function hasValue(value) {
        return value !== null && value !== undefined && value !== '';
    }

    function formatInteger(value) {
        if (!hasValue(value)) {
            return '--';
        }
        return Number(value).toLocaleString();
    }

    function formatGp(value) {
        if (!hasValue(value)) {
            return '--';
        }
        return `${formatInteger(value)} gp`;
    }

    function formatCompactNumber(value) {
        if (!hasValue(value)) {
            return '--';
        }

        const amount = Number(value) || 0;
        if (Math.abs(amount) >= 1000000000) {
            return `${(amount / 1000000000).toFixed(2)}b`;
        }
        if (Math.abs(amount) >= 1000000) {
            return `${(amount / 1000000).toFixed(1)}m`;
        }
        if (Math.abs(amount) >= 1000) {
            return `${(amount / 1000).toFixed(1)}k`;
        }
        return formatInteger(amount);
    }

    function formatCompactGp(value) {
        const compactValue = formatCompactNumber(value);
        return compactValue === '--' ? compactValue : `${compactValue} gp`;
    }

    function formatPercent(value) {
        if (!hasValue(value)) {
            return '--';
        }
        return `${Number(value).toFixed(1)}%`;
    }

    function formatIsoDateOnly(value) {
        if (!value) {
            return '--';
        }
        return String(value).split('T')[0];
    }

    function formatScanTime(meta) {
        if (!meta || !meta.rangeEndIso) {
            return 'No local data for this range';
        }
        if (meta.timeframe === 'custom' && meta.rangeStartIso) {
            return `Custom scan · ${formatIsoDateOnly(meta.rangeStartIso)} - ${new Date(meta.rangeEndIso).toLocaleString()}`;
        }
        return `Local scan · ${new Date(meta.rangeEndIso).toLocaleString()}`;
    }

    function getWikiIconUrl(icon) {
        if (!icon) {
            return null;
        }
        return `https://oldschool.runescape.wiki/images/${encodeURIComponent(String(icon).replace(/ /g, '_'))}`;
    }

    function getInitials(name) {
        return String(name)
            .split(/\s+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0].toUpperCase())
            .join('');
    }

    function buildQueryString(params) {
        const query = new URLSearchParams();
        Object.entries(params).forEach(([key, value]) => {
            if (hasValue(value)) {
                query.set(key, value);
            }
        });
        return query.toString();
    }

    async function fetchJson(url, params) {
        /**
         * Fetch JSON with consistent error extraction.
         *
         * The backend returns `{error: "..."}` for validation failures. Reading
         * the body before throwing keeps the UI message useful without exposing
         * raw response text or stack traces.
         */
        const response = await fetch(`${url}?${buildQueryString(params)}`, {
            headers: {'Accept': 'application/json'},
        });
        const payload = await response.json().catch(() => ({}));

        if (!response.ok) {
            throw new Error(payload.error || 'Flip Finder request failed.');
        }

        return payload;
    }

    function fetchResults() {
        return fetchJson(endpoints.results, {
            timeframe: state.timeframe,
            percent: state.percent,
            signal: state.signal,
            search: state.search,
            sort: state.sort,
            sortDirection: state.sortDirection,
            page: state.page,
            minVolume: state.minVolume,
            minPrice: state.minPrice,
            customDate: state.timeframe === 'custom' ? state.customDate : '',
        });
    }

    function fetchSelectedHistory() {
        if (!selectedResult) {
            return Promise.resolve(null);
        }

        return fetchJson(endpoints.history, {
            timeframe: state.chartTimeframe,
            itemId: selectedResult.id,
            customDate: state.chartTimeframe === 'custom' ? state.customDate : '',
        });
    }

    function setSort(sortKey, shouldToggleDirection = false) {
        if (shouldToggleDirection && state.sort === sortKey) {
            state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            state.sort = sortKey;
            state.sortDirection = defaultSortDirections[sortKey] || 'asc';
        }
        state.page = 1;
        refreshResults();
    }

    function updateSortHeaders() {
        elements.sortHeaders.forEach((header) => {
            const isSorted = header.dataset.sort === state.sort;
            header.classList.toggle('sorted', isSorted);
            header.classList.toggle('asc', isSorted && state.sortDirection === 'asc');
            header.classList.toggle('desc', isSorted && state.sortDirection === 'desc');
            header.setAttribute('aria-sort', isSorted ? (state.sortDirection === 'asc' ? 'ascending' : 'descending') : 'none');
        });
    }

    function syncHorizontalScrollbarVisibility() {
        if (!elements.resultsScroll || !elements.tableScrollbar || !elements.tableScrollbarTrack) {
            return;
        }

        syncResultsViewportWidth();
        const hasOverflow = !elements.resultsTable.hidden && elements.resultsScroll.scrollWidth > elements.resultsScroll.clientWidth + 1;
        elements.tableScrollbar.hidden = !hasOverflow;
        elements.tableScrollbarTrack.style.width = `${elements.resultsScroll.scrollWidth}px`;

        if (hasOverflow) {
            elements.tableScrollbar.scrollLeft = elements.resultsScroll.scrollLeft;
        }
    }

    function syncResultsViewportWidth() {
        if (!elements.resultsScroll || !elements.resultsBody) {
            return;
        }
        elements.resultsBody.style.setProperty('--ff-results-viewport-width', `${elements.resultsScroll.clientWidth}px`);
    }

    function syncHorizontalScroll(source, target) {
        if (!source || !target || isSyncingHorizontalScroll) {
            return;
        }
        isSyncingHorizontalScroll = true;
        target.scrollLeft = source.scrollLeft;
        isSyncingHorizontalScroll = false;
    }

    function syncResultsPanelHeight() {
        /**
         * Keep the results card capped to the chart card's natural desktop height.
         *
         * The chart card should define the row size. The results list then scrolls
         * inside its own card instead of forcing the chart card to stretch taller.
         */
        if (!elements.resultsPanel || !elements.chartPanel) {
            return;
        }

        if (window.innerWidth <= 1100) {
            elements.resultsPanel.style.height = '';
            syncHorizontalScrollbarVisibility();
            return;
        }

        const chartPanelHeight = Math.ceil(elements.chartPanel.getBoundingClientRect().height);
        elements.resultsPanel.style.height = chartPanelHeight > 0 ? `${chartPanelHeight}px` : '';
        syncHorizontalScrollbarVisibility();
    }

    function queueResultsPanelHeightSync() {
        if (resultsPanelHeightFrame) {
            window.cancelAnimationFrame(resultsPanelHeightFrame);
        }

        resultsPanelHeightFrame = window.requestAnimationFrame(() => {
            resultsPanelHeightFrame = 0;
            syncResultsPanelHeight();
        });
    }

    function handleViewportResize() {
        syncHorizontalScrollbarVisibility();
        queueResultsPanelHeightSync();
    }

    function bindHorizontalScrollbar() {
        if (!elements.resultsScroll || !elements.tableScrollbar) {
            return;
        }

        elements.resultsScroll.addEventListener('scroll', () => {
            syncHorizontalScroll(elements.resultsScroll, elements.tableScrollbar);
        });
        elements.tableScrollbar.addEventListener('scroll', () => {
            syncHorizontalScroll(elements.tableScrollbar, elements.resultsScroll);
        });
        window.addEventListener('resize', handleViewportResize);
    }

    function bindResultsPanelHeightSync() {
        if (!elements.resultsPanel || !elements.chartPanel) {
            return;
        }

        if ('ResizeObserver' in window) {
            const chartPanelObserver = new ResizeObserver(() => {
                queueResultsPanelHeightSync();
            });
            chartPanelObserver.observe(elements.chartPanel);
        }

        queueResultsPanelHeightSync();
    }

    function getSignalLabel(signal) {
        if (signal === 'low') {
            return 'Near Low';
        }
        if (signal === 'high') {
            return 'Near High';
        }
        if (signal === 'both') {
            return 'Near Both';
        }
        return '--';
    }

    function getSignalClass(signal) {
        return signal === 'both' ? 'both' : signal;
    }

    function getMemberText(result) {
        if (result.members === true) {
            return 'Members';
        }
        if (result.members === false) {
            return 'Free';
        }
        return null;
    }

    function renderItemIcon(result) {
        const fallback = escapeHtml(getInitials(result.name) || '?');
        const iconUrl = getWikiIconUrl(result.icon);
        if (!iconUrl) {
            return `<span class="ff-item-icon fallback">${fallback}</span>`;
        }
        return `<span class="ff-item-icon" data-fallback="${fallback}"><img src="${escapeHtml(iconUrl)}" alt="${escapeHtml(result.name)}"></span>`;
    }

    function wireItemIconFallbacks(scope) {
        if (!scope) {
            return;
        }

        scope.querySelectorAll('.ff-item-icon img').forEach((image) => {
            const showFallback = () => {
                const wrapper = image.closest('.ff-item-icon');
                if (!wrapper) {
                    return;
                }
                wrapper.classList.add('fallback');
                wrapper.textContent = wrapper.dataset.fallback || '?';
            };

            image.addEventListener('error', showFallback);
            if (image.complete && image.naturalWidth === 0) {
                showFallback();
            }
        });
    }

    function renderResult(result) {
        const selectedClass = selectedResult && selectedResult.id === result.id ? ' selected' : '';
        const signalClass = getSignalClass(result.signal);
        const itemDetails = [
            hasValue(result.buyLimit) ? `Limit ${formatInteger(result.buyLimit)}` : null,
            getMemberText(result),
        ].filter(Boolean).join(' · ') || `Item ${formatInteger(result.id)}`;

        return `
            <button type="button" class="ff-result-row${selectedClass}" data-item-id="${result.id}" role="row" aria-label="${escapeHtml(result.name)}">
                <span class="ff-item-cell" role="cell">
                    ${renderItemIcon(result)}
                    <span>
                        <span class="ff-item-name">${escapeHtml(result.name)}</span>
                        <span class="ff-item-subtext">${escapeHtml(itemDetails)}</span>
                    </span>
                </span>
                <span class="ff-signal-cell" role="cell">
                    <span class="ff-cell-label">Signal</span>
                    <span class="ff-signal-badge ${signalClass}">${getSignalLabel(result.signal)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">From Low</span>
                    <span class="ff-distance">${formatPercent(result.distanceFromLow)}</span>
                    <span class="ff-muted-value">${formatCompactGp(result.periodLow)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">From High</span>
                    <span class="ff-distance">${formatPercent(result.distanceFromHigh)}</span>
                    <span class="ff-muted-value">${formatCompactGp(result.periodHigh)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">Current</span>
                    <span class="ff-price">${formatGp(result.currentPrice)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">Volume GP</span>
                    <span class="ff-volume">${formatCompactGp(result.volume)}</span>
                </span>
            </button>
        `;
    }

    function updateSegmentedButtons(buttons, activeValue, dataName) {
        buttons.forEach((button) => {
            const isActive = button.dataset[dataName] === activeValue;
            button.classList.toggle('active', isActive);
            button.setAttribute('aria-pressed', String(isActive));
        });
    }

    function renderResultsMeta(payload) {
        if (!payload) {
            const visibleCount = filteredResults.length;
            elements.resultsMeta.textContent = `${formatInteger(visibleCount)} item${visibleCount === 1 ? '' : 's'}`;
            return;
        }

        const totalMatches = payload.totalMatches || 0;
        if (!totalMatches) {
            elements.resultsMeta.textContent = '0 items';
            return;
        }

        const visibleCount = filteredResults.length;
        const firstVisible = ((payload.page - 1) * payload.pageSize) + 1;
        const lastVisible = firstVisible + visibleCount - 1;
        elements.resultsMeta.textContent = `${formatInteger(firstVisible)}-${formatInteger(lastVisible)} of ${formatInteger(totalMatches)} items`;
    }

    function renderLoadingIndicator() {
        return `
            <div class="ff-results-loading" role="status" aria-label="Loading results">
                <span class="ff-loading-spinner" aria-hidden="true"></span>
            </div>
        `;
    }

    function updatePageButtons() {
        if (elements.previousPageButton) {
            elements.previousPageButton.disabled = isLoadingResults || !hasPreviousPage;
        }
        if (!elements.nextPageButton) {
            return;
        }
        elements.nextPageButton.disabled = isLoadingResults || !hasNextPage;
    }

    function renderResults(results) {
        if (isLoadingResults) {
            elements.emptyState.hidden = true;
            elements.resultsTable.hidden = false;
            syncResultsViewportWidth();
            elements.resultsBody.innerHTML = renderLoadingIndicator();
            updatePageButtons();
            syncHorizontalScrollbarVisibility();
            window.requestAnimationFrame(syncHorizontalScrollbarVisibility);
            return;
        }

        if (resultError) {
            elements.emptyState.textContent = resultError.message;
            elements.emptyState.hidden = false;
            elements.resultsTable.hidden = true;
            elements.resultsBody.innerHTML = '';
            updatePageButtons();
            syncHorizontalScrollbarVisibility();
            return;
        }

        elements.emptyState.textContent = 'No matching items.';
        elements.emptyState.hidden = results.length > 0;
        elements.resultsTable.hidden = results.length === 0;
        elements.resultsBody.innerHTML = results.map(renderResult).join('');
        updatePageButtons();

        elements.resultsBody.querySelectorAll('.ff-result-row').forEach((button) => {
            button.addEventListener('click', () => {
                state.selectedItemId = Number(button.dataset.itemId);
                selectedResult = filteredResults.find((result) => result.id === state.selectedItemId) || null;
                selectedHistory = null;
                renderResults(filteredResults);
                refreshSelectedHistory();
            });
        });

        wireItemIconFallbacks(elements.resultsBody);

        syncHorizontalScrollbarVisibility();
        window.requestAnimationFrame(syncHorizontalScrollbarVisibility);
    }

    function syncSelectedResult(results) {
        if (!results.length) {
            selectedResult = null;
            selectedHistory = null;
            state.selectedItemId = null;
            return;
        }

        selectedResult = results.find((result) => result.id === state.selectedItemId) || null;

        if (!selectedResult) {
            selectedHistory = null;
            state.selectedItemId = null;
            return;
        }

        state.selectedItemId = selectedResult.id;
    }

    function resetSelectedPanel(message = 'Select an item to view its chart.') {
        elements.selectedMeta.textContent = '--';
        if (elements.selectedIconSlot) {
            elements.selectedIconSlot.innerHTML = '<span class="ff-item-icon ff-selected-item-icon fallback">?</span>';
        }
        elements.selectedSignal.textContent = '--';
        elements.selectedSignal.className = 'ff-signal-badge';
        elements.selectedPrice.textContent = '--';
        elements.selectedLowDistance.textContent = '--';
        elements.selectedHighDistance.textContent = '--';
        elements.selectedRange.textContent = '--';
        elements.priceChartEmpty.textContent = message;
        elements.priceChartEmpty.hidden = false;

        if (priceChart) {
            priceChart.destroy();
            priceChart = null;
        }
    }

    function renderSelectedPanel() {
        if (!selectedResult) {
            resetSelectedPanel();
            return;
        }

        const signalClass = getSignalClass(selectedResult.signal);
        const historyRangeLow = selectedHistory && hasValue(selectedHistory.periodLow) ? selectedHistory.periodLow : selectedResult.periodLow;
        const historyRangeHigh = selectedHistory && hasValue(selectedHistory.periodHigh) ? selectedHistory.periodHigh : selectedResult.periodHigh;

        elements.selectedMeta.textContent = selectedResult.name;
        if (elements.selectedIconSlot) {
            elements.selectedIconSlot.innerHTML = renderItemIcon(selectedResult).replace('ff-item-icon', 'ff-item-icon ff-selected-item-icon');
            wireItemIconFallbacks(elements.selectedIconSlot);
        }
        elements.selectedSignal.textContent = getSignalLabel(selectedResult.signal);
        elements.selectedSignal.className = `ff-signal-badge ${signalClass}`;
        elements.selectedPrice.textContent = formatGp(selectedResult.currentPrice);
        elements.selectedLowDistance.textContent = formatPercent(selectedResult.distanceFromLow);
        elements.selectedHighDistance.textContent = formatPercent(selectedResult.distanceFromHigh);
        elements.selectedRange.textContent = `${formatCompactGp(historyRangeLow)} - ${formatCompactGp(historyRangeHigh)}`;

        if (isLoadingHistory) {
            elements.priceChartEmpty.textContent = 'Loading item history...';
            elements.priceChartEmpty.hidden = false;
        } else if (historyError) {
            elements.priceChartEmpty.textContent = historyError.message;
            elements.priceChartEmpty.hidden = false;
        } else if (!selectedHistory || !selectedHistory.points.length) {
            elements.priceChartEmpty.textContent = 'No history for this item and timeframe.';
            elements.priceChartEmpty.hidden = false;
        } else {
            elements.priceChartEmpty.hidden = true;
        }
    }

    function renderPriceChart() {
        if (!window.Chart || !elements.priceChartCanvas) {
            return;
        }

        if (priceChart) {
            priceChart.destroy();
            priceChart = null;
        }

        if (!selectedResult || !selectedHistory || !selectedHistory.points.length || isLoadingHistory || historyError) {
            return;
        }

        const labels = selectedHistory.points.map((point) => point.label || point.isoTimestamp || '');
        const prices = selectedHistory.points.map((point) => point.price);
        const periodLow = selectedHistory.periodLow;
        const periodHigh = selectedHistory.periodHigh;
        const lowLine = selectedHistory.points.map(() => periodLow);
        const highLine = selectedHistory.points.map(() => periodHigh);
        const context = elements.priceChartCanvas.getContext('2d');
        const gradient = context.createLinearGradient(0, 0, 0, 260);
        gradient.addColorStop(0, 'rgba(37, 99, 235, 0.22)');
        gradient.addColorStop(1, 'rgba(37, 99, 235, 0.02)');

        priceChart = new Chart(context, {
            type: 'line',
            data: {
                labels,
                datasets: [
                    {
                        label: 'Price',
                        data: prices,
                        borderColor: '#2563EB',
                        backgroundColor: gradient,
                        borderWidth: 2.5,
                        pointRadius: 0,
                        pointHoverRadius: 4,
                        tension: 0.22,
                        fill: true,
                    },
                    {
                        label: 'Period low',
                        data: lowLine,
                        borderColor: '#0F766E',
                        borderDash: [6, 6],
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                    {
                        label: 'Period high',
                        data: highLine,
                        borderColor: '#B45309',
                        borderDash: [6, 6],
                        borderWidth: 1.5,
                        pointRadius: 0,
                        fill: false,
                    },
                ],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {mode: 'index', intersect: false},
                plugins: {
                    legend: {display: true, labels: {boxWidth: 10, usePointStyle: true}},
                    tooltip: {
                        callbacks: {
                            label: (contextItem) => `${contextItem.dataset.label}: ${formatGp(contextItem.parsed.y)}`,
                        },
                    },
                },
                scales: {
                    x: {grid: {display: false}, ticks: {maxRotation: 0, autoSkip: true, maxTicksLimit: 6}},
                    y: {ticks: {callback: (value) => formatCompactGp(value)}},
                },
            },
        });
    }

    function updateControlStates() {
        updateSegmentedButtons(elements.timeframeButtons, state.timeframe, 'timeframe');
        updateSegmentedButtons(elements.chartTimeframeButtons, state.chartTimeframe, 'timeframe');
        updateSegmentedButtons(elements.signalButtons, state.signal, 'signal');
        updateSortHeaders();
        elements.percentRange.value = String(state.percent);
        elements.percentInput.value = String(state.percent);
        elements.minVolumeInput.value = state.minVolume;
        elements.minPriceInput.value = state.minPrice;
        elements.searchInput.value = state.search;
        elements.sortSelect.value = state.sort;
        updatePageButtons();
    }

    async function refreshResults() {
        /**
         * Refresh the result table from the backend.
         *
         * Each call gets a monotonically increasing request id. Late responses
         * are ignored so fast typing or slider movement cannot overwrite newer
         * results with stale payloads.
         */
        const requestId = resultsRequestId + 1;
        resultsRequestId = requestId;
        isLoadingResults = true;
        resultError = null;
        updateControlStates();
        renderResults(filteredResults);

        try {
            const payload = await fetchResults();
            if (requestId !== resultsRequestId) {
                return;
            }

            isLoadingResults = false;
            filteredResults = payload.results || [];
            state.page = payload.page || state.page;
            hasPreviousPage = Boolean(payload.hasPreviousPage);
            hasNextPage = Boolean(payload.hasNextPage);
            syncSelectedResult(filteredResults);
            elements.updatedAt.textContent = formatScanTime(payload.meta);
            renderResultsMeta(payload);
            renderResults(filteredResults);
            refreshSelectedHistory();
        } catch (error) {
            if (requestId !== resultsRequestId) {
                return;
            }

            isLoadingResults = false;
            resultError = error;
            filteredResults = [];
            selectedResult = null;
            selectedHistory = null;
            hasPreviousPage = false;
            hasNextPage = false;
            elements.updatedAt.textContent = 'Flip Finder unavailable';
            renderResultsMeta(null);
            renderResults(filteredResults);
            renderSelectedPanel();
            renderPriceChart();
        }
    }

    async function refreshSelectedHistory() {
        const requestId = historyRequestId + 1;
        historyRequestId = requestId;

        if (!selectedResult) {
            isLoadingHistory = false;
            historyError = null;
            selectedHistory = null;
            renderSelectedPanel();
            renderPriceChart();
            return;
        }

        isLoadingHistory = true;
        historyError = null;
        selectedHistory = null;
        renderSelectedPanel();
        renderPriceChart();

        try {
            const payload = await fetchSelectedHistory();
            if (requestId !== historyRequestId) {
                return;
            }

            isLoadingHistory = false;
            selectedHistory = payload || null;
            renderSelectedPanel();
            renderPriceChart();
        } catch (error) {
            if (requestId !== historyRequestId) {
                return;
            }

            isLoadingHistory = false;
            historyError = error;
            selectedHistory = null;
            renderSelectedPanel();
            renderPriceChart();
        }
    }

    function queueResultsRefresh(delay = 0) {
        window.clearTimeout(refreshTimer);
        refreshTimer = window.setTimeout(refreshResults, delay);
    }

    function queueFirstPageRefresh(delay = 0) {
        state.page = 1;
        queueResultsRefresh(delay);
    }

    function setPercent(value) {
        state.percent = Math.round(clampNumber(value, 0.1, 25) * 10) / 10;
        updateControlStates();
        queueFirstPageRefresh(180);
    }

    function getTodayInputValue() {
        const now = new Date();
        const localNow = new Date(now.getTime() - (now.getTimezoneOffset() * 60000));
        return localNow.toISOString().slice(0, 10);
    }

    function setCustomDateError(message) {
        if (!elements.customDateError) {
            return;
        }
        elements.customDateError.textContent = message;
        elements.customDateError.hidden = !message;
    }

    function openCustomDateModal(target, returnFocusElement) {
        if (!elements.customDateModal || !elements.customDateInput) {
            return;
        }
        customDateTarget = target;
        customDateReturnFocus = returnFocusElement || document.activeElement;
        elements.customDateInput.max = getTodayInputValue();
        elements.customDateInput.value = state.customDate || elements.customDateInput.max;
        setCustomDateError('');
        elements.customDateModal.hidden = false;
        elements.customDateModal.setAttribute('aria-hidden', 'false');
        window.requestAnimationFrame(() => elements.customDateInput.focus());
    }

    function closeCustomDateModal() {
        if (!elements.customDateModal) {
            return;
        }
        elements.customDateModal.hidden = true;
        elements.customDateModal.setAttribute('aria-hidden', 'true');
        if (customDateReturnFocus && typeof customDateReturnFocus.focus === 'function') {
            customDateReturnFocus.focus();
        }
        customDateReturnFocus = null;
    }

    function applyCustomDateSelection() {
        const selectedDate = elements.customDateInput ? elements.customDateInput.value : '';
        if (!selectedDate) {
            setCustomDateError('Select a date.');
            return;
        }

        state.customDate = selectedDate;
        if (customDateTarget === 'chart') {
            state.chartTimeframe = 'custom';
            closeCustomDateModal();
            updateControlStates();
            refreshSelectedHistory();
            return;
        }

        state.timeframe = 'custom';
        state.chartTimeframe = 'custom';
        closeCustomDateModal();
        queueFirstPageRefresh();
    }

    elements.timeframeButtons.forEach((button) => {
        button.addEventListener('click', () => {
            if (!supportedTimeframes.has(button.dataset.timeframe)) {
                return;
            }
            if (button.dataset.timeframe === 'custom') {
                openCustomDateModal('results', button);
                return;
            }
            state.timeframe = button.dataset.timeframe;
            state.chartTimeframe = state.timeframe;
            queueFirstPageRefresh();
        });
    });

    elements.chartTimeframeButtons.forEach((button) => {
        button.addEventListener('click', () => {
            if (!supportedTimeframes.has(button.dataset.timeframe)) {
                return;
            }
            if (button.dataset.timeframe === 'custom') {
                openCustomDateModal('chart', button);
                return;
            }
            state.chartTimeframe = button.dataset.timeframe;
            updateControlStates();
            refreshSelectedHistory();
        });
    });

    elements.signalButtons.forEach((button) => {
        button.addEventListener('click', () => {
            state.signal = button.dataset.signal;
            queueFirstPageRefresh();
        });
    });

    elements.sortHeaders.forEach((header) => {
        header.addEventListener('click', () => {
            setSort(header.dataset.sort, true);
        });
    });

    elements.percentRange.addEventListener('input', () => setPercent(elements.percentRange.value));
    elements.percentInput.addEventListener('input', () => setPercent(elements.percentInput.value));
    elements.minVolumeInput.addEventListener('input', () => {
        state.minVolume = elements.minVolumeInput.value;
        queueFirstPageRefresh(250);
    });
    elements.minPriceInput.addEventListener('input', () => {
        state.minPrice = elements.minPriceInput.value;
        queueFirstPageRefresh(250);
    });
    elements.searchInput.addEventListener('input', () => {
        state.search = elements.searchInput.value;
        queueFirstPageRefresh(250);
    });
    elements.sortSelect.addEventListener('change', () => {
        setSort(elements.sortSelect.value, false);
    });
    elements.resetButton.addEventListener('click', () => {
        Object.assign(state, defaultState);
        selectedHistory = null;
        hasPreviousPage = false;
        hasNextPage = false;
        queueFirstPageRefresh();
    });
    elements.previousPageButton.addEventListener('click', () => {
        if (!hasPreviousPage || isLoadingResults) {
            return;
        }
        state.page = Math.max(1, state.page - 1);
        if (elements.resultsScroll) {
            elements.resultsScroll.scrollTop = 0;
        }
        refreshResults();
    });
    elements.nextPageButton.addEventListener('click', () => {
        if (!hasNextPage || isLoadingResults) {
            return;
        }
        state.page += 1;
        if (elements.resultsScroll) {
            elements.resultsScroll.scrollTop = 0;
        }
        refreshResults();
    });

    if (elements.customDateForm) {
        elements.customDateForm.addEventListener('submit', (event) => {
            event.preventDefault();
            applyCustomDateSelection();
        });
    }
    if (elements.customDateCancelButton) {
        elements.customDateCancelButton.addEventListener('click', closeCustomDateModal);
    }
    if (elements.customDateCloseButton) {
        elements.customDateCloseButton.addEventListener('click', closeCustomDateModal);
    }
    if (elements.customDateModal) {
        elements.customDateModal.addEventListener('click', (event) => {
            if (event.target === elements.customDateModal) {
                closeCustomDateModal();
            }
        });
    }
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && elements.customDateModal && !elements.customDateModal.hidden) {
            closeCustomDateModal();
        }
    });

    elements.updatedAt.textContent = 'Loading local market data...';
    bindHorizontalScrollbar();
    bindResultsPanelHeightSync();
    refreshResults();
}());
