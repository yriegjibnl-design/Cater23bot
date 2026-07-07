import os
import random
import sqlite3
import logging
import asyncio
import re
import json
import string
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# Try to import psycopg2 for PostgreSQL support; if unavailable, rely entirely on SQLite fallback
try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# ==========================================
# MAIN CORE BOT CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFqv00G_eAFkeP0x-UhrENKByEb5U5_MnM")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))
DATABASE_URL = os.getenv("DATABASE_URL", "")  # If set, automatically connects to PostgreSQL

DB_FILE = "club_tas.db"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==========================================
# UNIFIED DUAL DATABASE MANAGEMENT LAYER
# ==========================================
def get_db_connection():
    """
    Creates and returns a connection object. Supports PostgreSQL if DATABASE_URL
    is specified and available, otherwise seamlessly falls back to SQLite.
    """
    ssl_mode = os.getenv("DB_SSL_MODE", "allow")
    
    if DATABASE_URL and POSTGRES_AVAILABLE:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        try:
            conn = psycopg2.connect(url, sslmode=ssl_mode)
            return conn, True
        except Exception:
            logger.error("🔴 PostgreSQL Connection Failed", exc_info=True)
            raise
    else:
        try:
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            return conn, False
        except Exception:
            logger.error("🔴 SQLite Connection Failed", exc_info=True)
            raise
            
def execute_write(query, params=()):
    """Executes a write query (INSERT, UPDATE, DELETE) on the active database engine."""
    conn, is_pg = get_db_connection()
    if not is_pg:
        query = query.replace("%s", "?")
        
    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
        conn.commit()
        affected = cursor.rowcount
        return affected
    except Exception:
        logger.exception("🔴 Database write error")
        if conn:
            try:
                conn.rollback()
            except Exception:
                logger.exception("🔴 Rollback failed")
        return 0
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("🔴 Failed to close database connection")

def execute_read_one(query, params=()):
    """Executes a query and returns a single row as a dictionary format."""
    conn, is_pg = get_db_connection()
    if not is_pg:
        query = query.replace("%s", "?")
        
    cursor = None
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
            
        cursor.execute(query, params)
        row = cursor.fetchone()
        
        if row and not is_pg:
            return dict(row)
        return row
    except Exception:
        logger.exception("🔴 Database read one error")
        return None
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("🔴 Failed to close database connection in execute_read_one")

def execute_read_all(query, params=()):
    """Executes a query and returns all matching rows as a list of dictionaries."""
    conn, is_pg = get_db_connection()
    if not is_pg:
        query = query.replace("%s", "?")
        
    cursor = None
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
            
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not is_pg:
            return [dict(r) for r in rows]
        return rows
    except Exception:
        logger.exception("🔴 Database read all error")
        return []
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("🔴 Failed to close database connection in execute_read_all")

