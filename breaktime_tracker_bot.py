"""
Telegram Break Time Tracker Bot - CSR Breaktime
Tracks employee break times with buttons for different break types
Production-ready with daily database archiving and Philippine Time (UTC+8)
With real-time SQLite sync for dashboard integration.
"""
import os
import pandas as pd
import pytz
from datetime import datetime, timedelta, time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes, ConversationHandler

# Import database sync functions for real-time dashboard
try:
    from bot_db_integration import sync_break_out, sync_break_back
    from database.db import get_active_session, get_or_create_user, get_all_active_sessions, get_user_by_telegram_id
    DB_SYNC_ENABLED = True
    print("✅ Database sync enabled for real-time dashboard")
except ImportError:
    DB_SYNC_ENABLED = False
    print("⚠️ Database sync not available (bot_db_integration.py not found)")

# Import Microsoft Excel Online sync
try:
    from microsoft.excel_handler import sync_break_to_excel, get_excel_handler
    import asyncio
    EXCEL_SYNC_AVAILABLE = True
    print("✅ Excel Online sync module loaded")
except ImportError as e:
    EXCEL_SYNC_AVAILABLE = False
    print(f"⚠️ Excel Online sync not available: {e}")

# Bot Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable is required. Please set it in your .env file.")

# Group Chat ID for daily reports
GROUP_CHAT_ID = os.getenv('GROUP_CHAT_ID')
if not GROUP_CHAT_ID:
    print("WARNING: GROUP_CHAT_ID not set. Daily reports will not be sent to group.")

# Philippine Timezone
PH_TZ = pytz.timezone('Asia/Manila')

# For Docker: Use /app, for local: Use current directory
BASE_DIR = os.getenv('BASE_DIR', '/app')
DATABASE_DIR = os.path.join(BASE_DIR, "database")

# Conversation states
WAITING_FOR_REASON = 1

# Store user break sessions
user_sessions = {}

# Store users waiting to provide reasons
waiting_for_reason_users = {}

# Break type display name mapping (reverse lookup)
BREAK_TYPE_DISPLAY = {
    'B': '☕ Break',
    'W': '🚻 WC',
    'P': '🚽 WCP',
    'O': '⚠️ Other'
}


def get_active_session_from_db(telegram_id: int) -> dict:
    """
    Get active session from database and convert to in-memory format.
    This ensures sessions persist across bot restarts.
    """
    if not DB_SYNC_ENABLED:
        return None

    try:
        # Get user ID from telegram ID
        user = get_user_by_telegram_id(telegram_id)
        if not user:
            return None

        session = get_active_session(user['id'])
        if not session:
            return None

        # Convert DB format to in-memory format
        break_type_code = session.get('break_type_code', 'O')
        break_type_display = BREAK_TYPE_DISPLAY.get(break_type_code, '⚠️ Other')

        return {
            'break_type': break_type_display,
            'start_time': str(session['start_time']).split('.')[0],  # Remove microseconds
            'active': True,
            'reason': session.get('reason'),
            'group_chat_id': session.get('group_chat_id')
        }
    except Exception as e:
        print(f"[DB] Error getting active session: {e}")
        return None


def load_active_sessions_from_db():
    """
    Load all active sessions from database into memory on startup.
    This restores state after bot restarts.
    """
    if not DB_SYNC_ENABLED:
        return

    try:
        sessions = get_all_active_sessions()
        loaded_count = 0

        for session in sessions:
            telegram_id = session['telegram_id']
            break_type_code = session.get('break_type_name', 'Other')

            # Find the display name based on break_type_name
            break_type_display = break_type_code
            for code, display in BREAK_TYPE_DISPLAY.items():
                if code in str(session.get('break_type_id', '')):
                    break_type_display = display
                    break

            # Use break_type_name directly if available
            if 'break_type_name' in session:
                name = session['break_type_name']
                if 'Break' in name:
                    break_type_display = '☕ Break'
                elif 'WCP' in name:
                    break_type_display = '🚽 WCP'
                elif 'WC' in name:
                    break_type_display = '🚻 WC'
                elif 'Other' in name:
                    break_type_display = '⚠️ Other'

            user_sessions[telegram_id] = {
                'break_type': break_type_display,
                'start_time': str(session['start_time']).split('.')[0],
                'active': True,
                'reason': session.get('reason'),
                'full_name': session.get('full_name', 'Unknown'),
                'group_chat_id': session.get('group_chat_id')
            }
            loaded_count += 1

        if loaded_count > 0:
            print(f"✅ Loaded {loaded_count} active sessions from database")
    except Exception as e:
        print(f"[DB] Error loading active sessions: {e}")


