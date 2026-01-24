    // API COMMUNICATION
    // =============================================================================
    /**
     * Handles all server communication.
     * 
     * Why: Centralizing API calls makes it easier to handle errors consistently,
     * modify endpoints, and add features like request caching or retries.
     * 
     * How: Each method corresponds to a specific API action and returns a Promise.
     */
    const AlertsAPI = {
        /**
         * Fetches current alerts data from the server.
         * Returns both active alerts and triggered notifications.
         */
        async fetchAlerts() {
            try {
                const response = await fetch(AlertsConfig.endpoints.alerts);
                return await response.json();
            } catch (error) {
                console.error('Error fetching alerts:', error);
                return null;
            }
        },

        /**
         * Dismisses a triggered alert notification.
         * The alert remains in the system but the notification banner is hidden.
         */
        async dismissAlert(alertId) {
            try {
                await fetch(AlertsConfig.endpoints.dismiss, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': AlertsConfig.csrfToken
                    },
                    body: JSON.stringify({alert_id: alertId})
                });
                return true;
            } catch (error) {
                console.error('Error dismissing alert:', error);
                return false;
            }
        },

        /**
         * Deletes multiple alerts by their IDs.
         */
        async deleteAlerts(alertIds) {
            try {
                await fetch(AlertsConfig.endpoints.delete, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': AlertsConfig.csrfToken
                    },
                    body: JSON.stringify({alert_ids: alertIds})
                });
                return true;
            } catch (error) {
                console.error('Error deleting alerts:', error);
                return false;
            }
        },

        /**
         * Adds alerts to groups (creates groups if needed).
         */
        async groupAlerts(alertIds, groups, newGroups) {
            try {
                await fetch(AlertsConfig.endpoints.group, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': AlertsConfig.csrfToken
                    },
                    body: JSON.stringify({
                        alert_ids: alertIds,
                        groups: groups,
                        new_groups: newGroups
                    })
                });
                return true;
            } catch (error) {
                console.error('Error grouping alerts:', error);
                return false;
            }
        },

        /**
         * Deletes alert groups by name.
         */
        async deleteGroups(groups) {
            try {
                const response = await fetch(AlertsConfig.endpoints.deleteGroups, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': AlertsConfig.csrfToken
                    },
                    body: JSON.stringify({groups})
                });
                if (!response.ok) return false;
                const data = await response.json();
                return !!data.success;
            } catch (error) {
                console.error('Error deleting groups:', error);
                return false;
            }
        },

        /**
         * Updates an existing alert with new values.
         */
        async updateAlert(alertData) {
            try {
                await fetch(AlertsConfig.endpoints.update, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': AlertsConfig.csrfToken
                    },
                    body: JSON.stringify(alertData)
                });
                return true;
            } catch (error) {
                console.error('Error updating alert:', error);
                return false;
            }
        },

        /**
         * Searches for items by name query.
         * Used for autocomplete in item name fields.
         */
        async searchItems(query) {
            try {
                const url = AlertsConfig.endpoints.itemSearch + '?q=' + encodeURIComponent(query);
                const response = await fetch(url);
                return await response.json();
            } catch (error) {
                console.error('Error searching items:', error);
                return [];
            }
        }
    };


    // =============================================================================
