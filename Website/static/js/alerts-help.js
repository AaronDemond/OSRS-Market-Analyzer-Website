    function openAlertHelpModal() {
        const modal = document.getElementById('alertHelpModal');
        modal.classList.add('open');
        document.body.style.overflow = 'hidden';

        // Switch to the currently selected alert type
        const alertType = document.getElementById('alert-type').value;
        switchHelpTab(alertType);
    }

    function closeAlertHelpModal() {
        const modal = document.getElementById('alertHelpModal');
        modal.classList.remove('open');
        document.body.style.overflow = '';
    }

    function switchHelpTab(tabName) {
        // Update tabs
        document.querySelectorAll('.alert-help-tab').forEach(tab => {
            tab.classList.toggle('active', tab.dataset.helpTab === tabName);
        });

        // Update sections
        document.querySelectorAll('.alert-help-section').forEach(section => {
            section.classList.toggle('active', section.dataset.helpSection === tabName);
        });
    }

    // Tab click handlers
    document.querySelectorAll('.alert-help-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            switchHelpTab(tab.dataset.helpTab);
        });
    });

    // Close on overlay click
    document.getElementById('alertHelpModal').addEventListener('click', (e) => {
        if (e.target.classList.contains('alert-help-modal-overlay')) {
            closeAlertHelpModal();
        }
    });

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            closeAlertHelpModal();
        }
    });

    // =============================================================================
    // NEW GROUP MODAL FUNCTIONS
    // What: Functions for the "Create New Group" modal triggered by the "+" button
    // Why: Users need a way to create groups inline while creating an alert
    // How: Opens modal, handles input, creates group, updates AlertsState and dropdown
    // =============================================================================
    
    /**
     * Opens the modal for creating a new group.
     * What: Shows the new group modal dialog
     * Why: Users need a way to create groups without leaving the create alert form
     * How: Add 'show' class to modal overlay, focus the input field
     */
    function openNewGroupModal() {
        const modal = document.getElementById('new-group-modal');
        const input = document.getElementById('new-group-name-input');
        
        // Show the modal
        modal.classList.add('show');
        
        // Clear any previous input and focus
        input.value = '';
        input.focus();
        
        // Add event listener for Enter key
        // What: Allows user to press Enter to create the group
        // Why: Faster workflow than clicking the button
        // How: Listen for keydown, check for Enter, call createNewGroup
        input.onkeydown = function(e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                createNewGroup();
            } else if (e.key === 'Escape') {
                closeNewGroupModal();
            }
        };
    }
    
    /**
     * Closes the new group modal.
     * What: Hides the new group modal dialog
     * Why: User cancelled or finished creating a group
     * How: Remove 'show' class from modal overlay
     */
    function closeNewGroupModal() {
        const modal = document.getElementById('new-group-modal');
        modal.classList.remove('show');
    }
    
    /**
     * Creates a new group and adds it to the dropdown.
     * What: Validates input, adds new group to AlertsState, updates dropdown, selects it
     * Why: User wants to create a new group for their alert
     * How: Get input value, validate, add to AlertsState.alertGroups, update dropdown, select
     */
    function createNewGroup() {
        const input = document.getElementById('new-group-name-input');
        const groupName = input.value.trim();
        
        // Validate input
        // What: Ensure the group name is not empty
        // Why: Empty group names are not allowed
        // How: Check trimmed value length
        if (!groupName) {
            input.focus();
            return;
        }
        
        // Check for duplicates (case-insensitive)
        // What: Prevent creating duplicate groups
        // Why: Group names should be unique per user
        // How: Check if any existing group matches (ignoring case)
        const existingGroups = AlertsState.getAlertGroups();
        const isDuplicate = existingGroups.some(g => g.toLowerCase() === groupName.toLowerCase());
        if (isDuplicate) {
            // Show error - group already exists
            input.style.borderColor = '#dc3545';
            setTimeout(() => {
                input.style.borderColor = '';
            }, 2000);
            return;
        }
        
        // Add new group to AlertsState
        // What: Adds the new group name to the application state
        // Why: Makes it available in the dropdown and for future reference
        // How: Push to alertGroups array and call updateGroupDropdown
        existingGroups.push(groupName);
        AlertsState.setAlertGroups(existingGroups);
        
        // Select the newly created group in the dropdown
        // What: Automatically selects the new group in the dropdown
        // Why: User likely wants to use the group they just created
        // How: Set the select value to the new group name
        const dropdown = document.getElementById('alert-group');
        if (dropdown) {
            dropdown.value = groupName;
        }
        
        // Close the modal
        closeNewGroupModal();
    }
    
    // Close new group modal on overlay click
    // What: Click handler for modal overlay backdrop
    // Why: Standard UX pattern - clicking outside modal closes it
    // How: Check if click target is the overlay itself (not the content)
    document.getElementById('new-group-modal').addEventListener('click', function(e) {
        if (e.target === this) {
            closeNewGroupModal();
        }
    });