# Initialize tables structure across both database environments
def init_db_schema():
    """Initializes tables structure across both database environments"""
    conn, is_pg = get_db_connection()
    cursor = None
    try:
        cursor = conn.cursor()
        if is_pg:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id BIGINT PRIMARY KEY,
                username TEXT,
                score INTEGER DEFAULT 0,
                rank TEXT DEFAULT '🥉 Bronze I',
                title TEXT DEFAULT 'بدون لقب',
                title_expire TEXT,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                created_at TEXT,
                last_seen TEXT,
                unlocked_titles TEXT DEFAULT '[]',
                unlocked_perks TEXT DEFAULT '[]'
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_event (
                id SERIAL PRIMARY KEY,
                event_id INTEGER,
                event_name TEXT,
                end_time TEXT,
                extra_data TEXT,
                reward_type TEXT,
                reward_value TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS dice_history (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT,
                dice_value INTEGER,
                rolled_at TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS score_logs (
                telegram_id BIGINT,
                game_type TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (telegram_id, game_type)
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS shop (
                id SERIAL PRIMARY KEY,
                title_name TEXT UNIQUE,
                cost INTEGER,
                category TEXT,
                item_type TEXT DEFAULT 'title'
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                title_name TEXT,
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                duration_hours INTEGER
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS redeem_history (
                id SERIAL PRIMARY KEY,
                telegram_id BIGINT,
                code TEXT,
                used_at TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS offline_duels (
                duel_id TEXT PRIMARY KEY,
                creator_id BIGINT,
                wager INTEGER,
                rounds INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )""")
        else:
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                score INTEGER DEFAULT 0,
                rank TEXT DEFAULT '🥉 Bronze I',
                title TEXT DEFAULT 'بدون لقب',
                title_expire TEXT,
                wins INTEGER DEFAULT 0,
                losses INTEGER DEFAULT 0,
                draws INTEGER DEFAULT 0,
                total_games INTEGER DEFAULT 0,
                created_at TEXT,
                last_seen TEXT,
                unlocked_titles TEXT DEFAULT '[]',
                unlocked_perks TEXT DEFAULT '[]'
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_event (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id INTEGER,
                event_name TEXT,
                end_time TEXT,
                extra_data TEXT,
                reward_type TEXT,
                reward_value TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS dice_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                dice_value INTEGER,
                rolled_at TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS score_logs (
                telegram_id INTEGER,
                game_type TEXT,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (telegram_id, game_type)
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS shop (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title_name TEXT UNIQUE,
                cost INTEGER,
                category TEXT,
                item_type TEXT DEFAULT 'title'
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS redeem_codes (
                code TEXT PRIMARY KEY,
                title_name TEXT,
                max_uses INTEGER,
                current_uses INTEGER DEFAULT 0,
                duration_hours INTEGER
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS redeem_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id INTEGER,
                code TEXT,
                used_at TEXT
            )""")
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS offline_duels (
                duel_id TEXT PRIMARY KEY,
                creator_id INTEGER,
                wager INTEGER,
                rounds INTEGER,
                status TEXT DEFAULT 'pending',
                created_at TEXT
            )""")
            
        if conn:
            conn.commit()
    except Exception:
        logger.exception("🔴 Database schema initialization failed")
        raise
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("🔴 Failed to close database connection in init_db_schema")

# Initialize core configurations and structures
init_db_schema()

# Seed advanced custom store items into the repository database seamlessly
def seed_shop_items():
    """Seeds advanced custom store items into the repository database seamlessly."""
    items = [
        ("دوئل ۵ تا راند", 2000, "legendary", "perk_rounds"),
        ("XP سقف شرط +۵۰", 3500, "legendary", "perk_wager"),
        ("تاس شانس", 5000, "legendary", "perk_luckydice"),
        ("گلادیاتور نوپا", 200, "normal", "title"),
        ("ولخرجی شب", 600, "epic", "title"),
        ("الماس برتر", 1200, "legendary", "title")
    ]
    
    conn, is_pg = get_db_connection()
    query = """
        INSERT INTO shop (title_name, cost, category, item_type)
        VALUES (%s, %s, %s, %s) ON CONFLICT (title_name) DO NOTHING
    """
    if not is_pg:
        query = query.replace("%s", "?")
        
    cursor = None
    try:
        cursor = conn.cursor()
        for name, cost, cat, itype in items:
            cursor.execute(query, (name, cost, cat, itype))
        if conn:
            conn.commit()
    except Exception:
        logger.exception("🔴 Failed to seed shop items")
    finally:
        if cursor:
            try:
                cursor.close()
            except Exception:
                pass
        if conn:
            try:
                conn.close()
            except Exception:
                logger.exception("🔴 Failed to close connection in seed_shop_items")

seed_shop_items()

# ==========================================
# LOGIC & SYSTEM RULES DEFINITIONS
# ==========================================
DICE_SCORES = {1: -5, 2: 5, 3: 10, 4: 15, 5: 25, 6: 40}
CAT_NAMES = {"normal": "لقب عادی", "epic": "لقب افسانه‌ای", "legendary": "لقب لجندری"}

DICE_MOTIVATIONS = {
    6: ["🔥 **شــــــــــش ملوووووووک! میدان نبرد به آتش کشیده شد!**", "😎 شش چرخ روزگار به کامت چرخید! فوق‌العاده بود!"],
    5: ["⚡ **بسیار عالی! شانس با تو همراهه جنگجو!**", "💪 یک پرتاب قدرتمند و بی‌نقص!"],
    4: ["👍 **خوب و مطمئن! قدم به قدم به پیروزی نزدیک‌تر میشی.**", "🛡️ پرتابی محکم برای حفظ موقعیت!"],
    3: ["😐 **معمولی و متوسط... می‌تونست خیلی بهتر باشه!**", "💫 ششانس وسط زمین ایستاده، پرتاب بعدی رو محکم‌تر بزن!"],
    2: ["🤏 **امتیاز کمی بود! بوی بدشانسی میاد...**", "🌪️ تاس موافقی نبود، ولی غمت نباشه جنگجو!"],
    1: ["💀 **تاس کفتار گریبان‌گیرت شد! سقوط آزاد امتیاز!**", "❌ تاس کفتار تمام نقشه‌هات رو نقش بر آب کرد!"]
}

EVENT_NAMES_LIST = {
    1: "امتیاز دو برابر (Double XP) ⚡",
    2: "تاس شانس اختصاصی 🎲",
    3: "تاس معکوس و دیوانه‌وار 🃏",
    7: "تاس شانسی ناشناس (مخفی) 🎰",
    8: "پادشاه تپه (میدان دوئل) 👑",
    14: "انتقام خونین در کلوب 🩸",
    15: "جمعه سیاه بازارچه (تخفیف ویژه) 🛒",
    22: "چالش روزانه گلادیاتورها 🎯"
}

# In-memory states trackers
USER_DICE_COUNT = {}
USER_DUEL_COUNT = {}
USER_MUTE_TIMEOUT = {}
DUEL_COOLDOWNS = {}
ADMIN_STATES = {}
PV_DUEL_STATES = {}

def calculate_rank(score):
    """Calculates and returns the user's rank title based on their current score."""
    RANKS = [
        (14000, "🌌 Infinity"),
        (10000, "🏆 Grandmaster"),
        (7000, "💎 Diamond"),
        (4000, "🥇 Gold"),
        (1500, "🥈 Silver")
    ]
    
    for limit, title in RANKS:
        if score >= limit:
            return title
            
    return "🥉 Bronze I"

def is_user_admin(telegram_id):
    return int(telegram_id) == INITIAL_ADMIN_ID

def get_top_10_ids():
    """Retrieves the Telegram IDs of the top 10 users ranked by score and total games."""
    rows = execute_read_all("SELECT telegram_id FROM users ORDER BY score DESC, total_games DESC LIMIT 10")
    if not rows:
        return []
    return [int(r['telegram_id']) for r in rows]

def get_or_create_user(telegram_id, username):
    """Retrieves an existing user record or automatically creates a new profile safely."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    raw_user = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    
    if not raw_user:
        execute_write("""
            INSERT INTO users (telegram_id, username, score, rank, title, created_at, last_seen, unlocked_titles, unlocked_perks)
            VALUES (%s, %s, 0, '🥉 Bronze I', 'بدون لقب', %s, %s, '[]', '[]')
        """, (telegram_id, username, now_str, now_str))
        raw_user = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    else:
        execute_write("UPDATE users SET last_seen = %s, username = %s WHERE telegram_id = %s", (now_str, username, telegram_id))
    
    if not raw_user:
        return None
        
    user = dict(raw_user)
    top_10 = get_top_10_ids()
    if int(telegram_id) in top_10:
        user['title'] = "GOD OF DICE"
        
    return user
    
def update_stats(telegram_id, score_change, match_result):
    """Updates user game statistics, score, and rank safely after a match concludes."""
    raw_user = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    if not raw_user:
        return None
        
    user = dict(raw_user)
    current_score = int(user.get('score', 0))
    
    # Custom rule for high rank match results
    if current_score >= 10000:
        if match_result == 'win':
            score_change = 80
        elif match_result == 'loss':
            score_change = -100
            
    new_score = current_score + score_change
    if new_score > 14000:
        new_score = 14000
    elif new_score < 0:
        new_score = 0
        
    new_rank = calculate_rank(new_score)
    rank_changed = (new_rank != user.get('rank'))
    
    w_inc = 1 if match_result == 'win' else 0
    l_inc = 1 if match_result == 'loss' else 0
    d_inc = 1 if match_result == 'draw' else 0
    g_inc = 1 if match_result in ['win', 'loss', 'draw'] else 0
    
    try:
        execute_write("""
            UPDATE users 
            SET score = %s, rank = %s, wins = wins + %s, losses = losses + %s, draws = draws + %s, total_games = total_games + %s 
            WHERE telegram_id = %s
        """, (new_score, new_rank, w_inc, l_inc, d_inc, g_inc, telegram_id))
    except Exception:
        logger.exception(f"🔴 Failed to update stats for user {telegram_id}")
        return None
        
    return {
        "rank_changed": rank_changed,
        "new_rank": new_rank,
        "score": new_score
    }

def get_top_players():
    """Retrieves and formats the top 10 users with custom titles for the leaderboard."""
    rows = execute_read_all("SELECT * FROM users ORDER BY score DESC, total_games DESC LIMIT 10")
    if not rows:
        return []
        
    top_10_ids = [int(r['telegram_id']) for r in rows]
    formatted_rows = []
    
    for r in rows:
        user_dict = dict(r)
        if int(user_dict['telegram_id']) in top_10_ids:
            user_dict['title'] = "GOD OF DICE"
        formatted_rows.append(user_dict)
        
    return formatted_rows

def log_score_source(telegram_id, game_type):
    """Logs or increments the game play count per type for analytical tracking safely."""
    try:
        execute_write("""
            INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1)
            ON CONFLICT (telegram_id, game_type) DO UPDATE SET count = score_logs.count + 1
        """, (telegram_id, game_type))
    except Exception:
        logger.exception(f"🔴 Failed to log score source for user {telegram_id}")

def get_main_menu_keyboard():
    """Generates the main persistent reply keyboard markup for users."""
    keyboard = [
        [KeyboardButton("👤 پروفایل من"), KeyboardButton("🎲 پرتاب تاس")],
        [KeyboardButton("🏆 تالار افتخارات"), KeyboardButton("🛍️ بازارچه لقب")],
        [KeyboardButton("ℹ️ راهنمای کلوب")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==========================================
# SPAM DETECTION & MUTE SECURITY CORE
# ==========================================
import time

async def check_spam_and_mute(update: Update, action_type: str) -> bool:
    """Detects spam behavior from users and temporarily mutes them if limits are exceeded."""
    user_id = update.effective_user.id
    now = time.time()
    
    if user_id in USER_MUTE_TIMEOUT:
        if now < USER_MUTE_TIMEOUT[user_id]:
            return False
        else:
            del USER_MUTE_TIMEOUT[user_id]
            USER_DICE_COUNT[user_id] = 0
            USER_DUEL_COUNT[user_id] = 0
            
    if action_type == "dice":
        USER_DICE_COUNT[user_id] = USER_DICE_COUNT.get(user_id, 0) + 1
        USER_DUEL_COUNT[user_id] = 0
        if USER_DICE_COUNT[user_id] >= 10:
            USER_MUTE_TIMEOUT[user_id] = now + 120
            await update.message.reply_markdown(f"💀 **وضعیت سکوت!**\nکاربر @{update.effective_user.username or user_id} به دلیل اسپم تاس به مدت ۲ دقیقه جریمه شد.")
            return False
            
    elif action_type == "duel":
        USER_DUEL_COUNT[user_id] = USER_DUEL_COUNT.get(user_id, 0) + 1
        USER_DICE_COUNT[user_id] = 0
        if USER_DUEL_COUNT[user_id] >= 10:
            USER_MUTE_TIMEOUT[user_id] = now + 120
            await update.message.reply_markdown(f"💀 **وضعیت سکوت دوئل!**\nکاربر @{update.effective_user.username or user_id} به دلیل اسپم دستورات دوئل به مدت ۲ دقیقه جریمه شد.")
            return False
            
    return True

def get_current_active_event():
    """Retrieves the latest live active event and handles its lifecycle and expiration safely."""
    ev_raw = execute_read_one("SELECT * FROM active_event ORDER BY id DESC LIMIT 1")
    if not ev_raw:
        return None
        
    ev = dict(ev_raw)
    try:
        # Flexible parsing to handle times with or without seconds
        time_str = ev['end_time'].strip()
        if len(time_str) == 16:  # YYYY-MM-DD HH:MM
            end_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M")
        else:
            end_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
            
        if datetime.now() > end_time:
            execute_write("DELETE FROM active_event WHERE id = %s", (ev['id'],))
            return None
        return ev
    except Exception:
        logger.exception("🔴 Failed to process active event timing lifecycle")
        return None

# ==========================================
# COMMAND HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /start triggered by user {update.effective_user.id}")
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    if context.args and context.args[0].startswith("oduel_"):
        token = context.args[0].replace("oduel_", "").strip()
        await process_offline_duel_link(update, context, token)
        return

    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"اینجا جایی نیست که با خواهش و تمنا امتیاز جمع کنی! اینجا کلوپ گلادیاتورهاست؛ "
        f"جایی که شانس فقط به شجاع‌ها رو می‌کنه و یک پرتاب اشتباه، می‌تونه تو رو به قعر جدول بفرسته! 💀\n\n"
        f"⚡ **تاس‌های عادلانه مستقر شدن، بازارچه تگ‌های جنگی آمادست و حریف‌ها دندون تیز کردن!**\n"
        f"دستت رو بذار روی دکمه، تاس رو پرتاب کن و ثابت کن شاهِ این میدونی یا فقط یه تماشاچی! 🔥"
    )
    
    ev = get_current_active_event()
    text_btn = "🕹️ بخش ایونت (فعال 🔥)" if ev else "🕹️ بخش ایونت"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text_btn, callback_data="user_check_event")]])
    
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())
    await update.message.reply_text("✨ جهت بررسی رویدادها و چالش‌های زنده کلوب دکمه زیر را لمس کنید:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sends the structured help and rules text to the user, including admin options if applicable."""
    logger.info(f"Command /help triggered by user {update.effective_user.id}")
    
    help_text = (
        "⚔️ **لیست فرمان‌های نبرد کلوپ تاس (آپدیت بزرگ)** ⚔️\n\n"
        "🎲 `/roll` یا پرتاب تاس — پرتاب تاس انفرادی (دارای شانس حمله بحرانی متوالی)\n"
        "⚔️ `/duel` — دوئل شرطی در گروه (حداکثر تا ۵ راند، شرط تا سقف ۵۰ امتیاز)\n"
        "🔗 `/offline_duel` — ایجاد لینک دوئل غیابی اختصاصی\n"
        "🛍️ `/shop` یا بازارچه لقب — خرید دسته‌بندی‌شده انواع تگ و لقب‌ها\n"
        "👤 `/profile` یا پروفایل من — نمایش کارنامه جنگی با احتساب مساوی‌ها همراه با ویترین لقب‌ها\n"
        "🏆 `/leaderboard` یا تالار افتخارات — جدول مشاهیر و ۱۰ گلادیاتور برتر کلوپ\n"
        "🎁 `/redeem` — فعال‌سازی کدهای هدیه و لقب‌های موقت ادمین"
    )
    
    if is_user_admin(update.effective_user.id):
        help_text += "\n\n⚙️ **کنسول پنل فوق پیشرفته اتاق فرماندهی:** — `/admin`"
        
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())
# ==========================================
# CRITICAL HIT MECHANICS & SOLO ROLLS
# ==========================================
def register_and_check_critical(telegram_id, current_dice):
    """Logs the thrown dice value into history and evaluates if the user hit a triple critical safely."""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        execute_write("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (%s, %s, %s)", (telegram_id, current_dice, now_str))
    except Exception:
        logger.exception(f"🔴 Failed to log dice history for user {telegram_id}")

    history = execute_read_all("""
        SELECT dice_value FROM dice_history 
        WHERE telegram_id = %s 
        ORDER BY rolled_at DESC LIMIT 3
    """, (telegram_id,))
    
    is_critical = False
    if history and len(history) == 3:
        try:
            # Safely accessing database dictionary elements
            h0 = dict(history[0])['dice_value']
            h1 = dict(history[1])['dice_value']
            h2 = dict(history[2])['dice_value']
            
            if h0 == h1 == h2:
                is_critical = True
                execute_write("DELETE FROM dice_history WHERE telegram_id = %s", (telegram_id,))
        except Exception:
            logger.exception(f"🔴 Error evaluating matrix logic for user {telegram_id}")
            
    return is_critical

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles the solo dice rolling command, including critical hits and lucky perks."""
    logger.info(f"Command /dice triggered by user {update.effective_user.id}")
    if not await check_spam_and_mute(update, "dice"): 
        return
        
    user_id = update.effective_user.id
    username_or_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    user_data = get_or_create_user(user_id, username_or_name)
    
    if not user_data:
        await update.message.reply_markdown("⚠️ **خطا در بارگذاری اطلاعات پروفایل!** لطفاً مجدداً تلاش کنید.")
        return
        
    top_10 = get_top_10_ids()
    display_title = "[GOD OF DICE]" if user_id in top_10 else user_data.get('title', 'بدون لقب')
    title_tag = f" [{display_title}]" if display_title != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value 
    
    perks_raw = user_data.get('unlocked_perks')
    perks = json.loads(perks_raw) if perks_raw else []
    
    if dice_value == 1 and "perk_luckydice" in perks:
        if int(user_data.get('score', 0)) < 10000:
            await asyncio.sleep(2)
            await update.message.reply_markdown("🎲 **آیتم تاس شانس فعال شد!** عدد ۱ آمد، مجدداً یک تاس دیگر به عنوان شانس مجدد پرتاب می‌شود...")
            dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
            dice_value = dice_msg.dice.value
        else:
            await update.message.reply_markdown("⚠️ *آیتم تاس شانس در رنک و لیگ‌های بالای ۱۰۰۰۰ کاپ غیرفعال می‌باشد!*")

        # Lines 722 - 767 Optimized Safely
    ev = get_current_active_event()
    ev_bonus_text = ""

    if ev:
        ev_id = ev.get('event_id')
        if ev_id == 1:
            base_score *= 2
            ev_bonus_text = "\n⚡️ **[ایونت امتیاز ۲ برابر فعال است]**"
        elif ev_id == 2:
            # Safe JSON/Dict unpacking to prevent dictionary loading crashes
            ex_data_raw = ev.get('extra_data')
            ex_data = json.loads(ex_data_raw) if isinstance(ex_data_raw, str) else (ex_data_raw or {})
            
            if dice_value == int(ex_data.get('dice', 0)):
                base_score += 30
                ev_bonus_text = f"\n🎯 **[امتیاز بونوس ۳۰+ ایونت شانس تاس]** ({dice_value})"
        elif ev_id == 3:
            if dice_value == 1:
                base_score = 40
            elif dice_value == 6:
                base_score = -10
            ev_bonus_text = "\n🔄 **[ایونت تاس معکوس فعال است! قوانین جابه‌جا شده‌اند]**"
        elif ev_id == 7:
            ev_bonus_text = "\n🕵️‍♂️ **[ایونت تاس مخفی! آمار نهایی پایان ایونت محاسبه می‌شود]**"

    is_critical = register_and_check_critical(user_id, dice_value)
    
    if is_critical:
        # Fixed the NoneType bug by safely short-circuiting the event dict check
        has_double_xp = ev and ev.get('event_id') == 1
        score_gained = (dice_value * 3) * 3 if not has_double_xp else ((dice_value * 3) * 3) * 2
        motivation = f"⚡️🔥 **CRITICAL HIT! حمله بحرانی رخ داد!!!** سه پرتاب متوالی روی عدد **{dice_value}** و امتیاز شما ۳ برابر ارتقا یافت!"
    else:
        score_gained = base_score
        # Safe global dictionary lookup for motivations based on dice value
        motivation_pool = DICE_MOTIVATIONS.get(dice_value, ["پرتاب موفقیت‌آمیز بود!"])
        motivation = random.choice(motivation_pool) if isinstance(motivation_pool, list) else motivation_pool

    mode_str = 'win' if score_gained >= 0 else 'loss'
    result = update_stats(user_id, score_gained, mode_str)
    log_score_source(user_id, "solo_roll")

    sign = "+" if score_gained >= 0 else ""
    response = (
        f"👤 **مبارز:** {user_data.get('username', 'نامشخص')}{title_tag}\n"
        f"🎲 **تاس:** [ {dice_value} ] \n"
        f"💬 {motivation}\n"
        f"🏆 **تغییرات امتیاز:** `{sign}{score_gained} XP`{ev_bonus_text}"
    )

    if result and result.get('rank_changed'):
        response += f"\n🎖 **تغییر رتبه به:** **{result.get('new_rank')}**"

    await update.message.reply_markdown(response, reply_markup=get_main_menu_keyboard())

# ==========================================
# GROUP & WAGER DUELS SYSTEM
# ==========================================
import time

async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Initiates a live multiplayer wager duel between two group members safely."""
    logger.info(f"Command /duel triggered by user {update.effective_user.id}")
    if not await check_spam_and_mute(update, "duel"): 
        return
        
    p1 = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل گروهی، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p2 = update.message.reply_to_message.from_user
    if p1.id == p2.id or p2.is_bot: 
        return

    now = time.time()
    if p1.id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1.id]:
        left = int(DUEL_COOLDOWNS[p1.id] - now)
        await update.message.reply_text(f"⏳ **محدودیت ترافیک سرور!** تا {left} ثانیه دیگر نمی‌توانی دوئل جدیدی استارت کنی.")
        return

    p1_data = get_or_create_user(p1.id, p1.username if p1.username else p1.first_name)
    p2_data = get_or_create_user(p2.id, p2.username if p2.username else p2.first_name)
    
    if not p1_data or not p2_data:
        await update.message.reply_text("⚠️ **خطا در برقراری ارتباط با دیتابیس نبرد!** لطفاً مجدداً فرمان را صادر کنید.")
        return

    p1_perks_raw = p1_data.get('unlocked_perks')
    perks = json.loads(p1_perks_raw) if p1_perks_raw else []

    rounds = 3
    wager = 0
    max_rounds = 20 if "perk_rounds" in perks else 6
    max_wager = 500 if "perk_wager" in perks else 50

    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            if rounds > max_rounds: rounds = max_rounds
        except ValueError: 
            pass
        
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                if wager > max_wager:
                    await update.message.reply_text(f"❌ **خطای بالانس شاپ!** سقف شرط‌بندی شما حداکثر **{max_wager} امتیاز** است.")
                    return
            except ValueError: 
                pass

    if wager > 0:
        p1_score = int(p1_data.get('score', 0))
        p2_score = int(p2_data.get('score', 0))
        
        if p1_score < wager:
            await update.message.reply_text(f"❌ امتیاز شما کافی نیست! موجودی شما: {p1_score} XP")
            return
        if p2_score < wager:
            await update.message.reply_text(f"❌ امتیاز حریف شما برای این شرط‌بندی کافی نیست! موجودی حریف: {p2_score} XP")
            return

    p1_name = p1.username if p1.username else p1.first_name
    p2_name = p2.username if p2.username else p2.first_name
    p1_msg_id = update.message.message_id
    p2_msg_id = update.message.reply_to_message.message_id

    wager_text = f"💰 **شرط نبرد:** {wager} XP (مجموعاً {wager * 2} امتیاز در وسط زمین!)\n" if wager > 0 else ""

    keyboard = [[
        InlineKeyboardButton("⚔️ قبول می‌کنم", callback_data=f"gduel_yes_{p1.id}_{p2.id}_{rounds}_{p1_msg_id}_{p2_msg_id}_{wager}"),
        InlineKeyboardButton("🏳️ نه", callback_data=f"gduel_no_{p2.id}")
    ]]
    
    await update.message.reply_markdown(
        f"⚔️ **درخواست دوئل گروهی!**\n\n👤 **شروع‌کننده:** {p1_name}\n🎯 **حریف:** {p2_name}\n🏁 **راند:** {rounds}\n{wager_text}\nآیا چالش را قبول می‌کنی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# OFFLINE DUEL INHERITANCE SYSTEM
# ==========================================
async def offline_duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates an offline/invitation duel link with safe score validation."""
    logger.info(f"Command /offline_duel triggered by user {update.effective_user.id}")
    
    # 1. Added spam protection for performance safety
    if not await check_spam_and_mute(update, "duel"): 
        return
        
    user_id = update.effective_user.id
    username_or_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    user_data = get_or_create_user(user_id, username_or_name)
    
    if not user_data:
        await update.message.reply_text("⚠️ **خطا در ارتباط با سرور بازی!** لطفاً مجدداً تلاش کنید.")
        return

    perks_raw = user_data.get('unlocked_perks')
    perks = json.loads(perks_raw) if perks_raw else []

    rounds = 3
    wager = 0
    max_rounds = 20 if "perk_rounds" in perks else 6
    max_wager = 500 if "perk_wager" in perks else 50

    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            if rounds > max_rounds: rounds = max_rounds
        except ValueError: 
            pass
            
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                if wager > max_wager:
                    await update.message.reply_text(f"❌ سقف شرط‌بندی شما {max_wager} XP می‌باشد.")
                    return
            except ValueError: 
                pass

    # 2. Defending against NoneType score values safely
    if wager > 0:
        user_score = int(user_data.get('score', 0))
        if user_score < wager:
            await update.message.reply_text(f"❌ امتیاز کافی برای شرط بندی ندارید! موجودی: {user_score} XP")
            return

        # === Continuation of offline_duel_command (Lines 917 - 935) ===
    token = "".join(random.choices(string.ascii_letters + string.digits, k=10))
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    execute_write("""
        INSERT INTO offline_duels (duel_id, creator_id, wager, rounds, status, created_at)
        VALUES (%s, %s, %s, %s, 'pending', %s)
    """, (token, user_id, wager, rounds, now_str))

    bot_info = await context.bot.get_me()
    duel_link = f"https://t.me/{bot_info.username}?start=oduel_{token}"
    
    response = (
        f"🔗 **لینک دوئل غیابی اختصاصی با موفقیت ساخته شد!**\n\n"
        f"🏁 تعداد راند: {rounds}\n"
        f"💰 مبلغ شرط: {wager} XP\n"
        f"📌 لینک را برای حریف خود بفرستید تا نبرد به صورت خودکار آغاز شود:\n\n"
        f"`{duel_link}`"
    )
    await update.message.reply_markdown(response)


# === Secure Implementation of process_offline_duel_link (Lines 936 - 971) ===
async def process_offline_duel_link(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    """Processes the incoming deep-linked offline duel invite safely with full balance checks."""
    user_id = update.effective_user.id
    user_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    user_data = get_or_create_user(user_id, user_name)
    
    if not user_data:
        await update.message.reply_text("⚠️ **خطای سیستم بازی!** اطلاعات شما در سرور نبرد یافت نشد.")
        return

    raw_duel = execute_read_one("SELECT * FROM offline_duels WHERE duel_id = %s", (token,))
    if not raw_duel:
        await update.message.reply_text("❌ لینک دوئل غیابی نامعتبر است یا پیدا نشد.")
        return
        
    duel = dict(raw_duel)
    if duel.get('status') != 'pending':
        await update.message.reply_text("❌ این لینک قبلاً استفاده شده و منقضی شده است.")
        return
        
    if int(duel.get('creator_id', 0)) == user_id:
        await update.message.reply_text("❌ شما نمی‌توانید با لینک خودتان وارد دوئل غیابی شوید!")
        return

    # SECURITY PATCH: Anti-cheat balance check for the opponent
    wager = int(duel.get('wager', 0))
    opponent_score = int(user_data.get('score', 0))
    if wager > 0 and opponent_score < wager:
        await update.message.reply_text(f"❌ **موجودی ناکافی!** امتیاز شما برای ورود به این شرط‌بندی کافی نیست.\n💰 شرط: {wager} XP | موجودی شما: {opponent_score} XP")
        return

    creator_id = duel.get('creator_id')
    raw_creator = execute_read_one("SELECT username FROM users WHERE telegram_id = %s", (creator_id,))
    creator_dict = dict(raw_creator) if raw_creator else {}
    creator_name = creator_dict.get('username') if creator_dict.get('username') else f"مبارز {creator_id}"
    
    keyboard = [[
        InlineKeyboardButton("⚔️ قبول نبرد و شروع خودکار", callback_data=f"oduel_accept_{token}"),
        InlineKeyboardButton("🏳️ رد نبرد", callback_data=f"oduel_reject_{token}")
    ]]
    
    wager_txt = f"💰 **مبلغ شرط نبرد:** {wager} XP\n" if wager > 0 else ""
    await update.message.reply_markdown(
        f"⚔️ **دعوت‌نامه دوئل غیابی اختصاصی!**\n\n"
        f"👤 **سازنده چالش:** {creator_name}\n"
        f"🏁 **تعداد راند:** {duel.get('rounds', 3)}\n"
        f"{wager_txt}"
        f"آیا آماده این چالش سرنوشت‌ساز هستی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# SHOWCASE / WARDROBE INTERFACE
# ==========================================
async def wardrobe_interface(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id=None):
    """Showcases the user's unlocked titles wardrobe with safe database checks."""
    query = update.callback_query
    user_id = target_user_id if target_user_id else update.effective_user.id
    
    raw_user_data = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (user_id,))
    user_data = dict(raw_user_data) if raw_user_data else {}
    
    # Safe JSON parsing for unlocked titles
    titles_raw = user_data.get('unlocked_titles')
    if isinstance(titles_raw, str):
        unlocked_titles = json.loads(titles_raw) if titles_raw else []
    else:
        unlocked_titles = titles_raw if isinstance(titles_raw, list) else []
        
    raw_shop_items = execute_read_all("SELECT title_name, category, item_type FROM shop")
    all_shop_items = [dict(item) for item in raw_shop_items] if raw_shop_items else []
    
    keyboard = []
    current_title = user_data.get('title', 'بدون لقب')
    
    # 1. Base Title Option Setup
    if current_title == 'بدون لقب':
        keyboard.append([InlineKeyboardButton("✅ بدون لقب (فعال)", callback_data="wardrobe_set_none")])
    else:
        keyboard.append([InlineKeyboardButton("🔓 بدون لقب", callback_data="wardrobe_set_none")])
        
    # 2. Dynamic Title Items Loop
    for item in all_shop_items:
        t_name = item.get('title_name')
        if not t_name:
            continue
            
        if t_name in unlocked_titles:
            if current_title == t_name:
                keyboard.append([InlineKeyboardButton(f"✅ {t_name} (فعال)", callback_data=f"wardrobe_active_{t_name}")])
            else:
                keyboard.append([InlineKeyboardButton(f"🔓 {t_name}", callback_data=f"wardrobe_select_{t_name}")])
        else:
            keyboard.append([InlineKeyboardButton(f"🔒 {t_name} (قفل)", callback_data=f"wardrobe_locked_{t_name}")])
            
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پروفایل", callback_data="wardrobe_back_profile")])
    
    text = "👑 **ویترین و صندوقچه اختصاصی لقب‌های شما**\nلقب مورد نظر خود را انتخاب کنید تا روی کارت عضویت شما فعال شود:"
    
    # 3. Safe message deliverer
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# LEADERS AND PROFILE CONTROLLERS
# ==========================================
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays the top 10 players leaderboard with secure dictionary lookups."""
    logger.info(f"Command /top triggered by user {update.effective_user.id}")
    top_players_raw = get_top_players()
    
    if not top_players_raw:
        msg = "📊 تالار افتخارات خالی است."
        if update.message: 
            await update.message.reply_text(msg)
        return msg, []
    
    top_players = [dict(p) for p in top_players_raw]
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    
    for index, player in enumerate(top_players):
        medals = "👑" if index == 0 else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        p_title = player.get('title', 'بدون لقب')
        title_tag = f" ({p_title})" if p_title != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player.get('username', 'نامشخص')}**{title_tag}\n  Rank: {player.get('rank', 'BRONZE')} | ⭐ {player.get('score', 0)} XP\n\n"
    
    leaderboard_text += "📢 *رنک‌های بالای ۷۰۰۰ و ۸۰۰۰ کاپ، سر ماه ریست شده و جوایز ویژه می‌گیرند!*"
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates the interactive player battle card safely."""
    logger.info(f"Command /profile or /rank triggered by user {update.effective_user.id}")
    user_id = update.effective_user.id
    
    raw_user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    user = dict(raw_user) if raw_user else {}
    
    total = int(user.get('total_games', 0))
    wins = int(user.get('wins', 0))
    win_rate = round((wins / total) * 100, 1) if total > 0 else 0
    
    top_10 = get_top_10_ids()
    display_title = "[GOD OF DICE]" if user_id in top_10 else user.get('title', 'بدون لقب')
    title_display = f"🏅 **لقب ویژه:** {display_title}" if display_title != 'بدون لقب' else "🏅 **لقب ویژه:** ندارد"
    
    profile_text = (
        f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
        f"👤 **نام جنگجو:** {user.get('username', 'نامشخص')}\n{title_display}\n"
        f"👑 **رتبه فعلی:** {user.get('rank', 'BRONZE')}\n💎 **کل امتیازات:** {user.get('score', 0)} XP\n\n"
        f"📊 **آمار جنگ‌ها:**\n⚔️ کل مسابقات: {total}\n"
        f"🟢 پیروزی: {wins}  |  🤝 مساوی: {user.get('draws', 0)}  |  🔴 شکست: {user.get('losses', 0)}\n🔥 **نرخ برد:** {win_rate}%\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    inline_kb = [[InlineKeyboardButton("👑 انتخاب لقب (ویترین)", callback_data="wardrobe_view")]]
    if update.message: 
        await update.message.reply_markdown(profile_text, reply_markup=InlineKeyboardMarkup(inline_kb))
    return profile_text

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renders the storefront including the new Special Battle Items menu button."""
    logger.info(f"Command /shop triggered by user {update.effective_user.id}")
    user_id = update.effective_user.id
    
    raw_user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    user = dict(raw_user) if raw_user else {}
    
    keyboard = [
        [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
        [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
        [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
        [InlineKeyboardButton("✨ آیتم‌های ویژه (مهمات نبرد)", callback_data="shopmain_cat_special")] # Added your 4th custom button here!
    ]
    
    if update.message:
        await update.message.reply_text(
            f"🏪 **به بازارچه لقب‌ها و مهمات خوش آمدی!**\n💰 موجودی شما: {user.get('score', 0)} XP\n\nدسته‌بندی مورد نظر خود را انتخاب کنید:", 
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
# ==========================================
# CALLBACKS INTERCEPTOR ENGINE
# ==========================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safely intercepts callback queries and processes live event view with accurate timers."""
    logger.info(f"Callback query received from user {update.effective_user.id}")
    query = update.callback_query
    data = query.data.split("_")
    chat_id = query.message.chat_id
    user_id = query.from_user.id

    if query.data == "user_check_event":
        ev = get_current_active_event()
        if not ev:
            await query.answer("❌ در حال حاضر هیچ ایونتی فعال نیست. منتظر اعلام ادمین‌ها باشید!", show_alert=True)
            return
        await query.answer()
        
        # Fixed critical timedelta bug using total_seconds() to handle multiple days properly
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        total_seconds = max(0, int((end_time - datetime.now()).total_seconds()))
        rem_h = total_seconds // 3600
        rem_m = (total_seconds % 3600) // 60
        
        # Safe JSON loading guards to prevent crashes if extra_data is missing or None
        extra_info = json.loads(ev['extra_data']) if ev.get('extra_data') else {}
        
        descriptions = {
            1: "امتیاز تمام فعالیت‌های شما شامل پرتاب تاس و بردها ۲ برابر محاسبه میشه! ⚡",
            2: f"شنیده‌ها حاکی از اونه که شانس تاس شماره {extra_info.get('dice', '?')} وحشتناک بالا رفته! 🎲",
            3: "قوانین برعکس شده رفیق! تاس ۱ بیشترین امتیاز رو داره و ۶ برات سقوط آزاد میاره! 🃏",
            7: "امتیاز تاس‌ها کاملاً مخفیه! بعد از پایان زمان ایونت جوایز بر اساس جدول اعطا میشه! 🎰",
            8: "رقابت وحشیانه سر بیشترین تعداد برد دوئل! پادشاه موقت تپه کیه؟ 👑",
            14: "وقت انتقامه! اگه حریفی که قبلاً تو رو برده شکست بدی، امتیازت دبل میشه! 🩸",
            15: f"تخفیف نجومی در بازارچه! قیمت همه تگ‌ها {extra_info.get('discount', '0')}% ریزش کرد! 🛒",
            22: "چالش مأموریتی گلادیاتورها فعال شد! وظایف محوله رو انجام بده تا غنیمت بگیری! 🎯"
        }
        
        r_type = ev.get('reward_type')
        r_val = ev.get('reward_value')
        reward_desc = "ندارد ❌"
        if r_type == "score": 
            reward_desc = f"💰 {r_val} امتیاز خالص (XP)"
        elif r_type == "tag": 
            reward_desc = f"🏷️ لقب انحصاری و موقت [ {r_val} ]"
        
        text = (
            f"🕹️ **پنجره اطلاعات ایونت زنده کلوب** 🕹️\n\n"
            f"🔥 **نام رویداد:** {ev.get('event_name', 'رویداد ویژه')}\n"
            f"📝 **توضیحات:** {descriptions.get(ev.get('event_id'), '')}\n\n"
            f"🎁 **پاداش نهایی ایونت:** {reward_desc}\n"
            f"⏳ **زمان باقی‌مانده:** {rem_h} ساعت و {rem_m} دقیقه"
        )
        await query.message.reply_text(text, parse_mode="Markdown")
        return

        # === 3. SECURE WARDROBE INTERACTION INTERCEPTOR ===
    if query.data == "wardrobe_view" or query.data == "wardrobe_back_profile":
        if query.data == "wardrobe_back_profile":
            await query.answer()
            raw_user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
            user = dict(raw_user) if raw_user else {}
            
            total = int(user.get('total_games', 0))
            wins = int(user.get('wins', 0))
            win_rate = round((wins / total) * 100, 1) if total > 0 else 0
            
            top_10 = get_top_10_ids()
            display_title = "[GOD OF DICE]" if user_id in top_10 else user.get('title', 'بدون لقب')
            title_display = f"🏅 **لقب ویژه:** {display_title}" if display_title != 'بدون لقب' else "🏅 **لقب ویژه:** ندارد"
            
            profile_text = (
                f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
                f"👤 **نام جنگجو:** {user.get('username', 'نامشخص')}\n{title_display}\n"
                f"👑 **رتبه فعلی:** {user.get('rank', 'BRONZE')}\n💎 **کل امتیازات:** {user.get('score', 0)} XP\n\n"
                f"📊 **آمار جنگ‌ها:**\n⚔️ کل مسابقات: {total}\n"
                f"🟢 پیروزی: {wins}  |  🤝 مساوی: {user.get('draws', 0)}  |  🔴 شکست: {user.get('losses', 0)}\n🔥 **نرخ برد:** {win_rate}%\n"
                f"━━━━━━━━━━━━━━━━━━━━"
            )
            inline_kb = [[InlineKeyboardButton("👑 انتخاب لقب (ویترین)", callback_data="wardrobe_view")]]
            await query.edit_message_text(profile_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(inline_kb))
        else:
            await query.answer()
            await wardrobe_interface(update, context)
        return

    if query.data == "wardrobe_set_none":
        execute_write("UPDATE users SET title = 'بدون لقب' WHERE telegram_id = %s", (user_id,))
        await query.answer("✅ لقب فعال شما با موفقیت حذف شد.", show_alert=True)
        await wardrobe_interface(update, context)
        return

    if data[0] == "wardrobe":
        action = data[1]
        target_title = "_".join(data[2:])
        if action == "locked":
            await query.answer("🔒 این لقب قفل است. می‌توانید آن را از بازارچه خریداری کنید!", show_alert=True)
        elif action == "select":
            execute_write("UPDATE users SET title = %s WHERE telegram_id = %s", (target_title, user_id))
            await query.answer(f"✅ لقب «{target_title}» روی مشخصات شما فعال شد.", show_alert=True)
            await wardrobe_interface(update, context)
        elif action == "active":
            await query.answer("✨ این لقب در حال حاضر فعال است.", show_alert=True)
        return

    # === 4. SECURE OFFLINE DUELS CONTROLLER ===
    if data[0] == "oduel":
        action = data[1]
        token = data[2]
        
        raw_duel = execute_read_one("SELECT * FROM offline_duels WHERE duel_id = %s", (token,))
        duel = dict(raw_duel) if raw_duel else {}
        
        if not duel or duel.get('status') != 'pending':
            await query.answer("❌ این چالش دیگر معتبر نیست.", show_alert=True)
            return
            
            if action == "reject":
                execute_write("UPDATE offline_duels SET status = 'rejected' WHERE duel_id = %s", (token,))
                await query.answer()
                await query.edit_message_text("❌ درخواست چالش دوئل غیابی رد شد.")
                return

            if action == "accept":
                p1_id = int(duel.get('creator_id', 0))
                p2_id = user_id
                wager = int(duel.get('wager', 0))
                rounds = int(duel.get('rounds', 3))

            
            p2_username = query.from_user.username if query.from_user.username else query.from_user.first_name
            get_or_create_user(p2_id, p2_username)
        
            # Fetch raw user data safely with guards
            raw_p1_chk = execute_read_one("SELECT score, username, unlocked_perks FROM users WHERE telegram_id = %s", (p1_id,))
            raw_p2_chk = execute_read_one("SELECT score, username, unlocked_perks FROM users WHERE telegram_id = %s", (p2_id,))
            
            p1_chk = dict(raw_p1_chk) if raw_p1_chk else {}
            p2_chk = dict(raw_p2_chk) if raw_p2_chk else {}
            
            if wager > 0:
                if not p1_chk or int(p1_chk.get('score', 0)) < wager:
                    await query.answer("❌ موجودی امتیاز سازنده چالش کافی نیست!", show_alert=True)
                    return
                if not p2_chk or int(p2_chk.get('score', 0)) < wager:
                    await query.answer("❌ موجودی امتیاز شما کافی نیست!", show_alert=True)
                    return

            execute_write("UPDATE offline_duels SET status = 'accepted' WHERE duel_id = %s", (token,))
            await query.answer()
            await query.edit_message_text("⚔️ **چالش پذیرفته شد! شبیه‌سازی دوئل غیابی آغاز می‌شود...**")
            
            p1_name = p1_chk.get('username', 'جنگجو ۱')
            p2_name = p2_chk.get('username', 'جنگجو ۲')
            
            # Extract Golden Dice Perk (Perk 1) status for both players
            p1_perks = json.loads(p1_chk.get('unlocked_perks')) if p1_chk.get('unlocked_perks') else []
            p2_perks = json.loads(p2_chk.get('unlocked_perks')) if p2_chk.get('unlocked_perks') else []
            
            p1_has_golden = "perk_luckydice" in p1_perks
            p2_has_golden = "perk_luckydice" in p2_perks
            
            p1_total, p2_total = 0, 0
            
            # Core Battle Simulator with Golden Dice Feature Injection
            for _ in range(rounds):
                # Player 1 Roll
                roll1 = random.randint(1, 6)
                if roll1 == 1 and p1_has_golden:
                    roll1 = random.randint(1, 6) # Reroll opportunity!
                p1_total += roll1
                
                # Player 2 Roll
                roll2 = random.randint(1, 6)
                if roll2 == 1 and p2_has_golden:
                    roll2 = random.randint(1, 6) # Reroll opportunity!
                p2_total += roll2
                
            ev = get_current_active_event()
            win_xp, lose_xp = 40, 5
            if ev and ev.get('event_id') == 1: 
                win_xp, lose_xp = 80, 10
                
            result_text = f"🏁 **نتیجه نهایی دوئل غیابی اختصاصی:**\n\n👤 {p1_name}: {p1_total} امتیاز تاس\n👤 {p2_name}: {p2_total} امتیاز تاس\n\n"
            
            if p1_total > p2_total:
                total_win = win_xp + wager
                total_lose = max(0, lose_xp - wager) # Defending against negative score leaks
                result_text += f"🏆 **برنده چالش:** {p1_name} (+{total_win} XP)\n🏅 بازنده: {p2_name} ({total_lose} XP)"
                update_stats(p1_id, total_win, 'win')
                update_stats(p2_id, total_lose, 'loss')
                log_score_source(p1_id, "offline_duel")
            elif p2_total > p1_total:
                total_win = win_xp + wager
                total_lose = max(0, lose_xp - wager) # Defending against negative score leaks
                result_text += f"🏆 **برنده چالش:** {p2_name} (+{total_win} XP)\n🏅 بازنده: {p1_name} ({total_lose} XP)"
                update_stats(p2_id, total_win, 'win')
                update_stats(p1_id, total_lose, 'loss')
                log_score_source(p2_id, "offline_duel")
            else:
                result_text += f"🤝 **نتیجه کاملاً مساوی شد! امتیازی تغییر نکرد.**"
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
                
            await context.bot.send_message(chat_id=chat_id, text=result_text)
            try:
                await context.bot.send_message(chat_id=p1_id, text=f"🔔 **یکی از لینک‌های دوئل غیابی شما انجام شد!**\n\n{result_text}")
            except: 
                pass
            return
                # === 5. SECURE PV DUEL INIT INTERCEPTOR ===
    if query.data == "pv_duel_start":
        if query.message.chat.type != "private":
            await query.answer("❌ این قابلیت فقط در پیوی ربات کار می‌کند!", show_alert=True)
            return
        await query.answer()
        PV_DUEL_STATES[user_id] = "WAITING_FOR_TARGET_NUMBER"
        await query.message.reply_text("🎯 **لطفاً شماره بازیکن مورد نظر خود را از لیست بالا وارد کنید (مثلاً عدد 1):**")
        return

    # === 6. SECURE PV DUEL BATTLE ENGINE WITH GOLDEN DICE INTERACTION ===
    if data[0] == "pvduel":
        action = data[1]
        p1_id = int(data[2])
        p2_id = int(data[3])
        
        if user_id != p2_id:
            await query.answer("❌ این درخواست برای شما نیست!", show_alert=True)
            return
            
        if action == "no":
            await query.answer()
            await query.edit_message_text("🏳️ شما درخواست دوئل را رد کردید.")
            try: 
                await context.bot.send_message(chat_id=p1_id, text=f"🏳️ درخواست دوئل شما توسط حریف رد شد.")
            except: 
                pass
            return
            
        if action == "yes":
            now = datetime.now().timestamp()
            if p1_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1_id]:
                await query.answer("❌ حریف در حال استراحت است.", show_alert=True)
                return
                
            await query.answer()
            await query.edit_message_text("⚔️ **دوئل آغاز شد! در حال پرتاب تاس‌ها...**")
            
            # Safe fetching for player usernames
            raw_p1 = execute_read_one('SELECT username, unlocked_perks FROM users WHERE telegram_id = %s', (p1_id,))
            raw_p2 = execute_read_one('SELECT username, unlocked_perks FROM users WHERE telegram_id = %s', (p2_id,))
            
            p1_dict = dict(raw_p1) if raw_p1 else {}
            p2_dict = dict(raw_p2) if raw_p2 else {}
            
            p1_name = p1_dict.get('username', f"مبارز {p1_id}")
            p2_name = p2_dict.get('username', f"مبارز {p2_id}")
            
            # Checking Golden Dice Perk (Perk 1) status
            p1_perks = json.loads(p1_dict.get('unlocked_perks')) if p1_dict.get('unlocked_perks') else []
            p2_perks = json.loads(p2_dict.get('unlocked_perks')) if p2_dict.get('unlocked_perks') else []
            p1_has_golden = "perk_luckydice" in p1_perks
            p2_has_golden = "perk_luckydice" in p2_perks

            p1_total, p2_total = 0, 0
            
            # --- Player 1 Live Turn ---
            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p1_id)
                    roll_val = d_msg.dice.value
                    
                    # Golden Dice Reroll Injection for Player 1
                    if roll_val == 1 and p1_has_golden:
                        await context.bot.send_message(chat_id=p1_id, text="✨ **پرک تاس طلایی فعال شد! چون ۱ آوردی، یه تاس دیگه برات پرتاب میشه...**")
                        d_msg = await context.bot.send_dice(chat_id=p1_id)
                        roll_val = d_msg.dice.value
                        
                    p1_total += roll_val
                    try: 
                        await context.bot.send_message(chat_id=p2_id, text=f"🎲 حریفت ({p1_name}) تاس انداخت و عدد 〖 {roll_val} 〗 اومد!")
                    except: 
                        pass
                except: 
                    pass
                await asyncio.sleep(0.5)
            await asyncio.sleep(3.5)
            
            # --- Player 2 Live Turn ---
            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p2_id)
                    roll_val = d_msg.dice.value
                    
                    # Golden Dice Reroll Injection for Player 2
                    if roll_val == 1 and p2_has_golden:
                        await context.bot.send_message(chat_id=p2_id, text="✨ **پرک تاس طلایی فعال شد! چون ۱ آوردی، یه تاس دیگه برات پرتاب میشه...**")
                        d_msg = await context.bot.send_dice(chat_id=p2_id)
                        roll_val = d_msg.dice.value
                        
                    p2_total += roll_val
                    try: 
                        await context.bot.send_message(chat_id=p1_id, text=f"🎲 حریفت ({p2_name}) تاس انداخت و عدد 〖 {roll_val} 〗 اومد!")
                    except: 
                        pass
                except: 
                    pass
                await asyncio.sleep(0.5)
            await asyncio.sleep(3.5)

            ev = get_current_active_event()
            win_xp, lose_xp = 40, 5
            if ev and ev.get('event_id') == 1: 
                win_xp, lose_xp = 80, 10

            summary_p1 = f"📊 **نتیجه نهایی دوئل پی‌وی:**\n\nتاس تو: `{p1_total}`\nتاس حریف: `{p2_total}`\n\n"
            summary_p2 = f"📊 **نتیجه نهایی دوئل پی‌وی:**\n\nتاس تو: `{p2_total}`\nتاس حریف: `{p1_total}`\n\n"

            if p1_total > p2_total:
                res_p1 = summary_p1 + f"🏆 پیروز شدید! (+{win_xp} XP)"
                res_p2 = summary_p2 + f"💀 شکست خوردید! (+{lose_xp} XP)"
                update_stats(p1_id, win_xp, 'win')
                update_stats(p2_id, lose_xp, 'loss')
            elif p2_total > p1_total:
                res_p1 = summary_p1 + f"💀 شکست خوردید! (+{lose_xp} XP)"
                res_p2 = summary_p2 + f"🏆 پیروز شدید! (+{win_xp} XP)"
                update_stats(p2_id, win_xp, 'win')
                update_stats(p1_id, lose_xp, 'loss')
            else:
                res_p1 = summary_p1 + f"🤝 مساوی شد!"
                res_p2 = summary_p2 + f"🤝 مساوی شد!"
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')

            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time
            DUEL_COOLDOWNS[p2_id] = finish_time
            
            try: 
                await context.bot.send_message(chat_id=p1_id, text=res_p1)
            except: 
                pass
            try: 
                await context.bot.send_message(chat_id=p2_id, text=res_p2)
            except: 
                pass
            return
        # === 7. SECURE GROUP DUEL BATTLE ENGINE WITH COOPERATIVE PERKS ===
    if data[0] == "gduel":
        action = data[1]
        if action == "no":
            await query.answer()
            if user_id != int(data[2]): 
                return
            await query.edit_message_text(f"🏳️ دوئل توسط حریف لغو شد.")
            return
            
        if action == "yes":
            p1_id, p2_id, rounds = int(data[2]), int(data[3]), int(data[4])
            p1_msg_id, p2_msg_id = int(data[5]), int(data[6])
            wager = int(data[7]) if len(data) > 7 else 0
            
            if user_id != p2_id: 
                await query.answer("❌ این درخواست دوئل برای شما ارسال نشده است!", show_alert=True)
                return
            
            # Safe fetching with rich dict structures
            raw_p1_chk = execute_read_one('SELECT score, username, unlocked_perks FROM users WHERE telegram_id = %s', (p1_id,))
            raw_p2_chk = execute_read_one('SELECT score, username, unlocked_perks FROM users WHERE telegram_id = %s', (p2_id,))
            
            p1_chk = dict(raw_p1_chk) if raw_p1_chk else {}
            p2_chk = dict(raw_p2_chk) if raw_p2_chk else {}
            
            if wager > 0:
                if not p1_chk or int(p1_chk.get('score', 0)) < wager:
                    await query.answer("❌ موجودی شروع‌کننده دوئل کافی نیست!", show_alert=True)
                    return
                if not p2_chk or int(p2_chk.get('score', 0)) < wager:
                    await query.answer("❌ موجودی شما برای تایید این شرط کافی نیست!", show_alert=True)
                    return
            
            now = datetime.now().timestamp()
            if p1_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1_id]:
                await query.answer("❌ محدودیت زمانی کول‌داون فعال است!", show_alert=True)
                return
            if p2_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p2_id]:
                await query.answer("❌ محدودیت زمانی کول‌داون فعال است!", show_alert=True)
                return
                
            await query.answer()
            await query.edit_message_text("⚔️ **نبرد گروهی تایید شد! بازی شروع می‌شود...**")
            
            p1_name = p1_chk.get('username', f"Player {p1_id}")
            p2_name = p2_chk.get('username', f"Player {p2_id}")

            # Checking Golden Dice Perk (Perk 1) status
            p1_perks = json.loads(p1_chk.get('unlocked_perks')) if p1_chk.get('unlocked_perks') else []
            p2_perks = json.loads(p2_chk.get('unlocked_perks')) if p2_chk.get('unlocked_perks') else []
            p1_has_golden = "perk_luckydice" in p1_perks
            p2_has_golden = "perk_luckydice" in p2_perks

            p1_total, p2_total = 0, 0
            
            # --- Round Rolling: Player 1 ---
            await context.bot.send_message(chat_id=chat_id, text=f"🎲 **در حال انداختن تاس برای بازیکن اول: {p1_name}**")
            await asyncio.sleep(1)
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
                roll_val = d.dice.value
                
                if roll_val == 1 and p1_has_golden:
                    await context.bot.send_message(chat_id=chat_id, text=f"✨ **تاس طلایی {p1_name} فعال شد! پرتاب مجدد...**")
                    d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
                    roll_val = d.dice.value
                    
                p1_total += roll_val
                await asyncio.sleep(2.5)
            await context.bot.send_message(chat_id=chat_id, text=f"📊 **مجموع امتیاز تاس‌های {p1_name}: {p1_total}**")
            
            await asyncio.sleep(1.5)

            # --- Round Rolling: Player 2 ---
            await context.bot.send_message(chat_id=chat_id, text=f"🎲 **در حال انداختن تاس برای بازیکن دوم: {p2_name}**")
            await asyncio.sleep(1)
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
                roll_val = d.dice.value
                
                if roll_val == 1 and p2_has_golden:
                    await context.bot.send_message(chat_id=chat_id, text=f"✨ **تاس طلایی {p2_name} فعال شد! پرتاب مجدد...**")
                    d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
                    roll_val = d.dice.value
                    
                p2_total += roll_val
                await asyncio.sleep(2.5)
            await context.bot.send_message(chat_id=chat_id, text=f"📊 **مجموع امتیاز تاس‌های {p2_name}: {p2_total}**")

            ev = get_current_active_event()
            win_xp, lose_xp = 40, 5
            if ev and ev.get('event_id') == 1: 
                win_xp, lose_xp = 80, 10

            result_text = f"🏁 **نتیجه نهایی دوئل گروهی:**\n\n👤 {p1_name}: {p1_total} امتیاز\n👤 {p2_name}: {p2_total} امتیاز\n\n"

            if p1_total > p2_total:
                total_win = win_xp + wager
                total_lose = max(0, lose_xp - wager)
                result_text += f"🏆 **برنده: {p1_name} (+{total_win} XP)**\n🏅 بازنده: {p2_name} ({total_lose} XP)"
                update_stats(p1_id, total_win, 'win')
                update_stats(p2_id, total_lose, 'loss')
                log_score_source(p1_id, "group_duel")
            elif p2_total > p1_total:
                total_win = win_xp + wager
                total_lose = max(0, lose_xp - wager)
                result_text += f"🏆 **برنده: {p2_name} (+{total_win} XP)**\n🏅 بازنده: {p1_name} ({total_lose} XP)"
                update_stats(p2_id, total_win, 'win')
                update_stats(p1_id, total_lose, 'loss')
                log_score_source(p2_id, "group_duel")
            else:
                result_text += f"🤝 **نتیجه مساوی شد! به هر دو بازیکن امتیازی اضافه نشد.**"
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
            
            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time
            DUEL_COOLDOWNS[p2_id] = finish_time
            await context.bot.send_message(chat_id=chat_id, text=result_text)
            return

