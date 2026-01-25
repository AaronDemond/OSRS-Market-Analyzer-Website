# Mobile Flips Page Test Checklist

## Overview
This document outlines the test procedures for the mobile overhaul of the My Flips page (`flips.html`).

## Test Environment
- **Device Sizes to Test**: 
  - Mobile: 320px - 480px width
  - Tablet: 481px - 900px width
  - Desktop: 901px+ width
- **Browsers**: Chrome, Firefox, Safari (iOS), Chrome (Android)

---

## 1. Mobile Controls Tests (max-width: 900px)

### 1.1 Action Dropdown Menu
**Expected Behavior**: On mobile, "New Flip" and "Delete Flip" buttons are hidden and replaced with a three-dot menu button.

**Test Steps**:
1. Resize browser to mobile width (< 900px)
2. Verify three-dot icon button is visible in the buttons row
3. Click the action menu button
4. Verify dropdown menu appears with "New Flip" and "Delete Flip" options
5. Click "New Flip" option
   - ✅ New Flip modal should open
6. Close modal, reopen action menu
7. Click "Delete Flip" option
   - ✅ Delete mode should activate (same behavior as desktop button)
8. Click outside the menu
   - ✅ Menu should close

**Pass Criteria**:
- [ ] Action dropdown button visible on mobile
- [ ] Desktop action buttons hidden on mobile
- [ ] Menu opens/closes correctly
- [ ] "New Flip" triggers modal
- [ ] "Delete Flip" activates delete mode
- [ ] Menu button shows active state when in delete mode (orange gradient)

---

### 1.2 Collapsible Search Bar
**Expected Behavior**: Search bar collapses to a search icon button, expands when clicked or focused.

**Test Steps**:
1. On mobile view, verify search bar shows as icon-only button (44x44px)
2. Click the search icon
   - ✅ Search bar should expand to full width
   - ✅ Input should receive focus
3. Type a search query
   - ✅ Clear button (×) should appear
   - ✅ Table should filter results
4. Click outside search bar (while empty)
   - ✅ Search bar should collapse back to icon
5. Type in search bar, then click outside
   - ✅ Search bar should remain expanded (has value)
6. Clear the search
   - ✅ Search bar should collapse after blur

**Pass Criteria**:
- [ ] Search collapses to icon on mobile by default
- [ ] Search icon is visible and centered in collapsed state
- [ ] Clicking icon expands search and focuses input
- [ ] Search expands/collapses correctly based on focus and value
- [ ] Search functionality works in both states
- [ ] Smooth transition animation between states

---

### 1.3 Icon-Only Buttons
**Expected Behavior**: Historical and Filter buttons show icon only (no text labels).

**Test Steps**:
1. On mobile view, locate Historical button
   - ✅ Should show clock icon only
   - ✅ Button should be 44x44px (minimum tap target)
2. Locate Filter button
   - ✅ Should show filter icon only
   - ✅ Filter badge should be visible if filters are active (positioned top-right)
3. Click Historical button
   - ✅ Historical modal should open
4. Click Filter button
   - ✅ Filter dropdown should open

**Pass Criteria**:
- [ ] Historical button text hidden on mobile
- [ ] Filter button text hidden on mobile
- [ ] Both buttons are easily tappable (44x44px minimum)
- [ ] Icons are clearly visible and sized appropriately
- [ ] All functionality preserved

---

### 1.4 Active Filter Badges
**Expected Behavior**: Active filters display as compact badges below the controls.

**Test Steps**:
1. On mobile, open filter dropdown
2. Apply a filter (e.g., Position Size)
3. Verify filter badge appears in the mobile sort indicator row
4. Apply multiple filters
   - ✅ All filter badges should display
   - ✅ Badges should wrap to multiple lines if needed
5. Click × on a filter badge
   - ✅ Filter should be removed
   - ✅ Badge should disappear

