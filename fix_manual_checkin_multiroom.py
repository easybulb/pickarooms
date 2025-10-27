#!/usr/bin/env python3
"""
Fix manual_checkin_reservation() to properly handle multi-room bookings:
1. When existing guest found: Generate PIN for the new room
2. When creating new guest: Find and link ALL reservations, generate PINs for all rooms
"""

import re

def fix_manual_checkin():
    print("Reading main/views.py...")
    with open('main/views.py', 'r', encoding='utf-8') as f:
        content = f.read()
    
    original_content = content
    
    # ================================================================
    # FIX 1: When existing guest found - generate PIN for new room
    # ================================================================
    print("Applying fix 1: Generate PIN for additional room when guest exists...")
    
    old_pattern_1 = r'''        # MULTI-ROOM: Check if guest with this booking reference already exists
        existing_guest = Guest\.objects\.filter\(reservation_number=reservation\.booking_reference\)\.first\(\)
        
        if existing_guest:
            # Guest already exists - link this reservation to existing guest
            reservation\.guest = existing_guest
            reservation\.save\(\)
            logger\.info\(f"Linked reservation \{reservation\.id\} to existing guest \{existing_guest\.id\} \(multi-room booking\)"\)
            messages\.success\(request, f"Linked to existing guest \{existing_guest\.full_name\}\. Room \{reservation\.room\.name\} added to their booking\."\)
            
            # Log the action
            AuditLog\.objects\.create\(
                user=request\.user,
                action="Manual Check-In \(Multi-Room\)",
                object_type="Reservation",
                object_id=reservation\.id,
                details=f"Linked reservation \{reservation\.booking_reference\} to existing guest \{existing_guest\.full_name\}"
            \)
            return redirect\('admin_page'\)'''

    new_pattern_1 = '''        # MULTI-ROOM: Check if guest with this booking reference already exists
        existing_guest = Guest.objects.filter(reservation_number=reservation.booking_reference).first()
        
        if existing_guest:
            # Guest already exists - link this reservation to existing guest
            reservation.guest = existing_guest
            reservation.save()
            logger.info(f"Linked reservation {reservation.id} to existing guest {existing_guest.id} (multi-room booking)")
            
            # MULTI-ROOM FIX: Generate PIN for this additional room using existing guest's PIN
            if existing_guest.front_door_pin and reservation.room.ttlock:
                try:
                    ttlock_client = TTLockClient()
                    uk_timezone = pytz.timezone("Europe/London")
                    now_uk_time = timezone.now().astimezone(uk_timezone)
                    
                    # Use existing guest's PIN
                    pin = existing_guest.front_door_pin
                    start_time = int(now_uk_time.timestamp() * 1000)
                    check_out_time_val = reservation.late_checkout_time if reservation.late_checkout_time else time(11, 0)
                    end_date = uk_timezone.localize(
                        datetime.datetime.combine(reservation.check_out_date, check_out_time_val)
                    ) + datetime.timedelta(days=1)
                    end_time = int(end_date.timestamp() * 1000)
                    
                    # Generate PIN for this room's lock
                    room_response = ttlock_client.generate_temporary_pin(
                        lock_id=reservation.room.ttlock.lock_id,
                        pin=pin,
                        start_time=start_time,
                        end_time=end_time,
                        name=f"Room - {reservation.room.name} - {existing_guest.full_name} - {pin}",
                    )
                    
                    if "keyboardPwdId" in room_response:
                        logger.info(f"Generated PIN for additional room {reservation.room.name} (multi-room booking)")
                        messages.success(request, f"Linked to existing guest {existing_guest.full_name}. Room {reservation.room.name} added with PIN {pin}.")
                    else:
                        logger.error(f"Failed to generate PIN for room {reservation.room.name}: {room_response.get('errmsg', 'Unknown error')}")
                        messages.warning(request, f"Linked reservation but failed to generate PIN for {reservation.room.name}. Guest can use existing PIN for other rooms.")
                except Exception as e:
                    logger.error(f"Failed to generate PIN for additional room: {str(e)}")
                    messages.warning(request, f"Linked reservation but PIN generation failed: {str(e)}")
            else:
                messages.success(request, f"Linked to existing guest {existing_guest.full_name}. Room {reservation.room.name} added to their booking.")
            
            # Log the action
            AuditLog.objects.create(
                user=request.user,
                action="Manual Check-In (Multi-Room)",
                object_type="Reservation",
                object_id=reservation.id,
                details=f"Linked reservation {reservation.booking_reference} to existing guest {existing_guest.full_name}, generated PIN for {reservation.room.name}"
            )
            return redirect('admin_page')'''

    content = re.sub(old_pattern_1, new_pattern_1, content, flags=re.DOTALL)
    
    if content == original_content:
        print("  [WARNING] Fix 1 pattern not found")
    else:
        print("  [OK] Fix 1 applied - PIN generation for additional rooms")
    
    # ================================================================
    # FIX 2: When creating new guest - find all reservations and generate PINs for all
    # ================================================================
    print("Applying fix 2: Find all reservations and generate PINs for all rooms...")
    
    old_pattern_2 = r'''            # Create guest with PIN
            guest = Guest\.objects\.create\(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                reservation_number=reservation\.booking_reference,
                check_in_date=reservation\.check_in_date,
                check_out_date=reservation\.check_out_date,
                assigned_room=reservation\.room,
                early_checkin_time=reservation\.early_checkin_time,
                late_checkout_time=reservation\.late_checkout_time,
                is_returning=previous_stays,
                front_door_pin=pin,
                front_door_pin_id=keyboard_pwd_id_front,
                room_pin_id=keyboard_pwd_id_room,
            \)

            # Link guest to reservation
            reservation\.guest = guest
            reservation\.save\(\)

            logger\.info\(f"Guest \{guest\.id\} created via manual check-in with PIN \{pin\}"\)
            messages\.success\(request, f"Guest \{full_name\} checked in successfully! PIN \(for both front door and room\): \{pin\}\."\)'''

    new_pattern_2 = '''            # MULTI-ROOM: Find all reservations with same booking reference
            all_reservations = Reservation.objects.filter(
                booking_reference=reservation.booking_reference,
                status='confirmed',
                guest__isnull=True
            ).select_related('room')
            
            # Generate PINs for ALL rooms
            room_pin_ids = []
            for res in all_reservations:
                if res.room.ttlock:
                    try:
                        room_response = ttlock_client.generate_temporary_pin(
                            lock_id=res.room.ttlock.lock_id,
                            pin=pin,
                            start_time=start_time,
                            end_time=end_time,
                            name=f"Room - {res.room.name} - {full_name} - {pin}",
                        )
                        if "keyboardPwdId" in room_response:
                            room_pin_ids.append(room_response["keyboardPwdId"])
                            logger.info(f"Generated PIN for room {res.room.name}")
                    except Exception as e:
                        logger.error(f"Failed to generate PIN for {res.room.name}: {str(e)}")

            # Create guest with PIN
            guest = Guest.objects.create(
                full_name=full_name,
                email=email,
                phone_number=phone_number,
                reservation_number=reservation.booking_reference,
                check_in_date=reservation.check_in_date,
                check_out_date=reservation.check_out_date,
                assigned_room=reservation.room,
                early_checkin_time=reservation.early_checkin_time,
                late_checkout_time=reservation.late_checkout_time,
                is_returning=previous_stays,
                front_door_pin=pin,
                front_door_pin_id=keyboard_pwd_id_front,
                room_pin_id=room_pin_ids[0] if room_pin_ids else keyboard_pwd_id_room,
            )

            # MULTI-ROOM: Link ALL reservations to this guest
            room_count = 0
            for res in all_reservations:
                res.guest = guest
                res.save()
                room_count += 1
                logger.info(f"Linked reservation {res.id} ({res.room.name}) to guest {guest.id}")

            room_msg = f"{room_count} rooms" if room_count > 1 else "room"
            logger.info(f"Guest {guest.id} created via manual check-in with PIN {pin} for {room_msg}")
            messages.success(request, f"Guest {full_name} checked in successfully! PIN (for front door and {room_msg}): {pin}.")'''

    content = re.sub(old_pattern_2, new_pattern_2, content, flags=re.DOTALL)
    
    if content == original_content:
        print("  [WARNING] Fix 2 pattern not found")
    else:
        print("  [OK] Fix 2 applied - Multi-room PIN generation for new guests")
    
    # Write changes
    if content != original_content:
        print("\nWriting changes to main/views.py...")
        with open('main/views.py', 'w', encoding='utf-8') as f:
            f.write(content)
        print("[OK] manual_checkin_reservation() multi-room fixes applied!")
        print("\nWhat was fixed:")
        print("1. When existing guest found: Generates PIN for the new room")
        print("2. When creating new guest: Finds all reservations and generates PINs for all rooms")
        print("3. Same PIN works across front door + all room doors")
        return 0
    else:
        print("\n[WARNING] No changes made - patterns may already be applied")
        return 1

if __name__ == "__main__":
    import sys
    try:
        sys.exit(fix_manual_checkin())
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
