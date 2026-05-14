(function () {
    const app = document.getElementById('flipFinderApp');

    if (!app) {
        return;
    }

    const timeframeConfig = {
        '1h': {label: '1h', points: 13, stepMinutes: 5},
        '6h': {label: '6h', points: 13, stepMinutes: 30},
        '24h': {label: '24h', points: 13, stepHours: 2},
        '7d': {label: '7d', points: 15, stepDays: 0.5},
        '30d': {label: '30d', points: 16, stepDays: 2},
        '90d': {label: '90d', points: 19, stepDays: 5},
        '1y': {label: '1y', points: 25, stepDays: 15},
        all: {label: 'All', points: 31, stepDays: 45},
    };

    const defaultState = {
        timeframe: '24h',
        percent: 5,
        signal: 'low',
        search: '',
        sort: 'closest',
        sortDirection: 'asc',
        selectedItemId: null,
    };

    const state = {...defaultState};

    const elements = {
        updatedAt: document.getElementById('ffUpdatedAt'),
        resetButton: document.getElementById('ffResetButton'),
        timeframeButtons: Array.from(document.querySelectorAll('#ffTimeframeGroup button')),
        signalButtons: Array.from(document.querySelectorAll('#ffSignalGroup button')),
        sortHeaders: Array.from(document.querySelectorAll('.ff-sort-header')),
        percentRange: document.getElementById('ffPercentRange'),
        percentInput: document.getElementById('ffPercentInput'),
        searchInput: document.getElementById('ffSearchInput'),
        sortSelect: document.getElementById('ffSortSelect'),
        resultsMeta: document.getElementById('ffResultsMeta'),
        resultsBody: document.getElementById('ffResultsBody'),
        resultsTable: document.getElementById('ffResultsTable'),
        resultsScroll: document.getElementById('ffResultsScroll'),
        tableScrollbar: document.getElementById('ffTableScrollbar'),
        tableScrollbarTrack: document.getElementById('ffTableScrollbarTrack'),
        emptyState: document.getElementById('ffEmptyState'),
        selectedMeta: document.getElementById('ffSelectedMeta'),
        selectedSignal: document.getElementById('ffSelectedSignal'),
        selectedPrice: document.getElementById('ffSelectedPrice'),
        selectedLowDistance: document.getElementById('ffSelectedLowDistance'),
        selectedHighDistance: document.getElementById('ffSelectedHighDistance'),
        selectedRange: document.getElementById('ffSelectedRange'),
        priceChartCanvas: document.getElementById('ffPriceChart'),
        priceChartEmpty: document.getElementById('ffPriceChartEmpty'),
        distributionChartCanvas: document.getElementById('ffDistributionChart'),
        distributionEmpty: document.getElementById('ffDistributionEmpty'),
    };

    const mockItems = [
        {
            id: 20997,
            name: 'Twisted bow',
            icon: 'Twisted bow.png',
            currentPrice: 1725000000,
            volume: 985000000,
            spread: 4500000,
            buyLimit: 8,
            members: true,
            phase: 0.4,
            trend: 0.18,
            distances: {default: {low: 3.2, high: 10.8}, '7d': {low: 6.8, high: 2.9}, all: {low: 19.4, high: 3.6}},
        },
        {
            id: 27277,
            name: "Tumeken's shadow",
            icon: "Tumeken's shadow.png",
            currentPrice: 1284000000,
            volume: 802000000,
            spread: 3200000,
            buyLimit: 8,
            members: true,
            phase: 1.1,
            trend: -0.06,
            distances: {default: {low: 8.4, high: 2.1}, '1h': {low: 2.6, high: 1.4}, '90d': {low: 16.2, high: 5.5}},
        },
        {
            id: 22486,
            name: 'Scythe of vitur',
            icon: 'Scythe of vitur.png',
            currentPrice: 1439000000,
            volume: 615000000,
            spread: 3850000,
            buyLimit: 8,
            members: true,
            phase: 2.2,
            trend: 0.1,
            distances: {default: {low: 2.2, high: 4.4}, '30d': {low: 9.7, high: 3.4}, all: {low: 28.5, high: 7.6}},
        },
        {
            id: 25862,
            name: 'Bow of faerdhinen',
            icon: 'Bow of faerdhinen (inactive).png',
            currentPrice: 138300000,
            volume: 611000000,
            spread: 410000,
            buyLimit: 8,
            members: true,
            phase: 1.7,
            trend: -0.12,
            distances: {default: {low: 1.5, high: 7.9}, '6h': {low: 4.7, high: 2.3}, '1y': {low: 12.8, high: 10.4}},
        },
        {
            id: 26219,
            name: "Osmumten's fang",
            icon: "Osmumten's fang.png",
            currentPrice: 17150000,
            volume: 292000000,
            spread: 68000,
            buyLimit: 8,
            members: true,
            phase: 0.9,
            trend: -0.2,
            distances: {default: {low: 5.8, high: 1.7}, '24h': {low: 4.8, high: 1.2}, '7d': {low: 10.9, high: 2.6}},
        },
        {
            id: 22978,
            name: 'Dragon hunter lance',
            icon: 'Dragon hunter lance.png',
            currentPrice: 64200000,
            volume: 188000000,
            spread: 225000,
            buyLimit: 8,
            members: true,
            phase: 2.9,
            trend: 0.08,
            distances: {default: {low: 9.9, high: 3.8}, '1h': {low: 2.1, high: 4.8}, '30d': {low: 4.1, high: 8.7}},
        },
        {
            id: 11785,
            name: 'Armadyl crossbow',
            icon: 'Armadyl crossbow.png',
            currentPrice: 31630000,
            volume: 254000000,
            spread: 122000,
            buyLimit: 8,
            members: true,
            phase: 0.2,
            trend: 0.14,
            distances: {default: {low: 2.8, high: 2.6}, '90d': {low: 8.8, high: 12.1}, all: {low: 21.5, high: 6.8}},
        },
        {
            id: 4151,
            name: 'Abyssal whip',
            icon: 'Abyssal whip.png',
            currentPrice: 1580000,
            volume: 144000000,
            spread: 9200,
            buyLimit: 70,
            members: true,
            phase: 2.4,
            trend: -0.05,
            distances: {default: {low: 7.1, high: 1.9}, '6h': {low: 1.8, high: 4.6}, '1y': {low: 13.2, high: 14.4}},
        },
        {
            id: 12934,
            name: 'Zulrah scales',
            icon: 'Zulrah scales 5.png',
            currentPrice: 188,
            volume: 2200000000,
            spread: 2,
            buyLimit: 30000,
            members: true,
            phase: 1.9,
            trend: -0.16,
            distances: {default: {low: 1.1, high: 6.7}, '24h': {low: 0.9, high: 4.8}, '7d': {low: 5.4, high: 2.0}},
        },
        {
            id: 565,
            name: 'Blood rune',
            icon: 'Blood rune.png',
            currentPrice: 221,
            volume: 1480000000,
            spread: 1,
            buyLimit: 25000,
            members: false,
            phase: 0.7,
            trend: 0.2,
            distances: {default: {low: 4.4, high: 1.3}, '30d': {low: 3.1, high: 7.9}, all: {low: 18.2, high: 5.1}},
        },
        {
            id: 6685,
            name: 'Saradomin brew(4)',
            icon: 'Saradomin brew(4).png',
            currentPrice: 7989,
            volume: 104900000,
            spread: 18,
            buyLimit: 2000,
            members: true,
            phase: 2.0,
            trend: -0.11,
            distances: {default: {low: 2.4, high: 5.2}, '1h': {low: 1.3, high: 2.8}, '90d': {low: 12.6, high: 2.7}},
        },
        {
            id: 3024,
            name: 'Super restore(4)',
            icon: 'Super restore(4).png',
            currentPrice: 9672,
            volume: 98000000,
            spread: 22,
            buyLimit: 2000,
            members: true,
            phase: 3.3,
            trend: 0.03,
            distances: {default: {low: 6.1, high: 2.4}, '24h': {low: 3.7, high: 2.0}, '30d': {low: 2.9, high: 7.1}},
        },
        {
            id: 11959,
            name: 'Black chinchompa',
            icon: 'Black chinchompa.png',
            currentPrice: 3617,
            volume: 84000000,
            spread: 31,
            buyLimit: 11000,
            members: true,
            phase: 2.7,
            trend: 0.17,
            distances: {default: {low: 2.0, high: 8.6}, '7d': {low: 6.4, high: 3.2}, '1y': {low: 16.8, high: 11.2}},
        },
        {
            id: 1513,
            name: 'Magic logs',
            icon: 'Magic logs.png',
            currentPrice: 1056,
            volume: 62000000,
            spread: 4,
            buyLimit: 12000,
            members: false,
            phase: 1.2,
            trend: -0.08,
            distances: {default: {low: 8.3, high: 2.2}, '6h': {low: 3.2, high: 4.0}, all: {low: 11.5, high: 18.4}},
        },
        {
            id: 453,
            name: 'Coal',
            icon: 'Coal.png',
            currentPrice: 173,
            volume: 49000000,
            spread: 1,
            buyLimit: 13000,
            members: false,
            phase: 0.5,
            trend: 0.07,
            distances: {default: {low: 3.6, high: 3.0}, '1h': {low: 0.8, high: 1.7}, '30d': {low: 9.6, high: 8.1}},
        },
        {
            id: 23959,
            name: 'Enhanced crystal teleport seed',
            icon: 'Enhanced crystal teleport seed.png',
            currentPrice: 3247703,
            volume: 128700000,
            spread: 16200,
            buyLimit: 70,
            members: true,
            phase: 2.5,
            trend: -0.18,
            distances: {default: {low: 11.5, high: 1.1}, '24h': {low: 7.2, high: 1.0}, '7d': {low: 4.7, high: 6.0}},
        },
        {
            id: 29025,
            name: 'Blood moon tassets',
            icon: 'Blood moon tassets.png',
            currentPrice: 10250320,
            volume: 84990000,
            spread: 78000,
            buyLimit: 8,
            members: true,
            phase: 3.0,
            trend: 0.21,
            distances: {default: {low: 1.7, high: 9.0}, '6h': {low: 4.8, high: 2.2}, '90d': {low: 24.6, high: 4.8}},
        },
        {
            id: 24514,
            name: 'Volatile orb',
            icon: 'Volatile orb.png',
            currentPrice: 40304521,
            volume: 82290000,
            spread: 185000,
            buyLimit: 8,
            members: true,
            phase: 1.4,
            trend: 0.1,
            distances: {default: {low: 4.6, high: 4.3}, '1h': {low: 6.4, high: 1.8}, all: {low: 30.0, high: 12.8}},
        },
    ];

    let filteredResults = [];
    let selectedResult = null;
    let priceChart = null;
    let distributionChart = null;
    let isSyncingHorizontalScroll = false;

    const defaultSortDirections = {
        closest: 'asc',
        name: 'asc',
        signal: 'asc',
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

    function formatInteger(value) {
        return Number(value).toLocaleString();
    }

    function formatGp(value) {
        return `${formatInteger(value)} gp`;
    }

    function formatCompactGp(value) {
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

    function formatPercent(value) {
        return `${Number(value).toFixed(1)}%`;
    }

    function getWikiIconUrl(icon) {
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

    function getDistanceProfile(item, timeframeKey) {
        return {
            ...item.distances.default,
            ...(item.distances[timeframeKey] || {}),
        };
    }

    function getHistoryLabel(timeframeKey, pointIndex, totalPoints) {
        const remaining = totalPoints - pointIndex - 1;
        if (remaining === 0) {
            return 'Now';
        }

        const config = timeframeConfig[timeframeKey];
        if (config.stepMinutes) {
            return `${remaining * config.stepMinutes}m ago`;
        }
        if (config.stepHours) {
            return `${remaining * config.stepHours}h ago`;
        }

        const days = remaining * config.stepDays;
        if (days < 1) {
            return `${Math.round(days * 24)}h ago`;
        }
        if (days >= 365) {
            return `${(days / 365).toFixed(1)}y ago`;
        }
        return `${Math.round(days)}d ago`;
    }

    function buildHistory(item, timeframeKey) {
        const config = timeframeConfig[timeframeKey];
        const profile = getDistanceProfile(item, timeframeKey);
        const periodLow = Math.max(1, Math.round(item.currentPrice / (1 + profile.low / 100)));
        const periodHigh = Math.max(item.currentPrice, Math.round(item.currentPrice / Math.max(0.05, 1 - profile.high / 100)));
        const range = Math.max(1, periodHigh - periodLow);
        const lowIndex = Math.max(1, Math.min(config.points - 3, Math.round(config.points * 0.28 + (item.id % 3))));
        const highIndex = Math.max(1, Math.min(config.points - 3, Math.round(config.points * 0.62 - (item.id % 2))));
        const points = [];

        for (let pointIndex = 0; pointIndex < config.points; pointIndex += 1) {
            const progress = pointIndex / (config.points - 1);
            const wave = Math.sin((progress * Math.PI * 2) + item.phase);
            const smallerWave = Math.cos((progress * Math.PI * 4) + item.phase) * 0.09;
            const trend = (progress - 0.5) * range * item.trend;
            let price = item.currentPrice + (wave * range * 0.18) + (smallerWave * range) + trend;

            if (pointIndex === lowIndex) {
                price = periodLow;
            } else if (pointIndex === highIndex) {
                price = periodHigh;
            } else if (pointIndex === config.points - 1) {
                price = item.currentPrice;
            } else {
                price = Math.max(periodLow, Math.min(periodHigh, Math.round(price)));
            }

            points.push({
                label: getHistoryLabel(timeframeKey, pointIndex, config.points),
                price: Math.round(price),
            });
        }

        return {
            points,
            periodLow,
            periodHigh,
        };
    }

    function buildResult(item) {
        const history = buildHistory(item, state.timeframe);
        const distanceFromLow = ((item.currentPrice - history.periodLow) / history.periodLow) * 100;
        const distanceFromHigh = ((history.periodHigh - item.currentPrice) / history.periodHigh) * 100;
        const nearLow = distanceFromLow <= state.percent;
        const nearHigh = distanceFromHigh <= state.percent;
        let signal = 'none';

        if (nearLow && nearHigh) {
            signal = 'both';
        } else if (nearLow) {
            signal = 'low';
        } else if (nearHigh) {
            signal = 'high';
        }

        return {
            ...item,
            history,
            distanceFromLow,
            distanceFromHigh,
            closestDistance: Math.min(distanceFromLow, distanceFromHigh),
            nearLow,
            nearHigh,
            signal,
        };
    }

    function resultMatchesSignal(result) {
        if (state.signal === 'low') {
            return result.nearLow;
        }
        if (state.signal === 'high') {
            return result.nearHigh;
        }
        return result.nearLow || result.nearHigh;
    }

    function getClosestSortDistance(result) {
        if (state.signal === 'low') {
            return result.distanceFromLow;
        }
        if (state.signal === 'high') {
            return result.distanceFromHigh;
        }
        return result.closestDistance;
    }

    function getFilteredResults() {
        const searchTerm = state.search.trim().toLowerCase();
        const results = mockItems
            .map(buildResult)
            .filter((result) => resultMatchesSignal(result))
            .filter((result) => !searchTerm || result.name.toLowerCase().includes(searchTerm));

        results.sort((firstResult, secondResult) => {
            let comparison = 0;

            if (state.sort === 'name') {
                comparison = firstResult.name.localeCompare(secondResult.name);
            } else if (state.sort === 'signal') {
                const signalOrder = {low: 1, high: 2, both: 3, none: 4};
                comparison = signalOrder[firstResult.signal] - signalOrder[secondResult.signal];
            } else if (state.sort === 'low') {
                comparison = firstResult.distanceFromLow - secondResult.distanceFromLow;
            } else if (state.sort === 'high') {
                comparison = firstResult.distanceFromHigh - secondResult.distanceFromHigh;
            } else {
                comparison = getClosestSortDistance(firstResult) - getClosestSortDistance(secondResult);
            }

            if (comparison === 0) {
                comparison = firstResult.name.localeCompare(secondResult.name);
            }

            return state.sortDirection === 'desc' ? -comparison : comparison;
        });

        return results;
    }

    function setSort(sortKey, shouldToggleDirection = false) {
        if (shouldToggleDirection && state.sort === sortKey) {
            state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            state.sort = sortKey;
            state.sortDirection = defaultSortDirections[sortKey] || 'asc';
        }
        renderAll();
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

        const hasOverflow = !elements.resultsTable.hidden && elements.resultsScroll.scrollWidth > elements.resultsScroll.clientWidth + 1;
        elements.tableScrollbar.hidden = !hasOverflow;
        elements.tableScrollbarTrack.style.width = `${elements.resultsScroll.scrollWidth}px`;

        if (hasOverflow) {
            elements.tableScrollbar.scrollLeft = elements.resultsScroll.scrollLeft;
        }
    }

    function syncHorizontalScroll(source, target) {
        if (!source || !target || isSyncingHorizontalScroll) {
            return;
        }
        isSyncingHorizontalScroll = true;
        target.scrollLeft = source.scrollLeft;
        isSyncingHorizontalScroll = false;
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
        window.addEventListener('resize', syncHorizontalScrollbarVisibility);
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

    function renderResult(result) {
        const selectedClass = selectedResult && selectedResult.id === result.id ? ' selected' : '';
        const signalClass = getSignalClass(result.signal);
        const memberText = result.members ? 'Members' : 'Free';

        return `
            <button type="button" class="ff-result-row${selectedClass}" data-item-id="${result.id}" role="row" aria-label="${escapeHtml(result.name)}">
                <span class="ff-item-cell" role="cell">
                    <span class="ff-item-icon" data-fallback="${escapeHtml(getInitials(result.name))}"><img src="${escapeHtml(getWikiIconUrl(result.icon))}" alt="${escapeHtml(result.name)}"></span>
                    <span>
                        <span class="ff-item-name">${escapeHtml(result.name)}</span>
                        <span class="ff-item-subtext">Limit ${formatInteger(result.buyLimit)} · ${memberText}</span>
                    </span>
                </span>
                <span class="ff-signal-cell" role="cell">
                    <span class="ff-cell-label">Signal</span>
                    <span class="ff-signal-badge ${signalClass}">${getSignalLabel(result.signal)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">Current</span>
                    <span class="ff-price">${formatGp(result.currentPrice)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">From Low</span>
                    <span class="ff-distance">${formatPercent(result.distanceFromLow)}</span>
                    <span class="ff-muted-value">${formatCompactGp(result.history.periodLow)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">From High</span>
                    <span class="ff-distance">${formatPercent(result.distanceFromHigh)}</span>
                    <span class="ff-muted-value">${formatCompactGp(result.history.periodHigh)}</span>
                </span>
                <span role="cell">
                    <span class="ff-cell-label">Volume</span>
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

    function renderResultsMeta(results) {
        elements.resultsMeta.textContent = `${formatInteger(results.length)} item${results.length === 1 ? '' : 's'}`;
    }

    function renderResults(results) {
        elements.emptyState.hidden = results.length > 0;
        elements.resultsTable.hidden = results.length === 0;
        elements.resultsBody.innerHTML = results.map(renderResult).join('');

        elements.resultsBody.querySelectorAll('.ff-result-row').forEach((button) => {
            button.addEventListener('click', () => {
                state.selectedItemId = Number(button.dataset.itemId);
                selectedResult = filteredResults.find((result) => result.id === state.selectedItemId) || null;
                renderAll();
            });
        });

        elements.resultsBody.querySelectorAll('.ff-item-icon img').forEach((image) => {
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

    function syncSelectedResult(results) {
        if (!results.length) {
            selectedResult = null;
            state.selectedItemId = null;
            return;
        }

        selectedResult = results.find((result) => result.id === state.selectedItemId) || results[0];
        state.selectedItemId = selectedResult.id;
    }

    function resetSelectedPanel() {
        elements.selectedMeta.textContent = '--';
        elements.selectedSignal.textContent = '--';
        elements.selectedSignal.className = 'ff-signal-badge';
        elements.selectedPrice.textContent = '--';
        elements.selectedLowDistance.textContent = '--';
        elements.selectedHighDistance.textContent = '--';
        elements.selectedRange.textContent = '--';
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
        elements.selectedMeta.textContent = selectedResult.name;
        elements.selectedSignal.textContent = getSignalLabel(selectedResult.signal);
        elements.selectedSignal.className = `ff-signal-badge ${signalClass}`;
        elements.selectedPrice.textContent = formatGp(selectedResult.currentPrice);
        elements.selectedLowDistance.textContent = formatPercent(selectedResult.distanceFromLow);
        elements.selectedHighDistance.textContent = formatPercent(selectedResult.distanceFromHigh);
        elements.selectedRange.textContent = `${formatCompactGp(selectedResult.history.periodLow)} - ${formatCompactGp(selectedResult.history.periodHigh)}`;
        elements.priceChartEmpty.hidden = true;
    }

    function renderPriceChart() {
        if (!window.Chart || !elements.priceChartCanvas) {
            return;
        }

        if (priceChart) {
            priceChart.destroy();
            priceChart = null;
        }

        if (!selectedResult) {
            return;
        }

        const labels = selectedResult.history.points.map((point) => point.label);
        const prices = selectedResult.history.points.map((point) => point.price);
        const lowLine = selectedResult.history.points.map(() => selectedResult.history.periodLow);
        const highLine = selectedResult.history.points.map(() => selectedResult.history.periodHigh);
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

    function getDistribution(results) {
        return {
            lowOnly: results.filter((result) => result.nearLow && !result.nearHigh).length,
            highOnly: results.filter((result) => result.nearHigh && !result.nearLow).length,
            both: results.filter((result) => result.nearLow && result.nearHigh).length,
        };
    }

    function renderDistributionChart(results) {
        if (!window.Chart || !elements.distributionChartCanvas) {
            return;
        }

        if (distributionChart) {
            distributionChart.destroy();
            distributionChart = null;
        }

        const distribution = getDistribution(results);
        const values = [distribution.lowOnly, distribution.highOnly, distribution.both];
        const hasValues = values.some((value) => value > 0);
        elements.distributionEmpty.hidden = hasValues;

        if (!hasValues) {
            return;
        }

        distributionChart = new Chart(elements.distributionChartCanvas.getContext('2d'), {
            type: 'doughnut',
            data: {
                labels: ['Near low', 'Near high', 'Near both'],
                datasets: [{
                    data: values,
                    backgroundColor: ['#0F766E', '#B45309', '#2563EB'],
                    borderWidth: 0,
                    hoverOffset: 4,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                cutout: '62%',
                plugins: {
                    legend: {position: 'bottom', labels: {boxWidth: 10, usePointStyle: true}},
                },
            },
        });
    }

    function updateControlStates() {
        updateSegmentedButtons(elements.timeframeButtons, state.timeframe, 'timeframe');
        updateSegmentedButtons(elements.signalButtons, state.signal, 'signal');
        updateSortHeaders();
        elements.percentRange.value = String(state.percent);
        elements.percentInput.value = String(state.percent);
        elements.searchInput.value = state.search;
        elements.sortSelect.value = state.sort;
    }

    function renderAll() {
        updateControlStates();
        filteredResults = getFilteredResults();
        syncSelectedResult(filteredResults);
        renderResultsMeta(filteredResults);
        renderResults(filteredResults);
        renderSelectedPanel();
        renderPriceChart();
        renderDistributionChart(filteredResults);
        syncHorizontalScrollbarVisibility();
        window.requestAnimationFrame(syncHorizontalScrollbarVisibility);
    }

    function setPercent(value) {
        state.percent = Math.round(clampNumber(value, 0.1, 25) * 10) / 10;
        renderAll();
    }

    elements.timeframeButtons.forEach((button) => {
        button.addEventListener('click', () => {
            state.timeframe = button.dataset.timeframe;
            renderAll();
        });
    });

    elements.signalButtons.forEach((button) => {
        button.addEventListener('click', () => {
            state.signal = button.dataset.signal;
            renderAll();
        });
    });

    elements.sortHeaders.forEach((header) => {
        header.addEventListener('click', () => {
            setSort(header.dataset.sort, true);
        });
    });

    elements.percentRange.addEventListener('input', () => setPercent(elements.percentRange.value));
    elements.percentInput.addEventListener('input', () => setPercent(elements.percentInput.value));
    elements.searchInput.addEventListener('input', () => {
        state.search = elements.searchInput.value;
        renderAll();
    });
    elements.sortSelect.addEventListener('change', () => {
        setSort(elements.sortSelect.value, false);
    });
    elements.resetButton.addEventListener('click', () => {
        Object.assign(state, defaultState);
        renderAll();
    });

    elements.updatedAt.textContent = `Mock scan · ${new Date().toLocaleString()}`;
    bindHorizontalScrollbar();
    renderAll();
}());
