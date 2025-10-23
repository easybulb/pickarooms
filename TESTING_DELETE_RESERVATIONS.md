# Testing Guide: Delete Reservations Feature

## Prerequisites
- Admin account with `main.delete_guest` permission
- Test database with sample reservations (both enriched and unenriched)

## Test Cases

### 1. Individual Delete - Unenriched Reservation ✓

**Steps:**
1. Log in as admin
2. Navigate to `/admin-page/all-reservations/`
3. Find an unenriched reservation (with ⚠ Unenriched badge)
4. Click the red "Delete" button in Actions column
5. Confirm in the dialog

**Expected Result:**
- Confirmation dialog appears: "Are you sure you want to delete this reservation?"
- After confirming, reservation is deleted
- Success message: "Reservation {booking_ref} deleted successfully."
- Reservation removed from table
- Audit log entry created

---

### 2. Individual Delete - Enriched Reservation ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/`
2. Find an enriched reservation (with ✓ Enriched badge)
3. Observe Actions column

**Expected Result:**
- No "Delete" button visible (only "View Guest" link)
- Checkbox column shows "—" (dash) instead of checkbox
- Cannot select or delete enriched reservations

---

### 3. Bulk Delete - Single Page Selection ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/`
2. Check 2-3 unenriched reservation checkboxes
3. Observe bulk actions bar appears
4. Click "Delete Selected" button
5. Confirm in dialog

**Expected Result:**
- Bulk actions bar appears showing count: "3 reservation(s) selected"
- Delete button is enabled (not grayed out)
- Confirmation dialog: "Are you sure you want to delete 3 reservation(s)?"
- After confirming: "Successfully deleted 3 reservation(s)."
- Selected reservations removed from table
- Audit log entries for each deletion

---

### 4. Bulk Delete - Select All on Page ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/`
2. Click the checkbox in the table header (first column)
3. All visible unenriched checkboxes get checked
4. Click "Delete Selected"
5. Confirm

**Expected Result:**
- All unenriched reservations on current page selected
- Enriched reservations remain unselected
- Bulk delete works as expected

---

### 5. Bulk Delete - Multi-Page Selection ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/` (ensure you have 10+ unenriched reservations)
2. Check 2 reservations on page 1
3. Navigate to page 2
4. Check 2 more reservations
5. Navigate back to page 1
6. Observe selection count
7. Click "Delete Selected"
8. Confirm

**Expected Result:**
- Selection count shows "4 reservation(s) selected"
- Selections persist across page navigation
- All 4 selected reservations deleted
- Success message: "Successfully deleted 4 reservation(s)."

---

### 6. Bulk Delete - Select All Button ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/`
2. Click "Select All" button in bulk actions bar
3. Observe all pages have selections
4. Navigate between pages to verify
5. Click "Deselect All"

**Expected Result:**
- "Select All" button selects ALL unenriched reservations (across all pages)
- Selection count shows total (e.g., "15 reservation(s) selected")
- Navigating to any page shows checkboxes checked
- "Deselect All" clears all selections
- Bulk actions bar hides when count reaches 0

---

### 7. Bulk Delete - Mixed Selection (Enriched + Unenriched) ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/`
2. Manually check 3 unenriched reservations
3. Note there are also 2 enriched reservations on screen (cannot check them)
4. Click "Delete Selected"
5. Confirm

**Expected Result:**
- Only 3 unenriched reservations can be selected
- Success message: "Successfully deleted 3 reservation(s)."
- No error about enriched reservations (they were never selected)

---

### 8. Permission Check - Unauthorized User ✓

**Steps:**
1. Log in as user WITHOUT `main.delete_guest` permission
2. Navigate to `/admin-page/all-reservations/`
3. Try to access `/admin-page/delete-reservation/1/` directly

**Expected Result:**
- Either no checkboxes/delete buttons visible, OR
- Accessing delete URL redirects to `/unauthorized/` page
- No deletions possible

---

### 9. Audit Log Verification ✓

**Steps:**
1. Delete 1 reservation individually
2. Delete 3 reservations in bulk
3. Navigate to `/audit-logs/`
4. Search for "Reservation Deleted"

**Expected Result:**
- 1 entry: "Reservation Deleted" with booking ref and room
- 3 entries: "Reservation Deleted (Bulk)" with booking refs and rooms
- Each entry shows username, timestamp, and details
- All 4 audit entries present

---

### 10. Error Handling - Non-existent Reservation ✓

**Steps:**
1. Navigate to `/admin-page/delete-reservation/99999/` (invalid ID)
2. Or manipulate form to submit invalid ID

**Expected Result:**
- 404 error or appropriate error message
- No database changes
- System remains stable

---

### 11. Filters + Delete ✓

**Steps:**
1. Navigate to `/admin-page/all-reservations/`
2. Apply filter: "Enrichment: Unenriched"
3. Apply filter: "Status: Confirmed"
4. Select multiple reservations
5. Delete them

**Expected Result:**
- Filters work correctly
- Only filtered reservations shown
- Bulk delete works on filtered results
- After deletion, page refreshes with filters maintained (or cleared)

---

### 12. Quick Filters + Delete ✓

**Steps:**
1. Click "Today" quick filter button
2. Select today's unenriched reservations
3. Delete them
4. Click "Tomorrow" button
5. Select and delete tomorrow's reservations

**Expected Result:**
- Quick filters work correctly
- Bulk delete works with quick filters
- No conflicts between filters and deletions

---

## Visual Checks

### UI Elements Present:
- ✅ Checkbox column (first column)
- ✅ Checkboxes only for unenriched reservations
- ✅ "—" (dash) for enriched reservations
- ✅ Bulk actions bar (yellow background)
- ✅ Selection count display
- ✅ "Select All" button
- ✅ "Deselect All" button
- ✅ Red "Delete Selected" button
- ✅ Individual red "Delete" buttons for unenriched reservations
- ✅ Header checkbox for page-level selection

### Styling:
- ✅ Bulk actions bar has yellow warning background
- ✅ Delete buttons are red (danger styling)
- ✅ Checkboxes are 18x18px and clickable
- ✅ Disabled states are grayed out
- ✅ Hover states work on buttons

### Responsiveness:
- ✅ Works on desktop
- ✅ Works on tablet
- ✅ Works on mobile (buttons stack properly)

---

## Common Issues to Watch For

1. **Checkboxes not appearing**: Ensure reservations are truly unenriched (guest field is NULL)
2. **Bulk actions bar not appearing**: Check JavaScript console for errors
3. **Delete button grayed out**: Must select at least one checkbox
4. **Permissions error**: User must have `main.delete_guest` permission
5. **Selections not persisting**: JavaScript may have issues with pagination

---

## Success Criteria

All 12 test cases pass ✓
- Individual delete works for unenriched
- Individual delete blocked for enriched
- Bulk delete works across pages
- Permissions enforced correctly
- Audit logs created
- No errors in console
- UI is responsive and intuitive
