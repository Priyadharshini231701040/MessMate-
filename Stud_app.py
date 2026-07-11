from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import sqlite3
from db import (
    init_db,
    confirm_booking,
    get_bookings_with_attendance,
    get_booking_history,
    submit_review,
    generate_qr_code,
    mark_attendance,
    calculate_daily_fines,
    get_fines,
    get_cancellations,
    reset_fines,
    create_user,
    verify_user,
    update_user_profile,
    update_user_password,
    get_user_by_email,
    get_attendance_calendar,
    add_notification,
    get_unread_notifications,
    mark_notification_as_read,
    check_booking_status,
    send_evening_reminders,
    send_fine_notifications,
    get_meal_times,
    can_cancel_meal,
    clear_meal_booking,
    get_booking_deadline,
    can_edit_booking,
    create_password_reset_token,
    verify_password_reset_token,
    update_password_with_token
)
from datetime import date, timedelta, datetime, time
from flask_mail import Mail, Message
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
from functools import wraps
import threading
import secrets
import hashlib
import os
import smtplib

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'  # Needed for flash messages and sessions

FOOTER_SYMBOL = "🍴 MessMate | Indian UA"

# Database connection lock to prevent concurrent access
db_lock = threading.Lock()

# --- Flask-Mail Configuration ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'your_email@gmail.com'  # Replace with your email
app.config['MAIL_PASSWORD'] = 'your_app_password'     # Replace with your app password
app.config['MAIL_DEFAULT_SENDER'] = 'your_email@gmail.com'
app.config['MAIL_DEBUG'] = True

try:
    mail = Mail(app)
    print("✓ Flask-Mail initialized successfully")
except Exception as e:
    print(f"✗ Flask-Mail initialization failed: {e}")
    mail = None
# --- End Mail Configuration ---

# Menu used in book.html
MENU = {
    "Breakfast": ["Idli", "Dosa", "Pongal"],
    "Lunch": ["Rice", "Dal", "Sabzi", "Chapati"],
    "Dinner": ["Roti", "Paneer", "Salad"]
}

# Meal times for cancellation policy
MEAL_TIMES = {
    "Breakfast": 8,   # 8 AM
    "Lunch": 13,      # 1 PM
    "Dinner": 20      # 8 PM
}

# Ensure DB & tables exist
init_db()

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please log in to access this page.', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Context processor to make notifications available in all templates
@app.context_processor
def inject_notifications():
    if 'user_id' in session:
        user_notifications = get_unread_notifications(session['user_id'])
        return dict(notifications=user_notifications)
    return dict(notifications=[])

# Context processor to make utility functions available in all templates
@app.context_processor
def inject_utility_functions():
    return dict(can_edit_booking=can_edit_booking, get_meal_times=get_meal_times)

# --- Scheduler for Email Reminders and Fines ---
def check_and_send_reminders():
    """Function to check for users who haven't booked tomorrow's meals and email them."""
    with db_lock:
        conn = sqlite3.connect("mess_app.db")
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, email, hostel_type FROM users")
        all_users = cursor.fetchall()
        conn.close()
    
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    
    for user_id, user_name, user_email, hostel_type in all_users:
        bookings = get_bookings_with_attendance(user_id, tomorrow_str)
        # Check if any meal is booked. If nothing is booked, send reminder.
        is_any_meal_booked = any(bookings['Breakfast']['food_items'] or
                                bookings['Lunch']['food_items'] or
                                bookings['Dinner']['food_items'])
        if not is_any_meal_booked:
            try:
                msg = Message(
                    subject='🍽 MessMate Reminder: Book Your Meals!',
                    sender=app.config['MAIL_DEFAULT_SENDER'],
                    recipients=[user_email],
                    body=f'''Hi {user_name}!

This is a reminder from MessMate. You haven't booked your meals for tomorrow ({tomorrow_str}) yet.

The booking window closes at 1 PM. Please book your meals to avoid missing out.

Book now: http://127.0.0.1:5000/book

Thank you!
The MessMate Team
'''
                )
                if mail:
                    mail.send(msg)
                    print(f"✓ Reminder email sent to {user_email}")
                else:
                    print(f"✗ Mail not configured, skipping email to {user_email}")
                
                # Add notification for user
                add_notification(
                    user_id,
                    f"You haven't booked any meals for tomorrow ({tomorrow_str}) yet. The booking window closes at 1 PM.",
                    "booking_reminder"
                )
            except Exception as e:
                print(f"✗ Error sending email to {user_email}: {e}")

