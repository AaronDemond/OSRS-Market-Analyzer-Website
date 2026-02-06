    /**
     * =============================================================================
     * OSRS ALERTS MANAGEMENT SYSTEM
     * =============================================================================
     * 
     * This module handles all client-side functionality for the alerts system:
     * - Creating and editing alerts (above/below threshold, spread alerts)
     * - Displaying triggered alerts with real-time updates
     * - Managing alert lifecycle (dismiss, delete)
     * - Item search autocomplete functionality
     * - Modal management for spread details and editing
     * 
     * Architecture:
     * - AlertsConfig: Central configuration object for settings and selectors
     * - AlertsState: Manages application state (filters, cached data, etc.)
     * - AlertsAPI: Handles all server communication
     * - AlertsUI: Manages DOM updates and rendering
     * - FormManager: Handles form field visibility and validation
     * - ModalManager: Controls modal dialogs
     * - AutocompleteManager: Handles item search suggestions
     * - EventManager: Sets up all event listeners
     * 
     * =============================================================================
     */

    // =============================================================================
    // CONFIGURATION
    // =============================================================================
    /**
     * Central configuration object containing all settings, selectors, and constants.
     * 
     * Why: Centralizing configuration makes it easy to modify settings without
     * searching through code. It also makes the codebase more maintainable.
     * 
     * How: All DOM selectors, API endpoints, and timing settings are defined here
     * and referenced throughout the application.
     */
    const AlertsConfig = {
        // API endpoints for server communication
        // =============================================================================
        // PERFORMANCE: Two-phase loading for instant page render
        // =============================================================================
        // alerts: Minimal endpoint - returns alerts instantly (no external API wait)
        // prices: Separate endpoint for price data - fetched in background after render
        // alertsFull: Full endpoint with all fields - use for detail page if needed
        endpoints: {
            alerts: '/api/alerts/minimal/',
            prices: '/api/alerts/prices/',
            alertsFull: '/api/alerts/',
            dismiss: '/api/alerts/dismiss/',
            delete: '/api/alerts/delete/',
            update: '/api/alerts/update/',
            group: '/api/alerts/group/',
            deleteGroups: '/api/alerts/groups/delete/',
            itemSearch: '/api/items/'
        },

        // Timing settings (in milliseconds)
        // =============================================================================
        // What: refreshInterval controls how often the frontend polls /api/alerts/
        // Why: User needs to see triggered alerts within 5 seconds of price changes
        // How: Poll every 5 seconds to check for alert status updates
        // Note: Performance optimizations were applied elsewhere (two-phase loading,
        //       price caching) so 5s polling is acceptable
        timing: {
            refreshInterval: 5000,      // How often to poll for alert updates (5 seconds)
            minSearchLength: 2          // Minimum characters before searching
        },

        // Available filters for the alerts list
        // Simple filters have just a test function
        // Input filters have requiresInput: true and testWithValue function
        filters: {
            triggered: {
                id: 'triggered',
                label: 'Triggered',
                test: alert => alert.is_triggered
            },
            notTriggered: {
                id: 'notTriggered',
                label: 'Not Triggered',
                test: alert => !alert.is_triggered
            },
            priceRange: {
                id: 'priceRange',
                label: 'Price',
                shortLabel: 'Price',
                requiresModal: true,
                testWithValue: (alert, value) => {
                    if (!value) return true;
                    const {min, max} = value;
                    const minPrice = min != null && min !== '' ? parseInt(min) : null;
                    const maxPrice = max != null && max !== '' ? parseInt(max) : null;

                    // Get the current price for the alert
                    let currentPrice = null;

                    // For above/below alerts, use the current price
                    if (alert.type === 'above' || alert.type === 'below') {
                        currentPrice = alert.current_price;
                    }
                    // For spread alerts with all items, use average of min/max (This is just for filtering)
                    else if (alert.type === 'spread' && alert.is_all_items) {
                        const minP = alert.minimum_price || 0;
                        const maxP = alert.maximum_price || 0;
                        currentPrice = (minP + maxP) / 2;
                    }
                    // For spread alerts with single item, use average of low/high
                    else if (alert.type === 'spread' && !alert.is_all_items) {
                        const low = alert.spread_low || 0;
                        const high = alert.spread_high || 0;
                        currentPrice = (low + high) / 2;
                    }
                    // For spike alerts, use current price
                    else if (alert.type === 'spike') {
                        currentPrice = alert.current_price;
                    }
                    // Default fallback
                    else {
                        currentPrice = alert.current_price || alert.price || 0;
                    }

                    if (currentPrice == null) return true;

                    // Check min bound (inclusive)
                    if (minPrice != null && !isNaN(minPrice) && currentPrice < minPrice) {
                        return false;
                    }

                    // Check max bound (inclusive)
                    if (maxPrice != null && !isNaN(maxPrice) && currentPrice > maxPrice) {
                        return false;
                    }

                    return true;
                }
            },
            myGroups: {
                id: 'myGroups',
                label: 'My Groups',
                requiresModal: true,
                testWithValue: (alert, selectedGroups) => {
                    if (!selectedGroups || selectedGroups.length === 0) return true;
                    // Check if alert belongs to any of the selected groups
                    const alertGroups = alert.groups || [];
                    return selectedGroups.some(group => alertGroups.includes(group));
                }
            }
        },

        // DOM element selectors for the create form
        selectors: {
            create: {
                alertType: '#alert-type',
                spreadScope: '#spread-scope',
                sustainedScope: '#sustained-scope',
                itemName: '#item-name',
                itemId: '#item-id',
                isAllItems: '#is-all-items',
                numberItems: '#number-of-items',
                direction: '#direction',
                emailNotification: '#email-notification',
                suggestions: '#item-suggestions',
                sustainedItemInput: '#sustained-item-input',
                sustainedItemIds: '#sustained-item-ids',
                sustainedItemSuggestions: '#sustained-item-suggestions',
                // Sustained move multi-item selector elements (new dropdown-style)
                sustainedSelectedItemsDropdown: '#sustained-selected-items-dropdown',
                sustainedSelectedItemsList: '#sustained-selected-items-list',
                sustainedNoItemsMessage: '#sustained-no-items-message',
                sustainedMultiItemToggle: '#sustained-multi-item-toggle',
                sustainedItemNotification: '#sustained-item-notification',
                // Spread multi-item selector elements
                spreadItemInput: '#spread-item-input',
                spreadItemIds: '#spread-item-ids',
                spreadItemSuggestions: '#spread-item-suggestions',
                // Spread multi-item selector elements (new dropdown-style)
                spreadSelectedItemsDropdown: '#spread-selected-items-dropdown',
                spreadSelectedItemsList: '#spread-selected-items-list',
                spreadNoItemsMessage: '#spread-no-items-message',
                spreadMultiItemToggle: '#spread-multi-item-toggle',
                spreadItemNotification: '#spread-item-notification',
                // Spike multi-item selector elements
                // What: DOM selectors for spike alert's multi-item selection UI
                // Why: Enables the multi-item picker functionality for spike alerts
                spikeScope: '#spike-scope',
                spikeItemInput: '#spike-item-input',
                spikeItemIds: '#spike-item-ids',
                spikeItemSuggestions: '#spike-item-suggestions',
                spikeSelectedItemsDropdown: '#spike-selected-items-dropdown',
                spikeSelectedItemsList: '#spike-selected-items-list',
                spikeNoItemsMessage: '#spike-no-items-message',
                spikeMultiItemToggle: '#spike-multi-item-toggle',
                spikeItemNotification: '#spike-item-notification',
                // Threshold alert multi-item selector elements
                // What: DOM selectors for threshold alert's item selection UI
                // Why: Enables the multi-item picker functionality for threshold alerts
                thresholdItemsTracked: '#threshold-items-tracked',
                thresholdItemInput: '#threshold-item-input',
                thresholdItemIds: '#threshold-item-ids',
                thresholdItemSuggestions: '#threshold-item-suggestions',
                thresholdSelectedItemsDropdown: '#threshold-selected-items-dropdown',
                thresholdSelectedItemsList: '#threshold-selected-items-list',
                thresholdNoItemsMessage: '#threshold-no-items-message',
                thresholdMultiItemToggle: '#threshold-multi-item-toggle',
                thresholdItemNotification: '#threshold-item-notification',
                thresholdType: '#threshold-type',
                thresholdDirection: '#threshold-direction',
                thresholdValue: '#threshold-value',
                thresholdReference: '#threshold-reference',
                // Collective Move alert multi-item selector elements
                // What: DOM selectors for collective_move alert's item selection UI
                // Why: Enables the multi-item picker functionality for collective move alerts
                // How: Similar pattern to threshold/spike alerts with scope, items, and settings
                collectiveScope: '#collective-scope',
                collectiveItemInput: '#collective-item-input',
                collectiveItemIds: '#collective-item-ids',
                collectiveItemSuggestions: '#collective-item-suggestions',
                collectiveSelectedItemsDropdown: '#collective-selected-items-dropdown',
                collectiveSelectedItemsList: '#collective-selected-items-list',
                collectiveNoItemsMessage: '#collective-no-items-message',
                collectiveMultiItemToggle: '#collective-multi-item-toggle',
                collectiveItemNotification: '#collective-item-notification',
                collectiveReference: '#collective-reference',
                collectiveCalculationMethod: '#collective-calculation-method',
                collectiveDirection: '#collective-direction',
                collectiveThreshold: '#collective-threshold',
                alertGroup: '#alert-group',
                groups: {
                    spreadScope: '#spread-scope-group',
                    spreadItems: '#spread-items-group',  // New group for spread multi-item selector
                    spikeScope: '#spike-scope-group',    // Spike scope selector group
                    spikeItems: '#spike-items-group',    // Spike multi-item selector group
                    sustainedScope: '#sustained-scope-group',
                    sustainedItems: '#sustained-items-group',
                    itemName: '#item-name-group',
                    price: '#price-group',
                    reference: '#reference-group',
                    percentage: '#percentage-group',
                    timeFrame: '#time-frame-group',
                    direction: '#direction-group',
                    minPrice: '#min-price-group',
                    maxPrice: '#max-price-group',
                    minConsecutiveMoves: '#min-consecutive-moves-group',
                    minMovePercentage: '#min-move-percentage-group',
                    volatilityBuffer: '#volatility-buffer-group',
                    volatilityMultiplier: '#volatility-multiplier-group',
                    minVolume: '#min-volume-group',
                    pressureStrength: '#pressure-strength-group',
                    pressureSpread: '#pressure-spread-group',
                    // Threshold alert form groups
                    // What: DOM selectors for threshold alert form field containers
                    // Why: Controls visibility of threshold-specific form fields
                    thresholdItemsTracked: '#threshold-items-tracked-group',
                    thresholdItems: '#threshold-items-group',
                    thresholdType: '#threshold-type-group',
                    thresholdDirection: '#threshold-direction-group',
                    thresholdValue: '#threshold-value-group',
                    thresholdReference: '#threshold-reference-group',
                    // Collective Move alert form groups
                    // What: DOM selectors for collective_move alert form field containers
                    // Why: Controls visibility of collective_move-specific form fields
                    collectiveScope: '#collective-scope-group',
                    collectiveItems: '#collective-items-group',
                    collectiveReference: '#collective-reference-group',
                    collectiveCalculationMethod: '#collective-calculation-method-group',
                    collectiveDirection: '#collective-direction-group',
                    collectiveThreshold: '#collective-threshold-group'
                }
            },
            // Other UI elements
            myAlertsPane: '#my-alerts',
            spreadModal: '#spread-modal',
            spreadItemsList: '#spread-items-list',
            spikeModal: '#spike-modal',
            spikeItemsList: '#spike-items-list',
            groupModal: '#group-modal',
            groupList: '#group-list',
            newGroupInput: '#new-group-input',
            tabButtons: '.tab-btn',
            tabPanes: '.tab-pane'
        },

        // Alert type constants for comparison
        alertTypes: {
            ABOVE: 'above',
            BELOW: 'below',
            SPREAD: 'spread',
            SPIKE: 'spike',
            SUSTAINED: 'sustained',
            THRESHOLD: 'threshold',
            COLLECTIVE_MOVE: 'collective_move'
        },

        // CSRF token for Django POST requests
        csrfToken: window.CSRF_TOKEN || ''
    };

console.log("Hello, world");
console.log(window.CSRF_TOKEN);