# ==========================================
# ADVANCED STORES CALLBACK HANDLERS
# ==========================================
async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes category selections and premium perk/title purchases dynamically."""
    logger.info(f"Shop callback query received from user {update.effective_user.id}")
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    await query.answer()
    
    # 1. PROCESS CATEGORY VIEW (INCLUDING THE NEW SPECIAL PERKS HANDLER)
    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        
        # Checking if user requested the custom Special Perks Category
        if cat_type == "special":
            shop_items = [
                {"id": 9001, "title_name": "🎲 تاس طلایی ۱ (تاس مجدد)", "cost": 150, "item_type": "perk_luckydice"},
                {"id": 9002, "title_name": "⚔️ افزایش راند دوئل (۲۰ راند)", "cost": 600, "item_type": "perk_rounds"},
                {"id": 9003, "title_name": "💰 ارتقای سقف شرط (۲۰۰ امتیاز)", "cost": 600, "item_type": "perk_wager"}
            ]
        else:
            raw_items = execute_read_all("SELECT id, title_name, cost, item_type FROM shop WHERE category = %s", (cat_type,))
            shop_items = [dict(i) for i in raw_items] if raw_items else []
            
        if not shop_items:
            await query.edit_message_text("🔒 محصولی در این بخش موجود نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")]]))
            return
            
        ev = get_current_active_event()
        discount_pct = 0
        if ev and ev.get('event_id') == 15 and ev.get('extra_data'):
            try:
                discount_pct = int(json.loads(ev['extra_data']).get('discount', 0))
            except:
                discount_pct = 0

        keyboard = []
        for item in shop_items:
            final_cost = int(item.get('cost', 0))
            if discount_pct > 0 and cat_type != "special": # Discounts apply only to standard titles
                final_cost = int(final_cost * (100 - discount_pct) / 100)
            keyboard.append([InlineKeyboardButton(f"{item.get('title_name')} 💰 {final_cost} XP", callback_data=f"shopbuy_id_{item.get('id')}")])
            
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        cat_title = "مهمات نبرد (ویژه)" if cat_type == "special" else CAT_NAMES.get(cat_type, cat_type)
        await query.edit_message_text(f"🛍️ لیست لقب‌ها و آیتم‌های بخش: {cat_title}", reply_markup=InlineKeyboardMarkup(keyboard))
        
    # 2. MAIN STOREFRONT BACK NAVIGATION BUTTON (WITH SPECIAL PERKS INCLUDED)
    elif data == "shopmain_back" or data == "shop_main_menu":
        keyboard = [
            [InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
            [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
            [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")],
            [InlineKeyboardButton("✨ آیتم‌های ویژه (مهمات نبرد)", callback_data="shopmain_cat_special")]
        ]
        await query.edit_message_text("🏪 **بازارچه لقب‌ها و آیتم‌ها**", reply_markup=InlineKeyboardMarkup(keyboard))
        
    # 3. SECURE TRANSACTION ENGINE FOR PURCHASING TITLES OR SPECIAL PERKS
    elif data.startswith("shopbuy_id_"):
        item_id = int(data.split("_")[2])
        
        # Hardcoded dynamic interception for the 3 Special Perks
        if item_id == 9001:
            item = {"id": 9001, "title_name": "تاس طلایی ۱ (تاس مجدد)", "cost": 150, "item_type": "perk_luckydice"}
        elif item_id == 9002:
            item = {"id": 9002, "title_name": "افزایش راند دوئل (۲۰ راند)", "cost": 600, "item_type": "perk_rounds"}
        elif item_id == 9003:
            item = {"id": 9003, "title_name": "ارتقای سقف شرط (۲۰۰ امتیاز)", "cost": 600, "item_type": "perk_wager"}
        else:
            raw_item = execute_read_one("SELECT * FROM shop WHERE id = %s", (item_id,))
            item = dict(raw_item) if raw_item else {}
            
        if not item: 
            return
        
        final_cost = int(item.get('cost', 0))
        ev = get_current_active_event()
        # Discounts only apply to regular items, not our custom virtual items
        if ev and ev.get('event_id') == 15 and item_id < 9000 and ev.get('extra_data'):
            try:
                pct = int(json.loads(ev['extra_data']).get('discount', 0))
                final_cost = int(final_cost * (100 - pct) / 100)
            except:
                pass

        raw_user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
        user = dict(raw_user) if raw_user else {}
        user_score = int(user.get('score', 0))
        
        if user_score < final_cost:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ امتیاز کافی نداری مشتی!")
            return
            
        new_score = user_score - final_cost
        
        # Safe JSON decoding guards
        titles_raw = user.get('unlocked_titles')
        if isinstance(titles_raw, str):
            unlocked_titles = json.loads(titles_raw) if titles_raw else []
        else:
            unlocked_titles = titles_raw if isinstance(titles_raw, list) else []
            
        perks_raw = user.get('unlocked_perks')
        if isinstance(perks_raw, str):
            unlocked_perks = json.loads(perks_raw) if perks_raw else []
        else:
            unlocked_perks = perks_raw if isinstance(perks_raw, list) else []
        
        i_type = item.get('item_type', 'title')
        i_name = item.get('title_name', 'آیتم ویژه')
        
        if i_type != 'title':
            if i_type not in unlocked_perks:
                unlocked_perks.append(i_type)
            execute_write('UPDATE users SET score = %s, unlocked_perks = %s WHERE telegram_id = %s', (new_score, json.dumps(unlocked_perks), user_id))
            await query.edit_message_text(f"🎉 قابلیت ویژه « {i_name} » فعال و به حساب شما متصل شد!")
        else:
            if i_name not in unlocked_titles:
                unlocked_titles.append(i_name)
            execute_write('UPDATE users SET score = %s, title = %s, unlocked_titles = %s WHERE telegram_id = %s', (new_score, i_name, json.dumps(unlocked_titles), user_id))
            await query.edit_message_text(f"🎉 تگ ویژه « {i_name} » فعال و به کمد افتخارات شما اضافه شد!")
# ==========================================
# MESSAGES MONITORING & STATE ROUTING
# ==========================================async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Safely processes text inputs, dashboard syncs, and PV duel targets with structural guards."""
    if not update.message or not update.message.text: 
        return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    # === 1. SECURE ADMIN LEADERBOARD SYNCHRONIZER ===
    if is_user_admin(user_id) and ("تالار مشاهیر" in text or "۱۰ گلادیاتور برتر" in text) and "XP" in text:
        lines = text.split("\n")
        current_username = None
        updated_count = 0
        for line in lines:
            user_match = re.search(r'(?:\d+\.\s*|👑|⚡|🛡️|🎖️)\s*([A-Za-z0-9_]+)', line)
            if user_match: 
                current_username = user_match.group(1).strip()
            score_match = re.search(r'(?:⭐\s*|\b)(\d+)\s*XP', line)
            if score_match and current_username:
                score_val = int(score_match.group(1))
                rank_val = calculate_rank(score_val)
                
                # Wrapped query result into a secure dict lookup guard
                raw_check = execute_read_one("SELECT 1 FROM users WHERE username = %s", (current_username,))
                user_check = dict(raw_check) if raw_check else {}
                
                if user_check:
                    execute_write("UPDATE users SET score = %s, rank = %s WHERE username = %s", (score_val, rank_val, current_username))
                else:
                    fake_id = -random.randint(1000000, 9999999)
                    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    execute_write("""
                        INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen, unlocked_titles, unlocked_perks) 
                        VALUES (%s, %s, %s, %s, %s, %s, '[]', '[]')
                    """, (fake_id, current_username, score_val, rank_val, now_str, now_str))
                updated_count += 1
                current_username = None
                
        if updated_count > 0:
            await update.message.reply_text(f"✅ آمار {updated_count} کاربر بازیابی و ثبت شد.")
            return

    # === 2. SAFE USER AUTO-REGISTRATION ===
    p_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    get_or_create_user(user_id, p_name)

    # === 3. REPLY KEYBOARD NAVIGATION DISPATCHER ===
    if text == "🎲 پرتاب تاس": 
        await dice_command(update, context)
        return
    elif text == "👤 پروفایل من": 
        await profile_command(update, context)
        return
    elif text == "🏆 تالار افتخارات": 
        await top_command(update, context)
        return
    elif text == "🏪 بازارچه لقب": 
        await shop_command(update, context)
        return
    elif text == "ℹ️ راهنمای کلوب": 
        await help_command(update, context)
        return

    # === 4. SECURE PV DUEL TARGET ACQUISITION SYSTEM ===
    if user_id in PV_DUEL_STATES and PV_DUEL_STATES[user_id] == "WAITING_FOR_TARGET_NUMBER":
        del PV_DUEL_STATES[user_id]
        try:
            selection = int(text)
            if selection < 1 or selection > 10: 
                raise ValueError
        except ValueError:
            await update.message.reply_text("❌ عدد نامعتبر است!")
            return
            
        top_players = get_top_players()
        if selection > len(top_players):
            await update.message.reply_text("❌ این شماره وجود ندارد!")
            return
            
        # Standardizing dictionary access via .get() methods safely
        target_player = dict(top_players[selection - 1]) if top_players[selection - 1] else {}
        target_id = target_player.get('telegram_id')
        target_name = target_player.get('username', 'نامشخص')
        
        if not target_id:
            await update.message.reply_text("❌ خطایی در بازخوانی اطلاعات بازیکن رخ داد!")
            return
        if target_id == user_id:
            await update.message.reply_text("❌ نمی‌توانی به خودت درخواست بدهی!")
            return
            
        keyboard = [[
            InlineKeyboardButton("⚔️ قبول نبرد", callback_data=f"pvduel_yes_{user_id}_{target_id}"),
            InlineKeyboardButton("🏳️ رد درخواست", callback_data=f"pvduel_no_{user_id}_{target_id}")
        ]]
        try:
            await context.bot.send_message(chat_id=target_id, text=f"⚔️ درخواست دوئل پیوی از طرف @{p_name}", reply_markup=InlineKeyboardMarkup(keyboard))
            await update.message.reply_markdown(f"🚀 درخواست برای @{target_name} فرستاده شد.")
        except: 
            await update.message.reply_text("❌ امکان ارسال پیام به حریف مقدور نبود!")
        return

        # === 5. SECURE ADMIN FSM EVENT CONFIGURATION INTERCEPTOR ===
    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        
        # --- Config State: Fetch Dice Number for Lucky Dice Event ---
        if state.startswith("EV_GET_DICE_"):
            try:
                ev_id = int(state.split("_")[3])
            except (IndexError, ValueError):
                ev_id = 2 # Safe fallback
                
            try:
                dice_num = int(text)
                if dice_num < 1 or dice_num > 6: 
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ فقط عدد ۱ تا ۶ وارد کنید!")
                return
                
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_{dice_num}"
            await update.message.reply_text("🕒 حالا مدت زمان این ایونت را به **ساعت** وارد کنید (مثلاً 4):")
            return

        # --- Config State: Fetch Discount Percent for Shop Sale Event ---
        elif state.startswith("EV_GET_DISCOUNT_"):
            try:
                ev_id = int(state.split("_")[3])
            except (IndexError, ValueError):
                ev_id = 15 # Safe fallback
                
            try:
                disc = max(1, min(100, int(text))) # Confining discount range between 1% and 100%
            except ValueError:
                await update.message.reply_text("❌ درصد تخفیف معتبر نیست! لطفاً یک عدد وارد کنید:")
                return
                
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_{disc}"
            await update.message.reply_text("🕒 حالا مدت زمان این ایونت را به **ساعت** وارد کنید (مثلاً 12):")
            return

        # --- Config State: Fetch Total Hours & Finalize Metadata ---
        elif state.startswith("EV_GET_HOURS_"):
            parts = state.split("_")
            try:
                ev_id = int(parts[3])
                param = parts[4] if len(parts) > 4 else "0"
            except (IndexError, ValueError):
                await update.message.reply_text("❌ خطایی در خواندن اطلاعات استیت رخ داد. فرآیند لغو شد.")
                del ADMIN_STATES[user_id]
                return
                
            try:
                hours = float(text)
                if hours <= 0: 
                    raise ValueError
            except ValueError:
                await update.message.reply_text("❌ مقدار ساعت نامعتبر است! لطفاً یک عدد بزرگتر از صفر وارد کنید:")
                return
            
            # Interactive Reward Verification for specific Event IDs
            if ev_id in [7, 8, 22]:
                ADMIN_STATES[user_id] = f"EV_ASK_REWARD_{ev_id}_{hours}_{param}"
                kb = [
                    [
                        InlineKeyboardButton("آره 🎁", callback_data=f"evrew_yes_{ev_id}_{hours}_{param}"),
                        InlineKeyboardButton("نه ❌", callback_data=f"evrew_no_{ev_id}_{hours}_{param}")
                    ]
                ]
                await update.message.reply_text("🎁 آیا می‌خواهید برای پایان زمان این ایونت پاداش اتوماتیک بگذارید؟", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await finalize_and_broadcast_event(update, context, ev_id, hours, param, "none", "")
            return

                # --- Config State: Finalize Custom Reward Configurations ---
        elif state.startswith("EV_VAL_REWARD_"):
            parts = state.split("_")
            try:
                ev_id = int(parts[3])
                hours = float(parts[4])
                param = parts[5]
                rew_type = parts[6]
            except (IndexError, ValueError):
                await update.message.reply_text("❌ خطا در تحلیل ساختار پاداش رویداد!")
                del ADMIN_STATES[user_id]
                return
            await finalize_and_broadcast_event(update, context, ev_id, hours, param, rew_type, text)
            return

        # --- Admin Action: Safe Global Broadcast Mechanism ---
        elif state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            raw_rows = execute_read_all('SELECT telegram_id FROM users')
            rows = [dict(r) for r in raw_rows] if raw_rows else []
            
            await update.message.reply_text(f"📢 ارسال پیام همگانی به {len(rows)} کاربر آغاز شد...")
            for row in rows:
                t_id = row.get('telegram_id')
                if not t_id:
                    continue
                try: 
                    await context.bot.send_message(chat_id=int(t_id), text=f"📢 **اطلاعیه مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: 
                    continue
            await update.message.reply_text("✅ پیام همگانی با موفقیت برای تمامی کاربران فعال فرستاده شد.")

        # --- Admin Action: Wait for Username to Modify Scores ---
        elif state == "WAITING_FOR_CUSTOM_USER":
            clean_user = text.replace('@', '').strip()
            ADMIN_STATES[user_id] = f"SET_SCORE_VAL_{clean_user}"
            await update.message.reply_text(f"🔢 حالا مقدار امتیازی که می‌خواهی به @{clean_user} اختصاص دهی را وارد کن:")

        # --- Admin Action: Finalize Custom Score Updates ---
        elif state.startswith("SET_SCORE_VAL_"):
            target_username = state.replace("SET_SCORE_VAL_", "")
            del ADMIN_STATES[user_id]
            try: 
                target_score = int(text)
            except ValueError: 
                await update.message.reply_text("❌ امتیاز وارد شده باید یک عدد صحیح باشد!"); return
                
            new_rank = calculate_rank(target_score)
            changes = execute_write("UPDATE users SET score = %s, rank = %s WHERE username = %s", (target_score, new_rank, target_username))
            await update.message.reply_text(f"🚀 امتیاز کاربر @{target_username} تغییر کرد." if changes > 0 else "❌ کاربر یافت نشد یا تغییری ایجاد نشد.")

        # --- Admin Action: Completely Reset a Specific User Profile ---
        elif state == "WAITING_FOR_USERNAME_RESET":
            del ADMIN_STATES[user_id]
            target = text.replace("@", "").strip()
            changes = execute_write("UPDATE users SET score = 0, rank = '🥉 Bronze I', title = 'بدون لقب' WHERE username = %s", (target,))
            await update.message.reply_text("🧹 حساب کاربر صفر و مشخصاتش ریست شد." if changes > 0 else "❌ کاربر مورد نظر در سیستم پیدا نشد.")

        # --- Admin Action: Initialize Redeem Code Sequence ---
        elif state == "WAITING_FOR_REDEEM_CODE":
            clean_rc = text.strip()
            ADMIN_STATES[user_id] = f"REDEEM_TITLE_{clean_rc}"
            await update.message.reply_text("✨ نام تگ یا لقبی که با این ردیم‌کد اهدا می‌شود را ارسال کنید:")

        # --- Admin Action: Attach Title to Redeem Code ---
        elif state.startswith("REDEEM_TITLE_"):
            rc_code = state.replace("REDEEM_TITLE_", "")
            ADMIN_STATES[user_id] = f"REDEEM_USES_{rc_code}|||{text.strip()}"
            await update.message.reply_text("👥 تعداد دفعات مجاز استفاده را وارد کنید:")

        # --- Admin Action: Set Max Uses for Redeem Code ---
        elif state.startswith("REDEEM_USES_"):
            payload = state.replace("REDEEM_USES_", "")
            parts = payload.split("|||") if "|||" in payload else payload.split("_", 1)
            rc_code = parts[0]
            rc_title = parts[1] if len(parts) > 1 else "لقب هدیه"
            
            try: 
                rc_uses = int(text)
            except ValueError: 
                await update.message.reply_text("❌ لطفا یک عدد صحیح برای دفعات مجاز وارد کنید:")
                return
            ADMIN_STATES[user_id] = f"REDEEM_HOURS_{rc_code}|||{rc_title}|||{rc_uses}"
            await update.message.reply_text("⏱️ مدت زمان ماندگاری تگ روی پروفایل را به ساعت وارد کنید:")

        # --- Admin Action: Finalize and Store Redeem Code Configuration ---
        elif state.startswith("REDEEM_HOURS_"):
            payload = state.replace("REDEEM_HOURS_", "")
            parts = payload.split("|||")
            del ADMIN_STATES[user_id]
            
            try: 
                rc_code = parts[0]
                rc_title = parts[1]
                rc_uses = int(parts[2])
                rc_hours = int(text)
            except (IndexError, ValueError): 
                await update.message.reply_text("❌ خطا در پردازش متادیتای ردیم کد!"); return
                
            execute_write('INSERT INTO redeem_codes (code, title_name, max_uses, duration_hours) VALUES (%s, %s, %s, %s) ON CONFLICT(code) DO UPDATE SET title_name=EXCLUDED.title_name, max_uses=EXCLUDED.max_uses, duration_hours=EXCLUDED.duration_hours',
                          (rc_code, rc_title, rc_uses, rc_hours))
            await update.message.reply_text(f"✅ ردیم کد جدید با موفقیت ساخته شد:\n🔑 کد: `{rc_code}`\n🏅 تگ: {rc_title}\n👥 ظرفیت: {rc_uses} بار\n⏱️ انقضا: {rc_hours} ساعت")

        # --- Admin Action: Create New Shop Title Item ---
        elif state == "WAITING_FOR_SHOP_TITLE":
            clean_t = text.strip()
            ADMIN_STATES[user_id] = f"SHOP_CAT_{clean_t}"
            keyboard = [
                [InlineKeyboardButton("🥈 لقب عادی", callback_data=f"setcat_normal_{clean_t}")],
                [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data=f"setcat_epic_{clean_t}")],
                [InlineKeyboardButton("👑 لقب لجندری", callback_data=f"setcat_legendary_{clean_t}")]
            ]
            await update.message.reply_text("📂 دسته‌بندی لقب جدید را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

        # --- Admin Action: Commit Final Shop Item and Price Configuration ---
        elif state.startswith("SHOP_PRICE_"):
            payload = state.replace("SHOP_PRICE_", "")
            parts = payload.split("_", 1)
            new_title = parts[0]
            cat_type = parts[1] if len(parts) > 1 else "normal"
            
            del ADMIN_STATES[user_id]
            try: 
                price = int(text)
            except ValueError: 
                await update.message.reply_text("❌ قیمت وارد شده معتبر نیست!"); return
            try:
                execute_write("INSERT INTO shop (title_name, cost, category, item_type) VALUES (%s, %s, %s, 'title')", (new_title, price, cat_type))
                await update.message.reply_text(f"✅ لقب « {new_title} » با قیمت {price} XP به شاپ اضافه شد.")
            except: 
                await update.message.reply_text("❌ این تگ قبلاً در لیست کاتالوگ بازارچه ثبت شده است.")
        return

    # === 6. SECURE GLOBAL AUTO-REDEEM INLINE HOOK ===
    clean_code = text.replace("/redeem ", "").replace("/redeem", "").replace("/", "").strip()
    if clean_code:
        raw_cdata = execute_read_one('SELECT 1 FROM redeem_codes WHERE code = %s', (clean_code,))
        cdata = dict(raw_cdata) if raw_cdata else {}
        if cdata:
            context.args = [clean_code]
            await redeem_command(update, context)
            return

# ==========================================
# EVENT STRUCTURAL SCHEDULER PROTOCOLS
# ==========================================
async def finalize_and_broadcast_event(update, context, ev_id, hours, param, rew_type, rew_val):
    admin_id = update.effective_user.id
    if admin_id in ADMIN_STATES: del ADMIN_STATES[admin_id]
    
    end_time = datetime.now() + timedelta(hours=hours)
    end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")
    
    ex_data = {}
    if ev_id == 2: ex_data["dice"] = param
    if ev_id == 15: ex_data["discount"] = param
    
    execute_write("DELETE FROM active_event")
    execute_write("""
        INSERT INTO active_event (event_id, event_name, end_time, extra_data, reward_type, reward_value)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (ev_id, EVENT_NAMES_LIST[ev_id], end_time_str, json.dumps(ex_data), rew_type, rew_val))
    
    users = execute_read_all("SELECT telegram_id FROM users")
    
    msg_broadcast = (
        f"🚨 **رویداد فوق‌العاده و جدید کلوب آغاز شد!** 🚨\n\n"
        f"🎯 **ایونت:** {EVENT_NAMES_LIST[ev_id]}\n"
        f"🕒 **مدت زمان رویداد:** {hours} ساعت\n"
        f"🎁 **پاداش نهایی:** {rew_val if rew_type != 'none' else 'جوایز سیستمی و دبل'}\n\n"
        f" همین حالا با کلیک روی دکمه شیشه‌ای زیر، جزئیات قوانین و جوایز این رویداد را بررسی کنید! 👇"
    )
    
    context.chat_data["admin_net_active"] = True
    broadcast_markup = InlineKeyboardMarkup([[InlineKeyboardButton("🕹️ جزئیات رویداد زنده", callback_data="user_check_event")]])
    
    try: await context.bot.send_message(chat_id=update.effective_chat.id, text=msg_broadcast, reply_markup=broadcast_markup, parse_mode="Markdown")
    except: pass
    
    for u in users:
        try: await context.bot.send_message(chat_id=u['telegram_id'], text=msg_broadcast, reply_markup=broadcast_markup, parse_mode="Markdown")
        except: continue

# ==========================================
# EXPANSIVE PROMO CODE REDEMPTION SYSTEMS
# ==========================================
async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Processes gift code redemptions securely with data type conversion guards."""
    logger.info(f"Command /redeem triggered by user {update.effective_user.id}")
    user_id = update.effective_user.id
    
    if context.args:
        code = context.args[0].strip().lower()
    else:
        code = update.message.text.replace("/redeem ", "").replace("/redeem", "").strip().lower()

    if not code:
        await update.message.reply_text("❌ فرمت اشتباه است. مثال: `/redeem ARIA88` یا ارسال مستقیم خود کد کلمه‌ای.")
        return
        
    # Standardizing db result into a robust dictionary
    raw_cdata = execute_read_one('SELECT * FROM redeem_codes WHERE LOWER(code) = %s', (code,))
    cdata = dict(raw_cdata) if raw_cdata else {}
    
    current_uses = int(cdata.get('current_uses', 0))
    max_uses = int(cdata.get('max_uses', 0))
    title_name = cdata.get('title_name', '')
    duration_hours = int(cdata.get('duration_hours', 24))
    
    if not cdata or current_uses >= max_uses:
        await update.message.reply_text("❌ کد معتبر نیست یا منقضی شده است.")
        return
        
    hist = execute_read_one('SELECT 1 FROM redeem_history WHERE telegram_id = %s AND code = %s', (user_id, code))
    if hist: 
        await update.message.reply_text("❌ شما قبلاً این کد هدیه را استفاده کرده‌اید.")
        return
    
    # Safe user lookup with fallback parser guards
    raw_user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    user_data = dict(raw_user) if raw_user else {}
    
    titles_raw = user_data.get('unlocked_titles')
    if isinstance(titles_raw, str):
        unlocked_titles = json.loads(titles_raw) if titles_raw else []
    else:
        unlocked_titles = titles_raw if isinstance(titles_raw, list) else []
    
    if title_name and title_name not in unlocked_titles:
        unlocked_titles.append(title_name)
        
    expire_time = (datetime.now() + timedelta(hours=duration_hours)).strftime("%Y-%m-%d %H:%M:%S")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    execute_write('INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (%s, %s, %s)', (user_id, code, now_str))
    execute_write('UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = %s', (code,))
    execute_write('UPDATE users SET title = %s, title_expire = %s, unlocked_titles = %s WHERE telegram_id = %s', (title_name, expire_time, json.dumps(unlocked_titles), user_id))
    
    await update.message.reply_text(f"🎉 کد هدیه فعال شد و لقب موقت **{title_name}** به ویترین شما اضافه و فعال گردید.")
    return
# ==========================================
# ADMINISTRATIVE HEADQUARTERS ROOM CONTROL
# ==========================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Generates the interactive core control center panel for verified admins."""
    logger.info(f"Command /admin triggered by user {update.effective_user.id}")
    if not is_user_admin(update.effective_user.id): 
        return
        
    keyboard = [
        [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="admin_top")],
        [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("🔄 باز‌یابی پیام رنک", callback_data="admin_restore_msg")],
        [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score"), InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
        [InlineKeyboardButton("➕ افزودن تگ جدید به شاپ", callback_data="admin_add_shop"), InlineKeyboardButton("🔑 ساخت ردیم کد", callback_data="admin_make_redeem")],
        [InlineKeyboardButton("📊 رهگیری آمار امتیازگیری", callback_data="admin_check_logs")],
        [InlineKeyboardButton("🕹️ سیستم فوق پیشرفته مدیریت ایونت‌ها", callback_data="admin_events_root")],
        [InlineKeyboardButton("🔄 ریست و پایان تمام ایونت‌ها", callback_data="admin_reset_all_events")], 
        [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
    ]
    await update.message.reply_text("🛠 **اتاق فرمان مدیریت پیشرفته ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def admin_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles admin dashboard button callbacks securely with access restriction guards."""
    logger.info(f"Admin callback control triggered by user {update.effective_user.id}")
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    # Secure Fire-wall Guard: Authenticate admin permission for all button interactions
    if not is_user_admin(user_id):
        await query.answer("❌ شما دسترسی به این بخش مدیریت را ندارید!", show_alert=True)
        return
        
    await query.answer()
    
    # 1. PROCESSING SHOP TITLE CATEGORY SETTINGS (WITH EXTENDED CHAR SPLIT PROTECTION)
    if data.startswith("setcat_"):
        payload = data.replace("setcat_", "")
        parts = payload.split("_", 1)  # Limits splitting to 1 time to preserve strings with underscores
        try:
            cat_type = parts[0]
            title_name = parts[1]
        except IndexError:
            await query.edit_message_text("❌ ساختار شناسه کاتالوگ نامعتبر است.")
            return
            
        ADMIN_STATES[user_id] = f"SHOP_PRICE_{title_name}_{cat_type}"
        await query.edit_message_text(f"💰 قیمت لقب « {title_name} » را وارد کنید:")
        return

    # 2. EVENTS ROOT CATALOG DIRECTORY NAVIGATION
    if data == "admin_events_root":
        kb = []
        for ev_id, ev_name in EVENT_NAMES_LIST.items():
            kb.append([InlineKeyboardButton(ev_name, callback_data=f"ev_manage_{ev_id}")])
        kb.append([InlineKeyboardButton("⬅️ بازگشت به پنل ادمین", callback_data="admin_home")])
        await query.edit_message_text("🕹️ **منوی مدیریت فوق پیشرفته ایونت‌ها:**\nایونت مدنظر را جهت پیکربندی انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
        return

    # 3. INTERACTIVE INDIVIDUAL EVENT CONFIGURATION POP-UP
    if data.startswith("ev_manage_"):
        try:
            ev_id = int(data.split("_")[2])
        except (IndexError, ValueError):
            return
            
        kb = [
            [
                InlineKeyboardButton("بله، فعال شود ✅", callback_data=f"ev_trigger_yes_{ev_id}"),
                InlineKeyboardButton("لغو ❌", callback_data="admin_events_root")
            ]
        ]
        await query.edit_message_text(f"⚔️ آیا از فعال‌سازی رویداد **«{EVENT_NAMES_LIST.get(ev_id, 'ناشناس')}»** اطمینان دارید؟", reply_markup=InlineKeyboardMarkup(kb))
        return

    # 4. DISPATCH STATE MACHINE BASED ON SELECTED EVENT TYPE
    if data.startswith("ev_trigger_yes_"):
        try:
            ev_id = int(data.split("_")[3])
        except (IndexError, ValueError):
            return
            
        if ev_id == 2:
            ADMIN_STATES[user_id] = f"EV_GET_DICE_{ev_id}"
            await query.edit_message_text("🎯 شانس کدام تاس را می‌خواهی زیاد کنی? (عدد ۱ تا ۶ را به صورت متنی بفرست):")
        elif ev_id == 15:
            ADMIN_STATES[user_id] = f"EV_GET_DISCOUNT_{ev_id}"
            await query.edit_message_text("💰 درصد تخفیف شاپ را به عدد وارد کن (مثلاً 50):")
        else:
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_0"
            await update.effective_chat.send_message("🕒 مدت زمان ایونت را به **ساعت** وارد کنید (مثلاً 2 یا 24):")
        return

    # 5. POST-EVENT REWARD SEQUENCING PROMPTS
    if data.startswith("evrew_"):
        parts = data.split("_")
        try:
            choice = parts[1]
            ev_id = int(parts[2])
            hours = float(parts[3])
            param = parts[4]
        except (IndexError, ValueError):
            return
        
        if choice == "no":
            await finalize_and_broadcast_event(update, context, ev_id, hours, param, "none", "")
            await query.edit_message_text("✅ ایونت با موفقیت فعال و فرستاده شد.")
        else:
            kb = [
                [
                    InlineKeyboardButton("امتیاز (XP) 💰", callback_data=f"evtype_score_{ev_id}_{hours}_{param}"),
                    InlineKeyboardButton("تگ اختصاصی (Tag) 🏷️", callback_data=f"evtype_tag_{ev_id}_{hours}_{param}")
                ]
            ]
            await query.edit_message_text("🎁 نوع جایزه پایان رویداد را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
        return

        # 6. PROCESSING FINAL EVENT REWARD METADATA VALUE TYPES
    if data.startswith("evtype_"):
        parts = data.split("_")
        try:
            rew_type = parts[1]
            ev_id = int(parts[2])
            hours = float(parts[3])
            param = parts[4]
        except (IndexError, ValueError):
            return
        
        ADMIN_STATES[user_id] = f"EV_VAL_REWARD_{ev_id}_{hours}_{param}_{rew_type}"
        if rew_type == "score":
            await query.edit_message_text("🔢 مقدار امتیاز نهایی را بنویسید (مثلاً 500):")
        else:
            await query.edit_message_text("✨ نام تگ انحصاری پایان رویداد را بنویسید (مثلاً: 👑 سلطان دوئل):")
        return

    # 7. GLOBAL TERMINATION OF ACTIVE EVENT LIFECYCLES
    if data == "admin_reset_all_events":
        execute_write("DELETE FROM active_event")
        execute_write("UPDATE users SET title = 'بدون لقب', title_expire = NULL")
        await query.edit_message_text("🔄 **ریست با موفقیت انجام شد!**\n\nتمام ایونت‌های فعال به پایان رسیدند و تگ/لقب همه کاربران غیرفعال شد. آمار امتیازات، برد و باخت‌ها و رنک گلادیاتورها کاملاً محفوظ مانده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
        return

    # 8. RE-RENDERING ADMIN ROOT CONTROLS MAIN MENU
    if data == "admin_home":
        keyboard = [
            [InlineKeyboardButton("📊 لیست کاربران", callback_data="admin_users"), InlineKeyboardButton("🏆 تالار مشاهیر", callback_data="admin_top")],
            [InlineKeyboardButton("📢 پیام همگانی", callback_data="admin_broadcast"), InlineKeyboardButton("🔄 باز‌یابی پیام رنک", callback_data="admin_restore_msg")],
            [InlineKeyboardButton("🚀 ارتقا امتیاز دلخواه", callback_data="admin_set_score"), InlineKeyboardButton("🧹 صفر کردن امتیاز", callback_data="admin_reset_score")],
            [InlineKeyboardButton("➕ افزودن تگ جدید به شاپ", callback_data="admin_add_shop"), InlineKeyboardButton("🔑 ساخت ردیم کد", callback_data="admin_make_redeem")],
            [InlineKeyboardButton("📊 رهگیری آمار امتیازگیری", callback_data="admin_check_logs")],
            [InlineKeyboardButton("🕹️ سیستم فوق پیشرفته مدیریت ایونت‌ها", callback_data="admin_events_root")],
            [InlineKeyboardButton("🔄 ریست و پایان تمام ایونت‌ها", callback_data="admin_reset_all_events")],
            [InlineKeyboardButton("❌ بستن پنل", callback_data="admin_close")]
        ]
        await query.edit_message_text("🛠 **اتاق فرمان مدیریت پویای ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 9. FETCH TOP 15 RANKED USERS WITH CONVERSION GUARDS
    elif data == "admin_users":
        raw_users = execute_read_all('SELECT username, score, rank FROM users ORDER BY score DESC LIMIT 15')
        users_list = [dict(u) for u in raw_users] if raw_users else []
        
        txt = "📊 **آمار کاربران برتر:**\n\n"
        for idx, u in enumerate(users_list): 
            u_name = u.get('username', 'نامشخص')
            u_score = u.get('score', 0)
            u_rank = u.get('rank', '🥉 Bronze I')
            txt += f"{idx+1}. 👤 @{u_name} | ⭐ {u_score} XP | {u_rank}\n"
            
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
        return

    # 10. SAFE INLINE REDIRECT FOR LEADERBOARD OVERVIEWS
    elif data == "admin_top":
        # Dynamic fallback to prevent NoneType execution failures
        top_players = get_top_players()
        txt = "🏆 **جدول ۱۰ گلادیاتور برتر کلوب:**\n\n"
        for idx, p in enumerate(top_players[:10]):
            d_p = dict(p)
            txt += f"{idx+1}. @{d_p.get('username', 'نامشخص')} ━ {d_p.get('score', 0)} XP\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
        return

    elif data == "admin_restore_msg":
        restore_text = "🏆 نمونه پیام تالار مشاهیر جهت ریست و آپدیت خودکار دیتابیس بوسیله کپی..."
        await query.edit_message_text(restore_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
        return
        
    elif data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")
        return
        
    elif data == "admin_set_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_CUSTOM_USER"
        await query.edit_message_text("👤 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
        return
        
    elif data == "admin_reset_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_RESET"
        await query.edit_message_text("🧹 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
        return
        
    elif data == "admin_add_shop":
        ADMIN_STATES[user_id] = "WAITING_FOR_SHOP_TITLE"
        await query.edit_message_text("✨ نام تگ اختصاصی جدید را بفرستید:")
        return
        
    elif data == "admin_make_redeem":
        ADMIN_STATES[user_id] = "WAITING_FOR_REDEEM_CODE"
        await query.edit_message_text("🔑 لطفا کد کلمه‌ای ردیم کد مدنظرتان را ارسال کنید یا عبارت `رندم` را بفرستید:")
        return
        
    elif data == "admin_check_logs":
        ADMIN_STATES[user_id] = "WAITING_FOR_LOGS_ID"
        await query.edit_message_text("📊 لطفا آیدی عددی کاربر مورد نظر را بفرستید:")
        return
        
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")
        return

# === 11. SECURE ADMINISTRATIVE ANALYTICS QUERY GENERATOR ===
async def handle_admin_logs_input(update: Update, user_id, text):
    """Generates structured profile analytics reports including recent game logs."""
    try: 
        target_id = int(text)
    except ValueError: 
        await update.message.reply_text("❌ آیدی فرستاده شده باید تماماً عدد باشد!")
        return
        
    raw_logs = execute_read_all('SELECT game_type, count FROM score_logs WHERE telegram_id = %s', (target_id,))
    logs = [dict(l) for l in raw_logs] if raw_logs else []
    
    if not logs: 
        await update.message.reply_text("📊 هیچ سابقه یا لاگ امتیازی برای این آیدی ثبت نشده است.")
        return
        
    report = f"📊 **گزارش آماری دقیق برای آیدی `{target_id}`:**\n\n"
    for row in logs:
        gtype = row.get('game_type', '')
        gcount = row.get('count', 0)
        
        if gtype == "solo_roll":
            gname = "🎲 تاس انفرادی پی‌وی"
        elif gtype == "pv_duel":
            gname = "⚔️ نبرد دوئل انفرادی (PV)"
        elif gtype == "group_duel":
            gname = "💥 دوئل مبارزات گروهی"
        else:
            gname = f"🔹 بخش {gtype}"
            
        report += f"┌ {gname}\n└ 📊 تعداد دفعات شرکت: `{gcount}` بار\n\n"
        
    await update.message.reply_text(report, parse_mode="Markdown")

# ==========================================
# ASYNCHRONOUS POLLING CORE LIFECYCLE
# ==========================================
def main():
    """Initializes the bot engine with comprehensive secure command and callback routing."""
    if BOT_TOKEN == "YOUR_DEFAULT_TOKEN_IF_NOT_SET": 
        print("❌ خطای پیکربندی: BOT_TOKEN تنظیم نشده است!")
        return
        
    application = Application.builder().token(BOT_TOKEN).build()

    # 1. COMMAND REGISTRY
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("dice", dice_command))
    application.add_handler(CommandHandler("duel", duel_command))
    application.add_handler(CommandHandler("offline_duel", offline_duel_command))
    application.add_handler(CommandHandler("profile", profile_command))
    application.add_handler(CommandHandler("rank", profile_command))
    application.add_handler(CommandHandler("top", top_command))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CommandHandler("shop", shop_command))
    application.add_handler(CommandHandler("redeem", redeem_command))

    # 2. CALLBACK QUERY ROUTING (Pattern-based security)
    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|oduel_|user_check_event|wardrobe_)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(admin_|setcat_|ev_|evrew_|evtype_)"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^(shopmain_|shopbuy_)"))
    
    # 3. INTERMEDIATE TEXT PROCESSING FILTER (Anti-Spam & State Management)
    async def mid_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text: 
            return
            
        uid = update.effective_user.id
        txt = update.message.text.strip()
        p_username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
        
        # Ensure user exists in DB before any processing
        get_or_create_user(uid, p_username)
            
        # Prioritize Admin State Machine Inputs
        if uid in ADMIN_STATES:
            state = ADMIN_STATES[uid]
            if state == "WAITING_FOR_LOGS_ID":
                del ADMIN_STATES[uid]
                await handle_admin_logs_input(update, uid, txt)
                return
                
        # Forward to general message processor
        await monitor_messages_and_inputs(update, context)

    # Register message handler with text filter
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mid_filter))

    print("🚀 ربات فوق پیشرفته کلوب تاس همراه با قفل ضداسپم متوالی با موفقیت ران شد...")
    application.run_polling()
if __name__ == "__main__":
    main()