# Schedule the tasks
scheduler = BackgroundScheduler()
scheduler.add_job(
    func=check_and_send_reminders,
    trigger=CronTrigger(hour=12, minute=0),  # 12:00 PM daily
    id='daily_reminder_job',
    name='Send daily booking reminders',
    replace_existing=True
)
scheduler.add_job(
    func=calculate_daily_fines,
    trigger=CronTrigger(hour=22, minute=0),  # 10:00 PM daily
    id='daily_fine_job',
    name='Calculate daily fines',
    replace_existing=True
)
scheduler.add_job(
    func=check_booking_status,
    trigger=CronTrigger(hour=12, minute=30),  # 12:30 PM daily
    id='booking_status_job',
    name='Check booking status',
    replace_existing=True
)
scheduler.add_job(
    func=send_evening_reminders,
    trigger=CronTrigger(hour=18, minute=0),  # 6:00 PM daily
    id='evening_reminder_job',
    name='Send evening reminders',
    replace_existing=True
)
scheduler.add_job(
    func=send_fine_notifications,
    trigger=CronTrigger(hour=9, minute=0),  # 9:00 AM daily
    id='fine_notification_job',
    name='Send fine notifications',
    replace_existing=True
)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

def test_email_configuration():
    """Test email configuration on startup"""
    print("\n=== Testing Email Configuration ===")
    print(f"MAIL_SERVER: {app.config['MAIL_SERVER']}")
    print(f"MAIL_PORT: {app.config['MAIL_PORT']}")
    print(f"MAIL_USE_TLS: {app.config['MAIL_USE_TLS']}")
    print(f"MAIL_USERNAME: {app.config['MAIL_USERNAME']}")
    print(f"MAIL_PASSWORD: {'*' * len(app.config['MAIL_PASSWORD']) if app.config['MAIL_PASSWORD'] else 'Not set'}")
    
    if not app.config['MAIL_USERNAME'] or app.config['MAIL_USERNAME'] == 'your_email@gmail.com':
        print("✗ MAIL_USERNAME not configured - using fallback reset links")
        return False
    
    try:
        # Test SMTP connection
        server = smtplib.SMTP(app.config['MAIL_SERVER'], app.config['MAIL_PORT'])
        server.starttls()
        server.login(app.config['MAIL_USERNAME'], app.config['MAIL_PASSWORD'])
        server.quit()
        print("✓ Email configuration test passed")
        return True
    except Exception as e:
        print(f"✗ Email configuration test failed: {e}")
        print("ℹ Using fallback reset links (links will be shown on page)")
        return False

# Test email on startup
email_configured = test_email_configuration()

# Authentication routes
@app.route("/")
def index():
    """Redirect to login or home based on authentication status"""
    if 'user_id' in session:
        return redirect(url_for('home'))
    return redirect(url_for('login'))

@app.route("/login", methods=["GET", "POST"])
def login():
    """User login"""
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        user = verify_user(email, password)
        if user:
            session['user_id'] = user[0]
            session['user_name'] = user[1]
            session['user_email'] = user[2]
            session['user_phone'] = user[3]
            session['hostel_type'] = user[4]
            flash('Login successful!', 'success')
            return redirect(url_for('home'))
        else:
            flash('Invalid email or password', 'danger')
    
    return render_template("login.html", footer_symbol=FOOTER_SYMBOL)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    """User registration"""
    if request.method == "POST":
        name = request.form.get("name")
        email = request.form.get("email")
        phone = request.form.get("phone")
        hostel_type = request.form.get("hostel_type")
        password = request.form.get("password")
        confirm_password = request.form.get("confirm_password")
        
        # Basic validation
        if password != confirm_password:
            flash('Passwords do not match', 'danger')
            return render_template("signup.html", footer_symbol=FOOTER_SYMBOL)
        
        user_id = create_user(name, email, phone, hostel_type, password)
        if user_id:
            flash('Registration successful! Please log in.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Email already exists. Please use a different email.', 'danger')
    
    return render_template("signup.html", footer_symbol=FOOTER_SYMBOL)