**Pass Criteria**:
- [ ] Filter badges display below controls on mobile
- [ ] Badges are compact and readable
- [ ] Remove button (×) works correctly
- [ ] Multiple badges wrap properly
- [ ] Desktop filter tags row is hidden on mobile

---

### 1.5 Compact Sort Indicator
**Expected Behavior**: Sort indicator displays compactly in mobile sort indicator row.

**Test Steps**:
1. Click a column header to sort
2. Verify sort indicator appears below controls
3. Click sort indicator value
   - ✅ Sort menu should open
4. Click sort arrow
   - ✅ Sort direction should toggle

**Pass Criteria**:
- [ ] Desktop inline sort indicator hidden on mobile
- [ ] Mobile sort indicator shows in separate row
- [ ] Sort indicator is compact and readable
- [ ] All sort functionality works

---

## 2. Mobile Table Tests

### 2.1 Show All Columns
**Expected Behavior**: All table columns are visible (not hidden) and accessible via horizontal scroll.

**Test Steps**:
1. On mobile view, locate the flips table
2. Verify the following columns are ALL visible:
   - Item
   - Price Paid
   - Quantity Holding
   - Position Size
   - High Price
   - Low Price
   - Unrealized Net
   - Realized Net
3. Verify table is readable but compact
   - ✅ Font size reduced appropriately
   - ✅ Padding is compact but usable

**Pass Criteria**:
- [ ] ALL 8 columns are visible on mobile
- [ ] No columns are hidden
- [ ] Text is readable despite smaller size
- [ ] Data is properly formatted

---

### 2.2 Horizontal Scroll Container
**Expected Behavior**: Table scrolls horizontally within a container, page does not scroll horizontally.

**Test Steps**:
1. On mobile, verify table is wider than screen
2. Try to scroll the page horizontally
   - ✅ Page should NOT scroll horizontally
3. Scroll the table horizontally (swipe left/right)
   - ✅ Table should scroll smoothly
   - ✅ All columns should be accessible
4. Verify first column (Item) is sticky
   - ✅ Item column stays visible while scrolling
   - ✅ Provides context for which row you're viewing

**Pass Criteria**:
- [ ] Table scrolls horizontally
- [ ] Page body does not scroll horizontally
- [ ] Smooth scrolling experience
- [ ] First column (Item) is sticky/fixed
- [ ] All data is accessible

---

### 2.3 Visual Scroll Indicators
**Expected Behavior**: Shadow gradients indicate scroll position.

**Test Steps**:
1. On mobile, verify table is at leftmost position
   - ✅ No left shadow should be visible
   - ✅ Right shadow should be visible (indicating more content)
2. Scroll table to the right
   - ✅ Left shadow should appear
   - ✅ Right shadow should remain
3. Scroll to rightmost position
   - ✅ Left shadow should remain visible
   - ✅ Right shadow should disappear
4. Scroll back to middle
   - ✅ Both shadows should be visible

**Pass Criteria**:
- [ ] Right shadow visible when not scrolled to end
- [ ] Left shadow visible when scrolled away from start
- [ ] Shadows update in real-time during scroll
- [ ] Shadows are subtle but noticeable
- [ ] Custom scrollbar is visible and usable

---

## 3. Responsive Behavior Tests

### 3.1 Viewport Resize
**Expected Behavior**: Layout adapts correctly when resizing between mobile and desktop.

**Test Steps**:
1. Start at desktop width (> 900px)
   - ✅ Desktop layout should be visible
2. Slowly resize to mobile width (< 900px)
   - ✅ Mobile layout should activate
   - ✅ All mobile features should work
3. Resize back to desktop
   - ✅ Desktop layout should restore
   - ✅ No layout issues or broken features

**Pass Criteria**:
- [ ] Smooth transition between layouts
- [ ] No JavaScript errors during resize
- [ ] All features work after resizing
- [ ] Table scroll wrapper adds/removes correctly

---

