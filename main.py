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
    if DATABASE_URL and POSTGRES_AVAILABLE:
        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url, sslmode="allow")
        return conn, True
    else:
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        return conn, False

def execute_write(query, params=()):
    """Executes a write query (INSERT, UPDATE, DELETE) on the active database engine."""
    conn, is_pg = get_db_connection()
    if not is_pg:
        query = query.replace("%s", "?")
    try:
        cursor = conn.cursor()
        cursor.execute(query, params)
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
    """Executes a query and returns a single row as a dictionary format."""
    conn, is_pg = get_db_connection()
    if not is_pg:
        query = query.replace("%s", "?")
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
        cursor.execute(query, params)
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
    """Executes a query and returns all matching rows as a list of dictionaries."""
    conn, is_pg = get_db_connection()
    if not is_pg:
        query = query.replace("%s", "?")
    try:
        if is_pg:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
        else:
            cursor = conn.cursor()
        cursor.execute(query, params)
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
    
    conn.commit()
    conn.close()

# Initialize core configurations and structures
init_db_schema()

# Seed advanced custom store items into the repository database seamlessly
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

# In-memory states trackers
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

def get_or_create_user(telegram_id, username):
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    if user and int(telegram_id) in top_10:
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
            await update.message.reply_markdown(f"💀 **وضعیت سکوت!**\nکاربر @{update.effective_user.username} به دلیل پرتاب متوالی ۱۰ تاس، به مدت **۲ دقیقه** از بازی محروم شد! اتمسفر کلوب را متشنج نکن.")
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
    logger.info(f"Command /help triggered by user {update.effective_user.id}")
    help_text = (
        "⚔️ 🔴 **لیست فرمان‌های نبرد کلوب تاس (آپدیت بزرگ)** 🔴 ⚔️\n\n"
        "🎲 `🎲 پرتاب تاس` — پرتاب تاس انفرادی (دارای شانس حمله بحرانی متوالی)\n"
        "⚔️ `/duel [راند] [مقدار شرط]` — **دوئل شرطی در گروه** (حداکثر تا ۶ راند، شرط تا سقف ۵۰ امتیاز)\n"
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
    logger.info(f"Command /dice triggered by user {update.effective_user.id}")
    if not await check_spam_and_mute(update, "dice"): return
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    
    top_10 = get_top_10_ids()
    display_title = "[GOD OF DICE]" if user_id in top_10 else user_data['title']
    title_tag = f" [{display_title}]" if display_title != 'بدون لقب' else ""
    
    dice_msg = await context.bot.send_dice(chat_id=update.effective_chat.id)
    dice_value = dice_msg.dice.value 
    
    perks_raw = user_data.get('unlocked_perks') if user_data else None
    perks = json.loads(perks_raw) if perks_raw else []
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
            ev_bonus_text = "\n🃏 **[ایونت تاس معکوس فعال است! قوانین جابه‌جا شده‌اند]**"
        elif ev_id == 7: 
            ev_bonus_text = "\n🎰 **[ایونت تاس مخفی! آمار نهایی پایان ایونت محاسبه می‌شود]**"

    is_critical = register_and_check_critical(user_id, dice_value)
    if is_critical:
        score_gained = (dice_value * 3) * 3 if not ev or ev['event_id'] != 1 else ((dice_value * 3) * 3) * 2
        motivation = f"⚡💥 **CRITICAL HIT! حمله بحرانی رخ داد!!!** 💥⚡\nسه پرتاب متوالی روی عدد 〖 **{dice_value}** 〗 نشاندید! قدرت امتیاز شما ۳ برابر ارتقا یافت!"
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
    logger.info(f"Command /duel triggered by user {update.effective_user.id}")
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
    p1_perks_raw = p1_data.get('unlocked_perks') if p1_data else None
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
    logger.info(f"Command /offline_duel triggered by user {update.effective_user.id}")
    user_id = update.effective_user.id
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    perks_raw = user_data.get('unlocked_perks') if user_data else None
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
        f"📌 لینک را برای حریف خود بفرستید تا نبرد به صورت خودکار آغاز شود:\n\n"
        f"`{duel_link}`"
    )
    await update.message.reply_markdown(response)

