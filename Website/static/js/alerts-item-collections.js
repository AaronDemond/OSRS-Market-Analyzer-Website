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
     * Valid values: 'spike', 'spread', 'sustained', 'threshold', 'collective_move'
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
    
    /**
     * editingCollectionId: ID of collection currently being edited, or null if creating new
     * What: Tracks which collection is being edited (if any)
     * Why: When saving, we need to know whether to call create or update API
     * How: Set when user clicks Edit on a collection, cleared when creating new
     */
    editingCollectionId: null,

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
     * @param {string} alertType - The alert type: 'spike', 'spread', 'sustained', 'threshold', 'collective_move'
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
        const createViewHeader = document.getElementById('create-view-header');
        
        if (selectView) selectView.classList.add('hidden');
        if (createView) createView.classList.remove('hidden');
        if (deleteView) deleteView.classList.add('hidden');
        
        // Reset create view state - this is a new collection, not editing
        // editingCollectionId: Set to null because we're creating, not editing
        this.editingCollectionId = null;
        this.selectedItems = [];
        this.dropdownOpen = false;
        this.selectedIndex = -1;
        
        // Update header to reflect create mode
        // What: Change header text to indicate creating new collection
        // Why: Same view is used for create and edit, so header must reflect current mode
        if (createViewHeader) createViewHeader.textContent = 'Create New Collection';
        
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
     * Shows the edit collection view (same UI as create but pre-filled).
     * 
     * What: Opens the create/edit view with existing collection data loaded
     * Why: User wants to modify an existing collection's items or name
     * How: Find collection by ID, populate form fields, set editing state
     * 
     * @param {number} collectionId - ID of the collection to edit
     */
    showEditView(collectionId) {
        // Find the collection in our loaded collections array
        // collection: The ItemCollection object to edit, or undefined if not found
        const collection = this.collections.find(c => c.id === collectionId);
        if (!collection) {
            alert('Collection not found');
            return;
        }
        
        console.log('=== showEditView called ===');
        console.log('Collection ID:', collectionId);
        console.log('Collection data:', JSON.stringify(collection));
        
        const selectView = document.getElementById('item-collection-select-view');
        const createView = document.getElementById('item-collection-create-view');
        const deleteView = document.getElementById('item-collection-delete-view');
        const createViewHeader = document.getElementById('create-view-header');
        
        if (selectView) selectView.classList.add('hidden');
        if (createView) createView.classList.remove('hidden');
        if (deleteView) deleteView.classList.add('hidden');
        
        // Set editing state - we're editing an existing collection
        // editingCollectionId: Store the ID so saveCollection knows to call update API
        this.editingCollectionId = collectionId;
        this.dropdownOpen = false;
        this.selectedIndex = -1;
        
        // Update header to reflect edit mode
        // What: Change header text to indicate editing existing collection
        // Why: Same view is used for create and edit, so header must reflect current mode
        if (createViewHeader) createViewHeader.textContent = 'Edit Collection';
        
        // Pre-populate the name input with the collection's current name
        const nameInput = document.getElementById('collection-name-input');
        if (nameInput) nameInput.value = collection.name || '';
        
        // Pre-populate selectedItems array with the collection's current items
        // What: Build selectedItems array from collection's item_ids and item_names
        // Why: The item selector uses this.selectedItems to track what's in the collection
        // How: Map item_ids and item_names arrays into {id, name} objects
        this.selectedItems = [];
        if (collection.item_ids && collection.item_names) {
            for (let i = 0; i < collection.item_ids.length; i++) {
                this.selectedItems.push({
                    id: collection.item_ids[i],
                    name: collection.item_names[i] || `Item ${collection.item_ids[i]}`
                });
            }
        }
        
        console.log('selectedItems after populating:', JSON.stringify(this.selectedItems));
        
        // Clear the item search input
        const itemInput = document.getElementById('collection-item-input');
        if (itemInput) itemInput.value = '';
        
        // Initialize the item selector and update displays
        // What: Set up event listeners and render current items
        // Why: Need to show existing items and allow adding/removing
        this.initCreateViewSelector();
        this.renderCreateViewSelectedItems();
        this.updatePreview();
        
        console.log('selectedItems after initCreateViewSelector:', JSON.stringify(this.selectedItems));
        
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
        console.log('=== loadCollections called ===');
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
            console.log('loadCollections response:', JSON.stringify(data));
            this.collections = data.collections || [];
            console.log('this.collections after load:', JSON.stringify(this.collections));
            
            // Update the UI with loaded collections
            this.renderCollections();
            
        } catch (error) {
            console.error('Error loading collections:', error);
            this.collections = [];
            this.renderCollections();
        }
    },

    /**
     * Saves a collection to the server (create new or update existing).
     * 
     * What: Creates a new item collection or updates an existing one
     * Why: Persists the collection for future use
     * How: Check if editingCollectionId is set - if so, call update API; otherwise create API
     * 
     * Note: The applyAfterSave parameter is no longer used (removed "Save & Apply" button)
     *       but kept for backwards compatibility. Always goes back to select view after save.
     * 
     * @param {boolean} applyAfterSave - DEPRECATED: No longer used, always false
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
        
        console.log('=== saveCollection called ===');
        console.log('this.selectedItems at save time:', JSON.stringify(this.selectedItems));
        console.log('this.selectedItems.length:', this.selectedItems.length);
        
        if (this.selectedItems.length === 0) {
            alert('Please add at least one item to the collection');
            return;
        }
        
        try {
            // Prepare data for API
            // itemIds: Array of integer item IDs to save
            // itemNames: Array of string item names to save
            const itemIds = this.selectedItems.map(item => item.id);
            const itemNames = this.selectedItems.map(item => item.name);
            
            console.log('itemIds to send:', JSON.stringify(itemIds));
            console.log('itemNames to send:', JSON.stringify(itemNames));
            console.log('editingCollectionId:', this.editingCollectionId);
            
            // Determine API endpoint based on whether we're editing or creating
            // What: Choose between create and update API endpoint
            // Why: If editingCollectionId is set, we're updating an existing collection
            // How: Build URL dynamically based on editingCollectionId
            let url;
            if (this.editingCollectionId) {
                // Update existing collection
                url = `/api/item-collections/${this.editingCollectionId}/update/`;
            } else {
                // Create new collection
                url = '/api/item-collections/create/';
            }
            
            console.log('URL:', url);
            
            const requestBody = {
                name: name,
                item_ids: itemIds,
                item_names: itemNames
            };
            console.log('Request body:', JSON.stringify(requestBody));
            
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': window.CSRF_TOKEN
                },
                body: JSON.stringify(requestBody)
            });
            
            const data = await response.json();
            console.log('Response:', JSON.stringify(data));
            
            if (!response.ok) {
                alert(data.error || 'Failed to save collection');
                return;
            }
            
            // Collection saved successfully
            // Always reload collections and go back to select view
            // (Save & Apply was removed per user request)
            await this.loadCollections();
            this.showSelectView();
            
            // Clear editing state after successful save
            this.editingCollectionId = null;
            
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
        // Each collection card shows: name, item count, items preview, apply/edit/delete buttons
        listContainer.innerHTML = this.collections.map(collection => {
            // item_names is an array of item name strings
            const itemCount = collection.item_names ? collection.item_names.length : 0;
            
            return `
                <div class="item-collection-card" data-collection-id="${collection.id}">
                    <div class="collection-info">
                        <div class="collection-name">${this.escapeHtml(collection.name)}</div>
                    </div>
                    <div class="collection-actions">
                        <span class="collection-count">${itemCount} item${itemCount !== 1 ? 's' : ''}</span>
                        <button type="button" class="collection-apply-btn" 
                            onclick="ItemCollectionManager.applyCollection(${collection.id})" 
                            title="Apply this collection">
                            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                                <path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/>
                            </svg>
                            Apply
                        </button>
                        <button type="button" class="collection-edit-btn" 
                            onclick="ItemCollectionManager.showEditView(${collection.id})" 
                            title="Edit this collection">
                            <svg viewBox="0 0 20 20" fill="currentColor" width="16" height="16">
                                <path d="M13.586 3.586a2 2 0 112.828 2.828l-.793.793-2.828-2.828.793-.793zM11.379 5.793L3 14.172V17h2.828l8.38-8.379-2.83-2.828z"/>
                            </svg>
                            Edit
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
        let freshSelectedList = document.getElementById('collection-selected-items-list');
        const freshSelectorBox = freshInput ? freshInput.closest('.multi-item-selector-box') : null;
        
        // Clone and replace selectedList to remove old event listeners
        // What: Prevents duplicate event listeners from accumulating
        // Why: initCreateViewSelector() is called multiple times (each create/edit)
        // How: Clone the element, replace it, get fresh reference
        if (freshSelectedList) {
            const newSelectedList = freshSelectedList.cloneNode(true);
            freshSelectedList.parentNode.replaceChild(newSelectedList, freshSelectedList);
            freshSelectedList = document.getElementById('collection-selected-items-list');
        }
        
        // Clone and replace previewList to remove old event listeners
        // What: Prevents duplicate event listeners from accumulating
        // Why: initCreateViewSelector() is called multiple times (each create/edit)
        // How: Clone the element, replace it, get fresh reference
        let previewList = document.getElementById('collection-preview-list');
        if (previewList) {
            const newPreviewList = previewList.cloneNode(true);
            previewList.parentNode.replaceChild(newPreviewList, previewList);
            previewList = document.getElementById('collection-preview-list');
        }
        
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
            console.log('=== removeItem called ===');
            console.log('Item ID to remove:', id);
            console.log('selectedItems BEFORE removal:', JSON.stringify(self.selectedItems));
            
            const itemToRemove = self.selectedItems.find(item => String(item.id) === String(id));
            const itemName = itemToRemove ? itemToRemove.name : 'Item';
            
            console.log('Item found to remove:', itemToRemove);
            
            self.selectedItems = self.selectedItems.filter(item => String(item.id) !== String(id));
            
            console.log('selectedItems AFTER removal:', JSON.stringify(self.selectedItems));
            
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
        
        console.log('=== Adding event listeners ===');
        console.log('freshSelectedList exists:', !!freshSelectedList);
        console.log('previewList exists:', !!previewList);
        
        // Handle remove button clicks in selected items dropdown
        if (freshSelectedList) {
            console.log('Adding click listener to freshSelectedList');
            freshSelectedList.addEventListener('click', function(e) {
                console.log('freshSelectedList click event fired');
                console.log('e.target:', e.target);
                console.log('e.target.classList:', e.target.classList.toString());
                if (e.target.classList.contains('remove-item-btn')) {
                    e.preventDefault();
                    e.stopPropagation();
                    const itemId = e.target.dataset.id;
                    console.log('Calling removeItem from freshSelectedList with id:', itemId);
                    removeItem(itemId);
                }
            });
        }
        
        // Handle remove button clicks in preview list (event delegation)
        // What: Allows removing items directly from the preview card
        // Why: User wants to remove items from preview without using the dropdown
        // How: Uses event delegation to handle clicks on dynamically generated buttons
        // Note: previewList was already cloned and replaced above to remove old listeners
        if (previewList) {
            console.log('Adding click listener to previewList');
            previewList.addEventListener('click', function(e) {
                console.log('previewList click event fired');
                console.log('e.target:', e.target);
                console.log('e.target.classList:', e.target.classList.toString());
                if (e.target.classList.contains('preview-item-remove')) {
                    e.preventDefault();
                    e.stopPropagation();
                    const itemId = e.target.dataset.id;
                    console.log('Calling removeItem from previewList with id:', itemId);
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
     * What: Displays a compact success/error label for item add/remove
     * Why: Long item names can overflow adjacent form labels, so the label must stay short
     * How: Ignores the detailed message for display and renders a fixed "success" or "error" label
     *      while keeping the existing color classes and auto-hide timing intact
     * 
     * @param {string} message - Original message (retained for compatibility, not displayed)
     * @param {string} type - 'success' or 'error'
     */
    showCreateNotification(message, type) {
        const notification = document.getElementById('collection-item-notification');
        if (!notification) return;
        
        // Clear any existing timeout
        if (this.notificationTimeout) {
            clearTimeout(this.notificationTimeout);
        }
        
        // Determine the compact label we will actually display in the UI
        // What: Normalize the message to a fixed "success" or "error" label
        // Why: Prevents long item names from spilling into adjacent form labels
        // How: Treat any non-error type as "success" and preserve "error" for failures
        // normalizedType: The final label used for both the text and CSS class
        const normalizedType = type === 'error' ? 'error' : 'success';

        // Set the compact label and styling
        // What: Apply the normalized label and matching class to the notification
        // Why: Keeps the UI short while preserving the existing color coding
        // How: Use normalizedType for both textContent and className
        notification.textContent = normalizedType;
        notification.className = 'item-notification ' + normalizedType + ' show';
        
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
        // - CollectiveMoveMultiItemSelector (for collective_move)
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
            },
            'collective_move': {
                // CollectiveMoveMultiItemSelector: Selector for collective move alert type
                // What: Maps collective_move alert type to its multi-item selector
                // Why: Allows applying item collections to collective move alerts
                // How: References the CollectiveMoveMultiItemSelector object defined in alerts-selectors.js
                selector: typeof CollectiveMoveMultiItemSelector !== 'undefined' ? CollectiveMoveMultiItemSelector : null,
                hiddenInput: '#collective-item-ids',
                selectedList: '#collective-selected-items-list',
                noItemsMsg: '#collective-no-items-message',
                notification: '#collective-item-notification'
            },
            'flip_confidence': {
                // ConfidenceMultiItemSelector: Selector for flip confidence alert type
                // What: Maps flip_confidence alert type to its multi-item selector
                // Why: Allows applying item collections to flip confidence alerts
                // How: References the ConfidenceMultiItemSelector object defined in alerts-selectors.js
                selector: typeof ConfidenceMultiItemSelector !== 'undefined' ? ConfidenceMultiItemSelector : null,
                hiddenInput: '#confidence-item-ids',
                selectedList: '#confidence-selected-items-list',
                noItemsMsg: '#confidence-no-items-message',
                notification: '#confidence-item-notification'
            },
            'dump': {
                // DumpMultiItemSelector: Selector for dump alert type
                // What: Maps dump alert type to its multi-item selector
                // Why: Allows applying item collections to dump alerts
                // How: References the DumpMultiItemSelector object defined in alerts-selectors.js
                selector: typeof DumpMultiItemSelector !== 'undefined' ? DumpMultiItemSelector : null,
                hiddenInput: '#dump-item-ids',
                selectedList: '#dump-selected-items-list',
                noItemsMsg: '#dump-no-items-message',
                notification: '#dump-item-notification'
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
        // What: Synchronizes the selector's in-memory item list with the collection result
        // Why: The selector's removeItem logic relies on selectedItems, and we need the
        //      correct item count to drive threshold type locking/unlocking behavior
        // How: Replace the selector's selectedItems array with the merged/replaced finalItems
        // selector: The multi-item selector instance for the current alert type
        if (selector) {
            selector.selectedItems = [...finalItems];
        }
        
        // Update hidden input with final item IDs
        // What: Stores the final item ID list for form submission
        // Why: The backend expects a comma-separated list of IDs for the alert items
        // How: Join the finalItems array IDs into a single comma-delimited string
        // hiddenInput: The hidden field tied to the alert form for item IDs
        hiddenInput.value = finalItems.map(item => item.id).join(',');
        
        // Use the selector's renderSelectedItems method if available
        // This ensures the DOM is rendered consistently with how the selector does it
        // selector: The selector instance that knows how to render its own item list UI
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

        // =============================================================================
        // THRESHOLD TYPE LOCK STATE SYNC (COLLECTION APPLY)
        // =============================================================================
        // What: Re-evaluate threshold type locking after applying a collection
        // Why: Applying a collection can change the item count without using the normal
        //      add/remove handlers, so we must re-run the lock/unlock logic to ensure
        //      percentage-only mode is enforced for multiple items and unlocked for 0/1
        // How: If the current alert type is threshold, call the existing FormManager
        //      updateThresholdTypeState helper, which uses the selector item count
        //      to enable/disable the dropdown and show/hide the 🚫 indicator + tooltip
        if (this.currentAlertType === 'threshold' && typeof FormManager !== 'undefined') {
            FormManager.updateThresholdTypeState();
        }
        
        // Show success notification
        // What: Display a compact success label after applying a collection
        // Why: Prevents long messages from overflowing the form label area
        // How: Use a fixed "success" label while keeping existing styling/timing
        if (notification) {
            notification.textContent = 'success';
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
