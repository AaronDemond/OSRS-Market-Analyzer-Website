    // ALERT ACTIONS
    // =============================================================================
    /**
     * Handles user actions on alerts (dismiss, delete, save).
     */
    const AlertActions = {
        /**
         * Handles selection from the actions dropdown.
         */
        handleAction(action) {
            if (action === 'delete') {
                this.confirmDelete();
            } else if (action === 'group') {
                GroupManager.open();
            }
        },

        /**
         * Dismisses a triggered alert notification.
         * 
         * What: Handles the full dismiss flow - updates localStorage, removes UI, calls API.
         * Why: User clicked X on a notification and wants it dismissed.
         * How: 
         *   1. Mark dismissed in localStorage (client-side persistence)
         *   2. Remove from active notifications cache
         *   3. Animate and remove the UI element
         *   4. Call API to persist is_dismissed=True to database
         * 
         * DEBUG: Added logging to trace dismiss flow.
         */
        async dismiss(alertId) {
            console.log('[DISMISS DEBUG] AlertActions.dismiss called with alertId:', alertId);
            
            // Mark as dismissed in localStorage so it stays dismissed across refreshes
            console.log('[DISMISS DEBUG] Marking as dismissed in localStorage...');
            AlertsState.dismissNotification(alertId);
            
            // Also remove from active notifications cache
            console.log('[DISMISS DEBUG] Removing from active notifications cache...');
            AlertsState.removeActiveNotification(alertId);
            
            // Animate out immediately for responsive feedback
            const banner = document.querySelector('.triggered-notification[data-alert-id="' + alertId + '"]');
            console.log('[DISMISS DEBUG] Found banner element:', banner);
            if (banner) {
                banner.classList.add('dismissing');
                setTimeout(() => banner.remove(), 300);
            }

            const line = document.querySelector('.status-notification .notification-line[data-kind="triggered"][data-alert-id="' + alertId + '"]');
            console.log('[DISMISS DEBUG] Found notification line:', line);
            if (line) {
                const box = line.closest('.status-notification');
                line.remove();
                if (box) {
                    const hasLines = box.querySelector('.notification-line');
                    // If no lines remain (status or triggered), remove box.
                    if (!hasLines) {
                        box.classList.add('dismissing');
                        setTimeout(() => box.remove(), 300);
                    }
                }
            }

            console.log('[DISMISS DEBUG] Calling AlertsAPI.dismissAlert...');
            await AlertsAPI.dismissAlert(alertId);
            console.log('[DISMISS DEBUG] API call completed');
        },

        /**
         * Confirms deletion of selected alerts.
         * Opens the delete confirmation modal instead of browser confirm.
         */
        confirmDelete() {
            const selectedItems = [];
            const selectedIds = [];

            document.querySelectorAll('.alert-checkbox:checked').forEach(cb => {
                const alertItem = cb.closest('.alert-item');
                if (alertItem) {
                    selectedItems.push(alertItem);
                    selectedIds.push(alertItem.dataset.alertId);
                }
            });

            if (selectedIds.length === 0) {
                AlertActions.showErrorNotification('Please select at least one alert to delete.');
                return;
            }

            // Store selected items and IDs for later use
            this.pendingDeleteItems = selectedItems;
            this.pendingDeleteIds = selectedIds;

            // Update modal message
            const message = document.getElementById('delete-confirm-message');
            if (message) {
                const count = selectedIds.length;
                message.textContent = 'Are you sure you want to delete ' + count + ' selected alert' + (count > 1 ? 's' : '') + '?';
            }

            // Show modal
            document.getElementById('delete-confirm-modal').style.display = 'flex';
        },

        /**
         * Executes the delete after modal confirmation.
         */
        async executeDelete() {
            const selectedItems = this.pendingDeleteItems || [];
            const selectedIds = this.pendingDeleteIds || [];

            if (selectedIds.length === 0) {
                closeDeleteConfirmModal();
                return;
            }

            // Close modal first
            closeDeleteConfirmModal();

            // Animate items out
            selectedItems.forEach(item => {
                item.classList.add('deleting');
            });

            // Wait for animation to complete (300ms matches CSS transition)
            await new Promise(resolve => setTimeout(resolve, 300));

            // Call API to delete
            const success = await AlertsAPI.deleteAlerts(selectedIds);
            if (success) {
                this.clearSelections();
                // Show status notification
                this.showStatusNotification('Alert' + (selectedIds.length > 1 ? 's' : '') + ' deleted');
                await AlertsRefresh.refresh();
            } else {
                selectedItems.forEach(item => item.classList.remove('deleting'));
            }

            // Clear pending state
            this.pendingDeleteItems = null;
            this.pendingDeleteIds = null;
        },

        /**
         * Clears any selected checkboxes.
         */
        clearSelections() {
            document.querySelectorAll('.alert-checkbox').forEach(cb => cb.checked = false);
        },

        /**
         * Shows a status notification at the top of the alerts pane.
         * 
         * What: Creates and displays a dismissible status message
         * Why: Provides user feedback for actions like delete
         * How: Inserts notification HTML into triggered-notifications container
         */
        clearStatusNotifications() {
            const container = document.getElementById('triggered-notifications');
            if (!container) return;

            container.querySelectorAll('.status-notification').forEach(box => {
                // Remove only status lines; keep triggered lines.
                box.querySelectorAll('.notification-line[data-kind="status"]').forEach(l => l.remove());

                // Remove legacy plain text (server messages) and <br> (treat as status).
                Array.from(box.childNodes).forEach(node => {
                    if (node.nodeType === 3 && node.textContent.trim()) node.remove();
                    if (node.nodeType === 1 && node.tagName === 'BR') node.remove();
                });

                const hasTriggered = box.querySelector('.notification-line[data-kind="triggered"]');
                if (!hasTriggered) {
                    box.remove();
                }
            });
        },

        normalizeStatusNotifications() {
            const container = document.getElementById('triggered-notifications');
            if (!container) return;

            const existingAll = container.querySelectorAll('.status-notification');
            if (existingAll.length === 0) return;

            const toStatusLine = (box, message) => {
                const btn = box.querySelector('.dismiss-btn');
                const line = document.createElement('div');
                line.className = 'notification-line';
                line.dataset.kind = 'status';
                const span = document.createElement('span');
                span.textContent = message;
                line.appendChild(span);
                if (btn) box.insertBefore(line, btn);
                else box.appendChild(line);
            };

            // Convert any legacy plain-text status messages into status lines.
            existingAll.forEach(box => {
                const plainText = Array.from(box.childNodes)
                    .filter(node => !(node.nodeType === 1 && node.classList && node.classList.contains('dismiss-btn')))
                    .filter(node => !(node.nodeType === 1 && node.classList && node.classList.contains('notification-line')))
                    .filter(node => node.nodeType === 3 || (node.nodeType === 1 && node.tagName === 'BR'))
                    .map(node => (node.textContent || '').trim())
                    .filter(Boolean)
                    .join(' ');

                // Remove those legacy nodes.
                Array.from(box.childNodes).forEach(node => {
                    const isBtn = node.nodeType === 1 && node.classList && node.classList.contains('dismiss-btn');
                    const isLine = node.nodeType === 1 && node.classList && node.classList.contains('notification-line');
                    if (isBtn || isLine) return;
                    if (node.nodeType === 3 || (node.nodeType === 1 && node.tagName === 'BR')) {
                        node.remove();
                    }
                });

                if (plainText) {
                    toStatusLine(box, plainText);
                }
            });

            if (existingAll.length <= 1) return;

            const first = existingAll[0];
            const firstBtn = first.querySelector('.dismiss-btn');

            for (let i = 1; i < existingAll.length; i++) {
                const n = existingAll[i];
                // Move status lines into the first box.
                n.querySelectorAll('.notification-line[data-kind="status"]').forEach(line => {
                    if (firstBtn) first.insertBefore(line.cloneNode(true), firstBtn);
                    else first.appendChild(line.cloneNode(true));
                });
                n.remove();
            }
        },

        mergeTriggeredNotificationsIntoStatus() {
            const container = document.getElementById('triggered-notifications');
            if (!container) return;

            this.normalizeStatusNotifications();

            const triggered = Array.from(container.querySelectorAll('.triggered-notification:not(.status-notification)'));
            if (triggered.length === 0) return;

            let statusBox = container.querySelector('.status-notification');
            if (!statusBox) {
                statusBox = document.createElement('div');
                statusBox.className = 'triggered-notification status-notification';

                const btn = document.createElement('button');
                btn.className = 'dismiss-btn';
                btn.innerHTML = '&times;';
                btn.setAttribute('onclick', 'dismissStatusNotification(this)');
                statusBox.appendChild(btn);

                container.insertBefore(statusBox, container.firstChild);
            }

            const globalBtn = statusBox.querySelector('.dismiss-btn');

            triggered.forEach(n => {
                const alertId = n.dataset.alertId;
                const span = n.querySelector('span');

                const line = document.createElement('div');
                line.className = 'notification-line';
                line.dataset.kind = 'triggered';
                if (alertId) line.dataset.alertId = alertId;

                if (span) {
                    line.appendChild(span.cloneNode(true));
                } else {
                    const msg = Array.from(n.childNodes)
                        .filter(node => !(node.nodeType === 1 && node.classList && node.classList.contains('dismiss-btn')))
                        .map(node => (node.textContent || '').trim())
                        .filter(Boolean)
                        .join(' ');
                    const s = document.createElement('span');
                    s.textContent = msg;
                    line.appendChild(s);
                }


                if (globalBtn) statusBox.insertBefore(line, globalBtn);
                else statusBox.appendChild(line);

                n.remove();
            });
        },

        showStatusNotification(message) {
            const container = document.getElementById('triggered-notifications');
            if (!container) return;

            this.normalizeStatusNotifications();

            let statusBox = container.querySelector('.status-notification');
            if (!statusBox) {
                statusBox = document.createElement('div');
                statusBox.className = 'triggered-notification status-notification';

                const btn = document.createElement('button');
                btn.className = 'dismiss-btn';
                btn.innerHTML = '&times;';
                btn.setAttribute('onclick', 'dismissStatusNotification(this)');
                statusBox.appendChild(btn);

                container.insertBefore(statusBox, container.firstChild);
            }

            const globalBtn = statusBox.querySelector('.dismiss-btn');

            const line = document.createElement('div');
            line.className = 'notification-line';
            line.dataset.kind = 'status';
            const span = document.createElement('span');
            span.textContent = message;
            line.appendChild(span);

            if (globalBtn) statusBox.insertBefore(line, globalBtn);
            else statusBox.appendChild(line);

            // Keep triggered + status in one visible box.
            this.mergeTriggeredNotificationsIntoStatus();
        },

        /**
         * Shows an error notification above the actions area.
         * @param {string} message - The error message to display
         */
        showErrorNotification(message) {
            const actionsWrapper = document.querySelector('.alert-actions-wrapper');
            if (!actionsWrapper) return;

            // Pause refresh while error notification is shown
            AlertsRefresh.errorNotificationActive = true;

            // Find or create error container above actions
            let errorContainer = actionsWrapper.querySelector('.actions-error-container');
            if (!errorContainer) {
                errorContainer = document.createElement('div');
                errorContainer.className = 'actions-error-container';
                actionsWrapper.insertBefore(errorContainer, actionsWrapper.firstChild);
            }

            // Remove any existing error notifications
            errorContainer.querySelectorAll('.triggered-notification.error-notification').forEach(n => n.remove());

            // Create error notification
            const notification = document.createElement('div');
            notification.className = 'triggered-notification error-notification';
            notification.innerHTML = message + '<button class="dismiss-btn" type="button">&times;</button>';

            // Function to clear error state
            const clearErrorState = () => {
                AlertsRefresh.errorNotificationActive = false;
            };

            // Add click handler for dismiss button
            const dismissBtn = notification.querySelector('.dismiss-btn');
            if (dismissBtn) {
                dismissBtn.addEventListener('click', function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    notification.classList.add('dismissing');
                    setTimeout(() => {
                        notification.remove();
                        clearErrorState();
                    }, 300);
                });
            }

            errorContainer.appendChild(notification);

            // Auto-dismiss after 5 seconds
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.classList.add('dismissing');
                    setTimeout(() => {
                        notification.remove();
                        clearErrorState();
                    }, 300);
                }
            }, 5000);
        }
    };


    // =============================================================================
    // GROUP MANAGEMENT
    // =============================================================================
    /**
     * Handles organizing alerts into groups.
     */
    const GroupManager = {
        escapeHtml(str) {
            if (!str) return '';
            return str.replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        },

        open() {
            const selectedIds = this.getSelectedAlertIds();
            if (selectedIds.length === 0) {
                AlertActions.showErrorNotification('Please select at least one alert first.');
                return;
            }

            this.renderExistingGroups();
            this.clearNewGroupInput();
            const modal = document.querySelector(AlertsConfig.selectors.groupModal);
            if (modal) {
                modal.style.display = 'flex';
            }
        },

        close() {
            const modal = document.querySelector(AlertsConfig.selectors.groupModal);
            if (modal) {
                modal.style.display = 'none';
            }
        },

        clearNewGroupInput() {
            const input = document.querySelector(AlertsConfig.selectors.newGroupInput);
            if (input) input.value = '';
        },

        renderExistingGroups() {
            const list = document.querySelector(AlertsConfig.selectors.groupList);
            if (!list) return;

            const groups = AlertsState.getAlertGroups();
            if (!groups || groups.length === 0) {
                list.innerHTML = '<p class="no-alerts">No groups yet. Add a new one below.</p>';
                return;
            }

            list.innerHTML = '';
            groups.forEach(name => {
                const pill = document.createElement('span');
                pill.className = 'group-pill';
                pill.dataset.group = name;
                pill.textContent = name;
                pill.onclick = function () {
                    this.classList.toggle('selected');
                };
                list.appendChild(pill);
            });
        },

        getSelectedAlertIds() {
            const ids = [];
            document.querySelectorAll('.alert-checkbox:checked').forEach(cb => {
                const item = cb.closest('.alert-item');
                if (item && item.dataset.alertId) {
                    ids.push(item.dataset.alertId);
                }
            });
            return ids;
        },

        parseNewGroups() {
            const input = document.querySelector(AlertsConfig.selectors.newGroupInput);
            if (!input || !input.value.trim()) return [];
            return input.value.split(',')
                .map(g => g.trim())
                .filter(g => g.length > 0);
        },

        getSelectedGroups() {
            const selected = [];
            document.querySelectorAll(AlertsConfig.selectors.groupList + ' .group-pill.selected')
                .forEach(pill => selected.push(pill.dataset.group));
            return selected;
        },

        async save() {
            const alertIds = this.getSelectedAlertIds();
            if (alertIds.length === 0) {
                AlertActions.showErrorNotification('Please select at least one alert first.');
                return;
            }

            const existingGroups = this.getSelectedGroups();
            const newGroups = this.parseNewGroups();

            if (existingGroups.length === 0 && newGroups.length === 0) {
                AlertActions.showErrorNotification('Please choose an existing group or add a new one.');
                return;
            }

            const success = await AlertsAPI.groupAlerts(alertIds, existingGroups, newGroups);
            if (success) {
                AlertActions.showStatusNotification('Alert' + (alertIds.length > 1 ? 's' : '') + ' organized into group(s)');
                this.close();
                AlertActions.clearSelections();
                await AlertsRefresh.refresh();
            }
        },

        async deleteSelectedGroups() {
            const selectedGroups = this.getSelectedGroups();
            if (selectedGroups.length === 0) {
                AlertActions.showErrorNotification('Please select at least one group to delete.');
                return;
            }

            const confirmed = window.confirm('Delete selected group' + (selectedGroups.length > 1 ? 's' : '') + '? This will remove them from all alerts.');
            if (!confirmed) return;

            const success = await AlertsAPI.deleteGroups(selectedGroups);
            if (success) {
                AlertActions.showStatusNotification('Group' + (selectedGroups.length > 1 ? 's' : '') + ' deleted');
                // Optimistically remove from local state to reflect immediately
                const remaining = AlertsState.getAlertGroups().filter(g => !selectedGroups.includes(g));
                AlertsState.setAlertGroups(remaining);
                await AlertsRefresh.refresh();
                this.renderExistingGroups();
            } else {
                AlertActions.showErrorNotification('Failed to delete selected group(s). Please try again.');
            }
        }
    };


    // =============================================================================
    // AUTOCOMPLETE MANAGEMENT
    // =============================================================================
    /**
     * Manages item search autocomplete functionality.
     * 
     * Why: Both create and edit forms need autocomplete. This manager provides
     * reusable autocomplete logic for any item name input.
     */
    const AutocompleteManager = {
        /**
         * Tracks the currently selected suggestion index for each dropdown.
         * Keys are dropdown element IDs, values are the selected index (-1 = none).
         */
        selectedIndex: {},

        /**
         * Sets up autocomplete for an input/dropdown pair with full keyboard support.
         * 
         * What: Enables item search with suggestions dropdown
         * Why: Users need to find items by name, and keyboard navigation improves UX
         * How: Listens for input changes to fetch suggestions, and keydown events
         *      for arrow key navigation, Enter to select, and Escape to close
         * 
         * @param {HTMLElement} input - The text input element
         * @param {HTMLElement} hiddenInput - Hidden input to store selected item ID
         * @param {HTMLElement} dropdown - The suggestions dropdown container
         */
        setup(input, hiddenInput, dropdown) {
            if (!input || !dropdown) return;

            const dropdownId = dropdown.id;
            this.selectedIndex[dropdownId] = -1;

            /**
             * Updates visual highlighting of the currently selected suggestion.
             * Adds 'selected' class to the active item and scrolls it into view.
             */
            const updateSelection = () => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                items.forEach((item, index) => {
                    if (index === this.selectedIndex[dropdownId]) {
                        item.classList.add('selected');
                        item.scrollIntoView({block: 'nearest'});
                    } else {
                        item.classList.remove('selected');
                    }
                });
            };

            /**
             * Selects the currently highlighted suggestion.
             * Sets the input value and hidden ID, then closes the dropdown.
             */
            const selectCurrentItem = () => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                const index = this.selectedIndex[dropdownId];

                if (index >= 0 && index < items.length) {
                    const selectedItem = items[index];
                    input.value = selectedItem.dataset.name;
                    hiddenInput.value = selectedItem.dataset.id;
                    dropdown.style.display = 'none';
                    this.selectedIndex[dropdownId] = -1;
                }
            };

            /**
             * Resets the selection index when new suggestions are loaded.
             */
            const resetSelection = () => {
                this.selectedIndex[dropdownId] = -1;
            };

            // Handle input changes - fetch suggestions
            input.addEventListener('input', async () => {
                const query = input.value;

                if (query.length < AlertsConfig.timing.minSearchLength) {
                    dropdown.style.display = 'none';
                    resetSelection();
                    return;
                }

                const items = await AlertsAPI.searchItems(query);

                if (items.length > 0) {
                    dropdown.innerHTML = AlertsUI.renderSuggestions(items);
                    dropdown.style.display = 'block';
                    resetSelection();
                } else {
                    dropdown.style.display = 'none';
                    resetSelection();
                }
            });

            // Handle keyboard navigation
            input.addEventListener('keydown', (e) => {
                // Only handle keys when dropdown is visible
                if (dropdown.style.display === 'none') return;

                const items = dropdown.querySelectorAll('.suggestion-item');
                if (items.length === 0) return;

                switch (e.key) {
                    case 'ArrowDown':
                        // Move selection down, wrap to top if at bottom
                        e.preventDefault();
                        this.selectedIndex[dropdownId] =
                            (this.selectedIndex[dropdownId] + 1) % items.length;
                        updateSelection();
                        break;

                    case 'ArrowUp':
                        // Move selection up, wrap to bottom if at top
                        e.preventDefault();
                        this.selectedIndex[dropdownId] =
                            this.selectedIndex[dropdownId] <= 0
                                ? items.length - 1
                                : this.selectedIndex[dropdownId] - 1;
                        updateSelection();
                        break;

                    case 'Tab':
                        e.preventDefault();
                        if (e.shiftKey) {
                            // Shift+Tab moves selection up like ArrowUp
                            this.selectedIndex[dropdownId] =
                                this.selectedIndex[dropdownId] <= 0
                                    ? items.length - 1
                                    : this.selectedIndex[dropdownId] - 1;
                        } else {
                            // Tab moves selection down like ArrowDown
                            this.selectedIndex[dropdownId] =
                                (this.selectedIndex[dropdownId] + 1) % items.length;
                        }
                        updateSelection();
                        break;

                    case 'Enter':
                        // Enter selects current item
                        if (this.selectedIndex[dropdownId] >= 0) {
                            e.preventDefault();
                            selectCurrentItem();
                        }
                        break;

                    case 'Escape':
                        // Escape closes dropdown without selecting
                        e.preventDefault();
                        dropdown.style.display = 'none';
                        resetSelection();
                        break;
                }
            });

            // Handle mouse click on suggestion
            dropdown.addEventListener('click', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    input.value = e.target.dataset.name;
                    hiddenInput.value = e.target.dataset.id;
                    dropdown.style.display = 'none';
                    resetSelection();
                }
            });

            // Handle mouse hover to update selection
            dropdown.addEventListener('mouseover', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    const items = dropdown.querySelectorAll('.suggestion-item');
                    items.forEach((item, index) => {
                        if (item === e.target) {
                            this.selectedIndex[dropdownId] = index;
                        }
                    });
                    updateSelection();
                }
            });
        },

        /**
         * Initializes autocomplete for both forms.
         */
        init() {
            // Create form autocomplete
            const createSelectors = AlertsConfig.selectors.create;
            this.setup(
                document.querySelector(createSelectors.itemName),
                document.querySelector(createSelectors.itemId),
                document.querySelector(createSelectors.suggestions)
            );
        }
    };


    // =============================================================================
    // MULTI-ITEM SELECTOR