async def process_offline_duel_link(update: Update, context: ContextTypes.DEFAULT_TYPE, token: str):
    user_id = update.effective_user.id
    user_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    user_data = get_or_create_user(user_id, user_name)
    
    duel = execute_read_one("SELECT * FROM offline_duels WHERE duel_id = %s", (token,))
    if not duel:
        await update.message.reply_text("❌ لینک دوئل غیابی نامعتبر است یا پیدا نشد.")
        return
        
    if duel['status'] != 'pending':
        await update.message.reply_text("❌ این لینک قبلاً استفاده شده و منقضی شده است.")
        return
        
    if int(duel['creator_id']) == user_id:
        await update.message.reply_text("❌ شما نمی‌توانید با لینک خودتان وارد دوئل غیابی شوید!")
        return

    creator = execute_read_one("SELECT username FROM users WHERE telegram_id = %s", (duel['creator_id'],))
    creator_name = creator['username'] if creator else f"مبارز {duel['creator_id']}"
    
    keyboard = [[
        InlineKeyboardButton("⚔️ قبول نبرد و شروع خودکار", callback_data=f"oduel_accept_{token}"),
        InlineKeyboardButton("🏳️ رد نبرد", callback_data=f"oduel_reject_{token}")
    ]]
    
    wager_txt = f"💰 **مبلغ شرط نبرد:** {duel['wager']} XP\n" if duel['wager'] > 0 else ""
    await update.message.reply_markdown(
        f"⚔️ **دعوت‌نامه دوئل غیابی اختصاصی!**\n\n"
        f"👤 **سازنده چالش:** {creator_name}\n"
        f"🏁 **تعداد راند:** {duel['rounds']}\n"
        f"{wager_txt}"
        f"آیا آماده این چالش سرنوشت‌ساز هستی؟",
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
    
    text = "👑 **ویترین و صندوقچه اختصاصی لقب‌های شما**\nلقب مورد نظر خود را انتخاب کنید تا روی کارت عضویت شما فعال شود:"
    if query:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# LEADERS AND PROFILE CONTROLLERS
# ==========================================
async def top_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /top triggered by user {update.effective_user.id}")
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
    
    leaderboard_text += "📢 *رنک‌های بالای ۷۰۰۰ و ۸۰۰۰ کاپ، سر ماه ریست شده و جوایز ویژه می‌گیرند!*"
    keyboard = [[InlineKeyboardButton("⚔️ دوئل با برترین‌ها (مخصوص پیوی)", callback_data="pv_duel_start")]]
    
    if update.message:
        await update.message.reply_markdown(leaderboard_text, reply_markup=InlineKeyboardMarkup(keyboard))
    return leaderboard_text, keyboard

async def profile_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /profile or /rank triggered by user {update.effective_user.id}")
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
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    
    inline_kb = [[InlineKeyboardButton("👑 انتخاب لقب (ویترین)", callback_data="wardrobe_view")]]
    if update.message: 
        await update.message.reply_markdown(profile_text, reply_markup=InlineKeyboardMarkup(inline_kb))
    return profile_text

async def shop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /shop triggered by user {update.effective_user.id}")
    user_id = update.effective_user.id
    user = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
                [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
                [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")]]
    if update.message:
        await update.message.reply_text(f"🏪 **به بازارچه لقب‌ها خوش آمدی!**\n💰 موجودی: {user['score']} XP\n\nانتخاب کنید:", reply_markup=InlineKeyboardMarkup(keyboard))

# ==========================================
# CALLBACKS INTERCEPTOR ENGINE
# ==========================================
async def handle_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        
        end_time = datetime.strptime(ev['end_time'], "%Y-%m-%d %H:%M:%S")
        rem = end_time - datetime.now()
        rem_h = rem.seconds // 3600
        rem_m = (rem.seconds % 3600) // 60
        
        descriptions = {
            1: "امتیاز تمام فعالیت‌های شما شامل پرتاب تاس و بردها ۲ برابر محاسبه میشه! ⚡",
            2: f"شنیده‌ها حاکی از اونه که شانس تاس شماره {json.loads(ev['extra_data']).get('dice')} وحشتناک بالا رفته! 🎲",
            3: "قوانین برعکس شده رفیق! تاس ۱ بیشترین امتیاز رو داره و ۶ برات سقوط آزاد میاره! 🃏",
            7: "امتیاز تاس‌ها کاملاً مخفیه! بعد از پایان زمان ایونت جوایز بر اساس جدول اعطا میشه! 🎰",
            8: "رقابت وحشیانه سر بیشترین تعداد برد دوئل! پادشاه موقت تپه کیه؟ 👑",
            14: "وقت انتقامه! اگه حریفی که قبلاً تو رو برده شکست بدی، امتیازت دبل میشه! 🩸",
            15: f"تخفیف نجومی در بازارچه! قیمت همه تگ‌ها {json.loads(ev['extra_data']).get('discount')}% ریزش کرد! 🛒",
            22: "چالش مأموریتی گلادیاتورها فعال شد! وظایف محوله رو انجام بده تا غنیمت بگیری! 🎯"
        }
        
        r_type = ev['reward_type']
        r_val = ev['reward_value']
        reward_desc = "ندارد ❌"
        if r_type == "score": reward_desc = f"💰 {r_val} امتیاز خالص (XP)"
        elif r_type == "tag": reward_desc = f"🏷️ لقب انحصاری و موقت [ {r_val} ]"
        
        text = (
            f"🕹️ **پنجره اطلاعات ایونت زنده کلوب** 🕹️\n\n"
            f"🔥 **نام رویداد:** {ev['event_name']}\n"
            f"📝 **توضیحات:** {descriptions.get(ev['event_id'], '')}\n\n"
            f"🎁 **پاداش نهایی ایونت:** {reward_desc}\n"
            f"⏳ **زمان باقی‌مانده:** {rem_h} ساعت و {rem_m} دقیقه"
        )
        await query.message.reply_text(text, parse_mode="Markdown")
        return

    if query.data == "wardrobe_view" or query.data == "wardrobe_back_profile":
        if query.data == "wardrobe_back_profile":
            await query.answer()
            user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
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

    if data[0] == "oduel":
        action = data[1]
        token = data[2]
        
        duel = execute_read_one("SELECT * FROM offline_duels WHERE duel_id = %s", (token,))
        if not duel or duel['status'] != 'pending':
            await query.answer("❌ این چالش دیگر معتبر نیست.", show_alert=True)
            return

        if action == "reject":
            execute_write("UPDATE offline_duels SET status = 'rejected' WHERE duel_id = %s", (token,))
            await query.answer()
            await query.edit_message_text("🏳️ درخواست چالش دوئل غیابی رد شد.")
            return

        if action == "accept":
            p1_id = int(duel['creator_id'])
            p2_id = user_id
            wager = int(duel['wager'])
            rounds = int(duel['rounds'])
            
            p1_chk = execute_read_one("SELECT score, username FROM users WHERE telegram_id = %s", (p1_id,))
            p2_chk = execute_read_one("SELECT score, username FROM users WHERE telegram_id = %s", (p2_id,))
            
            if wager > 0:
                if not p1_chk or p1_chk['score'] < wager:
                    await query.answer("❌ موجودی امتیاز سازنده چالش کافی نیست!", show_alert=True)
                    return
                if not p2_chk or p2_chk['score'] < wager:
                    await query.answer("❌ موجودی امتیاز شما کافی نیست!", show_alert=True)
                    return

            execute_write("UPDATE offline_duels SET status = 'accepted' WHERE duel_id = %s", (token,))
            await query.answer()
            await query.edit_message_text("⚔️ **چالش پذیرفته شد! شبیه‌سازی دوئل غیابی آغاز می‌شود...**")
            
            p1_name = p1_chk['username']
            p2_name = p2_chk['username']
            
            p1_total, p2_total = 0, 0
            
            for _ in range(rounds):
                p1_total += random.randint(1, 6)
                p2_total += random.randint(1, 6)
                
            ev = get_current_active_event()
            win_xp, lose_xp = 40, 5
            if ev and ev['event_id'] == 1: 
                win_xp, lose_xp = 80, 10
                
            result_text = f"🏁 **نتیجه نهایی دوئل غیابی اختصاصی:**\n\n👤 {p1_name}: {p1_total} امتیاز تاس\n👤 {p2_name}: {p2_total} امتیاز تاس\n\n"
            
            if p1_total > p2_total:
                total_win = win_xp + wager
                total_lose = lose_xp - wager
                result_text += f"🏆 **برنده چالش:** {p1_name} (+{total_win} XP)\n🏅 بازنده: {p2_name} ({total_lose} XP)"
                update_stats(p1_id, total_win, 'win')
                update_stats(p2_id, total_lose, 'loss')
                log_score_source(p1_id, "offline_duel")
            elif p2_total > p1_total:
                total_win = win_xp + wager
                total_lose = lose_xp - wager
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
            except: pass
            return

    if query.data == "pv_duel_start":
        if query.message.chat.type != "private":
            await query.answer("❌ این قابلیت فقط در پیوی ربات کار می‌کند!", show_alert=True)
            return
        await query.answer()
        PV_DUEL_STATES[user_id] = "WAITING_FOR_TARGET_NUMBER"
        await query.message.reply_text("🎯 **لطفاً شماره بازیکن مورد نظر خود را از لیست بالا وارد کنید (مثلاً عدد 1):**")
        return

    if data[0] == "pvduel":
        action = data[1]; p1_id = int(data[2]); p2_id = int(data[3])
        if user_id != p2_id:
            await query.answer("❌ این درخواست برای شما نیست!", show_alert=True)
            return
        if action == "no":
            await query.answer(); await query.edit_message_text("🏳️ شما درخواست دوئل را رد کردید.")
            try: await context.bot.send_message(chat_id=p1_id, text=f"🏳️ درخواست دوئل شما توسط حریف رد شد.")
            except: pass
            return
        if action == "yes":
            now = datetime.now().timestamp()
            if p1_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1_id]:
                await query.answer("❌ حریف در حال استراحت است.", show_alert=True); return
            await query.answer(); await query.edit_message_text("⚔️ **دوئل آغاز شد! در حال پرتاب تاس‌ها...**")
            
            p1_name = execute_read_one('SELECT username FROM users WHERE telegram_id = %s', (p1_id,))['username']
            p2_name = execute_read_one('SELECT username FROM users WHERE telegram_id = %s', (p2_id,))['username']

            p1_total, p2_total = 0, 0
            
            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p1_id)
                    p1_total += d_msg.dice.value
                    try: await context.bot.send_message(chat_id=p2_id, text=f"🎲 حریفت ({p1_name}) تاس انداخت و عدد 〖 {d_msg.dice.value} 〗 اومد!")
                    except: pass
                except: pass
                await asyncio.sleep(0.5)
            await asyncio.sleep(3.5)
            
            for _ in range(3):
                try:
                    d_msg = await context.bot.send_dice(chat_id=p2_id)
                    p2_total += d_msg.dice.value
                    try: await context.bot.send_message(chat_id=p1_id, text=f"🎲 حریفت ({p2_name}) تاس انداخت و عدد 〖 {d_msg.dice.value} 〗 اومد!")
                    except: pass
                except: pass
                await asyncio.sleep(0.5)
            await asyncio.sleep(3.5)

            ev = get_current_active_event()
            win_xp, lose_xp = 40, 5
            if ev and ev['event_id'] == 1: win_xp, lose_xp = 80, 10

            summary_p1 = f"📊 **نتیجه نهایی دوئل پی‌وی:**\n\nتاس تو: `{p1_total}`\nتاس حریف: `{p2_total}`\n\n"
            summary_p2 = f"📊 **نتیجه نهایی دوئل پی‌وی:**\n\nتاس تو: `{p2_total}`\nتاس حریف: `{p1_total}`\n\n"

            if p1_total > p2_total:
                res_p1 = summary_p1 + f"🏆 پیروز شدید! (+{win_xp} XP)"
                res_p2 = summary_p2 + f"💀 شکست خوردید! (+{lose_xp} XP)"
                update_stats(p1_id, win_xp, 'win'); update_stats(p2_id, lose_xp, 'loss')
            elif p2_total > p1_total:
                res_p1 = summary_p1 + f"💀 شکست خوردید! (+{lose_xp} XP)"
                res_p2 = summary_p2 + f"🏆 پیروز شدید! (+{win_xp} XP)"
                update_stats(p2_id, win_xp, 'win'); update_stats(p1_id, lose_xp, 'loss')
            else:
                res_p1 = summary_p1 + f"🤝 مساوی شد!"
                res_p2 = summary_p2 + f"🤝 مساوی شد!"
                update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')

            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time; DUEL_COOLDOWNS[p2_id] = finish_time
            try: await context.bot.send_message(chat_id=p1_id, text=res_p1)
            except: pass
            try: await context.bot.send_message(chat_id=p2_id, text=res_p2)
            except: pass
            return

    if data[0] == "gduel":
        action = data[1]
        if action == "no":
            await query.answer()
            if user_id != int(data[2]): return
            await query.edit_message_text(f"🏳️ دوئل توسط حریف لغو شد.")
            return
        if action == "yes":
            p1_id, p2_id, rounds = int(data[2]), int(data[3]), int(data[4])
            p1_msg_id, p2_msg_id = int(data[5]), int(data[6])
            wager = int(data[7]) if len(data) > 7 else 0
            
            if user_id != p2_id: 
                await query.answer("❌ این درخواست دوئل برای شما ارسال نشده است!", show_alert=True)
                return
            
            p1_chk = execute_read_one('SELECT score, username FROM users WHERE telegram_id = %s', (p1_id,))
            p2_chk = execute_read_one('SELECT score, username FROM users WHERE telegram_id = %s', (p2_id,))
            
            if wager > 0:
                if not p1_chk or p1_chk['score'] < wager:
                    await query.answer("❌ موجودی شروع‌کننده دوئل کافی نیست!", show_alert=True); return
                if not p2_chk or p2_chk['score'] < wager:
                    await query.answer("❌ موجودی شما برای تایید این شرط کافی نیست!", show_alert=True); return
            
            now = datetime.now().timestamp()
            if p1_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p1_id]:
                await query.answer("❌ محدودیت زمانی کول‌داون فعال است!", show_alert=True); return
            if p2_id in DUEL_COOLDOWNS and now < DUEL_COOLDOWNS[p2_id]:
                await query.answer("❌ محدودیت زمانی کول‌داون فعال است!", show_alert=True); return
                
            await query.answer(); await query.edit_message_text("⚔️ **نبرد گروهی تایید شد! بازی شروع می‌شود...**")
            
            p1_name = p1_chk['username'] if p1_chk else f"Player {p1_id}"
            p2_name = p2_chk['username'] if p2_chk else f"Player {p2_id}"

            p1_total, p2_total = 0, 0
            
            await context.bot.send_message(chat_id=chat_id, text=f"🎲 **در حال انداختن تاس برای بازیکن اول: {p1_name}**")
            await asyncio.sleep(1)
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p1_msg_id)
                p1_total += d.dice.value
                await asyncio.sleep(2.5)
            await context.bot.send_message(chat_id=chat_id, text=f"📊 **مجموع امتیاز تاس‌های {p1_name}: {p1_total}**")
            
            await asyncio.sleep(1.5)

            await context.bot.send_message(chat_id=chat_id, text=f"🎲 **در حال انداختن تاس برای بازیکن دوم: {p2_name}**")
            await asyncio.sleep(1)
            for _ in range(rounds):
                d = await context.bot.send_dice(chat_id=chat_id, reply_to_message_id=p2_msg_id)
                p2_total += d.dice.value
                await asyncio.sleep(2.5)
            await context.bot.send_message(chat_id=chat_id, text=f"📊 **مجموع امتیاز تاس‌های {p2_name}: {p2_total}**")

            ev = get_current_active_event()
            
            win_xp, lose_xp = 40, 5
            if ev and ev['event_id'] == 1: win_xp, lose_xp = 80, 10

            result_text = f"🏁 **نتیجه نهایی دوئل گروهی:**\n\n👤 {p1_name}: {p1_total} امتیاز\n👤 {p2_name}: {p2_total} امتیاز\n\n"

            if p1_total > p2_total:
                total_win = win_xp + wager
                total_lose = lose_xp - wager
                result_text += f"🏆 **برنده: {p1_name} (+{total_win} XP)**\n🏅 بازنده: {p2_name} ({total_lose} XP)"
                update_stats(p1_id, total_win, 'win'); update_stats(p2_id, total_lose, 'loss')
                log_score_source(p1_id, "group_duel")
            elif p2_total > p1_total:
                total_win = win_xp + wager
                total_lose = lose_xp - wager
                result_text += f"🏆 **برنده: {p2_name} (+{total_win} XP)**\n🏅 بازنده: {p1_name} ({total_lose} XP)"
                update_stats(p2_id, total_win, 'win'); update_stats(p1_id, total_lose, 'loss')
                log_score_source(p2_id, "group_duel")
            else:
                result_text += f"🤝 **نتیجه مساوی شد! به هر دو بازیکن امتیازی اضافه نشد.**"
                update_stats(p1_id, 0, 'draw'); update_stats(p2_id, 0, 'draw')
            
            finish_time = datetime.now().timestamp() + 15.0
            DUEL_COOLDOWNS[p1_id] = finish_time; DUEL_COOLDOWNS[p2_id] = finish_time
            await context.bot.send_message(chat_id=chat_id, text=result_text)

