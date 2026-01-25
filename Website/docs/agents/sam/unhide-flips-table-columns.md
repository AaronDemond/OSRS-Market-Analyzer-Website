# Unhide Flips Table Columns on Mobile

**Date:** 2026-01-25  
**Agent:** Sam (Mobile Web Specialist)  
**Task:** Remove column hiding behavior on the flips tracking table for mobile viewports

---

## Problem

The flips tracking table was hiding 4 columns on screens smaller than 1100px:
- **Price Paid** (column 2)
- **Quantity Holding** (column 3)
- **High Price** (column 5)
- **Low Price** (column 6)

This left only 4 columns visible on mobile:
- Item
- Position Size
- Unrealized Net
- Realized Net

Users wanted to see **all 8 columns** on mobile devices.

---

## Solution

Removed the `display: none` CSS rules that were hiding columns in the `@media (max-width: 1100px)` media query.

The table now shows all columns and relies on the existing horizontal scroll wrapper (applied via JavaScript at 900px viewport width) to allow users to scroll horizontally to see all data.

---

## File Changed

**`templates/flips.html`** (lines 1830-1843)

### Before
```css
/* Hide columns on mobile: Price Paid, Quantity Holding, High Price, Low Price */
#flipsTable th:nth-child(2),
#flipsTable td:nth-child(2),
#flipsTable th:nth-child(3),
#flipsTable td:nth-child(3),
#flipsTable th:nth-child(5),
#flipsTable td:nth-child(5),
#flipsTable th:nth-child(6),
#flipsTable td:nth-child(6) {
    display: none;
}

#flipsTable {
    font-size: 0.75rem;
    width: 100%;
    max-width: 100%;
    table-layout: fixed;
}
```

### After
```css
/* =====================================================================
   TABLE COLUMNS - ALL VISIBLE WITH HORIZONTAL SCROLL
   =====================================================================
   What: All 8 table columns remain visible on tablet/mobile viewports
   Why: Users requested full data visibility rather than hiding columns
   How: Removed display:none rules; table uses horizontal scroll wrapper
        that is applied via JavaScript (setupTableScrollWrapper) at 900px
   ===================================================================== */
#flipsTable {
    font-size: 0.75rem;
    width: auto;           /* Allow table to expand beyond viewport width */
    min-width: 100%;       /* At minimum, fill the available space */
    table-layout: auto;    /* Let columns size based on their content */
}
```

---

## How Horizontal Scrolling Works

The existing implementation at `@media (max-width: 900px)` already includes:

1. **JavaScript Scroll Wrapper** (`setupTableScrollWrapper()` function):
   - Wraps the table in a `.table-scroll-wrapper` div
   - Enables `overflow-x: auto` for horizontal scrolling
   - Adds shadow indicators to show when content is scrollable

2. **Sticky First Column**:
   - The Item name column is `position: sticky; left: 0`
   - Stays visible while scrolling horizontally for context

3. **Visual Scroll Indicators**:
   - Left shadow appears when scrolled right (content to the left)
   - Right shadow appears when content is available to the right

---

## Mobile UX Considerations

- **All data visible**: Users can now see all price and P&L information
- **Horizontal scroll**: Swipe gesture to reveal additional columns
- **Sticky item name**: First column stays pinned for context
- **Compact text**: Font size reduced to 0.75rem for space efficiency
- **No text wrapping**: `white-space: nowrap` keeps columns compact

---

## Testing Checklist

- [ ] Verify all 8 columns visible at 1100px viewport width
- [ ] Verify all 8 columns visible at 900px viewport width
- [ ] Verify horizontal scroll works on mobile devices
- [ ] Verify sticky first column works correctly
- [ ] Verify scroll shadow indicators appear/disappear appropriately

---

# Delete Mode and Search UX Improvements

**Date:** 2026-01-25  
**Task:** Fix delete mode cancellation, add mobile instruction modal, fix search scroll on mobile

---

## Problems

1. **Delete mode couldn't be cancelled** - Once delete was clicked, there was no way to cancel without clicking the button again
2. **No guidance on mobile** - Mobile users didn't know they needed to tap a row after clicking delete
3. **Search input hidden by keyboard** - On mobile, when the search icon was clicked, the keyboard covered the input field

---

## Solutions

### 1. Delete Mode Auto-Cancel

Added a global click listener that cancels delete mode when the user clicks anywhere outside the table.

**New behavior:**
- Click anywhere outside the flips table → delete mode cancels
- Click on another button/control → delete mode cancels
- Navigate away from page → delete mode cancels (beforeunload listener)
- Click the delete button again → delete mode cancels (existing behavior)

**Code added (around line 4990):**
```javascript
document.addEventListener('click', function(e) {
    if (!deleteMode || isProcessing) return;

    const flipsTable = document.getElementById('flipsTable');
    const mobileActionsBtn = document.getElementById('mobileActionsBtn');
    const mobileActionMenu = document.getElementById('mobileActionMenu');

    const isInsideTable = flipsTable && flipsTable.contains(e.target);
    const isDeleteButton = deleteBtn.contains(e.target);
    const isMobileActions = (mobileActionsBtn && mobileActionsBtn.contains(e.target)) ||
                           (mobileActionMenu && mobileActionMenu.contains(e.target));

    if (!isInsideTable && !isDeleteButton && !isMobileActions) {
        cancelDeleteMode();
    }
});
```