def get_ph_time():
    """Get current Philippine time."""
    return datetime.now(PH_TZ)


def get_daily_log_file():
    """Get the log file path for today's date (PH Time)."""
    now = get_ph_time()
    today = now.strftime('%Y-%m-%d')
    year_month = now.strftime('%Y-%m')

    # Create directory structure: database/YYYY-MM/
    month_dir = os.path.join(DATABASE_DIR, year_month)
    os.makedirs(month_dir, exist_ok=True)

    # File format: break_logs_YYYY-MM-DD.xlsx
    log_file = os.path.join(month_dir, f"break_logs_{today}.xlsx")
    return log_file


def init_database_structure():
    """Initialize the database directory structure."""
    os.makedirs(DATABASE_DIR, exist_ok=True)
    print(f"Database directory: {DATABASE_DIR}")

    log_file = get_daily_log_file()
    if not os.path.exists(log_file):
        df = pd.DataFrame(columns=['User ID', 'Username', 'Full Name', 'Break Type', 'Action', 'Timestamp', 'Duration (minutes)', 'Reason'])
        df.to_excel(log_file, index=False, engine='openpyxl')
        print(f"Created new daily log file: {log_file}")
    else:
        print(f"Using existing log file: {log_file}")


async def log_break_activity_async(user_id, username, full_name, break_type, action, timestamp, duration=None, reason=None, group_chat_id=None):
    """Async version: Log break activity to Excel file, SQLite, AND Excel Online"""
    # Log to local Excel file (original behavior)
    log_file = get_daily_log_file()

    if os.path.exists(log_file):
        df = pd.read_excel(log_file, engine='openpyxl')
    else:
        df = pd.DataFrame(columns=['User ID', 'Username', 'Full Name', 'Break Type', 'Action', 'Timestamp', 'Duration (minutes)', 'Reason'])

    new_row = pd.DataFrame([[user_id, username, full_name, break_type, action, timestamp, duration or '', reason or '']],
                          columns=['User ID', 'Username', 'Full Name', 'Break Type', 'Action', 'Timestamp', 'Duration (minutes)', 'Reason'])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel(log_file, index=False, engine='openpyxl')

    # Sync to SQLite for real-time dashboard
    if DB_SYNC_ENABLED:
        try:
            if action == 'OUT':
                sync_break_out(user_id, username, full_name, break_type, timestamp, reason, group_chat_id)
            elif action == 'BACK':
                sync_break_back(user_id, username, full_name, break_type, timestamp, duration or 0, reason, group_chat_id)
        except Exception as e:
            print(f"[DB Sync Error] {e}")

    # Sync to Excel Online (Microsoft OneDrive)
    if EXCEL_SYNC_AVAILABLE:
        try:
            await sync_break_to_excel(
                user_id, username, full_name, break_type,
                action, timestamp, duration, reason
            )
        except Exception as e:
            print(f"[Excel Online Sync Error] {e}")


