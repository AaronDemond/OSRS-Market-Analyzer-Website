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
        const errorBadge = document.getElementById('new-group-name-error');
        const groupName = input.value.trim();
        
        // Hide any previous error badge before validating
        // What: Clears the inline error message on each attempt
        // Why: Ensures old errors don't linger when user retries
        // How: Remove the "show" class and clear text content
        if (errorBadge) {
            errorBadge.classList.remove('show');
            errorBadge.textContent = '';
        }
        
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
            
            // Show inline duplicate error badge
            // What: Displays a red inline message stating the group already exists
            // Why: User requested a clear, specific message when a duplicate is entered
            // How: Reuse item-notification error styling and auto-hide after delay
            if (errorBadge) {
                errorBadge.textContent = 'Error: group already exists';
                errorBadge.classList.add('show');
                setTimeout(() => {
                    errorBadge.classList.remove('show');
                    errorBadge.textContent = '';
                }, 2500);
            }
            
            // Reset input border after a short delay
            // What: Clears the red border used to indicate an error
            // Why: Avoids leaving the input in a permanent error state
            // How: Restore original border color after timeout
            setTimeout(() => {
                input.style.borderColor = '';
            }, 2000);
            return;
        }
        
        // Add new group to AlertsState as a pending client-side group
        // What: Registers the group as pending so refreshes don't overwrite it
        // Why: Server refresh overwrites the dropdown list and would drop the new group
        // How: Use AlertsState.registerPendingGroup to dedupe and merge with server groups
        AlertsState.registerPendingGroup(groupName);
        
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
        
        // Return keyboard focus to the group dropdown after modal closes
        // What: Calls .focus() on the #alert-group select element after successful group creation
        // Why: Accessibility best practice - when a modal closes, focus should return to the 
        //      triggering element or a logical next element. The group dropdown is the logical
        //      location since the user just created a group and that group is now selected.
        // How: Query for #alert-group element, verify it exists (defensive null check to avoid
        //      runtime errors), then call .focus() to move keyboard focus to the dropdown
        // Note: This ensures keyboard-only users can continue their workflow without having to
        //       manually navigate back to the form controls
        const groupDropdown = document.getElementById('alert-group');
        if (groupDropdown) {
            groupDropdown.focus();
        }
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
