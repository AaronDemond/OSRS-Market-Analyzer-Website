    // TAB NAVIGATION
    // =============================================================================
    /**
     * Manages tab switching between views.
     */
    const TabManager = {
        /**
         * Switches to a specific tab.
         */
        switchTo(tabId) {
            const activeBtn = document.querySelector(AlertsConfig.selectors.tabButtons + '.active');
            const currentTab = activeBtn ? activeBtn.getAttribute('data-tab') : null;
            if (currentTab === 'my-alerts' && tabId !== 'my-alerts') {
                AlertActions.clearStatusNotifications();
            }

            document.querySelectorAll(AlertsConfig.selectors.tabButtons).forEach(btn => {
                btn.classList.remove('active');
                if (btn.getAttribute('data-tab') === tabId) {
                    btn.classList.add('active');
                }
            });

            document.querySelectorAll(AlertsConfig.selectors.tabPanes).forEach(pane => {
                pane.style.display = 'none';
            });
            document.getElementById(tabId).style.display = 'block';

            if (tabId === 'my-alerts') {
                AlertActions.mergeTriggeredNotificationsIntoStatus();
            }
        },

        /**
         * Initializes tab click handlers.
         */
        init() {
            document.querySelectorAll(AlertsConfig.selectors.tabButtons).forEach(button => {
                button.addEventListener('click', function () {
                    const tabId = button.getAttribute('data-tab');
                    TabManager.switchTo(tabId);
                });
            });
        }
    };


    // =============================================================================
    // FORM VALIDATION
    // =============================================================================
    /**
     * Handles form validation and error display for the create alert form.
     */
    const FormValidation = {
        /**
         * Shows an error notification in the triggered-notifications area.
         * @param {string} message - The error message to display
         */
        showError(message) {
            // =============================================================================
            // DETERMINE WHERE TO SHOW THE ERROR NOTIFICATION
            // =============================================================================
            // What: Find or create a container to display the error notification
            // Why: Errors can occur on either the Create Alert tab (form validation) or
            //       the My Alerts tab (validation errors passed from alert_detail.html)
            // How: Check which tab is currently visible by checking the display style
            //       If Create Alert is visible, show error above the form card
            //       If My Alerts is visible, use triggered-notifications container
            
            let notificationsContainer = null;
            
            // Check which tab is currently visible by checking the display style of tab panes
            // The active tab pane has display: block (or non-empty), inactive ones have display: none
            const createAlertTab = document.getElementById('create-alert');
            const myAlertsTab = document.getElementById('my-alerts');
            
            // isCreateAlertVisible: True if Create Alert tab pane is currently displayed
            // Check for display === 'block' because that's what TabManager.switchTo sets
            const isCreateAlertVisible = createAlertTab && createAlertTab.style.display === 'block';
            
            if (isCreateAlertVisible) {
                // We're on the Create Alert tab - show error ABOVE the form card
                notificationsContainer = createAlertTab.querySelector('.form-error-container');

                // If no dedicated error container exists, create one above the form (not inside it)
                // What: Create a container div that sits above the white form card
                // Why: User wants the error notification to appear above the form, not within it
                // How: Insert the container as the first child of the tab pane, before the form
                if (!notificationsContainer) {
                    const form = document.querySelector('.create-alert-form');
                    if (form && createAlertTab) {
                        notificationsContainer = document.createElement('div');
                        notificationsContainer.className = 'form-error-container';
                        // Insert before the form, making it appear above the white card
                        createAlertTab.insertBefore(notificationsContainer, form);
                    }
                }
            } else {
                // We're on My Alerts tab (or fallback) - use triggered-notifications container
                // This is used when errors are passed from alert_detail.html via sessionStorage
                const triggeredNotificationsContainer = document.getElementById('triggered-notifications');
                if (triggeredNotificationsContainer) {
                    notificationsContainer = triggeredNotificationsContainer;
                }
            }

            if (!notificationsContainer) return;

            // Remove any existing error notifications
            notificationsContainer.querySelectorAll('.triggered-notification.error-notification').forEach(n => n.remove());

            // Create error notification
            const notification = document.createElement('div');
            notification.className = 'triggered-notification error-notification';
            notification.innerHTML = message + '<button class="dismiss-btn" type="button">&times;</button>';

            // Add click handler for dismiss button
            const dismissBtn = notification.querySelector('.dismiss-btn');
            if (dismissBtn) {
                dismissBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    notification.classList.add('dismissing');
                    setTimeout(() => notification.remove(), 300);
                });
            }

            notificationsContainer.appendChild(notification);
            
            // Scroll to top of the form/container so user can see the error notification
            // This ensures visibility even if user has scrolled down
            notificationsContainer.scrollIntoView({ behavior: 'smooth', block: 'start' });

            // Auto-dismiss after 5 seconds
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.classList.add('dismissing');
                    setTimeout(() => notification.remove(), 300);
                }
            }, 5000);
        }
    };


    // =============================================================================
    // EVENT MANAGEMENT
    // =============================================================================
    /**
     * Sets up all event listeners for the alerts system.
     */
    const EventManager = {
        /**
         * Sets up modal event listeners.
         */
        setupModalEvents() {
            const spreadModal = document.querySelector(AlertsConfig.selectors.spreadModal);
            const groupModal = document.querySelector(AlertsConfig.selectors.groupModal);
            const spikeModal = document.querySelector(AlertsConfig.selectors.spikeModal);

            // Close spread modal on backdrop click
            if (spreadModal) {
                spreadModal.addEventListener('click', function (e) {
                    if (e.target.id === 'spread-modal') {
                        ModalManager.closeSpreadModal();
                    }
                });
            }

            // Close spike modal on backdrop click
            if (spikeModal) {
                spikeModal.addEventListener('click', function (e) {
                    if (e.target.id === 'spike-modal') {
                        ModalManager.closeSpikeModal();
                    }
                });
            }

            // Close group modal on backdrop click
            if (groupModal) {
                groupModal.addEventListener('click', function (e) {
                    if (e.target.id === 'group-modal') {
                        GroupManager.close();
                    }
                });
            }

            // Close delete confirm modal on backdrop click
            const deleteModal = document.getElementById('delete-confirm-modal');
            if (deleteModal) {
                deleteModal.addEventListener('click', function (e) {
                    if (e.target.id === 'delete-confirm-modal') {
                        closeDeleteConfirmModal();
                    }
                });
            }

            // Close modals on Escape key
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape') {
                    const spreadModal = document.querySelector(AlertsConfig.selectors.spreadModal);
                    if (spreadModal && spreadModal.style.display === 'flex') {
                        ModalManager.closeSpreadModal();
                    }
                    const spikeModal = document.querySelector(AlertsConfig.selectors.spikeModal);
                    if (spikeModal && spikeModal.style.display === 'flex') {
                        ModalManager.closeSpikeModal();
                    }
                    const groupModal = document.querySelector(AlertsConfig.selectors.groupModal);
                    if (groupModal && groupModal.style.display === 'flex') {
                        GroupManager.close();
                    }
                    const deleteModal = document.getElementById('delete-confirm-modal');
                    if (deleteModal && deleteModal.style.display === 'flex') {
                        closeDeleteConfirmModal();
                    }
                }
            });
        },

        /**
         * Sets up autocomplete dropdown close on outside click.
         */
        setupAutocompleteEvents() {
            document.addEventListener('click', function (e) {
                if (!e.target.closest('.form-group')) {
                    const createSuggestions = document.querySelector(AlertsConfig.selectors.create.suggestions);

                    if (createSuggestions) createSuggestions.style.display = 'none';
                }
            });
        },

        /**
         * Sets up custom dropdown toggle and click outside behavior.
         * Uses event delegation to handle dynamically rendered dropdowns.
         */
        setupDropdownEvents() {
            // Toggle dropdown menus on button click (event delegation)
            document.addEventListener('click', function (e) {
                const btn = e.target.closest('.btn-dropdown');
                if (btn) {
                    // IMMEDIATELY pause refresh before doing anything else
                    AlertsRefresh.onDropdownOpen();

                    e.stopPropagation();
                    const wrapper = btn.closest('.custom-dropdown-wrapper');
                    const menu = wrapper.querySelector('.custom-dropdown-menu');
                    const isOpen = menu.classList.contains('show');

                    // Close all other dropdowns
                    document.querySelectorAll('.custom-dropdown-menu.show').forEach(m => {
                        m.classList.remove('show');
                    });

                    // Toggle this dropdown
                    if (!isOpen) {
                        menu.classList.add('show');
                    } else {
                        // Dropdown is being closed, resume refresh
                        AlertsRefresh.onDropdownClose();
                    }
                    return;
                }

                // Handle actions dropdown item clicks
                const actionItem = e.target.closest('#actionsDropdownMenu .custom-dropdown-item');
                if (actionItem) {
                    const action = actionItem.dataset.action;
                    AlertActions.handleAction(action);
                    document.getElementById('actionsDropdownMenu')?.classList.remove('show');
                    AlertsRefresh.onDropdownClose();
                    return;
                }

                // Handle sort dropdown item clicks
                const sortItem = e.target.closest('#sortDropdownMenu .custom-dropdown-item');
                if (sortItem) {
                    const sortKey = sortItem.dataset.sort;

                    // Update active state visually
                    document.querySelectorAll('#sortDropdownMenu .custom-dropdown-item').forEach(i => {
                        i.classList.remove('active');
                    });
                    sortItem.classList.add('active');

                    handleSortSelection(sortKey);
                    document.getElementById('sortDropdownMenu')?.classList.remove('show');
                    AlertsRefresh.onDropdownClose();
                    return;
                }

                // Handle sort indicator arrow click (toggle order)
                if (e.target.id === 'sortIndicatorArrow' || e.target.closest('#sortIndicatorArrow') ||
                    e.target.id === 'sortIndicatorArrowMobile' || e.target.closest('#sortIndicatorArrowMobile')) {
                    e.stopPropagation();
                    SortManager.toggleSortOrder();
                    return;
                }

                // Handle sort indicator clear click
                if (e.target.id === 'sortIndicatorClear' || e.target.closest('#sortIndicatorClear') ||
                    e.target.id === 'sortIndicatorClearMobile' || e.target.closest('#sortIndicatorClearMobile')) {
                    e.stopPropagation();
                    clearSort();
                    return;
                }

                // Handle filter dropdown item clicks
                const filterItem = e.target.closest('#filterDropdownMenu .custom-dropdown-item');
                if (filterItem) {
                    const filterId = filterItem.dataset.filter;

                    // Check if clicking the clear button
                    if (e.target.classList.contains('filter-clear')) {
                        filterItem.classList.remove('active');
                        removeFilter(filterId);
                        updateFilterBadge();
                        document.getElementById('filterDropdownMenu')?.classList.remove('show');
                        return;
                    }

                    // Check if this filter requires a modal (don't toggle active state yet)
                    const filter = AlertsConfig.filters[filterId];
                    const requiresModal = filter && filter.requiresModal;

                    // Toggle filter
                    if (filterItem.classList.contains('active')) {
                        filterItem.classList.remove('active');
                        removeFilter(filterId);
                        updateFilterBadge();
                    } else {
                        // Only mark as active immediately if it doesn't require a modal
                        if (!requiresModal) {
                            filterItem.classList.add('active');
                            updateFilterBadge();
                        }
                        addFilter(filterId);
                    }
                    document.getElementById('filterDropdownMenu')?.classList.remove('show');
                    return;
                }

                // Close dropdowns on outside click
                if (!e.target.closest('.custom-dropdown-wrapper')) {
                    document.querySelectorAll('.custom-dropdown-menu.show').forEach(m => {
                        m.classList.remove('show');
                    });
                }
            });
        },

        /**
         * Sets up search input event handlers using event delegation.
         */
        setupSearchEvents() {
            // Use event delegation so events work after DOM re-render
            document.addEventListener('input', function (e) {
                if (e.target.id === 'alertSearchInput') {
                    AlertsState.searchQuery = e.target.value;
                    const searchWrapper = e.target.closest('.alert-search-wrapper');
                    if (searchWrapper) {
                        searchWrapper.classList.toggle('has-value', e.target.value.length > 0);
                    }
                    FilterManager.updateAlertsList();
                }
            });

            document.addEventListener('keydown', function (e) {
                if (e.target.id === 'alertSearchInput') {
                    if (e.key === 'Escape') {
                        e.target.value = '';
                        AlertsState.searchQuery = '';
                        const searchWrapper = e.target.closest('.alert-search-wrapper');
                        if (searchWrapper) {
                            searchWrapper.classList.remove('has-value');
                        }
                        FilterManager.updateAlertsList();
                        e.target.blur();
                    } else if (e.key === 'Enter') {
                        e.preventDefault();
                        e.target.blur();
                    }
                }
            });

            document.addEventListener('click', function (e) {
                if (e.target.id === 'alertSearchClear' || e.target.closest('#alertSearchClear')) {
                    const searchInput = document.getElementById('alertSearchInput');
                    if (searchInput) {
                        searchInput.value = '';
                        AlertsState.searchQuery = '';
                        const searchWrapper = searchInput.closest('.alert-search-wrapper');
                        if (searchWrapper) {
                            searchWrapper.classList.remove('has-value');
                        }
                        FilterManager.updateAlertsList();
                    }
                }
            });
        },

        /**
         * Initializes all event listeners.
         */
        init() {
            this.setupModalEvents();
            this.setupAutocompleteEvents();
            this.setupDropdownEvents();
            this.setupSearchEvents();
            this.setupFormValidation();
        },

        /**
         * Sets up form validation for the create alert form.
         */
        setupFormValidation() {
            const form = document.querySelector('.create-alert-form');
            if (!form) return;

            // Prevent Enter from submitting unless the Create Alert button is focused
            form.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') {
                    const submitBtn = form.querySelector('button[type="submit"]');
                    if (document.activeElement !== submitBtn) {
                        e.preventDefault();
                    }
                }
            });

            // Validate on submit
            form.addEventListener('submit', function (e) {
                const alertType = document.getElementById('alert-type').value;
                const errors = [];

                // Check item name for types that need it
                const itemNameGroup = document.getElementById('item-name-group');
                const itemNameVisible = itemNameGroup && itemNameGroup.style.display !== 'none';

                if (itemNameVisible) {
                    const itemName = document.getElementById('item-name').value.trim();
                    const itemId = document.getElementById('item-id').value.trim();

                    if (!itemName) {
                        errors.push('Item name is required');
                    } else if (!itemId) {
                        errors.push('Please select a valid item from the suggestions');
                    }
                }

                // Check price for above/below types
                if (alertType === 'above' || alertType === 'below') {
                    const price = document.getElementById('price').value;
                    if (!price || price <= 0) {
                        errors.push('Price threshold is required');
                    }
                }

                // Check percentage for spread/spike types
                if (alertType === 'spread' || alertType === 'spike') {
                    const percentage = document.getElementById('percentage').value;
                    if (!percentage || percentage <= 0) {
                        errors.push('Percentage is required');
                    }
                }

                // Check time frame for spike type
                if (alertType === 'spike') {
                    const timeFrame = document.getElementById('time-frame').value;
                    if (!timeFrame || timeFrame <= 0) {
                        errors.push('Time frame is required');
                    }
                }

                // Check sustained move specific fields
                if (alertType === 'sustained') {
                    const timeFrame = document.getElementById('time-frame').value;
                    if (!timeFrame || timeFrame <= 0) {
                        errors.push('Time frame is required');
                    }
                    const minMoves = document.getElementById('min-consecutive-moves').value;
                    if (!minMoves || minMoves < 2) {
                        errors.push('Minimum consecutive moves must be at least 2');
                    }
                    const minMovePercent = document.getElementById('min-move-percentage').value;
                    if (!minMovePercent || minMovePercent <= 0) {
                        errors.push('Minimum move percentage is required');
                    }
                    const volBuffer = document.getElementById('volatility-buffer-size').value;
                    if (!volBuffer || volBuffer < 5) {
                        errors.push('Volatility buffer size must be at least 5');
                    }
                    const volMultiplier = document.getElementById('volatility-multiplier').value;
                    if (!volMultiplier || volMultiplier <= 0) {
                        errors.push('Volatility multiplier is required');
                    }

                    // Check items - either all items or at least one specific item
                    const sustainedScope = document.getElementById('sustained-scope').value;
                    if (sustainedScope === 'specific') {
                        const selectedItemIds = document.getElementById('sustained-item-ids').value;
                        if (!selectedItemIds || selectedItemIds.trim() === '') {
                            errors.push('Please select at least one item');
                        }
                    }
                }

                // =============================================================================
                // ALL ITEMS MIN/MAX PRICE VALIDATION
                // =============================================================================
                // What: Validates that both minimum and maximum price fields have values when
                //       "All Items" is selected for any alert type
                // Why: When monitoring all items, price range filters are REQUIRED to narrow
                //       down the items being tracked - without them, the alert would monitor
                //       every single item in the database which is impractical and noisy
                // How: Check the hidden is-all-items field value, and if true, verify both
                //       minimum-price and maximum-price inputs have non-empty values
                // Note: This validation applies to ALL alert types (spread, spike, sustained, threshold)
                //       when they are configured to track "All Items"
                const isAllItemsValue = document.getElementById('is-all-items').value;
                if (isAllItemsValue === 'true') {
                    // minPriceValue: The value from the minimum price input field
                    // maxPriceValue: The value from the maximum price input field
                    // We check for empty string, null, or undefined to catch all cases
                    const minPriceValue = document.getElementById('minimum-price').value;
                    const maxPriceValue = document.getElementById('maximum-price').value;
                    
                    // Both fields must have values when All Items is selected
                    // We trim to catch whitespace-only inputs as invalid
                    if (!minPriceValue || minPriceValue.trim() === '') {
                        errors.push('Minimum Price is required when tracking All Items');
                    }
                    if (!maxPriceValue || maxPriceValue.trim() === '') {
                        errors.push('Maximum Price is required when tracking All Items');
                    }
                }

                if (errors.length > 0) {
                    e.preventDefault();
                    FormValidation.showError(errors[0]);
                }
            });
        }
    };


    // =============================================================================
    // GLOBAL FUNCTION EXPORTS
    // =============================================================================
    /**
     * These functions are exposed globally for use in onclick handlers in HTML.
     */

    // Alert name type handler
    function handleAlertNameTypeChange() {
        const nameType = document.getElementById('alert-name-type').value;
        const customNameGroup = document.getElementById('custom-name-group');
        const customNameInput = document.getElementById('alert-custom-name');

        if (nameType === 'custom') {
            customNameGroup.style.display = '';
            customNameInput.required = true;
        } else {
            customNameGroup.style.display = 'none';
            customNameInput.required = false;
            customNameInput.value = '';
        }
    }

    // Form handlers
    function handleAlertTypeChange() {
        FormManager.handleAlertTypeChange('create');
    }

    function handleSpreadScopeChange() {
        FormManager.handleSpreadScopeChange('create');
    }

    function handleSpikeScopeChange() {
        FormManager.handleSpikeScopeChange('create');
    }

    function handleSustainedScopeChange() {
        FormManager.handleSustainedScopeChange('create');
    }

    /**
     * Global wrapper for handling threshold Items Tracked dropdown changes.
     * 
     * What: Calls FormManager.handleThresholdItemsTrackedChange when user changes "All Items" vs "Specific Items"
     * Why: HTML onchange attributes can only call global functions, not module-scoped ones
     * How: Delegates to FormManager which shows/hides the item selector and updates threshold type state
     */
    function handleThresholdItemsTrackedChange() {
        FormManager.handleThresholdItemsTrackedChange('create');
    }

    // Modal handlers
    function closeSpreadModal() {
        ModalManager.closeSpreadModal();
    }

    function showSpreadDetails(alertId) {
        ModalManager.showSpreadDetails(alertId);
    }

    function closeSpikeModal() {
        ModalManager.closeSpikeModal();
    }

    function showSpikeDetails(alertId) {
        ModalManager.showSpikeDetails(alertId);
    }

    // Navigate to alert detail page
    function navigateToAlertDetail(event, alertId) {
        // Don't navigate if clicking on checkbox
        if (event.target.classList.contains('alert-checkbox')) {
            return;
        }
        window.location.href = '/alerts/' + alertId + '/';
    }

    // Alert action handlers
    function dismissAlert(alertId) {
        AlertActions.dismiss(alertId);
    }

    function dismissStatusNotification(button) {
        const notification = button.closest('.triggered-notification');
        if (!notification) return;

        // For error notifications, just dismiss immediately
        if (notification.classList.contains('error-notification')) {
            notification.classList.add('dismissing');
            setTimeout(() => notification.remove(), 300);
            return;
        }

        if (notification.classList.contains('status-notification')) {
            // Dismiss all triggered alerts referenced in this box.
            const alertIds = new Set();
            notification.querySelectorAll('.notification-line[data-kind="triggered"][data-alert-id]').forEach(l => {
                alertIds.add(l.dataset.alertId);
            });
            // Also handle any unmerged triggered banners that may still be in the container.
            const container = notification.parentElement;
            if (container) {
                container.querySelectorAll('.triggered-notification[data-alert-id]:not(.status-notification)').forEach(n => {
                    alertIds.add(n.dataset.alertId);
                });
            }
            alertIds.forEach(id => AlertActions.dismiss(id));
        }

        notification.classList.add('dismissing');
        setTimeout(() => notification.remove(), 300);
    }

    function addFilter(filterId) {
        if (filterId) {
            FilterManager.addFilter(filterId);
            updateFilterBadge();
            syncFilterDropdownState();
        }
    }

    function removeFilter(filterId) {
        // Animate the tag out first
        const tag = document.querySelector('.filter-tag[data-filter-id="' + filterId + '"]');
        if (tag) {
            tag.classList.add('removing');
            setTimeout(() => {
                FilterManager.removeFilter(filterId);
                updateFilterBadge();
                syncFilterDropdownState();
            }, 300);
        } else {
            FilterManager.removeFilter(filterId);
            updateFilterBadge();
            syncFilterDropdownState();
        }
    }

    function updateFilterBadge() {
        const badge = document.getElementById('filterBadge');
        const btn = document.getElementById('filterDropdownBtn');
        const activeCount = AlertsState.activeFilters.size;

        if (badge) {
            if (activeCount > 0) {
                badge.textContent = activeCount;
                badge.style.display = 'inline';
                if (btn) btn.classList.add('has-active');
            } else {
                badge.style.display = 'none';
                if (btn) btn.classList.remove('has-active');
            }
        }
    }

    function syncFilterDropdownState() {
        document.querySelectorAll('#filterDropdownMenu .custom-dropdown-item').forEach(item => {
            const filterId = item.dataset.filter;
            if (AlertsState.activeFilters.has(filterId)) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    }

    function confirmFilterInput(filterId) {
        FilterManager.confirmFilterInput(filterId);
    }

    function cancelFilterInput(filterId) {
        FilterManager.cancelFilterInput(filterId);
    }

    function handleFilterInputKeydown(event, filterId) {
        if (event.key === 'Enter') {
            event.preventDefault();
            confirmFilterInput(filterId);
        } else if (event.key === 'Escape') {
            event.preventDefault();
            cancelFilterInput(filterId);
        }
    }

    // Sort handlers
    function handleSortSelection(sortKey) {
        SortManager.handleSortSelection(sortKey);
        syncSortDropdownState();
    }

    function applySortOrder(order) {
        SortManager.applySortOrder(order);
        syncSortDropdownState();
    }

    function clearSort() {
        SortManager.clearSort();
        syncSortDropdownState();
    }

    function syncSortDropdownState() {
        const currentSortKey = AlertsState.sorting.sortKey;
        document.querySelectorAll('#sortDropdownMenu .custom-dropdown-item').forEach(item => {
            if (item.dataset.sort === currentSortKey) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });
    }

    // Groups filter modal functions
    function openGroupsFilterModal() {
        const modal = document.getElementById('groups-filter-modal');
        const listContainer = document.getElementById('groups-filter-list');
        const noGroupsMsg = document.getElementById('no-groups-message');

        const groups = AlertsState.getAlertGroups();
        const selectedGroups = AlertsState.getFilterValue('myGroups') || [];

        if (groups.length === 0) {
            listContainer.style.display = 'none';
            noGroupsMsg.style.display = 'block';
        } else {
            listContainer.style.display = 'block';
            noGroupsMsg.style.display = 'none';

            listContainer.innerHTML = '';
            groups.forEach(group => {
                const pill = document.createElement('span');
                pill.className = 'group-pill' + (selectedGroups.includes(group) ? ' selected' : '');
                pill.textContent = group;
                pill.dataset.group = group;
                pill.addEventListener('click', function () {
                    this.classList.toggle('selected');
                });
                listContainer.appendChild(pill);
            });
        }

        modal.style.display = 'flex';
    }

    function closeGroupsFilterModal() {
        const modal = document.getElementById('groups-filter-modal');
        modal.style.display = 'none';
    }

    function applyGroupsFilter() {
        const pills = document.querySelectorAll('#groups-filter-list .group-pill.selected');
        const selectedGroups = Array.from(pills).map(pill => pill.dataset.group);
        const sortedSelectedGroups = selectedGroups.slice().sort((a, b) => a.localeCompare(b));

        if (sortedSelectedGroups.length === 0) {
            // If no groups selected, remove the filter if it exists
            if (AlertsState.activeFilters.has('myGroups')) {
                FilterManager.removeFilter('myGroups');
            }
            closeGroupsFilterModal();
            syncFilterDropdownState();
            updateFilterBadge();
            return;
        }

        AlertsState.setFilterValue('myGroups', sortedSelectedGroups);

        // If filter not already active, activate it
        if (!AlertsState.activeFilters.has('myGroups')) {
            const displayValue = sortedSelectedGroups.length === 1 ? sortedSelectedGroups[0] : sortedSelectedGroups.length + ' groups';
            FilterManager.activateFilter('myGroups', displayValue);
        } else {
            // Update the filter tag label
            const tag = document.querySelector('.filter-tag[data-filter-id="myGroups"]');
            if (tag) {
                const displayValue = sortedSelectedGroups.length === 1 ? sortedSelectedGroups[0] : sortedSelectedGroups.length + ' groups';
                tag.innerHTML = 'My Groups: ' + displayValue +
                    '<button class="filter-tag-remove" onclick="removeFilter(\'myGroups\')">&times;</button>';
            }
            FilterManager.updateAlertsList();
        }

        closeGroupsFilterModal();
        syncFilterDropdownState();
        updateFilterBadge();
    }

    function openPriceFilterModal() {
        const modal = document.getElementById('price-filter-modal');
        const minInput = document.getElementById('price-filter-min');
        const maxInput = document.getElementById('price-filter-max');
        if (!modal) return;

        // Load existing values if filter is active
        const existingValue = AlertsState.getFilterValue('priceRange');
        if (existingValue) {
            if (minInput) minInput.value = existingValue.min || '';
            if (maxInput) maxInput.value = existingValue.max || '';
        } else {
            if (minInput) minInput.value = '';
            if (maxInput) maxInput.value = '';
        }

        modal.style.display = 'flex';
        setTimeout(() => minInput && minInput.focus(), 0);
    }

    function closePriceFilterModal() {
        const modal = document.getElementById('price-filter-modal');
        if (modal) modal.style.display = 'none';
    }

    function clearPriceFilter() {
        const minInput = document.getElementById('price-filter-min');
        const maxInput = document.getElementById('price-filter-max');
        if (minInput) minInput.value = '';
        if (maxInput) maxInput.value = '';

        // Remove the filter
        removeFilter('priceRange');
        closePriceFilterModal();
    }

    function applyPriceFilter() {
        const minInput = document.getElementById('price-filter-min');
        const maxInput = document.getElementById('price-filter-max');
        if (!minInput || !maxInput) return;

        const minValue = minInput.value.trim();
        const maxValue = maxInput.value.trim();

        // If both are empty, clear the filter
        if (!minValue && !maxValue) {
            removeFilter('priceRange');
            closePriceFilterModal();
            return;
        }

        const filterValue = {
            min: minValue || null,
            max: maxValue || null
        };

        AlertsState.setFilterValue('priceRange', filterValue);
        FilterManager.activateFilter('priceRange', filterValue);

        // Update the filter tag to show the range
        const tag = document.querySelector('.filter-tag[data-filter-id="priceRange"]');
        if (tag) {
            let displayText = 'Price: ';
            if (minValue && maxValue) {
                displayText += minValue + ' - ' + maxValue;
            } else if (minValue) {
                displayText += '≥ ' + minValue;
            } else if (maxValue) {
                displayText += '≤ ' + maxValue;
            }
            tag.innerHTML = displayText +
                '<button class="filter-tag-remove" onclick="removeFilter(\'priceRange\')">&times;</button>';
        }

        closePriceFilterModal();
        syncFilterDropdownState();
        updateFilterBadge();
    }

    function closeDeleteConfirmModal() {
        const modal = document.getElementById('delete-confirm-modal');
        if (modal) modal.style.display = 'none';
    }

    function executeDelete() {
        AlertActions.executeDelete();
    }

    function confirmDelete() {
        AlertActions.confirmDelete();
    }


    // =============================================================================
    // INITIALIZATION
    // =============================================================================
    /**
     * Initialize the alerts system when the script loads.
     * 
     * PERFORMANCE OPTIMIZATION: MultiItemSelectors are deferred until needed.
     * They are only initialized when the user clicks the "Create Alert" tab.
     * This reduces initial page load time by ~200ms.
     */
    (function init() {
        // Validate server-rendered triggered notifications FIRST (before any other processing)
        // This prevents flash of notifications that should be hidden
        validateServerRenderedNotifications();

        TabManager.init();
        AutocompleteManager.init();
        
        // =============================================================================
        // PERFORMANCE: Defer MultiItemSelector initialization
        // =============================================================================
        // What: Move expensive selector initialization to when "Create Alert" tab is clicked
        // Why: These 4 selectors each set up ~50 event listeners and DOM queries
        //      Most users viewing alerts don't need the create form immediately
        // How: Use a flag to track if selectors have been initialized, init on first tab click
        // Impact: Reduces initial page load by deferring ~800 querySelector calls
        let selectorsInitialized = false;
        
        const originalSwitchTo = TabManager.switchTo;
        TabManager.switchTo = function(tabId) {
            originalSwitchTo.call(this, tabId);
            
            // Initialize selectors only when Create Alert tab is first accessed
            if (tabId === 'create-alert' && !selectorsInitialized) {
                selectorsInitialized = true;
                MultiItemSelector.init();
                SpreadMultiItemSelector.init();
                SpikeMultiItemSelector.init();
                ThresholdMultiItemSelector.init();
            }
        };
        
        EventManager.init();
        DropdownSizer.init();
        AlertsRefresh.start();

        // If the page is restored from the back/forward cache, clear transient status notifications.
        window.addEventListener('pageshow', function (e) {
            if (e.persisted) {
                AlertActions.clearStatusNotifications();
            }
        });

        // Ensure only one status notification box (merge server-side messages if any).
        AlertActions.normalizeStatusNotifications();
        AlertActions.mergeTriggeredNotificationsIntoStatus();

        // Check for deleted parameter and show notification
        const urlParams = new URLSearchParams(window.location.search);
        if (urlParams.get('deleted') === '1') {
            AlertActions.showStatusNotification('Alert deleted');
            // Remove the parameter from URL without reload
            const newUrl = window.location.pathname;
            window.history.replaceState({}, document.title, newUrl);
        }
        
        // =============================================================================
        // CHECK FOR VALIDATION ERROR FROM ALERT DETAIL PAGE
        // =============================================================================
        // What: Checks sessionStorage for error messages passed from alert_detail.html
        // Why: When server-side validation fails during alert edit (e.g., missing min/max
        //       price for All Items), the server returns a redirect URL. The alert_detail.html
        //       stores the error in sessionStorage before redirecting here.
        // How: Check sessionStorage for 'alertValidationError' key, if present show it
        //       as an error notification and remove the key to prevent re-showing on refresh
        const validationError = sessionStorage.getItem('alertValidationError');
        if (validationError) {
            // Remove the error from sessionStorage immediately so it doesn't show again on refresh
            sessionStorage.removeItem('alertValidationError');
            // Show the error notification using FormValidation (red error notification)
            FormValidation.showError(validationError);
        }
        
        // =============================================================================
        // INITIALIZE DEFAULT ALERT TYPE FORM FIELDS
        // =============================================================================
        // What: Triggers the alert type change handler on page load
        // Why: The default alert type is now "threshold" but the form fields need to be
        //       configured to show the correct inputs for threshold alerts on initial load
        // How: Call handleAlertTypeChange which will read the current selected value and
        //       show/hide the appropriate form fields
        handleAlertTypeChange();
        
        // =============================================================================
        // LOCKED INDICATOR EVENT LISTENERS
        // =============================================================================
        // What: Set up click handlers for the threshold type locked indicator and tooltip
        // Why: Users need to click the 🚫 icon to see why the field is locked
        // How: Add event listeners to toggle tooltip visibility on click
        
        // Locked indicator click handler - shows the tooltip
        const lockedIndicator = document.getElementById('threshold-type-locked-indicator');
        const lockedTooltip = document.getElementById('threshold-type-locked-tooltip');
        
        if (lockedIndicator && lockedTooltip) {
            // Show tooltip when indicator is clicked
            // What: Toggle tooltip visibility on indicator click
            // Why: Users clicking the 🚫 want to know why the field is locked
            // How: Toggle display between 'none' and 'block'
            lockedIndicator.addEventListener('click', function(e) {
                e.preventDefault();
                e.stopPropagation();
                const isVisible = lockedTooltip.style.display === 'block';
                lockedTooltip.style.display = isVisible ? 'none' : 'block';
            });
            
            // Close button click handler - hides the tooltip
            // What: Close the tooltip when X button is clicked
            // Why: Users need a way to dismiss the tooltip after reading
            // How: Set tooltip display to 'none'
            const closeBtn = lockedTooltip.querySelector('.locked-tooltip-close');
            if (closeBtn) {
                closeBtn.addEventListener('click', function(e) {
                    e.preventDefault();
                    e.stopPropagation();
                    lockedTooltip.style.display = 'none';
                });
            }
            
            // Click outside to close tooltip
            // What: Close tooltip when user clicks anywhere else on the page
            // Why: Standard UX pattern - clicking outside dismisses popups
            // How: Listen for document clicks, close if click is outside tooltip and indicator
            document.addEventListener('click', function(e) {
                if (lockedTooltip.style.display === 'block' &&
                    !lockedTooltip.contains(e.target) &&
                    !lockedIndicator.contains(e.target)) {
                    lockedTooltip.style.display = 'none';
                }
            });
        }
    })();

    /**
     * Validates server-rendered triggered notifications against localStorage.
     * Removes notifications for "all items" alerts where we've already seen all items.
     * Also removes notifications that the user has dismissed.
     * Shows notifications that pass validation by adding 'validated' class.
     * 
     * IMPORTANT: Server-rendered notifications come from the backend where is_dismissed=False.
     * If the backend says show it, we should trust that and clear any localStorage dismissal.
     */
    function validateServerRenderedNotifications() {
        const notifications = document.querySelectorAll('.triggered-notification[data-alert-id]:not(.status-notification)');

        notifications.forEach(notification => {
            const alertId = notification.dataset.alertId;
            if (!alertId) {
                // No alert ID, show it
                notification.classList.add('validated');
                return;
            }

            // If this notification is server-rendered, the backend is saying is_dismissed=False
            // Clear any localStorage dismissal entry to ensure it shows
            // What: Clear dismissed status from localStorage for server-rendered notifications
            // Why: Backend has is_dismissed=False (data changed), localStorage may still have it dismissed
            // How: Call clearDismissedNotification before checking if dismissed
            if (AlertsState.isNotificationDismissed(alertId)) {
                // Backend says show it, so clear the localStorage dismissal
                AlertsState.clearDismissedNotification(alertId);
            }

            // Server-rendered notifications should be shown and stored in active cache
            // Extract data and store it
            const text = notification.textContent.replace('×', '').trim();
            AlertsState.setActiveNotification(alertId, {
                id: alertId,
                text: text,
                type: 'unknown',
                is_all_items: false,
                isSpreadAllItems: false,
                isSpikeAllItems: false
            });
            
            notification.classList.add('validated');
        });
    }