@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    """Handle forgot password requests"""
    if request.method == "POST":
        email = request.form.get("email")
        user = get_user_by_email(email)
        
        if user:
            # Generate reset token and send email
            token = create_password_reset_token(user[0])
            reset_url = url_for('reset_password', token=token, _external=True)
            
            # Try to send email
            email_sent = False
            if email_configured and mail:
                try:
                    msg = Message(
                        subject='🔐 MessMate - Password Reset Request',
                        sender=app.config['MAIL_DEFAULT_SENDER'],
                        recipients=[email],
                        html=f'''
                        <h3>Password Reset Request</h3>
                        <p>Hello {user[1]},</p>
                        <p>You have requested to reset your password for your MessMate account.</p>
                        <p>Click the link below to reset your password:</p>
                        <p><a href="{reset_url}" style="background-color: #007bff; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px;">Reset Password</a></p>
                        <p>This link will expire in 1 hour for security reasons.</p>
                        <p>If you didn't request this reset, please ignore this email.</p>
                        <br>
                        <p>Best regards,<br>The MessMate Team</p>
                        '''
                    )
                    mail.send(msg)
                    email_sent = True
                    flash('Password reset instructions have been sent to your email.', 'success')
                    print(f"✓ Password reset email sent to {email}")
                except Exception as e:
                    print(f"✗ Error sending email to {email}: {str(e)}")
                    email_sent = False
            
            # If email failed or not configured, show the link directly
            if not email_sent:
                flash(f'''
                <strong>Email sending failed.</strong> For development: 
                <a href="{reset_url}" class="alert-link">Click here to reset password</a>
                ''', 'warning')
        else:
            # Don't reveal whether email exists, but still show success message
            flash('If that email exists in our system, reset instructions will be sent.', 'success')
        
        return redirect(url_for('forgot_password'))
    
    return render_template("forgot_password.html", footer_symbol=FOOTER_SYMBOL, email_configured=email_configured)

@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    """Handle password reset with token"""
    # Verify token
    user_id = verify_password_reset_token(token)
    
    if not user_id:
        flash('Invalid or expired reset token.', 'danger')
        return redirect(url_for('forgot_password'))
    
    if request.method == "POST":
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")
        
        if not new_password or not confirm_password:
            flash('Please fill in all fields.', 'danger')
            return render_template("reset_password.html", token=token, footer_symbol=FOOTER_SYMBOL)
        
        if new_password != confirm_password:
            flash('Passwords do not match.', 'danger')
            return render_template("reset_password.html", token=token, footer_symbol=FOOTER_SYMBOL)
        
        if len(new_password) < 6:
            flash('Password must be at least 6 characters long.', 'danger')
            return render_template("reset_password.html", token=token, footer_symbol=FOOTER_SYMBOL)
        
        # Update password
        success = update_password_with_token(user_id, new_password, token)
        if success:
            flash('Password has been reset successfully! You can now log in with your new password.', 'success')
            return redirect(url_for('login'))
        else:
            flash('Error resetting password. Please try again.', 'danger')
    
    return render_template("reset_password.html", token=token, footer_symbol=FOOTER_SYMBOL)

@app.route("/manual-reset/<email>")
def manual_reset(email):
    """Manual reset endpoint for testing - creates a reset token and returns the link"""
    user = get_user_by_email(email)
    if user:
        token = create_password_reset_token(user[0])
        reset_url = url_for('reset_password', token=token, _external=True)
        return f'''
        <h2>Manual Reset Link for {email}</h2>
        <p>Reset URL: <a href="{reset_url}">{reset_url}</a></p>
        <p><strong>Copy this link and use it to reset your password:</strong></p>
        <input type="text" value="{reset_url}" style="width: 100%; padding: 10px; margin: 10px 0;" readonly>
        <p><a href="{reset_url}" class="btn btn-primary">Reset Password Now</a></p>
        '''
    return f'<h2>User {email} not found</h2>'

