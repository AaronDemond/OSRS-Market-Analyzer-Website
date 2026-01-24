    // UI RENDERING
    // =============================================================================
    /**
     * Handles all DOM updates and HTML rendering.
     * 
     * Why: Separating UI logic from business logic makes the code easier to test,
     * modify, and understand. Changes to how things look don't affect how they work.
     * 
     * How: Each method handles a specific rendering task and returns HTML strings
     * or directly manipulates the DOM as appropriate.
     */
    const AlertsUI = {
        /**
         * Generates the triggered text for an alert based on its type and data.
         * 
         * Why: Different alert types need different information displayed when triggered.
         * - Spread (all items): Shows clickable link to view all matching items
         * - Spread (single item): Shows low, high, and spread percentage
         * - Above/Below: Shows the price movement that triggered the alert
         */
        buildTriggeredText(alert) {
            return 'Triggered';
        },

        /**
         * Checks if an alert is a spread-all-items type.
         */
        isSpreadAllItemsAlert(alert) {
            return alert.type === AlertsConfig.alertTypes.SPREAD &&
                alert.is_all_items &&
                alert.triggered_data;
        },

        /**
         * Checks if an alert is a spike-all-items type.
         */
        isSpikeAllItemsAlert(alert) {
            return alert.type === AlertsConfig.alertTypes.SPIKE &&
                alert.is_all_items &&
                alert.triggered_data;
        },

        /**
         * Renders the green notification banners for triggered alerts.
         * Stores notifications in localStorage so they persist until explicitly dismissed.
         * For "all items" alerts, tracks NEW triggered items.
         */
        renderTriggeredNotifications(triggeredAlerts) {
            // First, process incoming alerts and store them in active notifications cache
            if (triggeredAlerts && triggeredAlerts.length > 0) {
                triggeredAlerts.forEach(alert => {
                    // IMPORTANT: If the backend returns this alert with is_dismissed=False,
                    // it means the alert data has changed and we should show it again.
                    // Clear it from localStorage dismissed list to allow it to show.
                    // What: Clear this alert from the localStorage dismissed list
                    // Why: Backend sets is_dismissed=False when data changes, but localStorage still has it dismissed
                    // How: Call clearDismissedNotification to remove from localStorage dismissed set
                    if (AlertsState.isNotificationDismissed(alert.id)) {
                        // Backend says show it (is_dismissed=False), but localStorage says dismissed
                        // Trust the backend - clear the localStorage entry so notification can show
                        AlertsState.clearDismissedNotification(alert.id);
                    }
                    
                    const isSpreadAllItems = this.isSpreadAllItemsAlert(alert);
                    const isSpikeAllItems = this.isSpikeAllItemsAlert(alert);
                    const isAllItemsAlert = isSpreadAllItems || isSpikeAllItems;

                    // Cache spread/spike data for later use in modal
                    if (isSpreadAllItems) {
                        AlertsState.setSpreadData(alert.id, alert.triggered_data);
                    }
                    if (isSpikeAllItems) {
                        AlertsState.setSpikeData(alert.id, alert.triggered_data);
                    }

                    // Determine notification text
                    let notificationText = alert.triggered_text;
                    
                    // For "all items" alerts, check for NEW items
                    if (isAllItemsAlert && alert.triggered_data) {
                        const result = AlertsState.computeNewTriggeredItems(alert.id, alert.triggered_data);
                        
                        // If this is a subsequent load with new items, update the text
                        if (!result.isInitialLoad && result.newCount > 0) {
                            const matchPattern = /\((\d+) item\(s\) matched\)/;
                            if (matchPattern.test(notificationText)) {
                                notificationText = notificationText.replace(matchPattern, `(${result.newCount} NEW item(s) matched)`);
                            } else {
                                notificationText += ` (${result.newCount} NEW item(s))`;
                            }
                        }
                    }

                    // Store in active notifications cache (persists to localStorage)
                    AlertsState.setActiveNotification(alert.id, {
                        id: alert.id,
                        text: notificationText,
                        type: alert.type,
                        is_all_items: alert.is_all_items,
                        isSpreadAllItems: isSpreadAllItems,
                        isSpikeAllItems: isSpikeAllItems
                    });
                });
            }

            // Now render ALL active notifications from localStorage
            const activeNotifications = AlertsState.getActiveNotifications();
            let html = '';
            
            Object.values(activeNotifications).forEach(notification => {
                // Double-check it's not dismissed
                if (AlertsState.isNotificationDismissed(notification.id)) {
                    return;
                }
                
                const clickHandler = notification.isSpreadAllItems
                    ? 'onclick="ModalManager.showSpreadDetails(' + notification.id + ')"'
                    : (notification.isSpikeAllItems ? 'onclick="ModalManager.showSpikeDetails(' + notification.id + ')"' : '');
                const clickableClass = (notification.isSpreadAllItems || notification.isSpikeAllItems) ? 'clickable-triggered' : '';

                html += '<div class="triggered-notification" data-alert-id="' + notification.id + '">' +
                    '<span class="' + clickableClass + '" ' + clickHandler + '>' + notification.text + '</span>' +
                    '<button class="dismiss-btn" onclick="dismissAlert(' + notification.id + ')">&times;</button>' +
                    '</div>';
            });

            return html;
        },

        /**
         * Renders the action dropdown and filter dropdown.
         * @param {boolean} hasAlerts - Whether there are alerts to display
         * @param {string} preservedFilterTagsHtml - HTML of preserved filter tags (optional)
         */
        renderActionButtons(hasAlerts, preservedFilterTagsHtml) {
            if (!hasAlerts) return '';

            // Build filter dropdown items
            let filterItems = '';
            for (const [id, filter] of Object.entries(AlertsConfig.filters)) {
                const isActive = FilterManager.isActive(id);
                filterItems += '<div class="custom-dropdown-item' + (isActive ? ' active' : '') + '" data-filter="' + id + '">' +
                    '<span>' + filter.label + '</span>' +
                    '<span class="filter-check">✓</span>' +
                    '<span class="filter-clear" title="Clear filter">×</span>' +
                    '</div>';
            }

            // Use preserved filter tags if provided, otherwise build from state
            let tags = preservedFilterTagsHtml || '';
            if (!preservedFilterTagsHtml) {
                for (const filterId of AlertsState.activeFilters) {
                    const filter = AlertsConfig.filters[filterId];
                    if (filter) {
                        tags += '<span class="filter-tag" data-filter-id="' + filterId + '">' + filter.label +
                            '<button class="filter-tag-remove" onclick="removeFilter(\'' + filterId + '\')">&times;</button>' +
                            '</span>';
                    }
                }
            }

            // Build sort indicator HTML (desktop)
            let sortIndicatorHtml = '';
            // Build mobile sort indicator HTML
            let mobileSortIndicatorHtml = '';

            if (AlertsState.sorting.sortKey) {
                const sortOption = SortManager.options[AlertsState.sorting.sortKey];
                const label = sortOption ? sortOption.label : 'Sort';
                const arrow = AlertsState.sorting.sortOrder === 'asc' ? '↑' : '↓';
                sortIndicatorHtml = '<div class="sort-indicator-wrapper" id="sortIndicatorWrapper">' +
                    '<div class="sort-indicator active" id="sortIndicator">' +
                    '<span class="sort-indicator-label">Sorted by:</span>' +
                    '<span class="sort-indicator-value" id="sortIndicatorValue">' + label + '</span>' +
                    '<span class="sort-indicator-arrow" id="sortIndicatorArrow" title="Toggle sort order">' + arrow + '</span>' +
                    '<span class="sort-indicator-clear" id="sortIndicatorClear" title="Clear sort">×</span>' +
                    '</div>' +
                    '</div>';
                mobileSortIndicatorHtml = '<div class="sort-indicator-mobile-row" id="sortIndicatorMobileRow">' +
                    '<div class="sort-indicator active" id="sortIndicatorMobile">' +
                    '<span class="sort-indicator-label">Sorted by:</span>' +
                    '<span class="sort-indicator-value" id="sortIndicatorValueMobile">' + label + '</span>' +
                    '<span class="sort-indicator-arrow" id="sortIndicatorArrowMobile" title="Toggle sort order">' + arrow + '</span>' +
                    '<span class="sort-indicator-clear" id="sortIndicatorClearMobile" title="Clear sort">×</span>' +
                    '</div>' +
                    '</div>';
            } else {
                sortIndicatorHtml = '<div class="sort-indicator-wrapper" id="sortIndicatorWrapper">' +
                    '<div class="sort-indicator" id="sortIndicator">' +
                    '<span class="sort-indicator-label">Sorted by:</span>' +
                    '<span class="sort-indicator-value" id="sortIndicatorValue"></span>' +
                    '<span class="sort-indicator-arrow" id="sortIndicatorArrow" title="Toggle sort order">↓</span>' +
                    '<span class="sort-indicator-clear" id="sortIndicatorClear" title="Clear sort">×</span>' +
                    '</div>' +
                    '</div>';
                mobileSortIndicatorHtml = '<div class="sort-indicator-mobile-row" id="sortIndicatorMobileRow">' +
                    '<div class="sort-indicator" id="sortIndicatorMobile">' +
                    '<span class="sort-indicator-label">Sorted by:</span>' +
                    '<span class="sort-indicator-value" id="sortIndicatorValueMobile"></span>' +
                    '<span class="sort-indicator-arrow" id="sortIndicatorArrowMobile" title="Toggle sort order">↓</span>' +
                    '<span class="sort-indicator-clear" id="sortIndicatorClearMobile" title="Clear sort">×</span>' +
                    '</div>' +
                    '</div>';
            }

            // Build sort dropdown items
            const currentSortKey = AlertsState.sorting.sortKey;
            const sortItems = '' +
                '<div class="custom-dropdown-item' + (currentSortKey === 'alphabetically' ? ' active' : '') + '" data-sort="alphabetically"><span>Alphabetically</span><span class="sort-check">✓</span></div>' +
                '<div class="custom-dropdown-item' + (currentSortKey === 'lastTriggered' ? ' active' : '') + '" data-sort="lastTriggered"><span>Last Triggered Time</span><span class="sort-check">✓</span></div>' +
                '<div class="custom-dropdown-item' + (currentSortKey === 'alertType' ? ' active' : '') + '" data-sort="alertType"><span>Alert Type</span><span class="sort-check">✓</span></div>' +
                '<div class="custom-dropdown-item' + (currentSortKey === 'thresholdDistance' ? ' active' : '') + '" data-sort="thresholdDistance"><span>Threshold Distance</span><span class="sort-check">✓</span></div>' +
                '<div class="custom-dropdown-item' + (currentSortKey === 'createdDate' ? ' active' : '') + '" data-sort="createdDate"><span>Created Date</span><span class="sort-check">✓</span></div>';

            // Calculate filter badge
            const activeCount = AlertsState.activeFilters.size;
            const filterBadge = activeCount > 0
                ? '<span class="filter-badge" id="filterBadge">' + activeCount + '</span>'
                : '<span class="filter-badge" id="filterBadge" style="display: none;">0</span>';
            const filterBtnClass = activeCount > 0 ? 'btn-dropdown btn-filter has-active' : 'btn-dropdown btn-filter';

            // Build search bar with current value preserved
            const searchValue = AlertsState.searchQuery || '';
            const searchHasValue = searchValue.length > 0 ? ' has-value' : '';
            const searchBarHtml = '' +
                '<div class="alert-search-wrapper' + searchHasValue + '">' +
                '<svg class="alert-search-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"/>' +
                '</svg>' +
                '<input type="text" class="alert-search-input" id="alertSearchInput" placeholder="Search alerts..." autocomplete="off" value="' + searchValue.replace(/"/g, '&quot;') + '">' +
                '<button type="button" class="alert-search-clear" id="alertSearchClear" title="Clear search">×</button>' +
                '</div>';

            return '<div class="alert-actions-wrapper">' +
                '<div class="alert-actions">' +
                '<div class="alert-actions-left">' +
                '<div class="custom-dropdown-wrapper">' +
                '<button type="button" class="btn-dropdown btn-actions" id="actionsDropdownBtn">' +
                '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/>' +
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>' +
                '</svg>' +
                '<span class="btn-text">Actions</span>' +
                '</button>' +
                '<div class="custom-dropdown-menu" id="actionsDropdownMenu">' +
                '<div class="custom-dropdown-header">Actions</div>' +
                '<div class="custom-dropdown-item" data-action="delete"><span>Delete</span></div>' +
                '<div class="custom-dropdown-item" data-action="group"><span>Add to Group</span></div>' +
                '</div>' +
                '</div>' +
                searchBarHtml +
                '</div>' +
                '<div class="alert-actions-right" id="active-filters">' +
                '<div class="alert-actions-controls">' +
                '<div class="sort-controls">' +
                sortIndicatorHtml +
                '<div class="custom-dropdown-wrapper">' +
                '<button type="button" class="btn-dropdown btn-sort" id="sortDropdownBtn">' +
                '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4h13M3 8h9m-9 4h6m4 0l4-4m0 0l4 4m-4-4v12"/>' +
                '</svg>' +
                '<span class="btn-text">Sort</span>' +
                '</button>' +
                '<div class="custom-dropdown-menu" id="sortDropdownMenu">' +
                '<div class="custom-dropdown-header">Sort by</div>' +
                sortItems +
                '</div>' +
                '</div>' +
                '</div>' +
                '<div class="custom-dropdown-wrapper">' +
                '<button type="button" class="' + filterBtnClass + '" id="filterDropdownBtn">' +
                '<svg fill="none" stroke="currentColor" viewBox="0 0 24 24">' +
                '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z"/>' +
                '</svg>' +
                '<span class="btn-text">Filters</span>' +
                filterBadge +
                '</button>' +
                '<div class="custom-dropdown-menu" id="filterDropdownMenu">' +
                '<div class="custom-dropdown-header">Filter by</div>' +
                filterItems +
                '</div>' +
                '</div>' +
                '</div>' +
                '</div>' +
                '</div>' +
                mobileSortIndicatorHtml +
                '<div class="alert-indicators">' +
                '<div class="filter-tags">' + tags + '</div>' +
                '</div>' +
                '</div>';
        },

        /**
         * Renders a single alert list item.
         */
        renderAlertItem(alert) {
            const isSpreadAllItems = this.isSpreadAllItemsAlert(alert);
            const isSpikeAllItems = this.isSpikeAllItemsAlert(alert);

            // typeIconSvgs: inline SVGs keyed by alert type; ensures we show meaningful icons (spread/spike/sustained/threshold) when no item art exists (e.g., all-items alerts) by rendering semantic shapes that match alert intent. Icons use color cues for quick recognition.
            const typeIconSvgs = {
                // Spread: purple double-ended arrow between price ticks (margin/difference).
                spread: '<svg fill="none" stroke="#7C3AED" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 7v10M15 7v10M6 12h12M6 12l3-3M6 12l3 3M18 12l-3-3M18 12l-3 3"/></svg>',
                // Spike: red warning triangle with exclamation.
                spike: '<svg viewBox="0 0 24 24"><path d="M12 4l8 14H4L12 4z" fill="#DC2626" stroke="#B91C1C" stroke-width="1.5"/><path d="M12 9v5" stroke="#FFFFFF" stroke-width="2" stroke-linecap="round"/><circle cx="12" cy="17.5" r="1.2" fill="#FFFFFF"/></svg>',
                // Sustained: straight green line up/right on chart axes.
                sustained: '<svg fill="none" stroke="#16A34A" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 18h16M4 18V6M4 18L18 6"/></svg>',
                // Threshold: orange horizontal line with arrow pointing up/down representing price crossing a threshold level.
                threshold: '<svg fill="none" stroke="#F97316" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 12h16"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8V4M12 4l-3 3M12 4l3 3"/><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 16v4M12 20l-3-3M12 20l3-3"/></svg>'
            };

            // Cache spread data if triggered (for detail page)
            if (isSpreadAllItems && alert.is_triggered) {
                AlertsState.setSpreadData(alert.id, alert.triggered_data);
            }
            if (isSpikeAllItems && alert.is_triggered) {
                AlertsState.setSpikeData(alert.id, alert.triggered_data);
            }

            // Build triggered badge if needed
            let triggeredBadge = '';
            if (alert.is_triggered) {
                const triggeredText = this.buildTriggeredText(alert);
                triggeredBadge = '<span class="alert-triggered">' + triggeredText + '</span>';
            }

            // Build active/inactive status display
            const isActive = alert.is_active === true;
            const statusDisplay = isActive
                ? '<span class="alert-status alert-status-active">Active</span>'
                : '<span class="alert-status alert-status-inactive">Inactive</span>';

            // Build sort info text based on current sort
            let sortInfoHtml = '';
            const currentSort = AlertsState.sorting.sortKey;
            if (currentSort === 'lastTriggered') {
                const ts = alert.last_triggered_at || alert.triggered_at || alert.triggered_time || alert.last_triggered_time;
                let timeText = 'Never';
                if (ts) {
                    const date = new Date(ts);
                    if (!isNaN(date.getTime())) {
                        timeText = date.toLocaleString();
                    }
                }
                sortInfoHtml = '<div class="alert-sort-info">Last triggered: ' + timeText + '</div>';
            } else if (currentSort === 'createdDate') {
                let timeText = 'Unknown';
                if (alert.created_at) {
                    const date = new Date(alert.created_at);
                    if (!isNaN(date.getTime())) {
                        timeText = date.toLocaleString();
                    }
                }
                sortInfoHtml = '<div class="alert-sort-info">Created: ' + timeText + '</div>';
            } else if (currentSort === 'alertType') {
                const typeText = alert.type ? alert.type.charAt(0).toUpperCase() + alert.type.slice(1) : 'Unknown';
                sortInfoHtml = '<div class="alert-sort-info">Type: ' + typeText + '</div>';
            } else if (currentSort === 'thresholdDistance') {
                const thresholdDistance = SortManager.getThresholdDistance(alert);
                let distText = 'N/A';
                // =============================================================================
                // DISPLAY THRESHOLD DISTANCE OR MULTI-ITEM MESSAGE
                // =============================================================================
                // What: Format the threshold distance for display in the sort info section
                // Why: Users need visual feedback on how close alerts are to triggering
                // How: Check if result is a number (show %), 'multi' (show tracking message), or null (show N/A)
                if (thresholdDistance === 'multi') {
                    // Multi-item alert - distance calculation not applicable
                    distText = 'N/A - Tracking Multiple Items';
                } else if (typeof thresholdDistance === 'number' && !Number.isNaN(thresholdDistance)) {
                    distText = thresholdDistance.toFixed(2) + '%';
                }
                sortInfoHtml = '<div class="alert-sort-info">Threshold distance: ' + distText + '</div>';
            }

            // Build icon HTML - use item image if available, otherwise placeholder
            // Icons are served locally from /static/icons/ for faster loading
            // Local icons are named by item name (e.g., "Abyssal whip.png")
            let iconHtml;
            if (alert.icon) {
                // Cache the icon for this item
                if (alert.item_id) {
                    AlertsState.iconCache[alert.item_id] = alert.icon;
                }
                // iconFilename: Build local path using item_name (icons are named by item name, not API icon field)
                // Example: item_name "Abyssal whip" -> "/static/icons/Abyssal whip.png"
                // Falls back to alert.icon (replacing underscores with spaces) if item_name not available
                const iconFilename = alert.item_name ? alert.item_name : alert.icon.replace(/_/g, ' ').replace(/\.png$/i, '');
                const iconUrl = '/static/icons/' + encodeURIComponent(iconFilename) + '.png';
                iconHtml = '<img class="alert-icon" src="' + iconUrl + '" alt="" loading="lazy">';
            } else if (typeIconSvgs[alert.type]) {
                // Use semantic SVG icon when we lack item art (covers all-items and missing-icon cases) so the visual matches alert intent.
                iconHtml = '<span class="alert-icon-placeholder alert-type-icon" aria-hidden="true">' + typeIconSvgs[alert.type] + '</span>';
            } else if (alert.is_all_items) {
                // "All items" alerts fallback to neutral stack icon when no type-specific SVG exists.
                iconHtml = '<span class="alert-icon-placeholder">📊</span>';
            } else {
                // Fallback bell for items without icons and no type-specific SVG.
                iconHtml = '<span class="alert-icon-placeholder">🔔</span>';
            }

            // Determine display text - use custom name if not 'Default'
            const displayText = (alert.alert_name && alert.alert_name !== 'Default')
                ? alert.alert_name
                : alert.text;

            return '<li class="alert-item clickable-alert" data-alert-id="' + alert.id + '" data-alert-text="' + (alert.text || '').replace(/"/g, '&quot;') + '" onclick="navigateToAlertDetail(event, ' + alert.id + ')">' +
                '<input type="checkbox" class="alert-checkbox" onclick="event.stopPropagation()">' +
                iconHtml +
                '<div class="alert-content">' +
                '<span class="alert-text">' + displayText + '</span>' +
                sortInfoHtml +
                '</div>' +
                triggeredBadge +
                statusDisplay +
                '</li>';
        },

        /**
         * Renders the complete alerts list.
         * When groups filter is active, displays alerts grouped by their group names.
         */
        renderAlertsList(alerts) {
            if (!alerts || alerts.length === 0) {
                return '<p class="no-alerts">No active alerts. Create one to get started!</p>';
            }

            // Apply active filters then sort
            const filteredAlerts = SortManager.applySort(FilterManager.applyFilters(alerts));

            if (filteredAlerts.length === 0) {
                return '<p class="no-alerts">No alerts match the current filters.</p>';
            }

            // Check if groups filter is active - if so, render grouped
            const selectedGroups = AlertsState.getFilterValue('myGroups');
            if (selectedGroups && selectedGroups.length > 0 && AlertsState.activeFilters.has('myGroups')) {
                return this.renderGroupedAlertsList(filteredAlerts, selectedGroups);
            }

            let html = '<ul class="alerts-list">';
            filteredAlerts.forEach(alert => {
                html += this.renderAlertItem(alert);
            });
            html += '</ul>';
            return html;
        },

        /**
         * Renders alerts grouped by their group names.
         * Groups are displayed in alphabetical order, each with a header.
         */
        renderGroupedAlertsList(alerts, selectedGroups) {
            // Sort selected groups alphabetically
            const sortedGroups = [...selectedGroups].sort((a, b) => a.localeCompare(b));

            // Group alerts by their groups
            const groupedAlerts = {};
            sortedGroups.forEach(group => {
                groupedAlerts[group] = [];
            });

            alerts.forEach(alert => {
                const alertGroups = alert.groups || [];
                sortedGroups.forEach(group => {
                    if (alertGroups.includes(group)) {
                        groupedAlerts[group].push(alert);
                    }
                });
            });

            let html = '';
            sortedGroups.forEach(group => {
                const groupAlerts = groupedAlerts[group];
                if (groupAlerts.length > 0) {
                    const sortedGroupAlerts = SortManager.applySort(groupAlerts);
                    html += '<div class="alert-group">';
                    html += '<h3 class="alert-group-header">' + group + '</h3>';
                    html += '<ul class="alerts-list">';
                    sortedGroupAlerts.forEach(alert => {
                        html += this.renderAlertItem(alert);
                    });
                    html += '</ul>';
                    html += '</div>';
                }
            });

            if (!html) {
                return '<p class="no-alerts">No alerts found in the selected groups.</p>';
            }

            return html;
        },

        /**
         * Renders the spread details modal content.
         */
        renderSpreadItemsList(items) {
            let html = '';
            items.forEach(item => {
                const lowPrice = item.low ? item.low.toLocaleString() : 'N/A';
                const highPrice = item.high ? item.high.toLocaleString() : 'N/A';

                html += '<li>' +
                    '<div>' +
                    '<span class="spread-item-name">' + item.item_name + '</span>' +
                    '<div class="spread-item-details">Low: ' + lowPrice + ' | High: ' + highPrice + '</div>' +
                    '</div>' +
                    '<span class="spread-item-percentage">' + item.spread + '%</span>' +
                    '</li>';
            });
            return html;
        },

        /**
         * Renders spike items list for all-items spike alerts.
         */
        renderSpikeItemsList(items) {
            let html = '';
            items.forEach(item => {
                const baseline = item.baseline ? item.baseline.toLocaleString() : 'N/A';
                const current = item.current ? item.current.toLocaleString() : 'N/A';
                const percent = item.percent_change != null ? item.percent_change.toFixed(2) : 'N/A';
                const pctClass = (item.percent_change != null && item.percent_change < 0)
                    ? 'spread-item-percentage negative-change'
                    : 'spread-item-percentage';
                html += '<li>' +
                    '<div>' +
                    '<span class="spread-item-name">' + item.item_name + '</span>' +
                    '<div class="spread-item-details">Baseline: ' + baseline + ' | Current: ' + current + '</div>' +
                    '</div>' +
                    '<span class="' + pctClass + '">' + percent + '%</span>' +
                    '</li>';
            });
            return html;
        },

        /**
         * Renders autocomplete suggestions.
         */
        renderSuggestions(items) {
            let html = '';
            items.forEach(item => {
                html += '<div class="suggestion-item" data-id="' + item.id + '" data-name="' + item.name + '">' + item.name + '</div>';
            });
            return html;
        },

        /**
         * Updates the entire My Alerts pane with fresh data.
         * Preserves status notifications and filter tags to prevent flashing.
         */
        updateMyAlertsPane(data) {
            const pane = document.querySelector(AlertsConfig.selectors.myAlertsPane);
            if (!pane) return;

            if (data && data.groups) {
                AlertsState.setAlertGroups(data.groups);
            }

            // Cache alerts data for instant filtering/sorting
            if (data && data.alerts) {
                AlertsState.setCachedAlerts(data.alerts);
            }

            // Check if any alert checkboxes are checked
            const hasCheckedAlerts = pane.querySelectorAll('.alert-checkbox:checked').length > 0;

            // If any checkboxes are checked, skip the update entirely to preserve selection
            if (hasCheckedAlerts) {
                return;
            }

            // Check if filter dropdown is currently open/focused
            const filterDropdown = pane.querySelector('.filter-dropdown');
            const isFilterDropdownOpen = filterDropdown && document.activeElement === filterDropdown;

            // Check if sort dropdown is currently open/focused
            const sortDropdown = pane.querySelector('.sort-dropdown');
            const isSortDropdownOpen = sortDropdown && document.activeElement === sortDropdown;

            // Check if actions dropdown is currently open/focused
            const actionsDropdown = pane.querySelector('.action-dropdown');
            const isActionsDropdownOpen = actionsDropdown && document.activeElement === actionsDropdown;

            // If there are active filters, a filter input is open, or any dropdown is open, do selective update
            const hasActiveFilters = AlertsState.activeFilters.size > 0;
            const hasFilterInput = pane.querySelector('.filter-input-container') !== null;

            if (hasActiveFilters || hasFilterInput || isFilterDropdownOpen || isSortDropdownOpen || isActionsDropdownOpen) {
                this.updateMyAlertsPaneSelective(data);
                return;
            }

            // Preserve any status notifications (e.g., "Alert created")
            const existingStatusNotifications = pane.querySelectorAll('.status-notification');
            let statusHtml = '';
            existingStatusNotifications.forEach(n => {
                const clone = n.cloneNode(true);
                clone.querySelectorAll('.notification-line[data-kind="triggered"]').forEach(l => l.remove());

                const check = clone.cloneNode(true);
                const btn = check.querySelector('.dismiss-btn');
                if (btn) btn.remove();

                const hasContent = check.textContent.trim().length > 0 || check.querySelector('.notification-line');
                if (hasContent) {
                    statusHtml += clone.outerHTML;
                }
            });

            const notificationsHtml = this.renderTriggeredNotifications(data.triggered);
            const actionsHtml = this.renderActionButtons(data.alerts && data.alerts.length > 0, '');

            let alertsHtml = '';
            if (data.alerts && data.alerts.length > 0) {
                alertsHtml = this.renderAlertsList(data.alerts);
            } else if (!data.triggered || data.triggered.length === 0) {
                alertsHtml = this.renderAlertsList([]);
            }

            pane.innerHTML = '<div id="triggered-notifications">' + statusHtml + notificationsHtml + '</div>' +
                actionsHtml + alertsHtml;
            AlertActions.mergeTriggeredNotificationsIntoStatus();
        },

        /**
         * Selectively updates parts of the My Alerts pane without touching the action bar.
         * Used when filters are active to prevent filter tags from flashing.
         */
        updateMyAlertsPaneSelective(data) {
            const pane = document.querySelector(AlertsConfig.selectors.myAlertsPane);
            if (!pane) return;

            if (data && data.groups) {
                AlertsState.setAlertGroups(data.groups);
            }

            // Update triggered notifications (preserve status notifications)
            const notificationsContainer = pane.querySelector('#triggered-notifications');
            if (notificationsContainer) {
                const existingStatusNotifications = notificationsContainer.querySelectorAll('.status-notification');
                let statusHtml = '';
                existingStatusNotifications.forEach(n => {
                    const clone = n.cloneNode(true);
                    clone.querySelectorAll('.notification-line[data-kind="triggered"]').forEach(l => l.remove());

                    const check = clone.cloneNode(true);
                    const btn = check.querySelector('.dismiss-btn');
                    if (btn) btn.remove();

                    const hasContent = check.textContent.trim().length > 0 || check.querySelector('.notification-line');
                    if (hasContent) {
                        statusHtml += clone.outerHTML;
                    }
                });
                const notificationsHtml = this.renderTriggeredNotifications(data.triggered);
                notificationsContainer.innerHTML = statusHtml + notificationsHtml;
                AlertActions.mergeTriggeredNotificationsIntoStatus();
            }

            // Update alerts list only - find the container to replace
            const alertsList = pane.querySelector('.alerts-list');
            const alertGroup = pane.querySelector('.alert-group');
            const noAlertsMsg = pane.querySelector('.no-alerts');
            const loadingContainer = pane.querySelector('.loading-container');
            const alertsListContainer = pane.querySelector('#alerts-list-container');

            const filteredAlerts = FilterManager.applyFilters(data.alerts || []);
            const sortedAlerts = SortManager.applySort(filteredAlerts);

            // Check if groups filter is active
            const selectedGroups = AlertsState.getFilterValue('myGroups');
            const isGroupedView = selectedGroups && selectedGroups.length > 0 && AlertsState.activeFilters.has('myGroups');

            // Build the new HTML
            let newHtml = '';
            if (sortedAlerts.length === 0) {
                newHtml = '<p class="no-alerts">No alerts match the current filters.</p>';
            } else if (isGroupedView) {
                newHtml = this.renderGroupedAlertsList(sortedAlerts, selectedGroups);
            } else {
                newHtml = '<ul class="alerts-list">';
                sortedAlerts.forEach(alert => {
                    newHtml += this.renderAlertItem(alert);
                });
                newHtml += '</ul>';
            }

            // Replace the existing content
            if (alertGroup) {
                // If we have grouped view, replace all groups
                const allGroups = pane.querySelectorAll('.alert-group');
                const firstGroup = allGroups[0];
                allGroups.forEach((g, i) => {if (i > 0) g.remove();});
                if (firstGroup) {
                    firstGroup.outerHTML = newHtml;
                }
            } else if (alertsList) {
                alertsList.outerHTML = newHtml;
            } else if (alertsListContainer) {
                // Replace the loading container with alerts
                alertsListContainer.outerHTML = newHtml;
            } else if (loadingContainer) {
                // Replace standalone loading container
                loadingContainer.outerHTML = newHtml;
            } else if (noAlertsMsg) {
                noAlertsMsg.outerHTML = newHtml;
            }
        }
    };


    // =============================================================================
    // SORT MANAGEMENT
    // =============================================================================
    const SortManager = {
        options: {
            alphabetically: {id: 'alphabetically', label: 'Alphabetically', defaultOrder: 'asc'},
            lastTriggered: {id: 'lastTriggered', label: 'Last Triggered Time', defaultOrder: 'desc'},
            alertType: {id: 'alertType', label: 'Alert Type', defaultOrder: 'asc'},
            thresholdDistance: {id: 'thresholdDistance', label: 'Threshold Distance', defaultOrder: 'asc'},
            createdDate: {id: 'createdDate', label: 'Created Date', defaultOrder: 'desc'}
        },

        getSortValue(alert, sortKey) {
            switch (sortKey) {
                case 'alphabetically':
                    return (alert.text || '').toLowerCase();
                case 'lastTriggered': {
                    const ts = alert.last_triggered_at || alert.triggered_at || alert.triggered_time || alert.last_triggered_time;
                    return this.parseDateValue(ts);
                }
                case 'alertType':
                    return (alert.type || '').toString();
                case 'thresholdDistance':
                    return this.getThresholdDistance(alert);
                case 'createdDate':
                    return this.parseDateValue(alert.created_at);
                default:
                    return null;
            }
        },

        parseDateValue(value) {
            if (!value) return null;
            const ts = Date.parse(value);
            return isNaN(ts) ? null : ts;
        },

        getThresholdDistance(alert) {
            const {alertTypes} = AlertsConfig;
            if ((alert.type === alertTypes.ABOVE || alert.type === alertTypes.BELOW) && alert.price && alert.current_price) {
                const target = Number(alert.price);
                const current = Number(alert.current_price);
                if (!target || !Number.isFinite(current)) return null;
                const percentDiff = ((current - target) / target) * 100;
                return Number.isFinite(percentDiff) ? percentDiff : null;
            }
            if (alert.type === alertTypes.SPREAD && alert.percentage != null) {
                if (alert.spread_percentage != null) {
                    return Math.abs(alert.percentage - alert.spread_percentage);
                }
                if (alert.spread_current_percentage != null) {
                    return Math.abs(alert.percentage - alert.spread_current_percentage);
                }
            }
            if (alert.type === alertTypes.SPIKE) {
                // Use spike triggered data when available
                if (alert.triggered_data) {
                    try {
                        const data = JSON.parse(alert.triggered_data);
                        const baseline = Number(data?.baseline);
                        const current = Number(data?.current ?? alert.current_price);
                        if (Number.isFinite(baseline) && baseline !== 0 && Number.isFinite(current)) {
                            return ((current - baseline) / baseline) * 100;
                        }
                    } catch (e) {
                        // ignore parse errors
                    }
                }
                // Fallback to current price vs stored baseline in current_price if available (no baseline -> null)
                return null;
            }
            // =============================================================================
            // THRESHOLD ALERT DISTANCE CALCULATION
            // =============================================================================
            // What: Calculate how close a threshold alert is to being triggered
            // Why: Users want to see progress towards their alert threshold in the UI
            // How: For value-based: Calculate % difference between current price and target
            //      For percentage-based: Calculate current % change from baseline vs threshold
            // Note: Only works for single-item alerts; multi-item returns 'multi' flag for UI display
            if (alert.type === alertTypes.THRESHOLD) {
                // Check if this is a multi-item alert (item_ids contains multiple items or is_all_items)
                // What: Determine if alert tracks multiple items
                // Why: Threshold distance calculation only makes sense for single items
                // How: Parse item_ids JSON and check length, or check is_all_items flag
                if (alert.is_all_items) {
                    return 'multi';  // Signal to UI to show "N/A - Tracking Multiple Items"
                }
                if (alert.item_ids) {
                    try {
                        const itemIds = JSON.parse(alert.item_ids);
                        if (Array.isArray(itemIds) && itemIds.length > 1) {
                            return 'multi';  // Signal to UI to show "N/A - Tracking Multiple Items"
                        }
                    } catch (e) {
                        // Ignore parse errors, continue with calculation attempt
                    }
                }
                
                // Single-item threshold alert - calculate distance
                const thresholdType = alert.threshold_type || 'percentage';
                const currentPrice = Number(alert.current_price);
                
                if (!Number.isFinite(currentPrice) || currentPrice === 0) {
                    return null;  // No current price data available
                }
                
                if (thresholdType === 'value') {
                    // Value-based threshold: Calculate % distance from current price to target price
                    // What: How far is current price from the target in percentage terms
                    // Why: Gives user a sense of how close they are to their price target
                    // How: ((target - current) / current) * 100 for up direction
                    //      ((current - target) / current) * 100 for down direction
                    const targetPrice = Number(alert.target_price);
                    if (!Number.isFinite(targetPrice) || targetPrice === 0) {
                        return null;
                    }
                    
                    const direction = alert.direction || 'up';
                    if (direction === 'up') {
                        // For "up" alerts, positive = price needs to go up, negative = already above target
                        return ((targetPrice - currentPrice) / currentPrice) * 100;
                    } else {
                        // For "down" alerts, positive = price needs to go down, negative = already below target
                        return ((currentPrice - targetPrice) / currentPrice) * 100;
                    }
                } else {
                    // Percentage-based threshold: Calculate current % change from baseline
                    // What: How much has the price changed from baseline, compared to threshold
                    // Why: Shows progress towards the percentage threshold
                    // How: Parse reference_prices to get baseline, calculate current % change
                    if (!alert.reference_prices) {
                        return null;  // No baseline prices stored
                    }
                    
                    let baseline = null;
                    try {
                        const refPrices = JSON.parse(alert.reference_prices);
                        // For single-item alerts, get the baseline for the tracked item
                        const itemId = String(alert.item_id);
                        baseline = Number(refPrices[itemId]);
                    } catch (e) {
                        return null;  // Parse error
                    }
                    
                    if (!Number.isFinite(baseline) || baseline === 0) {
                        return null;  // Invalid baseline
                    }
                    
                    // Calculate current % change from baseline
                    // What: The actual percentage change that has occurred
                    // Why: Compare this to the threshold percentage to see how close to triggering
                    const currentChange = ((currentPrice - baseline) / baseline) * 100;
                    const thresholdPct = Number(alert.percentage) || 0;
                    const direction = alert.direction || 'up';
                    
                    if (direction === 'up') {
                        // For "up" alerts: threshold - currentChange = how much more it needs to rise
                        // Positive = needs to rise more, negative = already above threshold
                        return thresholdPct - currentChange;
                    } else {
                        // For "down" alerts: (-thresholdPct) - currentChange = how much more it needs to fall
                        // We want to show: if threshold is -5% and current is -3%, distance is 2%
                        return (-thresholdPct) - currentChange;
                    }
                }
            }
            return null;
        },

        applySort(alerts) {
            const sorted = [...alerts];
            const {sortKey, sortOrder} = AlertsState.sorting || {};
            if (!sortKey) {
                return sorted.sort((a, b) => (a.text || '').localeCompare(b.text || ''));
            }

            const direction = sortOrder === 'asc' ? 1 : -1;

            sorted.sort((a, b) => {
                const aVal = this.getSortValue(a, sortKey);
                const bVal = this.getSortValue(b, sortKey);
                // =============================================================================
                // HANDLE MISSING/INVALID SORT VALUES
                // =============================================================================
                // What: Determine if sort values are missing or non-numeric
                // Why: Alerts with missing values (null, undefined, NaN, 'multi') should sort to the end
                // How: Check for null, undefined, NaN, and the special 'multi' string marker
                // Note: We must NOT treat all strings as missing, because alphabetical sort returns strings!
                //       Only the special 'multi' marker (returned for multi-item threshold alerts) is missing.
                // =============================================================================
                const isMissingValue = (val) => val === null || val === undefined || Number.isNaN(val) || val === 'multi';
                const aMissing = isMissingValue(aVal);
                const bMissing = isMissingValue(bVal);

                // If one or both values are missing, handle specially
                if (aMissing || bMissing) {
                    if (aMissing && bMissing) {
                        // Both missing - fall back to alphabetical comparison
                        return (a.text || '').localeCompare(b.text || '');
                    }
                    // One is missing - push missing values to the end
                    if (aMissing) return 1;
                    if (bMissing) return -1;
                }
                
                // Both values are valid - compare them based on type
                // For strings (alphabetical sort): use localeCompare
                // For numbers (date, threshold distance): use numeric comparison
                if (typeof aVal === 'string' && typeof bVal === 'string') {
                    // String comparison (alphabetically sort)
                    const result = aVal.localeCompare(bVal);
                    return result * direction;
                } else {
                    // Numeric comparison (dates, threshold distance, etc.)
                    if (aVal > bVal) return direction;
                    if (aVal < bVal) return -direction;
                    return 0;
                }
            });

            return sorted;
        },

        handleSortSelection(sortKey) {
            if (!sortKey) return;
            const defaultOrder = this.options[sortKey]?.defaultOrder || 'asc';

            // If same sort is already active, just toggle order
            if (AlertsState.sorting.sortKey === sortKey) {
                this.toggleSortOrder();
                return;
            }

            // Apply new sort with default order
            AlertsState.sorting.sortKey = sortKey;
            AlertsState.sorting.sortOrder = defaultOrder;
            AlertsState.sorting.pendingKey = null;
            this.updateSortIndicator();
            FilterManager.updateAlertsList();
        },

        toggleSortOrder() {
            if (!AlertsState.sorting.sortKey) return;
            AlertsState.sorting.sortOrder = AlertsState.sorting.sortOrder === 'asc' ? 'desc' : 'asc';
            this.updateSortIndicator();
            FilterManager.updateAlertsList();
        },

        updateSortIndicator() {
            const indicator = document.getElementById('sortIndicator');
            const valueEl = document.getElementById('sortIndicatorValue');
            const arrowEl = document.getElementById('sortIndicatorArrow');

            // Mobile sort indicator elements
            const mobileRow = document.getElementById('sortIndicatorMobileRow');
            const mobileIndicator = document.getElementById('sortIndicatorMobile');
            const mobileValueEl = document.getElementById('sortIndicatorValueMobile');
            const mobileArrowEl = document.getElementById('sortIndicatorArrowMobile');

            if (!indicator) return;

            if (AlertsState.sorting.sortKey) {
                const option = this.options[AlertsState.sorting.sortKey];
                const label = option ? option.label : 'Sort';
                const arrow = AlertsState.sorting.sortOrder === 'asc' ? '↑' : '↓';

                // Update desktop indicator
                if (valueEl) valueEl.textContent = label;
                if (arrowEl) arrowEl.textContent = arrow;
                indicator.classList.add('active');

                // Update mobile indicator
                if (mobileValueEl) mobileValueEl.textContent = label;
                if (mobileArrowEl) mobileArrowEl.textContent = arrow;
                if (mobileIndicator) mobileIndicator.classList.add('active');
            } else {
                indicator.classList.remove('active');
                if (mobileIndicator) mobileIndicator.classList.remove('active');
            }

            // Update dropdown active states
            syncSortDropdownState();
        },

        applySortOrder(order) {
            const sortKey = AlertsState.sorting.pendingKey || AlertsState.sorting.sortKey;
            if (!sortKey) return;
            AlertsState.sorting.sortKey = sortKey;
            AlertsState.sorting.sortOrder = order || this.options[sortKey]?.defaultOrder || 'asc';
            AlertsState.sorting.pendingKey = null;
            this.updateSortIndicator();
            FilterManager.updateAlertsList();
            AlertsRefresh.resumeAfterSort();
        },

        clearSort() {
            AlertsState.sorting = {sortKey: null, sortOrder: null, pendingKey: null};
            this.updateSortIndicator();
            FilterManager.updateAlertsList();
        },

        renderSortTag() {
            // No longer using sort tags - using sort indicator instead
            // Keep this method for compatibility but do nothing
        }
    };


    // =============================================================================
    // FILTER MANAGEMENT
