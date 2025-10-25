# 📱 SMS Reply Quick Reference Card

**Print this and keep near your phone!**

---

## ✅ What You'll Receive

### Alert Format (From System)
```
PickARooms Alert:
Booking #1234567890 for 20 Jan 2025 
not found in iCal.

Reply format:
1-3 = Room 1, 3 nights
2-2 = Room 2, 2 nights
3-1 = Room 3, 1 night
4-5 = Room 4, 5 nights
X = Cancel

Example: Reply "2-3" for Room 2, 3 nights
```

### Multiple Bookings (Collision)
```
PickARooms Alert:
4 Bookings for 20 Jan 2025:

A) #6582060925
B) #5317556059
C) #7891234560
D) #9876543210

Reply format:
A1-3 = Booking A, Room 1, 3 nights
B2-2 = Booking B, Room 2, 2 nights
X = Cancel all

Example: Reply "A2-3"
```

---

## 📝 How to Reply

### Single Booking
| Your Reply | What It Means |
|------------|---------------|
| `1-2` | Room 1, 2 nights |
| `2-3` | Room 2, 3 nights |
| `3-1` | Room 3, 1 night |
| `4-5` | Room 4, 5 nights |
| `X` | Cancel (no reservation) |

### Multiple Bookings
| Your Reply | What It Means |
|------------|---------------|
| `A1-3` | Booking A → Room 1, 3 nights |
| `B2-2` | Booking B → Room 2, 2 nights |
| `C3-1` | Booking C → Room 3, 1 night |
| `D4-5` | Booking D → Room 4, 5 nights |
| `X` | Cancel all |

---

## ✅ Confirmation Messages You'll Receive

### Success ✅
```
✅ ENRICHMENT COMPLETE

Booking: #6582060925
Room: Room 2
Check-in: 20 Jan 2025
Check-out: 23 Jan 2025 (3 nights)

Reservation created and awaiting guest 
check-in. Guest will provide contact 
details when they check in via the app.
```

### Already Assigned ⚠️
```
⚠️ ALREADY ASSIGNED

Booking #6582060925 was already assigned 
to Room 2 earlier.

No duplicate reservation created.
```

### Cancelled ✅
```
✅ CANCELLED

Booking: #6582060925
Check-in: 20 Jan 2025

No reservation created. Guest will need 
to book again if they still want the room.
```

### Error ❌
```
❌ Invalid format: '2 3'

Valid formats:
• 2-3 (Room 2, 3 nights)
• A1-3 (Booking A, Room 1, 3 nights)
• X (Cancel)
```

---

## 🏠 Room Reference

| Room | Description |
|------|-------------|
| Room 1 | No Onsuite middle floor double room |
| Room 2 | Middle Floor Room with OnSuite |
| Room 3 | Single Room |
| Room 4 | Topmost Room |

---

## 🔍 Quick Check Commands

### Check if enrichment worked:
```bash
python manage.py check_enrichment_status [BOOKING_REF]
```

### View in browser:
```
https://www.pickarooms.com/admin-page/pending-enrichments/
https://www.pickarooms.com/admin-page/all-reservations/
```

---

## ⚠️ Common Mistakes

❌ `2 3` (space - WRONG)  
✅ `2-3` (dash - CORRECT)

❌ `A 1-3` (space - WRONG)  
✅ `A1-3` (no space - CORRECT)

❌ `room 2 for 3 nights` (text - WRONG)  
✅ `2-3` (short format - CORRECT)

---

## 📞 If Something Goes Wrong

1. Check SMS confirmation message
2. Run: `python manage.py check_enrichment_status [REF]`
3. Check admin page: `/admin-page/pending-enrichments/`
4. Re-reply to original SMS if needed

---

**Phone:** +44 7539029629  
**System:** https://www.pickarooms.com  
**Admin:** https://www.pickarooms.com/admin-page/

---

**Keep this card handy for quick reference!** 📌