@app.route("/email-test")
def email_test():
    """Test email configuration"""
    if email_configured and mail:
        try:
            msg = Message(
                subject='Test Email from MessMate',
                sender=app.config['MAIL_DEFAULT_SENDER'],
                recipients=[app.config['MAIL_USERNAME']],
                body='This is a test email from MessMate. If you receive this, email configuration is working!'
            )
            mail.send(msg)
            return 'Test email sent successfully!'
        except Exception as e:
            return f'Failed to send test email: {str(e)}'
    else:
        return 'Email not configured properly. Check your MAIL_USERNAME and MAIL_PASSWORD settings.'

@app.route("/logout")
def logout():
    """User logout"""
    session.clear()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# Protected routes
@app.route("/home")
@login_required
def home():
    today_str = date.today().isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()

    # real bookings from DB with attendance
    todays = get_bookings_with_attendance(session['user_id'], today_str)
    tomorrows = get_bookings_with_attendance(session['user_id'], tomorrow_str)

    # Get fines and cancellations for dashboard
    student_fines = get_fines(session['user_id'])
    student_cancellations = get_cancellations(session['user_id'])
    
    # Calculate total due for fines
    total_due = sum(fine['amount'] for fine in student_fines if not fine['paid'])
    
    # Make sure QRs are available only for booked meals
    today_qr = {}
    tomorrow_qr = {}
    
    for meal in ["Breakfast", "Lunch", "Dinner"]:
        if todays[meal]['food_items']:
            today_qr[meal] = generate_qr_code(f"{session['user_id']}-{today_str}-{meal}")
        if tomorrows[meal]['food_items']:
            tomorrow_qr[meal] = generate_qr_code(f"{session['user_id']}-{tomorrow_str}-{meal}")

    # Determine gender emoji
    gender_emoji = "👩" if session.get('hostel_type') == 'Female' else "👨"

    return render_template(
        "home.html",
        bookings=todays,
        tomorrow=tomorrows,
        today_qr=today_qr,
        tomorrow_qr=tomorrow_qr,
        today_str=today_str,
        tomorrow_str=tomorrow_str,
        fines=student_fines,
        cancellations=student_cancellations,
        total_due=total_due,  # Pass the calculated total due
        footer_symbol=FOOTER_SYMBOL,
        gender_emoji=gender_emoji
    )

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """User profile management"""
    if request.method == "POST":
        # Check if it's a profile update or password change
        if 'current_password' in request.form:
            # Password change
            current_password = request.form.get("current_password")
            new_password = request.form.get("new_password")
            confirm_password = request.form.get("confirm_password")
            
            # Verify current password
            user = verify_user(session['user_email'], current_password)
            if not user:
                flash('Current password is incorrect', 'danger')
                return redirect(url_for('profile'))
            
            if new_password != confirm_password:
                flash('New passwords do not match', 'danger')
                return redirect(url_for('profile'))
            
            # Update password
            update_user_password(session['user_id'], new_password)
            flash('Password updated successfully!', 'success')
            
        else:
            # Profile update
            name = request.form.get("name")
            phone = request.form.get("phone")
            hostel_type = request.form.get('hostel_type')
            
            update_user_profile(session['user_id'], name, phone, hostel_type)
            
            # Update session
            session['user_name'] = name
            session['user_phone'] = phone
            session['hostel_type'] = hostel_type
            
            flash('Profile updated successfully!', 'success')
        
        return redirect(url_for('profile'))
    
    # Determine gender emoji
    gender_emoji = "👩" if session.get('hostel_type') == 'Female' else "👨"
    
    return render_template("profile.html", footer_symbol=FOOTER_SYMBOL, gender_emoji=gender_emoji)

