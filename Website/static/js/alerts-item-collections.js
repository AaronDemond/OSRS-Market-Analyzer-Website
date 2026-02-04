/**
 * =============================================================================
 * ITEM COLLECTION MANAGER
 * =============================================================================
 * 
 * What: Manages the Item Collection feature - allows users to save and apply
 *       pre-defined groups of items to alerts for faster alert creation.
 * 
 * Why: Users who frequently create alerts for the same groups of items (e.g.,
 *      high-value flips, daily watchlist, specific categories) can save time
 *      by applying a saved collection instead of selecting items one-by-one.
 * 
 * How: This manager handles:
 *      - Opening/closing the item collection modal
 *      - Switching between select view and create view
 *      - Loading saved collections from the server API
 *      - Creating new collections (name + items)
 *      - Deleting existing collections
 *      - Applying collections to the alert form (merge or replace mode)
 * 
 * Variables:
 *   - collections: Array of saved collection objects from the server
 *   - currentAlertType: The alert type that opened the modal ('spike', 'spread', etc.)
 *   - selectedItems: Items selected in the create view (for new collection)
 *   - collectionToDelete: ID of collection pending deletion confirmation
 *   - dropdownOpen: Whether the selected items dropdown is open
 *   - selectedIndex: Index of highlighted suggestion in autocomplete
 *   - notificationTimeout: Timeout reference for auto-hiding notifications
 * 
 * Dependencies:
 *   - AlertsAPI: For searching items during autocomplete
 *   - AlertsUI: For rendering suggestion items
 *   - Window.CSRF_TOKEN: For API requests
 */