def log_break_activity(user_id, username, full_name, break_type, action, timestamp, duration=None, reason=None, group_chat_id=None):
    """Log break activity to daily Excel file AND SQLite database for real-time dashboard"""
    # Log to local Excel file (original behavior)
    log_file = get_daily_log_file()

    if os.path.exists(log_file):
        df = pd.read_excel(log_file, engine='openpyxl')
    else:
        df = pd.DataFrame(columns=['User ID', 'Username', 'Full Name', 'Break Type', 'Action', 'Timestamp', 'Duration (minutes)', 'Reason'])

    new_row = pd.DataFrame([[user_id, username, full_name, break_type, action, timestamp, duration or '', reason or '']],
                          columns=['User ID', 'Username', 'Full Name', 'Break Type', 'Action', 'Timestamp', 'Duration (minutes)', 'Reason'])
    df = pd.concat([df, new_row], ignore_index=True)
    df.to_excel(log_file, index=False, engine='openpyxl')

    # Sync to SQLite for real-time dashboard
    if DB_SYNC_ENABLED:
        try:
            if action == 'OUT':
                sync_break_out(user_id, username, full_name, break_type, timestamp, reason, group_chat_id)
            elif action == 'BACK':
                sync_break_back(user_id, username, full_name, break_type, timestamp, duration or 0, reason, group_chat_id)
        except Exception as e:
            print(f"[DB Sync Error] {e}")

    # Schedule Excel Online sync (non-blocking, fire-and-forget)
    if EXCEL_SYNC_AVAILABLE:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(sync_break_to_excel(
                user_id, username, full_name, break_type,
                action, timestamp, duration, reason
            ))
        except RuntimeError:
            # No running event loop - skip Excel sync
            pass
        except Exception as e:
            print(f"[Excel Online Sync Error] {e}")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message with break time buttons"""
    user = update.effective_user

    keyboard = [
        [
            InlineKeyboardButton("☕ Break Out (B1)", callback_data='B1'),
            InlineKeyboardButton("✅ Break Back (B2)", callback_data='B2')
        ],
        [
            InlineKeyboardButton("🚻 WC Out (W1)", callback_data='W1'),
            InlineKeyboardButton("✅ WC Back (W2)", callback_data='W2')
        ],
        [
            InlineKeyboardButton("🚽 WCP Out (P1)", callback_data='P1'),
            InlineKeyboardButton("✅ WCP Back (P2)", callback_data='P2')
        ],
        [
            InlineKeyboardButton("⚠️ Other Out (O1)", callback_data='O1'),
            InlineKeyboardButton("✅ Other Back (O2)", callback_data='O2')
        ],
        [
            InlineKeyboardButton("📊 My Break Summary", callback_data='summary')
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_message = (
        f"👋 Welcome {user.first_name}!\n\n"
        "🕐 **Break Time Tracker Bot**\n\n"
        "Track your breaks using the buttons below:\n\n"
        "☕ **Break** - B1 (Out) / B2 (Back) - 30 mins\n"
        "🚻 **WC** - W1 (Out) / W2 (Back) - 5 mins\n"
        "🚽 **WCP** - P1 (Out) / P2 (Back) - 10 mins\n"
        "⚠️ **Other** - O1 (Out) / O2 (Back) - Reason required\n\n"
        "Click a button to log your break time!"
    )

    await update.message.reply_text(welcome_message, reply_markup=reply_markup, parse_mode='Markdown')


async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()

    user = query.from_user
    user_id = user.id
    username = user.username or 'N/A'
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    action_code = query.data
    timestamp = get_ph_time().strftime('%Y-%m-%d %H:%M:%S')

    group_chat_id = None
    if query.message.chat.type in ['group', 'supergroup']:
        group_chat_id = query.message.chat.id

    if action_code == 'summary':
        await show_summary(query, user_id, username, full_name)
        return ConversationHandler.END

    break_types = {
        'B': '☕ Break',
        'W': '🚻 WC',
        'P': '🚽 WCP',
        'O': '⚠️ Other'
    }

    break_type_code = action_code[0]
    action_type = action_code[1]
    break_type = break_types.get(break_type_code, 'Unknown')

    # Check in-memory first, then fallback to database
    active_session = user_sessions.get(user_id)
    if not active_session or not active_session.get('active'):
        # Try to get from database (handles bot restarts)
        db_session = get_active_session_from_db(user_id)
        if db_session:
            user_sessions[user_id] = db_session  # Sync to memory
            active_session = db_session

    is_active = active_session and active_session.get('active')

    # Handle "OUT" actions (B1, W1, P1, O1)
    if action_type == '1':
        if is_active:
            await query.message.reply_text(
                f"""⚠️ **Warning, {full_name}!**

You still have an active break: {active_session['break_type']}

Please clock back in first before starting a new break!""",
                parse_mode='Markdown'
            )
            return ConversationHandler.END

        if action_code == 'O1':
            context.user_data['break_type'] = break_type
            context.user_data['start_time'] = timestamp
            context.user_data['group_chat_id'] = group_chat_id
            await query.message.reply_text(
                f"""⚠️ **Other Concern - Out, {full_name}**

🕐 Time: {timestamp}

Please type the reason for your break:""",
                parse_mode='Markdown'
            )
            return WAITING_FOR_REASON

        session_data = {
            'break_type': break_type,
            'start_time': timestamp,
            'active': True,
            'full_name': full_name,
            'group_chat_id': group_chat_id
        }
        if break_type_code in ['E', 'S']:
            session_data['reminder_sent'] = False
        user_sessions[user_id] = session_data

        log_break_activity(user_id, username, full_name, break_type, 'OUT', timestamp, group_chat_id=group_chat_id)

        await query.message.reply_text(
            f"""✅ **{full_name}** - Break Started

Type: {break_type}
🕐 Time Out: {timestamp}

