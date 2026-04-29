/**
 * Client-side validation for integer overflow on the alerts page.
 *
 * Django's IntegerField has a documented range of -2147483648 to 2147483647
 * (signed 32-bit). Any user-entered value outside that range will be rejected
 * server-side. This script provides immediate, client-side feedback by showing
 * a warning beneath any number input whose value exceeds the bounds.
 *
 * The warning is informational only — it does not block submission so the
 * server remains the source of truth.
 */
(function () {
    'use strict';

    const INT_MAX = 2147483647;
    const INT_MIN = -2147483648;
    const WARNING_CLASS = 'int-overflow-warning';

    function getOrCreateWarning(input) {
        let warn = input.parentElement
            ? input.parentElement.querySelector('.' + WARNING_CLASS)
            : null;
        if (!warn) {
            warn = document.createElement('small');
            warn.className = WARNING_CLASS;
            warn.setAttribute('role', 'alert');
            warn.style.display = 'none';
            warn.style.color = '#d9534f';
            warn.style.marginTop = '4px';
            warn.style.fontSize = '0.85em';
            // Insert directly after the input so it sits with any existing
            // .form-hint sibling without disrupting layout.
            if (input.nextSibling) {
                input.parentElement.insertBefore(warn, input.nextSibling);
            } else {
                input.parentElement.appendChild(warn);
            }
        }
        return warn;
    }

    function validate(input) {
        const raw = input.value;
        if (raw === '' || raw === null || raw === undefined) {
            const existing = input.parentElement
                ? input.parentElement.querySelector('.' + WARNING_CLASS)
                : null;
            if (existing) existing.style.display = 'none';
            return;
        }
        const value = Number(raw);
        if (!Number.isFinite(value)) {
            return;
        }
        const warn = getOrCreateWarning(input);
        if (value > INT_MAX) {
            warn.textContent =
                'Value exceeds the maximum allowed (' +
                INT_MAX.toLocaleString() +
                ').';
            warn.style.display = 'block';
        } else if (value < INT_MIN) {
            warn.textContent =
                'Value is below the minimum allowed (' +
                INT_MIN.toLocaleString() +
                ').';
            warn.style.display = 'block';
        } else {
            warn.style.display = 'none';
        }
    }

    function attach(input) {
        if (input.dataset.intOverflowBound === '1') return;
        input.dataset.intOverflowBound = '1';
        input.addEventListener('input', function () {
            validate(input);
        });
        input.addEventListener('blur', function () {
            validate(input);
        });
    }

    function init() {
        const inputs = document.querySelectorAll('input[type="number"]');
        inputs.forEach(attach);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
