import os
import sys
import random
import sqlite3
import logging
import asyncio
import re
import json
import string
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Union, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, CallbackQueryHandler, filters

# Try to import psycopg2 for PostgreSQL support; if unavailable, rely entirely on SQLite fallback
try:
    import psycopg2
    from psycopg2.extras import DictCursor, RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False

# ==========================================
# MAIN CORE BOT CONFIGURATION
# ==========================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8894117383:AAFqv00G_eAFkeP0x-UhrENKByEb5U5_MnM")
INITIAL_ADMIN_ID = int(os.getenv("ADMIN_ID", "7430881772"))
DATABASE_URL = os.getenv("DATABASE_URL", "")

DB_FILE = "club_tas.db"
OLD_DB_FILE = "game_database.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("ClubTasBot")

if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
    IS_POSTGRES = True
    logger.info("Database Mode: Production PostgreSQL detected.")
else:
    IS_POSTGRES = False
    logger.info(f"Database Mode: Local SQLite fallback detected. File: {DB_FILE}")

# ==========================================
# UNIFIED DUAL DATABASE MANAGEMENT LAYER
# ==========================================
def adapt_query(query_string: str) -> str:
    if IS_POSTGRES:
        return query_string.replace("?", "%s")
    return query_string.replace("%s", "?")

def get_db_connection():
    try:
        if DATABASE_URL and POSTGRES_AVAILABLE and IS_POSTGRES:
            url = DATABASE_URL
            if url.startswith("postgres://"):
                url = url.replace("postgres://", "postgresql://", 1)
            connection = psycopg2.connect(url, cursor_factory=DictCursor)
            connection.autocommit = False
            return connection, True
        else:
            connection = sqlite3.connect(DB_FILE)
            connection.row_factory = sqlite3.Row
            return connection, False
    except Exception as error:
        logger.critical(f"Fatal database connection error: {error}")
        raise error

def execute_write(query, params=()):
    conn, is_pg = get_db_connection()
    formatted_query = adapt_query(query)
    try:
        cursor = conn.cursor()
        cursor.execute(formatted_query, params)
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        return affected
    except Exception as e:
        logger.error(f"Database write error: {e}")
        conn.rollback()
        return 0
    finally:
        conn.close()

def execute_read_one(query, params=()):
    conn, is_pg = get_db_connection()
    formatted_query = adapt_query(query)
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
        cursor.execute(formatted_query, params)
        row = cursor.fetchone()
        cursor.close()
        if row and not is_pg:
            return dict(row)
        return row
    except Exception as e:
        logger.error(f"Database read one error: {e}")
        return None
    finally:
        conn.close()

def execute_read_all(query, params=()):
    conn, is_pg = get_db_connection()
    formatted_query = adapt_query(query)
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
        cursor.execute(formatted_query, params)
        rows = cursor.fetchall()
        cursor.close()
        if not is_pg:
            return [dict(r) for r in rows]
        return rows
    except Exception as e:
        logger.error(f"Database read all error: {e}")
        return []
    finally:
        conn.close()