@app.route("/book", methods=["GET", "POST"])
@login_required
def book():
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    
    if request.method == "POST":
        # For each meal, get selected checkboxes and save
        for meal in MENU.keys():
            selected = request.form.getlist(f"{meal}_items")
            confirm_booking(session['user_id'], meal, selected, booking_date=tomorrow_str)
        flash("Meals booked successfully!", "success")
        
        # Add notification
        add_notification(
            session['user_id'],
            f"You have successfully booked meals for tomorrow ({tomorrow_str}).",
            "booking_confirmation"
        )
        
        return redirect(url_for("book"))

    # GET -> prefill with whatever is already booked for tomorrow
    prefill = get_bookings_with_attendance(session['user_id'], tomorrow_str)
    
    # Get booking deadline info
    booking_start, booking_end = get_booking_deadline()
    
    return render_template("book.html",
                          menu=MENU,
                          prefill=prefill,
                          footer_symbol=FOOTER_SYMBOL,
                          booking_start=booking_start,
                          booking_end=booking_end,
                          can_edit=can_edit_booking())

@app.route("/history")
@login_required
def history():
    """Display booking history for any selected date"""
    # Get the selected date from query parameters, default to today
    selected_date_str = request.args.get('date', date.today().isoformat())
    
    # Validate date format
    try:
        selected_date = datetime.strptime(selected_date_str, '%Y-%m-%d').date()
        selected_date_str = selected_date.isoformat()
    except ValueError:
        selected_date_str = date.today().isoformat()
        selected_date = date.today()
    
    today_str = date.today().isoformat()
    tomorrow_str = (date.today() + timedelta(days=1)).isoformat()
    
    # Get bookings for the selected date
    selected_date_bookings = get_bookings_with_attendance(session['user_id'], selected_date_str)
    
    # Generate QR codes only for booked meals and for today/tomorrow only
    selected_date_qr = {}
    if selected_date <= date.today() + timedelta(days=1):  # Only generate QR for today and tomorrow
        for meal in ["Breakfast", "Lunch", "Dinner"]:
            if selected_date_bookings[meal]['food_items']:
                selected_date_qr[meal] = generate_qr_code(f"{session['user_id']}-{selected_date_str}-{meal}")

    return render_template(
        "history.html",
        today_str=today_str,
        tomorrow_str=tomorrow_str,
        selected_date=selected_date_str,
        selected_date_bookings=selected_date_bookings,
        selected_date_qr=selected_date_qr,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/reviews", methods=["GET", "POST"])
@login_required
def reviews():
    # Show bookings for yesterday to review
    yesterday_str = (date.today() - timedelta(days=1)).isoformat()
    available_bookings = get_bookings_with_attendance(session['user_id'], yesterday_str)

    if request.method == "POST":
        meal_type = request.form.get("meal_type")
        item = request.form.get("item")
        rating = int(request.form.get("rating"))
        feedback = request.form.get("feedback")
        submit_review(session['user_id'], date.today().isoformat(), meal_type, item, rating, feedback)
        flash("Review submitted successfully!", "success")
        return redirect(url_for("reviews"))

    return render_template("reviews.html", bookings=available_bookings, footer_symbol=FOOTER_SYMBOL)

@app.route("/scan/<student_id>/<date_str>/<meal_type>")
def scan_qr(student_id, date_str, meal_type):
    """This endpoint is hit when a mess staff scans a student's QR code."""
    mark_attendance(student_id, date_str, meal_type, "Present")
    return f"Attendance marked for {student_id} on {date_str} ({meal_type})!"

@app.route("/fines")
@login_required
def fines():
    """Display fines page"""
    student_fines = get_fines(session['user_id'])
    total_due = sum(fine['amount'] for fine in student_fines if not fine['paid'])
    paid_amount = sum(fine['amount'] for fine in student_fines if fine['paid'])
    return render_template("fines.html", fines=student_fines, total_due=total_due, paid_amount=paid_amount, footer_symbol=FOOTER_SYMBOL)

@app.route("/process_payment", methods=["POST"])
@login_required
def process_payment():
    """Process payment for fines"""
    fine_id = request.form.get("fine_id")
    amount = request.form.get("amount")
    payment_method = request.form.get("payment_method")
    
    # In a real implementation, you would integrate with a payment gateway here
    # For now, we'll simulate a successful payment
    
    # Log payment details (for demo purposes)
    print(f"Processing payment: Fine ID={fine_id}, Amount={amount}, Method={payment_method}")
    
    if payment_method == "credit_card":
        card_number = request.form.get("card_number")
        expiry_date = request.form.get("expiry_date")
        cvv = request.form.get("cvv")
        cardholder_name = request.form.get("cardholder_name")
        print(f"Card details: {card_number[-4:]}, Exp: {expiry_date}, Name: {cardholder_name}")
    
    elif payment_method == "upi":
        upi_id = request.form.get("upi_id")
        print(f"UPI ID: {upi_id}")
    
    elif payment_method == "net_banking":
        bank = request.form.get("bank")
        print(f"Bank: {bank}")
    
    elif payment_method == "wallet":
        wallet = request.form.get("wallet")
        mobile = request.form.get("mobile")
        print(f"Wallet: {wallet}, Mobile: {mobile}")
    
    # Update the database
    try:
        if fine_id == "all":
            # Pay all fines
            conn = sqlite3.connect("mess_app.db")
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE fines SET paid = 1 WHERE student_id = ? AND paid = 0",
                (session['user_id'],)
            )
            conn.commit()
            conn.close()
            message = f"Successfully paid all fines totaling ₹{amount} via {payment_method.replace('_', ' ')}!"
        else:
            # Pay a specific fine
            conn = sqlite3.connect("mess_app.db")
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE fines SET paid = 1 WHERE id = ?",
                (fine_id,)
            )
            conn.commit()
            conn.close()
            message = f"Successfully paid fine of ₹{amount} via {payment_method.replace('_', ' ')}!"
        
        return jsonify({"success": True, "message": message})
    
    except Exception as e:
        return jsonify({"success": False, "message": f"Payment failed: {str(e)}"})