Don't forget to clock back in when you return!""",
            parse_mode='Markdown'
        )
        return ConversationHandler.END

    # Handle "BACK" actions (E2, C2, S2, O2)
    elif action_type == '2':
        if not is_active:
            await query.message.reply_text(
                f"""⚠️ **No Active Break, {full_name}!**

You don't have an active break to end.
Please start a break first!""",
                parse_mode='Markdown'
            )
            return ConversationHandler.END

        active_break_type_name = active_session['break_type']
        if active_break_type_name != break_type:
            await query.message.reply_text(
                f"""⚠️ **Warning, {full_name}!**

You are trying to end a '{break_type}' break, but your active break is '{active_break_type_name}'.""",
                parse_mode='Markdown'
            )
            return ConversationHandler.END

        start_time_str = active_session['start_time']
        reason = active_session.get('reason', None)

        start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        duration_minutes = round((end_time - start_time).total_seconds() / 60, 1)

        # Clear session FIRST to stop reminders immediately
        user_sessions[user_id] = {'active': False}

        log_break_activity(user_id, username, full_name, break_type, 'BACK', timestamp, duration_minutes, reason, group_chat_id=group_chat_id)

        reason_text = f"\n📝 Reason: {reason}" if reason else ""
        await query.message.reply_text(
            f"""✅ **{full_name}** - Break Ended

Type: {break_type}
🕐 Time Out: {start_time_str}
🕐 Time Back: {timestamp}
⏱️ Duration: {duration_minutes:.1f} minutes{reason_text}

Welcome back!""",
            parse_mode='Markdown'
        )
        return ConversationHandler.END


async def handle_reason(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reason input for O1 (Other Concern)"""
    user = update.effective_user
    user_id = user.id
    username = user.username or 'N/A'
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    reason = update.message.text

    break_type = context.user_data['break_type']
    start_time = context.user_data['start_time']
    group_chat_id = context.user_data.get('group_chat_id')

    user_sessions[user_id] = {
        'break_type': break_type,
        'start_time': start_time,
        'active': True,
        'reason': reason,
        'full_name': full_name,
        'group_chat_id': group_chat_id
    }

    log_break_activity(user_id, username, full_name, break_type, 'OUT', start_time, reason=reason, group_chat_id=group_chat_id)

    await update.message.reply_text(
        f"""✅ **{full_name}** - Break Started

Type: {break_type}
📝 Reason: {reason}
🕐 Time Out: {start_time}

Don't forget to clock back in when you return!""",
        parse_mode='Markdown'
    )
    return ConversationHandler.END


async def show_summary(query, user_id, username, full_name):
    """Show user's break summary for today"""
    today = get_ph_time().strftime('%Y-%m-%d')
    log_file = get_daily_log_file()

    if not os.path.exists(log_file):
        await query.message.reply_text("📊 No break history found for today.")
        return

    df = pd.read_excel(log_file, engine='openpyxl')
    df['Timestamp'] = df['Timestamp'].astype(str)
    user_breaks_df = df[(df['User ID'] == user_id) & (df['Timestamp'].str.startswith(today))]

    if user_breaks_df.empty:
        await query.message.reply_text(f"📊 **Today's Break Summary**\n\nNo breaks recorded today.")
        return

    total_time = user_breaks_df[user_breaks_df['Break Type'] != '🚻 WC']['Duration (minutes)'].sum()

    summary_df = user_breaks_df[user_breaks_df['Action'] == 'BACK'].groupby('Break Type').agg(
        count=('Break Type', 'size'),
        total_duration=('Duration (minutes)', 'sum')
    ).to_dict('index')

    summary_text = f"📊 **Today's Break Summary**\n\n"
    summary_text += f"👤 {full_name}\n"
    summary_text += f"📅 Date: {today}\n\n"

    summary_text += "**Break Details:**\n"
    if not summary_df:
        summary_text += "No breaks completed today.\n"
    else:
        for break_type, stats in summary_df.items():
            summary_text += f"• {break_type}: {stats['count']} time(s) - {stats['total_duration']:.1f} min\n"

    summary_text += f"\n⏱️ **Total Break Time (excluding WC):** {total_time:.1f} minutes\n"

    await query.message.reply_text(summary_text, parse_mode='Markdown')