# Initialize tables structure across both database environments
def init_db_schema():
    conn, is_pg = get_db_connection()
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
            unlocked_perks TEXT DEFAULT '[]',
            player_status VARCHAR(50) DEFAULT 'idle',
            current_duel_id TEXT DEFAULT NULL
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
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS infinity_rank (
            telegram_id BIGINT PRIMARY KEY,
            username TEXT,
            score INT,
            updated_at TEXT
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
            unlocked_perks TEXT DEFAULT '[]',
            player_status TEXT DEFAULT 'idle',
            current_duel_id TEXT DEFAULT NULL
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
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS infinity_rank (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            score INTEGER,
            updated_at TEXT
        )""")
    
    conn.commit()
    conn.close()

init_db_schema()

def seed_shop_items():
    items = [
        ("دوعل تا ۲۰ راند", 2000, "legendary", "perk_rounds"),
        ("سقف شرط ۵۰۰ XP", 3500, "legendary", "perk_wager"),
        ("تاس شانس", 5000, "legendary", "perk_luckydice"),
        ("گلادیاتور نوپا", 200, "normal", "title"),
        ("شکارچی شب", 600, "epic", "title"),
        ("الماس برتر", 1200, "legendary", "title")
    ]
    for name, cost, cat, itype in items:
        execute_write("""
            INSERT INTO shop (title_name, cost, category, item_type) 
            VALUES (%s, %s, %s, %s) ON CONFLICT (title_name) DO NOTHING
        """, (name, cost, cat, itype))

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

USER_DICE_COUNT = {}
USER_DUEL_COUNT = {}
USER_MUTE_TIMEOUT = {}
DUEL_COOLDOWNS = {}
ADMIN_STATES = {}
PV_DUEL_STATES = {}

def calculate_rank(score):
    if score >= 14000: return "🌌 Infinity"
    elif score >= 10000: return "🏆 Grandmaster"
    elif score >= 7000: return "💎 Diamond"
    elif score >= 4000: return "🥇 Gold"
    elif score >= 1500: return "🥈 Silver"
    else: return "🥉 Bronze I"

def is_user_admin(telegram_id):
    return int(telegram_id) == INITIAL_ADMIN_ID

def get_top_10_ids():
    rows = execute_read_all("SELECT telegram_id FROM users ORDER BY score DESC, total_games DESC LIMIT 10")
    return [int(r['telegram_id']) for r in rows]

def update_infinity_ranks():
    elite_players = execute_read_all("SELECT telegram_id, username, score FROM users ORDER BY score DESC LIMIT 10")
    execute_write("DELETE FROM infinity_rank;")
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for player in elite_players:
        execute_write(
            "INSERT INTO infinity_rank (telegram_id, username, score, updated_at) VALUES (%s, %s, %s, %s);",
            (player['telegram_id'], player['username'], player['score'], now_str)
        )

def check_and_remove_expired_titles(telegram_id: int) -> bool:
    record = execute_read_one("SELECT title_expire, title FROM users WHERE telegram_id = %s;", (telegram_id,))
    if record and record['title_expire']:
        try:
            expiration_threshold = datetime.strptime(record['title_expire'], "%Y-%m-%d %H:%M:%S")
            if datetime.now() > expiration_threshold:
                execute_write("UPDATE users SET title = 'بدون لقب', title_expire = NULL WHERE telegram_id = %s;", (telegram_id,))
                return True
        except ValueError:
            logger.error(f"Malformed textual timestamps for UID: {telegram_id}")
    return False

def get_or_create_user(telegram_id, username):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    check_and_remove_expired_titles(telegram_id)
    user = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    if not user:
        execute_write("""
            INSERT INTO users (telegram_id, username, score, rank, title, created_at, last_seen, unlocked_titles, unlocked_perks)
            VALUES (%s, %s, 0, '🥉 Bronze I', 'بدون لقب', %s, %s, '[]', '[]')
        """, (telegram_id, username, now_str, now_str))
        user = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    else:
        execute_write("UPDATE users SET last_seen = %s, username = %s WHERE telegram_id = %s", (now_str, username, telegram_id))
    
    top_10 = get_top_10_ids()
    if int(telegram_id) in top_10:
        user['title'] = "[GOD OF DICE]"
    return user

def update_stats(telegram_id, score_change, match_result):
    user = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (telegram_id,))
    if not user:
        return None
    
    current_score = user['score']
    if current_score >= 10000:
        if match_result == 'win':
            score_change = 80
        elif match_result == 'loss':
            score_change = -100
            
    new_score = current_score + score_change
    if new_score > 14000:
        new_score = 14000
    if new_score < 0:
        new_score = 0
        
    new_rank = calculate_rank(new_score)
    rank_changed = (new_rank != user['rank'])
    
    w_inc = 1 if match_result == 'win' else 0
    l_inc = 1 if match_result == 'loss' else 0
    d_inc = 1 if match_result == 'draw' else 0
    g_inc = 1 if match_result in ['win', 'loss', 'draw'] else 0
    
    execute_write("""
        UPDATE users 
        SET score = %s, rank = %s, wins = wins + %s, losses = losses + %s, draws = draws + %s, total_games = total_games + %s
        WHERE telegram_id = %s
    """, (new_score, new_rank, w_inc, l_inc, d_inc, g_inc, telegram_id))
    
    update_infinity_ranks()
    return {"rank_changed": rank_changed, "new_rank": new_rank, "score": new_score}

def get_top_players():
    rows = execute_read_all("SELECT * FROM users ORDER BY score DESC, total_games DESC LIMIT 10")
    top_10_ids = [int(r['telegram_id']) for r in rows]
    for idx, r in enumerate(rows):
        if int(r['telegram_id']) in top_10_ids:
            rows[idx]['title'] = "[GOD OF DICE]"
    return rows

def log_score_source(telegram_id, game_type):
    execute_write("""
        INSERT INTO score_logs (telegram_id, game_type, count) VALUES (%s, %s, 1)
        ON CONFLICT(telegram_id, game_type) DO UPDATE SET count = score_logs.count + 1
    """, (telegram_id, game_type))

def get_main_menu_keyboard():
    keyboard = [
        [KeyboardButton("🎲 پرتاب تاس"), KeyboardButton("👤 پروفایل من")],
        [KeyboardButton("🏆 تالار افتخارات"), KeyboardButton("🏪 بازارچه لقب")],
        [KeyboardButton("ℹ️ راهنمای کلوب")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ==========================================
# SPAM DETECTION & MUTE SECURITY CORE
# ==========================================
async def check_spam_and_mute(update: Update, action_type: str) -> bool:
    user_id = update.effective_user.id
    now = datetime.now().timestamp()
    
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
            await update.message.reply_markdown(f"💀 **وضعیت سکوت!**\nکاربر @{update.effective_user.username} به دلیل پرتاب متوالی ۱۰ تاس، به مدت **۲ دقیقه** از بازی محروم شد!")
            return False

    elif action_type == "duel":
        USER_DUEL_COUNT[user_id] = USER_DUEL_COUNT.get(user_id, 0) + 1
        USER_DICE_COUNT[user_id] = 0
        if USER_DUEL_COUNT[user_id] >= 10:
            USER_MUTE_TIMEOUT[user_id] = now + 120
            await update.message.reply_markdown(f"💀 **وضعیت سکوت دوئل!**\nکاربر @{update.effective_user.username} به دلیل ارسال ۱۰ درخواست دوئل رگباری، به مدت **۲ دقیقه** در لیست سیاه قرار گرفت!")
            return False

    return True

def get_current_active_event():
    ev = execute_read_one("SELECT * FROM active_event ORDER BY id DESC LIMIT 1")
    if not ev:
        return None
    try:
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        if datetime.now() > end_time:
            execute_write("DELETE FROM active_event")
            return None
        return ev
    except:
        return None

# ==========================================
# COMMAND HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username if user.username else user.first_name)
    
    if context.args and context.args[0].startswith("oduel_"):
        token = context.args[0].replace("oduel_", "").strip()
        await process_offline_duel_link(update, context, token)
        return

    welcome_text = (
        f"⚔️ **به قلمرو خونین و بی‌رحم «نبرد تاس» خوش آمدی، {user.first_name}!** ⚔️\n\n"
        f"اینجا جایی نیست که با خواهش و تمنا امتیاز جمع کنی! اینجا کلوپ گلادیاتورهاست؛\n\n"
        f"دستت رو بذار روی دکمه، تاس رو پرتاب کن و ثابت کن شاهِ این میدونی یا فقط یه تماشاچی! 🔥"
    )
    
    ev = get_current_active_event()
    text_btn = "🕹️ بخش ایونت (فعال 🔥)" if ev else "🕹️ بخش ایونت"
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text_btn, callback_data="user_check_event")]])
    
    await update.message.reply_markdown(welcome_text, reply_markup=get_main_menu_keyboard())
    await update.message.reply_text("✨ جهت بررسی رویدادها و چالش‌های زنده کلوب دکمه زیر را لمس کنید:", reply_markup=reply_markup)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی\n"
        "⚔️ `/duel [راند] [مقدار شرط]` — **دوئل شرطی در گروه**\n"
        "🔗 `/offline_duel [راند] [مقدار شرط]` — **ایجاد لینک دوئل غیابی اختصاصی**\n"
        "🏪 `🏪 بازارچه لقب` — خرید دسته‌بندی‌شده انواع تگ و لقب‌ها\n"
        "👤 `👤 پروفایل من` — نمایش کارنامه جنگی با احتساب مساوی‌ها همراه با ویترین لقب‌ها\n"
        "🏆 `🏆 تالار افتخارات` — جدول مشاهیر و ۱۰ گلادیاتور برتر کلوب\n"
        "🔑 `/redeem [کد]` — فعال‌سازی کدهای هدیه و لقب‌های موقت ادمین\n"
    )
    if is_user_admin(update.effective_user.id): 
        help_text += "\n⚙️ `/admin` — کنترل پنل فوق پیشرفته اتاق فرماندهی"
    await update.message.reply_markdown(help_text, reply_markup=get_main_menu_keyboard())

# ==========================================
# CRITICAL HIT MECHANICS & SOLO ROLLS
# ==========================================
def register_and_check_critical(telegram_id, current_dice):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    execute_write("INSERT INTO dice_history (telegram_id, dice_value, rolled_at) VALUES (%s, %s, %s)", (telegram_id, current_dice, now_str))
    
    history = execute_read_all("""
        SELECT dice_value FROM dice_history 
        WHERE telegram_id = %s 
        ORDER BY rolled_at DESC LIMIT 3
    """, (telegram_id,))
    
    is_critical = False
    if len(history) == 3:
        if history[0]['dice_value'] == history[1]['dice_value'] == history[2]['dice_value']:
            is_critical = True
            execute_write("DELETE FROM dice_history WHERE telegram_id = %s", (telegram_id,))
            
    return is_critical

async def dice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "dice"): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    top_10 = get_top_10_ids()
    display_title = "[GOD OF DICE]" if user_id in top_10 else user_data['title']
    title_tag = f" [{display_title}]" if display_title != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value
    
    perks = json.loads(user_data['unlocked_perks'] if user_data['unlocked_perks'] else '[]')
    if dice_value == 1 and "perk_luckydice" in perks:
        if user_data['score'] < 10000:
            await asyncio.sleep(2)
            await update.message.reply_markdown("🎲 **آیتم تاس شانس فعال شد!** عدد ۱ آمد، مجدداً یک تاس دیگر به عنوان شانس مجدد پرتاب می‌شود...")
            dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
            dice_value = dice_msg.dice.value
        else:
            await update.message.reply_markdown("⚠️ *آیتم تاس شانس در رنک و لیگ‌های بالای ۱۰۰۰۰ کاپ غیرفعال می‌باشد!*")

    await asyncio.sleep(3)
    base_score = DICE_SCORES[dice_value]
    
    ev = get_current_active_event()
    ev_bonus_text = ""
    
    if ev:
        ev_id = ev['event_id']
        if ev_id == 1: 
            base_score *= 2
            ev_bonus_text = "\n⚡ **[ایونت امتیاز ۲ برابر فعال است]**"
        elif ev_id == 2: 
            ex_data = json.loads(ev['extra_data'])
            if dice_value == int(ex_data.get('dice', 0)):
                base_score += 30
                ev_bonus_text = f"\n🎯 **[ایونت شانس تاس {dice_value}! +30 امتیاز بونوس]**"
        elif ev_id == 3: 
            if dice_value == 1: base_score = 40
            elif dice_value == 6: base_score = -10
            ev_bonus_text = "\n🃏 **[ایونت تاس معکوس فعال است!]**"

    is_critical = register_and_check_critical(user_id, dice_value)
    if is_critical:
        score_gained = (dice_value * 3) * 3 if not ev or ev['event_id'] != 1 else ((dice_value * 3) * 3) * 2
        motivation = f"⚡💥 **CRITICAL HIT! حمله بحرانی رخ داد!!!** 💥⚡"
    else:
        score_gained = base_score
        motivation = random.choice(DICE_MOTIVATIONS[dice_value])
    
    mode_str = 'win' if score_gained > 0 else 'loss'
    result = update_stats(user_id, score_gained, mode_str)
    log_score_source(user_id, "solo_roll")
    
    sign = "+" if score_gained >= 0 else ""
    response = (
        f"👤 **مبارز:** {user_data['username']}{title_tag}\n"
        f"🎲 **تاس:** 〖 **{dice_value}** 〗\n"
        f"📢 {motivation}\n"
        f"🏆 **تغییرات امتیاز:** {sign}{score_gained} XP{ev_bonus_text}"
    )
    if result and result["rank_changed"]: 
        response += f"\n🎖️ **تغییر رتبه به: {result['new_rank']}**"
    await update.message.reply_markdown(response, reply_markup=get_main_menu_keyboard())

# ==========================================
# GROUP & WAGER DUELS SYSTEM
# ==========================================
async def duel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await check_spam_and_mute(update, "duel"): return
    p1 = update.effective_user
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ برای شروع دوئل گروهی، باید این دستور را روی پیام حریف ریپلای کنید!")
        return

    p2 = update.message.reply_to_message.from_user
    now = datetime.now().timestamp()
    if p1.id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1.id]:
        left = int(DUEL_COOLDOWNS[p1.id] - now)
        await update.message.reply_text(f"⏳ **محدودیت ترافیک سرور!** تا {left} ثانیه دیگر نمی‌توانی دوئل جدیدی استارت کنی.")
        return

    if p1.id == p2.id or p2.is_bot: return

    p1_data = get_or_create_user(p1.id, p1.username if p1.username else p1.first_name)
    p2_data = get_or_create_user(p2.id, p2.username if p2.username else p2.first_name)
    perks = json.loads(p1_data['unlocked_perks'] if p1_data['unlocked_perks'] else '[]')

    rounds = 3
    wager = 0
    max_rounds = 20 if "perk_rounds" in perks else 6
    max_wager = 500 if "perk_wager" in perks else 50

    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            if rounds > max_rounds: rounds = max_rounds
        except ValueError: pass
        
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                if wager > max_wager:
                    await update.message.reply_text(f"❌ **خطای بالانس شاپ!** سقف شرط‌بندی شما حداکثر **{max_wager} امتیاز** است.")
                    return
            except ValueError: pass

    if wager > 0:
        if p1_data['score'] < wager:
            await update.message.reply_text(f"❌ امتیاز شما کافی نیست! موجودی شما: {p1_data['score']} XP")
            return
        if p2_data['score'] < wager:
            await update.message.reply_text(f"❌ امتیاز حریف شما برای این شرط‌بندی کافی نیست! موجودی حریف: {p2_data['score']} XP")
            return

    p1_name = p1.username if p1.username else p1.first_name
    p2_name = p2.username if p2.username else p2.first_name
    p1_msg_id = update.message.message_id
    p2_msg_id = update.message.reply_to_message.message_id

    wager_text = f"💰 **شرط نبرد:** {wager} XP\n" if wager > 0 else ""

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
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    perks = json.loads(user_data['unlocked_perks'] if user_data['unlocked_perks'] else '[]')

    rounds = 3
    wager = 0
    max_rounds = 20 if "perk_rounds" in perks else 6
    max_wager = 500 if "perk_wager" in perks else 50

    if context.args:
        try:
            rounds = int(context.args[0])
            if rounds < 1: rounds = 3
            if rounds > max_rounds: rounds = max_rounds
        except ValueError: pass
        if len(context.args) > 1:
            try:
                wager = int(context.args[1])
                if wager < 0: wager = 0
                if wager > max_wager:
                    await update.message.reply_text(f"❌ سقف شرط‌بندی شما {max_wager} XP می‌باشد.")
                    return
            except ValueError: pass

    if wager > 0 and user_data['score'] < wager:
        await update.message.reply_text(f"❌ امتیاز کافی برای شرط بندی ندارید! موجودی: {user_data['score']} XP")
        return

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
        f"`{duel_link}`"
    )
    await update.message.reply_markdown(response)

async def process_offline_duel_link(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user_id = update.effective_user.id
    user_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    user_data = get_or_create_user(user_id, user_name)
    
    duel = execute_read_one("SELECT * FROM offline_duels WHERE duel_id = %s", (token,))
    if not duel:
        await update.message.reply_text("❌ لینک دوئل غیابی نامعتبر است.")
        return
        
    if duel['status'] != 'pending':
        await update.message.reply_text("❌ این لینک منقضی شده است.")
        return
        
    if int(duel['creator_id']) == user_id:
        await update.message.reply_text("❌ شما نمی‌توانید با لینک خودتان وارد دوئل شوید!")
        return

    creator = execute_read_one("SELECT username FROM users WHERE telegram_id = %s", (duel['creator_id'],))
    creator_name = creator['username'] if creator else f"مبارز {duel['creator_id']}"
    
    keyboard = [[
        InlineKeyboardButton("⚔️ قبول نبرد", callback_data=f"oduel_accept_{token}"),
        InlineKeyboardButton("🏳️ رد نبرد", callback_data=f"oduel_reject_{token}")
    ]]
    
    wager_txt = f"💰 **مبلغ شرط نبرد:** {duel['wager']} XP\n" if duel['wager'] > 0 else ""
    await update.message.reply_markdown(
        f"⚔️ **دعوت‌نامه دوئل غیابی اختصاصی!**\n\n"
        f"👤 **سازنده چالش:** {creator_name}\n"
        f"🏁 **تعداد راند:** {duel['rounds']}\n"
        f"{wager_txt}"
        f"آیا آماده این چالش هستی؟",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ==========================================
# SHOWCASE / WARDROBE INTERFACE
# ==========================================
async def wardrobe_interface(update: Update, context: ContextTypes.DEFAULT_TYPE, target_user_id=None):
    query = update.callback_query
    user_id = target_user_id if target_user_id else update.effective_user.id
    user_data = execute_read_one("SELECT * FROM users WHERE telegram_id = %s", (user_id,))
    
    unlocked_titles = json.loads(user_data['unlocked_titles'] if user_data['unlocked_titles'] else '[]')
    all_shop_items = execute_read_all("SELECT title_name, category, item_type FROM shop")
    
    keyboard = []
    if user_data['title'] == 'بدون لقب':
        keyboard.append([InlineKeyboardButton("✅ بدون لقب (فعال)", callback_data="wardrobe_set_none")])
    else:
        keyboard.append([InlineKeyboardButton("🔓 بدون لقب", callback_data="wardrobe_set_none")])
        
    for item in all_shop_items:
        t_name = item['title_name']
        if t_name in unlocked_titles:
            if user_data['title'] == t_name:
                keyboard.append([InlineKeyboardButton(f"✅ {t_name} (فعال)", callback_data=f"wardrobe_active_{t_name}")])
            else:
                keyboard.append([InlineKeyboardButton(f"🔓 {t_name}", callback_data=f"wardrobe_select_{t_name}")])
        else:
            keyboard.append([InlineKeyboardButton(f"🔒 {t_name} (قفل)", callback_data=f"wardrobe_locked_{t_name}")])
            
    keyboard.append([InlineKeyboardButton("🔙 بازگشت به پروفایل", callback_data="wardrobe_back_profile")])
    
    text = "👑 **ویترین و صندوقچه اختصاصی لقب‌های شما**\nلقب مورد نظر خود را انتخاب کنید:"
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# LEADERS AND PROFILE CONTROLLERS
# ==========================================
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    top_players = get_top_players()
    if not top_players:
        if update.message: 
            await update.message.reply_text("📊 تالار افتخارات خالی است.")
        return "📊 تالار افتخارات خالی است.", []
    
    leaderboard_text = "🏆 **تالار مشاهیر و ۱۰ گلادیاتور برتر کلوب** 🏆\n\n"
    for index, player in enumerate(top_players):
        medals = "👑" if index == 0 else "⚡" if index == 1 else "🛡️" if index == 2 else "🎖️"
        title_tag = f" ({player['title']})" if player['title'] != 'بدون لقب' else ""
        leaderboard_text += f"{medals} {index + 1}. **{player['username']}**{title_tag}\n  Rank: {player['rank']} | ⭐ {player['score']} XP\n\n"
    
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها", callback_data="pv_duel_start")]]
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    win_rate = round((user['wins'] / user['total_games']) * 100, 1) if user['total_games'] > 0 else 0
    
    top_10 = get_top_10_ids()
    display_title = "[GOD OF DICE]" if user_id in top_10 else user['title']
    title_display = f"🏅 **لقب ویژه:** {display_title}" if display_title != 'بدون لقب' else "🏅 **لقب ویژه:** ندارد"
    
    profile_text = (
        f"🎮 ━━━ **کارت عضویت کلوب نبرد** ━━━ 🎮\n\n"
        f"👤 **نام جنگجو:** {user['username']}\n{title_display}\n"
        f"👑 **رتبه فعلی:** {user['rank']}\n💎 **کل امتیازات:** {user['score']} XP\n\n"
        f"📊 **آمار جنگ‌ها:**\n⚔️ کل مسابقات: {user['total_games']}\n"
        f"🟢 پیروزی: {user['wins']}  |  🤝 مساوی: {user['draws']}  |  🔴 شکست: {user['losses']}\n🔥 **نرخ برد:** {win_rate}%\n"
    )
    
    inline_kb = [[InlineKeyboardButton("👑 انتخاب لقب (ویترین)", callback_data="wardrobe_view")]]
    if update.message: 
        await update.message.reply_markdown(profile_text, reply_markup=InlineKeyboardMarkup(inline_kb))
    return profile_text

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
                [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
                [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")]]
    if update.message:
        await update.message.reply_text(f"🏪 **به بازارچه لقب‌ها خوش آمدی!**\n💰 موجودی: {user['score']} XP\n\nانتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text("❌ لطفاً کد هدیه را وارد کنید. مثال: /redeem GIFT100")
        return
    code = context.args[0].strip()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    voucher = execute_read_one("SELECT * FROM redeem_codes WHERE code = %s;", (code,))
    if not voucher:
        await update.message.reply_text("❌ کد هدیه نامعتبر یا منقضی شده است.")
        return
        
    already_used = execute_read_one("SELECT 1 FROM redeem_history WHERE telegram_id = %s AND code = %s;", (user_id, code))
    if already_used:
        await update.message.reply_text("❌ شما قبلاً از این کد هدیه استفاده کرده‌اید.")
        return
        
    if voucher['current_uses'] >= voucher['max_uses']:
        await update.message.reply_text("❌ ظرفیت استفاده از این کد هدیه به اتمام رسیده است.")
        return
        
    execute_write("UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = %s;", (code,))
    execute_write("INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (%s, %s, %s);", (user_id, code, now_str))
    
    duration = int(voucher['duration_hours'])
    expire_date_str = None
    if duration > 0:
        expire_date_str = (datetime.now() + timedelta(hours=duration)).strftime("%Y-%m-%d %H:%M:%S")
        
    execute_write("UPDATE users SET title = %s, title_expire = %s WHERE telegram_id = %s;", (voucher['title_name'], expire_date_str, user_id))
    
    # Save to unlocked list
    user_data = execute_read_one("SELECT unlocked_titles FROM users WHERE telegram_id = %s;", (user_id,))
    unlocked = json.loads(user_data['unlocked_titles'] if user_data['unlocked_titles'] else '[]')
    if voucher['title_name'] not in unlocked:
        unlocked.append(voucher['title_name'])
        execute_write("UPDATE users SET unlocked_titles = %s WHERE telegram_id = %s;", (json.dumps(unlocked), user_id))
        
    await update.message.reply_text(f"🎉 کد هدیه با موفقیت فعال شد! لقب [ {voucher['title_name']} ] به شما اعطا گردید.")

# ==========================================
# CALLBACKS INTERCEPTOR ENGINE
# ==========================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split("_")
    user_id = query.from_user.id

    if query.data == "user_check_event":
        ev = get_current_active_event()
        if not ev:
            await query.answer("❌ در حال حاضر هیچ ایونتی فعال نیست.", show_alert=True)
            return
        await query.answer()
        
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        rem = end_time - datetime.now()
        rem_h = rem.seconds // 3600
        rem_m = (rem.seconds % 3600) // 60
        
        text = f"🕹️ **پنجره اطلاعات ایونت زنده کلوب** 🕹️\n\n🔥 **نام رویداد:** {ev['event_name']}\n⏰ زمان باقی‌مانده: {rem_h} ساعت و {rem_m} دقیقه"
        await query.message.reply_text(text)
        return

    # Wardrobe Intercepts
    if data[0] == "wardrobe":
        await query.answer()
        if data[1] == "view":
            await wardrobe_interface(update, context, user_id)
        elif data[1] == "set" and data[2] == "none":
            execute_write("UPDATE users SET title = 'بدون لقب' WHERE telegram_id = %s", (user_id,))
            await query.message.reply_text("✅ لقب شما با موفقیت برداشته شد.")
        elif data[1] == "select":
            t_name = data[2]
            execute_write("UPDATE users SET title = %s WHERE telegram_id = %s", (t_name, user_id))
            await query.message.reply_text(f"✅ لقب [ {t_name} ] با موفقیت فعال شد.")
        elif data[1] == "back" and data[2] == "profile":
            await profile_command(update, context)
        return

    # Shop Category Intercepts
    if data[0] == "shopmain" and data[1] == "cat":
        await query.answer()
        cat = data[2]
        items = execute_read_all("SELECT * FROM shop WHERE category = %s", (cat,))
        keyboard = []
        for it in items:
            keyboard.append([InlineKeyboardButton(f"{it['title_name']} - {it['cost']} XP", callback_data=f"buyitem_{it['title_name']}_{it['cost']}_{it['item_type']}")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت به بازارچه", callback_data="back_shop")])
        await query.edit_message_text(f"🛒 لیست آیتم‌های دسته {CAT_NAMES.get(cat, cat)}:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if data[0] == "buyitem":
        await query.answer()
        item_name = data[1]
        cost = int(data[2])
        item_type = data[3]
        
        user = execute_read_one("SELECT score, unlocked_titles, unlocked_perks FROM users WHERE telegram_id = %s", (user_id,))
        if user['score'] < cost:
            await query.message.reply_text("❌ امتیاز شما برای خرید این آیتم کافی نیست.")
            return
            
        if item_type == "title":
            unlocked = json.loads(user['unlocked_titles'] if user['unlocked_titles'] else '[]')
            if item_name in unlocked:
                await query.message.reply_text("❌ شما این لقب را قبلاً خریداری کرده‌اید.")
                return
            unlocked.append(item_name)
            execute_write("UPDATE users SET score = score - %s, unlocked_titles = %s WHERE telegram_id = %s", (cost, json.dumps(unlocked), user_id))
        else:
            perks = json.loads(user['unlocked_perks'] if user['unlocked_perks'] else '[]')
            if item_name in perks:
                await query.message.reply_text("❌ شما این ارتقا را قبلاً خریداری کرده‌اید.")
                return
            perks.append(item_name)
            execute_write("UPDATE users SET score = score - %s, unlocked_perks = %s WHERE telegram_id = %s", (cost, json.dumps(perks), user_id))
            
        await query.message.reply_text(f"🎉 آیتم [ {item_name} ] با موفقیت خریداری شد!")
        return

    if query.data == "back_shop":
        await query.answer()
        await shop_command(update, context)
        return

    # Group Duel Execution Handler Logic
    if data[0] == "gduel":
        await query.answer()
        if data[1] == "no":
            await query.message.edit_text("🏳️ درخواست دوئل توسط حریف رد شد.")
            return
            
        if data[1] == "yes":
            p1_id = int(data[2])
            p2_id = int(data[3])
            rounds = int(data[4])
            wager = int(data[7])
            
            if user_id != p2_id:
                return # Only the challenged user can accept
                
            await query.message.edit_text("⚔️ **نبرد آغاز شد! سیستم در حال پرتاب تاس‌ها...**")
            
            p1_score, p2_score = 0, 0
            for r in range(1, rounds + 1):
                d1 = random.randint(1, 6)
                d2 = random.randint(1, 6)
                p1_score += DICE_SCORES[d1]
                p2_score += DICE_SCORES[d2]
                
            # Compute Final Outcomes
            if p1_score > p2_score:
                update_stats(p1_id, wager if wager > 0 else 30, 'win')
                update_stats(p2_id, -wager if wager > 0 else -20, 'loss')
                winner_text = f"🏆 برنده دوئل: بازیکن شماره یک!"
            elif p2_score > p1_score:
                update_stats(p2_id, wager if wager > 0 else 30, 'win')
                update_stats(p1_id, -wager if wager > 0 else -20, 'loss')
                winner_text = f"🏆 برنده دوئل: بازیکن شماره دو (شما)!"
            else:
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
                winner_text = "🤝 نتیجه نبرد مساوی شد!"
                
            await query.message.reply_markdown(f"🏁 **پایان دوئل گروهی!**\n\nامتیاز بازیکن اول: {p1_score}\nامتیاز بازیکن دوم: {p2_score}\n\n📢 {winner_text}")
        return

    # Offline Duels Intercepts
    if data[0] == "oduel":
        await query.answer()
        token = data[2]
        duel = execute_read_one("SELECT * FROM offline_duels WHERE duel_id = %s", (token,))
        
        if not duel or duel['status'] != 'pending':
            await query.message.edit_text("❌ این دوئل دیگر در دسترس نیست.")
            return
            
        if data[1] == "reject":
            execute_write("UPDATE offline_duels SET status = 'rejected' WHERE duel_id = %s", (token,))
            await query.message.edit_text("🏳️ دوئل غیابی رد شد.")
            return
            
        if data[1] == "accept":
            p1_id = int(duel['creator_id'])
            p2_id = user_id
            wager = int(duel['wager'])
            rounds = int(duel['rounds'])
            
            execute_write("UPDATE offline_duels SET status = 'finished' WHERE duel_id = %s", (token,))
            
            p1_score, p2_score = 0, 0
            for _ in range(rounds):
                p1_score += DICE_SCORES[random.randint(1, 6)]
                p2_score += DICE_SCORES[random.randint(1, 6)]
                
            if p1_score > p2_score:
                update_stats(p1_id, wager if wager > 0 else 40, 'win')
                update_stats(p2_id, -wager if wager > 0 else -30, 'loss')
                res_txt = "⚔️ شما شکست خوردید! حریف پیروز میدان شد."
            elif p2_score > p1_score:
                update_stats(p2_id, wager if wager > 0 else 40, 'win')
                update_stats(p1_id, -wager if wager > 0 else -30, 'loss')
                res_txt = "🏆 تبریک! شما پیروز این دوئل غیابی شدید!"
            else:
                update_stats(p1_id, 0, 'draw')
                update_stats(p2_id, 0, 'draw')
                res_txt = "🤝 نتیجه نبرد غیابی مساوی شد!"
                
            await query.message.edit_text(f"🏁 **نتایج نبرد غیابی:**\n\nامتیاز طراح چالش: {p1_score}\nامتیاز شما: {p2_score}\n\n📢 {res_txt}")
        return

# ==========================================
# TEXT MESSAGES TEXT HANDLERS ROUTER
# ==========================================
async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🎲 پرتاب تاس":
        await dice_command(update, context)
    elif text == "👤 پروفایل من":
        await profile_command(update, context)
    elif text == "🏆 تالار افتخارات":
        await top_command(update, context)
    elif text == "🏪 بازارچه لقب":
        await shop_command(update, context)
    elif text == "ℹ️ راهنمای کلوب":
        await help_command(update, context)

# ==========================================
# ADMIN COMMAND CENTER PANELS
# ==========================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_user_admin(update.effective_user.id): return
    admin_kb = [
        [InlineKeyboardButton("⚡ ایجاد ایونت جدید", callback_data="admin_event_create")],
        [InlineKeyboardButton("🔑 ساخت کد هدیه", callback_data="admin_redeem_create")]
    ]
    await update.message.reply_text("⚙️ **اتاق فرماندهی کلوب نبرد تاس**\nگزینه مورد نظر را جهت پیکربندی سرور انتخاب کنید:", reply_markup=InlineKeyboardMarkup(admin_kb))

# ==========================================
# MAIN INITIALIZATION APPLICATION BUILDER
# ==========================================
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("duel", duel_command))
    app.add_handler(CommandHandler("offline_duel", offline_duel_command))
    app.add_handler(CommandHandler("redeem", redeem_command))
    app.add_handler(CommandHandler("admin", admin_command))
    
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    app.add_handler(CallbackQueryHandler(handle_callbacks))
    
    logger.info("⚡ Bot Core Infrastructure Online and Listening Stream...")
    app.run_polling()

if __name__ == '__main__':
    main()
