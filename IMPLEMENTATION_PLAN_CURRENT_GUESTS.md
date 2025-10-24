# Current Guests Toggle Feature - Implementation Plan

## ✅ Backup Complete
- Branch created: `pickarooms-full-20/10/2026`
- Pushed to GitHub successfully

## 🎯 Implementation Strategy

### Phase 1: Update Backend (views.py)
**Location:** `main/views.py` - `admin_page()` function (line 909)

**Changes Needed:**

1. **Add "Current Guests" query** (all active stays):
```python
# Get current guests (ALL active stays - not just today's check-ins)
current_guests = Guest.objects.filter(
    is_archived=False,
    check_in_date__lte=today,  # Already checked in
    check_out_date__gte=today   # Not yet checked out
).select_related('assigned_room').order_by('check_out_date')

current_reservations = Reservation.objects.filter(
    check_in_date__lte=today,
    check_out_date__gte=today,
    status='confirmed',
    guest__isnull=True
).select_related('room').order_by('check_out_date')
```

2. **Build `current_entries` list** (same format as `todays_entries`)

3. **Calculate Dashboard Summary Stats**:
```python
dashboard_stats = {
    'in_house': current_guests.filter(check_in_date__lt=today).count(),
    'checking_in_today': todays_guests.count() + todays_reservations.count(),
    'checking_out_today': Guest.objects.filter(is_archived=False, check_out_date=today).count(),
    'total_rooms': Room.objects.count(),
    'occupied_rooms': current_guests.values('assigned_room').distinct().count(),
    'pending_checkins': current_reservations.count(),
}
```

4. **Pass both datasets to template**:
- `todays_entries` (today's check-ins only)
- `current_entries` (all active stays)
- `dashboard_stats`

### Phase 2: Update Frontend (admin_page.html)

**Changes:**

1. **Add Toggle Button** (above table):
```html
<div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px;">
    <h2 id="table-title">Today's Check-Ins</h2>
    <button onclick="toggleGuestView()" class="add-guest-btn" style="background: #17a2b8;">
        <span id="toggle-text">Show Current Guests</span>
    </button>
</div>
```

2. **Two hidden tables**:
- `<table id="todays-table">` (default visible)
- `<table id="current-table">` (default hidden)

3. **JavaScript toggle function**:
```javascript
let showingCurrent = false;

function toggleGuestView() {
    const todaysTable = document.getElementById('todays-table');
    const currentTable = document.getElementById('current-table');
    const title = document.getElementById('table-title');
    const toggleText = document.getElementById('toggle-text');
    
    showingCurrent = !showingCurrent;
    
    if (showingCurrent) {
        todaysTable.style.display = 'none';
        currentTable.style.display = 'table';
        title.textContent = 'Current Guests (In Rooms Now)';
        toggleText.textContent = 'Show Today\'s Check-Ins';
    } else {
        todaysTable.style.display = 'table';
        currentTable.style.display = 'none';
        title.textContent = 'Today\'s Check-Ins';
        toggleText.textContent = 'Show Current Guests';
    }
}
```

4. **Add Dashboard Summary** (below table):
```html
<div class="dashboard-summary" style="background: #f8f9fa; padding: 20px; border-radius: 8px; margin-top: 20px;">
    <h3>📊 Dashboard Summary</h3>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-top: 15px;">
        <div class="stat-card">
            <div class="stat-value">{{ dashboard_stats.in_house }}</div>
            <div class="stat-label">✅ Currently In House</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{{ dashboard_stats.checking_in_today }}</div>
            <div class="stat-label">📥 Checking In Today</div>
        </div>
        <!-- ... more stats -->
    </div>
</div>
```

### Phase 3: Add Status & Night Progress Columns

**New Columns**:
- Status (🟢 IN-STAY, 🟡 JUST ARRIVED, 🔴 LEAVING TODAY, ⚪ NOT CHECKED IN)
- Night (e.g., "Night 2/3")

**Helper functions in Python**:
```python
def get_guest_status(entry, today):
    if not entry['is_enriched']:
        return '⚪ NOT CHECKED IN'
    if entry['check_in_date'] == today:
        return '🟡 JUST ARRIVED'
    elif entry['check_out_date'] == today:
        return '🔴 LEAVING TODAY'
    else:
        return '🟢 IN-STAY'

def get_night_progress(check_in, check_out, today):
    total_nights = (check_out - check_in).days
    nights_spent = (today - check_in).days
    current_night = nights_spent + 1
    return f"Night {current_night}/{total_nights}"
```

## 🚀 Execution Steps

1. Update `admin_page()` view with new queries
2. Update template with toggle button + two tables
3. Add JavaScript toggle logic
4. Add dashboard summary section
5. Test toggle functionality
6. Test data accuracy

## 📌 Files to Modify

1. `main/views.py` - admin_page function
2. `main/templates/main/admin_page.html` - UI changes

Ready to proceed with implementation?
