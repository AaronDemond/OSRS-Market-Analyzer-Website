/*
    Global Checkbox Enter Key Toggle Handler
    =========================================
    What: Enables users to toggle checkboxes using the Enter key when focused.
    Why: Improves keyboard accessibility and user experience by allowing checkboxes
         to be toggled with Enter key, similar to how Space key works by default.
         Prevents accidental form submission when users press Enter on a checkbox.
    How:
        1. Listen for keydown events globally on the document
        2. Check if the focused element is a checkbox input
        3. Check if the Enter key was pressed (key code 13 or key === 'Enter')
        4. Prevent default behavior (which would submit the form)
        5. Stop event propagation to prevent parent form handlers from triggering
        6. Toggle the checkbox checked state by inverting its current value
        7. Trigger a 'change' event so any existing event listeners are notified
*/

// Wait for the DOM to be fully loaded before attaching event listeners
// This ensures all elements are available before we try to interact with them
document.addEventListener('DOMContentLoaded', function() {
    
    // Add a global keydown event listener to the entire document
    // This uses event delegation to catch all keyboard events, even for dynamically added checkboxes
    document.addEventListener('keydown', function(event) {
        // Get the currently focused element in the DOM
        const focusedElement = document.activeElement;
        
        // Check if the focused element is a checkbox input AND the Enter key was pressed
        // We check both event.key (modern browsers) and event.keyCode (legacy support)
        if (focusedElement && 
            focusedElement.tagName === 'INPUT' && 
            focusedElement.type === 'checkbox' &&
            (event.key === 'Enter' || event.keyCode === 13)) {
            
            // Prevent the default Enter key behavior (form submission)
            event.preventDefault();
            
            // Stop the event from bubbling up to parent elements
            // This ensures form submit handlers don't get triggered
            event.stopPropagation();
            
            // Toggle the checkbox state by inverting its current checked value
            focusedElement.checked = !focusedElement.checked;
            
            // Dispatch a 'change' event on the checkbox to notify any existing event listeners
            // This ensures that any JavaScript code listening for checkbox changes still works
            const changeEvent = new Event('change', { bubbles: true });
            focusedElement.dispatchEvent(changeEvent);
        }
    });
});