async def menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu with buttons"""
    keyboard = [
        [
            InlineKeyboardButton("☕ Break Out (B1)", callback_data='B1'),
            InlineKeyboardButton("✅ Break Back (B2)", callback_data='B2')
        ],
        [
            InlineKeyboardButton("🚻 WC Out (W1)", callback_data='W1'),
            InlineKeyboardButton("✅ WC Back (W2)", callback_data='W2')
        ],
        [
            InlineKeyboardButton("🚽 WCP Out (P1)", callback_data='P1'),
            InlineKeyboardButton("✅ WCP Back (P2)", callback_data='P2')
        ],
        [
            InlineKeyboardButton("⚠️ Other Out (O1)", callback_data='O1'),
            InlineKeyboardButton("✅ Other Back (O2)", callback_data='O2')
        ],
        [
            InlineKeyboardButton("📊 My Break Summary", callback_data='summary')
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🕐 **Break Time Tracker**\n\nSelect an option:", reply_markup=reply_markup, parse_mode='Markdown')


def get_keyboard(user_id):
    """Return the main keyboard"""
    keyboard = [
        [
            InlineKeyboardButton("☕ Break Out (B1)", callback_data='B1'),
            InlineKeyboardButton("✅ Break Back (B2)", callback_data='B2')
        ],
        [
            InlineKeyboardButton("🚻 WC Out (W1)", callback_data='W1'),
            InlineKeyboardButton("✅ WC Back (W2)", callback_data='W2')
        ],
        [
            InlineKeyboardButton("🚽 WCP Out (P1)", callback_data='P1'),
            InlineKeyboardButton("✅ WCP Back (P2)", callback_data='P2')
        ],
        [
            InlineKeyboardButton("⚠️ Other Out (O1)", callback_data='O1'),
            InlineKeyboardButton("✅ Other Back (O2)", callback_data='O2')
        ],
        [
            InlineKeyboardButton("📊 My Break Summary", callback_data='summary')
        ]
    ]
    return InlineKeyboardMarkup(keyboard)


async def handle_break_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle break commands like /b1, /b2, /w1, /w2, /p1, /p2"""
    user = update.effective_user
    user_id = user.id
    username = user.username or 'N/A'
    full_name = f"{user.first_name} {user.last_name or ''}".strip()
    timestamp = get_ph_time().strftime('%Y-%m-%d %H:%M:%S')
    keyboard = get_keyboard(user_id)

    group_chat_id = None
    if update.message.chat.type in ['group', 'supergroup']:
        group_chat_id = update.message.chat.id

    command = update.message.text.split()[0].lower().replace('/', '').upper()
    message_parts = update.message.text.split(maxsplit=1)
    reason_from_command = message_parts[1] if len(message_parts) > 1 else None

    break_types = {
        'B': '☕ Break',
        'W': '🚻 WC',
        'P': '🚽 WCP',
        'O': '⚠️ Other'
    }

    if command not in ['B1', 'B2', 'W1', 'W2', 'P1', 'P2', 'O1', 'O2']:
        return

    break_type_code = command[0]
    action_type = command[1]
    break_type = break_types.get(break_type_code, 'Unknown')

    # Check in-memory first, then fallback to database
    active_session = user_sessions.get(user_id)
    if not active_session or not active_session.get('active'):
        # Try to get from database (handles bot restarts)
        db_session = get_active_session_from_db(user_id)
        if db_session:
            user_sessions[user_id] = db_session  # Sync to memory
            active_session = db_session

    is_active = active_session and active_session.get('active')

    # Handle OUT actions
    if action_type == '1':
        if is_active:
            await update.message.reply_text(
                f"""⚠️ {full_name}

You already have an active break: {active_session['break_type']}

Please finish it first!""",
                reply_markup=keyboard
            )
            return

        session_data = {
            'break_type': break_type,
            'start_time': timestamp,
            'active': True,
            'reason': reason_from_command,
            'full_name': full_name,
            'group_chat_id': group_chat_id,
            'reminder_sent': False
        }
        user_sessions[user_id] = session_data

        log_break_activity(user_id, username, full_name, break_type, 'OUT', timestamp, reason=reason_from_command, group_chat_id=group_chat_id)

        reason_text = f"\n📝 Reason: {reason_from_command}" if reason_from_command else ""
        await update.message.reply_text(
            f"""✅ {full_name} - Break Started

Type: {break_type}{reason_text}
🕐 Time Out: {timestamp}""",
            reply_markup=keyboard
        )

    # Handle BACK actions
    elif action_type == '2':
        if not is_active:
            await update.message.reply_text(
                f"""⚠️ **{full_name}**

No active break to end!""",
                reply_markup=keyboard, parse_mode='Markdown'
            )
            return

        active_break_type_name = active_session['break_type']
        if active_break_type_name != break_type:
            await update.message.reply_text(
                f"""⚠️ **{full_name}**

You are trying to end a '{break_type}' break, but your active break is '{active_break_type_name}'.""",
                reply_markup=keyboard, parse_mode='Markdown'
            )
            return

        start_time = datetime.strptime(active_session['start_time'], '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        duration_minutes = round((end_time - start_time).total_seconds() / 60, 1)
        reason = active_session.get('reason')
        session_group_chat_id = active_session.get('group_chat_id')

        # Clear session FIRST to stop reminders immediately
        user_sessions[user_id] = {'active': False}

        log_break_activity(user_id, username, full_name, break_type, 'BACK', timestamp, duration_minutes, reason, session_group_chat_id)

        reason_text = f"\n📝 Reason: {reason}" if reason else ""
        await update.message.reply_text(
            f"""✅ **{full_name}** - Break Ended

Type: {break_type}
⏱️ Duration: {duration_minutes:.1f} min{reason_text}""",
            reply_markup=keyboard, parse_mode='Markdown'
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancels and ends the conversation."""
    await update.message.reply_text("Operation cancelled.")
    return ConversationHandler.END


async def check_break_reminders(context: ContextTypes.DEFAULT_TYPE):
    """Periodically check for long-running breaks and send reminders to group EVERY MINUTE."""
    now = get_ph_time()
    now_naive = datetime.strptime(now.strftime('%Y-%m-%d %H:%M:%S'), '%Y-%m-%d %H:%M:%S')

    for user_id, session in user_sessions.items():
        if session.get('active'):
            break_type = session.get('break_type')

            reminder_config = {
                '☕ Break': 30,
                '🚻 WC': 5,
                '🚽 WCP': 10
            }

            if break_type in reminder_config:
                threshold_minutes = reminder_config[break_type]
                start_time = datetime.strptime(session['start_time'], '%Y-%m-%d %H:%M:%S')
                duration_minutes = (now_naive - start_time).total_seconds() / 60

                if duration_minutes >= threshold_minutes:
                    full_name = session.get('full_name', 'there')
                    over_minutes = int(duration_minutes - threshold_minutes)

                    # Always send to group if GROUP_CHAT_ID is set
                    target_chat_id = GROUP_CHAT_ID if GROUP_CHAT_ID else user_id

                    warning_msg = f"""⚠️ BREAK TIME WARNING ⚠️

👤 {full_name}
📍 {break_type}
⏱️ Duration: {int(duration_minutes)} mins
🚨 OVER LIMIT by {over_minutes} mins!

Time limit: {threshold_minutes} mins
Please clock back now using /b2, /w2, or /p2"""

                    try:
                        await context.bot.send_message(
                            chat_id=target_chat_id,
                            text=warning_msg
                        )
                        print(f"⚠️ Warning sent for {full_name} - {break_type} over by {over_minutes} mins")
                    except Exception as e:
                        print(f"Failed to send reminder: {e}")


async def send_daily_report_to_group(context: ContextTypes.DEFAULT_TYPE):
    """Send daily break report to the configured Telegram group."""
    if not GROUP_CHAT_ID:
        print("GROUP_CHAT_ID not configured. Skipping group report.")
        return

    yesterday = (get_ph_time() - timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"\n{'='*50}")
    print(f"Sending daily report for {yesterday} to group {GROUP_CHAT_ID}...")
    print(f"{'='*50}")

    # Get yesterday's log file
    year_month = (get_ph_time() - timedelta(days=1)).strftime('%Y-%m')
    month_dir = os.path.join(DATABASE_DIR, year_month)
    log_file = os.path.join(month_dir, f"break_logs_{yesterday}.xlsx")

    if not os.path.exists(log_file):
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=f"👋 @j365_kash @juangee18\n\n📊 DAILY BREAK REPORT\n\n📅 Date: {yesterday}\n\n✅ No break activity recorded."
        )
        return

    df = pd.read_excel(log_file, engine='openpyxl')

    if df.empty:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=f"👋 @j365_kash @juangee18\n\n📊 DAILY BREAK REPORT\n\n📅 Date: {yesterday}\n\n✅ No break activity recorded."
        )
        return

    # Build comprehensive report with user mentions
    report_text = f"👋 @j365_kash @juangee18\n\n"
    report_text += f"📊 DAILY BREAK REPORT\n"
    report_text += f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    report_text += f"📅 Date: {yesterday}\n"
    report_text += f"🕐 Timezone: Philippine Time (UTC+8)\n\n"

    # Get unique users
    unique_users = df['Full Name'].unique()
    report_text += f"👥 Total Employees: {len(unique_users)}\n\n"

    # Summary by break type
    report_text += "📈 Summary by Break Type:\n"
    back_df = df[df['Action'] == 'BACK']
    if not back_df.empty:
        type_summary = back_df.groupby('Break Type').agg(
            count=('Break Type', 'size'),
            total_duration=('Duration (minutes)', 'sum'),
            avg_duration=('Duration (minutes)', 'mean')
        )
        for break_type, row in type_summary.iterrows():
            report_text += f"• {break_type}: {int(row['count'])} breaks, {row['total_duration']:.1f} min total (avg: {row['avg_duration']:.1f} min)\n"
    else:
        report_text += "• No completed breaks\n"

    # Individual user summaries (only show if there are completed breaks)
    if not back_df.empty:
        report_text += "\n👤 Individual Summaries:\n"
        for full_name in unique_users:
            user_df = df[df['Full Name'] == full_name]
            user_back_df = user_df[user_df['Action'] == 'BACK']

            if not user_back_df.empty:
                total_time = float(user_back_df[user_back_df['Break Type'] != '🚻 WC']['Duration (minutes)'].sum())
                report_text += f"\n{full_name}:\n"
                user_type_summary = user_back_df.groupby('Break Type').agg(
                    count=('Break Type', 'size'),
                    total_duration=('Duration (minutes)', 'sum')
                )
                for break_type, row in user_type_summary.iterrows():
                    report_text += f"  • {break_type}: {int(row['count'])}x - {float(row['total_duration']):.1f} min\n"
                report_text += f"  ⏱️ Total (excl. WC): {total_time:.1f} min\n"

    # Check for missing BACK logs
    missing_backs = []
    for full_name in unique_users:
        user_df = df[df['Full Name'] == full_name]
        for break_type in user_df['Break Type'].unique():
            type_df = user_df[user_df['Break Type'] == break_type]
            out_count = len(type_df[type_df['Action'] == 'OUT'])
            back_count = len(type_df[type_df['Action'] == 'BACK'])
            if out_count > back_count:
                missing_backs.append(f"• {full_name}: {break_type} ({out_count - back_count} missing)")

    if missing_backs:
        report_text += "\n⚠️ MISSING CLOCK-BACKS:\n"
        for missing in missing_backs:
            report_text += f"{missing}\n"
    else:
        report_text += "\n✅ All users clocked back!\n"

    report_text += f"\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    report_text += f"🤖 CSR Breaktime Bot\n"
    report_text += f"📍 Auto report: 12:00 AM PH Time"

    try:
        await context.bot.send_message(
            chat_id=GROUP_CHAT_ID,
            text=report_text
        )
        print(f"✅ Daily report sent to group {GROUP_CHAT_ID}")
    except Exception as e:
        print(f"❌ Failed to send daily report: {e}")


async def run_end_of_day_reports(context: ContextTypes.DEFAULT_TYPE):
    """Run daily reports for 'no back' breaks and individual summaries."""
    yesterday = (get_ph_time() - timedelta(days=1)).strftime('%Y-%m-%d')
    print(f"\n{'='*50}")
    print(f"Running end-of-day reports for {yesterday}...")
    print(f"{'='*50}")

    # Send daily report to group
    await send_daily_report_to_group(context)

    # Get yesterday's log file
    year_month = (get_ph_time() - timedelta(days=1)).strftime('%Y-%m')
    month_dir = os.path.join(DATABASE_DIR, year_month)
    log_file = os.path.join(month_dir, f"break_logs_{yesterday}.xlsx")

    if not os.path.exists(log_file):
        print(f"Log file not found for {yesterday}. Skipping daily reports.")
        return

    df = pd.read_excel(log_file, engine='openpyxl')

    if df.empty:
        print("No activity yesterday. Skipping reports.")
        return

    _generate_no_back_summary(df, yesterday)
    await _send_individual_summaries(df, context)


def _generate_no_back_summary(df: pd.DataFrame, date: str):
    """Analyzes the dataframe for breaks that were not ended and prints a summary."""
    print(f"\n--- Daily 'No Back' Report for {date} ---")
    summary = {}
    for _, row in df.iterrows():
        user_key = (row['User ID'], row['Full Name'])
        if user_key not in summary:
            summary[user_key] = {}

        break_type = row['Break Type']
        if break_type not in summary[user_key]:
            summary[user_key][break_type] = {'OUT': 0, 'BACK': 0}

        summary[user_key][break_type][row['Action']] += 1

    found_missing = False
    for user, breaks in summary.items():
        user_id, full_name = user
        for break_type, actions in breaks.items():
            if actions['OUT'] > actions['BACK']:
                found_missing = True
                print(f"⚠️  User: {full_name} ({user_id}) - Break: {break_type} - Missing {actions['OUT'] - actions['BACK']} 'BACK' log(s).")

    if not found_missing:
        print("✅ All breaks were properly logged.")
    print(f"{'='*50}\n")


async def _send_individual_summaries(df: pd.DataFrame, context: ContextTypes.DEFAULT_TYPE):
    """Sends each user a summary of their breaks for the day."""
    unique_users = df['User ID'].unique()

    for user_id in unique_users:
        user_df = df[df['User ID'] == user_id]
        full_name = user_df['Full Name'].iloc[0]
        report_date = str(user_df['Timestamp'].iloc[0]).split()[0]

        total_time = user_df[user_df['Break Type'] != '🚻 WC']['Duration (minutes)'].sum()

        summary_df = user_df[user_df['Action'] == 'BACK'].groupby('Break Type').agg(
            count=('Break Type', 'size'),
            total_duration=('Duration (minutes)', 'sum')
        ).to_dict('index')

        summary_text = f"📊 **Your Daily Break Summary**\n\n"
        summary_text += f"👤 {full_name}\n"
        summary_text += f"📅 Date: {report_date}\n\n"

        summary_text += "**Break Details:**\n"
        if not summary_df:
            summary_text += "No breaks completed for this day.\n"
        else:
            for break_type, stats in summary_df.items():
                summary_text += f"• {break_type}: {stats['count']} time(s) - {stats['total_duration']:.1f} min\n"

        summary_text += f"\n⏱️ **Total Break Time (excluding WC):** {total_time:.1f} minutes\n"

        try:
            await context.bot.send_message(chat_id=user_id, text=summary_text, parse_mode='Markdown')
        except Exception as e:
            print(f"Failed to send daily summary to {user_id}: {e}")


async def init_excel_sync():
    """Initialize Excel Online sync if configured."""
    if EXCEL_SYNC_AVAILABLE:
        try:
            handler = get_excel_handler()
            if handler.enabled:
                success = await handler.initialize()
                if success:
                    print("✅ Excel Online sync initialized")
                else:
                    print("⚠️ Excel Online sync failed to initialize")
            else:
                print("ℹ️ Excel Online sync disabled (set EXCEL_SYNC_ENABLED=true)")
        except Exception as e:
            print(f"⚠️ Excel Online sync error: {e}")


def main():
    """Start the bot"""
    print("\n" + "="*60)
    print("🤖 CSR Break Time Tracker Bot - Production Mode")
    print("🕐 Timezone: Philippine Time (UTC+8)")
    print("="*60)

    init_database_structure()

    # Load active sessions from database (restores state after restart)
    load_active_sessions_from_db()

    # Note: Excel Online sync will be initialized when first used (lazy init)
    # This avoids event loop conflicts with the Telegram bot
    if EXCEL_SYNC_AVAILABLE:
        print("ℹ️ Excel Online sync module loaded (will init on first use)")

    application = Application.builder().token(BOT_TOKEN).build()

    job_queue = application.job_queue
    job_queue.run_repeating(check_break_reminders, interval=60, first=0)
    print("✅ Break reminder system activated (checks every 60 seconds)")

    # Run daily reports at midnight PH time (00:00)
    job_queue.run_daily(run_end_of_day_reports, time=time(0, 0), job_kwargs={'misfire_grace_time': 30})
    print(f"✅ Daily report system scheduled (runs at midnight PH time)")
    print(f"✅ Reports will be sent to GROUP_CHAT_ID: {GROUP_CHAT_ID}")
    print("="*60)

    conv_handler = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_callback, pattern='^O1$')],
        states={
            WAITING_FOR_REASON: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_reason)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        per_message=False
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('menu', menu))
    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(button_callback))
    application.add_handler(CommandHandler("b1", handle_break_command))
    application.add_handler(CommandHandler("b2", handle_break_command))
    application.add_handler(CommandHandler("w1", handle_break_command))
    application.add_handler(CommandHandler("w2", handle_break_command))
    application.add_handler(CommandHandler("p1", handle_break_command))
    application.add_handler(CommandHandler("p2", handle_break_command))
    application.add_handler(CommandHandler("o1", handle_break_command))
    application.add_handler(CommandHandler("o2", handle_break_command))

    print("\n🚀 Bot is now running...")
    print("📂 Database location:", DATABASE_DIR)
    print("📊 Today's log file:", get_daily_log_file())
    print(f"🕐 Current PH Time: {get_ph_time().strftime('%Y-%m-%d %H:%M:%S')}")
    print("\nPress Ctrl+C to stop the bot\n")
    print("="*60 + "\n")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