# ==========================================
# ADVANCED STORES CALLBACK HANDLERS
# ==========================================
async def shop_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Shop callback query received from user {update.effective_user.id}")
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    
    if data.startswith("shopmain_cat_"):
        cat_type = data.replace("shopmain_cat_", "")
        shop_items = execute_read_all("SELECT id, title_name, cost, item_type FROM shop WHERE category = %s", (cat_type,))
        if not shop_items:
            await query.edit_message_text(f"🔒 محصولی در این بخش موجود نیست.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")]])); return
            
        ev = get_current_active_event()
        discount_pct = 0
        if ev and ev['event_id'] == 15:
            discount_pct = int(json.loads(ev['extra_data']).get('discount', 0))

        keyboard = []
        for item in shop_items:
            final_cost = item['cost']
            if discount_pct > 0:
                final_cost = int(final_cost * (100 - discount_pct) / 100)
            keyboard.append([InlineKeyboardButton(f"{item['title_name']} 💰 {final_cost} XP", callback_data=f"shopbuy_id_{item['id']}")])
        keyboard.append([InlineKeyboardButton("🔙 بازگشت", callback_data="shopmain_back")])
        await query.edit_message_text(f"🛍️ لیست لقب‌ها و آیتم‌های بخش: {CAT_NAMES[cat_type]}", reply_markup=InlineKeyboardMarkup(keyboard))
        
    elif data == "shopmain_back":
        keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data="shopmain_cat_normal")],
                    [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data="shopmain_cat_epic")],
                    [InlineKeyboardButton("👑 لقب لجندری", callback_data="shopmain_cat_legendary")]]
        await query.edit_message_text("🏪 **بازارچه لقب‌ها و آیتم‌ها**", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith("shopbuy_id_"):
        item_id = int(data.split("_")[2])
        item = execute_read_one("SELECT * FROM shop WHERE id = %s", (item_id,))
        if not item: return
        
        ev = get_current_active_event()
        final_cost = item['cost']
        if ev and ev['event_id'] == 15:
            pct = int(json.loads(ev['extra_data']).get('discount', 0))
            final_cost = int(final_cost * (100 - pct) / 100)

        user = get_or_create_user(user_id, query.from_user.username if query.from_user.username else query.from_user.first_name)
        if user['score'] < final_cost:
            await context.bot.send_message(chat_id=query.message.chat_id, text="❌ امتیاز کافی نداری مشتی!"); return
            
        new_score = user['score'] - final_cost
        
        unlocked_titles = json.loads(user['unlocked_titles'] if user['unlocked_titles'] else '[]')
        unlocked_perks = json.loads(user['unlocked_perks'] if user['unlocked_perks'] else '[]')
        
        if item['item_type'] != 'title':
            if item['item_type'] not in unlocked_perks:
                unlocked_perks.append(item['item_type'])
            execute_write('UPDATE users SET score = %s, unlocked_perks = %s WHERE telegram_id = %s', (new_score, json.dumps(unlocked_perks), user_id))
            await query.edit_message_text(f"🎉 قابلیت ویژه « {item['title_name']} » فعال و به حساب شما متصل شد!")
        else:
            if item['title_name'] not in unlocked_titles:
                unlocked_titles.append(item['title_name'])
            execute_write('UPDATE users SET score = %s, title = %s, unlocked_titles = %s WHERE telegram_id = %s', (new_score, item['title_name'], json.dumps(unlocked_titles), user_id))
            await query.edit_message_text(f"🎉 تگ ویژه « {item['title_name']} » فعال و به کمد افتخارات شما اضافه شد!")

# ==========================================
# MESSAGES MONITORING & STATE ROUTING
# ==========================================
async def monitor_messages_and_inputs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if is_user_admin(user_id) and ("تالار مشاهیر" in text or "۱۰ گلادیاتور برتر" in text) and "XP" in text:
        lines = text.split("\n"); current_username = None; updated_count = 0
        for line in lines:
            user_match = re.search(r'(?:\d+\.\s*|👑|⚡|🛡️|🎖️)\s*([A-Za-z0-9_]+)', line)
            if user_match: current_username = user_match.group(1).strip()
            score_match = re.search(r'(?:⭐\s*|\b)(\d+)\s*XP', line)
            if score_match and current_username:
                score_val = int(score_match.group(1)); rank_val = calculate_rank(score_val)
                user_check = execute_read_one("SELECT 1 FROM users WHERE username = %s", (current_username,))
                if user_check:
                    execute_write("UPDATE users SET score = %s, rank = %s WHERE username = %s", (score_val, rank_val, current_username))
                else:
                    fake_id = -random.randint(1000000, 9999999); now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    execute_write("""
                        INSERT INTO users (telegram_id, username, score, rank, created_at, last_seen, unlocked_titles, unlocked_perks) 
                        VALUES (%s, %s, %s, %s, %s, %s, '[]', '[]')
                    """, (fake_id, current_username, score_val, rank_val, now_str, now_str))
                updated_count += 1; current_username = None
        if updated_count > 0:
            await update.message.reply_text(f"✅ آمار {updated_count} کاربر بازیابی و ثبت شد.")
            return

    p_name = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
    get_or_create_user(user_id, p_name)

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

    if user_id in PV_DUEL_STATES and PV_DUEL_STATES[user_id] == "WAITING_FOR_TARGET_NUMBER":
        del PV_DUEL_STATES[user_id]
        try:
            selection = int(text)
            if selection < 1 or selection > 10: raise ValueError
        except ValueError:
            await update.message.reply_text("❌ عدد نامعتبر است!"); return
        top_players = get_top_players()
        if selection > len(top_players):
            await update.message.reply_text("❌ این شماره وجود ندارد!"); return
        target_player = top_players[selection - 1]
        target_id = target_player['telegram_id']; target_name = target_player['username']
        if target_id == user_id:
            await update.message.reply_text("❌ نمی‌توانی به خودت درخواست بدهی!"); return
        keyboard = [[
            InlineKeyboardButton("⚔️ قبول نبرد", callback_data=f"pvduel_yes_{user_id}_{target_id}"),
            InlineKeyboardButton("🏳️ رد درخواست", callback_data=f"pvduel_no_{user_id}_{target_id}")
        ]]
        try:
            await context.bot.send_message(chat_id=target_id, text=f"⚔️ درخواست دوئل پیوی از طرف @{p_name}", reply_markup=InlineKeyboardMarkup(keyboard))
            await update.message.reply_markdown(f"🚀 درخواست برای @{target_name} فرستاده شد.")
        except: await update.message.reply_text("❌ امکان ارسال پیام به حریف مقدور نبود!")
        return

    if user_id in ADMIN_STATES:
        state = ADMIN_STATES[user_id]
        
        if state.startswith("EV_GET_DICE_"):
            ev_id = int(state.split("_")[3])
            try:
                dice_num = int(text)
                if dice_num < 1 or dice_num > 6: raise ValueError
            except ValueError:
                await update.message.reply_text("❌ فقط عدد ۱ تا ۶ وارد کنید!"); return
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_{dice_num}"
            await update.message.reply_text("🕒 حالا مدت زمان این ایونت را به **ساعت** وارد کنید (مثلاً 4):")
            return

        elif state.startswith("EV_GET_DISCOUNT_"):
            ev_id = int(state.split("_")[3])
            try:
                disc = int(text)
            except ValueError:
                await update.message.reply_text("❌ درصد تخفیف معتبر نیست!"); return
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_{disc}"
            await update.message.reply_text("🕒 حالا مدت زمان این ایونت را به **ساعت** وارد کنید (مثلاً 12):")
            return

        elif state.startswith("EV_GET_HOURS_"):
            parts = state.split("_")
            ev_id = int(parts[3])
            param = parts[4] if len(parts) > 4 else "0"
            try:
                hours = float(text)
            except ValueError:
                await update.message.reply_text("❌ مقدار ساعت نامعتبر است!"); return
            
            if ev_id in [7, 8, 22]:
                ADMIN_STATES[user_id] = f"EV_ASK_REWARD_{ev_id}_{hours}_{param}"
                kb = [[InlineKeyboardButton("آره 🎁", callback_data=f"evrew_yes_{ev_id}_{hours}_{param}"),
                       InlineKeyboardButton("نه ❌", callback_data=f"evrew_no_{ev_id}_{hours}_{param}")]]
                await update.message.reply_text("🎁 آیا می‌خواهید برای پایان زمان این ایونت پاداش اتوماتیک بگذارید؟", reply_markup=InlineKeyboardMarkup(kb))
            else:
                await finalize_and_broadcast_event(update, context, ev_id, hours, param, "none", "")
            return

        elif state.startswith("EV_VAL_REWARD_"):
            parts = state.split("_")
            ev_id = int(parts[3])
            hours = float(parts[4])
            param = parts[5]
            rew_type = parts[6]
            await finalize_and_broadcast_event(update, context, ev_id, hours, param, rew_type, text)
            return

        elif state == "WAITING_FOR_BROADCAST":
            del ADMIN_STATES[user_id]
            rows = execute_read_all('SELECT telegram_id FROM users')
            for row in rows:
                try: await context.bot.send_message(chat_id=row['telegram_id'], text=f"📢 **اطلاعیه مدیریت:**\n\n{text}", parse_mode="Markdown")
                except: continue
            await update.message.reply_text("✅ پیام همگانی فرستاده شد.")
        elif state == "WAITING_FOR_CUSTOM_USER":
            ADMIN_STATES[user_id] = f"SET_SCORE_VAL_{text.replace('@', '')}"
            await update.message.reply_text(f"🔢 حالا مقدار امتیازی که می‌خواهی اختصاص دهی را وارد کن:")
        elif state.startswith("SET_SCORE_VAL_"):
            target_username = state.replace("SET_SCORE_VAL_", "")
            del ADMIN_STATES[user_id]
            try: target_score = int(text)
            except ValueError: await update.message.reply_text("❌ خطا!"); return
            new_rank = calculate_rank(target_score)
            changes = execute_write("UPDATE users SET score = %s, rank = %s WHERE username = %s", (target_score, new_rank, target_username))
            await update.message.reply_text(f"🚀 امتیاز کاربر @{target_username} تغییر کرد." if changes > 0 else "❌ کاربر یافت نشد.")
        elif state == "WAITING_FOR_USERNAME_RESET":
            del ADMIN_STATES[user_id]; target = text.replace("@", "")
            changes = execute_write("UPDATE users SET score = 0, rank = '🥉 Bronze I', title = 'بدون لقب' WHERE username = %s", (target,))
            await update.message.reply_text("🧹 حساب کاربر صفر شد." if changes > 0 else "❌ پیدا نشد.")
        elif state == "WAITING_FOR_REDEEM_CODE":
            ADMIN_STATES[user_id] = f"REDEEM_TITLE_{text}"
            await update.message.reply_text("✨ نام تگ یا لقبی که با این ردیم‌کد اهدا می‌شود را ارسال کنید:")
        elif state.startswith("REDEEM_TITLE_"):
            rc_code = state.replace("REDEEM_TITLE_", "")
            ADMIN_STATES[user_id] = f"REDEEM_USES_{rc_code}_{text}"
            await update.message.reply_text("👥 تعداد دفعات مجاز استفاده را وارد کنید:")
        elif state.startswith("REDEEM_USES_"):
            parts = state.split("_"); rc_code = parts[2]; rc_title = parts[3]
            try: rc_uses = int(text)
            except ValueError: return
            ADMIN_STATES[user_id] = f"REDEEM_HOURS_{rc_code}_{rc_title}_{rc_uses}"
            await update.message.reply_text("⏱️ مدت زمان ماندگاری تگ روی پروفایل (ساعت):")
        elif state.startswith("REDEEM_HOURS_"):
            parts = state.split("_"); rc_code = parts[2]; rc_title = parts[3]; rc_uses = int(parts[4])
            del ADMIN_STATES[user_id]
            try: rc_hours = int(text)
            except ValueError: return
            execute_write('INSERT INTO redeem_codes (code, title_name, max_uses, duration_hours) VALUES (%s, %s, %s, %s) ON CONFLICT(code) DO UPDATE SET title_name=EXCLUDED.title_name, max_uses=EXCLUDED.max_uses, duration_hours=EXCLUDED.duration_hours',
                          (rc_code, rc_title, rc_uses, rc_hours))
            await update.message.reply_text(f"✅ ردیم کد `{rc_code}` ساخته شد.")
        elif state == "WAITING_FOR_SHOP_TITLE":
            ADMIN_STATES[user_id] = f"SHOP_CAT_{text}"
            keyboard = [[InlineKeyboardButton("🥈 لقب عادی", callback_data=f"setcat_normal_{text}")],
                        [InlineKeyboardButton("🔮 لقب افسانه‌ای", callback_data=f"setcat_epic_{text}")],
                        [InlineKeyboardButton("👑 لقب لجندری", callback_data=f"setcat_legendary_{text}")]]
            await update.message.reply_text("📂 دسته‌بندی لقب جدید را مشخص کنید:", reply_markup=InlineKeyboardMarkup(keyboard))
        elif state.startswith("SHOP_PRICE_"):
            parts = state.split("_"); new_title = parts[2]; cat_type = parts[3]
            del ADMIN_STATES[user_id]
            try: price = int(text)
            except ValueError: return
            try:
                execute_write("INSERT INTO shop (title_name, cost, category, item_type) VALUES (%s, %s, %s, 'title')", (new_title, price, cat_type))
                await update.message.reply_text(f"✅ لقب « {new_title} » به شاپ اضافه شد.")
            except: 
                await update.message.reply_text("❌ این تگ قبلاً ثبت شده است.")
        return

    clean_code = text.replace("/redeem ", "").replace("/redeem", "").replace("/", "").strip()
    if clean_code:
        cdata = execute_read_one('SELECT 1 FROM redeem_codes WHERE code = %s', (clean_code,))
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
    logger.info(f"Command /redeem triggered by user {update.effective_user.id}")
    user_id = update.effective_user.id
    if context.args:
    code = context.args[0].strip().lower()
   else:
    code = update.message.text.replace("/redeem ", "").replace("/redeem", "").strip().lower()

    if not code:
        await update.message.reply_text("❌ فرمت اشتباه است. مثال: `/redeem ARIA88` یا ارسال مستقیم خود کد کلمه‌ای.")
        return
        
    cdata = execute_read_one('SELECT * FROM redeem_codes WHERE code = %s', (code,))
    if not cdata or cdata['current_uses'] >= cdata['max_uses']:
        await update.message.reply_text("❌ کد معتبر نیست یا منقضی شده."); return
        
    hist = execute_read_one('SELECT 1 FROM redeem_history WHERE telegram_id = %s AND code = %s', (user_id, code))
    if hist: 
        await update.message.reply_text("❌ شما قبلاً این کد را استفاده کرده‌اید."); return
    
    user_data = get_or_create_user(user_id, update.effective_user.username if update.effective_user.username else update.effective_user.first_name)
    unlocked_titles = json.loads(user_data['unlocked_titles'] if user_data['unlocked_titles'] else '[]')
    
    if cdata['title_name'] not in unlocked_titles:
        unlocked_titles.append(cdata['title_name'])
        
    expire_time = (datetime.now() + timedelta(hours=cdata['duration_hours'])).strftime("%Y-%m-%d %H:%M:%S")
    execute_write('INSERT INTO redeem_history (telegram_id, code, used_at) VALUES (%s, %s, %s)', (user_id, code, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    execute_write('UPDATE redeem_codes SET current_uses = current_uses + 1 WHERE code = %s', (code,))
    execute_write('UPDATE users SET title = %s, title_expire = %s, unlocked_titles = %s WHERE telegram_id = %s', (cdata['title_name'], expire_time, json.dumps(unlocked_titles), user_id))
    
    await update.message.reply_text(f"🎉 کد هدیه فعال شد و لقب موقت **{cdata['title_name']}** به ویترین شما اضافه و فعال گردید.")

# ==========================================
# ADMINISTRATIVE HEADQUARTERS ROOM CONTROL
# ==========================================
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Command /admin triggered by user {update.effective_user.id}")
    if not is_user_admin(update.effective_user.id): return
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
    logger.info(f"Admin callback control triggered by user {update.effective_user.id}")
    query = update.callback_query; user_id = query.from_user.id; data = query.data
    await query.answer()
    
    if data.startswith("setcat_"):
        parts = data.split("_"); cat_type = parts[1]; title_name = parts[2]
        ADMIN_STATES[user_id] = f"SHOP_PRICE_{title_name}_{cat_type}"
        await query.edit_message_text(f"💰 قیمت لقب « {title_name} » را وارد کنید:")
        return

    if data == "admin_events_root":
        kb = []
        for ev_id, ev_name in EVENT_NAMES_LIST.items():
            kb.append([InlineKeyboardButton(ev_name, callback_data=f"ev_manage_{ev_id}")])
        kb.append([InlineKeyboardButton("⬅️ بازگشت به پنل ادمین", callback_data="admin_home")])
        await query.edit_message_text("🕹️ **منوی مدیریت فوق پیشرفته ایونت‌ها:**\nایونت مدنظر را جهت پیکربندی انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("ev_manage_"):
        ev_id = int(data.split("_")[2])
        kb = [[InlineKeyboardButton("بله، فعال شود ✅", callback_data=f"ev_trigger_yes_{ev_id}"),
               InlineKeyboardButton("لغو ❌", callback_data="admin_events_root")]]
        await query.edit_message_text(f"⚔️ آیا از فعال‌سازی رویداد **«{EVENT_NAMES_LIST[ev_id]}»** اطمینان دارید؟", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("ev_trigger_yes_"):
        ev_id = int(data.split("_")[3])
        if ev_id == 2:
            ADMIN_STATES[user_id] = f"EV_GET_DICE_{ev_id}"
            await query.edit_message_text("🎯 شانس کدام تاس را می‌خواهی زیاد کنی? (عدد ۱ تا ۶ را به صورت متنی بفرست):")
        elif ev_id == 15:
            ADMIN_STATES[user_id] = f"EV_GET_DISCOUNT_{ev_id}"
            await query.edit_message_text("💰 درصد تخفیف شاپ را به عدد وارد کن (مثلاً 50):")
        else:
            ADMIN_STATES[user_id] = f"EV_GET_HOURS_{ev_id}_0"
            await query.edit_message_text("🕒 مدت زمان ایونت را به **ساعت** وارد کنید (مثلاً 2 یا 24):")
        return

    if data.startswith("evrew_"):
        parts = data.split("_")
        choice = parts[1]
        ev_id = int(parts[2])
        hours = float(parts[3])
        param = parts[4]
        
        if choice == "no":
            await finalize_and_broadcast_event(update, context, ev_id, hours, param, "none", "")
            await query.edit_message_text("✅ ایونت با موفقیت فعال و فرستاده شد.")
        else:
            kb = [[InlineKeyboardButton("امتیاز (XP) 💰", callback_data=f"evtype_score_{ev_id}_{hours}_{param}"),
                   InlineKeyboardButton("تگ اختصاصی (Tag) 🏷️", callback_data=f"evtype_tag_{ev_id}_{hours}_{param}")]]
            await query.edit_message_text("🎁 نوع جایزه پایان رویداد را انتخاب کنید:", reply_markup=InlineKeyboardMarkup(kb))
        return

    if data.startswith("evtype_"):
        parts = data.split("_")
        rew_type = parts[1]
        ev_id = int(parts[2])
        hours = float(parts[3])
        param = parts[4]
        
        ADMIN_STATES[user_id] = f"EV_VAL_REWARD_{ev_id}_{hours}_{param}_{rew_type}"
        if rew_type == "score":
            await query.edit_message_text("🔢 مقدار امتیاز نهایی را بنویسید (مثلاً 500):")
        else:
            await query.edit_message_text("✨ نام تگ انحصاری پایان رویداد را بنویسید (مثلاً: 👑 سلطان دوئل):")
        return

    if data == "admin_reset_all_events":
        execute_write("DELETE FROM active_event")
        execute_write("UPDATE users SET title = 'بدون لقب', title_expire = NULL")
        await query.edit_message_text("🔄 **ریست با موفقیت انجام شد!**\n\nتمام ایونت‌های فعال به پایان رسیدند و تگ/لقب همه کاربران غیرفعال شد. آمار امتیازات، برد و باخت‌ها و رنک گلادیاتورها کاملاً محفوظ مانده است.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
        return

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
    elif data == "admin_users":
        users = execute_read_all('SELECT username, score, rank FROM users ORDER BY score DESC LIMIT 15')
        txt = "📊 **آمار کاربران برتر:**\n\n"
        for idx, u in enumerate(users): txt += f"{idx+1}. 👤 @{u['username']} | ⭐ {u['score']} XP | {u['rank']}\n"
        await query.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_top":
        text, kb = await top_command(update, context)
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_restore_msg":
        restore_text = "🏆 نمونه پیام تالار مشاهیر جهت ریست و آپدیت خودکار دیتابیس بوسیله کپی..."
        await query.edit_message_text(restore_text, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ بازگشت", callback_data="admin_home")]]))
    elif data == "admin_broadcast":
        ADMIN_STATES[user_id] = "WAITING_FOR_BROADCAST"
        await query.edit_message_text("📢 متن پیام همگانی خود را ارسال کنید:")
    elif data == "admin_set_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_CUSTOM_USER"
        await query.edit_message_text("👤 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_reset_score":
        ADMIN_STATES[user_id] = "WAITING_FOR_USERNAME_RESET"
        await query.edit_message_text("🧹 نام کاربری فرد مورد نظر را بدون @ بفرستید:")
    elif data == "admin_add_shop":
        ADMIN_STATES[user_id] = "WAITING_FOR_SHOP_TITLE"
        await query.edit_message_text("✨ نام تگ اختصاصی جدید را بفرستید:")
    elif data == "admin_make_redeem":
        ADMIN_STATES[user_id] = "WAITING_FOR_REDEEM_CODE"
        await query.edit_message_text("🔑 لطفا کد کلمه‌ای ردیم کد مدنظرتان را ارسال کنید:")
    elif data == "admin_check_logs":
        ADMIN_STATES[user_id] = "WAITING_FOR_LOGS_ID"
        await query.edit_message_text("📊 لطفا آیدی عددی کاربر مورد نظر را بفرستید:")
    elif data == "admin_close":
        await query.edit_message_text("🔒 پنل مدیریت بسته شد.")

async def handle_admin_logs_input(update: Update, user_id, text):
    try: target_id = int(text)
    except ValueError: return
    logs = execute_read_all('SELECT game_type, count FROM score_logs WHERE telegram_id = %s', (target_id,))
    if not logs: 
        await update.message.reply_text("📊 لاگی یافت نشد."); return
    report = f"📊 **گزارش آیدی `{target_id}`:**\n\n"
    for row in logs:
        gname = "🎲 تاس انفرادی" if row['game_type'] == "solo_roll" else "⚔️ نبرد دوئل"
        report += f"🔹 تعداد بازی در بخش {gname}: `{row['count']}` بار\n"
    await update.message.reply_text(report, parse_mode="Markdown")

# ==========================================
# ASYNCHRONOUS POLLING CORE LIFECYCLE
# ==========================================
def main():
    if BOT_TOKEN == "YOUR_DEFAULT_TOKEN_IF_NOT_SET": return
    application = Application.builder().token(BOT_TOKEN).build()

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

    application.add_handler(CallbackQueryHandler(handle_callbacks, pattern="^(pv_duel_start|pvduel_|gduel_|oduel_|user_check_event|wardrobe_)"))
    application.add_handler(CallbackQueryHandler(admin_buttons, pattern="^(admin_|setcat_|ev_|evrew_|evtype_)"))
    application.add_handler(CallbackQueryHandler(shop_callback, pattern="^(shopmain_|shopbuy_)"))
    
    async def mid_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.message and update.message.text:
            uid = update.effective_user.id
            txt = update.message.text.strip()
            
            p_username = update.effective_user.username if update.effective_user.username else update.effective_user.first_name
            get_or_create_user(uid, p_username)
            
            if uid in ADMIN_STATES and ADMIN_STATES[uid] == "WAITING_FOR_LOGS_ID":
                del ADMIN_STATES[uid]
                await handle_admin_logs_input(update, uid, txt)
                return
                
        await monitor_messages_and_inputs(update, context)

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mid_filter))

    print("🚀 ربات فوق پیشرفته کلوب تاس همراه با قفل ضداسپم متوالی با موفقیت ران شد...")
    application.run_polling()

if __name__ == "__main__":
    main()
