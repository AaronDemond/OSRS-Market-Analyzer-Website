# Mobile Flips Page - Visual Verification Guide

This guide provides visual reference points to quickly verify the mobile overhaul is working correctly.

---

## Quick Visual Checks

### 1. Desktop View (> 900px width)

**What You Should See**:
```
[New Flip] [Delete Flip]  [Search____________] [Historical] [Filters]
```

✅ Two separate action buttons (New Flip, Delete Flip)  
✅ Full-width search bar with placeholder text  
✅ Historical button with text label  
✅ Filters button with text label  
✅ Sort indicator inline with search (if active)  
✅ Filter tags in separate row below (if active)

**What You Should NOT See**:
❌ Three-dot menu button  
❌ Search icon-only button  
❌ Icon-only Historical/Filter buttons

---

### 2. Mobile View (< 900px width)

**What You Should See**:
```
[⋮]  [🔍] [🕐] [🔽]
     ↓ Mobile sort indicator (if active)
     ↓ Filter badges (if active)
```

✅ Three-dot action menu button (⋮)  
✅ Collapsed search as icon button (🔍)  
✅ Historical as icon-only (🕐)  
✅ Filter as icon-only (🔽)  
✅ Sort indicator below controls (when active)  
✅ Filter badges below controls (when active)

**What You Should NOT See**:
❌ "New Flip" button text  
❌ "Delete Flip" button text  
❌ "Historical" text label  
❌ "Filters" text label  
❌ Expanded search bar (unless clicked)  
❌ Inline sort indicator with search row

---

## Detailed Component Checks

### Mobile Action Dropdown

**Collapsed State**:
- Single icon button with three vertical dots (⋮)
- 44x44px square button
- Same styling as other control buttons
- Orange gradient when delete mode active

**Expanded State** (after clicking):
- Dropdown menu appears below button
- Two items in menu:
  1. New Flip (with + icon)
  2. Delete Flip (with trash icon)
- Menu has rounded corners, shadow
- Light gray/beige hover effect

---

### Collapsible Search Bar

**Collapsed State** (default on mobile):
- Square button, 44x44px
- Centered search icon (🔍)
- No visible placeholder text
- No clear button (×)

**Expanded State** (after clicking/focusing):
- Full-width search bar
- Input field with placeholder "Search..."
- Clear button (×) appears when typing
- Smooth expansion animation (~0.3s)

**Behavior**:
- Clicking collapsed search → expands and focuses
- Typing → clear button appears
- Blur with empty value → collapses back
- Blur with text → stays expanded
- Clearing text then blurring → collapses

---

### Icon-Only Buttons

**Historical Button**:
- Clock icon (🕐) only, no text
- 44x44px square
- Blue highlight on hover
- Opens modal on click

**Filter Button**:
- Filter/funnel icon (🔽) only, no text
- 44x44px square
- Badge shows count (top-right corner, red circle)
- Opens dropdown on click

---

### Table Display

**Mobile Table View**:
- All 8 columns visible:
  1. Item (sticky on left)
  2. Price Paid
  3. Quantity Holding
  4. Position Size
  5. High Price
  6. Low Price
  7. Unrealized Net
  8. Realized Net

**Scroll Behavior**:
- Horizontal scrollbar at bottom
- Left shadow when scrolled right
- Right shadow when can scroll more right
- First column (Item) stays fixed
- Page doesn't scroll horizontally

**Visual Indicators**:
- Left edge: Shadow gradient (when scrolled)
- Right edge: Shadow gradient (when more content)
- Scrollbar: 6px height, gray with rounded corners

---

## State-Based Checks

### When Delete Mode Active

**Mobile View Changes**:
- Action dropdown button: Orange gradient background
- Menu stays functional
- Table rows: Red on hover
- "Click a row to delete" behavior same as desktop

### When Search Has Value

