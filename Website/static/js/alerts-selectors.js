    /**
     * Manages multi-item selection for sustained move alerts.
     * 
     * What: Allows users to select multiple specific items to monitor for sustained price moves
     * Why: Users may want to monitor sustained moves on a curated list of items
     * How: Uses box-style input with dropdown toggle showing selected items - matches alert_detail.html
     * 
     * This implementation mirrors the styling and behavior from alert_detail.html's MultiItemEditor
     * for visual consistency across the application.
     */
    const MultiItemSelector = {
        // selectedItems: Array of {id, name} objects representing currently selected items
        selectedItems: [],
        // selectedIndex: Index of currently highlighted suggestion in dropdown (-1 = none)
        selectedIndex: -1,
        // notificationTimeout: Reference to timeout for auto-hiding notifications
        notificationTimeout: null,
        // dropdownOpen: Tracks if the selected items dropdown is currently open
        dropdownOpen: false,

        /**
         * Initializes the multi-item selector for sustained move alerts.
         * 
         * What: Sets up event listeners for the sustained item search input and dropdown toggle
         * Why: Enables autocomplete functionality, dropdown management, and item removal
         * How: Attaches input, keydown, click handlers to relevant DOM elements
         */
        init() {
            // Get all DOM elements needed for the multi-item selector
            // input: Text input where user types to search for items to add
            const input = document.querySelector(AlertsConfig.selectors.create.sustainedItemInput);
            // dropdown: Container showing autocomplete suggestions when typing
            const dropdown = document.querySelector(AlertsConfig.selectors.create.sustainedItemSuggestions);
            // hiddenInput: Hidden field that stores comma-separated item IDs for form submission
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.sustainedItemIds);
            // selectedDropdown: Container showing list of already selected items
            const selectedDropdown = document.querySelector(AlertsConfig.selectors.create.sustainedSelectedItemsDropdown);
            // selectedList: Inner container where selected item rows are rendered
            const selectedList = document.querySelector(AlertsConfig.selectors.create.sustainedSelectedItemsList);
            // noItemsMsg: Message shown when no items are selected
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.sustainedNoItemsMessage);
            // toggleBtn: Button with chevron arrow to show/hide selected items dropdown
            const toggleBtn = document.querySelector(AlertsConfig.selectors.create.sustainedMultiItemToggle);
            // selectorBox: The main container box for the selector (for click-outside handling)
            const selectorBox = input ? input.closest('.multi-item-selector-box') : null;

            if (!input || !dropdown || !hiddenInput || !selectedDropdown) return;

            // Reference to 'this' for use inside closures
            const self = this;
            this.selectedItems = [];
            this.selectedIndex = -1;
            this.dropdownOpen = false;

            /**
             * Updates the hidden input with current selected item IDs.
             * Called whenever items are added or removed to keep form data in sync.
             */
            const updateHiddenInput = () => {
                hiddenInput.value = this.selectedItems.map(item => item.id).join(',');
            };

            /**
             * Updates visual selection state in autocomplete dropdown.
             * Highlights the currently selected suggestion item.
             */
            const updateSelection = () => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                items.forEach((item, index) => {
                    if (index === this.selectedIndex) {
                        item.classList.add('selected');
                        item.scrollIntoView({block: 'nearest'});
                    } else {
                        item.classList.remove('selected');
                    }
                });
            };

            /**
             * Adds an item to the selected list.
             * 
             * What: Adds item to selectedItems array and updates UI
             * Why: Central function for adding items from autocomplete or manual entry
             * How: Checks for duplicates, adds to array, updates hidden input and renders list
             * 
             * @param {string} id - The item's unique identifier
             * @param {string} name - The item's display name
             */
            const addItem = (id, name) => {
                // =============================================================================
                // CHECK FOR DUPLICATE ITEMS BEFORE ADDING
                // =============================================================================
                // What: Prevents the same item from being added multiple times to the selection
                // Why: Users shouldn't be able to add duplicate items - this would cause confusion
                //      and potentially duplicate alert notifications for the same item
                // How: Compares IDs using String() conversion to handle type mismatches
                //      (API returns numbers, DOM stores strings from dataset attributes)
                if (this.selectedItems.some(item => String(item.id) === String(id))) {
                    this.showNotification(`${name} is already selected`, 'error');
                    return;
                }

                this.selectedItems.push({id, name});
                updateHiddenInput();
                this.renderSelectedItems();
                input.value = '';
                dropdown.style.display = 'none';
                this.selectedIndex = -1;

                // Show success notification
                this.showNotification(`${name} added`, 'success');
            };

            /**
             * Removes an item from the selected list.
             * 
             * What: Removes item from selectedItems array and updates UI
             * Why: Called when user clicks the red X button on an item
             * 
             * @param {string} id - The item's unique identifier to remove
             */
            const removeItem = (id) => {
                const itemToRemove = this.selectedItems.find(item => String(item.id) === String(id));
                const itemName = itemToRemove ? itemToRemove.name : 'Item';
                this.selectedItems = this.selectedItems.filter(item => String(item.id) !== String(id));
                updateHiddenInput();
                this.renderSelectedItems();

                // Show removal notification
                this.showNotification(`${itemName} removed`, 'success');
            };

            // Handle remove button clicks in selected items dropdown (event delegation)
            if (selectedList) {
                selectedList.addEventListener('click', function(e) {
                    if (e.target.classList.contains('remove-item-btn')) {
                        e.preventDefault();
                        e.stopPropagation();
                        const itemId = e.target.dataset.id;
                        removeItem(itemId);
                    }
                });
            }

            // Handle dropdown toggle button clicks
            if (toggleBtn) {
                toggleBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Close autocomplete suggestions if open
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    
                    // Toggle selected items dropdown
                    this.dropdownOpen = !this.dropdownOpen;
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.add('show');
                        toggleBtn.classList.add('active');
                    } else {
                        selectedDropdown.classList.remove('show');
                        toggleBtn.classList.remove('active');
                    }
                });
            }

            // Close dropdowns when clicking outside
            document.addEventListener('click', (e) => {
                if (selectorBox && !selectorBox.contains(e.target)) {
                    // Close selected items dropdown
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.remove('show');
                        if (toggleBtn) toggleBtn.classList.remove('active');
                        this.dropdownOpen = false;
                    }
                    // Close autocomplete suggestions
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle input changes - fetch suggestions
            input.addEventListener('input', async () => {
                const query = input.value;

                // Close selected items dropdown when user starts typing
                if (this.dropdownOpen) {
                    selectedDropdown.classList.remove('show');
                    if (toggleBtn) toggleBtn.classList.remove('active');
                    this.dropdownOpen = false;
                }

                if (query.length < AlertsConfig.timing.minSearchLength) {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    return;
                }

                const items = await AlertsAPI.searchItems(query);

                // =============================================================================
                // FILTER OUT ALREADY SELECTED ITEMS FROM SUGGESTIONS
                // =============================================================================
                // What: Removes items that are already in the selectedItems array from the suggestions
                // Why: Once a user has added an item to be tracked, it shouldn't appear in the
                //      dropdown suggestions anymore - this prevents confusion and duplicate selection attempts
                // How: Uses Array.filter() to keep only items whose ID is not found in selectedItems.
                //      String conversion ensures type-safe comparison (API may return number, DOM stores string)
                const filteredItems = items.filter(item =>
                    !this.selectedItems.some(selected => String(selected.id) === String(item.id))
                );

                if (filteredItems.length > 0) {
                    dropdown.innerHTML = AlertsUI.renderSuggestions(filteredItems);
                    dropdown.style.display = 'block';
                    this.selectedIndex = -1;
                } else {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle keyboard navigation in dropdown
            input.addEventListener('keydown', (e) => {
                if (dropdown.style.display === 'none') {
                    // Backspace with empty input removes last item
                    if (e.key === 'Backspace' && input.value === '' && this.selectedItems.length > 0) {
                        const lastItem = this.selectedItems[this.selectedItems.length - 1];
                        removeItem(lastItem.id);
                    }
                    return;
                }

                const items = dropdown.querySelectorAll('.suggestion-item');
                if (items.length === 0) return;

                switch (e.key) {
                    case 'ArrowDown':
                        e.preventDefault();
                        this.selectedIndex = (this.selectedIndex + 1) % items.length;
                        updateSelection();
                        break;

                    case 'ArrowUp':
                        e.preventDefault();
                        this.selectedIndex = this.selectedIndex <= 0
                            ? items.length - 1
                            : this.selectedIndex - 1;
                        updateSelection();
                        break;

                    case 'Tab':
                        e.preventDefault();
                        if (e.shiftKey) {
                            this.selectedIndex = this.selectedIndex <= 0
                                ? items.length - 1
                                : this.selectedIndex - 1;
                        } else {
                            this.selectedIndex = (this.selectedIndex + 1) % items.length;
                        }
                        updateSelection();
                        break;

                    case 'Enter':
                        if (this.selectedIndex >= 0) {
                            e.preventDefault();
                            const selectedItem = items[this.selectedIndex];
                            addItem(selectedItem.dataset.id, selectedItem.dataset.name);
                        }
                        break;

                    case 'Escape':
                        e.preventDefault();
                        dropdown.style.display = 'none';
                        this.selectedIndex = -1;
                        break;
                }
            });

            // Handle mouse click on suggestion
            dropdown.addEventListener('click', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    addItem(e.target.dataset.id, e.target.dataset.name);
                }
            });

            // Handle mouse hover to update selection
            dropdown.addEventListener('mouseover', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    const items = dropdown.querySelectorAll('.suggestion-item');
                    items.forEach((item, index) => {
                        if (item === e.target) {
                            this.selectedIndex = index;
                        }
                    });
                    updateSelection();
                }
            });
        },

        /**
         * Renders the selected items in the dropdown list.
         * Shows each item with its name and a red X remove button - matching alert_detail.html styling.
         * 
         * What: Updates the DOM to display all currently selected items
         * Why: Provides visual feedback of selected items with ability to remove
         * How: Generates HTML rows for each item with remove button
         */
        renderSelectedItems() {
            const selectedList = document.querySelector(AlertsConfig.selectors.create.sustainedSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.sustainedNoItemsMessage);

            if (!selectedList) return;

            if (this.selectedItems.length === 0) {
                selectedList.innerHTML = '';
                if (noItemsMsg) noItemsMsg.classList.add('show');
            } else {
                if (noItemsMsg) noItemsMsg.classList.remove('show');
                selectedList.innerHTML = this.selectedItems.map(item =>
                    `<div class="selected-item-row">
                        <span class="item-name">${item.name}</span>
                        <button type="button" class="remove-item-btn" data-id="${item.id}" title="Remove ${item.name}">×</button>
                    </div>`
                ).join('');
            }
        },

        /**
         * Shows a small notification next to the "Items" label.
         * 
         * What: Displays success/error feedback for item add/remove operations
         * Why: Provides immediate visual feedback without disruptive popups
         * How: Updates the notification span with text and appropriate class, auto-hides after delay
         * 
         * @param {string} message - The notification message to display
         * @param {string} type - 'success' for green (item added/removed) or 'error' for red (duplicate)
         */
        showNotification(message, type) {
            const notification = document.querySelector(AlertsConfig.selectors.create.sustainedItemNotification);
            if (!notification) return;

            // Clear any existing timeout to prevent overlapping notifications
            if (this.notificationTimeout) {
                clearTimeout(this.notificationTimeout);
            }

            // Set the message and styling
            notification.textContent = message;
            notification.className = 'item-notification ' + type + ' show';

            // Auto-hide after 2.5 seconds
            this.notificationTimeout = setTimeout(() => {
                notification.classList.remove('show');
            }, 2500);
        },

        /**
         * Clears all selected items.
         * 
         * What: Removes all items from the selection
         * Why: Called when switching scope mode or after form submission
         * How: Empties the array and clears DOM elements
         */
        clear() {
            this.selectedItems = [];
            const selectedList = document.querySelector(AlertsConfig.selectors.create.sustainedSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.sustainedNoItemsMessage);
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.sustainedItemIds);
            
            if (selectedList) selectedList.innerHTML = '';
            if (noItemsMsg) noItemsMsg.classList.add('show');
            if (hiddenInput) hiddenInput.value = '';
        },

        /**
         * Gets the selected item IDs.
         */
        getSelectedIds() {
            return this.selectedItems.map(item => item.id);
        }
    };


    // =============================================================================
    // SPREAD MULTI-ITEM SELECTOR
    // =============================================================================
    /**
     * Manages multi-item selection for spread alerts with "Specific Item(s)" option.
     * 
     * What: Allows users to select multiple specific items to monitor for spread threshold
     * Why: Users may want to monitor spread on a curated list of items instead of all or just one
     * How: Uses box-style input with dropdown toggle showing selected items - matches alert_detail.html
     * 
     * This implementation mirrors the styling and behavior from alert_detail.html's MultiItemEditor
     * for visual consistency across the application.
     */
    const SpreadMultiItemSelector = {
        // selectedItems: Array of {id, name} objects representing currently selected items
        selectedItems: [],
        // selectedIndex: Index of currently highlighted suggestion in dropdown (-1 = none)
        selectedIndex: -1,
        // notificationTimeout: Reference to timeout for auto-hiding notifications
        notificationTimeout: null,
        // dropdownOpen: Tracks if the selected items dropdown is currently open
        dropdownOpen: false,

        /**
         * Initializes the spread multi-item selector.
         * 
         * What: Sets up event listeners for the spread item search input and dropdown toggle
         * Why: Enables autocomplete functionality, dropdown management, and item removal
         * How: Attaches input, keydown, click handlers to relevant DOM elements
         */
        init() {
            // Get all DOM elements needed for the multi-item selector
            // input: Text input where user types to search for items to add
            const input = document.querySelector(AlertsConfig.selectors.create.spreadItemInput);
            // dropdown: Container showing autocomplete suggestions when typing
            const dropdown = document.querySelector(AlertsConfig.selectors.create.spreadItemSuggestions);
            // hiddenInput: Hidden field that stores comma-separated item IDs for form submission
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.spreadItemIds);
            // selectedDropdown: Container showing list of already selected items
            const selectedDropdown = document.querySelector(AlertsConfig.selectors.create.spreadSelectedItemsDropdown);
            // selectedList: Inner container where selected item rows are rendered
            const selectedList = document.querySelector(AlertsConfig.selectors.create.spreadSelectedItemsList);
            // noItemsMsg: Message shown when no items are selected
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.spreadNoItemsMessage);
            // toggleBtn: Button with chevron arrow to show/hide selected items dropdown
            const toggleBtn = document.querySelector(AlertsConfig.selectors.create.spreadMultiItemToggle);
            // selectorBox: The main container box for the selector (for click-outside handling)
            const selectorBox = input ? input.closest('.multi-item-selector-box') : null;

            if (!input || !dropdown || !hiddenInput || !selectedDropdown) return;

            // Reference to 'this' for use inside closures
            const self = this;
            this.selectedItems = [];
            this.selectedIndex = -1;
            this.dropdownOpen = false;

            /**
             * Updates the hidden input with current selected item IDs.
             * Called whenever items are added or removed to keep form data in sync.
             */
            const updateHiddenInput = () => {
                hiddenInput.value = this.selectedItems.map(item => item.id).join(',');
            };

            /**
             * Updates visual selection state in autocomplete dropdown.
             * Highlights the currently selected suggestion item.
             */
            const updateSelection = () => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                items.forEach((item, index) => {
                    if (index === this.selectedIndex) {
                        item.classList.add('selected');
                        item.scrollIntoView({block: 'nearest'});
                    } else {
                        item.classList.remove('selected');
                    }
                });
            };

            /**
             * Adds an item to the selected list.
             * 
             * What: Adds item to selectedItems array and updates UI
             * Why: Central function for adding items from autocomplete or manual entry
             * How: Checks for duplicates, adds to array, updates hidden input and renders list
             * 
             * @param {string} id - The item's unique identifier
             * @param {string} name - The item's display name
             */
            const addItem = (id, name) => {
                // =============================================================================
                // CHECK FOR DUPLICATE ITEMS BEFORE ADDING
                // =============================================================================
                // What: Prevents the same item from being added multiple times to the selection
                // Why: Users shouldn't be able to add duplicate items - this would cause confusion
                //      and potentially duplicate alert notifications for the same item
                // How: Compares IDs using String() conversion to handle type mismatches
                //      (API returns numbers, DOM stores strings from dataset attributes)
                if (this.selectedItems.some(item => String(item.id) === String(id))) {
                    this.showNotification(`${name} is already selected`, 'error');
                    return;
                }

                this.selectedItems.push({id, name});
                updateHiddenInput();
                this.renderSelectedItems();
                input.value = '';
                dropdown.style.display = 'none';
                this.selectedIndex = -1;

                // Show success notification
                this.showNotification(`${name} added`, 'success');
            };

            /**
             * Removes an item from the selected list.
             * 
             * What: Removes item from selectedItems array and updates UI
             * Why: Called when user clicks the red X button on an item
             * 
             * @param {string} id - The item's unique identifier to remove
             */
            const removeItem = (id) => {
                const itemToRemove = this.selectedItems.find(item => String(item.id) === String(id));
                const itemName = itemToRemove ? itemToRemove.name : 'Item';
                this.selectedItems = this.selectedItems.filter(item => String(item.id) !== String(id));
                updateHiddenInput();
                this.renderSelectedItems();

                // Show removal notification
                this.showNotification(`${itemName} removed`, 'success');
            };

            // Handle remove button clicks in selected items dropdown (event delegation)
            if (selectedList) {
                selectedList.addEventListener('click', function(e) {
                    if (e.target.classList.contains('remove-item-btn')) {
                        e.preventDefault();
                        e.stopPropagation();
                        const itemId = e.target.dataset.id;
                        removeItem(itemId);
                    }
                });
            }

            // Handle dropdown toggle button clicks
            if (toggleBtn) {
                toggleBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Close autocomplete suggestions if open
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    
                    // Toggle selected items dropdown
                    this.dropdownOpen = !this.dropdownOpen;
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.add('show');
                        toggleBtn.classList.add('active');
                    } else {
                        selectedDropdown.classList.remove('show');
                        toggleBtn.classList.remove('active');
                    }
                });
            }

            // Close dropdowns when clicking outside
            document.addEventListener('click', (e) => {
                if (selectorBox && !selectorBox.contains(e.target)) {
                    // Close selected items dropdown
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.remove('show');
                        if (toggleBtn) toggleBtn.classList.remove('active');
                        this.dropdownOpen = false;
                    }
                    // Close autocomplete suggestions
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle input changes - fetch suggestions from API
            input.addEventListener('input', async () => {
                const query = input.value;

                // Close selected items dropdown when user starts typing
                if (this.dropdownOpen) {
                    selectedDropdown.classList.remove('show');
                    if (toggleBtn) toggleBtn.classList.remove('active');
                    this.dropdownOpen = false;
                }

                // minSearchLength: Minimum characters before searching (prevents API spam)
                if (query.length < AlertsConfig.timing.minSearchLength) {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    return;
                }

                // Fetch matching items from API
                const items = await AlertsAPI.searchItems(query);

                // =============================================================================
                // FILTER OUT ALREADY SELECTED ITEMS FROM SUGGESTIONS
                // =============================================================================
                // What: Removes items that are already in the selectedItems array from the suggestions
                // Why: Once a user has added an item to be tracked, it shouldn't appear in the
                //      dropdown suggestions anymore - this prevents confusion and duplicate selection attempts
                // How: Uses Array.filter() to keep only items whose ID is not found in selectedItems.
                //      String conversion ensures type-safe comparison (API returns number IDs, DOM stores string IDs)
                const filteredItems = items.filter(item =>
                    !this.selectedItems.some(selected => String(selected.id) === String(item.id))
                );

                if (filteredItems.length > 0) {
                    dropdown.innerHTML = AlertsUI.renderSuggestions(filteredItems);
                    dropdown.style.display = 'block';
                    this.selectedIndex = -1;
                } else {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle keyboard navigation in dropdown
            input.addEventListener('keydown', (e) => {
                if (dropdown.style.display === 'none') {
                    // Backspace with empty input removes last item
                    if (e.key === 'Backspace' && input.value === '' && this.selectedItems.length > 0) {
                        const lastItem = this.selectedItems[this.selectedItems.length - 1];
                        removeItem(lastItem.id);
                    }
                    return;
                }

                const items = dropdown.querySelectorAll('.suggestion-item');
                if (items.length === 0) return;

                switch (e.key) {
                    case 'ArrowDown':
                        e.preventDefault();
                        this.selectedIndex = (this.selectedIndex + 1) % items.length;
                        updateSelection();
                        break;

                    case 'ArrowUp':
                        e.preventDefault();
                        this.selectedIndex = this.selectedIndex <= 0
                            ? items.length - 1
                            : this.selectedIndex - 1;
                        updateSelection();
                        break;

                    case 'Tab':
                        e.preventDefault();
                        if (e.shiftKey) {
                            this.selectedIndex = this.selectedIndex <= 0
                                ? items.length - 1
                                : this.selectedIndex - 1;
                        } else {
                            this.selectedIndex = (this.selectedIndex + 1) % items.length;
                        }
                        updateSelection();
                        break;

                    case 'Enter':
                        if (this.selectedIndex >= 0) {
                            e.preventDefault();
                            const selectedItem = items[this.selectedIndex];
                            addItem(selectedItem.dataset.id, selectedItem.dataset.name);
                        }
                        break;

                    case 'Escape':
                        e.preventDefault();
                        dropdown.style.display = 'none';
                        this.selectedIndex = -1;
                        break;
                }
            });

            // Handle mouse click on suggestion
            dropdown.addEventListener('click', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    addItem(e.target.dataset.id, e.target.dataset.name);
                }
            });

            // Handle mouse hover to update selection
            dropdown.addEventListener('mouseover', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    const items = dropdown.querySelectorAll('.suggestion-item');
                    items.forEach((item, index) => {
                        if (item === e.target) {
                            this.selectedIndex = index;
                        }
                    });
                    updateSelection();
                }
            });
        },

        /**
         * Renders the selected items in the dropdown list.
         * Shows each item with its name and a red X remove button - matching alert_detail.html styling.
         * 
         * What: Updates the DOM to display all currently selected items
         * Why: Provides visual feedback of selected items with ability to remove
         * How: Generates HTML rows for each item with remove button
         */
        renderSelectedItems() {
            const selectedList = document.querySelector(AlertsConfig.selectors.create.spreadSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.spreadNoItemsMessage);

            if (!selectedList) return;

            if (this.selectedItems.length === 0) {
                selectedList.innerHTML = '';
                if (noItemsMsg) noItemsMsg.classList.add('show');
            } else {
                if (noItemsMsg) noItemsMsg.classList.remove('show');
                selectedList.innerHTML = this.selectedItems.map(item =>
                    `<div class="selected-item-row">
                        <span class="item-name">${item.name}</span>
                        <button type="button" class="remove-item-btn" data-id="${item.id}" title="Remove ${item.name}">×</button>
                    </div>`
                ).join('');
            }
        },

        /**
         * Shows a small notification next to the "Items" label.
         * 
         * What: Displays success/error feedback for item add/remove operations
         * Why: Provides immediate visual feedback without disruptive popups
         * How: Updates the notification span with text and appropriate class, auto-hides after delay
         * 
         * @param {string} message - The notification message to display
         * @param {string} type - 'success' for green (item added/removed) or 'error' for red (duplicate)
         */
        showNotification(message, type) {
            const notification = document.querySelector(AlertsConfig.selectors.create.spreadItemNotification);
            if (!notification) return;

            // Clear any existing timeout to prevent overlapping notifications
            if (this.notificationTimeout) {
                clearTimeout(this.notificationTimeout);
            }

            // Set the message and styling
            notification.textContent = message;
            notification.className = 'item-notification ' + type + ' show';

            // Auto-hide after 2.5 seconds
            this.notificationTimeout = setTimeout(() => {
                notification.classList.remove('show');
            }, 2500);
        },

        /**
         * Clears all selected items.
         * 
         * What: Removes all items from the selection
         * Why: Called when switching scope mode or after form submission
         * How: Empties the array and clears DOM elements
         */
        clear() {
            this.selectedItems = [];
            const selectedList = document.querySelector(AlertsConfig.selectors.create.spreadSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.spreadNoItemsMessage);
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.spreadItemIds);
            
            if (selectedList) selectedList.innerHTML = '';
            if (noItemsMsg) noItemsMsg.classList.add('show');
            if (hiddenInput) hiddenInput.value = '';
        },

        /**
         * Gets the selected item IDs.
         * 
         * @returns {Array} Array of item ID strings
         */
        getSelectedIds() {
            return this.selectedItems.map(item => item.id);
        }
    };


    // =============================================================================
    // SPIKE MULTI-ITEM SELECTOR
    // =============================================================================
    /**
     * SpikeMultiItemSelector
     * ======================
     * What: Manages multi-item selection for spike alerts with "Specific Item(s)" option.
     * Why: Users may want to monitor spike on a curated list of items instead of all or just one.
     * How: Uses box-style input with dropdown toggle showing selected items - same pattern as spread.
     * 
     * This implementation mirrors SpreadMultiItemSelector for visual and behavioral consistency.
     * Multi-item spike alerts will:
     * - Trigger when ANY item exceeds the threshold
     * - Re-trigger when triggered_data changes (different items or percentages)
     * - Deactivate when ALL items are simultaneously within threshold
     */
    const SpikeMultiItemSelector = {
        // selectedItems: Array of {id, name} objects representing currently selected items
        selectedItems: [],
        // selectedIndex: Index of currently highlighted suggestion in dropdown (-1 = none)
        selectedIndex: -1,
        // notificationTimeout: Reference to timeout for auto-hiding notifications
        notificationTimeout: null,
        // dropdownOpen: Tracks if the selected items dropdown is currently open
        dropdownOpen: false,

        /**
         * Initializes the spike multi-item selector.
         * 
         * What: Sets up event listeners for the spike item search input and dropdown toggle
         * Why: Enables autocomplete functionality, dropdown management, and item removal
         * How: Attaches input, keydown, click handlers to relevant DOM elements
         */
        init() {
            // Get all DOM elements needed for the multi-item selector
            const input = document.querySelector(AlertsConfig.selectors.create.spikeItemInput);
            const dropdown = document.querySelector(AlertsConfig.selectors.create.spikeItemSuggestions);
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.spikeItemIds);
            const selectedDropdown = document.querySelector(AlertsConfig.selectors.create.spikeSelectedItemsDropdown);
            const selectedList = document.querySelector(AlertsConfig.selectors.create.spikeSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.spikeNoItemsMessage);
            const toggleBtn = document.querySelector(AlertsConfig.selectors.create.spikeMultiItemToggle);
            const selectorBox = input ? input.closest('.multi-item-selector-box') : null;

            if (!input || !dropdown || !hiddenInput || !selectedDropdown) return;

            const self = this;
            this.selectedItems = [];
            this.selectedIndex = -1;
            this.dropdownOpen = false;

            /**
             * Updates the hidden input with current selected item IDs.
             */
            const updateHiddenInput = () => {
                hiddenInput.value = this.selectedItems.map(item => item.id).join(',');
            };

            /**
             * Updates visual selection state in autocomplete dropdown.
             */
            const updateSelection = () => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                items.forEach((item, index) => {
                    if (index === this.selectedIndex) {
                        item.classList.add('selected');
                        item.scrollIntoView({block: 'nearest'});
                    } else {
                        item.classList.remove('selected');
                    }
                });
            };

            /**
             * Adds an item to the selected list.
             * 
             * What: Adds item to selectedItems array and updates UI
             * Why: Central function for adding items from autocomplete or manual entry
             * How: Checks for duplicates using String() conversion for type-safe comparison,
             *      adds to array, updates hidden input and renders list
             */
            const addItem = (id, name) => {
                // =============================================================================
                // CHECK FOR DUPLICATE ITEMS BEFORE ADDING
                // =============================================================================
                // What: Prevents the same item from being added multiple times to the selection
                // Why: Users shouldn't be able to add duplicate items - this would cause confusion
                //      and potentially duplicate alert notifications for the same item
                // How: Compares IDs using String() conversion to handle type mismatches
                //      (API returns numbers, DOM stores strings from dataset attributes)
                if (this.selectedItems.some(item => String(item.id) === String(id))) {
                    this.showNotification(`${name} is already selected`, 'error');
                    return;
                }

                this.selectedItems.push({id, name});
                updateHiddenInput();
                this.renderSelectedItems();
                input.value = '';
                dropdown.style.display = 'none';
                this.selectedIndex = -1;
                this.showNotification(`${name} added`, 'success');
            };

            /**
             * Removes an item from the selected list.
             */
            const removeItem = (id) => {
                const itemToRemove = this.selectedItems.find(item => String(item.id) === String(id));
                const itemName = itemToRemove ? itemToRemove.name : 'Item';
                this.selectedItems = this.selectedItems.filter(item => String(item.id) !== String(id));
                updateHiddenInput();
                this.renderSelectedItems();
                this.showNotification(`${itemName} removed`, 'success');
            };

            // Handle remove button clicks in selected items dropdown
            if (selectedList) {
                selectedList.addEventListener('click', function(e) {
                    if (e.target.classList.contains('remove-item-btn')) {
                        e.preventDefault();
                        e.stopPropagation();
                        const itemId = e.target.dataset.id;
                        removeItem(itemId);
                    }
                });
            }

            // Handle dropdown toggle button clicks
            if (toggleBtn) {
                toggleBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    
                    this.dropdownOpen = !this.dropdownOpen;
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.add('show');
                        toggleBtn.classList.add('active');
                    } else {
                        selectedDropdown.classList.remove('show');
                        toggleBtn.classList.remove('active');
                    }
                });
            }

            // Close dropdowns when clicking outside
            document.addEventListener('click', (e) => {
                if (selectorBox && !selectorBox.contains(e.target)) {
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.remove('show');
                        if (toggleBtn) toggleBtn.classList.remove('active');
                        this.dropdownOpen = false;
                    }
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle input changes - fetch suggestions from API
            input.addEventListener('input', async () => {
                const query = input.value;

                if (this.dropdownOpen) {
                    selectedDropdown.classList.remove('show');
                    if (toggleBtn) toggleBtn.classList.remove('active');
                    this.dropdownOpen = false;
                }

                if (query.length < AlertsConfig.timing.minSearchLength) {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    return;
                }

                const items = await AlertsAPI.searchItems(query);
                
                // =============================================================================
                // FILTER OUT ALREADY SELECTED ITEMS FROM SUGGESTIONS
                // =============================================================================
                // What: Removes items that are already in the selectedItems array from the suggestions
                // Why: Once a user has added an item to be tracked, it shouldn't appear in the
                //      dropdown suggestions anymore - this prevents confusion and duplicate selection attempts
                // How: Uses Array.filter() to keep only items whose ID is not found in selectedItems
                const filteredItems = items ? items.filter(item =>
                    !this.selectedItems.some(selected => String(selected.id) === String(item.id))
                ) : [];
                
                if (filteredItems.length > 0) {
                    dropdown.innerHTML = filteredItems.map(item =>
                        `<div class="suggestion-item" data-id="${item.id}" data-name="${item.name}">${item.name}</div>`
                    ).join('');
                    dropdown.style.display = 'block';
                    this.selectedIndex = -1;

                    // Add click handlers to suggestions
                    dropdown.querySelectorAll('.suggestion-item').forEach(item => {
                        item.addEventListener('click', () => {
                            addItem(item.dataset.id, item.dataset.name);
                        });
                    });
                } else {
                    // If no items left after filtering, hide the dropdown entirely
                    // (don't show "No items found" since items exist but are already selected)
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle keyboard navigation in dropdown
            // What: Enables keyboard-based navigation and selection of autocomplete suggestions
            // Why: Users expect Tab/Shift+Tab to navigate through suggestions like arrow keys
            // How: ArrowDown/Tab move down, ArrowUp/Shift+Tab move up, Enter selects, Escape closes
            input.addEventListener('keydown', (e) => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                const itemCount = items.length;

                // Only process navigation keys when dropdown is visible and has items
                // What: Check if dropdown is visible before handling navigation
                // Why: Allows normal Tab behavior when no suggestions are shown
                // How: Check display style and item count before preventing default
                if (dropdown.style.display === 'none' || itemCount === 0) {
                    // Backspace with empty input removes last selected item
                    if (e.key === 'Backspace' && input.value === '' && this.selectedItems.length > 0) {
                        const lastItem = this.selectedItems[this.selectedItems.length - 1];
                        removeItem(lastItem.id);
                    }
                    return;
                }

                switch (e.key) {
                    case 'ArrowDown':
                        // What: Move selection down through suggestions
                        // Why: Standard keyboard navigation pattern
                        // How: Increment index, wrap around at end using modulo
                        e.preventDefault();
                        this.selectedIndex = (this.selectedIndex + 1) % itemCount;
                        updateSelection();
                        break;

                    case 'ArrowUp':
                        // What: Move selection up through suggestions
                        // Why: Standard keyboard navigation pattern
                        // How: Decrement index, wrap to end if at beginning
                        e.preventDefault();
                        this.selectedIndex = this.selectedIndex <= 0
                            ? itemCount - 1
                            : this.selectedIndex - 1;
                        updateSelection();
                        break;

                    case 'Tab':
                        // What: Tab navigates through suggestions like arrow keys
                        // Why: Users expect Tab to move through autocomplete options, not focus next element
                        // How: Shift+Tab goes up, Tab goes down, same as arrow keys
                        e.preventDefault();
                        if (e.shiftKey) {
                            // Shift+Tab: Move selection up (same as ArrowUp)
                            this.selectedIndex = this.selectedIndex <= 0
                                ? itemCount - 1
                                : this.selectedIndex - 1;
                        } else {
                            // Tab: Move selection down (same as ArrowDown)
                            this.selectedIndex = (this.selectedIndex + 1) % itemCount;
                        }
                        updateSelection();
                        break;

                    case 'Enter':
                        // What: Select the currently highlighted suggestion
                        // Why: Standard keyboard pattern for confirming selection
                        // How: Add the highlighted item to selected list, clear input
                        e.preventDefault();
                        if (this.selectedIndex >= 0 && this.selectedIndex < itemCount) {
                            const selected = items[this.selectedIndex];
                            addItem(selected.dataset.id, selected.dataset.name);
                        }
                        break;

                    case 'Escape':
                        // What: Close the suggestions dropdown without selecting
                        // Why: Standard keyboard pattern for canceling/dismissing
                        // How: Hide dropdown, reset selection index
                        e.preventDefault();
                        dropdown.style.display = 'none';
                        this.selectedIndex = -1;
                        break;
                }
            });

            // Handle focus
            input.addEventListener('focus', async () => {
                if (input.value.length >= AlertsConfig.timing.minSearchLength) {
                    const items = await AlertsAPI.searchItems(input.value);
                    if (items && items.length > 0) {
                        dropdown.innerHTML = items.map(item =>
                            `<div class="suggestion-item" data-id="${item.id}" data-name="${item.name}">${item.name}</div>`
                        ).join('');
                        dropdown.style.display = 'block';

                        dropdown.querySelectorAll('.suggestion-item').forEach(item => {
                            item.addEventListener('click', () => {
                                addItem(item.dataset.id, item.dataset.name);
                            });
                        });
                    }
                    updateSelection();
                }
            });
        },

        /**
         * Renders the selected items in the dropdown list.
         */
        renderSelectedItems() {
            const selectedList = document.querySelector(AlertsConfig.selectors.create.spikeSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.spikeNoItemsMessage);

            if (!selectedList) return;

            if (this.selectedItems.length === 0) {
                selectedList.innerHTML = '';
                if (noItemsMsg) noItemsMsg.classList.add('show');
            } else {
                if (noItemsMsg) noItemsMsg.classList.remove('show');
                selectedList.innerHTML = this.selectedItems.map(item =>
                    `<div class="selected-item-row">
                        <span class="item-name">${item.name}</span>
                        <button type="button" class="remove-item-btn" data-id="${item.id}" title="Remove ${item.name}">×</button>
                    </div>`
                ).join('');
            }
        },

        /**
         * Shows a small notification next to the "Items" label.
         */
        showNotification(message, type) {
            const notification = document.querySelector(AlertsConfig.selectors.create.spikeItemNotification);
            if (!notification) return;

            if (this.notificationTimeout) {
                clearTimeout(this.notificationTimeout);
            }

            notification.textContent = message;
            notification.className = 'item-notification ' + type + ' show';

            this.notificationTimeout = setTimeout(() => {
                notification.classList.remove('show');
            }, 2500);
        },

        /**
         * Clears all selected items.
         */
        clear() {
            this.selectedItems = [];
            const selectedList = document.querySelector(AlertsConfig.selectors.create.spikeSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.spikeNoItemsMessage);
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.spikeItemIds);
            
            if (selectedList) selectedList.innerHTML = '';
            if (noItemsMsg) noItemsMsg.classList.add('show');
            if (hiddenInput) hiddenInput.value = '';
        },

        /**
         * Gets the selected item IDs.
         * 
         * @returns {Array} Array of item ID strings
         */
        getSelectedIds() {
            return this.selectedItems.map(item => item.id);
        },

        /**
         * Sets items for editing an existing alert.
         * 
         * @param {Array} items - Array of {id, name} objects to set as selected
         */
        setItems(items) {
            this.selectedItems = items || [];
            this.renderSelectedItems();
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.spikeItemIds);
            if (hiddenInput) {
                hiddenInput.value = this.selectedItems.map(item => item.id).join(',');
            }
        }
    };


    // =============================================================================
    // THRESHOLD MULTI-ITEM SELECTOR
    // =============================================================================
    /**
     * ThresholdMultiItemSelector
     * ===========================
     * What: Manages the multi-item selection interface for threshold alerts.
     * Why: Threshold alerts can monitor multiple specific items, requiring a UI to add/remove items.
     * How: Provides autocomplete search, selected items dropdown, and item management functionality.
     *      Nearly identical to SpreadMultiItemSelector but operates on threshold-specific DOM elements.
     * 
     * This selector is used when:
     * - User selects "Threshold" as alert type
     * - User selects "Specific Items" in Items Tracked dropdown
     * 
     * Key behaviors:
     * - When items are added/removed, updates FormManager.updateThresholdTypeState()
     *   to enforce percentage mode when multiple items are selected
     * - Clears selection when switching to "All Items" mode
     */
    const ThresholdMultiItemSelector = {
        // selectedItems: Array of {id, name} objects representing currently selected items
        selectedItems: [],
        // selectedIndex: Index of currently highlighted suggestion in dropdown (-1 = none)
        selectedIndex: -1,
        // notificationTimeout: Reference to timeout for auto-hiding notifications
        notificationTimeout: null,
        // dropdownOpen: Tracks if the selected items dropdown is currently open
        dropdownOpen: false,

        /**
         * Initializes the threshold multi-item selector.
         * 
         * What: Sets up event listeners for the threshold item search input and dropdown toggle
         * Why: Enables autocomplete functionality, dropdown management, and item removal
         * How: Attaches input, keydown, click handlers to relevant DOM elements
         */
        init() {
            // Get all DOM elements needed for the multi-item selector
            // input: Text input where user types to search for items to add
            const input = document.querySelector(AlertsConfig.selectors.create.thresholdItemInput);
            // dropdown: Container showing autocomplete suggestions when typing
            const dropdown = document.querySelector(AlertsConfig.selectors.create.thresholdItemSuggestions);
            // hiddenInput: Hidden field that stores comma-separated item IDs for form submission
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.thresholdItemIds);
            // selectedDropdown: Container showing list of already selected items
            const selectedDropdown = document.querySelector(AlertsConfig.selectors.create.thresholdSelectedItemsDropdown);
            // selectedList: Inner container where selected item rows are rendered
            const selectedList = document.querySelector(AlertsConfig.selectors.create.thresholdSelectedItemsList);
            // noItemsMsg: Message shown when no items are selected
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.thresholdNoItemsMessage);
            // toggleBtn: Button with chevron arrow to show/hide selected items dropdown
            const toggleBtn = document.querySelector(AlertsConfig.selectors.create.thresholdMultiItemToggle);
            // selectorBox: The main container box for the selector (for click-outside handling)
            const selectorBox = input ? input.closest('.multi-item-selector-box') : null;

            if (!input || !dropdown || !hiddenInput || !selectedDropdown) return;

            // Reference to 'this' for use inside closures
            const self = this;
            this.selectedItems = [];
            this.selectedIndex = -1;
            this.dropdownOpen = false;

            /**
             * Updates the hidden input with current selected item IDs.
             * Called whenever items are added or removed to keep form data in sync.
             */
            const updateHiddenInput = () => {
                hiddenInput.value = this.selectedItems.map(item => item.id).join(',');
            };

            /**
             * Updates visual selection state in autocomplete dropdown.
             * Highlights the currently selected suggestion item.
             */
            const updateSelection = () => {
                const items = dropdown.querySelectorAll('.suggestion-item');
                items.forEach((item, index) => {
                    if (index === this.selectedIndex) {
                        item.classList.add('selected');
                        item.scrollIntoView({block: 'nearest'});
                    } else {
                        item.classList.remove('selected');
                    }
                });
            };

            /**
             * Adds an item to the selected list.
             * 
             * What: Adds item to selectedItems array and updates UI
             * Why: Central function for adding items from autocomplete or manual entry
             * How: Checks for duplicates, adds to array, updates hidden input and renders list
             * 
             * @param {string} id - The item's unique identifier
             * @param {string} name - The item's display name
             */
            const addItem = (id, name) => {
                // =============================================================================
                // CHECK FOR DUPLICATE ITEMS BEFORE ADDING
                // =============================================================================
                // What: Prevents the same item from being added multiple times to the selection
                // Why: Users shouldn't be able to add duplicate items - this would cause confusion
                //      and potentially duplicate alert notifications for the same item
                // How: Compares IDs using String() conversion to handle type mismatches
                //      (API returns numbers, DOM stores strings from dataset attributes)
                if (this.selectedItems.some(item => String(item.id) === String(id))) {
                    this.showNotification(`${name} is already selected`, 'error');
                    return;
                }

                this.selectedItems.push({id, name});
                updateHiddenInput();
                this.renderSelectedItems();
                input.value = '';
                dropdown.style.display = 'none';
                this.selectedIndex = -1;

                // Show success notification
                this.showNotification(`${name} added`, 'success');

                // Update threshold type state (lock to percentage if multiple items)
                FormManager.updateThresholdTypeState();
            };

            /**
             * Removes an item from the selected list.
             * 
             * What: Removes item from selectedItems array and updates UI
             * Why: Called when user clicks the red X button on an item
             * 
             * @param {string} id - The item's unique identifier to remove
             */
            const removeItem = (id) => {
                const itemToRemove = this.selectedItems.find(item => String(item.id) === String(id));
                const itemName = itemToRemove ? itemToRemove.name : 'Item';
                this.selectedItems = this.selectedItems.filter(item => String(item.id) !== String(id));
                updateHiddenInput();
                this.renderSelectedItems();

                // Show removal notification
                this.showNotification(`${itemName} removed`, 'success');

                // Update threshold type state (may unlock value option if only 1 item left)
                FormManager.updateThresholdTypeState();
            };

            // Handle remove button clicks in selected items dropdown (event delegation)
            if (selectedList) {
                selectedList.addEventListener('click', function(e) {
                    if (e.target.classList.contains('remove-item-btn')) {
                        e.preventDefault();
                        e.stopPropagation();
                        const itemId = e.target.dataset.id;
                        removeItem(itemId);
                    }
                });
            }

            // Handle dropdown toggle button clicks
            if (toggleBtn) {
                toggleBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    
                    // Close autocomplete suggestions if open
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    
                    // Toggle selected items dropdown
                    this.dropdownOpen = !this.dropdownOpen;
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.add('show');
                        toggleBtn.classList.add('active');
                    } else {
                        selectedDropdown.classList.remove('show');
                        toggleBtn.classList.remove('active');
                    }
                });
            }

            // Close dropdowns when clicking outside
            document.addEventListener('click', (e) => {
                if (selectorBox && !selectorBox.contains(e.target)) {
                    // Close selected items dropdown
                    if (this.dropdownOpen) {
                        selectedDropdown.classList.remove('show');
                        if (toggleBtn) toggleBtn.classList.remove('active');
                        this.dropdownOpen = false;
                    }
                    // Close autocomplete suggestions
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle input changes - fetch suggestions from API
            input.addEventListener('input', async () => {
                const query = input.value;

                // Close selected items dropdown when user starts typing
                if (this.dropdownOpen) {
                    selectedDropdown.classList.remove('show');
                    if (toggleBtn) toggleBtn.classList.remove('active');
                    this.dropdownOpen = false;
                }

                // minSearchLength: Minimum characters before searching (prevents API spam)
                if (query.length < AlertsConfig.timing.minSearchLength) {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                    return;
                }

                // Fetch matching items from API
                const items = await AlertsAPI.searchItems(query);

                // =============================================================================
                // FILTER OUT ALREADY SELECTED ITEMS FROM SUGGESTIONS
                // =============================================================================
                // What: Removes items that are already in the selectedItems array from the suggestions
                // Why: Once a user has added an item to be tracked, it shouldn't appear in the
                //      dropdown suggestions anymore - this prevents confusion and duplicate selection attempts
                // How: Uses Array.filter() to keep only items whose ID is not found in selectedItems.
                //      String conversion ensures type-safe comparison (API returns number IDs, DOM stores string IDs)
                const filteredItems = items.filter(item =>
                    !this.selectedItems.some(selected => String(selected.id) === String(item.id))
                );

                if (filteredItems.length > 0) {
                    dropdown.innerHTML = AlertsUI.renderSuggestions(filteredItems);
                    dropdown.style.display = 'block';
                    this.selectedIndex = -1;
                } else {
                    dropdown.style.display = 'none';
                    this.selectedIndex = -1;
                }
            });

            // Handle keyboard navigation in dropdown
            input.addEventListener('keydown', (e) => {
                if (dropdown.style.display === 'none') {
                    // Backspace with empty input removes last item
                    if (e.key === 'Backspace' && input.value === '' && this.selectedItems.length > 0) {
                        const lastItem = this.selectedItems[this.selectedItems.length - 1];
                        removeItem(lastItem.id);
                    }
                    return;
                }

                const items = dropdown.querySelectorAll('.suggestion-item');
                if (items.length === 0) return;

                switch (e.key) {
                    case 'ArrowDown':
                        e.preventDefault();
                        this.selectedIndex = (this.selectedIndex + 1) % items.length;
                        updateSelection();
                        break;

                    case 'ArrowUp':
                        e.preventDefault();
                        this.selectedIndex = this.selectedIndex <= 0
                            ? items.length - 1
                            : this.selectedIndex - 1;
                        updateSelection();
                        break;

                    case 'Tab':
                        e.preventDefault();
                        if (e.shiftKey) {
                            this.selectedIndex = this.selectedIndex <= 0
                                ? items.length - 1
                                : this.selectedIndex - 1;
                        } else {
                            this.selectedIndex = (this.selectedIndex + 1) % items.length;
                        }
                        updateSelection();
                        break;

                    case 'Enter':
                        if (this.selectedIndex >= 0) {
                            e.preventDefault();
                            const selectedItem = items[this.selectedIndex];
                            addItem(selectedItem.dataset.id, selectedItem.dataset.name);
                        }
                        break;

                    case 'Escape':
                        e.preventDefault();
                        dropdown.style.display = 'none';
                        this.selectedIndex = -1;
                        break;
                }
            });

            // Handle mouse click on suggestion
            dropdown.addEventListener('click', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    addItem(e.target.dataset.id, e.target.dataset.name);
                }
            });

            // Handle mouse hover to update selection
            dropdown.addEventListener('mouseover', (e) => {
                if (e.target.classList.contains('suggestion-item')) {
                    const items = dropdown.querySelectorAll('.suggestion-item');
                    items.forEach((item, index) => {
                        if (item === e.target) {
                            this.selectedIndex = index;
                        }
                    });
                    updateSelection();
                }
            });
        },

        /**
         * Renders the selected items in the dropdown list.
         * Shows each item with its name and a red X remove button - matching spread selector styling.
         * 
         * What: Updates the DOM to display all currently selected items
         * Why: Provides visual feedback of selected items with ability to remove
         * How: Generates HTML rows for each item with remove button
         */
        renderSelectedItems() {
            const selectedList = document.querySelector(AlertsConfig.selectors.create.thresholdSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.thresholdNoItemsMessage);

            if (!selectedList) return;

            if (this.selectedItems.length === 0) {
                selectedList.innerHTML = '';
                if (noItemsMsg) noItemsMsg.classList.add('show');
            } else {
                if (noItemsMsg) noItemsMsg.classList.remove('show');
                selectedList.innerHTML = this.selectedItems.map(item =>
                    `<div class="selected-item-row">
                        <span class="item-name">${item.name}</span>
                        <button type="button" class="remove-item-btn" data-id="${item.id}" title="Remove ${item.name}">×</button>
                    </div>`
                ).join('');
            }
        },

        /**
         * Shows a small notification next to the "Items" label.
         * 
         * What: Displays success/error feedback for item add/remove operations
         * Why: Provides immediate visual feedback without disruptive popups
         * How: Updates the notification span with text and appropriate class, auto-hides after delay
         * 
         * @param {string} message - The notification message to display
         * @param {string} type - 'success' for green (item added/removed) or 'error' for red (duplicate)
         */
        showNotification(message, type) {
            const notification = document.querySelector(AlertsConfig.selectors.create.thresholdItemNotification);
            if (!notification) return;

            // Clear any existing timeout to prevent overlapping notifications
            if (this.notificationTimeout) {
                clearTimeout(this.notificationTimeout);
            }

            // Set the message and styling
            notification.textContent = message;
            notification.className = 'item-notification ' + type + ' show';

            // Auto-hide after 2.5 seconds
            this.notificationTimeout = setTimeout(() => {
                notification.classList.remove('show');
            }, 2500);
        },

        /**
         * Clears all selected items.
         * 
         * What: Removes all items from the selection
         * Why: Called when switching to "All Items" mode or after form submission
         * How: Empties the array and clears DOM elements
         */
        clear() {
            this.selectedItems = [];
            const selectedList = document.querySelector(AlertsConfig.selectors.create.thresholdSelectedItemsList);
            const noItemsMsg = document.querySelector(AlertsConfig.selectors.create.thresholdNoItemsMessage);
            const hiddenInput = document.querySelector(AlertsConfig.selectors.create.thresholdItemIds);
            
            if (selectedList) selectedList.innerHTML = '';
            if (noItemsMsg) noItemsMsg.classList.add('show');
            if (hiddenInput) hiddenInput.value = '';
        },

        /**
         * Gets the selected item IDs.
         * 
         * @returns {Array} Array of item ID strings
         */
        getSelectedIds() {
            return this.selectedItems.map(item => item.id);
        }
    };


    // =============================================================================
    // ALERTS REFRESH
    // =============================================================================
    /**
     * Handles periodic refresh of alerts data.
     * 
     * Why: Alerts can be triggered by the background script at any time.
     * Periodic refresh ensures the UI stays in sync.
     */
    const AlertsRefresh = {
        intervalId: null,
        pausedForSort: false,
        errorNotificationActive: false,
        dropdownOpen: false,

        /**
         * Checks if any dropdown is currently open or search is active.
         */
        isDropdownOpen() {
            // Check the explicit dropdown open flag first
            if (this.dropdownOpen) {
                return true;
            }
            // Check if any dropdown menu is open
            if (document.querySelector('.custom-dropdown-menu.show') !== null) {
                return true;
            }
            // Check if search input is focused
            const searchInput = document.getElementById('alertSearchInput');
            if (searchInput && document.activeElement === searchInput) {
                return true;
            }
            // Check if error notification is active
            if (this.errorNotificationActive) {
                return true;
            }
            return false;
        },

        /**
         * Called immediately when a dropdown button is clicked to pause refresh.
         */
        onDropdownOpen() {
            this.dropdownOpen = true;
        },

        /**
         * Called when all dropdowns are closed to resume refresh.
         */
        onDropdownClose() {
            this.dropdownOpen = false;
        },

        /**
         * Fetches fresh data and updates the UI.
         * Skips refresh if a dropdown is open to prevent UI disruption.
         * 
         * PERFORMANCE: Two-phase loading for instant render
         * Phase 1: Fetch alerts (instant - no external API)
         * Phase 2: Fetch prices in background, update cached alerts
         */
        async refresh() {
            // Don't refresh if any dropdown is open
            if (this.isDropdownOpen()) {
                return;
            }

            // =================================================================
            // PHASE 1: Fetch and render alerts INSTANTLY (no price API wait)
            // =================================================================
            const data = await AlertsAPI.fetchAlerts();
            if (data) {
                AlertsUI.updateMyAlertsPane(data);
                
                // =============================================================
                // PHASE 2: Fetch prices in background, then update cached data
                // =============================================================
                // This runs AFTER the list is visible, so user sees content fast
                this.fetchAndApplyPrices(data.alerts);
            }
        },
        
        /**
         * Fetches prices and updates cached alerts with price data.
         * Called after initial render so price latency doesn't block UI.
         * 
         * What: Fetches prices from external API, updates alert cache with current_price
         * Why: Allows threshold distance sorting to work after initial render
         * How: Gets prices, maps to alerts by item_id, updates AlertsState cache
         */
        async fetchAndApplyPrices(alerts) {
            if (!alerts || alerts.length === 0) return;
            
            const priceData = await AlertsAPI.fetchPrices();
            if (!priceData || !priceData.prices) return;
            
            const prices = priceData.prices;
            
            // Update each cached alert with its price data
            const cachedAlerts = AlertsState.getCachedAlerts();
            if (!cachedAlerts) return;
            
            let updated = false;
            cachedAlerts.forEach(alert => {
                if (alert.item_id && !alert.is_all_items) {
                    const itemPrices = prices[String(alert.item_id)];
                    if (itemPrices) {
                        // Calculate current_price based on reference type
                        const ref = alert.reference || 'high';
                        if (ref === 'low') {
                            alert.current_price = itemPrices.low;
                        } else if (ref === 'average') {
                            const high = itemPrices.high;
                            const low = itemPrices.low;
                            if (high && low) {
                                alert.current_price = Math.floor((high + low) / 2);
                            }
                        } else {
                            alert.current_price = itemPrices.high;
                        }
                        
                        // Calculate spread_percentage for spread alerts
                        if (alert.type === 'spread') {
                            const high = itemPrices.high;
                            const low = itemPrices.low;
                            if (high && low && low > 0) {
                                alert.spread_percentage = Math.round(((high - low) / low) * 10000) / 100;
                            }
                        }
                        updated = true;
                    }
                }
            });
            
            // If we updated any alerts and user is sorting by threshold distance,
            // trigger a re-render to show the updated sort order
            if (updated && AlertsState.sorting.sortKey === 'thresholdDistance') {
                // Re-render with updated price data
                AlertsUI.renderFromCache();
            }
        },

        /**
         * Starts the periodic refresh interval.
         */
        start() {
            if (this.intervalId) return;
            this.refresh();
            this.intervalId = setInterval(
                () => this.refresh(),
                AlertsConfig.timing.refreshInterval
            );
        },

        /**
         * Temporarily pause refresh while user chooses sort order.
         */
        pauseForSort() {
            this.pausedForSort = true;
            this.stop();
        },

        /**
         * Resume refresh if it was paused for sort selection.
         */
        resumeAfterSort() {
            if (!this.pausedForSort) return;
            this.pausedForSort = false;
            this.start();
        },

        /**
         * Stops the periodic refresh.
         */
        stop() {
            if (this.intervalId) {
                clearInterval(this.intervalId);
                this.intervalId = null;
            }
        }
    };


