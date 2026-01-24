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
     */
    (function init() {
        // Validate server-rendered triggered notifications FIRST (before any other processing)
        // This prevents flash of notifications that should be hidden
        validateServerRenderedNotifications();

        TabManager.init();
        AutocompleteManager.init();
        MultiItemSelector.init();
        SpreadMultiItemSelector.init();  // Initialize spread multi-item selector
        SpikeMultiItemSelector.init();   // Initialize spike multi-item selector
        ThresholdMultiItemSelector.init();  // Initialize threshold multi-item selector
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
</script>

<!-- Alert Help Modal -->
<div class="alert-help-modal-overlay" id="alertHelpModal">
    <div class="alert-help-modal">
        <div class="alert-help-modal-header">
            <h2>
                <svg viewBox="0 0 20 20" fill="currentColor" width="24" height="24">
                    <path fill-rule="evenodd"
                        d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-8-3a1 1 0 00-.867.5 1 1 0 11-1.731-1A3 3 0 0113 8a3.001 3.001 0 01-2 2.83V11a1 1 0 11-2 0v-1a1 1 0 011-1 1 1 0 100-2zm0 8a1 1 0 100-2 1 1 0 000 2z"
                        clip-rule="evenodd" />
                </svg>
                Understanding Alert Types
            </h2>
            <button class="alert-help-modal-close" onclick="closeAlertHelpModal()">&times;</button>
        </div>
        <div class="alert-help-modal-body">
            <div class="alert-help-tabs">
                <button class="alert-help-tab" data-help-tab="spread">Spread</button>
                <button class="alert-help-tab" data-help-tab="spike">Spike</button>
                <button class="alert-help-tab" data-help-tab="sustained">Sustained</button>
                <button class="alert-help-tab" data-help-tab="threshold">Threshold</button>
            </div>
            <div class="alert-help-content">
                <!-- Spread Alert -->
                <div class="alert-help-section" data-help-section="spread">
                    <h3>
                        Spread Alert
                        <span class="alert-type-badge spread">Flip Margin</span>
                    </h3>
                    <p class="subtitle">Get notified when the buy/sell margin (spread) exceeds a percentage. Essential
                        for finding profitable flipping opportunities.</p>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                                    clip-rule="evenodd" />
                            </svg>
                            How It Works
                        </h4>
                        <p>The <strong>spread</strong> is the percentage difference between the high price (what buyers
                            pay) and the low price (what sellers receive). A higher spread means more potential profit
                            per flip.</p>
                        <p style="margin-top: 12px;"><strong>Formula:</strong> Spread % = ((High Price - Low Price) /
                            Low Price) × 100</p>
                        
                        <div class="input-fields-guide" style="margin-top: 16px;">
                            <h5 style="font-size: 13px; font-weight: 600; margin-bottom: 10px; color: var(--text);">📝 Input Fields Explained:</h5>
                            <ul>
                                <li><strong>Apply To:</strong> Choose what items to monitor:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Specific Item(s)</em> - Select one or more specific items you want to track. Great for monitoring your favorite flip items.</li>
                                        <li><em>All Items</em> - Scan the entire Grand Exchange for any item meeting your spread criteria. Requires price filters to avoid noise.</li>
                                    </ul>
                                </li>
                                <li><strong>Items</strong> (when Specific Item(s) selected): Type to search for items. Click an item to add it to your list. Click the dropdown arrow to see/remove selected items. You can add multiple items to monitor simultaneously.</li>
                                <li><strong>Percentage (%):</strong> The minimum spread percentage that will trigger the alert. For example, entering "5" means you'll be notified when an item has a 5%+ margin between buy and sell prices.</li>
                                <li><strong>Minimum Price</strong> (when All Items selected): Only monitor items worth at least this much GP. Filters out low-value junk items. Enter raw number (e.g., 1000000 for 1M).</li>
                                <li><strong>Maximum Price</strong> (when All Items selected): Only monitor items worth at most this much GP. Useful for staying within your cash stack limits.</li>
                            </ul>
                        </div>
                    </div>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                                <path fill-rule="evenodd"
                                    d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"
                                    clip-rule="evenodd" />
                            </svg>
                            When To Use
                        </h4>
                        <ul>
                            <li>Finding items worth flipping across the entire GE</li>
                            <li>Monitoring your favorite flip items for optimal margins</li>
                            <li>Setting up "All Items" alerts to discover new opportunities</li>
                        </ul>
                    </div>

                    <div class="example-scenario">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path
                                    d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
                            </svg>
                            Example Scenario
                        </h4>
                        <p>Set an "All Items" spread alert for 5% with a minimum price of 1,000,000 gp. You'll be
                            notified whenever any item worth 1M+ has a 5%+ margin - perfect for finding high-value
                            flips!</p>
                    </div>

                    <div class="recommended-values">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                    clip-rule="evenodd" />
                            </svg>
                            Recommended Starting Values
                        </h4>
                        <div class="value-grid">
                            <div class="recommended-value">
                                <div class="label">Spread Percentage</div>
                                <div class="value">3-5% for high-value items</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Minimum Price</div>
                                <div class="value">500,000 - 1,000,000 gp</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Maximum Price</div>
                                <div class="value">Based on your cash stack</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Spike Alert -->
                <div class="alert-help-section" data-help-section="spike">
                    <h3>
                        Spike Alert
                        <span class="alert-type-badge spike">Rapid Change</span>
                    </h3>
                    <p class="subtitle">Get notified when an item's price changes rapidly within a time window. Catch
                        sudden market movements as they happen.</p>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                                    clip-rule="evenodd" />
                            </svg>
                            How It Works
                        </h4>
                        <p>Spike alerts use a <strong>rolling time window</strong> to compare the current price against
                            the price from exactly <em>[time frame]</em> ago. If the price change exceeds your threshold,
                            you'll be notified.</p>
                        
                        <div class="input-fields-guide" style="margin-top: 16px;">
                            <h5 style="font-size: 13px; font-weight: 600; margin-bottom: 10px; color: var(--text);">📝 Input Fields Explained:</h5>
                            <ul>
                                <li><strong>Apply To:</strong> Choose what items to monitor:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Specific Item(s)</em> - Select one or more specific items to track for price spikes. The multi-item selector handles both single and multiple items.</li>
                                        <li><em>All Items</em> - Scan the entire Grand Exchange for any item spiking. Requires price filters to avoid noise from low-value items.</li>
                                    </ul>
                                </li>
                                <li><strong>Items</strong> (when Specific Item(s) selected): Type to search for items. Click an item to add it. Click the dropdown arrow to see/remove selected items. Monitor multiple items simultaneously.</li>
                                <li><strong>Percentage (%):</strong> The minimum price change percentage that triggers the alert. For example, "10" means a 10% price change within your time frame will trigger. Enter values between 0.001 and 100.</li>
                                <li><strong>Time Frame (minutes):</strong> The rolling window for comparison. The alert compares the current price to the price from exactly this many minutes ago. For example, "60" compares current price to the price 1 hour ago.</li>
                                <li><strong>Direction:</strong> Which price movements to track:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Both</em> - Alert on both price increases AND decreases. Best for catching all market movements.</li>
                                        <li><em>Up</em> - Only alert when price increases by the percentage. Good for catching pumps.</li>
                                        <li><em>Down</em> - Only alert when price decreases by the percentage. Good for catching crashes/buying opportunities.</li>
                                    </ul>
                                </li>
                                <li><strong>Minimum Price</strong> (when All Items selected): Only monitor items worth at least this much GP. Filters out cheap items that spike frequently due to low volume.</li>
                                <li><strong>Maximum Price</strong> (when All Items selected): Only monitor items worth at most this much GP. Useful for filtering to your budget range.</li>
                            </ul>
                        </div>
                        
                        <div class="alert-help-note" style="margin-top: 12px; padding: 10px; background: rgba(255, 193, 7, 0.1); border-radius: 6px; border-left: 3px solid #ffc107;">
                            <strong>⏳ Warmup Period:</strong> The alert won't trigger until enough time has passed to establish a baseline.
                            For example, a 10-minute spike alert needs 10 minutes of price data before it can make valid comparisons.
                        </div>
                    </div>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                                <path fill-rule="evenodd"
                                    d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"
                                    clip-rule="evenodd" />
                            </svg>
                            When To Use
                        </h4>
                        <ul>
                            <li>Catching items that spike after game updates or news</li>
                            <li>Detecting crash opportunities to buy low</li>
                            <li>Monitoring volatile items for trading opportunities</li>
                            <li>Setting "All Items" to find any item spiking in the market</li>
                            <li>Watching a curated list of items with "Specific Item(s)" mode</li>
                        </ul>
                    </div>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
                                    clip-rule="evenodd" />
                            </svg>
                            Multi-Item Behavior
                        </h4>
                        <p>When monitoring <strong>multiple specific items</strong>:</p>
                        <ul>
                            <li><strong>Triggers:</strong> When <em>any</em> item exceeds the threshold</li>
                            <li><strong>Re-triggers:</strong> When the triggered items or their percentages change</li>
                            <li><strong>No spam:</strong> Won't re-notify if the same items have the same values</li>
                            <li><strong>Deactivates:</strong> Only when <em>all</em> items are simultaneously within the threshold</li>
                        </ul>
                    </div>

                    <div class="example-scenario">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path
                                    d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
                            </svg>
                            Example Scenario
                        </h4>
                        <p>Set an "All Items" spike alert for 10% within 60 minutes, direction "Up", with minimum price
                            100,000 gp. When any item worth 100k+ jumps 10% in an hour, you'll be the first to know!</p>
                    </div>

                    <div class="recommended-values">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                    clip-rule="evenodd" />
                            </svg>
                            Recommended Starting Values
                        </h4>
                        <div class="value-grid">
                            <div class="recommended-value">
                                <div class="label">Percentage Change</div>
                                <div class="value">5-10%</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Time Frame</div>
                                <div class="value">30-60 minutes</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Direction</div>
                                <div class="value">Both (to catch all movements)</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Minimum Price</div>
                                <div class="value">100,000+ gp</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Sustained Move Alert -->
                <div class="alert-help-section" data-help-section="sustained">
                    <h3>
                        Sustained Move Alert
                        <span class="alert-type-badge sustained">Trend Detection</span>
                    </h3>
                    <p class="subtitle">Get notified when an item shows consistent price movement in one direction.
                        Detect emerging trends before they become obvious.</p>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                                    clip-rule="evenodd" />
                            </svg>
                            How It Works
                        </h4>
                        <p>Unlike spike alerts that catch sudden moves, sustained move alerts detect <strong>consistent
                                trends</strong>. They look for multiple consecutive price movements in the same
                            direction, filtering out noise to find real trends.</p>
                        
                        <div class="input-fields-guide" style="margin-top: 16px;">
                            <h5 style="font-size: 13px; font-weight: 600; margin-bottom: 10px; color: var(--text);">📝 Input Fields Explained:</h5>
                            <ul>
                                <li><strong>Apply To:</strong> Choose what items to monitor:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Specific Item(s)</em> - Select one or more specific items to track for sustained price trends.</li>
                                        <li><em>All Items</em> - Scan the entire Grand Exchange for any item showing sustained movement. Use with price filters.</li>
                                    </ul>
                                </li>
                                <li><strong>Items</strong> (when Specific Item(s) selected): Type to search for items. Click to add to your watchlist. Click the dropdown arrow to see/remove selected items.</li>
                                <li><strong>Min Consecutive Moves:</strong> How many consecutive price updates must move in the same direction to trigger. For example, "5" means 5 data points in a row must all be going up (or all going down). Minimum value is 2.</li>
                                <li><strong>Min Move %:</strong> The minimum percentage change for each individual price movement to count. For example, "0.5" means each move must be at least 0.5% - smaller changes are ignored as noise. Helps filter out tiny fluctuations.</li>
                                <li><strong>Direction:</strong> Which trends to track:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Both</em> - Alert on both upward AND downward trends.</li>
                                        <li><em>Up</em> - Only alert when price is trending upward consistently.</li>
                                        <li><em>Down</em> - Only alert when price is trending downward consistently.</li>
                                    </ul>
                                </li>
                                <li><strong>Min Volume:</strong> Only consider items with at least this many trades. Filters out low-activity items where price movements may be unreliable.</li>
                                <li><strong>Volatility Buffer (N):</strong> The rolling buffer size used to calculate average volatility. A larger buffer (e.g., 20) means smoother volatility estimates over more data points.</li>
                                <li><strong>Volatility Multiplier (K):</strong> The total sustained move must exceed K × average volatility to trigger. Higher values (e.g., 1.5-2.0) filter out normal market noise by requiring the trend to be significantly larger than typical price swings.</li>
                                <li><strong>Market Pressure:</strong> Optional filter based on buy/sell pressure:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>No Pressure Filter</em> - Don't filter by market pressure.</li>
                                        <li><em>Weak+</em> - Requires any detected buying/selling pressure.</li>
                                        <li><em>Moderate+</em> - Requires pressure detected within 5 minutes.</li>
                                        <li><em>Strong</em> - Requires pressure detected within 1 minute.</li>
                                    </ul>
                                </li>
                                <li><strong>Min Spread % for Pressure:</strong> Minimum high-low spread percentage required to confirm market pressure. Higher values ensure the spread is meaningful.</li>
                            </ul>
                        </div>
                    </div>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                                <path fill-rule="evenodd"
                                    d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"
                                    clip-rule="evenodd" />
                            </svg>
                            When To Use
                        </h4>
                        <ul>
                            <li>Detecting items being manipulated or merched</li>
                            <li>Finding items trending up before a big spike</li>
                            <li>Catching items in decline before they crash further</li>
                            <li>Identifying genuine market trends vs random noise</li>
                        </ul>
                    </div>

                    <div class="example-scenario">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path
                                    d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
                            </svg>
                            Example Scenario
                        </h4>
                        <p>Set a sustained move alert for "All Items" with 5 consecutive moves, 0.5% minimum move,
                            direction "Up". When any item moves up 5 times in a row, each by at least 0.5%, you'll catch
                            the trend early!</p>
                    </div>

                    <div class="recommended-values">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                    clip-rule="evenodd" />
                            </svg>
                            Recommended Starting Values
                        </h4>
                        <div class="value-grid">
                            <div class="recommended-value">
                                <div class="label">Consecutive Moves</div>
                                <div class="value">4-6 moves</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Min Move %</div>
                                <div class="value">0.3-0.5%</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Direction</div>
                                <div class="value">Both (catch all trends)</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Min Volume</div>
                                <div class="value">100+ (filters low-trade items)</div>
                            </div>
                        </div>
                    </div>
                </div>

                <!-- Threshold Alert -->
                <div class="alert-help-section" data-help-section="threshold">
                    <h3>
                        Threshold Alert
                        <span class="alert-type-badge threshold">Price Change</span>
                    </h3>
                    <p class="subtitle">Get notified when an item's price changes by a specific percentage or GP value from its baseline.
                        Flexible monitoring for price movements in either direction.</p>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z"
                                    clip-rule="evenodd" />
                            </svg>
                            How It Works
                        </h4>
                        <p>Threshold alerts compare the current price against a <strong>baseline price</strong> (captured when the alert is created), or when price crosses over a specific value you specify. When tracking more than one item, only percentage thresholds are available.
                            When the price changes by your specified percentage or GP amount, you'll be notified. Unlike spike alerts that use
                            rolling time windows, threshold alerts use a fixed reference point.</p>
                        
                        <div class="input-fields-guide" style="margin-top: 16px;">
                            <h5 style="font-size: 13px; font-weight: 600; margin-bottom: 10px; color: var(--text);">📝 Input Fields Explained:</h5>
                            <ul>
                                <li><strong>Apply To:</strong> Choose what items to monitor:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Specific Item(s)</em> - Select one or more specific items. Best for tracking items you own or want to buy.</li>
                                        <li><em>All Items</em> - Scan the entire Grand Exchange. The threshold type is automatically locked to "Percentage" for this mode. Use with price filters.</li>
                                    </ul>
                                </li>
                                <li><strong>Items</strong> (when Specific Item(s) selected): Type to search for items. Click to add. Click the dropdown arrow to see/remove selected items. Each item gets its own baseline price when the alert is created.</li>
                                <li><strong>Direction:</strong> Which price movements to track:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Up</em> - Only alert when price increases above baseline by the threshold amount.</li>
                                        <li><em>Down</em> - Only alert when price decreases below baseline by the threshold amount.</li>
                                    </ul>
                                </li>
                                <li><strong>Threshold Type:</strong> How to measure the price change:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>Percentage</em> - Alert triggers when price changes by X% with respect to its value at alert creation time. For example, "10" means a 10% change from baseline. Best for comparing items of different values.</li>
                                        <li><em>Value (GP)</em> - Alert triggers when price crosses above or below a specified value.</li>
                                    </ul>
                                </li>
                                <li><strong>Threshold:</strong> The amount of change required to trigger the alert. Enter a number between 0.01 and 100 for percentages, or any GP value for Value mode. For percentage, enter "10" for 10%, not "0.10".</li>
                                <li><strong>Reference Price:</strong> Which price to monitor:
                                    <ul style="margin-top: 4px; margin-left: 16px;">
                                        <li><em>High (Instant Buy)</em> - The price you pay to buy instantly. Good for tracking buying opportunities.</li>
                                        <li><em>Low (Instant Sell)</em> - The price you receive when selling instantly. Good for tracking when to sell.</li>
                                        <li><em>Average</em> - The midpoint between high and low. Good for general price tracking.</li>
                                    </ul>
                                </li>
                                <li><strong>Minimum Price</strong> (when All Items selected): Only monitor items worth at least this much GP. Filters out low-value items.</li>
                                <li><strong>Maximum Price</strong> (when All Items selected): Only monitor items worth at most this much GP. Useful for staying within budget.</li>
                            </ul>
                        </div>
                        
                        <div class="alert-help-note" style="margin-top: 12px; padding: 10px; background: rgba(255, 193, 7, 0.1); border-radius: 6px; border-left: 3px solid #ffc107;">
                            <strong>📊 Baseline Price:</strong> When you create a threshold alert, the system captures the current price as the "baseline".
                            All future comparisons are made against this baseline, not a rolling window. You can see the baseline price on the alert detail page.
                        </div>
                    </div>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path d="M9 2a1 1 0 000 2h2a1 1 0 100-2H9z" />
                                <path fill-rule="evenodd"
                                    d="M4 5a2 2 0 012-2 3 3 0 003 3h2a3 3 0 003-3 2 2 0 012 2v11a2 2 0 01-2 2H6a2 2 0 01-2-2V5zm3 4a1 1 0 000 2h.01a1 1 0 100-2H7zm3 0a1 1 0 000 2h3a1 1 0 100-2h-3zm-3 4a1 1 0 100 2h.01a1 1 0 100-2H7zm3 0a1 1 0 100 2h3a1 1 0 100-2h-3z"
                                    clip-rule="evenodd" />
                            </svg>
                            When To Use
                        </h4>
                        <ul>
                            <li>You bought an item and want to know when it rises/falls by a specific percentage</li>
                            <li>Monitoring portfolio items for significant price changes</li>
                            <li>Setting price-based exit or entry triggers</li>
                            <li>Tracking items with specific GP profit targets (single item, Value mode)</li>
                            <li>Scanning all items for significant market movements</li>
                        </ul>
                    </div>

                    <div class="alert-help-card">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M3 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm0 4a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1z"
                                    clip-rule="evenodd" />
                            </svg>
                            Threshold vs Spike Alerts
                        </h4>
                        <p>Understanding when to use each:</p>
                        <ul>
                            <li><strong>Threshold:</strong> Uses a <em>fixed baseline</em> (price when created). Good for "notify me when this item is 10% higher than when I bought it".</li>
                            <li><strong>Spike:</strong> Uses a <em>rolling time window</em>. Good for "notify me when this item moves 10% in the last hour". Resets continuously.</li>
                        </ul>
                    </div>

                    <div class="example-scenario">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path
                                    d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.464 5.05l-.707-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1h4v1a2 2 0 11-4 0zM12 14c.015-.34.208-.646.477-.859a4 4 0 10-4.954 0c.27.213.462.519.476.859h4.002z" />
                            </svg>
                            Example Scenario
                        </h4>
                        <p>You just bought an Armadyl Godsword for 15M and want to sell when it goes up 15%. Create a threshold alert with
                            Direction "Up", Threshold Type "Percentage", Threshold "15", and Reference "High". When the high price rises 15%
                            above your baseline (to ~17.25M), you'll be notified to sell!</p>
                    </div>

                    <div class="recommended-values">
                        <h4>
                            <svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
                                <path fill-rule="evenodd"
                                    d="M6.267 3.455a3.066 3.066 0 001.745-.723 3.066 3.066 0 013.976 0 3.066 3.066 0 001.745.723 3.066 3.066 0 012.812 2.812c.051.643.304 1.254.723 1.745a3.066 3.066 0 010 3.976 3.066 3.066 0 00-.723 1.745 3.066 3.066 0 01-2.812 2.812 3.066 3.066 0 00-1.745.723 3.066 3.066 0 01-3.976 0 3.066 3.066 0 00-1.745-.723 3.066 3.066 0 01-2.812-2.812 3.066 3.066 0 00-.723-1.745 3.066 3.066 0 010-3.976 3.066 3.066 0 00.723-1.745 3.066 3.066 0 012.812-2.812zm7.44 5.252a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z"
                                    clip-rule="evenodd" />
                            </svg>
                            Recommended Starting Values
                        </h4>
                        <div class="value-grid">
                            <div class="recommended-value">
                                <div class="label">Threshold Type</div>
                                <div class="value">Percentage (more flexible)</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Threshold</div>
                                <div class="value">5-15% for most items</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Direction</div>
                                <div class="value">Up (for selling) / Down (for buying)</div>
                            </div>
                            <div class="recommended-value">
                                <div class="label">Reference Price</div>
                                <div class="value">High for selling, Low for buying</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