@app.route("/reset_fines")
@login_required
def reset_fines_route():
    """Reset fines to unpaid status for testing"""
    reset_fines(session['user_id'])
    flash("Fines have been reset to unpaid status for testing!", "info")
    return redirect(url_for('fines'))

@app.route("/cancel", methods=["GET", "POST"])
@login_required
def cancel_meal():
    """Allow students to submit cancellation requests."""
    if request.method == "POST":
        # Get the selected meal from the dropdown
        meal_selection = request.form.get("meal_selection")
        reason = request.form.get("reason")
        
        if not meal_selection:
            flash("Please select a meal to cancel.", "danger")
            return redirect(url_for('cancel_meal'))
        
        # Parse the selection (format: date_mealtype)
        date_val, meal_type = meal_selection.split('_', 1)
        
        # Check if cancellation is allowed (at least 1 hour before meal time)
        if not can_cancel_meal(date_val, meal_type):
            flash("Cancellation is not allowed. You can only cancel meals at least 1 hour before the meal time.", "danger")
            return redirect(url_for('cancel_meal'))

        # Check if the meal was actually booked
        bookings = get_bookings_with_attendance(session['user_id'], date_val)
        if not bookings[meal_type]['food_items']:
            flash(f"You didn't book {meal_type} on {date_val}, so no cancellation is needed.", "warning")
            return redirect(url_for('cancel_meal'))

        # Insert the cancellation request into the database
        conn = sqlite3.connect("mess_app.db")
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO cancellations (student_id, date, meal_type, reason, approved) VALUES (?, ?, ?, ?, ?)",
            (session['user_id'], date_val, meal_type, reason, 1)  # Auto-approve if within time
        )
        conn.commit()
        conn.close()
        
        # Clear the booking
        clear_meal_booking(session['user_id'], date_val, meal_type)
        
        flash("Meal cancelled successfully!", "success")
        
        # Add notification
        add_notification(
            session['user_id'],
            f"Your {meal_type} on {date_val} has been cancelled successfully.",
            "cancellation_confirmation"
        )
        
        return redirect(url_for('home'))

    # For GET request, show available meals that can be cancelled
    today = date.today()
    tomorrow = today + timedelta(days=1)
    
    # Get bookings for today and tomorrow
    today_bookings = get_bookings_with_attendance(session['user_id'], today.isoformat())
    tomorrow_bookings = get_bookings_with_attendance(session['user_id'], tomorrow.isoformat())
    
    # Prepare list of meals that can be cancelled
    cancellable_meals = []
    
    # Check today's meals
    for meal_type in ["Breakfast", "Lunch", "Dinner"]:
        if today_bookings[meal_type]['food_items'] and can_cancel_meal(today.isoformat(), meal_type):
            cancellable_meals.append({
                'date': today.isoformat(),
                'meal_type': meal_type,
                'food_items': today_bookings[meal_type]['food_items']
            })
    
    # Check tomorrow's meals
    for meal_type in ["Breakfast", "Lunch", "Dinner"]:
        if tomorrow_bookings[meal_type]['food_items'] and can_cancel_meal(tomorrow.isoformat(), meal_type):
            cancellable_meals.append({
                'date': tomorrow.isoformat(),
                'meal_type': meal_type,
                'food_items': tomorrow_bookings[meal_type]['food_items']
            })
    
    return render_template("cancel.html", cancellable_meals=cancellable_meals, meal_times=MEAL_TIMES, footer_symbol=FOOTER_SYMBOL)