**Mobile View Changes**:
- Search bar stays expanded (doesn't collapse)
- Clear button (×) visible
- Results filter in real-time

### When Filters Active

**Mobile View Changes**:
- Filter button: Badge shows count
- Filter badges appear below controls
- Each badge: 
  - Blue background
  - Filter name + value
  - × remove button
- Badges wrap to multiple lines if needed

### When Sorted

**Mobile View Changes**:
- Mobile sort indicator appears below controls
- Shows: "Sorted by: [Column Name] [↑/↓]"
- Clicking indicator opens sort menu
- Clicking arrow toggles direction

---

## Browser DevTools Testing

### How to Test Mobile View

1. **Chrome/Edge**:
   - Press F12 to open DevTools
   - Click device toolbar icon (Ctrl+Shift+M)
   - Select "Responsive" or device
   - Set width to 375px (iPhone SE)

2. **Firefox**:
   - Press F12 to open DevTools
   - Click responsive design mode (Ctrl+Shift+M)
   - Set width to 375px

3. **Safari**:
   - Develop menu → Enter Responsive Design Mode
   - Choose iPhone SE or custom width

### Viewport Widths to Test

- **320px**: Smallest phone (iPhone SE portrait)
- **375px**: Standard small phone
- **414px**: Larger phone (iPhone Pro Max)
- **768px**: Tablet portrait
- **900px**: Breakpoint (test both 899px and 901px)

---

## Common Visual Issues to Look For

### ❌ Layout Breaking

**Issue**: Controls overlap or extend off-screen  
**Check**: Resize to 320px width  
**Expected**: All controls fit, nothing overlaps

**Issue**: Table causes horizontal page scroll  
**Check**: Swipe left/right on page body  
**Expected**: Only table scrolls, not page

### ❌ Text Visibility

**Issue**: Icon-only buttons show text snippets  
**Check**: Look for partial "Hi..." or "Fil..." text  
**Expected**: Only icons visible, no text

**Issue**: Search placeholder visible when collapsed  
**Check**: Collapsed search shows "Sea..." text  
**Expected**: Only icon visible when collapsed

### ❌ Touch Target Size

**Issue**: Buttons too small to tap comfortably  
**Check**: Measure in DevTools (should be 44x44px min)  
**Expected**: All interactive elements ≥ 44px

### ❌ Animation Glitches

**Issue**: Search expansion is jumpy or instant  
**Check**: Click collapsed search, watch expansion  
**Expected**: Smooth 0.3s ease animation

**Issue**: Menu doesn't animate, appears instantly  
**Check**: Open/close action dropdown  
**Expected**: Should appear immediately (no animation needed)

---

## Performance Checks

### Smooth Scrolling

**Test**: 
1. Open mobile view
2. Scroll table horizontally back and forth rapidly
3. Observe frame rate

**Expected**:
- No stuttering or lag
- Shadows update smoothly
- Scrollbar responds immediately

### Memory Usage

**Test**:
1. Open Chrome DevTools → Performance
2. Record while interacting with mobile controls
3. Check for memory leaks

**Expected**:
- No continuous memory growth
- Event listeners cleaned up properly
- No DOM leaks

---

## Accessibility Checks

### Keyboard Navigation

**Test**:
1. Use Tab key to navigate through controls
2. Use Space/Enter to activate buttons

**Expected**:
- Can reach all controls via Tab
- Focus indicators visible
- All buttons activate with keyboard

### Screen Reader

**Test** (with NVDA/JAWS/VoiceOver):
1. Navigate through mobile controls
2. Listen to button announcements

**Expected**:
- Buttons announce their purpose
- State changes announced
- No unlabeled buttons

---

## Regression Testing

### Features That Should Still Work

✅ Adding a new flip  
✅ Deleting a flip  
✅ Sorting by any column  
✅ Filtering by any criteria  
✅ Searching for items  
✅ Historical view  
✅ Stats calculations  
✅ Auto-refresh data

### Visual Elements That Should Be Unchanged

✅ Color scheme  
✅ Table styling (on desktop)  
✅ Modal designs  
✅ Header/footer  
✅ Desktop button layout (> 900px)  
✅ Stats cards  

---

## Sign-Off Checklist

Before considering the mobile overhaul complete, verify:

- [ ] Desktop view unchanged (> 900px)
- [ ] Mobile action dropdown works
- [ ] Search collapses/expands correctly
- [ ] All table columns visible on mobile
- [ ] Table scrolls horizontally only
- [ ] Page doesn't scroll horizontally
- [ ] All buttons are 44x44px minimum
- [ ] Icons clearly visible
- [ ] Filter badges display correctly
- [ ] Sort indicator appears correctly
- [ ] Smooth animations
- [ ] No console errors
- [ ] Works in Chrome/Firefox/Safari
- [ ] Touch interactions feel natural
- [ ] Keyboard navigation works
- [ ] Screen reader accessible

---

## Quick Fix Reference

### Issue: Search doesn't collapse

**Check**: `filterSearchWrapper` has `collapsed` class  
**Fix**: JavaScript not running, check console for errors

### Issue: Action dropdown doesn't open

**Check**: Click listener attached to `mobileActionsBtn`  
**Fix**: Check element ID matches, verify Bootstrap loaded

### Issue: Table causes page scroll

**Check**: Table wrapped in `table-scroll-wrapper` div  
**Fix**: JavaScript `setupTableScrollWrapper()` not running on mobile

### Issue: Buttons show text on mobile

**Check**: `@media (max-width: 900px)` rules applying  
**Fix**: Check browser width is actually < 900px, hard refresh (Ctrl+F5)

### Issue: First column not sticky

**Check**: Browser supports `position: sticky`  
**Fix**: Acceptable fallback (column scrolls with rest)

---

## Screenshots Recommendation

Take screenshots at these key states for documentation:

1. **Desktop view**: Full layout with all features visible
2. **Mobile default**: Collapsed search, no active filters
3. **Mobile with expanded search**: Showing search in use
4. **Mobile action dropdown open**: Menu displayed
5. **Mobile with filters**: Badges visible below controls
6. **Mobile table scroll**: Showing horizontal scroll and shadows
7. **Mobile delete mode**: Orange action button, red table hover

Store in: `/docs/screenshots/mobile-flips-page/`

---

## Conclusion

This visual guide should help you quickly verify that the mobile overhaul is working correctly. Focus on the critical path features first (action dropdown, search collapse, table scroll), then move to edge cases and polish.

If all visual checks pass, the implementation is solid! 🎉