const ItemCollectionManager = {
    // =============================================================================
    // STATE VARIABLES
    // =============================================================================
    
    /**
     * collections: Array of ItemCollection objects loaded from server
     * Each object has: id, name, item_ids (array), item_names (array), created_at
     */
    collections: [],
    
    /**
     * currentAlertType: String identifying which alert type opened the modal
     * Valid values: 'spike', 'spread', 'sustained', 'threshold'
     * Used to determine which form elements to update when applying a collection
     */
    currentAlertType: null,
    
    /**
     * selectedItems: Array of {id, name} objects for items selected in create view
     * These items will become the collection when saved
     */
    selectedItems: [],
    
    /**
     * collectionToDelete: ID of collection user wants to delete
     * Set when delete button clicked, used when delete is confirmed
     */
    collectionToDelete: null,
    
    /**
     * dropdownOpen: Boolean tracking if selected items dropdown is visible
     * Used in create view to show/hide the list of items added to new collection
     */
    dropdownOpen: false,
    
    /**
     * selectedIndex: Index of currently highlighted suggestion in autocomplete
     * -1 means no suggestion is highlighted
     */
    selectedIndex: -1,
    
    /**
     * notificationTimeout: Reference to setTimeout for auto-hiding notifications
     * Cleared and reset when new notification shown to prevent stacking
     */
    notificationTimeout: null,

    // =============================================================================
    // MODAL OPEN/CLOSE METHODS
    // =============================================================================

    /**
     * Opens the Item Collection modal for the specified alert type.
     * 
     * What: Makes the modal visible and loads saved collections
     * Why: Called when user clicks "Collection" button above an item selector
     * How: Sets currentAlertType, shows modal overlay, loads collections from API
     * 
     * @param {string} alertType - The alert type: 'spike', 'spread', 'sustained', 'threshold'
     */
    open(alertType) {
        // Store which alert type opened the modal so we know which form to update
        this.currentAlertType = alertType;
        
        // Get modal element and make it visible
        const modal = document.getElementById('item-collection-modal');
        if (modal) {
            modal.classList.add('show');
            // Prevent body scrolling while modal is open
            document.body.style.overflow = 'hidden';
        }
        
        // Load collections from server and show select view
        this.loadCollections();
        this.showSelectView();
    },

    /**
     * Closes the Item Collection modal and resets state.
     * 
     * What: Hides the modal and clears temporary state
     * Why: Called when user clicks close button or outside modal
     * How: Removes show class, resets state variables, re-enables body scroll
     */
    close() {
        const modal = document.getElementById('item-collection-modal');
        if (modal) {
            modal.classList.remove('show');
            // Re-enable body scrolling
            document.body.style.overflow = '';
        }
        
        // Reset state for next open
        this.currentAlertType = null;
        this.collectionToDelete = null;
        this.selectedItems = [];
        this.dropdownOpen = false;
        this.selectedIndex = -1;
    },

    // =============================================================================
    // VIEW SWITCHING METHODS
    // =============================================================================

    /**
     * Shows the select/browse view and hides other views.
     * 
     * What: Switches modal to the collection selection view
     * Why: This is the default view showing saved collections
     * How: Toggles 'hidden' class on view divs
     */
    showSelectView() {
        const selectView = document.getElementById('item-collection-select-view');
        const createView = document.getElementById('item-collection-create-view');
        const deleteView = document.getElementById('item-collection-delete-view');
        
        if (selectView) selectView.classList.remove('hidden');
        if (createView) createView.classList.add('hidden');
        if (deleteView) deleteView.classList.add('hidden');
        
        // Reset create view state
        this.selectedItems = [];
        this.collectionToDelete = null;
        
        // Clear create form inputs
        const nameInput = document.getElementById('collection-name-input');
        if (nameInput) nameInput.value = '';
        
        // Update the collections list display
        this.renderCollections();
    },

    /**
     * Shows the create new collection view and hides other views.
     * 
     * What: Switches modal to the collection creation view
     * Why: User wants to create a new collection
     * How: Toggles 'hidden' class, initializes create view state
     */
    showCreateView() {
        const selectView = document.getElementById('item-collection-select-view');
        const createView = document.getElementById('item-collection-create-view');
        const deleteView = document.getElementById('item-collection-delete-view');
        
        if (selectView) selectView.classList.add('hidden');
        if (createView) createView.classList.remove('hidden');
        if (deleteView) deleteView.classList.add('hidden');
        
        // Reset create view state
        this.selectedItems = [];
        this.dropdownOpen = false;
        this.selectedIndex = -1;
        
        // Clear form inputs
        const nameInput = document.getElementById('collection-name-input');
        const itemInput = document.getElementById('collection-item-input');
        if (nameInput) nameInput.value = '';
        if (itemInput) itemInput.value = '';
        
        // Initialize the item selector and update preview
        this.initCreateViewSelector();
        this.renderCreateViewSelectedItems();
        this.updatePreview();
        
        // Focus the name input
        if (nameInput) nameInput.focus();
    },

    /**
     * Shows the delete confirmation view.
     * 
     * What: Switches modal to delete confirmation view
     * Why: Requires user confirmation before deleting a collection
     * How: Stores collection ID, shows delete view with collection name
     * 
     * @param {number} collectionId - ID of collection to delete
     * @param {string} collectionName - Name of collection (for display)
     */
    showDeleteView(collectionId, collectionName) {
        const selectView = document.getElementById('item-collection-select-view');
        const createView = document.getElementById('item-collection-create-view');
        const deleteView = document.getElementById('item-collection-delete-view');
        const nameSpan = document.getElementById('delete-collection-name');
        
        if (selectView) selectView.classList.add('hidden');
        if (createView) createView.classList.add('hidden');
        if (deleteView) deleteView.classList.remove('hidden');
        
        // Store which collection is pending deletion
        this.collectionToDelete = collectionId;
        
        // Show the collection name in the confirmation message
        if (nameSpan) nameSpan.textContent = collectionName;
    },

    // =============================================================================
    // API METHODS - Server Communication
    // =============================================================================

    /**
     * Loads all saved collections from the server API.
     * 
     * What: Fetches the user's saved item collections
     * Why: Needed to populate the select view with available collections
     * How: Makes GET request to /api/item-collections/, stores result in this.collections
     */
    async loadCollections() {
        try {
            const response = await fetch('/api/item-collections/', {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });
            
            if (!response.ok) {
                throw new Error('Failed to load collections');
            }
            
            const data = await response.json();
            this.collections = data.collections || [];
            
            // Update the UI with loaded collections
            this.renderCollections();
            
        } catch (error) {
            console.error('Error loading collections:', error);
            this.collections = [];
            this.renderCollections();
        }
    },

    /**
     * Saves a new collection to the server.
     * 
     * What: Creates a new item collection with the given name and items
     * Why: Persists the collection for future use
     * How: POST to /api/item-collections/create/ with name and items
     * 
     * @param {boolean} applyAfterSave - If true, applies collection after saving
     */
    async saveCollection(applyAfterSave) {
        // Get the collection name from input
        const nameInput = document.getElementById('collection-name-input');
        const name = nameInput ? nameInput.value.trim() : '';
        
        // Validate inputs
        if (!name) {
            alert('Please enter a collection name');
            return;
        }
        
        if (this.selectedItems.length === 0) {
            alert('Please add at least one item to the collection');
            return;
        }
        
        try {
            // Prepare data for API
            const itemIds = this.selectedItems.map(item => item.id);
            const itemNames = this.selectedItems.map(item => item.name);
            
            const response = await fetch('/api/item-collections/create/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify({
                    name: name,
                    item_ids: itemIds,
                    item_names: itemNames
                })
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                alert(data.error || 'Failed to save collection');
                return;
            }
            
            // Collection saved successfully
            if (applyAfterSave) {
                // Apply the newly created collection to the form
                this.applyCollectionToForm(itemIds, itemNames);
                this.close();
            } else {
                // Reload collections and go back to select view
                await this.loadCollections();
                this.showSelectView();
            }
            
        } catch (error) {
            console.error('Error saving collection:', error);
            alert('Failed to save collection. Please try again.');
        }
    },

    /**
     * Deletes a collection after user confirmation.
     * 
     * What: Permanently removes a collection from the server
     * Why: Called when user confirms deletion in delete view
     * How: POST to /api/item-collections/{id}/delete/ with collection ID
     */
    async confirmDelete() {
        if (!this.collectionToDelete) return;
        
        try {
            const response = await fetch(`/api/item-collections/${this.collectionToDelete}/delete/`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                }
            });
            
            const data = await response.json();
            
            if (!response.ok) {
                alert(data.error || 'Failed to delete collection');
                return;
            }
            
            // Delete successful, reload collections and show select view
            this.collectionToDelete = null;
            await this.loadCollections();
            this.showSelectView();
            
        } catch (error) {
            console.error('Error deleting collection:', error);
            alert('Failed to delete collection. Please try again.');
        }
    },

    // =============================================================================
    // UI RENDERING METHODS
    // =============================================================================

    /**
     * Renders the list of saved collections in the select view.
     * 
     * What: Populates the collections list with saved collection cards
     * Why: Shows users their available collections for selection
     * How: Iterates over this.collections and generates HTML for each
     */
    renderCollections() {
        const listContainer = document.getElementById('item-collection-list');
        const emptyMessage = document.getElementById('item-collection-empty');
        const applyModeSection = document.getElementById('item-collection-apply-mode');
        
        if (!listContainer) return;
        
        // Handle empty state
        if (this.collections.length === 0) {
            listContainer.innerHTML = '';
            if (emptyMessage) emptyMessage.style.display = 'flex';
            if (applyModeSection) applyModeSection.style.display = 'none';
            return;
        }
        
        // Hide empty message, show apply mode options
        if (emptyMessage) emptyMessage.style.display = 'none';
        if (applyModeSection) applyModeSection.style.display = 'block';
        
        // Generate HTML for each collection
        // Each collection card shows: name, item count, items preview, apply/delete buttons
        listContainer.innerHTML = this.collections.map(collection => {
            // item_names is an array of item name strings
            const itemCount = collection.item_names ? collection.item_names.length : 0;
            const itemPreview = collection.item_names ? collection.item_names.slice(0, 3).join(', ') : '';
            const hasMore = itemCount > 3 ? ` +${itemCount - 3} more` : '';
            
            return `
                <div class="item-collection-card" data-collection-id="${collection.id}">
                    <div class="collection-info">
                        <div class="collection-name">${this.escapeHtml(collection.name)}</div>
                        <div class="collection-meta">
                            <span class="collection-count">${itemCount} item${itemCount !== 1 ? 's' : ''}</span>
                            <span class="collection-preview">${this.escapeHtml(itemPreview)}${hasMore}</span>
                        </div>
                    </div>
                    <div class="collection-actions">
                        <button type="button" class="collection-apply-btn" 
                            onclick="ItemCollectionManager.applyCollection(${collection.id})" 
                            title="Apply this collection">
                            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                            </svg>
                            Apply
                        </button>
                        <button type="button" class="collection-delete-btn" 
                            onclick="ItemCollectionManager.showDeleteView(${collection.id}, '${this.escapeHtml(collection.name).replace(/'/g, "\\'")}')" 
                            title="Delete this collection">
                            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                                <path fill-rule="evenodd" d="M9 2a1 1 0 00-.894.553L7.382 4H4a1 1 0 000 2v10a2 2 0 002 2h8a2 2 0 002-2V6a1 1 0 100-2h-3.382l-.724-1.447A1 1 0 0011 2H9zM7 8a1 1 0 012 0v6a1 1 0 11-2 0V8zm5-1a1 1 0 00-1 1v6a1 1 0 102 0V8a1 1 0 00-1-1z" clip-rule="evenodd"/>
                            </svg>
                        </button>
                    </div>
                </div>
            `;
        }).join('');
    },

    /**
     * Renders the selected items list in the create view dropdown.
     * 
     * What: Updates the dropdown showing items added to the new collection
     * Why: Provides visual feedback of selected items with remove option
     * How: Generates HTML for each item with red X remove button
     */
    renderCreateViewSelectedItems() {
        const selectedList = document.getElementById('collection-selected-items-list');
        const noItemsMsg = document.getElementById('collection-no-items-message');
        
        if (!selectedList) return;
        
        if (this.selectedItems.length === 0) {
            selectedList.innerHTML = '';
            if (noItemsMsg) noItemsMsg.classList.add('show');
        } else {
            if (noItemsMsg) noItemsMsg.classList.remove('show');
            selectedList.innerHTML = this.selectedItems.map(item =>
                `<div class="selected-item-row">
                    <span class="item-name">${this.escapeHtml(item.name)}</span>
                    <button type="button" class="remove-item-btn" data-id="${item.id}" title="Remove ${this.escapeHtml(item.name)}">×</button>
                </div>`
            ).join('');
        }
    },

    /**
     * Updates the items preview card in the create view.
     * 
     * What: Shows a scrollable preview of all items that will be in the collection
     * Why: User requested visual preview before saving
     * How: Updates preview card with item count and list of item names with remove buttons
     */
    updatePreview() {
        const previewCount = document.getElementById('collection-preview-count');
        const previewList = document.getElementById('collection-preview-list');
        
        if (previewCount) {
            const count = this.selectedItems.length;
            previewCount.textContent = `${count} item${count !== 1 ? 's' : ''}`;
        }
        
        if (previewList) {
            if (this.selectedItems.length === 0) {
                previewList.innerHTML = '<div class="preview-empty">No items added yet</div>';
            } else {
                // Each preview item has a name span and a red X remove button
                previewList.innerHTML = this.selectedItems.map(item =>
                    `<div class="preview-item" data-item-id="${item.id}">
                        <span class="preview-item-name">${this.escapeHtml(item.name)}</span>
                        <button type="button" class="preview-item-remove" data-id="${item.id}" title="Remove ${this.escapeHtml(item.name)}">×</button>
                    </div>`
                ).join('');
            }
        }
    },
    
    /**
     * Removes an item from the create view by ID.
     * 
     * What: Removes item from selectedItems array and updates all UI elements
     * Why: Called when user clicks red X in either dropdown or preview card
     * How: Filters selectedItems, re-renders dropdown and preview
     * 
     * @param {string|number} itemId - ID of item to remove
     */
    removeItemFromCreate(itemId) {
        const itemToRemove = this.selectedItems.find(item => String(item.id) === String(itemId));
        const itemName = itemToRemove ? itemToRemove.name : 'Item';
        
        // Filter out the item
        this.selectedItems = this.selectedItems.filter(item => String(item.id) !== String(itemId));
        
        // Update both the dropdown and preview
        this.renderCreateViewSelectedItems();
        this.updatePreview();
        
        // Show notification
        this.showCreateNotification(`${itemName} removed`, 'success');
    },

    // =============================================================================
    // CREATE VIEW ITEM SELECTOR
    // =============================================================================

    /**
     * Initializes the multi-item selector in the create view.
     * 
     * What: Sets up event listeners for the item search and selection
     * Why: Enables autocomplete, dropdown toggle, and item management
     * How: Attaches input, keydown, click handlers matching existing selector pattern
     */
    initCreateViewSelector() {
        const input = document.getElementById('collection-item-input');
        const dropdown = document.getElementById('collection-item-suggestions');
        const selectedDropdown = document.getElementById('collection-selected-items-dropdown');
        const selectedList = document.getElementById('collection-selected-items-list');
        const toggleBtn = document.getElementById('collection-multi-item-toggle');
        const selectorBox = input ? input.closest('.multi-item-selector-box') : null;
        
        if (!input || !dropdown || !selectedDropdown) return;
        
        // Reference to 'this' for use inside closures
        const self = this;
        
        // Remove old event listeners by cloning and replacing elements
        const newInput = input.cloneNode(true);
        input.parentNode.replaceChild(newInput, input);
        
        if (toggleBtn) {
            const newToggle = toggleBtn.cloneNode(true);
            toggleBtn.parentNode.replaceChild(newToggle, toggleBtn);
        }
        
        // Get fresh references after cloning
        const freshInput = document.getElementById('collection-item-input');
        const freshToggle = document.getElementById('collection-multi-item-toggle');
        const freshDropdown = document.getElementById('collection-item-suggestions');
        const freshSelectedDropdown = document.getElementById('collection-selected-items-dropdown');
        const freshSelectedList = document.getElementById('collection-selected-items-list');
        const freshSelectorBox = freshInput ? freshInput.closest('.multi-item-selector-box') : null;
        
        /**
         * Adds an item to the selected list for the new collection.
         * 
         * What: Adds item to selectedItems array and updates UI
         * Why: Central function for adding items from autocomplete
         * How: Checks duplicates, adds to array, updates dropdown and preview
         * 
         * @param {string} id - Item's unique identifier
         * @param {string} name - Item's display name
         */
        const addItem = (id, name) => {
            // Check for duplicates
            if (self.selectedItems.some(item => String(item.id) === String(id))) {
                self.showCreateNotification(`${name} is already selected`, 'error');
                return;
            }
            
            self.selectedItems.push({id, name});
            self.renderCreateViewSelectedItems();
            self.updatePreview();
            freshInput.value = '';
            freshDropdown.style.display = 'none';
            self.selectedIndex = -1;
            
            self.showCreateNotification(`${name} added`, 'success');
        };
        
        /**
         * Removes an item from the selected list.
         * 
         * @param {string} id - Item's unique identifier to remove
         */
        const removeItem = (id) => {
            const itemToRemove = self.selectedItems.find(item => String(item.id) === String(id));
            const itemName = itemToRemove ? itemToRemove.name : 'Item';
            self.selectedItems = self.selectedItems.filter(item => String(item.id) !== String(id));
            self.renderCreateViewSelectedItems();
            self.updatePreview();
            
            self.showCreateNotification(`${itemName} removed`, 'success');
        };
        
        /**
         * Updates visual selection state in autocomplete dropdown.
         */
        const updateSelection = () => {
            const items = freshDropdown.querySelectorAll('.suggestion-item');
            items.forEach((item, index) => {
                if (index === self.selectedIndex) {
                    item.classList.add('selected');
                    item.scrollIntoView({block: 'nearest'});
                } else {
                    item.classList.remove('selected');
                }
            });
        };
        
        // Handle remove button clicks in selected items dropdown
        if (freshSelectedList) {
            freshSelectedList.addEventListener('click', function(e) {
                if (e.target.classList.contains('remove-item-btn')) {
                    e.preventDefault();
                    e.stopPropagation();
                    const itemId = e.target.dataset.id;
                    removeItem(itemId);
                }
            });
        }
        
        // Handle remove button clicks in preview list (event delegation)
        // What: Allows removing items directly from the preview card
        // Why: User wants to remove items from preview without using the dropdown
        // How: Uses event delegation to handle clicks on dynamically generated buttons
        const previewList = document.getElementById('collection-preview-list');
        if (previewList) {
            previewList.addEventListener('click', function(e) {
                if (e.target.classList.contains('preview-item-remove')) {
                    e.preventDefault();
                    e.stopPropagation();
                    const itemId = e.target.dataset.id;
                    removeItem(itemId);
                }
            });
        }
        
        // Handle dropdown toggle button clicks
        if (freshToggle) {
            freshToggle.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                
                // Close autocomplete suggestions if open
                freshDropdown.style.display = 'none';
                self.selectedIndex = -1;
                
                // Toggle selected items dropdown
                self.dropdownOpen = !self.dropdownOpen;
                if (self.dropdownOpen) {
                    freshSelectedDropdown.classList.add('show');
                    freshToggle.classList.add('active');
                } else {
                    freshSelectedDropdown.classList.remove('show');
                    freshToggle.classList.remove('active');
                }
            });
        }
        
        // Close dropdowns when clicking outside (within modal)
        const modal = document.getElementById('item-collection-modal');
        if (modal) {
            modal.addEventListener('click', (e) => {
                if (freshSelectorBox && !freshSelectorBox.contains(e.target)) {
                    // Close selected items dropdown
                    if (self.dropdownOpen) {
                        freshSelectedDropdown.classList.remove('show');
                        if (freshToggle) freshToggle.classList.remove('active');
                        self.dropdownOpen = false;
                    }
                    // Close autocomplete suggestions
                    freshDropdown.style.display = 'none';
                    self.selectedIndex = -1;
                }
            });
        }
        
        // Handle input changes - fetch suggestions
        freshInput.addEventListener('input', async () => {
            const query = freshInput.value;
            
            // Close selected items dropdown when typing
            if (self.dropdownOpen) {
                freshSelectedDropdown.classList.remove('show');
                if (freshToggle) freshToggle.classList.remove('active');
                self.dropdownOpen = false;
            }
            
            // Minimum 2 characters to search
            if (query.length < 2) {
                freshDropdown.style.display = 'none';
                self.selectedIndex = -1;
                return;
            }
            
            // Use AlertsAPI to search items
            const items = await AlertsAPI.searchItems(query);
            
            // Filter out already selected items
            const filteredItems = items.filter(item =>
                !self.selectedItems.some(selected => String(selected.id) === String(item.id))
            );
            
            if (filteredItems.length > 0) {
                freshDropdown.innerHTML = AlertsUI.renderSuggestions(filteredItems);
                freshDropdown.style.display = 'block';
                self.selectedIndex = -1;
            } else {
                freshDropdown.style.display = 'none';
                self.selectedIndex = -1;
            }
        });
        
        // Handle keyboard navigation
        freshInput.addEventListener('keydown', (e) => {
            if (freshDropdown.style.display === 'none') {
                // Backspace with empty input removes last item
                if (e.key === 'Backspace' && freshInput.value === '' && self.selectedItems.length > 0) {
                    const lastItem = self.selectedItems[self.selectedItems.length - 1];
                    removeItem(lastItem.id);
                }
                return;
            }
            
            const items = freshDropdown.querySelectorAll('.suggestion-item');
            if (items.length === 0) return;
            
            switch (e.key) {
                case 'ArrowDown':
                    e.preventDefault();
                    self.selectedIndex = (self.selectedIndex + 1) % items.length;
                    updateSelection();
                    break;
                    
                case 'ArrowUp':
                    e.preventDefault();
                    self.selectedIndex = self.selectedIndex <= 0
                        ? items.length - 1
                        : self.selectedIndex - 1;
                    updateSelection();
                    break;
                    
                case 'Tab':
                    e.preventDefault();
                    if (e.shiftKey) {
                        self.selectedIndex = self.selectedIndex <= 0
                            ? items.length - 1
                            : self.selectedIndex - 1;
                    } else {
                        self.selectedIndex = (self.selectedIndex + 1) % items.length;
                    }
                    updateSelection();
                    break;
                    
                case 'Enter':
                    if (self.selectedIndex >= 0) {
                        e.preventDefault();
                        const selectedItem = items[self.selectedIndex];
                        addItem(selectedItem.dataset.id, selectedItem.dataset.name);
                    }
                    break;
                    
                case 'Escape':
                    e.preventDefault();
                    freshDropdown.style.display = 'none';
                    self.selectedIndex = -1;
                    break;
            }
        });
        
        // Handle mouse click on suggestion
        freshDropdown.addEventListener('click', (e) => {
            if (e.target.classList.contains('suggestion-item')) {
                addItem(e.target.dataset.id, e.target.dataset.name);
            }
        });
        
        // Handle mouse hover to update selection
        freshDropdown.addEventListener('mouseover', (e) => {
            if (e.target.classList.contains('suggestion-item')) {
                const items = freshDropdown.querySelectorAll('.suggestion-item');
                items.forEach((item, index) => {
                    if (item === e.target) {
                        self.selectedIndex = index;
                    }
                });
                updateSelection();
            }
        });
    },

    /**
     * Shows a notification in the create view.
     * 
     * What: Displays success/error feedback for item add/remove
     * Why: Immediate visual feedback without disruptive popups
     * How: Updates notification span with text and class
     * 
     * @param {string} message - The notification message
     * @param {string} type - 'success' or 'error'
     */
    showCreateNotification(message, type) {
        const notification = document.getElementById('collection-item-notification');
        if (!notification) return;
        
        // Clear any existing timeout
        if (this.notificationTimeout) {
            clearTimeout(this.notificationTimeout);
        }
        
        // Set message and styling
        notification.textContent = message;
        notification.className = 'item-notification ' + type + ' show';
        
        // Auto-hide after delay
        this.notificationTimeout = setTimeout(() => {
            notification.classList.remove('show');
        }, 2000);
    },

    // =============================================================================
    // COLLECTION APPLICATION METHODS
    // =============================================================================

    /**
     * Applies a saved collection to the alert form.
     * 
     * What: Takes a collection's items and adds them to the current alert's item selector
     * Why: Main feature - quickly populate alert with pre-defined item group
     * How: Gets apply mode (merge/replace), finds collection, calls applyCollectionToForm
     * 
     * @param {number} collectionId - ID of the collection to apply
     */
    applyCollection(collectionId) {
        // Find the collection
        const collection = this.collections.find(c => c.id === collectionId);
        if (!collection) {
            alert('Collection not found');
            return;
        }
        
        // Apply to form and close modal
        this.applyCollectionToForm(collection.item_ids, collection.item_names);
        this.close();
    },

    /**
     * Applies item IDs and names to the current alert type's form.
     * 
     * What: Updates the appropriate multi-item selector with collection items
     * Why: Actually populates the form with the collection data
     * How: Based on currentAlertType, finds the right selector and updates its internal state
     *      IMPORTANT: Must update both the selector's selectedItems array AND the DOM
     *      to ensure remove functionality works correctly after applying
     * 
     * @param {Array<number>} itemIds - Array of item IDs
     * @param {Array<string>} itemNames - Array of item names
     */
    applyCollectionToForm(itemIds, itemNames) {
        if (!this.currentAlertType || !itemIds || !itemNames) return;
        
        // Get the apply mode (merge or replace)
        const modeInput = document.querySelector('input[name="apply-mode"]:checked');
        const mode = modeInput ? modeInput.value : 'merge';
        
        // Map alert type to the appropriate selector object and elements
        // IMPORTANT: The actual selector object names in alerts-selectors.js are:
        // - SpikeMultiItemSelector (not SpikeItemSelector)
        // - SpreadMultiItemSelector (not SpreadItemSelector)
        // - MultiItemSelector (for sustained)
        // - ThresholdMultiItemSelector (not ThresholdItemSelector)
        const selectorMap = {
            'spike': {
                selector: typeof SpikeMultiItemSelector !== 'undefined' ? SpikeMultiItemSelector : null,
                hiddenInput: '#spike-item-ids',
                selectedList: '#spike-selected-items-list',
                noItemsMsg: '#spike-no-items-message',
                notification: '#spike-item-notification'
            },
            'spread': {
                selector: typeof SpreadMultiItemSelector !== 'undefined' ? SpreadMultiItemSelector : null,
                hiddenInput: '#spread-item-ids',
                selectedList: '#spread-selected-items-list',
                noItemsMsg: '#spread-no-items-message',
                notification: '#spread-item-notification'
            },
            'sustained': {
                selector: typeof MultiItemSelector !== 'undefined' ? MultiItemSelector : null,
                hiddenInput: '#sustained-item-ids',
                selectedList: '#sustained-selected-items-list',
                noItemsMsg: '#sustained-no-items-message',
                notification: '#sustained-item-notification'
            },
            'threshold': {
                selector: typeof ThresholdMultiItemSelector !== 'undefined' ? ThresholdMultiItemSelector : null,
                hiddenInput: '#threshold-item-ids',
                selectedList: '#threshold-selected-items-list',
                noItemsMsg: '#threshold-no-items-message',
                notification: '#threshold-item-notification'
            }
        };
        
        const config = selectorMap[this.currentAlertType];
        if (!config) return;
        
        // Get the selector object
        const selector = config.selector;
        const hiddenInput = document.querySelector(config.hiddenInput);
        const selectedList = document.querySelector(config.selectedList);
        const noItemsMsg = document.querySelector(config.noItemsMsg);
        const notification = document.querySelector(config.notification);
        
        if (!hiddenInput) return;
        
        // Build items array from ids and names
        const newItems = itemIds.map((id, index) => ({
            id: id,
            name: itemNames[index] || `Item ${id}`
        }));
        
        // Get existing items from selector or hidden input
        let existingItems = [];
        if (selector && Array.isArray(selector.selectedItems)) {
            existingItems = [...selector.selectedItems];
        } else if (hiddenInput.value) {
            // Reconstruct from hidden input and DOM
            const existingIds = hiddenInput.value.split(',').filter(id => id);
            existingIds.forEach(existingId => {
                const existingRow = selectedList ? selectedList.querySelector(`[data-id="${existingId}"]`) : null;
                let existingName = `Item ${existingId}`;
                if (existingRow) {
                    const nameSpan = existingRow.closest('.selected-item-row');
                    if (nameSpan) {
                        const nameEl = nameSpan.querySelector('.item-name');
                        if (nameEl) existingName = nameEl.textContent;
                    }
                }
                existingItems.push({ id: existingId, name: existingName });
            });
        }
        
        // Calculate final items based on mode
        let finalItems;
        if (mode === 'replace') {
            // Replace: Use only new items
            finalItems = [...newItems];
        } else {
            // Merge: Start with existing items, add new ones that don't exist
            finalItems = [...existingItems];
            newItems.forEach(newItem => {
                if (!finalItems.some(existing => String(existing.id) === String(newItem.id))) {
                    finalItems.push(newItem);
                }
            });
        }
        
        // CRITICAL: Update the selector's internal selectedItems array
        // This ensures remove functionality works correctly after applying
        // The selector's removeItem function uses this.selectedItems internally
        if (selector) {
            selector.selectedItems = [...finalItems];
        }
        
        // Update hidden input with final item IDs
        hiddenInput.value = finalItems.map(item => item.id).join(',');
        
        // Use the selector's renderSelectedItems method if available
        // This ensures the DOM is rendered consistently with how the selector does it
        if (selector && typeof selector.renderSelectedItems === 'function') {
            selector.renderSelectedItems();
        } else if (selectedList) {
            // Fallback: render directly if selector not available
            if (finalItems.length === 0) {
                selectedList.innerHTML = '';
                if (noItemsMsg) noItemsMsg.classList.add('show');
            } else {
                if (noItemsMsg) noItemsMsg.classList.remove('show');
                selectedList.innerHTML = finalItems.map(item =>
                    `<div class="selected-item-row">
                        <span class="item-name">${this.escapeHtml(item.name)}</span>
                        <button type="button" class="remove-item-btn" data-id="${item.id}" title="Remove ${this.escapeHtml(item.name)}">×</button>
                    </div>`
                ).join('');
            }
        }
        
        // Show success notification
        if (notification) {
            const count = newItems.length;
            notification.textContent = mode === 'replace' 
                ? `${count} item${count !== 1 ? 's' : ''} applied` 
                : `${count} item${count !== 1 ? 's' : ''} merged`;
            notification.className = 'item-notification success show';
            setTimeout(() => notification.classList.remove('show'), 2000);
        }
    },

    // =============================================================================
    // UTILITY METHODS
    // =============================================================================

    /**
     * Escapes HTML special characters to prevent XSS.
     * 
     * What: Converts < > & " ' to HTML entities
     * Why: User input (collection names, item names) must be escaped before display
     * How: Uses regex replacement for each special character
     * 
     * @param {string} text - Text to escape
     * @returns {string} Escaped text safe for HTML insertion
     */
    escapeHtml(text) {
        if (!text) return '';
        return String(text)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }
};

// =============================================================================
// MODAL CLOSE ON OVERLAY CLICK
// =============================================================================
// What: Closes the modal when user clicks outside the modal content
// Why: Standard modal UX pattern for easy dismissal
// How: Listens for clicks on overlay, checks if target is the overlay itself
document.addEventListener('DOMContentLoaded', () => {
    const modal = document.getElementById('item-collection-modal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            // Only close if clicking the overlay itself, not the modal content
            if (e.target === modal) {
                ItemCollectionManager.close();
            }
        });
    }
});