@app.route("/attendance")
@login_required
def attendance():
    """Display attendance calendar"""
    # Get the selected month and year from query parameters, default to current month
    year = request.args.get('year', date.today().year, type=int)
    month = request.args.get('month', date.today().month, type=int)
    
    # Get calendar data for the selected month
    calendar_data = get_attendance_calendar(session['user_id'], year, month)
    
    # Get fines for the selected month
    monthly_fines = []
    student_fines = get_fines(session['user_id'])
    for fine in student_fines:
        fine_date = datetime.strptime(fine['date'], '%Y-%m-%d').date()
        if fine_date.year == year and fine_date.month == month:
            monthly_fines.append(fine)
    
    # Calculate previous and next month for navigation
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    next_month = month + 1 if month < 12 else 1
    next_year = year if month < 12 else year + 1
    
    # Calculate first weekday for calendar grid
    first_day = date(year, month, 1)
    first_weekday = (first_day.weekday() + 1) % 7  # Convert Monday=0 to Monday=1, Sunday=6 to Sunday=0
    
    # Get today's date as string for comparison in template
    today_str = date.today().isoformat()
    
    return render_template(
        "attendance.html",
        calendar_data=calendar_data,
        current_month=first_day,
        monthly_fines=monthly_fines,
        prev_month=prev_month,
        prev_year=prev_year,
        next_month=next_month,
        next_year=next_year,
        first_weekday=first_weekday,
        today_str=today_str,
        footer_symbol=FOOTER_SYMBOL
    )

@app.route("/notifications")
@login_required
def notifications():
    """Display user notifications"""
    user_notifications = get_unread_notifications(session['user_id'])
    return render_template("notifications.html", notifications=user_notifications, footer_symbol=FOOTER_SYMBOL)

@app.route("/mark_notification_read/<int:notification_id>")
@login_required
def mark_notification_read(notification_id):
    """Mark a notification as read"""
    mark_notification_as_read(notification_id)
    flash("Notification marked as read.", "success")
    return redirect(url_for('notifications'))

@app.route("/mark_all_notifications_read")
@login_required
def mark_all_notifications_read():
    """Mark all notifications as read"""
    conn = sqlite3.connect("mess_app.db")
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE notifications SET is_read = 1 WHERE user_id = ?",
        (session['user_id'],)
    )
    conn.commit()
    conn.close()
    flash("All notifications marked as read.", "success")
    return redirect(url_for('notifications'))

@app.route("/force_fine_calculation")
@login_required
def force_fine_calculation():
    """Manual endpoint to trigger fine calculation (for testing)"""
    calculate_daily_fines()
    flash("Fines calculation completed!", "info")
    return redirect(url_for('fines'))

if __name__ == "__main__":
    print("\n=== Starting MessMate Server ===")
    print("Available test routes:")
    print("  - /manual-reset/your_email@example.com (Get reset link directly)")
    print("  - /email-test (Test email configuration)")
    print("  - /forgot-password (Normal password reset flow)")
    app.run(debug=True)
