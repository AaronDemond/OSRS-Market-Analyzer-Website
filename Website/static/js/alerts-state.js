    // DROPDOWN SIZING (compact label, expandable options)
    // =============================================================================
    const DropdownSizer = {
        _canvas: null,

        measureText(text, select) {
            if (!this._canvas) this._canvas = document.createElement('canvas');
            const ctx = this._canvas.getContext('2d');
            const style = window.getComputedStyle(select);
            ctx.font = `${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
            return ctx.measureText(text || '').width;
        },

        applySizing(select) {
            if (!select) return;
            const padding =
                parseFloat(window.getComputedStyle(select).paddingLeft || 0) +
                parseFloat(window.getComputedStyle(select).paddingRight || 0);
            const arrowSpace = 24; // room for native dropdown arrow

            const calcWidth = text => this.measureText(text, select) + padding + arrowSpace;
            const getExpandedWidth = () => {
                let max = 0;
                Array.from(select.options).forEach(opt => {max = Math.max(max, calcWidth(opt.text));});
                return max || calcWidth(select.options[0]?.text || '');
            };

            const updateCompactWidth = () => {
                const selectedText = select.options[select.selectedIndex]?.text || select.options[0]?.text || '';
                select.dataset.compactWidth = calcWidth(selectedText);
            };

            const applyCompact = () => {
                const width = select.dataset.compactWidth || calcWidth(select.options[0]?.text || '');
                select.style.minWidth = `${width}px`;
            };

            const expandedWidth = getExpandedWidth();
            select.dataset.expandedWidth = expandedWidth;
            updateCompactWidth();
            applyCompact();

            const expand = () => {select.style.minWidth = `${select.dataset.expandedWidth}px`;};
            const collapse = () => {applyCompact();};

            select.addEventListener('focus', expand);
            select.addEventListener('mousedown', expand);
            select.addEventListener('blur', collapse);
            select.addEventListener('change', () => {
                updateCompactWidth();
                collapse();
            });
        },

        init() {
            this.applySizing(document.querySelector('.action-dropdown'));
            this.applySizing(document.querySelector('.sort-dropdown'));
            this.applySizing(document.querySelector('.filter-dropdown'));
        }
    };


    // =============================================================================
    // STATE MANAGEMENT
    // =============================================================================
    /**
     * Application state manager.
     * 
     * Why: Centralizing state prevents scattered variables and makes it easier
     * to track and debug the application's current status.
     * 
     * How: All mutable state is stored in this object and accessed/modified
     * through consistent patterns.
     */
    const AlertsState = {
        spreadDataCache: {},            // Cache for spread alert data (keyed by alert ID)
        spikeDataCache: {},             // Cache for spike all-items data
        activeFilters: new Set(),       // Currently active filter IDs
        filterValues: {},               // Values for input-based filters (keyed by filter ID)
        alertGroups: [],                // Known alert groups
        cachedAlerts: [],               // Cached alerts data for instant filtering/sorting
        searchQuery: '',                // Current search query
        iconCache: {},                  // Cache for item icons (keyed by item_id)
        previousTriggeredItems: {},     // Track previously seen triggered items per alert (keyed by alert ID)
        dismissedNotifications: null,   // Set of dismissed alert notification IDs (persisted to localStorage)
        sorting: {                      // Current sorting state
            sortKey: null,
            sortOrder: null,
            pendingKey: null
        },

        /**
         * Gets the set of dismissed notification alert IDs.
         * Loads from localStorage if not in memory.
         */
        getDismissedNotifications() {
            if (this.dismissedNotifications !== null) {
                return this.dismissedNotifications;
            }
            // Load from localStorage
            try {
                const stored = localStorage.getItem('dismissedAlertNotifications');
                if (stored) {
                    this.dismissedNotifications = new Set(JSON.parse(stored));
                    return this.dismissedNotifications;
                }
            } catch (e) {
                console.error('Error loading dismissed notifications from localStorage:', e);
            }
            this.dismissedNotifications = new Set();
            return this.dismissedNotifications;
        },

        /**
         * Marks a notification as dismissed.
         * Persists to localStorage.
         */
        dismissNotification(alertId) {
            const dismissed = this.getDismissedNotifications();
            dismissed.add(String(alertId));
            try {
                localStorage.setItem('dismissedAlertNotifications', JSON.stringify([...dismissed]));
            } catch (e) {
                console.error('Error saving dismissed notifications to localStorage:', e);
            }
        },

        /**
         * Checks if a notification has been dismissed.
         */
        isNotificationDismissed(alertId) {
            return this.getDismissedNotifications().has(String(alertId));
        },

        /**
         * Clears a dismissed notification (e.g., when alert is re-triggered with new data).
         */
        clearDismissedNotification(alertId) {
            const dismissed = this.getDismissedNotifications();
            dismissed.delete(String(alertId));
            try {
                localStorage.setItem('dismissedAlertNotifications', JSON.stringify([...dismissed]));
            } catch (e) {
                console.error('Error saving dismissed notifications to localStorage:', e);
            }
        },

        /**
         * Active notifications cache - stores notification data that should be shown.
         * This persists notifications even if they're no longer in the API response.
         */
        activeNotificationsCache: null,

        /**
         * Gets all active notifications from localStorage.
         */
        getActiveNotifications() {
            if (this.activeNotificationsCache !== null) {
                return this.activeNotificationsCache;
            }
            try {
                const stored = localStorage.getItem('activeAlertNotifications');
                if (stored) {
                    this.activeNotificationsCache = JSON.parse(stored);
                    return this.activeNotificationsCache;
                }
            } catch (e) {
                console.error('Error loading active notifications from localStorage:', e);
            }
            this.activeNotificationsCache = {};
            return this.activeNotificationsCache;
        },

        /**
         * Adds or updates an active notification.
         */
        setActiveNotification(alertId, notificationData) {
            const active = this.getActiveNotifications();
            active[String(alertId)] = notificationData;
            try {
                localStorage.setItem('activeAlertNotifications', JSON.stringify(active));
            } catch (e) {
                console.error('Error saving active notifications to localStorage:', e);
            }
        },

        /**
         * Removes an active notification (when dismissed).
         */
        removeActiveNotification(alertId) {
            const active = this.getActiveNotifications();
            delete active[String(alertId)];
            try {
                localStorage.setItem('activeAlertNotifications', JSON.stringify(active));
            } catch (e) {
                console.error('Error saving active notifications to localStorage:', e);
            }
        },

        /**
         * Gets a specific active notification.
         */
        getActiveNotification(alertId) {
            return this.getActiveNotifications()[String(alertId)] || null;
        },

        /**
         * Stores spread data for a specific alert in the cache.
         * This allows the spread details modal to access the data later.
         */
        setSpreadData(alertId, data) {
            this.spreadDataCache[alertId] = data;
        },

        /**
         * Retrieves cached spread data for an alert.
         * Returns null if no data exists for the given ID.
         */
        getSpreadData(alertId) {
            return this.spreadDataCache[alertId] || null;
        },

        setSpikeData(alertId, data) {
            this.spikeDataCache[alertId] = data;
        },

        getSpikeData(alertId) {
            return this.spikeDataCache[alertId] || null;
        },

        /**
         * Updates known alert groups from alert data payload.
         */
        setAlertGroups(groups) {
            this.alertGroups = Array.isArray(groups) ? groups : [];
            // Update the create form group dropdown
            this.updateGroupDropdown();
        },

        /**
         * Updates the group dropdown in the create alert form.
         */
        updateGroupDropdown() {
            const dropdown = document.querySelector(AlertsConfig.selectors.create.alertGroup);
            if (!dropdown) return;

            const currentValue = dropdown.value;
            dropdown.innerHTML = '<option value="">No Group</option>';

            this.alertGroups.forEach(group => {
                const option = document.createElement('option');
                option.value = group;
                option.textContent = group;
                dropdown.appendChild(option);
            });

            // Restore selection if still valid
            if (currentValue && this.alertGroups.includes(currentValue)) {
                dropdown.value = currentValue;
            }
        },

        /**
         * Returns known alert groups.
         */
        getAlertGroups() {
            return this.alertGroups || [];
        },

        /**
         * Caches the alerts array for instant filtering/sorting.
         */
        setCachedAlerts(alerts) {
            this.cachedAlerts = Array.isArray(alerts) ? alerts : [];
        },

        /**
         * Returns the cached alerts array.
         */
        getCachedAlerts() {
            return this.cachedAlerts || [];
        },

        /**
         * Sets a value for an input-based filter.
         */
        setFilterValue(filterId, value) {
            this.filterValues[filterId] = value;
        },

        /**
         * Gets the value for an input-based filter.
         */
        getFilterValue(filterId) {
            return this.filterValues[filterId] || null;
        },

        /**
         * Gets the set of previously triggered item IDs for an alert.
         * Loads from localStorage if not in memory.
         */
        getPreviousTriggeredItems(alertId) {
            // Check memory first
            if (this.previousTriggeredItems[alertId]) {
                return this.previousTriggeredItems[alertId];
            }
            // Load from localStorage
            try {
                const stored = localStorage.getItem('alertTriggeredItems_' + alertId);
                if (stored) {
                    const arr = JSON.parse(stored);
                    this.previousTriggeredItems[alertId] = new Set(arr);
                    return this.previousTriggeredItems[alertId];
                }
            } catch (e) {
                console.error('Error loading triggered items from localStorage:', e);
            }
            return new Set();
        },

        /**
         * Updates the set of triggered item IDs for an alert.
         * Persists to localStorage.
         */
        setPreviousTriggeredItems(alertId, itemIds) {
            const idSet = new Set(itemIds);
            this.previousTriggeredItems[alertId] = idSet;
            // Persist to localStorage
            try {
                localStorage.setItem('alertTriggeredItems_' + alertId, JSON.stringify([...idSet]));
            } catch (e) {
                console.error('Error saving triggered items to localStorage:', e);
            }
        },

        /**
         * Computes newly triggered items by comparing current vs previous.
         * Returns { newItems: [...], allItems: [...], newCount: number }
         * Handles both spread (item_id) and spike (id) data structures.
         */
        computeNewTriggeredItems(alertId, currentData) {
            if (!currentData) return {newItems: [], allItems: [], newCount: 0};

            let items = [];
            try {
                items = typeof currentData === 'string' ? JSON.parse(currentData) : currentData;
                if (!Array.isArray(items)) items = [];
            } catch (e) {
                return {newItems: [], allItems: [], newCount: 0};
            }

            const previousSet = this.getPreviousTriggeredItems(alertId);
            // Handle both spread (item_id) and spike (id) data structures
            const currentItemIds = items.map(item => String(item.item_id || item.id));

            // On first load (no previous data in memory or localStorage), initialize tracking
            if (previousSet.size === 0 && currentItemIds.length > 0) {
                // First time seeing this alert - store items but report 0 new
                this.setPreviousTriggeredItems(alertId, currentItemIds);
                return {newItems: [], allItems: items, newCount: 0, isInitialLoad: true};
            }

            // Find new items (in current but not in previous)
            const newItems = items.filter(item => {
                const itemId = String(item.item_id || item.id);
                return !previousSet.has(itemId);
            });

            // Update tracked items
            this.setPreviousTriggeredItems(alertId, currentItemIds);

            return {newItems, allItems: items, newCount: newItems.length};
        }
    };


    // =============================================================================
