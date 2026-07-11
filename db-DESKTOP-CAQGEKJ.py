import sqlite3
import qrcode
import io
import base64
from datetime import date, datetime, timedelta, time
from werkzeug.security import generate_password_hash, check_password_hash
import calendar
import threading
import secrets
import hashlib

DB_FILE = "mess_app.db"

# Database connection lock to prevent concurrent access
db_lock = threading.Lock()

# Price list for fine calculation
PRICE_LIST = {
    "Idli": 10, "Dosa": 25, "Pongal": 30,
    "Rice": 15, "Dal": 20, "Sabzi": 25, "Chapati": 5,
    "Roti": 5, "Paneer": 40, "Salad": 15
}

# Meal times for cancellation policy
MEAL_TIMES = {
    "Breakfast": 8,   # 8 AM
    "Lunch": 13,      # 1 PM
    "Dinner": 20      # 8 PM
}

def init_db():
    """Create tables if they don't exist (safe to call on every start)."""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Users table for authentication
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                phone TEXT NOT NULL,
                hostel_type TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                item TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                status TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                item TEXT NOT NULL,
                rating INTEGER NOT NULL,
                feedback TEXT
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS cancellations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                reason TEXT NOT NULL,
                approved INTEGER DEFAULT 0  -- 0 = Pending, 1 = Approved, 2 = Rejected
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_id TEXT NOT NULL,
                date TEXT NOT NULL,
                meal_type TEXT NOT NULL,
                amount REAL NOT NULL,
                paid INTEGER DEFAULT 0  -- 0 = Not Paid, 1 = Paid
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                type TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token TEXT NOT NULL UNIQUE,
                token_hash TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                used BOOLEAN DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        ''')
        conn.commit()
        conn.close()

# User authentication functions
def create_user(name, email, phone, hostel_type, password):
    """Create a new user with hashed password"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        password_hash = generate_password_hash(password)
        try:
            cursor.execute(
                "INSERT INTO users (name, email, phone, hostel_type, password_hash) VALUES (?, ?, ?, ?, ?)",
                (name, email, phone, hostel_type, password_hash)
            )
            conn.commit()
            user_id = cursor.lastrowid
            conn.close()
            return user_id
        except sqlite3.IntegrityError:
            conn.close()
            return None  # Email already exists

def get_user_by_email(email):
    """Get user by email"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cursor.fetchone()
        conn.close()
        return user

def verify_user(email, password):
    """Verify user credentials"""
    user = get_user_by_email(email)
    if user and check_password_hash(user[5], password):
        return user
    return None

def update_user_profile(user_id, name, phone, hostel_type):
    """Update user profile information"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET name = ?, phone = ?, hostel_type = ? WHERE id = ?",
            (name, phone, hostel_type, user_id)
        )
        conn.commit()
        conn.close()
        return True

def update_user_password(user_id, new_password):
    """Update user password"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        password_hash = generate_password_hash(new_password)
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id)
        )
        conn.commit()
        conn.close()
        return True

# Password reset functions
def create_password_reset_token(user_id):
    """Create a password reset token for a user"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Generate a secure random token
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        # Set expiration time (1 hour from now)
        expires_at = datetime.now() + timedelta(hours=1)
        
        # Delete any existing tokens for this user
        cursor.execute(
            "DELETE FROM password_reset_tokens WHERE user_id = ?",
            (user_id,)
        )
        
        # Insert new token
        cursor.execute(
            "INSERT INTO password_reset_tokens (user_id, token, token_hash, expires_at) VALUES (?, ?, ?, ?)",
            (user_id, token, token_hash, expires_at)
        )
        
        conn.commit()
        conn.close()
        
        return token

def verify_password_reset_token(token):
    """Verify a password reset token and return user_id if valid"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Hash the token to compare with stored hash
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        # Find the token
        cursor.execute(
            "SELECT user_id, expires_at, used FROM password_reset_tokens WHERE token_hash = ?",
            (token_hash,)
        )
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return None
        
        user_id, expires_at, used = result
        
        # Check if token is expired or used
        if datetime.now() > datetime.fromisoformat(expires_at) or used:
            conn.close()
            return None
        
        conn.close()
        return user_id

def update_password_with_token(user_id, new_password, token):
    """Update password using a valid reset token"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Hash the token to find it
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        
        # Verify token is still valid
        cursor.execute(
            "SELECT id FROM password_reset_tokens WHERE user_id = ? AND token_hash = ? AND used = 0 AND expires_at > datetime('now')",
            (user_id, token_hash)
        )
        token_record = cursor.fetchone()
        
        if not token_record:
            conn.close()
            return False
        
        # Update password with proper hashing
        password_hash = generate_password_hash(new_password)
        
        cursor.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (password_hash, user_id)
        )
        
        # Mark token as used
        cursor.execute(
            "UPDATE password_reset_tokens SET used = 1 WHERE user_id = ? AND token_hash = ?",
            (user_id, token_hash)
        )
        
        conn.commit()
        conn.close()
        return True

def clear_bookings(student_id, booking_date, meal_type=None):
    """Delete previous bookings for the given student/date and optionally meal_type."""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        if meal_type:
            cursor.execute(
                "DELETE FROM bookings WHERE student_id = ? AND date = ? AND meal_type = ?",
                (student_id, booking_date, meal_type)
            )
        else:
            cursor.execute(
                "DELETE FROM bookings WHERE student_id = ? AND date = ?",
                (student_id, booking_date)
            )
        conn.commit()
        conn.close()

def confirm_booking(student_id, meal_type, items, booking_date=None):
    """
    Save booking items for a student for a specific date and meal_type.
    This replaces previous entries for that student/date/meal.
    If items is empty, the booking is removed (no insertion).
    """
    if booking_date is None:
        booking_date = date.today().isoformat()

    # remove previous entries for this meal/date/student
    clear_bookings(student_id, booking_date, meal_type)

    if not items:
        # nothing to insert — user deselected everything for this meal
        return

    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        for item in items:
            cursor.execute(
                "INSERT INTO bookings (student_id, date, meal_type, item) VALUES (?, ?, ?, ?)",
                (student_id, booking_date, meal_type, item)
            )
        conn.commit()
        conn.close()

def get_bookings_by_date(student_id, booking_date):
    """Return dict: { 'Breakfast': [...], 'Lunch': [...], 'Dinner': [...] }"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT meal_type, item FROM bookings WHERE student_id = ? AND date = ?",
            (student_id, booking_date)
        )
        rows = cursor.fetchall()
        conn.close()
        bookings = {"Breakfast": [], "Lunch": [], "Dinner": []}
        for meal, item in rows:
            bookings.setdefault(meal, []).append(item)
        return bookings

def get_bookings_with_attendance(student_id, booking_date):
    """Return a dict with bookings and their attendance status."""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Get bookings
        cursor.execute(
            "SELECT meal_type, item FROM bookings WHERE student_id = ? AND date = ?",
            (student_id, booking_date)
        )
        rows = cursor.fetchall()
        bookings_dict = {"Breakfast": [], "Lunch": [], "Dinner": []}
        for meal, item in rows:
            bookings_dict.setdefault(meal, []).append(item)

        # Get attendance status
        cursor.execute(
            "SELECT meal_type, status FROM attendance WHERE student_id = ? AND date = ?",
            (student_id, booking_date)
        )
        attendance_rows = cursor.fetchall()
        attendance_dict = {}
        for meal, status in attendance_rows:
            attendance_dict[meal] = status

        conn.close()

    # Combine the information
    result = {}
    for meal in ["Breakfast", "Lunch", "Dinner"]:
        result[meal] = {
            'food_items': bookings_dict.get(meal, []),
            'status': attendance_dict.get(meal, 'Not Scanned') # Default to 'Not Scanned'
        }
    return result

def get_booking_history(student_id):
    """Return all booking rows for the student (date desc)."""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date, meal_type, item FROM bookings WHERE student_id = ? ORDER BY date DESC",
            (student_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        history = []
        for d, meal, item in rows:
            history.append({"date": d, "meal_type": meal, "item": item})
        return history

def submit_review(student_id, date_val, meal_type, item, rating, feedback):
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO reviews (student_id, date, meal_type, item, rating, feedback) VALUES (?, ?, ?, ?, ?, ?)",
            (student_id, date_val, meal_type, item, rating, feedback)
        )
        conn.commit()
        conn.close()

def get_reviews(student_id, meal_type, item):
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT rating, feedback, date FROM reviews WHERE student_id = ? AND meal_type = ? AND item = ? ORDER BY date DESC",
            (student_id, meal_type, item)
        )
        rows = cursor.fetchall()
        conn.close()
        return rows

def generate_qr_code(data):
    """Return base64 PNG image for embedding in <img src='data:image/png;base64,...'>"""
    qr = qrcode.QRCode(version=1, box_size=4, border=2)
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode()
    return encoded

def mark_attendance(student_id, date_val, meal_type, status):
    """Insert or update attendance status for a student on a date for a meal."""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # First, check if an entry already exists
        cursor.execute(
            "SELECT id FROM attendance WHERE student_id=? AND date=? AND meal_type=?",
            (student_id, date_val, meal_type)
        )
        existing = cursor.fetchone()

        if existing:
            # Update existing record
            cursor.execute(
                "UPDATE attendance SET status=? WHERE student_id=? AND date=? AND meal_type=?",
                (status, student_id, date_val, meal_type)
            )
        else:
            # Insert new record
            cursor.execute(
                "INSERT INTO attendance (student_id, date, meal_type, status) VALUES (?, ?, ?, ?)",
                (student_id, date_val, meal_type, status)
            )
        conn.commit()
        conn.close()

def calculate_daily_fines():
    """Check attendance for yesterday and apply fines for absent meals."""
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        # Get all users
        cursor.execute("SELECT id FROM users")
        all_students = [row[0] for row in cursor.fetchall()]

        for student_id in all_students:
            # Get yesterday's bookings with attendance status
            daily_data = get_bookings_with_attendance(student_id, yesterday_str)

            for meal_type, data in daily_data.items():
                food_items = data['food_items']
                status = data['status']

                # Check if a cancellation was approved for this meal
                cursor.execute(
                    "SELECT approved FROM cancellations WHERE student_id=? AND date=? AND meal_type=?",
                    (student_id, yesterday_str, meal_type)
                )
                cancellation = cursor.fetchone()
                
                # If meal was booked but not scanned and not cancelled, apply fine
                if status != 'Present' and food_items and (not cancellation or cancellation[0] != 1):
                    total_fine = sum(PRICE_LIST.get(item, 0) for item in food_items)
                    if total_fine > 0:
                        # Check if fine already exists
                        cursor.execute(
                            "SELECT id FROM fines WHERE student_id=? AND date=? AND meal_type=?",
                            (student_id, yesterday_str, meal_type)
                        )
                        existing_fine = cursor.fetchone()
                        
                        if not existing_fine:
                            # Insert into fines table
                            cursor.execute(
                                "INSERT INTO fines (student_id, date, meal_type, amount) VALUES (?, ?, ?, ?)",
                                (student_id, yesterday_str, meal_type, total_fine)
                            )
                            
                            # Add notification for the fine
                            add_notification(
                                student_id,
                                f"You have been fined ₹{total_fine} for missing {meal_type} on {yesterday_str}.",
                                "fine_notification"
                            )

        # For past meals that were booked but not scanned, mark as Absent
        for student_id in all_students:
            # Get all dates before today
            cursor.execute(
                "SELECT DISTINCT date FROM bookings WHERE student_id=? AND date < date('now')",
                (student_id,)
            )
            past_dates = [row[0] for row in cursor.fetchall()]
            
            for past_date in past_dates:
                past_data = get_bookings_with_attendance(student_id, past_date)
                for meal_type, data in past_data.items():
                    if data['food_items'] and data['status'] == 'Not Scanned':
                        # Check if we already have an attendance record
                        cursor.execute(
                            "SELECT id FROM attendance WHERE student_id=? AND date=? AND meal_type=?",
                            (student_id, past_date, meal_type)
                        )
                        existing = cursor.fetchone()
                        
                        if not existing:
                            mark_attendance(student_id, past_date, meal_type, "Absent")

        conn.commit()
        conn.close()

def get_fines(student_id):
    """Get all fines for a student"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, date, meal_type, amount, paid FROM fines WHERE student_id = ? ORDER BY date DESC",
            (student_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        fines = []
        for fine_id, date_val, meal_type, amount, paid in rows:
            fines.append({
                'id': fine_id,
                'date': date_val,
                'meal_type': meal_type,
                'amount': amount,
                'paid': bool(paid)
            })
        return fines

def get_cancellations(student_id):
    """Get all cancellation requests for a student"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT date, meal_type, reason, approved FROM cancellations WHERE student_id = ? ORDER BY date DESC",
            (student_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        cancellations = []
        for date_val, meal_type, reason, approved in rows:
            status = "Pending"
            if approved == 1:
                status = "Approved"
            elif approved == 2:
                status = "Rejected"
                
            cancellations.append({
                'date': date_val,
                'meal_type': meal_type,
                'reason': reason,
                'status': status
            })
        return cancellations

def reset_fines(student_id):
    """Reset all fines to unpaid status for testing purposes"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE fines SET paid = 0 WHERE student_id = ?",
            (student_id,)
        )
        conn.commit()
        conn.close()
        return True

def get_attendance_calendar(student_id, year, month):
    """Get attendance data for a calendar view"""
    # Get the first and last day of the month
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    
    # Generate all days in the month
    delta = last_day - first_day
    dates_in_month = [first_day + timedelta(days=i) for i in range(delta.days + 1)]
    
    # Get attendance for each day
    calendar_data = []
    for day in dates_in_month:
        day_str = day.isoformat()
        day_data = get_bookings_with_attendance(student_id, day_str)
        
        # Check if any meal was booked
        has_booking = any(day_data[meal]['food_items'] for meal in day_data)
        
        # Check attendance status
        breakfast_status = day_data['Breakfast']['status'] if day_data['Breakfast']['food_items'] else 'Not Booked'
        lunch_status = day_data['Lunch']['status'] if day_data['Lunch']['food_items'] else 'Not Booked'
        dinner_status = day_data['Dinner']['status'] if day_data['Dinner']['food_items'] else 'Not Booked'
        
        # Check if any fine exists for this day
        with db_lock:
            conn = sqlite3.connect(DB_FILE)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT amount FROM fines WHERE student_id = ? AND date = ?",
                (student_id, day_str)
            )
            fine_rows = cursor.fetchall()
            conn.close()
        
        has_fine = len(fine_rows) > 0
        fine_amount = sum(row[0] for row in fine_rows) if has_fine else 0
        
        calendar_data.append({
            'date': day,
            'date_str': day_str,
            'has_booking': has_booking,
            'breakfast_status': breakfast_status,
            'lunch_status': lunch_status,
            'dinner_status': dinner_status,
            'has_fine': has_fine,
            'fine_amount': fine_amount
        })
    
    return calendar_data

# Notification functions
def add_notification(user_id, message, notification_type):
    """Add a notification for a user"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO notifications (user_id, message, type) VALUES (?, ?, ?)",
            (user_id, message, notification_type)
        )
        conn.commit()
        conn.close()

def get_unread_notifications(user_id):
    """Get unread notifications for a user"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, message, type, created_at FROM notifications WHERE user_id = ? AND is_read = 0 ORDER BY created_at DESC",
            (user_id,)
        )
        rows = cursor.fetchall()
        conn.close()
        
        notifications = []
        for notif_id, message, notif_type, created_at in rows:
            notifications.append({
                'id': notif_id,
                'message': message,
                'type': notif_type,
                'created_at': created_at
            })
        return notifications

def mark_notification_as_read(notification_id):
    """Mark a notification as read"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ?",
            (notification_id,)
        )
        conn.commit()
        conn.close()

def check_booking_status():
    """Check if users have booked meals for tomorrow and send notifications"""
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email FROM users")
        all_users = cursor.fetchall()
        conn.close()
    
    for user_id, user_name, user_email in all_users:
        bookings = get_bookings_with_attendance(user_id, tomorrow_str)
        # Check if any meal is booked
        is_any_meal_booked = any(bookings[meal]['food_items'] for meal in bookings)
        
        if not is_any_meal_booked:
            # Add notification for user
            add_notification(
                user_id,
                f"You haven't booked any meals for tomorrow ({tomorrow_str}) yet. The booking window closes at 1 PM.",
                "booking_reminder"
            )

def send_evening_reminders():
    """Send evening reminders to book meals"""
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM users")
        all_users = cursor.fetchall()
        conn.close()
    
    for user_id, user_name in all_users:
        # Add notification for user
        add_notification(
            user_id,
            f"Don't forget to book your meals for tomorrow ({tomorrow_str})! Booking closes at 1 PM.",
            "evening_reminder"
        )

def send_fine_notifications():
    """Send notifications about fines"""
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get all users with fines from yesterday
        cursor.execute(
            "SELECT DISTINCT student_id FROM fines WHERE date = ? AND paid = 0",
            (yesterday_str,)
        )
        users_with_fines = [row[0] for row in cursor.fetchall()]
        
        for user_id in users_with_fines:
            # Get fine details
            cursor.execute(
                "SELECT meal_type, amount FROM fines WHERE student_id = ? AND date = ? AND paid = 0",
                (user_id, yesterday_str)
            )
            fines = cursor.fetchall()
            
            total_fine = sum(fine[1] for fine in fines)
            meal_types = ", ".join(set(fine[0] for fine in fines))
            
            # Add notification for user
            add_notification(
                user_id,
                f"You have been fined ₹{total_fine} for missing {meal_types} meal(s) on {yesterday_str}. Please check your fines page for details.",
                "fine_notification"
            )
        
        conn.close()

# New functions for meal cancellation and booking
def get_meal_times():
    """Return meal times"""
    return MEAL_TIMES

def can_cancel_meal(date_str, meal_type):
    """Check if a meal can be cancelled (at least 1 hour before meal time)"""
    meal_times = get_meal_times()
    meal_time = meal_times.get(meal_type)
    
    if not meal_time:
        return False
    
    # Parse the date string
    meal_date = datetime.strptime(date_str, '%Y-%m-%d').date()
    
    # Create datetime objects for meal time and current time
    meal_datetime = datetime.combine(meal_date, time(hour=meal_time))
    current_datetime = datetime.now()
    
    # Check if current time is at least 1 hour before meal time
    return current_datetime < (meal_datetime - timedelta(hours=1))

def clear_meal_booking(student_id, booking_date, meal_type):
    """Delete bookings for a specific meal"""
    with db_lock:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute(
            "DELETE FROM bookings WHERE student_id = ? AND date = ? AND meal_type = ?",
            (student_id, booking_date, meal_type)
        )
        conn.commit()
        conn.close()

def get_booking_deadline():
    """Get the booking deadline for tomorrow's meals"""
    today = date.today()
    # Booking is allowed from 6 PM today to 1 AM tomorrow
    booking_start = datetime.combine(today, time(hour=18))  # 6 PM today
    booking_end = datetime.combine(today + timedelta(days=1), time(hour=1))  # 1 AM tomorrow
    return booking_start, booking_end

def can_edit_booking():
    """Check if booking/editing is currently allowed"""
    booking_start, booking_end = get_booking_deadline()
    now = datetime.now()
    return booking_start <= now <= booking_end 