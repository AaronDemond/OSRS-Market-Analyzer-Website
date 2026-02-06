    /**
     * Manages alert list filtering.
     * 
     * Why: Users need to filter alerts by various criteria (triggered status, etc.)
     * to quickly find relevant alerts.
     * 
     * How: Maintains a set of active filter IDs in AlertsState. When rendering,
     * alerts are filtered through all active filter test functions.
     */
    const FilterManager = {
        /**
         * Adds a filter to the active filters set and updates the DOM.
         * For input-based filters, shows an input prompt first.
         */
        addFilter(filterId) {
            const filter = AlertsConfig.filters[filterId];
            if (!filter) return;
            if (filterId === 'myGroups' && AlertsState.activeFilters.has(filterId)) {
                this.showFilterModal(filterId);
                return;
            }
            if (AlertsState.activeFilters.has(filterId)) return;

            // If filter requires a modal, open it
            if (filter.requiresModal) {
                this.showFilterModal(filterId);
                return;
            }

            // If filter requires input, show input UI instead of adding directly
            if (filter.requiresInput) {
                this.showFilterInput(filterId);
                return;
            }

            this.activateFilter(filterId);
        },

        /**
         * Shows a modal for a modal-based filter.
         */
        showFilterModal(filterId) {
            const dropdown = document.querySelector('#active-filters .filter-dropdown');
            if (dropdown) dropdown.value = '';
            if (filterId === 'myGroups') {
                openGroupsFilterModal();
            } else if (filterId === 'priceRange') {
                openPriceFilterModal();
            }
        },

        /**
         * Shows the input UI for an input-based filter.
         */
        showFilterInput(filterId) {
            const filter = AlertsConfig.filters[filterId];
            const container = document.querySelector('#active-filters');
            const dropdown = container ? container.querySelector('.filter-dropdown') : null;
            if (!dropdown) return;

            // Create input UI
            const inputHtml = '<span class="filter-input-container" data-filter-id="' + filterId + '">' +
                '<input type="' + (filter.inputType || 'text') + '" class="filter-input" ' +
                'placeholder="' + (filter.inputPlaceholder || 'Enter value...') + '" ' +
                'onkeydown="handleFilterInputKeydown(event, \'' + filterId + '\')">' +
                '<button class="filter-input-confirm" onclick="confirmFilterInput(\'' + filterId + '\')">✓</button>' +
                '<button class="filter-input-cancel" onclick="cancelFilterInput(\'' + filterId + '\')">&times;</button>' +
                '</span>';

            dropdown.insertAdjacentHTML('beforebegin', inputHtml);

            // Focus the input
            const input = container.querySelector('.filter-input-container[data-filter-id="' + filterId + '"] .filter-input');
            if (input) input.focus();

            // Reset dropdown
            dropdown.value = '';
        },

        /**
         * Confirms the input for an input-based filter and activates it.
         */
        confirmFilterInput(filterId) {
            const container = document.querySelector('#active-filters');
            const inputContainer = container ? container.querySelector('.filter-input-container[data-filter-id="' + filterId + '"]') : null;
            const input = inputContainer ? inputContainer.querySelector('.filter-input') : null;

            if (!input || !input.value.trim()) {
                this.cancelFilterInput(filterId);
                return;
            }

            const value = input.value.trim();
            AlertsState.setFilterValue(filterId, value);

            // Remove input container
            inputContainer.remove();

            // Activate the filter with the value displayed
            this.activateFilter(filterId, value);
        },

        /**
         * Cancels the input for an input-based filter.
         */
        cancelFilterInput(filterId) {
            const container = document.querySelector('#active-filters');
            const inputContainer = container ? container.querySelector('.filter-input-container[data-filter-id="' + filterId + '"]') : null;
            if (inputContainer) {
                inputContainer.remove();
            }
        },

        /**
         * Activates a filter and adds its tag to the DOM.
         * @param {string} filterId - The filter ID
         * @param {string} displayValue - Optional value to display in the tag
         */
        activateFilter(filterId, displayValue) {
            AlertsState.activeFilters.add(filterId);

            // Add filter tag to DOM
            const filter = AlertsConfig.filters[filterId];
            const container = document.querySelector('#active-filters');
            const dropdown = container ? container.querySelector('.filter-dropdown') : null;
            const tagContainer = document.querySelector('.alert-indicators .filter-tags');
            if (dropdown) {
                // Format the label based on whether it's a numeric value or not
                let label;
                if (displayValue) {
                    const numValue = parseInt(displayValue);
                    if (!isNaN(numValue) && filter.requiresInput) {
                        label = filter.label + ': ' + numValue.toLocaleString();
                    } else {
                        label = filter.label + ': ' + displayValue;
                    }
                } else {
                    label = filter.label;
                }
                const tagHtml = '<span class="filter-tag" data-filter-id="' + filterId + '">' + label +
                    '<button class="filter-tag-remove" onclick="removeFilter(\'' + filterId + '\')">&times;</button>' +
                    '</span>';
                if (tagContainer) {
                    tagContainer.insertAdjacentHTML('beforeend', tagHtml);
                } else {
                    dropdown.insertAdjacentHTML('beforebegin', tagHtml);
                }

                // Remove the option from dropdown
                const option = dropdown.querySelector('option[value="' + filterId + '"]');
                if (option && filterId !== 'myGroups') option.remove();
            }

            // Only update the alerts list, not the entire pane
            this.updateAlertsList();
        },

        /**
         * Removes a filter from the active filters set.
         */
        removeFilter(filterId) {
            AlertsState.activeFilters.delete(filterId);
            AlertsState.filterValues[filterId] = null; // Clear any stored value

            const tagEl = document.querySelector('.filter-tag[data-filter-id="' + filterId + '"]');
            if (tagEl) tagEl.remove();

            // Re-add the option to dropdown
            const filter = AlertsConfig.filters[filterId];
            const dropdown = document.querySelector('#active-filters .filter-dropdown');
            if (dropdown && filter) {
                const existingOption = dropdown.querySelector('option[value="' + filterId + '"]');
                if (!existingOption) {
                    const option = document.createElement('option');
                    option.value = filterId;
                    option.textContent = filter.label;
                    dropdown.appendChild(option);
                }
            }

            // Only update the alerts list, not the entire pane
            this.updateAlertsList();
        },

        /**
         * Updates just the alerts list based on current filters.
         * Uses cached alerts data for instant response - no network request.
         */
        updateAlertsList() {
            const alerts = AlertsState.getCachedAlerts();

            const pane = document.querySelector('#my-alerts');
            if (!pane) return;

            const alertsList = pane.querySelector('.alerts-list');
            const alertGroup = pane.querySelector('.alert-group');
            const noAlertsMsg = pane.querySelector('.no-alerts');
            const filteredAlerts = this.applyFilters(alerts);
            const sortedAlerts = SortManager.applySort(filteredAlerts);
            const selectedGroups = AlertsState.getFilterValue('myGroups');
            const isGroupedView = selectedGroups && selectedGroups.length > 0 && AlertsState.activeFilters.has('myGroups');

            let newHtml = '';
            if (sortedAlerts.length === 0) {
                newHtml = '<p class="no-alerts">No alerts match the current filters.</p>';
            } else if (isGroupedView) {
                newHtml = AlertsUI.renderGroupedAlertsList(sortedAlerts, selectedGroups);
            } else {
                newHtml = '<ul class="alerts-list">';
                sortedAlerts.forEach(alert => {
                    newHtml += AlertsUI.renderAlertItem(alert);
                });
                newHtml += '</ul>';
            }

            if (alertGroup) {
                const allGroups = pane.querySelectorAll('.alert-group');
                const firstGroup = allGroups[0];
                allGroups.forEach((g, i) => {if (i > 0) g.remove();});
                if (firstGroup) {
                    firstGroup.outerHTML = newHtml;
                }
            } else if (alertsList) {
                alertsList.outerHTML = newHtml;
            } else if (noAlertsMsg) {
                noAlertsMsg.outerHTML = newHtml;
            }
        },

        /**
         * Checks if a filter is currently active.
         */
        isActive(filterId) {
            return AlertsState.activeFilters.has(filterId);
        },

        /**
         * Applies all active filters to an array of alerts.
         * Returns only alerts that pass ALL active filter tests.
         */
        applyFilters(alerts) {
            let result = alerts;

            // Apply search filter first
            if (AlertsState.searchQuery && AlertsState.searchQuery.trim()) {
                const query = AlertsState.searchQuery.toLowerCase().trim();
                result = result.filter(alert => {
                    const text = (alert.text || '').toLowerCase();
                    return text.includes(query);
                });
            }

            // Apply active filters
            if (AlertsState.activeFilters.size === 0) {
                return result;
            }

            return result.filter(alert => {
                for (const filterId of AlertsState.activeFilters) {
                    const filter = AlertsConfig.filters[filterId];
                    if (!filter) continue;

                    // Use testWithValue for input-based or modal-based filters
                    if ((filter.requiresInput || filter.requiresModal) && filter.testWithValue) {
                        const value = AlertsState.getFilterValue(filterId);
                        if (!filter.testWithValue(alert, value)) {
                            return false;
                        }
                    } else if (filter.test && !filter.test(alert)) {
                        return false;
                    }
                }
                return true;
            });
        }
    };


    // =============================================================================
    // FORM MANAGEMENT
    // =============================================================================
    /**
     * Manages form field visibility and state for create/edit forms.
     * 
     * Why: Different alert types require different fields. This manager handles
     * showing/hiding the appropriate fields based on user selections.
     * 
     * How: Uses configuration-driven approach to map alert types to visible fields.
     */
    const FormManager = {
        /**
         * Updates tabindex values based on alert type and scope (specific/all items).
         * 
         * What: Dynamically sets tabindex attributes to match visual layout
         * Why: The visual order of fields changes when switching between "Specific Items" and "All Items"
         *      modes because different fields are shown/hidden. Tab order must match visual order.
         * How: Defines tabindex maps for each alert type and scope combination, then applies them
         * 
         * @param {string} alertType - The type of alert ('spread', 'spike', 'sustained', 'threshold')
         * @param {boolean} isAllItems - Whether "All Items" mode is selected
         */
        updateTabIndices(alertType, isAllItems) {
            // =============================================================================
            // TABINDEX CONFIGURATION
            // =============================================================================
            // What: Defines the correct tab order for each alert type and scope combination
            // Why: Visual field order differs between "Specific Items" (shows item selector) and
            //      "All Items" (shows min/max price filters) modes
            // How: Maps field IDs to tabindex values based on their visual position in each mode
            // Note: Values start at 7 because common fields (Alert Type, Name, Group) use 1-6
            // =============================================================================
            
            const tabConfigs = {
                // SPREAD alert tabindex configuration
                spread: {
                    // Specific Items: Apply To → Items → Percentage → Notifications
                    specific: {
                        'spread-scope': 7,
                        'spread-item-input': 8,
                        'spread-multi-item-toggle': 9,
                        'percentage': 10
                    },
                    // All Items: Apply To → Max Price → Min Price → Percentage → Notifications
                    all: {
                        'spread-scope': 7,
                        'maximum-price': 8,
                        'minimum-price': 9,
                        'percentage': 10
                    }
                },
                
                // SPIKE alert tabindex configuration
                spike: {
                    // Specific Items: Apply To → Items → Direction → Percentage → Reference → Time Frame
                    specific: {
                        'spike-scope': 7,
                        'spike-item-input': 8,
                        'spike-multi-item-toggle': 9,
                        'direction': 10,
                        'percentage': 11,
                        'reference': 12,
                        'time-frame': 13
                    },
                    // All Items: Apply To → Direction → Max Price → Min Price → Percentage → Reference → Time Frame
                    all: {
                        'spike-scope': 7,
                        'direction': 8,
                        'maximum-price': 9,
                        'minimum-price': 10,
                        'percentage': 11,
                        'reference': 12,
                        'time-frame': 13
                    }
                },
                
                // SUSTAINED alert tabindex configuration
                sustained: {
                    // Specific Items: Apply To → Items → Direction → Market Pressure → Min Consecutive →
                    //                 Min Move% → Min Spread% → Min Volume → Reference → Time Frame →
                    //                 Vol Buffer → Vol Multiplier
                    specific: {
                        'sustained-scope': 7,
                        'sustained-item-input': 8,
                        'sustained-multi-item-toggle': 9,
                        'direction': 10,
                        'min-pressure-strength': 11,
                        'min-consecutive-moves': 12,
                        'min-move-percentage': 13,
                        'min-pressure-spread': 14,
                        'min-volume': 15,
                        'reference': 16,
                        'time-frame': 17,
                        'volatility-buffer-size': 18,
                        'volatility-multiplier': 19
                    },
                    // All Items: Apply To → Direction → Market Pressure → Max Price → Min Price → Min Consecutive →
                    //            Min Move% → Min Spread% → Min Volume → Reference → Time Frame →
                    //            Vol Buffer → Vol Multiplier
                    // What: Tab order for sustained alerts when "All Items" is selected
                    // Why: Users expect Min/Max price fields to be adjacent for easier form completion
                    // How: Place minimum-price immediately after maximum-price (tabindex 11)
                    all: {
                        'sustained-scope': 7,
                        'direction': 8,
                        'min-pressure-strength': 9,
                        'maximum-price': 10,
                        'minimum-price': 11,
                        'min-consecutive-moves': 12,
                        'min-move-percentage': 13,
                        'min-pressure-spread': 14,
                        'min-volume': 15,
                        'reference': 16,
                        'time-frame': 17,
                        'volatility-buffer-size': 18,
                        'volatility-multiplier': 19
                    }
                },
                
                // THRESHOLD alert tabindex configuration
                threshold: {
                    // Specific Items: Apply To → Items → Above/Below → Threshold Type → Reference → Threshold
                    specific: {
                        'threshold-items-tracked': 7,
                        'threshold-item-input': 8,
                        'threshold-multi-item-toggle': 9,
                        'threshold-direction': 10,
                        'threshold-type': 11,
                        'threshold-reference': 12,
                        'threshold-value': 13
                    },
                    // All Items: Apply To → Above/Below → Threshold Type → Max Price → Min Price → Reference → Threshold
                    all: {
                        'threshold-items-tracked': 7,
                        'threshold-direction': 8,
                        'threshold-type': 9,
                        'maximum-price': 10,
                        'minimum-price': 11,
                        'threshold-reference': 12,
                        'threshold-value': 13
                    }
                },
                
                // COLLECTIVE_MOVE alert tabindex configuration
                // What: Tab order for collective_move alerts in both specific and all items modes
                // Why: Users need logical tab flow through collective move configuration
                // How: Groups related fields together for efficient form completion
                collective_move: {
                    // Specific Items: Apply To → Items → Reference → Calculation Method → Direction → Threshold → Time Frame
                    specific: {
                        'collective-scope': 7,
                        'collective-item-input': 8,
                        'collective-multi-item-toggle': 9,
                        'collective-reference': 10,
                        'collective-calculation-method': 11,
                        'collective-direction': 12,
                        'collective-threshold': 13,
                        'time-frame': 14
                    },
                    // All Items: Apply To → Max Price → Min Price → Reference → Calculation Method → Direction → Threshold → Time Frame
                    all: {
                        'collective-scope': 7,
                        'maximum-price': 8,
                        'minimum-price': 9,
                        'collective-reference': 10,
                        'collective-calculation-method': 11,
                        'collective-direction': 12,
                        'collective-threshold': 13,
                        'time-frame': 14
                    }
                }
            };
            
            // Get the configuration for this alert type and scope
            const config = tabConfigs[alertType];
            if (!config) return;
            
            const tabMap = isAllItems ? config.all : config.specific;
            
            // Apply tabindex values to each field
            // What: Set the tabindex attribute on each input/select element
            // Why: Browser uses tabindex to determine tab navigation order
            // How: Find each element by ID and set its tabindex attribute
            for (const [fieldId, tabIndex] of Object.entries(tabMap)) {
                const element = document.getElementById(fieldId);
                if (element) {
                    element.setAttribute('tabindex', tabIndex);
                }
            }
        },

        /**
         * Updates form field visibility based on selected alert type.
         * 
         * @param {string} formType - 'create' for create form
         */
        handleAlertTypeChange(formType) {
            const selectors = AlertsConfig.selectors[formType];
            const alertType = document.querySelector(selectors.alertType).value;
            const groups = selectors.groups;

            // Get all form group elements
            const elements = {
                spreadScope: document.querySelector(groups.spreadScope),
                spreadItems: document.querySelector(groups.spreadItems),  // Spread multi-item selector group
                spikeScope: document.querySelector(groups.spikeScope),
                spikeItems: document.querySelector(groups.spikeItems),
                itemName: document.querySelector(groups.itemName),
                price: document.querySelector(groups.price),
                reference: document.querySelector(groups.reference),
                percentage: document.querySelector(groups.percentage),
                timeFrame: document.querySelector(groups.timeFrame),
                direction: document.querySelector(groups.direction),
                minPrice: document.querySelector(groups.minPrice),
                maxPrice: document.querySelector(groups.maxPrice),
                minConsecutiveMoves: document.querySelector(groups.minConsecutiveMoves),
                minMovePercentage: document.querySelector(groups.minMovePercentage),
                volatilityBuffer: document.querySelector(groups.volatilityBuffer),
                volatilityMultiplier: document.querySelector(groups.volatilityMultiplier),
                minVolume: document.querySelector(groups.minVolume),
                sustainedScope: document.querySelector(groups.sustainedScope),
                sustainedItems: document.querySelector(groups.sustainedItems),
                pressureStrength: document.querySelector(groups.pressureStrength),
                pressureSpread: document.querySelector(groups.pressureSpread),
                // Threshold alert elements
                thresholdItemsTracked: document.querySelector(groups.thresholdItemsTracked),
                thresholdItems: document.querySelector(groups.thresholdItems),
                thresholdType: document.querySelector(groups.thresholdType),
                thresholdDirection: document.querySelector(groups.thresholdDirection),
                thresholdValue: document.querySelector(groups.thresholdValue),
                thresholdReference: document.querySelector(groups.thresholdReference),
                // Collective Move alert elements
                // What: DOM elements for collective_move alert form field containers
                // Why: Controls visibility and access to collective_move-specific form fields
                collectiveScope: document.querySelector(groups.collectiveScope),
                collectiveItems: document.querySelector(groups.collectiveItems),
                collectiveReference: document.querySelector(groups.collectiveReference),
                collectiveCalculationMethod: document.querySelector(groups.collectiveCalculationMethod),
                collectiveDirection: document.querySelector(groups.collectiveDirection),
                collectiveThreshold: document.querySelector(groups.collectiveThreshold)
            };

            // Helper to hide all sustained move fields
            const hideSustainedFields = () => {
                if (elements.minConsecutiveMoves) elements.minConsecutiveMoves.style.display = 'none';
                if (elements.minMovePercentage) elements.minMovePercentage.style.display = 'none';
                if (elements.volatilityBuffer) elements.volatilityBuffer.style.display = 'none';
                if (elements.volatilityMultiplier) elements.volatilityMultiplier.style.display = 'none';
                if (elements.minVolume) elements.minVolume.style.display = 'none';
                if (elements.sustainedScope) elements.sustainedScope.style.display = 'none';
                if (elements.sustainedItems) elements.sustainedItems.style.display = 'none';
                if (elements.pressureStrength) elements.pressureStrength.style.display = 'none';
                if (elements.pressureSpread) elements.pressureSpread.style.display = 'none';
            };

            /**
             * Helper to hide all threshold alert specific fields
             * What: Hides all form fields that are specific to threshold alerts
             * Why: When switching away from threshold alert type, these fields should be hidden
             * How: Sets display to 'none' for each threshold-specific field group
             */
            const hideThresholdFields = () => {
                if (elements.thresholdItemsTracked) elements.thresholdItemsTracked.style.display = 'none';
                if (elements.thresholdItems) elements.thresholdItems.style.display = 'none';
                if (elements.thresholdType) elements.thresholdType.style.display = 'none';
                if (elements.thresholdDirection) elements.thresholdDirection.style.display = 'none';
                if (elements.thresholdValue) elements.thresholdValue.style.display = 'none';
                if (elements.thresholdReference) elements.thresholdReference.style.display = 'none';
                // Clear selected items when hiding
                ThresholdMultiItemSelector.clear();
            };
            
            /**
             * Helper to hide all collective move alert specific fields
             * What: Hides all form fields that are specific to collective_move alerts
             * Why: When switching away from collective_move alert type, these fields should be hidden
             * How: Sets display to 'none' for each collective_move-specific field group
             */
            const hideCollectiveFields = () => {
                if (elements.collectiveScope) elements.collectiveScope.style.display = 'none';
                if (elements.collectiveItems) elements.collectiveItems.style.display = 'none';
                if (elements.collectiveReference) elements.collectiveReference.style.display = 'none';
                if (elements.collectiveCalculationMethod) elements.collectiveCalculationMethod.style.display = 'none';
                if (elements.collectiveDirection) elements.collectiveDirection.style.display = 'none';
                if (elements.collectiveThreshold) elements.collectiveThreshold.style.display = 'none';
                // Clear selected items when hiding
                if (typeof CollectiveMoveMultiItemSelector !== 'undefined') {
                    CollectiveMoveMultiItemSelector.clear();
                }
            };

            /**
             * Helper to hide all spike alert specific fields
             * What: Hides the spike scope selector and multi-item selector
             * Why: When switching away from spike alert type, these fields should be hidden
             * How: Sets display to 'none' for spike-specific field groups and clears selected items
             */
            const hideSpikeFields = () => {
                if (elements.spikeScope) elements.spikeScope.style.display = 'none';
                if (elements.spikeItems) elements.spikeItems.style.display = 'none';
                // Clear selected items when hiding
                if (typeof SpikeMultiItemSelector !== 'undefined') {
                    SpikeMultiItemSelector.clear();
                }
            };
            
            /**
             * Helper to hide all spread alert specific fields
             * What: Hides the spread scope selector and multi-item selector
             * Why: When switching away from spread alert type, these fields should be hidden
             *      to prevent duplicate item input elements from appearing
             * How: Sets display to 'none' for spread-specific field groups and clears selected items
             */
            const hideSpreadFields = () => {
                if (elements.spreadScope) elements.spreadScope.style.display = 'none';
                if (elements.spreadItems) elements.spreadItems.style.display = 'none';
                // Clear selected items when hiding
                if (typeof SpreadMultiItemSelector !== 'undefined') {
                    SpreadMultiItemSelector.clear();
                }
            };

            if (alertType === AlertsConfig.alertTypes.SPREAD) {
                // Spread alerts: show spread-specific fields
                elements.spreadScope.style.display = 'block';
                elements.itemName.style.display = 'block';
                elements.price.style.display = 'none';
                elements.reference.style.display = 'none';
                elements.percentage.style.display = 'block';
                elements.timeFrame.style.display = 'none';
                elements.direction.style.display = 'none';
                hideSustainedFields();
                hideThresholdFields();
                hideSpikeFields();
                hideCollectiveFields();
                // What: Show min volume field for spread alerts
                // Why: Users can filter spread opportunities by minimum hourly trading volume (GP)
                //      to avoid low-volume items with inflated spreads that are impractical to flip
                // How: Override the hideSustainedFields() call above which hides minVolume,
                //      and explicitly show it for spread alerts
                if (elements.minVolume) elements.minVolume.style.display = 'block';

                // Let scope change handler determine remaining visibility
                this.handleSpreadScopeChange(formType);
            } else if (alertType === AlertsConfig.alertTypes.SPIKE) {
                // Spike alerts: show spike scope selector + percentage + time frame + direction
                // What: Configure form fields for spike alert creation
                // Why: Spike alerts can monitor all items or specific item(s) via the multi-item selector
                // How: Show spike-specific fields and use handleSpikeScopeChange to manage item selector visibility
                hideSpreadFields();  // Hide spread items to prevent duplicate item inputs
                hideCollectiveFields();
                if (elements.spikeScope) elements.spikeScope.style.display = 'block';
                // Note: itemName is hidden for spike alerts - we use the multi-item selector instead
                elements.itemName.style.display = 'none';
                elements.price.style.display = 'none';
                elements.reference.style.display = 'block';
                elements.percentage.style.display = 'block';
                elements.timeFrame.style.display = 'block';
                elements.direction.style.display = 'block';
                hideSustainedFields();
                hideThresholdFields();
                // Spike uses min/max only when all items selected; handleSpikeScopeChange manages visibility
                this.handleSpikeScopeChange(formType);
            } else if (alertType === AlertsConfig.alertTypes.SUSTAINED) {
                // Sustained Move alerts: scope selector + time frame + direction + reference + sustained-specific fields
                // What: Configure form fields for sustained move alert creation
                // Why: Sustained alerts need reference price selection (High/Low/Average) like spike and threshold
                // How: Show all sustained-specific fields plus the reference dropdown
                hideSpreadFields();  // Hide spread items to prevent duplicate item inputs
                hideSpikeFields();
                hideCollectiveFields();
                elements.itemName.style.display = 'none';
                elements.price.style.display = 'none';
                elements.reference.style.display = 'block';  // Show reference selector for sustained alerts
                elements.percentage.style.display = 'none';
                elements.timeFrame.style.display = 'block';
                elements.direction.style.display = 'block';
                hideThresholdFields();

                // Show sustained scope selector
                if (elements.sustainedScope) elements.sustainedScope.style.display = 'block';

                // Show sustained-specific fields
                if (elements.minConsecutiveMoves) elements.minConsecutiveMoves.style.display = 'block';
                if (elements.minMovePercentage) elements.minMovePercentage.style.display = 'block';
                if (elements.volatilityBuffer) elements.volatilityBuffer.style.display = 'block';
                if (elements.volatilityMultiplier) elements.volatilityMultiplier.style.display = 'block';
                if (elements.minVolume) elements.minVolume.style.display = 'block';

                // Show pressure filter fields
                if (elements.pressureStrength) elements.pressureStrength.style.display = 'block';
                if (elements.pressureSpread) elements.pressureSpread.style.display = 'block';

                // Let scope change handler determine item selector vs min/max price
                this.handleSustainedScopeChange(formType);
            } else if (alertType === AlertsConfig.alertTypes.THRESHOLD) {
                /**
                 * Threshold alerts configuration
                 * What: Shows threshold-specific fields and hides other alert type fields
                 * Why: Threshold alerts have a unique set of configuration options
                 * How: Hides spread/sustained/spike/above/below specific fields, shows threshold fields
                 */
                hideSpreadFields();  // Hide spread items to prevent duplicate item inputs
                hideSpikeFields();   // Hide spike items to prevent duplicate item inputs
                hideSustainedFields();
                hideCollectiveFields();
                if (elements.numberItems) elements.numberItems.style.display = 'none';
                elements.itemName.style.display = 'none';  // Using threshold's own item selector
                elements.price.style.display = 'none';  // Using threshold value instead
                elements.reference.style.display = 'none';  // Using threshold reference instead
                elements.percentage.style.display = 'none';  // Using threshold value instead
                elements.timeFrame.style.display = 'none';
                elements.direction.style.display = 'none';  // Using threshold direction instead
                elements.minPrice.style.display = 'none';
                elements.maxPrice.style.display = 'none';

                // Show threshold-specific fields
                if (elements.thresholdItemsTracked) elements.thresholdItemsTracked.style.display = 'block';
                if (elements.thresholdType) elements.thresholdType.style.display = 'block';
                if (elements.thresholdDirection) elements.thresholdDirection.style.display = 'block';
                if (elements.thresholdValue) elements.thresholdValue.style.display = 'block';
                if (elements.thresholdReference) elements.thresholdReference.style.display = 'block';

                // Let items tracked change handler determine item selector visibility
                this.handleThresholdItemsTrackedChange(formType);

                // Set is_all_items based on items tracked selection
                const itemsTrackedSelect = document.querySelector(selectors.thresholdItemsTracked);
                if (itemsTrackedSelect) {
                    document.querySelector(selectors.isAllItems).value = itemsTrackedSelect.value === 'all' ? 'true' : 'false';
                }
            } else if (alertType === AlertsConfig.alertTypes.COLLECTIVE_MOVE) {
                /**
                 * Collective Move alerts configuration
                 * What: Shows collective_move-specific fields and hides other alert type fields
                 * Why: Collective move alerts monitor average percentage change across multiple items
                 * How: Hides other alert type fields, shows collective_move fields
                 * Note: Collective move alerts MUST use specific items (no "All Items" option)
                 */
                hideSpreadFields();
                hideSpikeFields();
                hideSustainedFields();
                hideThresholdFields();
                if (elements.numberItems) elements.numberItems.style.display = 'none';
                elements.itemName.style.display = 'none';  // Using collective's own item selector
                elements.price.style.display = 'none';
                elements.reference.style.display = 'none';  // Using collective reference instead
                elements.percentage.style.display = 'none';  // Using collective threshold instead
                elements.timeFrame.style.display = 'block';
                elements.direction.style.display = 'none';  // Using collective direction instead
                elements.minPrice.style.display = 'none';
                elements.maxPrice.style.display = 'none';

                // Show collective_move-specific fields
                // Note: collectiveScope is NOT shown - collective move must use specific items
                if (elements.collectiveScope) elements.collectiveScope.style.display = 'none';
                if (elements.collectiveItems) elements.collectiveItems.style.display = 'block';  // Always show item selector
                if (elements.collectiveReference) elements.collectiveReference.style.display = 'block';
                if (elements.collectiveCalculationMethod) elements.collectiveCalculationMethod.style.display = 'block';
                if (elements.collectiveDirection) elements.collectiveDirection.style.display = 'block';
                if (elements.collectiveThreshold) elements.collectiveThreshold.style.display = 'block';

                // Collective move alerts must use specific items, not all items
                document.querySelector(selectors.isAllItems).value = 'false';
            } else {
                // Above/Below alerts: show threshold fields
                hideSpreadFields();  // Hide spread items to prevent duplicate item inputs
                hideSpikeFields();   // Hide spike items to prevent duplicate item inputs
                hideSustainedFields();
                hideThresholdFields();
                hideCollectiveFields();
                if (elements.numberItems) elements.numberItems.style.display = 'none';
                elements.itemName.style.display = 'block';
                elements.price.style.display = 'block';
                elements.reference.style.display = 'block';
                elements.percentage.style.display = 'none';
                elements.timeFrame.style.display = 'none';
                elements.direction.style.display = 'none';
                elements.minPrice.style.display = 'none';
                elements.maxPrice.style.display = 'none';

                // Reset is_all_items
                document.querySelector(selectors.isAllItems).value = 'false';
            }

            const directionInput = document.querySelector(selectors.direction);
            if (directionInput && elements.direction.style.display === 'none') {
                directionInput.value = 'both';
            }
        },

        /**
         * Handles changes to the collective_move alert "Scope" dropdown.
         * 
         * What: Shows/hides the item selector and min/max price based on scope selection
         * Why: When "All Items" is selected, items selector is hidden and price filters are shown
         *      When "Specific Items" is selected, items selector is shown and price filters hidden
         * How: Toggles visibility of items group and price filters
         * 
         * @param {string} formType - 'create' for create form
         */
        handleCollectiveScopeChange(formType) {
            const selectors = AlertsConfig.selectors[formType];
            const groups = selectors.groups;
            
            // Get the scope selection
            const collectiveScopeSelect = document.querySelector(selectors.collectiveScope);
            const collectiveItemsGroup = document.querySelector(groups.collectiveItems);
            const isAllItemsInput = document.querySelector(selectors.isAllItems);
            const minPriceGroup = document.querySelector(groups.minPrice);
            const maxPriceGroup = document.querySelector(groups.maxPrice);
            
            if (!collectiveScopeSelect) return;
            
            const selection = collectiveScopeSelect.value;
            
            if (selection === 'all') {
                // All Items mode: hide item selector, show price filters
                if (collectiveItemsGroup) collectiveItemsGroup.style.display = 'none';
                if (minPriceGroup) minPriceGroup.style.display = 'block';
                if (maxPriceGroup) maxPriceGroup.style.display = 'block';
                
                // Set is_all_items flag
                if (isAllItemsInput) isAllItemsInput.value = 'true';
                
                // Update tab indices for all items mode
                this.updateTabIndices('collective_move', true);
            } else {
                // Specific Items mode: show item selector, hide price filters
                if (collectiveItemsGroup) collectiveItemsGroup.style.display = 'block';
                if (minPriceGroup) minPriceGroup.style.display = 'none';
                if (maxPriceGroup) maxPriceGroup.style.display = 'none';
                
                // Clear is_all_items flag
                if (isAllItemsInput) isAllItemsInput.value = 'false';
                
                // Update tab indices for specific items mode
                this.updateTabIndices('collective_move', false);
            }
        },

        /**
         * Handles changes to the threshold alert "Items Tracked" dropdown.
         * 
         * What: Shows/hides the item selector and manages threshold type based on selection
         * Why: When "All Items" is selected, items selector is hidden and threshold type is locked to percentage
         *      When "Specific Items" is selected, items selector is shown and threshold type can be changed
         * How: Toggles visibility of items group and enforces percentage type for multi-item scenarios
         * 
         * @param {string} formType - 'create' for create form
         */
        handleThresholdItemsTrackedChange(formType) {
            const selectors = AlertsConfig.selectors[formType];
            const groups = selectors.groups;
            
            // Get the items tracked selection
            const itemsTrackedSelect = document.querySelector(selectors.thresholdItemsTracked);
            const thresholdItemsGroup = document.querySelector(groups.thresholdItems);
            const thresholdTypeSelect = document.querySelector(selectors.thresholdType);
            const isAllItemsInput = document.querySelector(selectors.isAllItems);
            
            // minPriceGroup/maxPriceGroup: Price filter containers for "all items" mode
            // What: DOM elements for minimum and maximum price filter inputs
            // Why: When tracking all items, users need to filter by price range to avoid noise
            // How: Show these fields only when "All Items" is selected
            const minPriceGroup = document.querySelector(groups.minPrice);
            const maxPriceGroup = document.querySelector(groups.maxPrice);
            
            if (!itemsTrackedSelect) return;
            
            const selection = itemsTrackedSelect.value;
            
            if (selection === 'all') {
                // All Items mode: hide item selector, show price filters, lock threshold type to percentage
                if (thresholdItemsGroup) thresholdItemsGroup.style.display = 'none';
                if (isAllItemsInput) isAllItemsInput.value = 'true';
                
                // Show min/max price filters for all items mode
                // What: Display price range filters when tracking all items
                // Why: Users need to filter which items to monitor based on price range
                // How: Set display to 'block' for both min and max price groups
                if (minPriceGroup) minPriceGroup.style.display = 'block';
                if (maxPriceGroup) maxPriceGroup.style.display = 'block';
                
                // Force percentage type for all items (can't use value for all items)
                if (thresholdTypeSelect) {
                    thresholdTypeSelect.value = 'percentage';
                    thresholdTypeSelect.disabled = true;
                }
                
                // Show locked indicator since threshold type is forced to percentage
                // What: Display 🚫 icon to indicate dropdown is locked
                // Why: Users need visual feedback that they cannot change this setting
                // How: Call helper function that manages indicator visibility
                this.updateThresholdTypeLockIndicator(true);
                
                // Clear any selected items
                ThresholdMultiItemSelector.clear();
                
                // Update tabindex values for All Items mode
                this.updateTabIndices('threshold', true);
            } else {
                // Specific Items mode: show item selector, hide price filters
                if (thresholdItemsGroup) thresholdItemsGroup.style.display = 'block';
                if (isAllItemsInput) isAllItemsInput.value = 'false';
                
                // Hide min/max price filters for specific items mode
                // What: Hide price range filters when tracking specific items
                // Why: Price filters only apply to "all items" mode where we need to narrow down
                // How: Set display to 'none' for both min and max price groups
                if (minPriceGroup) minPriceGroup.style.display = 'none';
                if (maxPriceGroup) maxPriceGroup.style.display = 'none';
                
                // Hide locked indicator (updateThresholdTypeState will re-show if needed)
                // What: Initially hide the locked indicator when switching to specific items
                // Why: Indicator should only show if multiple items are selected
                // How: Call helper function, then let updateThresholdTypeState decide
                this.updateThresholdTypeLockIndicator(false);
                
                // Check if threshold type should be enabled or disabled based on item count
                this.updateThresholdTypeState();
                
                // Update tabindex values for Specific Items mode
                this.updateTabIndices('threshold', false);
            }
        },

        /**
         * Updates the threshold type dropdown state based on selected item count.
         * 
         * What: Enables/disables threshold type dropdown based on number of selected items
         * Why: Value-based threshold only makes sense for single item; percentage works for multiple
         * How: If more than 1 item selected, force percentage and disable dropdown
         */
        updateThresholdTypeState() {
            const thresholdTypeSelect = document.querySelector(AlertsConfig.selectors.create.thresholdType);
            const selectedCount = ThresholdMultiItemSelector.selectedItems.length;
            // lockedIndicator: The 🚫 icon that appears when dropdown is locked
            const lockedIndicator = document.getElementById('threshold-type-locked-indicator');
            // lockedTooltip: The explanation popup that appears when indicator is clicked
            const lockedTooltip = document.getElementById('threshold-type-locked-tooltip');
            
            if (!thresholdTypeSelect) return;
            
            if (selectedCount > 1) {
                // Multiple items: force percentage type and show locked indicator
                // What: Lock the dropdown and display the locked indicator
                // Why: Value-based thresholds don't work with multiple items (each has different price)
                // How: Disable select, show 🚫 icon, hide any open tooltip
                thresholdTypeSelect.value = 'percentage';
                thresholdTypeSelect.disabled = true;
                if (lockedIndicator) lockedIndicator.style.display = 'inline-block';
            } else {
                // Single or no items: allow choice and hide locked indicator
                // What: Unlock the dropdown and hide the locked indicator
                // Why: Value-based thresholds are valid for single item monitoring
                // How: Enable select, hide 🚫 icon and tooltip
                thresholdTypeSelect.disabled = false;
                if (lockedIndicator) lockedIndicator.style.display = 'none';
                if (lockedTooltip) lockedTooltip.style.display = 'none';
            }
        },
        
        /**
         * Shows/hides the locked indicator for threshold type based on "All Items" mode.
         * 
         * What: Manages the locked indicator visibility when switching to/from All Items
         * Why: All Items mode forces percentage type, so users need visual feedback
         * How: Shows indicator when isAllItems is true, hides when false (unless multiple items selected)
         * 
         * @param {boolean} isAllItems - Whether "All Items" mode is selected
         */
        updateThresholdTypeLockIndicator(isAllItems) {
            const lockedIndicator = document.getElementById('threshold-type-locked-indicator');
            const lockedTooltip = document.getElementById('threshold-type-locked-tooltip');
            
            if (isAllItems) {
                // All Items mode: show locked indicator
                if (lockedIndicator) lockedIndicator.style.display = 'inline-block';
            } else {
                // Specific Items mode: let updateThresholdTypeState handle visibility
                // (it will show indicator if multiple items are selected)
                if (lockedIndicator) lockedIndicator.style.display = 'none';
                if (lockedTooltip) lockedTooltip.style.display = 'none';
            }
        },

        /**
         * Updates form fields based on spread scope selection.
         * 
         * What: Shows/hides form fields based on spread scope (all, specific, multiple)
         * Why: Different scope options require different input fields
         * How:
         *   - "all": Show min/max price filters, hide item selectors
         *   - "specific": Show single item selector, hide min/max and multi-item
         *   - "multiple": Show multi-item selector, hide single item and min/max
         * 
         * @param {string} formType - 'create' for create form
         */
        handleSpreadScopeChange(formType) {
            const selectors = AlertsConfig.selectors[formType];
            const spreadScope = document.querySelector(selectors.spreadScope).value;
            const groups = selectors.groups;

            // itemNameGroup: Container for single item name input
            const itemNameGroup = document.querySelector(groups.itemName);
            // spreadItemsGroup: Container for multi-item selector
            const spreadItemsGroup = document.querySelector(groups.spreadItems);
            // minPriceGroup/maxPriceGroup: Price filter containers for "all items" mode
            const minPriceGroup = document.querySelector(groups.minPrice);
            const maxPriceGroup = document.querySelector(groups.maxPrice);
            // isAllItemsInput: Hidden field that tells the backend if this is an all-items alert
            const isAllItemsInput = document.querySelector(selectors.isAllItems);

            if (spreadScope === 'all') {
                // All Items mode: show price filters, hide item selectors
                itemNameGroup.style.display = 'none';
                if (spreadItemsGroup) spreadItemsGroup.style.display = 'none';
                minPriceGroup.style.display = 'block';
                maxPriceGroup.style.display = 'block';
                isAllItemsInput.value = 'true';
                // Clear the multi-item selector when switching away
                SpreadMultiItemSelector.clear();
                // Update tabindex values for All Items mode
                this.updateTabIndices('spread', true);
            } else if (spreadScope === 'multiple') {
                // Multiple Specific Items mode: show multi-item selector, hide single item and price filters
                itemNameGroup.style.display = 'none';
                if (spreadItemsGroup) spreadItemsGroup.style.display = 'block';
                minPriceGroup.style.display = 'none';
                maxPriceGroup.style.display = 'none';
                isAllItemsInput.value = 'false';
                // Update tabindex values for Specific Items mode
                this.updateTabIndices('spread', false);
            } else {
                // Single Specific Item mode: show single item input, hide multi-item and price filters
                itemNameGroup.style.display = 'block';
                if (spreadItemsGroup) spreadItemsGroup.style.display = 'none';
                minPriceGroup.style.display = 'none';
                maxPriceGroup.style.display = 'none';
                isAllItemsInput.value = 'false';
                // Clear the multi-item selector when switching away
                SpreadMultiItemSelector.clear();
                // Update tabindex values for Specific Items mode
                this.updateTabIndices('spread', false);
            }
        },

        /**
         * Updates form fields based on spike scope selection.
         * 
         * What: Controls visibility of spike alert form fields based on scope dropdown
         * Why: Spike alerts can monitor all items or specific item(s) - the multi-item selector handles both single and multiple items
         * How: Shows/hides appropriate fields and updates hidden is_all_items flag
         *
         * @param {string} formType - 'create' for create form
         */
        handleSpikeScopeChange(formType) {
            const selectors = AlertsConfig.selectors[formType];
            const spikeScopeSelect = document.querySelector(selectors.spikeScope);
            const groups = selectors.groups;
            
            // itemNameGroup: Container for single item name input (no longer used for spike alerts)
            const itemNameGroup = document.querySelector(groups.itemName);
            // spikeItemsGroup: Container for multi-item selector (handles both single and multiple items)
            const spikeItemsGroup = document.querySelector(groups.spikeItems);
            // minPriceGroup/maxPriceGroup: Price filter containers for "all items" mode
            const minPriceGroup = document.querySelector(groups.minPrice);
            const maxPriceGroup = document.querySelector(groups.maxPrice);
            // isAllItemsInput: Hidden field that tells the backend if this is an all-items alert
            const isAllItemsInput = document.querySelector(selectors.isAllItems);

            // selection: Current value of the spike scope dropdown
            // What: Get the selected scope option
            // Why: Determines which form fields to show/hide
            // How: Read value from dropdown, default to 'multiple' (specific items mode)
            const selection = spikeScopeSelect ? spikeScopeSelect.value : 'multiple';

            if (selection === 'all') {
                // All Items mode: show price filters, hide item selectors
                // What: Configure form for monitoring all items
                // Why: When tracking all items, users need price range filters instead of item selectors
                // How: Hide item inputs, show price filters, set is_all_items flag to true
                if (itemNameGroup) itemNameGroup.style.display = 'none';
                if (spikeItemsGroup) spikeItemsGroup.style.display = 'none';
                if (minPriceGroup) minPriceGroup.style.display = 'block';
                if (maxPriceGroup) maxPriceGroup.style.display = 'block';
                if (isAllItemsInput) isAllItemsInput.value = 'true';
                // Clear the multi-item selector when switching to all items mode
                if (typeof SpikeMultiItemSelector !== 'undefined') {
                    SpikeMultiItemSelector.clear();
                }
                // Update tabindex values for All Items mode
                this.updateTabIndices('spike', true);
            } else {
                // Specific Item(s) mode: show multi-item selector, hide price filters
                // What: Configure form for monitoring specific item(s)
                // Why: Multi-item selector handles both single and multiple item selection
                // How: Show multi-item selector, hide legacy single item input and price filters
                if (itemNameGroup) itemNameGroup.style.display = 'none';
                if (spikeItemsGroup) spikeItemsGroup.style.display = 'block';
                if (minPriceGroup) minPriceGroup.style.display = 'none';
                if (maxPriceGroup) maxPriceGroup.style.display = 'none';
                if (isAllItemsInput) isAllItemsInput.value = 'false';
                // Update tabindex values for Specific Items mode
                this.updateTabIndices('spike', false);
            }
        },

        /**
         * Updates form fields based on sustained move scope selection.
         */
        handleSustainedScopeChange(formType) {
            const selectors = AlertsConfig.selectors[formType];
            const sustainedScopeSelect = document.querySelector(selectors.sustainedScope);
            const groups = selectors.groups;
            const sustainedItemsGroup = document.querySelector(groups.sustainedItems);
            const minPriceGroup = document.querySelector(groups.minPrice);
            const maxPriceGroup = document.querySelector(groups.maxPrice);
            const isAllItemsInput = document.querySelector(selectors.isAllItems);

            const selection = sustainedScopeSelect ? sustainedScopeSelect.value : 'specific';
            const isAll = selection === 'all';

            if (sustainedItemsGroup) sustainedItemsGroup.style.display = isAll ? 'none' : 'block';
            if (minPriceGroup) minPriceGroup.style.display = isAll ? 'block' : 'none';
            if (maxPriceGroup) maxPriceGroup.style.display = isAll ? 'block' : 'none';
            if (isAllItemsInput) isAllItemsInput.value = isAll ? 'true' : 'false';
            
            // Update tabindex values based on scope
            // What: Adjust tab order to match visual layout
            // Why: "All Items" mode shows different fields than "Specific Items" mode
            // How: Call updateTabIndices with the appropriate scope flag
            this.updateTabIndices('sustained', isAll);
        }
    };


    // =============================================================================
    // MODAL MANAGEMENT
    // =============================================================================
    /**
     * Controls modal dialogs (spread details modal and spike details modal).
     * 
     * Why: Modals have common behavior that should be handled consistently.
     */
    const ModalManager = {
        /**
         * Opens spread details modal with matching items.
         */
        showSpreadDetails(alertId) {
            const dataStr = AlertsState.getSpreadData(alertId);

            if (!dataStr) {
                console.error('No spread data found for alert', alertId);
                return;
            }

            const data = JSON.parse(dataStr);
            const list = document.querySelector(AlertsConfig.selectors.spreadItemsList);
            list.innerHTML = AlertsUI.renderSpreadItemsList(data);

            document.querySelector(AlertsConfig.selectors.spreadModal).style.display = 'flex';
        },

        /**
         * Closes the spread details modal.
         */
        closeSpreadModal() {
            document.querySelector(AlertsConfig.selectors.spreadModal).style.display = 'none';
        },

        /**
         * Opens spike details modal with matching items.
         */
        showSpikeDetails(alertId) {
            const dataStr = AlertsState.getSpikeData(alertId);

            if (!dataStr) {
                console.error('No spike data found for alert', alertId);
                return;
            }

            let data = [];
            try {
                data = JSON.parse(dataStr);
            } catch (e) {
                console.error('Failed to parse spike data', e);
                return;
            }
            const list = document.getElementById('spike-items-list');
            if (list) {
                list.innerHTML = AlertsUI.renderSpikeItemsList(data);
            }

            document.getElementById('spike-modal').style.display = 'flex';
        },

        /**
         * Closes the spike details modal.
         */
        closeSpikeModal() {
            const modal = document.getElementById('spike-modal');
            if (modal) modal.style.display = 'none';
        }
    };

