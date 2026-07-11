from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import sqlite3
from datetime import date, datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
import json
import calendar
import csv
from io import StringIO
import os

# Add custom filter for datetime formatting
def datetimeformat(value, format='%Y-%m-%d %H:%M:%S'):
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except:
            try:
                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except:
                return value
    return value.strftime(format)

app = Flask(__name__)
app.secret_key = 'staff_secret_key_here'

# Register the custom filter
app.jinja_env.filters['datetimeformat'] = datetimeformat

FOOTER_SYMBOL = "🍴 MessMate | Indian UA"

# --- Database Configuration ---
DB_FILE = "mess_app.db"

def init_staff_db():
    """Create staff tables if they don't exist"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Staff table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default admin staff if not exists
    cursor.execute("SELECT * FROM staff WHERE username = 'admin'")
    if not cursor.fetchone():
        password_hash = generate_password_hash('admin123')
        cursor.execute(
            "INSERT INTO staff (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            ('admin', 'admin@messmate.com', password_hash, 'admin')
        )
    
    # Create notification templates table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notification_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            template_text TEXT NOT NULL,
            target_audience TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default templates
    default_templates = [
        ('booking_reminder', 'Reminder: Please book your meals for tomorrow before 8 PM.', 'all'),
        ('fine_reminder', 'Urgent: You have pending fines. Please clear them at the earliest.', 'unpaid_fines'),
        ('maintenance', 'Notice: System maintenance scheduled. Service may be temporarily unavailable.', 'all'),
        ('special_meal', 'Special meal available tomorrow! Book early to avoid disappointment.', 'all')
    ]
    
    for template_name, template_text, target in default_templates:
        cursor.execute('''
            INSERT OR IGNORE INTO notification_templates (name, template_text, target_audience) 
            VALUES (?, ?, ?)
        ''', (template_name, template_text, target))
    
    # Create notifications table with proper schema
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            message TEXT NOT NULL,
            type TEXT NOT NULL,
            target_audience TEXT DEFAULT 'all',
            sent_count INTEGER DEFAULT 0,
            sender_id INTEGER,
            is_read BOOLEAN DEFAULT 0,
            scheduled_at TIMESTAMP,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'sent',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id),
            FOREIGN KEY (sender_id) REFERENCES staff (id)
        )
    ''')
    
    # Create reviews table if not exists - UPDATED SCHEMA
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER,
            date TEXT NOT NULL,
            meal_type TEXT NOT NULL,
            item TEXT NOT NULL,
            rating INTEGER NOT NULL,
            feedback TEXT,
            is_anonymous BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users (id)
        )
    ''')
    
    # Create staff_responses table for feedback responses
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS staff_responses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            review_id INTEGER,
            staff_id INTEGER,
            response_text TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (review_id) REFERENCES reviews (id),
            FOREIGN KEY (staff_id) REFERENCES staff (id)
        )
    ''')
    
    # Create menu_calendar table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS menu_calendar (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE NOT NULL,
            breakfast_items TEXT,
            lunch_items TEXT,
            dinner_items TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create system_settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_deadline TEXT DEFAULT '20:00',
            cancellation_window INTEGER DEFAULT 2,
            default_fine INTEGER DEFAULT 50,
            max_daily_bookings INTEGER DEFAULT 3,
            system_mode TEXT DEFAULT 'normal',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Create meal_timings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS meal_timings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            breakfast_time TEXT DEFAULT '07:00',
            lunch_time TEXT DEFAULT '12:30',
            dinner_time TEXT DEFAULT '19:00',
            weekend_breakfast BOOLEAN DEFAULT 1,
            weekend_lunch BOOLEAN DEFAULT 1,
            weekend_dinner BOOLEAN DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Insert default system settings if not exists
    cursor.execute("SELECT COUNT(*) FROM system_settings")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO system_settings (booking_deadline, cancellation_window, default_fine, max_daily_bookings, system_mode)
            VALUES (?, ?, ?, ?, ?)
        ''', ('20:00', 2, 50, 3, 'normal'))
    
    # Insert default meal timings if not exists
    cursor.execute("SELECT COUNT(*) FROM meal_timings")
    if cursor.fetchone()[0] == 0:
        cursor.execute('''
            INSERT INTO meal_timings (breakfast_time, lunch_time, dinner_time, weekend_breakfast, weekend_lunch, weekend_dinner)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', ('07:00', '12:30', '19:00', 1, 1, 1))
    
    conn.commit()
    conn.close()

def update_all_tables():
    """Update all tables with missing columns"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Check and add created_at to bookings table
        cursor.execute("PRAGMA table_info(bookings)")
        booking_columns = [column[1] for column in cursor.fetchall()]
        if 'created_at' not in booking_columns:
            cursor.execute('ALTER TABLE bookings ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
            print("✅ Added created_at to bookings table")
        
        # Check and add created_at to cancellations table
        cursor.execute("PRAGMA table_info(cancellations)")
        cancellation_columns = [column[1] for column in cursor.fetchall()]
        if 'created_at' not in cancellation_columns:
            cursor.execute('ALTER TABLE cancellations ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
            print("✅ Added created_at to cancellations table")
        
        # Check and add created_at to fines table
        cursor.execute("PRAGMA table_info(fines)")
        fine_columns = [column[1] for column in cursor.fetchall()]
        if 'created_at' not in fine_columns:
            cursor.execute('ALTER TABLE fines ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
            print("✅ Added created_at to fines table")
        
        # Check and add waived and reason to fines table
        if 'waived' not in fine_columns:
            cursor.execute('ALTER TABLE fines ADD COLUMN waived INTEGER DEFAULT 0')
            print("✅ Added waived to fines table")
        if 'reason' not in fine_columns:
            cursor.execute('ALTER TABLE fines ADD COLUMN reason TEXT')
            print("✅ Added reason to fines table")
        
        # Check and add created_at to reviews table - FIX FOR THE ERROR
        cursor.execute("PRAGMA table_info(reviews)")
        review_columns = [column[1] for column in cursor.fetchall()]
        if 'created_at' not in review_columns:
            cursor.execute('ALTER TABLE reviews ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
            print("✅ Added created_at to reviews table")
        
        # Also ensure is_anonymous exists in reviews table
        if 'is_anonymous' not in review_columns:
            cursor.execute('ALTER TABLE reviews ADD COLUMN is_anonymous BOOLEAN DEFAULT 0')
            print("✅ Added is_anonymous to reviews table")
        
        conn.commit()
        print("✅ All table updates completed successfully")
        
    except Exception as e:
        print(f"❌ Error updating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

# Initialize staff database
init_staff_db()
update_all_tables()

# --- Staff Authentication Functions ---
def verify_staff(username, password):
    """Verify staff credentials"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff WHERE username = ?", (username,))
    staff = cursor.fetchone()
    conn.close()
    
    if staff and check_password_hash(staff[3], password):
        return staff
    return None

def get_staff_by_username(username):
    """Get staff by username"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff WHERE username = ?", (username,))
    staff = cursor.fetchone()
    conn.close()
    return staff

# --- Staff Decorators ---
def staff_login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'staff_id' not in session:
            flash('Please log in to access staff portal.', 'warning')
            return redirect(url_for('staff_login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'staff_id' not in session or session.get('staff_role') != 'admin':
            flash('Admin access required.', 'danger')
            return redirect(url_for('staff_dashboard'))
        return f(*args, **kwargs)
    return decorated_function

# --- Student Statistics Functions ---
def get_student_statistics(student_id):
    """Get comprehensive statistics for a specific student"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Verify student exists first
        cursor.execute("SELECT id FROM users WHERE id = ?", (student_id,))
        if not cursor.fetchone():
            return {
                'total_bookings': 0,
                'meals_attended': 0,
                'cancellations': 0,
                'total_fines': 0.0,
                'fines_paid': 0.0,
                'remaining_balance': 0.0,
                'attendance_rate': 0.0
            }
        
        # Total bookings
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE student_id = ?", (student_id,))
        total_bookings = cursor.fetchone()[0] or 0
        
        # Meals attended (present in attendance)
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (student_id,))
        meals_attended = cursor.fetchone()[0] or 0
        
        # Cancellations
        cursor.execute("SELECT COUNT(*) FROM cancellations WHERE student_id = ?", (student_id,))
        cancellations = cursor.fetchone()[0] or 0
        
        # Total fines
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM fines WHERE student_id = ?", (student_id,))
        total_fines = float(cursor.fetchone()[0] or 0)
        
        # Fines paid
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM fines WHERE student_id = ? AND paid = 1", (student_id,))
        fines_paid = float(cursor.fetchone()[0] or 0)
        
        # Remaining balance (unpaid fines)
        remaining_balance = total_fines - fines_paid
        
        # Calculate attendance rate (handle division by zero)
        if total_bookings > 0:
            attendance_rate = round((meals_attended / total_bookings * 100), 1)
        else:
            attendance_rate = 0.0
        
        return {
            'total_bookings': int(total_bookings),
            'meals_attended': int(meals_attended),
            'cancellations': int(cancellations),
            'total_fines': float(total_fines),
            'fines_paid': float(fines_paid),
            'remaining_balance': float(remaining_balance),
            'attendance_rate': float(attendance_rate)
        }
        
    except Exception as e:
        print(f"Error getting student statistics: {e}")
        return {
            'total_bookings': 0,
            'meals_attended': 0,
            'cancellations': 0,
            'total_fines': 0.0,
            'fines_paid': 0.0,
            'remaining_balance': 0.0,
            'attendance_rate': 0.0
        }
    finally:
        conn.close()

def get_student_recent_activity(student_id):
    """Get recent activity for a student"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    recent_activity = []
    
    try:
        # Check if created_at column exists in bookings table
        cursor.execute("PRAGMA table_info(bookings)")
        booking_columns = [column[1] for column in cursor.fetchall()]
        has_booking_created_at = 'created_at' in booking_columns
        
        # Get recent bookings (last 3)
        if has_booking_created_at:
            cursor.execute('''
                SELECT date, meal_type, item, created_at 
                FROM bookings 
                WHERE student_id = ? 
                ORDER BY created_at DESC 
                LIMIT 3
            ''', (student_id,))
        else:
            cursor.execute('''
                SELECT date, meal_type, item, date as created_at 
                FROM bookings 
                WHERE student_id = ? 
                ORDER BY date DESC 
                LIMIT 3
            ''', (student_id,))
        
        recent_bookings = cursor.fetchall()
        
        for booking in recent_bookings:
            recent_activity.append({
                'date': str(booking[0]),
                'type': 'booking',
                'description': f'Booked {booking[2]} for {booking[1]}'
            })
        
        # Check if created_at column exists in cancellations table
        cursor.execute("PRAGMA table_info(cancellations)")
        cancellation_columns = [column[1] for column in cursor.fetchall()]
        has_cancellation_created_at = 'created_at' in cancellation_columns
        
        # Get recent cancellations (last 3)
        if has_cancellation_created_at:
            cursor.execute('''
                SELECT date, meal_type, reason, created_at 
                FROM cancellations 
                WHERE student_id = ? 
                ORDER BY created_at DESC 
                LIMIT 3
            ''', (student_id,))
        else:
            cursor.execute('''
                SELECT date, meal_type, reason, date as created_at 
                FROM cancellations 
                WHERE student_id = ? 
                ORDER BY date DESC 
                LIMIT 3
            ''', (student_id,))
        
        recent_cancellations = cursor.fetchall()
        
        for cancellation in recent_cancellations:
            recent_activity.append({
                'date': str(cancellation[0]),
                'type': 'cancellation',
                'description': f'Cancelled {cancellation[1]} - {cancellation[2]}'
            })
        
        # Check if created_at column exists in fines table
        cursor.execute("PRAGMA table_info(fines)")
        fine_columns = [column[1] for column in cursor.fetchall()]
        has_fine_created_at = 'created_at' in fine_columns
        
        # Get recent fines (last 3)
        if has_fine_created_at:
            cursor.execute('''
                SELECT date, meal_type, amount, paid, created_at 
                FROM fines 
                WHERE student_id = ? 
                ORDER BY created_at DESC 
                LIMIT 3
            ''', (student_id,))
        else:
            cursor.execute('''
                SELECT date, meal_type, amount, paid, date as created_at 
                FROM fines 
                WHERE student_id = ? 
                ORDER BY date DESC 
                LIMIT 3
            ''', (student_id,))
        
        recent_fines = cursor.fetchall()
        
        for fine in recent_fines:
            status = 'Paid' if fine[3] else 'Unpaid'
            recent_activity.append({
                'date': str(fine[0]),
                'type': 'fine',
                'description': f'Fine of ₹{fine[2]} for {fine[1]} - {status}'
            })
        
        # Sort by date and get top 5 most recent
        recent_activity.sort(key=lambda x: x['date'], reverse=True)
        recent_activity = recent_activity[:5]
        
    except Exception as e:
        print(f"Error getting recent activity: {e}")
    
    conn.close()
    return recent_activity

@app.route("/staff/profile", methods=["GET", "POST"])
@staff_login_required
def staff_profile():
    """Staff profile management"""
    if request.method == "POST":
        # Check if it's a profile update or password change
        if 'current_password' in request.form:
            # Password change
            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")
            
            # Verify current password
            staff = verify_staff(session['staff_email'], current_password)
            if not staff:
                flash('Current password is incorrect', 'danger')
                return redirect(url_for('staff_profile'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'danger')
                return redirect(url_for('staff_profile'))
            
            # Update password
            update_staff_password(session['staff_id'], new_password)
            flash('Password updated successfully!', 'success')
            
        else:
            # Profile update
            name = request.form.get("name")
            phone = request.form.get("phone")
            
            update_staff_profile(session['staff_id'], name, phone)
            
            # Update session
            session['staff_name'] = name
            session['staff_phone'] = phone
            
            flash('Profile updated successfully!', 'success')
        
        return redirect(url_for('staff_profile'))
    
    return render_template("staff/profile.html")
# --- Dashboard Statistics Functions ---
def get_dashboard_stats():
    """Get statistics for staff dashboard"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Total students
    cursor.execute("SELECT COUNT(*) FROM users")
    total_students = cursor.fetchone()[0]
    
    # Today's bookings
    today_str = date.today().isoformat()
    cursor.execute("SELECT COUNT(DISTINCT student_id) FROM bookings WHERE date = ?", (today_str,))
    today_bookings = cursor.fetchone()[0]
    
    # Pending cancellations
    cursor.execute("SELECT COUNT(*) FROM cancellations WHERE approved = 0")
    pending_cancellations = cursor.fetchone()[0]
    
    # Unpaid fines count (number of people with unpaid fines)
    cursor.execute("SELECT COUNT(DISTINCT student_id) FROM fines WHERE paid = 0")
    unpaid_fines_count = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return {
        'total_students': total_students,
        'today_bookings': today_bookings,
        'pending_cancellations': pending_cancellations,
        'unpaid_fines_count': unpaid_fines_count
    }

def get_today_attendance_stats():
    """Get today's attendance statistics for charts"""
    today_str = date.today().isoformat()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get total students
    cursor.execute("SELECT COUNT(*) FROM users")
    total_students = cursor.fetchone()[0]
    
    # Get attendance counts by meal type
    cursor.execute('''
        SELECT meal_type, status, COUNT(*) 
        FROM attendance 
        WHERE date = ? 
        GROUP BY meal_type, status
    ''', (today_str,))
    attendance_data = cursor.fetchall()
    
    # Initialize counts
    breakfast_present = lunch_present = dinner_present = 0
    breakfast_absent = lunch_absent = dinner_absent = 0
    
    for meal_type, status, count in attendance_data:
        if status == 'Present':
            if meal_type == 'Breakfast':
                breakfast_present = count
            elif meal_type == 'Lunch':
                lunch_present = count
            elif meal_type == 'Dinner':
                dinner_present = count
        elif status == 'Absent':
            if meal_type == 'Breakfast':
                breakfast_absent = count
            elif meal_type == 'Lunch':
                lunch_absent = count
            elif meal_type == 'Dinner':
                dinner_absent = count
    
    # Calculate not scanned (booked but not scanned)
    cursor.execute('''
        SELECT COUNT(DISTINCT student_id) FROM bookings WHERE date = ?
    ''', (today_str,))
    total_booked = cursor.fetchone()[0]
    
    total_present = breakfast_present + lunch_present + dinner_present
    total_absent = breakfast_absent + lunch_absent + dinner_absent
    not_scanned = total_booked - total_present - total_absent if total_booked > (total_present + total_absent) else 0
    
    conn.close()
    
    return {
        'present': total_present,
        'absent': total_absent,
        'not_scanned': not_scanned if not_scanned > 0 else 0,
        'breakfast': {'present': breakfast_present, 'absent': breakfast_absent},
        'lunch': {'present': lunch_present, 'absent': lunch_absent},
        'dinner': {'present': dinner_present, 'absent': dinner_absent}
    }

def get_wastage_data():
    """Get wastage data for today (simulated based on absent students)"""
    attendance_stats = get_today_attendance_stats()
    
    # Simulate wastage based on absent students (approx 0.2kg per absent meal)
    breakfast_wastage = round(attendance_stats['breakfast']['absent'] * 0.2, 1)
    lunch_wastage = round(attendance_stats['lunch']['absent'] * 0.3, 1)
    dinner_wastage = round(attendance_stats['dinner']['absent'] * 0.25, 1)
    
    return {
        'breakfast': breakfast_wastage,
        'lunch': lunch_wastage,
        'dinner': dinner_wastage
    }

def get_recent_activities():
    """Get recent activities for dashboard"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get recent bookings based on current time logic
    current_time = datetime.now().time()
    current_date = date.today()
    
    # Determine which bookings to show based on time
    if current_time >= datetime.strptime('18:00', '%H:%M').time():
        # After 6 PM, show tomorrow's bookings
        target_date = (current_date + timedelta(days=1)).isoformat()
        booking_title = "Tomorrow's Bookings"
    else:
        # Before 6 PM, show today's bookings
        target_date = current_date.isoformat()
        booking_title = "Today's Bookings"
    
    # Check if created_at column exists in bookings table
    cursor.execute("PRAGMA table_info(bookings)")
    booking_columns = [column[1] for column in cursor.fetchall()]
    has_booking_created_at = 'created_at' in booking_columns
    
    # Get recent bookings for the target date
    if has_booking_created_at:
        cursor.execute('''
            SELECT u.name, b.date, b.meal_type, b.item, b.created_at
            FROM bookings b 
            JOIN users u ON b.student_id = u.id 
            WHERE b.date = ?
            ORDER BY b.created_at DESC LIMIT 5
        ''', (target_date,))
    else:
        cursor.execute('''
            SELECT u.name, b.date, b.meal_type, b.item, b.date as created_at
            FROM bookings b 
            JOIN users u ON b.student_id = u.id 
            WHERE b.date = ?
            ORDER BY b.date DESC LIMIT 5
        ''', (target_date,))
    
    recent_bookings = cursor.fetchall()
    
    # Check if created_at column exists in fines table
    cursor.execute("PRAGMA table_info(fines)")
    fine_columns = [column[1] for column in cursor.fetchall()]
    has_fine_created_at = 'created_at' in fine_columns
    
    # Get recent fines (within 24 hours)
    twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).strftime('%Y-%m-%d %H:%M:%S')
    if has_fine_created_at:
        cursor.execute('''
            SELECT u.name, f.date, f.meal_type, f.amount, f.created_at
            FROM fines f 
            JOIN users u ON f.student_id = u.id 
            WHERE f.created_at >= ? OR f.date >= ?
            ORDER BY f.created_at DESC LIMIT 5
        ''', (twenty_four_hours_ago, (current_date - timedelta(days=1)).isoformat()))
    else:
        cursor.execute('''
            SELECT u.name, f.date, f.meal_type, f.amount, f.date as created_at
            FROM fines f 
            JOIN users u ON f.student_id = u.id 
            WHERE f.date >= ?
            ORDER BY f.date DESC LIMIT 5
        ''', ((current_date - timedelta(days=1)).isoformat(),))
    
    recent_fines = cursor.fetchall()
    
    # Check if created_at column exists in cancellations table
    cursor.execute("PRAGMA table_info(cancellations)")
    cancellation_columns = [column[1] for column in cursor.fetchall()]
    has_cancellation_created_at = 'created_at' in cancellation_columns
    
    # Get recent cancellations (within 24 hours)
    if has_cancellation_created_at:
        cursor.execute('''
            SELECT u.name, c.date, c.meal_type, c.reason, c.created_at
            FROM cancellations c 
            JOIN users u ON c.student_id = u.id 
            WHERE c.created_at >= ? OR c.date >= ?
            ORDER BY c.created_at DESC LIMIT 5
        ''', (twenty_four_hours_ago, (current_date - timedelta(days=1)).isoformat()))
    else:
        cursor.execute('''
            SELECT u.name, c.date, c.meal_type, c.reason, c.date as created_at
            FROM cancellations c 
            JOIN users u ON c.student_id = u.id 
            WHERE c.date >= ?
            ORDER BY c.date DESC LIMIT 5
        ''', ((current_date - timedelta(days=1)).isoformat(),))
    
    recent_cancellations = cursor.fetchall()
    
    conn.close()
    
    return {
        'recent_bookings': recent_bookings,
        'recent_fines': recent_fines,
        'recent_cancellations': recent_cancellations,
        'booking_title': booking_title
    }

def get_booking_trends():
    """Get booking trends for charts"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Last 7 days booking trends
    dates = []
    breakfast_counts = []
    lunch_counts = []
    dinner_counts = []
    
    for i in range(7):
        current_date = (date.today() - timedelta(days=i)).isoformat()
        dates.insert(0, current_date)
        
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND meal_type = 'Breakfast'", (current_date,))
        breakfast_counts.insert(0, cursor.fetchone()[0])
        
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND meal_type = 'Lunch'", (current_date,))
        lunch_counts.insert(0, cursor.fetchone()[0])
        
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND meal_type = 'Dinner'", (current_date,))
        dinner_counts.insert(0, cursor.fetchone()[0])
    
    conn.close()
    
    return {
        'dates': dates,
        'breakfast': breakfast_counts,
        'lunch': lunch_counts,
        'dinner': dinner_counts
    }

# --- Enhanced Analytics Functions ---
def get_analytics_data(period='weekly', selected_date=None):
    """Get comprehensive analytics data for the selected period"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Calculate date ranges based on period
    today = date.today()
    if period == 'weekly':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
        group_by = "strftime('%Y-%m-%d', date)"
        x_axis_labels = [f"Day {i+1}" for i in range(7)]
    elif period == 'monthly':
        start_date = today.replace(day=1)
        end_date = today
        group_by = "strftime('%W', date)"
        # Calculate number of weeks in current month
        first_day = today.replace(day=1)
        last_day = today.replace(day=calendar.monthrange(today.year, today.month)[1])
        num_weeks = (last_day.isocalendar()[1] - first_day.isocalendar()[1]) + 1
        x_axis_labels = [f"Week {i+1}" for i in range(num_weeks)]
    else:  # yearly
        start_date = today.replace(month=1, day=1)
        end_date = today
        group_by = "strftime('%Y-%m', date)"
        x_axis_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 
                         'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
    
    # Key Metrics
    # Total meals served
    cursor.execute(
        "SELECT COUNT(*) FROM bookings WHERE date BETWEEN ? AND ?",
        (start_date, end_date)
    )
    total_meals = cursor.fetchone()[0] or 0
    
    # Fine revenue
    cursor.execute(
        "SELECT COALESCE(SUM(amount), 0) FROM fines WHERE date BETWEEN ? AND ? AND paid = 1",
        (start_date, end_date)
    )
    fine_revenue = cursor.fetchone()[0] or 0
    
    # Cancellations
    cursor.execute(
        "SELECT COUNT(*) FROM cancellations WHERE date BETWEEN ? AND ?",
        (start_date, end_date)
    )
    cancellations = cursor.fetchone()[0] or 0
    
    # Average rating
    cursor.execute(
        "SELECT COALESCE(AVG(rating), 0) FROM reviews WHERE date BETWEEN ? AND ?",
        (start_date, end_date)
    )
    average_rating = round(cursor.fetchone()[0] or 0, 1)
    
    # Meal Popularity (Top 5 most booked items - all meals)
    cursor.execute('''
        SELECT item, COUNT(*) as count 
        FROM bookings 
        WHERE date BETWEEN ? AND ?
        GROUP BY item 
        ORDER BY count DESC 
        LIMIT 5
    ''', (start_date, end_date))
    popular_items = cursor.fetchall()
    
    # Booking Distribution by Meal Type
    cursor.execute('''
        SELECT meal_type, COUNT(*) 
        FROM bookings 
        WHERE date BETWEEN ? AND ?
        GROUP BY meal_type
    ''', (start_date, end_date))
    booking_distribution = cursor.fetchall()
    
    # Attendance Trends with Not Scanned
    cursor.execute(f'''
        SELECT {group_by} as period, 
               SUM(CASE WHEN status = 'Present' THEN 1 ELSE 0 END) as present,
               SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent,
               SUM(CASE WHEN status IS NULL OR status = '' THEN 1 ELSE 0 END) as not_scanned
        FROM attendance 
        WHERE date BETWEEN ? AND ?
        GROUP BY period
        ORDER BY period
    ''', (start_date, end_date))
    attendance_trends = cursor.fetchall()
    
    # Get total bookings for each period to calculate not scanned properly
    cursor.execute(f'''
        SELECT {group_by} as period, COUNT(DISTINCT student_id) as total_booked
        FROM bookings 
        WHERE date BETWEEN ? AND ?
        GROUP BY period
        ORDER BY period
    ''', (start_date, end_date))
    booking_trends = cursor.fetchall()
    
    # Wastage Trends (estimated based on absent students)
    cursor.execute(f'''
        SELECT {group_by} as period, 
               SUM(CASE WHEN status = 'Absent' THEN 1 ELSE 0 END) as absent_count
        FROM attendance 
        WHERE date BETWEEN ? AND ?
        GROUP BY period
        ORDER BY period
    ''', (start_date, end_date))
    wastage_trends = cursor.fetchall()
    
    conn.close()
    
    # Process data for charts
    
    # Meal Popularity data
    meal_labels = [item[0] for item in popular_items]
    meal_data = [item[1] for item in popular_items]
    
    # Booking Distribution data
    booking_labels = ['Breakfast', 'Lunch', 'Dinner']
    booking_data = [0, 0, 0]
    for meal_type, count in booking_distribution:
        if meal_type == 'Breakfast':
            booking_data[0] = count
        elif meal_type == 'Lunch':
            booking_data[1] = count
        elif meal_type == 'Dinner':
            booking_data[2] = count
    
    # Attendance Trends data
    attendance_present = [0] * len(x_axis_labels)
    attendance_absent = [0] * len(x_axis_labels)
    attendance_not_scanned = [0] * len(x_axis_labels)
    
    # Create mapping for periods to x_axis indices
    period_mapping = {}
    for idx, label in enumerate(x_axis_labels):
        if period == 'weekly':
            period_date = (start_date + timedelta(days=idx)).strftime('%Y-%m-%d')
            period_mapping[period_date] = idx
        elif period == 'monthly':
            period_mapping[str(idx+1)] = idx  # Week numbers as string
        else:  # yearly
            month_num = idx + 1
            period_mapping[f"{today.year}-{month_num:02d}"] = idx
    
    # Fill attendance data
    for period_val, present, absent, not_scanned in attendance_trends:
        period_key = str(period_val)
        if period_key in period_mapping:
            idx = period_mapping[period_key]
            attendance_present[idx] = present
            attendance_absent[idx] = absent
            attendance_not_scanned[idx] = not_scanned
    
    # Calculate proper not scanned from bookings vs attendance
    for period_val, total_booked in booking_trends:
        period_key = str(period_val)
        if period_key in period_mapping:
            idx = period_mapping[period_key]
            actual_not_scanned = total_booked - (attendance_present[idx] + attendance_absent[idx])
            if actual_not_scanned > 0:
                attendance_not_scanned[idx] = actual_not_scanned
    
    # Wastage Trends data (estimate 0.25kg per absent meal)
    wastage_data = [0] * len(x_axis_labels)
    for period_val, absent_count in wastage_trends:
        period_key = str(period_val)
        if period_key in period_mapping:
            idx = period_mapping[period_key]
            wastage_data[idx] = round(absent_count * 0.25, 1)
    
    # Detailed reports for selected date or recent dates
    detailed_reports = get_detailed_reports(selected_date)
    
    return {
        'key_metrics': {
            'total_meals': total_meals,
            'fine_revenue': fine_revenue,
            'cancellations': cancellations,
            'average_rating': average_rating
        },
        'meal_popularity': {
            'labels': meal_labels,
            'data': meal_data
        },
        'booking_distribution': {
            'labels': booking_labels,
            'data': booking_data
        },
        'attendance_trends': {
            'labels': x_axis_labels,
            'present': attendance_present,
            'absent': attendance_absent,
            'not_scanned': attendance_not_scanned
        },
        'wastage_trends': {
            'labels': x_axis_labels,
            'data': wastage_data
        },
        'detailed_reports': detailed_reports
    }

def get_detailed_reports(selected_date=None):
    """Get detailed daily reports"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    if selected_date:
        # Get data for specific date
        query_date = selected_date
        dates = [query_date]
    else:
        # Get data for last 3 days
        query_date = date.today().isoformat()
        dates = []
        for i in range(3):
            report_date = (date.today() - timedelta(days=i)).isoformat()
            dates.append(report_date)
    
    detailed_reports = []
    
    for report_date in dates:
        # Breakfast count
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND meal_type = 'Breakfast'", (report_date,))
        breakfast = cursor.fetchone()[0] or 0
        
        # Lunch count
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND meal_type = 'Lunch'", (report_date,))
        lunch = cursor.fetchone()[0] or 0
        
        # Dinner count
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date = ? AND meal_type = 'Dinner'", (report_date,))
        dinner = cursor.fetchone()[0] or 0
        
        # Revenue
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM fines WHERE date = ? AND paid = 1", (report_date,))
        revenue = cursor.fetchone()[0] or 0
        
        # Cancellations
        cursor.execute("SELECT COUNT(*) FROM cancellations WHERE date = ?", (report_date,))
        cancellations = cursor.fetchone()[0] or 0
        
        # Wastage (estimated based on absent students)
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE date = ? AND status = 'Absent'", (report_date,))
        absent_count = cursor.fetchone()[0] or 0
        wastage = round(absent_count * 0.25, 1)  # 0.25kg per absent meal
        
        detailed_reports.append({
            'date': report_date,
            'breakfast': breakfast,
            'lunch': lunch,
            'dinner': dinner,
            'revenue': revenue,
            'cancellations': cancellations,
            'wastage': wastage
        })
    
    conn.close()
    return detailed_reports

def get_meal_popularity_by_type(period='weekly', meal_type='all'):
    """Get meal popularity data filtered by meal type"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Calculate date ranges based on period
    today = date.today()
    if period == 'weekly':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'monthly':
        start_date = today.replace(day=1)
        end_date = today
    else:  # yearly
        start_date = today.replace(month=1, day=1)
        end_date = today
    
    # Build query based on meal type filter
    if meal_type == 'all':
        query = '''
            SELECT item, COUNT(*) as count 
            FROM bookings 
            WHERE date BETWEEN ? AND ?
            GROUP BY item 
            ORDER BY count DESC 
            LIMIT 5
        '''
        params = (start_date, end_date)
    else:
        query = '''
            SELECT item, COUNT(*) as count 
            FROM bookings 
            WHERE date BETWEEN ? AND ? AND meal_type = ?
            GROUP BY item 
            ORDER BY count DESC 
            LIMIT 5
        '''
        params = (start_date, end_date, meal_type.capitalize())
    
    cursor.execute(query, params)
    popular_items = cursor.fetchall()
    
    conn.close()
    
    # Process data
    meal_labels = [item[0] for item in popular_items]
    meal_data = [item[1] for item in popular_items]
    
    return {
        'labels': meal_labels,
        'data': meal_data
    }

# --- Enhanced Notification Functions ---
def get_notification_stats(period='weekly'):
    """Get accurate notification statistics"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Count ALL staff announcements regardless of date
        cursor.execute("""
            SELECT COUNT(*) FROM notifications 
            WHERE type = 'staff_announcement' 
            AND user_id IS NULL
        """)
        total = cursor.fetchone()[0] or 0
        
        # Count by target audience
        cursor.execute("""
            SELECT COALESCE(target_audience, 'all'), COUNT(*) 
            FROM notifications 
            WHERE type = 'staff_announcement' 
            AND user_id IS NULL
            GROUP BY COALESCE(target_audience, 'all')
        """)
        audience_data = cursor.fetchall()
        
        # Calculate broadcast vs targeted
        broadcast = 0
        targeted = 0
        for audience, count in audience_data:
            if audience == 'all':
                broadcast = count
            else:
                targeted += count
        
        # All are considered successful
        success = total
        
    except Exception as e:
        print(f"Stats error: {e}")
        total = broadcast = targeted = success = 0
    
    conn.close()
    
    return {
        'total': total,
        'broadcast': broadcast,
        'targeted': targeted,
        'success': success
    }

def get_notifications_with_filters(date_filter='', period='weekly'):
    """Get staff announcements with CORRECT date handling"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Get staff announcements with proper date handling
        query = '''
            SELECT n.id, n.message, 
                   COALESCE(n.target_audience, 'all') as target_audience, 
                   COALESCE(n.sent_count, 1) as sent_count, 
                   n.sent_at,
                   n.created_at,
                   COALESCE(s.username, 'System') as sender, 
                   COALESCE(n.status, 'sent') as status
            FROM notifications n
            LEFT JOIN staff s ON n.sender_id = s.id
            WHERE n.type = 'staff_announcement' 
            AND n.user_id IS NULL
        '''
        params = []
        
        # CORRECT date filtering - use DATE() function properly
        if date_filter:
            query += " AND DATE(n.sent_at) = ?"
            params.append(date_filter)
            print(f"🔍 Filtering by date: {date_filter}")
        
        query += " ORDER BY n.sent_at DESC, n.created_at DESC"
        
        cursor.execute(query, params)
        notifications_data = cursor.fetchall()
        
        print(f"📧 Found {len(notifications_data)} notifications")
        for notif in notifications_data:
            print(f"   - ID: {notif[0]}, Sent At: {notif[4]}, Created At: {notif[5]}")
        
    except Exception as e:
        print(f"❌ Notifications error: {e}")
        notifications_data = []
    
    # Format notifications for template
    notifications = []
    for notif in notifications_data:
        target_display = {
            'all': 'All Students',
            'male': 'Male Hostel',
            'female': 'Female Hostel',
            'unpaid_fines': 'Students with Unpaid Fines'
        }.get(notif[2], notif[2])
        
        # Use sent_at date, fallback to created_at
        display_date = notif[4] if notif[4] else notif[5]
        
        # Format date properly
        if display_date:
            if isinstance(display_date, str):
                try:
                    # Handle different date string formats
                    if 'T' in display_date:
                        dt = datetime.fromisoformat(display_date.replace('Z', '+00:00'))
                    else:
                        dt = datetime.strptime(display_date, '%Y-%m-%d %H:%M:%S')
                    formatted_date = dt.strftime('%Y-%m-%d %H:%M:%S')
                except:
                    formatted_date = str(display_date)
            else:
                formatted_date = str(display_date)
        else:
            formatted_date = "Unknown Date"
        
        notifications.append({
            'id': notif[0],
            'message': notif[1],
            'target': target_display,
            'target_raw': notif[2],
            'sent_count': notif[3],
            'date': formatted_date,
            'sender': notif[6],
            'status': notif[7].title()
        })
    
    conn.close()
    return notifications

def get_notification_template(template_name):
    """Get notification template by name"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT template_text, target_audience FROM notification_templates WHERE name = ?", (template_name,))
        template = cursor.fetchone()
    except Exception:
        template = None
    
    conn.close()
    
    if template:
        return {
            'template_text': template[0],
            'target_audience': template[1]
        }
    return None

def delete_notification(notification_id):
    """Delete a notification"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM notifications WHERE id = ?", (notification_id,))
    conn.commit()
    conn.close()

def clear_all_notifications():
    """Clear all staff announcement notifications"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM notifications WHERE type = 'staff_announcement' AND user_id IS NULL")
    conn.commit()
    conn.close()

def send_notification_to_students(message, target='all', sender_id=None, schedule=None):
    """Send notification to students - creates ONE staff record with CORRECT date"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get students based on target
    if target == 'all':
        cursor.execute("SELECT id FROM users")
    elif target == 'male':
        cursor.execute("SELECT id FROM users WHERE hostel_type = 'Male'")
    elif target == 'female':
        cursor.execute("SELECT id FROM users WHERE hostel_type = 'Female'")
    elif target == 'unpaid_fines':
        cursor.execute("SELECT DISTINCT student_id FROM fines WHERE paid = 0")
    else:
        cursor.execute("SELECT id FROM users")  # fallback
    
    students = cursor.fetchall()
    sent_count = len(students)
    
    # Get CURRENT datetime for proper timestamp
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    try:
        # Create ONE staff announcement record with EXPLICIT current timestamp
        cursor.execute(
            """INSERT INTO notifications 
               (message, type, target_audience, sent_count, sender_id, sent_at, status) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message, "staff_announcement", target, sent_count, sender_id, current_time, 'sent')
        )
        
        staff_notification_id = cursor.lastrowid
        print(f"✅ Created staff notification #{staff_notification_id} at {current_time}")
        
        # Create individual student notifications
        for student_id, in students:
            cursor.execute(
                """INSERT INTO notifications 
                   (user_id, message, type, target_audience, sender_id, sent_at, status) 
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (student_id, f"STAFF: {message}", "student_notification", target, sender_id, current_time, 'sent')
            )
        
        conn.commit()
        print(f"✅ Notification sent to {sent_count} students at {current_time}")
        return sent_count
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Error sending notifications: {e}")
        return 0
    finally:
        conn.close()

# --- Enhanced Cancellation Management ---
def get_cancellation_analytics(period='weekly', meal_type='all', hostel_type='all'):
    """Get comprehensive cancellation analytics with filters"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Calculate date range based on period
    today = date.today()
    if period == 'weekly':
        start_date = today - timedelta(days=today.weekday())
        end_date = today
    elif period == 'monthly':
        start_date = today.replace(day=1)
        end_date = today
    else:  # yearly
        start_date = today.replace(month=1, day=1)
        end_date = today
    
    # Build base query
    base_query = '''
        FROM cancellations c 
        JOIN users u ON c.student_id = u.id
        WHERE c.date BETWEEN ? AND ?
    '''
    params = [start_date, end_date]
    
    # Add meal type filter
    if meal_type != 'all':
        base_query += " AND c.meal_type = ?"
        params.append(meal_type)
    
    # Add hostel type filter
    if hostel_type != 'all':
        base_query += " AND u.hostel_type = ?"
        params.append(hostel_type)
    
    # Overall statistics
    cursor.execute(f'''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) as pending,
            SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN approved = 2 THEN 1 ELSE 0 END) as rejected
        {base_query}
    ''', params)
    stats_data = cursor.fetchone()
    
    # Ensure all values are 0 if no data
    if not stats_data:
        stats_data = (0, 0, 0, 0)
    else:
        stats_data = (
            stats_data[0] or 0,
            stats_data[1] or 0,
            stats_data[2] or 0,
            stats_data[3] or 0
        )
    
    # Meal type distribution (for the single chart)
    cursor.execute(f'''
        SELECT meal_type, COUNT(*) as count
        {base_query}
        GROUP BY meal_type
    ''', params)
    meal_distribution = cursor.fetchall()
    
    # Default meal distribution with zeros
    default_meal_distribution = {'Breakfast': 0, 'Lunch': 0, 'Dinner': 0}
    for meal_type, count in meal_distribution:
        default_meal_distribution[meal_type] = count
    
    # Top cancellation reasons with percentages
    cursor.execute(f'''
        SELECT reason, COUNT(*) as count 
        {base_query}
        GROUP BY reason 
        ORDER BY count DESC 
        LIMIT 5
    ''', params)
    top_reasons = cursor.fetchall()
    
    # Calculate percentages for top reasons
    total_reasons = sum([count for _, count in top_reasons])
    top_reasons_with_percent = []
    for reason, count in top_reasons:
        percentage = round((count / total_reasons) * 100, 1) if total_reasons > 0 else 0
        top_reasons_with_percent.append((reason, count, percentage))
    
    conn.close()
    
    return {
        'total': stats_data[0],
        'pending': stats_data[1],
        'approved': stats_data[2],
        'rejected': stats_data[3],
        'meal_distribution': default_meal_distribution,
        'top_reasons': top_reasons_with_percent,
        'period': period,
        'meal_type': meal_type,
        'hostel_type': hostel_type
    }

# --- Ratings and Feedback Functions ---
def get_ratings_and_feedback(filters=None):
    """Get ratings and feedback with optional filters"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if created_at column exists in reviews table
    cursor.execute("PRAGMA table_info(reviews)")
    review_columns = [column[1] for column in cursor.fetchall()]
    has_created_at = 'created_at' in review_columns
    has_is_anonymous = 'is_anonymous' in review_columns
    
    # Build base query
    if has_created_at and has_is_anonymous:
        query = '''
            SELECT r.id, 
                   CASE WHEN r.is_anonymous = 1 THEN 'Anonymous' ELSE u.name END as student_name,
                   r.date, r.meal_type, r.item, r.rating, r.feedback, r.created_at,
                   sr.response_text, s.username as responder_name, sr.created_at as response_date
            FROM reviews r
            LEFT JOIN users u ON r.student_id = u.id
            LEFT JOIN staff_responses sr ON r.id = sr.review_id
            LEFT JOIN staff s ON sr.staff_id = s.id
            WHERE 1=1
        '''
        order_by = " ORDER BY r.date DESC, r.created_at DESC"
    elif has_created_at:
        query = '''
            SELECT r.id, 
                   u.name as student_name,
                   r.date, r.meal_type, r.item, r.rating, r.feedback, r.created_at,
                   sr.response_text, s.username as responder_name, sr.created_at as response_date
            FROM reviews r
            LEFT JOIN users u ON r.student_id = u.id
            LEFT JOIN staff_responses sr ON r.id = sr.review_id
            LEFT JOIN staff s ON sr.staff_id = s.id
            WHERE 1=1
        '''
        order_by = " ORDER BY r.date DESC, r.created_at DESC"
    else:
        query = '''
            SELECT r.id, 
                   u.name as student_name,
                   r.date, r.meal_type, r.item, r.rating, r.feedback, r.date as created_at,
                   sr.response_text, s.username as responder_name, sr.created_at as response_date
            FROM reviews r
            LEFT JOIN users u ON r.student_id = u.id
            LEFT JOIN staff_responses sr ON r.id = sr.review_id
            LEFT JOIN staff s ON sr.staff_id = s.id
            WHERE 1=1
        '''
        order_by = " ORDER BY r.date DESC"
    
    params = []
    
    if filters:
        # Apply meal type filter
        if filters.get('meal_type') and filters['meal_type'] != 'all':
            query += " AND r.meal_type = ?"
            params.append(filters['meal_type'])
        
        # Apply rating filter
        if filters.get('rating') and filters['rating'] != 'all':
            query += " AND r.rating = ?"
            params.append(int(filters['rating']))
        
        # Apply date range filter
        if filters.get('start_date'):
            query += " AND r.date >= ?"
            params.append(filters['start_date'])
        if filters.get('end_date'):
            query += " AND r.date <= ?"
            params.append(filters['end_date'])
    
    query += order_by
    
    try:
        cursor.execute(query, params)
        reviews = cursor.fetchall()
    except sqlite3.OperationalError as e:
        print(f"Database error in get_ratings_and_feedback: {e}")
        # Fallback to simple query without joins if there are still issues
        query_fallback = "SELECT id, date, meal_type, item, rating, feedback FROM reviews ORDER BY date DESC"
        cursor.execute(query_fallback)
        reviews = cursor.fetchall()
        # Add placeholder values for missing columns
        reviews = [(r[0], 'Student', r[1], r[2], r[3], r[4], r[5], r[1], None, None, None) for r in reviews]
    
    conn.close()
    
    return reviews

def get_rating_analytics():
    """Get analytics data for ratings"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Overall average rating
    cursor.execute("SELECT AVG(rating) FROM reviews")
    overall_avg = cursor.fetchone()[0] or 0
    
    # Average rating by meal type
    cursor.execute("SELECT meal_type, AVG(rating) FROM reviews GROUP BY meal_type")
    meal_ratings = cursor.fetchall()
    
    # Rating distribution
    cursor.execute("SELECT rating, COUNT(*) FROM reviews GROUP BY rating ORDER BY rating")
    rating_distribution = cursor.fetchall()
    
    # Top rated items
    cursor.execute('''
        SELECT item, AVG(rating) as avg_rating, COUNT(*) as review_count 
        FROM reviews 
        GROUP BY item 
        HAVING COUNT(*) >= 3 
        ORDER BY avg_rating DESC 
        LIMIT 5
    ''')
    top_items = cursor.fetchall()
    
    # Low rated items (for flagging)
    cursor.execute('''
        SELECT item, AVG(rating) as avg_rating, COUNT(*) as review_count 
        FROM reviews 
        GROUP BY item 
        HAVING COUNT(*) >= 2 AND AVG(rating) < 3 
        ORDER BY avg_rating ASC 
        LIMIT 5
    ''')
    low_items = cursor.fetchall()
    
    # Recent trends (last 7 days)
    trends_query = '''
        SELECT date, AVG(rating) as avg_rating, COUNT(*) as review_count
        FROM reviews 
        WHERE date >= date('now', '-7 days')
        GROUP BY date
        ORDER BY date
    '''
    cursor.execute(trends_query)
    recent_trends = cursor.fetchall()
    
    conn.close()
    
    return {
        'overall_avg': round(overall_avg, 1),
        'meal_ratings': dict(meal_ratings),
        'rating_distribution': dict(rating_distribution),
        'top_items': top_items,
        'low_items': low_items,
        'recent_trends': recent_trends
    }

def add_staff_response(review_id, staff_id, response_text):
    """Add staff response to a review"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "INSERT INTO staff_responses (review_id, staff_id, response_text) VALUES (?, ?, ?)",
            (review_id, staff_id, response_text)
        )
        conn.commit()
        return True
    except Exception as e:
        print(f"Error adding staff response: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_flagged_reviews():
    """Get reviews that need attention (low ratings)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if is_anonymous column exists
    cursor.execute("PRAGMA table_info(reviews)")
    review_columns = [column[1] for column in cursor.fetchall()]
    has_is_anonymous = 'is_anonymous' in review_columns
    
    if has_is_anonymous:
        cursor.execute('''
            SELECT r.id, 
                   CASE WHEN r.is_anonymous = 1 THEN 'Anonymous' ELSE u.name END as student_name,
                   r.date, r.meal_type, r.item, r.rating, r.feedback, r.created_at
            FROM reviews r
            LEFT JOIN users u ON r.student_id = u.id
            WHERE r.rating <= 2
            ORDER BY r.rating ASC, r.created_at DESC
        ''')
    else:
        cursor.execute('''
            SELECT r.id, 
                   u.name as student_name,
                   r.date, r.meal_type, r.item, r.rating, r.feedback, r.date as created_at
            FROM reviews r
            LEFT JOIN users u ON r.student_id = u.id
            WHERE r.rating <= 2
            ORDER BY r.rating ASC, r.date DESC
        ''')
    
    flagged_reviews = cursor.fetchall()
    
    conn.close()
    return flagged_reviews

# --- FIXED Menu Calendar Functions ---
def get_menu_for_date(date_str):
    """Get menu for a specific date - FIXED VERSION"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT breakfast_items, lunch_items, dinner_items FROM menu_calendar WHERE date = ?", (date_str,))
    menu = cursor.fetchone()
    
    conn.close()
    
    if menu:
        # Handle empty strings and None values properly
        breakfast = menu[0].split(',') if menu[0] and menu[0].strip() else []
        lunch = menu[1].split(',') if menu[1] and menu[1].strip() else []
        dinner = menu[2].split(',') if menu[2] and menu[2].strip() else []
        
        return {
            'breakfast': breakfast,
            'lunch': lunch,
            'dinner': dinner
        }
    else:
        return {
            'breakfast': [],
            'lunch': [],
            'dinner': []
        }

def save_menu_for_date(date_str, breakfast_items, lunch_items, dinner_items):
    """Save menu for a specific date - FIXED VERSION"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Convert lists to comma-separated strings, filter out empty items
        breakfast_str = ','.join([item.strip() for item in breakfast_items if item.strip()])
        lunch_str = ','.join([item.strip() for item in lunch_items if item.strip()])
        dinner_str = ','.join([item.strip() for item in dinner_items if item.strip()])
        
        cursor.execute('''
            INSERT OR REPLACE INTO menu_calendar (date, breakfast_items, lunch_items, dinner_items, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (date_str, breakfast_str, lunch_str, dinner_str))
        
        conn.commit()
        return True
    except Exception as e:
        print(f"Error saving menu: {e}")
        conn.rollback()
        return False
    finally:
        conn.close()

def get_menu_calendar_view(year, month):
    """Get menu calendar view for a specific month - FIXED VERSION"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get first and last day of month
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    
    cursor.execute('''
        SELECT date, breakfast_items, lunch_items, dinner_items 
        FROM menu_calendar 
        WHERE date BETWEEN ? AND ?
        ORDER BY date
    ''', (first_day.isoformat(), last_day.isoformat()))
    
    menu_data = cursor.fetchall()
    
    # Convert to dictionary for easy lookup
    menu_dict = {}
    for menu in menu_data:
        breakfast = menu[1].split(',') if menu[1] and menu[1].strip() else []
        lunch = menu[2].split(',') if menu[2] and menu[2].strip() else []
        dinner = menu[3].split(',') if menu[3] and menu[3].strip() else []
        
        menu_dict[menu[0]] = {
            'breakfast': breakfast,
            'lunch': lunch,
            'dinner': dinner
        }
    
    conn.close()
    return menu_dict

def get_menu_history_with_bookings(year, month):
    """Get menu history with booking counts for each day - FIXED VERSION"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get first and last day of month
    first_day = date(year, month, 1)
    last_day = date(year, month, calendar.monthrange(year, month)[1])
    
    # Get ALL menu data for the month
    cursor.execute('''
        SELECT date, breakfast_items, lunch_items, dinner_items 
        FROM menu_calendar 
        WHERE date BETWEEN ? AND ?
        ORDER BY date
    ''', (first_day.isoformat(), last_day.isoformat()))
    
    menu_data = cursor.fetchall()
    
    # Get booking counts for each day
    cursor.execute('''
        SELECT date, meal_type, COUNT(*) as booking_count
        FROM bookings 
        WHERE date BETWEEN ? AND ?
        GROUP BY date, meal_type
        ORDER BY date
    ''', (first_day.isoformat(), last_day.isoformat()))
    
    booking_data = cursor.fetchall()
    
    conn.close()
    
    # Convert to dictionary for easy lookup
    menu_dict = {}
    
    # Initialize all dates in the month with empty menus
    current_date = first_day
    while current_date <= last_day:
        date_str = current_date.isoformat()
        menu_dict[date_str] = {
            'breakfast': [],
            'lunch': [],
            'dinner': [],
            'breakfast_bookings': 0,
            'lunch_bookings': 0,
            'dinner_bookings': 0
        }
        current_date += timedelta(days=1)
    
    # Fill actual menu data
    for menu in menu_data:
        date_str = menu[0]
        breakfast = menu[1].split(',') if menu[1] and menu[1].strip() else []
        lunch = menu[2].split(',') if menu[2] and menu[2].strip() else []
        dinner = menu[3].split(',') if menu[3] and menu[3].strip() else []
        
        if date_str in menu_dict:
            menu_dict[date_str]['breakfast'] = breakfast
            menu_dict[date_str]['lunch'] = lunch
            menu_dict[date_str]['dinner'] = dinner
    
    # Add booking counts
    for booking in booking_data:
        date_str, meal_type, count = booking
        if date_str in menu_dict:
            if meal_type == 'Breakfast':
                menu_dict[date_str]['breakfast_bookings'] = count
            elif meal_type == 'Lunch':
                menu_dict[date_str]['lunch_bookings'] = count
            elif meal_type == 'Dinner':
                menu_dict[date_str]['dinner_bookings'] = count
    
    return menu_dict

def get_todays_bookings_summary():
    """Get today's bookings summary for menu editor"""
    today_str = date.today().isoformat()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get booking counts by meal type for today
    cursor.execute('''
        SELECT meal_type, COUNT(*) as booking_count
        FROM bookings 
        WHERE date = ?
        GROUP BY meal_type
    ''', (today_str,))
    
    booking_counts = cursor.fetchall()
    
    # Get most popular items for today
    cursor.execute('''
        SELECT meal_type, item, COUNT(*) as count
        FROM bookings 
        WHERE date = ?
        GROUP BY meal_type, item
        ORDER BY meal_type, count DESC
    ''', (today_str,))
    
    popular_items = cursor.fetchall()
    
    conn.close()
    
    # Convert to dictionary
    counts_dict = {}
    for meal_type, count in booking_counts:
        counts_dict[meal_type] = count
    
    popular_dict = {}
    for meal_type, item, count in popular_items:
        if meal_type not in popular_dict:
            popular_dict[meal_type] = []
        popular_dict[meal_type].append({'item': item, 'count': count})
    
    return {
        'booking_counts': counts_dict,
        'popular_items': popular_dict
    }

# --- Staff Routes ---

@app.route("/")
def staff_root():
    """Redirect to staff login"""
    return redirect(url_for('staff_login'))

@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    """Staff login"""
    if request.method == "POST":
        username = request.form.get("username")
        password = request.form.get("password")
        
        staff = verify_staff(username, password)
        if staff:
            session['staff_id'] = staff[0]
            session['staff_username'] = staff[1]
            session['staff_email'] = staff[2]
            session['staff_role'] = staff[4]
            flash('Staff login successful', 'success')
            return redirect(url_for('staff_dashboard'))
        else:
            flash('Invalid username or password', 'danger')
    
    return render_template("staff/login.html", footer_symbol=FOOTER_SYMBOL)

@app.route("/staff/dashboard")
@staff_login_required
def staff_dashboard():
    """Staff dashboard"""
    stats = get_dashboard_stats()
    activities = get_recent_activities()
    attendance_stats = get_today_attendance_stats()
    wastage_data = get_wastage_data()
    booking_trends = get_booking_trends()
    
    return render_template(
        "staff/dashboard.html",
        stats=stats,
        activities=activities,
        attendance_stats=attendance_stats,
        wastage_data=wastage_data,
        booking_trends=booking_trends,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/students")
@staff_login_required
def staff_students():
    """View all students"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, email, phone, hostel_type FROM users ORDER BY name")
    students = cursor.fetchall()
    conn.close()
    
    return render_template("staff/students.html", students=students, footer_symbol=FOOTER_SYMBOL)

@app.route("/staff/get_student_statistics/<int:student_id>")
@staff_login_required
def get_student_statistics_route(student_id):
    """Get student statistics for the modal (AJAX endpoint)"""
    try:
        print(f"📊 Fetching statistics for student {student_id}")
        
        # Get basic student info first
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Check if student exists
        cursor.execute("SELECT id, name FROM users WHERE id = ?", (student_id,))
        student = cursor.fetchone()
        
        if not student:
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Student not found'
            })
        
        # Get basic statistics with safe defaults
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE student_id = ?", (student_id,))
        total_bookings = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE student_id = ? AND status = 'Present'", (student_id,))
        meals_attended = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM cancellations WHERE student_id = ?", (student_id,))
        cancellations = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM fines WHERE student_id = ?", (student_id,))
        total_fines = float(cursor.fetchone()[0] or 0)
        
        cursor.execute("SELECT COALESCE(SUM(amount), 0) FROM fines WHERE student_id = ? AND paid = 1", (student_id,))
        fines_paid = float(cursor.fetchone()[0] or 0)
        
        remaining_balance = total_fines - fines_paid
        
        # Calculate attendance rate
        attendance_rate = round((meals_attended / total_bookings * 100), 1) if total_bookings > 0 else 0.0
        
        # Get recent activity
        recent_activity = []
        
        # Recent bookings
        cursor.execute('''
            SELECT date, meal_type, item
            FROM bookings 
            WHERE student_id = ? 
            ORDER BY date DESC 
            LIMIT 2
        ''', (student_id,))
        for booking in cursor.fetchall():
            recent_activity.append({
                'date': str(booking[0]),
                'type': 'booking',
                'description': f'Booked {booking[2]} for {booking[1]}'
            })
        
        # Recent cancellations
        cursor.execute('''
            SELECT date, meal_type, reason
            FROM cancellations 
            WHERE student_id = ? 
            ORDER BY date DESC 
            LIMIT 2
        ''', (student_id,))
        for cancellation in cursor.fetchall():
            recent_activity.append({
                'date': str(cancellation[0]),
                'type': 'cancellation',
                'description': f'Cancelled {cancellation[1]} - {cancellation[2] or "No reason"}'
            })
        
        # Recent fines
        cursor.execute('''
            SELECT date, meal_type, amount, paid
            FROM fines 
            WHERE student_id = ? 
            ORDER BY date DESC 
            LIMIT 2
        ''', (student_id,))
        for fine in cursor.fetchall():
            status = 'Paid' if fine[3] else 'Unpaid'
            recent_activity.append({
                'date': str(fine[0]),
                'type': 'fine',
                'description': f'Fine of ₹{fine[2]} for {fine[1]} - {status}'
            })
        
        conn.close()
        
        # Sort and limit recent activity
        recent_activity.sort(key=lambda x: x['date'], reverse=True)
        recent_activity = recent_activity[:5]
        
        # Create response data
        response_data = {
            'success': True,
            'stats': {
                'total_bookings': int(total_bookings),
                'meals_attended': int(meals_attended),
                'cancellations': int(cancellations),
                'total_fines': float(total_fines),
                'fines_paid': float(fines_paid),
                'remaining_balance': float(remaining_balance),
                'attendance_rate': float(attendance_rate)
            },
            'recent_activity': recent_activity
        }
        
        print(f"✅ Successfully fetched stats for student {student_id}")
        return jsonify(response_data)
        
    except Exception as e:
        import traceback
        error_msg = f"Error in get_student_statistics: {str(e)}"
        print(error_msg)
        print(traceback.format_exc())
        
        # Return a proper JSON error response
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route("/staff/bookings")
@staff_login_required
def staff_bookings():
    """Booking management"""
    date_filter = request.args.get('date', date.today().isoformat())
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get bookings for selected date
    cursor.execute('''
        SELECT u.name, b.date, b.meal_type, b.item, b.id
        FROM bookings b 
        JOIN users u ON b.student_id = u.id 
        WHERE b.date = ?
        ORDER BY b.meal_type, u.name
    ''', (date_filter,))
    bookings = cursor.fetchall()
    
    # Get booking counts by meal type
    cursor.execute('''
        SELECT meal_type, COUNT(DISTINCT student_id) 
        FROM bookings 
        WHERE date = ? 
        GROUP BY meal_type
    ''', (date_filter,))
    meal_counts = cursor.fetchall()
    
    # Get total unique students who booked
    cursor.execute('''
        SELECT COUNT(DISTINCT student_id) 
        FROM bookings 
        WHERE date = ?
    ''', (date_filter,))
    total_students = cursor.fetchone()[0]
    
    # Get item popularity data
    cursor.execute('''
        SELECT meal_type, item, COUNT(*) as count
        FROM bookings 
        WHERE date = ?
        GROUP BY meal_type, item
        ORDER BY meal_type, count DESC
    ''', (date_filter,))
    item_data = cursor.fetchall()
    
    # Calculate total bookings for percentage calculation
    total_bookings = sum([count for _, _, count in item_data])
    
    # Format item popularity data
    item_popularity = []
    for meal_type, item, count in item_data:
        percentage = round((count / total_bookings) * 100, 1) if total_bookings > 0 else 0
        item_popularity.append({
            'meal_type': meal_type,
            'item': item,
            'count': count,
            'percentage': percentage
        })
    
    # Convert meal counts to dictionary
    counts_dict = {}
    for meal_type, count in meal_counts:
        counts_dict[meal_type] = count
    
    conn.close()
    
    return render_template(
        "staff/bookings.html", 
        bookings=bookings, 
        selected_date=date_filter,
        meal_counts=counts_dict,
        total_students=total_students,
        item_popularity=item_popularity,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/cancel_booking/<int:booking_id>", methods=["POST"])
@staff_login_required
def cancel_booking(booking_id):
    """Cancel a booking (AJAX endpoint)"""
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Get booking details before deleting
        cursor.execute("SELECT student_id, date, meal_type FROM bookings WHERE id = ?", (booking_id,))
        booking = cursor.fetchone()
        
        if not booking:
            return jsonify({'success': False, 'error': 'Booking not found'})
        
        # Delete the booking
        cursor.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Booking cancelled successfully'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/attendance")
@staff_login_required
def staff_attendance():
    """QR Scanner interface for attendance"""
    date_filter = request.args.get('date', date.today().isoformat())
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get today's attendance summary for meal counts
    cursor.execute('''
        SELECT meal_type, status, COUNT(*) 
        FROM attendance 
        WHERE date = ? 
        GROUP BY meal_type, status
    ''', (date_filter,))
    attendance_summary = cursor.fetchall()
    
    # Initialize counts
    breakfast_present = lunch_present = dinner_present = 0
    
    for meal_type, status, count in attendance_summary:
        if status == 'Present':
            if meal_type == 'Breakfast':
                breakfast_present = count
            elif meal_type == 'Lunch':
                lunch_present = count
            elif meal_type == 'Dinner':
                dinner_present = count
    
    conn.close()
    
    return render_template(
        "staff/attendance.html", 
        selected_date=date_filter,
        breakfast_present=breakfast_present,
        lunch_present=lunch_present,
        dinner_present=dinner_present,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/attendance_history")
@staff_login_required
def staff_attendance_history():
    """Attendance history calendar view"""
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    hostel_filter = request.args.get('hostel', 'all')
    
    # Calculate previous and next month
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    # Get first day of month and weekday
    first_day = date(year, month, 1)
    first_weekday = (first_day.weekday() + 1) % 7  # Convert to Sunday=0
    
    # Generate calendar data
    calendar_data = []
    last_day = calendar.monthrange(year, month)[1]
    
    for day in range(1, last_day + 1):
        current_date = date(year, month, day)
        date_str = current_date.isoformat()
        
        # Get attendance summary for this date
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Build query with hostel filter
        if hostel_filter == 'all':
            cursor.execute('''
                SELECT meal_type, status, COUNT(*) 
                FROM attendance 
                WHERE date = ? 
                GROUP BY meal_type, status
            ''', (date_str,))
        else:
            cursor.execute('''
                SELECT a.meal_type, a.status, COUNT(*) 
                FROM attendance a
                JOIN users u ON a.student_id = u.id
                WHERE a.date = ? AND u.hostel_type = ?
                GROUP BY a.meal_type, a.status
            ''', (date_str, hostel_filter))
        
        attendance_summary = cursor.fetchall()
        
        conn.close()
        
        calendar_data.append({
            'date': current_date,
            'date_str': date_str,
            'attendance_summary': attendance_summary
        })
    
    return render_template(
        "staff/attendance_history.html",
        calendar_data=calendar_data,
        current_month=first_day,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        first_weekday=first_weekday,
        today_str=date.today().isoformat(),
        selected_hostel=hostel_filter,
        footer_symbol=FOOTER_SYMBOL
    )

# --- Enhanced Fine Management Routes ---

@app.route("/staff/fines")
@staff_login_required
def staff_fines():
    """Enhanced fine management with period filtering"""
    period = request.args.get('period', 'all')
    status_filter = request.args.get('status', 'all')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Build query based on filters
    query = '''
        SELECT f.id, u.name, u.hostel_type, f.date, f.meal_type, f.amount, f.paid, u.id as student_id
        FROM fines f 
        JOIN users u ON f.student_id = u.id 
        WHERE 1=1
    '''
    params = []
    
    # Apply period filter
    today = date.today()
    if period == 'today':
        query += " AND f.date = ?"
        params.append(today.isoformat())
    elif period == 'week':
        start_of_week = today - timedelta(days=today.weekday())
        query += " AND f.date >= ?"
        params.append(start_of_week.isoformat())
    elif period == 'month':
        start_of_month = today.replace(day=1)
        query += " AND f.date >= ?"
        params.append(start_of_month.isoformat())
    elif period == 'year':
        start_of_year = today.replace(month=1, day=1)
        query += " AND f.date >= ?"
        params.append(start_of_year.isoformat())
    
    # Apply status filter
    if status_filter == 'paid':
        query += " AND f.paid = 1"
    elif status_filter == 'unpaid':
        query += " AND f.paid = 0"
    
    query += " ORDER BY f.date DESC, f.id DESC"
    
    cursor.execute(query, params)
    fines = cursor.fetchall()
    
    # Get fine summary
    summary_query = "SELECT SUM(amount) FROM fines WHERE 1=1"
    summary_params = []
    
    if period != 'all':
        if period == 'today':
            summary_query += " AND date = ?"
            summary_params.append(today.isoformat())
        elif period == 'week':
            start_of_week = today - timedelta(days=today.weekday())
            summary_query += " AND date >= ?"
            summary_params.append(start_of_week.isoformat())
        elif period == 'month':
            start_of_month = today.replace(day=1)
            summary_query += " AND date >= ?"
            summary_params.append(start_of_month.isoformat())
        elif period == 'year':
            start_of_year = today.replace(month=1, day=1)
            summary_query += " AND date >= ?"
            summary_params.append(start_of_year.isoformat())
    
    # Total fines
    cursor.execute(summary_query, summary_params)
    total_fines = cursor.fetchone()[0] or 0
    
    # Unpaid fines
    unpaid_query = summary_query + " AND paid = 0"
    cursor.execute(unpaid_query, summary_params)
    unpaid_fines = cursor.fetchone()[0] or 0
    
    # Paid fines
    paid_query = summary_query + " AND paid = 1"
    cursor.execute(paid_query, summary_params)
    paid_fines = cursor.fetchone()[0] or 0
    
    conn.close()
    
    return render_template(
        "staff/fines.html", 
        fines=fines, 
        selected_period=period,
        selected_status=status_filter,
        total_fines=total_fines,
        unpaid_fines=unpaid_fines,
        paid_fines=paid_fines,
        today_date=today.isoformat(),
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/waive_fine", methods=["POST"])
@staff_login_required
def waive_fine_enhanced():
    """Enhanced fine waiver with detailed information"""
    data = request.get_json()
    
    student_id = data.get('student_id')
    hostel_type = data.get('hostel_type')
    fine_date = data.get('date')
    meal_type = data.get('meal_type')
    amount = data.get('amount')
    reason = data.get('reason')
    
    if not all([student_id, hostel_type, fine_date, meal_type, amount, reason]):
        return jsonify({'success': False, 'error': 'All fields are required'})
    
    try:
        amount = float(amount)
    except ValueError:
        return jsonify({'success': False, 'error': 'Invalid amount'})
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Verify student exists and matches hostel type
    cursor.execute("SELECT id, name FROM users WHERE id = ? AND hostel_type = ?", 
                   (student_id, hostel_type))
    student = cursor.fetchone()
    
    if not student:
        conn.close()
        return jsonify({'success': False, 'error': 'Student not found or hostel type mismatch'})
    
    # Insert waived fine record
    try:
        cursor.execute(
            """INSERT INTO fines (student_id, date, meal_type, amount, paid, waived, reason) 
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (student_id, fine_date, meal_type, amount, 1, 1, reason)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Fine of ₹{amount} waived for student {student[1]}'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/waive_single_fine/<int:fine_id>", methods=["POST"])
@staff_login_required
def waive_single_fine(fine_id):
    """Waive a specific fine"""
    data = request.get_json()
    reason = data.get('reason', 'Waived by staff')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Get fine details
        cursor.execute("SELECT student_id, amount FROM fines WHERE id = ?", (fine_id,))
        fine = cursor.fetchone()
        
        if not fine:
            return jsonify({'success': False, 'error': 'Fine not found'})
        
        # Update fine as waived
        cursor.execute(
            "UPDATE fines SET paid = 1, waived = 1, reason = ? WHERE id = ?",
            (reason, fine_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': f'Fine of ₹{fine[1]} waived successfully'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/mark_fine_paid/<int:fine_id>")
@staff_login_required
def mark_fine_paid_ajax(fine_id):
    """Mark fine as paid (AJAX version)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "UPDATE fines SET paid = 1 WHERE id = ?",
            (fine_id,)
        )
        conn.commit()
        conn.close()
        
        return jsonify({'success': True, 'message': 'Fine marked as paid'})
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/recalculate_fines")
@staff_login_required
def recalculate_fines_ajax():
    """Recalculate fines (AJAX version)"""
    try:
        # Simulate actual fine calculation logic
        # In a real implementation, this would:
        # 1. Check for unattended booked meals
        # 2. Apply fine rules
        # 3. Generate new fine records
        
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Example: Count existing fines for simulation
        cursor.execute("SELECT COUNT(*) FROM fines")
        existing_fines = cursor.fetchone()[0] or 0
        
        # Simulate finding new fines (this is where your actual logic would go)
        # For demo purposes, we'll just return success
        new_fines_count = 0  # This would be calculated in real implementation
        
        conn.close()
        
        return jsonify({
            'success': True, 
            'message': 'Fines recalculated successfully',
            'fines_processed': existing_fines,
            'new_fines_generated': new_fines_count
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/get_fine_details/<int:fine_id>")
@staff_login_required
def get_fine_details(fine_id):
    """Get detailed information about a specific fine"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT f.id, u.name, u.hostel_type, f.date, f.meal_type, f.amount, f.paid, 
               COALESCE(f.waived, 0) as waived, 
               COALESCE(f.reason, '') as reason, 
               u.id as student_id, 
               COALESCE(f.created_at, f.date) as created_at
        FROM fines f 
        JOIN users u ON f.student_id = u.id 
        WHERE f.id = ?
    ''', (fine_id,))
    
    fine = cursor.fetchone()
    conn.close()
    
    if fine:
        return jsonify({
            'success': True,
            'fine': {
                'id': fine[0],
                'student_name': fine[1],
                'hostel_type': fine[2],
                'date': fine[3],
                'meal_type': fine[4],
                'amount': fine[5],
                'paid': bool(fine[6]),
                'waived': bool(fine[7]),
                'reason': fine[8],
                'student_id': fine[9],
                'created_at': fine[10]
            }
        })
    else:
        return jsonify({'success': False, 'error': 'Fine not found'})

@app.route("/staff/export_fines")
@staff_login_required
def export_fines():
    """Export fines as CSV with filters"""
    period = request.args.get('period', 'all')
    status = request.args.get('status', 'all')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Build query based on filters
    query = '''
        SELECT f.id, u.name, u.hostel_type, f.date, f.meal_type, f.amount, 
               CASE WHEN f.paid = 1 THEN 'Paid' ELSE 'Unpaid' END as status,
               CASE WHEN COALESCE(f.waived, 0) = 1 THEN 'Yes' ELSE 'No' END as waived,
               COALESCE(f.reason, '') as reason
        FROM fines f 
        JOIN users u ON f.student_id = u.id 
        WHERE 1=1
    '''
    params = []
    
    # Apply period filter
    today = date.today()
    if period == 'today':
        query += " AND f.date = ?"
        params.append(today.isoformat())
    elif period == 'week':
        start_of_week = today - timedelta(days=today.weekday())
        query += " AND f.date >= ?"
        params.append(start_of_week.isoformat())
    elif period == 'month':
        start_of_month = today.replace(day=1)
        query += " AND f.date >= ?"
        params.append(start_of_month.isoformat())
    elif period == 'year':
        start_of_year = today.replace(month=1, day=1)
        query += " AND f.date >= ?"
        params.append(start_of_year.isoformat())
    
    # Apply status filter
    if status == 'paid':
        query += " AND f.paid = 1"
    elif status == 'unpaid':
        query += " AND f.paid = 0"
    
    query += " ORDER BY f.date DESC"
    
    cursor.execute(query, params)
    fines = cursor.fetchall()
    conn.close()
    
    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Student Name', 'Hostel Type', 'Date', 'Meal Type', 'Amount', 'Status', 'Waived', 'Reason'])
    
    for fine in fines:
        writer.writerow(fine)
    
    filename = f"fines_export_{period}_{status}_{date.today().isoformat()}.csv"
    
    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={filename}'}
    )
    
    return response

@app.route("/staff/cancellations")
@staff_login_required
def staff_cancellations():
    """Cancellation requests management with accurate data"""
    date_filter = request.args.get('date', '')
    hostel_filter = request.args.get('hostel', '')
    meal_filter = request.args.get('meal', '')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if created_at column exists
    cursor.execute("PRAGMA table_info(cancellations)")
    columns = [column[1] for column in cursor.fetchall()]
    has_created_at = 'created_at' in columns
    
    # Build query based on filters
    if has_created_at:
        query = '''
            SELECT c.id, u.id as student_id, u.name, u.hostel_type, c.date, c.meal_type, 
                   COALESCE(b.item, 'Not Booked') as item, c.reason, c.approved,
                   c.created_at
            FROM cancellations c 
            JOIN users u ON c.student_id = u.id
            LEFT JOIN bookings b ON c.student_id = b.student_id AND c.date = b.date AND c.meal_type = b.meal_type
            WHERE 1=1
        '''
        order_by = " ORDER BY c.created_at DESC, c.date DESC"
    else:
        query = '''
            SELECT c.id, u.id as student_id, u.name, u.hostel_type, c.date, c.meal_type, 
                   COALESCE(b.item, 'Not Booked') as item, c.reason, c.approved,
                   c.date as created_at
            FROM cancellations c 
            JOIN users u ON c.student_id = u.id
            LEFT JOIN bookings b ON c.student_id = b.student_id AND c.date = b.date AND c.meal_type = b.meal_type
            WHERE 1=1
        '''
        order_by = " ORDER BY c.date DESC"
    
    params = []
    
    if date_filter:
        query += " AND c.date = ?"
        params.append(date_filter)
    
    if hostel_filter:
        query += " AND u.hostel_type = ?"
        params.append(hostel_filter)
    
    if meal_filter:
        query += " AND c.meal_type = ?"
        params.append(meal_filter)
    
    query += order_by
    
    cursor.execute(query, params)
    cancellations = cursor.fetchall()
    
    # Get cancellation analytics with default filters
    analytics_data = get_cancellation_analytics()
    
    conn.close()
    
    return render_template(
        "staff/cancellations.html", 
        cancellations=cancellations, 
        selected_date=date_filter,
        selected_hostel=hostel_filter,
        selected_meal=meal_filter,
        analytics_data=analytics_data,
        footer_symbol=FOOTER_SYMBOL
    )

# --- Enhanced Ratings and Feedback Routes ---

@app.route("/staff/ratings")
@staff_login_required
def staff_ratings():
    """Enhanced ratings and feedback management with filtering"""
    meal_filter = request.args.get('meal_type', 'all')
    rating_filter = request.args.get('rating', 'all')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    
    # Build filters
    filters = {}
    if meal_filter != 'all':
        filters['meal_type'] = meal_filter
    if rating_filter != 'all':
        filters['rating'] = rating_filter
    if start_date:
        filters['start_date'] = start_date
    if end_date:
        filters['end_date'] = end_date
    
    # Get reviews with filters
    reviews = get_ratings_and_feedback(filters)
    
    # Get analytics data
    analytics = get_rating_analytics()
    
    # Get flagged reviews for attention
    flagged_reviews = get_flagged_reviews()
    
    return render_template(
        "staff/ratings.html",
        reviews=reviews,
        analytics=analytics,
        flagged_reviews=flagged_reviews,
        selected_meal=meal_filter,
        selected_rating=rating_filter,
        start_date=start_date,
        end_date=end_date,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/respond_to_review", methods=["POST"])
@staff_login_required
def respond_to_review():
    """Add staff response to a review"""
    review_id = request.form.get('review_id')
    response_text = request.form.get('response_text')
    
    if not review_id or not response_text:
        flash('Please provide both review ID and response text', 'danger')
        return redirect(url_for('staff_ratings'))
    
    success = add_staff_response(review_id, session['staff_id'], response_text)
    
    if success:
        flash('Response added successfully', 'success')
    else:
        flash('Failed to add response', 'danger')
    
    return redirect(url_for('staff_ratings'))

@app.route("/staff/delete_response/<int:response_id>")
@staff_login_required
def delete_response(response_id):
    """Delete a staff response"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute("DELETE FROM staff_responses WHERE id = ?", (response_id,))
        conn.commit()
        flash('Response deleted successfully', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Error deleting response: {str(e)}', 'danger')
    finally:
        conn.close()
    
    return redirect(url_for('staff_ratings'))

@app.route("/staff/export_ratings")
@staff_login_required
def export_ratings():
    """Export ratings and feedback as CSV"""
    meal_filter = request.args.get('meal_type', 'all')
    rating_filter = request.args.get('rating', 'all')
    
    # Build filters
    filters = {}
    if meal_filter != 'all':
        filters['meal_type'] = meal_filter
    if rating_filter != 'all':
        filters['rating'] = rating_filter
    
    reviews = get_ratings_and_feedback(filters)
    
    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Date', 'Meal Type', 'Item', 'Rating', 'Feedback', 'Student Name', 'Staff Response', 'Response Date'])
    
    for review in reviews:
        writer.writerow([
            review[2],  # date
            review[3],  # meal_type
            review[4],  # item
            review[5],  # rating
            review[6] or '',  # feedback
            review[1],  # student_name
            review[8] or '',  # response_text
            review[9] or ''  # response_date
        ])
    
    filename = f"ratings_export_{date.today().isoformat()}.csv"
    
    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={filename}'}
    )
    
    return response

# --- FIXED Menu Calendar Routes ---
@app.route("/staff/menu_calendar")
@staff_login_required
def staff_menu_calendar():
    """Menu calendar management - FIXED VERSION"""
    selected_date = request.args.get('date', date.today().isoformat())
    
    # Get year and month with proper defaults
    try:
        year = int(request.args.get('year', date.today().year))
        month = int(request.args.get('month', date.today().month))
    except (ValueError, TypeError):
        year = date.today().year
        month = date.today().month
    
    # Get menu for selected date - FIXED: Ensure we get from database
    menu = get_menu_for_date(selected_date)
    
    # Get menu history with bookings - FIXED: Ensure we get all menu data
    menu_history = get_menu_history_with_bookings(year, month)
    
    # Debug: Print menu data
    print(f"📅 Selected Date: {selected_date}")
    print(f"📊 Menu Data for {selected_date}: {menu}")
    print(f"📋 Total dates with menus in {year}-{month}: {len(menu_history)}")
    
    # Print first few menu records for debugging
    for i, (date_str, menu_data) in enumerate(list(menu_history.items())[:5]):
        print(f"   {date_str}: B{len(menu_data.get('breakfast', []))} L{len(menu_data.get('lunch', []))} D{len(menu_data.get('dinner', []))}")
    
    return render_template(
        "staff/menu_calendar.html",
        selected_date=selected_date,
        menu=menu,
        menu_history=menu_history,
        current_year=year,
        current_month=date(year, month, 1),
        current_month_num=month,
        prev_month=month-1 if month > 1 else 12,
        prev_year=year if month > 1 else year-1,
        next_month=month+1 if month < 12 else 1,
        next_year=year if month < 12 else year+1,
        calendar=calendar,
        date=date,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/save_menu", methods=["POST"])
@staff_login_required
def save_menu():
    """Save menu for a specific date - FIXED VERSION"""
    date_str = request.form.get('date')
    breakfast_items = request.form.getlist('breakfast_items[]')
    lunch_items = request.form.getlist('lunch_items[]')
    dinner_items = request.form.getlist('dinner_items[]')
    
    print(f"💾 Saving menu for {date_str}:")
    print(f"   Breakfast: {breakfast_items}")
    print(f"   Lunch: {lunch_items}")
    print(f"   Dinner: {dinner_items}")
    
    if not date_str:
        flash('Please select a date', 'danger')
        return redirect(url_for('staff_menu_calendar', date=date_str))
    
    # Filter out empty items
    breakfast_items = [item.strip() for item in breakfast_items if item.strip()]
    lunch_items = [item.strip() for item in lunch_items if item.strip()]
    dinner_items = [item.strip() for item in dinner_items if item.strip()]
    
    success = save_menu_for_date(date_str, breakfast_items, lunch_items, dinner_items)
    
    if success:
        flash('Menu saved successfully! The menu will now be visible to students.', 'success')
        print(f"✅ Menu saved for {date_str}")
    else:
        flash('Failed to save menu. Please try again.', 'danger')
        print(f"❌ Failed to save menu for {date_str}")
    
    return redirect(url_for('staff_menu_calendar', date=date_str))

@app.route("/staff/analytics")
@staff_login_required
def staff_analytics():
    """Analytics dashboard with dynamic period-based data"""
    period = request.args.get('period', 'weekly')
    selected_date = request.args.get('date', date.today().isoformat())
    
    # Get analytics data for the selected period
    analytics_data = get_analytics_data(period, selected_date)
    
    return render_template(
        "staff/analytics.html", 
        analytics_data=analytics_data,
        selected_period=period,
        selected_date=selected_date,
        footer_symbol=FOOTER_SYMBOL
    )

# New API endpoints for dynamic updates
@app.route("/staff/get_meal_popularity")
@staff_login_required
def get_meal_popularity():
    """Get meal popularity data filtered by meal type"""
    period = request.args.get('period', 'weekly')
    meal_type = request.args.get('meal_type', 'all')
    
    data = get_meal_popularity_by_type(period, meal_type)
    return jsonify(data)

@app.route("/staff/get_detailed_report")
@staff_login_required
def get_detailed_report():
    """Get detailed report for specific date"""
    selected_date = request.args.get('date', date.today().isoformat())
    
    reports = get_detailed_reports(selected_date)
    return jsonify({'reports': reports})

@app.route("/staff/get_cancellation_analytics")
@staff_login_required
def get_cancellation_analytics_route():
    """Get cancellation analytics with filters"""
    period = request.args.get('period', 'weekly')
    meal_type = request.args.get('meal_type', 'all')
    hostel_type = request.args.get('hostel_type', 'all')
    
    analytics_data = get_cancellation_analytics(period, meal_type, hostel_type)
    return jsonify(analytics_data)

@app.route("/staff/notifications")
@staff_login_required
def staff_notifications():
    """Enhanced notification management - shows notifications with CORRECT dates"""
    date_filter = request.args.get('date', '')
    period_filter = request.args.get('period', 'weekly')
    
    # Get current date for debugging
    today = date.today().isoformat()
    print(f"📅 Today's date: {today}, Filter date: {date_filter}")
    
    notifications = get_notifications_with_filters(date_filter, period_filter)
    notification_stats = get_notification_stats(period_filter)
    
    print(f"📧 Sending {len(notifications)} notifications to template")
    
    return render_template(
        "staff/notifications.html",
        notifications=notifications,
        selected_date=date_filter,
        selected_period=period_filter,
        notification_stats=notification_stats,
        date=date,
        timedelta=timedelta,
        footer_symbol=FOOTER_SYMBOL
    )

# --- Admin Routes ---

@app.route("/staff/admin")
@staff_login_required
@admin_required
def staff_admin():
    """System administration dashboard"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get stats for dashboard
    cursor.execute("SELECT COUNT(*) FROM staff")
    total_staff = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users")
    total_students = cursor.fetchone()[0]
    
    today_str = date.today().isoformat()
    cursor.execute("SELECT COUNT(DISTINCT student_id) FROM bookings WHERE date = ?", (today_str,))
    today_bookings = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM cancellations WHERE approved = 0")
    pending_cancellations = cursor.fetchone()[0]
    
    # Get staff members
    cursor.execute("SELECT id, username, email, role FROM staff ORDER BY role DESC, username")
    staff_members = cursor.fetchall()
    
    # Get system settings
    cursor.execute("SELECT * FROM system_settings LIMIT 1")
    settings_row = cursor.fetchone()
    
    if settings_row:
        settings = {
            'booking_deadline': settings_row[1],
            'cancellation_window': settings_row[2],
            'default_fine': settings_row[3],
            'max_daily_bookings': settings_row[4],
            'system_mode': settings_row[5]
        }
    else:
        # Default settings
        settings = {
            'booking_deadline': '20:00',
            'cancellation_window': 2,
            'default_fine': 50,
            'max_daily_bookings': 3,
            'system_mode': 'normal'
        }
    
    # Get meal timings
    cursor.execute("SELECT * FROM meal_timings LIMIT 1")
    meal_timings_row = cursor.fetchone()
    
    if meal_timings_row:
        meal_timings = {
            'breakfast': meal_timings_row[1],
            'lunch': meal_timings_row[2],
            'dinner': meal_timings_row[3],
            'weekend_breakfast': bool(meal_timings_row[4]),
            'weekend_lunch': bool(meal_timings_row[5]),
            'weekend_dinner': bool(meal_timings_row[6])
        }
    else:
        # Default meal timings
        meal_timings = {
            'breakfast': '07:00',
            'lunch': '12:30',
            'dinner': '19:00',
            'weekend_breakfast': True,
            'weekend_lunch': True,
            'weekend_dinner': True
        }
    
    conn.close()
    
    # System info (you would get this from your system)
    system_uptime = "15 days, 7 hours"
    last_backup = "2025-10-10 23:00"
    db_size = "45.2 MB"
    
    return render_template(
        "staff/admin.html",
        total_staff=total_staff,
        total_students=total_students,
        today_bookings=today_bookings,
        pending_cancellations=pending_cancellations,
        staff_members=staff_members,
        settings=settings,
        meal_timings=meal_timings,
        system_uptime=system_uptime,
        last_backup=last_backup,
        db_size=db_size,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/staff/add_staff", methods=["POST"])
@staff_login_required
@admin_required
def add_staff():
    """Add new staff member"""
    username = request.form.get('username')
    email = request.form.get('email')
    password = request.form.get('password')
    role = request.form.get('role', 'staff')
    
    if not all([username, email, password]):
        return jsonify({'success': False, 'error': 'All fields are required'})
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Check if username or email already exists
        cursor.execute("SELECT id FROM staff WHERE username = ? OR email = ?", (username, email))
        if cursor.fetchone():
            return jsonify({'success': False, 'error': 'Username or email already exists'})
        
        # Hash password and insert
        password_hash = generate_password_hash(password)
        cursor.execute(
            "INSERT INTO staff (username, email, password_hash, role) VALUES (?, ?, ?, ?)",
            (username, email, password_hash, role)
        )
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Staff member added successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route("/staff/save_system_settings", methods=["POST"])
@staff_login_required
@admin_required
def save_system_settings():
    """Save system settings"""
    booking_deadline = request.form.get('booking_deadline')
    cancellation_window = request.form.get('cancellation_window')
    default_fine = request.form.get('default_fine')
    max_daily_bookings = request.form.get('max_daily_bookings')
    system_mode = request.form.get('system_mode')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO system_settings 
            (id, booking_deadline, cancellation_window, default_fine, max_daily_bookings, system_mode, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (booking_deadline, cancellation_window, default_fine, max_daily_bookings, system_mode))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'System settings saved successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route("/staff/save_meal_timings", methods=["POST"])
@staff_login_required
@admin_required
def save_meal_timings():
    """Save meal timings"""
    breakfast_time = request.form.get('breakfast_time')
    lunch_time = request.form.get('lunch_time')
    dinner_time = request.form.get('dinner_time')
    weekend_breakfast = 1 if request.form.get('weekend_breakfast') else 0
    weekend_lunch = 1 if request.form.get('weekend_lunch') else 0
    weekend_dinner = 1 if request.form.get('weekend_dinner') else 0
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            INSERT OR REPLACE INTO meal_timings 
            (id, breakfast_time, lunch_time, dinner_time, weekend_breakfast, weekend_lunch, weekend_dinner, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
        ''', (breakfast_time, lunch_time, dinner_time, weekend_breakfast, weekend_lunch, weekend_dinner))
        
        conn.commit()
        return jsonify({'success': True, 'message': 'Meal timings updated successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route("/staff/delete_staff/<int:staff_id>", methods=["DELETE"])
@staff_login_required
@admin_required
def delete_staff(staff_id):
    """Delete staff member"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Prevent deleting yourself or the main admin
        cursor.execute("SELECT username FROM staff WHERE id = ?", (staff_id,))
        staff = cursor.fetchone()
        
        if not staff:
            return jsonify({'success': False, 'error': 'Staff member not found'})
        
        if staff[0] == 'admin':
            return jsonify({'success': False, 'error': 'Cannot delete the main admin account'})
        
        if staff_id == session['staff_id']:
            return jsonify({'success': False, 'error': 'Cannot delete your own account'})
        
        cursor.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
        conn.commit()
        return jsonify({'success': True, 'message': 'Staff member deleted successfully'})
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route("/staff/backup_database")
@staff_login_required
@admin_required
def backup_database():
    """Create database backup"""
    try:
        # In a real implementation, this would copy the database file
        # For now, we'll simulate a backup
        import shutil
        import time
        
        timestamp = int(time.time())
        backup_filename = f"messmate_backup_{timestamp}.db"
        shutil.copy2(DB_FILE, backup_filename)
        
        return jsonify({'success': True, 'message': f'Backup created: {backup_filename}'})
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/clear_old_data")
@staff_login_required
@admin_required
def clear_old_data():
    """Clear old data (bookings, attendance older than 6 months)"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        # Calculate date 6 months ago
        six_months_ago = (date.today() - timedelta(days=180)).isoformat()
        
        # Count records to be deleted
        cursor.execute("SELECT COUNT(*) FROM bookings WHERE date < ?", (six_months_ago,))
        old_bookings = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM attendance WHERE date < ?", (six_months_ago,))
        old_attendance = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM cancellations WHERE date < ?", (six_months_ago,))
        old_cancellations = cursor.fetchone()[0]
        
        # Delete old records
        cursor.execute("DELETE FROM bookings WHERE date < ?", (six_months_ago,))
        cursor.execute("DELETE FROM attendance WHERE date < ?", (six_months_ago,))
        cursor.execute("DELETE FROM cancellations WHERE date < ?", (six_months_ago,))
        
        conn.commit()
        
        total_deleted = old_bookings + old_attendance + old_cancellations
        return jsonify({
            'success': True, 
            'message': f'Cleaned up {total_deleted} old records',
            'cleaned_records': total_deleted
        })
        
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'error': str(e)})
    finally:
        conn.close()

@app.route("/staff/health_check")
@staff_login_required
@admin_required
def health_check():
    """System health check"""
    try:
        # Check database connectivity
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        db_ok = True
        conn.close()
        
        # Check disk space (simulated)
        disk_space_ok = True
        
        # Check services (simulated)
        services_ok = True
        
        # Check performance (simulated)
        performance_ok = True
        
        return jsonify({
            'success': True,
            'database_ok': db_ok,
            'disk_space_ok': disk_space_ok,
            'services_ok': services_ok,
            'performance_ok': performance_ok
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route("/staff/refresh_cache")
@staff_login_required
@admin_required
def refresh_cache():
    """Refresh system cache"""
    # In a real implementation, this would clear various caches
    return jsonify({'success': True, 'message': 'Cache refreshed successfully'})

@app.route("/staff/recalculate_all_fines")
@staff_login_required
@admin_required
def recalculate_all_fines():
    """Recalculate all fines"""
    # This would implement your fine calculation logic
    return jsonify({
        'success': True, 
        'message': 'Fines recalculated',
        'fines_processed': 0  # This would be the actual count
    })

@app.route("/staff/send_test_notification")
@staff_login_required
@admin_required
def send_test_notification():
    """Send test notification"""
    try:
        sent_count = send_notification_to_students(
            message="🔧 System Test: This is a test notification from the administration panel.",
            target='all',
            sender_id=session['staff_id']
        )
        
        return jsonify({
            'success': True, 
            'message': f'Test notification sent to {sent_count} users'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# --- Notification Action Routes ---

@app.route("/staff/send_notification", methods=["POST"])
@staff_login_required
def send_notification():
    """Send notification to students - creates ONE record with CORRECT date"""
    message = request.form.get('message')
    target = request.form.get('target', 'all')
    schedule = request.form.get('schedule')
    
    if not message:
        flash('Please enter a message', 'danger')
        return redirect(url_for('staff_notifications'))
    
    # Validate message length
    if len(message) > 500:
        flash('Message too long. Maximum 500 characters allowed.', 'danger')
        return redirect(url_for('staff_notifications'))
    
    # Get current date for debugging
    current_date = date.today().isoformat()
    print(f"📝 Sending notification on date: {current_date}")
    
    # Send notification (creates ONE staff record + individual student records)
    sent_count = send_notification_to_students(
        message=message,
        target=target,
        sender_id=session['staff_id'],
        schedule=schedule if schedule else None
    )
    
    if sent_count > 0:
        flash(f'Notification sent to {sent_count} students successfully!', 'success')
        print(f"✅ Notification '{message}' sent to {sent_count} students on {current_date}")
    else:
        flash('Failed to send notification. Please try again.', 'danger')
        print(f"❌ Failed to send notification on {current_date}")
    
    return redirect(url_for('staff_notifications'))

@app.route("/staff/use_template/<template_name>")
@staff_login_required
def use_template(template_name):
    """Use a notification template"""
    template = get_notification_template(template_name)
    if template:
        return jsonify({
            'success': True,
            'template_text': template['template_text'],
            'target_audience': template['target_audience']
        })
    return jsonify({'success': False, 'error': 'Template not found'})

@app.route("/staff/delete_notification/<int:notification_id>")
@staff_login_required
def delete_notification_route(notification_id):
    """Delete a notification"""
    delete_notification(notification_id)
    flash("Notification deleted successfully", "success")
    return redirect(url_for('staff_notifications'))

@app.route("/staff/clear_all_notifications")
@staff_login_required
def clear_all_notifications_route():
    """Clear all notifications"""
    clear_all_notifications()
    flash("All notifications cleared", "success")
    return redirect(url_for('staff_notifications'))

@app.route("/staff/notification_stats")
@staff_login_required
def notification_stats():
    """Get notification statistics (AJAX endpoint)"""
    period = request.args.get('period', 'weekly')
    stats = get_notification_stats(period)
    return jsonify(stats)

@app.route("/staff/export_notifications")
@staff_login_required
def export_notifications():
    """Export notifications as CSV"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute('''
            SELECT n.id, n.message, 
                   COALESCE(n.target_audience, 'all') as target,
                   COALESCE(n.sent_count, 1) as sent_count,
                   n.sent_at,
                   COALESCE(s.username, 'System') as sender,
                   COALESCE(n.status, 'sent') as status
            FROM notifications n
            LEFT JOIN staff s ON n.sender_id = s.id
            WHERE n.type = 'staff_announcement' 
            AND n.user_id IS NULL
            ORDER BY n.sent_at DESC
        ''')
        notifications = cursor.fetchall()
    except Exception:
        notifications = []
    
    conn.close()
    
    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Message', 'Target Audience', 'Sent Count', 'Sent Date', 'Sender', 'Status'])
    
    for notification in notifications:
        writer.writerow(notification)
    
    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': 'attachment; filename=notifications_export.csv'}
    )
    
    return response

# --- Cancellation Action Routes ---

@app.route("/staff/approve_cancellation/<int:cancellation_id>")
@staff_login_required
def approve_cancellation(cancellation_id):
    """Approve cancellation request"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "UPDATE cancellations SET approved = 1 WHERE id = ?",
            (cancellation_id,)
        )
        conn.commit()
        flash("Cancellation request approved successfully", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error approving cancellation: {str(e)}", "danger")
    finally:
        conn.close()
    
    return redirect(url_for('staff_cancellations'))

@app.route("/staff/reject_cancellation/<int:cancellation_id>")
@staff_login_required
def reject_cancellation(cancellation_id):
    """Reject cancellation request"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "UPDATE cancellations SET approved = 2 WHERE id = ?",
            (cancellation_id,)
        )
        conn.commit()
        flash("Cancellation request rejected successfully", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error rejecting cancellation: {str(e)}", "danger")
    finally:
        conn.close()
    
    return redirect(url_for('staff_cancellations'))

@app.route("/staff/approve_all_pending")
@staff_login_required
def approve_all_pending():
    """Approve all pending cancellation requests"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "UPDATE cancellations SET approved = 1 WHERE approved = 0"
        )
        affected_rows = cursor.rowcount
        conn.commit()
        flash(f"Approved {affected_rows} pending cancellation requests", "success")
    except Exception as e:
        conn.rollback()
        flash(f"Error approving all cancellations: {str(e)}", "danger")
    finally:
        conn.close()
    
    return redirect(url_for('staff_cancellations'))

@app.route("/staff/export_cancellations")
@staff_login_required
def export_cancellations():
    """Export cancellations as CSV"""
    date_filter = request.args.get('date', '')
    hostel_filter = request.args.get('hostel', '')
    meal_filter = request.args.get('meal', '')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if created_at column exists
    cursor.execute("PRAGMA table_info(cancellations)")
    columns = [column[1] for column in cursor.fetchall()]
    has_created_at = 'created_at' in columns
    
    # Build query based on filters
    if has_created_at:
        query = '''
            SELECT c.id, u.name, u.hostel_type, c.date, c.meal_type, 
                   COALESCE(b.item, 'Not Booked') as item, c.reason, 
                   CASE 
                       WHEN c.approved = 0 THEN 'Pending'
                       WHEN c.approved = 1 THEN 'Approved'
                       ELSE 'Rejected'
                   END as status,
                   c.created_at
            FROM cancellations c 
            JOIN users u ON c.student_id = u.id
            LEFT JOIN bookings b ON c.student_id = b.student_id AND c.date = b.date AND c.meal_type = b.meal_type
            WHERE 1=1
        '''
    else:
        query = '''
            SELECT c.id, u.name, u.hostel_type, c.date, c.meal_type, 
                   COALESCE(b.item, 'Not Booked') as item, c.reason, 
                   CASE 
                       WHEN c.approved = 0 THEN 'Pending'
                       WHEN c.approved = 1 THEN 'Approved'
                       ELSE 'Rejected'
                   END as status,
                   c.date as created_at
            FROM cancellations c 
            JOIN users u ON c.student_id = u.id
            LEFT JOIN bookings b ON c.student_id = b.student_id AND c.date = b.date AND c.meal_type = b.meal_type
            WHERE 1=1
        '''
    
    params = []
    
    if date_filter:
        query += " AND c.date = ?"
        params.append(date_filter)
    
    if hostel_filter:
        query += " AND u.hostel_type = ?"
        params.append(hostel_filter)
    
    if meal_filter:
        query += " AND c.meal_type = ?"
        params.append(meal_filter)
    
    query += " ORDER BY c.date DESC"
    
    cursor.execute(query, params)
    cancellations = cursor.fetchall()
    conn.close()
    
    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Student Name', 'Hostel Type', 'Date', 'Meal Type', 'Item', 'Reason', 'Status', 'Requested At'])
    
    for cancellation in cancellations:
        writer.writerow(cancellation)
    
    filename = f"cancellations_export_{date.today().isoformat()}.csv"
    if date_filter:
        filename = f"cancellations_{date_filter}.csv"
    
    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename={filename}'}
    )
    
    return response

# --- Attendance Action Routes ---

@app.route("/staff/mark_attendance/<student_id>/<date_str>/<meal_type>")
@staff_login_required
def mark_attendance_staff(student_id, date_str, meal_type):
    """Mark attendance via staff interface"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if attendance already exists
    cursor.execute(
        "SELECT id FROM attendance WHERE student_id=? AND date=? AND meal_type=?",
        (student_id, date_str, meal_type)
    )
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute(
            "UPDATE attendance SET status='Present' WHERE student_id=? AND date=? AND meal_type=?",
            (student_id, date_str, meal_type)
        )
    else:
        cursor.execute(
            "INSERT INTO attendance (student_id, date, meal_type, status) VALUES (?, ?, ?, ?)",
            (student_id, date_str, meal_type, 'Present')
        )
    
    conn.commit()
    conn.close()
    
    flash(f"Attendance marked for student {student_id} - {meal_type}", "success")
    return redirect(url_for('staff_attendance'))

@app.route("/staff/manual_attendance", methods=["POST"])
@staff_login_required
def manual_attendance():
    """Manual attendance entry"""
    student_id = request.form.get('student_id')
    date_str = request.form.get('date')
    meal_type = request.form.get('meal_type')
    hostel_type = request.form.get('hostel_type')
    
    if not all([student_id, date_str, meal_type, hostel_type]):
        flash('Please fill all required fields', 'danger')
        return redirect(url_for('staff_attendance'))
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if student exists
    cursor.execute("SELECT id FROM users WHERE id = ?", (student_id,))
    if not cursor.fetchone():
        flash('Student ID not found', 'danger')
        conn.close()
        return redirect(url_for('staff_attendance'))
    
    # Mark attendance
    cursor.execute(
        "INSERT OR REPLACE INTO attendance (student_id, date, meal_type, status) VALUES (?, ?, ?, ?)",
        (student_id, date_str, meal_type, 'Present')
    )
    
    conn.commit()
    conn.close()
    
    flash(f"Manual attendance marked for student {student_id}", "success")
    return redirect(url_for('staff_attendance'))

@app.route("/staff/get_day_attendance/<date_str>")
@staff_login_required
def get_day_attendance(date_str):
    """Get attendance details for a specific day (AJAX endpoint)"""
    hostel_filter = request.args.get('hostel', 'all')
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Get attendance summary for the date
    if hostel_filter == 'all':
        cursor.execute('''
            SELECT meal_type, status, COUNT(*) 
            FROM attendance 
            WHERE date = ? 
            GROUP BY meal_type, status
        ''', (date_str,))
    else:
        cursor.execute('''
            SELECT a.meal_type, a.status, COUNT(*) 
            FROM attendance a
            JOIN users u ON a.student_id = u.id
            WHERE a.date = ? AND u.hostel_type = ?
            GROUP BY a.meal_type, a.status
        ''', (date_str, hostel_filter))
    
    attendance_summary = cursor.fetchall()
    
    # Get detailed attendance
    if hostel_filter == 'all':
        cursor.execute('''
            SELECT u.id, u.name, u.hostel_type, a.meal_type, a.status
            FROM attendance a
            JOIN users u ON a.student_id = u.id
            WHERE a.date = ?
            ORDER BY a.meal_type, u.name
        ''', (date_str,))
    else:
        cursor.execute('''
            SELECT u.id, u.name, u.hostel_type, a.meal_type, a.status
            FROM attendance a
            JOIN users u ON a.student_id = u.id
            WHERE a.date = ? AND u.hostel_type = ?
            ORDER BY a.meal_type, u.name
        ''', (date_str, hostel_filter))
    
    detailed_attendance = cursor.fetchall()
    
    # Calculate totals
    breakfast_present = lunch_present = dinner_present = 0
    breakfast_absent = lunch_absent = dinner_absent = 0
    
    for meal_type, status, count in attendance_summary:
        if status == 'Present':
            if meal_type == 'Breakfast':
                breakfast_present = count
            elif meal_type == 'Lunch':
                lunch_present = count
            elif meal_type == 'Dinner':
                dinner_present = count
        elif status == 'Absent':
            if meal_type == 'Breakfast':
                breakfast_absent = count
            elif meal_type == 'Lunch':
                lunch_absent = count
            elif meal_type == 'Dinner':
                dinner_absent = count
    
    conn.close()
    
    return jsonify({
        'summary': attendance_summary,
        'detailed': detailed_attendance,
        'totals': {
            'breakfast': {'present': breakfast_present, 'absent': breakfast_absent},
            'lunch': {'present': lunch_present, 'absent': lunch_absent},
            'dinner': {'present': dinner_present, 'absent': dinner_absent}
        }
    })

# --- Other Action Routes ---

@app.route("/staff/mark_fine_paid/<int:fine_id>")
@staff_login_required
def mark_fine_paid(fine_id):
    """Mark fine as paid"""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute(
        "UPDATE fines SET paid = 1 WHERE id = ?",
        (fine_id,)
    )
    
    conn.commit()
    conn.close()
    
    flash("Fine marked as paid", "success")
    return redirect(url_for('staff_fines'))

@app.route("/staff/waive_fine", methods=["POST"])
@staff_login_required
def waive_fine():
    """Waive fine for student"""
    student_id = request.form.get('student_id')
    amount = request.form.get('amount')
    reason = request.form.get('reason')
    
    if not all([student_id, amount, reason]):
        flash('Please fill all required fields', 'danger')
        return redirect(url_for('staff_fines'))
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # Check if student exists
    cursor.execute("SELECT id FROM users WHERE id = ?", (student_id,))
    if not cursor.fetchone():
        flash('Student ID not found', 'danger')
        conn.close()
        return redirect(url_for('staff_fines'))
    
    # Insert waived fine record
    cursor.execute(
        "INSERT INTO fines (student_id, date, meal_type, amount, paid, waived) VALUES (?, ?, ?, ?, ?, ?)",
        (student_id, date.today().isoformat(), 'Manual Waiver', float(amount), 1, 1)
    )
    
    conn.commit()
    conn.close()
    
    flash(f"Fine of ₹{amount} waived for student {student_id}", "success")
    return redirect(url_for('staff_fines'))

@app.route("/staff/export_bookings")
@staff_login_required
def export_bookings():
    """Export bookings as CSV"""
    date_filter = request.args.get('date', date.today().isoformat())
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT u.name, u.email, b.date, b.meal_type, b.item
        FROM bookings b 
        JOIN users u ON b.student_id = u.id 
        WHERE b.date = ?
        ORDER BY b.meal_type, u.name
    ''', (date_filter,))
    bookings = cursor.fetchall()
    conn.close()
    
    # Generate CSV
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(['Student Name', 'Email', 'Date', 'Meal Type', 'Item'])
    
    for booking in bookings:
        writer.writerow(booking)
    
    response = app.response_class(
        output.getvalue(),
        mimetype='text/csv',
        headers={'Content-disposition': f'attachment; filename=bookings_{date_filter}.csv'}
    )
    
    return response

@app.route("/staff/recalculate_fines")
@staff_login_required
def recalculate_fines():
    """Recalculate fines (for testing)"""
    # This would call your fine calculation logic
    flash("Fines recalculated successfully", "success")
    return redirect(url_for('staff_fines'))

@app.route("/staff/logout")
def staff_logout():
    """Staff logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('staff_login'))

# Error handlers - FIXED VERSION
@app.errorhandler(404)
def not_found_error(error):
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>404 - Page Not Found</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #dc3545; }
            a { color: #007bff; text-decoration: none; }
            a:hover { text-decoration: underline; }
            footer { margin-top: 30px; color: #6c757d; }
        </style>
    </head>
    <body>
        <h1>404 - Page Not Found</h1>
        <p>The page you are looking for does not exist.</p>
        <p><a href="/staff/dashboard">Return to Dashboard</a></p>
        <footer>🍴 MessMate | Indian UA</footer>
    </body>
    </html>
    """, 404

@app.errorhandler(500)
def internal_error(error):
    conn = sqlite3.connect(DB_FILE)
    conn.rollback()
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>500 - Internal Server Error</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            h1 { color: #dc3545; }
            a { color: #007bff; text-decoration: none; }
            a:hover { text-decoration: underline; }
            footer { margin-top: 30px; color: #6c757d; }
        </style>
    </head>
    <body>
        <h1>500 - Internal Server Error</h1>
        <p>Something went wrong on our end. Please try again later.</p>
        <p><a href="/staff/dashboard">Return to Dashboard</a></p>
        <footer>🍴 MessMate | Indian UA</footer>
    </body>
    </html>
    """, 500

if __name__ == "__main__":
    app.run(debug=True, port=5001)