### 2. Mobile Delete Instruction Modal

Added a new modal that appears only on mobile when delete mode is activated.

**New HTML (after delete confirm modal):**
```html
<div class="modal fade delete-instruction-modal" id="deleteInstructionModal" ...>
    <div class="modal-dialog modal-dialog-centered modal-sm">
        <div class="modal-content">
            <div class="modal-body text-center">
                <div class="instruction-icon">
                    <!-- Tap/pointer icon -->
                </div>
                <h6 class="instruction-title">Tap a flip to delete</h6>
                <p class="instruction-text">Tap on any row in the table to select it for deletion.</p>
                <button type="button" class="btn-got-it" data-bs-dismiss="modal">Got it</button>
            </div>
        </div>
    </div>
</div>
```

**CSS styles added:**
- Orange-themed icon container matching delete mode color
- Clean, centered layout with clear typography
- "Got it" button with orange gradient to match delete mode

**JavaScript logic:**
```javascript
if (isDeleteMobile()) {
    const instructionModal = new bootstrap.Modal(document.getElementById('deleteInstructionModal'));
    instructionModal.show();
}
```

### 3. Search Input Scroll on Mobile (with Collapse Fix)

Updated the search focus handler to scroll the input into view when the keyboard appears. Also fixed a bug where the search bar would immediately collapse after expanding due to blur events triggered by `scrollIntoView`.

**Problem:** The search bar would expand momentarily, then immediately collapse because:
1. `scrollIntoView()` can cause the input to lose focus (triggering blur)
2. The blur handler would then collapse the search bar after 200ms delay
3. Document-level click handlers could interfere with the expansion

**Solution:** Added an `isExpandingSearch` flag to prevent collapse during expansion:

```javascript
let isExpandingSearch = false;

filterSearchInput.addEventListener('focus', function() {
    if (isMobile()) {
        // Set flag to prevent blur from collapsing during expansion
        isExpandingSearch = true;

        filterSearchWrapper.classList.remove('collapsed');
        filterSearchWrapper.classList.add('expanded');

        setTimeout(function() {
            filterSearchWrapper.scrollIntoView({
                behavior: 'smooth',
                block: 'center'
            });

            // Clear flag after scroll animation completes
            setTimeout(function() {
                isExpandingSearch = false;
            }, 500);
        }, 300);
    }
});

filterSearchInput.addEventListener('blur', function() {
    // Don't collapse if we're in the middle of expanding
    if (isExpandingSearch) {
        return;
    }

    if (isMobile() && !filterSearchInput.value) {
        setTimeout(function() {
            // Double-check we're still not focused
            if (document.activeElement !== filterSearchInput && !filterSearchInput.value) {
                filterSearchWrapper.classList.add('collapsed');
                filterSearchWrapper.classList.remove('expanded');
            }
        }, SEARCH_COLLAPSE_DELAY_MS);
    }
});

// Also added e.stopPropagation() to wrapper click handler
filterSearchWrapper.addEventListener('click', function(e) {
    if (isMobile() && filterSearchWrapper.classList.contains('collapsed')) {
        e.stopPropagation(); // Prevent document click handlers from interfering
        filterSearchInput.focus();
    }
});
```

**Key improvements:**
- `isExpandingSearch` flag prevents premature collapse
- Double-check in blur handler ensures input isn't re-focused
- `e.stopPropagation()` prevents document click handlers from causing issues

---

## Files Changed

**`templates/flips.html`:**
- Added delete instruction modal HTML (after line 3058)
- Added CSS for `.delete-instruction-modal` (after line 1450)
- Rewrote delete mode JavaScript with:
  - `isDeleteMobile()` helper function
  - Global click listener to cancel delete mode
  - `beforeunload` listener for page navigation
  - Mobile instruction modal trigger
- Updated search focus handler with `scrollIntoView()`

---

## Testing Checklist

### Delete Mode Cancellation
- [ ] Click delete button, then click outside table → mode cancels
- [ ] Click delete button, then click Historical button → mode cancels
- [ ] Click delete button, then click Filter button → mode cancels
- [ ] Click delete button, then click inside table row → row selected (expected)
- [ ] Click delete button twice → mode cancels (existing behavior)

### Mobile Instruction Modal
- [ ] On mobile (≤900px), click delete → instruction modal appears
- [ ] Tap "Got it" → modal closes, delete mode still active
- [ ] Tap outside modal → modal closes, delete mode still active
- [ ] On desktop (>900px), click delete → no modal appears

### Search Scroll
- [ ] On mobile, tap search icon → keyboard appears, search bar scrolls into view
- [ ] Search bar should be centered in visible area above keyboard
- [ ] Smooth scroll animation occurs