### 3.2 Touch Interactions
**Expected Behavior**: All controls are easily tappable on touch devices.

**Test Steps**:
1. On a real mobile device or touch simulator:
2. Test tapping all buttons
   - Action dropdown button
   - Search icon
   - Historical button
   - Filter button
3. Verify tap targets are comfortable
   - ✅ Minimum 44x44px size met
   - ✅ No accidental taps on adjacent controls
4. Test swipe gestures on table
   - ✅ Horizontal swipe scrolls table
   - ✅ Vertical swipe scrolls page

**Pass Criteria**:
- [ ] All buttons have 44x44px minimum tap target
- [ ] Buttons don't overlap or interfere
- [ ] Touch scrolling works naturally
- [ ] No touch interaction bugs

---

## 4. Visual Design Tests

### 4.1 Color Scheme Consistency
**Expected Behavior**: Mobile maintains existing color scheme.

**Test Steps**:
1. Compare colors between desktop and mobile
   - ✅ Primary colors match
   - ✅ Button styles consistent
   - ✅ Hover/active states work

**Pass Criteria**:
- [ ] Colors match design system
- [ ] No visual regressions
- [ ] Consistent styling

---

### 4.2 Typography
**Expected Behavior**: Text is readable at mobile sizes.

**Test Steps**:
1. Verify all text is legible
2. Check font sizes are appropriate
3. Ensure proper contrast

**Pass Criteria**:
- [ ] All text readable
- [ ] Font sizes appropriate
- [ ] Good contrast ratios

---

## 5. Functionality Tests

### 5.1 All Features Work on Mobile
**Expected Behavior**: All page functionality works identically to desktop.

**Test Steps**:
1. Test sorting by clicking headers
2. Test filtering with all filter types
3. Test search functionality
4. Test adding a new flip
5. Test deleting a flip
6. Test historical view

**Pass Criteria**:
- [ ] Sorting works
- [ ] Filtering works
- [ ] Search works
- [ ] New flip works
- [ ] Delete flip works
- [ ] Historical view works
- [ ] No mobile-specific bugs

---

## 6. Performance Tests

### 6.1 Load Time
**Expected Behavior**: Page loads quickly on mobile devices.

**Test Steps**:
1. Clear cache
2. Load page on mobile
3. Measure load time

**Pass Criteria**:
- [ ] Page loads in < 3 seconds
- [ ] No excessive layout shifts
- [ ] Smooth animations

---

### 6.2 Scroll Performance
**Expected Behavior**: Scrolling is smooth with no jank.

**Test Steps**:
1. Scroll table horizontally
2. Scroll page vertically
3. Monitor frame rate

**Pass Criteria**:
- [ ] No jank during scroll
- [ ] 60fps maintained
- [ ] No memory leaks

---

## 7. Browser Compatibility

### 7.1 Cross-Browser Testing
**Test on**:
- [ ] Chrome Mobile (Android)
- [ ] Safari Mobile (iOS)
- [ ] Firefox Mobile
- [ ] Chrome Desktop (mobile viewport)
- [ ] Firefox Desktop (mobile viewport)
- [ ] Safari Desktop (mobile viewport)

**Pass Criteria**:
- [ ] Layout consistent across browsers
- [ ] All features work
- [ ] No browser-specific bugs

---

## Test Summary

**Total Tests**: ~40 individual test cases across 7 categories

**Critical Path Tests** (must pass):
1. Action dropdown shows and works
2. All table columns visible
3. Table scrolls horizontally
4. Page doesn't scroll horizontally
5. Search collapses/expands
6. All buttons are tappable (44x44px)

**Sign-off Required**:
- [ ] All critical tests pass
- [ ] No blocking bugs found
- [ ] Performance acceptable
- [ ] Cross-browser compatibility confirmed

---

## Notes
- Test on real devices when possible, not just browser simulators
- Pay special attention to touch interactions
- Verify on slow network connections
- Test with real data (many rows)
